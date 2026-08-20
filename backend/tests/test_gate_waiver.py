from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models.gate_waiver import GateWaiver
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services.gate_waiver_service import waiver_state


def _waiver(expires_at):
    return GateWaiver(
        tenant_id=1, gate_id=1, reason="r",
        approved_by_user_id=1, created_by=1, expires_at=expires_at,
    )


def test_a_waiver_is_live_all_through_its_expiry_day():
    """A DEADLINE IS A DAY. The UI writes expires_at at T00:00:00Z, so at
    instant precision a waiver expiring today reads expired from one minute
    past midnight — the exact bug A4 shipped and B2 inherited."""
    expiry = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)
    just_after_midnight = datetime(2026, 8, 19, 0, 1, tzinfo=timezone.utc)
    late_in_the_day = datetime(2026, 8, 19, 23, 59, tzinfo=timezone.utc)

    assert waiver_state(_waiver(expiry), just_after_midnight) == "live"
    assert waiver_state(_waiver(expiry), late_in_the_day) == "live"


def test_a_waiver_is_expired_the_day_after():
    expiry = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 8, 20, 0, 1, tzinfo=timezone.utc)
    assert waiver_state(_waiver(expiry), next_day) == "expired"


def test_a_null_expiry_never_expires():
    """NULL means 'no expiry', a legitimate permanent waiver — never confuse it
    with an expired one."""
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert waiver_state(_waiver(None), far_future) == "live"


@pytest_asyncio.fixture
async def gate(db_session, test_tenant, test_user) -> ReleaseGate:
    """A persisted ReleaseGate under a fresh Release in test_tenant."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Test Major",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(template)
    await db_session.flush()

    release = Release(
        tenant_id=test_tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()

    g = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name="SIT Exit",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(g)
    await db_session.commit()
    await db_session.refresh(g)
    return g


@pytest.mark.asyncio
async def test_overriding_a_gate_writes_a_waiver_row(db_session, test_tenant, test_user, gate):
    from app.services import release_gate_service, gate_waiver_service

    await release_gate_service.override_gate(
        db_session, gate.id, notes="accepted risk", tenant_id=test_tenant.id,
        user_id=test_user.id, expires_at=None, remediation="fix in next sprint",
        approved_by_user_id=test_user.id,
    )
    await db_session.flush()

    waivers = await gate_waiver_service.latest_waivers_for_gates(
        db_session, test_tenant.id, [gate.id]
    )
    assert waivers[gate.id].remediation == "fix in next sprint"
    assert gate.status == "overridden"
