"""Release Event Types API — CRUD for tenant-level event type catalogue."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import release_event_service
from app.api.v1.schemas.release_event import (
    ReleaseEventTypeCreate,
    ReleaseEventTypeUpdate,
    ReleaseEventTypeRead,
)

router = APIRouter(prefix="/release-event-types", tags=["Release Event Types"])


@router.get("", response_model=list[ReleaseEventTypeRead])
async def list_event_types(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_event_service.list_event_types(db, current_user.active_tenant_id)


@router.post("", response_model=ReleaseEventTypeRead, status_code=status.HTTP_201_CREATED)
async def create_event_type(
    data: ReleaseEventTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_event_service.create_event_type(db, data, current_user.active_tenant_id)


@router.put("/{type_id}", response_model=ReleaseEventTypeRead)
async def update_event_type(
    type_id: int,
    data: ReleaseEventTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_event_service.update_event_type(
        db, type_id, data, current_user.active_tenant_id
    )


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await release_event_service.delete_event_type(
        db, type_id, current_user.active_tenant_id
    )
