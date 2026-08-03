"""apply() then diff() over the same declaration must find nothing.

This is what pins the two halves together. Any disagreement between the writer
and the differ — a truncation applied on one side only, an edge one writes and
the other reports, a type inferred differently — shows up here as non-zero
drift, and would otherwise ship as a report that confidently describes changes
a scan would never make.
"""
import pytest

from app.db.models.dependency import DependencySource
from app.db.models.system import SubSystemSource, System
from app.services.docker_compose_import_service import parse_docker_compose
from app.services.scanning import reconcile
from app.services.terraform_hcl_import_service import parse_terraform_hcl

COMPOSE = b"""
services:
  api:
    image: nginx:1.25
    ports:
      - "8080:80"
    depends_on:
      - db
      - cache
  db:
    image: postgres:15
  cache:
    image: redis:7
  worker:
    image: celery:5
    depends_on:
      db:
        condition: service_healthy
"""

HCL = b"""
resource "aws_db_instance" "main" {
  allocated_storage = 20
}
resource "aws_elasticache_cluster" "sessions" {
  engine = "redis"
}
resource "aws_lambda_function" "worker" {
  runtime = "python3.12"
}
"""

# Two files that both declare api -> db, but disagree on api's published port.
# A real repo produces this shape whenever a dependency is redeclared across
# compose files — e.g. an override file republishing a different container
# port. (The importer keys the edge's port off the *container* side of
# "host:container", so the two files below must differ there, not just in
# the host-side port, to actually produce conflicting DeclaredEdge.port
# values.)
COMPOSE_CONFLICTING_PORT_A = b"""
services:
  api:
    image: nginx:1.25
    ports:
      - "8080:80"
    depends_on:
      - db
  db:
    image: postgres:15
"""

COMPOSE_CONFLICTING_PORT_B = b"""
services:
  api:
    image: nginx:1.25
    ports:
      - "9090:8443"
    depends_on:
      - db
  db:
    image: postgres:15
"""

# depends_on names a service no file in the repo defines — valid YAML, and
# something a partial or misconfigured repo really produces.
COMPOSE_UNDECLARED_DEPENDENCY = b"""
services:
  api:
    image: nginx:1.25
    depends_on:
      - ghost
"""

# Two files declaring disjoint services — the ordinary multi-file case, no
# conflict, just accumulation.
COMPOSE_DISJOINT_A = b"""
services:
  web:
    image: nginx:1.25
    depends_on:
      - db
  db:
    image: postgres:15
"""

COMPOSE_DISJOINT_B = b"""
services:
  worker:
    image: celery:5
    depends_on:
      - cache
  cache:
    image: redis:7
"""


@pytest.fixture
async def system(db_session, test_tenant):
    row = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_applying_then_diffing_a_compose_file_reports_no_drift(
    db_session, test_tenant, system
):
    declared = parse_docker_compose(COMPOSE, "docker-compose.yml")

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is False, (
        f"missing_in_catalogue={[s.name for s in report.subsystems_missing_in_catalogue]} "
        f"missing_in_code={report.subsystems_missing_in_code} "
        f"changed={report.subsystems_changed} "
        f"edges_missing={[(e.from_name, e.to_name) for e in report.edges_missing_in_catalogue]} "
        f"edges_absent={report.edges_missing_in_code} "
        f"edges_changed={report.edges_changed}"
    )


@pytest.mark.asyncio
async def test_applying_then_diffing_terraform_hcl_reports_no_drift(
    db_session, test_tenant, system
):
    declared = parse_terraform_hcl(HCL, "infra/main.tf")

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.TERRAFORM_HCL, edge_source=None, declared=declared,
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.TERRAFORM_HCL, edge_source=None, declared=declared,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is False, report


@pytest.mark.asyncio
async def test_the_round_trip_holds_for_over_length_names(
    db_session, test_tenant, system
):
    """Truncation happens in the parser. If apply() truncated instead, every
    long name would report a change forever, on every run."""
    long_name = "a" * 250
    content = f"services:\n  {long_name}:\n    image: postgres:15\n".encode()
    declared = parse_docker_compose(content, "docker-compose.yml")

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is False, report


@pytest.mark.asyncio
async def test_the_round_trip_holds_for_over_length_technology_and_source_path(
    db_session, test_tenant, system
):
    """Same hazard as the over-length-name test above, for the other two
    truncated fields. `technology` comes from the compose `image` with the
    tag stripped, so a long image name produces a long `technology`.
    `source_path` is the repository path handed to the parser. Both are only
    truncated in the parser, not in apply() — if either truncation moved (or
    were dropped) the stored row would differ from the declaration on every
    run. SQLite does not enforce column widths, so this can only fail on the
    PostgreSQL leg."""
    long_technology = "t" * 150
    long_path = "modules/" * 70 + "docker-compose.yml"
    assert len(long_technology) > 100
    assert len(long_path) > 500
    content = f"services:\n  api:\n    image: {long_technology}:latest\n".encode()
    declared = parse_docker_compose(content, long_path)

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is False, (
        f"subsystems_changed={report.subsystems_changed} "
        f"missing_in_catalogue={[s.name for s in report.subsystems_missing_in_catalogue]} "
        f"missing_in_code={report.subsystems_missing_in_code}"
    )


@pytest.mark.asyncio
async def test_applying_twice_then_diffing_still_reports_no_drift(
    db_session, test_tenant, system
):
    """Re-scanning must be idempotent — the delete-then-recreate of edges is
    the easiest place for a second run to leave the catalogue different."""
    declared = parse_docker_compose(COMPOSE, "docker-compose.yml")

    for _ in range(2):
        await reconcile.apply(
            db_session, system_id=system.id, tenant_id=test_tenant.id,
            source=SubSystemSource.DOCKER_COMPOSE,
            edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        )

    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        absence_computed=True, absence_reason=None,
    )
    assert report.has_drift is False, report


@pytest.mark.asyncio
async def test_removing_a_service_from_the_code_then_diffing_finds_it(
    db_session, test_tenant, system
):
    """The negative control. Without it the round-trip tests above would still
    pass against a diff() that always returns nothing."""
    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE,
        declared=parse_docker_compose(COMPOSE, "docker-compose.yml"),
    )

    shrunk = parse_docker_compose(
        b"services:\n  api:\n    image: nginx:1.25\n", "docker-compose.yml"
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=shrunk,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is True
    assert set(report.subsystems_missing_in_code) == {"db", "cache", "worker"}


@pytest.mark.asyncio
async def test_the_round_trip_holds_over_an_accumulated_state_with_a_repeated_edge(
    db_session, test_tenant, system
):
    """The real-scanner shape: two files accumulated with __add__, both
    declaring api -> db with a different port. This is exactly the shape of
    the one round-trip defect this feature has had — apply() resolved a
    repeated (from, to) edge first-wins while diff() resolved it last-wins, so
    a report described a change immediately after applying the very same
    value. Both are last-wins now; this pins it."""
    declared = (
        parse_docker_compose(COMPOSE_CONFLICTING_PORT_A, "a/docker-compose.yml")
        + parse_docker_compose(COMPOSE_CONFLICTING_PORT_B, "b/docker-compose.yml")
    )
    assert len([e for e in declared.edges if (e.from_name, e.to_name) == ("api", "db")]) == 2

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is False, (
        f"missing_in_catalogue={[s.name for s in report.subsystems_missing_in_catalogue]} "
        f"missing_in_code={report.subsystems_missing_in_code} "
        f"changed={report.subsystems_changed} "
        f"edges_missing={[(e.from_name, e.to_name, e.port) for e in report.edges_missing_in_catalogue]} "
        f"edges_absent={report.edges_missing_in_code} "
        f"edges_changed={report.edges_changed}"
    )


@pytest.mark.asyncio
async def test_the_round_trip_holds_when_a_dependency_names_an_undeclared_service(
    db_session, test_tenant, system
):
    """depends_on can name a service that is not defined anywhere in the repo
    — valid YAML, and something a partial or misconfigured repo really
    produces. apply() cannot write an edge whose endpoint was never declared
    as a subsystem, so diff() must not report it as missing either, or the
    round trip is permanently non-zero for every repo with this shape."""
    declared = parse_docker_compose(COMPOSE_UNDECLARED_DEPENDENCY, "docker-compose.yml")
    assert declared.edges and declared.edges[0].to_name == "ghost"

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is False, (
        f"missing_in_catalogue={[s.name for s in report.subsystems_missing_in_catalogue]} "
        f"missing_in_code={report.subsystems_missing_in_code} "
        f"changed={report.subsystems_changed} "
        f"edges_missing={[(e.from_name, e.to_name, e.port) for e in report.edges_missing_in_catalogue]} "
        f"edges_absent={report.edges_missing_in_code} "
        f"edges_changed={report.edges_changed}"
    )


@pytest.mark.asyncio
async def test_the_round_trip_holds_over_an_accumulated_state_with_disjoint_services(
    db_session, test_tenant, system
):
    """The ordinary multi-file case: two files declaring different services
    with no overlap. Confirms accumulation itself round-trips, not only the
    conflicting-edge case above."""
    declared = (
        parse_docker_compose(COMPOSE_DISJOINT_A, "a/docker-compose.yml")
        + parse_docker_compose(COMPOSE_DISJOINT_B, "b/docker-compose.yml")
    )
    assert {s.name for s in declared.subsystems} == {"web", "db", "worker", "cache"}

    await reconcile.apply(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
    )
    report = await reconcile.diff(
        db_session, system_id=system.id, tenant_id=test_tenant.id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE, declared=declared,
        absence_computed=True, absence_reason=None,
    )

    assert report.has_drift is False, (
        f"missing_in_catalogue={[s.name for s in report.subsystems_missing_in_catalogue]} "
        f"missing_in_code={report.subsystems_missing_in_code} "
        f"changed={report.subsystems_changed} "
        f"edges_missing={[(e.from_name, e.to_name, e.port) for e in report.edges_missing_in_catalogue]} "
        f"edges_absent={report.edges_missing_in_code} "
        f"edges_changed={report.edges_changed}"
    )
