"""Environment comparison assembled from the database, both engines."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.db.models.environment import (
    Environment,
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
    EnvironmentSystem,
)
from app.db.models.infrastructure_component import (
    InfrastructureComponent,
    InfrastructureComponentType,
)
from app.db.models.system import SubSystem, System
from app.db.models.version import EnvironmentSubSystemVersion
from app.services import environment_comparison_service as svc


@pytest.fixture
async def fixture_pair(db_session, test_tenant):
    """Two environments, one shared system, one shared subsystem."""
    left = Environment(tenant_id=test_tenant.id, name="SIT", environment_type="test")
    right = Environment(tenant_id=test_tenant.id, name="UAT", environment_type="test")
    system = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add_all([left, right, system])
    await db_session.flush()

    sub = SubSystem(tenant_id=test_tenant.id, system_id=system.id, name="api")
    db_session.add(sub)
    await db_session.flush()

    for env in (left, right):
        db_session.add(EnvironmentSystem(
            tenant_id=test_tenant.id, environment_id=env.id, system_id=system.id))
        db_session.add(EnvironmentSubSystem(
            tenant_id=test_tenant.id, environment_id=env.id, subsystem_id=sub.id,
            is_mocked=False))
    await db_session.flush()
    return {"left": left, "right": right, "system": system, "sub": sub}


async def _host(db_session, tenant_id, env, sub_id, *, component_type, role, name):
    component = InfrastructureComponent(
        tenant_id=tenant_id, name=name, component_type=component_type)
    db_session.add(component)
    await db_session.flush()
    env_sub = (await db_session.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == env.id,
            EnvironmentSubSystem.subsystem_id == sub_id,
        )
    )).scalar_one()
    db_session.add(EnvironmentSubSystemHost(
        tenant_id=tenant_id, environment_subsystem_id=env_sub.id,
        infrastructure_component_id=component.id, role=role))
    await db_session.flush()


@pytest.mark.asyncio
async def test_identical_environments_report_no_differences(
    db_session, test_tenant, fixture_pair
):
    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    assert result["summary"]["differing"] == 0
    assert all(row["differences"] == [] for row in result["subsystems"])


@pytest.mark.asyncio
async def test_same_host_shape_with_different_hostnames_is_not_a_difference(
    db_session, test_tenant, fixture_pair
):
    """The whole justification for host_shape.

    sit-app-01 and uat-app-01 are the same shape. If this ever fails, someone
    has changed the comparison back to host identity.
    """
    await _host(db_session, test_tenant.id, fixture_pair["left"], fixture_pair["sub"].id,
                component_type=InfrastructureComponentType.SERVER, role="primary",
                name="sit-app-01")
    await _host(db_session, test_tenant.id, fixture_pair["right"], fixture_pair["sub"].id,
                component_type=InfrastructureComponentType.SERVER, role="primary",
                name="uat-app-01")

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == []


@pytest.mark.asyncio
async def test_a_different_replica_count_is_a_host_shape_difference(
    db_session, test_tenant, fixture_pair
):
    await _host(db_session, test_tenant.id, fixture_pair["left"], fixture_pair["sub"].id,
                component_type=InfrastructureComponentType.SERVER, role="primary",
                name="sit-app-01")
    for name in ("uat-app-01", "uat-app-02"):
        await _host(db_session, test_tenant.id, fixture_pair["right"], fixture_pair["sub"].id,
                    component_type=InfrastructureComponentType.SERVER, role="primary",
                    name=name)

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == ["host_shape"]
    assert row["left"]["host_shape"][0]["count"] == 1
    assert row["right"]["host_shape"][0]["count"] == 2


@pytest.mark.asyncio
async def test_a_mocked_subsystem_differs_from_a_real_one(
    db_session, test_tenant, fixture_pair
):
    env_sub = (await db_session.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == fixture_pair["right"].id)
    )).scalar_one()
    env_sub.is_mocked = True
    env_sub.mock_notes = "stubbed until the gateway contract lands"
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == ["mocked"]
    # mock_notes travels for display but is never compared.
    assert row["right"]["mock_notes"] == "stubbed until the gateway contract lands"


@pytest.mark.asyncio
async def test_differing_mock_notes_alone_is_not_a_difference(
    db_session, test_tenant, fixture_pair
):
    """Free text would otherwise make every mocked subsystem differ."""
    rows = (await db_session.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.subsystem_id == fixture_pair["sub"].id)
    )).scalars().all()
    for i, row in enumerate(rows):
        row.is_mocked = True
        row.mock_notes = f"note {i}"
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == []


@pytest.mark.asyncio
async def test_version_differences_and_the_both_absent_case(
    db_session, test_tenant, fixture_pair
):
    # Absent on both sides first — must not be a difference.
    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)
    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["left"]["version"] is None and row["right"]["version"] is None
    assert row["differences"] == []

    # Now record one side only.
    db_session.add(EnvironmentSubSystemVersion(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=fixture_pair["sub"].id, build_identifier="b-1",
        version_label="1.4.0", installed_at=datetime(2026, 6, 1, tzinfo=timezone.utc)))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)
    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == ["version"]
    assert row["left"]["version"] == "1.4.0"


@pytest.mark.asyncio
async def test_the_version_used_is_the_current_one_not_the_first(
    db_session, test_tenant, fixture_pair
):
    """Two versions recorded for the same subsystem; the later one wins."""
    for label, day in (("1.0.0", 1), ("2.0.0", 9)):
        db_session.add(EnvironmentSubSystemVersion(
            tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
            subsystem_id=fixture_pair["sub"].id, build_identifier=f"b-{label}",
            version_label=label,
            installed_at=datetime(2026, 6, day, tzinfo=timezone.utc)))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["left"]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_a_subsystem_on_one_side_only_reports_presence_alone(
    db_session, test_tenant, fixture_pair
):
    extra = SubSystem(tenant_id=test_tenant.id,
                      system_id=fixture_pair["system"].id, name="worker")
    db_session.add(extra)
    await db_session.flush()
    db_session.add(EnvironmentSubSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=extra.id, is_mocked=True))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == extra.id)
    assert row["presence"] == "left_only"
    assert row["differences"] == ["presence"]
    assert row["right"] is None


@pytest.mark.asyncio
async def test_the_summary_agrees_with_the_rows(db_session, test_tenant, fixture_pair):
    """These are the two numbers that drifted apart three times in the
    pagination programme. They are built from the same arrays here."""
    extra = SubSystem(tenant_id=test_tenant.id,
                      system_id=fixture_pair["system"].id, name="worker")
    db_session.add(extra)
    await db_session.flush()
    db_session.add(EnvironmentSubSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=extra.id, is_mocked=False))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    rows = result["subsystems"]
    summary = result["summary"]
    assert summary["compared"] == len(rows)
    assert summary["differing"] == sum(1 for r in rows if r["differences"])
    for kind in ("presence", "mocked", "version", "host_shape"):
        assert summary["by_kind"][kind] == sum(
            1 for r in rows if kind in r["differences"]), kind


@pytest.mark.asyncio
async def test_differing_rows_come_first(db_session, test_tenant, fixture_pair):
    extra = SubSystem(tenant_id=test_tenant.id,
                      system_id=fixture_pair["system"].id, name="aaa-first-alphabetically")
    db_session.add(extra)
    await db_session.flush()
    db_session.add(EnvironmentSubSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=extra.id, is_mocked=False))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    assert result["subsystems"][0]["differences"] != []


@pytest.mark.asyncio
async def test_systems_presence_is_reported(db_session, test_tenant, fixture_pair):
    other = System(tenant_id=test_tenant.id, name="Reporting")
    db_session.add(other)
    await db_session.flush()
    db_session.add(EnvironmentSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["right"].id,
        system_id=other.id))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    by_name = {s["name"]: s for s in result["systems"]}
    assert by_name["Payments"]["presence"] == "both"
    assert by_name["Reporting"]["presence"] == "right_only"
