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


MALFORMED = b"""
resource "aws_instance" {
  ami           = "ami-123"
  instance_type = "t3.micro"
}
"""


@pytest.mark.asyncio
async def test_a_resource_missing_its_name_label_creates_nothing(
    db_session, test_tenant, system
):
    """Grammatically valid HCL, invalid Terraform. The attributes sit where the
    resource name should be, so taking those keys as names fabricates one bogus
    subsystem per attribute — and reports success while doing it."""
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=MALFORMED, db=db_session
    )
    assert result["subsystems_created"] == 0
    assert result["warnings"], "a skipped block must be reported, not silently dropped"

    from sqlalchemy import select
    names = {s.name for s in (await db_session.execute(
        select(SubSystem).where(SubSystem.system_id == system.id)
    )).scalars().all()}
    assert names == set()
    assert "aws_instance.ami" not in names


@pytest.mark.asyncio
async def test_a_well_formed_file_reports_no_warnings(db_session, test_tenant, system):
    """Positive control: the guard must not fire on valid input."""
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert result["subsystems_created"] == 2
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_component_type_is_inferred_like_the_tfstate_sibling(
    db_session, test_tenant, system
):
    """Unlike terraform_import_service (.tfstate), this importer used to leave
    every SubSystem at the default component_type with no technology. Reuse
    the same TF_TYPE_MAP-backed inference so an HCL-imported database reads
    as a database, not as an undifferentiated 'other'."""
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert result["subsystems_created"] == 2

    from sqlalchemy import select
    rows = {s.name: s for s in (await db_session.execute(
        select(SubSystem).where(SubSystem.system_id == system.id)
    )).scalars().all()}

    assert rows["aws_db_instance.main"].component_type == "database"
    assert rows["aws_db_instance.main"].technology == "aws_db_instance"
    # aws_instance has no entry in TF_TYPE_MAP — infer_component_type's
    # documented fallback is 'other', not left unset.
    assert rows["aws_instance.api"].component_type == "other"
    assert rows["aws_instance.api"].technology == "aws_instance"


@pytest.mark.asyncio
async def test_reimporting_refreshes_component_type_too(db_session, test_tenant, system):
    """The tfstate importer updates component_type/technology on every
    reimport, not just on first creation; this importer must match."""
    await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    second = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert second["subsystems_updated"] == 2

    from sqlalchemy import select
    row = (await db_session.execute(
        select(SubSystem).where(
            SubSystem.system_id == system.id, SubSystem.name == "aws_db_instance.main"
        )
    )).scalar_one()
    assert row.component_type == "database"


@pytest.mark.asyncio
async def test_a_resource_address_longer_than_200_chars_is_truncated(
    db_session, test_tenant, system
):
    """SubSystem.name is String(200). PostgreSQL raises on an over-length
    value where SQLite silently stores it — a long Terraform address (a
    deeply-nested module instance, say) is a dual-engine failure waiting to
    happen without the same [:200] terraform_import_service already applies.
    Must pass on both engines: run this file against SQLite and again with
    TEST_DATABASE_URL pointed at PostgreSQL.
    """
    long_name = "x" * 250
    tf = f'''
resource "aws_instance" "{long_name}" {{
  ami = "ami-123"
}}
'''.encode()

    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=tf, db=db_session
    )
    assert result["subsystems_created"] == 1

    from sqlalchemy import select
    row = (await db_session.execute(
        select(SubSystem).where(SubSystem.system_id == system.id)
    )).scalar_one()
    assert len(row.name) <= 200
    assert row.name == f"aws_instance.{long_name}"[:200]
