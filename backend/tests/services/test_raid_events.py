"""RAID lifecycle emits outbox events."""
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.event_log import EventLog
from app.api.v1.schemas.raid import RaidItemCreate, RaidItemUpdate
from app.services import raid_service


async def _make_release(db_session, tenant_id, user_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="Major", is_default=True,
        definition={"states": [], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=tenant_id, name="R1", release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=user_id,
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _events(db_session, item_id):
    rows = (await db_session.execute(
        select(EventLog).where(EventLog.aggregate_type == "RaidItem", EventLog.aggregate_id == item_id)
    )).scalars().all()
    return {e.event_type for e in rows}


@pytest.mark.asyncio
async def test_create_emits_raid_raised(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    assert "RaidItemRaised" in await _events(db_session, item.id)


@pytest.mark.asyncio
async def test_status_change_emits_event(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    await raid_service.update_item(db_session, item.id, RaidItemUpdate(status="mitigating"), tenant.id, user.id)
    assert "RaidItemStatusChanged" in await _events(db_session, item.id)
