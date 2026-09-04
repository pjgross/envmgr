from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.services import (
    agreement_gap_service, booking_service, booking_request_service,
    conflict_service, contention_forecast_service, environment_group_service,
    project_service,
)
from app.api.v1.schemas.agreement_gap import (
    AgreementGapAckRead,
    AgreementGapAckUpsert,
)
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
    # B4. SORTABLE, unlike `agreement_gap`: this is a stored column on the
    # joined booking_request, not a value resolved after the page is fetched.
    # It is therefore not a member of docs/pagination.md's permanently-
    # unsortable set.
    "protection_level": BookingRequest.protection_level,
}


def _to_response(
    booking,
    project_name_link: str | None,
    group_name: str | None,
    gap: agreement_gap_service.GapWarning | None,
    has_unacknowledged_conflicts: bool,
    contention_state: str | None,
) -> BookingResponse:
    """Convert a Booking ORM object to BookingResponse, populating fields from booking_request.

    `project_name_link` is a batch-resolved name the caller must fetch via
    `project_service.get_project_names` (tenant-scoped, deliberately not
    filtering deleted_at) — never looked up per-row here.

    `group_name` is likewise batch-resolved, via
    `environment_group_service.get_group_names` — the name of the group
    (archived or not) this booking's `environment_group_id` points at, or
    None for a hand-picked environment. Required-positional, not defaulted:
    A1's review found a defaulted equivalent (`project_name_link=None`) left
    four of five call sites silently rendering null, because Pydantic
    silently defaults a missing non-column attribute rather than raising.

    `gap` is this booking's A3 usage-agreement warning, or None when there is
    none — batch-resolved via `agreement_gap_service.gap_warnings_for_bookings`
    for the WHOLE set the caller is responding with. Never
    `has_unacknowledged_agreement_gap` per row: that is the batch call for one
    booking, so a 50-row page would issue ~150 queries. Required-positional for
    the reason above.

    `has_unacknowledged_conflicts` is now required-positional too, and used to
    be the counter-example this docstring cited: it was assigned at the CALL
    SITE, and four of this function's six callers never assigned it, so those
    four reported every booking as conflict-free. It is batch-resolved via
    `conflict_service.bookings_with_unacknowledged_conflicts` — the per-row form
    costs `list_conflicts` plus one ack lookup PER CONFLICT and must never be
    called in a loop over a page.

    `contention_state` is B6's folded forward-contention state (`unowned` /
    `owned` / `decided`), or None when this booking has no contention — batch-
    resolved via `contention_forecast_service.contention_states_for_bookings`
    for the whole set the caller is responding with, same rule as `gap` above.
    Required-positional for the same reason: a defaulted equivalent would
    silently render null at every call site nobody remembered to update, which
    is exactly the class of bug B5 shipped with `idle`.
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
    resp.protection_level = req.protection_level
    resp.notes = req.notes
    resp.context_tag = req.context_tag
    resp.custom_fields = req.custom_fields
    resp.environment_group_id = booking.environment_group_id
    resp.environment_group_name = group_name
    # The same projection every EnvBookingSummary site splats as kwargs, applied
    # by assignment because this builder mutates a validated model. One spelling
    # of it, in agreement_gap_service.gap_fields.
    for field, value in agreement_gap_service.gap_fields(gap).items():
        setattr(resp, field, value)
    for field, value in conflict_service.conflict_fields(has_unacknowledged_conflicts).items():
        setattr(resp, field, value)
    resp.contention_state = contention_state
    return resp


async def _gap_for(db, booking, tenant_id: int) -> agreement_gap_service.GapWarning | None:
    """This booking's usage-agreement warning, or None.

    The batch call for a set of one — the four endpoints below respond with
    exactly one booking, and going through the same function as the list means
    a single booking's warning cannot word itself differently from the same
    booking's row in the list.
    """
    return (
        await agreement_gap_service.gap_warnings_for_bookings(db, [booking], tenant_id)
    ).get(booking.id)


async def _has_conflicts_for(db, booking, tenant_id: int) -> bool:
    """Whether this booking has a conflict its owner has not answered.

    The batch call for a set of one, exactly as `_gap_for` above — the four
    endpoints below respond with a single booking, and sharing the list's
    function means a detail read cannot disagree with the same booking's row in
    the list. Never the reverse: this must not be called in a loop over a page.
    """
    return booking.id in await conflict_service.bookings_with_unacknowledged_conflicts(
        db, [booking.id], tenant_id
    )


async def _contention_state_for(db, booking, tenant_id: int, *, now: datetime) -> str | None:
    """This booking's B6 forward-contention state, or None.

    The batch call for a set of one, exactly as `_gap_for`/`_has_conflicts_for`
    above — a single-booking detail read must not disagree with the same
    booking's row in the list, and must not be called in a loop over a page.
    """
    return (
        await contention_forecast_service.contention_states_for_bookings(
            db, tenant_id, [booking.id], now=now,
        )
    ).get(booking.id)


async def _ack_read(db, ack) -> AgreementGapAckRead:
    """Shape an ack ROW for the wire, resolving its author's NAME.

    THE ONLY way to build an `AgreementGapAckRead`: the schema's
    `acknowledged_by_username` is required and an ORM ack has no such attribute,
    so `model_validate(ack)` raises rather than silently sending null — the A1
    failure this codebase has already shipped once.

    Takes a row and returns a model — deliberately NOT `ack | None -> read |
    None`. It is used under `response_model=AgreementGapAckRead`, which is not
    optional, so a None slipping through would surface as a FastAPI
    response-validation 500 naming nothing. Callers that may hold no row (the
    detail read) test for it themselves; `upsert_ack` always returns one, and if
    it ever stops, the error below says so in one line.

    One extra indexed lookup on a detail read, and only when an ack exists.
    """
    if ack is None:
        raise RuntimeError(
            "_ack_read was handed no acknowledgement row: an ack was expected "
            "here and none exists. Callers that may have none must test for it."
        )
    return AgreementGapAckRead(
        notes=ack.notes,
        acknowledged_by=ack.acknowledged_by,
        acknowledged_at=ack.acknowledged_at,
        acknowledged_by_username=await agreement_gap_service.ack_author_username(db, ack),
    )


def _request_summary(req) -> BookingRequestSummary:
    """Compose a BookingRequestSummary from a BookingRequest ORM object."""
    summary = BookingRequestSummary.model_validate(req)
    summary.booked_by_username = req.booker.username if getattr(req, "booker", None) else None
    return summary


@router.get("/", response_model=list[BookingResponse])
async def list_bookings(
    response: Response,
    environment_id: Optional[int] = None,
    start: Optional[datetime] = Query(
        None,
        description="Overlap window start. With `end`, returns bookings whose "
        "own interval overlaps it — NOT bookings that start inside it. "
        "Supplying exactly one of `start`/`end` is a 422.",
    ),
    end: Optional[datetime] = Query(None, description="Overlap window end."),
    booking_status: Optional[str] = None,
    project_id: Optional[int] = Query(None),
    agreement_gap: Optional[bool] = Query(
        None,
        description=(
            "true: only bookings no live usage agreement covers. false: only "
            "those covered, plus those whose request names no project. Omit "
            "for every booking — omission is the 'no selection' sentinel, "
            "deliberately not a third value such as 'all'."
        ),
    ),
    protection: Optional[Literal["soft", "hard"]] = Query(
        None,
        description=(
            "Only bookings whose request declares this protection level. "
            "OMIT the key for no filter — an empty value is a 422, not an "
            "ignored param."
        ),
    ),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(BOOKING_SORTS, default="start_date")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if (start is None) != (end is None):
        # A half-specified range is far more likely a caller bug than an
        # intent to filter on an open-ended window — silently ignoring it
        # (FastAPI's default for an unrecognised param) is the exact failure
        # this filter exists to close, so treat a half-specified one the
        # same way.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start and end must both be supplied, or neither.",
        )
    now = datetime.now(timezone.utc)
    bookings, total, contention_states = await booking_service.list_bookings(
        db,
        current_user.active_tenant_id,
        environment_id=environment_id,
        start=start,
        end=end,
        booking_status=booking_status,
        project_id=project_id,
        agreement_gap=agreement_gap,
        protection=protection,
        page=page,
        sort=sort,
        now=now,
    )
    set_total_count(response, total)
    names = await project_service.get_project_names(
        db, {b.booking_request.project_id for b in bookings}, current_user.active_tenant_id
    )
    group_names = await environment_group_service.get_group_names(
        db, {b.environment_group_id for b in bookings}, current_user.active_tenant_id
    )
    # Once for the page, never once per row — see _to_response. The conflict
    # flag beside it used to be the counter-example: it ran
    # `has_unacknowledged_conflicts` inside this loop, which is `list_conflicts`
    # plus one ack lookup PER CONFLICT, so a 50-row page cost 50 x (1 +
    # conflicts) queries and got worse the busier the estate was.
    gaps = await agreement_gap_service.gap_warnings_for_bookings(
        db, bookings, current_user.active_tenant_id
    )
    conflicts = await conflict_service.bookings_with_unacknowledged_conflicts(
        db, [b.id for b in bookings], current_user.active_tenant_id
    )
    return [
        _to_response(
            b,
            names.get(b.booking_request.project_id),
            group_names.get(b.environment_group_id),
            gaps.get(b.id),
            b.id in conflicts,
            contention_states.get(b.id),
        )
        for b in bookings
    ]


@router.post("/", response_model=BookingCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    data: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    booking, warnings = await booking_service.create_booking(db, data, current_user, now=now)
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    group_names = await environment_group_service.get_group_names(
        db, {booking.environment_group_id}, current_user.active_tenant_id
    )
    return BookingCreateResponse(
        booking=_to_response(
            booking,
            names.get(booking.booking_request.project_id),
            group_names.get(booking.environment_group_id),
            await _gap_for(db, booking, current_user.active_tenant_id),
            await _has_conflicts_for(db, booking, current_user.active_tenant_id),
            await _contention_state_for(db, booking, current_user.active_tenant_id, now=now),
        ),
        overlap_warnings=warnings,
    )


@router.get("/contention-horizon")
async def get_contention_horizon(
    weeks: int = Query(6, ge=1, le=104),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """B6 — the leading-indicator count: "N contentions in the next N weeks".

    READ-ONLY, like the rest of B6. Registered ahead of `/{booking_id}` so it
    is never shadowed by that route.
    """
    now = datetime.now(timezone.utc)
    start = now
    end = now + timedelta(weeks=weeks)
    count = await contention_forecast_service.contention_count_in_window(
        db, current_user.active_tenant_id, start=start, end=end
    )
    return {"count": count, "weeks": weeks}


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.get_booking(db, booking_id, current_user.active_tenant_id)
    now = datetime.now(timezone.utc)
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    group_names = await environment_group_service.get_group_names(
        db, {booking.environment_group_id}, current_user.active_tenant_id
    )
    resp = _to_response(
        booking,
        names.get(booking.booking_request.project_id),
        group_names.get(booking.environment_group_id),
        await _gap_for(db, booking, current_user.active_tenant_id),
        await _has_conflicts_for(db, booking, current_user.active_tenant_id),
        await _contention_state_for(db, booking, current_user.active_tenant_id, now=now),
    )
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    # Who accepted this booking's gap, and when — the detail read ONLY (see
    # BookingResponse.agreement_gap_ack). Tenant-filtered by `get_ack`: a
    # malformed row bearing another tenant's tenant_id must not be read back as
    # ours, and `test_another_tenants_ack_row_is_never_read_back_as_ours` fails
    # without that filter.
    ack = await agreement_gap_service.get_ack(db, booking.id, current_user.active_tenant_id)
    resp.agreement_gap_ack = await _ack_read(db, ack) if ack is not None else None
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
    now = datetime.now(timezone.utc)
    booking = await booking_service.update_standard_fields(
        db, booking_id, values, current_user, now=now
    )
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    group_names = await environment_group_service.get_group_names(
        db, {booking.environment_group_id}, current_user.active_tenant_id
    )
    resp = _to_response(
        booking,
        names.get(booking.booking_request.project_id),
        group_names.get(booking.environment_group_id),
        await _gap_for(db, booking, current_user.active_tenant_id),
        await _has_conflicts_for(db, booking, current_user.active_tenant_id),
        await _contention_state_for(db, booking, current_user.active_tenant_id, now=now),
    )
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
    now = datetime.now(timezone.utc)
    names = await project_service.get_project_names(
        db, {booking.booking_request.project_id}, current_user.active_tenant_id
    )
    group_names = await environment_group_service.get_group_names(
        db, {booking.environment_group_id}, current_user.active_tenant_id
    )
    return _to_response(
        booking,
        names.get(booking.booking_request.project_id),
        group_names.get(booking.environment_group_id),
        await _gap_for(db, booking, current_user.active_tenant_id),
        await _has_conflicts_for(db, booking, current_user.active_tenant_id),
        await _contention_state_for(db, booking, current_user.active_tenant_id, now=now),
    )


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


@router.put("/{booking_id}/agreement-gap/ack", response_model=AgreementGapAckRead)
async def ack_agreement_gap(
    booking_id: int,
    data: AgreementGapAckUpsert,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Acknowledge this booking's usage-agreement gap.

    Open to any tenant member, deliberately: a gap is a governance finding, not
    a message between bookers (see agreement_gap_service.upsert_ack). The gap
    itself is never written — only the acknowledgement is.
    """
    ack = await agreement_gap_service.upsert_ack(
        db, booking_id, notes=data.notes,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    # Same shape as `GET /bookings/{id}`'s `agreement_gap_ack`, from the same
    # builder: the panel holds this answer in local state until the page
    # refetches, so a name on one and not the other would name the acknowledger
    # in this session and not the next.
    return await _ack_read(db, ack)


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
