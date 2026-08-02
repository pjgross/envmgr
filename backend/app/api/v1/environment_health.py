"""Environment Health API — push (API key) + history + overview (JWT)."""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, pagination, set_total_count
from app.db.base import get_db
from app.core.security import get_current_user, api_key_auth
from app.services import environment_health_service as svc
from app.api.v1.schemas.environment_health import (
    HealthSampleCreate,
    HealthSample,
    EnvironmentHealthOverviewRow,
)

router = APIRouter(prefix="/environments", tags=["environment-health"])


@router.post("/{env_id}/health", response_model=HealthSample, status_code=status.HTTP_201_CREATED)
async def push_health(
    env_id: int,
    data: HealthSampleCreate,
    db: AsyncSession = Depends(get_db),
    key=Depends(api_key_auth("environment:health")),
):
    """Push a health sample for an environment (authenticated via API key)."""
    return await svc.record_sample(
        db, key.tenant_id, env_id, data.status, data.source, data.detail, data.recorded_at
    )


@router.get("/{env_id}/health/history", response_model=list[HealthSample])
async def health_history(
    env_id: int,
    response: Response,
    # Keeps this endpoint's own long-standing contract (50 by default, 500 at
    # most) rather than adopting the shared 500/1000: a health timeline is read
    # by a human, and 500 samples is already more than one can take in.
    page: Page = Depends(pagination(default_limit=50, max_limit=500)),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return health history for a single environment, newest first (JWT auth)."""
    rows, total = await svc.get_history(db, current_user.active_tenant_id, env_id, page)
    set_total_count(response, total)
    return rows


@router.get("/health", response_model=list[EnvironmentHealthOverviewRow])
async def health_overview(
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the health overview for all non-decommissioned environments in the tenant (JWT auth)."""
    rows, total = await svc.health_overview(db, current_user.active_tenant_id, page=page)
    set_total_count(response, total)
    return rows
