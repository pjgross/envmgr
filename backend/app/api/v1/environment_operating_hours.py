"""Environment operating-hours config + per-env utilization API (Phase 5 SP5a)."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import environment_operating_hours_service as ops_service
from app.services import environment_utilization_service as util_service
from app.api.v1.metrics import _as_dt
from app.api.v1.schemas.environment_operating_hours import (
    OperatingHoursConfigIn,
    OperatingHoursConfigResponse,
    EnvironmentUtilization,
)

router = APIRouter(prefix="/environments", tags=["environment-operating-hours"])


@router.get("/{env_id}/operating-hours", response_model=OperatingHoursConfigResponse)
async def get_operating_hours(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cfg = await ops_service.get_config(db, current_user.active_tenant_id, env_id)
    if cfg is None:
        return OperatingHoursConfigResponse(configured=False)
    return OperatingHoursConfigResponse(configured=True, timezone=cfg.timezone, week=cfg.week)


@router.put("/{env_id}/operating-hours", response_model=OperatingHoursConfigResponse)
async def put_operating_hours(
    env_id: int,
    body: OperatingHoursConfigIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cfg = await ops_service.upsert_config(
        db, current_user.active_tenant_id, env_id, body.timezone,
        [d.model_dump() for d in body.week],
    )
    return OperatingHoursConfigResponse(configured=True, timezone=cfg.timezone, week=cfg.week)


@router.get("/{env_id}/utilization", response_model=EnvironmentUtilization)
async def get_environment_utilization(
    env_id: int,
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await util_service.environment_utilization(
        db, current_user.active_tenant_id, env_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
    )
