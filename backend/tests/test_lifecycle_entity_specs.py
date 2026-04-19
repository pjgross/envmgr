from app.api.v1.schemas.booking_lifecycle import (
    ENTITY_FIELD_SPECS,
    validate_definition_for_entity,
    LifecycleDefinition,
)


def test_release_entity_is_registered():
    assert "release" in ENTITY_FIELD_SPECS
    spec = ENTITY_FIELD_SPECS["release"]
    assert {"name", "description", "release_type", "target_date", "actual_date", "raised_by"} <= set(spec["valid"])


def test_validate_definition_accepts_release_standard_fields():
    definition = LifecycleDefinition.model_validate({
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "completed", "label": "Complete", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {
            "draft": {
                "standard_fields": {
                    "name": {"editable_by": ["Admin"]},
                    "target_date": {"editable_by": ["Admin"]},
                },
                "custom_fields": {},
            },
        },
    })
    validate_definition_for_entity(definition, "release")  # no raise


def test_validate_definition_rejects_unknown_release_standard_field():
    definition = LifecycleDefinition.model_validate({
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "completed", "label": "Complete", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {
            "draft": {
                "standard_fields": {"bogus_field": {"editable_by": ["Admin"]}},
                "custom_fields": {},
            },
        },
    })
    import pytest
    with pytest.raises(ValueError):
        validate_definition_for_entity(definition, "release")
