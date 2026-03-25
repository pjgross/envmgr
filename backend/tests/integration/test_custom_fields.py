"""Integration tests for custom field definition CRUD (tenant admin API)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.core.security import get_password_hash


DEFAULT_TEST_DEFINITION = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
        {"key": "closed", "label": "Closed", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin", "Release Manager", "Developer"]},
        {"from_state": "submitted", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin", "Release Manager"]},
        {"from_state": "submitted", "to_state": "rejected", "label": "Reject", "allowed_roles": ["Admin", "Release Manager"]},
        {"from_state": "approved", "to_state": "closed", "label": "Close", "allowed_roles": ["Admin", "Release Manager"]},
    ],
    "field_permissions": {
        "draft": {"editable_fields": ["project_name", "start_date", "end_date", "notes", "exclusive_use", "custom_fields"], "editable_by": ["Admin", "Release Manager", "Developer"]},
        "submitted": {"editable_fields": ["notes"], "editable_by": ["Admin", "Release Manager"]},
        "approved": {"editable_fields": ["notes"], "editable_by": ["Admin", "Release Manager"]},
        "rejected": {"editable_fields": [], "editable_by": []},
        "closed": {"editable_fields": [], "editable_by": []},
    }
}


@pytest_asyncio.fixture
async def default_booking_type_id(client: AsyncClient, auth_headers: dict) -> int:
    tmpl_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Test Lifecycle CF", "definition": DEFAULT_TEST_DEFINITION},
    )
    assert tmpl_resp.status_code == 201, tmpl_resp.text
    template_id = tmpl_resp.json()["id"]
    bt_resp = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "Test Type CF", "lifecycle_template_id": template_id},
    )
    assert bt_resp.status_code == 201, bt_resp.text
    return bt_resp.json()["id"]


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
    # Sending field_key and field_type in body — schema should discard them silently
    resp = await client.patch(
        f"/api/v1/tenant/fields/{field_id}",
        headers=auth_headers,
        json={"label": "New Label", "field_key": "hacked_key", "field_type": "number"},
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


# ---------------------------------------------------------------------------
# Validation tests (requires entity creation endpoints)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_required_field_blocks_booking_creation(client: AsyncClient, auth_headers: dict, default_booking_type_id: int):
    # Define a required text field on bookings
    await _create_field(client, auth_headers, label="Ticket Ref", field_key="ticket_ref", required=True)
    # Create an environment to book
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    # Attempt to create booking without the required custom field
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type_id": default_booking_type_id,
        "exclusive_use": False,
    })
    assert resp.status_code == 422
    assert "ticket_ref" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_required_field_passes_when_provided(client: AsyncClient, auth_headers: dict, default_booking_type_id: int):
    await _create_field(client, auth_headers, label="Ticket Ref", field_key="ticket_ref", required=True)
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env 2", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type_id": default_booking_type_id,
        "exclusive_use": False,
        "custom_fields": {"ticket_ref": "JIRA-123"},
    })
    assert resp.status_code == 201
    assert resp.json()["booking"]["custom_fields"]["ticket_ref"] == "JIRA-123"


@pytest.mark.asyncio
async def test_number_field_rejects_non_numeric(client: AsyncClient, auth_headers: dict, default_booking_type_id: int):
    await _create_field(client, auth_headers, label="Team Size", field_key="team_size", field_type="number", required=False)
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env 3", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type_id": default_booking_type_id,
        "exclusive_use": False,
        "custom_fields": {"team_size": "not-a-number"},
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unknown_custom_field_keys_are_accepted(client: AsyncClient, auth_headers: dict, default_booking_type_id: int):
    """Unknown keys (e.g. from soft-deleted fields) must not cause errors."""
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env 4", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type_id": default_booking_type_id,
        "exclusive_use": False,
        "custom_fields": {"orphaned_old_key": "some value"},
    })
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_required_field_blocks_system_creation(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, entity_type="system", label="Owner", field_key="owner", required=True)
    resp = await client.post("/api/v1/systems/", headers=auth_headers, json={"name": "MySys"})
    assert resp.status_code == 422
    assert "owner" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_partial_update_without_custom_fields_succeeds(client: AsyncClient, auth_headers: dict):
    """A PATCH that omits custom_fields should not trigger required-field validation."""
    # Create a required field
    await _create_field(client, auth_headers, entity_type="system", label="Owner", field_key="owner2", required=True)
    # Create a system (with the required field satisfied)
    sys_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "TestSysPartial", "custom_fields": {"owner2": "Alice"}},
    )
    assert sys_resp.status_code == 201, sys_resp.text
    sys_id = sys_resp.json()["id"]
    # Now PATCH only the name — should NOT require custom_fields
    patch_resp = await client.patch(
        f"/api/v1/systems/{sys_id}",
        headers=auth_headers,
        json={"name": "UpdatedName"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["name"] == "UpdatedName"
