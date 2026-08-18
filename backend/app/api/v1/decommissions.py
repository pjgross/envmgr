"""Initiating a decommission, and reading the one live (or most recent) record.

Cross-tenant is 404, never 403, on every route here — following
`app/api/v1/contentions.py`. `environment_decommission_service.get_environment`
(really `environment_service.get_environment`, tenant-filtered) is what makes
that true: a foreign-tenant id simply never matches the query, so the 404 and
the "doesn't exist" case are indistinguishable to the caller, which is the
point.

Two routes, not one:

  - POST .../decommission -- initiate.
  - GET  .../decommission -- the live record, or the most recent terminal
    one when there is no live record, or null. A 404 for "this environment
    has never been decommissioned" would make the panel's ordinary case an
    error path; null is the answer, and the panel renders its initiate
    control from it.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.decommission import DecommissionCreate, DecommissionRead
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.environment_decommission import EnvironmentDecommission
from app.services import environment_decommission_service

router = APIRouter(prefix="/environments", tags=["decommissions"])


def _to_read(row: EnvironmentDecommission, now: datetime) -> DecommissionRead:
    """One decommission as a response. `state` is computed here, never
    `model_validate`d, because there is no state column to validate from —
    see the schema module docstring."""
    return DecommissionRead(
        id=row.id,
        environment_id=row.environment_id,
        reason=row.reason,
        warned_at=row.warned_at,
        scheduled_teardown_at=row.scheduled_teardown_at,
        initiated_by=row.initiated_by,
        extension_requested_at=row.extension_requested_at,
        extension_reason=row.extension_reason,
        extension_until=row.extension_until,
        extension_decided_at=row.extension_decided_at,
        extension_granted=row.extension_granted,
        torn_down_at=row.torn_down_at,
        cancelled_at=row.cancelled_at,
        cancel_reason=row.cancel_reason,
        state=environment_decommission_service.decommission_state(row, now),
    )


@router.post(
    "/{environment_id}/decommission",
    response_model=DecommissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_decommission(
    environment_id: int,
    data: DecommissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # One clock for the whole request: the stored row and its rendered state
    # must come from the same instant, or a row created at 23:59:59 could
    # render 'due' a moment later purely from re-reading the wall clock.
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    row = await environment_decommission_service.initiate(
        db,
        tenant_id,
        environment_id,
        current_user,
        reason=data.reason,
        scheduled_teardown_at=data.scheduled_teardown_at,
    )
    return _to_read(row, now)


@router.get(
    "/{environment_id}/decommission",
    response_model=Optional[DecommissionRead],
)
async def get_decommission(
    environment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    tenant_id = current_user.active_tenant_id
    # 404 across tenants, never 403 — resolving the environment first is what
    # makes a foreign-tenant id behave identically to one that never existed.
    await environment_decommission_service.get_environment(db, environment_id, tenant_id)

    row = await environment_decommission_service.get_live(db, tenant_id, environment_id)
    if row is None:
        row = await environment_decommission_service.get_most_recent(
            db, tenant_id, environment_id
        )
    if row is None:
        return None
    return _to_read(row, now)
