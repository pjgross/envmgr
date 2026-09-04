import pytest
from datetime import datetime, timedelta, timezone

from tests.factories import ensure_environment, make_booking

# NOTE: datetimes are sent via `params=` (httpx URL-encodes them), never
# interpolated into the URL string directly — `now.isoformat()` contains a
# literal `+00:00`, and an un-encoded `+` in a query string means a space, so
# `f"...?start={now.isoformat()}"` corrupts the value into an unparseable
# datetime. `tests/test_calendar_timeline_bounds.py` already established this
# pattern for the same reason.


@pytest.mark.asyncio
async def test_a_booking_spanning_the_range_matches_even_though_it_started_before(
    client, auth_headers, test_tenant, test_user, db_session
):
    """The whole point of an OVERLAP test rather than a "starts within" one.

    A booking running 1-10 September is live on the 4th. An implementation of
    `start_date >= :start` passes every test that only seeds bookings starting
    inside the window, and is wrong for exactly the rows this filter exists to
    find.
    """
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    spanning = await make_booking(
        db_session,
        test_tenant.id,
        booked_by=test_user.id,
        environment=env,
        start=now - timedelta(days=3),
        end=now + timedelta(days=6),
    )
    before = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now - timedelta(days=30), end=now - timedelta(days=20),
    )
    after = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(days=20), end=now + timedelta(days=30),
    )

    r = await client.get(
        "/api/v1/bookings/",
        params={"start": now.isoformat(), "end": now.isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert spanning.id in ids, "a booking spanning the probe instant is live now"
    assert before.id not in ids
    assert after.id not in ids


@pytest.mark.asyncio
async def test_a_zero_width_probe_is_what_the_live_now_tile_sends(
    client, auth_headers, test_tenant, test_user, db_session
):
    """`?start=<now>&end=<now>`. If overlap is written as a strict
    `start < :end AND end > :start`, a booking that starts EXACTLY at the
    probe instant fails `start_date < end` (now < now is False) and the
    dashboard tile silently undercounts a booking that has, in fact, just
    started."""
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    live = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now, end=now + timedelta(hours=2),
    )
    r = await client.get(
        "/api/v1/bookings/",
        params={"start": now.isoformat(), "end": now.isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert live.id in {row["id"] for row in r.json()}


@pytest.mark.asyncio
async def test_the_range_filter_runs_in_sql_before_the_page(
    client, auth_headers, test_tenant, test_user, db_session
):
    """X-Total-Count must describe the FILTERED set. If the filter ran in
    Python after the query, the header would count the unfiltered rows and
    every paged consumer would be wrong."""
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    for i in range(3):
        await make_booking(
            db_session, test_tenant.id, booked_by=test_user.id, environment=env,
            start=now - timedelta(days=100 + i), end=now - timedelta(days=90 + i),
        )
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now - timedelta(hours=1), end=now + timedelta(hours=1),
    )
    r = await client.get(
        "/api/v1/bookings/",
        params={"start": now.isoformat(), "end": now.isoformat(), "limit": 1},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_supplying_only_start_is_a_422(
    client, auth_headers, test_tenant, test_user, db_session
):
    """A half-specified range is far more likely a caller bug than an intent
    to filter on an open-ended window — silently ignoring it is the exact
    failure this task closes."""
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    r = await client.get(
        "/api/v1/bookings/",
        params={"start": now.isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_supplying_only_end_is_a_422(
    client, auth_headers, test_tenant, test_user, db_session
):
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    r = await client.get(
        "/api/v1/bookings/",
        params={"end": now.isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_active_true_excludes_draft_and_rejected_bookings(
    client, auth_headers, test_tenant, test_user, db_session
):
    """Finding 1 of the PR 3 whole-branch review: the Dashboard's "Bookings
    live now" tile counted `?start=&end=` alone, which includes a booking
    nobody has submitted (draft, the factory's default status) and one that
    was refused (rejected) — dates say nothing about whether a claim on the
    environment is real. `?active=true` excludes the codebase's own
    `INACTIVE_BOOKING_STATUSES` set."""
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    submitted = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now - timedelta(hours=1), end=now + timedelta(hours=1),
    )
    submitted.status = "submitted"
    draft = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now - timedelta(hours=1), end=now + timedelta(hours=1),
    )
    # draft is the factory's default status — left alone.
    rejected = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now - timedelta(hours=1), end=now + timedelta(hours=1),
    )
    rejected.status = "rejected"
    await db_session.flush()

    r = await client.get(
        "/api/v1/bookings/",
        params={"start": now.isoformat(), "end": now.isoformat(), "active": "true"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert submitted.id in ids
    assert draft.id not in ids
    assert rejected.id not in ids


@pytest.mark.asyncio
async def test_without_active_the_old_default_behaviour_is_unchanged(
    db_session, test_tenant, test_user, client, auth_headers
):
    """`active` is opt-in — every OTHER consumer of `GET /bookings/` (the
    BookingList grid included) must keep seeing every status by default."""
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    draft = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now - timedelta(hours=1), end=now + timedelta(hours=1),
    )

    r = await client.get(
        "/api/v1/bookings/",
        params={"start": now.isoformat(), "end": now.isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert draft.id in {row["id"] for row in r.json()}
