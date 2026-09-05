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
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.go_no_go import GoNoGoDecisionCreate
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

    `sort` is accepted for the same reason `pir_finding_service.
    worklist_query` takes it — a future sortable column costs no interface
    change — though nothing yet whitelists one via `sorting()`; `apply_sort`
    is a no-op when `sort` is None. Chained BEFORE the `decided_at`/`id`
    tiebreaker, never instead of it.
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
