"""Tests for release_event_service — system-type protection + event CRUD."""
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.user import Tenant
from app.api.v1.schemas.release_event import (
    ReleaseEventCreate,
    ReleaseEventTypeCreate,
    ReleaseEventTypeUpdate,
)
from app.services import release_event_service


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_release(db_session, tenant_id, user_id):
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

    release = Release(
        tenant_id=tenant_id, name="R1", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="draft", raised_by=user_id,
    )
    db_session.add(release)
    await db_session.flush()
    return release


async def _make_system_event_type(db_session, tenant_id, name="Reschedule Reason"):
    et = ReleaseEventType(
        tenant_id=tenant_id, name=name, is_system=True
    )
    db_session.add(et)
    await db_session.flush()
    return et


# ── test_system_event_type_cannot_be_renamed ──────────────────────────────────

@pytest.mark.asyncio
async def test_system_event_type_cannot_be_renamed(db_session, tenant, user):
    from fastapi import HTTPException
    et = await _make_system_event_type(db_session, tenant.id, "Reschedule Reason")

    with pytest.raises(HTTPException) as exc_info:
        await release_event_service.update_event_type(
            db_session, et.id,
            ReleaseEventTypeUpdate(name="New Name"),
            tenant.id,
        )
    assert exc_info.value.status_code == 422
    assert "renamed" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_system_event_type_color_can_be_changed(db_session, tenant, user):
    """System types allow only color updates."""
    et = await _make_system_event_type(db_session, tenant.id, "Scope Change")

    updated = await release_event_service.update_event_type(
        db_session, et.id,
        ReleaseEventTypeUpdate(display_color="#aabbcc"),
        tenant.id,
    )
    assert updated.display_color == "#aabbcc"
    assert updated.name == "Scope Change"


# ── test_system_event_type_cannot_be_deleted ──────────────────────────────────

@pytest.mark.asyncio
async def test_system_event_type_cannot_be_deleted(db_session, tenant, user):
    from fastapi import HTTPException
    et = await _make_system_event_type(db_session, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        await release_event_service.delete_event_type(db_session, et.id, tenant.id)
    assert exc_info.value.status_code == 422
    assert "deleted" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_non_system_event_type_can_be_deleted(db_session, tenant, user):
    et = await release_event_service.create_event_type(
        db_session,
        ReleaseEventTypeCreate(name="Custom Note"),
        tenant.id,
    )
    assert et.is_system is False

    await release_event_service.delete_event_type(db_session, et.id, tenant.id)
    assert et.deleted_at is not None


# ── test_record_auto_event_happy_path ────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_auto_event_happy_path(db_session, tenant, user):
    await _make_system_event_type(db_session, tenant.id, "Reschedule Reason")
    release = await _make_release(db_session, tenant.id, user.id)

    event = await release_event_service.record_auto_event(
        db_session,
        release_id=release.id,
        tenant_id=tenant.id,
        user_id=user.id,
        event_type_name="Reschedule Reason",
        description="Target shifted by 2 weeks",
    )
    assert event is not None
    assert event.description == "Target shifted by 2 weeks"
    assert event.recorded_by == user.id


# ── test_record_auto_event_missing_type_returns_none ─────────────────────────

@pytest.mark.asyncio
async def test_record_auto_event_missing_type_returns_none(db_session, tenant, user):
    """If event type does not exist, record_auto_event returns None without raising."""
    release = await _make_release(db_session, tenant.id, user.id)

    result = await release_event_service.record_auto_event(
        db_session,
        release_id=release.id,
        tenant_id=tenant.id,
        user_id=user.id,
        event_type_name="Nonexistent Type",
        description="should not be written",
    )
    assert result is None

    events = (
        await db_session.execute(
            select(ReleaseEvent).where(ReleaseEvent.release_id == release.id)
        )
    ).scalars().all()
    assert len(events) == 0


# ── test_tenant_isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation(db_session, tenant, user):
    from fastapi import HTTPException
    tenant_b = Tenant(name="Other Co", slug="other-co")
    db_session.add(tenant_b)
    await db_session.flush()

    et = await _make_system_event_type(db_session, tenant.id, "Scope Change")

    # Tenant B cannot see tenant A's event type
    with pytest.raises(HTTPException) as exc_info:
        await release_event_service.update_event_type(
            db_session, et.id,
            ReleaseEventTypeUpdate(display_color="#000000"),
            tenant_b.id,
        )
    assert exc_info.value.status_code == 404

    # Listing event types for tenant B returns empty
    b_types = await release_event_service.list_event_types(db_session, tenant_b.id)
    assert len(b_types) == 0


# ── test_create_and_list_events ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_list_events(db_session, tenant, user):
    et = await release_event_service.create_event_type(
        db_session, ReleaseEventTypeCreate(name="Test Note"), tenant.id
    )
    release = await _make_release(db_session, tenant.id, user.id)

    event = await release_event_service.create_event(
        db_session, release.id,
        ReleaseEventCreate(event_type_id=et.id, description="Stakeholder review complete"),
        tenant.id, user.id,
    )
    assert event.id is not None

    events, total = await release_event_service.list_events(db_session, release.id, tenant.id)
    assert len(events) == 1
    assert total == 1
    assert events[0].description == "Stakeholder review complete"


# ── tenant isolation: event_type_id must belong to the caller's tenant ────────

@pytest.mark.asyncio
async def test_create_event_rejects_foreign_tenant_event_type(db_session, tenant, user):
    """A release event cannot reference another tenant's event type."""
    from fastapi import HTTPException

    other = Tenant(name="Evt Org", slug="evt-org")
    db_session.add(other)
    await db_session.flush()
    foreign_type = ReleaseEventType(tenant_id=other.id, name="Their Type", is_system=False)
    db_session.add(foreign_type)
    await db_session.flush()

    release = await _make_release(db_session, tenant.id, user.id)

    with pytest.raises(HTTPException) as exc:
        await release_event_service.create_event(
            db_session, release.id,
            ReleaseEventCreate(event_type_id=foreign_type.id, description="nope"),
            tenant.id, user.id,
        )
    assert exc.value.status_code == 404
