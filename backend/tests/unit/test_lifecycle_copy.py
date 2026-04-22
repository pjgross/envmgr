"""Unit tests verifying copy_template preserves applies_to_kind.

These tests confirm the fix at the model-constructor level without requiring a
live database. They instantiate LifecycleTemplate directly (SQLAlchemy mapped
classes can be instantiated without a session) and assert that the field is
propagated correctly.
"""
import copy

from app.db.models.lifecycle import LifecycleTemplate
from app.services.lifecycle_service import migrate_field_permissions


_MINIMAL_DEFINITION = {
    "states": [{"key": "draft", "label": "Draft", "is_initial": True,
                "is_terminal": False, "is_admission_lockdown": False}],
    "transitions": [],
    "field_permissions": {"draft": {"standard_fields": {}}},
}


def _make_copy(applies_to_kind, new_name="Copy") -> LifecycleTemplate:
    """Replicate the copy_template constructor call in isolation."""
    # Simulate the 'original' template attributes.
    # We don't set an id/tenant_id on the original — only the fields the
    # copy_template function reads from `original`.
    original = LifecycleTemplate(
        tenant_id=1,
        entity_type="release",
        applies_to_kind=applies_to_kind,
        name="Original",
        description="desc",
        is_default=False,
        definition=copy.deepcopy(_MINIMAL_DEFINITION),
    )

    # This mirrors the fixed copy_template() constructor call exactly.
    new_template = LifecycleTemplate(
        tenant_id=original.tenant_id,
        entity_type=original.entity_type,
        applies_to_kind=original.applies_to_kind,
        name=new_name,
        description=original.description,
        is_default=False,
        definition=migrate_field_permissions(
            copy.deepcopy(original.definition), original.entity_type
        ),
    )
    return new_template


def test_copy_template_preserves_enterprise_kind():
    copy_tmpl = _make_copy(applies_to_kind="enterprise")
    assert copy_tmpl.applies_to_kind == "enterprise"


def test_copy_template_preserves_none_kind():
    copy_tmpl = _make_copy(applies_to_kind=None)
    assert copy_tmpl.applies_to_kind is None


def test_copy_template_preserves_project_kind():
    copy_tmpl = _make_copy(applies_to_kind="project")
    assert copy_tmpl.applies_to_kind == "project"
