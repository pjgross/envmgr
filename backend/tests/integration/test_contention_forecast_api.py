"""B6 Task 3 — the horizon count on the API surface. READS ONLY.

`GET /bookings/contention-horizon?weeks=<int>` answers "N contentions in the
next <weeks> weeks" — the leading-indicator half of B6, sitting beside the
per-pair machinery Tasks 1/2 shipped in `contention_forecast_service.py`.

THE WINDOW TESTS THE OVERLAP INTERVAL, NEVER EITHER BOOKING'S OWN SPAN. The
service decomposes `max(s1,s2) < end AND min(e1,e2) > start` into four
per-booking comparisons to avoid GREATEST/LEAST (SQLite has neither), and that
decomposition shipped in Task 1 with NO test at all — this file is the first
and only guard on it.
`test_the_horizon_tests_the_overlap_interval_not_either_booking` is the one
that matters most: it is built so that the long-running booking (created
first, so it holds the LOWER id and lands in the `b1` role the query's
`b1.id < b2.id` normalisation always produces) starts inside the horizon on
its own, while the pair's actual overlap does not begin until long after it.
A window test that only consulted `b1`'s own span — instead of both bookings'
— would report this pair as a contention today; the correct one must not.

THE COUNT IS OF CONTENTIONS, NEVER OF BOOKINGS. Two bookings clashing is ONE
contention; `test_the_count_is_of_contentions_not_bookings` builds two
SEPARATE clashes (on two different environments, 4 bookings total) so the
booking count (4) and the contention count (2) genuinely differ. Three
mutually overlapping bookings would not discriminate: that shape is three
pairs AND three bookings.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from tests.factories import ensure_environment, ensure_user, make_booking


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_the_count_is_of_contentions_not_bookings(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """TWO BOOKINGS CLASHING IS ONE CONTENTION. Counting marked bookings
    double-counts every pair and inflates the headline number this feature
    exists to make trustworthy. Build a fixture where the two numbers differ:
    three mutually overlapping bookings are THREE pairs and THREE bookings, so
    use two separate clashes instead — 4 bookings, 2 contentions."""
    now = _now()
    env1 = await ensure_environment(db_session, test_tenant.id, slot=1)
    env2 = await ensure_environment(db_session, test_tenant.id, slot=2)

    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env1,
        start=now + timedelta(days=1), end=now + timedelta(days=3),
    )
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env1,
        start=now + timedelta(days=2), end=now + timedelta(days=4),
    )
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env2,
        start=now + timedelta(days=1), end=now + timedelta(days=3),
    )
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env2,
        start=now + timedelta(days=2), end=now + timedelta(days=4),
    )

    r = await client.get("/api/v1/bookings/contention-horizon?weeks=6", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"count": 2, "weeks": 6}


@pytest.mark.asyncio
async def test_a_clash_beyond_the_horizon_is_not_counted(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """Two bookings that start clashing in four months are not a contention in
    the next six weeks."""
    now = _now()
    env = await ensure_environment(db_session, test_tenant.id, slot=1)

    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(weeks=17), end=now + timedelta(weeks=18),
    )
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(weeks=17, days=1), end=now + timedelta(weeks=18, days=1),
    )

    r = await client.get("/api/v1/bookings/contention-horizon?weeks=6", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["count"] == 0


@pytest.mark.asyncio
async def test_the_horizon_tests_the_overlap_interval_not_either_booking(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """LOAD-BEARING. A booking starting tomorrow that runs for a year, clashing
    with one that starts in four months, is NOT a contention in the next six
    weeks — the pair does not overlap until month four. Defining the horizon on
    either booking's start would report a clash that cannot happen yet.

    `long_running` is created FIRST, so it holds the lower id and is always the
    `b1` side of `overlapping_pairs`' `b1.id < b2.id` normalisation — the side
    a naive "test just this booking's own span" implementation would most
    plausibly consult. `long_running`'s own span (tomorrow .. +400 days) is
    well inside a 6-week horizon on its own; only the true overlap interval
    (~weeks 17-20, set by `later`) puts this pair outside it.
    """
    now = _now()
    env = await ensure_environment(db_session, test_tenant.id, slot=1)

    long_running = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(days=1), end=now + timedelta(days=400),
    )
    later = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(weeks=17), end=now + timedelta(weeks=20),
    )
    assert long_running.id < later.id

    r = await client.get("/api/v1/bookings/contention-horizon?weeks=6", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["count"] == 0


@pytest.mark.asyncio
async def test_widening_the_horizon_finds_more(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """?weeks=26 sees a clash that ?weeks=2 does not."""
    now = _now()
    env = await ensure_environment(db_session, test_tenant.id, slot=1)

    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(weeks=10), end=now + timedelta(weeks=11),
    )
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(weeks=10, days=1), end=now + timedelta(weeks=11, days=1),
    )

    narrow = await client.get("/api/v1/bookings/contention-horizon?weeks=2", headers=auth_headers)
    wide = await client.get("/api/v1/bookings/contention-horizon?weeks=26", headers=auth_headers)

    assert narrow.status_code == 200
    assert wide.status_code == 200
    assert narrow.json()["count"] == 0
    assert wide.json()["count"] == 1


@pytest.mark.asyncio
async def test_an_out_of_range_weeks_value_is_422(client: AsyncClient, auth_headers: dict):
    r = await client.get("/api/v1/bookings/contention-horizon?weeks=0", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_another_tenants_contentions_are_not_counted(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, tenant
):
    """A clash built in a DIFFERENT tenant (`tenant`, "Phase3 Org") must not be
    counted by `auth_headers`' tenant (`test_tenant`, "Test Org"). Deliberately
    NOT paired with `auth_headers` for the clash itself — `tenant` and
    `auth_headers` belong to different tenants, and combining them would query
    across tenants and pass vacuously (conftest.py's docstring on `tenant`
    warns about exactly this pairing). The other tenant's clash is real, so if
    the tenant filter were ever dropped this would start seeing it and fail.
    """
    now = _now()
    other_env = await ensure_environment(db_session, tenant.id, slot=1)
    other_user = await ensure_user(db_session, tenant.id)
    await make_booking(
        db_session, tenant.id, booked_by=other_user.id, environment=other_env,
        start=now + timedelta(days=1), end=now + timedelta(days=3),
    )
    await make_booking(
        db_session, tenant.id, booked_by=other_user.id, environment=other_env,
        start=now + timedelta(days=2), end=now + timedelta(days=4),
    )

    r = await client.get("/api/v1/bookings/contention-horizon?weeks=6", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["count"] == 0
