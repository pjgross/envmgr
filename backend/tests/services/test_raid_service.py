"""Tests for raid_service CRUD."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.raid import RaidItem, RaidItemHistory
from app.api.v1.schemas.raid import RaidItemCreate, RaidItemUpdate
from app.services import raid_service, raid_config_service


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


@pytest.mark.asyncio
async def test_create_allocates_ref_codes_per_type(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    r1 = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    r2 = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="B"), tenant.id, user.id)
    i1 = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="issue", title="C"), tenant.id, user.id)
    assert raid_service.ref_code(r1) == "R-001"
    assert raid_service.ref_code(r2) == "R-002"
    assert raid_service.ref_code(i1) == "I-001"
    assert r1.status == "open"
    # assumption initialises validation_status
    a1 = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="assumption", title="D"), tenant.id, user.id)
    assert a1.validation_status == "unvalidated"


@pytest.mark.asyncio
async def test_read_mapper_computes_severity_and_rag(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    item = await raid_service.create_item(
        db_session, rel.id,
        RaidItemCreate(item_type="risk", title="A", probability=4, impact=5), tenant.id, user.id)
    read = raid_service.to_read(item, cfg)
    assert read.ref_code == "R-001"
    assert read.severity == 20
    assert read.rag == "red"


@pytest.mark.asyncio
async def test_update_invalid_transition_rejected(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    with pytest.raises(HTTPException) as exc:
        await raid_service.update_item(db_session, item.id, RaidItemUpdate(status="resolved"), tenant.id, user.id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_update_writes_history_and_sets_closed_at(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    await raid_service.update_item(db_session, item.id, RaidItemUpdate(status="mitigating", title="A2"), tenant.id, user.id)
    updated = await raid_service.update_item(db_session, item.id, RaidItemUpdate(status="closed"), tenant.id, user.id)
    assert updated.status == "closed"
    assert updated.closed_at is not None
    hist = (await db_session.execute(
        select(RaidItemHistory).where(RaidItemHistory.raid_item_id == item.id)
    )).scalars().all()
    fields = {h.field_name for h in hist}
    assert "status" in fields and "title" in fields


@pytest.mark.asyncio
async def test_soft_delete_hides_from_list(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="issue", title="A"), tenant.id, user.id)
    await raid_service.delete_item(db_session, item.id, tenant.id, user.id)
    items, _ = await raid_service.list_items(db_session, rel.id, tenant.id, config=cfg)
    assert item.id not in [i.id for i in items]


@pytest.mark.asyncio
async def test_create_rejects_foreign_tenant_owner(db_session, tenant, user, second_tenant_factory):
    rel = await _make_release(db_session, tenant.id, user.id)
    other_t, other_u = await second_tenant_factory()
    with pytest.raises(HTTPException) as exc:
        await raid_service.create_item(
            db_session, rel.id,
            RaidItemCreate(item_type="risk", title="A", owner_id=other_u.id), tenant.id, user.id)
    assert exc.value.status_code == 400
