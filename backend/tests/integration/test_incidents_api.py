"""Integration tests for the Incidents API (Phase 5 SP1)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.services.incident_defaults import seed_incident_defaults_for_tenant


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Authenticated HTTP client scoped to `tenant`/`user`, with incident defaults seeded."""
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.commit()

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
async def test_incident_crud_and_transition_flow(authed_client):
    # create
    r = await authed_client.post("/api/v1/incidents", json={"title": "Outage", "severity": "P1"})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    assert r.json()["status"] == "new"
    # list
    r = await authed_client.get("/api/v1/incidents")
    assert r.status_code == 200 and any(i["id"] == iid for i in r.json())
    # transition
    r = await authed_client.post(f"/api/v1/incidents/{iid}/transition", json={"to_state": "investigating"})
    assert r.status_code == 200 and r.json()["status"] == "investigating"
    # detail
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "investigating"
    assert any(t["to_state"] in ("identified", "resolved") for t in body["allowed_transitions"])
    # delete
    r = await authed_client.delete(f"/api/v1/incidents/{iid}")
    assert r.status_code == 204
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_transition_returns_422(authed_client):
    iid = (await authed_client.post("/api/v1/incidents", json={"title": "x", "severity": "P3"})).json()["id"]
    r = await authed_client.post(f"/api/v1/incidents/{iid}/transition", json={"to_state": "closed"})
    assert r.status_code == 422
