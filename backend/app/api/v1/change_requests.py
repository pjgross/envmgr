from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import change_request_service
from app.api.v1.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestUpdate,
    ChangeRequestResponse,
    ChangeRequestDetailResponse,
    ChangeRequestTransition,
    ChangeHistoryEntry,
)


router = APIRouter(prefix="/change-requests", tags=["Change Requests"])


@router.get("", response_model=list[ChangeRequestResponse])
async def list_change_requests(
    environment_id: Optional[int] = Query(None),
    subsystem_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    scheduled_from: Optional[datetime] = Query(None),
    scheduled_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await change_request_service.list_change_requests(
        db,
        current_user.active_tenant_id,
        environment_id=environment_id,
        subsystem_id=subsystem_id,
        status_filter=status_filter,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
    )


@router.post("", response_model=ChangeRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_change_request(
    data: ChangeRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await change_request_service.create_change_request(
        db, data, current_user, current_user.active_tenant_id
    )


@router.get("/{cr_id}", response_model=ChangeRequestDetailResponse)
async def get_change_request_detail(
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cr = await change_request_service.get_change_request(
        db, cr_id, current_user.active_tenant_id
    )
    history = await change_request_service.list_history(
        db, cr_id, current_user.active_tenant_id
    )
    # Pydantic v2 model_validate handles the history list via ChangeHistoryEntry
    detail = ChangeRequestDetailResponse.model_validate(cr)
    detail.history = [ChangeHistoryEntry.model_validate(h) for h in history]
    return detail


@router.patch("/{cr_id}", response_model=ChangeRequestResponse)
async def update_change_request(
    cr_id: int,
    data: ChangeRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await change_request_service.update_change_request(
        db, cr_id, data, current_user, current_user.active_tenant_id
    )


@router.post("/{cr_id}/transition", response_model=ChangeRequestResponse)
async def transition_change_request(
    cr_id: int,
    data: ChangeRequestTransition,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await change_request_service.transition_status(
        db,
        cr_id,
        data.to_state,
        current_user,
        current_user.active_tenant_id,
        notes=data.notes,
    )


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
