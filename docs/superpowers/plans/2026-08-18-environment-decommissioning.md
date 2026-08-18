# Phase 7 B5 — Decommissioning Workflow + Idle Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An environment can be decommissioned through a recorded process — warning, a chance to extend, signed backup/teardown attestations — instead of a dropdown; and environments nobody has deployed to or booked for N days are flagged as ghosts.

**Architecture:** Four additive tables and one nullable column. The decommission row stores **facts only** and its state is computed, following A4's `ContentionEscalation` — no status column, no scheduler, one SQL clause reproducing the branch order. Idle is derived in SQL like B2's `quarantine_clause`. The single new refusal is date-based: a booking running past `scheduled_teardown_at`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend); React 18 + TypeScript + MUI DataGrid + Redux Toolkit (frontend); pytest (dual engine: SQLite + PostgreSQL) and vitest.

**Spec:** [docs/superpowers/specs/2026-08-18-environment-decommissioning-design.md](../specs/2026-08-18-environment-decommissioning-design.md) — **read it before Task 1.** Every "why" below is short because the spec carries it.

## Global Constraints

Every task's requirements implicitly include all of these.

- **B5 CHANGES EXACTLY TWO THINGS OUTSIDE ITS OWN RECORDS.** (1) `environment.status` becomes `DECOMMISSIONED` at teardown. (2) A booking whose window runs past `scheduled_teardown_at` is refused. **Nothing else.** No booking is cancelled, transitioned, shortened or deleted anywhere in this plan. Idle detection changes nothing at all. If you find yourself writing to `Booking` outside a test fixture, stop — you are outside B5.
- **The state is COMPUTED, never stored.** There is no `state` column on `environment_decommission` and there must never be one. If you add one, you have created something to invalidate and a scheduler to run.
- **A deadline is a day.** Every comparison of `scheduled_teardown_at`, and the idle cutoff, goes through `expiry_boundary` from `app/core/day_boundaries.py`. **Do not write a second copy of that rule** — read that module's docstring first.
- **No dialect date arithmetic, ever.** Neither engine's interval syntax is portable. Cutoff instants are computed in **Python** and passed into the query as literals (Task 3 shows the exact pattern). If you type `interval` or `julianday`, you are wrong.
- **`environment.status` stores the enum MEMBER NAME** — the column holds `ACTIVE`, not `active`. Prefer `EnvironmentStatus.X` over a string literal: it is the house convention and survives a rename of the enum value. NOTE, CORRECTED 2026-08-18: a string literal is NOT broken — SQLAlchemy's `Enum` coerces a value-matching literal to the stored name, and both forms emit identical SQL. This is a consistency rule, not a bug fix.
- **Enum-ish columns are never native.** `String(30)` per the house rule; `booking.status` is the precedent.
- **Migrations are hand-written.** `alembic revision -m "..."` then write the DDL yourself. Never `--autogenerate` — `init_db()` calls `create_all`, so autogenerate sees nothing to do.
- **`alembic downgrade -1` on the dev database will drop someone else's table.** It steps back from the *current* head, not from your revision. Use the scratch database `tests/test_migration_schema_drift.py` builds.
- **No `db.commit()` in services.** `get_db()` auto-commits; use `db.flush()` when you need an id mid-transaction.
- **Every query on a tenant-scoped table filters `tenant_id`, using `current_user.active_tenant_id`**, never `.tenant_id` — impersonation makes them differ.
- **Every request schema declares `extra="forbid"`.** `ProjectCreate` silently discarded a field for want of it.
- **Response fields carrying a computed verdict are required-positional, never defaulted.** A defaulted field renders a confident answer at a site that never computed one.
- **Never fabricate a foreign key in a test.** Use `backend/tests/factories.py` (`ensure_environment`, `ensure_user`, `ensure_user_group`, `ensure_environment_tier`, `make_booking`, …). SQLite enforces FKs here.
- **Backend test command:** `cd backend && PYTHONPATH=. uv run pytest -q`. Single file: `PYTHONPATH=. uv run pytest tests/path/test_x.py -q`.
- **Frontend test command:** `cd frontend && npx vitest run <path>`.
- **Test cadence.** Focused tests every task (fast, foreground). **Full SQLite suite at Tasks 3, 8 and 17. Full PostgreSQL suite at Tasks 1, 3, 8 and 17** — Task 1 carries the migration, Task 3 the `CASE`-based idle clause, Task 8 the refusal. CI runs both legs on push regardless.
- **Full-suite commands:** `cd backend && PYTHONPATH=. uv run pytest -q` and `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest -q`. **Both exceed the 600s foreground Bash limit.** Launch with `run_in_background`, redirect to a fixed log path, and wait with `until grep -qE "[0-9]+ (passed|failed)" <log>; do sleep 20; done`. Output sent only to a pipe is lost when the shell ends.
- **Commit per task**, conventional commits (`feat(b5):`, `test(b5):`, `docs(b5):`). Do not push; the branch is merged at the end.
- **Branch:** `feature/phase7-b5-decommissioning` already exists and carries the spec commit. Work on it.

---

## File Structure

**Backend — create**
- `app/core/decommission_states.py` — the five state constants and the valid set. Its own module, mirroring `app/core/booking_states.py` and `app/core/protection_levels.py`, so the service and the API share them without a cycle.
- `app/db/models/environment_decommission.py` — `EnvironmentDecommission`, `EnvironmentDecommissionAttestation`, `EnvironmentDecommissionStep`. One file: they change together.
- `app/db/models/environment_lifecycle_policy.py` — `EnvironmentLifecyclePolicy`.
- `app/db/migrations/versions/<rev>_envdecommission.py` — four tables, one column, the step seed.
- `app/services/environment_decommission_defaults.py` — the two seeded steps, following `environment_tier_defaults.py`.
- `app/services/environment_lifecycle_policy_service.py` — read/upsert the policy, CRUD the step vocabulary.
- `app/services/environment_idle_service.py` — `idle_clause` and its cutoff resolution. Its own module so `environment_service` gains one import, not a second concern.
- `app/services/environment_decommission_service.py` — the state machine, its SQL predicate, and every action.
- `app/api/v1/decommissions.py` — the action routes and the worklist.
- `app/api/v1/schemas/decommission.py` — request/response schemas.
- `backend/tests/test_b5_acts_only_where_it_says.py` — **the guard.**
- `backend/tests/services/test_decommission_state.py` — state and predicate agreement.
- `backend/tests/services/test_environment_idle.py` — the idle clause.
- `backend/tests/integration/test_decommission_api.py` — the workflow end to end.
- `backend/tests/integration/test_decommission_booking_refusal.py` — every create path.

**Backend — modify**
- `app/db/models/environment_tier.py` — `idle_threshold_days`
- `app/services/environment_service.py` — `?idle=` filter, `idle`/`decommission_state` on the view
- `app/services/environment_health_service.py` — the status-literal bug (Task 3)
- `app/services/booking_request_service.py` — the refusal, on `create_request` **and** `add_environment`
- `app/services/booking_service.py` — the refusal, on `create_booking` and the date-extending edit path
- `app/api/v1/environments.py` — the filter parameter
- `app/api/v1/tenant_admin_fields.py` — policy + step admin routes
- `app/api/v1/environment_tiers.py` — the threshold field
- `app/main.py` — register the decommissions router
- `app/services/tenant_service.py` — seed steps for a new tenant

**Frontend — create**
- `src/types/decommission.ts`, `src/services/decommissionService.ts`, `src/store/decommissionSlice.ts`
- `src/components/environments/DecommissionPanel.tsx` — banner, controls, attestation checklist
- `src/pages/decommissions/DecommissionWorklist.tsx`
- `src/components/admin/EnvironmentLifecyclePanel.tsx`
- Test files alongside each, under `__tests__/`

**Frontend — modify**
- `src/pages/environments/EnvironmentList.tsx` — idle + decommission columns and filters
- `src/pages/environments/EnvironmentDetail.tsx` — mount the panel
- `src/types/environment.ts` — `idle`, `decommission_state`
- `src/App.tsx` — the `/decommissions` route
- `src/constants/sortWhitelists.json` — the worklist's sortable columns

---

## Task 1: Data model, migration and the step seed

**Files:**
- Create: `backend/app/core/decommission_states.py`, `backend/app/db/models/environment_decommission.py`, `backend/app/db/models/environment_lifecycle_policy.py`, `backend/app/services/environment_decommission_defaults.py`, `backend/app/db/migrations/versions/<rev>_envdecommission.py`
- Modify: `backend/app/db/models/environment_tier.py`, `backend/app/db/models/__init__.py`, `backend/app/services/tenant_service.py`
- Test: `backend/tests/services/test_decommission_model.py`

**Interfaces:**
- Produces: `EnvironmentDecommission`, `EnvironmentDecommissionAttestation`, `EnvironmentDecommissionStep`, `EnvironmentLifecyclePolicy`; `STATE_WARNED/DUE/EXTENSION_REQUESTED/TORN_DOWN/CANCELLED`, `DECOMMISSION_STATES`; `seed_decommission_steps_for_tenant(db, tenant_id) -> None`; `EnvironmentTier.idle_threshold_days`.

- [ ] **Step 1: Write the state constants**

`backend/app/core/decommission_states.py`:

```python
"""B5 — the five decommission states.

Its own module, mirroring app/core/booking_states.py and
app/core/protection_levels.py, so the service, the API schemas and the tests
share one vocabulary without importing each other.

THESE ARE COMPUTED, NEVER STORED. There is no `state` column on
environment_decommission and there must never be one — see the spec §4.2.
"""

STATE_WARNED = "warned"
STATE_DUE = "due"
STATE_EXTENSION_REQUESTED = "extension_requested"
STATE_TORN_DOWN = "torn_down"
STATE_CANCELLED = "cancelled"

DECOMMISSION_STATES = (
    STATE_WARNED,
    STATE_DUE,
    STATE_EXTENSION_REQUESTED,
    STATE_TORN_DOWN,
    STATE_CANCELLED,
)

# Deliberately NO `LIVE_STATES` tuple. 'Live' is decided by
# `environment_decommission_service.live_predicate`, in SQL, over the same
# three columns -- a parallel tuple here would be a second definition of one
# rule, and the two would drift the first time a state is added.
```

- [ ] **Step 2: Write the models**

`backend/app/db/models/environment_decommission.py`:

```python
"""B5 — the decommissioning record, its attestations, and the tenant's
checklist vocabulary.

THE ROW STORES FACTS; THE STATE IS COMPUTED. Following A4's
ContentionEscalation: there is no status column, so there is nothing to
invalidate when a notice period elapses, and no scheduler to run.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentDecommission(Base):
    """One decommission attempt. At most one LIVE row per environment —
    enforced in the service, not by a partial unique index, which would be
    inert on SQLite (the same call B3a's group-name uniqueness made)."""

    __tablename__ = "environment_decommission"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    # Required: a decommission with no stated reason is not an audit record.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    warned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # warned_at + the tenant's decommission_notice_days. The initiator may move
    # it LATER, never earlier — an initiator who could shorten the notice would
    # make §2.12's five-day warning advisory, and the booking refusal derives
    # from this column.
    scheduled_teardown_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    initiated_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)

    # The extension block. ONE extension per decommission (spec §4.3): a second
    # request is refused, pointing at cancel-and-re-raise.
    extension_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_requested_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    extension_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extension_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    # NULL means "not decided" — which is branch 3 of the computed state.
    extension_granted: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )

    torn_down_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    torn_down_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )

    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentDecommission(id={self.id}, "
            f"environment_id={self.environment_id})>"
        )


class EnvironmentDecommissionAttestation(Base):
    """A human confirming a step happened. IMMUTABLE — no deleted_at, following
    BookingStatusHistory. A mistaken signature is corrected by cancelling the
    decommission, not by editing the record."""

    __tablename__ = "environment_decommission_attestation"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    decommission_id: Mapped[int] = mapped_column(
        ForeignKey("environment_decommission.id"), nullable=False, index=True
    )
    # A PLAIN STRING, NOT AN FK to environment_decommission_step: an attestation
    # must still read correctly after its step definition is retired. Same rule
    # as A2's environment_group_id being provenance rather than a live link.
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    signed_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Snapshot id, ticket, runbook link — the evidence a register can honestly
    # hold. Free text on purpose; it is not parsed.
    reference: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "decommission_id", "step_key", name="uq_decommission_step"
        ),
    )


class EnvironmentDecommissionStep(Base):
    """The tenant's checklist vocabulary, shaped like EnvironmentTier and
    BookingType."""

    __tablename__ = "environment_decommission_step"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

`backend/app/db/models/environment_lifecycle_policy.py`:

```python
"""B5 — one tenant's idle-detection and decommission-notice settings.

Shaped like EnvironmentNamingPolicy: tenant_id unique, no deleted_at, no DELETE
path. `idle_detection_enabled` is the off switch.
"""
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentLifecyclePolicy(Base):
    __tablename__ = "environment_lifecycle_policy"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True, unique=True
    )
    # DEFAULTS OFF. B2's ?governance_gap=true matched every environment on first
    # deploy and looked exactly like a bug; no tenant's estate should light up
    # with a flag they did not ask for.
    idle_detection_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    idle_threshold_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    # §2.12's five-day warning.
    decommission_notice_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
```

Add to `backend/app/db/models/environment_tier.py`:

```python
    # B5 — the per-tier idle threshold. NULL means "use the tenant default".
    # A Dev sandbox quiet for 30 days is a ghost; a DR or Training environment
    # quiet for 90 is behaving normally, and one tenant-wide number necessarily
    # mislabels one of them.
    idle_threshold_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
```

Export all four new classes from `backend/app/db/models/__init__.py` alongside the existing ones.

- [ ] **Step 3: Write the step defaults**

`backend/app/services/environment_decommission_defaults.py`:

```python
"""Seed the two standard decommission steps. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill,
following environment_tier_defaults.py.

The migration carries its own literal copy of this list rather than importing
it: a migration reproduces the past, so it must not change meaning when this
module gains a third step.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment_decommission import EnvironmentDecommissionStep

STANDARD_STEPS: list[dict[str, Any]] = [
    {
        "key": "final_backup",
        "label": "Final backup taken",
        "description": "Record the snapshot id or backup job reference.",
        "display_order": 10,
        "is_required": True,
    },
    {
        "key": "teardown",
        "label": "Infrastructure torn down",
        "description": "Record the ticket or runbook run that removed it.",
        "display_order": 20,
        "is_required": True,
    },
]


async def seed_decommission_steps_for_tenant(
    db: AsyncSession, tenant_id: int
) -> None:
    """Create any standard step this tenant does not already have, matched on
    `key` so a re-run adds nothing."""
    existing = set(
        (
            await db.execute(
                select(EnvironmentDecommissionStep.key).where(
                    EnvironmentDecommissionStep.tenant_id == tenant_id
                )
            )
        ).scalars()
    )
    for step in STANDARD_STEPS:
        if step["key"] in existing:
            continue
        db.add(EnvironmentDecommissionStep(tenant_id=tenant_id, **step))
    await db.flush()
```

Call it from `tenant_service.create_tenant()` beside `seed_environment_tier_defaults_for_tenant`.

- [ ] **Step 4: Write the failing test**

`backend/tests/services/test_decommission_model.py`:

```python
"""B5 Task 1 — the schema exists, and the seed is idempotent."""
import pytest
from sqlalchemy import select

from app.db.models.environment_decommission import (
    EnvironmentDecommission,
    EnvironmentDecommissionStep,
)
from app.db.models.environment_tier import EnvironmentTier
from app.services.environment_decommission_defaults import (
    seed_decommission_steps_for_tenant,
)
from tests.factories import ensure_environment, ensure_user


@pytest.mark.asyncio
async def test_the_seed_is_idempotent(db_session, tenant):
    await seed_decommission_steps_for_tenant(db_session, tenant.id)
    await seed_decommission_steps_for_tenant(db_session, tenant.id)

    keys = (
        await db_session.execute(
            select(EnvironmentDecommissionStep.key).where(
                EnvironmentDecommissionStep.tenant_id == tenant.id
            )
        )
    ).scalars().all()

    assert sorted(keys) == ["final_backup", "teardown"]


@pytest.mark.asyncio
async def test_a_decommission_row_stores_no_state(db_session, tenant):
    """THE STATE IS COMPUTED. If this fails, someone added a state column and
    with it something to invalidate and a scheduler to run."""
    assert not hasattr(EnvironmentDecommission, "state")
    assert not hasattr(EnvironmentDecommission, "status")


@pytest.mark.asyncio
async def test_the_tier_threshold_defaults_to_null(db_session, tenant):
    """NULL means 'use the tenant default' — a legitimate state, not a missing
    value, exactly as B1's null expires_at is."""
    tier = (
        await db_session.execute(
            select(EnvironmentTier).where(EnvironmentTier.tenant_id == tenant.id)
        )
    ).scalars().first()
    assert tier is not None
    assert tier.idle_threshold_days is None
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/services/test_decommission_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.environment_decommission'` before Step 2, then a missing-column error until Step 2 is complete.

- [ ] **Step 6: Write the migration**

Generate the file: `cd backend && uv run alembic revision -m "envdecommission"`, then **rename the revision id to `envdecommission`** and write the DDL by hand. `down_revision` is `aabc21374208` (B4's `bookingprotection`, the current single head — verify with `uv run alembic heads`).

```python
"""Phase 7 B5 — decommissioning workflow and idle detection.

ADDITIVE ONLY: four new tables, one nullable column on environment_tier, and a
seed of the two standard decommission steps for existing tenants. No backfill,
no data migration, nothing existing is rewritten.

The step seed is carried here as a LITERAL rather than imported from
environment_decommission_defaults: a migration reproduces the past, so it must
not change meaning when that module gains a third step. B3b's `envrequests`
recorded the deploy failure this prevents — a tenant that cannot complete the
workflow at all because its vocabulary was never seeded.

Revision ID: envdecommission
Revises: aabc21374208
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "envdecommission"
down_revision: Union[str, None] = "aabc21374208"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_STEPS = [
    ("final_backup", "Final backup taken",
     "Record the snapshot id or backup job reference.", 10),
    ("teardown", "Infrastructure torn down",
     "Record the ticket or runbook run that removed it.", 20),
]


def upgrade() -> None:
    op.create_table(
        "environment_decommission",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("warned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_teardown_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initiated_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("extension_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_requested_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("extension_reason", sa.Text(), nullable=True),
        sa.Column("extension_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extension_decided_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("extension_granted", sa.Boolean(), nullable=True),
        sa.Column("torn_down_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("torn_down_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_environment_decommission_tenant_id", "environment_decommission", ["tenant_id"])
    op.create_index("ix_environment_decommission_environment_id", "environment_decommission", ["environment_id"])

    op.create_table(
        "environment_decommission_attestation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("decommission_id", sa.Integer(),
                  sa.ForeignKey("environment_decommission.id"), nullable=False),
        sa.Column("step_key", sa.String(length=100), nullable=False),
        sa.Column("signed_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("decommission_id", "step_key", name="uq_decommission_step"),
    )
    op.create_index("ix_environment_decommission_attestation_tenant_id",
                    "environment_decommission_attestation", ["tenant_id"])
    op.create_index("ix_environment_decommission_attestation_decommission_id",
                    "environment_decommission_attestation", ["decommission_id"])

    op.create_table(
        "environment_decommission_step",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_environment_decommission_step_tenant_id",
                    "environment_decommission_step", ["tenant_id"])

    op.create_table(
        "environment_lifecycle_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"),
                  nullable=False, unique=True),
        sa.Column("idle_detection_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("idle_threshold_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("decommission_notice_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_environment_lifecycle_policy_tenant_id",
                    "environment_lifecycle_policy", ["tenant_id"])

    op.add_column(
        "environment_tier",
        sa.Column("idle_threshold_days", sa.Integer(), nullable=True),
    )

    # Seed the step vocabulary for every EXISTING tenant. Without this a tenant
    # provisioned before B5 can never complete a teardown.
    conn = op.get_bind()
    tenant_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM tenant"))]
    for tenant_id in tenant_ids:
        for key, label, description, order in _SEED_STEPS:
            conn.execute(
                sa.text(
                    "INSERT INTO environment_decommission_step "
                    "(tenant_id, key, label, description, display_order, "
                    " is_required, is_active, created_at, updated_at) "
                    "VALUES (:t, :k, :l, :d, :o, TRUE, TRUE, "
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"t": tenant_id, "k": key, "l": label, "d": description, "o": order},
            )


def downgrade() -> None:
    op.drop_column("environment_tier", "idle_threshold_days")
    op.drop_table("environment_lifecycle_policy")
    op.drop_table("environment_decommission_step")
    op.drop_table("environment_decommission_attestation")
    op.drop_table("environment_decommission")
```

- [ ] **Step 7: Run the focused tests and the drift guard**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_decommission_model.py tests/test_migration_schema_drift.py -q
```
Expected: PASS.

**Note on the drift guard:** it compares only column NAME SETS — not types, defaults or indexes. Its "N passed" is **not** evidence that your hand-written DDL matches the models. Read both side by side once before committing.

- [ ] **Step 8: Verify the migration on a real database, both directions**

Do **not** run `alembic downgrade -1` against the dev database — it steps back from the current head and will drop a table you did not write. Use a scratch database:

```bash
cd backend
createdb -h localhost -U envmgr envmgr_b5_scratch 2>/dev/null || true
DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_b5_scratch \
  PYTHONPATH=. uv run alembic upgrade head
DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_b5_scratch \
  PYTHONPATH=. uv run alembic downgrade envdecommission
DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_b5_scratch \
  PYTHONPATH=. uv run alembic upgrade head
dropdb -h localhost -U envmgr envmgr_b5_scratch
```
Expected: all three complete without error.

- [ ] **Step 9: Run the full PostgreSQL suite**

This task carries the migration, so both legs run. Launch in the background per the Global Constraints and wait on the log.

```bash
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest -q > /tmp/b5-t1-pg.log 2>&1
```
Expected: no new failures against `main`'s baseline.

- [ ] **Step 10: Commit**

```bash
git add backend/app/core/decommission_states.py backend/app/db/models/ \
        backend/app/services/environment_decommission_defaults.py \
        backend/app/services/tenant_service.py \
        backend/app/db/migrations/versions/ \
        backend/tests/services/test_decommission_model.py
git commit -m "feat(b5): decommission tables, lifecycle policy, tier threshold, migration"
```

---

## Task 2: Lifecycle policy and the step vocabulary

**Files:**
- Create: `backend/app/services/environment_lifecycle_policy_service.py`, `backend/app/api/v1/schemas/lifecycle_policy.py`
- Modify: `backend/app/api/v1/tenant_admin_fields.py`
- Test: `backend/tests/integration/test_lifecycle_policy_api.py`

**Interfaces:**
- Consumes: `EnvironmentLifecyclePolicy`, `EnvironmentDecommissionStep`, `seed_decommission_steps_for_tenant` (Task 1)
- Produces: `get_policy(db, tenant_id) -> EnvironmentLifecyclePolicy` (returns an **unsaved default instance** when no row exists, never None); `upsert_policy(db, tenant_id, *, idle_detection_enabled, idle_threshold_days, decommission_notice_days)`; `list_steps(db, tenant_id, *, active_only: bool)`; `create_step`/`update_step`/`delete_step`

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_lifecycle_policy_api.py`:

```python
"""B5 Task 2 — the tenant's lifecycle policy and decommission-step vocabulary."""
import pytest


@pytest.mark.asyncio
async def test_a_tenant_with_no_policy_row_reads_the_defaults(client, auth_headers):
    """No row is a legitimate state, not a 404: idle detection is simply off."""
    r = await client.get("/api/v1/tenant/environment-lifecycle-policy", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["idle_detection_enabled"] is False
    assert body["idle_threshold_days"] == 30
    assert body["decommission_notice_days"] == 5


@pytest.mark.asyncio
async def test_saving_the_policy_round_trips(client, auth_headers):
    r = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=auth_headers,
        json={
            "idle_detection_enabled": True,
            "idle_threshold_days": 45,
            "decommission_notice_days": 7,
        },
    )
    assert r.status_code == 200
    assert r.json()["idle_threshold_days"] == 45

    again = await client.get(
        "/api/v1/tenant/environment-lifecycle-policy", headers=auth_headers
    )
    assert again.json()["decommission_notice_days"] == 7


@pytest.mark.asyncio
async def test_the_read_model_cannot_be_echoed_back(client, auth_headers):
    """extra='forbid' — B2's naming policy shipped a 422 on EVERY save because
    the frontend echoed GET's body, id and timestamps included, into PUT."""
    r = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=auth_headers,
        json={
            "id": 1,
            "tenant_id": 1,
            "idle_detection_enabled": True,
            "idle_threshold_days": 45,
            "decommission_notice_days": 7,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_thresholds_must_be_positive(client, auth_headers):
    r = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=auth_headers,
        json={
            "idle_detection_enabled": True,
            "idle_threshold_days": 0,
            "decommission_notice_days": 5,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_steps_are_seeded_and_listable(client, auth_headers):
    r = await client.get("/api/v1/tenant/decommission-steps", headers=auth_headers)
    assert r.status_code == 200
    assert {s["key"] for s in r.json()} == {"final_backup", "teardown"}


@pytest.mark.asyncio
async def test_only_an_admin_may_write_the_policy(client, member_headers):
    """Reads are open to any tenant member; writes are Admin — the split B3a
    established for user groups."""
    read = await client.get(
        "/api/v1/tenant/environment-lifecycle-policy", headers=member_headers
    )
    assert read.status_code == 200

    write = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=member_headers,
        json={
            "idle_detection_enabled": True,
            "idle_threshold_days": 45,
            "decommission_notice_days": 5,
        },
    )
    assert write.status_code == 403
```

If no `member_headers` fixture exists in `conftest.py`, add one issuing a token for a non-Admin user in the same tenant, following how `auth_headers` is built.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_lifecycle_policy_api.py -q`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: Write the schemas**

`backend/app/api/v1/schemas/lifecycle_policy.py`:

```python
from pydantic import BaseModel, ConfigDict, Field


class EnvironmentLifecyclePolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idle_detection_enabled: bool
    idle_threshold_days: int
    decommission_notice_days: int


class EnvironmentLifecyclePolicyUpdate(BaseModel):
    """The WRITE model. extra='forbid' and no id/timestamps — the frontend must
    not echo the read model back. B2 shipped a 422 on every save for want of
    this distinction, and a mocked service cannot notice."""

    model_config = ConfigDict(extra="forbid")

    idle_detection_enabled: bool
    idle_threshold_days: int = Field(ge=1, le=3650)
    decommission_notice_days: int = Field(ge=1, le=365)


class DecommissionStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label: str
    description: str | None
    display_order: int
    is_required: bool
    is_active: bool


class DecommissionStepWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    description: str | None = None
    display_order: int = 0
    is_required: bool = True
    is_active: bool = True
```

- [ ] **Step 4: Write the service**

`backend/app/services/environment_lifecycle_policy_service.py`. `get_policy` returns an **unsaved default instance** when the tenant has no row — never `None`, so no caller has to invent the defaults a second time:

```python
async def get_policy(db: AsyncSession, tenant_id: int) -> EnvironmentLifecyclePolicy:
    """The tenant's policy, or an UNSAVED instance carrying the defaults.

    Never None. A caller that had to handle None would re-state the default
    thresholds, and two places stating one default is how they drift.
    """
    row = (
        await db.execute(
            select(EnvironmentLifecyclePolicy).where(
                EnvironmentLifecyclePolicy.tenant_id == tenant_id
            )
        )
    ).scalars().first()
    if row is not None:
        return row
    return EnvironmentLifecyclePolicy(
        tenant_id=tenant_id,
        idle_detection_enabled=False,
        idle_threshold_days=30,
        decommission_notice_days=5,
    )
```

`upsert_policy` loads or creates the row, assigns the three fields and flushes. Step CRUD follows `environment_tier_service` — soft delete, name/key uniqueness enforced **in the service** (a partial unique index is inert on SQLite), and `delete_step` refuses to soft-delete a step that any live decommission still needs? **No** — it does not: a retired step simply stops being required, and the attestation's `step_key` is a plain string precisely so old records still read. Do not add that refusal.

- [ ] **Step 5: Wire the routes into `tenant_admin_fields.py`**

Follow the `environment-naming-policy` routes directly above: `GET` open to any tenant member via `get_current_user`, `PUT` and every step mutation gated on `require_tenant_admin()`.

- [ ] **Step 6: Run the tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_lifecycle_policy_api.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/environment_lifecycle_policy_service.py \
        backend/app/api/v1/schemas/lifecycle_policy.py \
        backend/app/api/v1/tenant_admin_fields.py \
        backend/tests/integration/test_lifecycle_policy_api.py
git commit -m "feat(b5): tenant lifecycle policy and decommission-step vocabulary"
```

---

## Task 3: Idle detection

**Files:**
- Create: `backend/app/services/environment_idle_service.py`
- Modify: `backend/app/services/environment_service.py`, `backend/app/api/v1/environments.py`, `backend/app/services/environment_health_service.py`
- Test: `backend/tests/services/test_environment_idle.py`

**Interfaces:**
- Consumes: `get_policy` (Task 2), `expiry_boundary` (`app/core/day_boundaries.py`)
- Produces: `async def idle_state(db, tenant_id, now) -> IdleState` (a frozen dataclass carrying `enabled: bool` and `cutoff_expr`); `def idle_clause(state: IdleState, now: datetime)`. `EnvironmentView` gains `idle: bool` (**required-positional**).

- [ ] **Step 1: Standardise the status comparison (NOT a bug fix — see the correction below)**

`environment.status` stores the enum **member name** (`ACTIVE`), so
`environment_health_service.py:103`'s `Environment.status != "decommissioned"`
compares against a value that never appears in the column — it is always true,
and decommissioned environments are **not** excluded from the health overview.
B5 filters on status throughout and must not build on this.

Add to `backend/tests/services/test_environment_idle.py`:

```python
@pytest.mark.asyncio
async def test_a_decommissioned_environment_is_absent_from_the_health_overview(
    db_session, tenant
):
    """PRE-EXISTING BUG, fixed here. environment.status stores the enum member
    NAME — the column holds 'ACTIVE', never 'active' — so a string-literal
    comparison silently matched nothing and excluded nothing."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.status = EnvironmentStatus.DECOMMISSIONED
    await db_session.flush()

    overview = await environment_health_service.health_overview(db_session, tenant.id)

    assert all(row.environment_id != env.id for row in overview)
```

Then change the line to `Environment.status != EnvironmentStatus.DECOMMISSIONED`
and import the enum. Run this one test before and after: it must fail first.

- [ ] **Step 2: Write the failing idle tests**

```python
"""B5 Task 3 — idle detection: derived in SQL, never stored."""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.environment import EnvironmentStatus
from app.services import environment_idle_service, environment_service
from tests.factories import ensure_environment, ensure_environment_tier, make_booking

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


async def _enable(db, tenant_id, days=30):
    from app.services import environment_lifecycle_policy_service as svc
    await svc.upsert_policy(
        db, tenant_id,
        idle_detection_enabled=True,
        idle_threshold_days=days,
        decommission_notice_days=5,
    )


@pytest.mark.asyncio
async def test_an_environment_with_no_activity_is_idle(db_session, tenant):
    await _enable(db_session, tenant.id)
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=200)
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert [v.environment.id for v in views] == [env.id]


@pytest.mark.asyncio
async def test_a_recent_booking_makes_it_active(db_session, tenant):
    await _enable(db_session, tenant.id)
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=200)
    await make_booking(
        db_session, tenant.id, env.id,
        start=NOW - timedelta(days=3), end=NOW - timedelta(days=1),
    )
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_a_long_booking_spanning_the_window_makes_it_active(db_session, tenant):
    """OVERLAP, NOT START. A three-month booking taken four months ago means the
    environment was claimed the whole time; a start-date test calls it idle."""
    await _enable(db_session, tenant.id)
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=400)
    await make_booking(
        db_session, tenant.id, env.id,
        start=NOW - timedelta(days=120), end=NOW + timedelta(days=1),
    )
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_an_environment_younger_than_its_threshold_is_never_idle(db_session, tenant):
    """Otherwise every new environment is born a ghost — B2's policy-age guard."""
    await _enable(db_session, tenant.id, days=30)
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=5)
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_the_tier_override_wins_over_the_tenant_default(db_session, tenant):
    await _enable(db_session, tenant.id, days=30)
    tier = await ensure_environment_tier(db_session, tenant.id, name="DR")
    tier.idle_threshold_days = 90
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.tier_id = tier.id
    env.created_at = NOW - timedelta(days=200)
    await make_booking(
        db_session, tenant.id, env.id,
        start=NOW - timedelta(days=60), end=NOW - timedelta(days=59),
    )
    await db_session.flush()

    # Quiet for 60 days: idle under the 30-day default, active under DR's 90.
    views, _ = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_a_non_active_environment_is_never_idle(db_session, tenant):
    """Answers FALSE, never null. An inactive environment is idle by
    definition; flagging it buries the real ghosts."""
    await _enable(db_session, tenant.id)
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=200)
    env.status = EnvironmentStatus.INACTIVE
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_nothing_is_idle_while_detection_is_disabled(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    env.created_at = NOW - timedelta(days=999)
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert views == []


@pytest.mark.asyncio
async def test_the_filtered_total_describes_the_filtered_set(db_session, tenant):
    """X-Total-Count is the only evidence from outside that the filter ran in
    the query rather than over the page."""
    await _enable(db_session, tenant.id)
    idle_env = await ensure_environment(db_session, tenant.id, slot=1)
    idle_env.created_at = NOW - timedelta(days=200)
    busy = await ensure_environment(db_session, tenant.id, slot=2)
    busy.created_at = NOW - timedelta(days=200)
    await make_booking(
        db_session, tenant.id, busy.id,
        start=NOW - timedelta(days=2), end=NOW - timedelta(days=1),
    )
    await db_session.flush()

    _, total = await environment_service.list_environments(
        db_session, tenant.id, idle=True, now=NOW
    )
    assert total == 1
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/services/test_environment_idle.py -q`
Expected: FAIL — `list_environments() got an unexpected keyword argument 'idle'`.

- [ ] **Step 4: Write the idle service**

**The cutoff must not use dialect date arithmetic.** Neither engine's interval
syntax is portable, so the cutoff instants are computed in Python — one per
tier that overrides, plus the default — and injected as literals in a `CASE`.

`backend/app/services/environment_idle_service.py`:

```python
"""B5 — idle detection, derived in SQL on read.

NO DIALECT DATE ARITHMETIC. `boundary - N days` with a per-row N would need
PostgreSQL's interval syntax or SQLite's datetime(), and neither is portable.
Instead every distinct threshold is resolved to a plain INSTANT in Python and
injected as a literal in a CASE over tier_id — portable, indexable, and the
same trick `expiry_boundary` uses to keep a day-granular rule out of SQL.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import DateTime, and_, case, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_states import INACTIVE_BOOKING_STATUSES
from app.core.day_boundaries import expiry_boundary
from app.db.models.booking import Booking
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_tier import EnvironmentTier
from app.services import environment_lifecycle_policy_service


@dataclass(frozen=True)
class IdleState:
    """Everything the clause needs, resolved once per request."""

    enabled: bool
    cutoff_expr: object  # a SQL expression, or None when disabled


async def idle_state(db: AsyncSession, tenant_id: int, now: datetime) -> IdleState:
    policy = await environment_lifecycle_policy_service.get_policy(db, tenant_id)
    if not policy.idle_detection_enabled:
        return IdleState(enabled=False, cutoff_expr=None)

    boundary = expiry_boundary(now)
    default_cutoff = boundary - timedelta(days=policy.idle_threshold_days)

    overrides = (
        await db.execute(
            select(EnvironmentTier.id, EnvironmentTier.idle_threshold_days).where(
                EnvironmentTier.tenant_id == tenant_id,
                EnvironmentTier.idle_threshold_days.is_not(None),
            )
        )
    ).all()

    dt = DateTime(timezone=True)
    if not overrides:
        expr = literal(default_cutoff, dt)
    else:
        expr = case(
            *[
                (Environment.tier_id == tier_id,
                 literal(boundary - timedelta(days=days), dt))
                for tier_id, days in overrides
            ],
            else_=literal(default_cutoff, dt),
        )
    return IdleState(enabled=True, cutoff_expr=expr)


def idle_clause(state: IdleState, now: datetime):
    """No deployment and no booking overlapping [cutoff, now], for an ACTIVE
    environment older than its own threshold.

    Returns a always-false literal when detection is disabled, so callers need
    no branch and `?idle=false` still means what it says.
    """
    if not state.enabled:
        return literal(False)

    cutoff = state.cutoff_expr

    no_deployment = ~(
        select(Deployment.id)
        .where(
            Deployment.environment_id == Environment.id,
            Deployment.tenant_id == Environment.tenant_id,
            Deployment.deployed_at >= cutoff,
        )
        .exists()
    )
    # Overlap, not start: half-open, matching conflict_service's convention.
    no_booking = ~(
        select(Booking.id)
        .where(
            Booking.environment_id == Environment.id,
            Booking.tenant_id == Environment.tenant_id,
            Booking.deleted_at.is_(None),
            Booking.status.notin_(INACTIVE_BOOKING_STATUSES),
            Booking.start_date < now,
            Booking.end_date > cutoff,
        )
        .exists()
    )
    return and_(
        Environment.status == EnvironmentStatus.ACTIVE,
        Environment.created_at <= cutoff,
        no_deployment,
        no_booking,
    )
```

**Check before you finish:** if `Deployment` carries a `deleted_at`, add
`Deployment.deleted_at.is_(None)` to the first EXISTS. Read the model; do not
assume either way.

- [ ] **Step 5: Wire it into `environment_service.list_environments`**

Add `idle: Optional[bool] = None` and `now: Optional[datetime] = None`
parameters (defaulting `now` to `datetime.now(timezone.utc)` **once**, at the
top — one clock decides the filter and every rendered value, or a row on its
boundary is selected by one and rendered by the other). Resolve `idle_state`
once, label the clause into the view select as `idle`, and apply it as a
`WHERE` only when `idle is not None`.

`EnvironmentView` gains `idle: bool` as a **required-positional** field, beside
B2's `quarantined`, for the reason recorded there.

- [ ] **Step 6: Add the query parameter**

In `environments.py`, beside `quarantined`:

```python
    idle: Optional[bool] = Query(
        None,
        description=(
            "No deployment and no booking for the tier's or tenant's threshold. "
            "Advisory only — nothing is refused or changed on account of it. No "
            "selection is an OMITTED key; an empty value is a 422."
        ),
    ),
```

**Do not add `idle` to `ENVIRONMENT_SORTS`.** It is a correlated EXISTS, not a
column `apply_sort` can address; whitelisting it would 500 on a bare
`?sort_by=idle`.

- [ ] **Step 7: Run the focused tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/services/test_environment_idle.py tests/integration/test_environments.py -q`
Expected: PASS.

- [ ] **Step 8: Run both full suites**

The `CASE` expression and the literal-typed datetimes are exactly where the two
engines diverge. Launch both in the background per the Global Constraints.

Expected: no new failures on either leg.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/environment_idle_service.py \
        backend/app/services/environment_service.py \
        backend/app/services/environment_health_service.py \
        backend/app/api/v1/environments.py \
        backend/tests/services/test_environment_idle.py
git commit -m "feat(b5): idle detection derived in SQL, and the status-literal fix it exposed"
```

---

## Task 4: The computed state and its SQL predicate

**Files:**
- Create: `backend/app/services/environment_decommission_service.py`, `backend/tests/services/test_decommission_state.py`

**Interfaces:**
- Consumes: `EnvironmentDecommission` (Task 1), state constants (Task 1), `expiry_boundary`
- Produces: `def decommission_state(row: EnvironmentDecommission, now: datetime) -> str`; `def state_predicate(state: str, now: datetime)`; `def live_predicate(now: datetime)`

- [ ] **Step 1: Write the failing test**

`backend/tests/services/test_decommission_state.py`:

```python
"""B5 Task 4 — the state is COMPUTED, and its SQL predicate reproduces the same
branch order. Two mechanisms answering one question: every state test asserts
both, because that is the shape this codebase has repeatedly paid for."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.decommission_states import (
    STATE_CANCELLED, STATE_DUE, STATE_EXTENSION_REQUESTED, STATE_TORN_DOWN,
    STATE_WARNED, DECOMMISSION_STATES,
)
from app.db.models.environment_decommission import EnvironmentDecommission
from app.services.environment_decommission_service import (
    decommission_state, state_predicate,
)

NOW = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


def _row(**kw) -> EnvironmentDecommission:
    base = dict(
        warned_at=NOW - timedelta(days=1),
        scheduled_teardown_at=NOW + timedelta(days=4),
    )
    base.update(kw)
    return EnvironmentDecommission(**base)


def test_a_fresh_decommission_is_warned():
    assert decommission_state(_row(), NOW) == STATE_WARNED


def test_it_becomes_due_once_the_notice_elapses():
    row = _row(scheduled_teardown_at=NOW - timedelta(days=1))
    assert decommission_state(row, NOW) == STATE_DUE


def test_the_teardown_day_itself_is_still_warned():
    """A DEADLINE IS A DAY. At instant precision this reads `due` from one
    minute past midnight on its own teardown day, and ?state=warned then hides
    exactly the rows closest to their deadline — A4's bug, and B2's."""
    row = _row(scheduled_teardown_at=NOW.replace(hour=0, minute=0))
    assert decommission_state(row, NOW) == STATE_WARNED


def test_an_undecided_extension_outranks_the_clock():
    row = _row(
        scheduled_teardown_at=NOW - timedelta(days=1),
        extension_requested_at=NOW - timedelta(hours=2),
    )
    assert decommission_state(row, NOW) == STATE_EXTENSION_REQUESTED


def test_a_decided_extension_falls_through_to_the_clock():
    """Granting MOVES scheduled_teardown_at and LEAVES the block as the record
    of the decision, so branch 3 stops matching and the audit trail survives."""
    row = _row(
        scheduled_teardown_at=NOW + timedelta(days=30),
        extension_requested_at=NOW - timedelta(days=2),
        extension_decided_at=NOW - timedelta(days=1),
        extension_granted=True,
    )
    assert decommission_state(row, NOW) == STATE_WARNED


def test_torn_down_outranks_an_undecided_extension():
    row = _row(
        extension_requested_at=NOW - timedelta(days=2),
        torn_down_at=NOW - timedelta(hours=1),
    )
    assert decommission_state(row, NOW) == STATE_TORN_DOWN


def test_cancelled_outranks_everything():
    row = _row(
        extension_requested_at=NOW - timedelta(days=2),
        torn_down_at=NOW - timedelta(hours=1),
        cancelled_at=NOW - timedelta(minutes=1),
    )
    assert decommission_state(row, NOW) == STATE_CANCELLED


@pytest.mark.asyncio
@pytest.mark.parametrize("state", DECOMMISSION_STATES)
async def test_the_predicate_and_the_function_agree(db_session, tenant, state, decommission_fixtures):
    """One fixture spanning all five branches, including rows ON their boundary
    day. The filter and the rendered chip must not disagree."""
    rows = (
        await db_session.execute(
            select(EnvironmentDecommission).where(
                EnvironmentDecommission.tenant_id == tenant.id,
                state_predicate(state, NOW),
            )
        )
    ).scalars().all()

    selected = {r.id for r in rows}
    computed = {
        r.id for r in decommission_fixtures if decommission_state(r, NOW) == state
    }
    assert selected == computed


def test_an_unknown_state_raises():
    with pytest.raises(ValueError):
        state_predicate("nonsense", NOW)
```

Add a `decommission_fixtures` fixture to that module creating one row per
branch plus two boundary rows (`scheduled_teardown_at` at exactly
`expiry_boundary(NOW)` and one second before it), using `ensure_environment`
and `ensure_user` from `tests/factories.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/services/test_decommission_state.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the state function and predicate**

```python
def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes where PostgreSQL hands back aware ones.
    A copy of contention_service._utc, copied rather than imported for the
    reason recorded there. The rule that must NOT be copied is the day boundary.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def decommission_state(row: EnvironmentDecommission, now: datetime) -> str:
    """COMPUTED, never stored — which is why B5 needs no scheduler.

    THE BRANCH ORDER IS THE RULE. Cancelled outranks torn down (a record can be
    both if someone cancels a mistaken teardown), torn down outranks an
    undecided extension (the environment is gone; the request is moot), and an
    undecided extension outranks the clock (the owner is owed an answer before
    the notice runs out).

    THE TEARDOWN DAY ITSELF IS STILL `warned`. Compared against
    expiry_boundary(now) — the start of today — not against `now`. See that
    function for the defect this avoids and the two sub-projects that paid for
    it.
    """
    if row.cancelled_at is not None:
        return STATE_CANCELLED
    if row.torn_down_at is not None:
        return STATE_TORN_DOWN
    if row.extension_requested_at is not None and row.extension_decided_at is None:
        return STATE_EXTENSION_REQUESTED
    if _utc(row.scheduled_teardown_at) >= expiry_boundary(now):
        return STATE_WARNED
    return STATE_DUE


def state_predicate(state: str, now: datetime):
    """The five states as SQL, over the same columns `decommission_state` reads.

    IN SQL, NEVER IN PYTHON: a worklist filtered after the page was fetched
    would window the unfiltered set, and X-Total-Count would describe the wrong
    total. The branch order above is REPRODUCED here, not approximated.
    """
    boundary = expiry_boundary(now)
    D = EnvironmentDecommission

    not_terminal = and_(D.cancelled_at.is_(None), D.torn_down_at.is_(None))
    no_open_extension = or_(
        D.extension_requested_at.is_(None),
        D.extension_decided_at.is_not(None),
    )

    if state == STATE_CANCELLED:
        return D.cancelled_at.is_not(None)
    if state == STATE_TORN_DOWN:
        return and_(D.cancelled_at.is_(None), D.torn_down_at.is_not(None))
    if state == STATE_EXTENSION_REQUESTED:
        return and_(
            not_terminal,
            D.extension_requested_at.is_not(None),
            D.extension_decided_at.is_(None),
        )
    if state == STATE_WARNED:
        return and_(not_terminal, no_open_extension,
                    D.scheduled_teardown_at >= boundary)
    if state == STATE_DUE:
        return and_(not_terminal, no_open_extension,
                    D.scheduled_teardown_at < boundary)
    raise ValueError(f"unknown decommission state {state!r}")


def live_predicate(now: datetime):
    """A decommission that still constrains bookings: not cancelled, not torn
    down, not soft-deleted. Task 8's refusal hangs off exactly this."""
    D = EnvironmentDecommission
    return and_(
        D.deleted_at.is_(None),
        D.cancelled_at.is_(None),
        D.torn_down_at.is_(None),
    )
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/services/test_decommission_state.py -q`
Expected: PASS, including both parametrised boundary rows.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_decommission_service.py \
        backend/tests/services/test_decommission_state.py
git commit -m "feat(b5): the decommission state, computed, with its SQL predicate"
```

---

## Task 5: Initiating a decommission, and the permission rules

**Files:**
- Modify: `backend/app/services/environment_decommission_service.py`
- Create: `backend/app/api/v1/decommissions.py`, `backend/app/api/v1/schemas/decommission.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_decommission_api.py`

**Interfaces:**
- Produces: `async def assert_may_run(db, environment, user)`; `async def assert_may_defend(db, environment, user)`; `async def initiate(db, tenant_id, environment_id, user, *, reason, scheduled_teardown_at=None) -> EnvironmentDecommission`; `async def get_live(db, tenant_id, environment_id) -> Optional[EnvironmentDecommission]`

- [ ] **Step 1: Write the failing test**

```python
"""B5 Task 5 — initiating, and the two permission rules."""
import pytest


@pytest.mark.asyncio
async def test_the_operations_team_may_initiate(client, team_headers, env_with_team):
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "Project closed"},
    )
    assert r.status_code == 201
    assert r.json()["state"] == "warned"


@pytest.mark.asyncio
async def test_the_teardown_date_defaults_to_the_notice_period(
    client, team_headers, env_with_team
):
    """§2.12's five-day warning, from the tenant's decommission_notice_days."""
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "Project closed"},
    )
    body = r.json()
    warned = datetime.fromisoformat(body["warned_at"])
    teardown = datetime.fromisoformat(body["scheduled_teardown_at"])
    assert (teardown - warned).days == 5


@pytest.mark.asyncio
async def test_the_initiator_may_set_a_later_date(client, team_headers, env_with_team):
    later = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "End of contract", "scheduled_teardown_at": later},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_the_initiator_may_not_shorten_the_notice(client, team_headers, env_with_team):
    """An initiator who could shorten the notice would make the five-day
    warning advisory, and the booking refusal derives from this date."""
    sooner = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "Urgent", "scheduled_teardown_at": sooner},
    )
    assert r.status_code == 422
    assert "notice" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_stranger_may_not_initiate(client, other_member_headers, env_with_team):
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=other_member_headers,
        json={"reason": "no"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_an_admin_may_always_initiate(client, auth_headers, env_with_team):
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=auth_headers,
        json={"reason": "Admin override"},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_with_no_operations_group_the_gate_degrades_to_admin_only(
    client, auth_headers, member_headers, env_without_team
):
    """B3b's rule, carried over verbatim. operations_group_id is nullable and
    most environments have no group yet; a permission resolving to nobody is a
    stuck workflow."""
    refused = await client.post(
        f"/api/v1/environments/{env_without_team.id}/decommission",
        headers=member_headers, json={"reason": "no"},
    )
    assert refused.status_code == 403

    allowed = await client.post(
        f"/api/v1/environments/{env_without_team.id}/decommission",
        headers=auth_headers, json={"reason": "yes"},
    )
    assert allowed.status_code == 201


@pytest.mark.asyncio
async def test_only_one_live_decommission_per_environment(
    client, team_headers, env_with_team
):
    first = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "one"},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "two"},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_a_reason_is_required(client, team_headers, env_with_team):
    """A decommission with no stated reason is not an audit record."""
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "   "},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_another_tenants_environment_is_404_not_403(
    client, team_headers, foreign_env
):
    r = await client.post(
        f"/api/v1/environments/{foreign_env.id}/decommission",
        headers=team_headers, json={"reason": "no"},
    )
    assert r.status_code == 404
```

Fixtures to add in this module: `env_with_team` (an environment whose
`operations_group_id` points at a group containing the `team_headers` user),
`env_without_team`, `foreign_env` (another tenant's), and header fixtures for a
team member, a plain member and a member of a different team.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_decommission_api.py -q`
Expected: FAIL — 404 on the route.

- [ ] **Step 3: Write the permission helpers**

Read `environment_request_service.assert_may_transition` and
`environment_service.assert_may_edit_handover` **first** — these are the second
and third readers of group membership and **all three must stay in step**: same
tenant scoping, same Admin-or-master bypass, same degradation to Admin-only
when the group is empty or absent.

```python
async def assert_may_run(db, environment, user) -> None:
    """The operating team, or an Admin / master admin. Everything except
    requesting an extension goes through here."""


async def assert_may_defend(db, environment, user) -> None:
    """The environment's NAMED OWNER, or an Admin.

    The party being acted upon is NOT gated on team membership — B3b gated a
    requester's own submission on membership and made the primary journey
    impossible, because the person defending an environment is by definition
    not on the team decommissioning it.
    """
```

- [ ] **Step 4: Write `initiate` and `get_live`**

`initiate` must, in this order: resolve the environment (404 across tenants,
never 403), `assert_may_run`, reject a blank reason, refuse a second live row
with **409**, compute `scheduled_teardown_at` as
`warned_at + policy.decommission_notice_days` and **refuse an earlier
caller-supplied date with 422**, then insert.

`get_live` selects the one row matching `live_predicate(now)` for that
environment and tenant.

- [ ] **Step 5: Write the schemas and the route**

`DecommissionCreate` with `extra="forbid"`, `reason: str = Field(min_length=1)`
and an optional `scheduled_teardown_at`. `DecommissionRead` carries `state` as
a **required** field, computed in the response builder — never
`model_validate(row)`, which cannot produce it (the same reason B4's
`protection_level` is set explicitly in `_to_response`). Mount the router in
`main.py`.

**Two routes, not one:**

- `POST /environments/{id}/decommission` -- initiate.
- `GET /environments/{id}/decommission` -- the live record, or the most
  recent terminal one when there is no live record, or **null**. A 404 for
  'this environment has never been decommissioned' would make the panel's
  normal case an error path; null is the answer, and the panel renders its
  initiate control from it.

- [ ] **Step 6: Run the tests, then commit**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_decommission_api.py -q`
Expected: PASS.

```bash
git commit -am "feat(b5): initiate a decommission, with the team/owner permission split"
```

---

## Task 6: The extension

**Files:**
- Modify: `backend/app/services/environment_decommission_service.py`, `backend/app/api/v1/decommissions.py`, `backend/app/api/v1/schemas/decommission.py`
- Test: `backend/tests/integration/test_decommission_api.py` (append)

**Interfaces:**
- Produces: `async def request_extension(db, decommission, user, *, reason, until)`; `async def decide_extension(db, decommission, user, *, granted)`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_the_owner_may_request_an_extension(client, owner_headers, live_decommission):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers,
        json={"reason": "UAT runs to month end", "until": _iso(days=30)},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "extension_requested"


@pytest.mark.asyncio
async def test_granting_moves_the_date_and_keeps_the_record(
    client, team_headers, owner_headers, live_decommission
):
    """Branch 3 stops matching and the row falls through to `warned` on the new
    clock — the audit trail survives because the block is not cleared."""
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers,
        json={"reason": "need it", "until": _iso(days=30)},
    )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": True},
    )
    body = r.json()
    assert body["state"] == "warned"
    assert body["extension_granted"] is True
    assert body["extension_reason"] == "need it"
    assert body["scheduled_teardown_at"].startswith(_iso(days=30)[:10])


@pytest.mark.asyncio
async def test_refusing_moves_nothing(client, team_headers, owner_headers, live_decommission):
    before = live_decommission.scheduled_teardown_at
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "please", "until": _iso(days=30)},
    )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": False},
    )
    assert r.json()["extension_granted"] is False
    assert r.json()["scheduled_teardown_at"] == before.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_only_one_extension_per_decommission(
    client, team_headers, owner_headers, live_decommission
):
    """A second request is refused, pointing at cancel-and-re-raise."""
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "first", "until": _iso(days=30)},
    )
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": False},
    )
    second = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "again", "until": _iso(days=60)},
    )
    assert second.status_code == 409
    assert "cancel" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_the_team_may_not_request_an_extension_on_the_owners_behalf(
    client, team_headers, live_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=team_headers, json={"reason": "x", "until": _iso(days=30)},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_may_not_decide_their_own_request(
    client, owner_headers, live_decommission
):
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": _iso(days=30)},
    )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=owner_headers, json={"granted": True},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_an_extension_must_be_later_than_the_current_date(
    client, owner_headers, live_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": _iso(days=1)},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_torn_down_decommission_takes_no_extension(
    client, owner_headers, torn_down_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{torn_down_decommission.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": _iso(days=30)},
    )
    assert r.status_code == 409
```

- [ ] **Step 2: Run to verify they fail** — Expected: 404 on both routes.

- [ ] **Step 3: Implement**

`request_extension`: `assert_may_defend`; 409 if the row is not live; 409 if
`extension_requested_at` is already set, with a message naming
cancel-and-re-raise; 422 if `until` is not after the current
`scheduled_teardown_at`; then set the four request fields.

`decide_extension`: `assert_may_run`; 409 if there is no undecided request;
set `extension_decided_at/by` and `extension_granted`; **and on grant only**,
`scheduled_teardown_at = extension_until`. Clear nothing.

- [ ] **Step 4: Run the tests, then commit**

```bash
git commit -am "feat(b5): the extension request and its decision"
```

---

## Task 7: Attestations, teardown and cancel

**Files:**
- Modify: `backend/app/services/environment_decommission_service.py`, `backend/app/api/v1/decommissions.py`, `backend/app/api/v1/schemas/decommission.py`
- Test: `backend/tests/integration/test_decommission_api.py` (append)

**Interfaces:**
- Produces: `async def sign_attestation(db, decommission, user, *, step_key, reference, notes)`; `async def tear_down(db, decommission, user)`; `async def cancel(db, decommission, user, *, reason)`; `async def missing_required_steps(db, decommission) -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_teardown_is_refused_until_every_required_step_is_signed(
    client, team_headers, live_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    # NAMING the missing steps — a bare "not allowed" on a checklist is
    # unactionable.
    assert "final_backup" in detail and "teardown" in detail


@pytest.mark.asyncio
async def test_signing_every_step_permits_teardown(client, team_headers, live_decommission):
    for key in ("final_backup", "teardown"):
        s = await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers,
            json={"step_key": key, "reference": "SNAP-1", "notes": None},
        )
        assert s.status_code == 201

    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert r.status_code == 200
    assert r.json()["state"] == "torn_down"


@pytest.mark.asyncio
async def test_teardown_decommissions_the_environment(
    client, team_headers, db_session, live_decommission
):
    """THE ONE ACTING STEP. This and the booking refusal are the whole of what
    B5 changes outside its own records."""
    for key in ("final_backup", "teardown"):
        await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers, json={"step_key": key, "reference": "x", "notes": None},
        )
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )

    env = await db_session.get(Environment, live_decommission.environment_id)
    await db_session.refresh(env)
    assert env.status == EnvironmentStatus.DECOMMISSIONED


@pytest.mark.asyncio
async def test_an_optional_step_does_not_gate_teardown(
    client, team_headers, db_session, tenant, live_decommission
):
    step = EnvironmentDecommissionStep(
        tenant_id=tenant.id, key="dns", label="DNS removed",
        display_order=30, is_required=False, is_active=True,
    )
    db_session.add(step)
    await db_session.flush()

    for key in ("final_backup", "teardown"):
        await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers, json={"step_key": key, "reference": "x", "notes": None},
        )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_an_inactive_step_does_not_gate_teardown(
    client, team_headers, db_session, tenant, live_decommission
):
    """A retired step stops being required; it does not freeze the workflow."""


@pytest.mark.asyncio
async def test_a_step_may_be_signed_only_once(client, team_headers, live_decommission):
    first = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers, json={"step_key": "final_backup", "reference": "a", "notes": None},
    )
    assert first.status_code == 201
    again = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers, json={"step_key": "final_backup", "reference": "b", "notes": None},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_an_unknown_step_key_is_refused(client, team_headers, live_decommission):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers, json={"step_key": "invented", "reference": None, "notes": None},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_admin_may_always_cancel(client, auth_headers, live_decommission):
    """THE ESCAPE HATCH. A4 established that an approval workflow without one
    produces unrecoverable states, and B3b shipped two."""
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/cancel",
        headers=auth_headers, json={"reason": "Kept after all"},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_cancelling_leaves_the_environment_active(
    client, auth_headers, db_session, live_decommission
):
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/cancel",
        headers=auth_headers, json={"reason": "Kept"},
    )
    env = await db_session.get(Environment, live_decommission.environment_id)
    await db_session.refresh(env)
    assert env.status == EnvironmentStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_cancelled_decommission_frees_the_environment_for_a_new_one(
    client, auth_headers, team_headers, live_decommission, env_with_team
):
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/cancel",
        headers=auth_headers, json={"reason": "Kept"},
    )
    again = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "Actually no"},
    )
    assert again.status_code == 201


@pytest.mark.asyncio
async def test_teardown_reports_the_bookings_it_did_not_touch(
    client, team_headers, live_decommission, booking_after_teardown
):
    """SURFACES, never touches. The response names them; the rows are unchanged
    — the guard test in Task 15 proves the second half."""
    for key in ("final_backup", "teardown"):
        await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers, json={"step_key": key, "reference": "x", "notes": None},
        )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert booking_after_teardown.id in [b["id"] for b in r.json()["remaining_bookings"]]
```

Fill in the body of `test_an_inactive_step_does_not_gate_teardown` following
the optional-step test above it: create a step, set `is_active=False`, sign
only the two seeded steps, assert 200.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`missing_required_steps` selects active, required, non-deleted steps for the
tenant and subtracts the signed `step_key`s. `sign_attestation` validates the
key against that vocabulary (422), 409s on a duplicate, and refuses a
non-live row. `tear_down` calls `assert_may_run`, 409s if not live, 422s
naming `missing_required_steps`, then sets `torn_down_at/by` **and**
`environment.status = EnvironmentStatus.DECOMMISSIONED`. `cancel` sets the
three cancel fields and touches nothing else.

- [ ] **Step 4: Run the tests, then commit**

```bash
git commit -am "feat(b5): attestations, gated teardown, and the cancel escape hatch"
```

---

## Task 8: The booking refusal

**Files:**
- Modify: `backend/app/services/booking_request_service.py`, `backend/app/services/booking_service.py`
- Create: `backend/tests/integration/test_decommission_booking_refusal.py`

**Interfaces:**
- Consumes: `live_predicate` (Task 4)
- Produces: `async def assert_bookable(db, tenant_id, environment_ids, start, end) -> None` in `environment_decommission_service` — raises 409 naming the environment and the teardown date

- [ ] **Step 1: Write the failing tests**

**One test per create path.** A test covering one path proves nothing about
the others — this is the `exclusive_use_requested` asymmetry CLAUDE.md still
lists as open, and the whole reason this task exists as its own gate.

```python
"""B5 Task 8 — a booking running past teardown is refused, on EVERY path.

THE THREE CREATE PATHS ARE INDEPENDENT CODE. booking_request_service has two of
them (create_request and add_environment, the second being a create in disguise
that a grep-by-endpoint sweep misses) and booking_service has the third, which
release_booking_service delegates to.
"""

@pytest.mark.asyncio
async def test_a_booking_ending_before_teardown_is_accepted(
    client, auth_headers, env_being_decommissioned
):
    r = await client.post("/api/v1/booking-requests/", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id),
        "start_date": _iso(days=1), "end_date": _iso(days=2),
    })
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_create_request_refuses_a_booking_past_teardown(
    client, auth_headers, env_being_decommissioned
):
    r = await client.post("/api/v1/booking-requests/", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id),
        "start_date": _iso(days=1), "end_date": _iso(days=20),
    })
    assert r.status_code == 409
    assert env_being_decommissioned.name in r.json()["detail"]


@pytest.mark.asyncio
async def test_add_environment_refuses_a_booking_past_teardown(
    client, auth_headers, existing_request, env_being_decommissioned
):
    """A CREATE IN DISGUISE. This is the path a sweep by endpoint name misses."""
    r = await client.post(
        f"/api/v1/booking-requests/{existing_request.id}/environments",
        headers=auth_headers,
        json={"environment_id": env_being_decommissioned.id},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_the_legacy_booking_path_refuses_a_booking_past_teardown(
    client, auth_headers, env_being_decommissioned
):
    r = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_being_decommissioned.id,
        "start_date": _iso(days=1), "end_date": _iso(days=20),
        "booking_type_id": 1, "purpose": "x",
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_extending_an_existing_booking_past_teardown_is_refused(
    client, auth_headers, existing_booking, env_being_decommissioned
):
    """Moving an end date past teardown is the same act as booking past it."""
    r = await client.patch(
        f"/api/v1/booking-requests/{existing_booking.booking_request_id}/standard-fields",
        headers=auth_headers, json={"end_date": _iso(days=20)},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_granting_an_extension_permits_the_longer_booking_with_no_second_write(
    client, auth_headers, team_headers, owner_headers, env_being_decommissioned,
    live_decommission
):
    """THE WHOLE POINT OF THE DATE RULE. Nothing lifts a flag; the line moves."""
    refused = await client.post("/api/v1/booking-requests/", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id),
        "start_date": _iso(days=1), "end_date": _iso(days=20),
    })
    assert refused.status_code == 409

    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "need it", "until": _iso(days=60)},
    )
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": True},
    )

    accepted = await client.post("/api/v1/booking-requests/", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id),
        "start_date": _iso(days=1), "end_date": _iso(days=20),
    })
    assert accepted.status_code == 201


@pytest.mark.asyncio
async def test_a_cancelled_decommission_refuses_nothing(
    client, auth_headers, env_being_decommissioned, cancelled_decommission
):
    r = await client.post("/api/v1/booking-requests/", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id),
        "start_date": _iso(days=1), "end_date": _iso(days=99),
    })
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_a_decommissioned_environment_takes_no_bookings_at_all(
    client, auth_headers, decommissioned_env
):
    """The degenerate case B5 also closes: nothing today looks at
    environment.status on any create path."""
    r = await client.post("/api/v1/booking-requests/", headers=auth_headers, json={
        **_request_body(decommissioned_env.id),
        "start_date": _iso(days=1), "end_date": _iso(days=2),
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_an_environment_with_no_decommission_is_unaffected(
    client, auth_headers, plain_env
):
    r = await client.post("/api/v1/booking-requests/", headers=auth_headers, json={
        **_request_body(plain_env.id),
        "start_date": _iso(days=1), "end_date": _iso(days=400),
    })
    assert r.status_code == 201
```

- [ ] **Step 2: Run to verify they fail** — every refusal test returns 201.

- [ ] **Step 3: Prove you found every path before writing the rule**

Run all of these and reconcile the results against the three call sites you are
about to edit. Any hit you cannot account for is a fourth path:

```bash
cd backend
grep -rn "Booking(" app/services/ app/api/
grep -rn "environment_id=" app/services/booking_service.py app/services/booking_request_service.py
grep -rn "start_date" app/services/ | grep -i "update\|patch\|edit"
```

- [ ] **Step 4: Implement `assert_bookable` and call it from every path**

```python
async def assert_bookable(
    db: AsyncSession, tenant_id: int, environment_ids: Sequence[int],
    start: datetime, end: datetime,
) -> None:
    """Refuse a booking that runs past a live decommission's teardown date.

    THE RULE IS THE DATE, NOT THE EXISTENCE OF A DECOMMISSION. The environment
    still exists until teardown and a team may legitimately need it next week; a
    blanket refusal would need a carve-out for exactly that, and granting an
    extension would need a second write to lift a stored flag. Here the line
    simply moves.

    BATCHED — one query for every environment on the request, not one per
    environment. A group booking may name a dozen.
    """
```

It runs one select over `EnvironmentDecommission` joined to `Environment`,
filtered by `live_predicate(now)`, `environment_id.in_(environment_ids)` and
`scheduled_teardown_at < end`; plus a second condition catching
`Environment.status == EnvironmentStatus.DECOMMISSIONED` for any of the ids.
Every refusal names **the environment and the date** — `Environment.name` is
already available, and CLAUDE.md's display-names rule forbids `env #N`.

Call it from `create_request`, `add_environment`, `create_booking`, and the
`standard-fields` date-update path.

- [ ] **Step 5: Run the focused tests**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_decommission_booking_refusal.py -q`
Expected: PASS, all ten.

- [ ] **Step 6: Run both full suites**

This task adds a refusal to the busiest write paths in the application. Both
legs, in the background, per the Global Constraints.
Expected: no new failures. **If an unrelated booking test now 409s, you have
made the rule too broad** — read it before relaxing the test.

- [ ] **Step 7: Commit**

```bash
git commit -am "feat(b5): refuse a booking that runs past a scheduled teardown, on every create path"
```

---

## Task 9: The worklist

**Files:**
- Modify: `backend/app/services/environment_decommission_service.py`, `backend/app/api/v1/decommissions.py`
- Test: `backend/tests/integration/test_decommission_worklist.py`

**Interfaces:**
- Produces: `async def list_decommissions(db, tenant_id, *, state, page, sort, now) -> tuple[list[DecommissionView], int]`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_the_worklist_filters_by_state_in_sql(client, auth_headers, mixed_decommissions):
    r = await client.get("/api/v1/decommissions?state=due", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "2"
    assert {row["state"] for row in r.json()} == {"due"}


@pytest.mark.asyncio
async def test_no_state_selection_is_an_omitted_key(client, auth_headers, mixed_decommissions):
    """`any` client-side, an OMITTED key on the wire. Never `all` — that is
    buildParams' own sentinel, and A3, A4, B2 and B4 each collided with it."""
    r = await client.get("/api/v1/decommissions", headers=auth_headers)
    assert int(r.headers["X-Total-Count"]) == len(mixed_decommissions)


@pytest.mark.asyncio
async def test_an_empty_state_is_a_422_not_an_ignored_param(client, auth_headers):
    r = await client.get("/api/v1/decommissions?state=", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_the_rendered_state_matches_the_filter(client, auth_headers, boundary_decommission):
    """ONE CLOCK decides the filter and every rendered state. Taken twice, a row
    whose deadline falls between the two reads is selected as warned and
    rendered as due."""
    r = await client.get("/api/v1/decommissions?state=warned", headers=auth_headers)
    ids = [row["id"] for row in r.json()]
    assert boundary_decommission.id in ids
    row = next(x for x in r.json() if x["id"] == boundary_decommission.id)
    assert row["state"] == "warned"


@pytest.mark.asyncio
async def test_paging_is_stable_across_ties(client, auth_headers, same_date_decommissions):
    """Ordered by a UNIQUE key: without the primary-key tiebreaker LIMIT/OFFSET
    duplicates and drops rows once ties exist, and these all share a date."""
    first = await client.get("/api/v1/decommissions?limit=2&offset=0", headers=auth_headers)
    second = await client.get("/api/v1/decommissions?limit=2&offset=2", headers=auth_headers)
    ids = [r["id"] for r in first.json()] + [r["id"] for r in second.json()]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_an_unknown_sort_is_a_422_not_a_silent_fallback(client, auth_headers):
    r = await client.get("/api/v1/decommissions?sort_by=invented", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_names_travel_with_the_row(client, auth_headers, mixed_decommissions):
    """The environment name, the initiator and the owner resolve server-side —
    a picker fetch would read a capped list and render `—`."""
    row = (await client.get("/api/v1/decommissions", headers=auth_headers)).json()[0]
    assert row["environment_name"]
    assert row["initiated_by_username"]


@pytest.mark.asyncio
async def test_another_tenants_decommissions_are_invisible(client, auth_headers, foreign_decommission):
    r = await client.get("/api/v1/decommissions", headers=auth_headers)
    assert foreign_decommission.id not in [row["id"] for row in r.json()]
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`sorting()` whitelist: `scheduled_teardown_at`, `warned_at`, `environment`
(→ `Environment.name`). **`state` is not in it** — it is computed, and
whitelisting it would 500. Chain `apply_sort(query, sort).order_by(
EnvironmentDecommission.id)` — **before** the tiebreaker, never instead of it.
Take `now` **once** at the top of the endpoint and pass it to both
`state_predicate` and every rendered row.

Resolve `environment_name`, `initiated_by_username` and `owner_username` in
**batch** lookups that do **not** filter `deleted_at` — read-rendering
lookups, following `get_project_names` and `get_environment_names`. And do not
tenant-qualify the username join: under master-admin impersonation the
initiator may legitimately sit outside the row's tenant, and A3's ack lost
exactly that name to a `User.tenant_id ==` join.

- [ ] **Step 4: Surface `decommission_state` on the environment list**

The File Structure promises it and Task 11 renders it; this is where it is
built, now that every state is reachable.

Add to `environment_service._view_query` a **correlated scalar subquery**
selecting the live decommission's fields, then compute the label per row from
the **same clock** the page's other derivations use. `EnvironmentView` gains
`decommission_state: Optional[str]` as a **required-positional** field, beside
`idle` and B2's `quarantined`.

A LEFT JOIN would be wrong here: an environment may have several terminal
decommissions and one live one, and a join over them multiplies its row. Filter
the subquery with `live_predicate(now)`.

Write these tests in `tests/services/test_environment_idle.py`:

```python
@pytest.mark.asyncio
async def test_the_list_carries_the_live_decommission_state(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    await _warn(db_session, tenant.id, env, teardown=NOW + timedelta(days=4))

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, now=NOW
    )
    row = next(v for v in views if v.environment.id == env.id)
    assert row.decommission_state == "warned"


@pytest.mark.asyncio
async def test_an_environment_with_no_decommission_carries_null(db_session, tenant):
    # Null means "never decommissioned". The grid cell renders NOTHING for it —
    # never an empty chip, which reads as a state of its own.
    env = await ensure_environment(db_session, tenant.id, slot=1)

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, now=NOW
    )
    row = next(v for v in views if v.environment.id == env.id)
    assert row.decommission_state is None


@pytest.mark.asyncio
async def test_a_cancelled_decommission_leaves_the_row_null(db_session, tenant):
    # Only a LIVE decommission labels the row. A cancelled one is history, and a
    # row still chipped `cancelled` reads as an ongoing situation.
    env = await ensure_environment(db_session, tenant.id, slot=1)
    row_ = await _warn(db_session, tenant.id, env, teardown=NOW + timedelta(days=4))
    row_.cancelled_at = NOW - timedelta(hours=1)
    await db_session.flush()

    views, _ = await environment_service.list_environments(
        db_session, tenant.id, now=NOW
    )
    assert next(
        v for v in views if v.environment.id == env.id
    ).decommission_state is None


@pytest.mark.asyncio
async def test_several_terminal_decommissions_do_not_multiply_the_row(
    db_session, tenant
):
    # The join-versus-subquery trap: three cancelled attempts and one live one
    # must still yield ONE row for this environment.
    env = await ensure_environment(db_session, tenant.id, slot=1)
    for _ in range(3):
        dead = await _warn(db_session, tenant.id, env, teardown=NOW)
        dead.cancelled_at = NOW - timedelta(days=1)
    await _warn(db_session, tenant.id, env, teardown=NOW + timedelta(days=4))
    await db_session.flush()

    views, total = await environment_service.list_environments(
        db_session, tenant.id, now=NOW
    )
    assert total == 1
    assert len([v for v in views if v.environment.id == env.id]) == 1
```

Add a module-level `_warn(db, tenant_id, env, *, teardown)` helper creating one
`EnvironmentDecommission` through `ensure_user` for `initiated_by`.

**Expose it on the API too.** `decommission_state` must be added to
`EnvironmentResponse` in `app/api/v1/schemas/environment.py` and set in
`from_view` — REQUIRED, not defaulted. Task 3 shipped `idle` on the view and
the filter but not on the response, leaving it computed, filterable and
invisible to every consumer; Task 11 renders both fields. Do not repeat it.
Add an integration test asserting the field comes back over HTTP with the
right value, not merely that the key is present.

**Do not add `decommission_state` to `ENVIRONMENT_SORTS`** — it is computed
from a subquery, not a column, and whitelisting it would 500 on a bare
`?sort_by=decommission_state`.

- [ ] **Step 5: Run the tests, then commit**

```bash
cd backend && PYTHONPATH=. uv run pytest \
  tests/integration/test_decommission_worklist.py \
  tests/services/test_environment_idle.py -q
```

```bash
git commit -am "feat(b5): the decommission worklist, and the live state on the environment list"
```

---

## Task 10: Frontend types, service and slice

**Files:**
- Create: `frontend/src/types/decommission.ts`, `frontend/src/services/decommissionService.ts`, `frontend/src/store/decommissionSlice.ts`, `frontend/src/store/__tests__/decommissionSlice.test.ts`
- Modify: `frontend/src/types/environment.ts`, `frontend/src/store/index.ts`

**Interfaces:**
- Produces: `DecommissionState` (union of the five literals), `Decommission`, `DecommissionStep`; thunks `fetchDecommission`, `initiateDecommission`, `requestExtension`, `decideExtension`, `signAttestation`, `tearDown`, `cancelDecommission`, `fetchDecommissionWorklist`

- [ ] **Step 1: Write the failing test**

```ts
import { AxiosError } from 'axios';

describe('decommissionSlice', () => {
  it('surfaces the server reason, not the HTTP status', async () => {
    // RTK's default miniSerializeError copies only name/message/stack/code, and
    // a real Axios error's .message is "Request failed with status code 422".
    // A test rejecting with a plain Error carrying the final text PASSES WHILE
    // THE APP IS BROKEN — so this mocks the AxiosError shape.
    const err = new AxiosError('Request failed with status code 422');
    (err as AxiosError).response = {
      data: { detail: 'Sign these first: final_backup, teardown' },
      status: 422, statusText: '', headers: {}, config: {} as never,
    };
    vi.mocked(api.post).mockRejectedValueOnce(err);

    const result = await store.dispatch(tearDown(1));

    expect(result.payload).toContain('final_backup');
  });

  it('keeps the worklist total from X-Total-Count', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: [{ id: 1 }], headers: { 'x-total-count': '37' },
    });
    await store.dispatch(fetchDecommissionWorklist({ page: 0, pageSize: 25 }));
    expect(store.getState().decommission.worklistTotal).toBe(37);
  });
});
```

- [ ] **Step 2: Run to verify it fails.** `cd frontend && npx vitest run src/store/__tests__/decommissionSlice.test.ts`

- [ ] **Step 3: Implement**

Every mutating thunk uses `rejectWithValue(formatApiError(err))` from
`services/apiError.ts`, and every caller reads `result.payload` — not
`result.error.message`.

`frontend/src/types/environment.ts` gains:

```ts
  /** B5 — no deployment or booking for the threshold. Advisory only. */
  idle: boolean;
  /** B5 — the live decommission's computed state, or null if there is none. */
  decommission_state: DecommissionState | null;
```

- [ ] **Step 4: Run the tests, then commit.**

```bash
git commit -am "feat(b5): decommission types, service and slice"
```

---

## Task 11: The environment list — idle and decommission columns

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentList.tsx`
- Create: `frontend/src/pages/environments/__tests__/environmentIdleColumn.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const IDLE_ROW = { ...baseEnv, id: 1, name: 'Ghost UAT', idle: true, decommission_state: null };
const BUSY_ROW = { ...baseEnv, id: 2, name: 'Busy SIT', idle: false, decommission_state: null };
const DYING_ROW = { ...baseEnv, id: 3, name: 'Old Perf', idle: true, decommission_state: 'warned' };

describe('EnvironmentList — B5 idle and decommission', () => {
  it('renders the Idle chip only for idle rows', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [IDLE_ROW, BUSY_ROW], headers: { 'x-total-count': '2' },
    });

    renderWithProviders(<EnvironmentList />);

    await waitFor(() => expect(screen.getByText('Ghost UAT')).toBeInTheDocument());
    expect(screen.getAllByLabelText('Idle')).toHaveLength(1);
  });

  it('renders the decommission state as a chip beside it', async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [DYING_ROW], headers: { 'x-total-count': '1' },
    });

    renderWithProviders(<EnvironmentList />);

    await waitFor(() => expect(screen.getByText(/warned/i)).toBeInTheDocument());
  });

  it('renders nothing at all for a row with no decommission', async () => {
    // Never an empty chip — an empty chip reads as a state of its own.
    vi.mocked(api.get).mockResolvedValue({
      data: [BUSY_ROW], headers: { 'x-total-count': '1' },
    });

    renderWithProviders(<EnvironmentList />);

    await waitFor(() => expect(screen.getByText('Busy SIT')).toBeInTheDocument());
    expect(screen.queryByTestId('decommission-chip')).not.toBeInTheDocument();
  });

  it('sends ?idle=true when the filter is set', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });
    renderWithProviders(<EnvironmentList />);

    await userEvent.click(await screen.findByLabelText('Idle'));
    await userEvent.click(screen.getByRole('option', { name: 'Idle only' }));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        expect.stringContaining('idle=true'), expect.anything(),
      );
    });
  });

  it('omits the key entirely when the filter is Any', async () => {
    // NEVER `all` — buildParams' own sentinel. Two states building
    // byte-identical params means the grid never refetches, which is how this
    // has now bitten A3, A4, B2 and B4 in turn.
    vi.mocked(api.get).mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });
    renderWithProviders(<EnvironmentList />);

    await userEvent.click(await screen.findByLabelText('Idle'));
    await userEvent.click(screen.getByRole('option', { name: 'Any' }));

    await waitFor(() => {
      const url = vi.mocked(api.get).mock.calls.at(-1)![0];
      expect(url).not.toContain('idle=');
    });
  });

  it('does not offer Idle or Decommission as sortable columns', () => {
    // Both are computed — a correlated EXISTS and a correlated subquery — not
    // columns apply_sort can address. A bare ?sort_by=idle would 500.
    const columns = buildEnvironmentColumns(defaultArgs);

    expect(columns.find((c) => c.field === 'idle')!.sortable).toBe(false);
    expect(columns.find((c) => c.field === 'decommission_state')!.sortable).toBe(false);
  });

  it('has no custom-field column whose field collides with a static one', () => {
    // The cf_ namespacing rule. A tenant custom field keyed `idle` would
    // otherwise share a grid column id with the new static column, and MUI's
    // spurious visibility change gets PERSISTED by saveColumnModel — silently
    // hiding the real column, and unrepairable for anyone whose stored model
    // already shares the key. No fixture defines a colliding custom field, so
    // only this structural assertion can catch it.
    const columns = buildEnvironmentColumns({
      ...defaultArgs,
      customFields: [{ field_key: 'idle', label: 'Idle?' }],
    });
    const fields = columns.map((c) => c.field);

    expect(new Set(fields).size).toBe(fields.length);
    expect(fields).toContain('cf_idle');
  });

  it('reads a custom field by its RAW key, not the namespaced column id', () => {
    // The namespace is a grid-column id only. A valueGetter that looked up
    // `cf_idle` would render a correctly-named, permanently-empty column.
    const columns = buildEnvironmentColumns({
      ...defaultArgs,
      customFields: [{ field_key: 'idle', label: 'Idle?' }],
    });
    const col = columns.find((c) => c.field === 'cf_idle')!;

    expect(col.valueGetter!({ row: { custom_fields: { idle: 'yes' } } } as never))
      .toBe('yes');
  });
});
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Namespace any custom-field column as `cf_<key>`
if this page does not already (check first — `BookingList` and `SystemCatalog`
were converted on 2026-08-04, `EnvironmentList` earlier). Bind the filter to
the **draft-aware value**, and add both columns with `sortable: false`.

- [ ] **Step 4: Run the tests, then commit.**

```bash
git commit -am "feat(b5): idle and decommission columns on the environment list"
```

---

## Task 12: The decommission panel on the environment detail

**Files:**
- Create: `frontend/src/components/environments/DecommissionPanel.tsx`, `frontend/src/components/environments/__tests__/DecommissionPanel.test.tsx`
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AxiosError } from 'axios';

const WARNED = {
  id: 7, environment_id: 1, state: 'warned' as const,
  reason: 'Project closed', warned_at: '2026-08-18T09:00:00Z',
  scheduled_teardown_at: '2026-08-23T09:00:00Z',
  initiated_by_username: 'ops.alice', extension_granted: null,
  attestations: [],
};
const STEPS = [
  { id: 1, key: 'final_backup', label: 'Final backup taken', is_required: true, is_active: true },
  { id: 2, key: 'teardown', label: 'Infrastructure torn down', is_required: true, is_active: true },
];

describe('DecommissionPanel', () => {
  it('shows the teardown date and the state chip', async () => {
    renderWithProviders(<DecommissionPanel decommission={WARNED} steps={STEPS} env={ownedEnv} />);

    expect(screen.getByText(/23 Aug 2026/)).toBeInTheDocument();
    expect(screen.getByText(/warned/i)).toBeInTheDocument();
  });

  it('offers the extension control to the owner and not to a bystander', async () => {
    const { rerender } = renderWithProviders(
      <DecommissionPanel decommission={WARNED} steps={STEPS} env={ownedEnv} currentUser={owner} />,
    );
    expect(screen.getByRole('button', { name: /request extension/i })).toBeInTheDocument();

    rerender(
      <DecommissionPanel decommission={WARNED} steps={STEPS} env={ownedEnv} currentUser={bystander} />,
    );
    expect(screen.queryByRole('button', { name: /request extension/i })).not.toBeInTheDocument();
  });

  it('lists every required step with its signer once signed', async () => {
    const signed = {
      ...WARNED,
      attestations: [
        { step_key: 'final_backup', signed_by_username: 'ops.bob',
          signed_at: '2026-08-19T10:00:00Z', reference: 'SNAP-42' },
      ],
    };

    renderWithProviders(<DecommissionPanel decommission={signed} steps={STEPS} env={ownedEnv} />);

    expect(screen.getByText('Final backup taken')).toBeInTheDocument();
    expect(screen.getByText(/ops\.bob/)).toBeInTheDocument();
    expect(screen.getByText(/SNAP-42/)).toBeInTheDocument();
    expect(screen.getByText('Infrastructure torn down')).toBeInTheDocument();
  });

  it('disables Tear down until every required step is signed, and says why', async () => {
    // A control that is merely disabled teaches nothing. The reason renders
    // beside it — the same call the 422 makes by naming the missing steps.
    renderWithProviders(
      <DecommissionPanel decommission={WARNED} steps={STEPS} env={ownedEnv} currentUser={teamMember} />,
    );

    expect(screen.getByRole('button', { name: /tear down/i })).toBeDisabled();
    expect(screen.getByText(/final backup taken/i)).toBeInTheDocument();
    expect(screen.getByText(/sign .* before tearing down/i)).toBeInTheDocument();
  });

  it('enables Tear down once the last required step is signed', async () => {
    const allSigned = {
      ...WARNED,
      attestations: STEPS.map((s) => ({
        step_key: s.key, signed_by_username: 'ops.bob',
        signed_at: '2026-08-19T10:00:00Z', reference: 'x',
      })),
    };

    renderWithProviders(
      <DecommissionPanel decommission={allSigned} steps={STEPS} env={ownedEnv} currentUser={teamMember} />,
    );

    expect(screen.getByRole('button', { name: /tear down/i })).toBeEnabled();
  });

  it('re-renders when the decommission changes without unmounting', async () => {
    // A frontend test that only ever MOUNTS cannot see state that outlives an
    // unmount, nor a stale effect. Three bugs on this programme needed a second
    // render to surface — rerender with new props, do not remount.
    const { rerender } = renderWithProviders(
      <DecommissionPanel decommission={WARNED} steps={STEPS} env={ownedEnv} />,
    );
    expect(screen.getByText(/23 Aug 2026/)).toBeInTheDocument();

    rerender(
      <DecommissionPanel
        decommission={{ ...WARNED, scheduled_teardown_at: '2026-09-30T09:00:00Z' }}
        steps={STEPS}
        env={ownedEnv}
      />,
    );

    expect(screen.getByText(/30 Sep 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/23 Aug 2026/)).not.toBeInTheDocument();
  });

  it('surfaces the server error text when teardown is refused', async () => {
    // Mock the AxiosError SHAPE. A test rejecting with a plain Error carrying
    // the final text passes while the app shows "Request failed with status
    // code 422" — RTK's miniSerializeError drops response.data.detail.
    const err = new AxiosError('Request failed with status code 422');
    err.response = {
      data: { detail: 'Sign these first: final_backup, teardown' },
      status: 422, statusText: '', headers: {}, config: {} as never,
    };
    vi.mocked(api.post).mockRejectedValueOnce(err);

    renderWithProviders(
      <DecommissionPanel decommission={WARNED} steps={STEPS} env={ownedEnv} currentUser={teamMember} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /cancel decommission/i }));

    await waitFor(() => {
      expect(screen.getByText(/Sign these first: final_backup, teardown/)).toBeInTheDocument();
    });
  });
});

describe('B5 acts only where it says', () => {
  it('renders the remaining bookings and offers no control that changes one', async () => {
    const withBookings = {
      ...WARNED,
      remaining_bookings: [{ id: 11, purpose: 'Regression', end_date: '2026-09-10T17:00:00Z' }],
    };

    renderWithProviders(
      <DecommissionPanel decommission={withBookings} steps={STEPS} env={ownedEnv} currentUser={teamMember} />,
    );

    expect(screen.getByText('Regression')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /cancel booking/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /move booking/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** The panel carries the banner, the controls the
viewer may use, and the attestation checklist — **all three together**. A2's
lesson: repair controls live next to the state they repair, or a banner
diagnoses a situation and offers no way to act on it.

- [ ] **Step 4: Run the tests, then commit.**

```bash
git commit -am "feat(b5): the decommission panel on the environment detail"
```

---

## Task 13: The worklist page

**Files:**
- Create: `frontend/src/pages/decommissions/DecommissionWorklist.tsx`, `frontend/src/pages/decommissions/__tests__/DecommissionWorklist.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/constants/sortWhitelists.json`

- [ ] **Step 1: Write the failing tests** — server-paged from the first render
(never fetch-then-filter), `?state=` round-trips through the URL, the total
comes from `X-Total-Count`, and every sortable column is in the whitelist
JSON while `state` is not.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**, following `/contentions`. Add the nav entry.

- [ ] **Step 4: Run the tests, then commit.**

```bash
git commit -am "feat(b5): the decommission worklist page"
```

---

## Task 14: Admin surfaces

**Files:**
- Create: `frontend/src/components/admin/EnvironmentLifecyclePanel.tsx` + test
- Modify: the admin page that hosts the naming-policy panel; `frontend/src/components/admin/` tier editor

- [ ] **Step 1: Write the failing tests**

```tsx
it('PUTs the update model and never the read model', async () => {
  // The schema declares extra="forbid" and the read model carries id and
  // timestamps, so echoing GET's body back is a 422 on EVERY save. A mocked
  // service cannot notice — pin the exact key set.
  const body = vi.mocked(api.put).mock.calls.at(-1)![1];
  expect(Object.keys(body).sort()).toEqual([
    'decommission_notice_days', 'idle_detection_enabled', 'idle_threshold_days',
  ]);
});

it('shows a non-admin the settings read-only rather than hiding them', async () => {
  // Reads are open to any tenant member; only writes are Admin. B3a's UI was
  // over-gated on exactly the false analogy with /tenant/users and it took a
  // review to catch.
});

it('leaves the tier threshold blank rather than showing the tenant default', async () => {
  // NULL means "use the tenant default". Pre-filling it with 30 turns every
  // save into an explicit per-tier override nobody asked for.
});
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the tests, then commit.**

```bash
git commit -am "feat(b5): admin panel for the lifecycle policy, steps and tier thresholds"
```

---

## Task 15: The guard

**Files:**
- Create: `backend/tests/test_b5_acts_only_where_it_says.py`
- Create: a `describe('B5 acts only where it says')` block in `DecommissionPanel.test.tsx`

**This task is the promise of the sub-project.** A3, A4, B2 and B4 each shipped
a named test asserting an absence. B5 acts, so its guard asserts the *limit* of
the acting.

- [ ] **Step 1: Write the guard**

```python
"""B5 ACTS ONLY WHERE IT SAYS.

B5 changes exactly two things outside its own records:
  1. environment.status becomes DECOMMISSIONED at teardown;
  2. a booking whose window runs past scheduled_teardown_at is refused.

IF ANY TEST HERE FAILS, B5 HAS STARTED DOING SOMETHING ELSE.

Prove this file non-vacuous before trusting it: make tear_down cancel the
bookings it reports, watch test_teardown_cancels_no_booking fail, then revert.
"""

@pytest.mark.asyncio
async def test_initiating_changes_no_booking(db_session, tenant, env_with_team, bookings_on_env):
    """Not the count, not the status, not the dates, not deleted_at."""


@pytest.mark.asyncio
async def test_teardown_cancels_no_booking(db_session, tenant, live_decommission, bookings_on_env):
    """Every booking on the environment is byte-identical after teardown —
    including the ones the response named as remaining."""


@pytest.mark.asyncio
async def test_a_running_booking_still_runs_after_teardown(db_session, tenant, live_decommission, running_booking):
    """The environment is gone from the register; the booking is not."""


@pytest.mark.asyncio
async def test_teardown_transitions_no_booking(db_session, tenant, live_decommission, bookings_on_env):
    """No BookingStatusHistory row is written by any decommission action."""


@pytest.mark.asyncio
async def test_idle_detection_changes_nothing_at_all(db_session, tenant, populated_estate):
    """Enable it, list the estate, and assert every environment, booking and
    deployment row is unchanged. Idle is a derived READ."""


@pytest.mark.asyncio
async def test_no_write_path_consults_idle():
    """Structural, and labelled a smoke alarm rather than a proof, following
    B4's grep assertion: no module under app/services other than
    environment_idle_service and environment_service references idle_clause."""


@pytest.mark.asyncio
async def test_a_decommission_changes_no_other_environment(db_session, tenant, live_decommission, bystander_env):
    """Two environments, one decommissioned. The second is untouched — status,
    owner, expiry, name verdict."""


@pytest.mark.asyncio
async def test_cancelling_restores_nothing_and_breaks_nothing(db_session, tenant, live_decommission, populated_estate):
    """Cancel writes three fields on its own row and touches no other table."""


@pytest.mark.asyncio
async def test_nothing_raises_on_a_decommission_except_the_documented_refusals(db_session):
    """The documented set is: 403 on a permission gate, 404 across tenants, 409
    on a second live decommission / a second extension / a duplicate
    attestation / a non-live row / a booking past teardown, and 422 on a bad
    date, a blank reason, an unknown step key or missing required steps.

    A grep-based structural assertion over environment_decommission_service —
    a ±300-char window, no call-graph following. DELIBERATELY A SMOKE ALARM,
    NOT A PROOF, exactly as B4's equivalent is labelled.
    """
```

Fill each body out fully — capture every field of every booking row before the
action and compare the whole tuple after, rather than asserting on one column.
B4's guard is the model; read it first.

The fixtures this file needs, defined at its top:

- `bookings_on_env` — three bookings on the environment being decommissioned:
  one finished, one running now, one starting after the teardown date.
- `running_booking` — the middle one of those, returned alone for readability.
- `populated_estate` — two tenants' worth of environments, bookings and
  deployments, so "nothing changed" is a claim about a populated database and
  not about an empty one.
- `bystander_env` — a second environment in the same tenant, with its own
  owner, expiry and name verdict.

Each assertion captures **every column** of the rows it guards before the
action (`{r.id: {c.name: getattr(r, c.name) for c in r.__table__.columns}}`)
and compares the whole mapping afterwards. Asserting on one column is how a
guard passes while the thing it guards has changed.

- [ ] **Step 2: Prove the guard is non-vacuous**

Make `tear_down` cancel the bookings it reports. Run the file. **At least
`test_teardown_cancels_no_booking` and `test_a_running_booking_still_runs_after_teardown`
must fail.** Revert, run again, all pass. Record the result in the commit
message — a guard nobody has seen fail is a guard nobody has tested.

- [ ] **Step 3: Write the UI half**

`describe('B5 acts only where it says')` — the panel renders remaining bookings
and offers no control that mutates one.

- [ ] **Step 4: Commit**

```bash
git commit -am "test(b5): the guard — B5 acts only where it says, and no further"
```

---

## Task 16: Documentation

**Files:**
- Modify: `CLAUDE.md`, `docs/phases/phase-7.md`, `docs/admin-guide.md`, `docs/user-guide.md`, `docs/pagination.md`

- [ ] **Step 1: `docs/phases/phase-7.md`** — tick B5, add a "What B5 established" section covering: the acting limit and its guard; state computed not stored; the date-based refusal and the three create paths; the attestation model; the team/owner split and its degradation; idle's exclusion of health samples; the four §2.12 deviations.

- [ ] **Step 2: `CLAUDE.md`** — a B5 block in the same voice as B4's, plus two new **Common Pitfalls** entries:
  - *Writing dialect date arithmetic for a per-row threshold* — the `CASE`-of-literals pattern and why.
  - *Reasoning about what a column comparison emits instead of compiling it* — this branch spent two rounds arguing that `Environment.status != "decommissioned"` was inert because the column holds `ACTIVE`. It is not: SQLAlchemy's `Enum` coerces the literal to the stored name. One `compile(compile_kwargs={"literal_binds": True})` settles such questions instantly. **Do NOT document a status-literal bug — there isn't one.**

- [ ] **Step 3: `docs/admin-guide.md`** — the lifecycle policy, the step vocabulary, the tier override, and **that idle detection is off by default and why**.

- [ ] **Step 4: `docs/user-guide.md`** — what a warning means, how to ask for an extension, that one extension is allowed, and that bookings past the teardown date are refused while shorter ones are not.

- [ ] **Step 5: `docs/pagination.md`** — add `idle` and `decommission_state` to the permanently-unsortable set with their reasons; record `/decommissions` as bounded.

- [ ] **Step 6: Commit**

```bash
git commit -am "docs(b5): decommissioning and idle detection in the guides, phase-7 and the pitfalls"
```

---

## Task 17: Whole-branch verification

- [ ] **Step 1: Both full suites, from a clean tree.** Background, per the Global Constraints. Expected: zero failures on both legs.

- [ ] **Step 2: Lint and build.**

```bash
cd frontend && npm run lint && npm run build
cd backend && uv run ruff check .
```

- [ ] **Step 3: A mutation pass over the rules this plan explains at length.**
Six of seven mutation survivors on A4 were exactly the rules its comments
explained best. At minimum, break each of these and confirm a **named** test
fails:

| Mutation | Test that must fail |
|---|---|
| Drop the tier `COALESCE`, use the tenant default for all | `test_the_tier_override_wins_over_the_tenant_default` |
| Compare against `now` instead of `expiry_boundary(now)` | `test_the_teardown_day_itself_is_still_warned` |
| Remove the `created_at <= cutoff` age guard | `test_an_environment_younger_than_its_threshold_is_never_idle` |
| Let the initiator set an earlier teardown date | `test_the_initiator_may_not_shorten_the_notice` |
| Drop the refusal from `add_environment` only | `test_add_environment_refuses_a_booking_past_teardown` |
| Clear the extension block on grant | `test_granting_moves_the_date_and_keeps_the_record` |
| Remove the attestation gate on teardown | `test_teardown_is_refused_until_every_required_step_is_signed` |
| Remove a `tenant_id` filter from any new query | a named isolation test |

**Any mutation that leaves the suite green is a missing test, not a passing
mutation.** Write it before continuing.

- [ ] **Step 4: A browser pass.** Six defects on the pagination programme and
three on B2 were found only here, every one with a fully green suite. Walk:
enable idle detection in the admin panel and watch the estate's chips change;
set a tier override and watch one tier's chips change back; initiate a
decommission; try to book past the teardown date and read the error; request an
extension as the owner; grant it; make the same booking again and watch it
succeed; sign one step and read the disabled Tear down control's reason; sign
the second and tear down; confirm the environment reads decommissioned and its
existing bookings are untouched; cancel a different decommission and confirm
the environment is unaffected.

**jsdom cannot render DataGrid chips reliably** — A3 found this the hard way, so
the list-page half of this walk is load-bearing rather than a formality.

- [ ] **Step 5: Commit and hand back**

```bash
git commit -am "test(b5): whole-branch verification — dual engine, mutation pass, browser pass"
```

Then stop. **Do not merge.** Report: both suite results, the mutation table
with its outcomes, what the browser pass found, and anything deferred.
