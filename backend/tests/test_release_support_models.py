from datetime import datetime, timezone
import pytest
from app.db.models.release import Release
from app.db.models.test_phase import TestPhase
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_system import ReleaseSystem
from app.db.models.release_dependency import ReleaseDependency


@pytest.mark.asyncio
async def test_release_gate_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()
    phase = TestPhase(tenant_id=tenant.id, release_id=release.id, name="SIT", order=1, status="pending")
    db_session.add(phase); await db_session.flush()
    gate = ReleaseGate(
        tenant_id=tenant.id, release_id=release.id, test_phase_id=phase.id,
        name="SIT Exit", status="pending",
    )
    db_session.add(gate); await db_session.flush()
    assert gate.id is not None


@pytest.mark.asyncio
async def test_release_system_persists(db_session, tenant, user, release_lifecycle_template, system):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()
    rs = ReleaseSystem(
        tenant_id=tenant.id, release_id=release.id, system_id=system.id,
        role="changing", deployment_date=None,
    )
    db_session.add(rs); await db_session.flush()
    assert rs.id is not None
    assert rs.role == "changing"


@pytest.mark.asyncio
async def test_release_dependency_persists(db_session, tenant, user, release_lifecycle_template):
    def make_release(name):
        return Release(tenant_id=tenant.id, name=name, release_type="Major", release_kind="project",
                       lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    a = make_release("A"); b = make_release("B")
    db_session.add_all([a, b]); await db_session.flush()
    dep = ReleaseDependency(
        tenant_id=tenant.id, release_id=a.id, depends_on_release_id=b.id,
        kind="deploys_after", notes="A must go after B",
        last_dependency_target_date=b.target_date,
    )
    db_session.add(dep); await db_session.flush()
    assert dep.id is not None
