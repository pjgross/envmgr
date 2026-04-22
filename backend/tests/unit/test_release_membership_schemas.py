import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.api.v1.schemas.release_membership import (
    ReleaseMembershipCreate,
    ReleaseMembershipRead,
    MembershipRejectRequest,
    MembershipRemoveRequest,
)


def test_create_requires_project_release_id():
    with pytest.raises(ValidationError):
        ReleaseMembershipCreate()


def test_create_with_notes():
    m = ReleaseMembershipCreate(project_release_id=42, notes="nominating team A")
    assert m.project_release_id == 42


def test_reject_requires_notes():
    with pytest.raises(ValidationError):
        MembershipRejectRequest()


def test_remove_requires_reason():
    with pytest.raises(ValidationError):
        MembershipRemoveRequest()
