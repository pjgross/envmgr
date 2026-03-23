from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.version import EnvironmentSubSystemVersion
from app.db.models.system import SubSystem
from app.api.v1.schemas.version import VersionCreate
from app.services.environment_service import get_environment


async def record_version(
    db: AsyncSession,
    env_id: int,
    data: VersionCreate,
    tenant_id: int,
) -> EnvironmentSubSystemVersion:
    """
    Always INSERT a new row (never update) — append-only audit trail.
    """
    # 1. Verify environment belongs to tenant
    await get_environment(db, env_id, tenant_id)

    # 2. Verify subsystem belongs to tenant
    sub_result = await db.execute(
        select(SubSystem).where(
            SubSystem.id == data.subsystem_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    subsystem = sub_result.scalar_one_or_none()
    if subsystem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subsystem not found",
        )

    # 3. Create EnvironmentSubSystemVersion row
    version_kwargs: dict = dict(
        environment_id=env_id,
        subsystem_id=data.subsystem_id,
        build_id=data.build_id,
        version_label=data.version_label,
        tenant_id=tenant_id,
    )
    if data.installed_at is not None:
        version_kwargs["installed_at"] = data.installed_at

    version = EnvironmentSubSystemVersion(**version_kwargs)

    # 4. Persist
    db.add(version)
    await db.flush()

    # 5. Refresh with subsystem relationship loaded
    await db.refresh(version, attribute_names=["subsystem"])

    return version


async def list_versions(
    db: AsyncSession,
    env_id: int,
    tenant_id: int,
    current_only: bool = False,
) -> list[EnvironmentSubSystemVersion]:
    """
    List version history for an environment.
    If current_only=True, return only the latest row per subsystem.
    """
    # Verify environment belongs to tenant
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSubSystemVersion)
        .where(
            EnvironmentSubSystemVersion.environment_id == env_id,
            EnvironmentSubSystemVersion.tenant_id == tenant_id,
        )
        .options(selectinload(EnvironmentSubSystemVersion.subsystem))
        .order_by(
            EnvironmentSubSystemVersion.subsystem_id,
            EnvironmentSubSystemVersion.installed_at.desc(),
        )
    )
    all_versions = list(result.scalars().all())

    if not current_only:
        return all_versions

    # Keep only the latest per subsystem_id (already ordered DESC by installed_at)
    seen: dict[int, EnvironmentSubSystemVersion] = {}
    for v in all_versions:
        if v.subsystem_id not in seen:
            seen[v.subsystem_id] = v
    return sorted(seen.values(), key=lambda v: v.subsystem_id)
