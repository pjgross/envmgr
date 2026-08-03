"""Writing a DeclaredState into the catalogue."""
import pytest
from sqlalchemy import select

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


async def _apply(db, system, tenant_id, declared, edge_source=None):
    return await reconcile.apply(
        db, system_id=system.id, tenant_id=tenant_id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=edge_source, declared=declared,
    )


@pytest.mark.asyncio
async def test_a_new_declaration_creates_a_row_stamped_with_its_provenance(
    db_session, test_tenant, system
):
    declared = DeclaredState(subsystems=[
        DeclaredSubsystem("api", "web_service", "nginx", "docker-compose.yml"),
    ])

    result = await _apply(db_session, system, test_tenant.id, declared)

    assert (result.subsystems_created, result.subsystems_updated) == (1, 0)
    row = (await db_session.execute(
        select(SubSystem).where(SubSystem.name == "api")
    )).scalar_one()
    assert row.source == SubSystemSource.DOCKER_COMPOSE
    assert row.source_path == "docker-compose.yml"


@pytest.mark.asyncio
async def test_applying_stamps_provenance_on_rows_it_merely_updates(
    db_session, test_tenant, system
):
    """Subsystems created before the source column existed backfilled to
    'manual'. They must stop reading as hand-made once a scan matches them,
    or they would never be eligible for drift."""
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="api",
        component_type="other", source=SubSystemSource.MANUAL,
    ))
    await db_session.flush()

    declared = DeclaredState(subsystems=[
        DeclaredSubsystem("api", "web_service", "nginx", "docker-compose.yml"),
    ])
    result = await _apply(db_session, system, test_tenant.id, declared)

    assert (result.subsystems_created, result.subsystems_updated) == (0, 1)
    row = (await db_session.execute(
        select(SubSystem).where(SubSystem.name == "api")
    )).scalar_one()
    assert row.source == SubSystemSource.DOCKER_COMPOSE
    assert row.component_type.value == "web_service"


@pytest.mark.asyncio
async def test_applying_never_deletes_a_row_the_declaration_dropped(
    db_session, test_tenant, system
):
    """The documented limit that makes the drift report worth having: a scan
    cannot resolve 'in the catalogue but not in the code'."""
    db_session.add(SubSystem(
        tenant_id=test_tenant.id, system_id=system.id, name="legacy",
        component_type="web_service", source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.flush()

    await _apply(db_session, system, test_tenant.id, DeclaredState(subsystems=[
        DeclaredSubsystem("api", "web_service", "nginx", "docker-compose.yml"),
    ]))

    names = set((await db_session.execute(
        select(SubSystem.name).where(SubSystem.system_id == system.id)
    )).scalars().all())
    assert names == {"legacy", "api"}


@pytest.mark.asyncio
async def test_edges_are_written_between_declared_subsystems(
    db_session, test_tenant, system
):
    declared = DeclaredState(
        subsystems=[
            DeclaredSubsystem("api", "web_service", "nginx", "docker-compose.yml"),
            DeclaredSubsystem("db", "database", "postgres", "docker-compose.yml"),
        ],
        edges=[DeclaredEdge("api", "db", 5432, "docker-compose.yml")],
    )

    result = await _apply(
        db_session, system, test_tenant.id, declared,
        edge_source=DependencySource.DOCKER_COMPOSE,
    )

    assert result.dependencies_written == 1
    edge = (await db_session.execute(select(ComponentDependency))).scalar_one()
    assert edge.port == 5432
    assert edge.source == DependencySource.DOCKER_COMPOSE


@pytest.mark.asyncio
async def test_an_edge_to_an_undeclared_endpoint_is_skipped(
    db_session, test_tenant, system
):
    """A compose file can name a service in depends_on that it never defines.
    diff() has to skip these identically or the round-trip breaks."""
    declared = DeclaredState(
        subsystems=[DeclaredSubsystem("api", "web_service", "nginx", "c.yml")],
        edges=[DeclaredEdge("api", "ghost", None, "c.yml")],
    )

    result = await _apply(
        db_session, system, test_tenant.id, declared,
        edge_source=DependencySource.DOCKER_COMPOSE,
    )

    assert result.dependencies_written == 0


@pytest.mark.asyncio
async def test_a_duplicate_edge_pair_is_written_once(db_session, test_tenant, system):
    """uq_component_dep is (from, to, tenant). A second identical pair would
    raise IntegrityError and cost the whole detector its savepoint."""
    declared = DeclaredState(
        subsystems=[
            DeclaredSubsystem("api", "web_service", None, "c.yml"),
            DeclaredSubsystem("db", "database", None, "c.yml"),
        ],
        edges=[
            DeclaredEdge("api", "db", 5432, "c.yml"),
            DeclaredEdge("api", "db", 5432, "c.yml"),
        ],
    )

    result = await _apply(
        db_session, system, test_tenant.id, declared,
        edge_source=DependencySource.DOCKER_COMPOSE,
    )

    assert result.dependencies_written == 1


@pytest.mark.asyncio
async def test_edges_are_left_alone_when_the_source_declares_none(
    db_session, test_tenant, system
):
    """Terraform passes edge_source=None. Reconciling edges on its behalf would
    delete every compose edge in the system the moment a .tf file is scanned."""
    sub_a = SubSystem(tenant_id=test_tenant.id, system_id=system.id,
                      name="api", component_type="web_service")
    sub_b = SubSystem(tenant_id=test_tenant.id, system_id=system.id,
                      name="db", component_type="database")
    db_session.add_all([sub_a, sub_b])
    await db_session.flush()
    db_session.add(ComponentDependency(
        tenant_id=test_tenant.id, from_subsystem_id=sub_a.id, to_subsystem_id=sub_b.id,
        # Pass the enum member, not "api_call". DependencyType's SAEnum has no
        # values_callable, so it stores enum NAMES — a raw value string fails.
        dependency_type=DependencyType.API_CALL,
        source=DependencySource.DOCKER_COMPOSE,
    ))
    await db_session.flush()

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.TERRAFORM_HCL, edge_source=None,
        declared=DeclaredState(subsystems=[
            DeclaredSubsystem("aws_db_instance.main", "database", "aws_db_instance", "main.tf"),
        ]),
    )

    surviving = (await db_session.execute(select(ComponentDependency))).scalars().all()
    assert len(surviving) == 1


@pytest.mark.asyncio
async def test_a_self_referencing_edge_is_skipped(db_session, test_tenant, system):
    """A subsystem cannot depend on itself; from_id == to_id must be dropped
    same as an edge to an undeclared endpoint, or a scan could write a
    self-loop into the catalogue."""
    declared = DeclaredState(
        subsystems=[DeclaredSubsystem("api", "web_service", None, "c.yml")],
        edges=[DeclaredEdge("api", "api", None, "c.yml")],
    )

    result = await _apply(
        db_session, system, test_tenant.id, declared,
        edge_source=DependencySource.DOCKER_COMPOSE,
    )

    assert result.dependencies_written == 0
    surviving = (await db_session.execute(select(ComponentDependency))).scalars().all()
    assert surviving == []


@pytest.mark.asyncio
async def test_edge_source_none_with_declared_edges_raises(
    db_session, test_tenant, system
):
    """edge_source=None promises 'this source declares no edges'. A caller
    that breaks that promise must be stopped loudly: writing the edges
    anyway would stamp them source=MANUAL (SQLAlchemy's Python-side default
    kicks in for an explicit None) and a re-scan would then hit
    IntegrityError on uq_component_dep, since the None-keyed delete can never
    clean the mislabelled rows back up."""
    declared = DeclaredState(
        subsystems=[
            DeclaredSubsystem("api", "web_service", None, "main.tf"),
            DeclaredSubsystem("db", "database", None, "main.tf"),
        ],
        edges=[DeclaredEdge("api", "db", None, "main.tf")],
    )

    with pytest.raises(ValueError):
        await _apply(db_session, system, test_tenant.id, declared, edge_source=None)


@pytest.mark.asyncio
async def test_edge_source_none_with_no_edges_returns_quietly(
    db_session, test_tenant, system
):
    """The normal Terraform case: no edges declared, edge_source=None, no
    exception — only a DeclaredState carrying edges should raise."""
    declared = DeclaredState(subsystems=[
        DeclaredSubsystem("aws_db_instance.main", "database", "aws_db_instance", "main.tf"),
    ])

    result = await _apply(db_session, system, test_tenant.id, declared, edge_source=None)

    assert (result.subsystems_created, result.subsystems_updated) == (1, 0)


@pytest.mark.asyncio
async def test_reapplying_the_same_edges_does_not_accumulate_duplicates(
    db_session, test_tenant, system
):
    declared = DeclaredState(
        subsystems=[
            DeclaredSubsystem("api", "web_service", None, "c.yml"),
            DeclaredSubsystem("db", "database", None, "c.yml"),
        ],
        edges=[DeclaredEdge("api", "db", 5432, "c.yml")],
    )

    await _apply(db_session, system, test_tenant.id, declared,
                 edge_source=DependencySource.DOCKER_COMPOSE)
    await _apply(db_session, system, test_tenant.id, declared,
                 edge_source=DependencySource.DOCKER_COMPOSE)

    edges = (await db_session.execute(select(ComponentDependency))).scalars().all()
    assert len(edges) == 1
