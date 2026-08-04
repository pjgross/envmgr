import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.system import System
from app.db.models.environment import Environment, EnvironmentSystem, EnvironmentStatus
from tests.factories import ensure_environment_tier


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


async def _make_system(db_session, tenant_id, name) -> int:
    s = System(tenant_id=tenant_id, name=name)
    db_session.add(s)
    await db_session.flush()
    return s.id


async def _make_env(db_session, tenant_id, name, status=EnvironmentStatus.ACTIVE) -> int:
    tier = await ensure_environment_tier(db_session, tenant_id)
    e = Environment(tenant_id=tenant_id, name=name, tier_id=tier.id, status=status)
    db_session.add(e)
    await db_session.flush()
    return e.id


async def _host(db_session, tenant_id, env_id, system_id):
    db_session.add(EnvironmentSystem(tenant_id=tenant_id, environment_id=env_id, system_id=system_id))
    await db_session.flush()


async def _link(authed_client, rid, sid, role):
    resp = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": role})
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_coverage_matrix(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    pay = await _make_system(db_session, tenant.id, "Payments")
    ident = await _make_system(db_session, tenant.id, "Identity")
    ledger = await _make_system(db_session, tenant.id, "Ledger")
    monitor = await _make_system(db_session, tenant.id, "Monitoring")

    await _link(authed_client, rid, pay, "changing")
    await _link(authed_client, rid, ident, "regression")
    await _link(authed_client, rid, ledger, "changing")
    await _link(authed_client, rid, monitor, "config_only")

    env_a = await _make_env(db_session, tenant.id, "SIT-A")
    env_b = await _make_env(db_session, tenant.id, "SIT-B")
    env_c = await _make_env(db_session, tenant.id, "OLD", status=EnvironmentStatus.DECOMMISSIONED)
    await _host(db_session, tenant.id, env_a, pay)
    await _host(db_session, tenant.id, env_a, ident)
    await _host(db_session, tenant.id, env_b, ident)
    await _host(db_session, tenant.id, env_c, ledger)
    await _host(db_session, tenant.id, env_a, monitor)

    resp = await authed_client.get(f"/api/v1/releases/{rid}/environment-coverage")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    needed_names = sorted(s["system_name"] for s in body["needed_systems"])
    assert needed_names == ["Identity", "Ledger", "Payments"]

    envs = {e["name"]: set(e["covered_system_ids"]) for e in body["environments"]}
    assert set(envs.keys()) == {"SIT-A", "SIT-B"}
    assert envs["SIT-A"] == {pay, ident}
    assert envs["SIT-B"] == {ident}

    assert body["uncovered_system_ids"] == [ledger]


@pytest.mark.asyncio
async def test_coverage_empty_when_no_testable_systems(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id, "OnlyConfig")
    await _link(authed_client, rid, sid, "config_only")
    resp = await authed_client.get(f"/api/v1/releases/{rid}/environment-coverage")
    assert resp.status_code == 200
    assert resp.json() == {"needed_systems": [], "environments": [], "uncovered_system_ids": []}


@pytest.mark.asyncio
async def test_coverage_excludes_foreign_tenant_environment(authed_client, tenant, db_session, release_lifecycle_template, second_tenant_factory):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id, "Payments")
    await _link(authed_client, rid, sid, "changing")

    # An environment in ANOTHER tenant, linked (via a cross-tenant EnvironmentSystem row)
    # to this tenant's system, must NOT be returned as coverage.
    other_tenant, _ = await second_tenant_factory()
    foreign_env = await _make_env(db_session, other_tenant.id, "FOREIGN")
    await _host(db_session, other_tenant.id, foreign_env, sid)

    resp = await authed_client.get(f"/api/v1/releases/{rid}/environment-coverage")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["environments"] == []            # foreign env excluded
    assert body["uncovered_system_ids"] == [sid] # system hosted only by a foreign env → uncovered


@pytest.mark.asyncio
async def test_coverage_missing_release_404(authed_client):
    resp = await authed_client.get("/api/v1/releases/999999/environment-coverage")
    assert resp.status_code == 404
