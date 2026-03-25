from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.dependency import (
    SystemDependency,
    ComponentDependency,
    ComponentEndpoint,
)
from app.db.models.system import System, SubSystem
from app.api.v1.schemas.dependency import (
    SystemDependencyCreate,
    SystemDependencyUpdate,
    ComponentDependencyCreate,
    ComponentDependencyUpdate,
    ComponentEndpointCreate,
    ComponentEndpointUpdate,
)
from app.services.system_service import get_system


# ---------------------------------------------------------------------------
# SystemDependency operations
# ---------------------------------------------------------------------------


async def list_system_dependencies(
    db: AsyncSession, system_id: int, tenant_id: int
) -> tuple[list[SystemDependency], list[SystemDependency]]:
    # Verify system belongs to tenant
    await get_system(db, system_id, tenant_id)

    # Outgoing: this system depends on others
    outgoing_result = await db.execute(
        select(SystemDependency)
        .where(
            SystemDependency.from_system_id == system_id,
            SystemDependency.tenant_id == tenant_id,
        )
        .options(
            selectinload(SystemDependency.to_system),
            selectinload(SystemDependency.from_system),
        )
        .order_by(SystemDependency.id)
    )
    outgoing = list(outgoing_result.scalars().all())

    # Incoming: others depend on this system
    incoming_result = await db.execute(
        select(SystemDependency)
        .where(
            SystemDependency.to_system_id == system_id,
            SystemDependency.tenant_id == tenant_id,
        )
        .options(
            selectinload(SystemDependency.to_system),
            selectinload(SystemDependency.from_system),
        )
        .order_by(SystemDependency.id)
    )
    incoming = list(incoming_result.scalars().all())

    return outgoing, incoming


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
        direction=data.direction,
        source=data.source,
        label=data.label,
        tenant_id=tenant_id,
    )
    db.add(dep)
    await db.flush()

    # Reload with relationships
    result = await db.execute(
        select(SystemDependency)
        .where(SystemDependency.id == dep.id)
        .options(
            selectinload(SystemDependency.to_system),
            selectinload(SystemDependency.from_system),
        )
    )
    return result.scalar_one()


async def delete_system_dependency(
    db: AsyncSession, dep_id: int, system_id: int, tenant_id: int
) -> None:
    result = await db.execute(
        select(SystemDependency).where(
            SystemDependency.id == dep_id,
            SystemDependency.tenant_id == tenant_id,
            or_(
                SystemDependency.from_system_id == system_id,
                SystemDependency.to_system_id == system_id,
            ),
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


async def update_system_dependency(
    db: AsyncSession,
    dep_id: int,
    system_id: int,
    data: SystemDependencyUpdate,
    tenant_id: int,
) -> SystemDependency:
    result = await db.execute(
        select(SystemDependency)
        .where(
            SystemDependency.id == dep_id,
            SystemDependency.tenant_id == tenant_id,
            or_(
                SystemDependency.from_system_id == system_id,
                SystemDependency.to_system_id == system_id,
            ),
        )
        .options(
            selectinload(SystemDependency.from_system),
            selectinload(SystemDependency.to_system),
        )
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dependency not found",
        )
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(dep, field, value)
    await db.flush()
    return dep


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
) -> tuple[list[ComponentDependency], list[ComponentDependency]]:
    # Verify subsystem belongs to tenant
    await _get_subsystem(db, subsystem_id, tenant_id)

    # Outgoing: this subsystem depends on others
    outgoing_result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.from_subsystem_id == subsystem_id,
            ComponentDependency.tenant_id == tenant_id,
        )
        .options(
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
        .order_by(ComponentDependency.id)
    )
    outgoing = list(outgoing_result.scalars().all())

    # Incoming: others depend on this subsystem
    incoming_result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.to_subsystem_id == subsystem_id,
            ComponentDependency.tenant_id == tenant_id,
        )
        .options(
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
        .order_by(ComponentDependency.id)
    )
    incoming = list(incoming_result.scalars().all())

    return outgoing, incoming


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
        direction=data.direction,
        protocol=data.protocol,
        port=data.port,
        source=data.source,
        label=data.label,
        tenant_id=tenant_id,
    )
    db.add(dep)
    await db.flush()

    # Reload with relationships
    result = await db.execute(
        select(ComponentDependency)
        .where(ComponentDependency.id == dep.id)
        .options(
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    return result.scalar_one()


async def delete_component_dependency(
    db: AsyncSession, dep_id: int, subsystem_id: int, tenant_id: int
) -> None:
    result = await db.execute(
        select(ComponentDependency).where(
            ComponentDependency.id == dep_id,
            ComponentDependency.tenant_id == tenant_id,
            or_(
                ComponentDependency.from_subsystem_id == subsystem_id,
                ComponentDependency.to_subsystem_id == subsystem_id,
            ),
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


async def update_component_dependency(
    db: AsyncSession,
    dep_id: int,
    subsystem_id: int,
    data: ComponentDependencyUpdate,
    tenant_id: int,
) -> ComponentDependency:
    result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.id == dep_id,
            ComponentDependency.tenant_id == tenant_id,
            or_(
                ComponentDependency.from_subsystem_id == subsystem_id,
                ComponentDependency.to_subsystem_id == subsystem_id,
            ),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Component dependency not found",
        )
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(dep, field, value)
    await db.flush()
    return dep


# ---------------------------------------------------------------------------
# ComponentEndpoint operations
# ---------------------------------------------------------------------------


async def _get_component_dependency(
    db: AsyncSession, dep_id: int, subsystem_id: int, tenant_id: int
) -> ComponentDependency:
    """Load a ComponentDependency with all relationships, verifying tenant + subsystem ownership."""
    result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.id == dep_id,
            ComponentDependency.tenant_id == tenant_id,
            or_(
                ComponentDependency.from_subsystem_id == subsystem_id,
                ComponentDependency.to_subsystem_id == subsystem_id,
            ),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Component dependency not found",
        )
    return dep


async def create_component_endpoint(
    db: AsyncSession,
    dep_id: int,
    subsystem_id: int,
    data: ComponentEndpointCreate,
    tenant_id: int,
) -> ComponentDependency:
    """Add an endpoint to a component dependency and return the updated dependency."""
    dep = await _get_component_dependency(db, dep_id, subsystem_id, tenant_id)

    endpoint = ComponentEndpoint(
        dependency_id=dep_id,
        http_method=data.http_method,
        path=data.path,
        description=data.description,
        tenant_id=tenant_id,
    )
    db.add(endpoint)
    await db.flush()
    await db.refresh(dep, ["endpoints"])
    return dep


async def update_component_endpoint(
    db: AsyncSession,
    dep_id: int,
    endpoint_id: int,
    subsystem_id: int,
    data: ComponentEndpointUpdate,
    tenant_id: int,
) -> ComponentDependency:
    """Update an endpoint and return the parent dependency with all endpoints."""
    dep = await _get_component_dependency(db, dep_id, subsystem_id, tenant_id)

    ep_result = await db.execute(
        select(ComponentEndpoint).where(
            ComponentEndpoint.id == endpoint_id,
            ComponentEndpoint.dependency_id == dep_id,
            ComponentEndpoint.tenant_id == tenant_id,
        )
    )
    ep = ep_result.scalar_one_or_none()
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ep, field, value)
    await db.flush()
    await db.refresh(dep, ["endpoints"])
    return dep


async def delete_component_endpoint(
    db: AsyncSession,
    dep_id: int,
    endpoint_id: int,
    subsystem_id: int,
    tenant_id: int,
) -> ComponentDependency:
    """Delete an endpoint and return the parent dependency with remaining endpoints."""
    dep = await _get_component_dependency(db, dep_id, subsystem_id, tenant_id)

    ep_result = await db.execute(
        select(ComponentEndpoint).where(
            ComponentEndpoint.id == endpoint_id,
            ComponentEndpoint.dependency_id == dep_id,
            ComponentEndpoint.tenant_id == tenant_id,
        )
    )
    ep = ep_result.scalar_one_or_none()
    if ep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")

    await db.delete(ep)
    await db.flush()
    await db.refresh(dep, ["endpoints"])
    return dep
