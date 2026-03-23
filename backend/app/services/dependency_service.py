from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.dependency import SystemDependency, ComponentDependency
from app.db.models.system import System, SubSystem
from app.api.v1.schemas.dependency import SystemDependencyCreate, ComponentDependencyCreate
from app.services.system_service import get_system


# ---------------------------------------------------------------------------
# SystemDependency operations
# ---------------------------------------------------------------------------


async def list_system_dependencies(
    db: AsyncSession, system_id: int, tenant_id: int
) -> list[SystemDependency]:
    # Verify system belongs to tenant
    await get_system(db, system_id, tenant_id)
    result = await db.execute(
        select(SystemDependency)
        .where(
            SystemDependency.from_system_id == system_id,
            SystemDependency.tenant_id == tenant_id,
        )
        .options(selectinload(SystemDependency.to_system))
        .order_by(SystemDependency.id)
    )
    return list(result.scalars().all())


async def create_system_dependency(
    db: AsyncSession,
    system_id: int,
    data: SystemDependencyCreate,
    tenant_id: int,
) -> SystemDependency:
    # Verify from_system belongs to tenant
    await get_system(db, system_id, tenant_id)

    # Self-reference check before any further DB queries
    if data.to_system_id == system_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A system cannot depend on itself",
        )

    # Verify to_system belongs to tenant
    to_sys_result = await db.execute(
        select(System).where(
            System.id == data.to_system_id,
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    if to_sys_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target system not found in this tenant",
        )

    # Check not duplicate
    existing = await db.execute(
        select(SystemDependency).where(
            SystemDependency.from_system_id == system_id,
            SystemDependency.to_system_id == data.to_system_id,
            SystemDependency.tenant_id == tenant_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This dependency already exists",
        )

    dep = SystemDependency(
        from_system_id=system_id,
        to_system_id=data.to_system_id,
        dependency_type=data.dependency_type,
        source=data.source,
        tenant_id=tenant_id,
    )
    db.add(dep)
    await db.flush()

    # Reload with relationship
    result = await db.execute(
        select(SystemDependency)
        .where(SystemDependency.id == dep.id)
        .options(selectinload(SystemDependency.to_system))
    )
    return result.scalar_one()


async def delete_system_dependency(
    db: AsyncSession, dep_id: int, system_id: int, tenant_id: int
) -> None:
    result = await db.execute(
        select(SystemDependency).where(
            SystemDependency.id == dep_id,
            SystemDependency.from_system_id == system_id,
            SystemDependency.tenant_id == tenant_id,
        )
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dependency not found",
        )
    await db.delete(dep)
    await db.flush()


# ---------------------------------------------------------------------------
# ComponentDependency operations
# ---------------------------------------------------------------------------


async def _get_subsystem(
    db: AsyncSession, subsystem_id: int, tenant_id: int
) -> SubSystem:
    """Load a subsystem verifying tenant ownership."""
    result = await db.execute(
        select(SubSystem).where(
            SubSystem.id == subsystem_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SubSystem not found",
        )
    return sub


async def list_component_dependencies(
    db: AsyncSession, subsystem_id: int, tenant_id: int
) -> list[ComponentDependency]:
    # Verify subsystem belongs to tenant
    await _get_subsystem(db, subsystem_id, tenant_id)
    result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.from_subsystem_id == subsystem_id,
            ComponentDependency.tenant_id == tenant_id,
        )
        .options(selectinload(ComponentDependency.to_subsystem))
        .order_by(ComponentDependency.id)
    )
    return list(result.scalars().all())


async def create_component_dependency(
    db: AsyncSession,
    subsystem_id: int,
    data: ComponentDependencyCreate,
    tenant_id: int,
) -> ComponentDependency:
    # Verify from_subsystem belongs to tenant
    await _get_subsystem(db, subsystem_id, tenant_id)

    # Verify to_subsystem belongs to tenant
    await _get_subsystem(db, data.to_subsystem_id, tenant_id)

    # Check for self-reference
    if subsystem_id == data.to_subsystem_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A subsystem cannot depend on itself",
        )

    # Check not duplicate
    existing = await db.execute(
        select(ComponentDependency).where(
            ComponentDependency.from_subsystem_id == subsystem_id,
            ComponentDependency.to_subsystem_id == data.to_subsystem_id,
            ComponentDependency.tenant_id == tenant_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This component dependency already exists",
        )

    dep = ComponentDependency(
        from_subsystem_id=subsystem_id,
        to_subsystem_id=data.to_subsystem_id,
        dependency_type=data.dependency_type,
        protocol=data.protocol,
        port=data.port,
        source=data.source,
        tenant_id=tenant_id,
    )
    db.add(dep)
    await db.flush()

    # Reload with relationship
    result = await db.execute(
        select(ComponentDependency)
        .where(ComponentDependency.id == dep.id)
        .options(selectinload(ComponentDependency.to_subsystem))
    )
    return result.scalar_one()


async def delete_component_dependency(
    db: AsyncSession, dep_id: int, subsystem_id: int, tenant_id: int
) -> None:
    result = await db.execute(
        select(ComponentDependency).where(
            ComponentDependency.id == dep_id,
            ComponentDependency.from_subsystem_id == subsystem_id,
            ComponentDependency.tenant_id == tenant_id,
        )
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Component dependency not found",
        )
    await db.delete(dep)
    await db.flush()
