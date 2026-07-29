"""Integration tests for the Environment Operating Hours + per-env utilization API (SP5a)."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.environment import Environment

UTC = timezone.utc

_FULL = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(5)] + \
        [{"closed": True}, {"closed": True}]


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username, "password": "password123", "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


async def _env(db, tenant_id, name="SIT"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


@pytest.mark.asyncio
async def test_get_operating_hours_unset(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.get(f"/api/v1/environments/{env.id}/operating-hours")
    assert r.status_code == 200, r.text
    assert r.json() == {"configured": False, "timezone": None, "week": None}


@pytest.mark.asyncio
async def test_put_then_get_operating_hours(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.put(f"/api/v1/environments/{env.id}/operating-hours",
                                json={"timezone": "Europe/London", "week": _FULL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["timezone"] == "Europe/London"
    assert body["week"][0]["open"] == "09:00"
    g = await authed_client.get(f"/api/v1/environments/{env.id}/operating-hours")
    assert g.json()["timezone"] == "Europe/London"


@pytest.mark.asyncio
async def test_put_invalid_timezone_422(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.put(f"/api/v1/environments/{env.id}/operating-hours",
                                json={"timezone": "Nowhere/Nope", "week": _FULL})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_env_utilization_endpoint(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    await authed_client.put(f"/api/v1/environments/{env.id}/operating-hours",
                            json={"timezone": "UTC", "week": _FULL})
    r = await authed_client.get(f"/api/v1/environments/{env.id}/utilization",
                                params={"date_from": "2026-06-01", "date_to": "2026-06-07"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"environment_id", "environment_name", "configured", "timezone",
                         "total_operating_seconds", "booked_operating_seconds", "utilization_pct"}
    assert body["total_operating_seconds"] == 40 * 3600


@pytest.mark.asyncio
async def test_env_utilization_requires_dates(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.get(f"/api/v1/environments/{env.id}/utilization")
    assert r.status_code == 422
