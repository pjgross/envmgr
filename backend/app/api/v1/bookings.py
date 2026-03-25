from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import booking_service
from app.api.v1.schemas.booking import (
    BookingCreate,
    BookingResponse,
    BookingCreateResponse,
    BookingTransitionRequest,
    BookingStatusHistoryResponse,
    AllowedTransitionResponse,
)

router = APIRouter()


async def require_admin_or_rm(current_user=Depends(get_current_user)):
    """Require Admin or Release Manager role."""
    if not (
        current_user.is_master_admin
        or current_user.role in ("Admin", "Release Manager")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Release Manager required",
        )
    return current_user


def _to_response(booking) -> BookingResponse:
    """Convert a Booking ORM object to BookingResponse, populating optional display fields."""
    resp = BookingResponse.model_validate(booking)
    resp.environment_name = booking.environment.name if booking.environment else None
    resp.booked_by_username = booking.booker.username if booking.booker else None
    return resp


@router.get("/", response_model=list[BookingResponse])
async def list_bookings(
    environment_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    booking_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bookings = await booking_service.list_bookings(
        db,
        current_user.active_tenant_id,
        environment_id=environment_id,
        start=start,
        end=end,
        booking_status=booking_status,
    )
    return [_to_response(b) for b in bookings]


@router.post("/", response_model=BookingCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    data: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking, warnings = await booking_service.create_booking(db, data, current_user)
    return BookingCreateResponse(
        booking=_to_response(booking),
        overlap_warnings=warnings,
    )


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.get_booking(db, booking_id, current_user.active_tenant_id)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp


@router.patch("/{booking_id}/standard-fields", response_model=BookingResponse)
async def update_standard_fields(
    booking_id: int,
    values: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.update_standard_fields(db, booking_id, values, current_user)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp


@router.patch("/{booking_id}/custom-fields", response_model=BookingResponse)
async def update_custom_fields(
    booking_id: int,
    values: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.update_custom_fields(db, booking_id, values, current_user)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp


@router.post("/{booking_id}/approve", response_model=BookingResponse)
async def approve_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin_or_rm),
):
    booking = await booking_service.approve_booking(db, booking_id, current_user)
    return _to_response(booking)


@router.post("/{booking_id}/reject", response_model=BookingResponse)
async def reject_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin_or_rm),
):
    booking = await booking_service.reject_booking(db, booking_id, current_user)
    return _to_response(booking)


@router.post("/{booking_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await booking_service.cancel_booking(db, booking_id, current_user)


@router.post("/{booking_id}/transition", response_model=BookingResponse)
async def transition_booking_state(
    booking_id: int,
    data: BookingTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.transition_state(db, booking_id, data.to_state, current_user, data.notes)
    return _to_response(booking)


@router.get("/{booking_id}/history", response_model=list[BookingStatusHistoryResponse])
async def get_booking_history(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_service.get_status_history(db, booking_id, current_user.active_tenant_id)


@router.get("/{booking_id}/allowed-transitions", response_model=list[AllowedTransitionResponse])
async def get_allowed_transitions_for_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_service.get_booking_allowed_transitions(db, booking_id, current_user)


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await booking_service.delete_series(db, booking_id, current_user)


@router.delete("/{booking_id}/occurrence", status_code=status.HTTP_204_NO_CONTENT)
async def delete_occurrence(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await booking_service.delete_occurrence(db, booking_id, current_user)
