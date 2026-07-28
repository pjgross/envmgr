import pytest
from datetime import datetime, timezone
from app.services import incident_service
from app.services.incident_defaults import seed_incident_defaults_for_tenant
from app.api.v1.schemas.incident import IncidentCreate, IncidentUpdate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.system import System
from app.db.models.lifecycle import LifecycleTemplate


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
