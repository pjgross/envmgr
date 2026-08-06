from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.db.models.booking import Booking
from app.services import booking_service, booking_request_service, conflict_service, project_service
from app.api.v1.schemas.booking import (
    BookingCreate,
    BookingResponse,
    BookingCreateResponse,
    BookingRequestSummary,
    BookingTransitionRequest,
    BookingStatusHistoryResponse,
    AllowedTransitionResponse,
)

router = APIRouter()

# today's default ordering is `start_date ASC, id` — sorting() must preserve
# that when no sort_by/sort_dir is requested at all (plain default_dir="asc").
BOOKING_SORTS = {
    "start_date": Booking.start_date,
    "end_date": Booking.end_date,
    "status": Booking.status,
}


def _to_response(booking, project_name_link: str | None = None) -> BookingResponse:
    """Convert a Booking ORM object to BookingResponse, populating fields from booking_request.

    `project_name_link` is a batch-resolved name the caller must fetch via
    `project_service.get_project_names` (tenant-scoped, deliberately not
    filtering deleted_at) — never looked up per-row here.
    """
    resp = BookingResponse.model_validate(booking)
    resp.environment_name = booking.environment.name if booking.environment else None
    req = booking.booking_request
    assert req is not None, f"Booking {booking.id} missing booking_request"
    resp.project_name = req.project_name
    resp.project_id = req.project_id
    resp.project_name_link = project_name_link
    resp.booked_by = req.booked_by
    resp.booked_by_username = req.booker.username if getattr(req, "booker", None) else None
    resp.booking_type_id = req.booking_type_id
    resp.exclusive_use = req.exclusive_use_requested
    resp.notes = req.notes
    resp.context_tag = req.context_tag
    resp.custom_fields = req.custom_fields
    return resp


def _request_summary(req) -> BookingRequestSummary:
    """Compose a BookingRequestSummary from a BookingRequest ORM object."""
    summary = BookingRequestSummary.model_validate(req)
    summary.booked_by_username = req.booker.username if getattr(req, "booker", None) else None
    return summary


@router.get("/", response_model=list[BookingResponse])
async def list_bookings(
    response: Response,
    environment_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    booking_status: Optional[str] = None,
    project_id: Optional[int] = Query(None),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(BOOKING_SORTS, default="start_date")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bookings, total = await booking_service.list_bookings(
        db,
        current_user.active_tenant_id,
        environment_id=environment_id,
        start=start,
        end=end,
        booking_status=booking_status,
        project_id=project_id,
        page=page,
        sort=sort,
    )
    set_total_count(response, total)
    names = await project_service.get_project_names(
        db, {b.booking_request.project_id for b in bookings}, current_user.active_tenant_id
    )
    responses: list[BookingResponse] = []
    for b in bookings:
        resp = _to_response(b, names.get(b.booking_request.project_id))
        resp.has_unacknowledged_conflicts = await conflict_service.has_unacknowledged_conflicts(
            db, b.id, current_user.active_tenant_id
        )
        responses.append(resp)
    return responses


@router.post("/", response_model=BookingCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    data: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking, warnings = await booking_service.create_booking(db, data, current_user)
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    return BookingCreateResponse(
        booking=_to_response(booking, names.get(booking.booking_request.project_id)),
        overlap_warnings=warnings,
    )


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.get_booking(db, booking_id, current_user.active_tenant_id)
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    resp = _to_response(booking, names.get(booking.booking_request.project_id))
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.has_unacknowledged_conflicts = await conflict_service.has_unacknowledged_conflicts(
        db, booking.id, current_user.active_tenant_id
    )
    if booking.booking_request_id is not None:
        request_obj = await booking_request_service._get_request(
            db, booking.booking_request_id, current_user.active_tenant_id
        )
        resp.request = _request_summary(request_obj)
    return resp


@router.patch("/{booking_id}/standard-fields", response_model=BookingResponse)
async def update_standard_fields(
    booking_id: int,
    values: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.update_standard_fields(db, booking_id, values, current_user)
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    resp = _to_response(booking, names.get(booking.booking_request.project_id))
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp


@router.post("/{booking_id}/transition", response_model=BookingResponse)
async def transition_booking_state(
    booking_id: int,
    data: BookingTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.transition_state(db, booking_id, data.to_state, current_user, data.notes)
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    return _to_response(booking, names.get(booking.booking_request.project_id))


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
