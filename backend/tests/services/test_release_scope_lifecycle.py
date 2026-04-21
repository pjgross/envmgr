"""Service-level tests for scope-item lifecycle: history, moves, kind-rule gating."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_change_history import (
    ReleaseChangeReleaseHistory,
    ReleaseChangeStatusHistory,
)
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.api.v1.schemas.release_change import ReleaseChangeCreate, ReleaseChangeUpdate
from app.services import release_scope_service, scope_change_rule_service


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_release(db_session, tenant_id, user_id, status="draft", name="R"):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=f"Tpl-{name}",
        is_default=False,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()

    release = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=tpl.id,
        status=status,
        raised_by=user_id,
    )
    db_session.add(release)
    await db_session.flush()
    return release


async def _seed_scope_change_event_type(db_session, tenant_id):
    et = ReleaseEventType(tenant_id=tenant_id, name="Scope Change", is_system=True)
    db_session.add(et)
    await db_session.flush()
    return et


async def _count_release_history(db_session, change_id):
    rows = (
        await db_session.execute(
            select(ReleaseChangeReleaseHistory).where(
                ReleaseChangeReleaseHistory.change_id == change_id
            )
        )
    ).scalars().all()
    return rows


async def _count_status_history(db_session, change_id):
    rows = (
        await db_session.execute(
            select(ReleaseChangeStatusHistory).where(
                ReleaseChangeStatusHistory.change_id == change_id
            )
        )
    ).scalars().all()
    return rows


# ── 1. create_change inserts initial release history row ──────────────────────

@pytest.mark.asyncio
async def test_create_change_inserts_release_history_row(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Login flow", change_kind="story"),
        tenant.id, user.id,
    )

    rows = await _count_release_history(db_session, change.id)
    assert len(rows) == 1
    assert rows[0].from_release_id is None
    assert rows[0].to_release_id == release.id


# ── 2. create_change with external_status inserts status history ──────────────

@pytest.mark.asyncio
async def test_create_change_with_external_status_inserts_status_history(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Item A", change_kind="story", external_status="In Progress"),
        tenant.id, user.id,
    )

    rows = await _count_status_history(db_session, change.id)
    assert len(rows) == 1
    assert rows[0].from_status is None
    assert rows[0].to_status == "In Progress"


# ── 3. create_change without external_status → no status history ──────────────

@pytest.mark.asyncio
async def test_create_change_without_external_status_inserts_no_status_history(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Item B", change_kind="story"),
        tenant.id, user.id,
    )

    rows = await _count_status_history(db_session, change.id)
    assert len(rows) == 0


# ── 4. update external_status inserts status history row ─────────────────────

@pytest.mark.asyncio
async def test_update_external_status_inserts_status_history_row(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Item C", change_kind="story", external_status="Open"),
        tenant.id, user.id,
    )
    # There's already 1 status-history row from create (from=None, to="Open").

    await release_scope_service.update_change(
        db_session, change.id,
        ReleaseChangeUpdate(external_status="Done"),
        tenant.id, user.id,
    )

    rows = await _count_status_history(db_session, change.id)
    # First row: None → Open (at create), second: Open → Done (at update)
    assert len(rows) == 2
    last = sorted(rows, key=lambda r: r.id)[-1]
    assert last.from_status == "Open"
    assert last.to_status == "Done"


# ── 5. update external_status same value → no new row ────────────────────────

@pytest.mark.asyncio
async def test_update_external_status_no_change_no_row(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Item D", change_kind="story", external_status="Open"),
        tenant.id, user.id,
    )
    initial_count = len(await _count_status_history(db_session, change.id))

    # Update with the exact same status — should be a no-op for history.
    await release_scope_service.update_change(
        db_session, change.id,
        ReleaseChangeUpdate(external_status="Open"),
        tenant.id, user.id,
    )

    rows = await _count_status_history(db_session, change.id)
    assert len(rows) == initial_count  # no new row added


# ── 6. move_change success ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_move_change_success(db_session, tenant, user):
    release_a = await _make_release(db_session, tenant.id, user.id, name="RA")
    release_b = await _make_release(db_session, tenant.id, user.id, name="RB")

    change = await release_scope_service.create_change(
        db_session, release_a.id,
        ReleaseChangeCreate(title="Move me", change_kind="story"),
        tenant.id, user.id,
    )

    result = await release_scope_service.move_change(
        db_session, change.id, release_b.id, tenant.id, user.id, notes="Moving to RB",
    )

    assert result.release_id == release_b.id

    rows = await _count_release_history(db_session, change.id)
    # 1st row: initial assign (None → RA), 2nd: move (RA → RB)
    assert len(rows) == 2
    move_row = sorted(rows, key=lambda r: r.id)[-1]
    assert move_row.from_release_id == release_a.id
    assert move_row.to_release_id == release_b.id
    assert move_row.notes == "Moving to RB"


# ── 7. move_change to backlog (None) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_move_change_to_backlog(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="To backlog", change_kind="story"),
        tenant.id, user.id,
    )

    result = await release_scope_service.move_change(
        db_session, change.id, None, tenant.id, user.id,
    )

    assert result.release_id is None

    rows = await _count_release_history(db_session, change.id)
    assert len(rows) == 2
    move_row = sorted(rows, key=lambda r: r.id)[-1]
    assert move_row.from_release_id == release.id
    assert move_row.to_release_id is None


# ── 8. move_change from backlog back to a release ─────────────────────────────

@pytest.mark.asyncio
async def test_move_change_from_backlog_back_to_release(db_session, tenant, user):
    release_a = await _make_release(db_session, tenant.id, user.id, name="RA2")
    release_b = await _make_release(db_session, tenant.id, user.id, name="RB2")

    # Start in RA, move to backlog, then move to RB.
    change = await release_scope_service.create_change(
        db_session, release_a.id,
        ReleaseChangeCreate(title="Backlog journey", change_kind="story"),
        tenant.id, user.id,
    )
    await release_scope_service.move_change(db_session, change.id, None, tenant.id, user.id)
    result = await release_scope_service.move_change(db_session, change.id, release_b.id, tenant.id, user.id)

    assert result.release_id == release_b.id

    rows = sorted(await _count_release_history(db_session, change.id), key=lambda r: r.id)
    last = rows[-1]
    assert last.from_release_id is None
    assert last.to_release_id == release_b.id


# ── 9. move_change idempotent — same release returns row, no extra history ────

@pytest.mark.asyncio
async def test_move_change_idempotent_same_release_returns_no_op(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Idempotent", change_kind="story"),
        tenant.id, user.id,
    )
    history_before = await _count_release_history(db_session, change.id)

    result = await release_scope_service.move_change(
        db_session, change.id, release.id, tenant.id, user.id,
    )

    assert result.release_id == release.id
    history_after = await _count_release_history(db_session, change.id)
    assert len(history_after) == len(history_before)  # no new history row


# ── 10. move_change rejects jira-sourced items ────────────────────────────────

@pytest.mark.asyncio
async def test_move_change_rejects_jira_source(db_session, tenant, user):
    release_a = await _make_release(db_session, tenant.id, user.id, name="JiraRA")
    release_b = await _make_release(db_session, tenant.id, user.id, name="JiraRB")

    jira_change = ReleaseChange(
        tenant_id=tenant.id,
        release_id=release_a.id,
        external_key="PROJ-99",
        title="Jira issue",
        change_kind="story",
        source="jira",
    )
    db_session.add(jira_change)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await release_scope_service.move_change(
            db_session, jira_change.id, release_b.id, tenant.id, user.id,
        )
    assert exc_info.value.status_code == 422
    assert "jira" in exc_info.value.detail.lower()


# ── 11. move_change rejects cross-tenant target ───────────────────────────────

@pytest.mark.asyncio
async def test_move_change_rejects_cross_tenant_target(db_session, tenant, user):
    from app.db.models.user import Tenant
    other_tenant = Tenant(name="Other Co", slug="other-co-lc")
    db_session.add(other_tenant)
    await db_session.flush()

    release_own = await _make_release(db_session, tenant.id, user.id, name="OwnR")

    # Create a release in the other tenant's context
    other_tpl = LifecycleTemplate(
        tenant_id=other_tenant.id,
        entity_type="release",
        name="OtherTpl",
        is_default=False,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(other_tpl)
    await db_session.flush()
    other_release = Release(
        tenant_id=other_tenant.id, name="OtherR", release_type="Major",
        release_kind="project", lifecycle_template_id=other_tpl.id,
        status="draft", raised_by=user.id,
    )
    db_session.add(other_release)
    await db_session.flush()

    change = await release_scope_service.create_change(
        db_session, release_own.id,
        ReleaseChangeCreate(title="Cross-tenant test", change_kind="story"),
        tenant.id, user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await release_scope_service.move_change(
            db_session, change.id, other_release.id, tenant.id, user.id,
        )
    assert exc_info.value.status_code in (404, 422)


# ── 12. kind rule false suppresses scope change event ────────────────────────

@pytest.mark.asyncio
async def test_kind_rule_false_suppresses_scope_change_event(db_session, tenant, user):
    await _seed_scope_change_event_type(db_session, tenant.id)
    await scope_change_rule_service.seed_default_rules(db_session, tenant.id)
    # Default: story=True, defect=False.

    # approved release → post-approval, events should fire for counting kinds only.
    release = await _make_release(db_session, tenant.id, user.id, status="approved")

    # defect kind (counts=False) should NOT emit a scope change event.
    await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Bug fix", change_kind="defect"),
        tenant.id, user.id,
    )
    events_after_defect = (
        await db_session.execute(
            select(ReleaseEvent).where(ReleaseEvent.release_id == release.id)
        )
    ).scalars().all()
    assert len(events_after_defect) == 0, "defect should not emit scope change event"

    # story kind (counts=True) SHOULD emit.
    await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="New feature", change_kind="story"),
        tenant.id, user.id,
    )
    events_after_story = (
        await db_session.execute(
            select(ReleaseEvent).where(ReleaseEvent.release_id == release.id)
        )
    ).scalars().all()
    assert len(events_after_story) == 1, "story should emit scope change event"


# ── 13. list_release_history returns rows ordered by moved_at ────────────────

@pytest.mark.asyncio
async def test_list_release_history_returns_rows_ordered_by_moved_at(db_session, tenant, user):
    release_a = await _make_release(db_session, tenant.id, user.id, name="HistA")
    release_b = await _make_release(db_session, tenant.id, user.id, name="HistB")

    change = await release_scope_service.create_change(
        db_session, release_a.id,
        ReleaseChangeCreate(title="History order test", change_kind="story"),
        tenant.id, user.id,
    )
    await release_scope_service.move_change(db_session, change.id, release_b.id, tenant.id, user.id)

    rows = await release_scope_service.list_release_history(db_session, change.id, tenant.id)

    assert len(rows) >= 2
    # Ensure chronological order
    timestamps = [r.moved_at for r in rows]
    assert timestamps == sorted(timestamps)


# ── 14. list_status_history returns rows ordered by changed_at ───────────────

@pytest.mark.asyncio
async def test_list_status_history_returns_rows_ordered_by_changed_at(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Status history order", change_kind="story", external_status="Open"),
        tenant.id, user.id,
    )
    await release_scope_service.update_change(
        db_session, change.id,
        ReleaseChangeUpdate(external_status="In Progress"),
        tenant.id, user.id,
    )
    await release_scope_service.update_change(
        db_session, change.id,
        ReleaseChangeUpdate(external_status="Done"),
        tenant.id, user.id,
    )

    rows = await release_scope_service.list_status_history(db_session, change.id, tenant.id)

    assert len(rows) == 3  # None→Open, Open→InProgress, InProgress→Done
    timestamps = [r.changed_at for r in rows]
    assert timestamps == sorted(timestamps)
