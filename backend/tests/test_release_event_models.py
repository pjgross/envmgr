from datetime import datetime, timezone
import pytest
from app.db.models.release import Release
from app.db.models.release_event import ReleaseEventType, ReleaseEvent


@pytest.mark.asyncio
async def test_release_event_type_persists(db_session, tenant):
    t = ReleaseEventType(
        tenant_id=tenant.id, name="Reschedule Reason",
        display_color="#ff0000", is_system=True,
    )
    db_session.add(t); await db_session.flush()
    assert t.id is not None


@pytest.mark.asyncio
async def test_release_event_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()
    et = ReleaseEventType(tenant_id=tenant.id, name="Note", is_system=False)
    db_session.add(et); await db_session.flush()
    ev = ReleaseEvent(
        tenant_id=tenant.id, release_id=release.id, event_type_id=et.id,
        description="Stakeholder note: FYI", occurred_at=datetime.now(timezone.utc),
        recorded_by=user.id,
    )
    db_session.add(ev); await db_session.flush()
    assert ev.id is not None
