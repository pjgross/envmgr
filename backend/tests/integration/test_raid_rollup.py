"""Integration tests for enterprise_rollup_service.raid_rollup."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.raid import RaidItem
from app.db.models.release import Release
from app.services import (
    enterprise_membership_service,
    enterprise_rollup_service,
    raid_config_service,
)


# ── Local helpers (mirrored from test_enterprise_rollup_service.py) ────────────


async def _make_lifecycle_template_with_admission(
    db: AsyncSession, tenant_id: int
) -> LifecycleTemplate:
    definition: dict = {
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "admission_open", "label": "Admission Open", "is_initial": False, "is_terminal": False},
        ],
        "transitions": [],
        "field_permissions": {
            "draft": {"standard_fields": {}, "custom_fields": {}},
            "admission_open": {"standard_fields": {}, "custom_fields": {}},
        },
        "action_permissions": {
            "admission_open": {
                "membership.admit": ["Admin"],
                "membership.reject": ["Admin"],
            },
        },
    }
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="RAID Rollup Test Lifecycle",
        is_default=False,
        applies_to_kind="enterprise",
        definition=definition,
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def _make_release(db, tenant_id, user_id, tpl_id, name, kind="project") -> Release:
    r = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Major",
        release_kind=kind,
        lifecycle_template_id=tpl_id,
        status="draft" if kind == "project" else "admission_open",
        raised_by=user_id,
    )
    db.add(r)
    await db.flush()
    return r


async def _make_raid_item(
    db, tenant_id, release_id, user_id, *, item_type, seq, title, status,
    probability=None, impact=None, review_date=None,
) -> RaidItem:
    item = RaidItem(
        tenant_id=tenant_id,
        release_id=release_id,
        item_type=item_type,
        seq=seq,
        title=title,
        status=status,
        raised_by=user_id,
        raised_at=datetime.now(timezone.utc),
        probability=probability,
        impact=impact,
        review_date=review_date,
    )
    db.add(item)
    await db.flush()
    return item


# ── Test ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raid_rollup_aggregates_accepted_members_only(db_session, tenant, user):
    """Rollup aggregates RAID items across accepted members; non-members excluded."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(db_session, tenant.id)
    ent = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise RAID-1", kind="enterprise"
    )
    p1 = await _make_release(db_session, tenant.id, user.id, tpl.id, "Project RAID-P1")
    p2 = await _make_release(db_session, tenant.id, user.id, tpl.id, "Project RAID-P2")
    # Non-member project — its RAID item must be excluded
    p3 = await _make_release(db_session, tenant.id, user.id, tpl.id, "Project RAID-Outsider")

    # Member 1: a red risk (severity 25 -> red)
    await _make_raid_item(
        db_session, tenant.id, p1.id, user.id,
        item_type="risk", seq=1, title="Red risk on P1", status="open",
        probability=5, impact=5,
    )
    # Member 2: an open issue
    await _make_raid_item(
        db_session, tenant.id, p2.id, user.id,
        item_type="issue", seq=1, title="Open issue on P2", status="open",
    )
    # Non-member: a risk that must NOT appear
    await _make_raid_item(
        db_session, tenant.id, p3.id, user.id,
        item_type="risk", seq=1, title="Excluded outsider risk", status="open",
        probability=5, impact=5,
    )

    # Request + accept p1 and p2; p3 is never a member
    m1 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p1.id
    )
    m2 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p2.id
    )
    await enterprise_membership_service.accept(db_session, user=user, membership_id=m1.id)
    await enterprise_membership_service.accept(db_session, user=user, membership_id=m2.id)

    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    result = await enterprise_rollup_service.raid_rollup(
        db_session, ent.id, tenant.id, cfg
    )

    # Aggregated counts from the two members only (1 risk + 1 issue)
    assert result["counts_by_type"]["risk"] == 1
    assert result["counts_by_type"]["issue"] == 1
    assert result["counts_by_rag"]["red"] == 1
    assert result["open_issues"] >= 1

    # top_risks contains the red risk and NOT the outsider
    titles = {tr["title"] for tr in result["top_risks"]}
    assert "Red risk on P1" in titles
    assert "Excluded outsider risk" not in titles

    # highest severity first
    top = result["top_risks"][0]
    assert top["rag"] == "red"
    assert top["release_id"] == p1.id
