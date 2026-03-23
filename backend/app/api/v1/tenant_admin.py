from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import require_tenant_admin
from app.services import tenant_service, user_admin_service
from app.api.v1.schemas import (
    TenantAdminSettings, TenantResponse, TenantUpdate,
    UserAdminCreate, UserAdminUpdate, UserRoleUpdate, UserResponse,
)

router = APIRouter()


@router.get("/settings", response_model=TenantResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await tenant_service.get_tenant(db, current_user.active_tenant_id)


@router.patch("/settings", response_model=TenantResponse)
async def update_settings(
    data: TenantAdminSettings,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await tenant_service.update_tenant(
        db, current_user.active_tenant_id, TenantUpdate(settings=data.settings)
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.list_users(db, current_user.active_tenant_id)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserAdminCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.create_user_in_tenant(db, current_user.active_tenant_id, data)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.get_user(db, user_id, current_user.active_tenant_id)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.update_user(db, user_id, current_user.active_tenant_id, data)


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def set_user_role(
    user_id: int,
    data: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.set_user_role(db, user_id, current_user.active_tenant_id, data.role)


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.deactivate_user(db, user_id, current_user.active_tenant_id)
