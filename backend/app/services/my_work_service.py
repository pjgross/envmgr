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
  no bypass. Filtered to the three states spec §5 names (`warned`, `due`,
  `extension_requested` — `warned` deliberately included so the notice
  period itself shows up here, not just the deadline day) via
  `decommission_state`, the same computed-state function the worklist's own
  chip renders from.
- `pir_finding_service.list_actions(..., owner_id=...)` — `is_overdue` on
  each row is the same function `GET /pir-actions` renders from; `overdue`
  is a count over rows this call already fetched, never a second query.
  Filtered in Python to `status` membership in
  `pir_finding_service.LIVE_ACTION_STATUSES` (`list_actions`' own `status=`
  takes one value, and there are two non-terminal statuses) — the
  codebase's own already-defined non-terminal set, never a re-derived one.
- `incident_service.list_incidents(..., filters={"open": True})` — the
  same filter `GET /incidents?open=true` sends, resolving "non-terminal"
  from the tenant's own incident lifecycle template
  (`lifecycle_service.terminal_status_clause`) rather than a hardcoded
  status — `"open"` was never itself an incident status. Incidents carry no
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

from app.api.v1.schemas.my_work import MyWorkResponse, QueueResult, WorkItem
from app.core.decommission_states import (
    STATE_DUE, STATE_EXTENSION_REQUESTED, STATE_WARNED,
)
from app.core.pagination import Page, Sort, fetch_page
from app.core.security import Role
from app.db.models.contention_escalation import ContentionEscalation
from app.db.models.user import User
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

    WINDOWED (`page=Page(limit=ITEM_CAP, offset=0)`, PR 3's dashboard fix
    wave, finding 5): `list_requests` already takes its `total` from the same
    filtered query regardless of whether a page is supplied (`fetch_page_rows`
    counts against the filters, not against `len(rows)`), so asking for only
    the first `ITEM_CAP` rows changes nothing observable here — every filter
    this queue needs is already in SQL, before the window.
    """
    is_admin = user.role == Role.ADMIN
    views, total = await environment_request_service.list_requests(
        db, tenant_id,
        sort=Sort(column=environment_request_service.REQUEST_SORTS["needed_by"], descending=False),
        actionable_for=(user.id, is_admin),
        page=Page(limit=ITEM_CAP, offset=0),
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
        for view in views
    ]
    return QueueResult(count=total, items=items)


async def _contentions_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Every escalation naming me as owner, minus the ones I have already
    answered. `decided_at IS NULL` is a raw column read, not a re-derived
    version of `contention_service.state_predicate`'s open/expired split — this
    queue does not care which of those two a row is, only whether it is
    still undecided.

    THE `decided_at IS NULL` PREDICATE IS NOW IN SQL (PR 3's dashboard fix
    wave, finding 5), chained onto the `Select` `worklist_query` returns —
    it is a raw column on `ContentionEscalation`, not a value computed from
    the row (unlike `_decommissions_queue`'s state, below), so it is exactly
    as safe to push down as `pir_actions`' status filter. This is what makes
    windowing to `ITEM_CAP` safe instead of loading every escalation ever
    raised against me and filtering in Python.
    """
    query = contention_service.worklist_query(
        tenant_id, now=now, owner_user_id=user.id,
        sort=Sort(column=contention_service.ESCALATION_SORTS["respond_by"], descending=False),
    ).where(ContentionEscalation.decided_at.is_(None))
    rows, total = await fetch_page(db, query, Page(limit=ITEM_CAP, offset=0))
    views = await contention_service.escalation_views(db, rows, tenant_id, now)
    items = []
    for escalation in rows:
        view = views.get(escalation.id)
        env_a = view.booking_label.environment_name if view else None
        env_b = view.other_booking_label.environment_name if view else None
        title = (
            f"{env_a or 'Unknown'} vs {env_b or 'Unknown'}"
            if (env_a or env_b) else "Contention between unresolved bookings"
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
    return QueueResult(count=total, items=items)


async def _decommissions_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Narrowed by operations-group membership for EVERYONE, Admins included
    — `member_user_id` is passed unconditionally, with no Admin bypass (an
    Admin in no operations group correctly sees an empty card). Filtered to
    the three states spec §5 names: `warned`, `due` and
    `extension_requested` — using `decommission_state`, the same computed
    function the worklist's own chip renders from, never a re-derived
    version of it.

    `warned` IS INCLUDED, DELIBERATELY. B5's decommissioning design is
    warn-then-act: the notice period exists precisely so the operating team
    has time to complete attestations before teardown. A "waiting on me"
    card that stayed silent for the whole notice period and only lit up on
    the deadline day (`due`) would surface the work at exactly the moment it
    is too late to act on calmly — the warning would be pointless. Only
    `cancelled` and `torn_down` are excluded: both are terminal, and neither
    needs a human to do anything more.

    DELIBERATELY LEFT UNBOUNDED (PR 3's dashboard fix wave, finding 5): the
    `warned`/`due`/`extension_requested` filter above runs against
    `views[row.id].state`, a value `decommission_views` COMPUTES per row (it
    resolves `decommission_state`, which reads three columns and a clock),
    not a raw column this queue could push into a `WHERE`. Windowing the main
    query BEFORE this filter — the same mistake pir_actions' status filter
    used to make — would return the first `ITEM_CAP` decommissions in ANY
    state, filtered down afterwards, which is not the same set as the first
    `ITEM_CAP` ACTIONABLE ones, and `X-Total-Count` would describe the wrong
    thing. (`environment_decommission_service.state_predicate` DOES express
    one state at a time in SQL, and `worklist_query`'s own `state=` filter
    already uses it — but only for ONE state; this queue needs three ORed
    together, which is a real query restructure, not a one-line window
    change, and is left as a documented follow-on rather than done opportunistically
    inside an unrelated fix wave.)
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
        if views[row.id].state in (STATE_WARNED, STATE_DUE, STATE_EXTENSION_REQUESTED)
    ]
    items = [
        WorkItem(
            id=row.id,
            title=views[row.id].environment_name or "Decommission of an unresolved environment",
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
    """My NOT-YET-CLOSED PIR actions. `is_overdue` on each row comes from
    `pir_finding_service.list_actions` itself — the same computation
    `GET /pir-actions` renders from.

    `status IN (open, in_progress)` (`pir_finding_service.LIVE_ACTION_STATUSES`)
    IS NOW IN SQL, VIA `list_actions`' NEW `statuses=` PARAMETER — PR 3's
    dashboard fix wave, finding 5. This USED to fetch every action I own
    (already narrowed by `owner_id`, but with NO LIMIT) and keep only the
    live ones in Python, which windowing the main query would have made
    silently wrong (a page of the first `ITEM_CAP` actions BY ANY STATUS,
    then filtered down, is not the same set as the first `ITEM_CAP` LIVE
    actions). Pushing the status filter into the query first is what makes
    windowing safe here, unlike `_decommissions_queue` below, whose filter
    genuinely cannot move into SQL the same way.

    `overdue` is a SEPARATE, `limit=1` query with `overdue=True` added — not
    `sum(row["is_overdue"] for row in rows)` over the (now windowed) main
    page, which would undercount the moment there are more than `ITEM_CAP`
    live actions. Both calls share the same `now`, so a row cannot be
    selected as overdue by one query and excluded by the other.
    """
    rows, total = await pir_finding_service.list_actions(
        db, tenant_id, now=now, owner_id=user.id,
        statuses=pir_finding_service.LIVE_ACTION_STATUSES,
        sort=Sort(column=pir_finding_service.PirAction.due_date, descending=False),
        page=Page(limit=ITEM_CAP, offset=0),
    )
    _, overdue_total = await pir_finding_service.list_actions(
        db, tenant_id, now=now, owner_id=user.id,
        statuses=pir_finding_service.LIVE_ACTION_STATUSES, overdue=True,
        page=Page(limit=1, offset=0),
    )
    items = [
        WorkItem(
            id=row["id"],
            title=row["title"],
            subtitle=row["release_name"],
            url="/pir-actions",
            due=row["due_date"],
        )
        for row in rows
    ]
    return QueueResult(count=total, items=items, overdue=overdue_total)


async def _incidents_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Open incidents, tenant-wide — the same filter `GET
    /incidents?open=true` sends. Incidents carry no per-user ownership
    anywhere in this codebase, so there is no seam to narrow this to `user`
    with; every tenant member's card shows the same open incidents.

    `open=true` resolves to "non-terminal" via
    `lifecycle_service.terminal_status_clause`, read off the tenant's own
    incident lifecycle template — never a hardcoded status list. `"open"` was
    never itself a status value (the default template's states are `new`,
    `investigating`, `identified`, `fix_scheduled`, `resolved`, `closed`,
    `cancelled`); `?status=open` always returned zero rows in production.

    WINDOWED (`page=Page(limit=ITEM_CAP, offset=0)`, PR 3's dashboard fix
    wave, finding 5): `list_incidents` takes `total` from `fetch_page`
    against the same filtered query either way, so this is the same "no
    behaviour change" case `_environment_requests_queue` is.
    """
    rows, total = await incident_service.list_incidents(
        db, tenant_id, {"open": True}, page=Page(limit=ITEM_CAP, offset=0),
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
        for row in rows
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

    EACH QUEUE RUNS INSIDE ITS OWN `db.begin_nested()` SAVEPOINT, released on
    success and rolled back on failure (finding 2 of the PR 3 whole-branch
    review). On aiosqlite a failed statement leaves the session usable for
    the next queue; on asyncpg it does not — PostgreSQL aborts the WHOLE
    transaction at the database level, and every subsequent statement on the
    same connection raises `InFailedSQLTransactionError` until a rollback
    happens. Without this, a real database error in the FIRST queue would
    mark all five failed on PostgreSQL, breaking the "returns the queues
    that succeeded" promise exactly when it matters most.

    A SAVEPOINT, NOT A PLAIN `db.rollback()` — this was tried first and
    reverted after it broke a passing test. `Session.rollback()` EXPIRES
    EVERY OBJECT loaded in the session, not just ones touched by the failed
    statement — including `user`, which is loaded once by the caller
    (the route) BEFORE `build()` even starts and read by every queue after
    the first (`user.id`, `user.role`). The next access to an expired
    attribute triggers an implicit lazy-refresh, and `AsyncSession` cannot
    perform that refresh synchronously: it raises `MissingGreenlet`
    ("greenlet_spawn has not been called") the moment the SECOND queue reads
    `user.id`. A SAVEPOINT rollback (`nested.rollback()`) is scoped to work
    done since that savepoint began, so it leaves `user` — loaded well
    before this loop — untouched, exactly as `insert_or_reread`'s savepoint
    leaves the surrounding transaction usable without expiring the objects
    around it.

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
        # See this function's own docstring for why this is a SAVEPOINT
        # (`begin_nested`), not a bare `db.rollback()`.
        nested = await db.begin_nested()
        try:
            queues[key] = await fn(db, tenant_id=tenant_id, user=user, now=now)
        except Exception:
            logger.exception("my_work queue %s failed", key)
            # MUST run before the next queue's first statement, or a real
            # database error (asyncpg) poisons every queue after this one.
            await nested.rollback()
            queues[key] = QueueResult(count=0, items=[], failed=True)
        else:
            await nested.commit()
    return MyWorkResponse(as_of=now, queues=queues)
