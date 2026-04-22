"""Read-only rollup queries for an enterprise release.

All queries join on accepted memberships only.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.enterprise_rollup import SystemRollupRow
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.db.models.user import User


async def _accepted_child_ids(
    db: AsyncSession, tenant_id: int, enterprise_id: int
) -> list[int]:
    stmt = select(ReleaseMembership.project_release_id).where(
        ReleaseMembership.enterprise_release_id == enterprise_id,
        ReleaseMembership.tenant_id == tenant_id,
        ReleaseMembership.state == MembershipState.ACCEPTED.value,
    )
    return [r for (r,) in (await db.execute(stmt)).all()]


async def systems_rollup(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> list[SystemRollupRow]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return []

    stmt = (
        select(ReleaseSystem, System, Release)
        .join(System, ReleaseSystem.system_id == System.id)
        .join(Release, ReleaseSystem.release_id == Release.id)
        .where(
            ReleaseSystem.release_id.in_(child_ids),
            ReleaseSystem.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    by_system: dict[int, dict] = {}
    for rs, sys, rel in (await db.execute(stmt)).all():
        entry = by_system.setdefault(
            sys.id,
            {"system_id": sys.id, "system_name": sys.name, "roles_by_project": {}},
        )
        entry["roles_by_project"].setdefault(rel.name, []).append(rs.role)
    return [SystemRollupRow(**v) for v in by_system.values()]
