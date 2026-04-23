import pytest
from pydantic import ValidationError

from app.api.v1.schemas.booking_lifecycle import (
    LifecycleDefinition,
    LifecycleState,
    validate_definition_for_entity,
)


def test_state_accepts_is_admission_lockdown_flag():
    s = LifecycleState(key="x", label="X", is_initial=True, is_admission_lockdown=True)
    assert s.is_admission_lockdown is True


def test_state_default_is_admission_lockdown_false():
    s = LifecycleState(key="x", label="X", is_initial=True)
    assert s.is_admission_lockdown is False


def test_definition_accepts_action_permissions_block():
    d = LifecycleDefinition(
        states=[LifecycleState(key="draft", label="Draft", is_initial=True)],
        transitions=[],
        field_permissions={"draft": {"standard_fields": {}}},
        action_permissions={
            "draft": {"membership.admit": ["Admin"], "membership.reject": ["Admin"]}
        },
    )
    assert d.action_permissions["draft"]["membership.admit"] == ["Admin"]


def test_enterprise_kind_validation_single_lockdown_state():
    d = LifecycleDefinition(
        states=[
            LifecycleState(key="a", label="A", is_initial=True, is_admission_lockdown=True),
            LifecycleState(key="b", label="B", is_admission_lockdown=True),
        ],
        transitions=[],
        field_permissions={"a": {"standard_fields": {}}, "b": {"standard_fields": {}}},
    )
    with pytest.raises(ValueError, match="at most one"):
        validate_definition_for_entity(d, "release", applies_to_kind="enterprise")


def test_enterprise_kind_validation_rejects_unknown_action_key():
    d = LifecycleDefinition(
        states=[LifecycleState(key="draft", label="Draft", is_initial=True)],
        transitions=[],
        field_permissions={"draft": {"standard_fields": {}}},
        action_permissions={"draft": {"membership.bogus": ["Admin"]}},
    )
    with pytest.raises(ValueError, match="unknown action_key"):
        validate_definition_for_entity(d, "release", applies_to_kind="enterprise")


def test_non_enterprise_rejects_action_permissions():
    # Use entity_type="release" which has no mandatory fields, so the
    # action_permissions guard (in the else branch) is reached cleanly.
    d = LifecycleDefinition(
        states=[LifecycleState(key="draft", label="Draft", is_initial=True)],
        transitions=[],
        field_permissions={"draft": {"standard_fields": {}}},
        action_permissions={"draft": {"membership.admit": ["Admin"]}},
    )
    # Non-enterprise release template (applies_to_kind="project")
    with pytest.raises(ValueError, match="action_permissions only valid"):
        validate_definition_for_entity(d, "release", applies_to_kind="project")
    # Release template with no applies_to_kind
    with pytest.raises(ValueError, match="action_permissions only valid"):
        validate_definition_for_entity(d, "release", applies_to_kind=None)


def test_non_enterprise_rejects_lockdown_flag():
    # Use entity_type="release" (no mandatory fields) so the lockdown guard fires.
    d = LifecycleDefinition(
        states=[LifecycleState(key="draft", label="Draft", is_initial=True, is_admission_lockdown=True)],
        transitions=[],
        field_permissions={"draft": {"standard_fields": {}}},
    )
    with pytest.raises(ValueError, match="is_admission_lockdown only valid"):
        validate_definition_for_entity(d, "release", applies_to_kind="project")
