"""Tests for RAID scope links + item relations (with tenant-isolation)."""
import pytest
from fastapi import HTTPException

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.api.v1.schemas.raid import RaidItemCreate
from app.services import raid_service


async def _make_release(db_session, tenant_id, user_id, name="R1"):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="Major", is_default=True,
        definition={"states": [], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=user_id,
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _scope(db_session, tenant_id, release_id, title="Story"):
    rc = ReleaseChange(tenant_id=tenant_id, release_id=release_id, title=title,
                       change_kind="story", source="manual")
    db_session.add(rc)
    await db_session.flush()
    return rc


@pytest.mark.asyncio
async def test_add_scope_link_and_get(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    rc = await _scope(db_session, tenant.id, rel.id)
    await raid_service.add_scope_link(db_session, rel.id, item.id, rc.id, tenant.id)
    links = await raid_service.get_links(db_session, item.id, tenant.id)
    assert links["scope_change_ids"] == [rc.id]
    # idempotent
    await raid_service.add_scope_link(db_session, rel.id, item.id, rc.id, tenant.id)
    links2 = await raid_service.get_links(db_session, item.id, tenant.id)
    assert links2["scope_change_ids"] == [rc.id]


@pytest.mark.asyncio
async def test_scope_link_rejects_foreign_tenant(db_session, tenant, user, second_tenant_factory):
    rel = await _make_release(db_session, tenant.id, user.id)
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    other_t, other_u = await second_tenant_factory()
    other_rel = await _make_release(db_session, other_t.id, other_u.id, name="OtherR")
    foreign_rc = await _scope(db_session, other_t.id, other_rel.id, title="Foreign")
    with pytest.raises(HTTPException) as exc:
        await raid_service.add_scope_link(db_session, rel.id, item.id, foreign_rc.id, tenant.id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_scope_link_rejects_other_release(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    rel2 = await _make_release(db_session, tenant.id, user.id, name="R2")
    item = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    rc_other = await _scope(db_session, tenant.id, rel2.id, title="OtherRelStory")
    with pytest.raises(HTTPException) as exc:
        await raid_service.add_scope_link(db_session, rel.id, item.id, rc_other.id, tenant.id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_add_relation_and_self_forbidden(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    a = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    b = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="issue", title="B"), tenant.id, user.id)
    await raid_service.add_relation(db_session, a.id, b.id, "relates_to", tenant.id)
    links = await raid_service.get_links(db_session, a.id, tenant.id)
    assert links["relations"] == [{"to_item_id": b.id, "relation": "relates_to"}]
    with pytest.raises(HTTPException) as exc:
        await raid_service.add_relation(db_session, a.id, a.id, "relates_to", tenant.id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_relation_rejects_foreign_tenant_target(db_session, tenant, user, second_tenant_factory):
    rel = await _make_release(db_session, tenant.id, user.id)
    a = await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="A"), tenant.id, user.id)
    other_t, other_u = await second_tenant_factory()
    other_rel = await _make_release(db_session, other_t.id, other_u.id, name="OtherR")
    foreign = await raid_service.create_item(db_session, other_rel.id, RaidItemCreate(item_type="risk", title="F"), other_t.id, other_u.id)
    with pytest.raises(HTTPException) as exc:
        await raid_service.add_relation(db_session, a.id, foreign.id, "relates_to", tenant.id)
    assert exc.value.status_code == 404
