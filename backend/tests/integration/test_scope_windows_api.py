import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.system import System
from app.db.models.release_system import ReleaseSystem


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


async def _link_system(db_session, tenant_id, release_id, name="Core"):
    system = System(tenant_id=tenant_id, name=name)
    db_session.add(system)
    await db_session.flush()
    db_session.add(ReleaseSystem(
        tenant_id=tenant_id, release_id=release_id, system_id=system.id, role="changing",
    ))
    await db_session.flush()
    return system.id


@pytest.mark.asyncio
async def test_system_filter_and_window_fields(authed_client, tenant, db_session, release_lifecycle_template):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Sysrel", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id, "scope_deadline": future,
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    sid = await _link_system(db_session, tenant.id, rid)

    r2 = await authed_client.post("/api/v1/releases", json={
        "name": "Other", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id,
    })
    assert r2.status_code == 201

    resp = await authed_client.get(f"/api/v1/releases?system_id={sid}")
    assert resp.status_code == 200, resp.text
    ids = [x["id"] for x in resp.json()]
    assert ids == [rid]
    row = resp.json()[0]
    assert row["window_status"] == "open"
    assert row["days_to_cutoff"] in (29, 30)
    assert [s["name"] for s in row["systems"]] == ["Core"]

    allresp = await authed_client.get("/api/v1/releases")
    other = next(x for x in allresp.json() if x["id"] == r2.json()["id"])
    assert other["window_status"] == "no_cutoff"
    assert other["days_to_cutoff"] is None
    assert other["systems"] == []


@pytest.mark.asyncio
async def test_shipped_wins_over_past_deadline_via_api(authed_client, tenant, db_session, release_lifecycle_template):
    from sqlalchemy import select
    from app.db.models.release import Release

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Shipped", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id, "scope_deadline": past,
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    # Stamp actual_date directly (simulates a deployed release)
    rel = (await db_session.execute(select(Release).where(Release.id == rid))).scalar_one()
    rel.actual_date = datetime.now(timezone.utc)
    await db_session.flush()

    resp = await authed_client.get("/api/v1/releases")
    assert resp.status_code == 200
    row = next(x for x in resp.json() if x["id"] == rid)
    assert row["window_status"] == "shipped"
    assert row["days_to_cutoff"] is None


@pytest.mark.asyncio
async def test_enterprise_release_reports_no_cutoff_via_api(authed_client, release_lifecycle_template):
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Ent", "release_type": "Test Major", "release_kind": "enterprise",
        "lifecycle_template_id": release_lifecycle_template.id,
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    resp = await authed_client.get("/api/v1/releases")
    assert resp.status_code == 200
    row = next(x for x in resp.json() if x["id"] == rid)
    assert row["window_status"] == "no_cutoff"
    assert row["days_to_cutoff"] is None


@pytest.mark.asyncio
async def test_system_filter_is_tenant_scoped(
    authed_client, tenant, db_session, second_tenant_factory
):
    # A system that belongs to a DIFFERENT tenant.
    other_tenant, _ = await second_tenant_factory()
    foreign = System(tenant_id=other_tenant.id, name="Foreign")
    db_session.add(foreign)
    await db_session.flush()

    # Filtering by a foreign tenant's system id must yield no releases for the
    # calling tenant (which has none linked to that system).
    resp = await authed_client.get(f"/api/v1/releases?system_id={foreign.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
