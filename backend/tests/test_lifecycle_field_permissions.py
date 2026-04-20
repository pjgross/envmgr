from app.services.lifecycle_service import get_field_permissions_for_state


DEFINITION = {
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "name": {"editable_by": ["Admin", "Release Manager"]},
                "description": {"editable_by": ["Admin"]},
                "target_date": {"editable_by": []},
            },
            "custom_fields": {
                "sign_off": {"editable_by": ["Admin"]},
                "release_notes": {"editable_by": ["Admin", "Release Manager"]},
            },
        },
        "approved": {
            "standard_fields": {
                "name": {"editable_by": []},
            },
            "custom_fields": {},
        },
    }
}

VALID_STANDARD = {"name", "description", "target_date", "release_type"}
ACTIVE_CUSTOM = {"sign_off", "release_notes", "retired_field"}


def test_returns_both_maps_for_configured_state():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Admin", ACTIVE_CUSTOM, VALID_STANDARD
    )
    assert set(result.keys()) == {"custom_field_permissions", "standard_field_permissions"}
    sp = result["standard_field_permissions"]
    assert sp["name"] == {"editable": True}
    assert sp["description"] == {"editable": True}
    assert sp["target_date"] == {"editable": False}
    assert sp["release_type"] == {"editable": False}
    cp = result["custom_field_permissions"]
    assert cp["sign_off"] == {"visible": True, "editable": True}
    assert cp["release_notes"] == {"visible": True, "editable": True}
    assert "retired_field" not in cp


def test_readonly_role_sees_editable_false():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Developer", ACTIVE_CUSTOM, VALID_STANDARD
    )
    assert all(v == {"editable": False} for v in result["standard_field_permissions"].values())
    assert result["custom_field_permissions"]["sign_off"] == {"visible": True, "editable": False}


def test_soft_deleted_custom_field_excluded():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Admin", {"release_notes"}, VALID_STANDARD
    )
    assert "sign_off" not in result["custom_field_permissions"]
    assert "release_notes" in result["custom_field_permissions"]


def test_unknown_state_returns_all_fields_not_editable():
    result = get_field_permissions_for_state(
        DEFINITION, "unknown_state", "Admin", ACTIVE_CUSTOM, VALID_STANDARD
    )
    assert result["custom_field_permissions"] == {}
    assert all(v == {"editable": False} for v in result["standard_field_permissions"].values())
    assert set(result["standard_field_permissions"].keys()) == VALID_STANDARD


def test_empty_valid_standard_returns_empty_standard_map():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Admin", ACTIVE_CUSTOM, set()
    )
    assert result["standard_field_permissions"] == {}
