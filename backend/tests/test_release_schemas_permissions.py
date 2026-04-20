from app.api.v1.schemas.release import ReleaseRead


def test_release_read_accepts_permissions_fields():
    """ReleaseRead must accept custom_field_permissions and standard_field_permissions."""
    data = {
        "id": 1, "tenant_id": 1, "name": "R1", "description": None,
        "release_type": "project", "release_kind": "project",
        "parent_release_id": None, "template_id": None,
        "lifecycle_template_id": 2, "status": "draft",
        "target_date": None, "actual_date": None,
        "custom_fields": None, "raised_by": 3,
        "created_at": "2026-04-20T00:00:00Z", "updated_at": "2026-04-20T00:00:00Z",
        "custom_field_permissions": {"sign_off": {"visible": True, "editable": True}},
        "standard_field_permissions": {"name": {"editable": True}},
    }
    obj = ReleaseRead.model_validate(data)
    assert obj.custom_field_permissions == {"sign_off": {"visible": True, "editable": True}}
    assert obj.standard_field_permissions == {"name": {"editable": True}}


def test_release_read_permissions_fields_optional():
    """Both permissions fields default to None when omitted."""
    data = {
        "id": 1, "tenant_id": 1, "name": "R1", "description": None,
        "release_type": "project", "release_kind": "project",
        "parent_release_id": None, "template_id": None,
        "lifecycle_template_id": 2, "status": "draft",
        "target_date": None, "actual_date": None,
        "custom_fields": None, "raised_by": 3,
        "created_at": "2026-04-20T00:00:00Z", "updated_at": "2026-04-20T00:00:00Z",
    }
    obj = ReleaseRead.model_validate(data)
    assert obj.custom_field_permissions is None
    assert obj.standard_field_permissions is None
