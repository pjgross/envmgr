"""Phase 9 C4 Task 2 — the per-component rollback plan: CRUD plus the batch
read-rendering lookups the wire schema needs.

NOTHING HERE REFUSES A BOOKING OR A RELEASE TRANSITION. The two HTTPException
404s below are input validation on the plan's own two foreign keys (the
release must be in the caller's tenant; the system must be one the release
actually touches) — not a policy verdict. Policy enforcement, if the tenant
has any turned on, is Task 5's `release_readiness_service`, which reads these
rows but never writes them.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.rollback import RollbackPlanCreate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.rollback import ReleaseRollbackPlan, REVERSIBILITY_VALUES
from app.db.models.system import System
from app.db.models.user import User


async def _get_release(db: AsyncSession, release_id: int, tenant_id: int) -> Release:
    """Return the release or 404. Tenant-qualified — a release in another
    tenant must read as not-found, never as a system-mismatch, so this check
    always runs BEFORE the release_system membership check below."""
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


async def _require_release_system(db: AsyncSession, release_id: int, system_id: int) -> None:
    """A plan may only name a system the release actually touches. No
    tenant_id filter needed here — release_id is already tenant-validated by
    the time this runs, and release_system.release_id ties the row to it."""
    exists = (
        await db.execute(
            select(ReleaseSystem.id).where(
                ReleaseSystem.release_id == release_id,
                ReleaseSystem.system_id == system_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This system is not attached to the release"
        )


async def list_plans(
    db: AsyncSession, release_id: int, tenant_id: int
) -> list[ReleaseRollbackPlan]:
    """Every live plan for one release. Validates the release is in the
    caller's tenant first — same 404-not-mismatch ordering as upsert_plan."""
    await _get_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(ReleaseRollbackPlan).where(
                ReleaseRollbackPlan.release_id == release_id,
                ReleaseRollbackPlan.tenant_id == tenant_id,
                ReleaseRollbackPlan.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return list(rows)


async def upsert_plan(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    user_id: int,
    data: RollbackPlanCreate,
) -> ReleaseRollbackPlan:
    """Create or update the one plan for (release_id, data.system_id).

    Validates in order: the release is in the caller's tenant (404), then the
    system is on that release's release_system rows (404). Then it selects an
    existing row for the pair with deleted_at IS NULL and updates it, or
    creates one — the unique constraint on (release_id, system_id) exists as
    a backstop, not as the thing this function relies on to avoid a second
    row.
    """
    await _get_release(db, release_id, tenant_id)
    await _require_release_system(db, release_id, data.system_id)

    existing = (
        await db.execute(
            select(ReleaseRollbackPlan).where(
                ReleaseRollbackPlan.release_id == release_id,
                ReleaseRollbackPlan.system_id == data.system_id,
                ReleaseRollbackPlan.tenant_id == tenant_id,
                ReleaseRollbackPlan.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        plan = ReleaseRollbackPlan(
            tenant_id=tenant_id,
            release_id=release_id,
            system_id=data.system_id,
            steps=data.steps,
            reversibility=data.reversibility,
            estimated_minutes=data.estimated_minutes,
            notes=data.notes,
        )
        db.add(plan)
        await db.flush()
        return plan

    # DO NOT RE-AGREE ON UPDATE. A plan a sponsor agreed to and someone then
    # rewrote is not the plan they agreed to — changing what the plan SAYS
    # (steps or reversibility) clears the agreement rather than leaving a
    # stale sign-off attached to different content. This is exactly the kind
    # of rule a later tidying pass reads as redundant and removes; it is not.
    if existing.steps != data.steps or existing.reversibility != data.reversibility:
        existing.agreed_by_user_id = None
        existing.agreed_at = None

    existing.steps = data.steps
    existing.reversibility = data.reversibility
    existing.estimated_minutes = data.estimated_minutes
    existing.notes = data.notes
    await db.flush()
    return existing


async def agree_plan(
    db: AsyncSession, plan_id: int, tenant_id: int, user_id: int
) -> ReleaseRollbackPlan:
    """Record that `user_id` has agreed to a plan as it currently stands."""
    plan = (
        await db.execute(
            select(ReleaseRollbackPlan).where(
                ReleaseRollbackPlan.id == plan_id,
                ReleaseRollbackPlan.tenant_id == tenant_id,
                ReleaseRollbackPlan.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rollback plan not found")
    plan.agreed_by_user_id = user_id
    plan.agreed_at = datetime.now(timezone.utc)
    await db.flush()
    return plan


async def delete_plan(db: AsyncSession, plan_id: int, tenant_id: int) -> None:
    plan = (
        await db.execute(
            select(ReleaseRollbackPlan).where(
                ReleaseRollbackPlan.id == plan_id,
                ReleaseRollbackPlan.tenant_id == tenant_id,
                ReleaseRollbackPlan.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rollback plan not found")
    plan.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def plans_for_releases(
    db: AsyncSession, tenant_id: int, release_ids: list[int]
) -> dict[int, list[ReleaseRollbackPlan]]:
    """Batch form — ONE query for a set of release ids. release_readiness_service
    (Task 5) calls this once per response, never once per component."""
    if not release_ids:
        return {}
    rows = (
        await db.execute(
            select(ReleaseRollbackPlan).where(
                ReleaseRollbackPlan.release_id.in_(release_ids),
                ReleaseRollbackPlan.tenant_id == tenant_id,
                ReleaseRollbackPlan.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    by_release: dict[int, list[ReleaseRollbackPlan]] = {}
    for row in rows:
        by_release.setdefault(row.release_id, []).append(row)
    return by_release


async def get_system_names(
    db: AsyncSession, system_ids: set[Optional[int]], tenant_id: int
) -> dict[int, str]:
    """Names for a set of system ids, for rendering on plan rows. Deliberately
    does NOT filter deleted_at — following environment_service.get_environment_names
    and A1's read-rendering rule, an archived system must still render its
    name on the plan that references it."""
    ids = {s for s in system_ids if s is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(System.id, System.name).where(
                System.id.in_(ids),
                System.tenant_id == tenant_id,
            )
        )
    ).all()
    return {sid: name for sid, name in rows}


async def usernames_for(db: AsyncSession, user_ids: set[Optional[int]]) -> dict[int, str]:
    """Resolve agreer usernames for the wire.

    DELIBERATELY NOT TENANT-QUALIFIED (no User.tenant_id == tenant_id). Under
    master-admin impersonation the agreer can legitimately sit outside the
    release's own tenant — a tenant-qualified join would render them as
    nobody, losing the one name the agreement's audit trail exists to hold.
    Same rule as gate_waiver_service.usernames_for and
    contention_service.usernames_for; C2's approved_by_username shipped this
    bug the other way round (tenant-qualified where it shouldn't have been).
    """
    ids = {u for u in user_ids if u is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    ).all()
    return {uid: username for uid, username in rows}


def to_read(plan: ReleaseRollbackPlan, system_name: Optional[str], agreed_by_username: Optional[str]):
    """Shape one plan ROW for the wire."""
    from app.api.v1.schemas.rollback import RollbackPlanRead

    return RollbackPlanRead(
        id=plan.id,
        release_id=plan.release_id,
        system_id=plan.system_id,
        system_name=system_name,
        steps=plan.steps,
        reversibility=plan.reversibility,
        estimated_minutes=plan.estimated_minutes,
        notes=plan.notes,
        agreed_by_user_id=plan.agreed_by_user_id,
        agreed_by_username=agreed_by_username,
        agreed_at=plan.agreed_at,
    )


async def reads_for_plans(
    db: AsyncSession, tenant_id: int, plans: list[ReleaseRollbackPlan]
):
    """The wire-shaped form of a list of plans — batched name lookups, never
    one query per row."""
    system_names = await get_system_names(db, {p.system_id for p in plans}, tenant_id)
    usernames = await usernames_for(db, {p.agreed_by_user_id for p in plans})
    return [
        to_read(p, system_names.get(p.system_id), usernames.get(p.agreed_by_user_id))
        for p in plans
    ]


def rollup(plans) -> Optional[str]:
    """The WORST reversibility across a release's plans, or None if there are none.

    Computed, never stored: any component's plan can change at any time, and a
    stored rollup would be falsified by the next edit. Same call C2 made for
    evidence staleness and waiver state.

    Returns None rather than "reversible" for an empty set — an unanswered
    question must not render as a reassuring answer.

    An unrecognised value sorts LAST (worst) rather than first, so a bad row is
    loud rather than silently treated as safe.
    """
    if not plans:
        return None
    order = {value: index for index, value in enumerate(REVERSIBILITY_VALUES)}
    return max(
        (p.reversibility for p in plans),
        key=lambda value: order.get(value, len(REVERSIBILITY_VALUES)),
    )
