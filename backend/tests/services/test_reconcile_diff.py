"""Comparing a DeclaredState against the catalogue without writing."""
import pytest

from app.db.models.dependency import (
    ComponentDependency, DependencySource, DependencyType,
)
from app.db.models.system import SubSystem, SubSystemSource, System
from app.services.scanning import reconcile
from app.services.scanning.declared import (
    DeclaredEdge, DeclaredState, DeclaredSubsystem,
)


@pytest.fixture
async def system(db_session, test_tenant):
    row = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add(row)
    await db_session.flush()
    return row


async def _diff(db, system, tenant_id, declared, *, absence_computed=True,
                edge_source=None):
    return await reconcile.diff(
        db, system_id=system.id, tenant_id=tenant_id,
        source=SubSystemSource.DOCKER_COMPOSE, edge_source=edge_source,
        declared=declared, absence_computed=absence_computed,
        absence_reason=None if absence_computed else "the tree was truncated",
    )


@pytest.mark.asyncio
async def test_a_subsystem_only_in_the_code_is_missing_from_the_catalogue(
    db_session, test_tenant, system
):
    declared = DeclaredState(subsystems=[
        DeclaredSubsystem("api", "web_service", "nginx", "docker-compose.yml"),
    ])

    report = await _diff(db_session, system, test_tenant.id, declared)

    assert [s.name for s in report.subsystems_missing_in_catalogue] == ["api"]
    assert report.subsystems_missing_in_code == []


@pytest.mark.asyncio
async def test_an_iac_sourced_row_no_longer_declared_is_missing_from_the_code(
    db_session, test_tenant, system
):
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="legacy",
        component_type="web_service", source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.flush()

    report = await _diff(db_session, system, test_tenant.id, DeclaredState())

    assert report.subsystems_missing_in_code == ["legacy"]


@pytest.mark.asyncio
async def test_a_hand_created_row_is_never_reported_as_missing_from_the_code(
    db_session, test_tenant, system
):
    """The whole reason provenance was added. Without it this row appears as
    drift on every run and the report becomes noise people learn to ignore."""
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="hand-made",
        component_type="web_service", source=SubSystemSource.MANUAL,
    ))
    await db_session.flush()

    report = await _diff(db_session, system, test_tenant.id, DeclaredState())

    assert report.subsystems_missing_in_code == []


@pytest.mark.asyncio
async def test_a_row_from_a_different_source_is_not_reported_as_missing(
    db_session, test_tenant, system
):
    """Comparison is scoped per source. Without this, scanning only the compose
    file would report every Terraform row as deleted."""
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="aws_db_instance.main",
        component_type="database", source=SubSystemSource.TERRAFORM_HCL,
    ))
    await db_session.flush()

    report = await _diff(db_session, system, test_tenant.id, DeclaredState())

    assert report.subsystems_missing_in_code == []


@pytest.mark.asyncio
async def test_a_changed_component_type_is_reported_with_both_values(
    db_session, test_tenant, system
):
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="api",
        component_type="other", technology="nginx",
        source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.flush()

    report = await _diff(db_session, system, test_tenant.id, DeclaredState(subsystems=[
        DeclaredSubsystem("api", "web_service", "nginx", "docker-compose.yml"),
    ]))

    assert len(report.subsystems_changed) == 1
    change = report.subsystems_changed[0]
    assert (change.name, change.field) == ("api", "component_type")
    assert (change.catalogue, change.declared) == ("other", "web_service")


@pytest.mark.asyncio
async def test_a_moved_declaration_is_not_drift(db_session, test_tenant, system):
    """A resource moving between files is a refactor. Reporting it would bury
    the real findings."""
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="api",
        component_type="web_service", technology="nginx",
        source=SubSystemSource.DOCKER_COMPOSE, source_path="old/compose.yml",
    ))
    await db_session.flush()

    report = await _diff(db_session, system, test_tenant.id, DeclaredState(subsystems=[
        DeclaredSubsystem("api", "web_service", "nginx", "new/compose.yml"),
    ]))

    assert report.subsystems_changed == []
    assert report.has_drift is False


@pytest.mark.asyncio
async def test_absence_is_null_not_empty_when_it_could_not_be_computed(
    db_session, test_tenant, system
):
    """'We checked and found nothing missing' and 'we could not check' are
    opposite conclusions. An empty list renders them identical."""
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="legacy",
        component_type="web_service", source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.flush()

    report = await _diff(
        db_session, system, test_tenant.id, DeclaredState(), absence_computed=False,
    )

    assert report.subsystems_missing_in_code is None
    assert report.absence_reason == "the tree was truncated"


@pytest.mark.asyncio
async def test_a_duplicate_declaration_warns_and_is_counted_once(
    db_session, test_tenant, system
):
    """Two compose files declaring the same service collapse to one row, last
    write wins. Silent is how a person ends up debugging the wrong file."""
    declared = DeclaredState(subsystems=[
        DeclaredSubsystem("redis", "cache", "redis", "a/compose.yml"),
        DeclaredSubsystem("redis", "cache", "redis", "b/compose.yml"),
    ])

    report = await _diff(db_session, system, test_tenant.id, declared)

    assert len(report.subsystems_missing_in_catalogue) == 1
    assert any("a/compose.yml" in w and "b/compose.yml" in w for w in report.warnings)


@pytest.mark.asyncio
async def test_an_edge_only_in_the_code_is_missing_from_the_catalogue(
    db_session, test_tenant, system
):
    declared = DeclaredState(
        subsystems=[
            DeclaredSubsystem("api", "web_service", None, "c.yml"),
            DeclaredSubsystem("db", "database", None, "c.yml"),
        ],
        edges=[DeclaredEdge("api", "db", 5432, "c.yml")],
    )

    report = await _diff(db_session, system, test_tenant.id, declared,
                         edge_source=DependencySource.DOCKER_COMPOSE)

    assert [(e.from_name, e.to_name) for e in report.edges_missing_in_catalogue] == [
        ("api", "db")
    ]


@pytest.mark.asyncio
async def test_an_edge_to_an_undeclared_endpoint_is_not_reported(
    db_session, test_tenant, system
):
    """apply() cannot write it, so diff() must not claim it is missing —
    otherwise the round-trip never reaches zero."""
    declared = DeclaredState(
        subsystems=[DeclaredSubsystem("api", "web_service", None, "c.yml")],
        edges=[DeclaredEdge("api", "ghost", None, "c.yml")],
    )

    report = await _diff(db_session, system, test_tenant.id, declared,
                         edge_source=DependencySource.DOCKER_COMPOSE)

    assert report.edges_missing_in_catalogue == []


@pytest.mark.asyncio
async def test_a_self_referencing_edge_is_not_reported(db_session, test_tenant, system):
    """apply() drops a self-loop (from_id == to_id) rather than writing it, so
    diff() must skip it too — otherwise it would report a self-loop as
    missing-in-catalogue forever, since apply() can never write one to close
    the gap."""
    declared = DeclaredState(
        subsystems=[DeclaredSubsystem("api", "web_service", None, "c.yml")],
        edges=[DeclaredEdge("api", "api", None, "c.yml")],
    )

    report = await _diff(db_session, system, test_tenant.id, declared,
                         edge_source=DependencySource.DOCKER_COMPOSE)

    assert report.edges_missing_in_catalogue == []


@pytest.mark.asyncio
async def test_a_changed_port_is_reported(db_session, test_tenant, system):
    api_sub = SubSystem(tenant_id=test_tenant.id, system_id=system.id, name="api",
                        component_type="web_service", source=SubSystemSource.DOCKER_COMPOSE)
    db_sub = SubSystem(tenant_id=test_tenant.id, system_id=system.id, name="db",
                       component_type="database", source=SubSystemSource.DOCKER_COMPOSE)
    db_session.add_all([api_sub, db_sub])
    await db_session.flush()
    db_session.add(ComponentDependency(
        tenant_id=test_tenant.id, from_subsystem_id=api_sub.id, to_subsystem_id=db_sub.id,
        # The enum member, not "api_call": DependencyType stores enum NAMES.
        dependency_type=DependencyType.API_CALL,
        source=DependencySource.DOCKER_COMPOSE, port=5432,
    ))
    await db_session.flush()

    declared = DeclaredState(
        subsystems=[
            DeclaredSubsystem("api", "web_service", None, "c.yml"),
            DeclaredSubsystem("db", "database", None, "c.yml"),
        ],
        edges=[DeclaredEdge("api", "db", 6432, "c.yml")],
    )
    report = await _diff(db_session, system, test_tenant.id, declared,
                         edge_source=DependencySource.DOCKER_COMPOSE)

    assert len(report.edges_changed) == 1
    assert (report.edges_changed[0].catalogue_port,
            report.edges_changed[0].declared_port) == (5432, 6432)


@pytest.mark.asyncio
async def test_edges_are_not_compared_when_the_source_declares_none(
    db_session, test_tenant, system
):
    report = await _diff(db_session, system, test_tenant.id, DeclaredState(),
                         edge_source=None)
    assert report.edges_missing_in_catalogue == []
    assert report.edges_missing_in_code is None


@pytest.mark.asyncio
async def test_diff_writes_nothing(db_session, test_tenant, system):
    """It is a report. If it could write, running it would change the answer."""
    from sqlalchemy import func, select as sa_select

    before = (await db_session.execute(
        sa_select(func.count()).select_from(SubSystem)
    )).scalar_one()

    await _diff(db_session, system, test_tenant.id, DeclaredState(subsystems=[
        DeclaredSubsystem("api", "web_service", "nginx", "c.yml"),
    ]))
    await db_session.flush()

    after = (await db_session.execute(
        sa_select(func.count()).select_from(SubSystem)
    )).scalar_one()
    assert after == before
