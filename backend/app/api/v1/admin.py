from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import require_master_admin, create_access_token
from app.services import tenant_service, user_admin_service
from app.api.v1.schemas import (
    TenantCreate, TenantUpdate, TenantResponse,
    UserAdminCreate, UserResponse, ImpersonationToken,
)

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
