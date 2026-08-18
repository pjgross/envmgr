"""B5 Task 3 — idle detection: derived in SQL, never stored.

Fixture names: the real fixtures in tests/conftest.py are `db_session` and
`test_tenant` (a `tenant` alias also exists, kept for Phase 3 model tests, but
this file uses the canonical `test_tenant` name throughout).

`make_booking`'s real signature is keyword-only (`booked_by=`, `environment=`,
not a positional environment id) and defaults `status` to the model default
"draft" — which is itself one of `INACTIVE_BOOKING_STATUSES`, so a booking
that is meant to make an environment non-idle must have its status bumped off
draft after creation, via `_active_booking` below.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.environment import EnvironmentStatus
from app.services import environment_health_service, environment_service
from tests.factories import ensure_environment, ensure_environment_tier, ensure_user, make_booking

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


async def _enable(db, tenant_id, days=30):
    from app.services import environment_lifecycle_policy_service as svc
    await svc.upsert_policy(
        db, tenant_id,
        idle_detection_enabled=True,
        idle_threshold_days=days,
        decommission_notice_days=5,
    )


async def _active_booking(db, tenant_id, env, *, start, end):
    """A booking that counts as a live claim on `env`.

    `make_booking` takes no `status` kwarg and the model default is "draft" —
    itself one of INACTIVE_BOOKING_STATUSES, so a bare `make_booking` call
    would not stop the environment from reading idle. Bump the status after
    creation, same as other suites that need a non-draft booking.
    """
    booker = await ensure_user(db, tenant_id)
    booking = await make_booking(
        db, tenant_id, booked_by=booker.id, environment=env, start=start, end=end
    )
    booking.status = "approved"
    await db.flush()
    return booking


@pytest.mark.asyncio
async def test_a_decommissioned_environment_is_absent_from_the_health_overview(
    db_session, test_tenant
):
    """PRE-EXISTING BUG, fixed here. environment.status stores the enum member
    NAME — the column holds 'ACTIVE', never 'active' — so a string-literal
    comparison silently matched nothing and excluded nothing."""
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.status = EnvironmentStatus.DECOMMISSIONED
    await db_session.flush()

    overview, _total = await environment_health_service.health_overview(db_session, test_tenant.id)

    assert all(row["environment_id"] != env.id for row in overview)


@pytest.mark.asyncio
async def test_an_environment_with_no_activity_is_idle(db_session, test_tenant):
    await _enable(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=200)
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert [v.environment.id for v in views] == [env.id]


@pytest.mark.asyncio
async def test_a_recent_booking_makes_it_active(db_session, test_tenant):
    await _enable(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=200)
    await _active_booking(
        db_session, test_tenant.id, env,
        start=NOW - timedelta(days=3), end=NOW - timedelta(days=1),
    )
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_a_long_booking_spanning_the_window_makes_it_active(db_session, test_tenant):
    """OVERLAP, NOT START. A three-month booking taken four months ago means the
    environment was claimed the whole time; a start-date test calls it idle."""
    await _enable(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=400)
    await _active_booking(
        db_session, test_tenant.id, env,
        start=NOW - timedelta(days=120), end=NOW + timedelta(days=1),
    )
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_an_environment_younger_than_its_threshold_is_never_idle(db_session, test_tenant):
    """Otherwise every new environment is born a ghost — B2's policy-age guard."""
    await _enable(db_session, test_tenant.id, days=30)
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=5)
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_the_tier_override_wins_over_the_tenant_default(db_session, test_tenant):
    await _enable(db_session, test_tenant.id, days=30)
    tier = await ensure_environment_tier(db_session, test_tenant.id, name="DR")
    tier.idle_threshold_days = 90
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.tier_id = tier.id
    env.created_at = NOW - timedelta(days=200)
    await _active_booking(
        db_session, test_tenant.id, env,
        start=NOW - timedelta(days=60), end=NOW - timedelta(days=59),
    )
    await db_session.flush()

    # Quiet for 60 days: idle under the 30-day default, active under DR's 90.
    views, _ = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_a_non_active_environment_is_never_idle(db_session, test_tenant):
    """Answers FALSE, never null. An inactive environment is idle by
    definition; flagging it buries the real ghosts."""
    await _enable(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=200)
    env.status = EnvironmentStatus.INACTIVE
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_nothing_is_idle_while_detection_is_disabled(db_session, test_tenant):
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=999)
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_the_filtered_total_describes_the_filtered_set(db_session, test_tenant):
    """X-Total-Count is the only evidence from outside that the filter ran in
    the query rather than over the page."""
    await _enable(db_session, test_tenant.id)
    idle_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    idle_env.created_at = NOW - timedelta(days=200)
    busy = await ensure_environment(db_session, test_tenant.id, slot=2)
    busy.created_at = NOW - timedelta(days=200)
    await _active_booking(
        db_session, test_tenant.id, busy,
        start=NOW - timedelta(days=2), end=NOW - timedelta(days=1),
    )
    await db_session.flush()

    _, total = await environment_service.list_environments(
        db_session, test_tenant.id, idle=True, now=NOW
    )
    assert total == 1
