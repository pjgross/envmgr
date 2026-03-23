from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from dateutil.rrule import rrulestr
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.booking import Booking, BookingType, BookingStatus, ContextTag
from app.api.v1.schemas.booking import BookingCreate
from app.core.events import publish_event


@dataclass
class OverlapResult:
    blocked: bool
    conflicts: list[int] = field(default_factory=list)
    warnings: list[int] = field(default_factory=list)


async def check_overlap(
    db: AsyncSession,
    env_id: int,
    start: datetime,
    end: datetime,
    tenant_id: int,
    booking_type: BookingType,
    exclude_id: Optional[int] = None,
) -> OverlapResult:
    """
    Find bookings that overlap with [start, end] for this environment.
    Overlap condition: existing.start_date < end AND existing.end_date > start
    """
    query = select(Booking).where(
        Booking.environment_id == env_id,
        Booking.tenant_id == tenant_id,
        Booking.deleted_at.is_(None),
        Booking.status != BookingStatus.REJECTED,
        Booking.start_date < end,
        Booking.end_date > start,
    )
    if exclude_id is not None:
        query = query.where(Booking.id != exclude_id)

    result = await db.execute(query)
    overlapping = list(result.scalars().all())

    if not overlapping:
        return OverlapResult(blocked=False)

    # If new booking is EXCLUSIVE or any existing is EXCLUSIVE → blocked
    has_exclusive = booking_type == BookingType.EXCLUSIVE or any(
        b.booking_type == BookingType.EXCLUSIVE for b in overlapping
    )

    if has_exclusive:
        return OverlapResult(
            blocked=True,
            conflicts=[b.id for b in overlapping],
        )

    # All SHARED — not blocked, just warnings
    return OverlapResult(
        blocked=False,
        warnings=[b.id for b in overlapping],
    )


async def create_booking(
    db: AsyncSession, data: BookingCreate, current_user
) -> tuple[Booking, list[int]]:
    """
    Returns (parent_booking, overlap_warnings_list).
    Raises 409 if exclusive conflict exists.
    """
    overlap = await check_overlap(
        db,
        data.environment_id,
        data.start_date,
        data.end_date,
        current_user.active_tenant_id,
        data.booking_type,
    )
    if overlap.blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Exclusive booking conflict",
                "conflicts": overlap.conflicts,
            },
        )

    # Determine context_tag
    if data.context_tag is not None and data.context_tag != ContextTag.NONE:
        ctx = data.context_tag
    elif data.release_id is not None:
        ctx = ContextTag.DEPLOYMENT
    elif data.test_phase_id is not None:
        ctx = ContextTag.REGRESSION
    else:
        ctx = ContextTag.NONE

    parent = Booking(
        environment_id=data.environment_id,
        project_name=data.project_name,
        booked_by=current_user.id,
        start_date=data.start_date,
        end_date=data.end_date,
        booking_type=data.booking_type,
        status=BookingStatus.PENDING,
        notes=data.notes,
        recurrence_rule=data.recurrence_rule,
        recurrence_parent_id=None,
        release_id=data.release_id,
        test_phase_id=data.test_phase_id,
        context_tag=ctx,
        tenant_id=current_user.active_tenant_id,
    )
    db.add(parent)
    await db.flush()
    await db.refresh(parent)

    # Generate recurring occurrences if RRULE provided
    if data.recurrence_rule:
        try:
            rule = rrulestr(data.recurrence_rule, dtstart=data.start_date, ignoretz=False)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid recurrence rule: {exc}",
            )
        duration = data.end_date - data.start_date
        horizon = data.start_date + timedelta(days=365)
        # Generate occurrences AFTER the start_date (parent IS the first occurrence)
        occurrences = list(rule.between(data.start_date, horizon, inc=False))
        # Cap at 100
        occurrences = occurrences[:100]

        for dt in occurrences:
            child = Booking(
                environment_id=data.environment_id,
                project_name=data.project_name,
                booked_by=current_user.id,
                start_date=dt,
                end_date=dt + duration,
                booking_type=data.booking_type,
                status=BookingStatus.PENDING,
                notes=data.notes,
                recurrence_rule=None,  # children don't store the rule
                recurrence_parent_id=parent.id,
                release_id=data.release_id,
                test_phase_id=data.test_phase_id,
                context_tag=ctx,
                tenant_id=current_user.active_tenant_id,
            )
            db.add(child)

        await db.flush()

    # Re-fetch the parent with relationships eagerly loaded
    parent = await get_booking(db, parent.id, current_user.active_tenant_id)
    await publish_event(
        db,
        event_type="BookingCreated",
        aggregate_id=parent.id,
        aggregate_type="Booking",
        payload={
            "id": parent.id,
            "project_name": parent.project_name,
            "environment_id": parent.environment_id,
            "tenant_id": parent.tenant_id,
        },
        tenant_id=parent.tenant_id,
    )
    return parent, overlap.warnings


async def get_booking(db: AsyncSession, booking_id: int, tenant_id: int) -> Booking:
    result = await db.execute(
        select(Booking)
        .options(
            selectinload(Booking.environment),
            selectinload(Booking.booker),
        )
        .where(
            Booking.id == booking_id,
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


async def list_bookings(
    db: AsyncSession,
    tenant_id: int,
    environment_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    booking_status: Optional[BookingStatus] = None,
) -> list[Booking]:
    query = (
        select(Booking)
        .options(
            selectinload(Booking.environment),
            selectinload(Booking.booker),
        )
        .where(
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
        )
    )
    if environment_id is not None:
        query = query.where(Booking.environment_id == environment_id)
    if start is not None and end is not None:
        query = query.where(Booking.start_date < end, Booking.end_date > start)
    if booking_status is not None:
        query = query.where(Booking.status == booking_status)
    query = query.order_by(Booking.start_date.asc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def approve_booking(db: AsyncSession, booking_id: int, tenant_id: int) -> Booking:
    booking = await get_booking(db, booking_id, tenant_id)
    booking.status = BookingStatus.APPROVED

    # If this is a parent booking, also approve all pending children
    if booking.recurrence_parent_id is None:
        await db.execute(
            update(Booking)
            .where(
                Booking.recurrence_parent_id == booking_id,
                Booking.status == BookingStatus.PENDING,
                Booking.deleted_at.is_(None),
            )
            .values(status=BookingStatus.APPROVED)
        )

    await db.flush()
    # Re-fetch with eager relationships after flush
    result = await get_booking(db, booking_id, tenant_id)
    await publish_event(
        db,
        event_type="BookingApproved",
        aggregate_id=result.id,
        aggregate_type="Booking",
        payload={
            "id": result.id,
            "project_name": result.project_name,
            "environment_id": result.environment_id,
            "tenant_id": result.tenant_id,
        },
        tenant_id=result.tenant_id,
    )
    return result


async def reject_booking(db: AsyncSession, booking_id: int, tenant_id: int) -> Booking:
    booking = await get_booking(db, booking_id, tenant_id)
    booking.status = BookingStatus.REJECTED

    # If this is a parent booking, also reject all pending children
    if booking.recurrence_parent_id is None:
        await db.execute(
            update(Booking)
            .where(
                Booking.recurrence_parent_id == booking_id,
                Booking.status == BookingStatus.PENDING,
                Booking.deleted_at.is_(None),
            )
            .values(status=BookingStatus.REJECTED)
        )

    await db.flush()
    # Re-fetch with eager relationships after flush
    result = await get_booking(db, booking_id, tenant_id)
    await publish_event(
        db,
        event_type="BookingRejected",
        aggregate_id=result.id,
        aggregate_type="Booking",
        payload={
            "id": result.id,
            "project_name": result.project_name,
            "environment_id": result.environment_id,
            "tenant_id": result.tenant_id,
        },
        tenant_id=result.tenant_id,
    )
    return result


async def cancel_booking(db: AsyncSession, booking_id: int, current_user) -> None:
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)

    # Verify ownership or admin/RM role
    is_owner = booking.booked_by == current_user.id
    is_privileged = current_user.is_master_admin or current_user.role in ("Admin", "Release Manager")
    if not (is_owner or is_privileged):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to cancel this booking",
        )

    booking.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="BookingCancelled",
        aggregate_id=booking.id,
        aggregate_type="Booking",
        payload={
            "id": booking.id,
            "project_name": booking.project_name,
            "environment_id": booking.environment_id,
            "tenant_id": booking.tenant_id,
        },
        tenant_id=booking.tenant_id,
    )


async def delete_occurrence(db: AsyncSession, booking_id: int, current_user) -> None:
    """Soft-delete a single booking occurrence."""
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)

    is_owner = booking.booked_by == current_user.id
    is_privileged = current_user.is_master_admin or current_user.role in ("Admin", "Release Manager")
    if not (is_owner or is_privileged):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this booking occurrence",
        )

    booking.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def delete_series(db: AsyncSession, booking_id: int, current_user) -> None:
    """Soft-delete the entire series (parent + all children)."""
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)

    # Allow if owner or Admin/Release Manager/master admin
    is_owner = booking.booked_by == current_user.id
    is_privileged = current_user.is_master_admin or current_user.role in ("Admin", "Release Manager")
    if not (is_owner or is_privileged):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own booking series",
        )

    # Find root: if booking has a parent, load the parent
    if booking.recurrence_parent_id is not None:
        root = await get_booking(db, booking.recurrence_parent_id, current_user.active_tenant_id)
    else:
        root = booking

    now = datetime.now(timezone.utc)
    root.deleted_at = now

    # Bulk soft-delete all children
    await db.execute(
        update(Booking)
        .where(
            Booking.recurrence_parent_id == root.id,
            Booking.deleted_at.is_(None),
        )
        .values(deleted_at=now)
    )

    await db.flush()
