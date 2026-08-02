"""Integration tests for the Environment Health API (Phase 5 SP3)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.environment import Environment
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash
from app.services import api_key_service, environment_health_service as svc


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Authenticated HTTP client scoped to `tenant`/`user`."""
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
async def demo_environment_id(db_session, tenant) -> int:
    """A persisted Environment in the test tenant; yields its id."""
    env = Environment(
        tenant_id=tenant.id,
        name="health-test-env",
        environment_type="SIT",
        status="active",
    )
    db_session.add(env)
    await db_session.flush()
    await db_session.commit()
    return env.id


@pytest_asyncio.fixture(scope="function")
async def health_api_key(db_session, tenant, user) -> str:
    """Raw API key token with the `environment:health` scope for `tenant`."""
    _key, raw = await api_key_service.create_key(
        db_session,
        tenant_id=tenant.id,
        created_by=user.id,
        name="health-ci-key",
        scopes=["environment:health"],
    )
    await db_session.commit()
    return raw


@pytest_asyncio.fixture(scope="function")
async def no_scope_api_key(db_session, tenant, user) -> str:
    """Raw API key token with NO relevant scope for `tenant`."""
    _key, raw = await api_key_service.create_key(
        db_session,
        tenant_id=tenant.id,
        created_by=user.id,
        name="noscope-key",
        scopes=["other:scope"],
    )
    await db_session.commit()
    return raw


@pytest_asyncio.fixture(scope="function")
async def other_tenant_environment_with_down_sample(db_session) -> int:
    """A second tenant with an environment that has a 'down' health sample.
    Returns the environment id (should NOT appear in the first tenant's overview)."""
    other_tenant = Tenant(name="Other Health Org", slug="other-health-org")
    db_session.add(other_tenant)
    await db_session.flush()

    other_user = User(
        tenant_id=other_tenant.id,
        username="other-health-admin",
        email="admin@other-health-org.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()

    other_env = Environment(
        tenant_id=other_tenant.id,
        name="other-tenant-env",
        environment_type="SIT",
        status="active",
    )
    db_session.add(other_env)
    await db_session.flush()

    # Insert a health sample for the other tenant's env
    await svc.record_sample(
        db_session, other_tenant.id, other_env.id, "down", "pytest-isolation"
    )
    await db_session.commit()
    return other_env.id


# ---------------------------------------------------------------------------
# Core API tests (TDD: these fail until the router is mounted)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_push_with_api_key(authed_client, health_api_key, demo_environment_id):
    r = await authed_client.post(
        f"/api/v1/environments/{demo_environment_id}/health",
        json={"status": "down", "source": "pytest"},
        headers={"X-Api-Key": health_api_key},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "down"


@pytest.mark.asyncio
async def test_health_push_missing_key_401(authed_client, demo_environment_id):
    r = await authed_client.post(
        f"/api/v1/environments/{demo_environment_id}/health",
        json={"status": "up", "source": "x"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_health_overview_and_history(authed_client, health_api_key, demo_environment_id):
    await authed_client.post(
        f"/api/v1/environments/{demo_environment_id}/health",
        json={"status": "issue", "source": "x"},
        headers={"X-Api-Key": health_api_key},
    )
    ov = await authed_client.get("/api/v1/environments/health")
    assert ov.status_code == 200
    assert any(r["environment_id"] == demo_environment_id for r in ov.json())
    hist = await authed_client.get(f"/api/v1/environments/{demo_environment_id}/health/history")
    assert hist.status_code == 200 and len(hist.json()) >= 1


# ---------------------------------------------------------------------------
# Scope / isolation tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_push_key_without_scope_403(authed_client, no_scope_api_key, demo_environment_id):
    r = await authed_client.post(
        f"/api/v1/environments/{demo_environment_id}/health",
        json={"status": "up", "source": "x"},
        headers={"X-Api-Key": no_scope_api_key},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_overview_tenant_scoped(authed_client, other_tenant_environment_with_down_sample):
    ov = await authed_client.get("/api/v1/environments/health")
    assert ov.status_code == 200
    assert all(r["environment_id"] != other_tenant_environment_with_down_sample for r in ov.json())


@pytest.mark.asyncio
async def test_history_advertises_the_total_and_honours_the_window(
    authed_client, health_api_key, demo_environment_id
):
    """The endpoint used to take a bare `limit` and return no total, so a client
    holding a partial history had no way to know it was partial."""
    for i in range(4):
        await authed_client.post(
            f"/api/v1/environments/{demo_environment_id}/health",
            json={"status": "up", "source": f"src-{i}"},
            headers={"X-Api-Key": health_api_key},
        )

    windowed = await authed_client.get(
        f"/api/v1/environments/{demo_environment_id}/health/history",
        params={"limit": 2},
    )
    assert windowed.status_code == 200
    body = windowed.json()
    assert len(body) == 2
    total = int(windowed.headers["X-Total-Count"])
    # The total must describe the whole history, not the page just returned —
    # returning len(rows) here would satisfy a test that only checked presence.
    assert total >= 4
    assert total > len(body)

    # And the second page continues rather than repeating the first.
    second = await authed_client.get(
        f"/api/v1/environments/{demo_environment_id}/health/history",
        params={"limit": 2, "offset": 2},
    )
    assert second.status_code == 200
    assert {r["id"] for r in second.json()}.isdisjoint({r["id"] for r in body})


@pytest.mark.asyncio
async def test_history_rejects_a_limit_beyond_its_own_cap(
    authed_client, demo_environment_id
):
    """This endpoint keeps its own 500 cap rather than the shared 1000. A
    rejected value is a 422, never a silent clamp — the same contract the
    pagination primitive applies everywhere else."""
    r = await authed_client.get(
        f"/api/v1/environments/{demo_environment_id}/health/history",
        params={"limit": 501},
    )
    assert r.status_code == 422
