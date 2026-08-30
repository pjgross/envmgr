"""Integration tests for the PIR API (Phase 5 SP4) — Task 4."""
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
    """Authenticated HTTP client scoped to `tenant`/`user`."""
    # Seed incident defaults so that PIR tests linked to incidents work.
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


@pytest_asyncio.fixture(scope="function")
async def demo_release_id(db_session, tenant, user) -> int:
    """A persisted Release in the test tenant; yields its id.

    Creates a minimal LifecycleTemplate + Release directly in the DB,
    mirroring the pattern used by test_raid_api.py (raid_release fixture).
    """
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="PIR Test Major",
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
        name="PIR Integration Test Release",
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
async def test_pir_crud_flow(authed_client, demo_release_id):
    # none yet — GET should return 200 with null body or 204
    assert (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).status_code in (200, 204)
    # create
    r = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir",
        json={"summary": "went ok"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"
    # Create returns the same hydrated shape a GET does, so a page that renders
    # the response of its own POST cannot disagree with the next read.
    assert r.json()["findings"] == []
    # The retired free-text fields are REFUSED, not silently dropped: a client
    # still sending them is told they are gone.
    assert (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir", json={"root_cause": "n/a"}
    )).status_code == 422
    # duplicate -> 409
    assert (
        await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={})
    ).status_code == 409
    # complete
    r = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir", json={"status": "complete"}
    )
    assert r.status_code == 200 and r.json()["status"] == "complete"
    # delete
    assert (
        await authed_client.delete(f"/api/v1/releases/{demo_release_id}/pir")
    ).status_code == 204


@pytest.mark.asyncio
async def test_pir_get_unknown_release_returns_null(authed_client):
    """GET for a release that doesn't exist or has no PIR returns 200 null."""
    r = await authed_client.get("/api/v1/releases/999999/pir")
    # The service returns None; FastAPI serialises Optional as null (200) or 204.
    assert r.status_code in (200, 204)


@pytest.mark.asyncio
async def test_pir_patch_not_found_404(authed_client, demo_release_id):
    """PATCH when no PIR exists → 404."""
    r = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "x"}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pir_delete_not_found_404(authed_client, demo_release_id):
    """DELETE when no PIR exists → 404."""
    r = await authed_client.delete(f"/api/v1/releases/{demo_release_id}/pir")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_pir_unauthenticated(db_session, demo_release_id):
    """Unauthenticated requests → 401/403."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(f"/api/v1/releases/{demo_release_id}/pir")
        assert r.status_code in (401, 403)
    app.dependency_overrides.clear()
