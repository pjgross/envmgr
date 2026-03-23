from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import require_master_admin, create_access_token
from app.services import tenant_service, user_admin_service
from pydantic import BaseModel, Field
from app.api.v1.schemas import (
    TenantCreate, TenantUpdate, TenantResponse,
    UserAdminCreate, UserAdminUpdate, UserRoleUpdate, UserResponse, ImpersonationToken,
)


class PasswordReset(BaseModel):
    new_password: str = Field(..., min_length=8)

router = APIRouter()


@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await tenant_service.list_tenants(db)


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await tenant_service.create_tenant(db, data)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await tenant_service.get_tenant(db, tenant_id)


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: int,
    data: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await tenant_service.update_tenant(db, tenant_id, data)


@router.post("/tenants/{tenant_id}/disable", response_model=TenantResponse)
async def disable_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    if tenant_id == current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot disable your own tenant")
    return await tenant_service.disable_tenant(db, tenant_id)


@router.get("/tenants/{tenant_id}/users", response_model=list[UserResponse])
async def list_tenant_users(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await user_admin_service.list_users(db, tenant_id)


@router.post("/tenants/{tenant_id}/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_user(
    tenant_id: int,
    data: UserAdminCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await user_admin_service.create_user_in_tenant(db, tenant_id, data)


@router.patch("/tenants/{tenant_id}/users/{user_id}", response_model=UserResponse)
async def update_tenant_user(
    tenant_id: int,
    user_id: int,
    data: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await user_admin_service.update_user(db, user_id, tenant_id, data)


@router.patch("/tenants/{tenant_id}/users/{user_id}/role", response_model=UserResponse)
async def set_tenant_user_role(
    tenant_id: int,
    user_id: int,
    data: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await user_admin_service.set_user_role(db, user_id, tenant_id, data.role)


@router.post("/tenants/{tenant_id}/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_tenant_user(
    tenant_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await user_admin_service.deactivate_user(db, user_id, tenant_id)


@router.post("/tenants/{tenant_id}/users/{user_id}/reactivate", response_model=UserResponse)
async def reactivate_tenant_user(
    tenant_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    return await user_admin_service.reactivate_user(db, user_id, tenant_id)


@router.post("/tenants/{tenant_id}/users/{user_id}/reset-password", response_model=UserResponse)
async def reset_user_password(
    tenant_id: int,
    user_id: int,
    data: PasswordReset,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    from app.core.security import get_password_hash
    user = await user_admin_service.get_user(db, user_id, tenant_id)
    user.password_hash = get_password_hash(data.new_password)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/tenants/{tenant_id}/sign-in-as", response_model=ImpersonationToken)
async def sign_in_as_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    tenant = await tenant_service.get_tenant(db, tenant_id)
    token = create_access_token(data={
        "sub": str(current_user.id),
        "tenant_id": current_user.tenant_id,
        "impersonating_tenant_id": tenant_id,
    })
    return ImpersonationToken(access_token=token, target_tenant=tenant)
