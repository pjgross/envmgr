import pytest
from datetime import datetime, timezone, timedelta

from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.user import User, Tenant
from app.core.security import get_password_hash
from app.services import release_metrics_service

UTC = timezone.utc

_user_counter = 0


async def _user(db, tenant_id):
    global _user_counter
    _user_counter += 1
    u = User(tenant_id=tenant_id, username=f"rmuser{_user_counter}",
             email=f"rmuser{_user_counter}@test.com",
             password_hash=get_password_hash("x"), role="Viewer", is_active=True)
    db.add(u); await db.flush(); return u


async def _env(db, tenant_id, name):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


async def _booking_request(db, tenant_id, user_id):
    # Required non-defaulted columns: tenant_id, project_name, booking_type_id (FK — any int
    # is fine, SQLite tests don't enforce FKs), start_date, end_date, booked_by. context_tag
    # and exclusive_use_requested have model defaults. The request-level dates are placeholders;
    # conflict overlap is computed from the Booking rows, not the request.
    req = BookingRequest(
        tenant_id=tenant_id, project_name="Proj", booked_by=user_id, booking_type_id=1,
        start_date=datetime(2026, 6, 1, tzinfo=UTC), end_date=datetime(2026, 6, 30, tzinfo=UTC),
    )
    db.add(req); await db.flush(); return req


async def _booking(db, tenant_id, env_id, req_id, start, end, status="approved"):
    b = Booking(tenant_id=tenant_id, environment_id=env_id, booking_request_id=req_id,
                start_date=start, end_date=end, status=status)
    db.add(b); await db.flush(); return b


@pytest.mark.asyncio
async def test_conflicts_counts_one_overlapping_pair(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Two bookings that overlap (b2 starts before b1 ends)
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["environment_id"] == env.id
    assert rows[0]["environment_name"] == "SIT"
    assert rows[0]["month"] == "2026-06"
    assert rows[0]["conflict_count"] == 1


@pytest.mark.asyncio
async def test_conflicts_non_overlapping_is_zero(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=1))
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=2), t0 + timedelta(days=3))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []


@pytest.mark.asyncio
async def test_conflicts_excludes_draft_and_closed(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Overlapping window, but one booking is draft and one is closed → no counted pair
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=3), status="draft")
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4), status="closed")
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []


@pytest.mark.asyncio
async def test_conflicts_per_env_grouping(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env_a = await _env(db_session, tenant.id, "SIT")
    env_b = await _env(db_session, tenant.id, "UAT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Overlapping pair on env_a; overlapping pair on env_b
    await _booking(db_session, tenant.id, env_a.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env_a.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await _booking(db_session, tenant.id, env_b.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env_b.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert len(rows) == 2
    by_env = {r["environment_name"]: r["conflict_count"] for r in rows}
    assert by_env == {"SIT": 1, "UAT": 1}


@pytest.mark.asyncio
async def test_conflicts_tenant_isolation(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Second tenant with its own overlapping pair
    t2 = Tenant(name="Other Org", slug="other-org-rm")
    db_session.add(t2); await db_session.flush()
    u2 = await _user(db_session, t2.id)
    env2 = await _env(db_session, t2.id, "SIT2")
    req2 = await _booking_request(db_session, t2.id, u2.id)
    await _booking(db_session, t2.id, env2.id, req2.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, t2.id, env2.id, req2.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    # Query the FIRST tenant (which has no bookings) → empty
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []
