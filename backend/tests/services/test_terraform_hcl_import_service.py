"""Terraform .tf (HCL source) import.

Distinct from terraform_import_service, which parses .tfstate. HCL gives
DECLARED resources: no computed values, no resource ids. The two will not
produce identical rows for the same infrastructure.
"""
import pytest

from app.db.models.system import SubSystem, System
from app.services import terraform_hcl_import_service as svc

TF = b"""
resource "aws_instance" "api" {
  ami           = "ami-123"
  instance_type = "t3.micro"
}

resource "aws_db_instance" "main" {
  engine = "postgres"
}

variable "region" {
  default = "eu-west-2"
}
"""


@pytest.fixture
async def system(db_session, test_tenant):
    row = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_resources_become_subsystems(db_session, test_tenant, system):
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert result["subsystems_created"] == 2

    from sqlalchemy import select
    names = {s.name for s in (await db_session.execute(
        select(SubSystem).where(SubSystem.system_id == system.id)
    )).scalars().all()}
    assert names == {"aws_instance.api", "aws_db_instance.main"}


@pytest.mark.asyncio
async def test_non_resource_blocks_are_ignored(db_session, test_tenant, system):
    """variable/output/provider blocks are not infrastructure to inventory."""
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert result["subsystems_created"] == 2  # not 3 — `variable` excluded


@pytest.mark.asyncio
async def test_reimporting_updates_rather_than_duplicating(
    db_session, test_tenant, system
):
    await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    second = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert second["subsystems_created"] == 0
    assert second["subsystems_updated"] == 2


@pytest.mark.asyncio
async def test_invalid_hcl_raises_a_value_error(db_session, test_tenant, system):
    """The scanner turns this into a per-detector error rather than a 500."""
    with pytest.raises(ValueError):
        await svc.import_terraform_hcl(
            system_id=system.id, tenant_id=test_tenant.id,
            content=b'resource "aws_instance" {{{ broken', db=db_session,
        )


@pytest.mark.asyncio
async def test_an_empty_file_creates_nothing(db_session, test_tenant, system):
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=b"", db=db_session
    )
    assert result["subsystems_created"] == 0
