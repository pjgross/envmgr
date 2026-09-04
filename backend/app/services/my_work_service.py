"""`/my-work` — five "waiting on me" queues, composed under one clock.

TWO RULES GOVERN THIS FILE.

**No restated predicates.** Every queue calls an existing, already-exposed
service seam rather than writing a fresh `select()` that re-implements "which
rows are mine to act on" — that would look correct for months while quietly
drifting from the worklist page it is supposed to mirror:

- `environment_request_service.list_requests(..., actionable_for=(user_id,
  is_admin))`, which wraps `actionable_clause` — "requests my team must
  action," never one I raised myself.
- `contention_service.worklist_query(..., owner_user_id=...)` — every
  escalation naming me, filtered in Python to the undecided ones by reading
  `decided_at`, a raw column already on the row, never a re-derived deadline
  rule.
- `environment_decommission_service.worklist_query(..., member_user_id=...)`
  — narrowed by operations-group membership for EVERYONE, Admins included:
  no bypass. Filtered to the two actionable states via
  `decommission_state`, the same computed-state function the worklist's own
  chip renders from.
- `pir_finding_service.list_actions(..., owner_id=...)` — `is_overdue` on
  each row is the same function `GET /pir-actions` renders from; `overdue`
  is a count over rows this call already fetched, never a second query.
- `incident_service.list_incidents(..., filters={"status": "open"})` — the
  same filter `GET /incidents?status=open` sends. Incidents carry no
  per-user ownership in this codebase, so this queue is tenant-wide, not
  narrowed to `user`.

**One clock.** `now` is passed INTO `build()` and threaded to every queue
unchanged. Nothing here calls `datetime.now()` — two clocks in one response
could disagree across midnight, and `expiry_boundary(now)` would then give two
different answers about what is overdue. `datetime` is imported only for type
annotations; `build`'s own docstring restates the rule so a reviewer does not
have to re-derive it from the absence.
"""
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.decommission_states import STATE_DUE, STATE_EXTENSION_REQUESTED
from app.core.pagination import Sort
from app.core.security import Role
from app.db.models.user import User
from app.schemas.my_work import MyWorkResponse, QueueResult, WorkItem
from app.services import (
    contention_service,
    environment_decommission_service,
    environment_request_service,
    incident_service,
    pir_finding_service,
)

logger = logging.getLogger(__name__)

# Items are capped for a dashboard card; `count` always comes from the full
# set the same query/filter produced, never from `len(items)`.
ITEM_CAP = 5


async def _environment_requests_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """"Requests my team must action" — `list_requests`' own `actionable_for`
    wrapper around `environment_request_service.actionable_clause`. Never a
    request I raised myself; never one no team of mine can act on.
    """
    is_admin = user.role == Role.ADMIN
    views, total = await environment_request_service.list_requests(
        db, tenant_id,
        sort=Sort(column=environment_request_service.REQUEST_SORTS["needed_by"], descending=False),
        actionable_for=(user.id, is_admin),
    )
    items = [
        WorkItem(
            id=view.request.id,
            title=(
                view.environment_name
                or view.request.proposed_name
                or f"{view.request.kind} request"
            ),
            subtitle=f"{view.request.kind} request"
            + (f" from {view.requester_username}" if view.requester_username else ""),
            url=f"/environment-requests/{view.request.id}",
            due=view.request.needed_by,
        )
        for view in views[:ITEM_CAP]
    ]
    return QueueResult(count=total, items=items)


async def _contentions_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Every escalation naming me as owner, minus the ones I have already
    answered. `decided_at IS NOT NULL` is a raw column read, not a re-derived
    version of `contention_service.state_predicate`'s open/expired split — this
    queue does not care which of those two a row is, only whether it is
    still undecided.
    """
    query = contention_service.worklist_query(
        tenant_id, now=now, owner_user_id=user.id,
        sort=Sort(column=contention_service.ESCALATION_SORTS["respond_by"], descending=False),
    )
    rows = list((await db.execute(query)).scalars().all())
    undecided = [row for row in rows if row.decided_at is None]
    views = await contention_service.escalation_views(
        db, undecided[:ITEM_CAP], tenant_id, now
    )
    items = []
    for escalation in undecided[:ITEM_CAP]:
        view = views.get(escalation.id)
        env_a = view.booking_label.environment_name if view else None
        env_b = view.other_booking_label.environment_name if view else None
        title = (
            f"{env_a or 'Unknown'} vs {env_b or 'Unknown'}"
            if (env_a or env_b) else f"Contention #{escalation.id}"
        )
        items.append(
            WorkItem(
                id=escalation.id,
                title=title,
                subtitle=view.state if view else None,
                url="/contentions",
                due=escalation.respond_by,
            )
        )
    return QueueResult(count=len(undecided), items=items)


async def _decommissions_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Narrowed by operations-group membership for EVERYONE, Admins included
    — `member_user_id` is passed unconditionally, with no Admin bypass (an
    Admin in no operations group correctly sees an empty card). Filtered to
    the two states that actually need a human: `due` (teardown day has
    arrived) and `extension_requested` (someone is owed a decision) — using
    `decommission_state`, the same computed function the worklist's own chip
    renders from, never a re-derived version of it.
    """
    query = environment_decommission_service.worklist_query(
        tenant_id, now=now, member_user_id=user.id,
        sort=Sort(
            column=environment_decommission_service.DECOMMISSION_SORTS["scheduled_teardown_at"],
            descending=False,
        ),
    )
    rows = list((await db.execute(query)).scalars().all())
    views = await environment_decommission_service.decommission_views(
        db, rows, tenant_id, now
    )
    actionable = [
        row for row in rows
        if views[row.id].state in (STATE_DUE, STATE_EXTENSION_REQUESTED)
    ]
    items = [
        WorkItem(
            id=row.id,
            title=views[row.id].environment_name or f"Decommission #{row.id}",
            subtitle=views[row.id].state,
            url="/decommissions",
            due=row.scheduled_teardown_at,
        )
        for row in actionable[:ITEM_CAP]
    ]
    return QueueResult(count=len(actionable), items=items)


async def _pir_actions_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """My open PIR actions. `is_overdue` on each row comes from
    `pir_finding_service.list_actions` itself — the same computation
    `GET /pir-actions` renders from — so `overdue` is a count over rows this
    call already fetched, never a second query re-deriving the boundary.
    """
    rows, total = await pir_finding_service.list_actions(
        db, tenant_id, now=now, owner_id=user.id,
        sort=Sort(column=pir_finding_service.PirAction.due_date, descending=False),
    )
    overdue = sum(1 for row in rows if row["is_overdue"])
    items = [
        WorkItem(
            id=row["id"],
            title=row["title"],
            subtitle=row["release_name"],
            url="/pir-actions",
            due=row["due_date"],
        )
        for row in rows[:ITEM_CAP]
    ]
    return QueueResult(count=total, items=items, overdue=overdue)


async def _incidents_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Open incidents, tenant-wide — the same filter `GET
    /incidents?status=open` sends. Incidents carry no per-user ownership
    anywhere in this codebase, so there is no seam to narrow this to `user`
    with; every tenant member's card shows the same open incidents.
    """
    rows, total = await incident_service.list_incidents(
        db, tenant_id, {"status": "open"},
        sort=Sort(column=incident_service.Incident.detected_at, descending=False),
    )
    items = [
        WorkItem(
            id=row.id,
            title=row.title,
            subtitle=f"{row.severity} · {row.status}",
            url=f"/incidents/{row.id}",
            due=None,
        )
        for row in rows[:ITEM_CAP]
    ]
    return QueueResult(count=total, items=items)


async def build(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> MyWorkResponse:
    """`now` is passed IN, never taken here — one clock per request (§5).

    Each queue runs in its own `try/except`: one failing worklist must never
    fail the whole response, and the caller (the frontend card) must be able
    to tell "failed" apart from "nothing waiting on you" — `QueueResult(
    count=0, items=[], failed=True)` is not the same value as an empty,
    successful queue.

    The builders dict is built HERE, inside the function, not at module
    scope — a module-level dict captures each function object once, at
    import time, so patching e.g. `my_work_service._incidents_queue` in a
    test would silently miss it. Built fresh per call, each name is looked up
    from the module's globals at call time, which is what lets a test patch
    exactly one queue's builder and see the patch take effect.
    """
    builders = {
        "environment_requests": _environment_requests_queue,
        "contentions": _contentions_queue,
        "decommissions": _decommissions_queue,
        "pir_actions": _pir_actions_queue,
        "incidents": _incidents_queue,
    }
    queues: dict[str, QueueResult] = {}
    for key, fn in builders.items():
        try:
            queues[key] = await fn(db, tenant_id=tenant_id, user=user, now=now)
        except Exception:
            logger.exception("my_work queue %s failed", key)
            queues[key] = QueueResult(count=0, items=[], failed=True)
    return MyWorkResponse(as_of=now, queues=queues)
