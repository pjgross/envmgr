from typing import Any

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
            project_name=data["project_name"],  # dual-write during migration window
            booked_by=current_user.id,
            start_date=data["start_date"],
            end_date=data["end_date"],
            exclusive_use=data.get("exclusive_use_requested", False),
            booking_type_id=data["booking_type_id"],
            status=initial_state,
            notes=data.get("notes"),
            context_tag=ContextTag(data.get("context_tag", "none")),
            custom_fields=data.get("custom_fields"),
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
