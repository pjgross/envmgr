"""A subsystem must record where it came from.

Without this, a drift report cannot tell a resource deleted from the code
apart from one a person added by hand, so every hand-made subsystem would be
reported as drift on every run.
"""
import pytest
from sqlalchemy import text

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


@pytest.mark.asyncio
async def test_source_is_persisted_as_the_lowercase_enum_value_not_the_member_name(
    db_session, test_tenant
):
    """Guard the on-disk encoding of `source`, not just the round trip.

    Reading back through the ORM decodes with the same `values_callable` codec
    that wrote the value, so a round-trip assertion passes whether the column
    stores "terraform_hcl" (the enum VALUE) or "TERRAFORM_HCL" (the member
    NAME) — both decode fine as long as reader and writer agree. Querying with
    raw SQL bypasses that decode and asserts what is actually sitting in the
    column, which is what the migration's `server_default="manual"` depends on
    matching.
    """
    system = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add(system)
    await db_session.flush()

    explicit = SubSystem(
        tenant_id=test_tenant.id, system_id=system.id,
        name="aws_db_instance.main", component_type="database",
        source=SubSystemSource.TERRAFORM_HCL, source_path="infra/main.tf",
    )
    defaulted = SubSystem(
        tenant_id=test_tenant.id, system_id=system.id,
        name="api", component_type="web_service",
    )
    db_session.add_all([explicit, defaulted])
    await db_session.flush()

    raw = await db_session.execute(
        text("SELECT id, source FROM subsystem WHERE id IN (:a, :b)"),
        {"a": explicit.id, "b": defaulted.id},
    )
    raw_by_id = dict(raw.all())

    # Explicit assignment goes through the ORM's SAEnum codec.
    assert raw_by_id[explicit.id] == "terraform_hcl"
    # The default arrives via the column's server_default, a different path
    # (DDL-level, not the ORM codec) that could disagree with it.
    assert raw_by_id[defaulted.id] == "manual"
