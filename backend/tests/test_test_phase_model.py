from datetime import datetime, timezone, timedelta
import pytest
from app.db.models.release import Release
from app.db.models.test_phase import TestPhase


@pytest.mark.asyncio
async def test_test_phase_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()

    start = datetime.now(timezone.utc)
    phase = TestPhase(
        tenant_id=tenant.id,
        release_id=release.id,
        name="SIT",
        order=1,
        start_date=start,
        end_date=start + timedelta(days=5),
        status="pending",
    )
    db_session.add(phase)
    await db_session.flush()
    assert phase.id is not None
    assert phase.name == "SIT"
