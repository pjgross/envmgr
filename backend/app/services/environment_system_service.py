from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.environment import EnvironmentSystem, EnvironmentSystemStatus
from app.db.models.system import System
from app.services.environment_service import get_environment
from app.api.v1.schemas.environment import EnvironmentSystemCreate, EnvironmentSystemUpdate


async def list_systems_in_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> list[EnvironmentSystem]:
    # Verify environment belongs to tenant (raises 404 if not)
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSystem)
        .where(EnvironmentSystem.environment_id == env_id)
        .options(selectinload(EnvironmentSystem.system))
    )
    return list(result.scalars().all())


async def add_system_to_environment(
    db: AsyncSession,
    env_id: int,
    data: EnvironmentSystemCreate,
    tenant_id: int,
) -> EnvironmentSystem:
    # Verify environment belongs to tenant
    await get_environment(db, env_id, tenant_id)

    # Verify system belongs to tenant
    sys_result = await db.execute(
        select(System).where(
            System.id == data.system_id,
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    if sys_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")

    # Check not already assigned
    existing = await db.execute(
        select(EnvironmentSystem).where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.system_id == data.system_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System is already assigned to this environment",
        )

    env_sys = EnvironmentSystem(
        environment_id=env_id,
        system_id=data.system_id,
        tenant_id=tenant_id,
        status=data.status,
        mock_notes=data.mock_notes,
    )
    db.add(env_sys)
    await db.flush()
    # Reload with the system relationship
    await db.refresh(env_sys, ["system"])
    return env_sys


async def _get_env_system(
    db: AsyncSession, env_id: int, system_id: int, tenant_id: int
) -> EnvironmentSystem:
    """Internal helper: get EnvironmentSystem row or raise 404."""
    # Verify the parent environment belongs to this tenant first
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSystem)
        .where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.system_id == system_id,
        )
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys = result.scalar_one_or_none()
    if env_sys is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System not found in this environment",
        )
    return env_sys


async def update_system_in_environment(
    db: AsyncSession,
    env_id: int,
    system_id: int,
    data: EnvironmentSystemUpdate,
    tenant_id: int,
) -> EnvironmentSystem:
    env_sys = await _get_env_system(db, env_id, system_id, tenant_id)

    if data.status is not None:
        env_sys.status = data.status
    if data.mock_notes is not None:
        env_sys.mock_notes = data.mock_notes

    await db.flush()
    await db.refresh(env_sys, ["system"])
    return env_sys


async def remove_system_from_environment(
    db: AsyncSession, env_id: int, system_id: int, tenant_id: int
) -> None:
    env_sys = await _get_env_system(db, env_id, system_id, tenant_id)
    # Hard delete: junction record has no independent business value
    await db.delete(env_sys)
    await db.flush()
