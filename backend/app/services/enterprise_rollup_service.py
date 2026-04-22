"""Read-only rollup queries for an enterprise release.

All queries join on accepted memberships only.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.enterprise_rollup import ScopeRollupItem, SystemRollupRow
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
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


async def scope_rollup(
    db: AsyncSession,
    *,
    user: User,
    enterprise_id: int,
    change_kind: Optional[str] = None,
    status: Optional[str] = None,
    project_release_id: Optional[int] = None,
    system_id: Optional[int] = None,
    search: Optional[str] = None,
) -> list[ScopeRollupItem]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return []
    if project_release_id is not None:
        if project_release_id not in child_ids:
            return []
        child_ids = [project_release_id]

    stmt = (
        select(ReleaseChange, Release, System)
        .join(Release, ReleaseChange.release_id == Release.id)
        .outerjoin(System, ReleaseChange.system_id == System.id)
        .where(
            ReleaseChange.release_id.in_(child_ids),
            ReleaseChange.tenant_id == tenant_id,
            ReleaseChange.deleted_at.is_(None),
        )
    )
    if change_kind:
        stmt = stmt.where(ReleaseChange.change_kind == change_kind)
    if status:
        stmt = stmt.where(ReleaseChange.external_status == status)
    if system_id:
        stmt = stmt.where(ReleaseChange.system_id == system_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (ReleaseChange.title.ilike(like)) | (ReleaseChange.external_key.ilike(like))
        )

    items: list[ScopeRollupItem] = []
    for rc, rel, sys in (await db.execute(stmt)).all():
        items.append(ScopeRollupItem(
            release_change_id=rc.id,
            project_release_id=rel.id,
            project_release_name=rel.name,
            external_key=rc.external_key,
            title=rc.title,
            change_kind=rc.change_kind,
            external_status=rc.external_status,
            system_id=rc.system_id,
            system_name=sys.name if sys else None,
        ))
    return items
