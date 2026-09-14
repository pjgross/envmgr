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


@pytest.mark.asyncio
async def test_default_project_templates_carry_the_c6_flags(db_session, test_tenant):
    from app.services.release_defaults import seed_release_defaults_for_tenant
    from app.db.models.lifecycle import LifecycleTemplate
    from app.db.models.release_event import ReleaseEventType
    from sqlalchemy import select

    await seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
    rows = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == test_tenant.id,
        LifecycleTemplate.entity_type == "release"))).scalars().all()
    by_name = {r.name: r for r in rows}
    for name in ("Major", "Minor", "Emergency"):
        states = {s["key"]: s for s in by_name[name].definition["states"]}
        assert states["deployed"]["marks_deployed"] is True
        assert states["deployed"]["is_terminal"] is False
        assert states["completed"]["is_closed"] is True
        assert states["completed"]["marks_deployed"] is True
        assert states["backed_out"]["is_closed"] is True
        assert states["backed_out"].get("marks_deployed", False) is False
        assert states["cancelled"].get("is_closed", False) is False
        pairs = {(t["from_state"], t["to_state"]) for t in by_name[name].definition["transitions"]}
        assert ("deployed", "completed") in pairs
        assert ("deployed", "backed_out") in pairs
    major_pairs = {(t["from_state"], t["to_state"]) for t in by_name["Major"].definition["transitions"]}
    assert ("ready_for_release", "deployed") in major_pairs
    assert ("ready_for_release", "completed") in major_pairs  # the direct path stays
    enterprise = by_name["Enterprise Release — default"].definition["states"]
    assert not any(s.get("is_closed") or s.get("marks_deployed") for s in enterprise)

    names = {r.name for r in (await db_session.execute(select(ReleaseEventType).where(
        ReleaseEventType.tenant_id == test_tenant.id, ReleaseEventType.is_system.is_(True)
    ))).scalars().all()}
    assert {"Declared stable", "Stability declaration withdrawn",
            "Ops handover confirmed", "Ops handover withdrawn"} <= names
