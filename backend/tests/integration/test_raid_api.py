"""Integration tests for the RAID log endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release


@pytest_asyncio.fixture
async def raid_release(db_session, test_tenant, test_user):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id, entity_type="release", name="Major", is_default=True,
        definition={"states": [], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=test_tenant.id, name="R1", release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


@pytest.mark.asyncio
async def test_raid_crud_happy_path(client: AsyncClient, auth_headers, raid_release):
    # create
    resp = await client.post(
        f"/api/v1/releases/{raid_release.id}/raid",
        headers=auth_headers,
        json={"item_type": "risk", "title": "DB migration risk", "probability": 4, "impact": 5},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ref_code"] == "R-001"
    assert body["severity"] == 20
    assert body["rag"] == "red"
    item_id = body["id"]
    # list
    lst = await client.get(f"/api/v1/releases/{raid_release.id}/raid", headers=auth_headers)
    assert lst.status_code == 200
    assert len(lst.json()) == 1
    # get
    got = await client.get(f"/api/v1/releases/{raid_release.id}/raid/{item_id}", headers=auth_headers)
    assert got.status_code == 200
    # update (valid transition)
    upd = await client.patch(
        f"/api/v1/releases/{raid_release.id}/raid/{item_id}",
        headers=auth_headers, json={"status": "mitigating"})
    assert upd.status_code == 200
    assert upd.json()["status"] == "mitigating"
    # delete
    d = await client.delete(f"/api/v1/releases/{raid_release.id}/raid/{item_id}", headers=auth_headers)
    assert d.status_code == 204
    lst2 = await client.get(f"/api/v1/releases/{raid_release.id}/raid", headers=auth_headers)
    assert lst2.json() == []


@pytest.mark.asyncio
async def test_raid_invalid_transition_422(client: AsyncClient, auth_headers, raid_release):
    resp = await client.post(
        f"/api/v1/releases/{raid_release.id}/raid",
        headers=auth_headers, json={"item_type": "risk", "title": "X"})
    item_id = resp.json()["id"]
    bad = await client.patch(
        f"/api/v1/releases/{raid_release.id}/raid/{item_id}",
        headers=auth_headers, json={"status": "resolved"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_raid_unauthenticated(client: AsyncClient, raid_release):
    resp = await client.get(f"/api/v1/releases/{raid_release.id}/raid")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_raid_tenant_isolation(client: AsyncClient, db_session, auth_headers, raid_release):
    # A second tenant + admin cannot see or create RAID on tenant A's release.
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash
    other = Tenant(name="Other RAID Org", slug="other-raid-org")
    db_session.add(other)
    await db_session.flush()
    ou = User(tenant_id=other.id, username="oraid", email="o@raid.com",
              password_hash=get_password_hash("password123"), role="Admin", is_active=True)
    db_session.add(ou)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login",
        json={"username": "oraid", "password": "password123", "tenant_slug": other.slug})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # tenant B sees 404 on tenant A's release RAID
    assert (await client.get(f"/api/v1/releases/{raid_release.id}/raid", headers=other_headers)).status_code == 404
    assert (await client.post(f"/api/v1/releases/{raid_release.id}/raid", headers=other_headers,
            json={"item_type": "risk", "title": "sneaky"})).status_code == 404
