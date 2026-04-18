from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.infrastructure_component import (
    InfrastructureComponentSource,
    InfrastructureComponentType,
)
from app.services import infrastructure_component_service
from app.api.v1.schemas.infrastructure_component import (
    InfrastructureComponentCreate,
    InfrastructureComponentResponse,
    InfrastructureComponentUpdate,
)

router = APIRouter()


@router.get("/", response_model=list[InfrastructureComponentResponse])
async def list_components(
    component_type: Optional[InfrastructureComponentType] = None,
    provider: Optional[str] = None,
    region: Optional[str] = None,
    source: Optional[InfrastructureComponentSource] = None,
    search: Optional[str] = Query(None, description="Case-insensitive name contains"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await infrastructure_component_service.list_infrastructure_components(
        db,
        current_user.active_tenant_id,
        component_type=component_type,
        provider=provider,
        region=region,
        source=source,
        search=search,
    )


@router.post("/", response_model=InfrastructureComponentResponse, status_code=status.HTTP_201_CREATED)
async def create_component(
    data: InfrastructureComponentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await infrastructure_component_service.create_infrastructure_component(
        db, data, current_user.active_tenant_id
    )


@router.get("/{component_id}", response_model=InfrastructureComponentResponse)
async def get_component(
    component_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await infrastructure_component_service.get_infrastructure_component(
        db, component_id, current_user.active_tenant_id
    )


@router.patch("/{component_id}", response_model=InfrastructureComponentResponse)
async def update_component(
    component_id: int,
    data: InfrastructureComponentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await infrastructure_component_service.update_infrastructure_component(
        db, component_id, data, current_user.active_tenant_id
    )


@router.delete("/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_component(
    component_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await infrastructure_component_service.delete_infrastructure_component(
        db, component_id, current_user.active_tenant_id
    )
