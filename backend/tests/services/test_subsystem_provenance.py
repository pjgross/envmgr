"""A subsystem must record where it came from.

Without this, a drift report cannot tell a resource deleted from the code
apart from one a person added by hand, so every hand-made subsystem would be
reported as drift on every run.
"""
import pytest

from app.db.models.system import SubSystem, SubSystemSource, System


@pytest.mark.asyncio
async def test_a_subsystem_defaults_to_manual_provenance(db_session, test_tenant):
    system = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add(system)
    await db_session.flush()

    sub = SubSystem(
        tenant_id=test_tenant.id, system_id=system.id,
        name="api", component_type="web_service",
    )
    db_session.add(sub)
    await db_session.flush()

    assert sub.source == SubSystemSource.MANUAL
    assert sub.source_path is None


@pytest.mark.asyncio
async def test_provenance_round_trips_through_the_database(db_session, test_tenant):
    system = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add(system)
    await db_session.flush()

    sub = SubSystem(
        tenant_id=test_tenant.id, system_id=system.id,
        name="aws_db_instance.main", component_type="database",
        source=SubSystemSource.TERRAFORM_HCL, source_path="infra/main.tf",
    )
    db_session.add(sub)
    await db_session.flush()
    db_session.expunge(sub)

    reloaded = await db_session.get(SubSystem, sub.id)
    assert reloaded.source == SubSystemSource.TERRAFORM_HCL
    assert reloaded.source_path == "infra/main.tf"
