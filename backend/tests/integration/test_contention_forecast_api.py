"""B6 Task 3/4 — the horizon count and the folded state, on the API surface.
READS ONLY.

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

TASK 4 — `contention_state` on `BookingResponse`, folded ONCE PER RESPONSE,
NEVER ONCE PER ROW. `test_the_list_carries_the_contention_state` asserts the
VALUE over HTTP (not merely that the key is present — B5 shipped `idle`
computed, filterable and absent from the response, and only a reviewer
asking "what consumes this?" caught it).
`test_the_list_issues_no_query_per_row` is the structural guard: a 1-row page
and a 5-row page of uncontended bookings must execute the SAME number of SQL
statements. No existing facility in this suite counts statements across an
HTTP request — `_spy_on_execute` in test_sorting.py wraps `db_session.execute`
directly, which is ORM-call-level, not SQL-statement-level, and doesn't cross
the `client` boundary — so `_count_statements` below adds one via
`event.listen(engine, "before_cursor_execute", ...)`, listening on the same
engine `client` and the test body share through `db_session`.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import event

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


@contextmanager
def _count_statements(db_session):
    """Count SQL statements executed against `db_session`'s engine while the
    context is open. See the module docstring for why this suite needed a new
    facility rather than reusing `_spy_on_execute` (test_sorting.py).

    `client` (conftest.py) overrides `get_db` to yield this exact `db_session`,
    so listening on its bound engine's `before_cursor_execute` counts every
    statement an HTTP request made through it, ORM-issued or not.
    """
    counted = {"n": 0}
    sync_engine = db_session.bind.sync_engine

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counted["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counted
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


@pytest.mark.asyncio
async def test_the_list_carries_the_contention_state(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """Over HTTP, asserting the VALUE — not merely that the key is present.

    Two clashing bookings, no escalation recorded against the pair, so
    Task 2's fold reports `unowned` for both. `BOOKING_SORTS` was
    deliberately not extended for this field, so no `?sort_by=` is needed —
    default ordering (start_date asc) is enough to find the row by id.
    """
    now = _now()
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    clashing = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(days=1), end=now + timedelta(days=3),
    )
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(days=2), end=now + timedelta(days=4),
    )

    r = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    contended = next(row for row in rows if row["id"] == clashing.id)
    assert contended["contention_state"] == "unowned"


@pytest.mark.asyncio
async def test_an_uncontended_booking_carries_null(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """Null, and the grid cell renders NOTHING for it — never an empty chip.

    `contention_states_for_bookings` deliberately has no "none" state; an
    absent key is the only way "no contention" is spelled. This is the other
    half of the `.get(booking.id)` call — prove it returns None, not that it
    merely omits raising.
    """
    now = _now()
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    lonely = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(days=1), end=now + timedelta(days=3),
    )

    r = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    row = next(row for row in rows if row["id"] == lonely.id)
    assert row["contention_state"] is None


@pytest.mark.asyncio
async def test_the_list_issues_no_query_per_row(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """Structural guard: a page of N bookings must not cost N contention
    lookups. A 1-row page and a 5-row page of (mutually uncontended, so the
    fold's own query count is flat regardless of N) bookings must execute the
    SAME number of SQL statements — A3's rule, which measured a 50-row page
    through a per-booking helper at ~150 queries.
    """
    now = _now()
    env = await ensure_environment(db_session, test_tenant.id, slot=1)

    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=now + timedelta(days=1), end=now + timedelta(days=2),
    )
    with _count_statements(db_session) as one_row:
        r1 = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert r1.status_code == 200
    assert len(r1.json()) == 1

    for i in range(4):
        await make_booking(
            db_session, test_tenant.id, booked_by=test_user.id, environment=env,
            start=now + timedelta(days=10 + 2 * i), end=now + timedelta(days=11 + 2 * i),
        )
    with _count_statements(db_session) as five_rows:
        r5 = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert r5.status_code == 200
    assert len(r5.json()) == 5

    assert one_row["n"] == five_rows["n"], (
        f"1-row page issued {one_row['n']} statements, 5-row page issued "
        f"{five_rows['n']} — contention_state is being folded per row, not "
        "once per response"
    )
