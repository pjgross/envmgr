"""Reserved is derived from live bookings, never stored.

An environment that is reserved is still active — that is why this is a second
axis and not an EnvironmentStatus value.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.booking import Booking
from app.services import environment_service
from tests.factories import ensure_booking_type, ensure_environment_tier, ensure_user


async def _booking(db, tenant_id, env_id, status: str, *, covers_now: bool = True):
    from app.db.models.booking_request import BookingRequest

    user = await ensure_user(db, tenant_id)
    booking_type = await ensure_booking_type(db, tenant_id)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1) if covers_now else now + timedelta(days=7)
    end = now + timedelta(hours=1) if covers_now else now + timedelta(days=8)

    request = BookingRequest(
        tenant_id=tenant_id,
        project_name="proj",
        booking_type_id=booking_type.id,
        start_date=start,
        end_date=end,
        booked_by=user.id,
    )
    db.add(request)
    await db.flush()

    booking = Booking(
        tenant_id=tenant_id,
        environment_id=env_id,
        booking_request_id=request.id,
        start_date=start,
        end_date=end,
        status=status,
    )
    db.add(booking)
    await db.flush()
    return booking


async def _environment(db, tenant_id, name):
    from app.db.models.environment import Environment

    tier = await ensure_environment_tier(db, tenant_id)
    env = Environment(tenant_id=tenant_id, name=name, tier_id=tier.id)
    db.add(env)
    await db.flush()
    return env


@pytest.mark.asyncio
@pytest.mark.parametrize("dead_status", ["draft", "rejected", "closed"])
async def test_a_booking_that_is_not_a_live_claim_does_not_reserve(
    db_session, test_tenant, dead_status
):
    env = await _environment(db_session, test_tenant.id, f"env-{dead_status}")
    await _booking(db_session, test_tenant.id, env.id, dead_status)

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is False


@pytest.mark.asyncio
async def test_an_approved_booking_covering_now_reserves(db_session, test_tenant):
    env = await _environment(db_session, test_tenant.id, "env-approved")
    await _booking(db_session, test_tenant.id, env.id, "approved")

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is True


@pytest.mark.asyncio
async def test_a_future_booking_does_not_reserve_now(db_session, test_tenant):
    env = await _environment(db_session, test_tenant.id, "env-future")
    await _booking(db_session, test_tenant.id, env.id, "approved", covers_now=False)

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is False


@pytest.mark.asyncio
async def test_a_soft_deleted_booking_does_not_reserve(db_session, test_tenant):
    env = await _environment(db_session, test_tenant.id, "env-deleted")
    booking = await _booking(db_session, test_tenant.id, env.id, "approved")
    booking.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is False
