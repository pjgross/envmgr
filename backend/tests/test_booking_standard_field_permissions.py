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


def test_non_mandatory_field_can_be_readonly():
    """Non-mandatory field (notes) with no roles does not fail validation."""
    fields = {**MANDATORY_EDITABLE, "notes": {"editable_by": []}}
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
