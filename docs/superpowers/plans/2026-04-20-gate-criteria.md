# Gate Criteria + Release Overdue Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break each `ReleaseGate` into individually-owned criteria (title, due_date, assignee, notes), auto-complete the gate when all its criteria are done, and expose a per-release overdue count that signals whether a release is late.

**Architecture:** New `gate_criteria` table (1:N under `release_gate`); drop `release_gate.acceptance_criteria`. Criterion lifecycle is `open` ↔ `done` with soft delete. Completing the last open criterion triggers a one-way `ReleaseGate` auto-pass. Overdue is purely computed (`open AND due_date < now()`), never stored. The release list aggregates overdue counts the same way it already aggregates `phase_count` / `scope_count` / `blocker_count`.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Alembic, pytest-asyncio (SQLite in-memory), React 18, Redux Toolkit, MUI v5, TypeScript strict.

**Spec:** `docs/superpowers/specs/2026-04-20-gate-criteria-design.md` — read it first if anything here is unclear.

---

## Conventions (must follow — per `CLAUDE.md`)

- **Tenant scoping:** every query on tenant-scoped tables filters by `current_user.active_tenant_id`. Not `.tenant_id`.
- **Soft delete:** `deleted_at = datetime.now(timezone.utc)`. All queries add `.deleted_at.is_(None)`.
- **Enums:** `native_enum=False` or plain `String(20)`. No PG native ENUMs.
- **Migrations:** write the DDL by hand. Never `alembic revision --autogenerate`.
- **Services:** never call `db.commit()`. Use `db.flush()` to get IDs mid-transaction. `get_db()` auto-commits.
- **Events:** publish via `publish_event(db, event_type, aggregate_id, aggregate_type, payload, tenant_id)` inside the same transaction as the business write.
- **Tests:** SQLite in-memory (`conftest.py`). Use existing fixtures — `db_session`, `tenant`, `user`, `release_lifecycle_template`, `client`, `auth_headers`.
- **Branch:** `feature/gate-criteria` (already created).
- **Commit convention:** `feat:`, `fix:`, `refactor:`, `test:`, `docs:` — per-step commit, no squashing.
- **No push to `main`** — user drives the GitLab MR flow.

## File structure (lock in before writing tasks)

**Backend — create:**
- `backend/app/db/models/gate_criterion.py` — `GateCriterion` SQLAlchemy model
- `backend/app/db/migrations/versions/20260420_1200_p3s4_gate_criteria.py` — Alembic revision
- `backend/app/api/v1/schemas/gate_criterion.py` — Pydantic schemas
- `backend/app/services/gate_criterion_service.py` — CRUD + complete/reopen + overdue query
- `backend/app/api/v1/gate_criteria.py` — router for `/gate-criteria` endpoints + release sub-resource endpoints
- `backend/tests/test_gate_criterion_model.py` — model persistence + cascade tests
- `backend/tests/services/test_gate_criterion_service.py` — service-level including auto-pass edge cases + overdue query
- `backend/tests/test_gate_criteria_api.py` — HTTP integration tests

**Backend — modify:**
- `backend/app/db/models/release_gate.py` — drop `acceptance_criteria` column; add `criteria` relationship
- `backend/app/api/v1/schemas/release_gate.py` — drop `acceptance_criteria` from Create/Update/Read; enrich Read with `criteria` + `overdue_criterion_count`
- `backend/app/api/v1/schemas/release.py` — add `overdue_criterion_count` to `ReleaseListItemRead`
- `backend/app/services/release_gate_service.py` — drop `acceptance_criteria` in create/update; new `maybe_auto_pass_gate` helper; `list_gates` returns criteria + overdue count
- `backend/app/services/release_template_service.py` — when creating a release from template, if a template-gate has `acceptance_criteria`, create one initial criterion on the new gate
- `backend/app/api/v1/releases.py` — `list_releases` aggregates overdue counts; register the new criterion router
- `backend/app/main.py` — include the new router
- `backend/tests/test_release_support_models.py` — remove `acceptance_criteria=` from the gate fixture
- `backend/tests/services/test_release_gate_service.py` — update for new shape
- `backend/tests/test_releases_api.py` — update for new shape
- `backend/tests/integration/test_release_happy_path.py` — update for new shape
- `backend/tests/services/test_release_template_service.py` — adjust assertions re: template → gate seeding
- `backend/tests/test_release_template_model.py` — no behavioural change but sanity check

**Frontend — create:**
- `frontend/src/types/gateCriterion.ts` — TypeScript types
- `frontend/src/components/releases/CriterionRow.tsx` — single-row component
- `frontend/src/components/releases/CriterionDialog.tsx` — create/edit form

**Frontend — modify:**
- `frontend/src/types/release.ts` — drop `acceptance_criteria` from `ReleaseGateResponse`; add `criteria`, `overdue_criterion_count`; add `overdue_criterion_count` to `ReleaseListItemResponse`
- `frontend/src/services/releaseService.ts` — criterion CRUD + complete/reopen + fetch overdue
- `frontend/src/store/releaseSlice.ts` — thunks + reducers for criteria
- `frontend/src/components/releases/GatesTable.tsx` — expandable rows with criteria list + progress + overdue chip; remove acceptance_criteria column
- `frontend/src/components/releases/GateDecisionDialog.tsx` — remove acceptance_criteria display (keep the dialog itself)
- `frontend/src/pages/releases/ReleaseList.tsx` (or wherever list rows render) — overdue badge

> **Out of scope for this plan** (spec references): release template *shape* is unchanged; `ReleaseTemplateForm.tsx` continues to accept `acceptance_criteria` in the template's gate JSON. When a release is created from such a template, the service translates each template-gate's `acceptance_criteria` into a seeded criterion (Task 6). No notification infrastructure. No cross-release "my overdue activities" view. No criterion `in_progress` / `waived` states.

---

## Task 1: `GateCriterion` model + Alembic migration

Removes `release_gate.acceptance_criteria` and creates `gate_criteria`. Updates the tests that persist a gate with `acceptance_criteria` so they still pass.

**Files:**
- Create: `backend/app/db/models/gate_criterion.py`
- Create: `backend/app/db/migrations/versions/20260420_1200_p3s4_gate_criteria.py`
- Modify: `backend/app/db/models/release_gate.py`
- Modify: `backend/tests/test_release_support_models.py:17-22` (remove `acceptance_criteria="Zero Sev1"` from the `ReleaseGate(...)` fixture)
- Create: `backend/tests/test_gate_criterion_model.py`

- [ ] **Step 1: Write the failing model test**

Create `backend/tests/test_gate_criterion_model.py`:

```python
from datetime import datetime, timezone, timedelta
import pytest

from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.db.models.gate_criterion import GateCriterion


@pytest.mark.asyncio
async def test_gate_criterion_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    gate = ReleaseGate(
        tenant_id=tenant.id, release_id=release.id, name="SIT Exit", status="pending",
    )
    db_session.add(gate); await db_session.flush()

    due = datetime.now(timezone.utc) + timedelta(days=3)
    crit = GateCriterion(
        tenant_id=tenant.id, gate_id=gate.id,
        title="Zero Sev1 defects", notes="blocker list in Jira", due_date=due,
        assigned_to_user_id=user.id, status="open",
    )
    db_session.add(crit); await db_session.flush()

    assert crit.id is not None
    assert crit.status == "open"
    assert crit.completed_at is None
    assert crit.deleted_at is None


@pytest.mark.asyncio
async def test_gate_criterion_defaults(db_session, tenant, user, release_lifecycle_template):
    """Required fields only; status defaults to 'open'."""
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()
    gate = ReleaseGate(tenant_id=tenant.id, release_id=release.id, name="G", status="pending")
    db_session.add(gate); await db_session.flush()

    crit = GateCriterion(tenant_id=tenant.id, gate_id=gate.id, title="Minimal")
    db_session.add(crit); await db_session.flush()

    assert crit.status == "open"
    assert crit.due_date is None
    assert crit.assigned_to_user_id is None
    assert crit.notes is None
```

- [ ] **Step 2: Run it and confirm the failure is `ImportError: GateCriterion`**

Run: `cd backend && uv run pytest tests/test_gate_criterion_model.py -v`
Expected: `ImportError` — model doesn't exist.

- [ ] **Step 3: Create the model**

Create `backend/app/db/models/gate_criterion.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GateCriterion(Base):
    __tablename__ = "gate_criterion"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    gate_id: Mapped[int] = mapped_column(
        ForeignKey("release_gate.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

Note: `id`, `created_at`, `updated_at` come from `Base` (see `app/db/base.py:25-39`).

- [ ] **Step 4: Update `release_gate.py` — drop `acceptance_criteria`, add relationship**

Edit `backend/app/db/models/release_gate.py`. Replace the entire file contents:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReleaseGate(Base):
    __tablename__ = "release_gate"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("test_phase.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    criteria = relationship(
        "GateCriterion",
        primaryjoin="and_(ReleaseGate.id == foreign(GateCriterion.gate_id), "
                   "GateCriterion.deleted_at.is_(None))",
        lazy="noload",
    )
```

The relationship uses `lazy="noload"` so SQLAlchemy doesn't auto-load in async contexts (services use explicit `select()`). The filter keeps soft-deleted criteria out when the relationship is explicitly eager-loaded by a service.

- [ ] **Step 5: Update the model test that uses `acceptance_criteria`**

Edit `backend/tests/test_release_support_models.py` lines 17-22. Replace:

```python
    gate = ReleaseGate(
        tenant_id=tenant.id, release_id=release.id, test_phase_id=phase.id,
        name="SIT Exit", acceptance_criteria="Zero Sev1", status="pending",
    )
```

with:

```python
    gate = ReleaseGate(
        tenant_id=tenant.id, release_id=release.id, test_phase_id=phase.id,
        name="SIT Exit", status="pending",
    )
```

- [ ] **Step 6: Write the Alembic migration**

Create `backend/app/db/migrations/versions/20260420_1200_p3s4_gate_criteria.py`:

```python
"""phase 3 sub-project 4: gate criteria + drop release_gate.acceptance_criteria

Revision ID: p3s4gatecrit
Revises: p3s3releases
Create Date: 2026-04-20 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s4gatecrit"
down_revision: Union[str, None] = "p3s3releases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "gate_criterion"):
        op.create_table(
            "gate_criterion",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("gate_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(250), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["gate_id"], ["release_gate.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assigned_to_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["completed_by_user_id"], ["user.id"]),
        )
        op.create_index("ix_gate_criterion_tenant_gate", "gate_criterion", ["tenant_id", "gate_id"])
        op.create_index(
            "ix_gate_criterion_assignee_status", "gate_criterion",
            ["tenant_id", "assigned_to_user_id", "status"],
        )

    if _column_exists(conn, "release_gate", "acceptance_criteria"):
        op.drop_column("release_gate", "acceptance_criteria")


def downgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "release_gate", "acceptance_criteria"):
        op.add_column("release_gate", sa.Column("acceptance_criteria", sa.Text(), nullable=True))

    if _table_exists(conn, "gate_criterion"):
        op.drop_index("ix_gate_criterion_assignee_status", table_name="gate_criterion")
        op.drop_index("ix_gate_criterion_tenant_gate", table_name="gate_criterion")
        op.drop_table("gate_criterion")
```

- [ ] **Step 7: Run the model tests — new passes, fixture test still passes**

Run: `cd backend && uv run pytest tests/test_gate_criterion_model.py tests/test_release_support_models.py -v`
Expected: all pass.

- [ ] **Step 8: Run the full model-layer suite to catch stray `acceptance_criteria` references**

Run: `cd backend && uv run pytest tests/test_release_model.py tests/test_release_support_models.py tests/test_release_template_model.py tests/test_gate_criterion_model.py -v`
Expected: all pass. If any fail because of the dropped column, note them; we'll fix in later tasks (Tasks 7 and 9).

- [ ] **Step 9: Commit**

```bash
git add backend/app/db/models/gate_criterion.py backend/app/db/models/release_gate.py backend/app/db/migrations/versions/20260420_1200_p3s4_gate_criteria.py backend/tests/test_gate_criterion_model.py backend/tests/test_release_support_models.py
git commit -m "feat(gates): add GateCriterion model; drop acceptance_criteria column"
```

---

## Task 2: Pydantic schemas (criterion + gate updates)

**Files:**
- Create: `backend/app/api/v1/schemas/gate_criterion.py`
- Modify: `backend/app/api/v1/schemas/release_gate.py`
- Modify: `backend/app/api/v1/schemas/release.py`
- Create: `backend/tests/test_gate_criterion_schemas.py`

- [ ] **Step 1: Write the failing schema test**

Create `backend/tests/test_gate_criterion_schemas.py`:

```python
from datetime import datetime, timezone, timedelta

from app.api.v1.schemas.gate_criterion import (
    GateCriterionCreate,
    GateCriterionUpdate,
    GateCriterionRead,
)


def test_create_requires_title_only():
    obj = GateCriterionCreate.model_validate({"title": "Zero Sev1 defects"})
    assert obj.title == "Zero Sev1 defects"
    assert obj.due_date is None
    assert obj.assigned_to_user_id is None
    assert obj.notes is None


def test_create_accepts_all_fields():
    due = datetime.now(timezone.utc) + timedelta(days=1)
    obj = GateCriterionCreate.model_validate({
        "title": "Perf test pass", "notes": "p95 < 200ms",
        "due_date": due.isoformat(), "assigned_to_user_id": 42,
    })
    assert obj.notes == "p95 < 200ms"
    assert obj.assigned_to_user_id == 42


def test_update_accepts_partial():
    obj = GateCriterionUpdate.model_validate({"notes": "updated"})
    assert obj.notes == "updated"
    assert obj.title is None  # unset


def test_read_is_overdue_derived():
    """is_overdue is computed by serializer, not stored."""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    obj = GateCriterionRead.model_validate({
        "id": 1, "gate_id": 2, "title": "late", "notes": None,
        "due_date": past, "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "open", "completed_at": None, "completed_by_user_id": None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })
    assert obj.is_overdue is True


def test_read_done_is_never_overdue():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    obj = GateCriterionRead.model_validate({
        "id": 1, "gate_id": 2, "title": "late-but-done", "notes": None,
        "due_date": past, "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "done", "completed_at": datetime.now(timezone.utc),
        "completed_by_user_id": 7,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })
    assert obj.is_overdue is False


def test_read_null_due_date_is_not_overdue():
    obj = GateCriterionRead.model_validate({
        "id": 1, "gate_id": 2, "title": "no-deadline", "notes": None,
        "due_date": None, "assigned_to_user_id": None, "assigned_to_username": None,
        "status": "open", "completed_at": None, "completed_by_user_id": None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })
    assert obj.is_overdue is False
```

- [ ] **Step 2: Run the test, confirm ImportError**

Run: `cd backend && uv run pytest tests/test_gate_criterion_schemas.py -v`
Expected: `ImportError: cannot import name 'GateCriterionCreate' from 'app.api.v1.schemas.gate_criterion'`.

- [ ] **Step 3: Create the criterion schema module**

Create `backend/app/api/v1/schemas/gate_criterion.py`:

```python
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


class GateCriterionCreate(BaseModel):
    title: str = Field(..., max_length=250)
    notes: Optional[str] = None
    due_date: Optional[datetime] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=250)
    notes: Optional[str] = None
    due_date: Optional[datetime] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    title: str
    notes: Optional[str]
    due_date: Optional[datetime]
    assigned_to_user_id: Optional[int]
    assigned_to_username: Optional[str] = None
    status: str
    completed_at: Optional[datetime]
    completed_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    @computed_field  # exposed as `is_overdue` in JSON
    @property
    def is_overdue(self) -> bool:
        if self.status != "open" or self.due_date is None:
            return False
        return self.due_date < datetime.now(timezone.utc)


class GateCriterionWithGate(GateCriterionRead):
    """List-item variant used by /releases/{id}/overdue-criteria."""
    gate_name: str
```

- [ ] **Step 4: Update `release_gate.py` schema — drop `acceptance_criteria`, enrich Read**

Edit `backend/app/api/v1/schemas/release_gate.py`. Replace the entire file:

```python
# backend/app/api/v1/schemas/release_gate.py
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.schemas.gate_criterion import GateCriterionRead


class ReleaseGateCreate(BaseModel):
    name: str = Field(..., max_length=150)
    test_phase_id: Optional[int] = None


class ReleaseGateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    test_phase_id: Optional[int] = None


class ReleaseGateDecision(BaseModel):
    notes: Optional[str] = None


class ReleaseGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    test_phase_id: Optional[int]
    name: str
    status: str
    decided_by: Optional[int]
    decided_at: Optional[datetime]
    decision_notes: Optional[str]
    criteria: List[GateCriterionRead] = []
    overdue_criterion_count: int = 0
```

- [ ] **Step 5: Update `release.py` schema — add `overdue_criterion_count` to `ReleaseListItemRead`**

Edit `backend/app/api/v1/schemas/release.py`. Replace the `ReleaseListItemRead` class (currently lines 66-70):

```python
class ReleaseListItemRead(ReleaseRead):
    """Extended read schema for list endpoints — includes summary counts."""
    phase_count: int = 0
    scope_count: int = 0
    blocker_count: int = 0
    overdue_criterion_count: int = 0
```

- [ ] **Step 6: Run the schema tests**

Run: `cd backend && uv run pytest tests/test_gate_criterion_schemas.py tests/test_release_schemas.py tests/test_release_subresource_schemas.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/schemas/gate_criterion.py backend/app/api/v1/schemas/release_gate.py backend/app/api/v1/schemas/release.py backend/tests/test_gate_criterion_schemas.py
git commit -m "feat(gates): pydantic schemas for GateCriterion + gate/list enrichment"
```

---

## Task 3: `gate_criterion_service` — CRUD + overdue query

Pure CRUD now; auto-pass and complete/reopen come in Task 4.

**Files:**
- Create: `backend/app/services/gate_criterion_service.py`
- Create: `backend/tests/services/test_gate_criterion_service.py`

- [ ] **Step 1: Write the failing service test**

Create `backend/tests/services/test_gate_criterion_service.py`:

```python
from datetime import datetime, timezone, timedelta
import pytest

from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.api.v1.schemas.gate_criterion import GateCriterionCreate, GateCriterionUpdate
from app.services import gate_criterion_service


async def _make_gate(db, tenant, user, lifecycle_tmpl) -> ReleaseGate:
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=lifecycle_tmpl.id, status="draft", raised_by=user.id,
    )
    db.add(release); await db.flush()
    gate = ReleaseGate(tenant_id=tenant.id, release_id=release.id, name="G", status="pending")
    db.add(gate); await db.flush()
    return gate


@pytest.mark.asyncio
async def test_create_criterion(db_session, tenant, user, release_lifecycle_template):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate_id=gate.id, tenant_id=tenant.id, user_id=user.id,
        data=GateCriterionCreate(title="Zero Sev1"),
    )
    assert crit.id is not None
    assert crit.status == "open"
    assert crit.title == "Zero Sev1"


@pytest.mark.asyncio
async def test_list_criteria_for_gate_excludes_soft_deleted(
    db_session, tenant, user, release_lifecycle_template
):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))
    await gate_criterion_service.delete_criterion(db_session, b.id, tenant.id)

    rows = await gate_criterion_service.list_criteria_for_gate(db_session, gate.id, tenant.id)
    assert [r.id for r in rows] == [a.id]


@pytest.mark.asyncio
async def test_update_edits_fields(db_session, tenant, user, release_lifecycle_template):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    due = datetime.now(timezone.utc) + timedelta(days=1)
    await gate_criterion_service.update_criterion(
        db_session, crit.id, tenant.id,
        GateCriterionUpdate(title="A-rev", notes="more", due_date=due, assigned_to_user_id=user.id),
    )
    await db_session.refresh(crit)
    assert crit.title == "A-rev"
    assert crit.notes == "more"
    assert crit.assigned_to_user_id == user.id


@pytest.mark.asyncio
async def test_tenant_isolation_on_get(db_session, tenant, user, release_lifecycle_template):
    """A criterion from tenant A is 404 when queried as tenant B."""
    from fastapi import HTTPException
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))

    with pytest.raises(HTTPException) as exc_info:
        await gate_criterion_service.get_criterion(db_session, crit.id, tenant_id=99999)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_overdue_for_release(db_session, tenant, user, release_lifecycle_template):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    overdue = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id,
        GateCriterionCreate(title="late", due_date=past))
    _not_due_yet = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id,
        GateCriterionCreate(title="future", due_date=future))
    _no_due_date = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="nodate"))

    rows = await gate_criterion_service.list_overdue_for_release(
        db_session, release_id=gate.release_id, tenant_id=tenant.id)
    assert [r.id for r in rows] == [overdue.id]
```

- [ ] **Step 2: Run the tests — confirm ImportError**

Run: `cd backend && uv run pytest tests/services/test_gate_criterion_service.py -v`
Expected: ImportError for `gate_criterion_service`.

- [ ] **Step 3: Create the service**

Create `backend/app/services/gate_criterion_service.py`:

```python
"""GateCriterion service — CRUD, complete/reopen, overdue query.

Auto-pass of the parent gate is implemented in Task 4. This module stays small
and pure: CRUD + queries. Events are published from the caller's transaction.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.gate_criterion import GateCriterion
from app.db.models.release_gate import ReleaseGate
from app.api.v1.schemas.gate_criterion import GateCriterionCreate, GateCriterionUpdate


async def _get_gate_scoped(
    db: AsyncSession, gate_id: int, tenant_id: int
) -> ReleaseGate:
    gate = (
        await db.execute(
            select(ReleaseGate).where(
                ReleaseGate.id == gate_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if gate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release gate not found")
    return gate


async def get_criterion(
    db: AsyncSession, criterion_id: int, tenant_id: int
) -> GateCriterion:
    crit = (
        await db.execute(
            select(GateCriterion).where(
                GateCriterion.id == criterion_id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if crit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate criterion not found")
    return crit


async def list_criteria_for_gate(
    db: AsyncSession, gate_id: int, tenant_id: int
) -> list[GateCriterion]:
    rows = (
        await db.execute(
            select(GateCriterion).where(
                GateCriterion.gate_id == gate_id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            ).order_by(GateCriterion.id)
        )
    ).scalars().all()
    return list(rows)


async def list_overdue_for_release(
    db: AsyncSession, release_id: int, tenant_id: int
) -> list[GateCriterion]:
    """Overdue = open AND due_date IS NOT NULL AND due_date < now()."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(GateCriterion)
            .join(ReleaseGate, ReleaseGate.id == GateCriterion.gate_id)
            .where(
                ReleaseGate.release_id == release_id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
                GateCriterion.status == "open",
                GateCriterion.due_date.is_not(None),
                GateCriterion.due_date < now,
                ReleaseGate.deleted_at.is_(None),
            ).order_by(GateCriterion.due_date.asc())
        )
    ).scalars().all()
    return list(rows)


async def create_criterion(
    db: AsyncSession,
    gate_id: int,
    tenant_id: int,
    user_id: int,
    data: GateCriterionCreate,
) -> GateCriterion:
    gate = await _get_gate_scoped(db, gate_id, tenant_id)
    crit = GateCriterion(
        tenant_id=tenant_id,
        gate_id=gate.id,
        title=data.title,
        notes=data.notes,
        due_date=data.due_date,
        assigned_to_user_id=data.assigned_to_user_id,
        status="open",
    )
    db.add(crit)
    await db.flush()
    await publish_event(
        db,
        event_type="GateCriterionCreated",
        aggregate_id=crit.id,
        aggregate_type="GateCriterion",
        payload={"id": crit.id, "gate_id": gate.id, "title": crit.title},
        tenant_id=tenant_id,
    )
    return crit


async def update_criterion(
    db: AsyncSession,
    criterion_id: int,
    tenant_id: int,
    data: GateCriterionUpdate,
) -> GateCriterion:
    crit = await get_criterion(db, criterion_id, tenant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(crit, field, value)
    await db.flush()
    return crit


async def delete_criterion(
    db: AsyncSession, criterion_id: int, tenant_id: int
) -> None:
    crit = await get_criterion(db, criterion_id, tenant_id)
    crit.deleted_at = datetime.now(timezone.utc)
    await db.flush()
```

- [ ] **Step 4: Run the service tests**

Run: `cd backend && uv run pytest tests/services/test_gate_criterion_service.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/gate_criterion_service.py backend/tests/services/test_gate_criterion_service.py
git commit -m "feat(gates): gate_criterion_service CRUD + overdue query"
```

---

## Task 4: Complete / reopen + gate auto-pass

**Files:**
- Modify: `backend/app/services/gate_criterion_service.py` (append functions)
- Modify: `backend/app/services/release_gate_service.py` (add `maybe_auto_pass_gate`)
- Modify: `backend/tests/services/test_gate_criterion_service.py` (add auto-pass edges)

- [ ] **Step 1: Write the failing auto-pass tests**

Append to `backend/tests/services/test_gate_criterion_service.py`:

```python
from app.services import release_gate_service


@pytest.mark.asyncio
async def test_complete_criterion_autopasses_single(
    db_session, tenant, user, release_lifecycle_template
):
    """Single-criterion gate: completing the one criterion auto-passes."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))

    await gate_criterion_service.complete_criterion(db_session, crit.id, tenant.id, user.id)
    await db_session.refresh(gate)
    assert gate.status == "passed"
    assert gate.decided_by == user.id
    assert gate.decided_at is not None
    assert gate.decision_notes == "auto: all criteria met"


@pytest.mark.asyncio
async def test_complete_not_last_does_not_autopass(
    db_session, tenant, user, release_lifecycle_template
):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    _b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))

    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id)
    await db_session.refresh(gate)
    assert gate.status == "pending"


@pytest.mark.asyncio
async def test_zero_criteria_gate_does_not_autopass(
    db_session, tenant, user, release_lifecycle_template
):
    """Gate with no criteria rows must stay pending — called via helper directly."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    await release_gate_service.maybe_auto_pass_gate(db_session, gate, tenant.id, user.id)
    await db_session.refresh(gate)
    assert gate.status == "pending"


@pytest.mark.asyncio
async def test_soft_deleted_criterion_ignored_by_autopass(
    db_session, tenant, user, release_lifecycle_template
):
    """A deleted criterion shouldn't block or enable auto-pass."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))
    await gate_criterion_service.delete_criterion(db_session, b.id, tenant.id)

    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id)
    await db_session.refresh(gate)
    assert gate.status == "passed"


@pytest.mark.asyncio
async def test_reopen_after_autopass_does_not_revert_gate(
    db_session, tenant, user, release_lifecycle_template
):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    await gate_criterion_service.complete_criterion(db_session, crit.id, tenant.id, user.id)
    await db_session.refresh(gate)
    assert gate.status == "passed"

    await gate_criterion_service.reopen_criterion(db_session, crit.id, tenant.id)
    await db_session.refresh(gate)
    assert gate.status == "passed"  # one-way
    await db_session.refresh(crit)
    assert crit.status == "open"
    assert crit.completed_at is None
    assert crit.completed_by_user_id is None


@pytest.mark.asyncio
async def test_complete_on_already_passed_gate_does_not_re_emit(
    db_session, tenant, user, release_lifecycle_template
):
    """Completing a criterion on a passed gate is a no-op for gate state."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))

    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id)
    await gate_criterion_service.complete_criterion(db_session, b.id, tenant.id, user.id)
    await db_session.refresh(gate)
    decided_at_first = gate.decided_at
    assert gate.status == "passed"

    # Reopening and re-completing 'a' must NOT bump decided_at again
    await gate_criterion_service.reopen_criterion(db_session, a.id, tenant.id)
    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id)
    await db_session.refresh(gate)
    assert gate.decided_at == decided_at_first
```

- [ ] **Step 2: Run — expect AttributeErrors (complete/reopen/maybe_auto_pass_gate missing)**

Run: `cd backend && uv run pytest tests/services/test_gate_criterion_service.py -v`
Expected: new tests fail with AttributeError.

- [ ] **Step 3: Add `maybe_auto_pass_gate` to `release_gate_service`**

Edit `backend/app/services/release_gate_service.py`. Append (after `override_gate`):

```python
async def maybe_auto_pass_gate(
    db: AsyncSession,
    gate: ReleaseGate,
    tenant_id: int,
    user_id: int,
) -> bool:
    """If the gate is still pending AND has ≥1 non-deleted criterion AND every
    non-deleted criterion is 'done', transition it to passed. Returns True if
    the gate was transitioned. One-way: reopening a criterion later does NOT
    flip the gate back."""
    from app.db.models.gate_criterion import GateCriterion

    if gate.status != "pending":
        return False

    rows = (
        await db.execute(
            select(GateCriterion.status).where(
                GateCriterion.gate_id == gate.id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    if not rows:
        return False  # zero-criteria gate never auto-passes
    if any(s != "done" for s in rows):
        return False

    gate.status = "passed"
    gate.decided_by = user_id
    gate.decided_at = datetime.now(timezone.utc)
    gate.decision_notes = "auto: all criteria met"
    await db.flush()

    await _record_gate_event(
        db, gate, tenant_id, user_id,
        f"Gate '{gate.name}' passed automatically (all criteria met).",
    )
    await publish_event(
        db,
        event_type="GateAutoPassed",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": gate.release_id,
            "name": gate.name,
            "decided_by": user_id,
        },
        tenant_id=tenant_id,
    )
    return True
```

The import lives inside the function to avoid circular imports (`gate_criterion_service` imports `release_gate_service` via the module registry in Task 6).

- [ ] **Step 4: Add `complete_criterion` + `reopen_criterion` to `gate_criterion_service`**

Append to `backend/app/services/gate_criterion_service.py`:

```python
async def complete_criterion(
    db: AsyncSession,
    criterion_id: int,
    tenant_id: int,
    user_id: int,
) -> GateCriterion:
    """Mark a criterion done. If this makes the parent gate have all criteria
    done, auto-pass the gate (one-way)."""
    from app.services import release_gate_service  # lazy to avoid circular

    crit = await get_criterion(db, criterion_id, tenant_id)
    if crit.status == "done":
        return crit  # idempotent

    crit.status = "done"
    crit.completed_at = datetime.now(timezone.utc)
    crit.completed_by_user_id = user_id
    await db.flush()

    await publish_event(
        db,
        event_type="GateCriterionCompleted",
        aggregate_id=crit.id,
        aggregate_type="GateCriterion",
        payload={"id": crit.id, "gate_id": crit.gate_id, "completed_by": user_id},
        tenant_id=tenant_id,
    )

    gate = await release_gate_service._get_gate(db, crit.gate_id, tenant_id)
    await release_gate_service.maybe_auto_pass_gate(db, gate, tenant_id, user_id)
    return crit


async def reopen_criterion(
    db: AsyncSession, criterion_id: int, tenant_id: int
) -> GateCriterion:
    """Set a done criterion back to open. Does NOT flip the gate back to pending."""
    crit = await get_criterion(db, criterion_id, tenant_id)
    if crit.status == "open":
        return crit  # idempotent

    crit.status = "open"
    crit.completed_at = None
    crit.completed_by_user_id = None
    await db.flush()

    await publish_event(
        db,
        event_type="GateCriterionReopened",
        aggregate_id=crit.id,
        aggregate_type="GateCriterion",
        payload={"id": crit.id, "gate_id": crit.gate_id},
        tenant_id=tenant_id,
    )
    return crit
```

- [ ] **Step 5: Run — all auto-pass edge tests must pass**

Run: `cd backend && uv run pytest tests/services/test_gate_criterion_service.py -v`
Expected: all (10+) tests pass.

- [ ] **Step 6: Run the existing release_gate_service tests — ensure no regression on pass/fail/override**

Run: `cd backend && uv run pytest tests/services/test_release_gate_service.py -v`
Expected: all pass. If any fail because the test relied on `acceptance_criteria`, note it (Task 7 fixes those broadly).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/gate_criterion_service.py backend/app/services/release_gate_service.py backend/tests/services/test_gate_criterion_service.py
git commit -m "feat(gates): complete/reopen criterion + auto-pass gate (one-way)"
```

---

## Task 5: API router — criterion endpoints + release sub-resource + list enrichment

**Files:**
- Create: `backend/app/api/v1/gate_criteria.py`
- Modify: `backend/app/main.py` (include router)
- Modify: `backend/app/api/v1/releases.py` (list-releases overdue aggregation; gate listing enrichment; overdue sub-resource)
- Modify: `backend/app/services/release_gate_service.py` (`list_gates` returns with criteria + count)
- Create: `backend/tests/test_gate_criteria_api.py`

- [ ] **Step 1: Write the failing HTTP integration test**

Create `backend/tests/test_gate_criteria_api.py`:

```python
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient


async def _make_release_with_gate(client: AsyncClient, headers: dict) -> tuple[int, int]:
    """Create a release and a gate under it. Returns (release_id, gate_id)."""
    rel = await client.post(
        "/api/v1/releases",
        headers=headers,
        json={"name": "R", "release_type": "Major"},
    )
    assert rel.status_code == 201, rel.text
    rid = rel.json()["id"]

    gate = await client.post(
        f"/api/v1/releases/{rid}/gates",
        headers=headers,
        json={"name": "SIT Exit"},
    )
    assert gate.status_code == 201, gate.text
    return rid, gate.json()["id"]


@pytest.mark.asyncio
async def test_create_list_criterion(client: AsyncClient, auth_headers: dict):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    resp = await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "Zero Sev1"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "Zero Sev1"
    assert data["status"] == "open"
    assert data["is_overdue"] is False

    lst = await client.get(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria", headers=auth_headers,
    )
    assert lst.status_code == 200
    items = lst.json()
    assert len(items) == 1
    assert items[0]["id"] == data["id"]


@pytest.mark.asyncio
async def test_complete_triggers_gate_autopass(client: AsyncClient, auth_headers: dict):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    crit = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "A"},
    )).json()

    resp = await client.post(
        f"/api/v1/gate-criteria/{crit['id']}/complete", headers=auth_headers,
    )
    assert resp.status_code == 200

    # Gate should now be passed (via GET /releases/{rid}/gates)
    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert gates[0]["status"] == "passed"


@pytest.mark.asyncio
async def test_reopen_does_not_revert_gate(client: AsyncClient, auth_headers: dict):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    crit = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "A"},
    )).json()
    await client.post(f"/api/v1/gate-criteria/{crit['id']}/complete", headers=auth_headers)
    await client.post(f"/api/v1/gate-criteria/{crit['id']}/reopen", headers=auth_headers)

    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert gates[0]["status"] == "passed"


@pytest.mark.asyncio
async def test_release_overdue_endpoint(client: AsyncClient, auth_headers: dict):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    overdue = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "late", "due_date": past},
    )).json()
    _future = await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "future"},
    )

    resp = await client.get(f"/api/v1/releases/{rid}/overdue-criteria", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["id"] for r in rows] == [overdue["id"]]
    assert rows[0]["gate_name"] == "SIT Exit"
    assert rows[0]["is_overdue"] is True


@pytest.mark.asyncio
async def test_gate_list_includes_criteria_and_count(
    client: AsyncClient, auth_headers: dict,
):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "late", "due_date": past},
    )
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "ontime"},
    )

    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert len(gates[0]["criteria"]) == 2
    assert gates[0]["overdue_criterion_count"] == 1


@pytest.mark.asyncio
async def test_list_releases_includes_overdue_count(
    client: AsyncClient, auth_headers: dict,
):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "late", "due_date": past},
    )
    releases = (await client.get("/api/v1/releases", headers=auth_headers)).json()
    row = next(r for r in releases if r["id"] == rid)
    assert row["overdue_criterion_count"] == 1
```

- [ ] **Step 2: Run — expect the criterion endpoints to 404 and the list tests to fail on missing keys**

Run: `cd backend && uv run pytest tests/test_gate_criteria_api.py -v`
Expected: failures (endpoints / keys don't exist yet).

- [ ] **Step 3: Create the router**

Create `backend/app/api/v1/gate_criteria.py`:

```python
"""API — gate criteria.

Endpoints:
  POST   /releases/{release_id}/gates/{gate_id}/criteria   — create
  GET    /releases/{release_id}/gates/{gate_id}/criteria   — list for gate
  PUT    /gate-criteria/{criterion_id}                     — edit
  POST   /gate-criteria/{criterion_id}/complete            — mark done (may auto-pass gate)
  POST   /gate-criteria/{criterion_id}/reopen              — back to open
  DELETE /gate-criteria/{criterion_id}                     — soft delete
  GET    /releases/{release_id}/overdue-criteria           — flat overdue list

Auth: all endpoints require get_current_user. No role-gating for v1.
"""
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.core.security import get_current_user
from app.db.models.release_gate import ReleaseGate
from app.db.models.user import User
from app.services import gate_criterion_service, release_service
from app.api.v1.schemas.gate_criterion import (
    GateCriterionCreate,
    GateCriterionUpdate,
    GateCriterionRead,
    GateCriterionWithGate,
)


# Sub-resource router — mounted at /releases
release_sub_router = APIRouter(prefix="/releases", tags=["Gate Criteria"])

# Top-level router — mounted at /gate-criteria
router = APIRouter(prefix="/gate-criteria", tags=["Gate Criteria"])


async def _attach_assignee_username(
    db: AsyncSession, read: GateCriterionRead, user_id: int | None
) -> GateCriterionRead:
    if user_id is None:
        return read
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is not None:
        read.assigned_to_username = u.username
    return read


@release_sub_router.post(
    "/{release_id}/gates/{gate_id}/criteria",
    response_model=GateCriterionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_criterion(
    release_id: int,
    gate_id: int,
    data: GateCriterionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    # Tenant-scope the release to avoid leaking gate existence across tenants.
    await release_service.get_release(db, release_id, tenant_id)
    crit = await gate_criterion_service.create_criterion(
        db, gate_id=gate_id, tenant_id=tenant_id, user_id=current_user.id, data=data,
    )
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(crit), crit.assigned_to_user_id,
    )


@release_sub_router.get(
    "/{release_id}/gates/{gate_id}/criteria",
    response_model=List[GateCriterionRead],
)
async def list_criteria(
    release_id: int,
    gate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await release_service.get_release(db, release_id, tenant_id)
    rows = await gate_criterion_service.list_criteria_for_gate(db, gate_id, tenant_id)
    out: list[GateCriterionRead] = []
    for r in rows:
        out.append(
            await _attach_assignee_username(
                db, GateCriterionRead.model_validate(r), r.assigned_to_user_id,
            )
        )
    return out


@release_sub_router.get(
    "/{release_id}/overdue-criteria",
    response_model=List[GateCriterionWithGate],
)
async def list_overdue(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await release_service.get_release(db, release_id, tenant_id)
    rows = await gate_criterion_service.list_overdue_for_release(db, release_id, tenant_id)
    out: list[GateCriterionWithGate] = []
    for r in rows:
        gate = (await db.execute(
            select(ReleaseGate).where(ReleaseGate.id == r.gate_id)
        )).scalar_one()
        item = GateCriterionWithGate.model_validate({
            **GateCriterionRead.model_validate(r).model_dump(),
            "gate_name": gate.name,
        })
        await _attach_assignee_username(db, item, r.assigned_to_user_id)
        out.append(item)
    return out


@router.put("/{criterion_id}", response_model=GateCriterionRead)
async def update_criterion(
    criterion_id: int,
    data: GateCriterionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    crit = await gate_criterion_service.update_criterion(db, criterion_id, tenant_id, data)
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(crit), crit.assigned_to_user_id,
    )


@router.post("/{criterion_id}/complete", response_model=GateCriterionRead)
async def complete_criterion(
    criterion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    crit = await gate_criterion_service.complete_criterion(
        db, criterion_id, tenant_id, current_user.id,
    )
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(crit), crit.assigned_to_user_id,
    )


@router.post("/{criterion_id}/reopen", response_model=GateCriterionRead)
async def reopen_criterion(
    criterion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    crit = await gate_criterion_service.reopen_criterion(db, criterion_id, tenant_id)
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(crit), crit.assigned_to_user_id,
    )


@router.delete("/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_criterion(
    criterion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await gate_criterion_service.delete_criterion(db, criterion_id, tenant_id)
```

- [ ] **Step 4: Register the routers in `main.py`**

Open `backend/app/main.py` and find the block where other routers are included (look for `app.include_router(` calls for `releases`, `bookings` etc.). Add:

```python
from app.api.v1 import gate_criteria as gate_criteria_api

app.include_router(gate_criteria_api.release_sub_router, prefix="/api/v1")
app.include_router(gate_criteria_api.router, prefix="/api/v1")
```

Confirm the exact pattern by running:

Run: `cd backend && grep -n "include_router" app/main.py | head -20`

Place the new include lines in the same style and alongside the existing release/gate router includes.

- [ ] **Step 5: Enrich `release_gate_service.list_gates` to include criteria + overdue count**

Edit `backend/app/services/release_gate_service.py`. Replace `list_gates` (lines 78-92) with:

```python
async def list_gates(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[dict]:
    """Return gates plus nested criteria + overdue_criterion_count per gate.

    Shape matches ReleaseGateRead + criteria/overdue_criterion_count fields.
    Returned as dicts (not ORM objects) so the API can pass them straight to
    response_model without a second round of attribute hydration.
    """
    from datetime import datetime, timezone
    from app.db.models.gate_criterion import GateCriterion

    gate_rows = (
        await db.execute(
            select(ReleaseGate).where(
                ReleaseGate.release_id == release_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            ).order_by(ReleaseGate.id)
        )
    ).scalars().all()
    if not gate_rows:
        return []

    gate_ids = [g.id for g in gate_rows]
    crit_rows = (
        await db.execute(
            select(GateCriterion).where(
                GateCriterion.gate_id.in_(gate_ids),
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            ).order_by(GateCriterion.id)
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    by_gate: dict[int, list[GateCriterion]] = {gid: [] for gid in gate_ids}
    overdue_count: dict[int, int] = {gid: 0 for gid in gate_ids}
    for c in crit_rows:
        by_gate[c.gate_id].append(c)
        if c.status == "open" and c.due_date is not None and c.due_date < now:
            overdue_count[c.gate_id] += 1

    return [
        {
            "id": g.id, "tenant_id": g.tenant_id, "release_id": g.release_id,
            "test_phase_id": g.test_phase_id, "name": g.name, "status": g.status,
            "decided_by": g.decided_by, "decided_at": g.decided_at,
            "decision_notes": g.decision_notes,
            "criteria": by_gate[g.id],
            "overdue_criterion_count": overdue_count[g.id],
        }
        for g in gate_rows
    ]
```

- [ ] **Step 6: Enrich `list_releases` to include `overdue_criterion_count`**

Edit `backend/app/api/v1/releases.py`. Find the `list_releases` function (should be at or near line 99, contains the phase_counts / scope_counts / gate_counts blocks). After the existing `gate_counts` block, add a new block that aggregates overdue criteria per release, then set the field on the result item.

Locate this block (roughly lines 156-167 currently):
```python
    gate_rows = (
        await db.execute(
            select(ReleaseGate.release_id, func.count(ReleaseGate.id).label("cnt"))
            ...
            .group_by(ReleaseGate.release_id)
        )
    ).all()
    gate_counts = {row.release_id: row.cnt for row in gate_rows}
```

Insert AFTER that block, BEFORE `result = []`:

```python
    # Overdue criterion counts per release
    from datetime import datetime, timezone
    from app.db.models.gate_criterion import GateCriterion
    now = datetime.now(timezone.utc)
    overdue_rows = (
        await db.execute(
            select(ReleaseGate.release_id, func.count(GateCriterion.id).label("cnt"))
            .join(GateCriterion, GateCriterion.gate_id == ReleaseGate.id)
            .where(
                ReleaseGate.release_id.in_(release_ids),
                ReleaseGate.deleted_at.is_(None),
                GateCriterion.deleted_at.is_(None),
                GateCriterion.status == "open",
                GateCriterion.due_date.is_not(None),
                GateCriterion.due_date < now,
            )
            .group_by(ReleaseGate.release_id)
        )
    ).all()
    overdue_counts = {row.release_id: row.cnt for row in overdue_rows}
```

Then, in the final `for r in releases:` loop, add the line setting `item.overdue_criterion_count`:

```python
        item.overdue_criterion_count = overdue_counts.get(r.id, 0)
```

- [ ] **Step 7: Run the API integration tests**

Run: `cd backend && uv run pytest tests/test_gate_criteria_api.py -v`
Expected: all 6 pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/gate_criteria.py backend/app/main.py backend/app/services/release_gate_service.py backend/app/api/v1/releases.py backend/tests/test_gate_criteria_api.py
git commit -m "feat(gates): criterion API + overdue counts on gate list and release list"
```

---

## Task 6: Template → gate seed (preserve `acceptance_criteria` intent)

When a release is created from a `ReleaseTemplate` whose `gates` JSON has `acceptance_criteria` strings, seed one criterion per gate with that text as the criterion's `notes` (title fixed).

**Files:**
- Modify: `backend/app/services/release_template_service.py` — find the create-from-template flow; after each gate is created, if the template's gate entry has a non-empty `acceptance_criteria`, create a single criterion.
- Modify: `backend/tests/services/test_release_template_service.py` — add assertion that the criterion was seeded.

- [ ] **Step 1: Find the template-apply code**

Run: `cd backend && grep -n "acceptance_criteria\|ReleaseGate(" app/services/release_template_service.py`

Note the line where the gate is inserted (look for `db.add(ReleaseGate(...))` or `ReleaseGate(...)`). The plan assumes it is currently doing `acceptance_criteria=g.get("acceptance_criteria")` — which will break once the model drops the column. You MUST update that call to stop passing `acceptance_criteria` AND also seed a criterion with the old text.

- [ ] **Step 2: Modify the template-apply loop**

Replace the gate-insertion block (in whichever function performs the apply — likely `create_release_from_template` or similar). Starting from the existing logic that constructs the gate, change it to:

1. Stop passing `acceptance_criteria` to `ReleaseGate(...)`.
2. After `db.flush()` on the gate, if the template gate dict has a non-empty `acceptance_criteria` string, create a single `GateCriterion` via `gate_criterion_service.create_criterion(...)`.

Example shape (adapt to the real function name and loop variable):

```python
from app.services import gate_criterion_service
from app.api.v1.schemas.gate_criterion import GateCriterionCreate

# ... inside the per-gate loop:
gate = ReleaseGate(
    tenant_id=tenant_id,
    release_id=release.id,
    test_phase_id=g.get("test_phase_id"),
    name=g["name"],
    status="pending",
)
db.add(gate)
await db.flush()

seed_text = (g.get("acceptance_criteria") or "").strip()
if seed_text:
    await gate_criterion_service.create_criterion(
        db,
        gate_id=gate.id,
        tenant_id=tenant_id,
        user_id=user_id,
        data=GateCriterionCreate(
            title="Acceptance criteria",
            notes=seed_text,
        ),
    )
```

If the service function doesn't already have `user_id` in scope, thread it through from the caller (the caller is an endpoint in `releases.py` that already has `current_user.id`).

- [ ] **Step 3: Update the template-service test**

Open `backend/tests/services/test_release_template_service.py`. Find the test that creates a release from a template and asserts something about `acceptance_criteria` on the gate. Replace that assertion with:

```python
from app.services import gate_criterion_service

# ...after the release is created from the template:
gate = (await db_session.execute(
    select(ReleaseGate).where(ReleaseGate.release_id == release.id)
)).scalar_one()
assert not hasattr(gate, "acceptance_criteria")  # column gone

crits = await gate_criterion_service.list_criteria_for_gate(db_session, gate.id, tenant.id)
assert len(crits) == 1
assert crits[0].title == "Acceptance criteria"
assert crits[0].notes == "<the text that was in the template's gate acceptance_criteria>"
```

Adjust the literal text to match whatever the fixture uses. Don't over-assert shape; just that the seed happened.

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/services/test_release_template_service.py tests/services/test_release_gate_service.py -v`
Expected: all pass. Any failures in `test_release_gate_service.py` about `acceptance_criteria` are fixed here OR in Task 7 — trace each one.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_template_service.py backend/tests/services/test_release_template_service.py
git commit -m "feat(releases): seed gate criterion from template acceptance_criteria text"
```

---

## Task 7: Sweep remaining `acceptance_criteria` references in tests + service test

Targets all files found by `grep -rn "acceptance_criteria" backend/tests/ backend/app/services/` that haven't been touched yet.

**Files to check (diff and fix each):**
- `backend/tests/test_releases_api.py`
- `backend/tests/integration/test_release_happy_path.py`
- `backend/tests/services/test_release_gate_service.py`

- [ ] **Step 1: Run the current grep**

Run: `cd backend && grep -rn "acceptance_criteria" tests/ app/services/ app/api/ | grep -v migrations/`
Expected: list of remaining references.

- [ ] **Step 2: For each remaining reference, apply one of these rules**

Rule A — **Gate create payload in a test** (e.g. `json={"name": "x", "acceptance_criteria": "..."}`):
- Remove the `acceptance_criteria` key from the payload. The schema no longer accepts it.

Rule B — **Assertion that a gate's `acceptance_criteria` equals a value** (e.g. `assert gate["acceptance_criteria"] == "..."`):
- Delete the assertion. If the test's point was "the text survived round-trip", consider replacing with an assertion that a criterion with that text exists (only if the flow was template→gate — otherwise the old text was always user-entered and doesn't belong).

Rule C — **Direct model instantiation with `acceptance_criteria=`:**
- Remove the kwarg.

Rule D — **Service call passing `acceptance_criteria`** (e.g. `ReleaseGateCreate(acceptance_criteria=...)`):
- Remove the field from the payload.

- [ ] **Step 3: Apply each fix, one file at a time, committing nothing yet**

For each file, open it, remove the offending `acceptance_criteria` reference, and save. Prefer the Edit tool — do NOT rewrite whole files.

- [ ] **Step 4: Re-run grep — must be clean (excluding migrations file)**

Run: `cd backend && grep -rn "acceptance_criteria" tests/ app/services/ app/api/ | grep -v migrations/`
Expected: no lines.

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass (424+ previously; will rise by ~15-20 from new tests). If anything fails, trace it — do not mark green by suppressing.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/ backend/app/services/release_gate_service.py
git commit -m "refactor(tests): remove acceptance_criteria references from gate tests"
```

---

## Task 8: Frontend types + service client

**Files:**
- Create: `frontend/src/types/gateCriterion.ts`
- Modify: `frontend/src/types/release.ts`
- Modify: `frontend/src/services/releaseService.ts`

- [ ] **Step 1: Create `gateCriterion.ts`**

Create `frontend/src/types/gateCriterion.ts`:

```ts
export type GateCriterionStatus = 'open' | 'done';

export interface GateCriterion {
  id: number;
  gate_id: number;
  title: string;
  notes: string | null;
  due_date: string | null;
  assigned_to_user_id: number | null;
  assigned_to_username: string | null;
  status: GateCriterionStatus;
  completed_at: string | null;
  completed_by_user_id: number | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
}

export interface GateCriterionWithGate extends GateCriterion {
  gate_name: string;
}

export interface GateCriterionCreatePayload {
  title: string;
  notes?: string | null;
  due_date?: string | null;
  assigned_to_user_id?: number | null;
}

export interface GateCriterionUpdatePayload {
  title?: string;
  notes?: string | null;
  due_date?: string | null;
  assigned_to_user_id?: number | null;
}
```

- [ ] **Step 2: Update `release.ts`**

Edit `frontend/src/types/release.ts`:

Change the existing `ReleaseGateResponse` (around lines 41-52) to:

```ts
import type { GateCriterion } from './gateCriterion';

export interface ReleaseGateResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  test_phase_id: number | null;
  name: string;
  status: 'pending' | 'passed' | 'failed' | 'overridden';
  decided_by: number | null;
  decided_at: string | null;
  decision_notes: string | null;
  criteria: GateCriterion[];
  overdue_criterion_count: number;
}
```

Change `ReleaseGateCreatePayload` (around line 141) — remove `acceptance_criteria`:

```ts
export interface ReleaseGateCreatePayload {
  name: string;
  test_phase_id?: number | null;
}
```

Change `ReleaseGateUpdatePayload` similarly.

Find `ReleaseListItemResponse` (around line 24) and add `overdue_criterion_count: number;`.

- [ ] **Step 3: Add criterion methods to `releaseService.ts`**

Edit `frontend/src/services/releaseService.ts`. Add methods (inside the existing service object/class):

```ts
import type {
  GateCriterion,
  GateCriterionWithGate,
  GateCriterionCreatePayload,
  GateCriterionUpdatePayload,
} from '../types/gateCriterion';

// ...inside the releaseService methods:

async listCriteria(releaseId: number, gateId: number): Promise<GateCriterion[]> {
  const { data } = await api.get(`/releases/${releaseId}/gates/${gateId}/criteria`);
  return data;
},

async createCriterion(
  releaseId: number,
  gateId: number,
  payload: GateCriterionCreatePayload,
): Promise<GateCriterion> {
  const { data } = await api.post(
    `/releases/${releaseId}/gates/${gateId}/criteria`, payload,
  );
  return data;
},

async updateCriterion(
  criterionId: number,
  payload: GateCriterionUpdatePayload,
): Promise<GateCriterion> {
  const { data } = await api.put(`/gate-criteria/${criterionId}`, payload);
  return data;
},

async completeCriterion(criterionId: number): Promise<GateCriterion> {
  const { data } = await api.post(`/gate-criteria/${criterionId}/complete`);
  return data;
},

async reopenCriterion(criterionId: number): Promise<GateCriterion> {
  const { data } = await api.post(`/gate-criteria/${criterionId}/reopen`);
  return data;
},

async deleteCriterion(criterionId: number): Promise<void> {
  await api.delete(`/gate-criteria/${criterionId}`);
},

async listReleaseOverdueCriteria(releaseId: number): Promise<GateCriterionWithGate[]> {
  const { data } = await api.get(`/releases/${releaseId}/overdue-criteria`);
  return data;
},
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck 2>&1 | tail -20`
Expected: exit 0 — no type errors. If the existing project script isn't `typecheck`, use whichever is configured (`tsc --noEmit`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/gateCriterion.ts frontend/src/types/release.ts frontend/src/services/releaseService.ts
git commit -m "feat(gates): frontend types + API client for gate criteria"
```

---

## Task 9: Redux slice — thunks for criteria

**Files:**
- Modify: `frontend/src/store/releaseSlice.ts`

- [ ] **Step 1: Add thunks to the release slice**

Edit `frontend/src/store/releaseSlice.ts`. Add at the top of the thunks section:

```ts
import type {
  GateCriterion,
  GateCriterionCreatePayload,
  GateCriterionUpdatePayload,
} from '../types/gateCriterion';

export const createCriterion = createAsyncThunk(
  'release/createCriterion',
  async (args: { releaseId: number; gateId: number; payload: GateCriterionCreatePayload }) =>
    releaseService.createCriterion(args.releaseId, args.gateId, args.payload),
);

export const updateCriterion = createAsyncThunk(
  'release/updateCriterion',
  async (args: { criterionId: number; payload: GateCriterionUpdatePayload }) =>
    releaseService.updateCriterion(args.criterionId, args.payload),
);

export const completeCriterion = createAsyncThunk(
  'release/completeCriterion',
  async (criterionId: number) => releaseService.completeCriterion(criterionId),
);

export const reopenCriterion = createAsyncThunk(
  'release/reopenCriterion',
  async (criterionId: number) => releaseService.reopenCriterion(criterionId),
);

export const deleteCriterion = createAsyncThunk(
  'release/deleteCriterion',
  async (criterionId: number) => {
    await releaseService.deleteCriterion(criterionId);
    return criterionId;
  },
);
```

- [ ] **Step 2: Add reducers that update the gates array in slice state**

Inside the slice's `extraReducers`, add cases that locate the gate containing the affected criterion and mutate its `criteria` array. Skeleton (adapt to the slice's existing state shape):

```ts
builder
  .addCase(createCriterion.fulfilled, (state, action) => {
    const crit = action.payload;
    const gate = state.gates?.find((g) => g.id === crit.gate_id);
    if (gate) gate.criteria.push(crit);
  })
  .addCase(updateCriterion.fulfilled, (state, action) => {
    const crit = action.payload;
    const gate = state.gates?.find((g) => g.id === crit.gate_id);
    if (!gate) return;
    const i = gate.criteria.findIndex((c) => c.id === crit.id);
    if (i >= 0) gate.criteria[i] = crit;
  })
  .addCase(completeCriterion.fulfilled, (state, action) => {
    const crit = action.payload;
    const gate = state.gates?.find((g) => g.id === crit.gate_id);
    if (!gate) return;
    const i = gate.criteria.findIndex((c) => c.id === crit.id);
    if (i >= 0) gate.criteria[i] = crit;
    // Auto-pass may have flipped gate.status — re-fetch via listGates thunk if UI needs it.
  })
  .addCase(reopenCriterion.fulfilled, (state, action) => {
    const crit = action.payload;
    const gate = state.gates?.find((g) => g.id === crit.gate_id);
    if (!gate) return;
    const i = gate.criteria.findIndex((c) => c.id === crit.id);
    if (i >= 0) gate.criteria[i] = crit;
  })
  .addCase(deleteCriterion.fulfilled, (state, action) => {
    const criterionId = action.payload;
    state.gates?.forEach((gate) => {
      gate.criteria = gate.criteria.filter((c) => c.id !== criterionId);
    });
  });
```

After `completeCriterion.fulfilled`, the UI should dispatch the existing `fetchGates(releaseId)` thunk to pick up the auto-pass change — do this from the calling component (see Task 10).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck 2>&1 | tail -20`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/store/releaseSlice.ts
git commit -m "feat(gates): redux slice thunks and reducers for gate criteria"
```

---

## Task 10: Frontend components — `CriterionRow`, `CriterionDialog`, `GatesTable` expansion, release list overdue badge

**Files:**
- Create: `frontend/src/components/releases/CriterionRow.tsx`
- Create: `frontend/src/components/releases/CriterionDialog.tsx`
- Modify: `frontend/src/components/releases/GatesTable.tsx`
- Modify: `frontend/src/components/releases/GateDecisionDialog.tsx`
- Modify: the release-list page (look for where `ReleaseListItemResponse` is rendered; likely `frontend/src/pages/releases/ReleaseList.tsx`)

- [ ] **Step 1: Create `CriterionRow.tsx`**

Create `frontend/src/components/releases/CriterionRow.tsx`:

```tsx
import { Box, Checkbox, Chip, IconButton, Stack, Typography } from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import type { GateCriterion } from '../../types/gateCriterion';

interface Props {
  criterion: GateCriterion;
  onToggle: (criterion: GateCriterion) => void;
  onEdit: (criterion: GateCriterion) => void;
  onDelete: (criterion: GateCriterion) => void;
}

export default function CriterionRow({ criterion, onToggle, onEdit, onDelete }: Props) {
  const due = criterion.due_date ? new Date(criterion.due_date).toLocaleDateString() : null;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', py: 0.5, pl: 4, gap: 1 }}>
      <Checkbox
        size="small"
        checked={criterion.status === 'done'}
        onChange={() => onToggle(criterion)}
        inputProps={{ 'aria-label': `Complete ${criterion.title}` }}
      />
      <Typography
        variant="body2"
        sx={{
          flex: 1,
          textDecoration: criterion.status === 'done' ? 'line-through' : 'none',
        }}
      >
        {criterion.title}
      </Typography>
      {due && (
        <Chip
          size="small"
          label={due}
          color={criterion.is_overdue ? 'error' : 'default'}
          variant={criterion.is_overdue ? 'filled' : 'outlined'}
        />
      )}
      {criterion.assigned_to_username && (
        <Chip size="small" label={criterion.assigned_to_username} variant="outlined" />
      )}
      <Stack direction="row">
        <IconButton size="small" onClick={() => onEdit(criterion)} aria-label="edit">
          <EditIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" onClick={() => onDelete(criterion)} aria-label="delete">
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Stack>
    </Box>
  );
}
```

- [ ] **Step 2: Create `CriterionDialog.tsx`**

Create `frontend/src/components/releases/CriterionDialog.tsx`:

```tsx
import { useEffect, useState } from 'react';
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle,
  Stack, TextField, MenuItem,
} from '@mui/material';
import type {
  GateCriterion, GateCriterionCreatePayload, GateCriterionUpdatePayload,
} from '../../types/gateCriterion';

interface User { id: number; username: string }

interface Props {
  open: boolean;
  initial?: GateCriterion | null;
  users: User[];
  onClose: () => void;
  onSubmit: (payload: GateCriterionCreatePayload | GateCriterionUpdatePayload) => void;
}

export default function CriterionDialog({ open, initial, users, onClose, onSubmit }: Props) {
  const [title, setTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [assignee, setAssignee] = useState<number | ''>('');

  useEffect(() => {
    setTitle(initial?.title ?? '');
    setNotes(initial?.notes ?? '');
    setDueDate(initial?.due_date ? initial.due_date.slice(0, 16) : '');
    setAssignee(initial?.assigned_to_user_id ?? '');
  }, [initial, open]);

  const handleSubmit = () => {
    onSubmit({
      title: title.trim(),
      notes: notes.trim() || null,
      due_date: dueDate ? new Date(dueDate).toISOString() : null,
      assigned_to_user_id: assignee === '' ? null : Number(assignee),
    });
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{initial ? 'Edit criterion' : 'Add criterion'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Title" value={title} onChange={(e) => setTitle(e.target.value)}
            required fullWidth inputProps={{ maxLength: 250 }}
          />
          <TextField
            label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)}
            multiline rows={3} fullWidth
          />
          <TextField
            label="Due date" type="datetime-local" value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            InputLabelProps={{ shrink: true }} fullWidth
          />
          <TextField
            label="Assignee" select value={assignee}
            onChange={(e) => setAssignee(e.target.value === '' ? '' : Number(e.target.value))}
            fullWidth
          >
            <MenuItem value="">(unassigned)</MenuItem>
            {users.map((u) => (
              <MenuItem key={u.id} value={u.id}>{u.username}</MenuItem>
            ))}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!title.trim()} onClick={handleSubmit}>
          {initial ? 'Save' : 'Add'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 3: Update `GatesTable.tsx`**

Edit `frontend/src/components/releases/GatesTable.tsx`. Changes:

1. Remove the `acceptance_criteria` column and its references.
2. Add an expand/collapse affordance per row (MUI `IconButton` with chevron).
3. When expanded, render a stack of `<CriterionRow>` items plus an "Add criterion" button that opens `CriterionDialog`.
4. Show a progress chip on the gate row: `"{done}/{total} done"`. If `overdue_criterion_count > 0`, show a red chip `"{overdue_criterion_count} overdue"`.
5. After `completeCriterion` or `reopenCriterion` dispatches fulfil, dispatch the existing `fetchGates(releaseId)` thunk so the gate's `status` reflects any auto-pass.

Because this file already exists and has non-trivial structure, edit it in place with the Edit tool, keeping the existing action buttons (Decide / Delete) and table header intact.

- [ ] **Step 4: Update `GateDecisionDialog.tsx`**

The existing dialog displays `acceptance_criteria` somewhere. Open the file, remove any rendering of the field (search for `acceptance_criteria` in the file). The dialog itself (pass/fail/override buttons + notes textarea) stays.

- [ ] **Step 5: Add overdue badge to release list rows**

Find the release list rendering component. Run:

Run: `cd frontend && grep -rn "blocker_count" src/pages src/components | head -10`

Open whatever component renders `blocker_count`. Add next to it, in the same row, a chip:

```tsx
{release.overdue_criterion_count > 0 && (
  <Chip
    size="small"
    color="error"
    label={`${release.overdue_criterion_count} overdue`}
  />
)}
```

- [ ] **Step 6: Typecheck + run dev server + manually click through**

Run: `cd frontend && npm run typecheck 2>&1 | tail -20`
Expected: exit 0.

Then: start the dev server (`npm run dev`) and the backend (`cd backend && uv run uvicorn app.main:app --reload`). Log in as `admin` / `admin123` (tenant: `demo`). Create a release, add a gate, expand it, add two criteria — one with a past due date, one without. Confirm:
- Past-due criterion shows red chip.
- Completing both auto-passes the gate (gate row shows green status).
- Release list shows `1 overdue` chip before completion, disappears after.

Screenshot the happy path OR capture browser console for any warnings.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/releases/CriterionRow.tsx frontend/src/components/releases/CriterionDialog.tsx frontend/src/components/releases/GatesTable.tsx frontend/src/components/releases/GateDecisionDialog.tsx frontend/src/pages/
git commit -m "feat(gates): expandable gate rows with criteria; overdue badges on release list"
```

---

## Task 11: Push branch

- [ ] **Step 1: Push**

```bash
git push -u origin feature/gate-criteria
```

- [ ] **Step 2: Report the branch name + commits to the user.**

Do NOT open an MR — user drives the GitLab MR flow.

---

## Self-review

**Spec coverage:**
- Model fields ✓ (Task 1) — title, notes, due_date, assigned_to_user_id, status, completed_at, completed_by_user_id, deleted_at.
- Drop `acceptance_criteria` column ✓ (Task 1 migration + Tasks 2/6/7 for downstream cleanup).
- Auto-pass rule + zero-criteria + soft-deleted cases ✓ (Task 4).
- One-way auto-pass ✓ (Task 4 `test_reopen_after_autopass_does_not_revert_gate`).
- Overdue computation ✓ (Task 3 `list_overdue_for_release` + Task 2 serializer `is_overdue`).
- Per-release overdue count ✓ (Task 5 Step 6 — aggregated on release list).
- API surface ✓ (Task 5 — all 7 endpoints from the spec).
- Events emitted ✓ (Tasks 3/4 — `GateCriterionCreated`, `GateCriterionCompleted`, `GateCriterionReopened`, `GateAutoPassed`).
- Auth = `get_current_user`, no role gating ✓ (Task 5 router — no `require_role`).
- Template → gate seed ✓ (Task 6).
- Frontend types + service + slice + components + release list badge ✓ (Tasks 8-10).

**Placeholder scan:** no TBD/TODO. All code blocks complete. "Adapt to the slice's existing state shape" in Task 9 step 2 is the only adaptive instruction — it's explicitly labelled because the slice file isn't fully-shown in the plan; the skeleton is complete enough to transcribe.

**Type consistency:**
- Python: `GateCriterionCreate`, `GateCriterionUpdate`, `GateCriterionRead`, `GateCriterionWithGate` consistent across Task 2 schema, Task 3 service, Task 5 router.
- TypeScript: `GateCriterion`, `GateCriterionCreatePayload`, `GateCriterionUpdatePayload`, `GateCriterionWithGate` consistent across Task 8 types, Task 8 service, Task 9 slice, Task 10 components.
- Field name `assigned_to_user_id` is the same on both sides; `assigned_to_username` is a computed response-only field populated in the service and typed optional on the frontend.
- Event names match spec: `GateCriterionCreated`, `GateCriterionCompleted`, `GateCriterionReopened`, `GateAutoPassed`.

**Explicit scope check:** no `in_progress`/`waived` states, no notifications, no gate-level due_date, no global "my overdue" view — all deferred in spec and absent from plan.
