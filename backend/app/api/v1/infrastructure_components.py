from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.db.models.infrastructure_component import (
    InfrastructureComponent,
    InfrastructureComponentSource,
    InfrastructureComponentType,
)
from app.services import infrastructure_component_service
from app.api.v1.schemas.infrastructure_component import (
    HostImpactResponse,
    InfrastructureComponentCreate,
    InfrastructureComponentResponse,
    InfrastructureComponentUpdate,
)

router = APIRouter()


INFRASTRUCTURE_SORTS = {
    "name": InfrastructureComponent.name,
    "component_type": InfrastructureComponent.component_type,
    "provider": InfrastructureComponent.provider,
    "region": InfrastructureComponent.region,
    "source": InfrastructureComponent.source,
}


@router.get("/", response_model=list[InfrastructureComponentResponse])
async def list_components(
    response: Response,
    component_type: Optional[InfrastructureComponentType] = None,
    provider: Optional[str] = None,
    region: Optional[str] = None,
    source: Optional[InfrastructureComponentSource] = None,
    search: Optional[str] = Query(None, description="Case-insensitive name/provider/region contains"),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(INFRASTRUCTURE_SORTS, default="name")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await infrastructure_component_service.list_infrastructure_components(
        db,
        current_user.active_tenant_id,
        component_type=component_type,
        provider=provider,
        region=region,
        source=source,
        search=search,
        page=page,
        sort=sort,
    )
    set_total_count(response, total)
    return rows


@router.post("/", response_model=InfrastructureComponentResponse, status_code=status.HTTP_201_CREATED)
async def create_component(
    data: InfrastructureComponentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await infrastructure_component_service.create_infrastructure_component(
        db, data, current_user.active_tenant_id
    )


@router.get("/impact", response_model=HostImpactResponse)
async def host_impact(
    host_ids: list[int] = Query(default_factory=list),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readonly: for each environment whose subsystems run on any of `host_ids`,
    list the matching subsystems + host/role combinations. Used by the Change
    Request form to show platform-change impact inline.
    """
    return await infrastructure_component_service.host_impact(
        db, current_user.active_tenant_id, host_ids
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
