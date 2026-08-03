"""GET /api/v1/environments/compare."""
import pytest
from httpx import AsyncClient

from app.db.models.environment import Environment


@pytest.fixture
async def two_envs(db_session, test_tenant):
    a = Environment(tenant_id=test_tenant.id, name="SIT", environment_type="test")
    b = Environment(tenant_id=test_tenant.id, name="UAT", environment_type="test")
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)
    return a, b


@pytest.mark.asyncio
async def test_compare_is_not_swallowed_by_the_env_id_route(
    client: AsyncClient, auth_headers, two_envs
):
    """`/environments/compare` must be declared before `/environments/{env_id}`.

    Declared after, FastAPI matches "compare" against the int path parameter
    and answers 422 — the request never reaches this endpoint at all.
    """
    left, right = two_envs
    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": right.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["left"]["name"] == "SIT"
    assert body["right"]["name"] == "UAT"
    assert body["summary"]["compared"] == 0


@pytest.mark.asyncio
async def test_comparing_an_environment_with_itself_is_422(
    client: AsyncClient, auth_headers, two_envs
):
    left, _ = two_envs
    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": left.id},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_environment_is_404(client: AsyncClient, auth_headers, two_envs):
    left, _ = two_envs
    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": 9_999_999},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_another_tenants_environment_is_404(
    client: AsyncClient, auth_headers, db_session, two_envs, second_tenant_factory
):
    """Not 403 — the caller must not learn the environment exists."""
    left, _ = two_envs
    other_tenant, _ = await second_tenant_factory()
    foreign = Environment(
        tenant_id=other_tenant.id, name="Their UAT", environment_type="test")
    db_session.add(foreign)
    await db_session.commit()
    await db_session.refresh(foreign)

    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": foreign.id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_is_401(client: AsyncClient, two_envs):
    left, right = two_envs
    resp = await client.get(
        "/api/v1/environments/compare", params={"left": left.id, "right": right.id})
    assert resp.status_code == 401
