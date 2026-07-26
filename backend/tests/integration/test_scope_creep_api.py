import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db


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


@pytest.mark.asyncio
async def test_creep_surfaced_in_list_and_changes(authed_client, release_lifecycle_template):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Creepy", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id, "scope_deadline": past,
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    c = await authed_client.post(f"/api/v1/releases/{rid}/changes", json={
        "title": "late item", "change_kind": "story",
    })
    assert c.status_code == 201, c.text

    lst = await authed_client.get("/api/v1/releases")
    assert lst.status_code == 200
    mine = next(x for x in lst.json() if x["id"] == rid)
    assert mine["scope_creep_count"] == 1

    ch = await authed_client.get(f"/api/v1/releases/{rid}/changes")
    assert ch.status_code == 200
    assert ch.json()[0]["is_scope_creep"] is True
