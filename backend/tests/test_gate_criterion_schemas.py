from datetime import datetime, timezone, timedelta

from app.api.v1.schemas.gate_criterion import (
    GateCriterionCreate,
    GateCriterionUpdate,
    GateCriterionRead,
    GateCriterionWithGate,
)


def test_create_requires_title_only():
    obj = GateCriterionCreate.model_validate({"title": "Zero Sev1 defects"})
    assert obj.title == "Zero Sev1 defects"
    assert obj.assigned_to_user_id is None
    assert obj.notes is None


def test_create_accepts_all_fields():
    obj = GateCriterionCreate.model_validate({
        "title": "Perf test pass", "notes": "p95 < 200ms",
        "assigned_to_user_id": 42,
    })
    assert obj.notes == "p95 < 200ms"
    assert obj.assigned_to_user_id == 42


def test_update_accepts_partial():
    obj = GateCriterionUpdate.model_validate({"notes": "updated"})
    assert obj.notes == "updated"
    assert obj.title is None  # unset


def test_read_basic_fields():
    now = datetime.now(timezone.utc)
    obj = GateCriterionRead.model_validate({
        "id": 1, "gate_id": 2, "title": "a criterion", "notes": None,
        "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "open", "completed_at": None, "completed_by_user_id": None,
        "created_at": now, "updated_at": now,
    })
    assert obj.id == 1
    assert obj.gate_id == 2
    assert obj.status == "open"


def test_criterion_with_gate_carries_gate_due_date():
    """GateCriterionWithGate exposes gate_name and gate_due_date (not per-criterion due_date)."""
    now = datetime.now(timezone.utc)
    gate_due = now + timedelta(days=5)
    obj = GateCriterionWithGate.model_validate({
        "id": 1, "gate_id": 2, "title": "a criterion", "notes": None,
        "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "open", "completed_at": None, "completed_by_user_id": None,
        "created_at": now, "updated_at": now,
        "gate_name": "SIT Exit", "gate_due_date": gate_due,
    })
    assert obj.gate_name == "SIT Exit"
    assert obj.gate_due_date == gate_due
