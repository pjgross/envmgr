"""Integration tests for the PIR findings API — Task 2."""
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
    """A persisted Release in the test tenant; yields its id."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="PIR Findings Test Major",
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
        name="PIR Findings Integration Test Release",
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
async def test_findings_come_back_on_the_pir(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    created = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test", "root_cause": "Perf gate optional"},
    )
    assert created.status_code == 201, created.text

    got = await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")
    body = got.json()
    assert [f["title"] for f in body["findings"]] == ["No load test"]
    assert body["findings"][0]["root_cause"] == "Perf gate optional"
    assert body["findings"][0]["seq"] == 1


@pytest.mark.asyncio
async def test_a_finding_on_a_release_with_no_pir_is_a_404(authed_client, demo_release_id):
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_kind_is_a_422(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_sideways", "title": "T"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_not_dropped(authed_client, demo_release_id):
    """extra='forbid'. FastAPI and Pydantic drop unknown keys silently, and this
    codebase has shipped that bug three times."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T", "rootcause": "typo"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_and_delete_a_finding(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_well", "title": "Canary caught it"},
    )).json()["id"]

    patched = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}", json={"detail": "ran 30 min"})
    assert patched.status_code == 200
    assert patched.json()["title"] == "Canary caught it"
    assert patched.json()["detail"] == "ran 30 min"

    assert (await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}")).status_code == 204
    assert (await authed_client.get(
        f"/api/v1/releases/{demo_release_id}/pir")).json()["findings"] == []
