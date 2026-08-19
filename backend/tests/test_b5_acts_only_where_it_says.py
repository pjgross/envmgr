"""B5 ACTS ONLY WHERE IT SAYS, AND NO FURTHER.

The fifth sub-project running whose central promise is a named test — after
A1's test_an_agreement_changes_no_booking_behaviour, A4's
test_a_contention_changes_no_booking_behaviour, B2's
test_b2_advises_never_blocks and B4's test_b4_advises_never_blocks — but the
first that ACTS. A guard that only asserted absences would pass against a B5
that does nothing at all, so this file asserts the LIMIT of the acting
instead of an absence: B5 changes exactly two things outside its own
records —

  1. environment.status becomes DECOMMISSIONED at teardown;
  2. a booking whose window runs past scheduled_teardown_at is refused
     (Task 8's assert_bookable — not re-tested here; see
     test_decommission_booking_refusal.py for that behaviour. This file only
     needs to know that refusal exists, so the "documented refusal set" test
     below counts it).

NOTHING ELSE. No booking is cancelled, transitioned, shortened or deleted at
any step. Bookings already running still run. Idle detection changes
NOTHING WHATSOEVER — it is a derived read. A decommission never touches any
other environment. Cancelling restores nothing and breaks nothing beyond its
own three fields.

IF ANY TEST HERE FAILS, B5 HAS STARTED DOING SOMETHING ELSE. Do not "fix" it
by relaxing the assertion.

Proved non-vacuous rather than assumed: added a bug-injection loop to
tear_down (iterate every live booking on the environment and set
`booking.status = "cancelled"` via the ORM) and watched
test_teardown_cancels_no_booking AND
test_a_running_booking_still_runs_after_teardown both fail. Reverted; see the
task report for the exact failure output and the confirmation that `git
diff` came back clean afterwards.
"""
import pathlib
import re
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.booking import Booking
from app.db.models.booking_lifecycle import BookingStatusHistory
from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_decommission import (
    EnvironmentDecommission, EnvironmentDecommissionStep,
)
from app.services import (
    environment_decommission_service,
    environment_lifecycle_policy_service,
    environment_service,
)
from tests.factories import ensure_deployment, ensure_environment, ensure_user, make_booking


# ── The full-row snapshot helper ────────────────────────────────────────────
#
# Every column, not one. Asserting on a single column (status, say) is how a
# guard passes while the thing it guards has changed underneath it — Task 7
# shipped exactly that placeholder in
# test_teardown_reports_the_bookings_it_did_not_touch, whose docstring names
# this file as the place that replaces it with a field-by-field proof.


def _normalize(value):
    """SQLite hands back naive datetimes on `refresh()` while a freshly
    constructed Python object still holds the aware value it was built
    with — the same trap `contention_service._utc`'s docstring names, and
    the same one test_b4_advises_never_blocks.py's
    test_recording_a_contention_decision_still_changes_nothing works around
    by refreshing before its FIRST snapshot too, not just its second. Here
    every column is normalised to aware-UTC before comparison instead, so
    the snapshot is correct regardless of whether either side was refreshed
    — a comparison that requires ordering discipline to stay honest is a
    comparison waiting to go stale."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _snapshot(db_session, rows) -> dict:
    """`{(table name, id): {column: value}}` for every row passed, after an
    explicit refresh — so a mutation made at the SQL level (a bulk UPDATE
    bypassing the identity map) is caught, not just an in-memory attribute
    assignment. Keyed on `(tablename, id)` rather than bare `id` because
    environments, bookings and deployments in this file share one integer
    id space and a bare-id key could silently collide two different rows'
    snapshots into one dict entry.
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
#
# Every action in this file runs through the SERVICE layer with `test_user`
# (an Admin in test_tenant, per conftest.py) — `assert_may_run` and
# `assert_may_defend` both bypass on Admin, so none of these fixtures builds
# a real operating team the way test_decommission_api.py's `env_with_team`
# does. This file is not re-testing WHO may act (Tasks 5/6/7 already cover
# that); it is testing what acting changes. The name `env_with_team` is kept
# anyway for parity with its sibling file, even though no team is built —
# said explicitly here so a future reader isn't misled by the name alone.


@pytest_asyncio.fixture
async def env_with_team(db_session, test_tenant) -> Environment:
    """A plain environment in test_tenant. See the fixtures docstring above
    for why no operating team is actually built."""
    return await ensure_environment(db_session, test_tenant.id, slot=901)


@pytest_asyncio.fixture
async def bystander_env(db_session, test_tenant) -> Environment:
    """A SECOND environment in the SAME tenant, with its own owner, expiry
    and name-compliance verdict — the row
    test_a_decommission_changes_no_other_environment proves untouched by a
    decommission raised against `env_with_team`."""
    owner = await ensure_user(db_session, test_tenant.id, username="b5-guard-bystander-owner")
    env = await ensure_environment(db_session, test_tenant.id, slot=902)
    env.owner_user_id = owner.id
    env.expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    env.name_compliant = True
    await db_session.flush()
    await db_session.refresh(env)
    return env


@pytest_asyncio.fixture
async def bookings_on_env(db_session, test_tenant, test_user, env_with_team) -> list[Booking]:
    """Three bookings on `env_with_team`: one finished, one running now, one
    starting after the teardown date (five days out — the tenant's default
    notice period from `environment_lifecycle_policy_service.get_policy`'s
    unsaved-default value) — the three shapes every guard in this file must
    leave byte-identical."""
    now = datetime.now(timezone.utc)
    finished = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env_with_team,
        start=now - timedelta(days=10), end=now - timedelta(days=5),
    )
    running = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env_with_team,
        start=now - timedelta(days=1), end=now + timedelta(days=1),
    )
    future = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env_with_team,
        start=now + timedelta(days=20), end=now + timedelta(days=25),
    )
    await db_session.flush()
    return [finished, running, future]


@pytest_asyncio.fixture
async def running_booking(bookings_on_env) -> Booking:
    """The middle one of `bookings_on_env`, returned alone for readability."""
    return bookings_on_env[1]


@pytest_asyncio.fixture
async def live_decommission(
    db_session, test_tenant, test_user, env_with_team
) -> EnvironmentDecommission:
    """A live decommission on `env_with_team`, raised through the real
    `initiate` service call (as Admin) so it carries every invariant that
    call enforces, rather than being built by hand. No decommission steps
    are seeded for test_tenant in this file — `missing_required_steps`
    reads an empty vocabulary as "nothing required", so `tear_down` needs no
    attestations to proceed, and this file has no reason to seed a
    checklist Task 7's own tests already cover."""
    now = datetime.now(timezone.utc)
    return await environment_decommission_service.initiate(
        db_session, test_tenant.id, env_with_team.id, test_user,
        reason="B5 guard fixture", now=now,
    )


@pytest_asyncio.fixture
async def decommission_step(db_session, test_tenant) -> EnvironmentDecommissionStep:
    """One checklist step, for the sign_attestation guard test below —
    `live_decommission`'s own docstring notes no steps are seeded for
    test_tenant elsewhere in this file (teardown needs none to proceed), but
    signing one needs a real step_key to validate against. `is_required`
    doesn't matter here: this fixture never drives a teardown."""
    step = EnvironmentDecommissionStep(
        tenant_id=test_tenant.id, key="b5_guard_step", label="Guard step",
        is_required=False, is_active=True, display_order=1,
    )
    db_session.add(step)
    await db_session.flush()
    return step


@pytest_asyncio.fixture
async def populated_estate(db_session, test_tenant, test_user, second_tenant_factory):
    """Two tenants' worth of environments, bookings and deployments — so
    "nothing changed" is a claim about a database WITH DATA IN IT, not one
    about an empty table where every assertion is trivially true."""
    other_tenant, other_admin = await second_tenant_factory(
        "B5 Guard Second Org", "b5-guard-second-org"
    )

    env_a = await ensure_environment(db_session, test_tenant.id, slot=911)
    env_b = await ensure_environment(db_session, test_tenant.id, slot=912)
    other_env = await ensure_environment(db_session, other_tenant.id, slot=913)

    now = datetime.now(timezone.utc)
    booking_a = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env_a,
        start=now - timedelta(days=2), end=now + timedelta(days=2),
    )
    booking_b = await make_booking(
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
    await db_session.flush()
    return {
        "environments": [env_a, env_b, other_env],
        "bookings": [booking_a, booking_b, other_booking],
        "deployments": [deployment_a, other_deployment],
    }


# ── The guard ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initiating_changes_no_booking(
    db_session, test_tenant, test_user, env_with_team, bookings_on_env
):
    """Not the count, not the status, not the dates, not deleted_at — every
    column of every booking on the environment, before and after `initiate`
    runs."""
    before = await _snapshot(db_session, bookings_on_env)
    now = datetime.now(timezone.utc)
    await environment_decommission_service.initiate(
        db_session, test_tenant.id, env_with_team.id, test_user,
        reason="Guard test — initiate", now=now,
    )
    after = await _snapshot(db_session, bookings_on_env)
    assert before == after


@pytest.mark.asyncio
async def test_teardown_cancels_no_booking(
    db_session, test_tenant, test_user, live_decommission, bookings_on_env
):
    """Every booking on the environment is byte-identical after teardown —
    including the ones the response named as remaining. This REPLACES Task
    7's placeholder (test_teardown_reports_the_bookings_it_did_not_touch),
    which only asserted an id appeared in the response — that test's own
    docstring named this file as the place that proves the rows themselves
    never moved."""
    before = await _snapshot(db_session, bookings_on_env)
    now = datetime.now(timezone.utc)
    await environment_decommission_service.tear_down(
        db_session, live_decommission, test_user, now=now
    )
    after = await _snapshot(db_session, bookings_on_env)
    assert before == after


@pytest.mark.asyncio
async def test_a_running_booking_still_runs_after_teardown(
    db_session, test_tenant, test_user, live_decommission, running_booking
):
    """The environment is gone from the register; the booking is not.

    FULL-ROW COMPARE ON THE ENVIRONMENT TOO (fix wave item 3) — the same
    stronger pattern `test_cancelling_restores_nothing_and_breaks_nothing`
    already uses, applied here for the first time. The old version of this
    test asserted only `status` and `deleted_at`, a two-column spot-check
    that could not have caught teardown quietly touching a THIRD column
    (owner, expiry, name_compliant, custom_fields, ...). `status` is the one
    documented change; `updated_at` moves as a side effect of any ORM
    UPDATE. Anything else changing fails this test."""
    env = await db_session.get(Environment, live_decommission.environment_id)
    before_booking = await _snapshot(db_session, [running_booking])
    before_env = await _snapshot(db_session, [env])

    now = datetime.now(timezone.utc)
    await environment_decommission_service.tear_down(
        db_session, live_decommission, test_user, now=now
    )

    after_booking = await _snapshot(db_session, [running_booking])
    after_env = await _snapshot(db_session, [env])
    assert before_booking == after_booking

    env_key = (env.__tablename__, env.id)
    changed = {
        col for col, value in before_env[env_key].items()
        if value != after_env[env_key][col]
    }
    allowed_changes = {"status", "updated_at"}
    assert changed <= allowed_changes, (
        f"teardown touched unexpected environment column(s): "
        f"{changed - allowed_changes}"
    )
    assert after_env[env_key]["status"] == EnvironmentStatus.DECOMMISSIONED
    # gone from the ACTIVE register, not deleted
    assert after_env[env_key]["deleted_at"] is None


@pytest.mark.asyncio
async def test_teardown_transitions_no_booking(
    db_session, test_tenant, test_user, live_decommission, bookings_on_env
):
    """No BookingStatusHistory row is written by any decommission action."""
    booking_ids = [b.id for b in bookings_on_env]
    before = (
        await db_session.execute(
            select(BookingStatusHistory.id).where(
                BookingStatusHistory.booking_id.in_(booking_ids)
            )
        )
    ).scalars().all()
    assert before == [], "sanity: nothing should pre-exist to hide a false pass"

    now = datetime.now(timezone.utc)
    await environment_decommission_service.tear_down(
        db_session, live_decommission, test_user, now=now
    )

    after = (
        await db_session.execute(
            select(BookingStatusHistory.id).where(
                BookingStatusHistory.booking_id.in_(booking_ids)
            )
        )
    ).scalars().all()
    assert after == []


@pytest.mark.asyncio
async def test_requesting_an_extension_changes_no_booking_no_other_environment_no_deployment(
    db_session, test_tenant, test_user, live_decommission, bookings_on_env, populated_estate
):
    """Fix wave item 3: `request_extension` was never exercised by this
    guard — one of the three write paths on this file's own promise that
    went uncalled. `test_user` is Admin, which bypasses `assert_may_defend`
    the same way it bypasses `assert_may_run` elsewhere in this file."""
    other_rows = (
        populated_estate["environments"]
        + populated_estate["bookings"]
        + populated_estate["deployments"]
    )
    before_bookings = await _snapshot(db_session, bookings_on_env)
    before_other = await _snapshot(db_session, other_rows)

    now = datetime.now(timezone.utc)
    await environment_decommission_service.request_extension(
        db_session, live_decommission, test_user,
        reason="Guard test — request extension",
        until=live_decommission.scheduled_teardown_at + timedelta(days=3),
        now=now,
    )

    after_bookings = await _snapshot(db_session, bookings_on_env)
    after_other = await _snapshot(db_session, other_rows)
    assert before_bookings == after_bookings
    assert before_other == after_other


@pytest.mark.asyncio
async def test_deciding_an_extension_changes_no_booking_no_other_environment_no_deployment(
    db_session, test_tenant, test_user, live_decommission, bookings_on_env, populated_estate
):
    """Fix wave item 3: `decide_extension` is THE ONLY function in B5 that
    moves `scheduled_teardown_at` — and was never exercised by this guard.
    Granting on purpose (not refusing) is what makes the non-vacuity check
    below meaningful: this proves the date move itself touches nothing else,
    not merely that a no-op refusal touches nothing."""
    now = datetime.now(timezone.utc)
    await environment_decommission_service.request_extension(
        db_session, live_decommission, test_user,
        reason="Guard test — request extension",
        until=live_decommission.scheduled_teardown_at + timedelta(days=3),
        now=now,
    )

    other_rows = (
        populated_estate["environments"]
        + populated_estate["bookings"]
        + populated_estate["deployments"]
    )
    before_bookings = await _snapshot(db_session, bookings_on_env)
    before_other = await _snapshot(db_session, other_rows)

    await environment_decommission_service.decide_extension(
        db_session, live_decommission, test_user, granted=True, now=now,
    )

    after_bookings = await _snapshot(db_session, bookings_on_env)
    after_other = await _snapshot(db_session, other_rows)
    assert before_bookings == after_bookings
    assert before_other == after_other

    # Non-vacuity: prove the date actually moved, so this test cannot pass
    # against a decide_extension that silently no-ops instead of one that
    # acts and stays within bounds.
    await db_session.refresh(live_decommission)
    assert live_decommission.extension_granted is True
    assert live_decommission.scheduled_teardown_at == live_decommission.extension_until


@pytest.mark.asyncio
async def test_signing_an_attestation_changes_no_booking_no_other_environment_no_deployment(
    db_session, test_tenant, test_user, live_decommission, bookings_on_env,
    populated_estate, decommission_step,
):
    """Fix wave item 3: `sign_attestation` was never exercised by this
    guard. Signing writes its OWN new row (`environment_decommission_
    attestation`) — this test's job is only to prove it writes nothing
    else."""
    other_rows = (
        populated_estate["environments"]
        + populated_estate["bookings"]
        + populated_estate["deployments"]
    )
    before_bookings = await _snapshot(db_session, bookings_on_env)
    before_other = await _snapshot(db_session, other_rows)

    now = datetime.now(timezone.utc)
    attestation = await environment_decommission_service.sign_attestation(
        db_session, live_decommission, test_user,
        step_key=decommission_step.key, reference=None, notes=None, now=now,
    )

    after_bookings = await _snapshot(db_session, bookings_on_env)
    after_other = await _snapshot(db_session, other_rows)
    assert before_bookings == after_bookings
    assert before_other == after_other

    # Non-vacuity: the signature itself did happen.
    assert attestation.step_key == decommission_step.key
    assert attestation.signed_by == test_user.id


@pytest.mark.asyncio
async def test_idle_detection_changes_nothing_at_all(db_session, test_tenant, populated_estate):
    """Enable it, list the estate, and assert every environment, booking and
    deployment row is unchanged. Idle is a derived READ."""
    all_rows = (
        populated_estate["environments"]
        + populated_estate["bookings"]
        + populated_estate["deployments"]
    )
    before = await _snapshot(db_session, all_rows)

    now = datetime.now(timezone.utc)
    await environment_lifecycle_policy_service.upsert_policy(
        db_session, test_tenant.id,
        idle_detection_enabled=True, idle_threshold_days=1,
        decommission_notice_days=5,
    )
    await environment_service.list_environments(db_session, test_tenant.id, now=now)

    after = await _snapshot(db_session, all_rows)
    assert before == after


@pytest.mark.asyncio
async def test_no_write_path_consults_idle():
    """STRUCTURAL, and labelled a smoke alarm rather than a proof, following
    B4's grep assertion (test_no_production_module_refuses_on_a_protection_
    level). Idle is a derived READ — `idle_state`/`idle_clause` in
    environment_idle_service.py build a SQL boolean expression with no
    side effect of their own — so the only way a write path could act on it
    is by importing and consulting `idle_clause` itself. This checks that no
    module under app/services other than environment_idle_service (where it
    is defined) and environment_service (the one read path,
    list_environments/get_environment_view) references it.

    THIS IS A SMOKE ALARM, NOT A PROOF: a module that imported `idle_clause`
    under an alias (`from ... import idle_clause as ic`), re-exported it
    through a third module, or reached it through
    `environment_idle_service.idle_clause(...)` written with unusual
    whitespace this bare substring search fails to match, would not be
    caught — there is no call-graph following here, exactly the same limit
    B4's equivalent test documents about itself.
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services"
    allowed = {"environment_idle_service.py", "environment_service.py"}
    offenders = [
        path.name
        for path in sorted(root.glob("*.py"))
        if path.name not in allowed and "idle_clause" in path.read_text()
    ]
    assert not offenders, (
        "idle_clause must only be referenced by environment_idle_service "
        f"(where it's defined) and environment_service (the one read "
        f"path). Found a reference in: {offenders}"
    )


@pytest.mark.asyncio
async def test_a_decommission_changes_no_other_environment(
    db_session, test_tenant, test_user, live_decommission, bystander_env
):
    """Two environments, one decommissioned. The second is untouched —
    status, owner, expiry, name verdict, all of it."""
    before = await _snapshot(db_session, [bystander_env])
    now = datetime.now(timezone.utc)
    await environment_decommission_service.tear_down(
        db_session, live_decommission, test_user, now=now
    )
    after = await _snapshot(db_session, [bystander_env])
    assert before == after


@pytest.mark.asyncio
async def test_cancelling_restores_nothing_and_breaks_nothing(
    db_session, test_tenant, test_user, live_decommission, populated_estate
):
    """Cancel writes three fields (cancelled_at/cancelled_by/cancel_reason)
    on its OWN row and touches no other table — not the environment it was
    raised against (which must stay ACTIVE, never flip to DECOMMISSIONED on
    a cancel), and nothing in the wider populated estate."""
    env = await db_session.get(Environment, live_decommission.environment_id)
    other_rows = (
        populated_estate["environments"]
        + populated_estate["bookings"]
        + populated_estate["deployments"]
    )
    before_env = await _snapshot(db_session, [env])
    before_other = await _snapshot(db_session, other_rows)

    now = datetime.now(timezone.utc)
    cancelled = await environment_decommission_service.cancel(
        db_session, live_decommission, test_user, reason="Guard test — cancel", now=now,
    )

    after_env = await _snapshot(db_session, [env])
    after_other = await _snapshot(db_session, other_rows)

    assert before_env == after_env
    assert after_env[(env.__tablename__, env.id)]["status"] == EnvironmentStatus.ACTIVE
    assert before_other == after_other

    assert cancelled.cancelled_at is not None
    assert cancelled.cancelled_by == test_user.id
    assert cancelled.cancel_reason == "Guard test — cancel"


@pytest.mark.asyncio
async def test_nothing_raises_on_a_decommission_except_the_documented_refusals(db_session):
    """The documented set is: 403 on a permission gate, 404 across tenants,
    409 on a second live decommission / a second extension / a duplicate
    attestation / a non-live row / a booking past teardown, and 422 on a bad
    date, a blank reason, an unknown step key or missing required steps.

    A grep-based structural assertion over environment_decommission_service
    — every literal `raise HTTPException(status.HTTP_XXX_YYYY` call site in
    the file must use one of {403, 404, 409, 422}. DELIBERATELY A SMOKE
    ALARM, NOT A PROOF, exactly as B4's equivalent
    (test_no_production_module_refuses_on_a_protection_level) is labelled:
    it only matches the literal `raise HTTPException(status.HTTP_...`
    spelling used consistently throughout this file today. A refusal built
    by assigning the exception to a variable first
    (`exc = HTTPException(...); raise exc`), constructed with a keyword
    `status_code=` argument instead of positional, or raised from a helper
    in a DIFFERENT module that this service merely calls, would not be
    caught — there is no call-graph following. The five behavioural tests
    above are the real guard on "nothing here acts beyond the documented
    surface"; this one only catches a new refusal introduced with an
    undocumented status code, written in the file's own existing style.
    """
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app" / "services" / "environment_decommission_service.py"
    )
    text = path.read_text()
    codes_found = re.findall(r"raise HTTPException\(\s*status\.HTTP_(\d{3})_", text)
    assert codes_found, "sanity: this file is expected to raise HTTPException at all"
    allowed = {"403", "404", "409", "422"}
    offenders = [c for c in codes_found if c not in allowed]
    assert not offenders, (
        "environment_decommission_service may only ever raise 403/404/409/422 "
        f"on the documented refusals. Found: {offenders}"
    )
