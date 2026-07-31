from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.pagination import Page, fetch_page
from app.db.models.version import EnvironmentSubSystemVersion
from app.db.models.system import SubSystem
from app.db.models.environment import EnvironmentSystem
from app.api.v1.schemas.version import VersionCreate, VersionUpdate
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

    # 3. Verify the subsystem's parent system is linked to this environment
    env_system_result = await db.execute(
        select(EnvironmentSystem).where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.system_id == subsystem.system_id,
            EnvironmentSystem.tenant_id == tenant_id,
        )
    )
    if env_system_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Subsystem's parent system is not linked to this environment. "
                "Add the system to the environment before recording a version."
            ),
        )

    # 4. Build the new version row
    version_kwargs: dict = dict(
        environment_id=env_id,
        subsystem_id=data.subsystem_id,
        build_identifier=data.build_identifier,
        version_label=data.version_label,
        tenant_id=tenant_id,
    )
    if data.installed_at is not None:
        version_kwargs["installed_at"] = data.installed_at

    version = EnvironmentSubSystemVersion(**version_kwargs)

    # 5. Persist
    db.add(version)
    await db.flush()

    # 6. Refresh with subsystem relationship loaded
    await db.refresh(version, attribute_names=["subsystem"])

    return version


async def list_versions(
    db: AsyncSession,
    env_id: int,
    tenant_id: int,
    current_only: bool = False,
    page: Optional[Page] = None,
) -> tuple[list[EnvironmentSubSystemVersion], int]:
    """Version history for an environment.

    With current_only, the latest row per subsystem. That was a Python dedup
    over every row; it is now a ROW_NUMBER() window, so the result can be
    windowed. installed_at is not unique, so id DESC breaks ties inside the
    partition — the previous winner for a tie was whichever row the query
    happened to return first, which was undefined.
    """
    await get_environment(db, env_id, tenant_id)

    base = select(EnvironmentSubSystemVersion).where(
        EnvironmentSubSystemVersion.environment_id == env_id,
        EnvironmentSubSystemVersion.tenant_id == tenant_id,
    )

    if not current_only:
        query = base.options(
            selectinload(EnvironmentSubSystemVersion.subsystem)
        ).order_by(
            EnvironmentSubSystemVersion.subsystem_id,
            EnvironmentSubSystemVersion.installed_at.desc(),
            EnvironmentSubSystemVersion.id,
        )
        return await fetch_page(db, query, page)

    ranked = base.add_columns(
        func.row_number()
        .over(
            partition_by=EnvironmentSubSystemVersion.subsystem_id,
            order_by=(
                EnvironmentSubSystemVersion.installed_at.desc(),
                EnvironmentSubSystemVersion.id.desc(),
            ),
        )
        .label("rn")
    ).subquery()

    entity = aliased(EnvironmentSubSystemVersion, ranked)
    query = (
        select(entity)
        .where(ranked.c.rn == 1)
        .options(selectinload(entity.subsystem))
        .order_by(ranked.c.subsystem_id, ranked.c.id)
    )
    return await fetch_page(db, query, page)


async def update_version(
    db: AsyncSession,
    version_id: int,
    env_id: int,
    tenant_id: int,
    data: VersionUpdate,
) -> EnvironmentSubSystemVersion:
    result = await db.execute(
        select(EnvironmentSubSystemVersion).where(
            EnvironmentSubSystemVersion.id == version_id,
            EnvironmentSubSystemVersion.environment_id == env_id,
            EnvironmentSubSystemVersion.tenant_id == tenant_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    if data.build_identifier is not None:
        version.build_identifier = data.build_identifier
    if data.version_label is not None:
        version.version_label = data.version_label
    if data.installed_at is not None:
        version.installed_at = data.installed_at

    await db.flush()
    await db.refresh(version, attribute_names=["subsystem"])
    return version


async def delete_version(
    db: AsyncSession,
    version_id: int,
    env_id: int,
    tenant_id: int,
) -> None:
    result = await db.execute(
        select(EnvironmentSubSystemVersion).where(
            EnvironmentSubSystemVersion.id == version_id,
            EnvironmentSubSystemVersion.environment_id == env_id,
            EnvironmentSubSystemVersion.tenant_id == tenant_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    await db.delete(version)
    await db.flush()
