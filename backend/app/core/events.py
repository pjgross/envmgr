"""Outbox event publishing helpers."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.event_log import EventLog


async def publish_event(
    db: AsyncSession,
    event_type: str,
    aggregate_id: int,
    aggregate_type: str,
    payload: dict,
    tenant_id: int,
) -> EventLog:
    """
    Create an EventLog row in the current transaction (unpublished).

    The caller's transaction (get_db auto-commit) handles the commit atomically.
    DO NOT commit here.
    """
    event = EventLog(
        event_type=event_type,
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        payload=payload,
        tenant_id=tenant_id,
        published_at=None,
    )
    db.add(event)
    return event
