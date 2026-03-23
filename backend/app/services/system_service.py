from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system import System, SubSystem
from app.api.v1.schemas.system import SystemCreate, SystemUpdate, SubSystemCreate, SubSystemUpdate
from app.core.events import publish_event
from app.services.custom_field_service import validate_custom_fields


async def list_systems(db: AsyncSession, tenant_id: int) -> list[System]:
    result = await db.execute(
        select(System)
        .where(System.tenant_id == tenant_id, System.deleted_at.is_(None))
        .order_by(System.name)
    )
    return list(result.scalars().all())


async def get_system(db: AsyncSession, system_id: int, tenant_id: int) -> System:
    result = await db.execute(
        select(System).where(
            System.id == system_id,
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    system = result.scalar_one_or_none()
    if system is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")
    return system


async def create_system(db: AsyncSession, data: SystemCreate, tenant_id: int) -> System:
    # Check name uniqueness within tenant (active records only)
    existing = await db.execute(
        select(System).where(
            System.name == data.name,
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A system with this name already exists in this tenant",
        )
    await validate_custom_fields(db, tenant_id, "system", data.custom_fields)
    system = System(
        name=data.name,
        description=data.description,
        tenant_id=tenant_id,
        github_repository_url=data.github_repository_url,
        custom_fields=data.custom_fields,
    )
    db.add(system)
    await db.flush()
    await db.refresh(system)
    await publish_event(
        db,
        event_type="SystemCreated",
        aggregate_id=system.id,
        aggregate_type="System",
        payload={"id": system.id, "name": system.name, "tenant_id": system.tenant_id},
        tenant_id=system.tenant_id,
    )
    return system


async def update_system(
    db: AsyncSession, system_id: int, data: SystemUpdate, tenant_id: int
) -> System:
    system = await get_system(db, system_id, tenant_id)

    if data.name is not None and data.name != system.name:
        existing = await db.execute(
            select(System).where(
                System.name == data.name,
                System.tenant_id == tenant_id,
                System.id != system_id,
                System.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A system with this name already exists in this tenant",
            )
        system.name = data.name

    if data.description is not None:
        system.description = data.description
    if data.github_repository_url is not None:
        system.github_repository_url = data.github_repository_url
    if data.custom_fields is not None:
        system.custom_fields = data.custom_fields

    if data.custom_fields is not None:
        await validate_custom_fields(db, tenant_id, "system", data.custom_fields)
    await db.flush()
    await db.refresh(system)
    await publish_event(
        db,
        event_type="SystemUpdated",
        aggregate_id=system.id,
        aggregate_type="System",
        payload={"id": system.id, "name": system.name, "tenant_id": system.tenant_id},
        tenant_id=system.tenant_id,
    )
    return system


async def delete_system(db: AsyncSession, system_id: int, tenant_id: int) -> None:
    system = await get_system(db, system_id, tenant_id)
    now = datetime.now(timezone.utc)
    system.deleted_at = now

    # Cascade soft-delete all subsystems
    await db.execute(
        update(SubSystem)
        .where(SubSystem.system_id == system_id, SubSystem.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    await db.flush()
    await publish_event(
        db,
        event_type="SystemDeleted",
        aggregate_id=system.id,
        aggregate_type="System",
        payload={"id": system.id, "name": system.name, "tenant_id": system.tenant_id},
        tenant_id=system.tenant_id,
    )


# ---------------------------------------------------------------------------
# SubSystem operations
# ---------------------------------------------------------------------------


async def list_subsystems(
    db: AsyncSession, system_id: int, tenant_id: int
) -> list[SubSystem]:
    # Verify the parent system exists and belongs to the tenant
    await get_system(db, system_id, tenant_id)
    result = await db.execute(
        select(SubSystem)
        .where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
        .order_by(SubSystem.name)
    )
    return list(result.scalars().all())


async def get_subsystem(
    db: AsyncSession, subsystem_id: int, system_id: int, tenant_id: int
) -> SubSystem:
    result = await db.execute(
        select(SubSystem).where(
            SubSystem.id == subsystem_id,
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    subsystem = result.scalar_one_or_none()
    if subsystem is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SubSystem not found")
    return subsystem


async def create_subsystem(
    db: AsyncSession, system_id: int, data: SubSystemCreate, tenant_id: int
) -> SubSystem:
    # Verify parent system exists and belongs to tenant
    await get_system(db, system_id, tenant_id)

    # Check subsystem name uniqueness within system
    existing = await db.execute(
        select(SubSystem).where(
            SubSystem.name == data.name,
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A subsystem with this name already exists in this system",
        )

    await validate_custom_fields(db, tenant_id, "subsystem", data.custom_fields)
    subsystem = SubSystem(
        name=data.name,
        description=data.description,
        system_id=system_id,
        tenant_id=tenant_id,
        custom_fields=data.custom_fields,
    )
    db.add(subsystem)
    await db.flush()
    await db.refresh(subsystem)
    return subsystem


async def update_subsystem(
    db: AsyncSession,
    subsystem_id: int,
    system_id: int,
    data: SubSystemUpdate,
    tenant_id: int,
) -> SubSystem:
    subsystem = await get_subsystem(db, subsystem_id, system_id, tenant_id)

    if data.name is not None and data.name != subsystem.name:
        existing = await db.execute(
            select(SubSystem).where(
                SubSystem.name == data.name,
                SubSystem.system_id == system_id,
                SubSystem.tenant_id == tenant_id,
                SubSystem.id != subsystem_id,
                SubSystem.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A subsystem with this name already exists in this system",
            )
        subsystem.name = data.name

    if data.description is not None:
        subsystem.description = data.description
    if data.custom_fields is not None:
        subsystem.custom_fields = data.custom_fields

    if data.custom_fields is not None:
        await validate_custom_fields(db, tenant_id, "subsystem", data.custom_fields)
    await db.flush()
    await db.refresh(subsystem)
    return subsystem


async def delete_subsystem(
    db: AsyncSession, subsystem_id: int, system_id: int, tenant_id: int
) -> None:
    subsystem = await get_subsystem(db, subsystem_id, system_id, tenant_id)
    subsystem.deleted_at = datetime.now(timezone.utc)
    await db.flush()
