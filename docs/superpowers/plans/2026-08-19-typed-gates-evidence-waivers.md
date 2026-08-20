# Phase 9 C2 — Typed Gates, Evidence and Waivers: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give release gates a tenant-configurable type declaring failure behaviour and expected evidence, structured evidence linked to the deployment it vouches for, and waivers with an approver, an expiry and a remediation note — surfaced as advice in the UI and as a machine-readable verdict a DevOps pipeline can ask for.

**Architecture:** Four additive schema changes (three tables, two nullable columns) and one evaluator. `gate_readiness_service.evaluate()` is the only place the rules live; the release detail panel and the new `GET /api/v1/webhooks/release-ready` endpoint both call it, so they cannot disagree. Nothing refuses anything: no transition is blocked and `can-deploy` is untouched.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic (hand-written DDL), Pydantic v2, pytest (dual engine), React 18 + TypeScript + MUI + Redux Toolkit, vitest.

**Spec:** [../specs/2026-08-19-typed-gates-evidence-waivers-design.md](../specs/2026-08-19-typed-gates-evidence-waivers-design.md)

## Global Constraints

- **Every enum column uses `native_enum=False`** — a plain VARCHAR. PostgreSQL native ENUMs break the SQLite test leg.
- **Every query on a tenant-scoped table filters `tenant_id`**, taken from `current_user.active_tenant_id` (never `.tenant_id` — impersonation).
- **Never call `db.commit()` in a service.** `get_db()` auto-commits; a commit inside a service breaks the outbox pattern. Use `db.flush()` to get an id mid-transaction.
- **Soft deletes only** — set `deleted_at`; never `DELETE`.
- **Migrations are hand-written.** `alembic revision -m "..."` then write `op.create_table` / `op.add_column` by hand. `--autogenerate` produces empty migrations because `init_db()` calls `create_all`.
- **New list endpoints take `page: Page = Depends(pagination())`** and order by a **unique** key (append the primary key as a tiebreaker). Services return `(rows, total)`.
- **Frontend mutating thunks use `rejectWithValue(formatApiError(err))`** and callers read `result.payload`. A test that rejects with a plain `Error` passes while the app is broken — mock an `AxiosError` shape.
- **Run all three suites before claiming done:** SQLite, PostgreSQL (`TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`), and the frontend.
- **C2 refuses nothing.** No code in this plan may raise, 409, or return `False` from any existing guard on the basis of gate state. The only new refusals permitted are input validation on C2's own writes (422 on a bad payload, 404 on a cross-tenant id).

---

### Task 1: Schema — three tables, two columns, one migration

**Files:**
- Create: `backend/app/db/models/gate_type.py`
- Create: `backend/app/db/models/gate_evidence.py`
- Create: `backend/app/db/models/gate_waiver.py`
- Create: `backend/app/services/gate_type_defaults.py`
- Create: `backend/app/db/migrations/versions/<rev>_gatetypes.py`
- Modify: `backend/app/db/models/release_gate.py`
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/services/tenant_service.py`
- Test: `backend/tests/test_gate_type_defaults.py`

**Interfaces:**
- Produces: `GateType`, `GateEvidence`, `GateWaiver` models; `STANDARD_GATE_TYPES: list[dict]`; `seed_gate_type_defaults_for_tenant(db, tenant_id) -> None`; `ReleaseGate.gate_type_id`, `ReleaseGate.test_phase_id`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_gate_type_defaults.py
import pytest
from sqlalchemy import select

from app.db.models.gate_type import GateType
from app.services.gate_type_defaults import (
    STANDARD_GATE_TYPES,
    seed_gate_type_defaults_for_tenant,
)


@pytest.mark.asyncio
async def test_seeding_creates_the_eight_standard_types(db_session, test_tenant):
    await seed_gate_type_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(GateType).where(GateType.tenant_id == test_tenant.id)
        )
    ).scalars().all()

    assert len(rows) == len(STANDARD_GATE_TYPES) == 8
    assert {r.category for r in rows} == {
        "functional", "nfr", "integration", "security",
        "license", "accessibility", "business", "ops_readiness",
    }
    # Every standard type declares a behaviour; none is left to be guessed.
    assert all(r.failure_behaviour in {"block", "warn", "accept_with_exception"} for r in rows)


@pytest.mark.asyncio
async def test_seeding_is_idempotent_and_case_insensitive(db_session, test_tenant):
    db_session.add(GateType(
        tenant_id=test_tenant.id, name="security",
        failure_behaviour="warn", expected_evidence=[], display_order=0,
    ))
    await db_session.flush()

    await seed_gate_type_defaults_for_tenant(db_session, test_tenant.id)
    await seed_gate_type_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    names = [
        n.lower() for n in (
            await db_session.execute(
                select(GateType.name).where(GateType.tenant_id == test_tenant.id)
            )
        ).scalars().all()
    ]
    assert names.count("security") == 1
    assert len(names) == 8
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_gate_type_defaults.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.gate_type'`

- [ ] **Step 3: Write the three models**

```python
# backend/app/db/models/gate_type.py
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateType(Base):
    """Tenant-scoped release-gate type vocabulary.

    Shaped like EnvironmentTier, which B1 introduced for the same reason: a
    standard vocabulary that real tenants do not quite match. `category` maps a
    tenant's own name onto one of the eight standard types and is NULL for a
    type that matches none of them. A plain VARCHAR, not SAEnum — SAEnum stores
    the member NAME, which is why environment.status holds 'ACTIVE'.
    """

    __tablename__ = "gate_type"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # block | warn | accept_with_exception. Declares how a FAILURE READS in the
    # verdict — it never refuses anything. See the spec, section 2.
    failure_behaviour: Mapped[str] = mapped_column(String(30), nullable=False, default="warn")
    # JSON list of evidence KIND NAMES this type expects, e.g.
    # ["Test execution report", "Defect summary"]. Empty means none expected.
    # This is where the SIT -> UAT -> PreProd -> Production strictness ladder
    # lives: a "UAT Sign-off" type expects more kinds than a "SIT Sign-off".
    expected_evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requires_deployment_link: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
# backend/app/db/models/gate_evidence.py
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateEvidence(Base):
    """A reference vouching for a gate. NOT an artefact — this application has
    no file storage, so evidence is a URL plus an attestation of who added it.

    `deployment_id` is what makes it worth more than a bookmark: a deployment
    already pins which build of which subsystem landed in which environment and
    when, so evidence naming one inherits all of it — and becomes STALE when a
    later successful deployment of the same component supersedes it.
    """

    __tablename__ = "gate_evidence"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    gate_id: Mapped[int] = mapped_column(
        ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Free text, not an FK. The UI offers the type's expected_evidence entries
    # as choices; an unlisted kind is accepted and simply satisfies no
    # expectation.
    kind: Mapped[str] = mapped_column(String(150), nullable=False)
    label: Mapped[str] = mapped_column(String(250), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deployment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deployment.id"), nullable=True, index=True
    )
    added_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
# backend/app/db/models/gate_waiver.py
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateWaiver(Base):
    """The record behind an overridden gate: reason, approver, expiry,
    remediation.

    Rows ACCUMULATE as history; the latest live one is current. Re-waiving after
    an expiry must not overwrite the previous approver and reason — destroying
    that history destroys the one thing a waiver exists to create.

    There is NO state column. Live-versus-expired is computed from expires_at
    through expiry_boundary, A4's and B5's shape: nothing to invalidate, no
    scheduler.
    """

    __tablename__ = "gate_waiver"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    gate_id: Mapped[int] = mapped_column(
        ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    # NULL means "no expiry" — a permanent waiver, which is legitimate and must
    # not be confused with an expired one.
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    remediation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Add the two nullable columns to `ReleaseGate`**

In `backend/app/db/models/release_gate.py`, after `decision_notes`:

```python
    # Nullable, no backfill: every existing gate stays valid as UNTYPED, and
    # untyped is a state the verdict handles explicitly (it warns, never blocks
    # — no behaviour was declared, so none is invented).
    gate_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("gate_type.id"), nullable=True, index=True
    )
    # Nullable because MOST GATES HAVE NO PHASE: Scope Sign-off is created early
    # and belongs to none, and a Go/No-Go gate sits at the end and belongs to
    # none either. Only test sign-off gates carry one.
    test_phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("test_phase.id"), nullable=True, index=True
    )
```

- [ ] **Step 5: Register the models**

Add to `backend/app/db/models/__init__.py`, following the existing import style:

```python
from app.db.models.gate_type import GateType  # noqa: F401
from app.db.models.gate_evidence import GateEvidence  # noqa: F401
from app.db.models.gate_waiver import GateWaiver  # noqa: F401
```

- [ ] **Step 6: Write the defaults module**

```python
# backend/app/services/gate_type_defaults.py
"""Seed the eight standard release-gate types. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill,
following environment_tier_defaults.py and release_defaults.py.

The migration carries its own literal copy of this list rather than importing
it. That is deliberate: a migration reproduces the past, so it must not change
meaning when this module gains a ninth type.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.gate_type import GateType

STANDARD_GATE_TYPES: list[dict[str, Any]] = [
    {"name": "Functional",     "category": "functional",     "failure_behaviour": "block",
     "expected_evidence": ["Test execution report", "Defect summary"],
     "requires_deployment_link": True,  "display_order": 10},
    {"name": "NFR / Performance", "category": "nfr",         "failure_behaviour": "block",
     "expected_evidence": ["Performance test report"],
     "requires_deployment_link": True,  "display_order": 20},
    {"name": "Integration",    "category": "integration",    "failure_behaviour": "block",
     "expected_evidence": ["Integration test report"],
     "requires_deployment_link": True,  "display_order": 30},
    {"name": "Security",       "category": "security",       "failure_behaviour": "block",
     "expected_evidence": ["Security scan result"],
     "requires_deployment_link": True,  "display_order": 40},
    {"name": "License",        "category": "license",        "failure_behaviour": "warn",
     "expected_evidence": ["Dependency licence report"],
     "requires_deployment_link": False, "display_order": 50},
    {"name": "Accessibility",  "category": "accessibility",  "failure_behaviour": "warn",
     "expected_evidence": ["Accessibility audit"],
     "requires_deployment_link": False, "display_order": 60},
    {"name": "Business",       "category": "business",       "failure_behaviour": "accept_with_exception",
     "expected_evidence": ["Business sign-off"],
     "requires_deployment_link": False, "display_order": 70},
    {"name": "Ops Readiness",  "category": "ops_readiness",  "failure_behaviour": "block",
     "expected_evidence": ["Runbook", "Monitoring confirmation"],
     "requires_deployment_link": False, "display_order": 80},
]


async def seed_gate_type_defaults_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    """Create any of the standard gate types this tenant does not already have.

    Matched on lowercased name so a tenant that already has 'security' is not
    given a second 'Security'.
    """
    existing = {
        name.lower()
        for name in (
            await db.execute(
                select(GateType.name).where(GateType.tenant_id == tenant_id)
            )
        ).scalars().all()
    }
    for spec in STANDARD_GATE_TYPES:
        if spec["name"].lower() in existing:
            continue
        db.add(GateType(tenant_id=tenant_id, is_active=True, **spec))
```

- [ ] **Step 7: Call it for new tenants**

In `backend/app/services/tenant_service.py`, alongside the existing seeding calls (near line 57):

```python
from app.services.gate_type_defaults import seed_gate_type_defaults_for_tenant
...
    await seed_gate_type_defaults_for_tenant(db, tenant.id)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_gate_type_defaults.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Write the migration**

Run `cd backend && alembic revision -m "gatetypes"`, then write the DDL by hand. Copy the eight-type list literally into the migration — do **not** import `STANDARD_GATE_TYPES`.

```python
def upgrade() -> None:
    op.create_table(
        "gate_type",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("failure_behaviour", sa.String(30), nullable=False, server_default="warn"),
        sa.Column("expected_evidence", sa.JSON(), nullable=False),
        sa.Column("requires_deployment_link", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "gate_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("gate_id", sa.Integer(), sa.ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(150), nullable=False),
        sa.Column("label", sa.String(250), nullable=False),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployment.id"), nullable=True, index=True),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "gate_waiver",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("gate_id", sa.Integer(), sa.ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("release_gate", sa.Column("gate_type_id", sa.Integer(), sa.ForeignKey("gate_type.id"), nullable=True))
    op.add_column("release_gate", sa.Column("test_phase_id", sa.Integer(), sa.ForeignKey("test_phase.id"), nullable=True))
    op.create_index("ix_release_gate_gate_type_id", "release_gate", ["gate_type_id"])
    op.create_index("ix_release_gate_test_phase_id", "release_gate", ["test_phase_id"])
    # Backfill the eight types for every EXISTING tenant. Without this a tenant
    # has no vocabulary to type a gate with and the feature reads as broken
    # rather than unconfigured.
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    tenant_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM tenant")).fetchall()]
    gate_type = sa.table(
        "gate_type",
        sa.column("tenant_id"), sa.column("name"), sa.column("category"),
        sa.column("failure_behaviour"), sa.column("expected_evidence"),
        sa.column("requires_deployment_link"), sa.column("display_order"),
        sa.column("is_active"), sa.column("created_at"), sa.column("updated_at"),
    )
    for tenant_id in tenant_ids:
        existing = {
            r[0].lower()
            for r in conn.execute(
                sa.text("SELECT name FROM gate_type WHERE tenant_id = :t"), {"t": tenant_id}
            ).fetchall()
        }
        rows = [
            {**spec, "tenant_id": tenant_id, "is_active": True,
             "created_at": now, "updated_at": now,
             "expected_evidence": json.dumps(spec["expected_evidence"])}
            for spec in _STANDARD_GATE_TYPES
            if spec["name"].lower() not in existing
        ]
        if rows:
            op.bulk_insert(gate_type, rows)


def downgrade() -> None:
    op.drop_index("ix_release_gate_test_phase_id", table_name="release_gate")
    op.drop_index("ix_release_gate_gate_type_id", table_name="release_gate")
    op.drop_column("release_gate", "test_phase_id")
    op.drop_column("release_gate", "gate_type_id")
    op.drop_table("gate_waiver")
    op.drop_table("gate_evidence")
    op.drop_table("gate_type")
```

`_STANDARD_GATE_TYPES` is a **literal copy** of the eight dicts from `gate_type_defaults.py`, declared at the top of the migration module alongside `import json` and `from datetime import datetime, timezone`. Do not import the service module: a migration reproduces the past, so it must not change meaning when that list gains a ninth type.

**Critical:** `Base` gives every table `created_at`/`updated_at` — six tables shipped broken migrations by omitting them, which is why the drift guard exists. Include them on all three new tables.

- [ ] **Step 10: Apply and verify the migration on a scratch database**

Do **not** run `alembic downgrade -1` against the dev database — it steps back from the current head, not from your revision, and has already dropped `tenant_secret` once.

Run: `cd backend && alembic upgrade head && uv run pytest tests/test_migration_schema_drift.py -v`
Expected: PASS. Remember this compares **column name sets only** — not types, defaults or indexes — so its passing is not evidence the migration matches the models. Eyeball the types by hand.

- [ ] **Step 11: Commit**

```bash
git add backend/app/db/models/gate_type.py backend/app/db/models/gate_evidence.py \
        backend/app/db/models/gate_waiver.py backend/app/db/models/release_gate.py \
        backend/app/db/models/__init__.py backend/app/services/gate_type_defaults.py \
        backend/app/services/tenant_service.py backend/app/db/migrations/versions/ \
        backend/tests/test_gate_type_defaults.py
git commit -m "feat(c2): gate types, evidence and waivers — schema and seeding"
```

---

### Task 2: `gate_type` CRUD service and API

**Files:**
- Create: `backend/app/services/gate_type_service.py`
- Create: `backend/app/api/v1/schemas/gate_type.py`
- Create: `backend/app/api/v1/gate_types.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_gate_type_service.py`

**Interfaces:**
- Consumes: `GateType` (Task 1).
- Produces: `list_types(db, tenant_id, *, page=None, sort=None, include_inactive=True) -> tuple[list[GateType], int]`; `create_type(db, tenant_id, data) -> GateType`; `update_type(db, type_id, tenant_id, data) -> GateType`; `delete_type(db, type_id, tenant_id) -> None`; schemas `GateTypeCreate`, `GateTypeUpdate`, `GateTypeRead`; routes under `/api/v1/gate-types`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_gate_type_service.py
import pytest
from fastapi import HTTPException

from app.api.v1.schemas.gate_type import GateTypeCreate
from app.services import gate_type_service


@pytest.mark.asyncio
async def test_duplicate_name_is_refused_case_insensitively(db_session, test_tenant):
    await gate_type_service.create_type(
        db_session, test_tenant.id,
        GateTypeCreate(name="Security", failure_behaviour="block"),
    )
    with pytest.raises(HTTPException) as exc:
        await gate_type_service.create_type(
            db_session, test_tenant.id,
            GateTypeCreate(name="security", failure_behaviour="warn"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_type_from_another_tenant_is_not_visible(db_session, test_tenant, tenant):
    await gate_type_service.create_type(
        db_session, tenant.id, GateTypeCreate(name="Theirs", failure_behaviour="warn"),
    )
    rows, total = await gate_type_service.list_types(db_session, test_tenant.id)
    assert "Theirs" not in [r.name for r in rows]
    assert total == len(rows)


@pytest.mark.asyncio
async def test_an_unknown_failure_behaviour_is_a_422(db_session, test_tenant):
    with pytest.raises(Exception):
        GateTypeCreate(name="Odd", failure_behaviour="explode")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_gate_type_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.v1.schemas.gate_type'`

- [ ] **Step 3: Write the schemas**

```python
# backend/app/api/v1/schemas/gate_type.py
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

FailureBehaviour = Literal["block", "warn", "accept_with_exception"]


class GateTypeCreate(BaseModel):
    # extra="forbid" so a typo'd key is a 422 rather than a silent drop — the
    # POST /projects and POST /tenant/lifecycle-templates class of bug.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=150)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    failure_behaviour: FailureBehaviour = "warn"
    expected_evidence: list[str] = Field(default_factory=list)
    requires_deployment_link: bool = False
    display_order: int = 0
    is_active: bool = True


class GateTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=150)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    failure_behaviour: Optional[FailureBehaviour] = None
    expected_evidence: Optional[list[str]] = None
    requires_deployment_link: Optional[bool] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class GateTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    category: Optional[str]
    failure_behaviour: str
    expected_evidence: list[str]
    requires_deployment_link: bool
    display_order: int
    is_active: bool
```

- [ ] **Step 4: Write the service**

```python
# backend/app/services/gate_type_service.py
"""Gate type vocabulary — tenant-scoped CRUD.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
Same call environment_tier and user_group made.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_type import GateTypeCreate, GateTypeUpdate
from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.db.models.gate_type import GateType


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(GateType.id).where(
        GateType.tenant_id == tenant_id,
        func.lower(GateType.name) == name.lower(),
        GateType.deleted_at.is_(None),
    )
    if exclude_id is not None:
        query = query.where(GateType.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A gate type named {name} already exists"
        )


async def list_types(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    include_inactive: bool = True,
) -> tuple[list[GateType], int]:
    query = select(GateType).where(
        GateType.tenant_id == tenant_id, GateType.deleted_at.is_(None)
    )
    if not include_inactive:
        query = query.where(GateType.is_active.is_(True))
    # display_order defaults to 0, so ties are the normal case, not the
    # exception — the id tiebreaker is what stops LIMIT/OFFSET duplicating and
    # dropping rows across pages.
    query = apply_sort(query, sort).order_by(GateType.display_order, GateType.id)
    return await fetch_page(db, query, page)


async def create_type(
    db: AsyncSession, tenant_id: int, data: GateTypeCreate
) -> GateType:
    await _assert_name_free(db, tenant_id, data.name)
    row = GateType(tenant_id=tenant_id, **data.model_dump())
    db.add(row)
    await db.flush()
    return row


async def update_type(
    db: AsyncSession, type_id: int, tenant_id: int, data: GateTypeUpdate
) -> GateType:
    row = await get_type(db, type_id, tenant_id)
    fields = data.model_dump(exclude_unset=True)  # omitted key means "leave alone"
    if "name" in fields:
        await _assert_name_free(db, tenant_id, fields["name"], exclude_id=type_id)
    for key, value in fields.items():
        setattr(row, key, value)
    await db.flush()
    return row


async def get_type(db: AsyncSession, type_id: int, tenant_id: int) -> GateType:
    row = (
        await db.execute(
            select(GateType).where(
                GateType.id == type_id,
                GateType.tenant_id == tenant_id,
                GateType.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate type not found")
    return row


async def delete_type(db: AsyncSession, type_id: int, tenant_id: int) -> None:
    """Soft delete. Deliberately does NOT cascade to gates: a gate whose type
    is archived keeps pointing at it and renders the archived name — A1's
    read-rendering rule. A NEW assignment to an archived type is refused by
    get_type; an existing one is left alone."""
    row = await get_type(db, type_id, tenant_id)
    row.deleted_at = datetime.now(timezone.utc)
    await db.flush()
```

- [ ] **Step 5: Write the router and mount it**

```python
# backend/app/api/v1/gate_types.py
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_type import GateTypeCreate, GateTypeRead, GateTypeUpdate
from app.core.pagination import Page, Sort, pagination, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.db.models.gate_type import GateType
from app.services import gate_type_service

router = APIRouter()

GATE_TYPE_SORTS = {
    "name": GateType.name,
    "display_order": GateType.display_order,
    "category": GateType.category,
}


@router.get("", response_model=list[GateTypeRead])
async def list_gate_types(
    response: Response,
    include_inactive: bool = True,
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(GATE_TYPE_SORTS)),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Reads are open to ANY tenant member; only writes are Admin.

    Deliberately unlike /tenant/users, which really is admin-gated. B3a shipped
    this over-gated on exactly that false analogy and it took a review to catch.
    """
    rows, total = await gate_type_service.list_types(
        db, current_user.active_tenant_id, page=page, sort=sort,
        include_inactive=include_inactive,
    )
    response.headers["X-Total-Count"] = str(total)
    return rows


@router.post("", response_model=GateTypeRead, status_code=status.HTTP_201_CREATED)
async def create_gate_type(
    data: GateTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await gate_type_service.create_type(db, current_user.active_tenant_id, data)


@router.put("/{type_id}", response_model=GateTypeRead)
async def update_gate_type(
    type_id: int,
    data: GateTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await gate_type_service.update_type(
        db, type_id, current_user.active_tenant_id, data
    )


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gate_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await gate_type_service.delete_type(db, type_id, current_user.active_tenant_id)
```

Mount in `main.py` beside the other v1 routers:

```python
from app.api.v1 import gate_types as gate_types_router
...
app.include_router(
    gate_types_router.router, prefix="/api/v1/gate-types", tags=["Gate Types"]
)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_gate_type_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/gate_type_service.py backend/app/api/v1/schemas/gate_type.py \
        backend/app/api/v1/gate_types.py backend/app/main.py backend/tests/test_gate_type_service.py
git commit -m "feat(c2): gate type CRUD"
```

---

### Task 3: Waivers — `override_gate` writes a record, state is computed

**Files:**
- Create: `backend/app/services/gate_waiver_service.py`
- Modify: `backend/app/services/release_gate_service.py:320-360` (`override_gate`)
- Modify: `backend/app/api/v1/schemas/release_gate.py`
- Test: `backend/tests/test_gate_waiver.py`

**Interfaces:**
- Consumes: `GateWaiver` (Task 1), `expiry_boundary` from `app.core.day_boundaries`.
- Produces: `waiver_state(waiver, now) -> str` returning `"live"` or `"expired"`; `latest_waivers_for_gates(db, tenant_id, gate_ids) -> dict[int, GateWaiver]`; `ReleaseGateDecision` gains `expires_at`, `remediation`, `approved_by_user_id`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_gate_waiver.py
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.gate_waiver import GateWaiver
from app.services.gate_waiver_service import waiver_state


def _waiver(expires_at):
    return GateWaiver(
        tenant_id=1, gate_id=1, reason="r",
        approved_by_user_id=1, created_by=1, expires_at=expires_at,
    )


def test_a_waiver_is_live_all_through_its_expiry_day():
    """A DEADLINE IS A DAY. The UI writes expires_at at T00:00:00Z, so at
    instant precision a waiver expiring today reads expired from one minute
    past midnight — the exact bug A4 shipped and B2 inherited."""
    expiry = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)
    just_after_midnight = datetime(2026, 8, 19, 0, 1, tzinfo=timezone.utc)
    late_in_the_day = datetime(2026, 8, 19, 23, 59, tzinfo=timezone.utc)

    assert waiver_state(_waiver(expiry), just_after_midnight) == "live"
    assert waiver_state(_waiver(expiry), late_in_the_day) == "live"


def test_a_waiver_is_expired_the_day_after():
    expiry = datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 8, 20, 0, 1, tzinfo=timezone.utc)
    assert waiver_state(_waiver(expiry), next_day) == "expired"


def test_a_null_expiry_never_expires():
    """NULL means 'no expiry', a legitimate permanent waiver — never confuse it
    with an expired one."""
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert waiver_state(_waiver(None), far_future) == "live"


@pytest.mark.asyncio
async def test_overriding_a_gate_writes_a_waiver_row(db_session, test_tenant, test_user, gate):
    from app.services import release_gate_service, gate_waiver_service

    await release_gate_service.override_gate(
        db_session, gate.id, notes="accepted risk", tenant_id=test_tenant.id,
        user_id=test_user.id, expires_at=None, remediation="fix in next sprint",
        approved_by_user_id=test_user.id,
    )
    await db_session.flush()

    waivers = await gate_waiver_service.latest_waivers_for_gates(
        db_session, test_tenant.id, [gate.id]
    )
    assert waivers[gate.id].remediation == "fix in next sprint"
    assert gate.status == "overridden"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_gate_waiver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.gate_waiver_service'`

- [ ] **Step 3: Write `waiver_state` and the batch lookup**

```python
# backend/app/services/gate_waiver_service.py
"""Gate waivers — the record behind an overridden gate.

THERE IS NO STATE COLUMN. Live-versus-expired is computed here, through
expiry_boundary, so nothing has to be invalidated and no scheduler exists.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.day_boundaries import expiry_boundary
from app.db.models.gate_waiver import GateWaiver


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes where PostgreSQL returns aware ones.
    Comparing the two is a TypeError — an engine-dependent 500 invisible on the
    PostgreSQL leg."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def waiver_state(waiver: GateWaiver, now: datetime) -> str:
    """"live" or "expired". A DEADLINE IS A DAY: the expiry day itself is live."""
    expires_at = _utc(waiver.expires_at)
    if expires_at is None:
        return "live"
    return "expired" if expires_at < expiry_boundary(now) else "live"


async def latest_waivers_for_gates(
    db: AsyncSession, tenant_id: int, gate_ids: list[int]
) -> dict[int, GateWaiver]:
    """The current waiver per gate — ONE query for the page, never one per row.

    Rows accumulate as history; the newest live row per gate is current.
    """
    if not gate_ids:
        return {}
    rows = (
        await db.execute(
            select(GateWaiver)
            .where(
                GateWaiver.tenant_id == tenant_id,
                GateWaiver.gate_id.in_(gate_ids),
                GateWaiver.deleted_at.is_(None),
            )
            .order_by(GateWaiver.gate_id, GateWaiver.id.desc())
        )
    ).scalars().all()
    latest: dict[int, GateWaiver] = {}
    for row in rows:
        latest.setdefault(row.gate_id, row)  # first seen per gate is the newest
    return latest
```

- [ ] **Step 4: Make `override_gate` write the record**

Extend the existing function in `release_gate_service.py`. It keeps setting `status = "overridden"` and keeps requiring notes — **the status transition is unchanged**; C2 adds the record, not a new state. Add keyword-only parameters `expires_at`, `remediation`, `approved_by_user_id` (defaulting to `user_id`), and `db.add(GateWaiver(...))` before the existing `publish_event`. Widen `ReleaseGateDecision` with the three optional fields.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_gate_waiver.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gate_waiver_service.py backend/app/services/release_gate_service.py \
        backend/app/api/v1/schemas/release_gate.py backend/tests/test_gate_waiver.py
git commit -m "feat(c2): waivers with approver, expiry and remediation"
```

---

### Task 4: Evidence CRUD

**Files:**
- Create: `backend/app/services/gate_evidence_service.py`
- Create: `backend/app/api/v1/schemas/gate_evidence.py`
- Modify: `backend/app/api/v1/releases.py` (add routes to the existing `gates_router`)
- Test: `backend/tests/test_gate_evidence.py`

**Interfaces:**
- Consumes: `GateEvidence` (Task 1).
- Produces: `list_evidence(db, gate_id, tenant_id) -> list[GateEvidence]`; `add_evidence(db, gate_id, tenant_id, user_id, data) -> GateEvidence`; `delete_evidence(db, evidence_id, tenant_id) -> None`; `evidence_for_gates(db, tenant_id, gate_ids) -> dict[int, list[GateEvidence]]`; schemas `GateEvidenceCreate`, `GateEvidenceRead`; routes `GET|POST /api/v1/gates/{gate_id}/evidence`, `DELETE /api/v1/gates/evidence/{evidence_id}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_gate_evidence.py
import pytest
from fastapi import HTTPException

from app.api.v1.schemas.gate_evidence import GateEvidenceCreate
from app.services import gate_evidence_service


@pytest.mark.asyncio
async def test_a_deployment_from_another_tenant_is_refused(
    db_session, test_tenant, test_user, gate, other_tenant_deployment
):
    with pytest.raises(HTTPException) as exc:
        await gate_evidence_service.add_evidence(
            db_session, gate.id, test_tenant.id, test_user.id,
            GateEvidenceCreate(
                kind="Test execution report", label="Regression run",
                url="https://ci.example/1", deployment_id=other_tenant_deployment.id,
            ),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_evidence_needs_no_deployment(db_session, test_tenant, test_user, gate):
    """A licence report or a runbook vouches for no particular deployment.
    requires_deployment_link is advisory — it shapes the verdict, it does not
    refuse the write."""
    row = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Runbook", label="Ops runbook", url="https://wiki/rb"),
    )
    assert row.deployment_id is None


@pytest.mark.asyncio
async def test_an_unlisted_kind_is_accepted(db_session, test_tenant, test_user, gate):
    """kind is free text. The UI offers the type's expected kinds; an unlisted
    one is accepted and simply satisfies no expectation."""
    row = await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Something bespoke", label="One-off", url=None),
    )
    assert row.kind == "Something bespoke"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_gate_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.v1.schemas.gate_evidence'`

- [ ] **Step 3: Write the schemas and service**

```python
# backend/app/api/v1/schemas/gate_evidence.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GateEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(..., max_length=150)
    label: str = Field(..., max_length=250)
    url: Optional[str] = Field(None, max_length=1000)
    notes: Optional[str] = None
    deployment_id: Optional[int] = None


class GateEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    kind: str
    label: str
    url: Optional[str]
    notes: Optional[str]
    deployment_id: Optional[int]
    added_by: int
    created_at: datetime
    # Computed per response, never stored — see stale_evidence_ids. Set
    # explicitly at every construction site, not by model_validate(row): a
    # required field guards a construction site, and a non-column attribute
    # would otherwise silently default.
    is_stale: bool = False
```

```python
# backend/app/services/gate_evidence_service.py (the CRUD half)
async def add_evidence(
    db: AsyncSession,
    gate_id: int,
    tenant_id: int,
    user_id: int,
    data: GateEvidenceCreate,
) -> GateEvidence:
    await release_gate_service.get_gate(db, gate_id, tenant_id)  # 404s if not ours

    if data.deployment_id is not None:
        # Validate ONLY that the deployment is in this tenant. Do NOT also
        # require it to belong to the gate's release: a QA sign-off legitimately
        # cites a deployment made under an earlier release into the same
        # environment, and refusing that would block real evidence.
        found = (
            await db.execute(
                select(Deployment.id).where(
                    Deployment.id == data.deployment_id,
                    Deployment.tenant_id == tenant_id,
                    Deployment.deleted_at.is_(None),
                )
            )
        ).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")

    row = GateEvidence(
        tenant_id=tenant_id, gate_id=gate_id, added_by=user_id, **data.model_dump()
    )
    db.add(row)
    await db.flush()
    return row


async def evidence_for_gates(
    db: AsyncSession, tenant_id: int, gate_ids: list[int]
) -> dict[int, list[GateEvidence]]:
    """ONCE PER RESPONSE, never once per row. A 50-gate page through the
    single-gate function is ~50 queries."""
    if not gate_ids:
        return {}
    rows = (
        await db.execute(
            select(GateEvidence)
            .where(
                GateEvidence.tenant_id == tenant_id,
                GateEvidence.gate_id.in_(gate_ids),
                GateEvidence.deleted_at.is_(None),
            )
            .order_by(GateEvidence.gate_id, GateEvidence.id)
        )
    ).scalars().all()
    grouped: dict[int, list[GateEvidence]] = {gid: [] for gid in gate_ids}
    for row in rows:
        grouped[row.gate_id].append(row)
    return grouped
```

`list_evidence` and `delete_evidence` follow the same shape: tenant-filtered, soft delete on `deleted_at`.

- [ ] **Step 4: Add the routes**

On the existing `gates_router` in `releases.py`. Any tenant member may add evidence; deletion is soft and open to the same. These are per-gate collections bounded by a gate's own structure, so no `pagination()` is required — note that in the route docstring so the next reader does not think it was forgotten.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_gate_evidence.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gate_evidence_service.py backend/app/api/v1/schemas/gate_evidence.py \
        backend/app/api/v1/releases.py backend/tests/test_gate_evidence.py
git commit -m "feat(c2): gate evidence linked to deployments"
```

---

### Task 5: Staleness

**Files:**
- Modify: `backend/app/services/gate_evidence_service.py`
- Test: `backend/tests/test_gate_evidence_staleness.py`

**Interfaces:**
- Consumes: `GateEvidence`, `Deployment`, `Build`.
- Produces: `stale_evidence_ids(db, tenant_id, evidence_rows) -> set[int]`, taking the evidence rows already loaded and returning the ids whose deployment has been superseded.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_gate_evidence_staleness.py
import pytest

from app.services.gate_evidence_service import stale_evidence_ids


@pytest.mark.asyncio
async def test_a_later_successful_deployment_makes_evidence_stale(
    db_session, test_tenant, evidence_on_build_41, deploy_build_42_successfully
):
    """The whole point of the deployment link. A QA sign-off recorded against
    build 41 and then quietly undermined by a hotfix deploying 42 is exactly the
    failure the paperwork exists to prevent."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert evidence_on_build_41.id in stale


@pytest.mark.asyncio
async def test_a_failed_redeploy_does_not_make_evidence_stale(
    db_session, test_tenant, evidence_on_build_41, deploy_build_42_and_fail
):
    """A failed redeploy must not invalidate evidence that still correctly
    describes what is running."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


@pytest.mark.asyncio
async def test_a_rolled_back_deployment_does_not_make_evidence_stale(
    db_session, test_tenant, evidence_on_build_41, deploy_build_42_and_roll_back
):
    """After a rollback, build 41 is what is running again — so evidence for 41
    is current, not stale. Only status == 'success' counts."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


@pytest.mark.asyncio
async def test_a_deployment_of_a_different_component_is_irrelevant(
    db_session, test_tenant, evidence_on_build_41, deploy_a_different_subsystem
):
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


@pytest.mark.asyncio
async def test_a_deployment_into_a_different_environment_is_irrelevant(
    db_session, test_tenant, evidence_on_build_41, deploy_same_build_to_another_env
):
    """Evidence is about a component in an environment. A later deploy of the
    same component into Production says nothing about the UAT sign-off."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_gate_evidence_staleness.py -v`
Expected: FAIL — `ImportError: cannot import name 'stale_evidence_ids'`

- [ ] **Step 3: Implement it in two queries, never per row**

```python
async def stale_evidence_ids(
    db: AsyncSession, tenant_id: int, evidence_rows: list[GateEvidence]
) -> set[int]:
    """Evidence ids whose deployment has been superseded.

    Evidence links deployment D — build of subsystem S into environment E at
    time T. It is STALE if a later SUCCESSFUL deployment of S into E exists.

    'success' exactly, not 'not failed': a rolled_back deployment means the
    build it carried is no longer what is running, so it must not supersede
    anything. Computed on read — a stored flag would be falsified by the next
    deployment webhook.
    """
    linked = [e for e in evidence_rows if e.deployment_id is not None]
    if not linked:
        return set()

    referenced = {
        row.id: row
        for row in (
            await db.execute(
                select(
                    Deployment.id,
                    Build.subsystem_id,
                    Deployment.environment_id,
                    Deployment.deployed_at,
                )
                .join(Build, Build.id == Deployment.build_id)
                .where(
                    Deployment.id.in_([e.deployment_id for e in linked]),
                    Deployment.tenant_id == tenant_id,
                )
            )
        ).all()
    }
    if not referenced:
        return set()

    pairs = {(r.subsystem_id, r.environment_id) for r in referenced.values()}
    latest_rows = (
        await db.execute(
            select(
                Build.subsystem_id,
                Deployment.environment_id,
                func.max(Deployment.deployed_at).label("latest"),
            )
            .join(Build, Build.id == Deployment.build_id)
            .where(
                Deployment.tenant_id == tenant_id,
                Deployment.deleted_at.is_(None),
                Deployment.status == "success",
                or_(*[
                    and_(Build.subsystem_id == s, Deployment.environment_id == e)
                    for s, e in pairs
                ]),
            )
            .group_by(Build.subsystem_id, Deployment.environment_id)
        )
    ).all()
    latest = {(r.subsystem_id, r.environment_id): r.latest for r in latest_rows}

    stale: set[int] = set()
    for evidence in linked:
        ref = referenced.get(evidence.deployment_id)
        if ref is None:
            continue
        newest = _utc(latest.get((ref.subsystem_id, ref.environment_id)))
        if newest is not None and newest > _utc(ref.deployed_at):
            stale.add(evidence.id)
    return stale
```

Note the `or_(and_(...))` pair filter rather than a tuple `IN`: SQLite has no row-value `IN` support to rely on, and this form compiles identically on both engines. Same reasoning as B6 decomposing `GREATEST`/`LEAST` rather than reaching for a dialect function.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_gate_evidence_staleness.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the whole backend suite on both engines**

Run: `cd backend && uv run pytest -q`
Then: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS on both.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gate_evidence_service.py backend/tests/test_gate_evidence_staleness.py
git commit -m "feat(c2): evidence goes stale when its deployment is superseded"
```

---

### Task 6: The evaluator

**Files:**
- Create: `backend/app/services/gate_readiness_service.py`
- Create: `backend/app/api/v1/schemas/gate_readiness.py`
- Test: `backend/tests/test_gate_readiness.py`

**Interfaces:**
- Consumes: `latest_waivers_for_gates` + `waiver_state` (Task 3), `evidence_for_gates` + `stale_evidence_ids` (Tasks 4–5).
- Produces: `evaluate(db, release_id, tenant_id, now=None) -> ReleaseReadinessResponse`; schemas `ReadinessBlocker`, `ReadinessWarning`, `ReleaseReadinessResponse` with fields `ok`, `release_id`, `checked_at`, `blockers`, `warnings`.

- [ ] **Step 1: Write the failing tests — one per row of the rules table**

```python
# backend/tests/test_gate_readiness.py
import pytest

from app.services import gate_readiness_service


@pytest.mark.asyncio
async def test_a_pending_block_gate_is_a_blocker(db_session, test_tenant, release, pending_block_gate):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is False
    assert [b.type for b in result.blockers] == ["gate_pending"]
    assert result.blockers[0].ref_id == pending_block_gate.id


@pytest.mark.asyncio
async def test_a_failed_gate_is_a_blocker(db_session, test_tenant, release, failed_gate):
    """A failure is not waived, it is failed. To waive it you override it."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert [b.type for b in result.blockers] == ["gate_failed"]


@pytest.mark.asyncio
async def test_an_overridden_gate_with_a_live_waiver_is_only_a_warning(
    db_session, test_tenant, release, overridden_gate_with_live_waiver
):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    assert [w.type for w in result.warnings] == ["gate_waived"]


@pytest.mark.asyncio
async def test_an_expired_waiver_makes_the_gate_unmet_again(
    db_session, test_tenant, release, overridden_gate_with_expired_waiver
):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is False
    assert [b.type for b in result.blockers] == ["waiver_expired"]


@pytest.mark.asyncio
async def test_a_legacy_override_with_no_waiver_row_warns(
    db_session, test_tenant, release, gate_overridden_before_c2
):
    """Gates overridden before C2 keep their status and have no waiver row.
    They must not become blockers on the day this ships."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    assert [w.type for w in result.warnings] == ["gate_waived_no_record"]


@pytest.mark.asyncio
async def test_an_untyped_gate_warns_and_never_blocks(
    db_session, test_tenant, release, untyped_pending_gate
):
    """gate_type_id ships nullable with no backfill, so EVERY gate in EVERY
    existing tenant is untyped until someone types it. Inventing 'block' would
    turn on a wall of blockers nobody configured."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    assert [w.type for w in result.warnings] == ["gate_untyped"]


@pytest.mark.asyncio
async def test_a_passed_gate_missing_expected_evidence_warns(
    db_session, test_tenant, release, passed_gate_expecting_two_kinds_with_one
):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    warning = next(w for w in result.warnings if w.type == "evidence_missing")
    assert "Defect summary" in warning.detail


@pytest.mark.asyncio
async def test_stale_evidence_warns_and_names_both_deployments(
    db_session, test_tenant, release, passed_gate_with_stale_evidence
):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    warning = next(w for w in result.warnings if w.type == "evidence_stale")
    assert warning.ref_id is not None
    assert result.ok is True


@pytest.mark.asyncio
async def test_ok_is_exactly_the_absence_of_blockers(
    db_session, test_tenant, release, pending_block_gate
):
    """ok is derived in one expression, mirroring preflight_service's
    `ok=len(blockers) == 0`. It cannot drift from blockers because it IS
    blockers."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok == (len(result.blockers) == 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_gate_readiness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.gate_readiness_service'`

- [ ] **Step 3: Write the schemas**

Mirror `preflight.py` exactly, including `ok`:

```python
# backend/app/api/v1/schemas/gate_readiness.py
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ReadinessBlocker(BaseModel):
    type: Literal["gate_pending", "gate_failed", "waiver_expired"]
    ref_kind: Literal["gate"]
    ref_id: int
    gate_name: str
    gate_type: Optional[str] = None
    detail: Optional[str] = None


class ReadinessWarning(BaseModel):
    type: Literal[
        "gate_waived",
        "gate_waived_no_record",
        "gate_untyped",
        "gate_pending",
        "gate_failed",
        "evidence_missing",
        "evidence_stale",
    ]
    ref_kind: Literal["gate", "evidence"]
    ref_id: int
    gate_name: str
    gate_type: Optional[str] = None
    detail: Optional[str] = None


class ReleaseReadinessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ok: bool
    release_id: int
    checked_at: datetime
    blockers: list[ReadinessBlocker]
    warnings: list[ReadinessWarning]
```

- [ ] **Step 4: Write the evaluator**

```python
# backend/app/services/gate_readiness_service.py
"""The ONE place the gate rules live.

The release detail panel and GET /api/v1/webhooks/release-ready both call
evaluate(), so they cannot disagree. A gate chip contradicting the endpoint a
pipeline obeys would be worse than neither.

NOTHING HERE REFUSES ANYTHING. A "block" behaviour makes a gate a blocker in
this response; it does not stop a transition, a booking or a deployment.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_readiness import (
    ReadinessBlocker,
    ReadinessWarning,
    ReleaseReadinessResponse,
)
from app.db.models.gate_type import GateType
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import gate_evidence_service, gate_waiver_service


async def evaluate(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    now: Optional[datetime] = None,
) -> ReleaseReadinessResponse:
    # ONE CLOCK decides every waiver state in this response. Called per row,
    # two gates in one payload could disagree about what day it is.
    now = now or datetime.now(timezone.utc)

    release = (
        await db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if release is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release not found")

    rows = (
        await db.execute(
            select(ReleaseGate, GateType)
            .outerjoin(GateType, GateType.id == ReleaseGate.gate_type_id)
            .where(
                ReleaseGate.release_id == release_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            )
            .order_by(ReleaseGate.due_date, ReleaseGate.id)
        )
    ).all()

    gate_ids = [g.id for g, _ in rows]
    # Three batch calls, ONCE PER RESPONSE — never once per row.
    waivers = await gate_waiver_service.latest_waivers_for_gates(db, tenant_id, gate_ids)
    evidence = await gate_evidence_service.evidence_for_gates(db, tenant_id, gate_ids)
    all_evidence = [e for items in evidence.values() for e in items]
    stale_ids = await gate_evidence_service.stale_evidence_ids(db, tenant_id, all_evidence)

    blockers: list[ReadinessBlocker] = []
    warnings: list[ReadinessWarning] = []

    for gate, gate_type in rows:
        type_name = gate_type.name if gate_type else None
        behaviour = gate_type.failure_behaviour if gate_type else None

        def blocker(kind: str, detail: str) -> None:
            blockers.append(ReadinessBlocker(
                type=kind, ref_kind="gate", ref_id=gate.id,
                gate_name=gate.name, gate_type=type_name, detail=detail,
            ))

        def warning(kind: str, detail: str, ref_id: Optional[int] = None) -> None:
            warnings.append(ReadinessWarning(
                type=kind, ref_kind="evidence" if ref_id else "gate",
                ref_id=ref_id or gate.id, gate_name=gate.name,
                gate_type=type_name, detail=detail,
            ))

        # FIRST MATCH WINS, in this order.
        if gate.status == "failed":
            # A failure is not waived, it is failed. To waive it you override it.
            blocker("gate_failed", "The gate was failed.")
        elif gate.status == "overridden":
            waiver = waivers.get(gate.id)
            if waiver is None:
                # Overridden before C2 shipped. These must NOT become blockers
                # on the day this deploys.
                warning("gate_waived_no_record", "Waived, no expiry recorded.")
            elif gate_waiver_service.waiver_state(waiver, now) == "expired":
                blocker("waiver_expired", "The waiver has expired; the gate is unmet again.")
            else:
                warning("gate_waived", f"Waived by user {waiver.approved_by_user_id}.")
        elif gate.status == "pending":
            if behaviour is None:
                # EVERY gate in EVERY existing tenant is untyped until someone
                # types it. Inventing "block" would turn on a wall of blockers
                # nobody configured.
                warning("gate_untyped", "No gate type set, so no behaviour was declared.")
            elif behaviour == "block":
                blocker("gate_pending", "The gate has not been decided.")
            else:
                warning("gate_pending", "The gate has not been decided.")

        # Evidence checks run regardless of gate status: a passed gate missing
        # its expected evidence is exactly the case worth surfacing.
        items = evidence.get(gate.id, [])
        if gate_type and gate_type.expected_evidence:
            supplied = {e.kind for e in items}
            missing = [k for k in gate_type.expected_evidence if k not in supplied]
            if missing:
                warning("evidence_missing", "Expected but not supplied: " + ", ".join(missing))
        for item in items:
            if item.id in stale_ids:
                warning(
                    "evidence_stale",
                    f"'{item.label}' vouches for a deployment that has since been superseded.",
                    ref_id=item.id,
                )

    return ReleaseReadinessResponse(
        # Derived in one expression, mirroring preflight_service. `ok` cannot
        # drift from `blockers` because it IS `blockers`.
        ok=len(blockers) == 0,
        release_id=release_id,
        checked_at=now,
        blockers=blockers,
        warnings=warnings,
    )
```

**Note the closure caveat:** `blocker` and `warning` capture `gate` and `type_name` from the enclosing loop iteration and are called within it, which is correct here. Do not hoist them out of the loop.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_gate_readiness.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gate_readiness_service.py backend/app/api/v1/schemas/gate_readiness.py \
        backend/tests/test_gate_readiness.py
git commit -m "feat(c2): the gate readiness evaluator"
```

---

### Task 7: The pipeline endpoint

**Files:**
- Create: `backend/app/api/v1/webhooks/release_ready.py`
- Modify: `backend/app/main.py:105-190`
- Modify: `backend/app/api/v1/releases.py` (a `GET /{release_id}/readiness` for the UI, JWT-authenticated)
- Test: `backend/tests/test_release_ready_endpoint.py`

**Interfaces:**
- Consumes: `gate_readiness_service.evaluate` (Task 6).
- Produces: `GET /api/v1/webhooks/release-ready?release_id=` (API-key, scope `webhooks:release`); `GET /api/v1/releases/{release_id}/readiness` (JWT).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_release_ready_endpoint.py
import pytest


@pytest.mark.asyncio
async def test_it_always_returns_200_even_when_blocked(client, api_key_headers, release_with_blocker):
    """HTTP status is not the gate — can_deploy.py's docstring states the
    contract and this endpoint inherits it. A pipeline reads the body."""
    resp = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={release_with_blocker.id}",
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert resp.json()["blockers"]


@pytest.mark.asyncio
async def test_a_key_without_the_release_scope_is_refused(client, deployment_only_api_key_headers, release):
    """A new scope, not a reuse of webhooks:deployment: reusing it would
    silently widen what every existing deployment key can read to include
    waiver reasons, approver names and evidence URLs."""
    resp = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={release.id}", headers=deployment_only_api_key_headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_release_in_another_tenant_is_404(client, api_key_headers, other_tenant_release):
    resp = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={other_tenant_release.id}", headers=api_key_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_ui_route_and_the_pipeline_route_agree(
    client, auth_headers, api_key_headers, release_with_blocker
):
    """One evaluator, two surfaces. A gate chip contradicting the endpoint a
    pipeline obeys would be worse than neither."""
    ui = await client.get(f"/api/v1/releases/{release_with_blocker.id}/readiness", headers=auth_headers)
    pipeline = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={release_with_blocker.id}", headers=api_key_headers
    )
    assert ui.json()["ok"] == pipeline.json()["ok"]
    assert [b["ref_id"] for b in ui.json()["blockers"]] == [
        b["ref_id"] for b in pipeline.json()["blockers"]
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_release_ready_endpoint.py -v`
Expected: FAIL — 404 on both routes

- [ ] **Step 3: Write the webhook route**

```python
# backend/app/api/v1/webhooks/release_ready.py
"""GET /api/v1/webhooks/release-ready — release gate readiness.

Read-only advisory endpoint answering "are this release's gates satisfied?".
EnvManager never refuses a deployment; it answers a question the pipeline chose
to ask, and the pipeline enforces.

Auth via the `webhooks:release` API-key scope — deliberately NOT
`webhooks:deployment`, which would silently widen what every existing
deployment key can read to include governance detail. Always returns 200 OK
with a structured body: HTTP status is not the gate.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.gate_readiness import ReleaseReadinessResponse
from app.core.security import api_key_auth
from app.db.base import get_db
from app.services import gate_readiness_service

router = APIRouter()


@router.get("/release-ready", response_model=ReleaseReadinessResponse)
async def release_ready(
    release_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    api_key=Depends(api_key_auth(required_scope="webhooks:release")),
):
    return await gate_readiness_service.evaluate(db, release_id, api_key.tenant_id)
```

- [ ] **Step 4: Mount it and add the UI route**

In `main.py`, import beside `webhook_can_deploy_router` and include with `prefix="/api/v1/webhooks"`, `tags=["webhooks"]`. In `releases.py`, add `GET /{release_id}/readiness` calling the same `evaluate`. **Register it before any `/{release_id}/...` catch-all that could swallow it** — B6 lost a red-run afternoon to `GET /{booking_id}` capturing a literal segment and 422ing on int coercion.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_release_ready_endpoint.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/webhooks/release_ready.py backend/app/main.py \
        backend/app/api/v1/releases.py backend/tests/test_release_ready_endpoint.py
git commit -m "feat(c2): release-ready endpoint for deployment pipelines"
```

---

### Task 8: The guard — C2 advises, it never blocks

**Files:**
- Create: `backend/tests/test_c2_advises_never_blocks.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the guard**

```python
# backend/tests/test_c2_advises_never_blocks.py
"""C2 ADVISES; IT NEVER BLOCKS.

The guard on the whole design, in the line of A3, A4, B2 and B4. If any of
these fails, C2 has started acting and the spec is no longer true.
"""
import pytest


@pytest.mark.asyncio
async def test_a_release_with_a_failed_block_gate_still_transitions(
    client, auth_headers, release_with_failed_block_gate
):
    resp = await client.post(
        f"/api/v1/releases/{release_with_failed_block_gate.id}/transition",
        json={"to_state": "in_progress"}, headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_can_deploy_answers_identically_with_and_without_gate_state(
    client, api_key_headers, environment, subsystem, release_with_failed_block_gate
):
    """can-deploy is UNTOUCHED — not one blocker, not one warning."""
    before = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.slug}"
        f"&subsystem_slug={subsystem.slug}", headers=api_key_headers,
    )
    after = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.slug}"
        f"&subsystem_slug={subsystem.slug}&release_id={release_with_failed_block_gate.id}",
        headers=api_key_headers,
    )
    assert before.json()["blockers"] == after.json()["blockers"]
    assert before.json()["warnings"] == after.json()["warnings"]


@pytest.mark.asyncio
async def test_a_gate_can_still_be_passed_with_open_criteria_and_no_evidence(
    client, auth_headers, gate_expecting_evidence_with_open_criteria
):
    """C2 does not tighten pass_gate. Missing evidence is a WARNING in the
    verdict, never a refusal at the write."""
    resp = await client.post(
        f"/api/v1/gates/{gate_expecting_evidence_with_open_criteria.id}/pass",
        json={"notes": "signed off"}, headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_a_booking_is_unaffected_by_gate_state(
    client, auth_headers, environment, booking_type, release_with_failed_block_gate
):
    """Gate state reaches nothing outside the release page."""
    resp = await client.post(
        "/api/v1/booking-requests",
        json={
            "environment_ids": [environment.id],
            "booking_type_id": booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-02T17:00:00Z",
            "purpose": "unaffected by gates",
            "release_id": release_with_failed_block_gate.id,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
```

- [ ] **Step 2: Run it — it must pass immediately**

Run: `cd backend && uv run pytest tests/test_c2_advises_never_blocks.py -v`
Expected: PASS (4 tests). It passes on the first run by construction — which is exactly why the next step is not optional.

- [ ] **Step 3: Prove it is not vacuous**

An absence test nobody has tried to break is not evidence of anything. Temporarily insert a real refusal into the release transition path — raise `HTTPException(409)` when the release has a failed `block` gate — and run the file again.

Run: `cd backend && uv run pytest tests/test_c2_advises_never_blocks.py -v`
Expected: **FAIL** on `test_a_release_with_a_failed_block_gate_still_transitions`. Then revert the mutation and confirm it passes again. Record both outcomes in the commit message.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_c2_advises_never_blocks.py
git commit -m "test(c2): the guard — C2 advises, it never blocks

Proved non-vacuous: inserting a 409 into the release transition path
fails the first test; reverting it passes again."
```

---

### Task 9: Frontend — Gate Types admin panel

**Files:**
- Create: `frontend/src/services/gateTypeService.ts`
- Create: `frontend/src/store/gateTypeSlice.ts`
- Create: `frontend/src/components/admin/GateTypesPanel.tsx`
- Modify: `frontend/src/store/index.ts`
- Modify: the admin page that renders `EnvironmentTiersPanel` (add the tab)
- Test: `frontend/src/components/admin/__tests__/gateTypesPanel.test.tsx`

**Interfaces:**
- Consumes: `/api/v1/gate-types` (Task 2).
- Produces: `fetchGateTypes`, `createGateType`, `updateGateType`, `deleteGateType` thunks.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/admin/__tests__/gateTypesPanel.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AxiosError } from 'axios';

describe('GateTypesPanel', () => {
  it('shows the server reason when a save is refused, not the HTTP status', async () => {
    // A duplicate-name 409. Mocking a plain Error here would pass while the
    // app shows "Request failed with status code 409" — mock the AxiosError
    // shape so response.data.detail exists to be read.
    const err = new AxiosError('Request failed with status code 409');
    (err as any).response = { status: 409, data: { detail: 'A gate type named Security already exists' } };
    api.post = vi.fn().mockRejectedValue(err);

    render(<GateTypesPanel />);
    await userEvent.click(screen.getByRole('button', { name: /new gate type/i }));
    await userEvent.type(screen.getByLabelText(/name/i), 'Security');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText(/already exists/i)).toBeInTheDocument();
    });
  });

  it('renders the expected-evidence kinds as an editable list', async () => {
    render(<GateTypesPanel />);
    await waitFor(() => {
      expect(screen.getByText('Test execution report')).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/gateTypesPanel.test.tsx`
Expected: FAIL — cannot resolve `GateTypesPanel`

- [ ] **Step 3: Build the service, slice and panel**

Model on `EnvironmentTiersPanel.tsx` and its slice. Every mutating thunk ends `rejectWithValue(formatApiError(err))` and the panel reads `result.payload`. `expected_evidence` edits as a chip list. `failure_behaviour` is a three-value select — label them "Blocks (advisory)", "Warns" and "Accept with exception", and put a line under the control saying **no gate refuses a deployment; the label describes how it reads in the readiness verdict**. Without it the word "Blocks" is a straightforward lie about what the product does.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/gateTypesPanel.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/gateTypeService.ts frontend/src/store/gateTypeSlice.ts \
        frontend/src/store/index.ts frontend/src/components/admin/GateTypesPanel.tsx \
        frontend/src/components/admin/__tests__/gateTypesPanel.test.tsx
git commit -m "feat(c2): gate types admin panel"
```

---

### Task 10: Frontend — the gates panel

**Files:**
- Modify: `frontend/src/components/releases/GatesTable.tsx`
- Create: `frontend/src/components/releases/GateEvidenceList.tsx`
- Create: `frontend/src/components/releases/AddEvidenceDialog.tsx`
- Create: `frontend/src/components/releases/WaiverDialog.tsx`
- Create: `frontend/src/components/releases/ReadinessBanner.tsx`
- Test: `frontend/src/components/releases/__tests__/gateEvidence.test.tsx`

**Interfaces:**
- Consumes: evidence and waiver routes (Tasks 3–4), `GET /api/v1/releases/{id}/readiness` (Task 7).

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/releases/__tests__/gateEvidence.test.tsx
describe('C2 advises; it never blocks', () => {
  it('renders the pass control on a gate with a failed block type', async () => {
    // The UI half of the backend guard. A reviewer gated TransitionButtons on
    // A3's gap and watched 50 page tests pass, because the fixture returned no
    // allowed transitions — so assert the control is THERE, on a fixture where
    // it would otherwise render.
    render(<GatesTable gates={[failedBlockGate]} allowedTransitions={['pass']} />);
    expect(screen.getByRole('button', { name: /pass/i })).toBeEnabled();
  });
});

describe('AddEvidenceDialog', () => {
  it('offers the type\'s expected kinds but still accepts an unlisted one', async () => {
    render(<AddEvidenceDialog gate={gateExpectingTwoKinds} open onClose={vi.fn()} />);
    await userEvent.click(screen.getByLabelText(/kind/i));
    expect(screen.getByText('Test execution report')).toBeInTheDocument();

    // Free-solo: the backend accepts any string, so the control must too.
    await userEvent.type(screen.getByLabelText(/kind/i), 'Something bespoke');
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('/evidence'),
      expect.objectContaining({ kind: 'Something bespoke' }),
    );
  });

  it('does not refuse evidence with no deployment', async () => {
    render(<AddEvidenceDialog gate={gateRequiringDeploymentLink} open onClose={vi.fn()} />);
    await userEvent.type(screen.getByLabelText(/label/i), 'Ops runbook');
    // requires_deployment_link is a HINT, not a validation error.
    expect(screen.getByRole('button', { name: /add/i })).toBeEnabled();
  });
});

describe('GateEvidenceList', () => {
  it('marks stale evidence and names the superseding deployment', async () => {
    render(<GateEvidenceList evidence={[staleEvidence]} />);
    expect(screen.getByText(/superseded/i)).toBeInTheDocument();
  });

  it('shows a waiver expiry as a date, and is not overdue on the day itself', () => {
    // A DEADLINE IS A DAY. formatExpiry reported "overdue by 1 day" throughout
    // the day a thing expired; use expiryDayDelta/isExpiryOverdue from
    // utils/dates.ts, never a floored millisecond delta.
    render(<WaiverChip expiresAt={todayAtMidnightUtc} />);
    expect(screen.queryByText(/overdue/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/releases/__tests__/gateEvidence.test.tsx`
Expected: FAIL — cannot resolve `GateEvidenceList`

- [ ] **Step 3: Build the components**

`GatesTable` gains a type chip and a waiver chip. `GateEvidenceList` renders kind, label, link and the deployment it vouches for, with a "superseded" marker on stale rows. `WaiverDialog` replaces the bare override-notes prompt with reason, approver, expiry and remediation. `ReadinessBanner` renders the `/readiness` blockers and warnings at the top of the release page — and **must say plainly that it advises**, since nothing it lists prevents anything.

`AddEvidenceDialog` is the one that makes the rest reachable — without it evidence can only be added through the API, which is the "built it and connected it to nothing" defect B5 shipped four times. It takes:

- **Kind** — a free-solo autocomplete seeded from the gate type's `expected_evidence`, so the expected kinds are one click away but an unlisted kind can still be typed. A plain select would contradict the backend, which accepts any string.
- **Label** and **URL**.
- **Deployment** — an autocomplete over the release's own deployments, showing component, build number and environment (`Payments · build 412 · UAT · 14 Aug`). Optional, and clearly marked so: a runbook or a licence report vouches for no particular deployment. Where the gate's type sets `requires_deployment_link`, show a hint that evidence without one will be flagged — a **hint, not a validation error**, because the backend does not refuse it.

Fetch the deployment options through the existing `useSharedList`-style hook rather than a bare effect, so opening the dialog on a page that already lists deployments does not issue a duplicate GET.

Dates through `expiryDayDelta`/`isExpiryOverdue` in `utils/dates.ts`. Any new grid column namespaces custom fields `cf_<key>`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/releases/__tests__/gateEvidence.test.tsx`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the whole frontend suite**

Run: `cd frontend && npm test`
Expected: PASS. This is the third suite, not an afterthought — a regression once survived six verification steps because every one ran targeted files.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/releases/
git commit -m "feat(c2): gate types, evidence and waivers on the release page"
```

---

### Task 11: Open the pages, then document

**Files:**
- Modify: `docs/admin-guide.md`, `docs/user-guide.md`, `docs/plan.md`, `CLAUDE.md`
- Create: `docs/phases/phase-9.md`

- [ ] **Step 1: Open the app and use the feature**

Run the stack, log in as `admin` / `admin123` (tenant `demo`), and walk the whole journey: seed types appear in the admin panel; type an existing gate; add evidence linked to a deployment; deploy that component again and watch the evidence go stale; waive a failed gate with an expiry; call `release-ready` with `curl` and an API key holding the new scope.

**This step is not a formality.** Six defects on the pagination programme were found only by opening the page with a fully green suite, and B5 shipped four "built it and connected it to nothing" defects that no test caught because nothing called the code. For every new field, thunk and column, ask **what consumes this?**

- [ ] **Step 2: Write `docs/phases/phase-9.md`**

Record C2 as complete, the C1–C9 decomposition from the spec's §9, and the two open questions the spec deliberately leaves: whether a Stable Window becomes a `can-deploy` blocker (C9's call), and gate approver permissions (Phase 12, waiting on RBAC/OAuth).

- [ ] **Step 3: Update the guides and the roadmap**

Admin guide: the Gate Types panel, what `failure_behaviour` does and does not do, and **the deploy step** — existing tenants need `seed_gate_type_defaults_for_tenant` run, or they have no vocabulary and the feature reads as broken. User guide: evidence, staleness, waivers, and the `release-ready` endpoint with a worked `curl` example. `docs/plan.md`: Phase 9 row to 🟡 In progress. `CLAUDE.md`: a banner block in the established shape — what C2 established and what will bite if forgotten.

- [ ] **Step 4: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs(c2): phase 9 doc, guides and roadmap"
```

---

## Verification Before Done

- [ ] Backend suite green on **SQLite**
- [ ] Backend suite green on **PostgreSQL**
- [ ] Frontend suite green
- [ ] `test_c2_advises_never_blocks.py` proved non-vacuous by mutation, both outcomes recorded
- [ ] Mutation pass on the new tenant filters: drop each `tenant_id` filter in turn and confirm a named test fails. A1 shipped eight unguarded ones that no pre-existing test caught
- [ ] Every page opened in a browser, every new control used
