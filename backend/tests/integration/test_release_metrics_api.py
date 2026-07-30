"""Integration tests for the Release Metrics API (Phase 5 SP5b)."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.user import Tenant
from tests.factories import ensure_booking_type

UTC = timezone.utc


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username,
            "password": "password123",
            "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_release_metrics_shape(authed_client):
    r = await authed_client.get("/api/v1/metrics/releases",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "success_rate", "shipped_count", "failed_count",
        "emergency_pct", "emergency_count", "closed_count",
        "avg_cycle_time_seconds", "cycle_time_count",
    }


@pytest.mark.asyncio
async def test_release_metrics_requires_dates(authed_client):
    r = await authed_client.get("/api/v1/metrics/releases")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_booking_conflicts_shape(authed_client, db_session, tenant, user):
    env = Environment(tenant_id=tenant.id, name="SIT", environment_type="test")
    db_session.add(env); await db_session.flush()
    req = BookingRequest(
        tenant_id=tenant.id, project_name="Proj", booked_by=user.id,
        booking_type_id=(await ensure_booking_type(db_session, tenant.id)).id,
        start_date=datetime(2026, 6, 1, tzinfo=UTC), end_date=datetime(2026, 6, 30, tzinfo=UTC),
    )
    db_session.add(req); await db_session.flush()
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    db_session.add(Booking(tenant_id=tenant.id, environment_id=env.id, booking_request_id=req.id,
                           start_date=t0, end_date=t0 + timedelta(days=3), status="approved"))
    db_session.add(Booking(tenant_id=tenant.id, environment_id=env.id, booking_request_id=req.id,
                           start_date=t0 + timedelta(days=1), end_date=t0 + timedelta(days=4), status="approved"))
    await db_session.flush()

    r = await authed_client.get("/api/v1/metrics/bookings/conflicts",
                                params={"date_from": "2026-06-01", "date_to": "2026-06-30"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["environment_name"] == "SIT"
    assert body[0]["month"] == "2026-06"
    assert body[0]["conflict_count"] == 1


@pytest.mark.asyncio
async def test_booking_conflicts_requires_dates(authed_client):
    r = await authed_client.get("/api/v1/metrics/bookings/conflicts")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_booking_conflicts_is_tenant_scoped(authed_client, db_session):
    # Second tenant WITH its own overlapping booking pair — must not leak into the authed tenant.
    from app.db.models.user import User
    from app.core.security import get_password_hash
    t2 = Tenant(name="Other Org3", slug="other-org-rm-api")
    db_session.add(t2); await db_session.flush()
    u2 = User(tenant_id=t2.id, username="rmapiuser2", email="rmapiuser2@test.com",
              password_hash=get_password_hash("x"), role="Viewer", is_active=True)
    db_session.add(u2); await db_session.flush()
    env2 = Environment(tenant_id=t2.id, name="SIT2", environment_type="test")
    db_session.add(env2); await db_session.flush()
    req2 = BookingRequest(
        tenant_id=t2.id, project_name="Proj2", booked_by=u2.id,
        booking_type_id=(await ensure_booking_type(db_session, t2.id)).id,
        start_date=datetime(2026, 6, 1, tzinfo=UTC), end_date=datetime(2026, 6, 30, tzinfo=UTC),
    )
    db_session.add(req2); await db_session.flush()
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    db_session.add(Booking(tenant_id=t2.id, environment_id=env2.id, booking_request_id=req2.id,
                           start_date=t0, end_date=t0 + timedelta(days=3), status="approved"))
    db_session.add(Booking(tenant_id=t2.id, environment_id=env2.id, booking_request_id=req2.id,
                           start_date=t0 + timedelta(days=1), end_date=t0 + timedelta(days=4), status="approved"))
    await db_session.flush()
    # The authed client is scoped to the first tenant, which has no bookings → empty.
    r = await authed_client.get("/api/v1/metrics/bookings/conflicts",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200
    assert r.json() == []
