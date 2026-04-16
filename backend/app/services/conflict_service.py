from sqlalchemy import select, and_, or_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking

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
