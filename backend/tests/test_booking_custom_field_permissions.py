import pytest
from httpx import AsyncClient
from tests.factories import post_environment

DEFINITION_WITH_CUSTOM_FIELDS = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "project_name": {"editable_by": ["Admin"]},
                "start_date": {"editable_by": ["Admin"]},
                "end_date": {"editable_by": ["Admin"]},
                "booking_type": {"editable_by": ["Admin"]},
            },
            "custom_fields": {
                "release_notes": {"editable_by": ["Admin", "Release Manager"]},
                "sign_off": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "standard_fields": {},
            "custom_fields": {
                "sign_off": {"editable_by": []},
            },
        },
    },
}


@pytest.mark.asyncio
async def test_create_template_with_custom_field_permissions(client: AsyncClient, auth_headers: dict):
    """Template with custom_fields in field_permissions creates successfully."""
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "CF Test", "definition": DEFINITION_WITH_CUSTOM_FIELDS},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    draft_perms = data["definition"]["field_permissions"]["draft"]
    assert "custom_fields" in draft_perms
    assert draft_perms["custom_fields"]["release_notes"]["editable_by"] == ["Admin", "Release Manager"]


@pytest.mark.asyncio
async def test_create_template_with_unknown_role_in_custom_field_is_accepted(client: AsyncClient, auth_headers: dict):
    """custom_fields.editable_by with unknown role strings are accepted (no strict role validation).
    Legacy data may contain non-standard role strings — consistent with LifecycleTransition behaviour."""
    bad_def = {
        "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
        "transitions": [],
        "field_permissions": {
            "draft": {
                "standard_fields": {
                    "project_name": {"editable_by": ["Admin"]},
                    "start_date": {"editable_by": ["Admin"]},
                    "end_date": {"editable_by": ["Admin"]},
                    "booking_type": {"editable_by": ["Admin"]},
                },
                "custom_fields": {
                    "my_field": {"editable_by": ["NotARealRole"]},
                },
            }
        },
    }
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Unknown Roles", "definition": bad_def},
    )
    assert resp.status_code == 201, resp.text


from app.services.lifecycle_service import get_custom_field_permissions

DEFINITION = {
    "field_permissions": {
        "draft": {
            "editable_fields": [],
            "editable_by": [],
            "custom_fields": {
                "release_notes": {"editable_by": ["Admin", "Release Manager"]},
                "sign_off": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "editable_fields": [],
            "editable_by": [],
            "custom_fields": {
                "sign_off": {"editable_by": []},
            },
        },
    }
}

ACTIVE_KEYS = {"release_notes", "sign_off", "other_field"}


def test_get_custom_field_permissions_editable_role():
    """Admin in draft can edit release_notes."""
    result = get_custom_field_permissions(DEFINITION, "draft", "Admin", ACTIVE_KEYS)
    assert result["release_notes"] == {"visible": True, "editable": True}
    assert result["sign_off"] == {"visible": True, "editable": True}


def test_get_custom_field_permissions_readonly_role():
    """Developer in draft cannot edit — not in any editable_by."""
    result = get_custom_field_permissions(DEFINITION, "draft", "Developer", ACTIVE_KEYS)
    assert result["release_notes"] == {"visible": True, "editable": False}
    assert result["sign_off"] == {"visible": True, "editable": False}


def test_get_custom_field_permissions_field_hidden_in_state():
    """release_notes not listed in submitted → absent from result."""
    result = get_custom_field_permissions(DEFINITION, "submitted", "Admin", ACTIVE_KEYS)
    assert "release_notes" not in result
    assert result["sign_off"] == {"visible": True, "editable": False}  # editable_by: []


def test_get_custom_field_permissions_soft_deleted_field_excluded():
    """Field key in template but not in active_field_keys is excluded."""
    result = get_custom_field_permissions(DEFINITION, "draft", "Admin", {"release_notes"})
    assert "release_notes" in result
    assert "sign_off" not in result  # not in active_keys


def test_get_custom_field_permissions_state_not_in_template():
    """State with no field_permissions entry returns empty dict."""
    result = get_custom_field_permissions(DEFINITION, "approved", "Admin", ACTIVE_KEYS)
    assert result == {}


def test_get_custom_field_permissions_no_custom_fields_in_state():
    """State entry with no custom_fields key returns empty dict."""
    definition = {
        "field_permissions": {
            "draft": {"standard_fields": {"project_name": {"editable_by": ["Admin"]}}},
        }
    }
    result = get_custom_field_permissions(definition, "draft", "Admin", {"any_key"})
    assert result == {}


# Note: uses a different constant name to avoid clash with DEFINITION_WITH_CUSTOM_FIELDS from Task 1
BOOKING_DEF = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "project_name": {"editable_by": ["Admin"]},
                "start_date": {"editable_by": ["Admin"]},
                "end_date": {"editable_by": ["Admin"]},
                "booking_type": {"editable_by": ["Admin"]},
            },
            "custom_fields": {
                "release_notes": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "standard_fields": {},
            "custom_fields": {},
        },
    },
}


async def _setup_booking_with_cf_template(client, auth_headers):
    """Create template, booking type, environment, and booking. Return booking_id."""
    tmpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "CF Template", "definition": BOOKING_DEF},
    )
    template_id = tmpl.json()["id"]
    bt = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "CF Type", "lifecycle_template_id": template_id},
    )
    bt_id = bt.json()["id"]

    # Create custom field definition
    await client.post(
        "/api/v1/tenant/fields",
        headers=auth_headers,
        json={"entity_type": "booking", "label": "Release Notes", "field_key": "release_notes", "field_type": "text"},
    )

    env = await post_environment(client, auth_headers, "CFTestEnv")
    env_id = env.json()["id"]

    booking = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "CF Project",
            "start_date": "2026-04-01T09:00:00Z",
            "end_date": "2026-04-01T17:00:00Z",
            "booking_type_id": bt_id,
            "custom_fields": {"release_notes": "initial notes"},
        },
    )
    return booking.json()["booking"]["id"]


@pytest.mark.asyncio
async def test_get_booking_includes_custom_field_permissions(client: AsyncClient, auth_headers: dict):
    """GET /bookings/{id} includes custom_field_permissions resolved for current state+role."""
    booking_id = await _setup_booking_with_cf_template(client, auth_headers)

    resp = await client.get(f"/api/v1/bookings/{booking_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "custom_field_permissions" in data
    # Booking is in draft; Admin can edit release_notes
    assert data["custom_field_permissions"]["release_notes"] == {"visible": True, "editable": True}


