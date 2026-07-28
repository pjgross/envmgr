import pytest
from sqlalchemy import select
from app.db.models.lifecycle import LifecycleTemplate
from app.services.incident_defaults import seed_incident_defaults_for_tenant


@pytest.mark.asyncio
async def test_seeds_default_incident_template(db_session, tenant):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "incident",
        )
    )).scalars().all()
    assert len(rows) == 1
    tpl = rows[0]
    assert tpl.is_default is True
    keys = {s["key"] for s in tpl.definition["states"]}
    assert {"new", "investigating", "identified", "fix_scheduled", "resolved", "closed", "cancelled"} <= keys
    initial = [s for s in tpl.definition["states"] if s.get("is_initial")]
    assert len(initial) == 1 and initial[0]["key"] == "new"
    resolved = [s for s in tpl.definition["states"] if s.get("is_resolved")]
    assert resolved and resolved[0]["key"] == "resolved"


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, tenant):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "incident",
        )
    )).scalars().all()
    assert len(rows) == 1
