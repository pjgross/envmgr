import pytest
from datetime import datetime, timezone
from app.services import incident_service
from app.services.incident_defaults import seed_incident_defaults_for_tenant
from app.api.v1.schemas.incident import IncidentCreate, IncidentUpdate


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
