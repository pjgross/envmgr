from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, fetch_page
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.change_request import ChangeRequest, ChangeRequestEnvironment
from app.db.models.environment import Environment
from app.db.models.environment_health import EnvironmentHealthStatus

STALE_AFTER = timedelta(minutes=15)
# Booking statuses that are NOT a live claim on an environment: draft (uncommitted) plus
# the two terminal states (rejected, closed). The booking lifecycle has no "cancelled" state;
# this mirrors conflict_service.TERMINAL_STATES ({rejected, closed}) plus draft.
INACTIVE_BOOKING_STATUSES = {"draft", "rejected", "closed"}
INACTIVE_CR_STATUSES = {"cancelled", "rejected"}


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def record_sample(db: AsyncSession, tenant_id: int, environment_id: int,
                        status: str, source: str, detail: Optional[str] = None,
                        recorded_at: Optional[datetime] = None) -> EnvironmentHealthStatus:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id, Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if env is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Environment not found")
    row = EnvironmentHealthStatus(
        tenant_id=tenant_id, environment_id=environment_id, status=status, source=source,
        detail=detail, recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


async def get_history(db: AsyncSession, tenant_id: int, environment_id: int, limit: int = 50):
    limit = max(1, min(limit, 500))
    return list((await db.execute(
        select(EnvironmentHealthStatus).where(
            EnvironmentHealthStatus.tenant_id == tenant_id,
            EnvironmentHealthStatus.environment_id == environment_id,
        ).order_by(EnvironmentHealthStatus.recorded_at.desc()).limit(limit)
    )).scalars().all())


async def _latest(db, tenant_id, environment_id) -> Optional[EnvironmentHealthStatus]:
    return (await db.execute(
        select(EnvironmentHealthStatus).where(
            EnvironmentHealthStatus.tenant_id == tenant_id,
            EnvironmentHealthStatus.environment_id == environment_id,
        ).order_by(EnvironmentHealthStatus.recorded_at.desc()).limit(1)
    )).scalars().first()


def _derive_status(latest: Optional[EnvironmentHealthStatus], now: datetime):
    if latest is None:
        return "unknown", None
    rec = _utc(latest.recorded_at)
    if now - rec > STALE_AFTER:
        return "unknown", rec
    return latest.status, rec


async def health_overview(
    db: AsyncSession,
    tenant_id: int,
    now: Optional[datetime] = None,
    page: Optional[Page] = None,
) -> tuple[list[dict], int]:
    now = now or datetime.now(timezone.utc)
    query = select(Environment).where(
        Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
        Environment.status != "decommissioned",
    ).order_by(Environment.name.asc(), Environment.id)
    envs, total = await fetch_page(db, query, page)
    rows = []
    for env in envs:
        current, last_at = _derive_status(await _latest(db, tenant_id, env.id), now)
        booking = await _active_booking(db, tenant_id, env.id, now)
        outage = await _planned_outage(db, tenant_id, env.id, now)
        alert = current in ("down", "issue") and booking is not None and not outage
        rows.append({
            "environment_id": env.id, "environment_name": env.name,
            "current_status": current, "last_recorded_at": last_at,
            "active_booking": booking is not None, "active_booking_summary": booking,
            "planned_outage": outage, "alert": alert,
        })
    return rows, total


async def _active_booking(db, tenant_id, environment_id, now):
    """Return a booking-summary dict if there is an active (status not in
    INACTIVE_BOOKING_STATUSES = draft/rejected/closed) booking whose window covers `now`,
    otherwise None.
    Joins BookingRequest to retrieve the project_name."""
    rows = (await db.execute(
        select(Booking, BookingRequest)
        .outerjoin(BookingRequest, and_(
            BookingRequest.id == Booking.booking_request_id,
            BookingRequest.tenant_id == tenant_id,
            BookingRequest.deleted_at.is_(None),
        ))
        .where(
            Booking.tenant_id == tenant_id,
            Booking.environment_id == environment_id,
            Booking.deleted_at.is_(None),
        )
    )).all()
    for booking, req in rows:
        if booking.status in INACTIVE_BOOKING_STATUSES:
            continue
        start, end = _utc(booking.start_date), _utc(booking.end_date)
        if start and end and start <= now <= end:
            return {
                "project_name": req.project_name if req else "Booking",
                "start_date": start,
                "end_date": end,
            }
    return None


async def _planned_outage(db, tenant_id, environment_id, now):
    """Return True if there is a non-cancelled/rejected ChangeRequest with has_outage=True
    linked to environment_id whose outage window (falling back to scheduled window) covers `now`."""
    rows = (await db.execute(
        select(ChangeRequest)
        .join(ChangeRequestEnvironment, ChangeRequestEnvironment.change_request_id == ChangeRequest.id)
        .where(
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequestEnvironment.environment_id == environment_id,
            ChangeRequestEnvironment.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
            ChangeRequest.has_outage.is_(True),
        )
    )).scalars().all()
    for cr in rows:
        if cr.status in INACTIVE_CR_STATUSES:
            continue
        start = _utc(cr.outage_start) or _utc(cr.scheduled_start)
        end = _utc(cr.outage_end) or _utc(cr.scheduled_end)
        if start and end and start <= now <= end:
            return True
    return False
