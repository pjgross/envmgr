"""Integration tests for the Incidents API (Phase 5 SP1)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
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


# ── Task 5: PIR integration on incident detail + list ─────────────────────────

@pytest_asyncio.fixture(scope="function")
async def demo_release_id(db_session, tenant, user) -> int:
    """A persisted Release in the test tenant; yields its id."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="Incident PIR Test Release Template",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=tenant.id,
        name="Incident PIR Integration Test Release",
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=tpl.id,
        status="draft",
        raised_by=user.id,
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.commit()
    return r.id


@pytest.mark.asyncio
async def test_incident_detail_has_pir(authed_client, demo_release_id):
    """GET /incidents/{id} includes a `pir` object when a PIR is linked to the incident."""
    # Create incident
    r = await authed_client.post("/api/v1/incidents", json={"title": "PIR Test Outage", "severity": "P2"})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]

    # Detail before PIR — pir should be null
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 200
    assert r.json()["pir"] is None

    # Create a complete PIR on demo_release, linked to the incident
    r = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir",
        json={
            "incident_id": iid,
            "status": "complete",
            "summary": "All good",
            "root_cause": "Config drift",
            "action_plan": "Add alerting",
        },
    )
    assert r.status_code == 201, r.text

    # Detail after PIR — pir key should be populated
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 200, r.text
    body = r.json()
    pir = body.get("pir")
    assert pir is not None, f"Expected 'pir' in detail, got: {body}"
    assert pir["status"] == "complete"
    assert pir["release_id"] == demo_release_id
    assert pir["root_cause"] == "Config drift"
    assert pir["action_plan"] == "Add alerting"
    assert pir["summary"] == "All good"


@pytest.mark.asyncio
async def test_incident_list_has_pir_status(authed_client, demo_release_id):
    """GET /incidents list rows include `pir_status` — 'none' without PIR, 'complete' after."""
    # Create incident
    r = await authed_client.post("/api/v1/incidents", json={"title": "List PIR Test", "severity": "P3"})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]

    # List before PIR — pir_status should be "none"
    r = await authed_client.get("/api/v1/incidents")
    assert r.status_code == 200
    row = next((i for i in r.json() if i["id"] == iid), None)
    assert row is not None
    assert row["pir_status"] == "none"

    # Create a complete PIR linked to this incident
    r = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir",
        json={"incident_id": iid, "status": "complete"},
    )
    assert r.status_code == 201, r.text

    # List after PIR — pir_status should be "complete"
    r = await authed_client.get("/api/v1/incidents")
    assert r.status_code == 200
    row = next((i for i in r.json() if i["id"] == iid), None)
    assert row is not None, "Incident not found in list"
    assert row["pir_status"] == "complete", f"Expected 'complete', got: {row['pir_status']}"
