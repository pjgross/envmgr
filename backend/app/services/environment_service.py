from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment, EnvironmentStatus
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
