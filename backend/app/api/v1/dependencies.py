from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.services import dependency_service
from app.api.v1.schemas.dependency import (
    SystemDependencyCreate,
    SystemDependencyResponse,
    ComponentDependencyCreate,
    ComponentDependencyResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# System dependency endpoints (nested under /systems/{id}/dependencies)
# ---------------------------------------------------------------------------


@router.get(
    "/systems/{system_id}/dependencies",
    response_model=list[SystemDependencyResponse],
)
async def list_system_dependencies(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await dependency_service.list_system_dependencies(
        db, system_id, current_user.active_tenant_id
    )


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
    return await dependency_service.create_system_dependency(
        db, system_id, data, current_user.active_tenant_id
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


# ---------------------------------------------------------------------------
# Component dependency endpoints (nested under /subsystems/{id}/dependencies)
# ---------------------------------------------------------------------------


@router.get(
    "/subsystems/{subsystem_id}/dependencies",
    response_model=list[ComponentDependencyResponse],
)
async def list_component_dependencies(
    subsystem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await dependency_service.list_component_dependencies(
        db, subsystem_id, current_user.active_tenant_id
    )


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
    return await dependency_service.create_component_dependency(
        db, subsystem_id, data, current_user.active_tenant_id
    )


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
