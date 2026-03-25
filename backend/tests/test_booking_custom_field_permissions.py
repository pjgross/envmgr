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
