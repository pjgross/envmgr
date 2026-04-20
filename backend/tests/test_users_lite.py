import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_users_lite_returns_id_and_username(client: AsyncClient, auth_headers: dict, test_user):
    """GET /tenant/users/lite returns {id, username} for tenant members, no admin required."""
    resp = await client.get("/api/v1/tenant/users/lite", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert any(r["id"] == test_user.id and r["username"] == test_user.username for r in rows)
    # Must not leak other fields
    for r in rows:
        assert set(r.keys()) == {"id", "username"}


@pytest.mark.asyncio
async def test_users_lite_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/tenant/users/lite")
    assert resp.status_code in (401, 403)
