from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.booking import BookingStatus
from app.services import booking_service
from app.api.v1.schemas.booking import BookingCreate, BookingResponse, BookingCreateResponse

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
    # Populate environment_name if the relationship is loaded
    try:
        resp.environment_name = booking.environment.name if booking.environment else None
    except Exception:
        resp.environment_name = None
    # Populate booked_by_username if the relationship is loaded
    try:
        resp.booked_by_username = booking.booker.username if booking.booker else None
    except Exception:
        resp.booked_by_username = None
    return resp


@router.get("/", response_model=list[BookingResponse])
async def list_bookings(
    environment_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    booking_status: Optional[BookingStatus] = None,
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
    return _to_response(booking)


@router.post("/{booking_id}/approve", response_model=BookingResponse)
async def approve_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin_or_rm),
):
    booking = await booking_service.approve_booking(db, booking_id, current_user.active_tenant_id)
    return _to_response(booking)


@router.post("/{booking_id}/reject", response_model=BookingResponse)
async def reject_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin_or_rm),
):
    booking = await booking_service.reject_booking(db, booking_id, current_user.active_tenant_id)
    return _to_response(booking)


@router.post("/{booking_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await booking_service.cancel_booking(db, booking_id, current_user)


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await booking_service.delete_series(db, booking_id, current_user.active_tenant_id)


@router.delete("/{booking_id}/occurrence", status_code=status.HTTP_204_NO_CONTENT)
async def delete_occurrence(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await booking_service.delete_occurrence(db, booking_id, current_user)
