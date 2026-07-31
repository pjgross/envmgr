from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.core.pagination import Page, pagination, set_total_count
from app.services import change_request_service
from app.api.v1.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestUpdate,
    ChangeRequestResponse,
    ChangeRequestDetailResponse,
    ChangeRequestTransition,
    ChangeHistoryEntry,
    PreviewOutageConflictsRequest,
    PreviewOutageConflictsResponse,
)


router = APIRouter(prefix="/change-requests", tags=["Change Requests"])


async def _shape(db: AsyncSession, cr, tenant_id: int) -> dict:
    return await change_request_service.build_cr_response_dict(db, cr, tenant_id)


@router.get("", response_model=list[ChangeRequestResponse])
async def list_change_requests(
    response: Response,
    environment_id: Optional[int] = Query(None),
    host_id: Optional[int] = Query(None),
    subsystem_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    scheduled_from: Optional[datetime] = Query(None),
    scheduled_to: Optional[datetime] = Query(None),
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    crs, total = await change_request_service.list_change_requests(
        db,
        tenant_id,
        environment_id=environment_id,
        host_id=host_id,
        subsystem_id=subsystem_id,
        status_filter=status_filter,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
        page=page,
    )
    set_total_count(response, total)
    return [await _shape(db, cr, tenant_id) for cr in crs]


@router.post("", response_model=ChangeRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_change_request(
    data: ChangeRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    cr = await change_request_service.create_change_request(
        db, data, current_user, tenant_id
    )
    return await _shape(db, cr, tenant_id)


@router.post("/preview-outage-conflicts", response_model=PreviewOutageConflictsResponse)
async def preview_outage_conflicts(
    data: PreviewOutageConflictsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Advisory: list booking conflicts grouped by each environment in the
    effective set (explicit environment_ids ∪ envs derived from host_ids).
    """
    return await change_request_service.preview_outage_conflicts(
        db,
        environment_ids=data.environment_ids,
        host_ids=data.host_ids,
        outage_start=data.outage_start,
        outage_end=data.outage_end,
        tenant_id=current_user.active_tenant_id,
        exclude_change_request_id=data.exclude_change_request_id,
    )


@router.get("/{cr_id}", response_model=ChangeRequestDetailResponse)
async def get_change_request_detail(
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    cr = await change_request_service.get_change_request(db, cr_id, tenant_id)
    history = await change_request_service.list_history(db, cr_id, tenant_id)
    payload = await _shape(db, cr, tenant_id)
    payload["history"] = [ChangeHistoryEntry.model_validate(h).model_dump() for h in history]
    return payload


@router.patch("/{cr_id}", response_model=ChangeRequestResponse)
async def update_change_request(
    cr_id: int,
    data: ChangeRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    cr = await change_request_service.update_change_request(
        db, cr_id, data, current_user, tenant_id
    )
    return await _shape(db, cr, tenant_id)


@router.post("/{cr_id}/transition", response_model=ChangeRequestResponse)
async def transition_change_request(
    cr_id: int,
    data: ChangeRequestTransition,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    cr = await change_request_service.transition_status(
        db, cr_id, data.to_state, current_user, tenant_id, notes=data.notes,
    )
    return await _shape(db, cr, tenant_id)


@router.get("/{cr_id}/allowed-transitions")
async def get_allowed_transitions(
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await change_request_service.get_allowed_transitions(
        db, cr_id, current_user, current_user.active_tenant_id
    )


@router.delete("/{cr_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_change_request(
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await change_request_service.soft_delete_change_request(
        db, cr_id, current_user.active_tenant_id
    )
