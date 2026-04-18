from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, and_, or_, not_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.booking import Booking
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.booking_request import BookingRequest
from app.db.models.user import User

TERMINAL_STATES = {"rejected", "closed"}


async def list_conflicts(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> list[Booking]:
    """Return other bookings conflicting with booking_id — same env, overlapping window,
    neither in a lifecycle-defined terminal state."""
    me = (await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if me is None or me.status in TERMINAL_STATES:
        return []

    stmt = (
        select(Booking)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.id != me.id,
            Booking.environment_id == me.environment_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(TERMINAL_STATES)),
            # half-open overlap: [start, end)
            Booking.start_date < me.end_date,
            Booking.end_date > me.start_date,
        )
        .order_by(Booking.start_date)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _authorize_ack(db: AsyncSession, booking_id: int, tenant_id: int, user: User) -> None:
    """User must be the booking's parent-request owner or a listed delegate."""
    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if booking is None or booking.booking_request_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    req = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
    )).scalar_one()
    if user.id == req.booked_by:
        return
    if req.delegate_user_ids and user.id in req.delegate_user_ids:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the owner or a delegate may acknowledge a conflict",
    )


async def upsert_ack(
    db: AsyncSession,
    booking_id: int,
    other_booking_id: int,
    *,
    willing_to_share: bool,
    notes: str | None,
    current_user: User,
    tenant_id: int,
) -> BookingConflictAck:
    await _authorize_ack(db, booking_id, tenant_id, current_user)

    existing = (await db.execute(
        select(BookingConflictAck).where(
            BookingConflictAck.booking_id == booking_id,
            BookingConflictAck.other_booking_id == other_booking_id,
            BookingConflictAck.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is None:
        ack = BookingConflictAck(
            tenant_id=tenant_id,
            booking_id=booking_id,
            other_booking_id=other_booking_id,
            willing_to_share=willing_to_share,
            notes=notes,
            acknowledged_by=current_user.id,
            acknowledged_at=now,
        )
        db.add(ack)
        await db.flush()
        return ack

    existing.willing_to_share = willing_to_share
    existing.notes = notes
    existing.acknowledged_by = current_user.id
    existing.acknowledged_at = now
    await db.flush()
    return existing


async def get_ack(
    db: AsyncSession, booking_id: int, other_booking_id: int, tenant_id: int
) -> BookingConflictAck | None:
    return (await db.execute(
        select(BookingConflictAck).where(
            BookingConflictAck.booking_id == booking_id,
            BookingConflictAck.other_booking_id == other_booking_id,
            BookingConflictAck.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()


async def has_unacknowledged_conflicts(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> bool:
    conflicts = await list_conflicts(db, booking_id, tenant_id)
    if not conflicts:
        return False
    for other in conflicts:
        ack = await get_ack(db, booking_id, other.id, tenant_id)
        if ack is None or ack.willing_to_share is None:
            return True
    return False


@dataclass
class ReceivedFeedbackRow:
    ack: BookingConflictAck
    source_booking: Booking
    source_request: BookingRequest
    acknowledged_by: User
    booked_by: User


async def list_received_feedback(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> list[ReceivedFeedbackRow]:
    """Return acks left by other bookings' owners about this booking.

    Excludes rows where both willing_to_share and notes are empty (no actual
    feedback posted yet). Ordered by acknowledged_at DESC.
    """
    AckUser = aliased(User)
    OwnerUser = aliased(User)

    stmt = (
        select(
            BookingConflictAck,
            Booking,
            BookingRequest,
            AckUser,
            OwnerUser,
        )
        .join(Booking, Booking.id == BookingConflictAck.booking_id)
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
        .join(AckUser, AckUser.id == BookingConflictAck.acknowledged_by)
        .join(OwnerUser, OwnerUser.id == BookingRequest.booked_by)
        .where(
            BookingConflictAck.other_booking_id == booking_id,
            BookingConflictAck.tenant_id == tenant_id,
            or_(
                BookingConflictAck.willing_to_share.is_not(None),
                and_(
                    BookingConflictAck.notes.is_not(None),
                    BookingConflictAck.notes != "",
                ),
            ),
        )
        .order_by(BookingConflictAck.acknowledged_at.desc())
    )
    result = await db.execute(stmt)
    return [
        ReceivedFeedbackRow(
            ack=ack,
            source_booking=booking,
            source_request=req,
            acknowledged_by=ack_user,
            booked_by=owner_user,
        )
        for ack, booking, req, ack_user, owner_user in result.all()
    ]
