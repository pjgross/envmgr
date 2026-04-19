"""Tests for release_service CRUD + transition.

Uses in-memory SQLite via the shared db_session fixture (no migrations).
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.release_event import ReleaseEventType
from app.api.v1.schemas.release import ReleaseCreate, ReleaseUpdate
from app.services import release_service


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_lifecycle(tenant_id, name="Major", is_default=True, with_required=False):
    """Build a LifecycleTemplate for releases."""
    submitted_perms = {
        "standard_fields": {
            "name": {"editable_by": ["Admin"]},
            "target_date": {"editable_by": ["Admin"]},
        },
        "custom_fields": {},
    }
    if with_required:
        submitted_perms["required_fields"] = ["name", "target_date"]

    return LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=name,
        is_default=is_default,
        definition={
            "states": [
                {"key": "draft",      "label": "Draft",      "is_initial": True,  "is_terminal": False},
                {"key": "submitted",  "label": "Submitted",  "is_initial": False, "is_terminal": False},
                {"key": "completed",  "label": "Completed",  "is_initial": False, "is_terminal": True},
                {"key": "completed_with_issues", "label": "Completed w/Issues", "is_initial": False, "is_terminal": True},
                {"key": "cancelled",  "label": "Cancelled",  "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft",     "to_state": "submitted",             "allowed_roles": ["Admin", "ReleaseManager"]},
                {"from_state": "submitted", "to_state": "completed",             "allowed_roles": ["Admin", "ReleaseManager"]},
                {"from_state": "submitted", "to_state": "completed_with_issues", "allowed_roles": ["Admin", "ReleaseManager"]},
                {"from_state": "draft",     "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
            ],
            "field_permissions": {
                "draft":      {"standard_fields": {}, "custom_fields": {}},
                "submitted":  submitted_perms,
                "completed":  {"standard_fields": {}, "custom_fields": {}},
                "completed_with_issues": {"standard_fields": {}, "custom_fields": {}},
                "cancelled":  {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )


async def _create_lifecycle(db_session, tenant_id, **kwargs):
    tpl = _make_lifecycle(tenant_id, **kwargs)
    db_session.add(tpl)
    await db_session.flush()
    return tpl


# ── test_create_release_uses_tenant_default_lifecycle_when_none_provided ────

@pytest.mark.asyncio
async def test_create_release_uses_tenant_default_lifecycle_when_none_provided(
    db_session, tenant, user
):
    tpl = await _create_lifecycle(db_session, tenant.id, name="Default Major", is_default=True)

    data = ReleaseCreate(name="Release Alpha", release_type="Major")
    # No lifecycle_template_id provided
    assert data.lifecycle_template_id is None

    release = await release_service.create_release(db_session, data, tenant.id, user.id)
    assert release.lifecycle_template_id == tpl.id
    assert release.status == "draft"
    assert release.name == "Release Alpha"


@pytest.mark.asyncio
async def test_create_release_raises_when_no_default_lifecycle(db_session, tenant, user):
    from fastapi import HTTPException
    # No lifecycle templates seeded for this tenant
    data = ReleaseCreate(name="R", release_type="Major")
    with pytest.raises(HTTPException) as exc_info:
        await release_service.create_release(db_session, data, tenant.id, user.id)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_release_writes_initial_status_history(db_session, tenant, user):
    await _create_lifecycle(db_session, tenant.id, is_default=True)
    data = ReleaseCreate(name="R1", release_type="Minor")
    release = await release_service.create_release(db_session, data, tenant.id, user.id)

    hist = (
        await db_session.execute(
            select(ReleaseStatusHistory).where(ReleaseStatusHistory.release_id == release.id)
        )
    ).scalars().all()
    assert len(hist) == 1
    assert hist[0].from_state is None
    assert hist[0].to_state == "draft"
    assert hist[0].changed_by == user.id


# ── test_update_release_target_date_creates_reschedule_event ─────────────────

@pytest.mark.asyncio
async def test_update_release_target_date_creates_reschedule_event(
    db_session, tenant, user
):
    """When target_date changes on a non-draft release, a Reschedule Reason event is written."""
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)

    # Seed the Reschedule Reason system event type
    et = ReleaseEventType(
        tenant_id=tenant.id,
        name="Reschedule Reason",
        is_system=True,
        display_color="#ed6c02",
    )
    db_session.add(et)
    await db_session.flush()

    # Create a release and manually move it past draft
    data = ReleaseCreate(name="Rescheduled Release", release_type="Major",
                         target_date=datetime(2026, 6, 1, tzinfo=timezone.utc))
    release = await release_service.create_release(db_session, data, tenant.id, user.id)
    # Move to submitted so it's non-draft
    release.status = "submitted"
    await db_session.flush()

    new_date = datetime(2026, 7, 1, tzinfo=timezone.utc)
    updated = await release_service.update_release(
        db_session, release.id, ReleaseUpdate(target_date=new_date), tenant.id, user.id
    )
    assert updated.target_date == new_date

    # There should be a ReleaseEvent of type "Reschedule Reason"
    from app.db.models.release_event import ReleaseEvent
    events = (
        await db_session.execute(
            select(ReleaseEvent).where(
                ReleaseEvent.release_id == release.id,
                ReleaseEvent.event_type_id == et.id,
            )
        )
    ).scalars().all()
    assert len(events) == 1
    assert "target_date" in events[0].description


@pytest.mark.asyncio
async def test_update_release_no_reschedule_event_in_draft(db_session, tenant, user):
    """On draft status, changing target_date does NOT emit a Reschedule Reason event."""
    await _create_lifecycle(db_session, tenant.id, is_default=True)
    et = ReleaseEventType(tenant_id=tenant.id, name="Reschedule Reason", is_system=True)
    db_session.add(et)
    await db_session.flush()

    data = ReleaseCreate(name="Draft Release", release_type="Major",
                         target_date=datetime(2026, 6, 1, tzinfo=timezone.utc))
    release = await release_service.create_release(db_session, data, tenant.id, user.id)
    # Still in draft; update target_date
    await release_service.update_release(
        db_session, release.id, ReleaseUpdate(target_date=datetime(2026, 7, 1, tzinfo=timezone.utc)),
        tenant.id, user.id,
    )

    from app.db.models.release_event import ReleaseEvent
    events = (
        await db_session.execute(
            select(ReleaseEvent).where(ReleaseEvent.release_id == release.id)
        )
    ).scalars().all()
    assert len(events) == 0  # no event emitted for draft


# ── test_transition_blocked_when_required_fields_missing ─────────────────────

@pytest.mark.asyncio
async def test_transition_blocked_when_required_fields_missing(db_session, tenant, user):
    from fastapi import HTTPException
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True, with_required=True)

    # Create release without target_date
    release = Release(
        tenant_id=tenant.id, name="Release B", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await release_service.transition_release(
            db_session, release.id, "submitted", None, tenant.id, user.id, "Admin"
        )
    assert exc_info.value.status_code == 400
    # target_date is None → should be in the reason
    assert "target_date" in exc_info.value.detail


# ── test_transition_terminal_stamps_actual_date ───────────────────────────────

@pytest.mark.asyncio
async def test_transition_terminal_stamps_actual_date(db_session, tenant, user):
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)

    release = Release(
        tenant_id=tenant.id, name="Release C", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="submitted", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()

    assert release.actual_date is None
    updated = await release_service.transition_release(
        db_session, release.id, "completed", "All good", tenant.id, user.id, "Admin"
    )
    assert updated.status == "completed"
    assert updated.actual_date is not None


@pytest.mark.asyncio
async def test_transition_terminal_does_not_overwrite_actual_date(db_session, tenant, user):
    """If actual_date is already set, transition to terminal must NOT overwrite it."""
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)
    original_actual = datetime(2026, 5, 1, tzinfo=timezone.utc)

    release = Release(
        tenant_id=tenant.id, name="Release D", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="submitted", raised_by=user.id,
        actual_date=original_actual,
    )
    db_session.add(release)
    await db_session.flush()

    updated = await release_service.transition_release(
        db_session, release.id, "completed", None, tenant.id, user.id, "Admin"
    )
    assert updated.actual_date == original_actual


@pytest.mark.asyncio
async def test_transition_non_terminal_does_not_stamp_actual_date(db_session, tenant, user):
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)

    release = Release(
        tenant_id=tenant.id, name="Release E", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()

    updated = await release_service.transition_release(
        db_session, release.id, "submitted", None, tenant.id, user.id, "Admin"
    )
    assert updated.status == "submitted"
    assert updated.actual_date is None


@pytest.mark.asyncio
async def test_transition_role_blocked(db_session, tenant, user):
    from fastapi import HTTPException
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)

    release = Release(
        tenant_id=tenant.id, name="Release F", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await release_service.transition_release(
            db_session, release.id, "submitted", None, tenant.id, user.id, "Developer"
        )
    assert exc_info.value.status_code == 400


# ── test_tenant_isolation_list_releases ──────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation_list_releases(db_session, tenant, user):
    """Tenant A's releases must not appear in tenant B's list."""
    from app.db.models.user import Tenant
    tenant_b = Tenant(name="Tenant B", slug="tenant-b")
    db_session.add(tenant_b)
    await db_session.flush()

    tpl_a = await _create_lifecycle(db_session, tenant.id, is_default=True)
    tpl_b = _make_lifecycle(tenant_b.id, name="Default", is_default=True)
    db_session.add(tpl_b)
    await db_session.flush()

    # Create 2 releases for tenant A, 1 for tenant B
    for name in ("A-1", "A-2"):
        db_session.add(Release(
            tenant_id=tenant.id, name=name, release_type="Major",
            release_kind="project", lifecycle_template_id=tpl_a.id,
            status="draft", raised_by=user.id,
        ))
    db_session.add(Release(
        tenant_id=tenant_b.id, name="B-1", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl_b.id,
        status="draft", raised_by=user.id,
    ))
    await db_session.flush()

    releases_a, count_a = await release_service.list_releases(db_session, tenant.id)
    releases_b, count_b = await release_service.list_releases(db_session, tenant_b.id)

    assert count_a == 2
    assert count_b == 1
    assert all(r.tenant_id == tenant.id for r in releases_a)
    assert all(r.tenant_id == tenant_b.id for r in releases_b)


# ── test_soft_delete_hides_from_list ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_soft_delete_hides_from_list(db_session, tenant, user):
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)

    data = ReleaseCreate(name="To Be Deleted", release_type="Major")
    release = await release_service.create_release(db_session, data, tenant.id, user.id)

    releases_before, count_before = await release_service.list_releases(db_session, tenant.id)
    assert count_before == 1

    await release_service.delete_release(db_session, release.id, tenant.id)

    releases_after, count_after = await release_service.list_releases(db_session, tenant.id)
    assert count_after == 0
    assert len(releases_after) == 0


@pytest.mark.asyncio
async def test_soft_delete_sets_deleted_at(db_session, tenant, user):
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)
    data = ReleaseCreate(name="Delete Me", release_type="Minor")
    release = await release_service.create_release(db_session, data, tenant.id, user.id)

    await release_service.delete_release(db_session, release.id, tenant.id)
    assert release.deleted_at is not None


@pytest.mark.asyncio
async def test_get_release_not_found_after_delete(db_session, tenant, user):
    from fastapi import HTTPException
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)
    data = ReleaseCreate(name="Gone", release_type="Major")
    release = await release_service.create_release(db_session, data, tenant.id, user.id)
    await release_service.delete_release(db_session, release.id, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        await release_service.get_release(db_session, release.id, tenant.id)
    assert exc_info.value.status_code == 404


# ── list_releases filter tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_releases_filter_by_status(db_session, tenant, user):
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)
    for name, st in [("R1", "draft"), ("R2", "submitted"), ("R3", "draft")]:
        db_session.add(Release(
            tenant_id=tenant.id, name=name, release_type="Major",
            release_kind="project", lifecycle_template_id=tpl.id,
            status=st, raised_by=user.id,
        ))
    await db_session.flush()

    drafts, count = await release_service.list_releases(db_session, tenant.id, status="draft")
    assert count == 2
    assert all(r.status == "draft" for r in drafts)


@pytest.mark.asyncio
async def test_list_releases_filter_by_search(db_session, tenant, user):
    tpl = await _create_lifecycle(db_session, tenant.id, is_default=True)
    for name in ("Alpha Release", "Beta Release", "Gamma Drop"):
        db_session.add(Release(
            tenant_id=tenant.id, name=name, release_type="Major",
            release_kind="project", lifecycle_template_id=tpl.id,
            status="draft", raised_by=user.id,
        ))
    await db_session.flush()

    results, count = await release_service.list_releases(db_session, tenant.id, search="Release")
    assert count == 2
