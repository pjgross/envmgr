"""Phase 9 C4 Task 6 — rollback authorisation: the record of a rollback

decision that actually happened, raisable BEFORE OR AFTER the fact.

C4 MUST NEVER STAND BETWEEN A TEAM AND A 2AM RECOVERY. This record is an
audit trail and a PIR input, not permission: `record_authorisation` validates
ids ONLY — the release must be in the caller's tenant (404), and every id in
`system_ids` must appear on that release's release_system rows (404, naming
the offender). It does NOT inspect plan state, rehearsal state or the
readiness verdict — a rollback with no plan at all is exactly the case worth
recording, and it does not gate the deployment status machine: nothing here
can prevent a Deployment reaching `rolled_back`.
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.rollback import RollbackAuthorisationCreate, RollbackAuthorisationRead
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.rollback import ReleaseRollbackAuthorisation
from app.db.models.system import System
from app.db.models.user import User


async def _get_release(db: AsyncSession, release_id: int, tenant_id: int) -> Release:
    """Return the release or 404. Tenant-qualified — a release in another
    tenant must read as not-found, never as a system-mismatch, so this check
    always runs BEFORE the release_system membership check below. Same
    ordering as rollback_plan_service._get_release."""
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


async def _require_release_systems(
    db: AsyncSession, release_id: int, system_ids: list[int]
) -> None:
    """Every id in system_ids must appear on this release's release_system
    rows — 404 naming the first offender. No tenant_id filter needed here —
    release_id is already tenant-validated by the time this runs, and
    release_system.release_id ties every row to that release."""
    rows = (
        await db.execute(
            select(ReleaseSystem.system_id).where(
                ReleaseSystem.release_id == release_id,
                ReleaseSystem.system_id.in_(system_ids),
            )
        )
    ).scalars().all()
    attached = set(rows)
    for system_id in system_ids:
        if system_id not in attached:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"System {system_id} is not attached to this release",
            )


async def record_authorisation(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    user_id: int,
    data: RollbackAuthorisationCreate,
) -> ReleaseRollbackAuthorisation:
    """Record one rollback authorisation. Validates ids ONLY — see the module
    docstring. `decided_at` is written exactly as supplied; it may be in the
    past."""
    await _get_release(db, release_id, tenant_id)
    await _require_release_systems(db, release_id, data.system_ids)

    auth = ReleaseRollbackAuthorisation(
        tenant_id=tenant_id,
        release_id=release_id,
        decided_by_user_id=user_id,
        decided_at=data.decided_at,
        trigger=data.trigger,
        rationale=data.rationale,
        system_ids=list(data.system_ids),
    )
    db.add(auth)
    await db.flush()
    return auth


async def list_authorisations(
    db: AsyncSession, release_id: int, tenant_id: int
) -> list[ReleaseRollbackAuthorisation]:
    """Every live authorisation for one release, newest decision first.
    Validates the release is in the caller's tenant first — same
    404-not-mismatch ordering as record_authorisation."""
    await _get_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(ReleaseRollbackAuthorisation)
            .where(
                ReleaseRollbackAuthorisation.release_id == release_id,
                ReleaseRollbackAuthorisation.tenant_id == tenant_id,
                ReleaseRollbackAuthorisation.deleted_at.is_(None),
            )
            .order_by(
                ReleaseRollbackAuthorisation.decided_at.desc(),
                ReleaseRollbackAuthorisation.id.desc(),
            )
        )
    ).scalars().all()
    return list(rows)


async def get_system_names(
    db: AsyncSession, system_ids: set[Optional[int]], tenant_id: int
) -> dict[int, str]:
    """Names for a set of system ids, for rendering on authorisation rows.
    Deliberately does NOT filter deleted_at — following
    rollback_plan_service.get_system_names and A1's read-rendering rule, an
    archived system must still render its name on the rollback it was part
    of."""
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
    """Resolve decider usernames for the wire.

    DELIBERATELY NOT TENANT-QUALIFIED (no User.tenant_id == tenant_id). Under
    master-admin impersonation the decider can legitimately sit outside the
    release's own tenant — a tenant-qualified join would render them as
    nobody, losing the one name this audit trail exists to hold. Same rule as
    rollback_plan_service.usernames_for, rollback_rehearsal_service.
    usernames_for, gate_waiver_service.usernames_for and contention_service.
    usernames_for; C2's approved_by_username shipped this bug the other way
    round (tenant-qualified where it shouldn't have been).
    """
    ids = {u for u in user_ids if u is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    ).all()
    return {uid: username for uid, username in rows}


def to_read(
    auth: ReleaseRollbackAuthorisation,
    system_names: dict[int, str],
    decided_by_username: Optional[str],
) -> RollbackAuthorisationRead:
    """Shape one authorisation ROW for the wire."""
    return RollbackAuthorisationRead(
        id=auth.id,
        release_id=auth.release_id,
        decided_by_user_id=auth.decided_by_user_id,
        decided_by_username=decided_by_username,
        decided_at=auth.decided_at,
        trigger=auth.trigger,
        rationale=auth.rationale,
        system_ids=list(auth.system_ids),
        system_names=[
            system_names[sid] for sid in auth.system_ids if sid in system_names
        ],
    )


async def reads_for_authorisations(
    db: AsyncSession, tenant_id: int, authorisations: list[ReleaseRollbackAuthorisation]
) -> list[RollbackAuthorisationRead]:
    """The wire-shaped form of a list of authorisations — batched name
    lookups, never one query per row."""
    all_system_ids: set[Optional[int]] = set()
    for auth in authorisations:
        all_system_ids.update(auth.system_ids)
    system_names = await get_system_names(db, all_system_ids, tenant_id)
    usernames = await usernames_for(db, {a.decided_by_user_id for a in authorisations})
    return [
        to_read(a, system_names, usernames.get(a.decided_by_user_id))
        for a in authorisations
    ]
