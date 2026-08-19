"""B6 — forward contention: which bookings clash, folded per booking.

READS ONLY. Nothing in this module writes, and it must never learn how —
`tests/test_b6_writes_nothing.py` is the guard on that.

The overlap rules are NOT restated here. `conflict_service.conflicts_with` is
the one definition and already had three consumers before B6 — `list_conflicts`,
`_unacknowledged_conflict_exists` (both `conflict_service`), and A4's
`contention_service._pair_conflict_exists`; this is the fourth. A second copy
is the "two mechanisms enforcing one outcome" shape that has cost this
codebase repeatedly, and a calendar that disagreed with the Conflicts panel
about whether a clash exists would be worse than no calendar marker.
"""
from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.services import conflict_service, contention_service


async def overlapping_pairs(
    db: AsyncSession,
    tenant_id: int,
    *,
    booking_ids: Optional[Sequence[int]] = None,
    window: Optional[tuple[datetime, datetime]] = None,
) -> list[tuple[int, int]]:
    """Every live overlapping pair in this tenant, normalised `(lower, higher)`.

    THE DATABASE DOES THE PAIRING. Contention is pairwise, so a Python-side
    implementation is O(N^2) over a calendar's worth of bookings. Overlaps are
    sparse in real estates, so the cost here scales with the number of actual
    clashes rather than with how busy the calendar looks.

    `b1.id < b2.id` does two jobs: it halves the work, and it yields A4's
    normalised pair directly, so `escalations_for_pairs` — which keys by the
    pair AS GIVEN — matches without a second normalisation step.

    ONLY ONE SIDE NEED BE IN `booking_ids`. See the spec: requiring both would
    silently hide a long-running booking that the caller's range never renders,
    and the omission looks exactly like an absence of contention.
    """
    b1 = aliased(Booking)
    b2 = aliased(Booking)

    # conflict_service filters only the OTHER side; the subject's own liveness
    # is the caller's job there (`list_conflicts` checks it separately), so B6
    # applies the same three conditions to b1 itself.
    query = (
        select(b1.id, b2.id)
        .select_from(b1)
        .join(
            b2,
            and_(
                *conflict_service.conflicts_with(
                    b2,
                    subject_id=b1.id,
                    environment_id=b1.environment_id,
                    start_date=b1.start_date,
                    end_date=b1.end_date,
                    tenant_id=tenant_id,
                )
            ),
        )
        .where(
            b1.tenant_id == tenant_id,
            b1.deleted_at.is_(None),
            b1.status.notin_(conflict_service.TERMINAL_STATES),
            b1.id < b2.id,
        )
    )

    if booking_ids is not None:
        ids = list(booking_ids)
        if not ids:
            return []
        query = query.where(or_(b1.id.in_(ids), b2.id.in_(ids)))

    if window is not None:
        start, end = window
        # THE OVERLAP INTERVAL, WITHOUT GREATEST/LEAST — SQLite has neither.
        # max(b1.start, b2.start) <  end  <=>  b1.start < end  AND b2.start < end
        # min(b1.end,   b2.end)   > start <=>  b1.end   > start AND b2.end   > start
        query = query.where(
            b1.start_date < end, b2.start_date < end,
            b1.end_date > start, b2.end_date > start,
        )

    rows = (await db.execute(query.order_by(b1.id, b2.id))).all()
    return [(low, high) for low, high in rows]


async def contention_count_in_window(
    db: AsyncSession, tenant_id: int, *, start: datetime, end: datetime
) -> int:
    """How many CONTENTIONS fall inside the window — pairs, never bookings.

    A contention is inside the window when its OVERLAP INTERVAL is: the
    intersection of the two bookings, not either booking's own span. A pair
    that starts clashing in four months is not a contention in the next six
    weeks even if one of its bookings begins tomorrow.
    """
    return len(await overlapping_pairs(db, tenant_id, window=(start, end)))


STATE_UNOWNED = "unowned"
STATE_OWNED = "owned"
STATE_DECIDED = "decided"

#: Most actionable first. The fold keeps whichever appears earlier here.
#: "Nobody is on this" is the state that needs a human, so it outranks a
#: contention someone already owns, which outranks one already decided.
_PRECEDENCE = (STATE_UNOWNED, STATE_OWNED, STATE_DECIDED)


def _more_actionable(current: Optional[str], candidate: str) -> str:
    if current is None:
        return candidate
    return min(current, candidate, key=_PRECEDENCE.index)


async def contention_states_for_bookings(
    db: AsyncSession,
    tenant_id: int,
    booking_ids: Sequence[int],
    *,
    now: datetime,
) -> dict[int, str]:
    """The contention state of each REQUESTED booking that has one.

    ONCE PER RESPONSE, NEVER ONCE PER ROW. A3 measured a 50-row page through a
    per-booking helper at roughly 150 queries; this takes the whole page's ids
    and issues two.

    Absent key == no contention. There is deliberately no `none` state.
    """
    requested = set(booking_ids)
    if not requested:
        return {}

    pairs = await overlapping_pairs(db, tenant_id, booking_ids=list(requested))
    if not pairs:
        return {}

    escalations = await contention_service.escalations_for_pairs(db, pairs, tenant_id)

    states: dict[int, str] = {}
    for pair in pairs:
        escalation = escalations.get(pair)
        if escalation is None:
            pair_state = STATE_UNOWNED
        elif contention_service.escalation_state(escalation, now) == (
            contention_service.STATE_ANSWERED
        ):
            pair_state = STATE_DECIDED
        else:
            # `open` AND `expired`. An overdue escalation still has a named
            # owner who owes an answer; the booking's own page says so.
            pair_state = STATE_OWNED

        for booking_id in pair:
            if booking_id not in requested:
                # The counterpart decides the state; it does not get one.
                continue
            states[booking_id] = _more_actionable(states.get(booking_id), pair_state)

    return states
