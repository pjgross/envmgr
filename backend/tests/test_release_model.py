from datetime import datetime, timezone
import pytest
from app.db.models.release import Release, ReleaseStatusHistory


@pytest.mark.asyncio
async def test_release_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id,
        name="Sprint 42",
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id,
        status="draft",
        raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    assert release.id is not None
    assert release.release_kind == "project"
    assert release.status == "draft"
    assert release.parent_release_id is None


@pytest.mark.asyncio
async def test_release_status_history_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id,
        name="R1",
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id,
        status="submitted",
        raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    history = ReleaseStatusHistory(
        release_id=release.id,
        from_state="draft",
        to_state="submitted",
        changed_by=user.id,
        changed_at=datetime.now(timezone.utc),
        notes="initial submission",
    )
    db_session.add(history)
    await db_session.flush()
    assert history.id is not None
