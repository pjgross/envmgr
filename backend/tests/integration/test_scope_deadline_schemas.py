import pytest
from pydantic import ValidationError

from app.api.v1.schemas.gate_criterion import GateCriterionCreate


def test_criterion_accepts_valid_role():
    c = GateCriterionCreate(title="Scope signed off", assigned_role="Release Manager")
    assert c.assigned_role == "Release Manager"


def test_criterion_rejects_unknown_role():
    with pytest.raises(ValidationError):
        GateCriterionCreate(title="x", assigned_role="Wizard")


def test_criterion_rejects_role_and_user_together():
    with pytest.raises(ValidationError):
        GateCriterionCreate(title="x", assigned_role="Release Manager", assigned_to_user_id=5)
