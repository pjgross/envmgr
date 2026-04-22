import pytest
from datetime import datetime, timezone
from app.db.models.release_membership import ReleaseMembership, MembershipState


def test_model_defaults():
    m = ReleaseMembership(
        tenant_id=1,
        enterprise_release_id=10,
        project_release_id=20,
        state=MembershipState.PENDING_REQUEST.value,
        requested_by=99,
        requested_at=datetime.now(timezone.utc),
    )
    assert m.late_scope is False or m.late_scope is None  # default before flush


def test_state_enum_values():
    assert MembershipState.PENDING_REQUEST.value == "pending_request"
    assert MembershipState.ACCEPTED.value == "accepted"
    assert MembershipState.REJECTED.value == "rejected"
    assert MembershipState.WITHDRAWN.value == "withdrawn"
    assert MembershipState.REMOVED.value == "removed"
