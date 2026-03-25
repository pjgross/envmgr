"""Unit and integration tests for standard field permissions in lifecycle templates."""
import pytest
from pydantic import ValidationError
from app.api.v1.schemas.booking_lifecycle import (
    LifecycleDefinition,
    LifecycleFieldPermission,
    StandardFieldPermission,
    VALID_STANDARD_FIELD_NAMES,
    MANDATORY_STANDARD_FIELDS,
)

# --- Minimal valid definition with all mandatory fields editable in initial state ---

def _make_definition(draft_standard_fields: dict) -> dict:
    """Build a minimal LifecycleDefinition dict with given draft standard_fields."""
    return {
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "closed", "label": "Closed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "closed", "label": "Close", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {
            "draft": {"standard_fields": draft_standard_fields},
            "closed": {"standard_fields": {}},
        },
    }


MANDATORY_EDITABLE = {
    "project_name": {"editable_by": ["Admin"]},
    "start_date": {"editable_by": ["Admin"]},
    "end_date": {"editable_by": ["Admin"]},
    "booking_type": {"editable_by": ["Admin"]},
}


def test_valid_standard_fields():
    """LifecycleDefinition with all mandatory fields editable in initial state validates."""
    d = _make_definition(MANDATORY_EDITABLE)
    obj = LifecycleDefinition.model_validate(d)
    assert obj.states[0].is_initial is True


def test_invalid_standard_field_name():
    """standard_fields with unknown key is rejected with 422-style ValidationError."""
    fields = {**MANDATORY_EDITABLE, "nonexistent_field": {"editable_by": ["Admin"]}}
    d = _make_definition(fields)
    with pytest.raises(ValidationError, match="Invalid standard field names"):
        LifecycleDefinition.model_validate(d)


def test_invalid_role_in_standard_field():
    """standard_fields with invalid role raises ValidationError."""
    fields = {**MANDATORY_EDITABLE, "notes": {"editable_by": ["NotARealRole"]}}
    d = _make_definition(fields)
    with pytest.raises(ValidationError):
        LifecycleDefinition.model_validate(d)


def test_mandatory_field_missing_from_initial_state():
    """Initial state with a mandatory field missing from standard_fields is rejected."""
    incomplete = {k: v for k, v in MANDATORY_EDITABLE.items() if k != "start_date"}
    d = _make_definition(incomplete)
    with pytest.raises(ValidationError, match="start_date"):
        LifecycleDefinition.model_validate(d)


def test_mandatory_field_no_roles_in_initial_state():
    """Mandatory field with empty editable_by in initial state is rejected."""
    fields = {**MANDATORY_EDITABLE, "start_date": {"editable_by": []}}
    d = _make_definition(fields)
    with pytest.raises(ValidationError, match="start_date"):
        LifecycleDefinition.model_validate(d)


@pytest.mark.parametrize("field", ["notes", "exclusive_use", "context_tag"])
def test_non_mandatory_field_can_be_readonly(field):
    """Non-mandatory fields with no roles do not fail validation."""
    fields = {**MANDATORY_EDITABLE, field: {"editable_by": []}}
    d = _make_definition(fields)
    LifecycleDefinition.model_validate(d)  # should not raise


def test_valid_standard_field_names_constant():
    """VALID_STANDARD_FIELD_NAMES contains the 7 expected keys."""
    assert VALID_STANDARD_FIELD_NAMES == {
        "project_name", "start_date", "end_date", "booking_type",
        "notes", "exclusive_use", "context_tag",
    }


def test_mandatory_standard_fields_constant():
    """MANDATORY_STANDARD_FIELDS contains the 4 expected mandatory keys."""
    assert MANDATORY_STANDARD_FIELDS == {"project_name", "start_date", "end_date", "booking_type"}


# --- Migration tests ---

from app.services.booking_lifecycle_service import migrate_field_permissions


def test_migrate_old_shape_converts_to_standard_fields():
    """Old editable_fields/editable_by shape is converted per-field."""
    old = {
        "states": [{"key": "draft", "is_initial": True}],
        "field_permissions": {
            "draft": {
                "editable_fields": ["project_name", "start_date"],
                "editable_by": ["Admin", "Release Manager"],
                "custom_fields": {"release_notes": {"editable_by": ["Admin"]}},
            },
            "closed": {
                "editable_fields": [],
                "editable_by": [],
            },
        },
    }
    result = migrate_field_permissions(old)
    draft = result["field_permissions"]["draft"]
    assert draft["standard_fields"]["project_name"]["editable_by"] == ["Admin", "Release Manager"]
    assert draft["standard_fields"]["start_date"]["editable_by"] == ["Admin", "Release Manager"]
    # Fields NOT in editable_fields get empty editable_by
    assert draft["standard_fields"]["notes"]["editable_by"] == []
    assert draft["standard_fields"]["booking_type"]["editable_by"] == []
    # custom_fields preserved
    assert draft["custom_fields"]["release_notes"]["editable_by"] == ["Admin"]
    # editable_fields/editable_by removed
    assert "editable_fields" not in draft
    assert "editable_by" not in draft


def test_migrate_new_shape_is_noop():
    """Definition already using standard_fields is returned unchanged."""
    new = {
        "field_permissions": {
            "draft": {
                "standard_fields": {"project_name": {"editable_by": ["Admin"]}},
            },
        },
    }
    result = migrate_field_permissions(new)
    assert result["field_permissions"]["draft"]["standard_fields"]["project_name"]["editable_by"] == ["Admin"]
    assert "editable_fields" not in result["field_permissions"]["draft"]


def test_migrate_empty_definition():
    """Definition with no field_permissions is returned unchanged."""
    d = {"states": [], "transitions": [], "field_permissions": {}}
    result = migrate_field_permissions(d)
    assert result["field_permissions"] == {}


def test_migrate_mixed_shape():
    """Definition where some states are old shape and some are new shape — only old states converted."""
    mixed = {
        "field_permissions": {
            "draft": {
                "editable_fields": ["notes"],
                "editable_by": ["Admin"],
            },
            "submitted": {
                "standard_fields": {"project_name": {"editable_by": ["Admin"]}},
            },
        },
    }
    result = migrate_field_permissions(mixed)
    # draft converted
    assert "standard_fields" in result["field_permissions"]["draft"]
    assert "editable_fields" not in result["field_permissions"]["draft"]
    # submitted unchanged
    assert result["field_permissions"]["submitted"]["standard_fields"]["project_name"]["editable_by"] == ["Admin"]


# --- get_standard_field_permissions pure function tests ---

from app.services.booking_service import get_standard_field_permissions

SF_DEFINITION = {
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "project_name": {"editable_by": ["Admin", "Developer"]},
                "start_date": {"editable_by": ["Admin"]},
                "end_date": {"editable_by": ["Admin"]},
                "booking_type": {"editable_by": ["Admin"]},
                "notes": {"editable_by": []},
            }
        },
        "submitted": {
            "standard_fields": {}
        },
    }
}


def test_get_standard_field_permissions_editable_role():
    """Admin in draft can edit project_name and start_date."""
    result = get_standard_field_permissions(SF_DEFINITION, "draft", "Admin")
    assert "project_name" in result
    assert "start_date" in result


def test_get_standard_field_permissions_non_editable_field():
    """notes has empty editable_by — not in result for any role."""
    result = get_standard_field_permissions(SF_DEFINITION, "draft", "Admin")
    assert "notes" not in result


def test_get_standard_field_permissions_role_without_access():
    """Developer in draft can edit project_name but not start_date."""
    result = get_standard_field_permissions(SF_DEFINITION, "draft", "Developer")
    assert "project_name" in result
    assert "start_date" not in result


def test_get_standard_field_permissions_non_initial_state():
    """submitted state has no standard_fields — empty set returned."""
    result = get_standard_field_permissions(SF_DEFINITION, "submitted", "Admin")
    assert result == set()


def test_get_standard_field_permissions_unknown_state():
    """State not in field_permissions returns empty set (fail-closed)."""
    result = get_standard_field_permissions(SF_DEFINITION, "nonexistent", "Admin")
    assert result == set()
