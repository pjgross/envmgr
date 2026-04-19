"""Release event service — event type CRUD with system-type protection + event list/create.

System event types (is_system=True):
- Cannot be renamed (only display_color may change).
- Cannot be deleted.

Helpers used by other services:
- find_system_event_type(db, tenant_id, name) -> ReleaseEventType | None
- record_auto_event(db, release_id, tenant_id, user_id, event_type_name, description) -> ReleaseEvent | None
Never calls db.commit().
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.api.v1.schemas.release_event import (
    ReleaseEventCreate,
    ReleaseEventTypeCreate,
    ReleaseEventTypeUpdate,
)


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _get_event_type(
    db: AsyncSession, type_id: int, tenant_id: int
) -> ReleaseEventType:
    et = (
        await db.execute(
            select(ReleaseEventType).where(
                ReleaseEventType.id == type_id,
                ReleaseEventType.tenant_id == tenant_id,
                ReleaseEventType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if et is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release event type not found")
    return et


# ── Event types ───────────────────────────────────────────────────────────────

async def list_event_types(
    db: AsyncSession,
    tenant_id: int,
) -> list[ReleaseEventType]:
    rows = (
        await db.execute(
            select(ReleaseEventType).where(
                ReleaseEventType.tenant_id == tenant_id,
                ReleaseEventType.deleted_at.is_(None),
            ).order_by(ReleaseEventType.name)
        )
    ).scalars().all()
    return list(rows)


async def create_event_type(
    db: AsyncSession,
    data: ReleaseEventTypeCreate,
    tenant_id: int,
) -> ReleaseEventType:
    et = ReleaseEventType(
        tenant_id=tenant_id,
        name=data.name,
        display_color=data.display_color,
        is_system=False,
    )
    db.add(et)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseEventTypeCreated",
        aggregate_id=et.id,
        aggregate_type="ReleaseEventType",
        payload={"id": et.id, "name": et.name},
        tenant_id=tenant_id,
    )
    return et


async def update_event_type(
    db: AsyncSession,
    type_id: int,
    data: ReleaseEventTypeUpdate,
    tenant_id: int,
) -> ReleaseEventType:
    et = await _get_event_type(db, type_id, tenant_id)

    # System event types cannot be renamed
    if et.is_system and data.name is not None and data.name != et.name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "System event types cannot be renamed",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(et, field, value)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseEventTypeUpdated",
        aggregate_id=et.id,
        aggregate_type="ReleaseEventType",
        payload={"id": et.id, "name": et.name},
        tenant_id=tenant_id,
    )
    return et


async def delete_event_type(
    db: AsyncSession,
    type_id: int,
    tenant_id: int,
) -> None:
    et = await _get_event_type(db, type_id, tenant_id)

    if et.is_system:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "System event types cannot be deleted",
        )

    et.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseEventTypeDeleted",
        aggregate_id=et.id,
        aggregate_type="ReleaseEventType",
        payload={"id": et.id, "name": et.name},
        tenant_id=tenant_id,
    )


# ── Events ────────────────────────────────────────────────────────────────────

async def list_events(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[ReleaseEvent]:
    rows = (
        await db.execute(
            select(ReleaseEvent).where(
                ReleaseEvent.release_id == release_id,
                ReleaseEvent.tenant_id == tenant_id,
            ).order_by(ReleaseEvent.occurred_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def create_event(
    db: AsyncSession,
    release_id: int,
    data: ReleaseEventCreate,
    tenant_id: int,
    user_id: int,
) -> ReleaseEvent:
    occurred_at = data.occurred_at or datetime.now(timezone.utc)
    event = ReleaseEvent(
        tenant_id=tenant_id,
        release_id=release_id,
        event_type_id=data.event_type_id,
        description=data.description,
        occurred_at=occurred_at,
        recorded_by=user_id,
    )
    db.add(event)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseEventRecorded",
        aggregate_id=event.id,
        aggregate_type="ReleaseEvent",
        payload={
            "id": event.id,
            "release_id": release_id,
            "event_type_id": data.event_type_id,
            "recorded_by": user_id,
        },
        tenant_id=tenant_id,
    )
    return event


# ── Helpers for other services ────────────────────────────────────────────────

async def find_system_event_type(
    db: AsyncSession,
    tenant_id: int,
    name: str,
) -> Optional[ReleaseEventType]:
    """Look up a *system* event type by name. Returns None if not found.

    Filters on is_system=True so a user-renamed or user-created type with a
    colliding name won't be treated as the canonical 'Reschedule Reason' etc.
    """
    return (
        await db.execute(
            select(ReleaseEventType).where(
                ReleaseEventType.tenant_id == tenant_id,
                ReleaseEventType.name == name,
                ReleaseEventType.is_system.is_(True),
                ReleaseEventType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def record_auto_event(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    user_id: int,
    event_type_name: str,
    description: str,
) -> Optional[ReleaseEvent]:
    """Convenience: look up the system event type by name and write the event.

    Returns None if the event type doesn't exist (caller decides whether to raise).
    """
    et = await find_system_event_type(db, tenant_id, event_type_name)
    if et is None:
        return None

    event = ReleaseEvent(
        tenant_id=tenant_id,
        release_id=release_id,
        event_type_id=et.id,
        description=description,
        occurred_at=datetime.now(timezone.utc),
        recorded_by=user_id,
    )
    db.add(event)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseEventRecorded",
        aggregate_id=event.id,
        aggregate_type="ReleaseEvent",
        payload={
            "id": event.id,
            "release_id": release_id,
            "event_type_id": et.id,
            "recorded_by": user_id,
        },
        tenant_id=tenant_id,
    )
    return event
