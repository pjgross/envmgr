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


@pytest.mark.asyncio
async def test_scope_link_cross_tenant_rejected(client, db_session, auth_headers, raid_release):
    from app.db.models.user import Tenant, User
    from app.db.models.release import Release
    from app.db.models.release_change import ReleaseChange
    from app.db.models.lifecycle import LifecycleTemplate
    from app.core.security import get_password_hash
    # A RAID item on tenant A's release
    created = await client.post(f"/api/v1/releases/{raid_release.id}/raid",
        headers=auth_headers, json={"item_type": "risk", "title": "X"})
    item_id = created.json()["id"]
    # A scope item owned by a DIFFERENT tenant
    other = Tenant(name="XT Org", slug="xt-org"); db_session.add(other); await db_session.flush()
    ou = User(tenant_id=other.id, username="xtu", email="xt@o.com",
              password_hash=get_password_hash("password123"), role="Admin", is_active=True)
    tpl = LifecycleTemplate(tenant_id=other.id, entity_type="release", name="M", is_default=True,
        definition={"states": [], "transitions": [], "field_permissions": {}})
    db_session.add_all([ou, tpl]); await db_session.flush()
    orel = Release(tenant_id=other.id, name="OR", release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=ou.id)
    db_session.add(orel); await db_session.flush()
    frc = ReleaseChange(tenant_id=other.id, release_id=orel.id, title="F", change_kind="story", source="manual")
    db_session.add(frc); await db_session.commit(); await db_session.refresh(frc)
    # tenant A tries to link tenant B's scope item -> 400
    resp = await client.post(f"/api/v1/releases/{raid_release.id}/raid/{item_id}/scope-links",
        headers=auth_headers, json={"release_change_id": frc.id})
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_raid_rows_carry_the_owner_username(
    client: AsyncClient, auth_headers, raid_release, test_user
):
    """The owner's name travels with the row.

    It used to be resolved in the browser against the shared tenant-users
    collection, which the server caps at 500. Past the cap an item's owner
    rendered as an em dash — information lost on screen, not merely an option
    missing from a picker. Nothing in the UI said why.
    """
    created = await client.post(
        f"/api/v1/releases/{raid_release.id}/raid",
        headers=auth_headers,
        json={"item_type": "risk", "title": "Owned risk", "owner_id": test_user.id},
    )
    assert created.status_code == 201, created.text
    assert created.json()["owner_username"] == test_user.username

    listed = await client.get(
        f"/api/v1/releases/{raid_release.id}/raid", headers=auth_headers
    )
    assert listed.status_code == 200
    row = next(r for r in listed.json() if r["title"] == "Owned risk")
    assert row["owner_username"] == test_user.username


@pytest.mark.asyncio
async def test_raid_owner_username_is_null_when_unowned(
    client: AsyncClient, auth_headers, raid_release
):
    """An unowned item must not borrow some other item's owner — the batch
    lookup is keyed by owner_id, and a dict miss must stay None."""
    await client.post(
        f"/api/v1/releases/{raid_release.id}/raid",
        headers=auth_headers,
        json={"item_type": "issue", "title": "Unowned issue"},
    )
    listed = await client.get(
        f"/api/v1/releases/{raid_release.id}/raid", headers=auth_headers
    )
    row = next(r for r in listed.json() if r["title"] == "Unowned issue")
    assert row["owner_id"] is None
    assert row["owner_username"] is None


@pytest.mark.asyncio
async def test_each_row_gets_its_own_owner_not_the_first_one(
    client: AsyncClient, db_session, auth_headers, raid_release, test_tenant, test_user
):
    """Two owners, two names, each on the right row.

    With a single owner in the fixture, a mapper that handed every row the
    first name it found would pass — which is exactly what the first version of
    these tests did.
    """
    from app.core.security import get_password_hash
    from app.db.models.user import User

    second = User(
        tenant_id=test_tenant.id, username="owner-two", email="two@test.com",
        password_hash=get_password_hash("x"), role="User", is_active=True,
    )
    db_session.add(second)
    await db_session.commit()
    await db_session.refresh(second)

    for title, owner in (("first", test_user.id), ("second", second.id)):
        r = await client.post(
            f"/api/v1/releases/{raid_release.id}/raid",
            headers=auth_headers,
            json={"item_type": "risk", "title": title, "owner_id": owner},
        )
        assert r.status_code == 201, r.text

    listed = await client.get(
        f"/api/v1/releases/{raid_release.id}/raid", headers=auth_headers
    )
    by_title = {r["title"]: r for r in listed.json()}
    assert by_title["first"]["owner_username"] == test_user.username
    assert by_title["second"]["owner_username"] == "owner-two"
    assert by_title["first"]["owner_username"] != by_title["second"]["owner_username"]


@pytest.mark.asyncio
async def test_owner_lookup_is_tenant_scoped(
    client: AsyncClient, db_session, auth_headers, raid_release, test_tenant, test_user
):
    """The username lookup filters by tenant.

    owner_id is validated on write, so a foreign owner should never be stored —
    this guards the lookup itself, which would otherwise be a query keyed only
    on ids that happen to be unique per-database rather than per-tenant.
    """
    from app.services import raid_service

    names = await raid_service.owner_usernames(
        db_session,
        [type("Item", (), {"owner_id": test_user.id})()],
        tenant_id=test_tenant.id + 999,
    )
    assert names == {}, "a foreign tenant resolved this tenant's username"

    same_tenant = await raid_service.owner_usernames(
        db_session,
        [type("Item", (), {"owner_id": test_user.id})()],
        tenant_id=test_tenant.id,
    )
    assert same_tenant == {test_user.id: test_user.username}
