"""Integration tests for the DORA Metrics API (Phase 5 SP2)."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash
from tests.factories import ensure_change_request, ensure_environment, ensure_subsystem

_build_counter = 0
_deploy_counter = 0


async def _build(db, tenant_id, commit_dt, subsystem_id=None):
    global _build_counter
    _build_counter += 1
    sha = f"api{_build_counter:039d}"
    if subsystem_id is None:
        subsystem_id = (await ensure_subsystem(db, tenant_id)).id
    b = Build(tenant_id=tenant_id, subsystem_id=subsystem_id, git_sha=sha,
              build_number=str(_build_counter), commit_timestamp=commit_dt)
    db.add(b)
    await db.flush()
    return b


async def _deploy(db, tenant_id, build_id, env_id, deployed_dt, status="success", release_id=None,
                  change_request_id=None):
    global _deploy_counter
    _deploy_counter += 1
    if env_id is not None and env_id < 1000:
        # Small integers are slots, not real ids — see tests.factories.
        env_id = (await ensure_environment(db, tenant_id, env_id)).id
    if change_request_id is None:
        change_request_id = (await ensure_change_request(db, tenant_id)).id
    d = Deployment(tenant_id=tenant_id, build_id=build_id, environment_id=env_id,
                   release_id=release_id, change_request_id=change_request_id,
                   event_id=f"api-e{deployed_dt.timestamp()}-{_deploy_counter}",
                   deployed_at=deployed_dt, status=status, custom_fields={})
    db.add(d)
    await db.flush()
    return d


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Authenticated HTTP client scoped to `tenant`/`user`. No extra seeding required
    — the DORA endpoints return 200 with empty data when there are no deployments."""
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
async def test_dora_summary_endpoint(authed_client):
    r = await authed_client.get("/api/v1/metrics/dora",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"deployment_frequency", "lead_time", "change_failure_rate", "mttr"}


@pytest.mark.asyncio
async def test_dora_requires_dates(authed_client):
    r = await authed_client.get("/api/v1/metrics/dora")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dora_export_csv(authed_client):
    r = await authed_client.get("/api/v1/metrics/dora/export",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_plain_date_params_and_end_of_day_inclusive(authed_client, db_session, tenant):
    """Regression: UI sends plain YYYY-MM-DD strings; date_to is inclusive of the full day.

    A deployment at 23:00 on date_to must be counted (end_of_day=True in _as_dt).
    This documents the UI→API contract fixed in Phase 5 SP2.
    """
    UTC = timezone.utc
    commit_dt = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)
    # deployed_at is intentionally late on the last day of the window
    deploy_dt = datetime(2026, 6, 15, 23, 0, 0, tzinfo=UTC)

    b = await _build(db_session, tenant.id, commit_dt)
    await _deploy(db_session, tenant.id, b.id, 1, deploy_dt, "success")
    await db_session.flush()

    r = await authed_client.get(
        "/api/v1/metrics/dora",
        params={"date_from": "2026-06-01", "date_to": "2026-06-15"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deployment_frequency"]["total"] >= 1


@pytest.mark.asyncio
async def test_invalid_granularity_returns_422(authed_client):
    """Granularity must be one of day/week/month; bad values should 422."""
    r = await authed_client.get(
        "/api/v1/metrics/dora",
        params={"date_from": "2026-06-01", "date_to": "2026-06-15", "granularity": "year"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dora_is_tenant_scoped(authed_client, db_session, tenant):
    """
    A success deployment belonging to a second tenant must not appear in
    the authenticated tenant's deployment_frequency total.

    Isolation at the API layer: the endpoint uses current_user.active_tenant_id,
    so another tenant's deployment should yield total == 0 for this tenant.

    NOTE: service-level isolation is also independently tested in
    tests/services/test_dora_service.py::test_deployment_frequency_tenant_isolation.
    """
    UTC = timezone.utc
    t0 = datetime(2026, 6, 1, tzinfo=UTC)

    # Create a second tenant with a success deployment in the query window
    t2 = Tenant(name="Other Org", slug="other-org-dora")
    db_session.add(t2)
    await db_session.flush()

    b2 = await _build(db_session, t2.id, t0 - timedelta(days=1))
    await _deploy(db_session, t2.id, b2.id, 1, t0, "success")
    await db_session.flush()

    # The authed_client is scoped to `tenant`, which has NO deployments.
    r = await authed_client.get("/api/v1/metrics/dora",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200
    assert r.json()["deployment_frequency"]["total"] == 0
