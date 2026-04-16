import pytest
from datetime import datetime, timezone, timedelta

from app.services import conflict_service
from app.db.models.booking import Booking
from app.db.models.environment import Environment


async def _make_env(db_session, test_tenant, name: str = "env1") -> Environment:
    env = Environment(tenant_id=test_tenant.id, name=name, environment_type="dev")
    db_session.add(env)
    await db_session.flush()
    return env


async def _make_booking(db_session, test_tenant, test_user, env, start, end, status="submitted") -> Booking:
    b = Booking(
        tenant_id=test_tenant.id,
        environment_id=env.id,
        project_name="p",
        booked_by=test_user.id,
        start_date=start,
        end_date=end,
        exclusive_use=False,
        booking_type_id=1,  # dummy — not traversed for overlap
        status=status,
        context_tag="none",
    )
    db_session.add(b)
    await db_session.flush()
    return b


@pytest.mark.asyncio
async def test_overlap_same_env_open_window(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    b = await _make_booking(db_session, test_tenant, test_user, env, t0 + timedelta(days=1), t0 + timedelta(days=3))

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    ids = [c.id for c in conflicts]
    assert b.id in ids


@pytest.mark.asyncio
async def test_no_overlap_when_terminal(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2), status="rejected")
    await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2), status="closed")

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    assert conflicts == []


@pytest.mark.asyncio
async def test_no_overlap_different_env(db_session, test_tenant, test_user):
    env_a = await _make_env(db_session, test_tenant, name="env1")
    env_b = await _make_env(db_session, test_tenant, name="env2")

    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env_a, t0, t0 + timedelta(days=2))
    await _make_booking(db_session, test_tenant, test_user, env_b, t0, t0 + timedelta(days=2))

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    assert conflicts == []
