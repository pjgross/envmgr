# Drift Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only report on a System that shows where the subsystem catalogue no longer matches what the system's GitHub repository declares.

**Architecture:** Split parsing from persistence. Detectors currently *are* the writers, so "what the code declares" never exists as a value that could be compared. After this plan, each detector parses into a `DeclaredState` value, and two consumers read it: `reconcile.apply()` (what a scan does today) and `reconcile.diff()` (the new drift report). Because both read the same value, the report cannot describe a change a scan would not make.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, pytest (SQLite + PostgreSQL), React 18 + TypeScript + MUI.

**Spec:** [docs/superpowers/specs/2026-08-03-drift-detection-design.md](../specs/2026-08-03-drift-detection-design.md)

## Global Constraints

- **Enum columns use `native_enum=False`.** PostgreSQL native ENUMs break the SQLite test leg.
- **Migrations are hand-written.** `init_db()` calls `create_all`, so `alembic revision --autogenerate` produces empty migrations. Use `alembic revision -m "..."` and write `op.add_column` DDL yourself.
- **Never call `db.commit()` in a service.** `get_db()` commits on success; committing inside a service breaks the outbox pattern. Use `await db.flush()` when you need an id mid-transaction.
- **Tenant scoping:** every query filters on `tenant_id`. In endpoints use `current_user.active_tenant_id`, never `.tenant_id`.
- **Run both engines before claiming done:**
  `cd backend && uv run pytest -q`
  `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
- **Parsers emit canonical values.** Truncate in the parser, never in `apply()`: `name` to 200 chars, `technology` to 100, `source_path` to 500. If `apply()` truncated but the declared value did not, `diff()` would report a change on every single run.
- **Mutate every new test to confirm it fails.** This repo has a documented history of tests that passed while guarding nothing. Break the implementation deliberately, watch the test go red, restore it.
- **Commit after every task.** Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.

---

## File Structure

**Created:**
- `backend/app/services/scanning/declared.py` — the value objects. No imports from the app beyond stdlib/dataclasses.
- `backend/app/services/scanning/reconcile.py` — `apply()` and `diff()`, the only two modules that write or compare.
- `backend/app/db/migrations/versions/20260803_1400_subsystemsource_add_subsystem_provenance.py`
- `backend/tests/services/test_reconcile_apply.py`
- `backend/tests/services/test_reconcile_diff.py`
- `backend/tests/services/test_reconcile_roundtrip.py` — the load-bearing guarantee.
- `backend/tests/integration/test_drift_api.py`
- `frontend/src/components/systems/DriftDialog.tsx`
- `frontend/src/components/systems/__tests__/DriftDialog.test.tsx`

**Modified:**
- `backend/app/db/models/system.py` — `SubSystemSource` enum, two columns.
- `backend/app/services/scanning/registry.py` — `Detector` gains source fields; `parse` returns `DeclaredState`; `ParseContext` sheds `db`/`system_id`/`tenant_id`.
- `backend/app/services/docker_compose_import_service.py` — `parse_docker_compose()` pure; `import_docker_compose()` becomes a thin wrapper.
- `backend/app/services/terraform_hcl_import_service.py` — same split.
- `backend/app/services/terraform_import_service.py` — same split (`.tfstate` gains provenance for free).
- `backend/app/services/scanning/scanner.py` — walk extracted; `scan_repository()` and `drift_repository()` share it.
- `backend/app/services/scanning/detectors/compose.py`, `detectors/terraform_hcl.py` — declare their sources, return `DeclaredState`.
- `backend/app/api/v1/systems.py` — the drift endpoint.
- `frontend/src/types/githubIntegration.ts`, `frontend/src/services/githubIntegrationService.ts`, `frontend/src/pages/systems/SystemDetail.tsx`

**Deliberately unchanged:** `backend/app/api/v1/import_routes.py`. It calls `import_docker_compose` and `import_terraform` directly for file uploads; the wrapper functions keep their existing signatures and return shapes so that endpoint and its tests keep working untouched.

---

### Task 1: Subsystem provenance

Adds `source` and `source_path` to `SubSystem`. Without provenance, "in the catalogue but not in the code" cannot be distinguished from "added by hand on purpose", and the report would flag every manually-created subsystem forever.

**Files:**
- Modify: `backend/app/db/models/system.py`
- Create: `backend/app/db/migrations/versions/20260803_1400_subsystemsource_add_subsystem_provenance.py`
- Test: `backend/tests/services/test_subsystem_provenance.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SubSystemSource` enum with members `MANUAL`, `TERRAFORM`, `TERRAFORM_HCL`, `DOCKER_COMPOSE` (values `"manual"`, `"terraform"`, `"terraform_hcl"`, `"docker_compose"`); `SubSystem.source: SubSystemSource`; `SubSystem.source_path: str | None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_subsystem_provenance.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_subsystem_provenance.py -v`
Expected: FAIL — `ImportError: cannot import name 'SubSystemSource'`

- [ ] **Step 3: Add the enum and columns to the model**

In `backend/app/db/models/system.py`, add after the `ComponentType` enum:

```python
class SubSystemSource(str, enum.Enum):
    """Where a subsystem row came from.

    `terraform` is a .tfstate upload and `terraform_hcl` is .tf source read
    from a repository. They are separate values on purpose: the two formats do
    not produce identical rows (HCL has no computed values or resource ids), so
    a drift report must never compare one against the other.
    """

    MANUAL = "manual"
    TERRAFORM = "terraform"
    TERRAFORM_HCL = "terraform_hcl"
    DOCKER_COMPOSE = "docker_compose"
```

Then add these two columns to `SubSystem`, immediately after `custom_fields`:

```python
    source: Mapped[SubSystemSource] = mapped_column(
        SAEnum(
            SubSystemSource,
            native_enum=False,
            values_callable=lambda obj: [e.value for e in obj],
            name="subsystemsource",
        ),
        nullable=False,
        default=SubSystemSource.MANUAL,
        server_default=SubSystemSource.MANUAL.value,
    )
    #: Repository path that declared this subsystem, when it came from a scan.
    source_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_subsystem_provenance.py -v`
Expected: 2 passed

- [ ] **Step 5: Create the migration**

Create `backend/app/db/migrations/versions/20260803_1400_subsystemsource_add_subsystem_provenance.py`:

```python
"""subsystem provenance — source and source_path

Revision ID: subsystemsource
Revises: tenantsecrets
Create Date: 2026-08-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'subsystemsource'
down_revision: Union[str, None] = 'tenantsecrets'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows backfill to 'manual', including any a past scan created.
    # That errs quiet rather than noisy: those rows will not be reported as
    # drift until a scan re-stamps them, which apply() does on update as well
    # as on insert.
    op.add_column(
        "subsystem",
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="manual"),
    )
    op.add_column(
        "subsystem",
        sa.Column("source_path", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subsystem", "source_path")
    op.drop_column("subsystem", "source")
```

- [ ] **Step 6: Verify the migration matches the models**

The repo has a guard that builds a PostgreSQL database from the migration chain and diffs it against `Base.metadata`. It needs a reachable PostgreSQL server and skips without one.

Run: `cd backend && uv run pytest tests/test_migration_schema_drift.py -v`
Expected: PASS (or SKIPPED if no PostgreSQL — in that case start it with `docker-compose up -d` and re-run; do not proceed on a skip)

- [ ] **Step 7: Run the full suite on both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models/system.py \
        backend/app/db/migrations/versions/20260803_1400_subsystemsource_add_subsystem_provenance.py \
        backend/tests/services/test_subsystem_provenance.py
git commit -m "feat(subsystem): record where a subsystem came from

A drift report cannot tell a resource deleted from the code apart from one
a person added by hand without this, so every hand-made subsystem would be
reported as drift forever."
```

---

### Task 2: The DeclaredState value objects

The value that both `apply()` and `diff()` will read. Pure data, no database, no app imports.

**Files:**
- Create: `backend/app/services/scanning/declared.py`
- Test: `backend/tests/services/test_declared_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DeclaredSubsystem(name, component_type, technology, source_path)` (frozen); `DeclaredEdge(from_name, to_name, port, source_path)` (frozen); `DeclaredState(subsystems, edges, warnings)` supporting `+`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_declared_state.py`:

```python
"""The value a detector parses into.

The scanner accumulates one of these per detector across every file that
detector claimed, so addition has to be total: losing warnings when two files
merge would silently drop a parser's complaint about a malformed block.
"""
from app.services.scanning.declared import (
    DeclaredEdge, DeclaredState, DeclaredSubsystem,
)


def test_states_add_by_concatenating_every_field():
    a = DeclaredState(
        subsystems=[DeclaredSubsystem("api", "web_service", "nginx", "compose.yml")],
        edges=[DeclaredEdge("api", "db", 5432, "compose.yml")],
        warnings=["first"],
    )
    b = DeclaredState(
        subsystems=[DeclaredSubsystem("db", "database", "postgres", "other.yml")],
        edges=[],
        warnings=["second"],
    )

    total = a + b

    assert [s.name for s in total.subsystems] == ["api", "db"]
    assert [(e.from_name, e.to_name) for e in total.edges] == [("api", "db")]
    assert total.warnings == ["first", "second"]


def test_addition_does_not_mutate_either_operand():
    a = DeclaredState(subsystems=[DeclaredSubsystem("api", "web_service", None, "a.yml")])
    b = DeclaredState(subsystems=[DeclaredSubsystem("db", "database", None, "b.yml")])

    a + b

    assert len(a.subsystems) == 1
    assert len(b.subsystems) == 1


def test_an_empty_state_has_empty_collections_not_none():
    """Callers iterate these without checking; None would blow up mid-scan."""
    empty = DeclaredState()
    assert empty.subsystems == [] and empty.edges == [] and empty.warnings == []


def test_declared_entries_are_hashable_so_they_can_be_deduplicated():
    one = DeclaredSubsystem("api", "web_service", "nginx", "compose.yml")
    same = DeclaredSubsystem("api", "web_service", "nginx", "compose.yml")
    assert len({one, same}) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_declared_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.scanning.declared'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/scanning/declared.py`:

```python
"""What a repository declares, expressed as a value.

Detectors parse into these. `reconcile.apply` writes them and `reconcile.diff`
compares them against the catalogue — both reading the same value, which is
what stops a drift report describing a change a scan would not make.

Nothing here touches the database. That is the point: it is what makes the
parsers testable without one.

Values are canonical as emitted. Parsers truncate `name` to 200, `technology`
to 100 and `source_path` to 500 characters, matching the column widths, so
that a stored row compares equal to the declaration it came from. Truncating
in `apply()` instead would make `diff()` report a change on every run.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeclaredSubsystem:
    name: str
    component_type: str
    technology: str | None
    source_path: str


@dataclass(frozen=True)
class DeclaredEdge:
    from_name: str
    to_name: str
    port: int | None
    source_path: str


@dataclass
class DeclaredState:
    subsystems: list[DeclaredSubsystem] = field(default_factory=list)
    edges: list[DeclaredEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __add__(self, other: "DeclaredState") -> "DeclaredState":
        return DeclaredState(
            subsystems=[*self.subsystems, *other.subsystems],
            edges=[*self.edges, *other.edges],
            warnings=[*self.warnings, *other.warnings],
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_declared_state.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scanning/declared.py backend/tests/services/test_declared_state.py
git commit -m "feat(scanning): add DeclaredState, the value detectors parse into"
```

---

### Task 3: Split the compose importer into parse and apply-able parts

`import_docker_compose` currently parses and persists in one pass. Extract the parsing into a pure function returning `DeclaredState`. The writing half moves in Task 5; for now the existing writer is kept intact and simply consumes the parser, so behaviour and the existing tests are unchanged.

**Files:**
- Modify: `backend/app/services/docker_compose_import_service.py`
- Test: `backend/tests/services/test_compose_parser.py`

**Interfaces:**
- Consumes: `DeclaredState`, `DeclaredSubsystem`, `DeclaredEdge` from Task 2.
- Produces: `parse_docker_compose(content: bytes, path: str) -> DeclaredState`. `import_docker_compose(system_id, tenant_id, content, db)` keeps its signature and dict return shape.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_compose_parser.py`:

```python
"""Parsing a compose file is now a pure function — no database at all.

That is the whole point of the split: the drift report needs the declared
services as a value it can compare, and a parser that writes as it goes never
produces one.
"""
import pytest

from app.services.docker_compose_import_service import parse_docker_compose

COMPOSE = b"""
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


def test_services_become_declared_subsystems():
    declared = parse_docker_compose(COMPOSE, "docker-compose.yml")

    by_name = {s.name: s for s in declared.subsystems}
    assert set(by_name) == {"api", "db"}
    assert by_name["db"].component_type == "database"
    assert by_name["db"].technology == "postgres"
    assert by_name["api"].component_type == "api_gateway"


def test_every_declaration_records_the_path_that_declared_it():
    declared = parse_docker_compose(COMPOSE, "deploy/docker-compose.yml")
    assert {s.source_path for s in declared.subsystems} == {"deploy/docker-compose.yml"}


def test_depends_on_becomes_an_edge_carrying_the_published_port():
    declared = parse_docker_compose(COMPOSE, "docker-compose.yml")

    assert len(declared.edges) == 1
    edge = declared.edges[0]
    assert (edge.from_name, edge.to_name) == ("api", "db")
    assert edge.port == 80


def test_depends_on_accepts_the_long_form_with_conditions():
    content = b"""
services:
  api:
    image: nginx
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres
"""
    declared = parse_docker_compose(content, "docker-compose.yml")
    assert [(e.from_name, e.to_name) for e in declared.edges] == [("api", "db")]


def test_a_long_service_name_is_truncated_to_the_column_width():
    """PostgreSQL raises on an over-length value where SQLite silently stores
    it. Truncating here rather than in apply() also keeps a stored row equal to
    the declaration it came from, so diff() does not report a phantom change."""
    long_name = "x" * 250
    content = f"services:\n  {long_name}:\n    image: nginx\n".encode()
    declared = parse_docker_compose(content, "docker-compose.yml")
    assert len(declared.subsystems[0].name) == 200


def test_invalid_yaml_raises_value_error():
    with pytest.raises(ValueError, match="Invalid YAML"):
        parse_docker_compose(b"services: [unclosed", "docker-compose.yml")


def test_a_file_with_no_services_raises_value_error():
    with pytest.raises(ValueError, match="No services"):
        parse_docker_compose(b"version: '3'\n", "docker-compose.yml")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_compose_parser.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_docker_compose'`

- [ ] **Step 3: Extract the parser**

In `backend/app/services/docker_compose_import_service.py`, add this import at the top:

```python
from app.services.scanning.declared import DeclaredEdge, DeclaredState, DeclaredSubsystem
```

Then add the pure parser directly after `infer_component_type`:

```python
def parse_docker_compose(content: bytes, path: str) -> DeclaredState:
    """Read a compose file into the services and edges it declares.

    Pure: no database, no ids. Values are truncated to their column widths here
    so a stored row compares equal to the declaration it came from.
    """
    try:
        compose = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}")

    if not isinstance(compose, dict):
        raise ValueError(
            "Invalid docker-compose file: expected a YAML mapping at the top level"
        )

    services: dict[str, Any] = compose.get('services', {})
    if not isinstance(services, dict) or not services:
        raise ValueError("No services found in docker-compose file")

    declared = DeclaredState()
    for service_name, service_config in services.items():
        if not isinstance(service_name, str):
            continue
        service_config = service_config or {}
        image = service_config.get('image')
        technology = image.split(':')[0][:100] if image else None
        declared.subsystems.append(DeclaredSubsystem(
            name=service_name[:200],
            component_type=infer_component_type(image),
            technology=technology,
            source_path=path[:500],
        ))

    for service_name, service_config in services.items():
        if not isinstance(service_name, str):
            continue
        service_config = service_config or {}
        depends_on = service_config.get('depends_on', {})
        # depends_on is either a list of names or a mapping of name -> condition.
        if isinstance(depends_on, list):
            dep_names = depends_on
        elif isinstance(depends_on, dict):
            dep_names = list(depends_on.keys())
        else:
            dep_names = []

        ports = service_config.get('ports', [])
        port = None
        if ports:
            # ports are "host:container" strings or bare integers.
            try:
                port = int(str(ports[0]).split(':')[-1])
            except (ValueError, IndexError):
                port = None

        for dep_name in dep_names:
            if not isinstance(dep_name, str):
                continue
            declared.edges.append(DeclaredEdge(
                from_name=service_name[:200],
                to_name=dep_name[:200],
                port=port,
                source_path=path[:500],
            ))

    return declared
```

- [ ] **Step 4: Rewrite the writer to consume the parser**

Replace the body of `import_docker_compose` in the same file with:

```python
async def import_docker_compose(
    system_id: int,
    tenant_id: int,
    content: bytes,
    db: AsyncSession,
    path: str = "docker-compose.yml",
) -> dict[str, int]:
    """Parse a compose file and write what it declares.

    Kept for the direct-upload endpoint in api/v1/import_routes.py. The scan
    path does not use this — it parses once per file, accumulates, and applies
    the total, so two compose files no longer wipe each other's edges.
    """
    from app.db.models.system import SubSystemSource
    from app.services.scanning import reconcile

    declared = parse_docker_compose(content, path)
    result = await reconcile.apply(
        db,
        system_id=system_id,
        tenant_id=tenant_id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE,
        declared=declared,
    )
    return {
        'subsystems_created': result.subsystems_created,
        'subsystems_updated': result.subsystems_updated,
        'dependencies_created': result.dependencies_written,
    }
```

The import of `reconcile` is function-local on purpose: `reconcile` imports nothing from this module, but keeping it local avoids a cycle if that ever changes.

The module's top-level imports of `ComponentDependency`, `DependencyDirection`, `DependencyType`, `select`, `delete` and `SubSystem` are now unused — delete them. Keep `DependencySource`, which the wrapper above still passes.

**This step will not pass until Task 5 creates `reconcile.apply`.** Run only the parser test now; the writer is verified in Task 5 Step 6.

- [ ] **Step 5: Run the parser test to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_compose_parser.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/docker_compose_import_service.py \
        backend/tests/services/test_compose_parser.py
git commit -m "refactor(compose): extract a pure parser from the importer

A parser that writes as it goes never produces the declared value a drift
report has to compare against."
```

---

### Task 4: Split the two Terraform importers the same way

Both `.tf` (HCL) and `.tfstate` become pure parsers with thin writing wrappers. The `.tfstate` path gains provenance as a side effect.

**Files:**
- Modify: `backend/app/services/terraform_hcl_import_service.py`
- Modify: `backend/app/services/terraform_import_service.py`
- Test: `backend/tests/services/test_terraform_parsers.py`

**Interfaces:**
- Consumes: `DeclaredState`, `DeclaredSubsystem` from Task 2.
- Produces: `parse_terraform_hcl(content: bytes, path: str) -> DeclaredState`; `parse_tfstate(content: bytes, path: str) -> DeclaredState`. Both existing `import_*` functions keep their signatures and dict return shapes.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_terraform_parsers.py`:

```python
"""Both Terraform parsers, as pure functions.

.tf declares resources with no computed values and no resource ids; .tfstate
records what was actually built. The two never produce identical rows, which
is why they carry different provenance and are never compared against each
other.
"""
import json

import pytest

from app.services.terraform_hcl_import_service import parse_terraform_hcl
from app.services.terraform_import_service import parse_tfstate

HCL = b"""
resource "aws_db_instance" "main" {
  allocated_storage = 20
}

resource "aws_lambda_function" "worker" {
  runtime = "python3.12"
}

variable "region" {
  default = "eu-west-2"
}
"""


def test_resource_blocks_become_declared_subsystems_addressed_as_terraform_does():
    declared = parse_terraform_hcl(HCL, "infra/main.tf")

    by_name = {s.name: s for s in declared.subsystems}
    assert set(by_name) == {"aws_db_instance.main", "aws_lambda_function.worker"}
    assert by_name["aws_db_instance.main"].component_type == "database"
    assert by_name["aws_lambda_function.worker"].component_type == "worker"


def test_non_resource_blocks_are_not_inventoried():
    """variable, output, provider and locals are not infrastructure."""
    declared = parse_terraform_hcl(HCL, "infra/main.tf")
    assert not any("region" in s.name for s in declared.subsystems)


def test_hcl_declares_no_edges():
    """HCL dependency wiring is implicit in interpolations, which this does not
    read. Declaring zero edges is honest; guessing would not be."""
    assert parse_terraform_hcl(HCL, "infra/main.tf").edges == []


def test_the_declaring_path_is_recorded():
    declared = parse_terraform_hcl(HCL, "infra/modules/db/main.tf")
    assert {s.source_path for s in declared.subsystems} == {"infra/modules/db/main.tf"}


def test_a_resource_block_missing_its_name_label_is_warned_about_not_invented():
    """Without the guard the resource's own attributes parse as names, so one
    bogus subsystem per attribute is created while the scan reports success."""
    content = b'resource "aws_db_instance" {\n  allocated_storage = 20\n}\n'
    declared = parse_terraform_hcl(content, "main.tf")
    assert declared.subsystems == []
    assert any("name label" in w for w in declared.warnings)


def test_an_empty_file_declares_nothing_rather_than_raising():
    assert parse_terraform_hcl(b"   \n", "empty.tf").subsystems == []


def test_invalid_hcl_raises_value_error():
    with pytest.raises(ValueError, match="Invalid Terraform HCL"):
        parse_terraform_hcl(b'resource "x" {{{ unclosed', "main.tf")


def test_tfstate_managed_resources_become_declared_subsystems():
    state = json.dumps({
        "resources": [
            {"mode": "managed", "type": "aws_db_instance", "name": "main"},
            {"mode": "data", "type": "aws_ami", "name": "ubuntu"},
        ]
    }).encode()

    declared = parse_tfstate(state, "terraform.tfstate")

    assert [s.name for s in declared.subsystems] == ["aws_db_instance.main"]


def test_tfstate_data_sources_are_skipped():
    """A data source is something Terraform reads, not something it manages."""
    state = json.dumps({
        "resources": [{"mode": "data", "type": "aws_ami", "name": "ubuntu"}]
    }).encode()
    assert parse_tfstate(state, "terraform.tfstate").subsystems == []


def test_invalid_tfstate_json_raises_value_error():
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_tfstate(b"{not json", "terraform.tfstate")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_terraform_parsers.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_terraform_hcl'`

- [ ] **Step 3: Extract the HCL parser**

Replace the body of `backend/app/services/terraform_hcl_import_service.py` below its imports with:

```python
import io

import hcl2
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.scanning.declared import DeclaredState, DeclaredSubsystem
from app.services.terraform_import_service import infer_component_type


def parse_terraform_hcl(content: bytes, path: str) -> DeclaredState:
    """Read .tf source into the resources it declares. Pure — no database."""
    declared = DeclaredState()
    if not content.strip():
        return declared

    try:
        parsed = hcl2.load(io.StringIO(content.decode("utf-8")))
    except Exception as exc:  # hcl2 raises a variety of parser errors
        raise ValueError(f"Invalid Terraform HCL: {exc}") from exc

    # Only `resource` blocks are infrastructure to inventory. hcl2.load returns
    # parsed["resource"] as a list of single-key dicts:
    # {resource_type: {resource_name: {...body}}}.
    for block in parsed.get("resource", []) or []:
        if not isinstance(block, dict):
            declared.warnings.append("skipped a resource block that was not a mapping")
            continue
        for resource_type, bodies in block.items():
            if not isinstance(bodies, dict):
                declared.warnings.append(
                    f"skipped malformed resource block {resource_type!r}"
                )
                continue
            for name, body in bodies.items():
                # A real resource's value is its BODY — a dict. A `resource`
                # block missing its name label parses so that the resource's own
                # attributes sit here instead, and taking these keys as names
                # fabricates one bogus subsystem per attribute while reporting
                # success.
                if not isinstance(body, dict):
                    declared.warnings.append(
                        f"skipped {resource_type!r}: block appears to be missing "
                        "its name label"
                    )
                    continue
                declared.subsystems.append(DeclaredSubsystem(
                    name=f"{resource_type}.{name}"[:200],
                    component_type=infer_component_type(resource_type),
                    technology=resource_type[:100],
                    source_path=path[:500],
                ))

    return declared


async def import_terraform_hcl(
    system_id: int, tenant_id: int, content: bytes, db: AsyncSession,
    path: str = "main.tf",
) -> dict:
    """Parse .tf source and write what it declares."""
    from app.db.models.system import SubSystemSource
    from app.services.scanning import reconcile

    declared = parse_terraform_hcl(content, path)
    result = await reconcile.apply(
        db, system_id=system_id, tenant_id=tenant_id,
        source=SubSystemSource.TERRAFORM_HCL,
        # HCL declares no edges, so nothing may be deleted on its behalf.
        edge_source=None,
        declared=declared,
    )
    return {
        "subsystems_created": result.subsystems_created,
        "subsystems_updated": result.subsystems_updated,
        "warnings": declared.warnings,
    }
```

Keep the module docstring at the top of the file as it is.

- [ ] **Step 4: Extract the tfstate parser**

In `backend/app/services/terraform_import_service.py`, add to the imports:

```python
from app.services.scanning.declared import DeclaredState, DeclaredSubsystem
```

Then replace `import_terraform` with these two functions (leave `TF_TYPE_MAP` and `infer_component_type` exactly as they are):

```python
def parse_tfstate(content: bytes, path: str) -> DeclaredState:
    """Read a .tfstate JSON file into the resources it records. Pure.

    Dependencies are not produced: tfstate carries no explicit dependency graph.
    """
    try:
        state = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    resources = state.get('resources', [])
    if not isinstance(resources, list):
        raise ValueError("Invalid tfstate format: 'resources' must be a list")

    declared = DeclaredState()
    for resource in resources:
        if not isinstance(resource, dict) or resource.get('mode') != 'managed':
            # mode='data' is something Terraform reads, not something it manages.
            continue
        resource_type = resource.get('type', '')
        resource_name = resource.get('name', '')
        if not isinstance(resource_type, str) or not isinstance(resource_name, str):
            continue
        if not resource_type or not resource_name:
            continue
        declared.subsystems.append(DeclaredSubsystem(
            name=f"{resource_type}.{resource_name}"[:200],
            component_type=infer_component_type(resource_type),
            technology=resource_type[:100],
            source_path=path[:500],
        ))
    return declared


async def import_terraform(
    system_id: int,
    tenant_id: int,
    content: bytes,
    db: AsyncSession,
    path: str = "terraform.tfstate",
) -> dict[str, int]:
    """Parse a .tfstate file and write what it records."""
    from app.db.models.system import SubSystemSource
    from app.services.scanning import reconcile

    declared = parse_tfstate(content, path)
    result = await reconcile.apply(
        db, system_id=system_id, tenant_id=tenant_id,
        source=SubSystemSource.TERRAFORM,
        edge_source=None,
        declared=declared,
    )
    return {
        'subsystems_created': result.subsystems_created,
        'subsystems_updated': result.subsystems_updated,
    }
```

The `select` and `SubSystem` imports in this file are now unused — delete them.

- [ ] **Step 5: Run the parser test to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_terraform_parsers.py -v`
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/terraform_hcl_import_service.py \
        backend/app/services/terraform_import_service.py \
        backend/tests/services/test_terraform_parsers.py
git commit -m "refactor(terraform): extract pure parsers from both importers

.tfstate gains provenance as a side effect: it now writes through the same
apply() as every other source."
```

---

### Task 5: reconcile.apply — the writing half

One function that turns a `DeclaredState` into rows. Every importer now routes through it, so provenance stamping and edge handling exist in exactly one place.

**Files:**
- Create: `backend/app/services/scanning/reconcile.py`
- Test: `backend/tests/services/test_reconcile_apply.py`

**Interfaces:**
- Consumes: `DeclaredState` (Task 2), `SubSystemSource` (Task 1).
- Produces: `ApplyResult(subsystems_created: int, subsystems_updated: int, dependencies_written: int)`; `async apply(db, *, system_id, tenant_id, source, edge_source, declared) -> ApplyResult`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_reconcile_apply.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_reconcile_apply.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.scanning.reconcile'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/scanning/reconcile.py`:

```python
"""Write or compare a DeclaredState against the subsystem catalogue.

Both consumers read the same declared value, which is what stops the drift
report describing a change a scan would not make. `diff` is added in Task 6.
"""
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dependency import (
    ComponentDependency,
    DependencyDirection,
    DependencySource,
    DependencyType,
)
from app.db.models.system import SubSystem, SubSystemSource
from app.services.scanning.declared import DeclaredState


@dataclass
class ApplyResult:
    subsystems_created: int = 0
    subsystems_updated: int = 0
    dependencies_written: int = 0


async def catalogue(
    db: AsyncSession, *, system_id: int, tenant_id: int
) -> dict[str, SubSystem]:
    """Every live subsystem of this system, keyed by name.

    Name is the match key both halves use — the same key the importers have
    always upserted on, so the writer and the differ cannot disagree about
    identity.
    """
    rows = (await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )).scalars().all()
    return {row.name: row for row in rows}


async def apply(
    db: AsyncSession,
    *,
    system_id: int,
    tenant_id: int,
    source: SubSystemSource,
    edge_source: DependencySource | None,
    declared: DeclaredState,
) -> ApplyResult:
    """Write what `declared` says into the catalogue.

    Never deletes a subsystem: a resource removed from the code stays in the
    catalogue, which is precisely the drift the report exists to surface.

    `edge_source=None` means this source declares no dependency edges, and so
    none may be deleted on its behalf — otherwise scanning a .tf file would
    wipe every compose edge in the system.
    """
    existing = await catalogue(db, system_id=system_id, tenant_id=tenant_id)
    result = ApplyResult()
    declared_ids: dict[str, int] = {}

    for sub in declared.subsystems:
        row = existing.get(sub.name)
        if row is None:
            row = SubSystem(
                tenant_id=tenant_id,
                system_id=system_id,
                name=sub.name,
                component_type=sub.component_type,
                technology=sub.technology,
                source=source,
                source_path=sub.source_path,
            )
            db.add(row)
            await db.flush()  # assign the id the edges below need
            existing[sub.name] = row
            result.subsystems_created += 1
        else:
            row.component_type = sub.component_type
            row.technology = sub.technology
            # Stamped on update as well as insert, so rows that predate the
            # source column stop reading as hand-made once a scan matches them.
            row.source = source
            row.source_path = sub.source_path
            result.subsystems_updated += 1
        declared_ids[sub.name] = row.id

    if edge_source is None:
        await db.flush()
        return result

    all_ids = [row.id for row in existing.values()]
    if all_ids:
        # Delete-then-recreate: an edge dropped from the code disappears from
        # the catalogue, unlike a subsystem. The compose importer has always
        # behaved this way.
        await db.execute(
            delete(ComponentDependency).where(
                ComponentDependency.tenant_id == tenant_id,
                ComponentDependency.from_subsystem_id.in_(all_ids),
                ComponentDependency.source == edge_source,
            )
        )

    written: set[tuple[int, int]] = set()
    for edge in declared.edges:
        from_id = declared_ids.get(edge.from_name)
        to_id = declared_ids.get(edge.to_name)
        # An endpoint this declaration does not define cannot be written.
        # diff() skips the same edges, or the round-trip guarantee breaks.
        if from_id is None or to_id is None or from_id == to_id:
            continue
        if (from_id, to_id) in written:
            # uq_component_dep is (from, to, tenant): a repeat would raise
            # IntegrityError and cost this detector its whole savepoint.
            continue
        written.add((from_id, to_id))
        db.add(ComponentDependency(
            tenant_id=tenant_id,
            from_subsystem_id=from_id,
            to_subsystem_id=to_id,
            dependency_type=DependencyType.API_CALL,
            direction=DependencyDirection.ONE_WAY,
            source=edge_source,
            port=edge.port,
        ))
        result.dependencies_written += 1

    await db.flush()
    return result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_reconcile_apply.py -v`
Expected: 8 passed

- [ ] **Step 5: Mutate to confirm the tests discriminate**

Comment out the two provenance-stamping lines in the update branch (`row.source = source` and `row.source_path = sub.source_path`).

Run: `cd backend && uv run pytest tests/services/test_reconcile_apply.py -v`
Expected: FAIL on `test_applying_stamps_provenance_on_rows_it_merely_updates`

Restore the lines and confirm green again.

- [ ] **Step 6: Verify the existing importer tests still pass**

These exercise the wrappers written in Tasks 3 and 4 and are the refactor's safety net.

Run: `cd backend && uv run pytest tests/services/test_terraform_hcl_import_service.py tests/integration/test_repository_scan_api.py -v`
Expected: PASS

If `test_repository_scan_api.py` fails here it is because the detectors have not been rewired yet — that is Task 7. Note the failure and continue; do not weaken the test.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scanning/reconcile.py \
        backend/tests/services/test_reconcile_apply.py
git commit -m "feat(scanning): add reconcile.apply, the single writer

Every importer routes through it, so provenance stamping and edge handling
live in exactly one place."
```

---

### Task 6: reconcile.diff — the comparing half

**Files:**
- Modify: `backend/app/services/scanning/reconcile.py`
- Test: `backend/tests/services/test_reconcile_diff.py`

**Interfaces:**
- Consumes: `catalogue()`, `DeclaredState`, `SubSystemSource`, `DependencySource`.
- Produces: `ChangedSubsystem(name, field, catalogue, declared, source_path)`; `EdgeRef(from_name, to_name, port)`; `ChangedEdge(from_name, to_name, catalogue_port, declared_port, source_path)`; `DriftReport` with fields `subsystems_missing_in_catalogue: list[DeclaredSubsystem]`, `subsystems_missing_in_code: list[str] | None`, `subsystems_changed: list[ChangedSubsystem]`, `edges_missing_in_catalogue: list[DeclaredEdge]`, `edges_missing_in_code: list[EdgeRef] | None`, `edges_changed: list[ChangedEdge]`, `absence_computed: bool`, `absence_reason: str | None`, `warnings: list[str]`, and a property `has_drift: bool`; `async diff(db, *, system_id, tenant_id, source, edge_source, declared, absence_computed, absence_reason) -> DriftReport`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_reconcile_diff.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_reconcile_diff.py -v`
Expected: FAIL — `AttributeError: module 'app.services.scanning.reconcile' has no attribute 'diff'`

- [ ] **Step 3: Write the implementation**

Append to `backend/app/services/scanning/reconcile.py`:

```python
@dataclass(frozen=True)
class ChangedSubsystem:
    name: str
    field: str  # "component_type" | "technology"
    catalogue: str | None
    declared: str | None
    source_path: str


@dataclass(frozen=True)
class EdgeRef:
    from_name: str
    to_name: str
    port: int | None


@dataclass(frozen=True)
class ChangedEdge:
    from_name: str
    to_name: str
    catalogue_port: int | None
    declared_port: int | None
    source_path: str


@dataclass
class DriftReport:
    subsystems_missing_in_catalogue: list[DeclaredSubsystem]
    subsystems_missing_in_code: list[str] | None
    subsystems_changed: list[ChangedSubsystem]
    edges_missing_in_catalogue: list[DeclaredEdge]
    edges_missing_in_code: list[EdgeRef] | None
    edges_changed: list[ChangedEdge]
    absence_computed: bool
    absence_reason: str | None
    warnings: list[str]

    @property
    def has_drift(self) -> bool:
        return bool(
            self.subsystems_missing_in_catalogue
            or self.subsystems_missing_in_code
            or self.subsystems_changed
            or self.edges_missing_in_catalogue
            or self.edges_missing_in_code
            or self.edges_changed
        )


def _column_value(value) -> str | None:
    """Enum columns come back as the enum on one path and the raw string on
    another depending on how the row was loaded."""
    return getattr(value, "value", value)


async def diff(
    db: AsyncSession,
    *,
    system_id: int,
    tenant_id: int,
    source: SubSystemSource,
    edge_source: DependencySource | None,
    declared: DeclaredState,
    absence_computed: bool,
    absence_reason: str | None,
) -> DriftReport:
    """Compare `declared` against the catalogue. Writes nothing.

    `absence_computed=False` means the repository was read only in part, so
    files never read cannot be told apart from deleted ones. The absence
    categories are then left as None rather than computed wrong.
    """
    existing = await catalogue(db, system_id=system_id, tenant_id=tenant_id)
    warnings = list(declared.warnings)

    declared_by_name: dict[str, DeclaredSubsystem] = {}
    for sub in declared.subsystems:
        previous = declared_by_name.get(sub.name)
        if previous is not None and previous.source_path != sub.source_path:
            warnings.append(
                f"{sub.name!r} is declared in both {previous.source_path} and "
                f"{sub.source_path}; only the last is kept"
            )
        declared_by_name[sub.name] = sub

    missing_in_catalogue = [
        sub for name, sub in declared_by_name.items() if name not in existing
    ]

    changed: list[ChangedSubsystem] = []
    for name, sub in declared_by_name.items():
        row = existing.get(name)
        if row is None:
            continue
        row_type = _column_value(row.component_type)
        if row_type != sub.component_type:
            changed.append(ChangedSubsystem(
                name=name, field="component_type", catalogue=row_type,
                declared=sub.component_type, source_path=sub.source_path,
            ))
        if (row.technology or None) != (sub.technology or None):
            changed.append(ChangedSubsystem(
                name=name, field="technology", catalogue=row.technology,
                declared=sub.technology, source_path=sub.source_path,
            ))

    missing_in_code: list[str] | None = None
    if absence_computed:
        missing_in_code = sorted(
            name for name, row in existing.items()
            if _column_value(row.source) == source.value and name not in declared_by_name
        )

    edges_missing_in_catalogue: list[DeclaredEdge] = []
    edges_changed: list[ChangedEdge] = []
    edges_missing_in_code: list[EdgeRef] | None = None

    if edge_source is not None:
        name_by_id = {row.id: name for name, row in existing.items()}
        rows = []
        if name_by_id:
            rows = (await db.execute(
                select(ComponentDependency).where(
                    ComponentDependency.tenant_id == tenant_id,
                    ComponentDependency.source == edge_source,
                    ComponentDependency.from_subsystem_id.in_(list(name_by_id)),
                    ComponentDependency.to_subsystem_id.in_(list(name_by_id)),
                )
            )).scalars().all()
        catalogue_edges = {
            (name_by_id[row.from_subsystem_id], name_by_id[row.to_subsystem_id]): row
            for row in rows
        }

        declared_edges: dict[tuple[str, str], DeclaredEdge] = {}
        for edge in declared.edges:
            # Exactly the edges apply() would skip. Reporting one it cannot
            # write would leave the round-trip permanently non-zero.
            if edge.from_name == edge.to_name:
                continue
            if edge.from_name not in declared_by_name or edge.to_name not in declared_by_name:
                continue
            declared_edges[(edge.from_name, edge.to_name)] = edge

        for key, edge in declared_edges.items():
            row = catalogue_edges.get(key)
            if row is None:
                edges_missing_in_catalogue.append(edge)
            elif row.port != edge.port:
                edges_changed.append(ChangedEdge(
                    from_name=key[0], to_name=key[1], catalogue_port=row.port,
                    declared_port=edge.port, source_path=edge.source_path,
                ))

        if absence_computed:
            edges_missing_in_code = sorted(
                (
                    EdgeRef(from_name=key[0], to_name=key[1], port=row.port)
                    for key, row in catalogue_edges.items()
                    if key not in declared_edges
                ),
                key=lambda ref: (ref.from_name, ref.to_name),
            )

    return DriftReport(
        subsystems_missing_in_catalogue=missing_in_catalogue,
        subsystems_missing_in_code=missing_in_code,
        subsystems_changed=changed,
        edges_missing_in_catalogue=edges_missing_in_catalogue,
        edges_missing_in_code=edges_missing_in_code,
        edges_changed=edges_changed,
        absence_computed=absence_computed,
        absence_reason=absence_reason,
        warnings=warnings,
    )
```

Add `DeclaredEdge` and `DeclaredSubsystem` to the existing `declared` import at the top of the file:

```python
from app.services.scanning.declared import DeclaredEdge, DeclaredState, DeclaredSubsystem
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_reconcile_diff.py -v`
Expected: 13 passed

- [ ] **Step 5: Mutate to confirm the absence tests discriminate**

Change the `missing_in_code` guard from `if absence_computed:` to `if True:`.

Run: `cd backend && uv run pytest tests/services/test_reconcile_diff.py -v`
Expected: FAIL on `test_absence_is_null_not_empty_when_it_could_not_be_computed`

Then change the source filter from `== source.value` to `!= SubSystemSource.MANUAL.value`.

Expected: `test_a_row_from_a_different_source_is_not_reported_as_missing` FAILS

Restore both and confirm green.

- [ ] **Step 6: Run both engines**

Run: `cd backend && uv run pytest tests/services/test_reconcile_diff.py tests/services/test_reconcile_apply.py -q`
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/services/test_reconcile_diff.py tests/services/test_reconcile_apply.py -q`
Expected: PASS on both

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scanning/reconcile.py \
        backend/tests/services/test_reconcile_diff.py
git commit -m "feat(scanning): add reconcile.diff, the drift comparison

Absence is left uncomputed rather than computed wrong when the repository was
read only in part."
```

---

### Task 7: The round-trip guarantee

The load-bearing test of the whole feature. It fails the moment the writer and the differ disagree about identity, type inference or edge handling — the failure mode that would make drift detection actively misleading rather than merely incomplete.

**Files:**
- Test: `backend/tests/services/test_reconcile_roundtrip.py`

**Interfaces:**
- Consumes: `reconcile.apply`, `reconcile.diff`, both parsers.
- Produces: nothing — a guarantee, not an API.

- [ ] **Step 1: Write the test**

Create `backend/tests/services/test_reconcile_roundtrip.py`:

```python
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
```

- [ ] **Step 2: Run the tests**

Run: `cd backend && uv run pytest tests/services/test_reconcile_roundtrip.py -v`
Expected: 5 passed. If any round-trip test fails, the assertion message names the disagreeing category — fix `apply`/`diff` until they agree. Do not relax the assertion.

- [ ] **Step 3: Run on PostgreSQL too**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/services/test_reconcile_roundtrip.py -v`
Expected: 5 passed

- [ ] **Step 4: Mutate to confirm the guarantee is real**

In `reconcile.diff`, delete the line that skips edges with undeclared endpoints (`if edge.from_name not in declared_by_name or edge.to_name not in declared_by_name: continue`).

Run: `cd backend && uv run pytest tests/services/test_reconcile_roundtrip.py -v`
Expected: FAIL — the compose round-trip now reports an edge `apply()` never wrote

Restore the line and confirm green.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/services/test_reconcile_roundtrip.py
git commit -m "test(scanning): pin apply() and diff() to each other

A report that describes changes a scan would not make is worse than no
report. This fails the moment the two halves disagree."
```

---

### Task 8: Rewire the detectors and the scanner walk

Detectors now declare their sources and return `DeclaredState`. The repository walk is extracted so `scan_repository` and the new `drift_repository` share it rather than duplicating traversal, authentication and rate-limit handling.

**Files:**
- Modify: `backend/app/services/scanning/registry.py`
- Modify: `backend/app/services/scanning/detectors/compose.py`
- Modify: `backend/app/services/scanning/detectors/terraform_hcl.py`
- Modify: `backend/app/services/scanning/scanner.py`
- Test: `backend/tests/services/test_scanning_registry.py` (extend)

**Interfaces:**
- Consumes: `DeclaredState`, `reconcile.apply`, `reconcile.diff`.
- Produces: `Detector(name, matches, parse, subsystem_source, edge_source)`; `ParseContext(content, path, fetch)`; `scanner.drift_repository(db, *, token, system_id, tenant_id, repo_url) -> dict`; `scanner.scan_repository` keeps its signature and response shape.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/services/test_scanning_registry.py`:

```python
def test_every_detector_declares_the_provenance_it_writes():
    """diff() compares catalogue rows to the detector that owns their source.
    A detector without one would silently compare against nothing."""
    from app.db.models.system import SubSystemSource
    from app.services.scanning.detectors import DETECTORS

    for detector in DETECTORS:
        assert isinstance(detector.subsystem_source, SubSystemSource), detector.name


def test_only_detectors_that_declare_edges_may_delete_them():
    """edge_source is what apply() deletes on. A detector that parses no edges
    must pass None, or scanning a .tf file would wipe every compose edge."""
    from app.services.scanning.detectors import DETECTORS

    by_name = {d.name: d for d in DETECTORS}
    assert by_name["docker_compose"].edge_source is not None
    assert by_name["terraform_hcl"].edge_source is None


@pytest.mark.asyncio
async def test_a_detector_parses_without_a_database():
    """The refactor's whole point: parsing is pure, so it needs no session."""
    from app.services.scanning.registry import ParseContext

    async def _never_called(path):
        raise AssertionError("fetch should not be needed here")

    declared = await DOCKER_COMPOSE.parse(ParseContext(
        content=b"services:\n  api:\n    image: nginx\n",
        path="docker-compose.yml",
        fetch=_never_called,
    ))

    assert [s.name for s in declared.subsystems] == ["api"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_scanning_registry.py -v`
Expected: FAIL — `AttributeError: 'Detector' object has no attribute 'subsystem_source'`

- [ ] **Step 3: Update the registry**

Replace `backend/app/services/scanning/registry.py` below its docstring with:

```python
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from app.db.models.dependency import DependencySource
from app.db.models.system import SubSystemSource
from app.services.scanning.declared import DeclaredState


@dataclass
class DetectorResult:
    subsystems_created: int = 0
    subsystems_updated: int = 0
    dependencies_written: int = 0
    warnings: list[str] = field(default_factory=list)

    def __add__(self, other: "DetectorResult") -> "DetectorResult":
        return DetectorResult(
            subsystems_created=self.subsystems_created + other.subsystems_created,
            subsystems_updated=self.subsystems_updated + other.subsystems_updated,
            dependencies_written=self.dependencies_written + other.dependencies_written,
            warnings=[*self.warnings, *other.warnings],
        )


@dataclass(frozen=True)
class ParseContext:
    content: bytes
    path: str
    #: Fetch another file from the same repository. A Helm or Kustomize
    #: detector needs a companion file (values.yaml, an .env beside a compose
    #: file); without this it would have to own the walk.
    fetch: Callable[[str], Awaitable[Optional[bytes]]]


@dataclass(frozen=True)
class Detector:
    name: str
    matches: Callable[[str], bool]
    #: Pure: parses content into a value, touching no database. That is what
    #: lets one walk serve both the scan and the drift report.
    parse: Callable[[ParseContext], Awaitable[DeclaredState]]
    #: Provenance stamped on subsystems this detector declares, and the source
    #: whose catalogue rows it is compared against.
    subsystem_source: SubSystemSource
    #: The dependency source this detector owns, or None if it declares no
    #: edges. apply() deletes on this, so None means "never delete edges here".
    edge_source: DependencySource | None = None
```

Keep the existing module docstring at the top of the file.

- [ ] **Step 4: Update both detectors**

Replace `backend/app/services/scanning/detectors/compose.py` below its docstring and `_PATTERN` with:

```python
def _matches(path: str) -> bool:
    return _PATTERN.search(path) is not None


async def _parse(ctx: ParseContext) -> DeclaredState:
    return docker_compose_import_service.parse_docker_compose(ctx.content, ctx.path)


DOCKER_COMPOSE = Detector(
    name="docker_compose",
    matches=_matches,
    parse=_parse,
    subsystem_source=SubSystemSource.DOCKER_COMPOSE,
    edge_source=DependencySource.DOCKER_COMPOSE,
)
```

with these imports:

```python
import re

from app.db.models.dependency import DependencySource
from app.db.models.system import SubSystemSource
from app.services import docker_compose_import_service
from app.services.scanning.declared import DeclaredState
from app.services.scanning.registry import Detector, ParseContext
```

Replace `backend/app/services/scanning/detectors/terraform_hcl.py` entirely with:

```python
"""Terraform HCL detector."""
from app.db.models.system import SubSystemSource
from app.services import terraform_hcl_import_service
from app.services.scanning.declared import DeclaredState
from app.services.scanning.registry import Detector, ParseContext


def _matches(path: str) -> bool:
    # .tfstate and .tfvars are deliberately excluded: state is not normally
    # committed, and tfvars is configuration rather than resource declarations.
    return path.endswith(".tf")


async def _parse(ctx: ParseContext) -> DeclaredState:
    return terraform_hcl_import_service.parse_terraform_hcl(ctx.content, ctx.path)


TERRAFORM_HCL = Detector(
    name="terraform_hcl",
    matches=_matches,
    parse=_parse,
    subsystem_source=SubSystemSource.TERRAFORM_HCL,
    # HCL wires dependencies through interpolations, which this does not read.
    edge_source=None,
)
```

- [ ] **Step 5: Extract the walk in the scanner**

In `backend/app/services/scanning/scanner.py`, replace the `DetectorReport` dataclass and `scan_repository` with the following, keeping `_REPO_URL`, `_transport`, `get_detectors`, `parse_repo_url`, `_in_flight` and `ScanAlreadyRunning` exactly as they are:

```python
@dataclass
class DetectorWalk:
    detector: Detector
    paths: list[str] = field(default_factory=list)
    declared: DeclaredState = field(default_factory=DeclaredState)
    errors: list[str] = field(default_factory=list)
    #: Paths this detector claimed that the file cap dropped before the fetch
    #: loop reached them. Without this, a detector starved by the cap looks
    #: identical to one that read everything and found nothing: 300 .tf files
    #: ahead of docker-compose.yml in tree order means Compose is never
    #: fetched, yet its report is all zeros with no error.
    paths_unread: int = 0


@dataclass
class WalkResult:
    ref: str
    files_scanned: int
    truncated: bool
    stopped_early: bool
    walks: list[DetectorWalk]


def absence_is_computable(
    walk: DetectorWalk, *, truncated: bool, stopped_early: bool
) -> tuple[bool, Optional[str]]:
    """Whether "in the catalogue but not in the code" can be trusted.

    Positive findings survive a partial read; absence findings do not. A file
    that was never read is indistinguishable from one that was deleted, so
    when any part of this detector's input went unseen the absence categories
    are left uncomputed rather than computed wrong.
    """
    if truncated:
        return False, (
            "GitHub returned only part of this repository's file tree, so files "
            "it never listed cannot be told apart from deleted ones."
        )
    if stopped_early:
        return False, (
            "The scan stopped at its file limit, so files it never read cannot "
            "be told apart from deleted ones."
        )
    if walk.paths_unread:
        return False, (
            f"{walk.paths_unread} matching file(s) were not read, so they cannot "
            "be told apart from deleted ones."
        )
    if walk.errors:
        return False, (
            "Some matching files could not be fetched, so they cannot be told "
            "apart from deleted ones."
        )
    return True, None


async def _walk(client: GitHubClient, owner: str, repo: str) -> WalkResult:
    """Read the repository once and parse everything the detectors claim.

    Touches no database: both the scan and the drift report run this and then
    do their own thing with the result.
    """
    ref = await client.get_default_branch(owner, repo)
    tree = await client.get_tree(owner, repo, ref)

    detectors = get_detectors()
    walks = {d.name: DetectorWalk(detector=d) for d in detectors}

    # A path goes to EVERY detector that claims it — "first match wins" would
    # make behaviour depend on registry order.
    claimed: list[tuple[str, list[Detector]]] = []
    for path in tree.paths:
        wanted = [d for d in detectors if d.matches(path)]
        if wanted:
            claimed.append((path, wanted))

    stopped_early = len(claimed) > settings.MAX_SCAN_FILES
    dropped, claimed = (
        claimed[settings.MAX_SCAN_FILES:],
        claimed[: settings.MAX_SCAN_FILES],
    )
    for _, wanted in dropped:
        for detector in wanted:
            walks[detector.name].paths_unread += 1

    async def fetch(path: str) -> Optional[bytes]:
        try:
            return await client.get_blob(owner, repo, path, ref)
        except Exception:
            return None

    for path, wanted in claimed:
        try:
            content = await client.get_blob(owner, repo, path, ref)
        except (GitHubNotFound, GitHubUnavailable, GitHubUnexpectedResponse) as exc:
            # A transient 5xx, a 404, or a malformed body on ONE file must not
            # abort the whole walk. GitHubAuthError and GitHubRateLimited are
            # deliberately NOT caught: a 401 is dead for every remaining file
            # and must reach the endpoint's cleanup, and a 429 means every
            # subsequent call fails the same way.
            for detector in wanted:
                walks[detector.name].errors.append(f"{path}: {exc}")
            continue
        for detector in wanted:
            walk = walks[detector.name]
            walk.paths.append(path)
            try:
                walk.declared = walk.declared + await detector.parse(
                    ParseContext(content=content, path=path, fetch=fetch)
                )
            except Exception as exc:
                # One detector failing must not take the others with it.
                walk.errors.append(f"{path}: {exc}")

    return WalkResult(
        ref=ref,
        files_scanned=len(claimed),
        truncated=tree.truncated,
        stopped_early=stopped_early,
        walks=list(walks.values()),
    )


async def _with_repository(
    *, token: str, system_id: int, tenant_id: int, repo_url: str
) -> WalkResult:
    """Run the shared walk under the per-system lock, releasing the client.

    Takes no session: the walk reads GitHub and parses, nothing more. The
    database only enters once a caller applies or diffs the result.
    """
    owner, repo = parse_repo_url(repo_url)

    key = (tenant_id, system_id)
    if key in _in_flight:
        raise ScanAlreadyRunning("a scan of this system is already running")
    _in_flight.add(key)
    try:
        client = GitHubClient(token=token, transport=_transport())
        try:
            return await _walk(client, owner, repo)
        finally:
            # GitHubClient holds one pooled httpx client for its lifetime; a
            # walk that raises must still release it, or every failure leaks a
            # connection pool. Never let a close failure replace the exception
            # already propagating — the endpoint dispatches on that type, and
            # losing it means a revoked token is never cleared.
            try:
                await client.aclose()
            except Exception:
                pass
    finally:
        _in_flight.discard(key)


async def scan_repository(
    db: AsyncSession, *, token: str, system_id: int, tenant_id: int, repo_url: str
) -> dict:
    walk_result = await _with_repository(
        token=token, system_id=system_id, tenant_id=tenant_id, repo_url=repo_url
    )

    detectors_out = []
    for walk in walk_result.walks:
        applied = ApplyResult()
        errors = list(walk.errors)
        if walk.declared.subsystems or walk.declared.edges:
            try:
                # Each detector writes inside its own SAVEPOINT. Without it a
                # failed flush marks the whole session for rollback, and the
                # next use raises PendingRollbackError: one detector's failure
                # would erase every other detector's results at commit time.
                async with db.begin_nested():
                    applied = await reconcile.apply(
                        db,
                        system_id=system_id,
                        tenant_id=tenant_id,
                        source=walk.detector.subsystem_source,
                        edge_source=walk.detector.edge_source,
                        declared=walk.declared,
                    )
            except Exception as exc:
                errors.append(str(exc))
        detectors_out.append({
            "detector": walk.detector.name,
            "paths": walk.paths,
            "subsystems_created": applied.subsystems_created,
            "subsystems_updated": applied.subsystems_updated,
            "dependencies_written": applied.dependencies_written,
            "warnings": walk.declared.warnings,
            "errors": errors,
            "paths_unread": walk.paths_unread,
        })

    return {
        "ref": walk_result.ref,
        "files_scanned": walk_result.files_scanned,
        "truncated": walk_result.truncated,
        "stopped_early": walk_result.stopped_early,
        "detectors": detectors_out,
    }
```

Update the imports at the top of `scanner.py`:

```python
from app.services.scanning import reconcile
from app.services.scanning.declared import DeclaredState
from app.services.scanning.reconcile import ApplyResult
from app.services.scanning.registry import Detector, ParseContext
```

(`DetectorResult` is no longer used here; leave it exported from `registry.py`, where `test_scanning_registry.py` still asserts on it.)

- [ ] **Step 6: Run the scanning tests**

Run: `cd backend && uv run pytest tests/services/test_scanning_registry.py tests/integration/test_repository_scan_api.py -v`
Expected: PASS — including the pre-existing tests, which are the safety net for this refactor

- [ ] **Step 7: Run the whole suite on both engines**

Run: `cd backend && uv run pytest -q`
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS on both

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/scanning/registry.py \
        backend/app/services/scanning/detectors/compose.py \
        backend/app/services/scanning/detectors/terraform_hcl.py \
        backend/app/services/scanning/scanner.py \
        backend/tests/services/test_scanning_registry.py
git commit -m "refactor(scanning): one walk, two consumers

Detectors parse into a value and touch no database. The scan applies it; the
drift report will compare it."
```

---

### Task 9: The drift endpoint

**Files:**
- Modify: `backend/app/services/scanning/scanner.py`
- Modify: `backend/app/api/v1/systems.py`
- Test: `backend/tests/integration/test_drift_api.py`

**Interfaces:**
- Consumes: `_with_repository`, `absence_is_computable`, `reconcile.diff`.
- Produces: `scanner.drift_repository(db, *, token, system_id, tenant_id, repo_url) -> dict`; `GET /api/v1/systems/{system_id}/github/drift`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_drift_api.py`:

```python
"""The drift report endpoint. No network: a MockTransport stands in for GitHub."""
import base64

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import secrets as secrets_module
from app.db.models.system import SubSystem, SubSystemSource, System
from app.services import tenant_secret_service

COMPOSE = b"services:\n  api:\n    image: nginx\n  db:\n    image: postgres\n"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(
        secrets_module.settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


@pytest.fixture
async def connected_system(db_session, test_tenant, test_user):
    system = System(
        tenant_id=test_tenant.id, name="Payments",
        github_repository_url="https://github.com/acme/payments",
    )
    db_session.add(system)
    await db_session.flush()
    await tenant_secret_service.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc",
        created_by=test_user.id,
    )
    await db_session.commit()
    return system


def _github(tree, *, truncated=False, blob=COMPOSE):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/git/trees/" in url:
            return httpx.Response(200, json={
                "tree": [{"path": p, "type": "blob"} for p in tree],
                "truncated": truncated,
            })
        if "/contents/" in url:
            return httpx.Response(200, json={
                "content": base64.b64encode(blob).decode(), "encoding": "base64",
            })
        return httpx.Response(200, json={"default_branch": "main"})
    return httpx.MockTransport(handler)


def _compose(body):
    return next(d for d in body["detectors"] if d["detector"] == "docker_compose")


@pytest.mark.asyncio
async def test_an_empty_catalogue_reports_everything_the_code_declares(
    client, auth_headers, connected_system, monkeypatch
):
    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    compose = _compose(resp.json())
    names = {s["name"] for s in compose["subsystems"]["missing_in_catalogue"]}
    assert names == {"api", "db"}
    assert compose["subsystems"]["missing_in_code"] == []


@pytest.mark.asyncio
async def test_the_report_writes_nothing(
    client, auth_headers, connected_system, db_session, monkeypatch
):
    """It is a report. Writing would change the answer it just gave."""
    from sqlalchemy import func, select

    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    # The request ran in its own session; expire ours or the identity map
    # answers from before it and the test passes without proving anything.
    db_session.expire_all()
    count = (await db_session.execute(
        select(func.count()).select_from(SubSystem)
        .where(SubSystem.system_id == connected_system.id)
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_a_truncated_tree_leaves_absence_null_with_a_reason(
    client, auth_headers, connected_system, monkeypatch
):
    from app.services.scanning import scanner
    monkeypatch.setattr(
        scanner, "_transport", lambda: _github(["docker-compose.yml"], truncated=True)
    )

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    compose = _compose(resp.json())
    assert compose["absence_computed"] is False
    assert compose["subsystems"]["missing_in_code"] is None
    assert "partial" in compose["absence_reason"]
    # Positive findings survive a partial read.
    assert compose["subsystems"]["missing_in_catalogue"]


@pytest.mark.asyncio
async def test_a_deleted_service_is_reported_as_missing_from_the_code(
    client, auth_headers, connected_system, db_session, monkeypatch
):
    db_session.add(SubSystem(
        tenant_id=connected_system.tenant_id, system_id=connected_system.id,
        name="legacy", component_type="web_service",
        source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.commit()

    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    compose = _compose(resp.json())
    assert compose["subsystems"]["missing_in_code"] == ["legacy"]


@pytest.mark.asyncio
async def test_a_repository_with_no_iac_files_still_reports_deleted_rows(
    client, auth_headers, connected_system, db_session, monkeypatch
):
    """Looks alarming, is correct: a complete read of an empty declared set.
    A system whose compose file was deleted wholesale is exactly what this
    report exists to surface, so it must not be special-cased into silence."""
    db_session.add(SubSystem(
        tenant_id=connected_system.tenant_id, system_id=connected_system.id,
        name="api", component_type="web_service",
        source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.commit()

    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["README.md"]))

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    compose = _compose(resp.json())
    assert compose["absence_computed"] is True
    assert compose["subsystems"]["missing_in_code"] == ["api"]


@pytest.mark.asyncio
async def test_drift_requires_a_connected_github_account(
    client, auth_headers, db_session, test_tenant
):
    system = System(
        tenant_id=test_tenant.id, name="Unconnected",
        github_repository_url="https://github.com/acme/other",
    )
    db_session.add(system)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/systems/{system.id}/github/drift", headers=auth_headers
    )

    assert resp.status_code == 409
    assert "not connected" in resp.json()["detail"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_drift_api.py -v`
Expected: FAIL — 404 on the drift route

- [ ] **Step 3: Add drift_repository to the scanner**

Append to `backend/app/services/scanning/scanner.py`:

```python
async def drift_repository(
    db: AsyncSession, *, token: str, system_id: int, tenant_id: int, repo_url: str
) -> dict:
    """Report where the catalogue and the repository disagree. Writes nothing.

    Shares the scan's lock: comparing against a catalogue a concurrent scan is
    mutating would report differences that exist on neither side.
    """
    walk_result = await _with_repository(
        token=token, system_id=system_id, tenant_id=tenant_id, repo_url=repo_url
    )

    detectors_out = []
    for walk in walk_result.walks:
        absence_computed, absence_reason = absence_is_computable(
            walk,
            truncated=walk_result.truncated,
            stopped_early=walk_result.stopped_early,
        )
        report = await reconcile.diff(
            db,
            system_id=system_id,
            tenant_id=tenant_id,
            source=walk.detector.subsystem_source,
            edge_source=walk.detector.edge_source,
            declared=walk.declared,
            absence_computed=absence_computed,
            absence_reason=absence_reason,
        )
        detectors_out.append({
            "detector": walk.detector.name,
            "paths": walk.paths,
            "paths_unread": walk.paths_unread,
            "errors": walk.errors,
            "warnings": report.warnings,
            "absence_computed": report.absence_computed,
            "absence_reason": report.absence_reason,
            "has_drift": report.has_drift,
            "subsystems": {
                "missing_in_catalogue": [
                    {
                        "name": s.name,
                        "component_type": s.component_type,
                        "technology": s.technology,
                        "source_path": s.source_path,
                    }
                    for s in report.subsystems_missing_in_catalogue
                ],
                # None, never [] — "we checked and found nothing missing" and
                # "we could not check" are opposite conclusions.
                "missing_in_code": report.subsystems_missing_in_code,
                "changed": [
                    {
                        "name": c.name,
                        "field": c.field,
                        "catalogue": c.catalogue,
                        "declared": c.declared,
                        "source_path": c.source_path,
                    }
                    for c in report.subsystems_changed
                ],
            },
            "edges": {
                "missing_in_catalogue": [
                    {
                        "from_name": e.from_name,
                        "to_name": e.to_name,
                        "port": e.port,
                        "source_path": e.source_path,
                    }
                    for e in report.edges_missing_in_catalogue
                ],
                "missing_in_code": None if report.edges_missing_in_code is None else [
                    {"from_name": e.from_name, "to_name": e.to_name, "port": e.port}
                    for e in report.edges_missing_in_code
                ],
                "changed": [
                    {
                        "from_name": c.from_name,
                        "to_name": c.to_name,
                        "catalogue_port": c.catalogue_port,
                        "declared_port": c.declared_port,
                        "source_path": c.source_path,
                    }
                    for c in report.edges_changed
                ],
            },
        })

    return {
        "ref": walk_result.ref,
        "files_scanned": walk_result.files_scanned,
        "truncated": walk_result.truncated,
        "stopped_early": walk_result.stopped_early,
        "has_drift": any(d["has_drift"] for d in detectors_out),
        "detectors": detectors_out,
    }
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/v1/systems.py`, add immediately after `scan_system_repository`:

```python
@router.get("/{system_id}/github/drift")
async def system_repository_drift(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Report where the subsystem catalogue and the repository disagree.

    Read-only. Gated the same as the scan: it reads repository contents through
    the tenant's stored token, so it must not be looser than the write that
    does the same thing.
    """
    tenant_id = current_user.active_tenant_id
    system = await system_service.get_system(db, system_id, tenant_id)

    token = await tenant_secret_service.get_secret(db, tenant_id, TOKEN_KIND)
    if token is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "GitHub is not connected for this tenant. Connect it under "
            "Administration → GitHub Integration.",
        )

    try:
        return await scanner.drift_repository(
            db, token=token, system_id=system_id, tenant_id=tenant_id,
            repo_url=system.github_repository_url,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except ScanAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except GitHubAuthError:
        # Its own session: get_db rolls back on the HTTPException raised below,
        # which would silently discard a delete on `db` and leave the dead
        # token in place forever. Same reasoning as the scan endpoint above.
        async with AsyncSessionLocal() as cleanup:
            await tenant_secret_service.delete_secret(cleanup, tenant_id, TOKEN_KIND)
            await tenant_secret_service.delete_secret(cleanup, tenant_id, LOGIN_KIND)
            await cleanup.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "GitHub rejected the stored token. Reconnect the integration.",
        )
    except GitHubRateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"GitHub API rate limit exceeded. Resets at {exc.reset_at}.",
        )
    except GitHubNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except (GitHubUnavailable, GitHubUnexpectedResponse) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_drift_api.py -v`
Expected: 6 passed

- [ ] **Step 6: Mutate to confirm the soundness test discriminates**

In `absence_is_computable`, change the first branch to `if False:`.

Run: `cd backend && uv run pytest tests/integration/test_drift_api.py -v`
Expected: FAIL on `test_a_truncated_tree_leaves_absence_null_with_a_reason`

Restore it and confirm green.

- [ ] **Step 7: Run both engines**

Run: `cd backend && uv run pytest -q`
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS on both

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/scanning/scanner.py backend/app/api/v1/systems.py \
        backend/tests/integration/test_drift_api.py
git commit -m "feat(api): report repository drift for a system

GET /systems/{id}/github/drift. Absence is null with a reason when the
repository was read only in part, never an empty list."
```

---

### Task 10: The drift dialog

**Files:**
- Modify: `frontend/src/types/githubIntegration.ts`
- Modify: `frontend/src/services/githubIntegrationService.ts`
- Create: `frontend/src/components/systems/DriftDialog.tsx`
- Create: `frontend/src/components/systems/__tests__/DriftDialog.test.tsx`
- Modify: `frontend/src/pages/systems/SystemDetail.tsx`

**Interfaces:**
- Consumes: the drift response shape from Task 9.
- Produces: `DriftResult`, `DriftDetectorReport` types; `githubIntegrationService.drift(systemId)`; `<DriftDialog open systemId onClose />`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/systems/__tests__/DriftDialog.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DriftDialog from '../DriftDialog';
import { githubIntegrationService } from '../../../services/githubIntegrationService';

vi.mock('../../../services/githubIntegrationService', () => ({
  githubIntegrationService: { drift: vi.fn() },
}));

const detector = (overrides = {}) => ({
  detector: 'docker_compose',
  paths: ['docker-compose.yml'],
  paths_unread: 0,
  errors: [],
  warnings: [],
  absence_computed: true,
  absence_reason: null,
  has_drift: true,
  subsystems: { missing_in_catalogue: [], missing_in_code: [], changed: [] },
  edges: { missing_in_catalogue: [], missing_in_code: [], changed: [] },
  ...overrides,
});

const result = (detectors: unknown[], overrides = {}) => ({
  ref: 'main',
  files_scanned: 1,
  truncated: false,
  stopped_early: false,
  has_drift: true,
  detectors,
  ...overrides,
});

describe('DriftDialog', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('names each drifted subsystem rather than counting them', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        subsystems: {
          missing_in_catalogue: [{
            name: 'payments-api', component_type: 'web_service',
            technology: 'nginx', source_path: 'docker-compose.yml',
          }],
          missing_in_code: [],
          changed: [],
        },
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText('payments-api')).toBeInTheDocument();
  });

  it('states the positive when nothing has drifted', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({ has_drift: false })], { has_drift: false }) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(
      await screen.findByText(/catalogue matches the code/i),
    ).toBeInTheDocument();
  });

  it('explains why absence was not checked and omits the group entirely', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        absence_computed: false,
        absence_reason: 'GitHub returned only part of this repository.',
        subsystems: {
          missing_in_catalogue: [{
            name: 'api', component_type: 'web_service',
            technology: null, source_path: 'docker-compose.yml',
          }],
          missing_in_code: null,
          changed: [],
        },
      })], { truncated: true }) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText(/only part of this repository/i)).toBeInTheDocument();
    // The heading must be absent, not present over an empty list: rendering it
    // empty would read as "nothing is missing", the opposite conclusion.
    expect(screen.queryByText(/no longer in the code/i)).not.toBeInTheDocument();
  });

  it('shows both values for a changed field', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        subsystems: {
          missing_in_catalogue: [],
          missing_in_code: [],
          changed: [{
            name: 'api', field: 'component_type', catalogue: 'other',
            declared: 'web_service', source_path: 'docker-compose.yml',
          }],
        },
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText(/other/)).toBeInTheDocument();
    expect(screen.getByText(/web_service/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/systems/__tests__/DriftDialog.test.tsx`
Expected: FAIL — cannot resolve `../DriftDialog`

- [ ] **Step 3: Add the types**

Append to `frontend/src/types/githubIntegration.ts`:

```ts
export interface DriftSubsystem {
  name: string;
  component_type: string;
  technology: string | null;
  source_path: string;
}

export interface DriftChangedSubsystem {
  name: string;
  field: string;
  catalogue: string | null;
  declared: string | null;
  source_path: string;
}

export interface DriftEdge {
  from_name: string;
  to_name: string;
  port: number | null;
  source_path?: string;
}

export interface DriftChangedEdge {
  from_name: string;
  to_name: string;
  catalogue_port: number | null;
  declared_port: number | null;
  source_path: string;
}

export interface DriftDetectorReport {
  detector: string;
  paths: string[];
  paths_unread: number;
  errors: string[];
  warnings: string[];
  /** False when the repository was read only in part. */
  absence_computed: boolean;
  absence_reason: string | null;
  has_drift: boolean;
  subsystems: {
    missing_in_catalogue: DriftSubsystem[];
    /** null — not [] — when absence could not be computed. */
    missing_in_code: string[] | null;
    changed: DriftChangedSubsystem[];
  };
  edges: {
    missing_in_catalogue: DriftEdge[];
    missing_in_code: DriftEdge[] | null;
    changed: DriftChangedEdge[];
  };
}

export interface DriftResult {
  ref: string;
  files_scanned: number;
  truncated: boolean;
  stopped_early: boolean;
  has_drift: boolean;
  detectors: DriftDetectorReport[];
}
```

- [ ] **Step 4: Add the service call**

In `frontend/src/services/githubIntegrationService.ts`, add `DriftResult` to the type import and this method after `scan`:

```ts
  drift: (systemId: number): Promise<DriftResult> =>
    api.get(`/systems/${systemId}/github/drift`).then((r) => r.data),
```

- [ ] **Step 5: Write the dialog**

Create `frontend/src/components/systems/DriftDialog.tsx`:

```tsx
import { useState } from 'react';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, List, ListItem, ListItemText, Stack, Typography,
} from '@mui/material';
import { githubIntegrationService } from '../../services/githubIntegrationService';
import { formatApiError } from '../../services/apiError';
import type { DriftDetectorReport, DriftResult } from '../../types/githubIntegration';

interface Props {
  open: boolean;
  systemId: number;
  onClose: () => void;
}

function DetectorSection({ report }: { report: DriftDetectorReport }) {
  const { subsystems, edges } = report;

  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Chip label={report.detector} size="small" variant="outlined" />
        {report.paths.map((p) => (
          <Typography key={p} variant="caption" color="text.secondary">{p}</Typography>
        ))}
      </Stack>

      {!report.absence_computed && report.absence_reason && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {report.absence_reason} Subsystems and dependencies that are no longer
          declared could not be checked.
        </Alert>
      )}

      {subsystems.missing_in_catalogue.length > 0 && (
        <>
          <Typography variant="subtitle2">Declared in the code, not in EnvManager</Typography>
          <List dense disablePadding>
            {subsystems.missing_in_catalogue.map((s) => (
              <ListItem key={s.name} disableGutters>
                <ListItemText
                  primary={s.name}
                  secondary={`${s.component_type}${s.technology ? ` · ${s.technology}` : ''} · ${s.source_path}`}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {/* Rendered only when absence was computed. An empty list under this
          heading would read as "nothing is missing" — the opposite conclusion
          to "we could not check". */}
      {subsystems.missing_in_code && subsystems.missing_in_code.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            In EnvManager, no longer in the code
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Scanning will not remove these — the scanner never deletes.
          </Typography>
          <List dense disablePadding>
            {subsystems.missing_in_code.map((name) => (
              <ListItem key={name} disableGutters>
                <ListItemText primary={name} />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {subsystems.changed.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>Changed</Typography>
          <List dense disablePadding>
            {subsystems.changed.map((c) => (
              <ListItem key={`${c.name}-${c.field}`} disableGutters>
                <ListItemText
                  primary={c.name}
                  secondary={`${c.field}: ${c.catalogue ?? '—'} → ${c.declared ?? '—'}`}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {edges.missing_in_catalogue.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            Dependencies declared in the code, not in EnvManager
          </Typography>
          <List dense disablePadding>
            {edges.missing_in_catalogue.map((e) => (
              <ListItem key={`${e.from_name}-${e.to_name}`} disableGutters>
                <ListItemText primary={`${e.from_name} → ${e.to_name}`} />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {edges.missing_in_code && edges.missing_in_code.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            Dependencies in EnvManager, no longer in the code
          </Typography>
          <List dense disablePadding>
            {edges.missing_in_code.map((e) => (
              <ListItem key={`${e.from_name}-${e.to_name}`} disableGutters>
                <ListItemText primary={`${e.from_name} → ${e.to_name}`} />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {edges.changed.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>Dependencies changed</Typography>
          <List dense disablePadding>
            {edges.changed.map((c) => (
              <ListItem key={`${c.from_name}-${c.to_name}`} disableGutters>
                <ListItemText
                  primary={`${c.from_name} → ${c.to_name}`}
                  secondary={`port: ${c.catalogue_port ?? '—'} → ${c.declared_port ?? '—'}`}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {!report.has_drift && report.absence_computed && (
        <Typography variant="body2" color="text.secondary">
          The catalogue matches the code.
        </Typography>
      )}

      {report.warnings.map((w) => (
        <Alert key={w} severity="warning" sx={{ mt: 1 }}>{w}</Alert>
      ))}
      {report.errors.map((e) => (
        <Alert key={e} severity="error" sx={{ mt: 1 }}>{e}</Alert>
      ))}
    </Box>
  );
}

export default function DriftDialog({ open, systemId, onClose }: Props) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<DriftResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleCheck = async () => {
    setChecking(true);
    setError(null);
    try {
      setResult(await githubIntegrationService.drift(systemId));
    } catch (err) {
      setError(formatApiError(err, 'Drift check failed'));
    } finally {
      setChecking(false);
    }
  };

  const handleClose = () => {
    if (checking) return;
    setResult(null);
    setError(null);
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Repository drift</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Compares this system&apos;s subsystems against what its GitHub repository
            declares. Nothing is written — use Scan repository to apply changes.
          </Typography>

          {error && <Alert severity="error">{error}</Alert>}

          {result && (
            <Stack spacing={2}>
              <Typography variant="body2" color="text.secondary">
                Checked ref <strong>{result.ref}</strong> — {result.files_scanned} file
                {result.files_scanned === 1 ? '' : 's'} read.
              </Typography>

              {!result.has_drift && (
                <Alert severity="success">
                  No drift found — the catalogue matches the code.
                </Alert>
              )}

              <Divider />

              {result.detectors.map((d) => (
                <DetectorSection key={d.detector} report={d} />
              ))}
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={checking}>Close</Button>
        <Button variant="contained" onClick={handleCheck} disabled={checking}>
          {checking ? 'Checking…' : 'Check drift'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/systems/__tests__/DriftDialog.test.tsx`
Expected: 4 passed

- [ ] **Step 7: Wire the button into System detail**

In `frontend/src/pages/systems/SystemDetail.tsx`:

Add the import beside the scan dialog's (near line 72):

```tsx
import DriftDialog from '../../components/systems/DriftDialog';
```

Add state beside `scanDialogOpen` (near line 300):

```tsx
  const [driftDialogOpen, setDriftDialogOpen] = useState(false);
```

Add a second button immediately after the "Scan repository" `</Tooltip>` (near line 886):

```tsx
                  <Tooltip
                    title={
                      currentSystem?.github_repository_url
                        ? ''
                        : 'Set a GitHub Repository URL to enable drift checks'
                    }
                  >
                    <span>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => setDriftDialogOpen(true)}
                        disabled={!currentSystem?.github_repository_url}
                      >
                        Check drift
                      </Button>
                    </span>
                  </Tooltip>
```

Add the dialog beside `<ScanRepositoryDialog />` (near line 1860), matching however that block guards on `currentSystem`:

```tsx
        <DriftDialog
          open={driftDialogOpen}
          systemId={currentSystem.id}
          onClose={() => setDriftDialogOpen(false)}
        />
```

- [ ] **Step 8: Typecheck, lint and build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

Run: `cd frontend && npm run lint`
Expected: no new errors

Run: `cd frontend && npm run build`
Expected: builds cleanly

Run: `cd frontend && npx vitest run`
Expected: PASS

- [ ] **Step 9: Open the page**

Six defects in this repo's history were found only by opening the page, every one with a fully green suite. A green frontend suite is not evidence the feature works.

```bash
docker-compose up -d
cd backend && uvicorn app.main:app --reload   # separate terminal
cd frontend && npm run dev                    # separate terminal
```

Log in as `admin` / `admin123` (tenant `demo`), open a System that has a GitHub repository URL and a connected GitHub account, and confirm by eye:

1. **Check drift** on a system never scanned lists every service the repo declares under "Declared in the code, not in EnvManager".
2. Press **Scan repository**, then **Check drift** again — it now reports no drift and says the catalogue matches the code.
3. Rename or delete a subsystem in EnvManager, then **Check drift** — the change is reported in the right category and named, never as `#N`.
4. Nothing is written by a drift check: the subsystem list is unchanged after running one.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/types/githubIntegration.ts \
        frontend/src/services/githubIntegrationService.ts \
        frontend/src/components/systems/DriftDialog.tsx \
        frontend/src/components/systems/__tests__/DriftDialog.test.tsx \
        frontend/src/pages/systems/SystemDetail.tsx
git commit -m "feat(ui): show repository drift on System detail

A group whose absence could not be computed is omitted with a reason rather
than rendered empty — an empty list reads as the opposite conclusion."
```

---

### Task 11: Documentation

**Files:**
- Modify: `docs/phases/phase-6.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Update the phase document**

In `docs/phases/phase-6.md`, change the status line at the top from "Three sub-projects remain" to reflect that all four are shipped, and replace section 2 ("Drift detection — not started, and now the only remainder") with a shipped record covering: it compares repository IaC against the subsystem catalogue rather than `.tfstate` against recorded state; the parse/apply/diff split and why (a parser that writes never produces a comparable value); `SubSystem.source`/`source_path`; and the soundness rule (positive findings survive a partial read, absence findings do not). Note `.tf`-versus-`.tfstate` drift remains out of scope for the two reasons the spec gives.

- [ ] **Step 2: Update CLAUDE.md**

In the Phase 6 paragraph, record drift detection as shipped and Phase 6 as complete. Add to **Common Pitfalls**:

```markdown
- **Parsing that writes as it goes** — a scanner detector returns a `DeclaredState` value and touches no database. `reconcile.apply()` writes it and `reconcile.diff()` compares it, and both read the same value, which is what stops the drift report describing a change a scan would not make. Truncate to column widths **in the parser**, never in `apply()` — otherwise a stored row differs from the declaration it came from and `diff()` reports a phantom change on every run
- **Treating a partial read as a complete one** — `GET /systems/{id}/github/drift` computes "in the catalogue but not in the code" only when the whole tree was read. A truncated tree, the file cap, an unread path or a fetch error all make an unread file indistinguishable from a deleted one, so the absence categories come back **null with a reason**, never `[]`. "We checked and found nothing" and "we could not check" are opposite conclusions
```

- [ ] **Step 3: Commit**

```bash
git add docs/phases/phase-6.md CLAUDE.md
git commit -m "docs: record drift detection as shipped, completing Phase 6"
```

---

## Final verification

- [ ] `cd backend && uv run pytest -q` — PASS
- [ ] `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q` — PASS
- [ ] `cd backend && uv run pytest tests/test_migration_schema_drift.py -v` — PASS, not skipped
- [ ] `cd frontend && npx tsc --noEmit && npm run lint && npm run build && npx vitest run` — PASS
- [ ] The four manual checks in Task 10 Step 9 done by eye in the running app
- [ ] `git log --oneline main..HEAD` shows one commit per task, none of them a fixup for a step skipped earlier
