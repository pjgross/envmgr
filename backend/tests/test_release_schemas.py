# backend/tests/test_release_schemas.py
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from app.api.v1.schemas.release import ReleaseCreate, ReleaseUpdate, ReleaseRead


def test_release_create_requires_name_and_type():
    with pytest.raises(ValidationError):
        ReleaseCreate()


def test_release_create_valid():
    m = ReleaseCreate(
        name="R1", release_type="Major",
        lifecycle_template_id=1, template_id=None,
        description=None, target_date=None, custom_fields={},
    )
    assert m.release_kind == "project"


def test_release_update_partial():
    m = ReleaseUpdate(name="newname")
    assert m.name == "newname"
    assert m.target_date is None


def test_release_read_serialises():
    m = ReleaseRead(
        id=1, tenant_id=1, name="R1", description=None,
        release_type="Major", release_kind="project",
        parent_release_id=None, template_id=None,
        lifecycle_template_id=1, status="draft",
        target_date=None, actual_date=None,
        custom_fields={}, raised_by=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    d = m.model_dump()
    assert d["status"] == "draft"
