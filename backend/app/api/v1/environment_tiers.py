from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.db.models.environment_tier import EnvironmentTier
from app.api.v1.schemas.environment_tier import (
    EnvironmentTierCreate,
    EnvironmentTierResponse,
    EnvironmentTierUpdate,
)
from app.services import environment_tier_service

router = APIRouter()

ENVIRONMENT_TIER_SORTS = {
    "name": EnvironmentTier.name,
    "display_order": EnvironmentTier.display_order,
    "created_at": EnvironmentTier.created_at,
}


@router.get("/", response_model=list[EnvironmentTierResponse])
async def list_environment_tiers(
    response: Response,
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(ENVIRONMENT_TIER_SORTS, default="display_order")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Every tier for the tenant. Readable by any member — every environment
    form needs it."""
    rows, total = await environment_tier_service.list_tiers(
        db, current_user.active_tenant_id, page=page, sort=sort
    )
    set_total_count(response, total)
    return rows


@router.post(
    "/", response_model=EnvironmentTierResponse, status_code=status.HTTP_201_CREATED
)
async def create_environment_tier(
    data: EnvironmentTierCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_tier_service.create_tier(
        db, data, current_user.active_tenant_id
    )


@router.get("/{tier_id}", response_model=EnvironmentTierResponse)
async def get_environment_tier(
    tier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_tier_service.get_tier(
        db, tier_id, current_user.active_tenant_id
    )


@router.patch("/{tier_id}", response_model=EnvironmentTierResponse)
async def update_environment_tier(
    tier_id: int,
    data: EnvironmentTierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_tier_service.update_tier(
        db, tier_id, data, current_user.active_tenant_id
    )


@router.delete("/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment_tier(
    tier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_tier_service.delete_tier(
        db, tier_id, current_user.active_tenant_id
    )
