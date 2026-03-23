from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.environment import Environment, EnvironmentSystem, EnvironmentStatus, EnvironmentSystemStatus
from app.db.models.system import System
from app.db.models.dependency import SystemDependency
from app.api.v1.schemas.environment import EnvironmentCreate, EnvironmentUpdate


async def list_environments(
    db: AsyncSession,
    tenant_id: int,
    status_filter: Optional[EnvironmentStatus] = None,
    environment_type: Optional[str] = None,
) -> list[Environment]:
    query = (
        select(Environment)
        .where(Environment.tenant_id == tenant_id, Environment.deleted_at.is_(None))
    )
    if status_filter is not None:
        query = query.where(Environment.status == status_filter)
    if environment_type is not None:
        query = query.where(Environment.environment_type == environment_type)
    query = query.order_by(Environment.name)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> Environment:
    result = await db.execute(
        select(Environment).where(
            Environment.id == env_id,
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        )
    )
    env = result.scalar_one_or_none()
    if env is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    return env


async def create_environment(
    db: AsyncSession, data: EnvironmentCreate, tenant_id: int
) -> Environment:
    # Check name uniqueness within tenant (active records only)
    existing = await db.execute(
        select(Environment).where(
            Environment.name == data.name,
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An environment with this name already exists in this tenant",
        )
    env = Environment(
        name=data.name,
        description=data.description,
        environment_type=data.environment_type,
        status=data.status,
        tenant_id=tenant_id,
        custom_fields=data.custom_fields,
    )
    db.add(env)
    await db.flush()
    await db.refresh(env)
    return env


async def update_environment(
    db: AsyncSession, env_id: int, data: EnvironmentUpdate, tenant_id: int
) -> Environment:
    env = await get_environment(db, env_id, tenant_id)

    if data.name is not None and data.name != env.name:
        existing = await db.execute(
            select(Environment).where(
                Environment.name == data.name,
                Environment.tenant_id == tenant_id,
                Environment.id != env_id,
                Environment.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An environment with this name already exists in this tenant",
            )
        env.name = data.name

    if data.description is not None:
        env.description = data.description
    if data.environment_type is not None:
        env.environment_type = data.environment_type
    if data.status is not None:
        env.status = data.status
    if data.custom_fields is not None:
        env.custom_fields = data.custom_fields

    await db.flush()
    await db.refresh(env)
    return env


async def delete_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> None:
    env = await get_environment(db, env_id, tenant_id)
    env.deleted_at = datetime.now(timezone.utc)
    # EnvironmentSystem rows are a junction table — no soft-delete needed;
    # they're naturally excluded once the parent environment is gone.
    await db.flush()


async def verify_environment(db: AsyncSession, env_id: int, tenant_id: int) -> dict:
    """
    For each system in the environment, check if its declared dependencies are also
    present in the environment. Returns a gap report.
    """
    # Confirm environment exists and belongs to tenant
    await get_environment(db, env_id, tenant_id)

    # Load all EnvironmentSystem rows for this env, with the nested System
    env_sys_result = await db.execute(
        select(EnvironmentSystem)
        .where(EnvironmentSystem.environment_id == env_id)
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys_rows: list[EnvironmentSystem] = list(env_sys_result.scalars().all())

    # Build lookup: system_id → EnvironmentSystem
    env_system_map: dict[int, EnvironmentSystem] = {
        row.system_id: row for row in env_sys_rows
    }

    systems_result: list[dict] = []
    total_deps = 0
    satisfied_count = 0
    mocked_count = 0
    missing_count = 0

    for system_id, env_sys in env_system_map.items():
        # Load declared dependencies for this system within the tenant
        dep_result = await db.execute(
            select(SystemDependency)
            .where(
                SystemDependency.from_system_id == system_id,
                SystemDependency.tenant_id == tenant_id,
            )
        )
        deps: list[SystemDependency] = list(dep_result.scalars().all())

        verify_items: list[dict] = []
        for dep in deps:
            to_id = dep.to_system_id
            if to_id in env_system_map:
                to_env_sys = env_system_map[to_id]
                if to_env_sys.status == EnvironmentSystemStatus.MOCK:
                    dep_status = "mocked"
                    mocked_count += 1
                else:
                    dep_status = "satisfied"
                    satisfied_count += 1
            else:
                dep_status = "missing"
                missing_count += 1

            total_deps += 1

            # Resolve to_system name — try from env_system_map first, else query
            if to_id in env_system_map:
                to_system_name = env_system_map[to_id].system.name
            else:
                sys_result = await db.execute(
                    select(System).where(System.id == to_id)
                )
                sys_obj = sys_result.scalar_one_or_none()
                to_system_name = sys_obj.name if sys_obj else f"System#{to_id}"

            verify_items.append(
                {
                    "to_system_id": to_id,
                    "to_system_name": to_system_name,
                    "dependency_type": dep.dependency_type,
                    "status": dep_status,
                }
            )

        systems_result.append(
            {
                "system_id": system_id,
                "system_name": env_sys.system.name,
                "dependencies": verify_items,
            }
        )

    return {
        "environment_id": env_id,
        "total_dependencies": total_deps,
        "satisfied_count": satisfied_count,
        "mocked_count": mocked_count,
        "missing_count": missing_count,
        "systems": systems_result,
    }
