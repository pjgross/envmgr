"""Tests for RAID Risk->Issue (and Assumption->Risk/Issue) promotion."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.raid import RaidItem, RaidItemHistory
from app.api.v1.schemas.raid import RaidItemCreate
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


@pytest.mark.asyncio
async def test_promote_risk_to_issue(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    risk = await raid_service.create_item(
        db_session, rel.id,
        RaidItemCreate(item_type="risk", title="Data loss", probability=4, impact=5),
        tenant.id, user.id)
    issue = await raid_service.promote_item(db_session, rel.id, risk.id, "issue", tenant.id, user.id)
    assert issue.item_type == "issue"
    assert raid_service.ref_code(issue) == "I-001"
    assert issue.promoted_from_id == risk.id
    assert issue.title == "Data loss"
    assert issue.probability == 4 and issue.impact == 5
    # source risk is retained, marked promoted
    await db_session.refresh(risk)
    assert risk.status == "promoted"
    # history written on both
    hist = (await db_session.execute(
        select(RaidItemHistory).where(RaidItemHistory.raid_item_id.in_([risk.id, issue.id]))
    )).scalars().all()
    assert {h.raid_item_id for h in hist} >= {risk.id, issue.id}


@pytest.mark.asyncio
async def test_promote_assumption_to_issue(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    a = await raid_service.create_item(
        db_session, rel.id, RaidItemCreate(item_type="assumption", title="3rd party ready"),
        tenant.id, user.id)
    issue = await raid_service.promote_item(db_session, rel.id, a.id, "issue", tenant.id, user.id)
    assert issue.item_type == "issue"
    assert issue.promoted_from_id == a.id
    # assumption unchanged (still open)
    await db_session.refresh(a)
    assert a.status == "open"


@pytest.mark.asyncio
async def test_promote_invalid_pair_rejected(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id)
    issue = await raid_service.create_item(
        db_session, rel.id, RaidItemCreate(item_type="issue", title="X"), tenant.id, user.id)
    with pytest.raises(HTTPException) as exc:
        await raid_service.promote_item(db_session, rel.id, issue.id, "risk", tenant.id, user.id)
    assert exc.value.status_code == 400
