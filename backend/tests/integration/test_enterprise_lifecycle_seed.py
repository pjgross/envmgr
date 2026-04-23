import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.services import release_defaults


@pytest.mark.asyncio
async def test_seed_creates_enterprise_template(db_session, tenant):
    """Seeding a tenant produces exactly one enterprise-kind template with correct shape."""
    await release_defaults.seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()

    enterprise_templates = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
            LifecycleTemplate.applies_to_kind == "enterprise",
        )
    )).scalars().all()
    assert len(enterprise_templates) == 1
    tpl = enterprise_templates[0]
    states = [s["key"] for s in tpl.definition["states"]]
    assert "admission_closed" in states
    lockdown = next(s for s in tpl.definition["states"] if s.get("is_admission_lockdown"))
    assert lockdown["key"] == "admission_closed"
    perms = tpl.definition["action_permissions"]
    assert "Admin" in perms["admission_open"]["membership.admit"]


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, tenant):
    """Second call does not create a duplicate template."""
    await release_defaults.seed_release_defaults_for_tenant(db_session, tenant.id)
    await release_defaults.seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()

    enterprise_templates = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.applies_to_kind == "enterprise",
        )
    )).scalars().all()
    assert len(enterprise_templates) == 1
