import pytest
from sqlalchemy import select
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release_event import ReleaseEventType
from app.services.release_defaults import seed_release_defaults_for_tenant


@pytest.mark.asyncio
async def test_seed_release_defaults_creates_four_lifecycles(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
        )
    )).scalars().all()
    names = {r.name for r in rows}
    assert names == {"Major", "Minor", "Emergency", "Enterprise Release — default"}
    major = next(r for r in rows if r.name == "Major")
    assert major.is_default is True


@pytest.mark.asyncio
async def test_seed_release_defaults_creates_event_types(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(ReleaseEventType).where(ReleaseEventType.tenant_id == tenant.id)
    )).scalars().all()
    names = {r.name for r in rows}
    assert {"Reschedule Reason", "Scope Change", "Stakeholder Note", "Post-Go-Live Incident"} <= names
    for r in rows:
        if r.name in {"Reschedule Reason", "Scope Change", "Stakeholder Note", "Post-Go-Live Incident"}:
            assert r.is_system is True


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
        )
    )).scalars().all()
    assert len(rows) == 4  # still 4, not 8
