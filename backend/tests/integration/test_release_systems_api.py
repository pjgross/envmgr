import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.system import System


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


async def _make_release(authed_client, release_lifecycle_template) -> int:
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Rel", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_system(db_session, tenant_id, name="Core") -> int:
    s = System(tenant_id=tenant_id, name=name)
    db_session.add(s)
    await db_session.flush()
    return s.id


@pytest.mark.asyncio
async def test_add_and_list_release_system_hydrates_name(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id, "Payments")

    add = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={
        "system_id": sid, "role": "regression",
    })
    assert add.status_code == 201, add.text
    assert add.json()["system_name"] == "Payments"
    assert add.json()["role"] == "regression"

    lst = await authed_client.get(f"/api/v1/releases/{rid}/systems")
    assert lst.status_code == 200
    assert [row["system_name"] for row in lst.json()] == ["Payments"]


@pytest.mark.asyncio
async def test_duplicate_system_link_conflicts(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id)
    first = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": "changing"})
    assert first.status_code == 201
    dup = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": "changing"})
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_invalid_role_rejected(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id)
    bad = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": "wizard"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_foreign_system_rejected(authed_client, tenant, db_session, release_lifecycle_template, second_tenant_factory):
    rid = await _make_release(authed_client, release_lifecycle_template)
    other_tenant, _ = await second_tenant_factory()
    foreign_sid = await _make_system(db_session, other_tenant.id, "Foreign")
    resp = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": foreign_sid, "role": "changing"})
    assert resp.status_code == 400
