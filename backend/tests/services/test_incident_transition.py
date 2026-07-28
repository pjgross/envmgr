import pytest
from app.services import incident_service
from app.services.incident_defaults import seed_incident_defaults_for_tenant
from app.api.v1.schemas.incident import IncidentCreate
from fastapi import HTTPException


async def _make(db, tenant, user):
    await seed_incident_defaults_for_tenant(db, tenant.id)
    await db.flush()
    return await incident_service.create_incident(db, IncidentCreate(title="x", severity="P2"), tenant.id, user.id)


@pytest.mark.asyncio
async def test_valid_transition_updates_status_and_history(db_session, tenant, user):
    inc = await _make(db_session, tenant, user)
    out = await incident_service.transition(db_session, inc.id, "investigating", tenant.id, user.id, "Viewer")
    assert out.status == "investigating"
    hist = await incident_service.get_status_history(db_session, inc.id, tenant.id)
    assert hist[-1].from_state == "new" and hist[-1].to_state == "investigating"


@pytest.mark.asyncio
async def test_invalid_transition_rejected(db_session, tenant, user):
    inc = await _make(db_session, tenant, user)
    with pytest.raises(HTTPException) as e:
        await incident_service.transition(db_session, inc.id, "closed", tenant.id, user.id, "Viewer")
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_entering_resolved_sets_resolved_at_leaving_clears(db_session, tenant, user):
    inc = await _make(db_session, tenant, user)
    await incident_service.transition(db_session, inc.id, "investigating", tenant.id, user.id, "Viewer")
    inc = await incident_service.transition(db_session, inc.id, "resolved", tenant.id, user.id, "Viewer")
    assert inc.resolved_at is not None
    inc = await incident_service.transition(db_session, inc.id, "investigating", tenant.id, user.id, "Viewer")
    assert inc.resolved_at is None
