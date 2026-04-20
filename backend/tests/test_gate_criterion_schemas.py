from datetime import datetime, timezone, timedelta

from app.api.v1.schemas.gate_criterion import (
    GateCriterionCreate,
    GateCriterionUpdate,
    GateCriterionRead,
)


def test_create_requires_title_only():
    obj = GateCriterionCreate.model_validate({"title": "Zero Sev1 defects"})
    assert obj.title == "Zero Sev1 defects"
    assert obj.due_date is None
    assert obj.assigned_to_user_id is None
    assert obj.notes is None


def test_create_accepts_all_fields():
    due = datetime.now(timezone.utc) + timedelta(days=1)
    obj = GateCriterionCreate.model_validate({
        "title": "Perf test pass", "notes": "p95 < 200ms",
        "due_date": due.isoformat(), "assigned_to_user_id": 42,
    })
    assert obj.notes == "p95 < 200ms"
    assert obj.assigned_to_user_id == 42


def test_update_accepts_partial():
    obj = GateCriterionUpdate.model_validate({"notes": "updated"})
    assert obj.notes == "updated"
    assert obj.title is None  # unset


def test_read_is_overdue_derived():
    """is_overdue is computed by serializer, not stored."""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    obj = GateCriterionRead.model_validate({
        "id": 1, "gate_id": 2, "title": "late", "notes": None,
        "due_date": past, "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "open", "completed_at": None, "completed_by_user_id": None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })
    assert obj.is_overdue is True


def test_read_done_is_never_overdue():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    obj = GateCriterionRead.model_validate({
        "id": 1, "gate_id": 2, "title": "late-but-done", "notes": None,
        "due_date": past, "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "done", "completed_at": datetime.now(timezone.utc),
        "completed_by_user_id": 7,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })
    assert obj.is_overdue is False


def test_read_null_due_date_is_not_overdue():
    obj = GateCriterionRead.model_validate({
        "id": 1, "gate_id": 2, "title": "no-deadline", "notes": None,
        "due_date": None, "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "open", "completed_at": None, "completed_by_user_id": None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })
    assert obj.is_overdue is False
