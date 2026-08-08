from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import Exists, select, and_, or_, not_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.pagination import Page, fetch_page_rows
from app.core.upsert import insert_or_reread
from app.db.models.booking import Booking
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.user import User

TERMINAL_STATES = {"rejected", "closed"}


@dataclass
class ConflictingBooking:
    """Booking plus the display labels a UI needs without extra round-trips."""
    booking: Booking
    project_name: Optional[str]
    environment_name: Optional[str]


def conflicts_with(other, *, subject_id, environment_id, start_date, end_date, tenant_id):
    """What it means for `other` to conflict with a subject booking.

    ONE definition, two consumers: `list_conflicts` passes literals off a
    loaded `Booking`, and `_unacknowledged_conflict_exists` passes the
    correlated `Booking` columns straight through. Both therefore ask the same
    question, which is the point — a second copy of these five rules is
    precisely the "two mechanisms enforcing one outcome" shape that has cost
    this codebase repeated defects, because one test cannot then guard both.

    Every argument is keyword-only and required: a positional call site that
    silently swapped `start_date` and `end_date` would invert the overlap and
    still typecheck.
    """
    return (
        other.tenant_id == tenant_id,
        other.id != subject_id,
        other.environment_id == environment_id,
        other.deleted_at.is_(None),
        not_(other.status.in_(TERMINAL_STATES)),
        # half-open overlap: [start, end)
        other.start_date < end_date,
        other.end_date > start_date,
    )


async def list_conflicts(
    db: AsyncSession, booking_id: int, tenant_id: int, page: Optional[Page] = None
) -> tuple[list[ConflictingBooking], int]:
    """Return other bookings conflicting with booking_id — same env, overlapping window,
    neither in a lifecycle-defined terminal state. The result is enriched with the
    parent-request project name and environment name so UIs can show a human-readable
    label instead of "Booking #N".
    """
    me = (await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if me is None or me.status in TERMINAL_STATES:
        return [], 0

    stmt = (
        select(Booking, BookingRequest.project_name, Environment.name)
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id, isouter=True)
        .join(Environment, Environment.id == Booking.environment_id, isouter=True)
        .where(
            *conflicts_with(
                Booking,
                subject_id=me.id,
                environment_id=me.environment_id,
                start_date=me.start_date,
                end_date=me.end_date,
                tenant_id=tenant_id,
            )
        )
        .order_by(Booking.start_date, Booking.id)
    )
    rows, total = await fetch_page_rows(db, stmt, page)
    return [
        ConflictingBooking(
            booking=b,
            project_name=project_name,
            environment_name=env_name,
        )
        for b, project_name, env_name in rows
    ], total


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
        # A concurrent first-ack may land between the read above and this
        # insert; `uq_conflict_ack_pair` then refuses ours. insert_or_reread
        # hands back the row that won so the update below applies to it — the
        # later answer is recorded, as it would have been unraced. See
        # app/core/upsert.py for why this needs a savepoint.
        existing, inserted = await insert_or_reread(
            db,
            BookingConflictAck(
                tenant_id=tenant_id,
                booking_id=booking_id,
                other_booking_id=other_booking_id,
                willing_to_share=willing_to_share,
                notes=notes,
                acknowledged_by=current_user.id,
                acknowledged_at=now,
            ),
            lambda: get_ack(db, booking_id, other_booking_id, tenant_id),
        )
        if inserted:
            return existing

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


def _unacknowledged_conflict_exists(tenant_id: int) -> Exists:
    """EXISTS(a live conflicting booking this booking's owner has not answered).

    Correlates against `Booking`, so any query selecting from Booking can use
    it. The conditions are `list_conflicts`' verbatim — same tenant, a
    different booking, same environment, not soft-deleted, not in a terminal
    state, half-open `[start, end)` overlap — plus the unanswered test.

    "UNANSWERED" IS `willing_to_share IS NULL`, NOT "no ack row". A row can
    exist carrying only notes, and `has_unacknowledged_conflicts` has always
    treated that as still unanswered (`ack is None or ack.willing_to_share is
    None`). The inner `NOT EXISTS` therefore looks for an ack that HAS answered
    and negates it, which covers both cases in one clause.

    The ack's own `tenant_id` filter is load-bearing for the same reason
    `agreement_gap_service.get_ack`'s is: `uq_conflict_ack_pair` is on
    `(booking_id, other_booking_id)` alone, so a malformed row bearing another
    tenant's `tenant_id` is insertable and must not silence our warning.
    """
    other = aliased(Booking)
    ack = aliased(BookingConflictAck)
    answered = (
        select(ack.id)
        .where(
            ack.tenant_id == tenant_id,
            ack.booking_id == Booking.id,
            ack.other_booking_id == other.id,
            ack.willing_to_share.is_not(None),
        )
        .correlate(Booking, other)
        .exists()
    )
    return (
        select(other.id)
        .where(
            *conflicts_with(
                other,
                subject_id=Booking.id,
                environment_id=Booking.environment_id,
                start_date=Booking.start_date,
                end_date=Booking.end_date,
                tenant_id=tenant_id,
            ),
            ~answered,
        )
        .correlate(Booking)
        .exists()
    )


async def bookings_with_unacknowledged_conflicts(
    db: AsyncSession, booking_ids: Iterable[int], tenant_id: int
) -> set[int]:
    """Which of `booking_ids` have a conflict their owner has not answered.

    ONE query for the whole page. The per-row form this replaced cost
    `list_conflicts` plus one `get_ack` PER CONFLICT, for every row — so a
    50-row page issued 50 x (1 + conflicts) queries and got worse as the estate
    got busier. Mirrors `agreement_gap_service.gap_warnings_for_bookings`,
    which is the shape every response builder here now uses.

    A booking in a terminal state has no conflicts by definition, exactly as
    `list_conflicts` returns nothing for one — that filter is on the SUBJECT
    here and on the OTHER booking inside the EXISTS, and both are needed.

    Deliberately returns ids rather than rows: nothing downstream needs the
    conflicting bookings themselves, and returning them would invite a caller
    to render a page-sized set it never asked for.
    """
    ids = list(booking_ids)
    if not ids:
        return set()
    rows = await db.execute(
        select(Booking.id).where(
            Booking.id.in_(ids),
            Booking.tenant_id == tenant_id,
            not_(Booking.status.in_(TERMINAL_STATES)),
            _unacknowledged_conflict_exists(tenant_id),
        )
    )
    return set(rows.scalars().all())


def conflict_fields(flagged: bool) -> dict[str, object]:
    """One booking's conflict flag as the field every response carries.

    THE SINGLE SPELLING OF THAT PROJECTION, exactly as
    `agreement_gap_service.gap_fields` is for the gap pair. Written as
    `**conflict_fields(booking.id in conflicts)` so a call site reads as one
    decision rather than a line that can be quietly edited to a constant.

    A required field guards only that a site ANSWERS — not that it answers
    about the right booking. That is why every site has a named test, and why
    this takes the already-computed membership rather than a booking id and a
    set: passing the wrong id is then visible at the call site instead of
    hidden inside a helper.
    """
    return {"has_unacknowledged_conflicts": flagged}


async def has_unacknowledged_conflicts(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> bool:
    """The single-booking form, for detail reads.

    DERIVED FROM THE BATCH, not a second implementation. Two mechanisms
    answering one question means one test cannot guard both, and this codebase
    has already shipped a count and a list that disagreed two ways. NEVER call
    this in a loop over a page — that is the N x M this batch exists to kill.
    """
    return booking_id in await bookings_with_unacknowledged_conflicts(
        db, [booking_id], tenant_id
    )


@dataclass
class ReceivedFeedbackRow:
    ack: BookingConflictAck
    source_booking: Booking
    source_request: BookingRequest
    acknowledged_by: User
    booked_by: User


async def list_received_feedback(
    db: AsyncSession, booking_id: int, tenant_id: int, page: Optional[Page] = None
) -> tuple[list[ReceivedFeedbackRow], int]:
    """Return acks left by other bookings' owners about this booking, and the total.

    Excludes rows where both willing_to_share and notes are empty (no actual
    feedback posted yet). Ordered by acknowledged_at DESC.

    Every filter is in the WHERE clause, so windowing the query is safe — there
    is no Python-side predicate that a page would be applied ahead of.
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
        # `acknowledged_at` is a defaulted timestamp, so two acks written in the
        # same transaction tie on it; the primary key makes the order total, and
        # LIMIT/OFFSET is only correct over a total order.
        .order_by(BookingConflictAck.acknowledged_at.desc(), BookingConflictAck.id)
    )
    rows, total = await fetch_page_rows(db, stmt, page)
    return [
        ReceivedFeedbackRow(
            ack=ack,
            source_booking=booking,
            source_request=req,
            acknowledged_by=ack_user,
            booked_by=owner_user,
        )
        for ack, booking, req, ack_user, owner_user in rows
    ], total
