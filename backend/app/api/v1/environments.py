from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.environment import EnvironmentStatus
from app.services import environment_service, environment_system_service
from app.api.v1.schemas.environment import (
    EnvironmentCreate,
    EnvironmentUpdate,
    EnvironmentResponse,
    EnvironmentSystemCreate,
    EnvironmentSystemUpdate,
    EnvironmentSystemResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Environment endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[EnvironmentResponse])
async def list_environments(
    status: Optional[EnvironmentStatus] = None,
    environment_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_service.list_environments(
        db, current_user.active_tenant_id, status_filter=status, environment_type=environment_type
    )


@router.post("/", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    data: EnvironmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_service.create_environment(db, data, current_user.active_tenant_id)


@router.get("/{env_id}", response_model=EnvironmentResponse)
async def get_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_service.get_environment(db, env_id, current_user.active_tenant_id)


@router.patch("/{env_id}", response_model=EnvironmentResponse)
async def update_environment(
    env_id: int,
    data: EnvironmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_service.update_environment(
        db, env_id, data, current_user.active_tenant_id
    )


@router.delete("/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_service.delete_environment(db, env_id, current_user.active_tenant_id)


# ---------------------------------------------------------------------------
# EnvironmentSystem endpoints
# ---------------------------------------------------------------------------


@router.get("/{env_id}/systems", response_model=list[EnvironmentSystemResponse])
async def list_systems_in_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_system_service.list_systems_in_environment(
        db, env_id, current_user.active_tenant_id
    )


@router.post(
    "/{env_id}/systems",
    response_model=EnvironmentSystemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_system_to_environment(
    env_id: int,
    data: EnvironmentSystemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_system_service.add_system_to_environment(
        db, env_id, data, current_user.active_tenant_id
    )


@router.patch("/{env_id}/systems/{system_id}", response_model=EnvironmentSystemResponse)
async def update_system_in_environment(
    env_id: int,
    system_id: int,
    data: EnvironmentSystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_system_service.update_system_in_environment(
        db, env_id, system_id, data, current_user.active_tenant_id
    )


@router.delete("/{env_id}/systems/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_system_from_environment(
    env_id: int,
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_system_service.remove_system_from_environment(
        db, env_id, system_id, current_user.active_tenant_id
    )
