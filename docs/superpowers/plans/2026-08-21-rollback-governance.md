# Phase 9 C4 — Rollback Governance: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record how a release could be undone — a rollback plan per changing component, a reversibility rollup, an authorisation record when a rollback happens, and a rehearsal record per system — and fold all four into the existing readiness verdict.

**Architecture:** Four additive tables and no new columns on existing entities. C2's `gate_readiness_service` is renamed `release_readiness_service` and gains five rollback findings alongside its gate ones, so there remains exactly ONE verdict served to both the UI and deployment pipelines. Two per-tenant policy flags decide whether a finding is a blocker or a warning; both default off.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic (hand-written DDL), Pydantic v2, pytest (dual engine), React 18 + TypeScript + MUI + Redux Toolkit, vitest.

**Spec:** [../specs/2026-08-21-rollback-governance-design.md](../specs/2026-08-21-rollback-governance-design.md)

## Global Constraints

- **C4 RECORDS AND NEVER REFUSES.** No code in this plan may raise, 409, or return `False` from any existing guard on the basis of rollback state. The only permitted refusals are input validation on C4's own writes (422 on a bad payload, 404 on a cross-tenant or unknown id). `backend/tests/test_c4_records_never_refuses.py` (Task 8) is the guard.
- **Enum columns are plain VARCHAR** (`native_enum=False` semantics) — PostgreSQL native ENUMs break the SQLite leg.
- **Every query on a tenant-scoped table filters `tenant_id`**, from `current_user.active_tenant_id` (NOT `.tenant_id` — impersonation). Assume every filter is unguarded until a named test fails without it; prove new ones by mutation and report both outcomes.
- **Never call `db.commit()` in a service** — `get_db()` auto-commits. Use `db.flush()`.
- **Soft deletes only** (`deleted_at`), never hard `DELETE`.
- **Migrations are hand-written**: `alembic revision -m "..."` then write DDL by hand. NEVER `--autogenerate` (it produces empty migrations because `init_db()` calls `create_all`). Migrations live in **`backend/app/db/migrations/versions/`**, not `backend/alembic/`. `Base` supplies `created_at`/`updated_at` — include them on every `CREATE TABLE`, with `server_default=sa.func.now()`, or ORM inserts hit NOT NULL violations.
- **One clock per response.** Resolve `now` once and reuse it; called per row, two components could disagree about what day it is.
- **Batch once per response**, never once per component.
- **Frontend mutating thunks** use `rejectWithValue(formatApiError(err))` and callers read `result.payload`. Mock an `AxiosError` shape with `response.data.detail` in tests — a plain `Error` carrying the final text passes while the app is broken.
- **MUI:** `<Select aria-label=...>` puts the label on the root node, not the `role="combobox"` element. Use `inputProps={{ 'aria-label': ... }}`.
- **Testing cadence:** run TARGETED test files in the FOREGROUND. Do NOT run the full backend suite (~17 min SQLite / ~43 min PostgreSQL) — the controller runs it at checkpoints. NEVER use `run_in_background`, never poll, never `sleep`. Targeted files on PostgreSQL are cheap: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest <file> -q`.
- **The frontend gate is `npm run lint` AND `npx vitest run` AND `npm run build`** — not vitest and `tsc` alone. `npm run lint` runs `--report-unused-disable-directives --max-warnings 0`, so an *unnecessary* eslint-disable is a hard error. CI failed C2's merge commit on exactly that.

---

### Task 1: Schema — four tables, one migration, policy seeding

**Files:**
- Create: `backend/app/db/models/rollback.py` (all four models — they change together)
- Create: `backend/app/services/rollback_policy_service.py`
- Create: `backend/app/db/migrations/versions/<rev>_rollbackgov.py`
- Modify: `backend/app/db/models/__init__.py`
- Modify: `backend/app/services/tenant_service.py`
- Test: `backend/tests/test_rollback_policy.py`

**Interfaces:**
- Produces: models `ReleaseRollbackPlan`, `ReleaseRollbackAuthorisation`, `RollbackRehearsal`, `RollbackPolicy`; `get_or_create_policy(db, tenant_id) -> RollbackPolicy`; constants `REVERSIBILITY_VALUES = ("reversible", "lossy", "irreversible")` and `REHEARSAL_OUTCOMES = ("passed", "failed", "partial")`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rollback_policy.py
import pytest
from sqlalchemy import select

from app.db.models.rollback import RollbackPolicy
from app.services.rollback_policy_service import get_or_create_policy


@pytest.mark.asyncio
async def test_an_unseeded_tenant_gets_defaults_not_an_error(db_session, test_tenant):
    """An unseeded tenant must behave as defaults rather than erroring — that is
    what makes this feature need NO deploy step, unlike B3b's envrequests."""
    policy = await get_or_create_policy(db_session, test_tenant.id)
    assert policy.require_rollback_plan is False
    assert policy.require_current_rehearsal is False
    assert policy.rehearsal_validity_days == 90


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session, test_tenant):
    first = await get_or_create_policy(db_session, test_tenant.id)
    await db_session.flush()
    second = await get_or_create_policy(db_session, test_tenant.id)
    await db_session.flush()
    assert first.id == second.id
    rows = (
        await db_session.execute(
            select(RollbackPolicy).where(RollbackPolicy.tenant_id == test_tenant.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_policy_from_another_tenant_is_not_returned(db_session, test_tenant, other_tenant):
    mine = await get_or_create_policy(db_session, test_tenant.id)
    theirs = await get_or_create_policy(db_session, other_tenant.id)
    await db_session.flush()
    assert mine.id != theirs.id
    assert mine.tenant_id == test_tenant.id
```

If no `other_tenant` fixture exists, build one locally in the test file — `backend/tests/test_gate_evidence.py` has the precedent. Do NOT use the `tenant` fixture together with `auth_headers`: `tenant` creates a DIFFERENT tenant ("Phase3 Org") from `test_tenant` ("Test Org"), and mixing them makes tests pass vacuously.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_rollback_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.rollback'`

- [ ] **Step 3: Write the four models**

```python
# backend/app/db/models/rollback.py
"""Phase 9 C4 — rollback governance.

Four tables that change together, so they live together: the per-component
plan, the authorisation raised when a rollback actually happens, the per-system
rehearsal, and the per-tenant policy that decides whether a missing plan is a
blocker or a warning in the readiness verdict.

NOTHING HERE REFUSES ANYTHING. C4 records; CI executes rollbacks.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Fixed, NOT tenant-configurable. Reversibility is a property of a database
# migration, not of a tenant's process — and the rollup in
# release_readiness_service orders these three, which a tenant-defined
# vocabulary could not support.
REVERSIBILITY_VALUES = ("reversible", "lossy", "irreversible")
REHEARSAL_OUTCOMES = ("passed", "failed", "partial")


class ReleaseRollbackPlan(Base):
    """How ONE component of a release would be rolled back.

    Per (release, system) rather than per release, because rollback is rarely
    uniform: a stateless API reverts by redeploying the previous artefact where
    a schema migration may be one-way.
    """

    __tablename__ = "release_rollback_plan"
    __table_args__ = (
        UniqueConstraint("release_id", "system_id", name="uq_rollback_plan_release_system"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    steps: Mapped[str] = mapped_column(Text, nullable=False)
    # reversible | lossy | irreversible. `lossy` is the value that earns its
    # place: teams say "reversible" when they mean "reversible if you accept
    # losing an hour of writes", and that is the distinction a sponsor needs.
    reversibility: Mapped[str] = mapped_column(String(20), nullable=False)
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # BOTH NULLABLE, and the distinction is load-bearing: §2.11 asks for a plan
    # AGREED before deploy, so "written" and "agreed" are two states and an
    # unagreed draft is legitimate.
    agreed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    agreed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReleaseRollbackAuthorisation(Base):
    """The record of a rollback decision — raisable BEFORE OR AFTER the fact.

    Deliberately not attached to `Deployment`: a rollback may span several
    deployments, and the CI webhook that flips one to `rolled_back` knows the
    what but never the why.
    """

    __tablename__ = "release_rollback_authorisation"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decided_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # A JSON list of system ids, not a junction table: the set is small and is
    # never queried from the system side. Same storage choice as
    # gate_type.expected_evidence and build.jira_tickets.
    system_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RollbackRehearsal(Base):
    """Evidence that rolling back a SYSTEM has actually been tried.

    Per system, not per release: one rehearsal serves every release touching
    that system until it goes stale. Rows accumulate as history; the latest is
    current — the shape gate_waiver uses. Freshness is COMPUTED on read.
    """

    __tablename__ = "rollback_rehearsal"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    rehearsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rehearsed_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RollbackPolicy(Base):
    """One row per tenant, shaped like RaidConfig.

    BOTH REQUIREMENTS DEFAULT OFF. Every release predating C4 has no plans, so
    blocking on day one would redden the whole estate and teach everyone to
    ignore the banner — the lesson C2's untyped gates and B5's idle detection
    both paid for.
    """

    __tablename__ = "rollback_policy"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True, unique=True
    )
    require_rollback_plan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_current_rehearsal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rehearsal_validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
```

- [ ] **Step 4: Register the models**

Add to `backend/app/db/models/__init__.py`, following the existing import style:

```python
from app.db.models.rollback import (  # noqa: F401
    ReleaseRollbackPlan,
    ReleaseRollbackAuthorisation,
    RollbackRehearsal,
    RollbackPolicy,
)
```

- [ ] **Step 5: Write the policy service**

```python
# backend/app/services/rollback_policy_service.py
"""Per-tenant rollback policy — get-or-create with defaults.

Modelled on raid_config_service.seed_default_config, which is already
get-or-create. Because an unseeded tenant simply gets defaults, C4 needs NO
deploy step — unlike B3b's envrequests, and unlike what C2's docs initially
and wrongly claimed.
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.rollback import RollbackPolicy

DEFAULT_REHEARSAL_VALIDITY_DAYS = 90


async def get_or_create_policy(db: AsyncSession, tenant_id: int) -> RollbackPolicy:
    """Return this tenant's policy, creating it with defaults if absent."""
    existing = (
        await db.execute(
            select(RollbackPolicy).where(RollbackPolicy.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    policy = RollbackPolicy(
        tenant_id=tenant_id,
        require_rollback_plan=False,
        require_current_rehearsal=False,
        rehearsal_validity_days=DEFAULT_REHEARSAL_VALIDITY_DAYS,
    )
    db.add(policy)
    await db.flush()
    return policy


async def update_policy(
    db: AsyncSession,
    tenant_id: int,
    *,
    require_rollback_plan: Optional[bool] = None,
    require_current_rehearsal: Optional[bool] = None,
    rehearsal_validity_days: Optional[int] = None,
) -> RollbackPolicy:
    """Patch semantics: an omitted argument means "leave alone"."""
    policy = await get_or_create_policy(db, tenant_id)
    if require_rollback_plan is not None:
        policy.require_rollback_plan = require_rollback_plan
    if require_current_rehearsal is not None:
        policy.require_current_rehearsal = require_current_rehearsal
    if rehearsal_validity_days is not None:
        if rehearsal_validity_days < 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "rehearsal_validity_days must be at least 1",
            )
        policy.rehearsal_validity_days = rehearsal_validity_days
    await db.flush()
    return policy
```

- [ ] **Step 6: Seed the policy on tenant creation**

In `backend/app/services/tenant_service.py`, beside the other seeding calls (`raid_config_service.seed_default_config` is at line ~54):

```python
from app.services.rollback_policy_service import get_or_create_policy as get_or_create_rollback_policy
...
    await get_or_create_rollback_policy(db, tenant.id)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_rollback_policy.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Write the migration**

Run `cd backend && alembic revision -m "rollbackgov"`, then write the DDL by hand in `backend/app/db/migrations/versions/`. Read the `gatetypes` migration first and follow its shape.

```python
def upgrade() -> None:
    op.create_table(
        "release_rollback_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=False, index=True),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("reversibility", sa.String(20), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("agreed_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("release_id", "system_id", name="uq_rollback_plan_release_system"),
    )
    op.create_table(
        "release_rollback_authorisation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("system_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "rollback_rehearsal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=False, index=True),
        sa.Column("rehearsed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rehearsed_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "rollback_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True, unique=True),
        sa.Column("require_rollback_plan", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_current_rehearsal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rehearsal_validity_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("rollback_policy")
    op.drop_table("rollback_rehearsal")
    op.drop_table("release_rollback_authorisation")
    op.drop_table("release_rollback_plan")
```

**No backfill of any kind.** Existing tenants get their policy lazily via `get_or_create_policy`; existing releases legitimately have no plans.

- [ ] **Step 9: Verify the migration on a scratch database**

Do NOT run `alembic downgrade -1` against the dev database — it steps back from the current head, not from your revision, and has previously dropped an unrelated table.

```bash
docker exec envmgr-postgres psql -U envmgr -d postgres -c "DROP DATABASE IF EXISTS envmgr_migtest;" -c "CREATE DATABASE envmgr_migtest OWNER envmgr;"
cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_migtest uv run alembic upgrade head
```
Expected: the chain runs clean to your new revision. Then inspect the four tables and confirm `created_at`/`updated_at` are present on each. Also run `uv run pytest tests/test_migration_schema_drift.py -q` — but note it compares **column name sets only**, not types or defaults, so its passing is not evidence the migration matches the models. Eyeball the types by hand.

- [ ] **Step 10: Commit**

```bash
git add backend/app/db/models/rollback.py backend/app/db/models/__init__.py \
        backend/app/services/rollback_policy_service.py backend/app/services/tenant_service.py \
        backend/app/db/migrations/versions/ backend/tests/test_rollback_policy.py
git commit -m "feat(c4): rollback governance schema and per-tenant policy"
```

---

### Task 2: Rollback plan CRUD

**Files:**
- Create: `backend/app/services/rollback_plan_service.py`
- Create: `backend/app/api/v1/schemas/rollback.py`
- Modify: `backend/app/api/v1/releases.py`
- Test: `backend/tests/test_rollback_plan.py`
- Test: `backend/tests/integration/test_rollback_plan_api.py`

**Interfaces:**
- Consumes: `ReleaseRollbackPlan`, `REVERSIBILITY_VALUES` (Task 1).
- Produces: `list_plans(db, release_id, tenant_id) -> list[ReleaseRollbackPlan]`; `upsert_plan(db, release_id, tenant_id, user_id, data) -> ReleaseRollbackPlan`; `agree_plan(db, plan_id, tenant_id, user_id) -> ReleaseRollbackPlan`; `delete_plan(db, plan_id, tenant_id) -> None`; `plans_for_releases(db, tenant_id, release_ids) -> dict[int, list[ReleaseRollbackPlan]]`; schemas `RollbackPlanCreate`, `RollbackPlanRead`; routes under `/api/v1/releases/{release_id}/rollback-plans`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_rollback_plan.py
import pytest
from fastapi import HTTPException

from app.api.v1.schemas.rollback import RollbackPlanCreate
from app.services import rollback_plan_service


@pytest.mark.asyncio
async def test_a_plan_is_upserted_per_release_and_system(
    db_session, test_tenant, test_user, release, system
):
    first = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="Redeploy previous artefact",
                           reversibility="reversible"),
    )
    second = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="Redeploy, then replay the queue",
                           reversibility="lossy"),
    )
    assert first.id == second.id, "a second write for the same pair must update, not duplicate"
    assert second.steps == "Redeploy, then replay the queue"
    assert second.reversibility == "lossy"


@pytest.mark.asyncio
async def test_a_written_plan_is_not_an_agreed_plan(
    db_session, test_tenant, test_user, release, system
):
    """'Written' and 'agreed' are two states. An unagreed draft is legitimate."""
    plan = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(system_id=system.id, steps="s", reversibility="reversible"),
    )
    assert plan.agreed_by_user_id is None and plan.agreed_at is None

    agreed = await rollback_plan_service.agree_plan(
        db_session, plan.id, test_tenant.id, test_user.id
    )
    assert agreed.agreed_by_user_id == test_user.id
    assert agreed.agreed_at is not None


@pytest.mark.asyncio
async def test_a_system_outside_the_release_is_refused(
    db_session, test_tenant, test_user, release, unrelated_system
):
    """A plan may only name a system the release actually touches."""
    with pytest.raises(HTTPException) as exc:
        await rollback_plan_service.upsert_plan(
            db_session, release.id, test_tenant.id, test_user.id,
            RollbackPlanCreate(system_id=unrelated_system.id, steps="s",
                               reversibility="reversible"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_release_in_another_tenant_is_refused(
    db_session, test_tenant, test_user, other_tenant_release, system
):
    with pytest.raises(HTTPException) as exc:
        await rollback_plan_service.upsert_plan(
            db_session, other_tenant_release.id, test_tenant.id, test_user.id,
            RollbackPlanCreate(system_id=system.id, steps="s", reversibility="reversible"),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_reversibility_is_rejected_by_the_schema():
    with pytest.raises(Exception):
        RollbackPlanCreate(system_id=1, steps="s", reversibility="probably_fine")
```

Build the `release`, `system` and `unrelated_system` fixtures locally in the test file, following `backend/tests/test_release_gate_typing.py`. `unrelated_system` must be a system in the SAME tenant that is NOT on the release's `release_system` rows — otherwise the 404 could come from the tenant filter rather than the membership check, and the test proves the wrong thing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_rollback_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.v1.schemas.rollback'`

- [ ] **Step 3: Write the schemas**

```python
# backend/app/api/v1/schemas/rollback.py
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Reversibility = Literal["reversible", "lossy", "irreversible"]
RehearsalOutcome = Literal["passed", "failed", "partial"]


class RollbackPlanCreate(BaseModel):
    # extra="forbid" so a typo'd key is a 422 rather than a silent drop — the
    # POST /projects dropping priority_rank class of bug.
    model_config = ConfigDict(extra="forbid")

    system_id: int
    steps: str = Field(..., min_length=1)
    reversibility: Reversibility
    estimated_minutes: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None


class RollbackPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    release_id: int
    system_id: int
    system_name: Optional[str] = None
    steps: str
    reversibility: str
    estimated_minutes: Optional[int]
    notes: Optional[str]
    agreed_by_user_id: Optional[int]
    agreed_by_username: Optional[str] = None
    agreed_at: Optional[datetime]
```

- [ ] **Step 4: Write the service**

`upsert_plan` validates in this order: the release is in the caller's tenant (404 if not), then the system is on that release's `release_system` rows (404 if not). Then it selects an existing row for `(release_id, system_id)` with `deleted_at IS NULL` and updates it, or creates one.

**Do not re-agree on update.** When `upsert_plan` changes an existing row's `steps` or `reversibility`, clear `agreed_by_user_id`/`agreed_at` — a plan agreed by a sponsor and then rewritten is no longer the plan they agreed to. Say so in a comment; this is the kind of rule that gets "tidied" away.

`plans_for_releases` is the batch form — one query for a set of release ids, returning a dict. `release_readiness_service` (Task 5) uses it once per response.

`agreed_by_username` and `system_name` are resolved through the existing batch name lookups at render time. **Neither may filter `deleted_at`** — an archived system still renders its name on the plan that references it (A1's read-rendering rule), and the username lookup must not be tenant-qualified (impersonation; C2's `approved_by_username` shipped this bug the other way round).

- [ ] **Step 5: Add the routes**

On the releases router: `GET|PUT /api/v1/releases/{release_id}/rollback-plans` (PUT is the upsert), `POST /api/v1/releases/{release_id}/rollback-plans/{plan_id}/agree`, `DELETE /api/v1/releases/{release_id}/rollback-plans/{plan_id}`. JWT auth via `get_current_user`; tenant from `current_user.active_tenant_id`.

**Register any literal-segment route BEFORE a `/{id}` catch-all in the same router** — a literal captured by a catch-all fails on int coercion, which cost B6 a red-run afternoon. Verify by calling the route in a test, not by reasoning about FastAPI's rules.

These are per-release collections bounded by the release's own component count, so no `pagination()` is needed — note that in the route docstring so the next reader knows it was a decision.

- [ ] **Step 6: Write the HTTP-level tests**

```python
# backend/tests/integration/test_rollback_plan_api.py
import pytest


@pytest.mark.asyncio
async def test_a_plan_round_trips_over_http(client, auth_headers, release, system):
    put = await client.put(
        f"/api/v1/releases/{release.id}/rollback-plans",
        json={"system_id": system.id, "steps": "Redeploy previous artefact",
              "reversibility": "lossy", "estimated_minutes": 20},
        headers=auth_headers,
    )
    assert put.status_code == 200

    got = await client.get(
        f"/api/v1/releases/{release.id}/rollback-plans", headers=auth_headers
    )
    assert got.status_code == 200
    body = got.json()
    assert len(body) == 1
    assert body[0]["reversibility"] == "lossy"
    assert body[0]["estimated_minutes"] == 20
    assert body[0]["agreed_at"] is None


@pytest.mark.asyncio
async def test_an_unknown_key_is_a_422(client, auth_headers, release, system):
    """The schema is extra='forbid', so a typo cannot be silently dropped."""
    resp = await client.put(
        f"/api/v1/releases/{release.id}/rollback-plans",
        json={"system_id": system.id, "steps": "s", "reversibility": "reversible",
              "reversibilty": "typo"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
```

- [ ] **Step 7: Run all the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_rollback_plan.py tests/integration/test_rollback_plan_api.py -v`
Then the same files with `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test`.
Expected: PASS on both.

- [ ] **Step 8: Prove the tenant filters by mutation**

Remove the `tenant_id` filter from the release lookup in `upsert_plan`, run `test_a_release_in_another_tenant_is_refused`, confirm it FAILS, restore it, confirm it passes. Do the same for `list_plans`. Record both outcomes in your report — a filter no test can detect is dead code that ships.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/rollback_plan_service.py backend/app/api/v1/schemas/rollback.py \
        backend/app/api/v1/releases.py backend/tests/test_rollback_plan.py \
        backend/tests/integration/test_rollback_plan_api.py
git commit -m "feat(c4): rollback plans per changing component"
```

---

### Task 3: The reversibility rollup

**Files:**
- Modify: `backend/app/services/rollback_plan_service.py`
- Test: `backend/tests/test_rollback_rollup.py`

**Interfaces:**
- Consumes: `ReleaseRollbackPlan`, `REVERSIBILITY_VALUES`.
- Produces: `rollup(plans: list[ReleaseRollbackPlan]) -> Optional[str]` — the worst reversibility across the given plans, or `None` when there are none.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_rollback_rollup.py
from app.services.rollback_plan_service import rollup


class _P:
    """A stand-in carrying only what rollup reads — no database needed."""
    def __init__(self, reversibility):
        self.reversibility = reversibility


def test_the_worst_component_decides():
    assert rollup([_P("reversible"), _P("irreversible"), _P("lossy")]) == "irreversible"
    assert rollup([_P("reversible"), _P("lossy")]) == "lossy"
    assert rollup([_P("reversible"), _P("reversible")]) == "reversible"


def test_no_plans_means_no_verdict():
    """None, not 'reversible' — an unanswered question must never read as a
    reassuring answer."""
    assert rollup([]) is None


def test_an_unknown_value_never_wins_silently():
    """A value outside the vocabulary must not be ordered as if it were safe.
    It sorts as the WORST, so a bad row is loud rather than invisible."""
    assert rollup([_P("reversible"), _P("nonsense")]) == "nonsense"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_rollback_rollup.py -v`
Expected: FAIL — `ImportError: cannot import name 'rollup'`

- [ ] **Step 3: Implement it**

```python
# in backend/app/services/rollback_plan_service.py
from typing import Optional

from app.db.models.rollback import REVERSIBILITY_VALUES


def rollup(plans) -> Optional[str]:
    """The WORST reversibility across a release's plans, or None if there are none.

    Computed, never stored: any component's plan can change at any time, and a
    stored rollup would be falsified by the next edit. Same call C2 made for
    evidence staleness and waiver state.

    Returns None rather than "reversible" for an empty set — an unanswered
    question must not render as a reassuring answer.

    An unrecognised value sorts LAST (worst) rather than first, so a bad row is
    loud rather than silently treated as safe.
    """
    if not plans:
        return None
    order = {value: index for index, value in enumerate(REVERSIBILITY_VALUES)}
    return max(
        (p.reversibility for p in plans),
        key=lambda value: order.get(value, len(REVERSIBILITY_VALUES)),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_rollback_rollup.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rollback_plan_service.py backend/tests/test_rollback_rollup.py
git commit -m "feat(c4): the release reversibility rollup, worst component wins"
```

---

### Task 4: Rehearsals and freshness

**Files:**
- Create: `backend/app/services/rollback_rehearsal_service.py`
- Modify: `backend/app/api/v1/schemas/rollback.py`
- Modify: `backend/app/api/v1/systems.py`
- Test: `backend/tests/test_rollback_rehearsal.py`

**Interfaces:**
- Consumes: `RollbackRehearsal` (Task 1), `get_or_create_policy` (Task 1), `expiry_boundary` from `app.core.day_boundaries`.
- Produces: `rehearsal_state(rehearsal, validity_days, now) -> "current" | "stale"`; `latest_rehearsals_for_systems(db, tenant_id, system_ids) -> dict[int, RollbackRehearsal]`; `record_rehearsal(db, system_id, tenant_id, user_id, data) -> RollbackRehearsal`; `list_rehearsals(db, system_id, tenant_id) -> list[RollbackRehearsal]`; schemas `RehearsalCreate`, `RehearsalRead`; routes `GET|POST /api/v1/systems/{system_id}/rollback-rehearsals`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_rollback_rehearsal.py
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.rollback import RollbackRehearsal
from app.services.rollback_rehearsal_service import rehearsal_state


def _r(rehearsed_at):
    return RollbackRehearsal(
        tenant_id=1, system_id=1, rehearsed_at=rehearsed_at,
        rehearsed_by_user_id=1, outcome="passed",
    )


def test_a_rehearsal_is_current_all_through_its_final_day():
    """A DEADLINE IS A DAY. At instant precision a rehearsal recorded at 15:00
    would expire mid-afternoon on its last day — the bug A4 shipped, B2
    inherited and C2's waiver expiry had to avoid."""
    rehearsed = datetime(2026, 5, 23, 15, 0, tzinfo=timezone.utc)  # 90 days before 21 Aug
    last_day_early = datetime(2026, 8, 21, 0, 1, tzinfo=timezone.utc)
    last_day_late = datetime(2026, 8, 21, 23, 59, tzinfo=timezone.utc)

    assert rehearsal_state(_r(rehearsed), 90, last_day_early) == "current"
    assert rehearsal_state(_r(rehearsed), 90, last_day_late) == "current"


def test_a_rehearsal_is_stale_the_day_after():
    rehearsed = datetime(2026, 5, 23, 15, 0, tzinfo=timezone.utc)
    next_day = datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc)
    assert rehearsal_state(_r(rehearsed), 90, next_day) == "stale"


def test_a_naive_timestamp_does_not_raise():
    """SQLite returns naive datetimes where PostgreSQL returns aware ones, and
    comparing the two is a TypeError — an engine-dependent 500 invisible on the
    PostgreSQL leg."""
    naive = datetime(2026, 8, 20, 12, 0)
    assert rehearsal_state(_r(naive), 90, datetime(2026, 8, 21, 0, 1, tzinfo=timezone.utc)) == "current"


@pytest.mark.asyncio
async def test_the_latest_rehearsal_per_system_is_returned(
    db_session, test_tenant, test_user, system
):
    from app.services import rollback_rehearsal_service
    from app.api.v1.schemas.rollback import RehearsalCreate

    older = await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        outcome="failed"),
    )
    newer = await rollback_rehearsal_service.record_rehearsal(
        db_session, system.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                        outcome="passed"),
    )
    await db_session.flush()

    latest = await rollback_rehearsal_service.latest_rehearsals_for_systems(
        db_session, test_tenant.id, [system.id]
    )
    assert latest[system.id].id == newer.id, "history accumulates; the latest is current"
    assert older.id != newer.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_rollback_rehearsal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.rollback_rehearsal_service'`

- [ ] **Step 3: Write the freshness rule and the batch lookup**

```python
# backend/app/services/rollback_rehearsal_service.py
"""Rollback rehearsals — per system, freshness computed on read.

THERE IS NO STATE COLUMN and no scheduler. A rehearsal's currency follows from
its date and the tenant's validity period, exactly as A4's escalation state,
B5's decommission state and C2's waiver state all do.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.day_boundaries import expiry_boundary
from app.db.models.rollback import RollbackRehearsal


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes where PostgreSQL hands back aware ones;
    comparing the two raises TypeError. Copied rather than imported, following
    the note in app/core/day_boundaries.py — the rule that must NOT be copied is
    the day boundary itself, which is why expiry_boundary is imported."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def rehearsal_state(rehearsal: RollbackRehearsal, validity_days: int, now: datetime) -> str:
    """"current" or "stale". A DEADLINE IS A DAY: current all through its last day."""
    expires_at = _utc(rehearsal.rehearsed_at) + timedelta(days=validity_days)
    return "stale" if expires_at < expiry_boundary(now) else "current"


async def latest_rehearsals_for_systems(
    db: AsyncSession, tenant_id: int, system_ids: list[int]
) -> dict[int, RollbackRehearsal]:
    """The current rehearsal per system — ONE query for the page, never one per row."""
    if not system_ids:
        return {}
    rows = (
        await db.execute(
            select(RollbackRehearsal)
            .where(
                RollbackRehearsal.tenant_id == tenant_id,
                RollbackRehearsal.system_id.in_(system_ids),
                RollbackRehearsal.deleted_at.is_(None),
            )
            .order_by(RollbackRehearsal.system_id, RollbackRehearsal.rehearsed_at.desc(),
                      RollbackRehearsal.id.desc())
        )
    ).scalars().all()
    latest: dict[int, RollbackRehearsal] = {}
    for row in rows:
        latest.setdefault(row.system_id, row)  # first seen per system is the newest
    return latest
```

Note the ordering: `rehearsed_at DESC` then `id DESC`. `rehearsed_at` is caller-supplied, so ties are ordinary and the id tiebreaker is what makes "latest" deterministic.

- [ ] **Step 4: Add the schemas, the write path and the routes**

`RehearsalCreate` carries `rehearsed_at`, `outcome` (`RehearsalOutcome`), `notes`, with `extra="forbid"`. `record_rehearsal` validates the system is in the caller's tenant (404 otherwise). `RehearsalRead` carries the row plus `rehearsed_by_username` (batch-resolved, **not** tenant-qualified) and a computed `state`.

Routes `GET|POST /api/v1/systems/{system_id}/rollback-rehearsals` on the systems router, JWT auth.

**A rehearsal whose `outcome` is `failed` still counts as a rehearsal that happened, but it must NOT count as a current rehearsal** for readiness purposes — a rehearsal that failed proves the opposite of what the requirement wants. Handle that in Task 5's finding logic, not here; record the outcome faithfully.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_rollback_rehearsal.py -v`, then the PostgreSQL leg on the same file.
Expected: PASS (4 tests) on both.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rollback_rehearsal_service.py backend/app/api/v1/schemas/rollback.py \
        backend/app/api/v1/systems.py backend/tests/test_rollback_rehearsal.py
git commit -m "feat(c4): rollback rehearsals with computed freshness"
```

---

### Task 5: Fold rollback into the readiness verdict

**Files:**
- Rename: `backend/app/services/gate_readiness_service.py` → `backend/app/services/release_readiness_service.py`
- Modify: `backend/app/api/v1/schemas/gate_readiness.py`
- Modify: `backend/app/api/v1/releases.py`, `backend/app/api/v1/webhooks/release_ready.py`
- Modify: the five test files importing `gate_readiness_service`
- Test: `backend/tests/test_rollback_readiness.py`

**Interfaces:**
- Consumes: `plans_for_releases`, `rollup` (Tasks 2–3); `latest_rehearsals_for_systems`, `rehearsal_state` (Task 4); `get_or_create_policy` (Task 1).
- Produces: `release_readiness_service.evaluate(db, release_id, tenant_id, now=None) -> ReleaseReadinessResponse`, same signature as before; `ReadinessBlocker.type` and `ReadinessWarning.type` gain the new literals; `ReleaseReadinessResponse` gains `reversibility: Optional[str]`.
- Also produces, added to `rollback_plan_service` in this task: `changing_systems_for_release(db, release_id, tenant_id) -> list[tuple[int, str]]` — the (system_id, system_name) pairs whose `release_system.role` is `changing` or `config_only`, tenant-filtered, one query.

- [ ] **Step 1: Rename the service and fix every importer**

`grep -rn "gate_readiness_service" backend/` first — there are exactly two production importers (`app/api/v1/releases.py`, `app/api/v1/webhooks/release_ready.py`) and five test files. `git mv` the module, update all seven, and run the existing C2 tests to confirm the rename alone breaks nothing:

Run: `cd backend && uv run pytest tests/test_gate_readiness.py tests/test_c2_advises_never_blocks.py -q`
Expected: PASS, unchanged counts.

**Commit the rename on its own** before adding behaviour — a rename mixed with new logic makes the diff unreviewable:

```bash
git add -A && git commit -m "refactor(c4): gate_readiness_service becomes release_readiness_service"
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_rollback_readiness.py
import pytest

from app.services import release_readiness_service


@pytest.mark.asyncio
async def test_a_changing_component_with_no_plan_warns_by_default(
    db_session, test_tenant, release_with_changing_system
):
    """Policy defaults OFF, so day one is warnings, not a wall of blockers."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    assert result.ok is True
    assert "rollback_plan_missing" in [w.type for w in result.warnings]


@pytest.mark.asyncio
async def test_the_same_case_blocks_once_the_policy_requires_a_plan(
    db_session, test_tenant, release_with_changing_system, policy_requiring_plans
):
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    assert result.ok is False
    assert "rollback_plan_missing" in [b.type for b in result.blockers]


@pytest.mark.asyncio
async def test_a_regression_component_produces_no_rollback_findings(
    db_session, test_tenant, release_with_regression_system, policy_requiring_plans
):
    """A regression component is not being changed, so it has nothing to roll back."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_regression_system.id, test_tenant.id
    )
    rollback_types = [
        f.type for f in [*result.blockers, *result.warnings]
        if f.type.startswith("rollback_") or f.type.startswith("rehearsal_")
    ]
    assert rollback_types == []


@pytest.mark.asyncio
async def test_an_irreversible_change_never_blocks_even_with_policy_on(
    db_session, test_tenant, release_with_irreversible_plan, policy_requiring_plans
):
    """A one-way migration is a NORMAL thing to ship. Making it an error teaches
    teams to record it as reversible, destroying the signal."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_irreversible_plan.id, test_tenant.id
    )
    assert "rollback_irreversible" in [w.type for w in result.warnings]
    assert "rollback_irreversible" not in [b.type for b in result.blockers]


@pytest.mark.asyncio
async def test_an_unagreed_plan_is_reported_separately(
    db_session, test_tenant, release_with_unagreed_plan
):
    result = await release_readiness_service.evaluate(
        db_session, release_with_unagreed_plan.id, test_tenant.id
    )
    assert "rollback_plan_unagreed" in [w.type for w in result.warnings]


@pytest.mark.asyncio
async def test_a_failed_rehearsal_does_not_count_as_current(
    db_session, test_tenant, release_with_changing_system, failed_rehearsal_today
):
    """A rehearsal that FAILED proves the opposite of what the rule wants."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    types = [w.type for w in result.warnings]
    assert "rehearsal_missing" in types or "rehearsal_stale" in types


@pytest.mark.asyncio
async def test_the_response_carries_the_reversibility_rollup(
    db_session, test_tenant, release_with_irreversible_plan
):
    result = await release_readiness_service.evaluate(
        db_session, release_with_irreversible_plan.id, test_tenant.id
    )
    assert result.reversibility == "irreversible"


@pytest.mark.asyncio
async def test_gate_findings_are_unaffected(
    db_session, test_tenant, release_with_failed_block_gate
):
    """Adding rollback findings must not disturb C2's gate findings."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_failed_block_gate.id, test_tenant.id
    )
    assert "gate_failed" in [b.type for b in result.blockers]
```

Build the fixtures locally. **Make each one honestly produce the state it names** — a `release_with_changing_system` whose `release_system.role` is not actually `changing` makes its test prove nothing, and a `policy_requiring_plans` fixture that does not actually flip `require_rollback_plan` makes two tests pass for the wrong reason.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_rollback_readiness.py -v`
Expected: FAIL — the new finding types do not exist.

- [ ] **Step 4: Widen the schemas**

In `backend/app/api/v1/schemas/gate_readiness.py`, add to `ReadinessBlocker.type`: `"rollback_plan_missing"`, `"rollback_plan_unagreed"`, `"rehearsal_missing"`, `"rehearsal_stale"`. Add the same four to `ReadinessWarning.type`, plus `"rollback_irreversible"` and `"rollback_lossy"`. Widen `ref_kind` to include `"system"`. Add `reversibility: Optional[str] = None` to `ReleaseReadinessResponse`.

`gate_name` is currently required on both finding models — a rollback finding has no gate. Make it `Optional[str] = None` and set it explicitly at every construction site rather than relying on the default: a defaulted non-column field renders `null` at a site that forgot it, which is how C2 shipped a field permanently wrong.

- [ ] **Step 5: Add the rollback findings to `evaluate()`**

After the gate loop, using the SAME `now` already resolved at the top of the function:

```python
    policy = await rollback_policy_service.get_or_create_policy(db, tenant_id)

    # Only components actually being CHANGED can be rolled back. A regression
    # component is not being changed and produces no findings at all.
    changing = await rollback_plan_service.changing_systems_for_release(
        db, release_id, tenant_id
    )  # -> list[(system_id, system_name)]
    plans = (await rollback_plan_service.plans_for_releases(
        db, tenant_id, [release_id]
    )).get(release_id, [])
    rehearsals = await rollback_rehearsal_service.latest_rehearsals_for_systems(
        db, tenant_id, [s_id for s_id, _ in changing]
    )
    by_system = {p.system_id: p for p in plans}

    for system_id, system_name in changing:
        plan = by_system.get(system_id)
        if plan is None:
            _add("rollback_plan_missing", policy.require_rollback_plan, system_id,
                 system_name, f"{system_name} has no rollback plan.")
        else:
            if plan.agreed_at is None:
                _add("rollback_plan_unagreed", policy.require_rollback_plan, system_id,
                     system_name, f"{system_name}'s rollback plan has not been agreed.")
            if plan.reversibility == "irreversible":
                # ALWAYS a warning, whatever the policy says.
                _add("rollback_irreversible", False, system_id, system_name,
                     f"{system_name} cannot be rolled back — roll forward only.")
            elif plan.reversibility == "lossy":
                _add("rollback_lossy", False, system_id, system_name,
                     f"{system_name} can be rolled back, but data written since "
                     f"deploy is lost.")

        rehearsal = rehearsals.get(system_id)
        # A FAILED rehearsal is not a current rehearsal — it proves the opposite.
        if rehearsal is None or rehearsal.outcome == "failed":
            _add("rehearsal_missing", policy.require_current_rehearsal, system_id,
                 system_name, f"No successful rollback rehearsal recorded for {system_name}.")
        elif rollback_rehearsal_service.rehearsal_state(
            rehearsal, policy.rehearsal_validity_days, now
        ) == "stale":
            _add("rehearsal_stale", policy.require_current_rehearsal, system_id,
                 system_name,
                 f"{system_name}'s last rollback rehearsal was "
                 f"{rehearsal.rehearsed_at.date()}.")

    reversibility = rollback_plan_service.rollup(plans)
```

`_add(kind, is_blocker, system_id, system_name, detail)` is a small local helper appending to `blockers` or `warnings` with `ref_kind="system"`, `ref_id=system_id`, `gate_name=None`. Write it beside the existing `blocker`/`warning` helpers.

Finish by passing `reversibility=reversibility` into `ReleaseReadinessResponse`, and keep `ok=len(blockers) == 0` as the single derived expression it already is.

`changing_systems_for_release` is a new batch query in `rollback_plan_service`: the release's `release_system` rows whose `role` is in `("changing", "config_only")`, joined to `System` for the name, tenant-filtered, `deleted_at` filtered on the release side only.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_rollback_readiness.py tests/test_gate_readiness.py -v`, then both files on PostgreSQL.
Expected: PASS on both — including all of C2's existing gate tests, unchanged.

- [ ] **Step 7: Prove the batching**

Add a test asserting `latest_rehearsals_for_systems` is called ONCE for a release with three changing components, mirroring C2's `test_latest_waivers_for_gates_is_called_once_for_a_multi_gate_page`. Then prove it non-vacuous: change the call into a per-component loop, confirm the test fails, restore it.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(c4): rollback findings in the readiness verdict"
```

---

### Task 6: Rollback authorisation

**Files:**
- Create: `backend/app/services/rollback_authorisation_service.py`
- Modify: `backend/app/api/v1/schemas/rollback.py`, `backend/app/api/v1/releases.py`
- Test: `backend/tests/test_rollback_authorisation.py`

**Interfaces:**
- Consumes: `ReleaseRollbackAuthorisation` (Task 1).
- Produces: `record_authorisation(db, release_id, tenant_id, user_id, data) -> ReleaseRollbackAuthorisation`; `list_authorisations(db, release_id, tenant_id) -> list[ReleaseRollbackAuthorisation]`; schemas `RollbackAuthorisationCreate`, `RollbackAuthorisationRead`; routes `GET|POST /api/v1/releases/{release_id}/rollback-authorisations`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_rollback_authorisation.py
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.v1.schemas.rollback import RollbackAuthorisationCreate
from app.services import rollback_authorisation_service


@pytest.mark.asyncio
async def test_an_authorisation_can_be_recorded_with_no_plan_in_sight(
    db_session, test_tenant, test_user, release, system
):
    """C4 must never stand between a team and a 2am recovery. A rollback that
    happened is recorded whether or not anyone had written a plan."""
    auth = await rollback_authorisation_service.record_authorisation(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackAuthorisationCreate(
            decided_at=datetime(2026, 8, 21, 2, 14, tzinfo=timezone.utc),
            trigger="Checkout error rate above 5% for 10 minutes",
            rationale="Reverting to the previous build while we investigate",
            system_ids=[system.id],
        ),
    )
    assert auth.id is not None
    assert auth.system_ids == [system.id]


@pytest.mark.asyncio
async def test_it_can_be_recorded_after_the_fact(
    db_session, test_tenant, test_user, release, system
):
    """decided_at is caller-supplied and may be in the past — the record is an
    audit trail, not permission."""
    yesterday = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
    auth = await rollback_authorisation_service.record_authorisation(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackAuthorisationCreate(decided_at=yesterday, trigger="t", rationale="r",
                                    system_ids=[system.id]),
    )
    assert auth.decided_at == yesterday


@pytest.mark.asyncio
async def test_a_system_the_release_never_touched_is_refused(
    db_session, test_tenant, test_user, release, unrelated_system
):
    with pytest.raises(HTTPException) as exc:
        await rollback_authorisation_service.record_authorisation(
            db_session, release.id, test_tenant.id, test_user.id,
            RollbackAuthorisationCreate(decided_at=datetime.now(timezone.utc),
                                        trigger="t", rationale="r",
                                        system_ids=[unrelated_system.id]),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_empty_system_list_is_refused(
    db_session, test_tenant, test_user, release
):
    """A rollback of nothing is not a rollback."""
    with pytest.raises(Exception):
        RollbackAuthorisationCreate(decided_at=datetime.now(timezone.utc),
                                    trigger="t", rationale="r", system_ids=[])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_rollback_authorisation.py -v`
Expected: FAIL — `ImportError: cannot import name 'RollbackAuthorisationCreate'`

- [ ] **Step 3: Write the schemas and service**

```python
# in backend/app/api/v1/schemas/rollback.py
class RollbackAuthorisationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decided_at: datetime
    trigger: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)
    system_ids: list[int] = Field(..., min_length=1)


class RollbackAuthorisationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    release_id: int
    decided_by_user_id: int
    decided_by_username: Optional[str] = None
    decided_at: datetime
    trigger: str
    rationale: str
    system_ids: list[int]
    system_names: list[str] = []
```

`record_authorisation` validates the release is in the caller's tenant (404), then that every id in `system_ids` appears on that release's `release_system` rows (404 naming the offender). **It validates ids only — it must never inspect plan state, rehearsal state or the readiness verdict.** A rollback with no plan is exactly the case worth recording.

`system_names` and `decided_by_username` resolve through the batch lookups, neither filtering `deleted_at`, the username lookup not tenant-qualified.

- [ ] **Step 4: Add the routes**

`GET|POST /api/v1/releases/{release_id}/rollback-authorisations` on the releases router, JWT auth, any tenant member. Per-release collection, no pagination — note the decision in the docstring.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_rollback_authorisation.py -v`, then on PostgreSQL.
Expected: PASS (4 tests) on both.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rollback_authorisation_service.py backend/app/api/v1/schemas/rollback.py \
        backend/app/api/v1/releases.py backend/tests/test_rollback_authorisation.py
git commit -m "feat(c4): rollback authorisation, recordable after the fact"
```

---

### Task 7: The policy admin API

**Files:**
- Modify: `backend/app/api/v1/schemas/rollback.py`
- Create: `backend/app/api/v1/rollback_policy.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_rollback_policy_api.py`

**Interfaces:**
- Consumes: `get_or_create_policy`, `update_policy` (Task 1).
- Produces: schemas `RollbackPolicyRead`, `RollbackPolicyUpdate`; routes `GET|PUT /api/v1/tenant/rollback-policy`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/integration/test_rollback_policy_api.py
import pytest


@pytest.mark.asyncio
async def test_an_unconfigured_tenant_reads_defaults(client, auth_headers):
    resp = await client.get("/api/v1/tenant/rollback-policy", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "require_rollback_plan": False,
        "require_current_rehearsal": False,
        "rehearsal_validity_days": 90,
    }


@pytest.mark.asyncio
async def test_a_non_admin_can_read_but_not_write(client, member_headers):
    """Reads open to any tenant member; only writes are Admin — deliberately
    unlike /tenant/users. B3a shipped this over-gated on that false analogy."""
    assert (await client.get("/api/v1/tenant/rollback-policy",
                             headers=member_headers)).status_code == 200
    resp = await client.put("/api/v1/tenant/rollback-policy",
                            json={"require_rollback_plan": True}, headers=member_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_an_omitted_key_leaves_that_setting_alone(client, auth_headers):
    await client.put("/api/v1/tenant/rollback-policy",
                     json={"require_rollback_plan": True, "rehearsal_validity_days": 30},
                     headers=auth_headers)
    await client.put("/api/v1/tenant/rollback-policy",
                     json={"rehearsal_validity_days": 45}, headers=auth_headers)
    body = (await client.get("/api/v1/tenant/rollback-policy",
                             headers=auth_headers)).json()
    assert body["require_rollback_plan"] is True, "omitted means leave alone"
    assert body["rehearsal_validity_days"] == 45


@pytest.mark.asyncio
async def test_a_zero_validity_period_is_refused(client, auth_headers):
    resp = await client.put("/api/v1/tenant/rollback-policy",
                            json={"rehearsal_validity_days": 0}, headers=auth_headers)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_rollback_policy_api.py -v`
Expected: FAIL — 404 on both routes.

- [ ] **Step 3: Write the schemas, router and mount it**

`RollbackPolicyUpdate` has all three fields `Optional`, `extra="forbid"`, and `rehearsal_validity_days: Optional[int] = Field(None, ge=1)`. The service keys on "not None means set", so an omitted key leaves the setting alone.

Mount in `main.py` beside the other v1 routers with `prefix="/api/v1/tenant"`, `tags=["Rollback policy"]`. `GET` takes `get_current_user`; `PUT` takes `require_tenant_admin()`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_rollback_policy_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/rollback_policy.py backend/app/api/v1/schemas/rollback.py \
        backend/app/main.py backend/tests/integration/test_rollback_policy_api.py
git commit -m "feat(c4): the rollback policy admin API"
```

---

### Task 8: The guard — C4 records, it never refuses

**Files:**
- Create: `backend/tests/test_c4_records_never_refuses.py`

- [ ] **Step 1: Write the guard**

```python
# backend/tests/test_c4_records_never_refuses.py
"""C4 RECORDS AND NEVER REFUSES.

The guard on the whole design, in the line of A3, A4, B2, B4, B5 and C2. If any
of these fails, C4 has started standing between a team and a recovery.
"""
import pytest


@pytest.mark.asyncio
async def test_a_rollback_is_recordable_with_no_plan_and_a_blocking_policy(
    client, auth_headers, release_with_changing_system, system, policy_requiring_plans
):
    """The worst case: policy demands plans, none exists, production is on fire."""
    resp = await client.post(
        f"/api/v1/releases/{release_with_changing_system.id}/rollback-authorisations",
        json={"decided_at": "2026-08-21T02:14:00Z", "trigger": "error rate",
              "rationale": "reverting", "system_ids": [system.id]},
        headers=auth_headers,
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_a_release_with_rollback_blockers_still_transitions(
    client, auth_headers, release_with_changing_system, policy_requiring_plans
):
    resp = await client.post(
        f"/api/v1/releases/{release_with_changing_system.id}/transition",
        json={"to_state": "in_progress"}, headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_can_deploy_answers_identically_with_and_without_rollback_state(
    client, api_key_headers, environment, subsystem, release_with_changing_system,
    policy_requiring_plans
):
    """can-deploy is UNTOUCHED by C4 — not one blocker, not one warning."""
    before = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}", headers=api_key_headers,
    )
    after = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}&release_id={release_with_changing_system.id}",
        headers=api_key_headers,
    )
    assert before.json()["blockers"] == after.json()["blockers"]
    assert before.json()["warnings"] == after.json()["warnings"]


@pytest.mark.asyncio
async def test_a_deployment_still_reaches_rolled_back(
    client, api_key_headers, deployment_in_success, policy_requiring_plans
):
    """Nothing in C4 may gate the deployment status machine."""
    resp = await client.post(
        "/api/v1/webhooks/deployment",
        json={"event_id": "c4-guard-1", "status": "rolled_back",
              **deployment_in_success.webhook_payload},
        headers=api_key_headers,
    )
    assert resp.status_code in (200, 201)
```

Check each fixture and payload against the real endpoints before assuming — C2's equivalent guard found that `environment.slug`/`subsystem.slug` do not exist (`preflight_service` matches on `.name`) and that `POST /booking-requests` forbids `release_id`. Adjust to what the endpoints actually accept and say so in your report.

- [ ] **Step 2: Run it — it must pass immediately**

Run: `cd backend && uv run pytest tests/test_c4_records_never_refuses.py -v`
Expected: PASS. It passes by construction, which is exactly why the next step is not optional.

- [ ] **Step 3: Prove it is not vacuous**

Temporarily insert a real refusal into `rollback_authorisation_service.record_authorisation` — raise `HTTPException(409)` when the release has any `rollback_plan_missing` finding — and run the file again.

Expected: **FAIL** on `test_a_rollback_is_recordable_with_no_plan_and_a_blocking_policy`. Then do the same for the transition path (raise 409 when the readiness verdict has rollback blockers) and confirm the second test fails. Revert both, confirm `git status` is clean, and confirm the file passes again. **Record every outcome verbatim** in your report and the commit message.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_c4_records_never_refuses.py
git commit -m "test(c4): the guard — C4 records, it never refuses

Proved non-vacuous: a 409 in record_authorisation fails test 1; a 409 in
the transition path fails test 2; reverting both passes again."
```

---

### Task 9: Frontend — the Rollback panel and the policy admin

**Files:**
- Create: `frontend/src/services/rollbackService.ts`, `frontend/src/store/rollbackSlice.ts`
- Create: `frontend/src/types/rollback.ts`
- Create: `frontend/src/components/releases/RollbackPanel.tsx`, `RollbackPlanDialog.tsx`, `RecordRollbackDialog.tsx`
- Create: `frontend/src/components/admin/RollbackPolicyPanel.tsx`
- Create: `frontend/src/components/systems/RehearsalsPanel.tsx`
- Modify: `frontend/src/store/index.ts`, the release detail page, the system detail page, the admin page
- Test: `frontend/src/components/releases/__tests__/rollbackPanel.test.tsx`
- Test: `frontend/src/components/systems/__tests__/rehearsalsPanel.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/releases/__tests__/rollbackPanel.test.tsx
describe('RollbackPanel', () => {
  it('shows the release rollup and names the irreversible component', async () => {
    render(<RollbackPanel releaseId={1} />);
    await waitFor(() => {
      expect(screen.getByText(/irreversible/i)).toBeInTheDocument();
      expect(screen.getByText(/Payments/)).toBeInTheDocument();
    });
  });

  it('distinguishes a written plan from an agreed one', async () => {
    render(<RollbackPanel releaseId={1} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /agree/i })).toBeEnabled();
    });
  });

  it('shows the server reason when a save is refused', async () => {
    const err = new AxiosError('Request failed with status code 404');
    (err as any).response = { status: 404, data: { detail: 'System not found' } };
    api.put = vi.fn().mockRejectedValue(err);
    render(<RollbackPlanDialog releaseId={1} open onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(screen.getByText(/System not found/)).toBeInTheDocument());
  });
});

describe('C4 records; it never refuses', () => {
  it('leaves the record-rollback action enabled when plans are missing', async () => {
    // The UI half of the backend guard. Assert the control is THERE and
    // ENABLED on a fixture where it would otherwise render — a fixture that
    // renders no control at all cannot detect gating.
    render(<RollbackPanel releaseId={1} plans={[]} />);
    expect(screen.getByRole('button', { name: /record a rollback/i })).toBeEnabled();
  });
});
```

```tsx
// frontend/src/components/systems/__tests__/rehearsalsPanel.test.tsx
describe('RehearsalsPanel', () => {
  it('renders the history and marks the latest as current or stale', async () => {
    render(<RehearsalsPanel systemId={1} />);
    await waitFor(() => {
      expect(screen.getByText(/stale/i)).toBeInTheDocument();
    });
  });

  it('does not present a failed rehearsal as a pass', async () => {
    // The readiness verdict treats a failed rehearsal as "no successful
    // rehearsal", so the panel must not contradict the release banner.
    render(<RehearsalsPanel systemId={1} rehearsals={[{ outcome: 'failed' }]} />);
    expect(screen.queryByTestId('rehearsal-current')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/releases/__tests__/rollbackPanel.test.tsx`
Expected: FAIL — cannot resolve `RollbackPanel`.

- [ ] **Step 3: Build the components**

`RollbackPanel` renders the rollup chip, one row per changing component (steps, reversibility chip, estimated time, agreed-by or an Agree action), and the authorisation history. `RollbackPlanDialog` edits one component's plan; `RecordRollbackDialog` captures decider, time, trigger, rationale and affected systems — **always enabled, never gated on plan state**.

`RollbackPolicyPanel` carries the two toggles and the validity period, with copy saying plainly that enabling a requirement converts warnings into **blockers in the readiness verdict** and still refuses nothing. Model it on `EnvironmentTiersPanel.tsx` and mount it beside the other tenant policy panels.

**`RehearsalsPanel` on the system detail page** — the rehearsal history for that system, each row showing date, who ran it, outcome and notes, with the latest one's **current/stale** state made visible, plus a *Record a rehearsal* action. Without it, rehearsals are API-only: Task 4 builds the endpoints and nothing in the product reaches them. That is precisely the "built it and connected it to nothing" defect a sibling sub-project shipped four times, and the reason `gate_type_id` sat unusable until a task was inserted to expose it.

A rehearsal's state must render **honestly**: `failed` is not a pass, and a stale rehearsal must be visibly distinct from a current one — the readiness verdict treats both as "no successful rehearsal", so a panel showing a green tick beside either would contradict the banner on the release page.

**The readiness banner needs no change** — it already renders whatever the verdict returns. Confirm that by opening the page in Task 10 rather than by assuming it.

- [ ] **Step 4: Run the full frontend gate**

Run, in order:
- `cd frontend && npx vitest run src/components/releases/__tests__/rollbackPanel.test.tsx`
- `cd frontend && npx tsc --noEmit`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`

**All four must pass.** `npm run lint` runs `--report-unused-disable-directives --max-warnings 0`, so an unnecessary `eslint-disable` is a hard error — CI failed C2's merge commit on exactly that. Then run the whole frontend suite once and report the delta.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat(c4): rollback panel, plan dialogs and policy admin"
```

---

### Task 10: Open the pages, then document

**Files:**
- Modify: `docs/phases/phase-9.md`, `docs/admin-guide.md`, `docs/user-guide.md`, `CLAUDE.md`

- [ ] **Step 1: Open the app and use the feature**

```
cd backend && uvicorn app.main:app --reload
cd frontend && npm run dev
```
Login `admin` / `admin123`, tenant `demo`. Walk it: write a plan for a changing component, mark one irreversible and watch the release rollup change; agree a plan; edit an agreed plan and confirm the agreement clears; record a rehearsal on a system and watch a readiness warning disappear; turn `require_rollback_plan` on and watch warnings become blockers in the banner; record a rollback with no plan at all and confirm nothing refuses you; call `GET /api/v1/webhooks/release-ready` with an API key holding `webhooks:release` and paste the real output into your report.

**This step is not a formality.** On this project six defects in one programme were found only by opening the page with a green suite, and C2's browser pass found a warning printing a raw database id that no test caught. **Ask of every screen: what consumes this?**

Browser automation here is known to be flaky — prefer direct URL navigation, do not loop retries, and fall back to `curl` for the endpoint checks if the tooling stops responding.

- [ ] **Step 2: Write the docs, reflecting what you actually saw**

`docs/phases/phase-9.md` — mark C4 complete, keeping the C1–C9 table honest. `docs/admin-guide.md` — the Rollback policy panel, what each toggle does and does not do, and **that there is no deploy step** (the policy is created lazily with defaults). `docs/user-guide.md` — writing and agreeing a plan, what `lossy` means, recording a rehearsal, recording a rollback after the fact. `CLAUDE.md` — a banner block in the B5/B6/C2 shape covering: C4 records and never refuses (naming the guard test); the verdict service is now `release_readiness_service` and rollback findings live in the ONE verdict; `irreversible` never blocks whatever the policy says; a failed rehearsal is not a current rehearsal; both policy flags default off; and editing an agreed plan clears the agreement.

**Do not overstate.** If the browser pass found something broken, the docs must say so and you must report it.

- [ ] **Step 3: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs(c4): phase 9 doc, guides and roadmap"
```

---

## Verification Before Done

- [ ] Backend suite green on **SQLite**
- [ ] Backend suite green on **PostgreSQL**
- [ ] Frontend: `vitest`, `tsc --noEmit`, `npm run lint`, **and** `npm run build` — all four
- [ ] `test_c4_records_never_refuses.py` proved non-vacuous by mutation, both refusal points, outcomes recorded
- [ ] Every new `tenant_id` filter proved by mutation
- [ ] Migration verified on a scratch database, `created_at`/`updated_at` present on all four tables
- [ ] Every page opened in a browser, every new control used
