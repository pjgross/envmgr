from typing import Any
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest
from app.db.models.booking_lifecycle import BookingType, BookingLifecycleTemplate
from app.db.models.environment import Environment
from app.db.models.user import User
from app.services import conflict_service


async def _load_initial_state(db: AsyncSession, booking_type_id: int, tenant_id: int) -> str:
    bt = (await db.execute(
        select(BookingType).where(
            BookingType.id == booking_type_id,
            BookingType.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if bt is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown booking_type_id")
    tpl = (await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.id == bt.lifecycle_template_id
        )
    )).scalar_one()
    for s in tpl.definition.get("states", []):
        if s.get("is_initial"):
            return s["key"]
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lifecycle has no initial state")


async def create_request(
    db: AsyncSession,
    data: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> tuple[BookingRequest, dict[int, list[Booking]]]:
    env_ids: list[int] = data["environment_ids"]
    if not env_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "At least one environment_id is required"
        )
    if len(env_ids) != len(set(env_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "environment_ids must be unique"
        )

    envs = (await db.execute(
        select(Environment).where(
            Environment.id.in_(env_ids),
            Environment.tenant_id == tenant_id,
        )
    )).scalars().all()
    if len(envs) != len(env_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "One or more environment_ids not found"
        )

    initial_state = await _load_initial_state(db, data["booking_type_id"], tenant_id)

    req = BookingRequest(
        tenant_id=tenant_id,
        project_name=data["project_name"],
        booking_type_id=data["booking_type_id"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        notes=data.get("notes"),
        context_tag=ContextTag(data.get("context_tag", "none")),
        exclusive_use_requested=data.get("exclusive_use_requested", False),
        custom_fields=data.get("custom_fields"),
        booked_by=current_user.id,
        delegate_user_ids=data.get("delegate_user_ids"),
    )
    db.add(req)
    await db.flush()

    children: list[Booking] = []
    for env_id in env_ids:
        child = Booking(
            tenant_id=tenant_id,
            booking_request_id=req.id,
            environment_id=env_id,
            start_date=data["start_date"],
            end_date=data["end_date"],
            status=initial_state,
        )
        db.add(child)
        children.append(child)
    await db.flush()

    detected: dict[int, list[Booking]] = {}
    for c in children:
        others = await conflict_service.list_conflicts(db, c.id, tenant_id)
        if others:
            detected[c.id] = others

    await publish_event(
        db,
        event_type="BookingRequestCreated",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "child_ids": [c.id for c in children]},
        tenant_id=tenant_id,
    )
    # Eagerly load the bookings relationship so callers (and tests) can access
    # req.bookings without triggering async lazy-load outside a greenlet.
    await db.refresh(req, ["bookings"])
    return req, detected


async def preview_conflicts(
    db: AsyncSession,
    *,
    environment_ids: list[int],
    start_date: datetime,
    end_date: datetime,
    tenant_id: int,
) -> dict[int, list[Booking]]:
    """Return a dict keyed by environment_id listing existing bookings that would overlap.
    No database mutation."""
    from sqlalchemy import not_
    results: dict[int, list[Booking]] = {}
    for env_id in environment_ids:
        stmt = (
            select(Booking)
            .where(
                Booking.tenant_id == tenant_id,
                Booking.environment_id == env_id,
                Booking.deleted_at.is_(None),
                not_(Booking.status.in_(conflict_service.TERMINAL_STATES)),
                Booking.start_date < end_date,
                Booking.end_date > start_date,
            )
            .order_by(Booking.start_date)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if rows:
            results[env_id] = list(rows)
    return results


async def _get_request(db: AsyncSession, request_id: int, tenant_id: int) -> BookingRequest:
    req = (await db.execute(
        select(BookingRequest).where(
            BookingRequest.id == request_id, BookingRequest.tenant_id == tenant_id
        )
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


async def add_environment(
    db: AsyncSession,
    *,
    request_id: int,
    environment_id: int,
    start_date: datetime | None,
    end_date: datetime | None,
    current_user: User,
    tenant_id: int,
) -> Booking:
    req = await _get_request(db, request_id, tenant_id)

    env = (await db.execute(
        select(Environment).where(Environment.id == environment_id, Environment.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    # Reject if env already has a non-deleted child in this request
    existing = (await db.execute(
        select(Booking).where(
            Booking.booking_request_id == req.id,
            Booking.environment_id == environment_id,
            Booking.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Environment already in request")

    initial_state = await _load_initial_state(db, req.booking_type_id, tenant_id)

    child = Booking(
        tenant_id=tenant_id,
        booking_request_id=req.id,
        environment_id=environment_id,
        start_date=start_date or req.start_date,
        end_date=end_date or req.end_date,
        status=initial_state,
    )
    db.add(child)
    await db.flush()

    await publish_event(
        db,
        event_type="BookingEnvironmentAdded",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "booking_id": child.id, "environment_id": environment_id},
        tenant_id=tenant_id,
    )
    return child


async def remove_environment(
    db: AsyncSession,
    *,
    request_id: int,
    booking_id: int,
    current_user: User,
    tenant_id: int,
) -> None:
    req = await _get_request(db, request_id, tenant_id)
    child = (await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.booking_request_id == req.id,
            Booking.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if child is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment booking not found in request")

    child.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="BookingEnvironmentRemoved",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "booking_id": child.id},
        tenant_id=tenant_id,
    )


# Fields editable at the request level — must match the spec's PATCH endpoint
STANDARD_REQUEST_FIELDS = {
    "project_name",
    "booking_type_id",
    "start_date",
    "end_date",
    "notes",
    "context_tag",
    "exclusive_use_requested",
    "delegate_user_ids",
}


async def update_standard_fields(
    db: AsyncSession,
    *,
    request_id: int,
    values: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> BookingRequest:
    req = await _get_request(db, request_id, tenant_id)
    unknown = set(values) - STANDARD_REQUEST_FIELDS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown fields: {unknown}")

    # TODO permission gating using lifecycle field_permissions —
    # follow the same check used in booking_service.update_standard_fields today.
    # For now we allow the request owner to edit any standard field; sharpen in Task 16 once
    # the API wires permission checks.

    for k, v in values.items():
        if k == "context_tag" and v is not None:
            setattr(req, k, ContextTag(v))
        else:
            setattr(req, k, v)

    # Cascade start_date/end_date overrides to child Bookings so per-env dates stay in sync.
    if "start_date" in values or "end_date" in values:
        children = (await db.execute(
            select(Booking).where(
                Booking.booking_request_id == req.id, Booking.deleted_at.is_(None)
            )
        )).scalars().all()
        for child in children:
            if "start_date" in values:
                child.start_date = values["start_date"]
            if "end_date" in values:
                child.end_date = values["end_date"]
    await db.flush()

    await publish_event(
        db,
        event_type="BookingRequestUpdated",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "fields": list(values.keys())},
        tenant_id=tenant_id,
    )

    # Eagerly load the bookings relationship so callers (and tests) can access
    # req.bookings without triggering async lazy-load outside a greenlet.
    await db.refresh(req, ["bookings"])
    return req


async def update_custom_fields(
    db: AsyncSession,
    *,
    request_id: int,
    values: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> BookingRequest:
    req = await _get_request(db, request_id, tenant_id)
    req.custom_fields = values
    await db.flush()

    # Eagerly load the bookings relationship so callers (and tests) can access
    # req.bookings without triggering async lazy-load outside a greenlet.
    await db.refresh(req, ["bookings"])
    return req
