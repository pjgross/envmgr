"""Integration tests for custom field definition CRUD (tenant admin API)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.core.security import get_password_hash


# ---------------------------------------------------------------------------
# Second-tenant fixtures for isolation tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def other_tenant(db_session) -> Tenant:
    tenant = Tenant(name="Other CF Org", slug="other-cf-org")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def other_user(db_session, other_tenant) -> User:
    user = User(
        tenant_id=other_tenant.id,
        username="othercfadmin",
        email="admin@othercf.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def other_auth_headers(client, other_tenant, other_user) -> dict:
    response = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_field(client, auth_headers, **overrides) -> dict:
    payload = {
        "entity_type": "booking",
        "label": "Ticket Reference",
        "field_type": "text",
        "required": True,
        "display_order": 1,
        **overrides,
    }
    resp = await client.post("/api/v1/tenant/fields", headers=auth_headers, json=payload)
    return resp


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_field_definition(client: AsyncClient, auth_headers: dict):
    resp = await _create_field(client, auth_headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["label"] == "Ticket Reference"
    assert data["field_key"] == "ticket_reference"   # auto-generated from label
    assert data["field_type"] == "text"
    assert data["required"] is True
    assert data["entity_type"] == "booking"


@pytest.mark.asyncio
async def test_create_field_with_explicit_key(client: AsyncClient, auth_headers: dict):
    resp = await _create_field(client, auth_headers, label="My Label", field_key="my_key")
    assert resp.status_code == 201
    assert resp.json()["field_key"] == "my_key"


@pytest.mark.asyncio
async def test_create_field_duplicate_key_returns_409(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, label="A", field_key="dup_key")
    resp = await _create_field(client, auth_headers, label="B", field_key="dup_key")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_fields(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, label="Field One", display_order=2)
    await _create_field(client, auth_headers, label="Field Two", display_order=1)
    resp = await client.get("/api/v1/tenant/fields?entity_type=booking", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["label"] == "Field Two"   # ordered by display_order


@pytest.mark.asyncio
async def test_list_fields_requires_entity_type(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/tenant/fields", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_field(client: AsyncClient, auth_headers: dict):
    create_resp = await _create_field(client, auth_headers)
    field_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/tenant/fields/{field_id}",
        headers=auth_headers,
        json={"label": "Updated Label", "required": False},
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "Updated Label"
    assert resp.json()["required"] is False


@pytest.mark.asyncio
async def test_update_ignores_immutable_fields(client: AsyncClient, auth_headers: dict):
    create_resp = await _create_field(client, auth_headers, field_key="orig_key")
    field_id = create_resp.json()["id"]
    # Sending field_key and field_type in body — should be ignored (not in Update schema)
    resp = await client.patch(
        f"/api/v1/tenant/fields/{field_id}",
        headers=auth_headers,
        json={"label": "New Label"},
    )
    assert resp.status_code == 200
    assert resp.json()["field_key"] == "orig_key"
    assert resp.json()["field_type"] == "text"


@pytest.mark.asyncio
async def test_delete_field(client: AsyncClient, auth_headers: dict):
    create_resp = await _create_field(client, auth_headers)
    field_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/api/v1/tenant/fields/{field_id}", headers=auth_headers)
    assert del_resp.status_code == 204
    # Should not appear in list anymore
    list_resp = await client.get("/api/v1/tenant/fields?entity_type=booking", headers=auth_headers)
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, auth_headers: dict, other_auth_headers: dict):
    await _create_field(client, auth_headers, label="Tenant A Field")
    # Tenant B should see no fields
    resp = await client.get("/api/v1/tenant/fields?entity_type=booking", headers=other_auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_cannot_access_other_tenants_field(client: AsyncClient, auth_headers: dict, other_auth_headers: dict):
    create_resp = await _create_field(client, auth_headers)
    field_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/tenant/fields/{field_id}",
        headers=other_auth_headers,
        json={"label": "Stolen"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_fields(client: AsyncClient, db_session, test_tenant):
    viewer = User(
        tenant_id=test_tenant.id,
        username="viewer1",
        email="viewer@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(viewer)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", json={
        "username": "viewer1", "password": "password123", "tenant_slug": test_tenant.slug
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await _create_field(client, headers)
    assert resp.status_code == 403
