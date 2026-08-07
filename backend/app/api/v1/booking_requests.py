from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.pagination import Page, pagination, set_total_count
from app.core.security import get_current_user
from app.services import (
    booking_service, booking_request_service, environment_group_service,
    environment_service, project_service,
)
from app.api.v1.bookings import _to_response as _booking_to_response
from app.api.v1.schemas.booking import (
    BookingResponse, BookingTransitionRequest, AllowedTransitionResponse,
)
from app.api.v1.schemas.booking_request import (
    BookingRequestCreate, BookingRequestCreateResponse, BookingRequestResponse,
    BookingRequestUpdate, BookingRequestCustomFieldsUpdate,
    AddEnvironmentRequest, EnvBookingSummary,
    PreviewConflictsRequest, PreviewConflictsResponse,
)

router = APIRouter(prefix="/booking-requests", tags=["booking-requests"])


def _summaries(
    children, group_names: dict[int, str], env_names: dict[int, str]
) -> list[EnvBookingSummary]:
    # Basic projection — has_unacknowledged_conflicts is filled in by the
    # caller for the detail endpoint.
    #
    # `group_names` is a batch-resolved id->name map (see
    # environment_group_service.get_group_names, deliberately not filtering
    # deleted_at so an archived group still renders on the bookings made
    # against it). `env_names` is the same pattern via
    # environment_service.get_environment_names — a booking against a
    # soft-deleted environment must still render that environment's name.
    # Both required-positional, not defaulted: a missing arg here must raise
    # loudly rather than silently render every name as null, the same reason
    # bookings.py's _to_response is required-positional.
    return [
        EnvBookingSummary(
            id=c.id,
            environment_id=c.environment_id,
            environment_name=env_names.get(c.environment_id),
            start_date=c.start_date,
            end_date=c.end_date,
            status=c.status,
            environment_group_id=c.environment_group_id,
            environment_group_name=group_names.get(c.environment_group_id),
        )
        for c in children if c.deleted_at is None
    ]


def _rollup(children) -> str:
    active = [c for c in children if c.deleted_at is None]
    if not active:
        return "empty"
    statuses = {c.status for c in active}
    if statuses == {"approved"}:
        return "all_approved"
    if statuses == {"rejected"}:
        return "all_rejected"
    if len(statuses) == 1:
        return active[0].status
    terminals = {"approved", "rejected", "closed"}
    if statuses.issubset(terminals):
        return "mixed"
    return "mixed"


def _to_response(
    req, project_name_link: str | None,
    group_names: dict[int, str], env_names: dict[int, str],
) -> BookingRequestResponse:
    """`group_names` and `env_names` are required-positional, not defaulted —
    see _summaries."""
    return BookingRequestResponse(
        id=req.id, tenant_id=req.tenant_id, project_name=req.project_name,
        project_id=req.project_id, project_name_link=project_name_link,
        booking_type_id=req.booking_type_id, start_date=req.start_date, end_date=req.end_date,
        notes=req.notes, context_tag=req.context_tag.value if hasattr(req.context_tag, "value") else req.context_tag,
        exclusive_use_requested=req.exclusive_use_requested, custom_fields=req.custom_fields,
        booked_by=req.booked_by, delegate_user_ids=req.delegate_user_ids,
        rollup_status=_rollup(req.bookings),
        bookings=_summaries(req.bookings, group_names, env_names),
    )


async def _group_names_for(db: AsyncSession, requests, tenant_id: int) -> dict[int, str]:
    """Batch-resolve group names for every child booking across one or more
    BookingRequest ORM objects (their .bookings must already be loaded)."""
    ids = {
        c.environment_group_id
        for req in requests
        for c in req.bookings
        if c.environment_group_id is not None
    }
    return await environment_group_service.get_group_names(db, ids, tenant_id)


async def _env_names_for(db: AsyncSession, requests, tenant_id: int) -> dict[int, str]:
    """Batch-resolve environment names for every child booking across one or
    more BookingRequest ORM objects (their .bookings must already be
    loaded) — the environment_id counterpart to `_group_names_for`."""
    ids = {
        c.environment_id
        for req in requests
        for c in req.bookings
    }
    return await environment_service.get_environment_names(db, ids, tenant_id)


@router.post("", response_model=BookingRequestCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_booking_request(
    data: BookingRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    req, detected = await booking_request_service.create_request(
        db, data=data.model_dump(), current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    await db.refresh(req, attribute_names=["bookings"])
    names = await project_service.get_project_names(db, {req.project_id}, current_user.active_tenant_id)
    group_names = await environment_group_service.get_group_names(
        db,
        {c.environment_group_id for c in req.bookings if c.environment_group_id is not None}
        | {c.booking.environment_group_id for v in detected.values() for c in v
           if c.booking.environment_group_id is not None},
        current_user.active_tenant_id,
    )
    env_names = await _env_names_for(db, [req], current_user.active_tenant_id)
    return BookingRequestCreateResponse(
        request=_to_response(req, names.get(req.project_id), group_names, env_names),
        detected_conflicts={
            k: [EnvBookingSummary(
                    id=c.booking.id,
                    environment_id=c.booking.environment_id,
                    environment_name=c.environment_name,
                    project_name=c.project_name,
                    start_date=c.booking.start_date,
                    end_date=c.booking.end_date,
                    status=c.booking.status,
                    environment_group_id=c.booking.environment_group_id,
                    environment_group_name=group_names.get(c.booking.environment_group_id),
                ) for c in v]
            for k, v in detected.items()
        },
    )


@router.post("/preview-conflicts", response_model=PreviewConflictsResponse)
async def preview_conflicts(
    data: PreviewConflictsRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    conflicts = await booking_request_service.preview_conflicts(
        db, environment_ids=data.environment_ids,
        start_date=data.start_date, end_date=data.end_date,
        tenant_id=current_user.active_tenant_id,
    )
    group_names = await environment_group_service.get_group_names(
        db,
        {b.environment_group_id for v in conflicts.values() for b in v
         if b.environment_group_id is not None},
        current_user.active_tenant_id,
    )
    # Finding 7 (A2 whole-branch review): this endpoint builds EnvBookingSummary
    # directly rather than via `_summaries`, which is what left it the one
    # construction site (of three the review checked) still leaving
    # environment_name null — a `#N` fallback in the UI. Resolved the same
    # way `_summaries`/`_env_names_for` do, via the batch lookup this sits
    # right next to.
    env_names = await environment_service.get_environment_names(
        db,
        {b.environment_id for v in conflicts.values() for b in v},
        current_user.active_tenant_id,
    )
    return PreviewConflictsResponse(
        conflicts={
            k: [EnvBookingSummary(
                    id=b.id, environment_id=b.environment_id,
                    environment_name=env_names.get(b.environment_id),
                    start_date=b.start_date, end_date=b.end_date, status=b.status,
                    environment_group_id=b.environment_group_id,
                    environment_group_name=group_names.get(b.environment_group_id),
                ) for b in v]
            for k, v in conflicts.items()
        }
    )


@router.get("", response_model=list[BookingRequestResponse])
async def list_booking_requests(
    response: Response,
    project_id: Optional[int] = Query(None),
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    rows, total = await booking_request_service.list_booking_requests(
        db, current_user.active_tenant_id, page=page, project_id=project_id
    )
    set_total_count(response, total)
    names = await project_service.get_project_names(
        db, {r.project_id for r in rows}, current_user.active_tenant_id
    )
    group_names = await _group_names_for(db, rows, current_user.active_tenant_id)
    env_names = await _env_names_for(db, rows, current_user.active_tenant_id)
    return [_to_response(r, names.get(r.project_id), group_names, env_names) for r in rows]


@router.get("/{request_id}", response_model=BookingRequestResponse)
async def get_booking_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    req = await booking_request_service._get_request(db, request_id, current_user.active_tenant_id)
    await db.refresh(req, attribute_names=["bookings"])
    names = await project_service.get_project_names(db, {req.project_id}, current_user.active_tenant_id)
    group_names = await _group_names_for(db, [req], current_user.active_tenant_id)
    env_names = await _env_names_for(db, [req], current_user.active_tenant_id)
    return _to_response(req, names.get(req.project_id), group_names, env_names)


@router.patch("/{request_id}/standard-fields", response_model=BookingRequestResponse)
async def update_request_standard_fields(
    request_id: int,
    data: BookingRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    values = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k in data.model_fields_set}
    req = await booking_request_service.update_standard_fields(
        db, request_id=request_id, values=values,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    await db.refresh(req, attribute_names=["bookings"])
    names = await project_service.get_project_names(db, {req.project_id}, current_user.active_tenant_id)
    group_names = await _group_names_for(db, [req], current_user.active_tenant_id)
    env_names = await _env_names_for(db, [req], current_user.active_tenant_id)
    return _to_response(req, names.get(req.project_id), group_names, env_names)


@router.patch("/{request_id}/custom-fields", response_model=BookingRequestResponse)
async def update_request_custom_fields(
    request_id: int,
    data: BookingRequestCustomFieldsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    req = await booking_request_service.update_custom_fields(
        db, request_id=request_id, values=data.values,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    await db.refresh(req, attribute_names=["bookings"])
    names = await project_service.get_project_names(db, {req.project_id}, current_user.active_tenant_id)
    group_names = await _group_names_for(db, [req], current_user.active_tenant_id)
    env_names = await _env_names_for(db, [req], current_user.active_tenant_id)
    return _to_response(req, names.get(req.project_id), group_names, env_names)


@router.post("/{request_id}/environments", response_model=EnvBookingSummary, status_code=status.HTTP_201_CREATED)
async def add_environment_to_request(
    request_id: int,
    data: AddEnvironmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    child = await booking_request_service.add_environment(
        db, request_id=request_id, environment_id=data.environment_id,
        start_date=data.start_date, end_date=data.end_date,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    return EnvBookingSummary(
        id=child.id, environment_id=child.environment_id,
        start_date=child.start_date, end_date=child.end_date, status=child.status,
    )


@router.delete("/{request_id}/environments/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_environment_from_request(
    request_id: int,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    await booking_request_service.remove_environment(
        db, request_id=request_id, booking_id=booking_id,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )


@router.post(
    "/{request_id}/groups/{group_id}/transition",
    response_model=list[BookingResponse],
)
async def transition_group_bookings(
    request_id: int,
    group_id: int,
    data: BookingTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Move every member of this group booking, or none of them.

    `POST /bookings/{id}/transition` keeps its exact current meaning and
    stays available for a group member — it is the only repair tool when
    members diverge.
    """
    bookings = await booking_service.transition_group(
        db, request_id, group_id, data.to_state, current_user, data.notes
    )
    names = await project_service.get_project_names(
        db, {b.booking_request.project_id for b in bookings}, current_user.active_tenant_id
    )
    group_names = await environment_group_service.get_group_names(
        db, {b.environment_group_id for b in bookings}, current_user.active_tenant_id
    )
    return [
        _booking_to_response(
            b, names.get(b.booking_request.project_id), group_names.get(b.environment_group_id)
        )
        for b in bookings
    ]


@router.get(
    "/{request_id}/groups/{group_id}/allowed-transitions",
    response_model=list[AllowedTransitionResponse],
)
async def get_group_allowed_transitions_route(
    request_id: int,
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """The INTERSECTION of what every member allows — the endpoint the
    group's UI buttons come from."""
    return await booking_service.get_group_allowed_transitions(
        db, request_id, group_id, current_user
    )
