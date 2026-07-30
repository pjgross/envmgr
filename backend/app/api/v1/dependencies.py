from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, pagination, set_total_count
from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.dependency import ComponentDependency
from app.services import dependency_service
from app.api.v1.schemas.dependency import (
    SystemDependencyCreate,
    SystemDependencyUpdate,
    SystemDependencyResponse,
    ComponentDependencyCreate,
    ComponentDependencyUpdate,
    ComponentDependencyResponse,
    ComponentEndpointCreate,
    ComponentEndpointUpdate,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_comp_dep_response(
    dep: ComponentDependency, subsystem_id: int
) -> ComponentDependencyResponse:
    return ComponentDependencyResponse(
        id=dep.id,
        from_subsystem_id=dep.from_subsystem_id,
        to_subsystem_id=dep.to_subsystem_id,
        dependency_type=dep.dependency_type,
        direction=dep.direction,
        protocol=dep.protocol,
        port=dep.port,
        source=dep.source,
        label=dep.label,
        tenant_id=dep.tenant_id,
        to_subsystem=dep.to_subsystem,
        from_subsystem=dep.from_subsystem,
        is_incoming=dep.to_subsystem_id == subsystem_id,
        endpoints=dep.endpoints,
    )


# ---------------------------------------------------------------------------
# System dependency endpoints (nested under /systems/{id}/dependencies)
# ---------------------------------------------------------------------------


@router.get(
    "/systems/{system_id}/dependencies",
    response_model=list[SystemDependencyResponse],
)
async def list_system_dependencies(
    system_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await dependency_service.list_system_dependencies(
        db, system_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [
        SystemDependencyResponse(
            id=dep.id,
            from_system_id=dep.from_system_id,
            to_system_id=dep.to_system_id,
            dependency_type=dep.dependency_type,
            direction=dep.direction,
            source=dep.source,
            tenant_id=dep.tenant_id,
            to_system=dep.to_system,
            from_system=dep.from_system,
            is_incoming=dep.to_system_id == system_id,
        )
        for dep in rows
    ]


@router.post(
    "/systems/{system_id}/dependencies",
    response_model=SystemDependencyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_system_dependency(
    system_id: int,
    data: SystemDependencyCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    dep = await dependency_service.create_system_dependency(
        db, system_id, data, current_user.active_tenant_id
    )
    return SystemDependencyResponse(
        id=dep.id,
        from_system_id=dep.from_system_id,
        to_system_id=dep.to_system_id,
        dependency_type=dep.dependency_type,
        direction=dep.direction,
        source=dep.source,
        tenant_id=dep.tenant_id,
        to_system=dep.to_system,
        from_system=dep.from_system,
        is_incoming=False,
    )


@router.delete(
    "/systems/{system_id}/dependencies/{dep_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_system_dependency(
    system_id: int,
    dep_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await dependency_service.delete_system_dependency(
        db, dep_id, system_id, current_user.active_tenant_id
    )


@router.patch(
    "/systems/{system_id}/dependencies/{dep_id}",
    response_model=SystemDependencyResponse,
)
async def update_system_dependency(
    system_id: int,
    dep_id: int,
    data: SystemDependencyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    dep = await dependency_service.update_system_dependency(
        db, dep_id, system_id, data, current_user.active_tenant_id
    )
    return SystemDependencyResponse(
        id=dep.id,
        from_system_id=dep.from_system_id,
        to_system_id=dep.to_system_id,
        dependency_type=dep.dependency_type,
        direction=dep.direction,
        source=dep.source,
        tenant_id=dep.tenant_id,
        to_system=dep.to_system,
        from_system=dep.from_system,
        is_incoming=dep.to_system_id == system_id,
    )


# ---------------------------------------------------------------------------
# Component dependency endpoints (nested under /subsystems/{id}/dependencies)
# ---------------------------------------------------------------------------


@router.get(
    "/subsystems/{subsystem_id}/dependencies",
    response_model=list[ComponentDependencyResponse],
)
async def list_component_dependencies(
    subsystem_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await dependency_service.list_component_dependencies(
        db, subsystem_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [_build_comp_dep_response(dep, subsystem_id) for dep in rows]


@router.post(
    "/subsystems/{subsystem_id}/dependencies",
    response_model=ComponentDependencyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_component_dependency(
    subsystem_id: int,
    data: ComponentDependencyCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    dep = await dependency_service.create_component_dependency(
        db, subsystem_id, data, current_user.active_tenant_id
    )
    return _build_comp_dep_response(dep, subsystem_id)


@router.delete(
    "/subsystems/{subsystem_id}/dependencies/{dep_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_component_dependency(
    subsystem_id: int,
    dep_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await dependency_service.delete_component_dependency(
        db, dep_id, subsystem_id, current_user.active_tenant_id
    )


@router.patch(
    "/subsystems/{subsystem_id}/dependencies/{dep_id}",
    response_model=ComponentDependencyResponse,
)
async def update_component_dependency(
    subsystem_id: int,
    dep_id: int,
    data: ComponentDependencyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    dep = await dependency_service.update_component_dependency(
        db, dep_id, subsystem_id, data, current_user.active_tenant_id
    )
    return _build_comp_dep_response(dep, subsystem_id)


# ---------------------------------------------------------------------------
# Component endpoint endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/subsystems/{subsystem_id}/dependencies/{dep_id}/endpoints",
    response_model=ComponentDependencyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_component_endpoint(
    subsystem_id: int,
    dep_id: int,
    data: ComponentEndpointCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    dep = await dependency_service.create_component_endpoint(
        db, dep_id, subsystem_id, data, current_user.active_tenant_id
    )
    return _build_comp_dep_response(dep, subsystem_id)


@router.patch(
    "/subsystems/{subsystem_id}/dependencies/{dep_id}/endpoints/{endpoint_id}",
    response_model=ComponentDependencyResponse,
)
async def update_component_endpoint(
    subsystem_id: int,
    dep_id: int,
    endpoint_id: int,
    data: ComponentEndpointUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    dep = await dependency_service.update_component_endpoint(
        db, dep_id, endpoint_id, subsystem_id, data, current_user.active_tenant_id
    )
    return _build_comp_dep_response(dep, subsystem_id)


@router.delete(
    "/subsystems/{subsystem_id}/dependencies/{dep_id}/endpoints/{endpoint_id}",
    response_model=ComponentDependencyResponse,
)
async def delete_component_endpoint(
    subsystem_id: int,
    dep_id: int,
    endpoint_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    dep = await dependency_service.delete_component_endpoint(
        db, dep_id, endpoint_id, subsystem_id, current_user.active_tenant_id
    )
    return _build_comp_dep_response(dep, subsystem_id)
