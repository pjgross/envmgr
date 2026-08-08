"""Is a booking covered by one of its project's usage agreements?

A3 WARNS; it never blocks. Nothing here refuses a booking — the caller
surfaces what this returns and carries on. A1's
`test_an_agreement_changes_no_booking_behaviour` is the guard on that promise.

The coverage test is written as a SQL EXISTS first, and everything else is
derived from it. `GET /bookings` is bounded, so the filter must push down: a
Python-side filter would window the page BEFORE filtering and return the wrong
rows. Writing the Python form first and discovering later that it cannot be
pushed down is how `dependency-alerts` became permanently unbounded.

One expression, three consumers: `gap_clause` decides, `gaps_for_bookings`
decorates the rows it selects with a message, and `describe_gap` is
`gaps_for_bookings` for one booking. Nothing here re-implements the comparison
in Python — A1 shipped a count and a list, written three tasks apart, that
disagreed two ways.
"""
from datetime import datetime, timedelta, timezone
from typing import Iterable, NamedTuple, Optional

from fastapi import HTTPException, status
from sqlalchemy import Exists, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.project import Project, UsageAgreement
from app.db.models.usage_agreement_ack import UsageAgreementAck
from app.db.models.user import User


def covered_exists_clause(tenant_id: int) -> Exists:
    """EXISTS(a live agreement covering this booking's project, environment
    and dates).

    Correlates against `Booking` and `BookingRequest`, so any query selecting
    from Booking joined to its request can use it directly.

    "LIVE" IS NOT `deleted_at IS NULL` ON THE AGREEMENT ALONE. The project and
    the environment must both be live too, exactly as
    project_service._agreement_query requires. `delete_project` cascades a
    soft delete to its agreements; **`delete_environment` does not**, so a
    soft-deleted environment leaves agreement rows with a null `deleted_at`
    pointing at it — invisible to A1's list endpoints and fully visible to a
    naive query. Filtering only the agreement would honour agreements for dead
    environments.

    Window semantics: a null bound means NO bound, not "unknown". An agreement
    covers the booking when it starts no later than the booking starts and
    ends no earlier than the booking ends.

    BOUNDS ARE INSTANTS, NOT CALENDAR DAYS — and the message renders them as
    days. `starts_at`/`ends_at` are `DateTime(timezone=True)`, and the
    comparison is against the booking's own `start_date`/`end_date` instants,
    so an agreement recorded as ending `2026-06-30T00:00:00Z` does NOT cover a
    booking ending `2026-06-30T17:00:00Z`, while `_format_window` renders that
    bound as `30 Jun 2026`. Read as calendar days the end bound is therefore
    EXCLUSIVE of its own final day (and the start bound is inclusive of its
    first day only for bookings starting at or after that instant). This is the
    brief's expression verbatim and is deliberately unchanged; it is recorded
    here — and pinned by
    `test_the_window_bounds_are_instants_not_calendar_days` — so the
    user-facing copy is written against a stated rule rather than an assumption.
    If a future task wants day-granular inclusivity, it must change the
    comparison AND the wording together, in one commit.

    `.correlate(Booking, BookingRequest)` names the outer entities EXHAUSTIVELY,
    so SQLAlchemy cannot also correlate this subquery's own `Project` /
    `Environment` against an enclosing query that happens to select from them —
    which would silently narrow coverage to whatever row the outer query is on.
    The callers below additionally alias those two tables for name rendering, so
    the liveness join and the display join can never be confused for each other.
    """
    return (
        select(UsageAgreement.id)
        .join(
            Project,
            and_(
                Project.id == UsageAgreement.project_id,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            ),
        )
        .join(
            Environment,
            and_(
                Environment.id == UsageAgreement.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            ),
        )
        .where(
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.deleted_at.is_(None),
            UsageAgreement.project_id == BookingRequest.project_id,
            UsageAgreement.environment_id == Booking.environment_id,
            or_(
                UsageAgreement.starts_at.is_(None),
                UsageAgreement.starts_at <= Booking.start_date,
            ),
            or_(
                UsageAgreement.ends_at.is_(None),
                UsageAgreement.ends_at >= Booking.end_date,
            ),
        )
        .correlate(Booking, BookingRequest)
        .exists()
    )


def gap_clause(tenant_id: int) -> ColumnElement[bool]:
    """The filter form: this booking's request names a project AND no live
    agreement covers it.

    The `project_id IS NOT NULL` half is load-bearing, not defensive — a
    booking with no project is never in gap, and most existing bookings have
    none.

    Usable anywhere `Booking` is joined to `BookingRequest`. THAT JOIN IS THE
    CONSUMER'S AND MUST NOT BE TENANT-QUALIFIED — `gaps_for_bookings` does not
    qualify it either (see the comment on its own join), and qualifying it in
    one place without the other makes the list filter and the per-row message
    disagree about a malformed booking: exactly the A1 count-vs-list divergence
    this expression exists to prevent. If a future change wants the join
    qualified, it must be qualified in BOTH places in the same commit. Tenant
    scoping that changes an answer lives inside this clause and on
    `Booking.tenant_id` at the call site, so an unqualified join can leak
    nothing.
    """
    return and_(
        BookingRequest.project_id.is_not(None),
        ~covered_exists_clause(tenant_id),
    )


def _live_agreements_clause(tenant_id: int):
    """The same three liveness filters as the EXISTS above, minus the window
    and the correlation — "does a live agreement exist for this pair at all?".

    Kept beside the predicate deliberately: if these two ever disagree about
    what "live" means, a booking whose only agreement is for a soft-deleted
    environment would be told it is "outside the agreed window" of an
    agreement the rule refuses to honour.
    """
    return (
        select(
            UsageAgreement.project_id,
            UsageAgreement.environment_id,
            UsageAgreement.starts_at,
            UsageAgreement.ends_at,
        )
        .join(
            Project,
            and_(
                Project.id == UsageAgreement.project_id,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            ),
        )
        .join(
            Environment,
            and_(
                Environment.id == UsageAgreement.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            ),
        )
        .where(
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.deleted_at.is_(None),
        )
    )


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes for `DateTime(timezone=True)` columns
    while PostgreSQL hands back aware ones. Comparing the two raises, so
    normalise before any Python-side arithmetic — the stored values are UTC on
    both engines."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _format_date(value: datetime) -> str:
    """`1 Jan 2026` — no zero padding, no platform-specific strftime flags
    (`%-d` is glibc/BSD only)."""
    return f"{value.day} {value:%b %Y}"


def _format_window(starts_at: Optional[datetime], ends_at: Optional[datetime]):
    """The window as the reader must see it to know what to change.

    A both-null window is unreachable from a gap message — such an agreement
    covers everything, so its booking is not in gap — but it returns None
    rather than inventing a bound, so a future caller cannot render "None".
    """
    if starts_at is not None and ends_at is not None:
        return f"{_format_date(starts_at)} – {_format_date(ends_at)}"
    if starts_at is not None:
        return f"from {_format_date(starts_at)}"
    if ends_at is not None:
        return f"until {_format_date(ends_at)}"
    return None


def _distance(
    starts_at: Optional[datetime],
    ends_at: Optional[datetime],
    start: datetime,
    end: datetime,
) -> timedelta:
    """How far this window misses the booking by, for picking the nearest one.

    Overlapping windows are legal by construction, so several may miss; naming
    the closest is the one that tells the reader the smallest change that would
    fix it. Ties are broken by agreement id at the call site, so the message is
    deterministic rather than dependent on row order.
    """
    missed = timedelta(0)
    if starts_at is not None and starts_at > start:
        missed += starts_at - start
    if ends_at is not None and ends_at < end:
        missed += end - ends_at
    return missed


async def gaps_for_bookings(
    db: AsyncSession, bookings: Iterable[Booking], tenant_id: int
) -> dict[int, str]:
    """`booking_id -> message`, for those of `bookings` that are in gap.

    Bookings that are covered, that name no project, or that are not this
    tenant's are simply absent — a caller may `.get()` its way to
    `agreement_gap: None` without a second question.

    The gap decision is `gap_clause`, in SQL. Only the MESSAGE is assembled in
    Python, over the rows that clause already selected, so this can never
    disagree with `GET /bookings?agreement_gap=true`.
    """
    booking_ids = {b.id for b in bookings if b is not None and b.id is not None}
    if not booking_ids:
        return {}

    # Aliased purely for rendering, and deliberately NOT filtered on
    # `deleted_at`: an archived project or environment still renders its name
    # on the live booking that references it — A1's get_project_names rule.
    # Whether it COUNTS as coverage is the EXISTS's question, not this one.
    named_project = aliased(Project)
    named_environment = aliased(Environment)

    rows = (
        await db.execute(
            select(
                Booking.id,
                Booking.start_date,
                Booking.end_date,
                Booking.environment_id,
                BookingRequest.project_id,
                named_project.name.label("project_name"),
                named_environment.name.label("environment_name"),
            )
            # Deliberately NOT tenant-qualified, matching the join
            # `booking_service.list_bookings` adds for its `project_id` filter
            # (booking_service.py:306) — the one GET /bookings will apply
            # gap_clause over. Cite that function specifically, NOT the service
            # in general: A2's group query (booking_service.py:452-463) does
            # qualify `BookingRequest.tenant_id` and filter its `deleted_at`,
            # so the repo convention is mixed and only `list_bookings` is the
            # join this must match. Adding a filter here that the SQL consumer
            # does not have would make the two mechanisms disagree about a
            # malformed booking — the shape A2 hit three times. Tenant scoping
            # is on `Booking.tenant_id` below and on the two name joins, so a
            # cross-tenant request can change no answer and leak no name.
            #
            # `BookingRequest.deleted_at` is likewise NOT filtered, for the same
            # reason rather than by oversight: `list_bookings` does not filter
            # it, so filtering it here would hide from the message a booking the
            # list still reports as in gap. It is currently unreachable in any
            # case — nothing in the codebase ever sets it
            # (booking_service.py:456-462 records this). `Booking.deleted_at` is
            # left to the caller for the same reason: the caller's query decides
            # which bookings it is asking about.
            .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
            .outerjoin(
                named_project,
                and_(
                    named_project.id == BookingRequest.project_id,
                    named_project.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                named_environment,
                and_(
                    named_environment.id == Booking.environment_id,
                    named_environment.tenant_id == tenant_id,
                ),
            )
            .where(
                Booking.id.in_(booking_ids),
                Booking.tenant_id == tenant_id,
                gap_clause(tenant_id),
            )
        )
    ).all()
    if not rows:
        return {}

    windows = await _windows_for_pairs(
        db, {(r.project_id, r.environment_id) for r in rows}, tenant_id
    )

    messages: dict[int, str] = {}
    for row in rows:
        # A malformed cross-tenant reference is the only way a name is missing.
        # Never fall back to an id — this codebase renders entities by name.
        project_name = row.project_name or "This project"
        environment_name = row.environment_name or "this environment"
        candidates = windows.get((row.project_id, row.environment_id), [])
        if not candidates:
            messages[row.id] = (
                f"{project_name} has no usage agreement for {environment_name}"
            )
            continue
        start = _utc(row.start_date)
        end = _utc(row.end_date)
        nearest = min(
            candidates,
            key=lambda w: (_distance(w.starts_at, w.ends_at, start, end), w.agreement_id),
        )
        window = _format_window(nearest.starts_at, nearest.ends_at)
        message = (
            f"{project_name}'s booking falls outside its agreed window for "
            f"{environment_name}"
        )
        messages[row.id] = f"{message} ({window})" if window else message
    return messages


class _Window(NamedTuple):
    """One live agreement's window, for wording a message — never for deciding
    whether a booking is in gap, which is `gap_clause`'s job alone."""

    agreement_id: int
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]


async def _windows_for_pairs(
    db: AsyncSession,
    pairs: set[tuple[Optional[int], Optional[int]]],
    tenant_id: int,
) -> dict[tuple[int, int], list[_Window]]:
    """Every LIVE agreement window for the given (project, environment) pairs.

    One query for the whole page — the pairs come from rows the gap clause
    already selected, so this is bounded by the page, not by the estate.
    """
    usable = [(p, e) for p, e in pairs if p is not None and e is not None]
    if not usable:
        return {}
    # An OR of equality pairs rather than `tuple_(...).in_(...)`: row-value IN
    # is not portable across both engines this suite runs on.
    rows = (
        await db.execute(
            _live_agreements_clause(tenant_id)
            .add_columns(UsageAgreement.id)
            .where(
                or_(
                    *[
                        and_(
                            UsageAgreement.project_id == project_id,
                            UsageAgreement.environment_id == environment_id,
                        )
                        for project_id, environment_id in usable
                    ]
                )
            )
        )
    ).all()

    found: dict[tuple[int, int], list[_Window]] = {}
    for project_id, environment_id, starts_at, ends_at, agreement_id in rows:
        found.setdefault((project_id, environment_id), []).append(
            _Window(agreement_id, _utc(starts_at), _utc(ends_at))
        )
    return found


async def describe_gap(
    db: AsyncSession, booking: Booking, tenant_id: int
) -> Optional[str]:
    """The human message for one booking, or None when there is no gap.

    Delegates to the batch form so the single-booking answer cannot drift from
    the list's: both are `gap_clause`, and there is one message builder.
    """
    return (await gaps_for_bookings(db, [booking], tenant_id)).get(booking.id)


# --------------------------------------------------------------------------
# The acknowledgement.
#
# ONLY THE ACKNOWLEDGEMENT IS STORED — everything above stays computed. These
# three functions never decide whether a booking is in gap; they ask the
# predicate above and record, or read, a human's answer to it. A3 WARNS: none
# of them refuses or alters a booking.
# --------------------------------------------------------------------------


async def _load_booking(db: AsyncSession, booking_id: int, tenant_id: int) -> Optional[Booking]:
    """This tenant's booking, or None. The ONLY place the ack path resolves a
    booking id, so 404-vs-silence is decided once.

    `deleted_at` is deliberately NOT filtered, matching both
    `conflict_service._authorize_ack` and this module's own rule that
    `Booking.deleted_at` is the caller's question (see `gaps_for_bookings`).
    Acknowledging a soft-deleted booking changes nothing a user can see — its
    warning is not rendered anywhere — and refusing it would make this the one
    place in the ack path that disagrees with the predicate about which
    bookings exist.
    """
    return (
        await db.execute(
            select(Booking).where(
                Booking.id == booking_id, Booking.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


async def upsert_ack(
    db: AsyncSession,
    booking_id: int,
    *,
    notes: Optional[str],
    current_user: User,
    tenant_id: int,
) -> UsageAgreementAck:
    """Record — or replace — the acknowledgement of this booking's gap.

    Keyed on `booking_id` alone: a gap is a property of ONE booking, so a second
    row would be a second answer to a single question. Re-acknowledging
    overwrites the author and the timestamp as well as the notes, because the
    row answers "who accepted this risk, and when" about the CURRENT text.

    A booking that is not this tenant's is 404, never 403 — a cross-tenant id
    must not be confirmed to exist. There is deliberately no owner-or-delegate
    gate (unlike `conflict_service._authorize_ack`): a conflict ack is a message
    from one booker to another, so its author matters, whereas a gap is a
    governance finding that an admin or a project lead may reasonably be the one
    to accept. Anything narrower would leave the estate's warnings answerable
    only by whoever happened to make the booking.

    NOTHING HERE CHECKS FOR A GAP FIRST. Acknowledging a covered booking is
    accepted and simply changes no answer (`has_unacknowledged_agreement_gap`
    returns False either way) — refusing it would make the button a race
    against a gap that can close between the page rendering and the click, and
    A3 refuses nothing.
    """
    booking = await _load_booking(db, booking_id, tenant_id)
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )

    existing = await get_ack(db, booking_id, tenant_id)
    now = datetime.now(timezone.utc)
    if existing is None:
        ack = UsageAgreementAck(
            tenant_id=tenant_id,
            booking_id=booking_id,
            notes=notes,
            acknowledged_by=current_user.id,
            acknowledged_at=now,
        )
        db.add(ack)
        await db.flush()
        return ack

    existing.notes = notes
    existing.acknowledged_by = current_user.id
    existing.acknowledged_at = now
    await db.flush()
    return existing


async def get_ack(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> Optional[UsageAgreementAck]:
    """This tenant's acknowledgement of the booking, or None.

    Tenant-filtered even though `booking_id` is unique on its own: a malformed
    row carrying another tenant's `tenant_id` must not silence our warning, and
    `test_another_tenants_ack_row_never_suppresses_our_warning` fails without
    this filter.
    """
    return (
        await db.execute(
            select(UsageAgreementAck).where(
                UsageAgreementAck.booking_id == booking_id,
                UsageAgreementAck.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()


async def has_unacknowledged_agreement_gap(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> bool:
    """Is there a gap on this booking that nobody has acknowledged?

    Named to match the response field it feeds, so a reader does not have to
    check whether they are the same question. It answers "is there something to
    warn about", not "is there an ack row": NO GAP MEANS FALSE regardless of
    acks, mirroring `conflict_service.has_unacknowledged_conflicts`, which
    returns False early when there are no conflicts.

    The gap half is `describe_gap` — i.e. `gap_clause`, via the one message
    builder — and deliberately not a fourth query of its own. A private
    "is it in gap" EXISTS would be a second mechanism answering the question the
    module docstring exists to keep singular, and would carry its own copy of
    the Booking→BookingRequest join whose filters must match
    `gaps_for_bookings`' exactly. Discarding the message costs one extra query
    per booking and buys the guarantee that this flag can never contradict the
    text shown beside it.

    THEREFORE: never call this in a loop over a page. A list endpoint wants
    `gaps_for_bookings` for the whole page plus one ack lookup, not N of these.

    A booking that is not this tenant's is not in gap here — the same silence
    `describe_gap` gives it, rather than an exception, because this feeds a
    response field and not a permission decision.
    """
    booking = await _load_booking(db, booking_id, tenant_id)
    if booking is None:
        return False
    if await describe_gap(db, booking, tenant_id) is None:
        return False
    return await get_ack(db, booking_id, tenant_id) is None
