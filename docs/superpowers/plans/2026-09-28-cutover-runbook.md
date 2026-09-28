# Phase 9 C5a — Cutover Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-(release, environment) cutover runbook — tasks owned by teams, joined by dependencies, executed under one ordering rule, with a schedule computed on read — plus a Runbook tab on release detail and a "ready for my team" `/me/work` queue.

**Architecture:** Four new tables (migration `runbooks`). Three backend services with one job each: `runbook_schedule_service` (pure function, no DB — the only place scheduling rules live), `runbook_service` (plan/task/dependency writes and their validation), `runbook_execution_service` (status transitions, permissions, history, the ready predicate). A composite read (`runbook_view_service`) folds all three into one response carrying per-task `allowed_transitions`, so the UI never re-derives a rule. Frontend: service + slice + a `runbook/` component folder mounted as the fourteenth release tab.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic (hand-written DDL), pytest on SQLite + PostgreSQL; React 18, TypeScript, MUI + MUI X DataGrid (via `DataTable`), Redux Toolkit, Vitest + Testing Library.

**Spec:** [docs/superpowers/specs/2026-09-28-cutover-runbook-design.md](../specs/2026-09-28-cutover-runbook-design.md) — read it before starting any task; this plan argues from it.

## Global Constraints

- Every tenant-scoped query filters `tenant_id` on the entity it selects, using `current_user.active_tenant_id` (never `.tenant_id`).
- Services never call `db.commit()`; use `db.flush()` when an id is needed. `get_db` commits.
- Soft delete (`deleted_at`) for plans and tasks; **hard delete** for `runbook_task_dependency` rows (junction).
- No native enums: status/kind/pattern are `String` columns validated in Pydantic `Literal`s.
- Every request schema declares `model_config = ConfigDict(extra="forbid")`.
- "Manager" means `user.is_master_admin or user.role in ("Admin", "Release Manager")`.
- Usernames on history are resolved **without** a tenant filter (`gate_waiver_service.usernames_for`).
- Names render through read-rendering lookups that do not filter `deleted_at` (`user_group_service.get_group_names`, `environment_service.get_environment_names`, a local system-name lookup).
- Satisfied statuses are exactly `{"done", "skipped"}`.
- Schedule times are UTC, truncated to the minute. `expiry_boundary` is **not** used anywhere in C5a.
- C5a refuses only writes to runbook records. No other module may import a `runbook_*` service except `my_work_service` and the runbook router (Task 6 pins this).
- Frontend thunks `rejectWithValue(formatApiError(err, '…'))`; components read `result.payload`, never `result.error.message`.
- Tests mocking an API failure use an `AxiosError` shape with `response.data.detail`.
- Backend test commands run from `backend/`; frontend from `frontend/`. Run the PostgreSQL leg alone, never two at once.
- Implementers run only their own test files; the controller runs the three full suites (SQLite, PostgreSQL, frontend).

## Review Focus

1. **Naive datetimes from SQLite.** SQLite returns naive datetimes; comparing them with an aware `now` is a `TypeError` that only one engine sees. `compute()` normalises every instant through `_utc()`; Task 2 has a test feeding naive inputs.
2. **A soft-deleted predecessor** (plan deletion leaves edges pointing at deleted tasks) must count as absent in *both* the composite's `allowed_transitions` and the SQL `ready_clause`, or the queue and the tab disagree. Task 7's agreement test includes one.
3. **`at` in the future or omitted.** Omitted means "now"; future is 422. A back-dated `at` before a predecessor's finish is accepted (spec §4). Task 5 pins all three.
4. **Re-rendering the tab for a different release** must not show the previous release's plan (Redux state outliving an unmount — the A3 lesson). Task 9 re-renders with a new `releaseId`.
5. **A PATCH echoing the read model** (the B2 lesson): the task dialog must send only update-schema keys. Task 10 pins the exact key set sent.

---

## File Structure

**Backend — create**
- `backend/app/db/models/runbook.py` — the four models.
- `backend/app/db/migrations/versions/20260928_1000_runbooks_cutover_runbook.py` — migration `runbooks`.
- `backend/app/services/runbook_schedule_service.py` — pure scheduling.
- `backend/app/services/runbook_service.py` — plan/task/dependency writes + validation.
- `backend/app/services/runbook_execution_service.py` — transitions, permissions, history, ready predicate + queue.
- `backend/app/services/runbook_view_service.py` — composite read.
- `backend/app/api/v1/schemas/runbook.py` — request/response schemas.
- `backend/app/api/v1/runbooks.py` — router.
- `backend/tests/runbook_helpers.py` — shared test builders.
- `backend/tests/test_runbook_models.py`, `test_runbook_schedule.py`, `test_runbook_service.py`, `test_runbook_execution.py`, `test_runbook_api.py`, `test_runbook_my_work.py`, `test_c5a_refuses_only_within_runbook.py`.

**Backend — modify**
- `backend/app/db/models/__init__.py` — import the models.
- `backend/app/main.py` — mount the router.
- `backend/app/services/my_work_service.py`, `backend/app/api/v1/schemas/my_work.py` — seventh queue.
- `backend/tests/test_my_work_service.py` — queue key set.
- `backend/tests/test_pir_backfill_migration.py` — repin head literal to `runbooks`.

**Frontend — create**
- `frontend/src/types/runbook.ts`, `frontend/src/services/runbookService.ts`, `frontend/src/store/runbookSlice.ts`
- `frontend/src/components/releases/runbook/RunbookTab.tsx`, `RunbookTaskTable.tsx`, `RunbookTimeline.tsx`, `RunbookPlanDialog.tsx`, `RunbookTaskDialog.tsx`, `RunbookTransitionDialog.tsx`, `labels.ts`
- Tests under `frontend/src/components/releases/runbook/__tests__/` and `frontend/src/store/__tests__/runbookSlice.test.ts`

**Frontend — modify**
- `frontend/src/store/index.ts`, `frontend/src/pages/releases/ReleaseDetail.tsx`, `frontend/src/types/myWork.ts`, `frontend/src/pages/MyWork.tsx`, `frontend/src/pages/__tests__/myWork.test.tsx` (and any fixture of `MyWorkResponse`).

**Docs — modify** (Task 13): `docs/admin-guide.md`, `docs/user-guide.md`, `docs/phases/phase-9.md`, `docs/plan.md`, `docs/gap-analysis.md`, `CLAUDE.md`.

---

### Task 1: Models, migration, test helpers

**Files:**
- Create: `backend/app/db/models/runbook.py`
- Create: `backend/app/db/migrations/versions/20260928_1000_runbooks_cutover_runbook.py`
- Create: `backend/tests/runbook_helpers.py`
- Modify: `backend/app/db/models/__init__.py` (after the `go_no_go` import, ~line 98)
- Modify: `backend/tests/test_pir_backfill_migration.py:159-170` (head literal)
- Test: `backend/tests/test_runbook_models.py`

**Interfaces:**
- Produces: `RunbookPlan`, `RunbookTask`, `RunbookTaskDependency`, `RunbookTaskEvent` (in `app.db.models.runbook`); constants `TASK_STATUSES`, `TASK_KINDS`, `DEPLOY_PATTERNS`, `SATISFIED_STATUSES`.
- Produces (tests): `runbook_helpers.make_release(db, tenant_id, user_id, name="R") -> Release`, `make_system(db, tenant_id, name) -> System`, `attach_system(db, release, system, role="changing") -> ReleaseSystem`, `make_plan(db, release, environment, *, anchor, name="Cutover") -> RunbookPlan`, `make_task(db, plan, name, *, duration=30, team=None, system=None, fixed_start=None, status="not_started", kind="task") -> RunbookTask`, `link(db, task, *preds)`, `login_headers(client, db, tenant, username, role) -> (User, dict)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_runbook_models.py`:

```python
"""The four runbook tables exist, round-trip, and carry the defaults the
services rely on. Schema parity with the migration is test_migration_schema_drift's
job; this file checks the models themselves."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models.runbook import (
    RunbookPlan, RunbookTask, RunbookTaskDependency, RunbookTaskEvent,
    SATISFIED_STATUSES, TASK_STATUSES,
)
from tests.runbook_helpers import link, make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_plan_with_tasks_and_an_edge_round_trips(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    a = await make_task(db_session, plan, "Deploy API")
    b = await make_task(db_session, plan, "Smoke test")
    await link(db_session, b, a)
    db_session.add(RunbookTaskEvent(tenant_id=test_tenant.id, task_id=a.id, from_status="not_started",
                                    to_status="in_progress", at=ANCHOR, recorded_at=ANCHOR,
                                    by_user_id=test_user.id))
    await db_session.commit()

    assert (await db_session.get(RunbookTask, a.id)).status == "not_started"
    edges = (await db_session.execute(select(RunbookTaskDependency))).scalars().all()
    assert [(e.task_id, e.predecessor_task_id) for e in edges] == [(b.id, a.id)]
    assert (await db_session.get(RunbookPlan, plan.id)).anchor_start_at is not None


def test_the_satisfied_set_is_exactly_done_and_skipped():
    assert SATISFIED_STATUSES == frozenset({"done", "skipped"})
    assert set(TASK_STATUSES) == {"not_started", "in_progress", "done", "failed", "skipped"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runbook_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.runbook'`

- [ ] **Step 3: Write the models**

`backend/app/db/models/runbook.py`:

```python
"""Phase 9 C5a — cutover runbook.

A plan per (release, environment); tasks carried out by one team each, joined
by dependencies; an append-only history of every status change.

STATUS IS STORED, unlike the computed states elsewhere in this codebase: it is
a fact a person reports ("I started it"), not a function of other rows. What
is derived from it — schedule, lateness, criticality, the plan's state — is
computed on read by runbook_schedule_service and never stored.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TASK_STATUSES = ("not_started", "in_progress", "done", "failed", "skipped")
TASK_KINDS = ("task", "check", "deploy", "verification", "ramp")
DEPLOY_PATTERNS = ("rolling", "blue_green", "canary", "big_bang", "other")
# The ONE definition of "a successor may proceed past this task".
SATISFIED_STATUSES = frozenset({"done", "skipped"})


class RunbookPlan(Base):
    """At most one LIVE plan per (release, environment) — enforced in
    runbook_service, not by a partial unique index (inert on SQLite)."""

    __tablename__ = "runbook_plan"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("release.id"), nullable=False, index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environment.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    anchor_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deploy_pattern: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RunbookTask(Base):
    __tablename__ = "runbook_task"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("runbook_plan.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True)
    # A system id, NOT a release_system id: release_system rows are
    # hard-deleted, which is how C4 came to have orphaned plans.
    system_id: Mapped[Optional[int]] = mapped_column(ForeignKey("system.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="task")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fixed_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started")
    actual_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RunbookTaskDependency(Base):
    """`task_id` cannot start until `predecessor_task_id` is done or skipped.
    Hard-deleted, like every junction row in this codebase."""

    __tablename__ = "runbook_task_dependency"
    __table_args__ = (
        UniqueConstraint("task_id", "predecessor_task_id", name="uq_runbook_task_dependency"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("runbook_task.id"), nullable=False, index=True)
    predecessor_task_id: Mapped[int] = mapped_column(
        ForeignKey("runbook_task.id"), nullable=False, index=True)


class RunbookTaskEvent(Base):
    """Append-only. `at` is when the change is SAID to have happened (a task is
    often ticked after it finished); `recorded_at` is server time."""

    __tablename__ = "runbook_task_event"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("runbook_task.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    # Unused until C5b (pipeline updates); present now so C5b needs no migration.
    by_api_key_id: Mapped[Optional[int]] = mapped_column(ForeignKey("api_key.id"), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

Before writing `by_api_key_id`, confirm the API key table name: `grep -n "__tablename__" app/db/models/api_key.py` — use whatever it prints in the `ForeignKey`.

In `backend/app/db/models/__init__.py`, after the `go_no_go` import block, add:

```python
from app.db.models.runbook import (  # noqa: F401
    RunbookPlan, RunbookTask, RunbookTaskDependency, RunbookTaskEvent,
)
```

- [ ] **Step 4: Write the test helpers**

`backend/tests/runbook_helpers.py`:

```python
"""Builders for runbook tests. Every row points at rows these helpers or the
shared fixtures actually created — never a fabricated id (FKs are enforced)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.runbook import RunbookPlan, RunbookTask, RunbookTaskDependency
from app.db.models.system import System
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.services.release_defaults import seed_release_defaults_for_tenant


async def make_release(db, tenant_id: int, user_id: int, name: str = "R") -> Release:
    tpl = (await db.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == tenant_id, LifecycleTemplate.name == "Major"))).scalar_one_or_none()
    if tpl is None:
        await seed_release_defaults_for_tenant(db, tenant_id)
        tpl = (await db.execute(select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant_id, LifecycleTemplate.name == "Major"))).scalar_one()
    rel = Release(tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=user_id)
    db.add(rel)
    await db.flush()
    return rel


async def make_system(db, tenant_id: int, name: str) -> System:
    system = System(tenant_id=tenant_id, name=name)
    db.add(system)
    await db.flush()
    return system


async def attach_system(db, release: Release, system: System, role: str = "changing") -> ReleaseSystem:
    rs = ReleaseSystem(tenant_id=release.tenant_id, release_id=release.id, system_id=system.id, role=role)
    db.add(rs)
    await db.flush()
    return rs


async def make_plan(db, release: Release, environment: Environment, *, anchor: datetime,
                    name: str = "Cutover") -> RunbookPlan:
    plan = RunbookPlan(tenant_id=release.tenant_id, release_id=release.id,
                       environment_id=environment.id, name=name, anchor_start_at=anchor)
    db.add(plan)
    await db.flush()
    return plan


async def make_task(db, plan: RunbookPlan, name: str, *, duration: int = 30,
                    team: Optional[UserGroup] = None, system: Optional[System] = None,
                    fixed_start: Optional[datetime] = None, status: str = "not_started",
                    kind: str = "task") -> RunbookTask:
    task = RunbookTask(tenant_id=plan.tenant_id, plan_id=plan.id, name=name, kind=kind,
                       duration_minutes=duration, team_group_id=team.id if team else None,
                       system_id=system.id if system else None, fixed_start_at=fixed_start,
                       status=status)
    db.add(task)
    await db.flush()
    return task


async def link(db, task: RunbookTask, *preds: RunbookTask) -> None:
    for p in preds:
        db.add(RunbookTaskDependency(tenant_id=task.tenant_id, task_id=task.id, predecessor_task_id=p.id))
    await db.flush()


async def login_headers(client, db, tenant, username: str, role: str) -> tuple[User, dict]:
    user = User(tenant_id=tenant.id, username=username, email=f"{username}@test.com",
                password_hash=get_password_hash("password123"), role=role, is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    resp = await client.post("/api/v1/auth/login", json={
        "username": username, "password": "password123", "tenant_slug": tenant.slug})
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}
```

- [ ] **Step 5: Run the model test to verify it passes**

Run: `uv run pytest tests/test_runbook_models.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Write the migration**

`backend/app/db/migrations/versions/20260928_1000_runbooks_cutover_runbook.py`:

```python
"""runbooks — Phase 9 C5a cutover runbook

Revision ID: runbooks
Revises: closeout
Create Date: 2026-09-28 10:00:00

Additive: four tables, no change to any existing table, no backfill, no seed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "runbooks"
down_revision: Union[str, None] = "closeout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "runbook_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("anchor_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deploy_pattern", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    for col in ("id", "tenant_id", "release_id", "environment_id"):
        op.create_index(f"ix_runbook_plan_{col}", "runbook_plan", [col])

    op.create_table(
        "runbook_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("runbook_plan.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("team_group_id", sa.Integer(), sa.ForeignKey("user_group.id"), nullable=True),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="task"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fixed_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("actual_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    for col in ("id", "tenant_id", "plan_id", "team_group_id", "system_id"):
        op.create_index(f"ix_runbook_task_{col}", "runbook_task", [col])

    op.create_table(
        "runbook_task_dependency",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("runbook_task.id"), nullable=False),
        sa.Column("predecessor_task_id", sa.Integer(), sa.ForeignKey("runbook_task.id"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("task_id", "predecessor_task_id", name="uq_runbook_task_dependency"),
    )
    for col in ("id", "tenant_id", "task_id", "predecessor_task_id"):
        op.create_index(f"ix_runbook_task_dependency_{col}", "runbook_task_dependency", [col])

    op.create_table(
        "runbook_task_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("runbook_task.id"), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("by_api_key_id", sa.Integer(), sa.ForeignKey("api_key.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
    )
    for col in ("id", "tenant_id", "task_id"):
        op.create_index(f"ix_runbook_task_event_{col}", "runbook_task_event", [col])


def downgrade() -> None:
    op.drop_table("runbook_task_event")
    op.drop_table("runbook_task_dependency")
    op.drop_table("runbook_task")
    op.drop_table("runbook_plan")
```

(Use the same `api_key` table name you confirmed in Step 3.)

In `backend/tests/test_pir_backfill_migration.py`, change the docstring's `(`closeout`, as of Phase 9 sub-project C6 …` to `(`runbooks`, as of Phase 9 sub-project C5a …` and the asserted literal `"closeout"` to `"runbooks"`.

- [ ] **Step 7: Run migration tests**

Run: `uv run pytest tests/test_migration_schema_drift.py tests/test_pir_backfill_migration.py tests/test_runbook_models.py -q`
Expected: PASS (the drift and migration tests skip only if no PostgreSQL server is running — if they skip, start it with `docker-compose up -d` and rerun; a skip proves nothing).

- [ ] **Step 8: Apply to the dev database**

Run: `alembic current` (expect `closeout`), then `alembic upgrade head`, then `alembic current` (expect `runbooks`). Never `alembic downgrade -1` on dev.

- [ ] **Step 9: Commit**

```bash
git add backend/app/db/models/runbook.py backend/app/db/models/__init__.py \
  backend/app/db/migrations/versions/20260928_1000_runbooks_cutover_runbook.py \
  backend/tests/runbook_helpers.py backend/tests/test_runbook_models.py \
  backend/tests/test_pir_backfill_migration.py
git commit -m "feat(c5a): runbook tables and migration"
```

---

### Task 2: The schedule — a pure function

**Files:**
- Create: `backend/app/services/runbook_schedule_service.py`
- Test: `backend/tests/test_runbook_schedule.py`

**Interfaces:**
- Produces:
  - `class CycleError(ValueError)` with attribute `task_ids: set[int]` (tasks left unsorted).
  - `topological_order(task_ids: Iterable[int], edges: Iterable[tuple[int, int]]) -> list[int]` — edges are `(task_id, predecessor_id)`; raises `CycleError`.
  - `@dataclass(frozen=True) TaskInput(id: int, duration_minutes: int, fixed_start_at: datetime|None, status: str, actual_started_at: datetime|None, actual_finished_at: datetime|None)`
  - `@dataclass(frozen=True) TaskSchedule(planned_start, planned_finish, forecast_start, forecast_finish: datetime, late_start, overrunning, slipped_past_fixed_start, blocked, critical: bool)`
  - `@dataclass(frozen=True) PlanSchedule(tasks: dict[int, TaskSchedule], planned_end: datetime, forecast_end: datetime, slip_minutes: int, state: str)`
  - `compute(anchor: datetime, tasks: list[TaskInput], edges: list[tuple[int, int]], now: datetime) -> PlanSchedule`
  - `plan_state(statuses: Iterable[str]) -> str`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_runbook_schedule.py`:

```python
"""runbook_schedule_service.compute against hand-worked plans. Pure: no DB."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.runbook_schedule_service import (
    CycleError, TaskInput, compute, plan_state, topological_order,
)

A = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)   # anchor, 18:00 day 1
BEFORE = A - timedelta(days=1)                           # a "now" before anything


def t(id, dur=30, status="not_started", fixed=None, start=None, finish=None):
    return TaskInput(id=id, duration_minutes=dur, fixed_start_at=fixed, status=status,
                     actual_started_at=start, actual_finished_at=finish)


def m(n):
    return A + timedelta(minutes=n)


def test_a_chain_runs_back_to_back_from_the_anchor():
    s = compute(A, [t(1, 30), t(2, 20)], [(2, 1)], BEFORE)
    assert (s.tasks[1].planned_start, s.tasks[1].planned_finish) == (m(0), m(30))
    assert (s.tasks[2].planned_start, s.tasks[2].planned_finish) == (m(30), m(50))
    assert s.planned_end == m(50) and s.forecast_end == m(50)
    assert s.slip_minutes == 0 and s.state == "not_started"


def test_a_join_waits_for_the_latest_predecessor():
    # tests (3) cannot run until both deploys (1: 30m, 2: 90m) are done
    s = compute(A, [t(1, 30), t(2, 90), t(3, 15)], [(3, 1), (3, 2)], BEFORE)
    assert s.tasks[3].planned_start == m(90)


def test_a_fixed_start_later_than_the_predecessors_wins():
    next_evening = A + timedelta(days=1)
    s = compute(A, [t(1, 60), t(2, 10, fixed=next_evening)], [(2, 1)], BEFORE)
    assert s.tasks[2].planned_start == next_evening
    assert s.tasks[2].slipped_past_fixed_start is False


def test_the_second_evening_slips_when_a_pre_task_overruns():
    # pre-task planned 60m, started on time, still running 25h later
    next_evening = A + timedelta(days=1)
    now = A + timedelta(hours=25)
    s = compute(A, [t(1, 60, status="in_progress", start=A), t(2, 10, fixed=next_evening)], [(2, 1)], now)
    assert s.tasks[2].planned_start == next_evening
    assert s.tasks[2].forecast_start == now
    assert s.tasks[2].slipped_past_fixed_start is True
    assert s.tasks[2].late_start is True
    assert s.tasks[1].overrunning is True


def test_a_skipped_task_passes_time_through():
    s = compute(A, [t(1, 30, status="done", start=m(0), finish=m(30)), t(2, 60, status="skipped"), t(3, 10)],
                [(2, 1), (3, 2)], m(31))
    assert s.tasks[2].forecast_start == m(30) and s.tasks[2].forecast_finish == m(30)
    assert s.tasks[3].forecast_start == m(31)   # floored at now, not m(30)


def test_a_failed_task_blocks_everything_after_it_and_a_retry_clears_it():
    failed = compute(A, [t(1, 30, status="failed", start=m(0), finish=m(10)), t(2), t(3)],
                     [(2, 1), (3, 2)], m(20))
    assert failed.tasks[2].blocked and failed.tasks[3].blocked
    assert failed.state == "failed"
    retried = compute(A, [t(1, 30, status="in_progress", start=m(15)), t(2), t(3)],
                      [(2, 1), (3, 2)], m(20))
    assert not retried.tasks[2].blocked and retried.state == "in_progress"


def test_an_overdue_task_is_forecast_to_start_now_never_in_the_past():
    now = m(45)
    s = compute(A, [t(1, 30)], [], now)
    assert s.tasks[1].planned_start == m(0)
    assert s.tasks[1].forecast_start == now
    assert s.tasks[1].late_start is True
    assert s.slip_minutes == 45


def test_the_critical_path_is_the_longer_branch():
    # 1 → 3 (30m) and 2 → 3 (90m): only 2 and 3 are critical
    s = compute(A, [t(1, 30), t(2, 90), t(3, 15)], [(3, 1), (3, 2)], BEFORE)
    assert (s.tasks[1].critical, s.tasks[2].critical, s.tasks[3].critical) == (False, True, True)


def test_done_and_skipped_tasks_are_never_critical():
    s = compute(A, [t(1, 30, status="done", start=m(0), finish=m(30)), t(2, 30)], [(2, 1)], m(30))
    assert s.tasks[1].critical is False and s.tasks[2].critical is True


def test_a_zero_duration_milestone_takes_no_time():
    s = compute(A, [t(1, 30), t(2, 0), t(3, 10)], [(2, 1), (3, 2)], BEFORE)
    assert s.tasks[2].planned_start == s.tasks[2].planned_finish == m(30)
    assert s.tasks[3].planned_start == m(30)


def test_a_plan_with_no_tasks_ends_at_its_anchor():
    s = compute(A, [], [], BEFORE)
    assert s.planned_end == A and s.forecast_end == A and s.state == "not_started"


def test_seconds_are_truncated_and_naive_datetimes_are_read_as_utc():
    naive_anchor = datetime(2026, 10, 1, 18, 0, 42)            # what SQLite hands back
    naive_start = datetime(2026, 10, 1, 18, 5, 59)
    s = compute(naive_anchor, [t(1, 30, status="in_progress", start=naive_start)], [], m(6))
    assert s.tasks[1].planned_start == A
    assert s.tasks[1].forecast_start == m(5)


def test_a_cycle_raises_rather_than_looping():
    with pytest.raises(CycleError) as exc:
        topological_order([1, 2, 3], [(1, 2), (2, 1), (3, 1)])
    assert exc.value.task_ids == {1, 2, 3}
    with pytest.raises(CycleError):
        compute(A, [t(1), t(2)], [(1, 2), (2, 1)], BEFORE)


@pytest.mark.parametrize("statuses, state", [
    ([], "not_started"),
    (["not_started", "not_started"], "not_started"),
    (["done", "not_started"], "in_progress"),
    (["done", "skipped"], "complete"),
    (["done", "failed", "in_progress"], "failed"),
])
def test_plan_state_first_match_wins(statuses, state):
    assert plan_state(statuses) == state
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runbook_schedule.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.runbook_schedule_service'`

- [ ] **Step 3: Implement**

`backend/app/services/runbook_schedule_service.py`:

```python
"""The runbook schedule, computed on read. PURE — no database access.

This is the ONLY place scheduling rules live. The composite read, the
timeline, and (C5b) the readiness finding all read its output; nothing may
re-derive a start time, a lateness flag or criticality elsewhere.

Minute precision, UTC. Deliberately NOT expiry_boundary's day rule: a cutover
is measured in minutes. See spec §5.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from app.db.models.runbook import SATISFIED_STATUSES


class CycleError(ValueError):
    def __init__(self, task_ids: set[int]):
        super().__init__(f"dependency cycle among tasks {sorted(task_ids)}")
        self.task_ids = task_ids


@dataclass(frozen=True)
class TaskInput:
    id: int
    duration_minutes: int
    fixed_start_at: Optional[datetime]
    status: str
    actual_started_at: Optional[datetime]
    actual_finished_at: Optional[datetime]


@dataclass(frozen=True)
class TaskSchedule:
    planned_start: datetime
    planned_finish: datetime
    forecast_start: datetime
    forecast_finish: datetime
    late_start: bool
    overrunning: bool
    slipped_past_fixed_start: bool
    blocked: bool
    critical: bool


@dataclass(frozen=True)
class PlanSchedule:
    tasks: dict[int, TaskSchedule]
    planned_end: datetime
    forecast_end: datetime
    slip_minutes: int
    state: str


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes, PostgreSQL aware ones; comparing the two
    is a TypeError on one engine only. Read naive as UTC, truncate to the minute."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


def topological_order(task_ids: Iterable[int], edges: Iterable[tuple[int, int]]) -> list[int]:
    """Kahn's algorithm, ties broken by id so the order is deterministic.
    `edges` are (task_id, predecessor_id)."""
    ids = sorted(set(task_ids))
    indegree = {i: 0 for i in ids}
    successors: dict[int, list[int]] = defaultdict(list)
    for task_id, pred_id in edges:
        if task_id in indegree and pred_id in indegree:
            indegree[task_id] += 1
            successors[pred_id].append(task_id)
    ready = deque(i for i in ids if indegree[i] == 0)
    order: list[int] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for nxt in sorted(successors[current]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(ids):
        raise CycleError(set(ids) - set(order))
    return order


def plan_state(statuses: Iterable[str]) -> str:
    """First match wins: complete, failed, in_progress, not_started. A plan
    with no tasks is not_started (never 'complete')."""
    s = list(statuses)
    if s and all(x in SATISFIED_STATUSES for x in s):
        return "complete"
    if any(x == "failed" for x in s):
        return "failed"
    if any(x != "not_started" for x in s):
        return "in_progress"
    return "not_started"


def compute(anchor: datetime, tasks: list[TaskInput], edges: list[tuple[int, int]],
            now: datetime) -> PlanSchedule:
    anchor = _utc(anchor)
    now = _utc(now)
    by_id = {t.id: t for t in tasks}
    edges = [(a, b) for a, b in edges if a in by_id and b in by_id]
    preds: dict[int, list[int]] = defaultdict(list)
    succs: dict[int, list[int]] = defaultdict(list)
    for task_id, pred_id in edges:
        preds[task_id].append(pred_id)
        succs[pred_id].append(task_id)
    order = topological_order(by_id, edges)

    def dur(t: TaskInput) -> timedelta:
        return timedelta(minutes=t.duration_minutes)

    # Planned pass — the baseline; ignores status.
    p_start: dict[int, datetime] = {}
    p_finish: dict[int, datetime] = {}
    for i in order:
        t = by_id[i]
        start = max((p_finish[p] for p in preds[i]), default=anchor)
        fixed = _utc(t.fixed_start_at)
        if fixed is not None:
            start = max(start, fixed)
        p_start[i], p_finish[i] = start, start + dur(t)

    # Forecast pass — the plan as it now stands.
    f_start: dict[int, datetime] = {}
    f_finish: dict[int, datetime] = {}
    pred_driven: dict[int, datetime] = {}
    blocked: dict[int, bool] = {}
    for i in order:
        t = by_id[i]
        driven = max((f_finish[p] for p in preds[i]), default=anchor)
        pred_driven[i] = driven
        blocked[i] = any(by_id[p].status == "failed" or blocked[p] for p in preds[i])
        started, finished = _utc(t.actual_started_at), _utc(t.actual_finished_at)
        if t.status == "done":
            f_start[i] = started or finished or driven
            f_finish[i] = finished or f_start[i]
        elif t.status in ("in_progress", "failed"):
            f_start[i] = started or now
            f_finish[i] = max(f_start[i] + dur(t), now)
        elif t.status == "skipped":
            f_start[i] = f_finish[i] = driven
        else:  # not_started
            start = driven
            fixed = _utc(t.fixed_start_at)
            if fixed is not None:
                start = max(start, fixed)
            f_start[i] = max(start, now)
            f_finish[i] = f_start[i] + dur(t)

    planned_end = max(p_finish.values(), default=anchor)
    forecast_end = max(f_finish.values(), default=anchor)

    # Backward pass over the forecast for total float. A task's latest finish
    # is the earliest latest-start of its successors (or the plan's end).
    latest_finish: dict[int, datetime] = {}
    for i in reversed(order):
        latest_finish[i] = min(
            (latest_finish[s] - (f_finish[s] - f_start[s]) for s in succs[i]),
            default=forecast_end,
        )

    result: dict[int, TaskSchedule] = {}
    for i in order:
        t = by_id[i]
        fixed = _utc(t.fixed_start_at)
        started = _utc(t.actual_started_at)
        result[i] = TaskSchedule(
            planned_start=p_start[i], planned_finish=p_finish[i],
            forecast_start=f_start[i], forecast_finish=f_finish[i],
            late_start=f_start[i] > p_start[i],
            overrunning=t.status == "in_progress" and started is not None and now > started + dur(t),
            slipped_past_fixed_start=fixed is not None and pred_driven[i] > fixed,
            blocked=blocked[i],
            critical=t.status not in SATISFIED_STATUSES and latest_finish[i] == f_finish[i],
        )

    slip = int((forecast_end - planned_end).total_seconds() // 60)
    return PlanSchedule(tasks=result, planned_end=planned_end, forecast_end=forecast_end,
                        slip_minutes=max(slip, 0), state=plan_state(t.status for t in tasks))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_runbook_schedule.py -q`
Expected: PASS (all). If `test_the_second_evening_slips…` fails on `slipped_past_fixed_start`, check the pred-driven forecast of task 1: in progress since A with 60 min duration and `now = A+25h`, `f_finish[1] = now`, so `pred_driven[2] = now > next_evening`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/runbook_schedule_service.py backend/tests/test_runbook_schedule.py
git commit -m "feat(c5a): runbook schedule — planned, forecast, flags, critical path"
```

---

### Task 3: Plan writes

**Files:**
- Create: `backend/app/services/runbook_service.py` (plan half)
- Create: `backend/app/api/v1/schemas/runbook.py` (plan request schemas)
- Test: `backend/tests/test_runbook_service.py` (plan tests)

**Interfaces:**
- Consumes: models from Task 1; `release_service.get_release(db, release_id, tenant_id) -> Release` (404s on missing/deleted/other tenant).
- Produces (schemas): `RunbookPlanCreate(environment_id: int, name: str, anchor_start_at: datetime, deploy_pattern: DeployPattern|None=None, notes: str|None=None)`, `RunbookPlanUpdate(name: str|None, anchor_start_at: datetime|None, deploy_pattern: DeployPattern|None, notes: str|None)` — keyed on `model_fields_set`; type alias `DeployPattern = Literal["rolling","blue_green","canary","big_bang","other"]`.
- Produces (service): `get_plan(db, plan_id, tenant_id) -> RunbookPlan` (404), `list_plans(db, release_id, tenant_id, page) -> tuple[list[RunbookPlan], int]`, `create_plan(db, release_id, tenant_id, data) -> RunbookPlan`, `update_plan(db, plan, data) -> RunbookPlan`, `delete_plan(db, plan, tenant_id) -> None`, `live_tasks(db, plan_id, tenant_id) -> list[RunbookTask]` (ordered by `sort_order, id`), `live_edges(db, plan_id, tenant_id) -> list[tuple[int, int]]` (both ends live, `(task_id, predecessor_id)`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_runbook_service.py`:

```python
"""runbook_service: plan and task writes, and the validation that keeps the
dependency graph honest. Transitions are test_runbook_execution.py's."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.v1.schemas.runbook import RunbookPlanCreate, RunbookPlanUpdate
from app.core.pagination import Page
from app.db.models.runbook import RunbookPlan
from app.services import runbook_service
from tests.factories import ensure_environment
from tests.runbook_helpers import make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


def _create(env_id, **kw):
    return RunbookPlanCreate(environment_id=env_id, name=kw.get("name", "Cutover"), anchor_start_at=ANCHOR,
                             deploy_pattern=kw.get("deploy_pattern"))


@pytest.mark.asyncio
async def test_create_then_a_second_live_plan_for_the_pair_is_a_409(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(test_environment.id))
    assert plan.id and plan.environment_id == test_environment.id
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(test_environment.id))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_deleted_plans_slot_is_revived_with_the_same_id_and_no_tasks(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    first = await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(test_environment.id))
    await make_task(db_session, first, "old task")
    await runbook_service.delete_plan(db_session, first, test_tenant.id)
    again = await runbook_service.create_plan(db_session, release.id, test_tenant.id,
                                              _create(test_environment.id, name="Take two", deploy_pattern="canary"))
    assert again.id == first.id
    assert again.deleted_at is None and again.name == "Take two" and again.deploy_pattern == "canary"
    assert await runbook_service.live_tasks(db_session, again.id, test_tenant.id) == []


@pytest.mark.asyncio
async def test_an_environment_from_another_tenant_or_archived_is_refused(db_session, test_tenant, test_user, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    other_tenant, _ = await second_tenant_factory()
    foreign = await ensure_environment(db_session, other_tenant.id, name="foreign-env")
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(foreign.id))
    assert exc.value.status_code == 404
    archived = await ensure_environment(db_session, test_tenant.id, name="archived-env")
    archived.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(archived.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_plan_is_invisible_from_another_tenant(db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    other_tenant, _ = await second_tenant_factory()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.get_plan(db_session, plan.id, other_tenant.id)
    assert exc.value.status_code == 404
    rows, total = await runbook_service.list_plans(db_session, release.id, other_tenant.id, Page(limit=50, offset=0))
    assert rows == [] and total == 0


@pytest.mark.asyncio
async def test_update_changes_only_the_fields_sent(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    plan.notes = "keep me"
    await runbook_service.update_plan(db_session, plan, RunbookPlanUpdate(anchor_start_at=ANCHOR + timedelta(hours=1)))
    assert plan.notes == "keep me" and plan.anchor_start_at == ANCHOR + timedelta(hours=1)
    await runbook_service.update_plan(db_session, plan, RunbookPlanUpdate(notes=None))
    assert plan.notes is None


@pytest.mark.asyncio
async def test_a_plan_with_a_started_task_cannot_be_deleted(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    await make_task(db_session, plan, "running", status="in_progress")
    with pytest.raises(HTTPException) as exc:
        await runbook_service.delete_plan(db_session, plan, test_tenant.id)
    assert exc.value.status_code == 409
    assert (await db_session.get(RunbookPlan, plan.id)).deleted_at is None


@pytest.mark.asyncio
async def test_list_plans_orders_by_environment_name(db_session, test_tenant, test_user):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    zed = await ensure_environment(db_session, test_tenant.id, name="zed-prod")
    alpha = await ensure_environment(db_session, test_tenant.id, name="Alpha-preprod")
    await make_plan(db_session, release, zed, anchor=ANCHOR)
    await make_plan(db_session, release, alpha, anchor=ANCHOR)
    rows, total = await runbook_service.list_plans(db_session, release.id, test_tenant.id, Page(limit=50, offset=0))
    assert [p.environment_id for p in rows] == [alpha.id, zed.id] and total == 2
```

Before running, check `ensure_environment`'s signature: `grep -n "async def ensure_environment" -A8 tests/factories.py` and adapt the `name=` keyword if it differs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runbook_service.py -q`
Expected: FAIL — `ModuleNotFoundError` for `app.api.v1.schemas.runbook`.

- [ ] **Step 3: Write the plan schemas**

`backend/app/api/v1/schemas/runbook.py`:

```python
"""Phase 9 C5a — cutover runbook schemas.

Every REQUEST schema declares extra="forbid": an undeclared field on a request
schema is silent data loss here, not a validation error (C6's is_failed,
A4's priority_rank). Update schemas key on model_fields_set — an omitted key
means "leave alone", an explicit null clears a nullable field.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DeployPattern = Literal["rolling", "blue_green", "canary", "big_bang", "other"]
TaskKind = Literal["task", "check", "deploy", "verification", "ramp"]
TaskStatus = Literal["not_started", "in_progress", "done", "failed", "skipped"]


class RunbookPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment_id: int
    name: str = Field(min_length=1, max_length=200)
    anchor_start_at: datetime
    deploy_pattern: Optional[DeployPattern] = None
    notes: Optional[str] = None


class RunbookPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    anchor_start_at: Optional[datetime] = None
    deploy_pattern: Optional[DeployPattern] = None
    notes: Optional[str] = None
```

- [ ] **Step 4: Write the plan half of the service**

`backend/app/services/runbook_service.py`:

```python
"""Phase 9 C5a — runbook plan, task and dependency WRITES, and the validation
that keeps the graph honest. Status transitions live in
runbook_execution_service; the schedule in runbook_schedule_service.

C5a REFUSES ONLY WRITES TO ITS OWN RECORDS. Nothing in this file is consulted
by a deployment, a release transition, a booking, can-deploy or readiness —
tests/test_c5a_refuses_only_within_runbook.py is the guard.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.schemas.runbook import RunbookPlanCreate, RunbookPlanUpdate
from app.core.pagination import Page, fetch_page
from app.db.models.environment import Environment
from app.db.models.runbook import RunbookPlan, RunbookTask, RunbookTaskDependency
from app.services import release_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_plan(db: AsyncSession, plan_id: int, tenant_id: int) -> RunbookPlan:
    plan = (await db.execute(select(RunbookPlan).where(
        RunbookPlan.id == plan_id, RunbookPlan.tenant_id == tenant_id,
        RunbookPlan.deleted_at.is_(None)))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Runbook not found")
    return plan


async def list_plans(db: AsyncSession, release_id: int, tenant_id: int,
                     page: Optional[Page]) -> tuple[list[RunbookPlan], int]:
    query = (
        select(RunbookPlan)
        .join(Environment, Environment.id == RunbookPlan.environment_id)
        .where(RunbookPlan.release_id == release_id, RunbookPlan.tenant_id == tenant_id,
               RunbookPlan.deleted_at.is_(None))
        # Case folded explicitly: both engines collate by byte value (CLAUDE.md).
        .order_by(func.lower(Environment.name), RunbookPlan.id)
    )
    return await fetch_page(db, query, page)


async def _live_environment(db: AsyncSession, environment_id: int, tenant_id: int) -> Environment:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id, Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None)))).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    return env


async def create_plan(db: AsyncSession, release_id: int, tenant_id: int,
                      data: RunbookPlanCreate) -> RunbookPlan:
    await release_service.get_release(db, release_id, tenant_id)
    await _live_environment(db, data.environment_id, tenant_id)
    rows = (await db.execute(select(RunbookPlan).where(
        RunbookPlan.release_id == release_id, RunbookPlan.environment_id == data.environment_id,
        RunbookPlan.tenant_id == tenant_id).order_by(RunbookPlan.id))).scalars().all()
    if any(p.deleted_at is None for p in rows):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This release already has a runbook for that environment")
    # REVIVE a soft-deleted slot rather than insert a second row (C4's lesson).
    # Its old tasks stay soft-deleted: a revived plan starts empty.
    plan = rows[0] if rows else RunbookPlan(tenant_id=tenant_id, release_id=release_id,
                                            environment_id=data.environment_id)
    plan.name = data.name
    plan.anchor_start_at = data.anchor_start_at
    plan.deploy_pattern = data.deploy_pattern
    plan.notes = data.notes
    plan.deleted_at = None
    if not rows:
        db.add(plan)
    await db.flush()
    return plan


async def update_plan(db: AsyncSession, plan: RunbookPlan, data: RunbookPlanUpdate) -> RunbookPlan:
    sent = data.model_fields_set
    if "name" in sent:
        if data.name is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name cannot be null")
        plan.name = data.name
    if "anchor_start_at" in sent:
        if data.anchor_start_at is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "anchor_start_at cannot be null")
        plan.anchor_start_at = data.anchor_start_at
    if "deploy_pattern" in sent:
        plan.deploy_pattern = data.deploy_pattern
    if "notes" in sent:
        plan.notes = data.notes
    await db.flush()
    return plan


async def live_tasks(db: AsyncSession, plan_id: int, tenant_id: int) -> list[RunbookTask]:
    return list((await db.execute(select(RunbookTask).where(
        RunbookTask.plan_id == plan_id, RunbookTask.tenant_id == tenant_id,
        RunbookTask.deleted_at.is_(None)).order_by(RunbookTask.sort_order, RunbookTask.id))).scalars().all())


async def live_edges(db: AsyncSession, plan_id: int, tenant_id: int) -> list[tuple[int, int]]:
    """(task_id, predecessor_id) where BOTH ends are live tasks of this plan.
    A soft-deleted predecessor counts as absent — the same rule
    runbook_execution_service.ready_clause applies in SQL."""
    succ, pred = aliased(RunbookTask), aliased(RunbookTask)
    rows = (await db.execute(
        select(RunbookTaskDependency.task_id, RunbookTaskDependency.predecessor_task_id)
        .join(succ, succ.id == RunbookTaskDependency.task_id)
        .join(pred, pred.id == RunbookTaskDependency.predecessor_task_id)
        .where(RunbookTaskDependency.tenant_id == tenant_id,
               succ.plan_id == plan_id, succ.deleted_at.is_(None),
               pred.plan_id == plan_id, pred.deleted_at.is_(None))
        .order_by(RunbookTaskDependency.id))).all()
    return [(a, b) for a, b in rows]


async def delete_plan(db: AsyncSession, plan: RunbookPlan, tenant_id: int) -> None:
    tasks = await live_tasks(db, plan.id, tenant_id)
    started = [t.name for t in tasks if t.status != "not_started"]
    if started:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A runbook whose tasks have started cannot be deleted — its history is "
                            f"the record. Started: {', '.join(started)}")
    now = _now()
    plan.deleted_at = now
    for t in tasks:
        t.deleted_at = now
    await db.flush()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_runbook_service.py -q`
Expected: PASS (7 passed)

- [ ] **Step 6: Mutation check on the tenant filters**

Temporarily delete `RunbookPlan.tenant_id == tenant_id,` from `get_plan`; run `uv run pytest tests/test_runbook_service.py::test_a_plan_is_invisible_from_another_tenant -q`; expected FAIL. Restore it. Do the same for `list_plans`. Record in the commit message that both were watched failing.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/runbook_service.py backend/app/api/v1/schemas/runbook.py backend/tests/test_runbook_service.py
git commit -m "feat(c5a): runbook plan writes — one live plan per pair, revive, delete guard"
```

---

### Task 4: Task and dependency writes

**Files:**
- Modify: `backend/app/services/runbook_service.py` (append)
- Modify: `backend/app/api/v1/schemas/runbook.py` (append task request schemas)
- Test: `backend/tests/test_runbook_service.py` (append)

**Interfaces:**
- Consumes: Task 2's `topological_order`, `CycleError`; Task 3's `live_tasks`, `live_edges`, `get_plan`.
- Produces (schemas): `RunbookTaskCreate(name, description=None, team_group_id=None, system_id=None, kind: TaskKind="task", duration_minutes: int (ge=0, le=10080), fixed_start_at=None, sort_order: int=0, predecessor_ids: list[int]=[])`, `RunbookTaskUpdate` (same fields minus `predecessor_ids`, all optional, `model_fields_set`), `PredecessorsUpdate(predecessor_ids: list[int])`.
- Produces (service): `get_task(db, task_id, tenant_id) -> tuple[RunbookTask, RunbookPlan]` (404 if task or its plan is deleted), `create_task(db, plan, tenant_id, data) -> RunbookTask`, `update_task(db, task, plan, tenant_id, data) -> RunbookTask`, `delete_task(db, task, tenant_id) -> None`, `set_predecessors(db, task, plan, tenant_id, predecessor_ids: list[int]) -> None`.

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_runbook_service.py`)

```python
from sqlalchemy import select as _select

from app.api.v1.schemas.runbook import RunbookTaskCreate, RunbookTaskUpdate
from app.db.models.runbook import RunbookTask, RunbookTaskDependency
from tests.factories import ensure_user_group
from tests.runbook_helpers import attach_system, link, make_system


async def _plan(db, tenant, user, env):
    release = await make_release(db, tenant.id, user.id)
    return release, await make_plan(db, release, env, anchor=ANCHOR)


@pytest.mark.asyncio
async def test_create_task_with_predecessors_in_the_same_plan(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "A")
    b = await runbook_service.create_task(db_session, plan, test_tenant.id,
                                          RunbookTaskCreate(name="B", duration_minutes=10, predecessor_ids=[a.id]))
    assert await runbook_service.live_edges(db_session, plan.id, test_tenant.id) == [(b.id, a.id)]


@pytest.mark.asyncio
async def test_a_cycle_is_refused_naming_the_tasks(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "Deploy API")
    b = await make_task(db_session, plan, "Smoke test")
    await link(db_session, b, a)
    with pytest.raises(HTTPException) as exc:
        await runbook_service.set_predecessors(db_session, a, plan, test_tenant.id, [b.id])
    assert exc.value.status_code == 409
    assert "cycle" in exc.value.detail and "Deploy API" in exc.value.detail and "Smoke test" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await runbook_service.set_predecessors(db_session, a, plan, test_tenant.id, [a.id])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_predecessor_from_another_plan_or_deleted_is_refused(db_session, test_tenant, test_user, test_environment):
    release, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    other_env = await ensure_environment(db_session, test_tenant.id, name="other-env")
    other_plan = await make_plan(db_session, release, other_env, anchor=ANCHOR)
    mine = await make_task(db_session, plan, "mine")
    theirs = await make_task(db_session, other_plan, "theirs")
    gone = await make_task(db_session, plan, "gone")
    gone.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    for bad in (theirs.id, gone.id):
        with pytest.raises(HTTPException) as exc:
            await runbook_service.set_predecessors(db_session, mine, plan, test_tenant.id, [bad])
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_an_unsatisfied_predecessor_cannot_be_added_under_a_started_task(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    running = await make_task(db_session, plan, "running", status="in_progress")
    pending = await make_task(db_session, plan, "pending")
    finished = await make_task(db_session, plan, "finished", status="done")
    with pytest.raises(HTTPException) as exc:
        await runbook_service.set_predecessors(db_session, running, plan, test_tenant.id, [pending.id])
    assert exc.value.status_code == 409 and "pending" in exc.value.detail
    await runbook_service.set_predecessors(db_session, running, plan, test_tenant.id, [finished.id])  # fine


@pytest.mark.asyncio
async def test_set_predecessors_replaces_the_whole_set(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "A")
    b = await make_task(db_session, plan, "B")
    c = await make_task(db_session, plan, "C")
    await runbook_service.set_predecessors(db_session, c, plan, test_tenant.id, [a.id, b.id, a.id])
    assert sorted(await runbook_service.live_edges(db_session, plan.id, test_tenant.id)) == [(c.id, a.id), (c.id, b.id)]
    await runbook_service.set_predecessors(db_session, c, plan, test_tenant.id, [b.id])
    assert await runbook_service.live_edges(db_session, plan.id, test_tenant.id) == [(c.id, b.id)]


@pytest.mark.asyncio
async def test_a_started_task_cannot_be_deleted_and_a_not_started_one_takes_its_edges(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "A")
    b = await make_task(db_session, plan, "B")
    c = await make_task(db_session, plan, "C", status="in_progress")
    await link(db_session, b, a)
    with pytest.raises(HTTPException) as exc:
        await runbook_service.delete_task(db_session, c, test_tenant.id)
    assert exc.value.status_code == 409
    await runbook_service.delete_task(db_session, a, test_tenant.id)
    rows = (await db_session.execute(_select(RunbookTaskDependency))).scalars().all()
    assert rows == []   # hard-deleted in both directions
    assert (await db_session.get(RunbookTask, a.id)).deleted_at is not None


@pytest.mark.asyncio
async def test_team_validation_and_the_archived_carve_out(db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    ops = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    task = await runbook_service.create_task(db_session, plan, test_tenant.id,
                                             RunbookTaskCreate(name="T", duration_minutes=5, team_group_id=ops.id))
    ops.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    # re-sending the unchanged archived team is accepted
    await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                      RunbookTaskUpdate(name="T2", team_group_id=ops.id))
    fresh = await ensure_user_group(db_session, test_tenant.id, name="Archived")
    fresh.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                          RunbookTaskUpdate(team_group_id=fresh.id))
    assert exc.value.status_code == 404
    other_tenant, _ = await second_tenant_factory()
    foreign = await ensure_user_group(db_session, other_tenant.id, name="Foreign")
    with pytest.raises(HTTPException) as exc:
        await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                          RunbookTaskUpdate(team_group_id=foreign.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_system_must_be_on_the_release_unless_unchanged(db_session, test_tenant, test_user, test_environment):
    release, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    api = await make_system(db_session, test_tenant.id, "API")
    rs = await attach_system(db_session, release, api)
    stray = await make_system(db_session, test_tenant.id, "Stray")
    task = await runbook_service.create_task(db_session, plan, test_tenant.id,
                                             RunbookTaskCreate(name="Deploy", duration_minutes=5, system_id=api.id))
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_task(db_session, plan, test_tenant.id,
                                          RunbookTaskCreate(name="X", duration_minutes=5, system_id=stray.id))
    assert exc.value.status_code == 422
    await db_session.delete(rs)          # the system leaves the release (hard delete, as the API does)
    await db_session.flush()
    await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                      RunbookTaskUpdate(name="Deploy v2", system_id=api.id))
    assert task.system_id == api.id and task.name == "Deploy v2"


@pytest.mark.asyncio
async def test_a_task_in_another_tenant_is_not_found(db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    task = await make_task(db_session, plan, "T")
    other_tenant, _ = await second_tenant_factory()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.get_task(db_session, task.id, other_tenant.id)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runbook_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'RunbookTaskCreate'`

- [ ] **Step 3: Append the task schemas** to `backend/app/api/v1/schemas/runbook.py`

```python
class RunbookTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    system_id: Optional[int] = None
    kind: TaskKind = "task"
    duration_minutes: int = Field(ge=0, le=10080)
    fixed_start_at: Optional[datetime] = None
    sort_order: int = 0
    predecessor_ids: list[int] = Field(default_factory=list)


class RunbookTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    system_id: Optional[int] = None
    kind: Optional[TaskKind] = None
    duration_minutes: Optional[int] = Field(default=None, ge=0, le=10080)
    fixed_start_at: Optional[datetime] = None
    sort_order: Optional[int] = None


class PredecessorsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    predecessor_ids: list[int]
```

- [ ] **Step 4: Append the task half of the service** to `backend/app/services/runbook_service.py`

Add imports at the top: `from sqlalchemy import delete, or_`, `from app.api.v1.schemas.runbook import PredecessorsUpdate, RunbookTaskCreate, RunbookTaskUpdate` (extend the existing import), `from app.db.models.release_system import ReleaseSystem`, `from app.db.models.runbook import SATISFIED_STATUSES`, `from app.services import user_group_service`, `from app.services.runbook_schedule_service import CycleError, topological_order`.

```python
async def get_task(db: AsyncSession, task_id: int, tenant_id: int) -> tuple[RunbookTask, RunbookPlan]:
    row = (await db.execute(
        select(RunbookTask, RunbookPlan)
        .join(RunbookPlan, RunbookPlan.id == RunbookTask.plan_id)
        .where(RunbookTask.id == task_id, RunbookTask.tenant_id == tenant_id,
               RunbookTask.deleted_at.is_(None), RunbookPlan.deleted_at.is_(None)))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Runbook task not found")
    return row[0], row[1]


async def _validate_team(db, tenant_id: int, new_id: Optional[int], current_id: Optional[int]) -> None:
    """A1's archived-value carve-out: an unchanged team is accepted even if it
    has since been archived; a NEW assignment must be a live group of this tenant."""
    if new_id is None or new_id == current_id:
        return
    await user_group_service.get_group(db, new_id, tenant_id)   # 404s on archived / foreign


async def _validate_system(db, plan: RunbookPlan, tenant_id: int, new_id: Optional[int],
                           current_id: Optional[int]) -> None:
    """The permission guards a CHANGE, not a mention (B2): an unchanged system
    that has since left the release is accepted on a full-form save."""
    if new_id is None or new_id == current_id:
        return
    on_release = (await db.execute(select(ReleaseSystem.id).where(
        ReleaseSystem.release_id == plan.release_id, ReleaseSystem.system_id == new_id,
        ReleaseSystem.tenant_id == tenant_id))).first()
    if on_release is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That system is not part of this release")


async def create_task(db: AsyncSession, plan: RunbookPlan, tenant_id: int,
                      data: RunbookTaskCreate) -> RunbookTask:
    await _validate_team(db, tenant_id, data.team_group_id, None)
    await _validate_system(db, plan, tenant_id, data.system_id, None)
    task = RunbookTask(
        tenant_id=tenant_id, plan_id=plan.id, name=data.name, description=data.description,
        team_group_id=data.team_group_id, system_id=data.system_id, kind=data.kind,
        duration_minutes=data.duration_minutes, fixed_start_at=data.fixed_start_at,
        sort_order=data.sort_order, status="not_started")
    db.add(task)
    await db.flush()
    if data.predecessor_ids:
        await set_predecessors(db, task, plan, tenant_id, data.predecessor_ids)
    return task


_NOT_NULL = {"name", "kind", "duration_minutes", "sort_order"}


async def update_task(db: AsyncSession, task: RunbookTask, plan: RunbookPlan, tenant_id: int,
                      data: RunbookTaskUpdate) -> RunbookTask:
    sent = data.model_fields_set
    for field in _NOT_NULL & sent:
        if getattr(data, field) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be null")
    if "team_group_id" in sent:
        await _validate_team(db, tenant_id, data.team_group_id, task.team_group_id)
    if "system_id" in sent:
        await _validate_system(db, plan, tenant_id, data.system_id, task.system_id)
    for field in ("name", "description", "team_group_id", "system_id", "kind",
                  "duration_minutes", "fixed_start_at", "sort_order"):
        if field in sent:
            setattr(task, field, getattr(data, field))
    await db.flush()
    return task


async def delete_task(db: AsyncSession, task: RunbookTask, tenant_id: int) -> None:
    if task.status != "not_started":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"'{task.name}' has started and cannot be deleted — its history is the record")
    await db.execute(delete(RunbookTaskDependency).where(
        RunbookTaskDependency.tenant_id == tenant_id,
        or_(RunbookTaskDependency.task_id == task.id,
            RunbookTaskDependency.predecessor_task_id == task.id)))
    task.deleted_at = _now()
    await db.flush()


async def set_predecessors(db: AsyncSession, task: RunbookTask, plan: RunbookPlan, tenant_id: int,
                           predecessor_ids: list[int]) -> None:
    """Replace the whole set, validated as one unit (spec §4)."""
    ids = list(dict.fromkeys(predecessor_ids))
    tasks = {t.id: t for t in await live_tasks(db, plan.id, tenant_id)}
    if task.id in ids:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This dependency would create a cycle through: {task.name}")
    missing = [i for i in ids if i not in tasks]
    if missing:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Not live tasks in this runbook: {', '.join(map(str, missing))}")
    if task.status != "not_started":
        unsatisfied = [tasks[i] for i in ids if tasks[i].status not in SATISFIED_STATUSES]
        if unsatisfied:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{task.name}' has already started, so it cannot wait on tasks that are not done: "
                + ", ".join(f"{t.name} ({t.status})" for t in unsatisfied))
    edges = [(a, b) for a, b in await live_edges(db, plan.id, tenant_id) if a != task.id]
    edges += [(task.id, i) for i in ids]
    try:
        topological_order(tasks, edges)
    except CycleError as exc:
        names = sorted(tasks[i].name for i in exc.task_ids if i in tasks)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This dependency would create a cycle through: {', '.join(names)}")
    await db.execute(delete(RunbookTaskDependency).where(
        RunbookTaskDependency.tenant_id == tenant_id, RunbookTaskDependency.task_id == task.id))
    for i in ids:
        db.add(RunbookTaskDependency(tenant_id=tenant_id, task_id=task.id, predecessor_task_id=i))
    await db.flush()
```

Note: `CycleError.task_ids` is the set left unsorted by Kahn's algorithm — the cycle plus anything downstream of it. The message names all of them; that is acceptable and the test asserts only that both cycle members appear.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_runbook_service.py -q`
Expected: PASS

- [ ] **Step 6: Mutation check** — remove `RunbookTask.tenant_id == tenant_id,` from `get_task`; `test_a_task_in_another_tenant_is_not_found` must FAIL; restore.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/runbook_service.py backend/app/api/v1/schemas/runbook.py backend/tests/test_runbook_service.py
git commit -m "feat(c5a): runbook task and dependency writes — cycles, cross-plan, invariant refused"
```

---

### Task 5: Transitions, permissions and history

**Files:**
- Create: `backend/app/services/runbook_execution_service.py`
- Modify: `backend/app/api/v1/schemas/runbook.py` (append `TransitionRequest`)
- Test: `backend/tests/test_runbook_execution.py`

**Interfaces:**
- Consumes: Task 4's `get_task`, Task 3's `live_tasks`, `live_edges`.
- Produces (schema): `TransitionRequest(to_status: TaskStatus, at: datetime|None=None, reason: str|None=None)`.
- Produces (service):
  - `is_manager(user) -> bool`
  - `async team_ids_for(db, user_id: int, tenant_id: int, group_ids: set[int]) -> set[int]` — which of `group_ids` the user belongs to.
  - `allowed_transitions(task_status: str, pred_statuses: list[str], succ_statuses: list[str], *, manager: bool, team_member: bool) -> list[str]` — pure; targets the caller could perform right now, in the order `in_progress, done, failed, skipped, not_started`.
  - `async transition(db, task, plan, tenant_id, user, data: TransitionRequest, now: datetime) -> RunbookTask`
  - `async list_events(db, task_id, tenant_id, page) -> tuple[list[RunbookTaskEvent], int]`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_runbook_execution.py`:

```python
"""Spec §4, one test per row of the transition table, plus permissions,
reasons, `at`, and the invariant on reopen."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.schemas.runbook import TransitionRequest
from app.core.pagination import Page
from app.db.models.runbook import RunbookTaskEvent
from app.services import runbook_execution_service as ex
from tests.factories import add_group_member, ensure_user, ensure_user_group
from tests.runbook_helpers import link, make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
NOW = ANCHOR + timedelta(hours=1)


@pytest.fixture
async def world(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    team = await ensure_user_group(db_session, test_tenant.id, name="DBA")
    member = await ensure_user(db_session, test_tenant.id, username="dba1", role="Developer")
    outsider = await ensure_user(db_session, test_tenant.id, username="dev2", role="Developer")
    rm = await ensure_user(db_session, test_tenant.id, username="rm1", role="Release Manager")
    await add_group_member(db_session, team, member)
    for u in (member, outsider, rm):
        u.active_tenant_id = test_tenant.id
    test_user.active_tenant_id = test_tenant.id
    return dict(plan=plan, team=team, member=member, outsider=outsider, rm=rm, admin=test_user,
                tenant_id=test_tenant.id)


async def _go(db, w, task, user, to, **kw):
    return await ex.transition(db, task, w["plan"], w["tenant_id"], user, TransitionRequest(to_status=to, **kw), NOW)


@pytest.mark.asyncio
async def test_start_is_refused_until_every_predecessor_is_satisfied(db_session, world):
    w = world
    a = await make_task(db_session, w["plan"], "Deploy API", team=w["team"])
    b = await make_task(db_session, w["plan"], "Deploy DB", team=w["team"], status="in_progress")
    tests = await make_task(db_session, w["plan"], "Run tests", team=w["team"])
    await link(db_session, tests, a, b)
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, tests, w["member"], "in_progress")
    assert exc.value.status_code == 409
    assert "Deploy API (not_started)" in exc.value.detail and "Deploy DB (in_progress)" in exc.value.detail
    a.status, b.status = "done", "skipped"
    await db_session.flush()
    await _go(db_session, w, tests, w["member"], "in_progress")
    assert tests.status == "in_progress" and tests.actual_started_at == NOW


@pytest.mark.asyncio
async def test_not_started_straight_to_done_stamps_both_times(db_session, world):
    t = await make_task(db_session, world["plan"], "Check", team=world["team"])
    at = NOW - timedelta(minutes=5)
    await _go(db_session, world, t, world["member"], "done", at=at)
    assert t.actual_started_at == at and t.actual_finished_at == at


@pytest.mark.asyncio
async def test_in_progress_to_done_and_to_failed(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"], status="in_progress")
    await _go(db_session, world, t, world["member"], "failed")
    assert t.status == "failed" and t.actual_finished_at == NOW


@pytest.mark.asyncio
async def test_retry_restamps_the_start_clears_the_finish_and_keeps_the_failure(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"], status="in_progress")
    await _go(db_session, world, t, world["member"], "failed", at=NOW - timedelta(minutes=10))
    await _go(db_session, world, t, world["member"], "in_progress")
    assert t.status == "in_progress" and t.actual_started_at == NOW and t.actual_finished_at is None
    events = (await db_session.execute(select(RunbookTaskEvent).where(RunbookTaskEvent.task_id == t.id)
                                       .order_by(RunbookTaskEvent.id))).scalars().all()
    assert [(e.from_status, e.to_status) for e in events] == [("in_progress", "failed"), ("failed", "in_progress")]


@pytest.mark.asyncio
async def test_skip_is_manager_only_needs_a_reason_and_ignores_predecessors(db_session, world):
    w = world
    pred = await make_task(db_session, w["plan"], "Pred")
    t = await make_task(db_session, w["plan"], "T", team=w["team"])
    await link(db_session, t, pred)
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, t, w["member"], "skipped", reason="n/a")
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, t, w["rm"], "skipped")
    assert exc.value.status_code == 422
    await _go(db_session, w, t, w["rm"], "skipped", reason="not needed in this region")
    assert t.status == "skipped"
    ev = (await db_session.execute(select(RunbookTaskEvent).where(RunbookTaskEvent.task_id == t.id))).scalar_one()
    assert ev.note == "not needed in this region" and ev.by_user_id == w["rm"].id


@pytest.mark.asyncio
async def test_reopen_is_refused_under_a_started_successor(db_session, world):
    w = world
    a = await make_task(db_session, w["plan"], "A", status="done")
    b = await make_task(db_session, w["plan"], "B", status="in_progress")
    await link(db_session, b, a)
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, a, w["admin"], "not_started", reason="ticked wrong task")
    assert exc.value.status_code == 409 and "B" in exc.value.detail
    b.status = "not_started"
    await db_session.flush()
    await _go(db_session, w, a, w["admin"], "not_started", reason="ticked wrong task")
    assert a.status == "not_started" and a.actual_started_at is None and a.actual_finished_at is None


@pytest.mark.asyncio
async def test_a_transition_not_in_the_table_is_a_409(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"], status="done")
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, world, t, world["member"], "failed")
    assert exc.value.status_code == 409 and "done" in exc.value.detail


@pytest.mark.asyncio
async def test_permissions_team_manager_outsider_and_the_empty_team(db_session, world, test_tenant):
    w = world
    t = await make_task(db_session, w["plan"], "T", team=w["team"])
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, t, w["outsider"], "in_progress")
    assert exc.value.status_code == 403
    no_team = await make_task(db_session, w["plan"], "No team")
    with pytest.raises(HTTPException):
        await _go(db_session, w, no_team, w["member"], "in_progress")
    empty = await ensure_user_group(db_session, test_tenant.id, name="Empty")
    empty_task = await make_task(db_session, w["plan"], "Empty team", team=empty)
    with pytest.raises(HTTPException):
        await _go(db_session, w, empty_task, w["member"], "in_progress")
    await _go(db_session, w, no_team, w["rm"], "in_progress")
    await _go(db_session, w, empty_task, w["admin"], "in_progress")


@pytest.mark.asyncio
async def test_a_master_admin_impersonating_is_a_manager(db_session, world, second_tenant_factory):
    other_tenant, master = await second_tenant_factory()
    master.is_master_admin = True
    master.role = "Developer"
    master.active_tenant_id = world["tenant_id"]
    t = await make_task(db_session, world["plan"], "T")
    await _go(db_session, world, t, master, "skipped", reason="impersonated fix")
    assert t.status == "skipped"


@pytest.mark.asyncio
async def test_membership_is_tenant_qualified(db_session, world, second_tenant_factory):
    """A member row carrying ANOTHER tenant's id must not grant anything here."""
    other_tenant, _ = await second_tenant_factory()
    stranger = await ensure_user(db_session, world["tenant_id"], username="stranger", role="Developer")
    stranger.active_tenant_id = world["tenant_id"]
    from app.db.models.user_group import UserGroupMember
    db_session.add(UserGroupMember(tenant_id=other_tenant.id, group_id=world["team"].id, user_id=stranger.id))
    await db_session.flush()
    t = await make_task(db_session, world["plan"], "T", team=world["team"])
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, world, t, stranger, "in_progress")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_at_in_the_future_is_422_and_omitted_means_now(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"])
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, world, t, world["member"], "in_progress", at=NOW + timedelta(minutes=1))
    assert exc.value.status_code == 422
    await _go(db_session, world, t, world["member"], "in_progress")
    assert t.actual_started_at == NOW


@pytest.mark.asyncio
async def test_back_dating_before_a_predecessor_finished_is_accepted(db_session, world):
    """C5a does not police honest back-dating (spec §4)."""
    a = await make_task(db_session, world["plan"], "A", team=world["team"], status="in_progress")
    b = await make_task(db_session, world["plan"], "B", team=world["team"])
    await link(db_session, b, a)
    await _go(db_session, world, a, world["member"], "done", at=NOW)
    await _go(db_session, world, b, world["member"], "done", at=NOW - timedelta(minutes=30))
    assert b.status == "done"


@pytest.mark.parametrize("status, preds, succs, manager, member, expected", [
    ("not_started", ["done"], [], False, True, ["in_progress", "done"]),
    ("not_started", ["in_progress"], [], False, True, []),
    ("not_started", ["in_progress"], [], True, False, ["skipped"]),
    ("not_started", [], [], True, False, ["in_progress", "done", "skipped"]),
    ("in_progress", [], [], False, True, ["done", "failed"]),
    ("failed", [], [], False, True, ["in_progress"]),
    ("failed", [], [], True, False, ["in_progress", "skipped"]),
    ("done", [], ["not_started"], True, False, ["not_started"]),
    ("done", [], ["in_progress"], True, False, []),
    ("done", [], [], False, True, []),
    ("in_progress", [], [], False, False, []),
])
def test_allowed_transitions(status, preds, succs, manager, member, expected):
    assert ex.allowed_transitions(status, preds, succs, manager=manager, team_member=member) == expected


@pytest.mark.asyncio
async def test_events_are_newest_first_and_tenant_scoped(db_session, world, second_tenant_factory):
    t = await make_task(db_session, world["plan"], "T", team=world["team"])
    await _go(db_session, world, t, world["member"], "in_progress", at=NOW - timedelta(minutes=5))
    await _go(db_session, world, t, world["member"], "done")
    rows, total = await ex.list_events(db_session, t.id, world["tenant_id"], Page(limit=50, offset=0))
    assert [r.to_status for r in rows] == ["done", "in_progress"] and total == 2
    other_tenant, _ = await second_tenant_factory()
    rows, total = await ex.list_events(db_session, t.id, other_tenant.id, Page(limit=50, offset=0))
    assert rows == [] and total == 0
```

Check that `ensure_user` sets `is_active` (it doesn't pass it; the model default is `True`) and that `second_tenant_factory()` returns `(tenant, user)` — both confirmed in `conftest.py`/`factories.py`. `active_tenant_id` is a plain attribute set by `get_current_user`; the tests set it by hand exactly as that dependency does.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runbook_execution.py -q`
Expected: FAIL — `ImportError: cannot import name 'TransitionRequest'`

- [ ] **Step 3: Append `TransitionRequest`** to `backend/app/api/v1/schemas/runbook.py`

```python
class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_status: TaskStatus
    at: Optional[datetime] = None
    reason: Optional[str] = Field(default=None, max_length=2000)
```

- [ ] **Step 4: Implement**

`backend/app/services/runbook_execution_service.py`:

```python
"""Phase 9 C5a — runbook task status transitions, who may make them, and the
append-only history.

THE INVARIANT: no task is in_progress or done while any predecessor is
anything other than done or skipped. Every refusal here protects that one
sentence (spec §4). It is the ONLY rule C5a enforces, and only on writes to
runbook records.

Membership is read in exactly one place, `team_ids_for`.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.runbook import TransitionRequest
from app.core.pagination import Page, fetch_page
from app.core.security import Role
from app.db.models.runbook import (
    SATISFIED_STATUSES, RunbookPlan, RunbookTask, RunbookTaskDependency, RunbookTaskEvent,
)
from app.db.models.user_group import UserGroupMember
from app.services import runbook_service

EDGES: dict[str, tuple[str, ...]] = {
    "not_started": ("in_progress", "done", "skipped"),
    "in_progress": ("done", "failed"),
    "failed": ("in_progress", "skipped"),
    "done": ("not_started",),
    "skipped": ("not_started",),
}
_ORDER = ("in_progress", "done", "failed", "skipped", "not_started")
MANAGER_ONLY = {("not_started", "skipped"), ("failed", "skipped"),
                ("done", "not_started"), ("skipped", "not_started")}
NEEDS_PREDECESSORS = {("not_started", "in_progress"), ("not_started", "done")}
NEEDS_QUIET_SUCCESSORS = {("done", "not_started"), ("skipped", "not_started")}


def is_manager(user) -> bool:
    return bool(user.is_master_admin) or user.role in (Role.ADMIN, Role.RELEASE_MANAGER)


async def team_ids_for(db: AsyncSession, user_id: int, tenant_id: int, group_ids: set[int]) -> set[int]:
    """Which of `group_ids` the user is a member of, IN THIS TENANT. A task with
    no team, or a team with no members, simply matches nothing — degrading to
    managers only (B3b's rule)."""
    ids = {g for g in group_ids if g is not None}
    if not ids:
        return set()
    rows = (await db.execute(select(UserGroupMember.group_id).where(
        UserGroupMember.user_id == user_id, UserGroupMember.tenant_id == tenant_id,
        UserGroupMember.group_id.in_(ids)))).scalars().all()
    return set(rows)


def allowed_transitions(task_status: str, pred_statuses: list[str], succ_statuses: list[str], *,
                        manager: bool, team_member: bool) -> list[str]:
    """Targets the caller could perform RIGHT NOW. The UI renders only these."""
    out = []
    for to in EDGES.get(task_status, ()):
        pair = (task_status, to)
        if pair in MANAGER_ONLY:
            if not manager:
                continue
        elif not (manager or team_member):
            continue
        if pair in NEEDS_PREDECESSORS and any(s not in SATISFIED_STATUSES for s in pred_statuses):
            continue
        if pair in NEEDS_QUIET_SUCCESSORS and any(s != "not_started" for s in succ_statuses):
            continue
        out.append(to)
    return sorted(out, key=_ORDER.index)


async def _neighbours(db, task: RunbookTask, tenant_id: int) -> tuple[list[RunbookTask], list[RunbookTask]]:
    by_id = {t.id: t for t in await runbook_service.live_tasks(db, task.plan_id, tenant_id)}
    edges = await runbook_service.live_edges(db, task.plan_id, tenant_id)
    preds = [by_id[p] for s, p in edges if s == task.id]
    succs = [by_id[s] for s, p in edges if p == task.id]
    return preds, succs


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def transition(db: AsyncSession, task: RunbookTask, plan: RunbookPlan, tenant_id: int, user,
                     data: TransitionRequest, now: datetime) -> RunbookTask:
    to, frm = data.to_status, task.status
    pair = (frm, to)
    if to not in EDGES.get(frm, ()):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"'{task.name}' is {frm} and cannot move to {to}")
    manager = is_manager(user)
    if pair in MANAGER_ONLY:
        if not manager:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Only an Admin or Release Manager can skip or reopen a task")
    elif not manager:
        member = task.team_group_id is not None and task.team_group_id in await team_ids_for(
            db, user.id, tenant_id, {task.team_group_id})
        if not member:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Only the task's team, or an Admin or Release Manager, can update it")
    reason = (data.reason or "").strip() or None
    if pair in MANAGER_ONLY and reason is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A reason is required to skip or reopen a task")
    at = _utc(data.at) if data.at is not None else now
    if at > now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "'at' cannot be in the future")

    preds, succs = await _neighbours(db, task, tenant_id)
    if pair in NEEDS_PREDECESSORS:
        blocking = [p for p in preds if p.status not in SATISFIED_STATUSES]
        if blocking:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{task.name}' cannot start until these are done or skipped: "
                + ", ".join(f"{p.name} ({p.status})" for p in blocking))
    if pair in NEEDS_QUIET_SUCCESSORS:
        moving = [s for s in succs if s.status != "not_started"]
        if moving:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{task.name}' cannot be reopened while tasks that depend on it have started: "
                + ", ".join(f"{s.name} ({s.status})" for s in moving))

    if to == "in_progress":
        task.actual_started_at, task.actual_finished_at = at, None
    elif to == "done" and frm == "not_started":
        task.actual_started_at = task.actual_finished_at = at
    elif to in ("done", "failed", "skipped"):
        task.actual_finished_at = at
    elif to == "not_started":
        task.actual_started_at = task.actual_finished_at = None
    task.status = to
    db.add(RunbookTaskEvent(tenant_id=tenant_id, task_id=task.id, from_status=frm, to_status=to,
                            at=at, recorded_at=now, by_user_id=user.id, note=reason))
    await db.flush()
    return task


async def list_events(db: AsyncSession, task_id: int, tenant_id: int,
                      page: Optional[Page]) -> tuple[list[RunbookTaskEvent], int]:
    query = (select(RunbookTaskEvent)
             .where(RunbookTaskEvent.task_id == task_id, RunbookTaskEvent.tenant_id == tenant_id)
             .order_by(RunbookTaskEvent.recorded_at.desc(), RunbookTaskEvent.id.desc()))
    return await fetch_page(db, query, page)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_runbook_execution.py -q`
Expected: PASS. If `test_events_are_newest_first…` fails with equal `recorded_at`, the `id.desc()` tiebreaker decides — both events carry `NOW`, so order is by id; `done` was inserted second, so it comes first.

- [ ] **Step 6: Mutation checks** — (a) drop `UserGroupMember.tenant_id == tenant_id` from `team_ids_for`: `test_membership_is_tenant_qualified` must FAIL; (b) drop `RunbookTaskEvent.tenant_id == tenant_id` from `list_events`: the events test must FAIL. Restore both.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/runbook_execution_service.py backend/app/api/v1/schemas/runbook.py backend/tests/test_runbook_execution.py
git commit -m "feat(c5a): runbook transitions — the ordering refusal, skip/reopen, history"
```

---

### Task 6: Composite read, router, API tests, and the refusal guard

**Files:**
- Create: `backend/app/services/runbook_view_service.py`
- Create: `backend/app/api/v1/runbooks.py`
- Modify: `backend/app/api/v1/schemas/runbook.py` (append read schemas)
- Modify: `backend/app/main.py` (mount router near the closeout router)
- Test: `backend/tests/test_runbook_api.py`, `backend/tests/test_c5a_refuses_only_within_runbook.py`

**Interfaces:**
- Consumes: everything above; `user_group_service.get_group_names(db, ids) -> dict[int,str]`; `environment_service.get_environment_names(db, ids, tenant_id)`; `gate_waiver_service.usernames_for(db, ids)`.
- Produces (schemas): `RunbookPlanRead(id, release_id, environment_id, environment_name: str|None, name, anchor_start_at, deploy_pattern, notes, state: str)`; `RunbookTaskRead(id, name, description, kind, team_group_id, team_name, system_id, system_name, system_on_release: bool, duration_minutes, fixed_start_at, status, actual_started_at, actual_finished_at, sort_order, predecessor_ids: list[int], planned_start, planned_finish, forecast_start, forecast_finish, late_start, overrunning, slipped_past_fixed_start, blocked, critical: bool, allowed_transitions: list[str])`; `RunbookRead(plan: RunbookPlanRead, planned_end, forecast_end: datetime, slip_minutes: int, tasks: list[RunbookTaskRead])`; `RunbookTaskEventRead(id, from_status, to_status, at, recorded_at, by_username: str|None, note)`.
- Produces (service): `runbook_view_service.read(db, plan, tenant_id, user, now) -> RunbookRead`; `plan_reads(db, plans, tenant_id, now) -> list[RunbookPlanRead]`.
- Produces (HTTP): the routes of spec §6.

- [ ] **Step 1: Write the failing API tests**

`backend/tests/test_runbook_api.py`:

```python
"""The runbook routes end to end: roles, the composite read, 409 wording on
the wire, tenant isolation, and history usernames resolved without a tenant
qualifier."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.factories import add_group_member, ensure_user_group
from tests.runbook_helpers import attach_system, login_headers, make_release, make_system

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc).isoformat()


async def _plan(client, headers, release_id, env_id):
    r = await client.post(f"/api/v1/releases/{release_id}/runbooks", headers=headers,
                          json={"environment_id": env_id, "name": "Prod cutover", "anchor_start_at": ANCHOR})
    assert r.status_code == 201, r.text
    return r.json()["plan"]   # the create route returns the composite


async def _task(client, headers, plan_id, name, **kw):
    r = await client.post(f"/api/v1/runbooks/{plan_id}/tasks", headers=headers,
                          json={"name": name, "duration_minutes": kw.pop("duration", 30), **kw})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_the_composite_read_carries_schedule_names_and_allowed_transitions(
        client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    api = await make_system(db_session, test_tenant.id, "Payments API")
    await attach_system(db_session, release, api)
    team = await ensure_user_group(db_session, test_tenant.id, name="Payments team")
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    a = await _task(client, auth_headers, plan["id"], "Deploy API", system_id=api.id, team_group_id=team.id, kind="deploy")
    b = await _task(client, auth_headers, plan["id"], "Smoke test", predecessor_ids=[a["id"]], duration=15)
    body = (await client.get(f"/api/v1/runbooks/{plan['id']}", headers=auth_headers)).json()
    assert body["plan"]["environment_name"] == test_environment.name and body["plan"]["state"] == "not_started"
    tasks = {t["name"]: t for t in body["tasks"]}
    assert tasks["Deploy API"]["team_name"] == "Payments team"
    assert tasks["Deploy API"]["system_name"] == "Payments API" and tasks["Deploy API"]["system_on_release"] is True
    assert tasks["Smoke test"]["predecessor_ids"] == [a["id"]]
    assert tasks["Smoke test"]["planned_start"].startswith("2026-10-01T18:30")
    assert tasks["Deploy API"]["allowed_transitions"] == ["in_progress", "done", "skipped"]
    assert tasks["Smoke test"]["allowed_transitions"] == ["skipped"]
    assert body["planned_end"].startswith("2026-10-01T18:45")


@pytest.mark.asyncio
async def test_out_of_order_start_is_a_409_naming_the_blocker(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    a = await _task(client, auth_headers, plan["id"], "Deploy API")
    b = await _task(client, auth_headers, plan["id"], "Smoke test", predecessor_ids=[a["id"]])
    r = await client.post(f"/api/v1/runbook-tasks/{b['id']}/transition", headers=auth_headers,
                          json={"to_status": "in_progress"})
    assert r.status_code == 409 and "Deploy API (not_started)" in r.json()["detail"]


@pytest.mark.asyncio
async def test_structure_is_admin_or_rm_and_status_is_the_team(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    team = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    await db_session.commit()
    dev, dev_headers = await login_headers(client, db_session, test_tenant, "c5dev", "Developer")
    rm, rm_headers = await login_headers(client, db_session, test_tenant, "c5rm", "Release Manager")
    await add_group_member(db_session, team, dev)
    await db_session.commit()
    denied = await client.post(f"/api/v1/releases/{release.id}/runbooks", headers=dev_headers,
                               json={"environment_id": test_environment.id, "name": "X", "anchor_start_at": ANCHOR})
    assert denied.status_code == 403
    plan = await _plan(client, rm_headers, release.id, test_environment.id)
    task = await _task(client, rm_headers, plan["id"], "Restart", team_group_id=team.id)
    assert (await client.patch(f"/api/v1/runbook-tasks/{task['id']}", headers=dev_headers,
                               json={"duration_minutes": 5})).status_code == 403
    ok = await client.post(f"/api/v1/runbook-tasks/{task['id']}/transition", headers=dev_headers,
                           json={"to_status": "in_progress"})
    assert ok.status_code == 200, ok.text
    listed = await client.get(f"/api/v1/releases/{release.id}/runbooks", headers=dev_headers)
    assert listed.status_code == 200 and listed.headers["X-Total-Count"] == "1"
    assert listed.json()[0]["state"] == "in_progress"


@pytest.mark.asyncio
async def test_an_unknown_field_is_a_422(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    r = await client.patch(f"/api/v1/runbooks/{plan['id']}", headers=auth_headers, json={"state": "complete"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_another_tenant_sees_nothing(client, auth_headers, db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    task = await _task(client, auth_headers, plan["id"], "T")
    other_tenant, other_user = await second_tenant_factory()
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"username": other_user.username, "password": "password123",
                                                      "tenant_slug": other_tenant.slug})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"/api/v1/runbooks/{plan['id']}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/runbook-tasks/{task['id']}/events", headers=other)).status_code == 404
    assert (await client.post(f"/api/v1/runbook-tasks/{task['id']}/transition", headers=other,
                              json={"to_status": "in_progress"})).status_code == 404


@pytest.mark.asyncio
async def test_history_names_an_actor_from_outside_the_tenant(client, auth_headers, db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    task = await _task(client, auth_headers, plan["id"], "T")
    await client.post(f"/api/v1/runbook-tasks/{task['id']}/transition", headers=auth_headers, json={"to_status": "in_progress"})
    other_tenant, other_user = await second_tenant_factory()
    from sqlalchemy import update
    from app.db.models.runbook import RunbookTaskEvent
    await db_session.execute(update(RunbookTaskEvent).values(by_user_id=other_user.id))
    await db_session.commit()
    events = (await client.get(f"/api/v1/runbook-tasks/{task['id']}/events", headers=auth_headers)).json()
    assert events[0]["by_username"] == other_user.username


@pytest.mark.asyncio
async def test_a_system_that_left_the_release_still_renders_by_name(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    api = await make_system(db_session, test_tenant.id, "Legacy API")
    rs = await attach_system(db_session, release, api)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    await _task(client, auth_headers, plan["id"], "Deploy", system_id=api.id)
    await db_session.delete(rs)
    await db_session.commit()
    t = (await client.get(f"/api/v1/runbooks/{plan['id']}", headers=auth_headers)).json()["tasks"][0]
    assert t["system_name"] == "Legacy API" and t["system_on_release"] is False
```

- [ ] **Step 2: Write the guard test**

`backend/tests/test_c5a_refuses_only_within_runbook.py`:

```python
"""C5a REFUSES ONLY WRITES TO ITS OWN RUNBOOK RECORDS.

A runbook — however incomplete, failed or out of order — changes nothing
anywhere else: the release's readiness verdict is byte-identical with and
without one, the release still transitions, and no module outside the runbook
router and /me/work so much as imports a runbook service.

Proved non-vacuous (record in the commit): adding
`from app.services import runbook_service` to release_readiness_service makes
test_nothing_outside_the_runbook_imports_it fail; and appending a blocker for
an unfinished runbook inside evaluate() makes
test_readiness_is_identical_with_and_without_a_runbook fail.

C5b WILL deliberately amend exactly one test here when it folds runbook
findings into readiness — the way C6 amended test_pir_records_never_refuses.
"""
import pathlib
import re
from datetime import datetime, timezone

import pytest

from app.services import release_readiness_service
from tests.runbook_helpers import link, make_plan, make_release, make_task

ALLOWED_IMPORTERS = {
    "app/api/v1/runbooks.py",
    "app/services/my_work_service.py",
    "app/services/runbook_service.py",
    "app/services/runbook_execution_service.py",
    "app/services/runbook_view_service.py",
    "app/services/runbook_schedule_service.py",
}


def test_nothing_outside_the_runbook_imports_it():
    root = pathlib.Path(__file__).resolve().parents[1]
    pattern = re.compile(r"runbook_(service|execution_service|view_service|schedule_service)")
    offenders = []
    for path in (root / "app").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in ALLOWED_IMPORTERS or "/migrations/" in rel:
            continue
        if pattern.search(path.read_text()):
            offenders.append(rel)
    assert offenders == []


@pytest.mark.asyncio
async def test_readiness_is_identical_with_and_without_a_runbook(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    before = await release_readiness_service.evaluate(db_session, release.id, test_tenant.id, now)
    plan = await make_plan(db_session, release, test_environment, anchor=datetime(2026, 10, 1, tzinfo=timezone.utc))
    a = await make_task(db_session, plan, "Failed deploy", status="failed")
    b = await make_task(db_session, plan, "Blocked tests")
    await link(db_session, b, a)
    await db_session.commit()
    after = await release_readiness_service.evaluate(db_session, release.id, test_tenant.id, now)
    assert after.model_dump() == before.model_dump()


@pytest.mark.asyncio
async def test_a_release_with_a_failed_runbook_still_transitions(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=datetime(2026, 10, 1, tzinfo=timezone.utc))
    await make_task(db_session, plan, "Failed deploy", status="failed")
    await db_session.commit()
    allowed = (await client.get(f"/api/v1/releases/{release.id}/allowed-transitions", headers=auth_headers))
    assert allowed.status_code == 200, allowed.text
    targets = [t["to_state"] for t in allowed.json()]
    assert targets, "the seeded Major template offers at least one transition from draft"
    r = await client.post(f"/api/v1/releases/{release.id}/transition", headers=auth_headers,
                          json={"to_state": targets[0]})
    assert r.status_code == 200, r.text
```

Before running, confirm the release transition routes: `grep -n "allowed-transitions\|/transition" app/api/v1/releases.py` and the request body key (`to_state` or similar) — adjust the two calls to match what the router actually declares. If the first allowed target has `required_fields`, pick a target without them (inspect `allowed.json()`).

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_runbook_api.py tests/test_c5a_refuses_only_within_runbook.py -q`
Expected: FAIL — 404s on every `/runbooks` route (router not mounted). `test_nothing_outside…` and `test_readiness_is_identical…` may already pass; that is expected — they guard an absence.

- [ ] **Step 4: Append the read schemas** to `backend/app/api/v1/schemas/runbook.py`

```python
class RunbookPlanRead(BaseModel):
    id: int
    release_id: int
    environment_id: int
    environment_name: Optional[str]
    name: str
    anchor_start_at: datetime
    deploy_pattern: Optional[str]
    notes: Optional[str]
    state: str


class RunbookTaskRead(BaseModel):
    id: int
    name: str
    description: Optional[str]
    kind: str
    team_group_id: Optional[int]
    team_name: Optional[str]
    system_id: Optional[int]
    system_name: Optional[str]
    system_on_release: bool
    duration_minutes: int
    fixed_start_at: Optional[datetime]
    status: str
    actual_started_at: Optional[datetime]
    actual_finished_at: Optional[datetime]
    sort_order: int
    predecessor_ids: list[int]
    planned_start: datetime
    planned_finish: datetime
    forecast_start: datetime
    forecast_finish: datetime
    late_start: bool
    overrunning: bool
    slipped_past_fixed_start: bool
    blocked: bool
    critical: bool
    allowed_transitions: list[str]


class RunbookRead(BaseModel):
    plan: RunbookPlanRead
    planned_end: datetime
    forecast_end: datetime
    slip_minutes: int
    tasks: list[RunbookTaskRead]


class RunbookTaskEventRead(BaseModel):
    id: int
    from_status: str
    to_status: str
    at: datetime
    recorded_at: datetime
    by_username: Optional[str]
    note: Optional[str]
```

- [ ] **Step 5: Write the view service**

`backend/app/services/runbook_view_service.py`:

```python
"""The composite runbook read: plan + tasks + edges + the computed schedule +
rendered names + per-task allowed_transitions for the caller. The UI renders
only what this returns and never re-derives a rule."""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.runbook import RunbookPlanRead, RunbookRead, RunbookTaskRead
from app.db.models.release_system import ReleaseSystem
from app.db.models.runbook import RunbookPlan, RunbookTask
from app.db.models.system import System
from app.services import environment_service, runbook_execution_service, runbook_service, user_group_service
from app.services.runbook_schedule_service import TaskInput, compute, plan_state


def _inputs(tasks: list[RunbookTask]) -> list[TaskInput]:
    return [TaskInput(id=t.id, duration_minutes=t.duration_minutes, fixed_start_at=t.fixed_start_at,
                      status=t.status, actual_started_at=t.actual_started_at,
                      actual_finished_at=t.actual_finished_at) for t in tasks]


async def _system_names(db, ids: set, tenant_id: int) -> dict[int, str]:
    """Read-rendering: does NOT filter deleted_at — an archived system still names itself."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(System.id, System.name).where(
        System.id.in_(ids), System.tenant_id == tenant_id))).all()
    return {i: n for i, n in rows}


async def plan_reads(db: AsyncSession, plans: list[RunbookPlan], tenant_id: int) -> list[RunbookPlanRead]:
    env_names = await environment_service.get_environment_names(db, {p.environment_id for p in plans}, tenant_id)
    ids = [p.id for p in plans]
    statuses: dict[int, list[str]] = defaultdict(list)
    if ids:
        rows = (await db.execute(select(RunbookTask.plan_id, RunbookTask.status).where(
            RunbookTask.plan_id.in_(ids), RunbookTask.tenant_id == tenant_id,
            RunbookTask.deleted_at.is_(None)))).all()
        for plan_id, st in rows:
            statuses[plan_id].append(st)
    return [RunbookPlanRead(id=p.id, release_id=p.release_id, environment_id=p.environment_id,
                            environment_name=env_names.get(p.environment_id), name=p.name,
                            anchor_start_at=p.anchor_start_at, deploy_pattern=p.deploy_pattern,
                            notes=p.notes, state=plan_state(statuses[p.id])) for p in plans]


async def read(db: AsyncSession, plan: RunbookPlan, tenant_id: int, user, now: datetime) -> RunbookRead:
    tasks = await runbook_service.live_tasks(db, plan.id, tenant_id)
    edges = await runbook_service.live_edges(db, plan.id, tenant_id)
    schedule = compute(plan.anchor_start_at, _inputs(tasks), edges, now)
    by_id = {t.id: t for t in tasks}
    preds: dict[int, list[int]] = defaultdict(list)
    succs: dict[int, list[int]] = defaultdict(list)
    for s, p in edges:
        preds[s].append(p)
        succs[p].append(s)

    team_names = await user_group_service.get_group_names(db, {t.team_group_id for t in tasks})
    system_names = await _system_names(db, {t.system_id for t in tasks}, tenant_id)
    on_release = set((await db.execute(select(ReleaseSystem.system_id).where(
        ReleaseSystem.release_id == plan.release_id, ReleaseSystem.tenant_id == tenant_id))).scalars().all())
    manager = runbook_execution_service.is_manager(user)
    my_teams = await runbook_execution_service.team_ids_for(
        db, user.id, tenant_id, {t.team_group_id for t in tasks})
    [plan_read] = await plan_reads(db, [plan], tenant_id)

    out = []
    for t in tasks:
        sch = schedule.tasks[t.id]
        out.append(RunbookTaskRead(
            id=t.id, name=t.name, description=t.description, kind=t.kind,
            team_group_id=t.team_group_id, team_name=team_names.get(t.team_group_id),
            system_id=t.system_id, system_name=system_names.get(t.system_id),
            system_on_release=t.system_id is None or t.system_id in on_release,
            duration_minutes=t.duration_minutes, fixed_start_at=t.fixed_start_at, status=t.status,
            actual_started_at=t.actual_started_at, actual_finished_at=t.actual_finished_at,
            sort_order=t.sort_order, predecessor_ids=sorted(preds[t.id]),
            planned_start=sch.planned_start, planned_finish=sch.planned_finish,
            forecast_start=sch.forecast_start, forecast_finish=sch.forecast_finish,
            late_start=sch.late_start, overrunning=sch.overrunning,
            slipped_past_fixed_start=sch.slipped_past_fixed_start, blocked=sch.blocked, critical=sch.critical,
            allowed_transitions=runbook_execution_service.allowed_transitions(
                t.status, [by_id[p].status for p in preds[t.id]], [by_id[s].status for s in succs[t.id]],
                manager=manager, team_member=t.team_group_id in my_teams),
        ))
    out.sort(key=lambda r: (r.planned_start, r.sort_order, r.id))
    return RunbookRead(plan=plan_read, planned_end=schedule.planned_end, forecast_end=schedule.forecast_end,
                       slip_minutes=schedule.slip_minutes, tasks=out)
```

Check `get_group_names` tolerates a `None` in the set (`grep -n "def get_group_names" -A15 app/services/user_group_service.py`); if it does not filter `None`, pass `{t.team_group_id for t in tasks if t.team_group_id}`.

- [ ] **Step 6: Write the router**

`backend/app/api/v1/runbooks.py`:

```python
"""Phase 9 C5a — cutover runbook routes. Thin over the runbook services.

Mounted in main.py under /api/v1. Paths are /releases/{id}/runbooks,
/runbooks/{id}… and /runbook-tasks/{id}… — no literal segment follows a
catch-all in any router it shares a prefix with.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.runbook import (
    PredecessorsUpdate, RunbookPlanCreate, RunbookPlanRead, RunbookPlanUpdate, RunbookRead,
    RunbookTaskCreate, RunbookTaskEventRead, RunbookTaskRead, RunbookTaskUpdate, TransitionRequest,
)
from app.core.pagination import Page, pagination, set_total_count
from app.core.security import Role, get_current_user, require_role
from app.db.base import get_db
from app.services import (
    gate_waiver_service, release_service, runbook_execution_service, runbook_service, runbook_view_service,
)

router = APIRouter(tags=["Runbooks"])
_manager = require_role(Role.RELEASE_MANAGER)   # Admin and master admin pass too


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _read(db, plan, user) -> RunbookRead:
    return await runbook_view_service.read(db, plan, user.active_tenant_id, user, _now())


@router.get("/releases/{release_id}/runbooks", response_model=list[RunbookPlanRead])
async def list_runbooks(release_id: int, response: Response, page: Page = Depends(pagination()),
                        db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id
    await release_service.get_release(db, release_id, tenant_id)
    plans, total = await runbook_service.list_plans(db, release_id, tenant_id, page)
    set_total_count(response, total)
    return await runbook_view_service.plan_reads(db, plans, tenant_id)


@router.post("/releases/{release_id}/runbooks", response_model=RunbookRead, status_code=status.HTTP_201_CREATED)
async def create_runbook(release_id: int, data: RunbookPlanCreate, db: AsyncSession = Depends(get_db),
                         current_user=Depends(_manager)):
    plan = await runbook_service.create_plan(db, release_id, current_user.active_tenant_id, data)
    return await _read(db, plan, current_user)


@router.get("/runbooks/{plan_id}", response_model=RunbookRead)
async def get_runbook(plan_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    plan = await runbook_service.get_plan(db, plan_id, current_user.active_tenant_id)
    return await _read(db, plan, current_user)


@router.patch("/runbooks/{plan_id}", response_model=RunbookRead)
async def update_runbook(plan_id: int, data: RunbookPlanUpdate, db: AsyncSession = Depends(get_db),
                         current_user=Depends(_manager)):
    plan = await runbook_service.get_plan(db, plan_id, current_user.active_tenant_id)
    await runbook_service.update_plan(db, plan, data)
    return await _read(db, plan, current_user)


@router.delete("/runbooks/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_runbook(plan_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    plan = await runbook_service.get_plan(db, plan_id, tenant_id)
    await runbook_service.delete_plan(db, plan, tenant_id)


@router.post("/runbooks/{plan_id}/tasks", response_model=RunbookTaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(plan_id: int, data: RunbookTaskCreate, db: AsyncSession = Depends(get_db),
                      current_user=Depends(_manager)):
    """Returns the new task's row from the composite (schedule and
    allowed_transitions included), not a second task shape."""
    tenant_id = current_user.active_tenant_id
    plan = await runbook_service.get_plan(db, plan_id, tenant_id)
    task = await runbook_service.create_task(db, plan, tenant_id, data)
    composite = await _read(db, plan, current_user)
    return next(t for t in composite.tasks if t.id == task.id)


@router.patch("/runbook-tasks/{task_id}", response_model=RunbookRead)
async def update_task(task_id: int, data: RunbookTaskUpdate, db: AsyncSession = Depends(get_db),
                      current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    task, plan = await runbook_service.get_task(db, task_id, tenant_id)
    await runbook_service.update_task(db, task, plan, tenant_id, data)
    return await _read(db, plan, current_user)


@router.delete("/runbook-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    task, _ = await runbook_service.get_task(db, task_id, tenant_id)
    await runbook_service.delete_task(db, task, tenant_id)


@router.put("/runbook-tasks/{task_id}/predecessors", response_model=RunbookRead)
async def set_predecessors(task_id: int, data: PredecessorsUpdate, db: AsyncSession = Depends(get_db),
                           current_user=Depends(_manager)):
    tenant_id = current_user.active_tenant_id
    task, plan = await runbook_service.get_task(db, task_id, tenant_id)
    await runbook_service.set_predecessors(db, task, plan, tenant_id, data.predecessor_ids)
    return await _read(db, plan, current_user)


@router.post("/runbook-tasks/{task_id}/transition", response_model=RunbookRead)
async def transition_task(task_id: int, data: TransitionRequest, db: AsyncSession = Depends(get_db),
                          current_user=Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id
    task, plan = await runbook_service.get_task(db, task_id, tenant_id)
    now = _now()
    await runbook_execution_service.transition(db, task, plan, tenant_id, current_user, data, now)
    return await runbook_view_service.read(db, plan, tenant_id, current_user, now)


@router.get("/runbook-tasks/{task_id}/events", response_model=list[RunbookTaskEventRead])
async def task_events(task_id: int, response: Response, page: Page = Depends(pagination()),
                      db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    tenant_id = current_user.active_tenant_id
    await runbook_service.get_task(db, task_id, tenant_id)          # 404 across tenants
    rows, total = await runbook_execution_service.list_events(db, task_id, tenant_id, page)
    set_total_count(response, total)
    names = await gate_waiver_service.usernames_for(db, {r.by_user_id for r in rows if r.by_user_id})
    return [RunbookTaskEventRead(id=r.id, from_status=r.from_status, to_status=r.to_status, at=r.at,
                                 recorded_at=r.recorded_at, by_username=names.get(r.by_user_id), note=r.note)
            for r in rows]
```

In `backend/app/main.py`, next to the closeout router's `include_router` (grep `release_closeout`), add:

```python
from app.api.v1 import runbooks as runbooks_router
app.include_router(runbooks_router.router, prefix="/api/v1")
```

(follow the file's existing import grouping; put the import with the other `app.api.v1` router imports).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_runbook_api.py tests/test_c5a_refuses_only_within_runbook.py -q`
Expected: PASS

- [ ] **Step 8: Prove the guard non-vacuous** — (a) add `from app.services import runbook_service  # noqa` to `app/services/release_readiness_service.py`; `test_nothing_outside_the_runbook_imports_it` must FAIL; revert. (b) In `release_readiness_service.evaluate`, temporarily append a blocker when any `RunbookTask` for the release is not `done`; `test_readiness_is_identical…` must FAIL; revert. Note both in the commit message.

- [ ] **Step 9: Run every runbook test on PostgreSQL** (alone — no other PG run in flight)

Run: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/test_runbook_*.py tests/test_c5a_refuses_only_within_runbook.py -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/runbook_view_service.py backend/app/api/v1/runbooks.py \
  backend/app/api/v1/schemas/runbook.py backend/app/main.py \
  backend/tests/test_runbook_api.py backend/tests/test_c5a_refuses_only_within_runbook.py
git commit -m "feat(c5a): runbook routes, composite read, and the refuses-only-within-runbook guard"
```

---

### Task 7: The `/me/work` queue

**Files:**
- Modify: `backend/app/services/runbook_execution_service.py` (append `ready_clause`, `ready_queue`)
- Modify: `backend/app/services/my_work_service.py` (queue + docstring bullet + builders dict)
- Modify: `backend/app/api/v1/schemas/my_work.py` (comment: seven queues, add `runbook_tasks`)
- Modify: `backend/tests/test_my_work_service.py:46-49,444` (key sets)
- Test: `backend/tests/test_runbook_my_work.py`

**Interfaces:**
- Produces: `ready_clause()` — a SQLAlchemy boolean over `RunbookTask`: `not_started`, live, and no live unsatisfied predecessor; `async ready_queue(db, tenant_id, user_id, page) -> tuple[list[Row(task_id, task_name, plan_id, release_id, release_name, environment_name)], int]`; queue key `"runbook_tasks"`; `WorkItem.url = f"/releases/{release_id}?tab=runbook&plan={plan_id}"`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_runbook_my_work.py`:

```python
"""'Runbook tasks ready to start': the SQL predicate's own answers, and its
agreement with the composite read's allowed_transitions. Agreement alone would
prove only that two copies match, so each case is pinned independently too."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.pagination import Page
from app.services import runbook_execution_service as ex, runbook_view_service
from tests.factories import add_group_member, ensure_user, ensure_user_group
from tests.runbook_helpers import link, make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
async def setup(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id, name="Payments 4.2")
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    mine = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    theirs = await ensure_user_group(db_session, test_tenant.id, name="Theirs")
    me = await ensure_user(db_session, test_tenant.id, username="queue-me", role="Developer")
    me.active_tenant_id = test_tenant.id
    await add_group_member(db_session, mine, me)
    done = await make_task(db_session, plan, "done pred", status="done")
    skipped = await make_task(db_session, plan, "skipped pred", status="skipped")
    failed = await make_task(db_session, plan, "failed pred", status="failed")
    gone = await make_task(db_session, plan, "deleted pred")
    gone.deleted_at = ANCHOR
    tasks = {
        "ready_no_preds": await make_task(db_session, plan, "ready_no_preds", team=mine),
        "ready_done_skipped": await make_task(db_session, plan, "ready_done_skipped", team=mine),
        "blocked_by_failed": await make_task(db_session, plan, "blocked_by_failed", team=mine),
        "ready_deleted_pred": await make_task(db_session, plan, "ready_deleted_pred", team=mine),
        "already_running": await make_task(db_session, plan, "already_running", team=mine, status="in_progress"),
        "other_team": await make_task(db_session, plan, "other_team", team=theirs),
    }
    await link(db_session, tasks["ready_done_skipped"], done, skipped)
    await link(db_session, tasks["blocked_by_failed"], failed)
    await link(db_session, tasks["ready_deleted_pred"], gone)
    await db_session.flush()
    return dict(plan=plan, me=me, tasks=tasks, tenant_id=test_tenant.id)


EXPECTED = {"ready_no_preds", "ready_done_skipped", "ready_deleted_pred"}


@pytest.mark.asyncio
async def test_the_queue_holds_exactly_my_teams_ready_tasks(db_session, setup):
    rows, total = await ex.ready_queue(db_session, setup["tenant_id"], setup["me"].id, Page(limit=50, offset=0))
    assert {r.task_name for r in rows} == EXPECTED and total == 3
    assert {r.release_name for r in rows} == {"Payments 4.2"}


@pytest.mark.asyncio
async def test_the_queue_agrees_with_allowed_transitions(db_session, setup):
    body = await runbook_view_service.read(db_session, setup["plan"], setup["tenant_id"], setup["me"],
                                           ANCHOR + timedelta(hours=1))
    startable = {t.name for t in body.tasks if "in_progress" in t.allowed_transitions}
    rows, _ = await ex.ready_queue(db_session, setup["tenant_id"], setup["me"].id, Page(limit=50, offset=0))
    assert startable == {r.task_name for r in rows} == EXPECTED


@pytest.mark.asyncio
async def test_the_queue_is_tenant_scoped(db_session, setup, second_tenant_factory):
    other_tenant, _ = await second_tenant_factory()
    rows, total = await ex.ready_queue(db_session, other_tenant.id, setup["me"].id, Page(limit=50, offset=0))
    assert rows == [] and total == 0


@pytest.mark.asyncio
async def test_a_deleted_plan_leaves_the_queue(db_session, setup):
    setup["plan"].deleted_at = ANCHOR
    await db_session.flush()
    _, total = await ex.ready_queue(db_session, setup["tenant_id"], setup["me"].id, Page(limit=50, offset=0))
    assert total == 0


@pytest.mark.asyncio
async def test_me_work_serves_the_queue(client, db_session, test_tenant, setup):
    from tests.runbook_helpers import login_headers
    user, headers = await login_headers(client, db_session, test_tenant, "queue-http", "Developer")
    from app.db.models.user_group import UserGroup
    from sqlalchemy import select
    mine = (await db_session.execute(select(UserGroup).where(UserGroup.name == "Mine"))).scalar_one()
    await add_group_member(db_session, mine, user)
    await db_session.commit()
    body = (await client.get("/api/v1/me/work", headers=headers)).json()
    q = body["queues"]["runbook_tasks"]
    assert q["failed"] is False and q["count"] == 3
    assert all(i["url"].startswith("/releases/") and "tab=runbook" in i["url"] for i in q["items"])
```

Confirm the route is `/api/v1/me/work` with `grep -n "@router" app/api/v1/me.py`; adjust if it differs.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runbook_my_work.py -q`
Expected: FAIL — `AttributeError: module … has no attribute 'ready_queue'`

- [ ] **Step 3: Append to `runbook_execution_service.py`**

Add imports: `from sqlalchemy import and_, exists`, `from sqlalchemy.orm import aliased`, `from app.core.pagination import fetch_page_rows`, `from app.db.models.environment import Environment`, `from app.db.models.release import Release`.

```python
def ready_clause():
    """A task is READY when it is not_started, live, and no LIVE predecessor is
    unsatisfied. The SQL twin of allowed_transitions' predecessor rule —
    test_runbook_my_work.py holds the two equal. A soft-deleted predecessor
    counts as absent, as it does in runbook_service.live_edges."""
    pred = aliased(RunbookTask)
    return and_(
        RunbookTask.status == "not_started",
        RunbookTask.deleted_at.is_(None),
        ~exists().where(
            RunbookTaskDependency.task_id == RunbookTask.id,
            RunbookTaskDependency.predecessor_task_id == pred.id,
            pred.deleted_at.is_(None),
            pred.status.not_in(tuple(SATISFIED_STATUSES)),
        ),
    )


async def ready_queue(db: AsyncSession, tenant_id: int, user_id: int, page: Optional[Page]):
    """Tasks the user's teams could start now. Everyone — Admins included — sees
    only their OWN teams' tasks: this is "waiting on me", not a tenant list."""
    query = (
        select(RunbookTask.id.label("task_id"), RunbookTask.name.label("task_name"),
               RunbookPlan.id.label("plan_id"), Release.id.label("release_id"),
               Release.name.label("release_name"), Environment.name.label("environment_name"))
        .join(RunbookPlan, RunbookPlan.id == RunbookTask.plan_id)
        .join(Release, Release.id == RunbookPlan.release_id)
        .join(Environment, Environment.id == RunbookPlan.environment_id)
        .join(UserGroupMember, and_(UserGroupMember.group_id == RunbookTask.team_group_id,
                                    UserGroupMember.user_id == user_id,
                                    UserGroupMember.tenant_id == tenant_id))
        .where(RunbookTask.tenant_id == tenant_id, RunbookPlan.deleted_at.is_(None),
               Release.deleted_at.is_(None), ready_clause())
        .order_by(RunbookPlan.anchor_start_at, RunbookTask.id)
    )
    return await fetch_page_rows(db, query, page)
```

- [ ] **Step 4: Add the queue to `my_work_service.py`**

Add `runbook_execution_service` to the `from app.services import (...)` block. Add a docstring bullet after the incidents bullet:

```
- `runbook_execution_service.ready_queue(..., user_id)` — runbook tasks of
  the caller's own teams whose predecessors are all done or skipped, via
  `ready_clause`, the SQL twin of the composite read's allowed_transitions.
  Narrowed by membership for everyone, Admins included.
```

Change the module's first line to `"""`/my-work` — seven "waiting on me" queues, composed under one clock.` Add after `_hypercare_queue`:

```python
async def _runbook_tasks_queue(
    db: AsyncSession, *, tenant_id: int, user: User, now: datetime
) -> QueueResult:
    """Runbook tasks my teams can start now. No deadline column: the planned
    start is computed per plan, never stored, so `due` stays empty."""
    rows, total = await runbook_execution_service.ready_queue(
        db, tenant_id, user.id, Page(limit=ITEM_CAP, offset=0))
    items = [
        WorkItem(id=r.task_id, title=r.task_name, subtitle=f"{r.release_name} · {r.environment_name}",
                 url=f"/releases/{r.release_id}?tab=runbook&plan={r.plan_id}")
        for r in rows
    ]
    return QueueResult(count=total, items=items)
```

In `build()`'s builders dict add `"runbook_tasks": _runbook_tasks_queue,` after `"hypercare"`. In `schemas/my_work.py` update the `queues` comment to list `runbook_tasks` and say seven. In `tests/test_my_work_service.py` add `"runbook_tasks"` to the set at line ~48 and to the tuple at line ~444.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_runbook_my_work.py tests/test_my_work_service.py tests/test_me_work_matches_worklists.py -q`
Expected: PASS

- [ ] **Step 6: Mutation** — delete `pred.deleted_at.is_(None),` from `ready_clause`: `test_the_queue_holds_exactly…` must FAIL (`ready_deleted_pred` vanishes). Restore.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/runbook_execution_service.py backend/app/services/my_work_service.py \
  backend/app/api/v1/schemas/my_work.py backend/tests/test_my_work_service.py backend/tests/test_runbook_my_work.py
git commit -m "feat(c5a): /me/work runbook-tasks queue, held equal to allowed_transitions"
```

---

### Task 8: Frontend types, service and slice

**Files:**
- Create: `frontend/src/types/runbook.ts`, `frontend/src/services/runbookService.ts`, `frontend/src/store/runbookSlice.ts`
- Modify: `frontend/src/store/index.ts` (register `runbook: runbookReducer`)
- Test: `frontend/src/store/__tests__/runbookSlice.test.ts`

**Interfaces:**
- Produces (types): `TaskStatus`, `TaskKind`, `DeployPattern`, `RunbookPlanRead`, `RunbookTaskRead`, `RunbookRead`, `RunbookTaskEventRead`, `RunbookPlanCreate`, `RunbookPlanUpdate`, `RunbookTaskCreate`, `RunbookTaskUpdate`, `TransitionRequest` — mirroring `backend/app/api/v1/schemas/runbook.py` exactly.
- Produces (service): `runbookService.{listForRelease(releaseId), get(planId), create(releaseId, body), update(planId, body), remove(planId), createTask(planId, body), updateTask(taskId, body), removeTask(taskId), setPredecessors(taskId, ids), transition(taskId, body), events(taskId)}`.
- Produces (slice `runbook`): state `{ plansByRelease: Record<number, RunbookPlanRead[]>, byPlan: Record<number, RunbookRead>, loading: boolean, error: string|null }`; thunks `fetchRunbooks(releaseId)`, `fetchRunbook(planId)`, `createRunbook({releaseId, body})`, `updateRunbook({planId, body})`, `deleteRunbook({releaseId, planId})`, `createTask({planId, body})`, `updateTask({planId, taskId, body})`, `deleteTask({planId, taskId})`, `setPredecessors({planId, taskId, ids})`, `transitionTask({planId, taskId, body})`. Every write thunk resolves to the fresh `RunbookRead` (re-fetching where the route returns none), and rejects with `formatApiError`'s string.

- [ ] **Step 1: Write the failing slice test**

`frontend/src/store/__tests__/runbookSlice.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { AxiosError, AxiosHeaders } from 'axios';
import runbookReducer, { fetchRunbook, transitionTask, createTask } from '../runbookSlice';
import { runbookService } from '../../services/runbookService';
import type { RunbookRead } from '../../types/runbook';

vi.mock('../../services/runbookService', () => ({
  runbookService: {
    listForRelease: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    createTask: vi.fn(), updateTask: vi.fn(), removeTask: vi.fn(), setPredecessors: vi.fn(),
    transition: vi.fn(), events: vi.fn(),
  },
}));

const composite = (state: string): RunbookRead => ({
  plan: { id: 5, release_id: 7, environment_id: 2, environment_name: 'prod', name: 'Cutover',
          anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: null, notes: null, state },
  planned_end: '2026-10-01T19:00:00Z', forecast_end: '2026-10-01T19:00:00Z', slip_minutes: 0, tasks: [],
});

function conflict(detail: string) {
  return new AxiosError('Request failed with status code 409', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 409, statusText: 'Conflict', headers: {}, config: { headers: new AxiosHeaders() }, data: { detail },
  });
}

const makeStore = () => configureStore({ reducer: { runbook: runbookReducer } });

describe('runbookSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores a fetched composite by plan id', async () => {
    vi.mocked(runbookService.get).mockResolvedValue(composite('not_started'));
    const store = makeStore();
    await store.dispatch(fetchRunbook(5));
    expect(store.getState().runbook.byPlan[5].plan.state).toBe('not_started');
  });

  it('a transition stores the composite the server returns', async () => {
    vi.mocked(runbookService.transition).mockResolvedValue(composite('in_progress'));
    const store = makeStore();
    await store.dispatch(transitionTask({ planId: 5, taskId: 9, body: { to_status: 'in_progress' } }));
    expect(store.getState().runbook.byPlan[5].plan.state).toBe('in_progress');
  });

  it('a refused transition rejects with the server detail, not the HTTP status', async () => {
    vi.mocked(runbookService.transition).mockRejectedValue(conflict("'Smoke' cannot start until these are done or skipped: Deploy API (not_started)"));
    const store = makeStore();
    const result = await store.dispatch(transitionTask({ planId: 5, taskId: 9, body: { to_status: 'in_progress' } }));
    expect(result.payload).toContain('Deploy API (not_started)');
    expect(result.payload).not.toContain('status code');
  });

  it('creating a task re-reads the composite', async () => {
    vi.mocked(runbookService.createTask).mockResolvedValue({ id: 11 } as never);
    vi.mocked(runbookService.get).mockResolvedValue(composite('not_started'));
    const store = makeStore();
    await store.dispatch(createTask({ planId: 5, body: { name: 'T', duration_minutes: 5 } }));
    expect(runbookService.get).toHaveBeenCalledWith(5);
    expect(store.getState().runbook.byPlan[5]).toBeDefined();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/store/__tests__/runbookSlice.test.ts`
Expected: FAIL — cannot resolve `../runbookSlice`.

- [ ] **Step 3: Write types, service and slice**

`frontend/src/types/runbook.ts`:

```ts
// Phase 9 C5a — mirrors backend/app/api/v1/schemas/runbook.py exactly.
export type TaskStatus = 'not_started' | 'in_progress' | 'done' | 'failed' | 'skipped';
export type TaskKind = 'task' | 'check' | 'deploy' | 'verification' | 'ramp';
export type DeployPattern = 'rolling' | 'blue_green' | 'canary' | 'big_bang' | 'other';
export type PlanState = 'not_started' | 'in_progress' | 'complete' | 'failed';

export interface RunbookPlanRead {
  id: number;
  release_id: number;
  environment_id: number;
  environment_name: string | null;
  name: string;
  anchor_start_at: string;
  deploy_pattern: DeployPattern | null;
  notes: string | null;
  state: PlanState;
}

export interface RunbookTaskRead {
  id: number;
  name: string;
  description: string | null;
  kind: TaskKind;
  team_group_id: number | null;
  team_name: string | null;
  system_id: number | null;
  system_name: string | null;
  system_on_release: boolean;
  duration_minutes: number;
  fixed_start_at: string | null;
  status: TaskStatus;
  actual_started_at: string | null;
  actual_finished_at: string | null;
  sort_order: number;
  predecessor_ids: number[];
  planned_start: string;
  planned_finish: string;
  forecast_start: string;
  forecast_finish: string;
  late_start: boolean;
  overrunning: boolean;
  slipped_past_fixed_start: boolean;
  blocked: boolean;
  critical: boolean;
  allowed_transitions: TaskStatus[];
}

export interface RunbookRead {
  plan: RunbookPlanRead;
  planned_end: string;
  forecast_end: string;
  slip_minutes: number;
  tasks: RunbookTaskRead[];
}

export interface RunbookTaskEventRead {
  id: number;
  from_status: TaskStatus;
  to_status: TaskStatus;
  at: string;
  recorded_at: string;
  by_username: string | null;
  note: string | null;
}

export interface RunbookPlanCreate {
  environment_id: number;
  name: string;
  anchor_start_at: string;
  deploy_pattern?: DeployPattern | null;
  notes?: string | null;
}
export type RunbookPlanUpdate = Partial<Omit<RunbookPlanCreate, 'environment_id'>>;

export interface RunbookTaskCreate {
  name: string;
  description?: string | null;
  team_group_id?: number | null;
  system_id?: number | null;
  kind?: TaskKind;
  duration_minutes: number;
  fixed_start_at?: string | null;
  sort_order?: number;
  predecessor_ids?: number[];
}
export type RunbookTaskUpdate = Partial<Omit<RunbookTaskCreate, 'predecessor_ids'>>;

export interface TransitionRequest {
  to_status: TaskStatus;
  at?: string | null;
  reason?: string | null;
}
```

`frontend/src/services/runbookService.ts`:

```ts
import api from './api';
import type {
  RunbookPlanCreate, RunbookPlanRead, RunbookPlanUpdate, RunbookRead, RunbookTaskCreate,
  RunbookTaskEventRead, RunbookTaskRead, RunbookTaskUpdate, TransitionRequest,
} from '../types/runbook';

export const runbookService = {
  listForRelease: (releaseId: number): Promise<RunbookPlanRead[]> =>
    api.get(`/releases/${releaseId}/runbooks`, { params: { limit: 100 } }).then((r) => r.data),
  get: (planId: number): Promise<RunbookRead> => api.get(`/runbooks/${planId}`).then((r) => r.data),
  create: (releaseId: number, body: RunbookPlanCreate): Promise<RunbookRead> =>
    api.post(`/releases/${releaseId}/runbooks`, body).then((r) => r.data),
  update: (planId: number, body: RunbookPlanUpdate): Promise<RunbookRead> =>
    api.patch(`/runbooks/${planId}`, body).then((r) => r.data),
  remove: (planId: number): Promise<void> => api.delete(`/runbooks/${planId}`).then(() => undefined),
  createTask: (planId: number, body: RunbookTaskCreate): Promise<RunbookTaskRead> =>
    api.post(`/runbooks/${planId}/tasks`, body).then((r) => r.data),
  updateTask: (taskId: number, body: RunbookTaskUpdate): Promise<RunbookRead> =>
    api.patch(`/runbook-tasks/${taskId}`, body).then((r) => r.data),
  removeTask: (taskId: number): Promise<void> => api.delete(`/runbook-tasks/${taskId}`).then(() => undefined),
  setPredecessors: (taskId: number, ids: number[]): Promise<RunbookRead> =>
    api.put(`/runbook-tasks/${taskId}/predecessors`, { predecessor_ids: ids }).then((r) => r.data),
  transition: (taskId: number, body: TransitionRequest): Promise<RunbookRead> =>
    api.post(`/runbook-tasks/${taskId}/transition`, body).then((r) => r.data),
  events: (taskId: number): Promise<RunbookTaskEventRead[]> =>
    api.get(`/runbook-tasks/${taskId}/events`, { params: { limit: 100 } }).then((r) => r.data),
};
```

`frontend/src/store/runbookSlice.ts`:

```ts
import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { runbookService } from '../services/runbookService';
import { formatApiError } from '../services/apiError';
import type {
  RunbookPlanCreate, RunbookPlanRead, RunbookPlanUpdate, RunbookRead, RunbookTaskCreate,
  RunbookTaskUpdate, TransitionRequest,
} from '../types/runbook';

interface RunbookState {
  plansByRelease: Record<number, RunbookPlanRead[]>;
  byPlan: Record<number, RunbookRead>;
  loading: boolean;
  error: string | null;
}
const initialState: RunbookState = { plansByRelease: {}, byPlan: {}, loading: false, error: null };
type Rejected = { rejectValue: string };

export const fetchRunbooks = createAsyncThunk<RunbookPlanRead[], number, Rejected>(
  'runbook/list', async (releaseId, { rejectWithValue }) => {
    try { return await runbookService.listForRelease(releaseId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to load runbooks')); }
  });

export const fetchRunbook = createAsyncThunk<RunbookRead, number, Rejected>(
  'runbook/get', async (planId, { rejectWithValue }) => {
    try { return await runbookService.get(planId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to load runbook')); }
  });

// Every write resolves to the composite the server computed — the tab never
// renders a local guess. Consumers read `result.payload` on rejection.
export const createRunbook = createAsyncThunk<RunbookRead, { releaseId: number; body: RunbookPlanCreate }, Rejected>(
  'runbook/create', async ({ releaseId, body }, { rejectWithValue }) => {
    try { return await runbookService.create(releaseId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to create runbook')); }
  });

export const updateRunbook = createAsyncThunk<RunbookRead, { planId: number; body: RunbookPlanUpdate }, Rejected>(
  'runbook/update', async ({ planId, body }, { rejectWithValue }) => {
    try { return await runbookService.update(planId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update runbook')); }
  });

export const deleteRunbook = createAsyncThunk<{ releaseId: number; planId: number }, { releaseId: number; planId: number }, Rejected>(
  'runbook/delete', async (arg, { rejectWithValue }) => {
    try { await runbookService.remove(arg.planId); return arg; }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to delete runbook')); }
  });

export const createTask = createAsyncThunk<RunbookRead, { planId: number; body: RunbookTaskCreate }, Rejected>(
  'runbook/createTask', async ({ planId, body }, { rejectWithValue }) => {
    try { await runbookService.createTask(planId, body); return await runbookService.get(planId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to add task')); }
  });

export const updateTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number; body: RunbookTaskUpdate }, Rejected>(
  'runbook/updateTask', async ({ taskId, body }, { rejectWithValue }) => {
    try { return await runbookService.updateTask(taskId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update task')); }
  });

export const deleteTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number }, Rejected>(
  'runbook/deleteTask', async ({ planId, taskId }, { rejectWithValue }) => {
    try { await runbookService.removeTask(taskId); return await runbookService.get(planId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to delete task')); }
  });

export const setPredecessors = createAsyncThunk<RunbookRead, { planId: number; taskId: number; ids: number[] }, Rejected>(
  'runbook/setPredecessors', async ({ taskId, ids }, { rejectWithValue }) => {
    try { return await runbookService.setPredecessors(taskId, ids); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update dependencies')); }
  });

export const transitionTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number; body: TransitionRequest }, Rejected>(
  'runbook/transition', async ({ taskId, body }, { rejectWithValue }) => {
    try { return await runbookService.transition(taskId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update task')); }
  });

const runbookSlice = createSlice({
  name: 'runbook',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchRunbooks.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchRunbooks.fulfilled, (s, a) => { s.loading = false; s.plansByRelease[a.meta.arg] = a.payload; });
    b.addCase(fetchRunbooks.rejected, (s, a) => { s.loading = false; s.error = a.payload ?? 'Failed to load runbooks'; });
    b.addCase(fetchRunbook.rejected, (s, a) => { s.error = a.payload ?? 'Failed to load runbook'; });
    b.addCase(deleteRunbook.fulfilled, (s, a) => {
      delete s.byPlan[a.payload.planId];
      s.plansByRelease[a.payload.releaseId] =
        (s.plansByRelease[a.payload.releaseId] ?? []).filter((p) => p.id !== a.payload.planId);
    });
    for (const t of [fetchRunbook, createRunbook, updateRunbook, createTask, updateTask, deleteTask,
                     setPredecessors, transitionTask]) {
      b.addCase(t.fulfilled, (s, a) => {
        const read = a.payload as RunbookRead;
        s.byPlan[read.plan.id] = read;
        const list = s.plansByRelease[read.plan.release_id];
        if (list) {
          const i = list.findIndex((p) => p.id === read.plan.id);
          if (i >= 0) list[i] = read.plan; else list.push(read.plan);
        }
      });
    }
  },
});
export default runbookSlice.reducer;
```

In `frontend/src/store/index.ts`: `import runbookReducer from './runbookSlice';` beside `closeoutReducer`, and `runbook: runbookReducer,` beside `closeout: closeoutReducer,`.

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/store/__tests__/runbookSlice.test.ts && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/runbook.ts frontend/src/services/runbookService.ts frontend/src/store/runbookSlice.ts \
  frontend/src/store/index.ts frontend/src/store/__tests__/runbookSlice.test.ts
git commit -m "feat(c5a): runbook frontend types, service and slice"
```

---

### Task 9: The Runbook tab — switcher, header, task table, live refresh

**Files:**
- Create: `frontend/src/components/releases/runbook/labels.ts`, `RunbookTab.tsx`, `RunbookTaskTable.tsx`
- Modify: `frontend/src/pages/releases/ReleaseDetail.tsx` (doc comment, `RELEASE_TABS`, render line)
- Test: `frontend/src/components/releases/runbook/__tests__/runbookTab.test.tsx`

**Interfaces:**
- Consumes: slice thunks from Task 8; `DataTable` (`storageKey`, `userId`, `emptyMessage`, `disableVirtualization`, `autoHeight`); `formatBookingDateTime`; `s.auth.user` (`{ id, role, is_master_admin }`).
- Produces: `<RunbookTab releaseId={number} />`; `<RunbookTaskTable read={RunbookRead} canEdit={boolean} onAction={(task, to) => void} onEdit={(task) => void} />`; `labels.ts` exports `STATUS_LABEL`, `STATUS_COLOR`, `KIND_LABEL`, `PATTERN_LABEL`, `ACTION_LABEL: Record<TaskStatus, (from: TaskStatus) => string>`, `FLAG_TEXT`.
- The tab reads the selected plan from `?plan=` (via `useSearchParams`), defaulting to the first plan; it re-reads the composite every 30 s while `plan.state === 'in_progress'` and `document.visibilityState === 'visible'`.
- Actions: a target needing a reason (`skipped`, or `not_started` = reopen) opens `RunbookTransitionDialog` (Task 10). `in_progress`/`done`/`failed` dispatch immediately with no `at` — one click on the common path during a live cutover. A row whose `allowed_transitions` include `done` also shows a **Record time** button that opens the same dialog for `done`, where an "actually happened at" time can be given.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/releases/runbook/__tests__/runbookTab.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import { AxiosError, AxiosHeaders } from 'axios';
import runbookReducer from '../../../../store/runbookSlice';
import { runbookService } from '../../../../services/runbookService';
import type { RunbookRead, RunbookTaskRead } from '../../../../types/runbook';
import RunbookTab from '../RunbookTab';

vi.mock('../../../../services/runbookService', () => ({
  runbookService: {
    listForRelease: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    createTask: vi.fn(), updateTask: vi.fn(), removeTask: vi.fn(), setPredecessors: vi.fn(),
    transition: vi.fn(), events: vi.fn(),
  },
}));

const task = (over: Partial<RunbookTaskRead>): RunbookTaskRead => ({
  id: 1, name: 'Deploy API', description: null, kind: 'deploy', team_group_id: 3, team_name: 'Payments',
  system_id: 4, system_name: 'Payments API', system_on_release: true, duration_minutes: 30,
  fixed_start_at: null, status: 'not_started', actual_started_at: null, actual_finished_at: null, sort_order: 0,
  predecessor_ids: [], planned_start: '2026-10-01T18:00:00Z', planned_finish: '2026-10-01T18:30:00Z',
  forecast_start: '2026-10-01T18:00:00Z', forecast_finish: '2026-10-01T18:30:00Z', late_start: false,
  overrunning: false, slipped_past_fixed_start: false, blocked: false, critical: true,
  allowed_transitions: ['in_progress', 'done'], ...over,
});

const read = (releaseId: number, planId: number, state: RunbookRead['plan']['state'], tasks: RunbookTaskRead[]): RunbookRead => ({
  plan: { id: planId, release_id: releaseId, environment_id: 2, environment_name: `env-${releaseId}`,
          name: `Cutover ${releaseId}`, anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: 'canary', notes: null, state },
  planned_end: '2026-10-01T18:45:00Z', forecast_end: '2026-10-01T19:05:00Z', slip_minutes: 20, tasks,
});

function setup(releaseId: number, r: RunbookRead, role = 'Developer') {
  vi.mocked(runbookService.listForRelease).mockImplementation(async (rid) =>
    rid === releaseId ? [r.plan] : []);
  vi.mocked(runbookService.get).mockResolvedValue(r);
  const store = configureStore({ reducer: {
    runbook: runbookReducer,
    auth: (s = { user: { id: 1, role, is_master_admin: false } }) => s,
  }});
  const ui = (rid: number) => (
    <Provider store={store}><MemoryRouter><RunbookTab releaseId={rid} /></MemoryRouter></Provider>
  );
  return { store, ...render(ui(releaseId)), ui };
}

describe('RunbookTab', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it('renders the header and one row per task with its flags as text', async () => {
    const smoke = task({ id: 2, name: 'Smoke test', kind: 'verification', predecessor_ids: [1], blocked: true,
                         allowed_transitions: [], critical: false, late_start: true });
    setup(7, read(7, 5, 'in_progress', [task({}), smoke]));
    expect(await screen.findByText('Cutover 7')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /add task/i })).not.toBeInTheDocument();  // Developer
    expect(screen.getByText(/Canary/)).toBeInTheDocument();
    expect(screen.getByText(/20 min late/i)).toBeInTheDocument();
    const row = screen.getByText('Smoke test').closest('[role="row"]') as HTMLElement;
    expect(within(row).getByText('Deploy API')).toBeInTheDocument();       // predecessor by name
    expect(within(row).getByLabelText(/blocked by a failed task/i)).toBeInTheDocument();
    expect(within(row).getByLabelText(/late start/i)).toBeInTheDocument();
  });

  it('renders only the actions the server allows, and a start re-renders from the response', async () => {
    const r = read(7, 5, 'not_started', [task({})]);
    setup(7, r);
    await screen.findByText('Deploy API');
    expect(screen.getByRole('button', { name: 'Start Deploy API' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Skip Deploy API/ })).not.toBeInTheDocument();
    vi.mocked(runbookService.transition).mockResolvedValue(
      read(7, 5, 'in_progress', [task({ status: 'in_progress', allowed_transitions: ['done', 'failed'] })]));
    await userEvent.click(screen.getByRole('button', { name: 'Start Deploy API' }));
    expect(runbookService.transition).toHaveBeenCalledWith(1, { to_status: 'in_progress' });
    expect(await screen.findByRole('button', { name: 'Complete Deploy API' })).toBeInTheDocument();
  });

  it('shows the server refusal text, not an HTTP status', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]));
    await screen.findByText('Deploy API');
    vi.mocked(runbookService.transition).mockRejectedValue(new AxiosError('Request failed with status code 409',
      'ERR_BAD_REQUEST', undefined, undefined, { status: 409, statusText: 'Conflict', headers: {},
      config: { headers: new AxiosHeaders() }, data: { detail: "'Deploy API' cannot start until these are done or skipped: Backup (in_progress)" } }));
    await userEvent.click(screen.getByRole('button', { name: 'Start Deploy API' }));
    expect(await screen.findByText(/Backup \(in_progress\)/)).toBeInTheDocument();
    expect(screen.queryByText(/status code/)).not.toBeInTheDocument();
  });

  it('re-reads every 30 seconds while in progress and not once complete', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setup(7, read(7, 5, 'in_progress', [task({ status: 'in_progress' })]));
    await screen.findByText('Deploy API');
    const before = vi.mocked(runbookService.get).mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(30_000); });
    expect(vi.mocked(runbookService.get).mock.calls.length).toBe(before + 1);
    vi.mocked(runbookService.get).mockResolvedValue(read(7, 5, 'complete', [task({ status: 'done', allowed_transitions: [] })]));
    await act(async () => { vi.advanceTimersByTime(30_000); });
    const settled = vi.mocked(runbookService.get).mock.calls.length;
    await act(async () => { vi.advanceTimersByTime(90_000); });
    expect(vi.mocked(runbookService.get).mock.calls.length).toBe(settled);
  });

  it("does not show the previous release's runbook after re-rendering for another release", async () => {
    const { rerender, ui } = setup(7, read(7, 5, 'not_started', [task({})]));
    await screen.findByText('Cutover 7');
    vi.mocked(runbookService.listForRelease).mockResolvedValue([]);
    rerender(ui(8));
    await waitFor(() => expect(screen.queryByText('Cutover 7')).not.toBeInTheDocument());
    expect(await screen.findByText(/no runbook for this release yet/i)).toBeInTheDocument();
  });

  it('offers structure controls to a release manager only', async () => {
    setup(7, read(7, 5, 'not_started', [task({})]), 'Release Manager');
    expect(await screen.findByRole('button', { name: /add task/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/components/releases/runbook/__tests__/runbookTab.test.tsx`
Expected: FAIL — cannot resolve `../RunbookTab`.

- [ ] **Step 3: Write `labels.ts`**

```ts
import type { DeployPattern, TaskKind, TaskStatus } from '../../../types/runbook';

export const STATUS_LABEL: Record<TaskStatus, string> = {
  not_started: 'Not started', in_progress: 'In progress', done: 'Done', failed: 'Failed', skipped: 'Skipped',
};
export const STATUS_COLOR: Record<TaskStatus, 'default' | 'info' | 'success' | 'error' | 'warning'> = {
  not_started: 'default', in_progress: 'info', done: 'success', failed: 'error', skipped: 'warning',
};
export const KIND_LABEL: Record<TaskKind, string> = {
  task: 'Task', check: 'Check', deploy: 'Deploy', verification: 'Verification', ramp: 'Ramp',
};
export const PATTERN_LABEL: Record<DeployPattern, string> = {
  rolling: 'Rolling', blue_green: 'Blue-green', canary: 'Canary', big_bang: 'Big bang', other: 'Other',
};
/** The button text for moving a task to `to` from `from`. */
export function actionLabel(to: TaskStatus, from: TaskStatus): string {
  if (to === 'in_progress') return from === 'failed' ? 'Retry' : 'Start';
  if (to === 'done') return from === 'not_started' ? 'Mark done' : 'Complete';
  if (to === 'failed') return 'Fail';
  if (to === 'skipped') return 'Skip';
  return 'Reopen';
}
export const NEEDS_REASON = (to: TaskStatus) => to === 'skipped' || to === 'not_started';
export const FLAG_TEXT = {
  critical: 'On the critical path — a delay here moves the finish',
  late_start: 'Late start',
  overrunning: 'Overrunning its planned duration',
  slipped_past_fixed_start: 'Pushed past its fixed start time by earlier tasks',
  blocked: 'Blocked by a failed task',
} as const;
```

- [ ] **Step 4: Write `RunbookTaskTable.tsx`**

```tsx
/**
 * The runbook's task table. Renders ONLY what the composite read says —
 * action buttons come from `allowed_transitions`, never a local rule.
 * `disableVirtualization`: runbooks are tens of rows, and without it jsdom
 * renders a fraction of the columns (see CLAUDE.md, A3).
 */
import { Box, Button, Chip, Stack, Tooltip } from '@mui/material';
import WhatshotIcon from '@mui/icons-material/Whatshot';
import ScheduleIcon from '@mui/icons-material/Schedule';
import HourglassBottomIcon from '@mui/icons-material/HourglassBottom';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import BlockIcon from '@mui/icons-material/Block';
import type { GridColDef } from '@mui/x-data-grid';
import { useSelector } from 'react-redux';
import DataTable from '../../DataTable';
import type { RootState } from '../../../store';
import type { RunbookRead, RunbookTaskRead, TaskStatus } from '../../../types/runbook';
import { formatBookingDateTime } from '../../../utils/datetime';
import { FLAG_TEXT, KIND_LABEL, STATUS_COLOR, STATUS_LABEL, actionLabel } from './labels';

interface Props {
  read: RunbookRead;
  canEdit: boolean;
  onAction: (task: RunbookTaskRead, to: TaskStatus) => void;
  onRecordTime: (task: RunbookTaskRead) => void;
  onEdit: (task: RunbookTaskRead) => void;
}

const FLAGS: { key: keyof typeof FLAG_TEXT; Icon: typeof WhatshotIcon; color: 'error' | 'warning' | 'info' }[] = [
  { key: 'blocked', Icon: BlockIcon, color: 'error' },
  { key: 'critical', Icon: WhatshotIcon, color: 'error' },
  { key: 'late_start', Icon: ScheduleIcon, color: 'warning' },
  { key: 'overrunning', Icon: HourglassBottomIcon, color: 'warning' },
  { key: 'slipped_past_fixed_start', Icon: SkipNextIcon, color: 'info' },
];

export default function RunbookTaskTable({ read, canEdit, onAction, onRecordTime, onEdit }: Props) {
  const user = useSelector((s: RootState) => s.auth.user);
  const nameById = new Map(read.tasks.map((t) => [t.id, t.name]));
  const columns: GridColDef<RunbookTaskRead>[] = [
    { field: 'name', headerName: 'Task', flex: 1.4, minWidth: 180 },
    { field: 'kind', headerName: 'Kind', width: 110, valueGetter: (_v, row) => KIND_LABEL[row.kind] },
    { field: 'team_name', headerName: 'Team', width: 140, valueGetter: (_v, row) => row.team_name ?? '—' },
    {
      field: 'system_name', headerName: 'System', width: 170,
      valueGetter: (_v, row) => row.system_name
        ? (row.system_on_release ? row.system_name : `${row.system_name} (no longer on this release)`)
        : '—',
    },
    { field: 'duration_minutes', headerName: 'Mins', width: 70 },
    {
      field: 'predecessor_ids', headerName: 'After', flex: 1, minWidth: 160, sortable: false,
      valueGetter: (_v, row) => row.predecessor_ids.map((id) => nameById.get(id) ?? '—').join(', ') || '—',
    },
    { field: 'planned_start', headerName: 'Planned start', width: 150,
      valueGetter: (_v, row) => formatBookingDateTime(row.planned_start) },
    { field: 'forecast_start', headerName: 'Forecast start', width: 150,
      valueGetter: (_v, row) => formatBookingDateTime(row.forecast_start) },
    {
      field: 'status', headerName: 'Status', width: 120,
      renderCell: ({ row }) => <Chip size="small" label={STATUS_LABEL[row.status]} color={STATUS_COLOR[row.status]} />,
    },
    {
      field: 'flags', headerName: 'Flags', width: 130, sortable: false,
      renderCell: ({ row }) => (
        <Stack direction="row" spacing={0.5} alignItems="center" sx={{ height: '100%' }}>
          {FLAGS.filter((f) => row[f.key]).map(({ key, Icon, color }) => (
            <Tooltip key={key} title={FLAG_TEXT[key]}>
              <Icon fontSize="small" color={color} aria-label={FLAG_TEXT[key]} role="img" />
            </Tooltip>
          ))}
        </Stack>
      ),
    },
    {
      field: 'actions', headerName: 'Actions', minWidth: 240, flex: 1, sortable: false,
      renderCell: ({ row }) => (
        <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', height: '100%', flexWrap: 'wrap' }}>
          {row.allowed_transitions.map((to) => {
            const label = actionLabel(to, row.status);
            return (
              <Button key={to} size="small" variant={to === 'failed' ? 'text' : 'outlined'}
                      color={to === 'failed' ? 'error' : 'primary'} aria-label={`${label} ${row.name}`}
                      onClick={() => onAction(row, to)}>
                {label}
              </Button>
            );
          })}
          {row.allowed_transitions.includes('done') && (
            <Button size="small" aria-label={`Record a time for ${row.name}`} onClick={() => onRecordTime(row)}>
              Record time
            </Button>
          )}
          {canEdit && (
            <Button size="small" aria-label={`Edit ${row.name}`} onClick={() => onEdit(row)}>Edit</Button>
          )}
        </Box>
      ),
    },
  ];
  return (
    <DataTable<RunbookTaskRead>
      storageKey="release-runbook-tasks"
      userId={user?.id ?? 'guest'}
      rows={read.tasks}
      columns={columns}
      autoHeight
      disableVirtualization
      disableColumnFilter
      hideFooter
      emptyMessage="This runbook has no tasks yet."
    />
  );
}
```

`hideFooter` hides the pager but does **not** disable paging (IA PR 4's lesson): also pass `pageSizeOptions={[100]}` and `initialState={{ pagination: { paginationModel: { pageSize: 100 } } }}`, and add a one-line comment that runbooks over 100 tasks are out of scope for C5a. Check whether other `DataTable` users in `components/releases` set these the same way (`grep -rn "hideFooter" frontend/src/components/releases`) and follow them exactly.

- [ ] **Step 5: Write `RunbookTab.tsx`**

```tsx
/**
 * Release detail → Runbook (Phase 9 C5a). One plan per environment, selected
 * by `?plan=`. The tab renders the composite the server computed; while the
 * plan is in progress it re-reads every 30 s (paused while the document is
 * hidden), because several teams tick tasks at once during a cutover.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Chip, MenuItem, Paper, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import type { AppDispatch, RootState } from '../../../store';
import { fetchRunbook, fetchRunbooks, transitionTask } from '../../../store/runbookSlice';
import type { RunbookTaskRead, TaskStatus } from '../../../types/runbook';
import { formatBookingDateTime } from '../../../utils/datetime';
import RunbookTaskTable from './RunbookTaskTable';
import RunbookTimeline from './RunbookTimeline';
import RunbookPlanDialog from './RunbookPlanDialog';
import RunbookTaskDialog from './RunbookTaskDialog';
import RunbookTransitionDialog from './RunbookTransitionDialog';
import { NEEDS_REASON, PATTERN_LABEL } from './labels';

const POLL_MS = 30_000;
const STATE_COLOR = { not_started: 'default', in_progress: 'info', complete: 'success', failed: 'error' } as const;

export default function RunbookTab({ releaseId }: { releaseId: number }) {
  const dispatch = useDispatch<AppDispatch>();
  const [params, setParams] = useSearchParams();
  const user = useSelector((s: RootState) => s.auth.user);
  const plans = useSelector((s: RootState) => s.runbook.plansByRelease[releaseId]);
  const canEdit = !!user && (user.is_master_admin || user.role === 'Admin' || user.role === 'Release Manager');
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'table' | 'timeline'>('table');
  const [planDialog, setPlanDialog] = useState<'create' | 'edit' | null>(null);
  const [taskDialog, setTaskDialog] = useState<RunbookTaskRead | 'new' | null>(null);
  const [pending, setPending] = useState<{ task: RunbookTaskRead; to: TaskStatus } | null>(null);

  useEffect(() => { setError(null); dispatch(fetchRunbooks(releaseId)); }, [dispatch, releaseId]);

  // Only a plan that belongs to THIS release may be selected — a stale ?plan=
  // from another release must never render (re-render, don't just mount).
  const planId = useMemo(() => {
    if (!plans?.length) return null;
    const wanted = Number(params.get('plan'));
    return plans.some((p) => p.id === wanted) ? wanted : plans[0].id;
  }, [plans, params]);
  const read = useSelector((s: RootState) => (planId ? s.runbook.byPlan[planId] : undefined));
  const current = read && read.plan.release_id === releaseId ? read : undefined;

  useEffect(() => { if (planId) dispatch(fetchRunbook(planId)); }, [dispatch, planId]);

  const live = current?.plan.state === 'in_progress';
  useEffect(() => {
    if (!live || !planId) return undefined;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') dispatch(fetchRunbook(planId));
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [dispatch, live, planId]);

  const selectPlan = (id: number) => {
    const next = new URLSearchParams(params);
    next.set('plan', String(id));
    setParams(next, { replace: true });
  };

  const onAction = useCallback(async (task: RunbookTaskRead, to: TaskStatus) => {
    if (!planId) return;
    if (NEEDS_REASON(to)) { setPending({ task, to }); return; }   // skip and reopen ask why
    setError(null);
    const result = await dispatch(transitionTask({ planId, taskId: task.id, body: { to_status: to } }));
    if (transitionTask.rejected.match(result)) setError(result.payload ?? 'Failed to update task');
  }, [dispatch, planId]);

  if (plans === undefined) return <Typography color="text.secondary">Loading runbooks…</Typography>;

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
        {plans.length > 0 && (
          <TextField select size="small" label="Environment" value={planId ?? ''} sx={{ minWidth: 220 }}
                     onChange={(e) => selectPlan(Number(e.target.value))}>
            {plans.map((p) => <MenuItem key={p.id} value={p.id}>{p.environment_name ?? 'Unknown environment'}</MenuItem>)}
          </TextField>
        )}
        {canEdit && <Button variant="outlined" onClick={() => setPlanDialog('create')}>New runbook</Button>}
      </Stack>

      {plans.length === 0 && (
        <Typography color="text.secondary">There is no runbook for this release yet.</Typography>
      )}

      {current && (
        <>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between">
              <Box>
                <Typography variant="h6">{current.plan.name}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {current.plan.environment_name} · starts {formatBookingDateTime(current.plan.anchor_start_at)}
                  {current.plan.deploy_pattern && ` · ${PATTERN_LABEL[current.plan.deploy_pattern]}`}
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                <Chip label={current.plan.state.replace('_', ' ')} color={STATE_COLOR[current.plan.state]} />
                <Typography variant="body2">Planned end {formatBookingDateTime(current.planned_end)}</Typography>
                <Typography variant="body2">Forecast end {formatBookingDateTime(current.forecast_end)}</Typography>
                <Typography variant="body2" color={current.slip_minutes ? 'warning.main' : 'text.secondary'}>
                  {current.slip_minutes ? `${current.slip_minutes} min late` : 'On time'}
                </Typography>
                {canEdit && <Button size="small" onClick={() => setPlanDialog('edit')}>Edit runbook</Button>}
                {canEdit && <Button size="small" variant="contained" onClick={() => setTaskDialog('new')}>Add task</Button>}
              </Stack>
            </Stack>
          </Paper>
          <ToggleButtonGroup size="small" exclusive value={view} onChange={(_e, v) => v && setView(v)} aria-label="Runbook view">
            <ToggleButton value="table">Table</ToggleButton>
            <ToggleButton value="timeline">Timeline</ToggleButton>
          </ToggleButtonGroup>
          {view === 'table'
            ? <RunbookTaskTable read={current} canEdit={canEdit} onAction={onAction}
                                onRecordTime={(task) => setPending({ task, to: 'done' })}
                                onEdit={(t) => setTaskDialog(t)} />
            : <RunbookTimeline read={current} />}
        </>
      )}

      {planDialog && (
        <RunbookPlanDialog releaseId={releaseId} existing={planDialog === 'edit' ? current?.plan : undefined}
                           onClose={(createdId) => { setPlanDialog(null); if (createdId) selectPlan(createdId); }} />
      )}
      {taskDialog && current && (
        <RunbookTaskDialog read={current} task={taskDialog === 'new' ? undefined : taskDialog}
                           onClose={() => setTaskDialog(null)} />
      )}
      {pending && current && (
        <RunbookTransitionDialog planId={current.plan.id} task={pending.task} to={pending.to}
                                 onClose={() => setPending(null)} />
      )}
    </Stack>
  );
}
```

Task 10 creates the three dialogs and Task 11 the timeline. To keep this task's tests running now, create each as a minimal placeholder component returning `null` with the final prop signature (`RunbookPlanDialog({ releaseId, existing, onClose })`, `RunbookTaskDialog({ read, task, onClose })`, `RunbookTransitionDialog({ planId, task, to, onClose })`, `RunbookTimeline({ read })`); Tasks 10 and 11 replace their bodies.

- [ ] **Step 6: Wire the tab into `ReleaseDetail.tsx`**

Add ` *   runbook: Runbook` to the doc comment after `closeout`; add `{ key: 'runbook', label: 'Runbook' },` after the closeout entry in `RELEASE_TABS`; `import RunbookTab from '../../components/releases/runbook/RunbookTab';` next to the `CloseoutTab` import; and after the closeout render line: `{activeTab === 'runbook' && <RunbookTab releaseId={releaseId} />}`.

- [ ] **Step 7: Run to verify it passes**

Run: `npx vitest run src/components/releases/runbook && npx tsc --noEmit && npm run lint`
Expected: PASS. If the flag-icon `getByLabelText` fails because MUI's Tooltip overrides `aria-label` with its `title` (the IA PR 4 note), keep `title` and `aria-label` identical — they are here — and query by that text.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/releases/runbook frontend/src/pages/releases/ReleaseDetail.tsx
git commit -m "feat(c5a): Runbook tab — plan switcher, header, task table, 30s live refresh"
```

---

### Task 10: The three dialogs

**Files:**
- Modify (replace placeholders): `frontend/src/components/releases/runbook/RunbookPlanDialog.tsx`, `RunbookTaskDialog.tsx`, `RunbookTransitionDialog.tsx`
- Test: `frontend/src/components/releases/runbook/__tests__/runbookDialogs.test.tsx`

**Interfaces:**
- Consumes: thunks `createRunbook`, `updateRunbook`, `createTask`, `updateTask`, `deleteTask`, `setPredecessors`, `transitionTask`; `releaseService.listSystems(releaseId)` (confirm the name: `grep -n "releases/\${releaseId}/systems" src/services/releaseService.ts` — the method at line ~145); `userGroupService.listGroups({ limit: 500 })` returning `{ rows, total }`; `useAllEnvironments()` from `hooks/useAllEnvironments` returning `{ environments, loading, truncated }`; `toDateTimeLocal` from `utils/datetime`.
- Produces: the three components with the Task 9 signatures. `RunbookPlanDialog.onClose(createdPlanId?: number)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/releases/runbook/__tests__/runbookDialogs.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import runbookReducer from '../../../../store/runbookSlice';
import { runbookService } from '../../../../services/runbookService';
import type { RunbookRead, RunbookTaskRead } from '../../../../types/runbook';
import RunbookTaskDialog from '../RunbookTaskDialog';
import RunbookTransitionDialog from '../RunbookTransitionDialog';

vi.mock('../../../../services/runbookService', () => ({
  runbookService: { get: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), createTask: vi.fn(),
                    updateTask: vi.fn(), setPredecessors: vi.fn(), removeTask: vi.fn(), transition: vi.fn() },
}));
vi.mock('../../../../hooks/useAllEnvironments', () => ({
  useAllEnvironments: () => ({ environments: [{ id: 2, name: 'prod' }], loading: false, truncated: false }),
}));
vi.mock('../../../../services/userGroupService', () => ({
  userGroupService: { listGroups: vi.fn().mockResolvedValue({ rows: [{ id: 3, name: 'Payments' }], total: 1 }) },
}));
vi.mock('../../../../services/releaseService', () => ({
  releaseService: { listSystems: vi.fn().mockResolvedValue([{ id: 1, system_id: 4, system_name: 'Payments API', role: 'changing' }]) },
}));

const t = (id: number, name: string, over: Partial<RunbookTaskRead> = {}): RunbookTaskRead => ({
  id, name, description: null, kind: 'task', team_group_id: null, team_name: null, system_id: null, system_name: null,
  system_on_release: true, duration_minutes: 30, fixed_start_at: null, status: 'not_started', actual_started_at: null,
  actual_finished_at: null, sort_order: 0, predecessor_ids: [], planned_start: '2026-10-01T18:00:00Z',
  planned_finish: '2026-10-01T18:30:00Z', forecast_start: '2026-10-01T18:00:00Z', forecast_finish: '2026-10-01T18:30:00Z',
  late_start: false, overrunning: false, slipped_past_fixed_start: false, blocked: false, critical: false,
  allowed_transitions: [], ...over,
});
const read: RunbookRead = {
  plan: { id: 5, release_id: 7, environment_id: 2, environment_name: 'prod', name: 'Cutover',
          anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: null, notes: null, state: 'not_started' },
  planned_end: '2026-10-01T19:00:00Z', forecast_end: '2026-10-01T19:00:00Z', slip_minutes: 0,
  tasks: [t(1, 'Deploy API'), t(2, 'Smoke test', { predecessor_ids: [1] })],
};
const wrap = (ui: React.ReactElement) => render(
  <Provider store={configureStore({ reducer: { runbook: runbookReducer } })}>{ui}</Provider>);

describe('RunbookTaskDialog', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(runbookService.get).mockResolvedValue(read); });

  it('does not offer the task itself as its own predecessor', async () => {
    wrap(<RunbookTaskDialog read={read} task={read.tasks[1]} onClose={() => {}} />);
    await userEvent.click(screen.getByLabelText('Runs after'));
    const list = await screen.findByRole('listbox');
    expect(within(list).getByText('Deploy API')).toBeInTheDocument();
    expect(within(list).queryByText('Smoke test')).not.toBeInTheDocument();
  });

  it('an edit sends only update-schema keys, and predecessors separately', async () => {
    vi.mocked(runbookService.updateTask).mockResolvedValue(read);
    vi.mocked(runbookService.setPredecessors).mockResolvedValue(read);
    const onClose = vi.fn();
    wrap(<RunbookTaskDialog read={read} task={read.tasks[1]} onClose={onClose} />);
    const dur = screen.getByLabelText('Duration (minutes)');
    await userEvent.clear(dur);
    await userEvent.type(dur, '45');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    const [taskId, body] = vi.mocked(runbookService.updateTask).mock.calls[0];
    expect(taskId).toBe(2);
    expect(Object.keys(body).sort()).toEqual(
      ['description', 'duration_minutes', 'fixed_start_at', 'kind', 'name', 'system_id', 'team_group_id'].sort());
    expect(body.duration_minutes).toBe(45);
    expect(runbookService.setPredecessors).not.toHaveBeenCalled();   // unchanged set is not re-sent
    expect(onClose).toHaveBeenCalled();
  });

  it('a create sends predecessor_ids in the create body', async () => {
    vi.mocked(runbookService.createTask).mockResolvedValue(t(3, 'Ramp 10%') as never);
    wrap(<RunbookTaskDialog read={read} onClose={() => {}} />);
    await userEvent.type(screen.getByLabelText('Name'), 'Ramp 10%');
    await userEvent.click(screen.getByLabelText('Runs after'));
    await userEvent.click(await screen.findByRole('option', { name: 'Smoke test' }));
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    const [, body] = vi.mocked(runbookService.createTask).mock.calls[0];
    expect(body.predecessor_ids).toEqual([2]);
  });
});

describe('RunbookTransitionDialog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('skip requires a reason before it can be submitted', async () => {
    vi.mocked(runbookService.transition).mockResolvedValue(read);
    wrap(<RunbookTransitionDialog planId={5} task={read.tasks[0]} to="skipped" onClose={() => {}} />);
    const submit = screen.getByRole('button', { name: 'Skip task' });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Reason'), 'not needed in EU');
    await userEvent.click(submit);
    expect(runbookService.transition).toHaveBeenCalledWith(1, { to_status: 'skipped', reason: 'not needed in EU', at: null });
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/components/releases/runbook/__tests__/runbookDialogs.test.tsx`
Expected: FAIL — the placeholders render nothing.

- [ ] **Step 3: Implement `RunbookTransitionDialog.tsx`**

```tsx
/** Skip and reopen need a reason (spec §4); any transition may record when it
 * actually happened. The server enforces both — this dialog only asks. */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField } from '@mui/material';
import type { AppDispatch } from '../../../store';
import { transitionTask } from '../../../store/runbookSlice';
import type { RunbookTaskRead, TaskStatus } from '../../../types/runbook';
import { NEEDS_REASON, actionLabel } from './labels';

interface Props { planId: number; task: RunbookTaskRead; to: TaskStatus; onClose: () => void }

export default function RunbookTransitionDialog({ planId, task, to, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const [reason, setReason] = useState('');
  const [at, setAt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const needsReason = NEEDS_REASON(to);
  const verb = `${actionLabel(to, task.status)} task`;
  const submit = async () => {
    setError(null);
    const body = { to_status: to, reason: reason.trim() || null, at: at ? new Date(at).toISOString() : null };
    const result = await dispatch(transitionTask({ planId, taskId: task.id, body }));
    if (transitionTask.rejected.match(result)) setError(result.payload ?? 'Failed to update task');
    else onClose();
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{verb}: {task.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          {needsReason && (
            <TextField label="Reason" required multiline minRows={2} value={reason}
                       onChange={(e) => setReason(e.target.value)} />
          )}
          <TextField label="Actually happened at (optional)" type="datetime-local" value={at}
                     onChange={(e) => setAt(e.target.value)} InputLabelProps={{ shrink: true }}
                     helperText="Leave empty for now" />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={needsReason && !reason.trim()}>{verb}</Button>
      </DialogActions>
    </Dialog>
  );
}
```

Key order does not matter to `toHaveBeenCalledWith`. The *Record time* button Task 9 put on the table opens this same dialog for `done`.

- [ ] **Step 4: Implement `RunbookTaskDialog.tsx`**

```tsx
/**
 * Add or edit a task (Admin/RM). The PATCH sends only RunbookTaskUpdate keys —
 * never the read model (the schema is extra="forbid"; echoing a read row is a
 * 422 on every save). Predecessors travel separately, and only when changed.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField,
} from '@mui/material';
import type { AppDispatch } from '../../../store';
import { createTask, deleteTask, setPredecessors, updateTask } from '../../../store/runbookSlice';
import { userGroupService } from '../../../services/userGroupService';
import { releaseService } from '../../../services/releaseService';
import type { RunbookRead, RunbookTaskRead, TaskKind } from '../../../types/runbook';
import { toDateTimeLocal } from '../../../utils/datetime';
import { KIND_LABEL } from './labels';

interface Props { read: RunbookRead; task?: RunbookTaskRead; onClose: () => void }
type Option = { id: number; name: string };

const sameSet = (a: number[], b: number[]) => a.length === b.length && [...a].sort().join() === [...b].sort().join();

export default function RunbookTaskDialog({ read, task, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const planId = read.plan.id;
  const [name, setName] = useState(task?.name ?? '');
  const [description, setDescription] = useState(task?.description ?? '');
  const [kind, setKind] = useState<TaskKind>(task?.kind ?? 'task');
  const [duration, setDuration] = useState(String(task?.duration_minutes ?? 30));
  const [teamId, setTeamId] = useState<number | ''>(task?.team_group_id ?? '');
  const [systemId, setSystemId] = useState<number | ''>(task?.system_id ?? '');
  const [fixedStart, setFixedStart] = useState(task?.fixed_start_at ? toDateTimeLocal(task.fixed_start_at) : '');
  const [preds, setPreds] = useState<number[]>(task?.predecessor_ids ?? []);
  const [teams, setTeams] = useState<Option[]>([]);
  const [systems, setSystems] = useState<Option[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    userGroupService.listGroups({ limit: 500 }).then((r) => setTeams(r.rows.map((g) => ({ id: g.id, name: g.name }))));
    releaseService.listSystems(read.plan.release_id).then((rows) =>
      setSystems(rows.map((s) => ({ id: s.system_id, name: s.system_name ?? '—' }))));
  }, [read.plan.release_id]);

  // A task that left the release still shows its system (spec §3), so keep it selectable.
  const systemOptions = useMemo(() => {
    if (task?.system_id && !systems.some((s) => s.id === task.system_id)) {
      return [...systems, { id: task.system_id, name: `${task.system_name ?? '—'} (no longer on this release)` }];
    }
    return systems;
  }, [systems, task]);
  const predecessorOptions = read.tasks.filter((t) => t.id !== task?.id);
  const minutes = Number(duration);
  const valid = name.trim() !== '' && Number.isInteger(minutes) && minutes >= 0;

  const save = async () => {
    setError(null);
    const fields = {
      name: name.trim(), description: description.trim() || null, kind, duration_minutes: minutes,
      team_group_id: teamId === '' ? null : teamId, system_id: systemId === '' ? null : systemId,
      fixed_start_at: fixedStart ? new Date(fixedStart).toISOString() : null,
    };
    const result = task
      ? await dispatch(updateTask({ planId, taskId: task.id, body: fields }))
      : await dispatch(createTask({ planId, body: { ...fields, predecessor_ids: preds } }));
    if (result.meta.requestStatus === 'rejected') { setError((result.payload as string) ?? 'Failed to save task'); return; }
    if (task && !sameSet(preds, task.predecessor_ids)) {
      const p = await dispatch(setPredecessors({ planId, taskId: task.id, ids: preds }));
      if (setPredecessors.rejected.match(p)) { setError(p.payload ?? 'Failed to update dependencies'); return; }
    }
    onClose();
  };

  const remove = async () => {
    if (!task) return;
    const result = await dispatch(deleteTask({ planId, taskId: task.id }));
    if (deleteTask.rejected.match(result)) setError(result.payload ?? 'Failed to delete task');
    else onClose();
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{task ? `Edit ${task.name}` : 'Add task'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Description" multiline minRows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          <TextField select label="Kind" value={kind} onChange={(e) => setKind(e.target.value as TaskKind)}>
            {Object.entries(KIND_LABEL).map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
          </TextField>
          <TextField label="Duration (minutes)" type="number" inputProps={{ min: 0 }} value={duration}
                     onChange={(e) => setDuration(e.target.value)} />
          <TextField select label="Team" value={teamId} onChange={(e) => setTeamId(e.target.value === '' ? '' : Number(e.target.value))}>
            <MenuItem value="">No team (Admin / Release Manager only)</MenuItem>
            {teams.map((g) => <MenuItem key={g.id} value={g.id}>{g.name}</MenuItem>)}
          </TextField>
          <TextField select label="System" value={systemId} onChange={(e) => setSystemId(e.target.value === '' ? '' : Number(e.target.value))}>
            <MenuItem value="">None</MenuItem>
            {systemOptions.map((s) => <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>)}
          </TextField>
          <TextField label="Start no earlier than (optional)" type="datetime-local" value={fixedStart}
                     onChange={(e) => setFixedStart(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField select label="Runs after" value={preds} SelectProps={{ multiple: true }}
                     onChange={(e) => setPreds(typeof e.target.value === 'string' ? [] : (e.target.value as unknown as number[]))}
                     helperText="This task cannot start until all of these are done or skipped">
            {predecessorOptions.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        {task && task.status === 'not_started' && <Button color="error" onClick={remove}>Delete</Button>}
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!valid}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
```

If the `Select` with `label="Runs after"` does not expose that accessible name on the `combobox` (the C2 MUI gotcha), add `inputProps={{ 'aria-label': 'Runs after' }}` — and do the same for any other select a test queries by label.

- [ ] **Step 5: Implement `RunbookPlanDialog.tsx`**

```tsx
/** Create a runbook (environment, name, anchor, pattern) or edit one. The
 * environment is fixed after create — PATCH has no environment field. */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField } from '@mui/material';
import type { AppDispatch } from '../../../store';
import { createRunbook, deleteRunbook, updateRunbook } from '../../../store/runbookSlice';
import type { DeployPattern, RunbookPlanRead } from '../../../types/runbook';
import { toDateTimeLocal } from '../../../utils/datetime';
import { useAllEnvironments } from '../../../hooks/useAllEnvironments';
import { PATTERN_LABEL } from './labels';

interface Props { releaseId: number; existing?: RunbookPlanRead; onClose: (createdPlanId?: number) => void }

export default function RunbookPlanDialog({ releaseId, existing, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  // The shared picker hook: coalesces in-flight requests, and reports a
  // truncated list rather than pretending it is complete.
  const { environments: envs, truncated } = useAllEnvironments();
  const [environmentId, setEnvironmentId] = useState<number | ''>(existing?.environment_id ?? '');
  const [name, setName] = useState(existing?.name ?? 'Production cutover');
  const [anchor, setAnchor] = useState(existing ? toDateTimeLocal(existing.anchor_start_at) : '');
  const [pattern, setPattern] = useState<DeployPattern | ''>(existing?.deploy_pattern ?? '');
  const [notes, setNotes] = useState(existing?.notes ?? '');
  const [error, setError] = useState<string | null>(null);

  const valid = name.trim() !== '' && anchor !== '' && (existing || environmentId !== '');
  const save = async () => {
    setError(null);
    const common = { name: name.trim(), anchor_start_at: new Date(anchor).toISOString(),
                     deploy_pattern: pattern || null, notes: notes.trim() || null };
    const result = existing
      ? await dispatch(updateRunbook({ planId: existing.id, body: common }))
      : await dispatch(createRunbook({ releaseId, body: { ...common, environment_id: environmentId as number } }));
    if (result.meta.requestStatus === 'rejected') { setError((result.payload as string) ?? 'Failed to save runbook'); return; }
    onClose(existing ? undefined : (result.payload as { plan: { id: number } }).plan.id);
  };
  const remove = async () => {
    if (!existing) return;
    const result = await dispatch(deleteRunbook({ releaseId, planId: existing.id }));
    if (deleteRunbook.rejected.match(result)) setError(result.payload ?? 'Failed to delete runbook');
    else onClose();
  };
  return (
    <Dialog open onClose={() => onClose()} fullWidth maxWidth="sm">
      <DialogTitle>{existing ? 'Edit runbook' : 'New runbook'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          {!existing && (
            <TextField select label="Environment" required value={environmentId}
                       onChange={(e) => setEnvironmentId(Number(e.target.value))}
                       helperText={truncated ? 'Not every environment is listed — the estate exceeds the picker limit' : undefined}>
              {envs.map((e) => <MenuItem key={e.id} value={e.id}>{e.name}</MenuItem>)}
            </TextField>
          )}
          <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
          <TextField label="Starts at" type="datetime-local" required value={anchor}
                     onChange={(e) => setAnchor(e.target.value)} InputLabelProps={{ shrink: true }}
                     helperText="Tasks with nothing before them and no fixed time start here" />
          <TextField select label="Deploy pattern" value={pattern} onChange={(e) => setPattern(e.target.value as DeployPattern | '')}>
            <MenuItem value="">Not set</MenuItem>
            {Object.entries(PATTERN_LABEL).map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
          </TextField>
          <TextField label="Notes" multiline minRows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Stack>
      </DialogContent>
      <DialogActions>
        {existing && existing.state === 'not_started' && <Button color="error" onClick={remove}>Delete runbook</Button>}
        <Button onClick={() => onClose()}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!valid}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 6: Add a plan-dialog test** (append to `runbookDialogs.test.tsx`; add `import RunbookPlanDialog from '../RunbookPlanDialog';` with the other imports)

```tsx
describe('RunbookPlanDialog', () => {
  it('creates a runbook for the chosen environment and returns its id', async () => {
    vi.mocked(runbookService.create).mockResolvedValue(read);
    const onClose = vi.fn();
    wrap(<RunbookPlanDialog releaseId={7} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText(/Environment/));
    await userEvent.click(await screen.findByRole('option', { name: 'prod' }));
    await userEvent.type(screen.getByLabelText(/Starts at/), '2026-10-01T18:00');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    const [releaseId, body] = vi.mocked(runbookService.create).mock.calls[0];
    expect(releaseId).toBe(7);
    expect(body.environment_id).toBe(2);
    expect(onClose).toHaveBeenCalledWith(5);
  });
});
```

- [ ] **Step 7: Run to verify all pass**

Run: `npx vitest run src/components/releases/runbook && npx tsc --noEmit && npm run lint`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/releases/runbook
git commit -m "feat(c5a): runbook plan, task and transition dialogs"
```

---

### Task 11: The timeline

**Files:**
- Modify (replace placeholder): `frontend/src/components/releases/runbook/RunbookTimeline.tsx`
- Test: `frontend/src/components/releases/runbook/__tests__/runbookTimeline.test.tsx`

**Interfaces:**
- Consumes: `RunbookRead`. Produces `<RunbookTimeline read={RunbookRead} />`.
- Layout rule: a single horizontal scroll container (`overflowX: 'auto'`) holding an absolutely-positioned bar grid; the span is `min(planned start, forecast start)` → `max(planned_end, forecast_end)`; one row per task in the table's order; each row has a planned bar (outlined) and a forecast bar (filled, `error` colour when `critical`); a vertical "now" line when now is within the span. Width is `max(720, minutes × 2)` px so a two-evening plan is scrollable, never page-widening. Every bar carries an `aria-label` sentence, since jsdom performs no layout and the structure is what tests can see.

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { RunbookRead } from '../../../../types/runbook';
import RunbookTimeline from '../RunbookTimeline';

const base = {
  description: null, kind: 'task' as const, team_group_id: null, team_name: null, system_id: null, system_name: null,
  system_on_release: true, fixed_start_at: null, actual_started_at: null, actual_finished_at: null, sort_order: 0,
  predecessor_ids: [], late_start: false, overrunning: false, slipped_past_fixed_start: false, blocked: false,
  allowed_transitions: [], status: 'not_started' as const,
};
const read: RunbookRead = {
  plan: { id: 5, release_id: 7, environment_id: 2, environment_name: 'prod', name: 'Cutover',
          anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: null, notes: null, state: 'in_progress' },
  planned_end: '2026-10-02T19:00:00Z', forecast_end: '2026-10-02T20:00:00Z', slip_minutes: 60,
  tasks: [
    { ...base, id: 1, name: 'Pre-task', duration_minutes: 60, critical: true,
      planned_start: '2026-10-01T18:00:00Z', planned_finish: '2026-10-01T19:00:00Z',
      forecast_start: '2026-10-01T18:00:00Z', forecast_finish: '2026-10-01T20:00:00Z' },
    { ...base, id: 2, name: 'Evening two check', duration_minutes: 60, critical: false, predecessor_ids: [1],
      planned_start: '2026-10-02T18:00:00Z', planned_finish: '2026-10-02T19:00:00Z',
      forecast_start: '2026-10-02T19:00:00Z', forecast_finish: '2026-10-02T20:00:00Z' },
  ],
};

describe('RunbookTimeline', () => {
  it('draws a planned and a forecast bar per task, with readable labels', () => {
    render(<RunbookTimeline read={read} />);
    expect(screen.getByLabelText(/Pre-task: planned/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Pre-task: forecast .* critical/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Evening two check: forecast/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Evening two check: forecast .* critical/)).not.toBeInTheDocument();
  });

  it('scrolls inside itself rather than widening the page', () => {
    const { container } = render(<RunbookTimeline read={read} />);
    const scroller = container.querySelector('[data-testid="runbook-timeline-scroll"]') as HTMLElement;
    expect(scroller).not.toBeNull();
    expect(scroller.style.overflowX || getComputedStyle(scroller).overflowX).toBe('auto');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/components/releases/runbook/__tests__/runbookTimeline.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement**

```tsx
/**
 * Read-only planned-vs-forecast bars for a runbook. Modelled on
 * EnvironmentResourceGantt; deliberately not PhaseGanttEditor (an editor for a
 * different entity). Scrolls inside its own box — a runbook spanning two
 * evenings is wide, and page-level overflow here hides row labels under the
 * fixed drawer (IA PR 5).
 */
import { Box, Typography } from '@mui/material';
import type { RunbookRead } from '../../../types/runbook';
import { formatBookingDateTime } from '../../../utils/datetime';

const LABEL_W = 200;
const ROW_H = 36;
const PX_PER_MIN = 2;

export default function RunbookTimeline({ read }: { read: RunbookRead }) {
  const ms = (s: string) => new Date(s).getTime();
  const starts = read.tasks.flatMap((t) => [ms(t.planned_start), ms(t.forecast_start)]);
  const t0 = Math.min(ms(read.plan.anchor_start_at), ...starts);
  const t1 = Math.max(ms(read.planned_end), ms(read.forecast_end), t0 + 60_000);
  const minutes = (t1 - t0) / 60_000;
  const width = Math.max(720, minutes * PX_PER_MIN);
  const x = (s: string) => ((ms(s) - t0) / (t1 - t0)) * width;
  const now = Date.now();
  const showNow = now >= t0 && now <= t1;

  if (read.tasks.length === 0) {
    return <Typography color="text.secondary">This runbook has no tasks yet.</Typography>;
  }
  return (
    <Box data-testid="runbook-timeline-scroll" style={{ overflowX: 'auto' }} sx={{ border: 1, borderColor: 'divider', borderRadius: 1 }}>
      <Box sx={{ display: 'grid', gridTemplateColumns: `${LABEL_W}px ${width}px` }}>
        {read.tasks.map((t) => (
          <Box key={t.id} sx={{ display: 'contents' }}>
            <Box sx={{ height: ROW_H, px: 1, display: 'flex', alignItems: 'center', position: 'sticky', left: 0,
                       bgcolor: 'background.paper', zIndex: 1, borderBottom: 1, borderColor: 'divider' }}>
              <Typography variant="body2" noWrap title={t.name}>{t.name}</Typography>
            </Box>
            <Box sx={{ height: ROW_H, position: 'relative', borderBottom: 1, borderColor: 'divider' }}>
              <Box role="img"
                   aria-label={`${t.name}: planned ${formatBookingDateTime(t.planned_start)} to ${formatBookingDateTime(t.planned_finish)}`}
                   sx={{ position: 'absolute', top: 6, height: 10, left: x(t.planned_start),
                         width: Math.max(2, x(t.planned_finish) - x(t.planned_start)),
                         border: 1, borderColor: 'text.secondary', borderRadius: 0.5 }} />
              <Box role="img"
                   aria-label={`${t.name}: forecast ${formatBookingDateTime(t.forecast_start)} to ${formatBookingDateTime(t.forecast_finish)}${t.critical ? ', critical' : ''}`}
                   sx={{ position: 'absolute', top: 20, height: 10, left: x(t.forecast_start),
                         width: Math.max(2, x(t.forecast_finish) - x(t.forecast_start)),
                         bgcolor: t.critical ? 'error.main' : 'primary.main', borderRadius: 0.5 }} />
              {showNow && (
                <Box aria-hidden sx={{ position: 'absolute', top: 0, bottom: 0, width: 2, bgcolor: 'warning.main',
                                        left: ((now - t0) / (t1 - t0)) * width }} />
              )}
            </Box>
          </Box>
        ))}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', p: 1 }}>
        Outlined: planned. Filled: forecast. Red: on the critical path.
      </Typography>
    </Box>
  );
}
```

The test's `/Pre-task: forecast .* critical/` expects the literal `critical` after the dates; the label's `, critical` suffix supplies it.

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/components/releases/runbook && npx tsc --noEmit && npm run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/releases/runbook
git commit -m "feat(c5a): runbook timeline — planned vs forecast, critical path, scrolls in place"
```

---

### Task 12: The My work card

**Files:**
- Modify: `frontend/src/types/myWork.ts` (`MyWorkQueueKey` + header comment "seven")
- Modify: `frontend/src/pages/MyWork.tsx` (queue config entry)
- Modify: `frontend/src/pages/__tests__/myWork.test.tsx` (fixture gains `runbook_tasks`; `toHaveLength(6)` → `7` twice)
- Modify: any other `MyWorkResponse` fixture: `grep -rln "hypercare" frontend/src --include=*.test.ts*` — add `runbook_tasks` to each.

**Interfaces:**
- Consumes: the backend's `queues.runbook_tasks`.

- [ ] **Step 1: Update the tests first**

In `myWork.test.tsx`, add to the response fixture `runbook_tasks: { count: 1, items: [{ id: 21, title: 'Run smoke tests', subtitle: 'Payments 4.2 · prod', url: '/releases/7?tab=runbook&plan=5' }], failed: false }` (and the empty/failed variants the file builds), change both `toHaveLength(6)` to `toHaveLength(7)`, and add:

```tsx
it('lists runbook tasks ready for my team, linking to the plan', async () => {
  // render as the file's other tests do
  const link = await screen.findByRole('link', { name: 'Run smoke tests' });
  expect(link).toHaveAttribute('href', '/releases/7?tab=runbook&plan=5');
  expect(screen.getByText('Payments 4.2 · prod')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/pages/__tests__/myWork.test.tsx`
Expected: FAIL (6 cards, no runbook link)

- [ ] **Step 3: Implement**

In `types/myWork.ts` add `| 'runbook_tasks'` to `MyWorkQueueKey` and update the header comment to seven queues. In `MyWork.tsx`, after the `hypercare` entry:

```tsx
  {
    key: 'runbook_tasks',
    title: 'Runbook tasks ready for my team',
    // SUPERSET: there is no cross-release runbook list; each row opens its
    // own release's Runbook tab with the plan selected, which is where the
    // task is started.
    viewAllHref: '/releases',
    viewAllLabel: 'releases',
    viewAllCaption: 'All releases; runbooks live on each release',
  },
```

Match the exact shape of the existing entries (check whether `viewAllCaption` is optional in the config type).

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/pages/__tests__/myWork.test.tsx src/store/__tests__/myWorkSlice.test.ts && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/myWork.ts frontend/src/pages/MyWork.tsx frontend/src/pages/__tests__/myWork.test.tsx frontend/src/store/__tests__
git commit -m "feat(c5a): My work card for runbook tasks ready for my team"
```

---

### Task 13: Full suites, browser pass, docs

**Files:**
- Modify: `docs/admin-guide.md`, `docs/user-guide.md`, `docs/phases/phase-9.md`, `docs/plan.md`, `docs/gap-analysis.md`, `CLAUDE.md`

- [ ] **Step 1: The three full suites (controller runs these; one at a time)**

```bash
cd backend && uv run pytest -q
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
cd frontend && npm run lint && npx vitest run && npm run build
```

Expected: all green. If the PostgreSQL leg reports mass `UndefinedTable` errors, another PG run is in flight — recreate `envmgr_test` and rerun before believing anything.

- [ ] **Step 2: Browser pass** (dev servers running; `alembic current` = `runbooks`)

In the dev tenant, create three teams (e.g. *DBA*, *Payments*, *QA*) with a Developer member in two of them, and a release with at least three systems. Build the two-evening plan with **at least twelve tasks and two coordination points**: evening one — backup DB (DBA), migrate schema (DBA), pre-warm cache (Payments); evening two, fixed start 18:00 next day — check pre-tasks (DBA, after all three), deploy API / deploy worker / deploy UI (Payments, after the check), smoke tests (QA, after all three deploys), ramp 10% → 50% → 100% (Payments, a chain after smoke), verify dashboards (QA, after 100%). Then check, writing down what you saw:

1. Start *smoke tests* before the deploys are done: the 409 text names each deploy and its status.
2. As the Developer in *Payments*, see the evening-two deploy tasks on **My work** only once *check pre-tasks* is done; the *QA* tasks are absent.
3. Start *migrate schema* with an "actually happened at" in the past and leave it running past its duration: the *check pre-tasks* row shows the slipped-past-fixed-start flag, the header's slip grows, the timeline moves.
4. Fail *deploy worker*, see *smoke tests* flagged blocked; retry it; skip a ramp step with a reason; reopen a done task (refused while a successor has started, then allowed).
5. Leave the tab open with the plan in progress and tick a task from a second browser session: the first updates within 30 s.
6. Try to delete a started task and the plan: both refused with the reason shown.
7. Resize to 1024 px (iPad): the table and timeline scroll inside themselves; the page does not scroll horizontally; the Runbook tab is reachable in the tab strip.
8. Dark mode: the timeline bars and the sticky label column are legible.

Fix anything found, with a test that fails first, before continuing.

- [ ] **Step 3: Docs**

- `docs/user-guide.md` — a *Runbooks* section: what a runbook is, starting/completing/failing/retrying tasks, why a start can be refused, reading planned vs forecast and the flags, the My work card.
- `docs/admin-guide.md` — creating a runbook and tasks, teams and the no-team degradation, dependencies and why cycles are refused, skip/reopen and their reasons, deletion rules, the deploy-pattern values.
- `docs/phases/phase-9.md` — split C5 into C5a/C5b/C5c in the cluster table (C5a ✅ with today's date, C5b/C5c not started), add a C5a section mirroring the C6 section's shape, with the spec link.
- `docs/plan.md` and `docs/gap-analysis.md` — C5a shipped; C5b and C5c outstanding.
- `CLAUDE.md` — a **Phase 9 sub-project C5a** block beside the C6 block: what shipped, migration `runbooks` (additive, no deploy step), and "what will bite if forgotten": status is stored but everything derived is computed; the invariant and its single enforcement point; C5a refuses only within the runbook and `test_c5a_refuses_only_within_runbook.py` is the guard C5b amends in exactly one test; a Phase 4 webhook must never be refused (C5b's rule, recorded now); `ready_clause` and `allowed_transitions` are held equal by test; minute precision, not `expiry_boundary`; the task stores `system_id` not a `release_system` id; the head-pin literal in `test_pir_backfill_migration.py` is now `runbooks`; whatever the browser pass found. Update the **Next** paragraph's Phase 9 status line.

- [ ] **Step 4: Commit and open the PR**

```bash
git add docs CLAUDE.md
git commit -m "docs(c5a): runbook guides, phase-9 split, plan, gap analysis, CLAUDE.md"
git push -u github feature/phase9-c5-deployment-execution
gh pr create --title "feat: Phase 9 C5a — cutover runbook and execution" --body "<summary of the spec, the three suites' counts, the browser-pass findings>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

(Push and PR only with the owner's go-ahead.)
