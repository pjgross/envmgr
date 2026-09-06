"""Phase 9 C3 — recording a Go/No-Go decision: the composite write path.

NOTHING HERE REFUSES ANYTHING at the decision level: a decision with no
sign-offs, a `go` outcome beside a dissenting `no_go` sign-off, and a
decision with no conditions are all legitimate records of a real meeting.
The only refusals are input validation — a release, perspective or user that
does not exist in the caller's tenant, or a postdated `decided_at`.

VALIDATE EVERYTHING BEFORE CREATING ANYTHING. The PIR citation endpoint's
plan created its rows first and leaned on `get_db`'s rollback to undo a bad
request — which the shared-session `client` fixture used across this test
suite cannot observe at all. Every check below runs before the first `db.add`.

THE SNAPSHOT IS CAPTURED SERVER-SIDE. `record_decision` calls
`release_readiness_service.evaluate` itself; `GoNoGoDecisionCreate` carries no
snapshot fields, so there is no request shape that could substitute a
client-supplied verdict for the real one.
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.go_no_go import (
    GoNoGoConditionRead,
    GoNoGoDecisionCreate,
    GoNoGoDecisionRead,
    GoNoGoPerspectiveCreate,
    GoNoGoPerspectiveUpdate,
    GoNoGoSignoffRead,
)
from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.db.models.go_no_go import (
    GoNoGoCondition,
    GoNoGoDecision,
    GoNoGoPerspective,
    GoNoGoSignoff,
)
from app.db.models.release import Release
from app.db.models.user import User
from app.services import release_readiness_service

# The two rehearsal-related finding types release_readiness_service.evaluate
# can emit (both ReadinessWarning.type and ReadinessBlocker.type literals, in
# app/api/v1/schemas/gate_readiness.py) — a missing or a stale rehearsal.
# `rehearsal_state` on the decision is the TYPE of that finding, not the
# `rollback_rehearsal_service.rehearsal_state` "current"/"stale" value, which
# describes one rehearsal, not the release-wide verdict.
REHEARSAL_FINDING_TYPES = ("rehearsal_missing", "rehearsal_stale")


async def _get_release_or_404(db: AsyncSession, release_id: int, tenant_id: int) -> Release:
    release = (
        await db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if release is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release not found")
    return release


async def _assert_perspectives_exist(
    db: AsyncSession, tenant_id: int, perspective_ids: set[int]
) -> None:
    if not perspective_ids:
        return
    found = set(
        (
            await db.execute(
                select(GoNoGoPerspective.id).where(
                    GoNoGoPerspective.tenant_id == tenant_id,
                    GoNoGoPerspective.id.in_(perspective_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    missing = sorted(perspective_ids - found)
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Perspective not found: {missing[0]}"
        )


async def _assert_users_exist(
    db: AsyncSession, tenant_id: int, user_ids: set[int]
) -> None:
    if not user_ids:
        return
    # Checked against the CALLER'S tenant, same rule contention_service's
    # owner_user_id validation and environment_service's client-FK validation
    # follow — deliberately no `is_active` check, since someone who has since
    # left the tenant still genuinely signed off or was assigned a condition.
    found = set(
        (
            await db.execute(
                select(User.id).where(
                    User.id.in_(user_ids), User.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    missing = sorted(user_ids - found)
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User not found: {missing[0]}")


def _rehearsal_state_from(verdict) -> Optional[str]:
    """The rehearsal-related finding's `type`, from EITHER the verdict's
    warnings or its blockers, or None if there is none.
    release_readiness_service.evaluate's `_add()` routes a rehearsal finding
    to `blockers` instead of `warnings` the moment a tenant sets
    `require_current_rehearsal=True` — scanning only `warnings` would freeze
    this field as None for exactly the tenant that treats a stale or missing
    rehearsal as a blocker, indistinguishable from "no rehearsal concern at
    all" while `snapshot_blockers` on the same row names one. Read from
    `release_readiness_service.evaluate` directly rather than guessed:
    `rehearsal_missing`/`rehearsal_stale` are the only two rehearsal finding
    types it emits, in either list."""
    for finding in (*verdict.warnings, *verdict.blockers):
        if finding.type in REHEARSAL_FINDING_TYPES:
            return finding.type
    return None


async def record_decision(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    user_id: int,
    data: GoNoGoDecisionCreate,
) -> GoNoGoDecision:
    # 1. The release exists in this tenant.
    release = await _get_release_or_404(db, release_id, tenant_id)

    # 2. decided_at is not in the future — backdating is legitimate (the
    # meeting happened before someone got round to recording it); postdating
    # is not, since C3 records a decision that was TAKEN.
    now = datetime.now(timezone.utc)
    decided_at = data.decided_at
    if decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=timezone.utc)
    if decided_at > now:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "decided_at cannot be in the future"
        )

    # 3. Every perspective_id named by a sign-off exists in this tenant.
    perspective_ids = {s.perspective_id for s in data.signoffs}
    await _assert_perspectives_exist(db, tenant_id, perspective_ids)

    # 4. Every user_id — attendees, sign-offs, condition owners — exists in
    # this tenant.
    user_ids = set(data.attendees)
    user_ids.update(s.user_id for s in data.signoffs)
    user_ids.update(c.owner_user_id for c in data.conditions if c.owner_user_id is not None)
    await _assert_users_exist(db, tenant_id, user_ids)

    # 5. No two sign-offs IN THIS POST may name the same (perspective, user)
    # pair. `uq_go_no_go_signoff_unique` enforces this at the database level
    # — but by the time an INSERT trips it, this function has already run
    # several `db.add()` calls inside the same flush, and the caller sees a
    # bare, uncaught `IntegrityError` surface as a 500. Spec §3.3 calls a
    # repeated pair a CONFLICT, not two rows, so it is refused here, before
    # the first `db.add`, the same shape every other check in this function
    # follows. Same class of bug as the C4 rollback-plan revive 500.
    seen_pairs: set[tuple[int, int]] = set()
    for signoff in data.signoffs:
        pair = (signoff.perspective_id, signoff.user_id)
        if pair in seen_pairs:
            names = await perspective_names_for(db, tenant_id, {signoff.perspective_id})
            name = names.get(signoff.perspective_id, str(signoff.perspective_id))
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Duplicate sign-off for perspective '{name}' and user {signoff.user_id}",
            )
        seen_pairs.add(pair)

    # Only now — everything above has raised already if it was going to —
    # capture the snapshot and start creating rows. The snapshot is computed
    # SERVER-SIDE, never taken from the request.
    verdict = await release_readiness_service.evaluate(db, release_id, tenant_id, now=now)

    decision = GoNoGoDecision(
        tenant_id=tenant_id,
        release_id=release.id,
        outcome=data.outcome,
        rationale=data.rationale,
        decided_at=decided_at,
        chaired_by_user_id=user_id,
        attendees=list(data.attendees),
        snapshot_ok=verdict.ok,
        snapshot_blockers=[{"type": b.type, "detail": b.detail} for b in verdict.blockers],
        snapshot_warnings=[{"type": w.type, "detail": w.detail} for w in verdict.warnings],
        snapshot_reversibility=verdict.reversibility,
        snapshot_rehearsal_state=_rehearsal_state_from(verdict),
    )
    db.add(decision)
    await db.flush()  # assigns decision.id for the child rows below

    for signoff in data.signoffs:
        db.add(
            GoNoGoSignoff(
                decision_id=decision.id,
                perspective_id=signoff.perspective_id,
                user_id=signoff.user_id,
                verdict=signoff.verdict,
                dissent_note=signoff.dissent_note,
            )
        )

    for condition in data.conditions:
        db.add(
            GoNoGoCondition(
                decision_id=decision.id,
                text=condition.text,
                owner_user_id=condition.owner_user_id,
                due_date=condition.due_date,
            )
        )

    await db.flush()
    return decision


async def signoffs_for(db: AsyncSession, decision_id: int) -> list[GoNoGoSignoff]:
    rows = (
        await db.execute(
            select(GoNoGoSignoff)
            .where(GoNoGoSignoff.decision_id == decision_id)
            .order_by(GoNoGoSignoff.id)
        )
    ).scalars().all()
    return list(rows)


async def get_decision(
    db: AsyncSession, decision_id: int, tenant_id: int
) -> GoNoGoDecision:
    decision = (
        await db.execute(
            select(GoNoGoDecision).where(
                GoNoGoDecision.id == decision_id,
                GoNoGoDecision.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    return decision


def decisions_query(
    release_id: int, tenant_id: int, *, sort: Optional[Sort] = None
) -> Select:
    """The decision-history query for one release, EXPOSED so a structural
    test (Task 6) can assert the `id` tiebreaker directly — the seam
    `contention_service.worklist_query` and `pir_finding_service.
    worklist_query` exist for. Two decisions can share a `decided_at`
    (backdating is legitimate, and a batch import or two meetings recorded
    against the same clock time both tie), so dropping the tiebreaker would
    page identically on both engines until that happens and then silently
    duplicate or drop a row.

    `sort` is real, not a placeholder: `GO_NO_GO_SORTS` in `api/v1/releases.py`
    whitelists `decided_at` and `outcome` via `sorting()`, and the `GET`
    route's `sort` dependency is threaded through `list_decisions` straight
    into this call. `apply_sort` is a no-op only when the caller passes no
    `sort` at all — the case `latest_decision_for` below relies on. Chained
    BEFORE the `decided_at`/`id` tiebreaker, never instead of it, so a caller
    that does sort still gets a total order rather than one that only
    resolves ties on the sorted field.
    """
    query = select(GoNoGoDecision).where(
        GoNoGoDecision.release_id == release_id,
        GoNoGoDecision.tenant_id == tenant_id,
    )
    return apply_sort(query, sort).order_by(
        GoNoGoDecision.decided_at.desc(), GoNoGoDecision.id.desc()
    )


async def list_decisions(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
) -> tuple[list[GoNoGoDecision], int]:
    """One release's decision history, newest first, plus the unwindowed
    total. Every filter is in SQL, before the window, so `X-Total-Count`
    describes the release's full history rather than the page."""
    query = decisions_query(release_id, tenant_id, sort=sort)
    return await fetch_page(db, query, page)


async def latest_decision_for(
    db: AsyncSession, release_id: int, tenant_id: int
) -> Optional[GoNoGoDecision]:
    """The single most recent decision for a release, by the same
    `(decided_at desc, id desc)` order `decisions_query` uses. Exposed so
    `release_readiness_service.evaluate` can surface it as
    `latest_decision` — REPORTED there, never judged: nothing here feeds
    `blockers`, `warnings` or `ok`. Returns None if no decision has been
    recorded for this release.
    """
    return (
        (await db.execute(decisions_query(release_id, tenant_id).limit(1)))
        .scalars()
        .first()
    )


async def conditions_for(db: AsyncSession, decision_id: int) -> list[GoNoGoCondition]:
    rows = (
        await db.execute(
            select(GoNoGoCondition)
            .where(GoNoGoCondition.decision_id == decision_id)
            .order_by(GoNoGoCondition.id)
        )
    ).scalars().all()
    return list(rows)


async def close_condition(
    db: AsyncSession, condition_id: int, tenant_id: int, user_id: int, met: bool
) -> GoNoGoCondition:
    """The ONE mutation this append-only record allows. Closing (or
    reopening — `met=False` clears the fields again, for a condition marked
    met in error) a condition records a later FACT ABOUT the decision; it
    must never touch `outcome`, `rationale` or the frozen snapshot, none of
    which this function reads or writes.

    `GoNoGoCondition` carries no `tenant_id` of its own — tenant scoping goes
    through its parent decision via the join below.
    """
    condition = (
        await db.execute(
            select(GoNoGoCondition)
            .join(GoNoGoDecision, GoNoGoDecision.id == GoNoGoCondition.decision_id)
            .where(
                GoNoGoCondition.id == condition_id,
                GoNoGoDecision.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if condition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")
    if met:
        condition.met_at = datetime.now(timezone.utc)
        condition.met_by_user_id = user_id
    else:
        condition.met_at = None
        condition.met_by_user_id = None
    await db.flush()
    return condition


async def usernames_for(db: AsyncSession, user_ids) -> dict[int, str]:
    """Batched id -> username. Deliberately NOT tenant-qualified — the rule
    A3's `acknowledged_by_username`, A4's `usernames_for`, B5's and C2's all
    follow. Under master-admin impersonation a chair or signatory can
    legitimately sit outside the decision's own tenant, and a
    `User.tenant_id ==` join would render them as nobody — losing the one
    name a governance record exists to hold.
    """
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    ).all()
    return {uid: username for uid, username in rows}


async def perspective_names_for(
    db: AsyncSession, tenant_id: int, perspective_ids
) -> dict[int, str]:
    """Batched id -> name, TENANT-SCOPED — unlike `usernames_for` above. A
    perspective is a tenant-owned configuration row, not a cross-tenant user
    identity, so there is no impersonation case that needs an unscoped join;
    scoping it also means a perspective id from a different tenant (which
    should never reach here, since `_assert_perspectives_exist` already
    checked every id against this same tenant at record time) resolves to
    nothing rather than leaking another tenant's vocabulary.

    DECISION RECORDED HERE, per the whole-branch review: a sign-off stores
    `perspective_id`, not the name at signing time, so this always resolves
    the perspective's CURRENT name — a rename (`update_perspective`) changes
    what every past decision's sign-off table displays, including one
    recorded years earlier. This is deliberate, not a staleness bug: the
    perspective is the same configured concept, renamed, and the sign-off
    means "this person attested to that concept", not "this person saw the
    literal string 'Quality' on the day they signed". A perspective is never
    deleted (see `GoNoGoPerspective`'s docstring), only retired via
    `is_active=False`, so a resolved name never goes missing outright, and
    this lookup deliberately does not filter on `is_active` — a retired
    perspective's past sign-offs must keep resolving its name exactly like
    an active one's.
    """
    ids = {i for i in perspective_ids if i is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(GoNoGoPerspective.id, GoNoGoPerspective.name).where(
                GoNoGoPerspective.tenant_id == tenant_id,
                GoNoGoPerspective.id.in_(ids),
            )
        )
    ).all()
    return {pid: name for pid, name in rows}


async def _signoffs_for_decisions(
    db: AsyncSession, decision_ids: set[int]
) -> dict[int, list[GoNoGoSignoff]]:
    """One query for every sign-off on the given decisions, grouped by
    `decision_id` — the batched sibling of `signoffs_for`, which stays as
    the single-decision reader `record_decision`'s own tests exercise."""
    if not decision_ids:
        return {}
    rows = (
        await db.execute(
            select(GoNoGoSignoff)
            .where(GoNoGoSignoff.decision_id.in_(decision_ids))
            .order_by(GoNoGoSignoff.decision_id, GoNoGoSignoff.id)
        )
    ).scalars().all()
    by_decision: dict[int, list[GoNoGoSignoff]] = defaultdict(list)
    for row in rows:
        by_decision[row.decision_id].append(row)
    return by_decision


async def _conditions_for_decisions(
    db: AsyncSession, decision_ids: set[int]
) -> dict[int, list[GoNoGoCondition]]:
    """As `_signoffs_for_decisions`, for conditions."""
    if not decision_ids:
        return {}
    rows = (
        await db.execute(
            select(GoNoGoCondition)
            .where(GoNoGoCondition.decision_id.in_(decision_ids))
            .order_by(GoNoGoCondition.decision_id, GoNoGoCondition.id)
        )
    ).scalars().all()
    by_decision: dict[int, list[GoNoGoCondition]] = defaultdict(list)
    for row in rows:
        by_decision[row.decision_id].append(row)
    return by_decision


async def reads_for_decisions(
    db: AsyncSession, tenant_id: int, decisions: list[GoNoGoDecision]
) -> list[GoNoGoDecisionRead]:
    """The wire-shaped form of a page of decisions — batched across the
    WHOLE page, mirroring `rollback_plan_service.reads_for_plans`'s shape:
    one query for every decision's sign-offs, one for every decision's
    conditions, one `usernames_for` call over the union of every user id on
    the page (chairs, attendees, signatories, condition owners, condition
    closers), and one `perspective_names_for` call over the union of every
    sign-off's perspective id. Both name lookups are called exactly ONCE PER
    RESPONSE here, never once per row — the PIR programme's
    `gap_warnings_for_bookings` note, and the shape this function replaces:
    the route layer originally called a single-decision builder once per
    row, at up to three unbatched queries each (up to 1500 for a full
    500-row page).

    BOTH `POST` (a one-element list) and `GET`'s page call this — never a
    second, divergent construction site — so `unmet_condition_count` and
    every resolved name are built from exactly one code path and cannot
    drift between the two routes.
    """
    decision_ids = {d.id for d in decisions}
    signoffs_by_decision = await _signoffs_for_decisions(db, decision_ids)
    conditions_by_decision = await _conditions_for_decisions(db, decision_ids)

    user_ids: set[int] = {d.chaired_by_user_id for d in decisions}
    for d in decisions:
        user_ids.update(d.attendees)
    for signoffs in signoffs_by_decision.values():
        user_ids.update(s.user_id for s in signoffs)
    for conditions in conditions_by_decision.values():
        user_ids.update(c.owner_user_id for c in conditions if c.owner_user_id is not None)
        user_ids.update(c.met_by_user_id for c in conditions if c.met_by_user_id is not None)
    names = await usernames_for(db, user_ids)

    perspective_ids: set[int] = set()
    for signoffs in signoffs_by_decision.values():
        perspective_ids.update(s.perspective_id for s in signoffs)
    perspective_names = await perspective_names_for(db, tenant_id, perspective_ids)

    reads = []
    for decision in decisions:
        signoffs = signoffs_by_decision.get(decision.id, [])
        conditions = conditions_by_decision.get(decision.id, [])

        read = GoNoGoDecisionRead.model_validate(decision)
        read.chaired_by_username = names.get(decision.chaired_by_user_id)
        read.attendee_usernames = [
            names.get(uid, f"User #{uid}") for uid in decision.attendees
        ]
        read.signoffs = [
            GoNoGoSignoffRead.model_validate(s).model_copy(
                update={
                    "username": names.get(s.user_id),
                    "perspective_name": perspective_names.get(s.perspective_id),
                }
            )
            for s in signoffs
        ]
        read.conditions = [
            GoNoGoConditionRead.model_validate(c).model_copy(
                update={
                    "owner_username": names.get(c.owner_user_id)
                    if c.owner_user_id is not None
                    else None,
                    "met_by_username": names.get(c.met_by_user_id)
                    if c.met_by_user_id is not None
                    else None,
                }
            )
            for c in conditions
        ]
        read.unmet_condition_count = sum(1 for c in conditions if c.met_at is None)
        reads.append(read)
    return reads


async def get_condition(
    db: AsyncSession, condition_id: int, tenant_id: int
) -> GoNoGoCondition:
    """Tenant-scoped load, via the parent decision's `tenant_id` — the same
    join `close_condition` uses, since `GoNoGoCondition` carries no
    `tenant_id` of its own. Exposed so the route layer can load-then-check
    (`assert_may_close_condition`) before mutating, the shape
    `contention_service.get_escalation_by_id` + `assert_may_decide`
    established: a cross-tenant id 404s before the owner-or-admin question
    is ever asked, rather than a 403 that would confirm the record exists.
    """
    condition = (
        await db.execute(
            select(GoNoGoCondition)
            .join(GoNoGoDecision, GoNoGoDecision.id == GoNoGoCondition.decision_id)
            .where(
                GoNoGoCondition.id == condition_id,
                GoNoGoDecision.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if condition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")
    return condition


def assert_may_close_condition(condition: GoNoGoCondition, current_user: User) -> None:
    """The condition's OWNER, or Admin/Release Manager — §5's table.

    Mirrors `contention_service.assert_may_decide`'s owner-or-admin shape,
    widened to a second role because that is what the spec names here (a
    contention has no equivalent "Release Manager may always decide" rule).
    A condition with no owner (`owner_user_id is None`) can only ever be
    closed by Admin/RM — there is no "owner" branch to fall into.
    """
    if condition.owner_user_id is not None and current_user.id == condition.owner_user_id:
        return
    if current_user.is_master_admin or current_user.role in ("Admin", "Release Manager"):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only the condition's owner, or an Admin/Release Manager, may close this condition",
    )


# ── Perspectives (tenant-configurable vocabulary) ───────────────────────────
#
# Reads are open to any tenant member; writes are Admin-only — the route
# layer enforces that via `require_tenant_admin()`, not this module. No
# delete: retirement is `is_active=False` through the update path, the same
# reason `GoNoGoPerspective` carries no `deleted_at` column at all.

async def _assert_perspective_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(GoNoGoPerspective.id).where(
        GoNoGoPerspective.tenant_id == tenant_id,
        func.lower(GoNoGoPerspective.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.where(GoNoGoPerspective.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A perspective named {name} already exists"
        )


async def list_perspectives(
    db: AsyncSession, tenant_id: int, *, include_inactive: bool = True
) -> list[GoNoGoPerspective]:
    query = select(GoNoGoPerspective).where(GoNoGoPerspective.tenant_id == tenant_id)
    if not include_inactive:
        query = query.where(GoNoGoPerspective.is_active.is_(True))
    query = query.order_by(GoNoGoPerspective.sort_order, GoNoGoPerspective.id)
    return list((await db.execute(query)).scalars().all())


async def get_perspective(
    db: AsyncSession, perspective_id: int, tenant_id: int
) -> GoNoGoPerspective:
    row = (
        await db.execute(
            select(GoNoGoPerspective).where(
                GoNoGoPerspective.id == perspective_id,
                GoNoGoPerspective.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Perspective not found")
    return row


async def create_perspective(
    db: AsyncSession, tenant_id: int, data: GoNoGoPerspectiveCreate
) -> GoNoGoPerspective:
    await _assert_perspective_name_free(db, tenant_id, data.name)
    row = GoNoGoPerspective(tenant_id=tenant_id, **data.model_dump())
    db.add(row)
    await db.flush()
    return row


async def update_perspective(
    db: AsyncSession, perspective_id: int, tenant_id: int, data: GoNoGoPerspectiveUpdate
) -> GoNoGoPerspective:
    row = await get_perspective(db, perspective_id, tenant_id)
    fields = data.model_dump(exclude_unset=True)  # omitted key means "leave alone"
    if "name" in fields:
        await _assert_perspective_name_free(
            db, tenant_id, fields["name"], exclude_id=perspective_id
        )
    for key, value in fields.items():
        setattr(row, key, value)
    await db.flush()
    return row
