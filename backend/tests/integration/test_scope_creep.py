from datetime import datetime, timezone, timedelta

import pytest

from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.services import release_scope_service
from app.api.v1.schemas.release_change import ReleaseChangeCreate
from tests.factories import ensure_user


async def _release(db, tenant_id, template_id, deadline):
    r = Release(
        tenant_id=tenant_id, name="Creep R", release_type="Test Major",
        release_kind="project", lifecycle_template_id=template_id,
        status="draft", raised_by=(await ensure_user(db, tenant_id)).id,
        scope_deadline=deadline,
    )
    db.add(r)
    await db.flush()
    return r


@pytest.mark.asyncio
async def test_item_created_after_deadline_is_creep(db_session, tenant, release_lifecycle_template):
    deadline = datetime.now(timezone.utc) - timedelta(days=1)  # deadline in the past
    rel = await _release(db_session, tenant.id, release_lifecycle_template.id, deadline)
    ch = await release_scope_service.create_change(
        db_session, rel.id, ReleaseChangeCreate(title="late story", change_kind="story"),
        tenant.id, user_id=1,
    )
    ids = await release_scope_service.scope_creep_change_ids(db_session, rel, tenant.id)
    assert ch.id in ids
    counts = await release_scope_service.scope_creep_counts(db_session, [rel.id], tenant.id)
    assert counts.get(rel.id) == 1


@pytest.mark.asyncio
async def test_no_deadline_means_no_creep(db_session, tenant, release_lifecycle_template):
    rel = await _release(db_session, tenant.id, release_lifecycle_template.id, None)
    await release_scope_service.create_change(
        db_session, rel.id, ReleaseChangeCreate(title="s", change_kind="story"), tenant.id, user_id=1,
    )
    ids = await release_scope_service.scope_creep_change_ids(db_session, rel, tenant.id)
    assert ids == set()
    counts = await release_scope_service.scope_creep_counts(db_session, [rel.id], tenant.id)
    assert counts.get(rel.id, 0) == 0


@pytest.mark.asyncio
async def test_item_entered_before_deadline_is_not_creep(db_session, tenant, release_lifecycle_template):
    deadline = datetime.now(timezone.utc) + timedelta(days=30)  # deadline far in the future
    rel = await _release(db_session, tenant.id, release_lifecycle_template.id, deadline)
    ch = await release_scope_service.create_change(
        db_session, rel.id, ReleaseChangeCreate(title="early", change_kind="story"), tenant.id, user_id=1,
    )
    ids = await release_scope_service.scope_creep_change_ids(db_session, rel, tenant.id)
    assert ch.id not in ids
