from app.services.lifecycle_service import validate_transition


DEF_WITH_REQUIRED = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "submitted": {
            "standard_fields": {"name": {"editable_by": ["Admin"]}},
            "custom_fields":   {"sponsor": {"editable_by": ["Admin"]}},
            "required_fields": ["name", "sponsor"],
        },
    },
}


def test_required_fields_block_transition_when_empty():
    record = {"name": "", "custom_fields": {}}
    allowed, reason = validate_transition(DEF_WITH_REQUIRED, "draft", "submitted", "Admin", record)
    assert allowed is False
    assert "name" in reason and "sponsor" in reason


def test_required_fields_allow_transition_when_all_present():
    record = {"name": "my release", "custom_fields": {"sponsor": "alice"}}
    allowed, reason = validate_transition(DEF_WITH_REQUIRED, "draft", "submitted", "Admin", record)
    assert allowed is True
    assert reason is None


def test_role_block_comes_before_required_fields_check():
    record = {"name": "", "custom_fields": {}}
    allowed, reason = validate_transition(DEF_WITH_REQUIRED, "draft", "submitted", "Viewer", record)
    assert allowed is False
    assert "role" in reason.lower() or "not allowed" in reason.lower()


def test_backward_compat_empty_record_no_required_fields():
    definition_no_required = {
        "transitions": [{"from_state": "draft", "to_state": "submitted", "allowed_roles": ["Admin"]}],
        "field_permissions": {"submitted": {"standard_fields": {}, "custom_fields": {}}},
    }
    allowed, reason = validate_transition(definition_no_required, "draft", "submitted", "Admin", {})
    assert allowed is True
    assert reason is None
