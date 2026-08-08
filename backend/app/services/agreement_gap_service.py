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

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.project import Project, UsageAgreement


def covered_exists_clause(tenant_id: int):
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


def gap_clause(tenant_id: int):
    """The filter form: this booking's request names a project AND no live
    agreement covers it.

    The `project_id IS NOT NULL` half is load-bearing, not defensive — a
    booking with no project is never in gap, and most existing bookings have
    none.

    Usable anywhere `Booking` is joined to `BookingRequest`; that join must
    itself be tenant-qualified, since this clause reads `project_id` from
    whatever request the booking points at.
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
            # Deliberately NOT tenant-qualified, matching booking_service's own
            # Booking→BookingRequest join and the one GET /bookings will apply
            # gap_clause over. Adding a filter here that the SQL consumer does
            # not have would make the two mechanisms disagree about a malformed
            # booking — the shape A2 hit three times. Tenant scoping is on
            # `Booking.tenant_id` below and on the two name joins, so a
            # cross-tenant request can change no answer and leak no name.
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
    db: AsyncSession, pairs: set, tenant_id: int
) -> dict[tuple, list[_Window]]:
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

    found: dict[tuple, list[_Window]] = {}
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
