"""Tests for release_dependency_service — alert computation."""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.api.v1.schemas.release_dependency import ReleaseDependencyCreate
from app.services import release_dependency_service


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_lifecycle(db_session, tenant_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Major",
        is_default=True,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _make_release(db_session, tenant_id, user_id, name, target_date=None):
    tpl = await _make_lifecycle(db_session, tenant_id)
    release = Release(
        tenant_id=tenant_id, name=name, release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="draft", raised_by=user_id,
        target_date=target_date,
    )
    db_session.add(release)
    await db_session.flush()
    return release


# ── test_alerts_returns_diff_when_target_date_shifts ─────────────────────────

@pytest.mark.asyncio
async def test_alerts_returns_diff_when_target_date_shifts(db_session, tenant, user):
    original_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
    new_date = datetime(2026, 9, 15, tzinfo=timezone.utc)

    release_a = await _make_release(db_session, tenant.id, user.id, "A")
    release_b = await _make_release(db_session, tenant.id, user.id, "B", target_date=original_date)

    dep = await release_dependency_service.create_dependency(
        db_session, release_a.id,
        ReleaseDependencyCreate(depends_on_release_id=release_b.id),
        tenant.id,
    )

    # Simulate B's target_date shifting
    release_b.target_date = new_date
    await db_session.flush()

    alerts = await release_dependency_service.get_dependency_alerts(
        db_session, release_a.id, tenant.id
    )
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.dependency_id == dep.id
    assert alert.depends_on_release_id == release_b.id
    assert alert.diff_days == 14


# ── test_alerts_empty_when_no_change ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_alerts_empty_when_no_change(db_session, tenant, user):
    date = datetime(2026, 9, 1, tzinfo=timezone.utc)
    release_a = await _make_release(db_session, tenant.id, user.id, "A")
    release_b = await _make_release(db_session, tenant.id, user.id, "B", target_date=date)

    await release_dependency_service.create_dependency(
        db_session, release_a.id,
        ReleaseDependencyCreate(depends_on_release_id=release_b.id),
        tenant.id,
    )

    alerts = await release_dependency_service.get_dependency_alerts(
        db_session, release_a.id, tenant.id
    )
    assert alerts == []


# ── test_acknowledge_clears_alert ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acknowledge_clears_alert(db_session, tenant, user):
    original = datetime(2026, 9, 1, tzinfo=timezone.utc)
    shifted = datetime(2026, 9, 20, tzinfo=timezone.utc)

    release_a = await _make_release(db_session, tenant.id, user.id, "A")
    release_b = await _make_release(db_session, tenant.id, user.id, "B", target_date=original)

    dep = await release_dependency_service.create_dependency(
        db_session, release_a.id,
        ReleaseDependencyCreate(depends_on_release_id=release_b.id),
        tenant.id,
    )

    # Shift B
    release_b.target_date = shifted
    await db_session.flush()

    alerts_before = await release_dependency_service.get_dependency_alerts(
        db_session, release_a.id, tenant.id
    )
    assert len(alerts_before) == 1

    # Acknowledge
    await release_dependency_service.acknowledge_alert(
        db_session, release_a.id, dep.id, tenant.id
    )

    alerts_after = await release_dependency_service.get_dependency_alerts(
        db_session, release_a.id, tenant.id
    )
    assert len(alerts_after) == 0


# ── test_self_dependency_rejected ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_self_dependency_rejected(db_session, tenant, user):
    from fastapi import HTTPException
    release = await _make_release(db_session, tenant.id, user.id, "Solo")

    with pytest.raises(HTTPException) as exc_info:
        await release_dependency_service.create_dependency(
            db_session, release.id,
            ReleaseDependencyCreate(depends_on_release_id=release.id),
            tenant.id,
        )
    assert exc_info.value.status_code == 400
    assert "itself" in str(exc_info.value.detail)


# ── test_delete_dependency ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_dependency(db_session, tenant, user):
    release_a = await _make_release(db_session, tenant.id, user.id, "A")
    release_b = await _make_release(db_session, tenant.id, user.id, "B")

    dep = await release_dependency_service.create_dependency(
        db_session, release_a.id,
        ReleaseDependencyCreate(depends_on_release_id=release_b.id),
        tenant.id,
    )
    dep_id = dep.id

    await release_dependency_service.delete_dependency(db_session, dep_id, tenant.id)

    deps, total = await release_dependency_service.list_dependencies(
        db_session, release_a.id, tenant.id
    )
    assert len(deps) == 0
    assert total == 0
