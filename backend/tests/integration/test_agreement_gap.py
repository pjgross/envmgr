"""The usage-agreement coverage predicate (A3, task 2).

Every test here asks the SAME question three ways — `gap_clause` in SQL,
`describe_gap` for one booking, `gaps_for_bookings` in batch — because A1
shipped a count and a list, written three tasks apart, that disagreed two ways
with zero coverage. The last test in this file asserts the three against each
other over a mixed population rather than separately.

A3 WARNS. Nothing here may refuse a booking; that promise is guarded by
test_usage_agreements_api.test_an_agreement_changes_no_booking_behaviour.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.project import UsageAgreement
from app.services import agreement_gap_service
from tests.factories import ensure_booking_type, ensure_environment, ensure_project

# One fixed calendar for every test: an agreed window of H1 2026, a booking
# inside it, and one well outside it.
WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 30, tzinfo=timezone.utc)
INSIDE_START = datetime(2026, 3, 1, tzinfo=timezone.utc)
INSIDE_END = datetime(2026, 3, 5, tzinfo=timezone.utc)
OUTSIDE_START = datetime(2026, 8, 1, tzinfo=timezone.utc)
OUTSIDE_END = datetime(2026, 8, 5, tzinfo=timezone.utc)


async def _booking(
    db,
    tenant,
    user,
    booking_type,
    env,
    *,
    start=INSIDE_START,
    end=INSIDE_END,
    project_id=None,
):
    """A booking and the request that carries its project link."""
    request = BookingRequest(
        tenant_id=tenant.id,
        project_name="a purpose, not a project",
        project_id=project_id,
        booking_type_id=booking_type.id,
        start_date=start,
        end_date=end,
        booked_by=user.id,
    )
    db.add(request)
    await db.flush()
    booking = Booking(
        tenant_id=tenant.id,
        environment_id=env.id,
        start_date=start,
        end_date=end,
        booking_request_id=request.id,
    )
    db.add(booking)
    await db.flush()
    return booking


async def _agreement(db, tenant_id, project_id, environment_id, starts_at=None, ends_at=None):
    agreement = UsageAgreement(
        tenant_id=tenant_id,
        project_id=project_id,
        environment_id=environment_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(agreement)
    await db.flush()
    return agreement


async def _gap_ids_in_sql(db, tenant_id) -> set[int]:
    """The filter form, exercised exactly as GET /bookings will use it."""
    rows = (
        await db.execute(
            select(Booking.id)
            .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
            .where(
                Booking.tenant_id == tenant_id,
                agreement_gap_service.gap_clause(tenant_id),
            )
        )
    ).scalars().all()
    return set(rows)


@pytest.mark.asyncio
async def test_a_request_with_no_project_is_never_in_gap(
    db_session, test_tenant, test_user, test_booking_type
):
    """Opt-in per booking: every booking made before A1 shipped has no project,
    and warning on those would make A3's first day a wall of unfixable noise."""
    env = await ensure_environment(db_session, test_tenant.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env, project_id=None
    )

    # Zero agreements anywhere, and still no gap.
    assert (
        await agreement_gap_service.describe_gap(db_session, booking, test_tenant.id)
    ) is None
    assert await agreement_gap_service.gaps_for_bookings(
        db_session, [booking], test_tenant.id
    ) == {}
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == set()


@pytest.mark.asyncio
async def test_an_agreement_with_both_bounds_null_covers_any_dates(
    db_session, test_tenant, test_user, test_booking_type
):
    """A null bound means NO bound, not 'unknown'."""
    project = await ensure_project(db_session, test_tenant.id, name="Unbounded")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(db_session, test_tenant.id, project.id, env.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=project.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, booking, test_tenant.id)
    ) is None
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == set()


@pytest.mark.asyncio
async def test_an_agreement_with_only_a_start_covers_anything_after_it(
    db_session, test_tenant, test_user, test_booking_type
):
    project = await ensure_project(db_session, test_tenant.id, name="Open Ended")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(db_session, test_tenant.id, project.id, env.id, starts_at=WINDOW_START)

    after = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=project.id,
    )
    before = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=datetime(2025, 11, 1, tzinfo=timezone.utc),
        end=datetime(2025, 11, 5, tzinfo=timezone.utc),
        project_id=project.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, after, test_tenant.id)
    ) is None
    assert (
        await agreement_gap_service.describe_gap(db_session, before, test_tenant.id)
    ) is not None
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {before.id}


@pytest.mark.asyncio
async def test_an_agreement_with_only_an_end_covers_anything_before_it(
    db_session, test_tenant, test_user, test_booking_type
):
    project = await ensure_project(db_session, test_tenant.id, name="Open Started")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(db_session, test_tenant.id, project.id, env.id, ends_at=WINDOW_END)

    before = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=INSIDE_START, end=INSIDE_END, project_id=project.id,
    )
    after = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=project.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, before, test_tenant.id)
    ) is None
    assert (
        await agreement_gap_service.describe_gap(db_session, after, test_tenant.id)
    ) is not None
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {after.id}


@pytest.mark.asyncio
async def test_a_booking_inside_the_window_is_covered(
    db_session, test_tenant, test_user, test_booking_type
):
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(
        db_session, test_tenant.id, project.id, env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=INSIDE_START, end=INSIDE_END, project_id=project.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, booking, test_tenant.id)
    ) is None
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == set()


@pytest.mark.asyncio
async def test_the_window_bounds_are_instants_not_calendar_days(
    db_session, test_tenant, test_user, test_booking_type
):
    """Pins the exclusive/inclusive boundary the message renders as a DAY.

    `starts_at`/`ends_at` are compared as instants against the booking's own
    instants, so a window rendered `1 Jan 2026 – 30 Jun 2026` covers a booking
    ending at midnight on 30 June and NOT one ending at 17:00 that same day —
    the reader sees an inclusive date and gets an exclusive instant. This is the
    brief's expression verbatim; the test exists to record today's behaviour so
    the user-facing copy is written against a stated rule rather than an
    assumption, and so changing the comparison cannot happen silently.
    """
    project = await ensure_project(db_session, test_tenant.id, name="Boundary")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(
        db_session, test_tenant.id, project.id, env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )

    # Ends exactly ON the window's end instant → covered.
    on_the_instant = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=datetime(2026, 6, 29, tzinfo=timezone.utc), end=WINDOW_END,
        project_id=project.id,
    )
    # Ends later the SAME calendar day the window ends → in gap.
    later_that_day = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=datetime(2026, 6, 29, tzinfo=timezone.utc),
        end=datetime(2026, 6, 30, 17, 0, tzinfo=timezone.utc),
        project_id=project.id,
    )
    # Starts exactly ON the window's start instant → covered.
    from_the_instant = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=WINDOW_START, end=datetime(2026, 1, 5, tzinfo=timezone.utc),
        project_id=project.id,
    )
    # Starts earlier the SAME calendar day the window starts → in gap.
    earlier_that_day = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc),
        end=datetime(2026, 1, 5, tzinfo=timezone.utc),
        project_id=project.id,
    )

    assert (
        await agreement_gap_service.describe_gap(
            db_session, on_the_instant, test_tenant.id
        )
    ) is None
    assert (
        await agreement_gap_service.describe_gap(
            db_session, from_the_instant, test_tenant.id
        )
    ) is None
    # And the two same-day misses are warned about, quoting the day-granular
    # window they do not in fact fit inside.
    for booking in (later_that_day, earlier_that_day):
        message = await agreement_gap_service.describe_gap(
            db_session, booking, test_tenant.id
        )
        assert message is not None
        assert "1 Jan 2026 – 30 Jun 2026" in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {
        later_that_day.id,
        earlier_that_day.id,
    }


@pytest.mark.asyncio
async def test_a_booking_outside_the_window_is_in_gap_and_the_message_names_the_window(
    db_session, test_tenant, test_user, test_booking_type
):
    """Out-of-window and no-agreement share a severity but not their wording —
    the booker can only act on the difference if the message carries it."""
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(
        db_session, test_tenant.id, project.id, env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert "Mortgage" in message
    assert env.name in message
    assert "outside" in message
    # The window itself, so the reader can see what to change.
    assert "1 Jan 2026" in message
    assert "30 Jun 2026" in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_a_half_bounded_window_is_named_in_the_message(
    db_session, test_tenant, test_user, test_booking_type
):
    """A one-sided window must not render its missing bound as a date."""
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(
        db_session, test_tenant.id, project.id, env.id, starts_at=WINDOW_START
    )
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=datetime(2025, 11, 1, tzinfo=timezone.utc),
        end=datetime(2025, 11, 5, tzinfo=timezone.utc),
        project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert "from 1 Jan 2026" in message
    assert "None" not in message


@pytest.mark.asyncio
async def test_no_agreement_at_all_is_a_gap_naming_the_environment(
    db_session, test_tenant, test_user, test_booking_type
):
    project = await ensure_project(db_session, test_tenant.id, name="Unagreed")
    env = await ensure_environment(db_session, test_tenant.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert "Unagreed" in message
    assert env.name in message
    assert "no usage agreement" in message
    # It must NOT claim a window it does not have.
    assert "outside" not in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_an_agreement_for_another_environment_does_not_cover_this_one(
    db_session, test_tenant, test_user, test_booking_type
):
    """Guards the environment leg of the correlation: an unbounded agreement
    for a DIFFERENT environment must not silently cover every booking."""
    project = await ensure_project(db_session, test_tenant.id, name="Elsewhere")
    booked = await ensure_environment(db_session, test_tenant.id, slot=1)
    other = await ensure_environment(db_session, test_tenant.id, slot=2)
    await _agreement(db_session, test_tenant.id, project.id, other.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, booked,
        project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert booked.name in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_an_agreement_belonging_to_another_project_does_not_cover_this_booking(
    db_session, test_tenant, test_user, test_booking_type
):
    """Guards the project leg of the correlation."""
    mine = await ensure_project(db_session, test_tenant.id, name="Mine")
    theirs = await ensure_project(db_session, test_tenant.id, name="Theirs")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(db_session, test_tenant.id, theirs.id, env.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=mine.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert "Mine" in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_a_booking_does_not_borrow_another_projects_agreement_for_the_same_environment(
    db_session, test_tenant, test_user, test_booking_type
):
    """Guards the `BookingRequest` leg of `.correlate(Booking, BookingRequest)`.

    `.correlate()` names the outer FROMs EXHAUSTIVELY, so dropping
    `BookingRequest` from that list renders `booking_request` inside the
    subquery's own FROM and turns the project comparison into "some request
    SOMEWHERE names a project with a live agreement for this environment"
    instead of "THIS booking's request does". The test above
    (`..._belonging_to_another_project_...`) is one booking short of catching
    that: it never books the agreed project, so the uncorrelated scan finds
    nothing to match. Here the agreed project HAS a booking, which is what makes
    the false negative reachable — and it is a false negative on ordinary
    well-formed data, not a malformed edge.
    """
    agreed = await ensure_project(db_session, test_tenant.id, name="Has Agreement")
    unagreed = await ensure_project(db_session, test_tenant.id, name="Has None")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(db_session, test_tenant.id, agreed.id, env.id)

    covered = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=agreed.id,
    )
    uncovered = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=unagreed.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, covered, test_tenant.id)
    ) is None
    message = await agreement_gap_service.describe_gap(
        db_session, uncovered, test_tenant.id
    )
    assert message is not None
    assert "Has None" in message
    assert "no usage agreement" in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {uncovered.id}


@pytest.mark.asyncio
async def test_overlapping_agreements_where_one_covers_is_not_a_gap(
    db_session, test_tenant, test_user, test_booking_type
):
    """A1 made overlaps legal and refuses only an exact duplicate, so 'which
    agreement applies' is ambiguous by construction. Coverage is 'ANY single
    live agreement covers it' — the only reading that manufactures no false
    warnings."""
    project = await ensure_project(db_session, test_tenant.id, name="Overlapping")
    env = await ensure_environment(db_session, test_tenant.id)
    # Neither of these covers August...
    await _agreement(
        db_session, test_tenant.id, project.id, env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )
    # ...except this one, which does.
    await _agreement(
        db_session, test_tenant.id, project.id, env.id,
        starts_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=project.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, booking, test_tenant.id)
    ) is None
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == set()


@pytest.mark.asyncio
async def test_the_message_names_the_nearest_window_not_the_first_one(
    db_session, test_tenant, test_user, test_booking_type
):
    """Several windows may miss a booking. Naming the CLOSEST tells the reader
    the smallest change that would fix it; naming whichever the database
    returned first is arbitrary and, with overlaps legal by construction,
    unstable. The nearer window is created SECOND here, so an implementation
    that simply takes the lowest id fails."""
    project = await ensure_project(db_session, test_tenant.id, name="Nearest")
    env = await ensure_environment(db_session, test_tenant.id)
    # Ends 36 days before the booking ends.
    await _agreement(
        db_session, test_tenant.id, project.id, env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )
    # Starts 31 days after the booking starts — closer, but created later.
    await _agreement(
        db_session, test_tenant.id, project.id, env.id,
        starts_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert "1 Sep 2026 – 31 Dec 2026" in message
    assert "30 Jun 2026" not in message


@pytest.mark.asyncio
async def test_a_soft_deleted_agreement_is_not_coverage(
    db_session, test_tenant, test_user, test_booking_type
):
    project = await ensure_project(db_session, test_tenant.id, name="Withdrawn")
    env = await ensure_environment(db_session, test_tenant.id)
    agreement = await _agreement(db_session, test_tenant.id, project.id, env.id)
    agreement.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    # The wording must not promise a window from an agreement the rule refuses
    # to honour: "live" means the same thing to the message as to the predicate.
    assert "no usage agreement" in message
    assert "outside" not in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_an_agreement_whose_environment_was_soft_deleted_is_not_coverage(
    db_session, test_tenant, test_user, test_booking_type
):
    """'Live' is NOT `deleted_at IS NULL` on the agreement alone.

    The environment is soft-deleted DIRECTLY here, never via delete_project —
    that cascade sets the agreement's own deleted_at too and would hide the row
    a second way, masking the very join filter under test. That masking shape
    appeared three times on A2.

    The agreement's own deleted_at is asserted null below, so only the
    Environment join can produce the gap.
    """
    project = await ensure_project(db_session, test_tenant.id, name="Orphaned Env")
    env = await ensure_environment(db_session, test_tenant.id)
    agreement = await _agreement(db_session, test_tenant.id, project.id, env.id)
    env.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )

    assert agreement.deleted_at is None, "the cascade must not be what hides this row"
    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    # A dead counterparty means the rule cannot fire — and since no LIVE
    # agreement exists, the message is the no-agreement one, not a window one.
    assert "no usage agreement" in message
    # The environment's name still renders: an archived thing is still named on
    # the live row that references it (A1's get_project_names rule).
    assert env.name in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_an_agreement_whose_project_was_soft_deleted_is_not_coverage(
    db_session, test_tenant, test_user, test_booking_type
):
    """Soft-deleted directly, bypassing delete_project's cascade, for the same
    reason as the environment case above: this isolates the Project join."""
    project = await ensure_project(db_session, test_tenant.id, name="Orphaned Project")
    env = await ensure_environment(db_session, test_tenant.id)
    agreement = await _agreement(db_session, test_tenant.id, project.id, env.id)
    project.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )

    assert agreement.deleted_at is None, "the cascade must not be what hides this row"
    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    # The archived project still renders its name (A1's get_project_names rule)
    # while its agreement counts for nothing — so the wording is the
    # no-agreement one, not a window one.
    assert "Orphaned Project" in message
    assert "no usage agreement" in message
    assert "outside" not in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_an_agreement_belonging_to_another_tenant_is_not_coverage(
    db_session, test_tenant, test_user, test_booking_type, second_tenant_factory
):
    """A malformed row — our project, our environment, another tenant's
    tenant_id — must not grant coverage. Assume every tenant filter is
    unguarded until a named test fails without it."""
    project = await ensure_project(db_session, test_tenant.id, name="Ours")
    env = await ensure_environment(db_session, test_tenant.id)
    other_tenant, _other_admin = await second_tenant_factory()
    await _agreement(db_session, other_tenant.id, project.id, env.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    # Nor may the MESSAGE read another tenant's agreement and announce a window
    # from it — the wording is derived under the same liveness and tenant rules
    # as the predicate.
    assert "no usage agreement" in message
    assert "outside" not in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_an_agreement_whose_project_belongs_to_another_tenant_is_not_coverage(
    db_session, test_tenant, test_user, test_booking_type, second_tenant_factory
):
    """Guards the Project join's own tenant filter, independent of the
    agreement's: the row's tenant_id is ours, its project is not."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Their Project")
    env = await ensure_environment(db_session, test_tenant.id)
    # Malformed: our tenant_id and our environment, but another tenant's
    # project — and an unbounded window, so ONLY the Project join's tenant
    # filter can stop it covering the booking below.
    await _agreement(db_session, test_tenant.id, theirs.id, env.id)
    cross = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=theirs.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, cross, test_tenant.id)
    ) is not None
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {cross.id}


@pytest.mark.asyncio
async def test_a_cross_tenant_projects_window_is_never_quoted_in_the_message(
    db_session, test_tenant, test_user, test_booking_type, second_tenant_factory
):
    """The WORDING path carries its own `Project.tenant_id` filter, and this is
    what guards it.

    The test above uses an UNBOUNDED agreement, so it has no dates to leak — it
    guards the predicate's copy of this filter and cannot guard the message's.
    Two mechanisms answering one question means one test cannot guard both.
    Bounded here, so dropping the wording filter has something to quote: the
    message would become "…falls outside its agreed window… (1 Jan 2026 – 30 Jun
    2026)", announcing a window from a row the predicate itself refuses to
    honour.
    """
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Their Project")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(
        db_session, test_tenant.id, theirs.id, env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )
    # INSIDE the window, so only the Project join's tenant filter — on each
    # path — can keep this booking in gap and this window out of the message.
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        start=INSIDE_START, end=INSIDE_END, project_id=theirs.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert "no usage agreement" in message
    assert "outside" not in message
    assert "1 Jan 2026" not in message
    assert "30 Jun 2026" not in message
    assert "Their Project" not in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_an_agreement_whose_environment_belongs_to_another_tenant_is_not_coverage(
    db_session, test_tenant, test_user, test_booking_type, second_tenant_factory
):
    """Guards the Environment join's own tenant filter."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id)
    project = await ensure_project(db_session, test_tenant.id, name="Ours")
    # Malformed: our tenant_id, their environment. The booking is against that
    # same environment id, so only the join's tenant filter can refuse it.
    await _agreement(db_session, test_tenant.id, project.id, theirs.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, theirs,
        project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    # And the environment NAME join carries its own tenant filter, so the
    # malformed reference renders no name rather than another tenant's.
    assert theirs.name not in message
    assert "this environment" in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_a_cross_tenant_environments_window_is_never_quoted_in_the_message(
    db_session, test_tenant, test_user, test_booking_type, second_tenant_factory
):
    """The same shape as the project case above, for the WORDING path's
    `Environment.tenant_id` filter.

    The unbounded test above cannot guard it: under a mutant the message merely
    switches from the no-agreement wording to a windowless "outside its agreed
    window", and both of that test's assertions (`theirs.name not in message`,
    `"this environment" in message`) still hold. Bounded here, so the mutant has
    dates to leak and the assertions below can see it.
    """
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id)
    project = await ensure_project(db_session, test_tenant.id, name="Ours")
    await _agreement(
        db_session, test_tenant.id, project.id, theirs.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )
    # INSIDE the window, so only the Environment join's tenant filter — on each
    # path — can keep this booking in gap and this window out of the message.
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, theirs,
        start=INSIDE_START, end=INSIDE_END, project_id=project.id,
    )

    message = await agreement_gap_service.describe_gap(
        db_session, booking, test_tenant.id
    )
    assert message is not None
    assert "no usage agreement" in message
    assert "outside" not in message
    assert "1 Jan 2026" not in message
    assert "30 Jun 2026" not in message
    assert theirs.name not in message
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {booking.id}


@pytest.mark.asyncio
async def test_another_tenants_booking_is_never_described(
    db_session, test_tenant, test_user, test_booking_type, second_tenant_factory
):
    """Both read paths are tenant-scoped: asking about a booking that is not
    ours answers nothing, rather than leaking another tenant's project and
    environment names in a message."""
    other_tenant, other_admin = await second_tenant_factory()
    their_type = await ensure_booking_type(db_session, other_tenant.id)
    their_project = await ensure_project(db_session, other_tenant.id, name="Theirs")
    their_env = await ensure_environment(db_session, other_tenant.id)
    theirs = await _booking(
        db_session, other_tenant, other_admin, their_type, their_env,
        project_id=their_project.id,
    )

    assert (
        await agreement_gap_service.describe_gap(db_session, theirs, test_tenant.id)
    ) is None
    assert await agreement_gap_service.gaps_for_bookings(
        db_session, [theirs], test_tenant.id
    ) == {}
    # ...and it IS in gap for its own tenant, so the assertion above is not
    # vacuously true.
    assert (
        await agreement_gap_service.describe_gap(db_session, theirs, other_tenant.id)
    ) is not None


@pytest.mark.asyncio
async def test_a_malformed_booking_pointing_at_another_tenants_request_leaks_no_name(
    db_session, test_tenant, test_user, test_booking_type, second_tenant_factory
):
    """A booking of OURS whose request belongs to another tenant.

    The two mechanisms must agree about it — the Booking→BookingRequest join is
    the CONSUMER's, and `GET /bookings` does not tenant-qualify it (see
    booking_service.list_bookings' project_id filter), so tenant-qualifying it
    inside the batch query would make `describe_gap` say "covered" about a row
    the list reports as in gap. That divergence, not the row itself, is the
    hazard: no agreement of ours can reference another tenant's project, so a
    gap is the truthful answer either way.

    What must NOT happen is the other tenant's project or environment name
    reaching our message — the name joins carry their own tenant filter for
    exactly that, and this test is what guards them.
    """
    other_tenant, other_admin = await second_tenant_factory()
    their_type = await ensure_booking_type(db_session, other_tenant.id)
    their_project = await ensure_project(db_session, other_tenant.id, name="Theirs")
    their_env = await ensure_environment(db_session, other_tenant.id)
    theirs = await _booking(
        db_session, other_tenant, other_admin, their_type, their_env,
        project_id=their_project.id,
    )
    # A distinct slot, so "their name is absent" cannot pass by coincidence —
    # ensure_environment names by slot, and both tenants' slot 1 share a name.
    env = await ensure_environment(db_session, test_tenant.id, slot=3)

    malformed = Booking(
        tenant_id=test_tenant.id,
        environment_id=env.id,
        start_date=INSIDE_START,
        end_date=INSIDE_END,
        booking_request_id=theirs.booking_request_id,
    )
    db_session.add(malformed)
    await db_session.flush()

    message = await agreement_gap_service.describe_gap(
        db_session, malformed, test_tenant.id
    )
    assert message is not None
    assert malformed.id in await _gap_ids_in_sql(db_session, test_tenant.id)
    assert "Theirs" not in message, "another tenant's project name reached our message"
    assert their_env.name not in message
    # Ours renders normally, so the assertion above is not vacuously true.
    assert env.name in message


@pytest.mark.asyncio
async def test_the_batch_answer_and_the_sql_filter_agree_over_a_mixed_population(
    db_session, test_tenant, test_user, test_booking_type
):
    """Covered, out-of-window, unagreed and project-less bookings in one set.

    Asserted AGAINST EACH OTHER, not separately: A1 shipped a count and a list,
    written three tasks apart, that disagreed two ways with zero coverage. Two
    mechanisms answering one question means one test cannot guard both.
    """
    project = await ensure_project(db_session, test_tenant.id, name="Mixed")
    agreed_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    unagreed_env = await ensure_environment(db_session, test_tenant.id, slot=2)
    await _agreement(
        db_session, test_tenant.id, project.id, agreed_env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )

    covered = await _booking(
        db_session, test_tenant, test_user, test_booking_type, agreed_env,
        start=INSIDE_START, end=INSIDE_END, project_id=project.id,
    )
    out_of_window = await _booking(
        db_session, test_tenant, test_user, test_booking_type, agreed_env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=project.id,
    )
    unagreed = await _booking(
        db_session, test_tenant, test_user, test_booking_type, unagreed_env,
        start=INSIDE_START, end=INSIDE_END, project_id=project.id,
    )
    no_project = await _booking(
        db_session, test_tenant, test_user, test_booking_type, agreed_env,
        start=OUTSIDE_START, end=OUTSIDE_END, project_id=None,
    )
    every = [covered, out_of_window, unagreed, no_project]

    batch = await agreement_gap_service.gaps_for_bookings(
        db_session, every, test_tenant.id
    )
    assert set(batch) == {out_of_window.id, unagreed.id}
    assert "outside" in batch[out_of_window.id]
    assert "no usage agreement" in batch[unagreed.id]

    one_by_one = {
        b.id: await agreement_gap_service.describe_gap(db_session, b, test_tenant.id)
        for b in every
    }
    assert batch == {k: v for k, v in one_by_one.items() if v is not None}
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == set(batch)


@pytest.mark.asyncio
async def test_adding_the_missing_agreement_clears_the_gap_with_no_other_action(
    db_session, test_tenant, test_user, test_booking_type
):
    """The property the computed-not-stored design exists to give."""
    project = await ensure_project(db_session, test_tenant.id, name="Late Paperwork")
    env = await ensure_environment(db_session, test_tenant.id)
    booking = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )
    assert (
        await agreement_gap_service.describe_gap(db_session, booking, test_tenant.id)
    ) is not None

    await _agreement(db_session, test_tenant.id, project.id, env.id)

    assert (
        await agreement_gap_service.describe_gap(db_session, booking, test_tenant.id)
    ) is None


@pytest.mark.asyncio
async def test_gaps_for_bookings_answers_only_about_the_bookings_it_was_given(
    db_session, test_tenant, test_user, test_booking_type
):
    """`_windows_for_pairs` promises its pair set is "bounded by the page, not
    by the estate", and that promise rests entirely on `Booking.id.in_(...)`.

    Without it the first query scans every in-gap booking in the tenant. The
    caller still `.get()`s its own ids, so the answer stays *right* and only the
    cost goes wrong — which is exactly why nothing else here would notice. Two
    in-gap bookings, one asked about.
    """
    project = await ensure_project(db_session, test_tenant.id, name="Only Mine")
    env = await ensure_environment(db_session, test_tenant.id)
    asked_about = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )
    not_asked_about = await _booking(
        db_session, test_tenant, test_user, test_booking_type, env,
        project_id=project.id,
    )

    # Both are in gap, so the restriction is the only thing that can exclude one.
    assert await _gap_ids_in_sql(db_session, test_tenant.id) == {
        asked_about.id,
        not_asked_about.id,
    }
    assert set(
        await agreement_gap_service.gaps_for_bookings(
            db_session, [asked_about], test_tenant.id
        )
    ) == {asked_about.id}


@pytest.mark.asyncio
async def test_gaps_for_bookings_of_an_empty_list_asks_the_database_nothing(
    db_session, test_tenant
):
    assert await agreement_gap_service.gaps_for_bookings(
        db_session, [], test_tenant.id
    ) == {}
