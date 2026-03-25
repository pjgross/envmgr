import pytest
from httpx import AsyncClient

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
            "editable_fields": ["project_name"],
            "editable_by": ["Admin"],
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
async def test_create_template_with_invalid_role_in_custom_field(client: AsyncClient, auth_headers: dict):
    """custom_fields.editable_by with an invalid role returns 422."""
    bad_def = {
        "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
        "transitions": [],
        "field_permissions": {
            "draft": {
                "editable_fields": [],
                "editable_by": [],
                "custom_fields": {
                    "my_field": {"editable_by": ["NotARealRole"]},
                },
            }
        },
    }
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Bad Roles", "definition": bad_def},
    )
    assert resp.status_code == 422, resp.text


from app.services.booking_lifecycle_service import get_custom_field_permissions

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
            "draft": {"editable_fields": ["project_name"], "editable_by": ["Admin"]},
        }
    }
    result = get_custom_field_permissions(definition, "draft", "Admin", {"any_key"})
    assert result == {}
