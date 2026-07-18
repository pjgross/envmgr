"""Tests for raid_service.summary (counts + heat-map)."""
import pytest

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.api.v1.schemas.raid import RaidItemCreate
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
async def test_summary_counts_and_heatmap(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="risk", title="Hi", probability=4, impact=5), tenant.id, user.id)
    await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="issue", title="Lo", probability=1, impact=1), tenant.id, user.id)
    await raid_service.create_item(db_session, rel.id, RaidItemCreate(item_type="assumption", title="As"), tenant.id, user.id)
    s = await raid_service.summary(db_session, rel.id, tenant.id, cfg)
    assert s["counts_by_type"]["risk"] == 1
    assert s["counts_by_type"]["issue"] == 1
    assert s["counts_by_type"]["assumption"] == 1
    assert s["counts_by_rag"]["red"] == 1     # 4x5=20 -> red
    assert s["counts_by_rag"]["green"] == 1   # 1x1=1 -> green
    assert s["open_issues"] == 1              # the issue is open
    # heatmap: risk at probability 4, impact 5 -> index [3][4]
    assert "R-001" in s["heatmap"][3][4]
    assert len(s["heatmap"]) == 5 and len(s["heatmap"][0]) == 5
