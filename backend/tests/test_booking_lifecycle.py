import pytest
from httpx import AsyncClient


DEFAULT_DEFINITION = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin", "ReleaseManager", "User"]},
        {"from_state": "submitted", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "submitted", "to_state": "rejected", "label": "Reject", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "submitted", "to_state": "draft", "label": "Return", "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft": {"editable_fields": ["project_name", "notes"], "editable_by": ["Admin", "ReleaseManager", "User"]},
        "submitted": {"editable_fields": ["notes"], "editable_by": ["Admin", "ReleaseManager"]},
        "approved": {"editable_fields": [], "editable_by": []},
        "rejected": {"editable_fields": [], "editable_by": []},
    }
}


@pytest.mark.asyncio
async def test_create_lifecycle_template(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Test Lifecycle", "definition": DEFAULT_DEFINITION},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Test Lifecycle"
    assert data["tenant_id"] is not None


@pytest.mark.asyncio
async def test_update_template_propagates(client: AsyncClient, auth_headers: dict):
    """Updating a template is reflected on booking types that reference it."""
    t_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Propagation Test", "definition": DEFAULT_DEFINITION},
    )
    template_id = t_resp.json()["id"]

    # Create booking type referencing this template
    bt_resp = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "My Type", "lifecycle_template_id": template_id},
    )
    assert bt_resp.status_code == 201, bt_resp.text

    # Update template name
    upd = await client.put(
        f"/api/v1/tenant/lifecycle-templates/{template_id}",
        headers=auth_headers,
        json={"name": "Updated Name"},
    )
    assert upd.status_code == 200

    # Booking type still references updated template
    bt_get = await client.get(f"/api/v1/tenant/booking-types/{bt_resp.json()['id']}", headers=auth_headers)
    assert bt_get.json()["lifecycle_template_id"] == template_id


@pytest.mark.asyncio
async def test_copy_template_is_independent(client: AsyncClient, auth_headers: dict):
    """Copying a template creates an independent copy — updating the original does not affect the copy."""
    t_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Original", "definition": DEFAULT_DEFINITION},
    )
    original_id = t_resp.json()["id"]

    copy_resp = await client.post(
        f"/api/v1/tenant/lifecycle-templates/{original_id}/copy",
        headers=auth_headers,
        json={"name": "Copy"},
    )
    assert copy_resp.status_code == 201
    copy_id = copy_resp.json()["id"]
    assert copy_id != original_id

    # Update original — copy should still have old name
    await client.put(
        f"/api/v1/tenant/lifecycle-templates/{original_id}",
        headers=auth_headers,
        json={"name": "Original Modified"},
    )
    copy_get = await client.get(f"/api/v1/tenant/lifecycle-templates/{copy_id}", headers=auth_headers)
    assert copy_get.json()["name"] == "Copy"


@pytest.mark.asyncio
async def test_invalid_lifecycle_definition_rejected(client: AsyncClient, auth_headers: dict):
    """Definition with zero initial states is rejected with 422."""
    bad_definition = {**DEFAULT_DEFINITION, "states": [
        {"key": "draft", "label": "Draft", "is_initial": False, "is_terminal": False},
    ]}
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Bad", "definition": bad_definition},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_booking_type(client: AsyncClient, auth_headers: dict):
    t_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "TL", "definition": DEFAULT_DEFINITION},
    )
    resp = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "My Type", "lifecycle_template_id": t_resp.json()["id"], "color": "#FF5733"},
    )
    assert resp.status_code == 201
    assert resp.json()["color"] == "#FF5733"
