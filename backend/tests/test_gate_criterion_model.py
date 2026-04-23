from datetime import datetime, timezone
import pytest

from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.db.models.gate_criterion import GateCriterion


@pytest.mark.asyncio
async def test_gate_criterion_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    gate = ReleaseGate(
        tenant_id=tenant.id, release_id=release.id, name="SIT Exit", status="pending",
        due_date=datetime.now(timezone.utc),
    )
    db_session.add(gate); await db_session.flush()

    crit = GateCriterion(
        tenant_id=tenant.id, gate_id=gate.id,
        title="Zero Sev1 defects", notes="blocker list in Jira",
        assigned_to_user_id=user.id, status="open",
    )
    db_session.add(crit); await db_session.flush()

    assert crit.id is not None
    assert crit.status == "open"
    assert crit.completed_at is None
    assert crit.deleted_at is None


@pytest.mark.asyncio
async def test_gate_criterion_defaults(db_session, tenant, user, release_lifecycle_template):
    """Required fields only; status defaults to 'open'."""
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    gate = ReleaseGate(tenant_id=tenant.id, release_id=release.id, name="G", status="pending",
                      due_date=datetime.now(timezone.utc))
    db_session.add(gate); await db_session.flush()

    crit = GateCriterion(tenant_id=tenant.id, gate_id=gate.id, title="Minimal")
    db_session.add(crit); await db_session.flush()

    assert crit.status == "open"
    assert crit.assigned_to_user_id is None
    assert crit.notes is None
