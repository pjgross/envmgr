import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from app.services import incident_service
from app.services.incident_defaults import seed_incident_defaults_for_tenant
from app.api.v1.schemas.incident import IncidentCreate, IncidentUpdate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.system import System
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash


@pytest.mark.asyncio
async def test_create_resolves_default_template_and_initial_state(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="DB outage", severity="P1"), tenant.id, user.id
    )
    assert inc.status == "new"
    assert inc.lifecycle_template_id is not None
    assert inc.detected_at is not None
    hist = await incident_service.get_status_history(db_session, inc.id, tenant.id)
    assert len(hist) == 1 and hist[0].to_state == "new" and hist[0].from_state is None


@pytest.mark.asyncio
async def test_create_defaults_detected_at_to_now(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="x", severity="P3"), tenant.id, user.id
    )
    assert inc.detected_at is not None


@pytest.mark.asyncio
async def test_update_changes_fields_but_not_status(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="x", severity="P3"), tenant.id, user.id
    )
    updated = await incident_service.update_incident(
        db_session, inc.id, IncidentUpdate(title="y", severity="P2"), tenant.id
    )
    assert updated.title == "y" and updated.severity == "P2" and updated.status == "new"


@pytest.mark.asyncio
async def test_soft_delete_hides_from_list_and_get(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="x", severity="P3"), tenant.id, user.id
    )
    await incident_service.delete_incident(db_session, inc.id, tenant.id)
    assert await incident_service.get_incident(db_session, inc.id, tenant.id) is None
    rows = await incident_service.list_incidents(db_session, tenant.id, {})
    assert all(r.id != inc.id for r in rows)


@pytest.mark.asyncio
async def test_detail_hydrates_links_transitions_and_epic_grouping(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()

    # Create a System row inline
    sysrow = System(tenant_id=tenant.id, name="Payments")
    db_session.add(sysrow)
    await db_session.flush()

    # Create a release lifecycle template (required by Release model)
    release_tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="Default Release",
        is_default=True,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(release_tpl)
    await db_session.flush()

    # Create a fix Release row inline
    fix = Release(
        tenant_id=tenant.id,
        name="Fix R1",
        release_type="Patch",
        lifecycle_template_id=release_tpl.id,
        status="draft",
        raised_by=user.id,
    )
    db_session.add(fix)
    await db_session.flush()

    # Create two ReleaseChange rows with epic_id=7
    rc_a = ReleaseChange(
        tenant_id=tenant.id,
        release_id=fix.id,
        title="story A",
        change_kind="story",
        epic_id=7,
    )
    rc_b = ReleaseChange(
        tenant_id=tenant.id,
        release_id=fix.id,
        title="story B",
        change_kind="story",
        epic_id=7,
    )
    db_session.add(rc_a)
    db_session.add(rc_b)
    await db_session.flush()

    # Create the incident with system_id and fix_release_id
    inc = await incident_service.create_incident(
        db_session,
        IncidentCreate(title="x", severity="P1", system_id=sysrow.id, fix_release_id=fix.id),
        tenant.id, user.id,
    )

    detail = await incident_service.get_incident_detail(db_session, inc.id, tenant.id, "Viewer")
    assert detail is not None
    assert detail["system_name"] == "Payments"
    assert detail["fix_release"]["name"] == "Fix R1"
    assert [c.title for c in detail["fix_release_changes_by_epic"]["7"]] == ["story A", "story B"]
    assert any(t["to_state"] == "investigating" for t in detail["allowed_transitions"])
    assert len(detail["status_history"]) == 1


# ---------------------------------------------------------------------------
# Helpers shared by the IDOR guard tests below
# ---------------------------------------------------------------------------

async def _make_release_lifecycle_template(db_session, tenant_id: int) -> LifecycleTemplate:
    """Create a minimal release lifecycle template for the given tenant."""
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Default Release",
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


async def _make_release(db_session, tenant_id: int, user_id: int, lifecycle_template_id: int, name: str = "R1") -> Release:
    """Create a minimal Release row for the given tenant."""
    rel = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Major",
        lifecycle_template_id=lifecycle_template_id,
        status="draft",
        raised_by=user_id,
    )
    db_session.add(rel)
    await db_session.flush()
    return rel


async def _make_other_tenant(db_session, slug: str = "other-org") -> tuple:
    """Create a second Tenant + User inline and return (tenant, user)."""
    t = Tenant(name="Other Org", slug=slug)
    db_session.add(t)
    await db_session.flush()
    u = User(
        tenant_id=t.id,
        username=f"{slug}-admin",
        email=f"admin@{slug}.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(u)
    await db_session.flush()
    return t, u


# ---------------------------------------------------------------------------
# IDOR guard unit tests: _validate_fk_tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_rejects_other_tenant_release(db_session, tenant, user):
    """create_incident must reject a release_id belonging to a different tenant."""
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()

    other_tenant, other_user = await _make_other_tenant(db_session)
    other_tpl = await _make_release_lifecycle_template(db_session, other_tenant.id)
    other_rel = await _make_release(db_session, other_tenant.id, other_user.id, other_tpl.id, name="OtherRelease")

    with pytest.raises(HTTPException) as exc_info:
        await incident_service.create_incident(
            db_session,
            IncidentCreate(title="x", severity="P1", release_id=other_rel.id),
            tenant.id,
            user.id,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_other_tenant_system(db_session, tenant, user):
    """create_incident must reject a system_id belonging to a different tenant."""
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()

    other_tenant, _other_user = await _make_other_tenant(db_session, slug="other-org-sys")
    other_sys = System(tenant_id=other_tenant.id, name="OtherSystem")
    db_session.add(other_sys)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await incident_service.create_incident(
            db_session,
            IncidentCreate(title="x", severity="P1", system_id=other_sys.id),
            tenant.id,
            user.id,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_soft_deleted_same_tenant_release(db_session, tenant, user):
    """create_incident must reject a release_id that has been soft-deleted, even in the same tenant."""
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()

    tpl = await _make_release_lifecycle_template(db_session, tenant.id)
    rel = await _make_release(db_session, tenant.id, user.id, tpl.id, name="DeletedRelease")
    rel.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await incident_service.create_incident(
            db_session,
            IncidentCreate(title="x", severity="P1", release_id=rel.id),
            tenant.id,
            user.id,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_rejects_other_tenant_release(db_session, tenant, user):
    """update_incident must reject a release_id update pointing at another tenant's release."""
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()

    # Create a valid incident first
    inc = await incident_service.create_incident(
        db_session,
        IncidentCreate(title="x", severity="P2"),
        tenant.id,
        user.id,
    )

    other_tenant, other_user = await _make_other_tenant(db_session, slug="other-org-upd")
    other_tpl = await _make_release_lifecycle_template(db_session, other_tenant.id)
    other_rel = await _make_release(db_session, other_tenant.id, other_user.id, other_tpl.id, name="OtherRelUpd")

    with pytest.raises(HTTPException) as exc_info:
        await incident_service.update_incident(
            db_session,
            inc.id,
            IncidentUpdate(release_id=other_rel.id),
            tenant.id,
        )
    assert exc_info.value.status_code == 422
