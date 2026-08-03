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
