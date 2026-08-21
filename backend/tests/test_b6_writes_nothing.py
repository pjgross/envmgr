"""B6 TOUCHES NOTHING.

B6 adds no table, no column, no stored verdict, and no write path of any kind.
It reads bookings and A4's escalations and renders them somewhere new — the
first PURE-READ sub-project in Phase 7, after A3 (warns), A4 (advises), B2
(advises) and B5 (acts, narrowly). Where those four files guard an absence or
a limit, this one guards a stronger claim: NOTHING CHANGES AT ALL, anywhere,
through any of B6's three entry points.

IF ANY TEST HERE FAILS, B6 HAS STARTED WRITING.

Prove this file non-vacuous before trusting it: make `contention_states_for_
bookings` stamp anything at all onto a booking it inspects, watch
`test_reading_contention_changes_no_row` fail, then revert. Done here by
loading a `Booking` and setting `recurrence_rule` inside the fold, flushing,
and confirming the guard fails; see the task report for the exact output and
the confirmation that `git diff` came back clean afterwards.
"""
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory

from sqlalchemy import select

from app.db.models.booking_request import BookingRequest
from app.db.models.contention_escalation import ContentionEscalation
from app.services import contention_forecast_service, contention_service
from tests.factories import ensure_deployment, ensure_environment, make_booking


# ── The full-row snapshot helper ────────────────────────────────────────────
#
# Every column, not one — copied from test_b5_acts_only_where_it_says.py,
# B5's guard on the same class of claim. Asserting on a single column is how
# a guard passes while the thing it guards has changed underneath it.


def _normalize(value):
    """SQLite hands back naive datetimes on `refresh()` while a freshly
    constructed Python object still holds the aware value it was built with.
    Every column is normalised to aware-UTC before comparison so the
    snapshot is correct regardless of refresh ordering on either side."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _snapshot(db_session, rows) -> dict:
    """`{(table name, id): {column: value}}` for every row passed, after an
    explicit refresh — so a mutation made at the SQL level (a bulk UPDATE
    bypassing the identity map) is caught, not just an in-memory attribute
    assignment. Keyed on `(tablename, id)` rather than bare `id` because
    environments, bookings, deployments and escalations in this file share
    one integer id space and a bare-id key could silently collide two
    different rows' snapshots into one dict entry.
    """
    for row in rows:
        await db_session.refresh(row)
    return {
        (row.__tablename__, row.id): {
            c.name: _normalize(getattr(row, c.name)) for c in row.__table__.columns
        }
        for row in rows
    }


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def populated_estate(db_session, test_tenant, test_user, second_tenant_factory):
    """Two tenants' worth of environments, bookings — including a clashing
    pair, so the fold has something to actually find — deployments, and one
    A4 escalation raised against that clash. "Nothing changed" is trivially
    true over an empty database; this makes it a claim about a database WITH
    DATA IN IT.

    Built under `test_tenant`/`test_user`, not the plain `tenant` fixture,
    because `test_listing_bookings_with_contention_changes_no_row` below goes
    through HTTP with `auth_headers`, which logs in as `test_user` in
    `test_tenant` (see conftest.py) — an estate built under `tenant` would
    render as an empty page through that client, and "nothing changed" would
    again be a claim about no data.
    """
    other_tenant, other_admin = await second_tenant_factory(
        "B6 Guard Second Org", "b6-guard-second-org"
    )

    env_a = await ensure_environment(db_session, test_tenant.id, slot=931)
    env_b = await ensure_environment(db_session, test_tenant.id, slot=932)
    other_env = await ensure_environment(db_session, other_tenant.id, slot=933)

    now = datetime.now(timezone.utc)

    # The clashing pair: same environment, overlapping windows — the one
    # thing every B6 entry point below is meant to find and fold.
    clash_1 = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env_a,
        start=now - timedelta(days=1), end=now + timedelta(days=3),
    )
    clash_2 = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env_a,
        start=now, end=now + timedelta(days=5),
    )
    # A non-clashing booking, so a passing guard isn't merely "every booking
    # in the estate happens to be in the one pair under test".
    solo = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env_b,
        start=now - timedelta(days=40), end=now - timedelta(days=35),
    )
    other_booking = await make_booking(
        db_session, other_tenant.id, booked_by=other_admin.id, environment=other_env,
        start=now - timedelta(days=2), end=now + timedelta(days=2),
    )

    deployment_a = await ensure_deployment(
        db_session, test_tenant.id, env_a.id, deployed_at=now - timedelta(days=1)
    )
    other_deployment = await ensure_deployment(
        db_session, other_tenant.id, other_env.id, deployed_at=now - timedelta(days=1)
    )

    lower, higher = contention_service.normalise_pair(clash_1.id, clash_2.id)
    escalation = await contention_service.create_escalation(
        db_session,
        booking_id=lower,
        other_booking_id=higher,
        owner_user_id=test_user.id,
        respond_by=now + timedelta(days=3),
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    await db_session.flush()

    # BookingRequest — one per booking, created inside `make_booking` — is
    # EXACTLY where this codebase stores per-request state instead of on the
    # booking (protection_level, project_id: see CLAUDE.md's B4 note, "THE
    # LEVEL LIVES ON THE REQUEST, NOT THE BOOKING"). A B6 write landing here
    # is the most plausible shape a violation would take, and it would pass
    # every behavioural test that only snapshots `booking` — so it is
    # snapshotted explicitly, fetched by id rather than via the `booking_
    # request` relationship (which is not guaranteed loaded on an object
    # this session merely constructed and flushed, not queried back).
    all_bookings = [clash_1, clash_2, solo, other_booking]
    request_ids = [b.booking_request_id for b in all_bookings]
    requests = (
        await db_session.execute(
            select(BookingRequest).where(BookingRequest.id.in_(request_ids))
        )
    ).scalars().all()

    return {
        "environments": [env_a, env_b, other_env],
        "bookings": all_bookings,
        "booking_requests": list(requests),
        "deployments": [deployment_a, other_deployment],
        "escalations": [escalation],
    }


def _all_rows(estate: dict) -> list:
    """Every table `populated_estate` puts a row in that a B6 write could
    plausibly reach — SEE THE FULL TABLE INVENTORY in the fixture's own
    docstring and the task report for the tables deliberately excluded here
    (tenant, user, environment_tier, booking_type, lifecycle_template,
    system, subsystem, build, change_request) and why: each is an FK-parent
    row built by an idempotent `ensure_*` helper during fixture SETUP, and
    none is ever read, joined or referenced by any of B6's three entry
    points (`overlapping_pairs`, `contention_states_for_bookings`,
    `contention_count_in_window`, `escalations_for_pairs`)."""
    return (
        estate["environments"]
        + estate["bookings"]
        + estate["booking_requests"]
        + estate["deployments"]
        + estate["escalations"]
    )


# ── The guard ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reading_contention_changes_no_row(db_session, test_tenant, populated_estate):
    """Snapshot EVERY column of every booking, booking_request, environment,
    escalation and deployment; fold contention over the whole estate;
    compare the whole mapping. Asserting on one column is how a guard passes
    while the thing it guards has changed — and `booking_request` is the
    single most plausible place a stray write would land (see
    `_all_rows`'s docstring)."""
    all_rows = _all_rows(populated_estate)
    before = await _snapshot(db_session, all_rows)

    booking_ids = [b.id for b in populated_estate["bookings"]]
    now = datetime.now(timezone.utc)
    states = await contention_forecast_service.contention_states_for_bookings(
        db_session, test_tenant.id, booking_ids, now=now,
    )
    # Non-vacuity WITHIN the test: the fold must actually have found the
    # seeded clash, or a fold that silently found nothing would pass this
    # guard for the wrong reason.
    assert states, "sanity: the fold should have found the seeded contention"

    after = await _snapshot(db_session, all_rows)
    assert before == after


@pytest.mark.asyncio
async def test_the_horizon_count_changes_no_row(db_session, test_tenant, populated_estate):
    """Same shape, for `contention_count_in_window` — the leading-indicator
    count behind `/bookings/contention-horizon`."""
    all_rows = _all_rows(populated_estate)
    before = await _snapshot(db_session, all_rows)

    now = datetime.now(timezone.utc)
    count = await contention_forecast_service.contention_count_in_window(
        db_session, test_tenant.id,
        start=now - timedelta(days=5), end=now + timedelta(days=10),
    )
    assert count >= 1, "sanity: the seeded clash should fall inside this window"

    after = await _snapshot(db_session, all_rows)
    assert before == after


@pytest.mark.asyncio
async def test_listing_bookings_with_contention_changes_no_row(
    client, auth_headers, db_session, populated_estate
):
    """Through HTTP, since that is the path a user actually takes. `GET
    /bookings` folds contention for the whole page
    (`booking_service.list_bookings` →
    `contention_forecast_service.contention_states_for_bookings`) before the
    response is even built — this is the entry point that matters most,
    because it is the one a browser reaches."""
    all_rows = _all_rows(populated_estate)
    before = await _snapshot(db_session, all_rows)

    response = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    contention_states = {row["contention_state"] for row in payload if row["contention_state"]}
    assert contention_states, "sanity: the seeded clash should render a contention_state"

    after = await _snapshot(db_session, all_rows)
    assert before == after


@pytest.mark.asyncio
async def test_b6_adds_no_migration():
    """STRUCTURAL, and a SMOKE ALARM rather than a proof: `envdecommission`
    — B5's own migration and the revision `alembic heads` reported before any
    B6 commit landed — is the root of everything that has landed since, and
    what proves B6 itself introduced no schema change is that the chain from
    `envdecommission` forward is *exactly* the migrations that legitimately
    followed it, each chaining directly onto the last with no branch: if B6
    had added one, `envdecommission` would have two children, or one of the
    links below would not hold. Reads the migration chain directly (no
    database connection needed), so it runs identically on the SQLite-only
    leg and the PostgreSQL leg.

    Updated 2026-08-20 when `gatetypes` landed: the original assertion pinned
    the literal head to `envdecommission`, which was only ever going to hold
    until the next legitimate migration — B6 does not own the migration chain
    forever, only the claim that IT added nothing to it.

    Updated again 2026-08-21 when Phase 9 sub-project C4's `rollbackgov`
    (rollback governance schema) chained onto `gatetypes`, moving the head
    again. Rather than re-pin a single literal a third time, this now asserts
    the whole post-`envdecommission` chain's SHAPE — each known revision's
    `down_revision` in order — so the next legitimate migration only needs
    its own link appended here, and any change that inserts, reorders or
    branches a revision without updating this list still fails loudly.

    THIS IS A SMOKE ALARM, NOT A PROOF: it is a bounded check on the
    migration CHAIN alone. It would not catch a raw DDL statement executed at
    runtime (a `CREATE TABLE` buried in a service function, say), and it says
    so rather than implying "no new migration" means "no schema change of any
    kind".
    """
    backend_dir = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "app" / "db" / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads == ["rollbackgov"], (
        "the Alembic head is not the expected single migration on top of "
        "envdecommission — either B6 has started adding schema changes, or "
        "an unrelated migration landed without updating this pin"
    )
    # The chain from B5's envdecommission forward, each entry's own
    # down_revision naming the one before it. Root first.
    expected_chain = ["envdecommission", "gatetypes", "rollbackgov"]
    for child, parent in zip(expected_chain[1:], expected_chain[:-1]):
        assert script.get_revision(child).down_revision == parent, (
            f"{child} must chain directly onto {parent} — B6 (or something "
            "else) added an undocumented migration between the two, or the "
            "chain was reordered"
        )


@pytest.mark.asyncio
async def test_no_b6_module_writes(db_session):
    """STRUCTURAL, and a SMOKE ALARM rather than a proof: grep
    `contention_forecast_service.py` for `db.add`, `db.delete`, `update(`,
    `insert(`, `delete(` and `db.flush`. A substring scan of one file with no
    call-graph following; an aliased import, a write reached through a
    helper it calls, or one of these tokens written with unusual whitespace
    would not be caught. Labelled as such, following B4's and B5's
    precedent (`test_no_production_module_refuses_on_a_protection_level`,
    `test_no_write_path_consults_idle`).

    `db_session` is accepted but unused — kept to match the signature this
    file's brief specifies, for parity with the other tests here that DO
    need a session; this one is pure static analysis.
    """
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app" / "services" / "contention_forecast_service.py"
    )
    text = path.read_text()
    write_markers = ("db.add", "db.delete", "update(", "insert(", "delete(", "db.flush")
    offenders = [marker for marker in write_markers if marker in text]
    assert not offenders, (
        f"contention_forecast_service.py contains a write marker {offenders} "
        "— B6 must remain pure-read"
    )
