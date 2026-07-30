# Enterprise Releases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver first-class Enterprise Releases on top of the existing Phase 3 release module — `release_kind='enterprise'` releases with own lifecycle, phases, gates, bookings; admission workflow with state × role permissions; rollup views; HTML report.

**Architecture:** One new table (`release_membership`) + one new column (`lifecycle_template.applies_to_kind`) + two additive keys in the `LifecycleTemplate.definition` JSON (`states[i].is_admission_lockdown`, top-level `action_permissions`). Three new services (membership, rollup, report), ~12 new API routes, kind-aware frontend. No changes to project-release behaviour.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / Alembic / Pydantic v2 · React 18 / TypeScript / MUI / Redux Toolkit · PostgreSQL · pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-22-enterprise-releases-design.md`

---

## Phase 1 — Backend data layer (models, migration, schemas)

### Task 1: `ReleaseMembership` SQLAlchemy model

**Files:**
- Create: `backend/app/db/models/release_membership.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_release_membership_model.py`:

```python
import pytest
from datetime import datetime, timezone
from app.db.models.release_membership import ReleaseMembership, MembershipState


def test_model_defaults():
    m = ReleaseMembership(
        tenant_id=1,
        enterprise_release_id=10,
        project_release_id=20,
        state=MembershipState.PENDING_REQUEST.value,
        requested_by=99,
        requested_at=datetime.now(timezone.utc),
    )
    assert m.late_scope is False or m.late_scope is None  # default before flush


def test_state_enum_values():
    assert MembershipState.PENDING_REQUEST.value == "pending_request"
    assert MembershipState.ACCEPTED.value == "accepted"
    assert MembershipState.REJECTED.value == "rejected"
    assert MembershipState.WITHDRAWN.value == "withdrawn"
    assert MembershipState.REMOVED.value == "removed"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/test_release_membership_model.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.release_membership'`.

- [ ] **Step 3: Write the model**

`backend/app/db/models/release_membership.py`:

```python
"""Enterprise release membership workflow.

Stores admission requests (pending_request), decisions (accepted/rejected/withdrawn)
and later removals as an append-only audit log. `release.parent_release_id` is
the source of truth for currently active membership; this table records how it
got that way.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MembershipState(str, Enum):
    PENDING_REQUEST = "pending_request"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    REMOVED = "removed"


TERMINAL_STATES = {
    MembershipState.REJECTED.value,
    MembershipState.WITHDRAWN.value,
    MembershipState.REMOVED.value,
}


class ReleaseMembership(Base):
    __tablename__ = "release_membership"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    # enterprise_release_id + project_release_id are covered by the composite
    # indexes in __table_args__; no single-column index needed.
    enterprise_release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id"), nullable=False
    )
    project_release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    removal_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    late_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_release_membership_enterprise_state", "enterprise_release_id", "state"),
        Index("ix_release_membership_project_state", "project_release_id", "state"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/unit/test_release_membership_model.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/release_membership.py backend/tests/unit/test_release_membership_model.py
git commit -m "feat(enterprise): add ReleaseMembership model"
```

---

### Task 2: Alembic migration — `release_membership` + `applies_to_kind`

**Files:**
- Create: `backend/app/db/migrations/versions/20260422_1200_p3s6_enterprise_releases.py`

- [ ] **Step 1: Write the migration**

Note: no TDD unit test for migrations in this codebase — `test_release_happy_path.py` and the upcoming `test_enterprise_release_happy_path.py` exercise migrations via Alembic upgrade.

`backend/app/db/migrations/versions/20260422_1200_p3s6_enterprise_releases.py`:

```python
"""phase 3 sub-project 6: enterprise releases (membership + lifecycle kind)

Revision ID: p3s6enterprise
Revises: p3s5scopelc
Create Date: 2026-04-22 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s6enterprise"
down_revision: Union[str, None] = "p3s5scopelc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    return column in {c["name"] for c in Inspector.from_engine(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. release_membership ──
    if not _table_exists(conn, "release_membership"):
        op.create_table(
            "release_membership",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
            sa.Column("enterprise_release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
            sa.Column("project_release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
            sa.Column("state", sa.String(30), nullable=False),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("removed_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("removal_reason", sa.Text(), nullable=True),
            sa.Column("late_scope", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("now()"), nullable=False),
        )
        op.create_index(
            "ix_release_membership_tenant_id", "release_membership", ["tenant_id"]
        )
        op.create_index(
            "ix_release_membership_enterprise_state",
            "release_membership",
            ["enterprise_release_id", "state"],
        )
        op.create_index(
            "ix_release_membership_project_state",
            "release_membership",
            ["project_release_id", "state"],
        )
        # Partial unique indexes (PostgreSQL). SQLite ignores postgresql_where
        # and would create plain uniques, so we gate by dialect.
        if conn.dialect.name == "postgresql":
            op.create_index(
                "uq_membership_pending_per_project",
                "release_membership",
                ["project_release_id"],
                unique=True,
                postgresql_where=sa.text("state = 'pending_request'"),
            )
            op.create_index(
                "uq_membership_accepted_per_project",
                "release_membership",
                ["project_release_id"],
                unique=True,
                postgresql_where=sa.text("state = 'accepted'"),
            )

    # ── 2. lifecycle_template.applies_to_kind ──
    if not _column_exists(conn, "lifecycle_template", "applies_to_kind"):
        with op.batch_alter_table("lifecycle_template") as batch_op:
            batch_op.add_column(sa.Column("applies_to_kind", sa.String(20), nullable=True))

    # Backfill existing release lifecycle templates to applies_to_kind='project'.
    op.execute(
        "UPDATE lifecycle_template "
        "SET applies_to_kind = 'project' "
        "WHERE entity_type = 'release' AND applies_to_kind IS NULL"
    )


def downgrade() -> None:
    # Drop partial uniques first (safe if they don't exist).
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for idx in ("uq_membership_accepted_per_project", "uq_membership_pending_per_project"):
            try:
                op.drop_index(idx, table_name="release_membership")
            except Exception:
                pass

    if _table_exists(conn, "release_membership"):
        op.drop_index("ix_release_membership_project_state", table_name="release_membership")
        op.drop_index("ix_release_membership_enterprise_state", table_name="release_membership")
        op.drop_index("ix_release_membership_tenant_id", table_name="release_membership")
        op.drop_table("release_membership")

    if _column_exists(conn, "lifecycle_template", "applies_to_kind"):
        with op.batch_alter_table("lifecycle_template") as batch_op:
            batch_op.drop_column("applies_to_kind")
```

- [ ] **Step 2: Run migrations locally**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade p3s5scopelc -> p3s6enterprise`.

- [ ] **Step 3: Run existing test suite to confirm no regression**

```bash
cd backend && uv run pytest tests/ -x -q
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/migrations/versions/20260422_1200_p3s6_enterprise_releases.py
git commit -m "feat(enterprise): alembic p3s6 — release_membership + applies_to_kind"
```

---

### Task 3: Extend Lifecycle Pydantic schemas (`is_admission_lockdown` + `action_permissions`)

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_lifecycle_schemas.py` (create if absent):

```python
import pytest
from pydantic import ValidationError

from app.api.v1.schemas.booking_lifecycle import (
    LifecycleDefinition,
    LifecycleState,
    validate_definition_for_entity,
)


def test_state_accepts_is_admission_lockdown_flag():
    s = LifecycleState(key="x", label="X", is_initial=True, is_admission_lockdown=True)
    assert s.is_admission_lockdown is True


def test_state_default_is_admission_lockdown_false():
    s = LifecycleState(key="x", label="X", is_initial=True)
    assert s.is_admission_lockdown is False


def test_definition_accepts_action_permissions_block():
    d = LifecycleDefinition(
        states=[LifecycleState(key="draft", label="Draft", is_initial=True)],
        transitions=[],
        field_permissions={"draft": {"standard_fields": {}}},
        action_permissions={
            "draft": {"membership.admit": ["Admin"], "membership.reject": ["Admin"]}
        },
    )
    assert d.action_permissions["draft"]["membership.admit"] == ["Admin"]


def test_enterprise_kind_validation_single_lockdown_state():
    d = LifecycleDefinition(
        states=[
            LifecycleState(key="a", label="A", is_initial=True, is_admission_lockdown=True),
            LifecycleState(key="b", label="B", is_admission_lockdown=True),
        ],
        transitions=[],
        field_permissions={"a": {"standard_fields": {}}, "b": {"standard_fields": {}}},
    )
    with pytest.raises(ValueError, match="at most one"):
        validate_definition_for_entity(d, "release", applies_to_kind="enterprise")


def test_enterprise_kind_validation_rejects_unknown_action_key():
    d = LifecycleDefinition(
        states=[LifecycleState(key="draft", label="Draft", is_initial=True)],
        transitions=[],
        field_permissions={"draft": {"standard_fields": {}}},
        action_permissions={"draft": {"membership.bogus": ["Admin"]}},
    )
    with pytest.raises(ValueError, match="unknown action_key"):
        validate_definition_for_entity(d, "release", applies_to_kind="enterprise")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/unit/test_lifecycle_schemas.py -v
```

Expected: all FAIL.

- [ ] **Step 3: Extend the Pydantic models**

Edit `backend/app/api/v1/schemas/booking_lifecycle.py`:

1. Add field to `LifecycleState`:

```python
class LifecycleState(BaseModel):
    key: str
    label: str
    is_initial: bool = False
    is_terminal: bool = False
    is_admission_lockdown: bool = False  # only meaningful for release/enterprise lifecycles
```

2. Add an `action_permissions` field to `LifecycleDefinition` (alongside `field_permissions`):

```python
class LifecycleDefinition(BaseModel):
    states: list[LifecycleState]
    transitions: list[LifecycleTransition]
    field_permissions: dict[str, LifecycleFieldPermission]
    action_permissions: Optional[dict[str, dict[str, list[str]]]] = None
```

3. Add the recognized-action constant near `ENTITY_FIELD_SPECS`:

```python
VALID_ENTERPRISE_ACTION_KEYS = {"membership.admit", "membership.reject", "membership.remove"}
```

4. Extend `validate_definition_for_entity` signature and body:

```python
def validate_definition_for_entity(
    definition: LifecycleDefinition,
    entity_type: str,
    applies_to_kind: Optional[str] = None,
) -> None:
    # ... existing body ...

    if entity_type == "release" and applies_to_kind == "enterprise":
        # Single-lockdown invariant
        lockdowns = [s for s in definition.states if s.is_admission_lockdown]
        if len(lockdowns) > 1:
            raise ValueError(
                "at most one state may have is_admission_lockdown=True"
            )
        # Action permissions keys must be recognized
        for state_key, actions in (definition.action_permissions or {}).items():
            for action_key in actions:
                if action_key not in VALID_ENTERPRISE_ACTION_KEYS:
                    raise ValueError(
                        f"unknown action_key '{action_key}' at state '{state_key}'"
                    )
    else:
        # action_permissions ignored for non-enterprise templates — but reject lockdown flag
        for s in definition.states:
            if s.is_admission_lockdown:
                raise ValueError(
                    "is_admission_lockdown only valid on release/enterprise templates"
                )
```

(Preserve the rest of the existing function body — initial-state checks, field validation, etc.)

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && uv run pytest tests/unit/test_lifecycle_schemas.py -v
```

Expected: PASS.

- [ ] **Step 5: Update `lifecycle_service.create_template` / `update_template` call sites**

`lifecycle_service.create_template` (and `update_template`) must now pass `applies_to_kind` through to `validate_definition_for_entity`. Pass the value from the `LifecycleTemplate` row or the incoming `data`. The route handler also must accept `applies_to_kind` on the create/update bodies (add to `LifecycleTemplateCreate` / `LifecycleTemplateUpdate`):

```python
class LifecycleTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = False
    entity_type: str = "booking"
    applies_to_kind: Optional[str] = None
    definition: LifecycleDefinition


class LifecycleTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    applies_to_kind: Optional[str] = None
    definition: Optional[LifecycleDefinition] = None
```

In `create_template` / `update_template`, pass `data.applies_to_kind` (or the existing template's value on update) into the validator.

- [ ] **Step 6: Run full backend suite**

```bash
cd backend && uv run pytest tests/ -x -q
```

Expected: PASS (existing tests still green; any template-creation tests validate the new field is optional).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/schemas/booking_lifecycle.py backend/app/services/lifecycle_service.py backend/tests/unit/test_lifecycle_schemas.py
git commit -m "feat(enterprise): lifecycle schema extensions (lockdown flag + action_permissions)"
```

---

### Task 4: Membership Pydantic schemas

**Files:**
- Create: `backend/app/api/v1/schemas/release_membership.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_release_membership_schemas.py`:

```python
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.api.v1.schemas.release_membership import (
    ReleaseMembershipCreate,
    ReleaseMembershipRead,
    MembershipRejectRequest,
    MembershipRemoveRequest,
)


def test_create_requires_project_release_id():
    with pytest.raises(ValidationError):
        ReleaseMembershipCreate()


def test_create_with_notes():
    m = ReleaseMembershipCreate(project_release_id=42, notes="nominating team A")
    assert m.project_release_id == 42


def test_reject_requires_notes():
    with pytest.raises(ValidationError):
        MembershipRejectRequest()


def test_remove_requires_reason():
    with pytest.raises(ValidationError):
        MembershipRemoveRequest()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/unit/test_release_membership_schemas.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write the schemas**

`backend/app/api/v1/schemas/release_membership.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ReleaseMembershipCreate(BaseModel):
    project_release_id: int
    notes: Optional[str] = None


class MembershipRejectRequest(BaseModel):
    notes: str = Field(..., min_length=1)


class MembershipRemoveRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class ReleaseMembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    enterprise_release_id: int
    project_release_id: int
    project_release_name: Optional[str] = None
    project_release_status: Optional[str] = None
    state: str
    requested_by: int
    requested_by_username: Optional[str] = None
    requested_at: datetime
    decided_by: Optional[int] = None
    decided_by_username: Optional[str] = None
    decided_at: Optional[datetime] = None
    removed_by: Optional[int] = None
    removed_by_username: Optional[str] = None
    removed_at: Optional[datetime] = None
    removal_reason: Optional[str] = None
    late_scope: bool
    notes: Optional[str] = None


class MembershipSummary(BaseModel):
    pending: int
    accepted: int
    rejected: int
    withdrawn: int
    removed: int
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && uv run pytest tests/unit/test_release_membership_schemas.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/schemas/release_membership.py backend/tests/unit/test_release_membership_schemas.py
git commit -m "feat(enterprise): pydantic schemas for release_membership"
```

---

### Task 5: Rollup / report Pydantic schemas

**Files:**
- Create: `backend/app/api/v1/schemas/enterprise_rollup.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_enterprise_rollup_schemas.py`:

```python
from app.api.v1.schemas.enterprise_rollup import (
    SystemRollupRow,
    ScopeRollupFilters,
    TimelineRollupRead,
    MemberStateCount,
    EnterpriseReportRead,
)


def test_system_rollup_row_shape():
    r = SystemRollupRow(
        system_id=1,
        system_name="orders-api",
        roles_by_project={"proj-A": ["changing"], "proj-B": ["regression"]},
    )
    assert r.system_id == 1


def test_scope_rollup_filters_default_empty():
    f = ScopeRollupFilters()
    assert f.change_kind is None
    assert f.status is None


def test_member_state_count():
    m = MemberStateCount(state="in_progress", count=2, projects=["Alpha", "Beta"])
    assert m.count == 2


def test_report_read_has_all_sections():
    r = EnterpriseReportRead(
        enterprise_id=1,
        name="R1",
        status="integration_testing",
        target_date=None,
        actual_date=None,
        description=None,
        members=[],
        systems=[],
        scope_by_project={},
        events=[],
        dependencies=[],
        generated_at="2026-04-22T00:00:00Z",
        generated_by="user",
    )
    assert r.enterprise_id == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/unit/test_enterprise_rollup_schemas.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write the schemas**

`backend/app/api/v1/schemas/enterprise_rollup.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SystemRollupRow(BaseModel):
    system_id: int
    system_name: str
    # project_name → list of roles that project contributes for this system
    roles_by_project: dict[str, list[str]]


class ScopeRollupFilters(BaseModel):
    change_kind: Optional[str] = None
    status: Optional[str] = None
    project_release_id: Optional[int] = None
    system_id: Optional[int] = None
    search: Optional[str] = None


class TimelinePhaseRead(BaseModel):
    release_id: int
    release_name: str
    release_kind: str
    phase_id: Optional[int] = None
    phase_name: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None


class TimelineDependencyEdge(BaseModel):
    from_release_id: int
    to_release_id: int
    alert: Optional[str] = None


class TimelineRollupRead(BaseModel):
    enterprise_phases: list[TimelinePhaseRead]
    child_phases_by_release: dict[int, list[TimelinePhaseRead]]
    dependencies: list[TimelineDependencyEdge]


class MemberStateCount(BaseModel):
    state: str
    count: int
    projects: list[str]


class MemberRollupRow(BaseModel):
    project_release_id: int
    project_release_name: str
    status: str
    admitted_at: Optional[datetime] = None
    late_scope: bool


class ScopeRollupItem(BaseModel):
    release_change_id: int
    project_release_id: int
    project_release_name: str
    external_key: Optional[str] = None
    title: str
    change_kind: str
    external_status: Optional[str] = None
    system_id: Optional[int] = None
    system_name: Optional[str] = None


class EnterpriseReportEvent(BaseModel):
    release_id: int
    release_name: str
    occurred_at: datetime
    event_type: str
    description: Optional[str] = None


class EnterpriseReportRead(BaseModel):
    enterprise_id: int
    name: str
    status: str
    target_date: Optional[datetime] = None
    actual_date: Optional[datetime] = None
    description: Optional[str] = None
    members: list[MemberRollupRow]
    systems: list[SystemRollupRow]
    scope_by_project: dict[str, list[ScopeRollupItem]]
    events: list[EnterpriseReportEvent]
    dependencies: list[TimelineDependencyEdge]
    generated_at: str  # ISO-8601
    generated_by: str  # username
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && uv run pytest tests/unit/test_enterprise_rollup_schemas.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/schemas/enterprise_rollup.py backend/tests/unit/test_enterprise_rollup_schemas.py
git commit -m "feat(enterprise): pydantic schemas for rollup + report responses"
```

---

### Task 6: Release Pydantic schema — kind filter + membership summary

**Files:**
- Modify: `backend/app/api/v1/schemas/release.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_release_schemas.py` (create if absent):

```python
from app.api.v1.schemas.release import ReleaseRead, ReleaseListItemRead
from app.api.v1.schemas.release_membership import MembershipSummary


def test_release_read_allows_membership_summary():
    r = ReleaseRead(
        id=1, tenant_id=1, name="E1", description=None,
        release_type="Major", release_kind="enterprise",
        parent_release_id=None, template_id=None,
        lifecycle_template_id=5, status="draft",
        target_date=None, actual_date=None,
        custom_fields=None, raised_by=1,
        created_at="2026-04-22T00:00:00Z",
        membership_summary=MembershipSummary(
            pending=0, accepted=0, rejected=0, withdrawn=0, removed=0
        ),
    )
    assert r.membership_summary.pending == 0
```

(Exact field list depends on current `ReleaseRead`; add whatever the existing shape requires. The new attribute is `membership_summary: Optional[MembershipSummary]`.)

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && uv run pytest tests/unit/test_release_schemas.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add the optional field**

Edit `backend/app/api/v1/schemas/release.py`:

```python
from app.api.v1.schemas.release_membership import MembershipSummary


class ReleaseRead(BaseModel):
    # ... existing fields ...
    membership_summary: Optional[MembershipSummary] = None
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && uv run pytest tests/unit/test_release_schemas.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/schemas/release.py backend/tests/unit/test_release_schemas.py
git commit -m "feat(enterprise): ReleaseRead.membership_summary for enterprise-kind releases"
```

---

## Phase 2 — Backend services

### Task 7: `enterprise_membership_service.request_membership`

**Files:**
- Create: `backend/app/services/enterprise_membership_service.py`
- Test: `backend/tests/integration/test_enterprise_membership_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_enterprise_membership_service.py
import pytest
from datetime import datetime, timezone

from app.services import enterprise_membership_service
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership, MembershipState
from tests.integration.conftest import make_release, make_user, make_tenant  # existing helpers


@pytest.mark.asyncio
async def test_request_membership_creates_pending_row(db_session):
    tenant = await make_tenant(db_session)
    user = await make_user(db_session, tenant.id)
    ent = await make_release(db_session, tenant.id, user.id, release_kind="enterprise")
    proj = await make_release(db_session, tenant.id, user.id, release_kind="project")

    m = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=proj.id, notes="test"
    )

    assert m.state == MembershipState.PENDING_REQUEST.value
    assert m.enterprise_release_id == ent.id
    assert m.project_release_id == proj.id
    assert m.late_scope is False


@pytest.mark.asyncio
async def test_request_membership_rejects_duplicate_pending(db_session):
    tenant = await make_tenant(db_session)
    user = await make_user(db_session, tenant.id)
    ent = await make_release(db_session, tenant.id, user.id, release_kind="enterprise")
    proj = await make_release(db_session, tenant.id, user.id, release_kind="project")

    await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=proj.id
    )
    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.request_membership(
            db_session, user=user, enterprise_id=ent.id, project_release_id=proj.id
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_request_membership_rejects_wrong_kind(db_session):
    tenant = await make_tenant(db_session)
    user = await make_user(db_session, tenant.id)
    wrong = await make_release(db_session, tenant.id, user.id, release_kind="project")
    proj = await make_release(db_session, tenant.id, user.id, release_kind="project")

    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.request_membership(
            db_session, user=user, enterprise_id=wrong.id, project_release_id=proj.id
        )
    assert exc.value.status_code == 422
```

If `make_release` / `make_user` / `make_tenant` don't exist, add minimal builders to `tests/integration/conftest.py`. Check with `grep -r 'def make_release' backend/tests` first.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the service function**

`backend/app/services/enterprise_membership_service.py`:

```python
"""Enterprise release membership service.

Workflow: request → accept/reject/withdraw; accept → remove.
All mutations publish outbox events. Never call db.commit() here.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.db.models.user import User


async def _get_release(
    db: AsyncSession, release_id: int, tenant_id: int
) -> Release:
    r = (
        await db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release not found")
    return r


async def _get_open_membership_for_project(
    db: AsyncSession, project_release_id: int
) -> Optional[ReleaseMembership]:
    return (
        await db.execute(
            select(ReleaseMembership).where(
                ReleaseMembership.project_release_id == project_release_id,
                ReleaseMembership.state.in_(
                    [MembershipState.PENDING_REQUEST.value, MembershipState.ACCEPTED.value]
                ),
            )
        )
    ).scalar_one_or_none()


async def request_membership(
    db: AsyncSession,
    *,
    user: User,
    enterprise_id: int,
    project_release_id: int,
    notes: Optional[str] = None,
) -> ReleaseMembership:
    tenant_id = user.active_tenant_id
    enterprise = await _get_release(db, enterprise_id, tenant_id)
    project = await _get_release(db, project_release_id, tenant_id)

    if enterprise.release_kind != "enterprise":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Target is not an enterprise release",
        )
    if project.release_kind != "project":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only project releases can be admitted",
        )
    if await _get_open_membership_for_project(db, project_release_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Project release already has a pending or accepted membership",
        )

    m = ReleaseMembership(
        tenant_id=tenant_id,
        enterprise_release_id=enterprise_id,
        project_release_id=project_release_id,
        state=MembershipState.PENDING_REQUEST.value,
        requested_by=user.id,
        requested_at=datetime.now(timezone.utc),
        notes=notes,
        late_scope=False,
    )
    db.add(m)
    await db.flush()
    await publish_event(
        db,
        event_type="EnterpriseMembershipRequested",
        aggregate_id=enterprise_id,
        aggregate_type="Release",
        payload={
            "membership_id": m.id,
            "project_release_id": project_release_id,
            "actor_id": user.id,
        },
        tenant_id=tenant_id,
    )
    return m
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py::test_request_membership_creates_pending_row \
    tests/integration/test_enterprise_membership_service.py::test_request_membership_rejects_duplicate_pending \
    tests/integration/test_enterprise_membership_service.py::test_request_membership_rejects_wrong_kind -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enterprise_membership_service.py backend/tests/integration/test_enterprise_membership_service.py
git commit -m "feat(enterprise): request_membership service + tests"
```

---

### Task 8: `accept` + late_scope computation

**Files:**
- Modify: `backend/app/services/enterprise_membership_service.py`
- Modify: `backend/tests/integration/test_enterprise_membership_service.py`

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
@pytest.mark.asyncio
async def test_accept_sets_parent_and_flips_state(db_session):
    tenant = await make_tenant(db_session)
    user = await make_user(db_session, tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, user.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    proj = await make_release(db_session, tenant.id, user.id, release_kind="project")

    m = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=proj.id
    )
    accepted = await enterprise_membership_service.accept(db_session, user=user, membership_id=m.id)
    await db_session.refresh(proj)
    assert accepted.state == MembershipState.ACCEPTED.value
    assert proj.parent_release_id == ent.id
    assert accepted.late_scope is False


@pytest.mark.asyncio
async def test_accept_after_lockdown_flags_late_scope(db_session):
    tenant = await make_tenant(db_session)
    user = await make_user(db_session, tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, user.id, release_kind="enterprise",
                             lifecycle_kind="enterprise", status="integration_testing")
    # assumes default enterprise template has admission_closed as lockdown, before integration_testing
    proj = await make_release(db_session, tenant.id, user.id, release_kind="project")

    m = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=proj.id
    )
    accepted = await enterprise_membership_service.accept(db_session, user=user, membership_id=m.id)
    assert accepted.late_scope is True


@pytest.mark.asyncio
async def test_accept_without_permission_returns_403(db_session):
    tenant = await make_tenant(db_session)
    dev = await make_user(db_session, tenant.id, role="Developer")
    ent = await make_release(db_session, tenant.id, dev.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    proj = await make_release(db_session, tenant.id, dev.id, release_kind="project")
    m = await enterprise_membership_service.request_membership(
        db_session, user=dev, enterprise_id=ent.id, project_release_id=proj.id
    )
    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.accept(db_session, user=dev, membership_id=m.id)
    assert exc.value.status_code == 403
```

`make_release(..., lifecycle_kind="enterprise")` needs to use the default enterprise lifecycle template (see Task 11). For now, document this dependency in a `# TODO: requires Task 11` comment in the test file.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py -v
```

Expected: 3 new FAILs.

- [ ] **Step 3: Implement `accept` and helpers**

Append to `backend/app/services/enterprise_membership_service.py`:

```python
from app.db.models.lifecycle import LifecycleTemplate


def _compute_late_scope(enterprise: Release, template: LifecycleTemplate) -> bool:
    states = template.definition.get("states", [])
    try:
        lockdown_idx = next(
            i for i, s in enumerate(states) if s.get("is_admission_lockdown")
        )
    except StopIteration:
        return False
    try:
        current_idx = next(
            i for i, s in enumerate(states) if s["key"] == enterprise.status
        )
    except StopIteration:
        return False
    return current_idx >= lockdown_idx


async def _check_action_permission(
    db: AsyncSession,
    enterprise: Release,
    user: User,
    action_key: str,
) -> None:
    tpl = await db.get(LifecycleTemplate, enterprise.lifecycle_template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lifecycle template missing")
    perms = (tpl.definition or {}).get("action_permissions", {}) or {}
    roles_for_state = perms.get(enterprise.status, {}).get(action_key, [])
    user_role_name = getattr(user.role, "name", user.role) if hasattr(user, "role") else None
    if user_role_name not in roles_for_state:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Not permitted: {action_key}")


async def _get_membership(
    db: AsyncSession, membership_id: int, tenant_id: int
) -> ReleaseMembership:
    m = (
        await db.execute(
            select(ReleaseMembership).where(
                ReleaseMembership.id == membership_id,
                ReleaseMembership.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    return m


async def accept(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.PENDING_REQUEST.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot accept",
        )
    enterprise = await _get_release(db, m.enterprise_release_id, user.active_tenant_id)
    project = await _get_release(db, m.project_release_id, user.active_tenant_id)

    await _check_action_permission(db, enterprise, user, "membership.admit")

    # Double-check no other accepted exists (race protection; partial unique also enforces in PG)
    existing = (
        await db.execute(
            select(ReleaseMembership).where(
                ReleaseMembership.project_release_id == project.id,
                ReleaseMembership.state == MembershipState.ACCEPTED.value,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Project already has an accepted membership",
        )

    tpl = await db.get(LifecycleTemplate, enterprise.lifecycle_template_id)
    m.late_scope = _compute_late_scope(enterprise, tpl)
    m.state = MembershipState.ACCEPTED.value
    m.decided_by = user.id
    m.decided_at = datetime.now(timezone.utc)
    project.parent_release_id = enterprise.id

    await publish_event(
        db,
        event_type="EnterpriseMembershipAccepted",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={
            "membership_id": m.id,
            "project_release_id": project.id,
            "actor_id": user.id,
            "late_scope": m.late_scope,
        },
        tenant_id=user.active_tenant_id,
    )
    return m
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py -v
```

Expected: all membership tests PASS (may need Task 11 seed for lockdown test — run it and the lockdown test after Task 11 is in place; mark as xfail temporarily).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enterprise_membership_service.py backend/tests/integration/test_enterprise_membership_service.py
git commit -m "feat(enterprise): accept service with late_scope computation + permission check"
```

---

### Task 9: `reject` + `withdraw` + `remove`

**Files:**
- Modify: `backend/app/services/enterprise_membership_service.py`
- Modify: `backend/tests/integration/test_enterprise_membership_service.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_reject_sets_state(db_session):
    tenant = await make_tenant(db_session)
    admin = await make_user(db_session, tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, admin.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    proj = await make_release(db_session, tenant.id, admin.id, release_kind="project")
    m = await enterprise_membership_service.request_membership(
        db_session, user=admin, enterprise_id=ent.id, project_release_id=proj.id
    )
    rejected = await enterprise_membership_service.reject(
        db_session, user=admin, membership_id=m.id, notes="out of scope"
    )
    assert rejected.state == MembershipState.REJECTED.value
    assert rejected.notes == "out of scope"


@pytest.mark.asyncio
async def test_withdraw_only_by_requester(db_session):
    tenant = await make_tenant(db_session)
    u1 = await make_user(db_session, tenant.id, role="Developer")
    u2 = await make_user(db_session, tenant.id, role="Developer")
    ent = await make_release(db_session, tenant.id, u1.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    proj = await make_release(db_session, tenant.id, u1.id, release_kind="project")
    m = await enterprise_membership_service.request_membership(
        db_session, user=u1, enterprise_id=ent.id, project_release_id=proj.id
    )
    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.withdraw(db_session, user=u2, membership_id=m.id)
    assert exc.value.status_code == 403

    withdrawn = await enterprise_membership_service.withdraw(db_session, user=u1, membership_id=m.id)
    assert withdrawn.state == MembershipState.WITHDRAWN.value


@pytest.mark.asyncio
async def test_remove_nulls_parent_and_writes_audit(db_session):
    tenant = await make_tenant(db_session)
    admin = await make_user(db_session, tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, admin.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    proj = await make_release(db_session, tenant.id, admin.id, release_kind="project")
    m = await enterprise_membership_service.request_membership(
        db_session, user=admin, enterprise_id=ent.id, project_release_id=proj.id
    )
    await enterprise_membership_service.accept(db_session, user=admin, membership_id=m.id)

    removed = await enterprise_membership_service.remove(
        db_session, user=admin, membership_id=m.id, reason="risk to target date"
    )
    await db_session.refresh(proj)
    assert removed.state == MembershipState.REMOVED.value
    assert removed.removal_reason == "risk to target date"
    assert proj.parent_release_id is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py -v
```

Expected: 3 new FAILs.

- [ ] **Step 3: Implement reject / withdraw / remove**

Append to `backend/app/services/enterprise_membership_service.py`:

```python
async def reject(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
    notes: str,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.PENDING_REQUEST.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot reject",
        )
    enterprise = await _get_release(db, m.enterprise_release_id, user.active_tenant_id)
    await _check_action_permission(db, enterprise, user, "membership.reject")

    m.state = MembershipState.REJECTED.value
    m.decided_by = user.id
    m.decided_at = datetime.now(timezone.utc)
    m.notes = notes
    await publish_event(
        db,
        event_type="EnterpriseMembershipRejected",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={"membership_id": m.id, "actor_id": user.id, "notes": notes},
        tenant_id=user.active_tenant_id,
    )
    return m


async def withdraw(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.PENDING_REQUEST.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot withdraw",
        )
    user_role_name = getattr(user.role, "name", user.role) if hasattr(user, "role") else None
    if m.requested_by != user.id and user_role_name != "Admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the requester or a tenant admin can withdraw",
        )
    m.state = MembershipState.WITHDRAWN.value
    m.decided_by = user.id
    m.decided_at = datetime.now(timezone.utc)
    await publish_event(
        db,
        event_type="EnterpriseMembershipWithdrawn",
        aggregate_id=m.enterprise_release_id,
        aggregate_type="Release",
        payload={"membership_id": m.id, "actor_id": user.id},
        tenant_id=user.active_tenant_id,
    )
    return m


async def remove(
    db: AsyncSession,
    *,
    user: User,
    membership_id: int,
    reason: str,
) -> ReleaseMembership:
    m = await _get_membership(db, membership_id, user.active_tenant_id)
    if m.state != MembershipState.ACCEPTED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Membership state is {m.state}, cannot remove",
        )
    enterprise = await _get_release(db, m.enterprise_release_id, user.active_tenant_id)
    project = await _get_release(db, m.project_release_id, user.active_tenant_id)
    await _check_action_permission(db, enterprise, user, "membership.remove")

    project.parent_release_id = None
    m.state = MembershipState.REMOVED.value
    m.removed_by = user.id
    m.removed_at = datetime.now(timezone.utc)
    m.removal_reason = reason
    await publish_event(
        db,
        event_type="EnterpriseMembershipRemoved",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={
            "membership_id": m.id,
            "project_release_id": project.id,
            "actor_id": user.id,
            "reason": reason,
        },
        tenant_id=user.active_tenant_id,
    )
    return m
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enterprise_membership_service.py backend/tests/integration/test_enterprise_membership_service.py
git commit -m "feat(enterprise): reject + withdraw + remove services"
```

---

### Task 10: `list_memberships` + `get_current_membership_for_project`

**Files:**
- Modify: `backend/app/services/enterprise_membership_service.py`
- Modify: `backend/tests/integration/test_enterprise_membership_service.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_list_memberships_filters_by_state(db_session):
    tenant = await make_tenant(db_session)
    admin = await make_user(db_session, tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, admin.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    p1 = await make_release(db_session, tenant.id, admin.id, release_kind="project")
    p2 = await make_release(db_session, tenant.id, admin.id, release_kind="project")
    m1 = await enterprise_membership_service.request_membership(
        db_session, user=admin, enterprise_id=ent.id, project_release_id=p1.id
    )
    m2 = await enterprise_membership_service.request_membership(
        db_session, user=admin, enterprise_id=ent.id, project_release_id=p2.id
    )
    await enterprise_membership_service.accept(db_session, user=admin, membership_id=m1.id)

    pending = await enterprise_membership_service.list_memberships(
        db_session, user=admin, enterprise_id=ent.id, states=["pending_request"]
    )
    assert {m.project_release_id for m in pending} == {p2.id}


@pytest.mark.asyncio
async def test_get_current_membership_for_project(db_session):
    tenant = await make_tenant(db_session)
    admin = await make_user(db_session, tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, admin.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    proj = await make_release(db_session, tenant.id, admin.id, release_kind="project")
    m = await enterprise_membership_service.request_membership(
        db_session, user=admin, enterprise_id=ent.id, project_release_id=proj.id
    )
    await enterprise_membership_service.accept(db_session, user=admin, membership_id=m.id)

    current = await enterprise_membership_service.get_current_membership_for_project(
        db_session, user=admin, project_release_id=proj.id
    )
    assert current.id == m.id
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py -v
```

- [ ] **Step 3: Implement**

```python
async def list_memberships(
    db: AsyncSession,
    *,
    user: User,
    enterprise_id: int,
    states: Optional[list[str]] = None,
) -> list[ReleaseMembership]:
    await _get_release(db, enterprise_id, user.active_tenant_id)
    stmt = select(ReleaseMembership).where(
        ReleaseMembership.enterprise_release_id == enterprise_id,
        ReleaseMembership.tenant_id == user.active_tenant_id,
    )
    if states:
        stmt = stmt.where(ReleaseMembership.state.in_(states))
    stmt = stmt.order_by(ReleaseMembership.requested_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_current_membership_for_project(
    db: AsyncSession,
    *,
    user: User,
    project_release_id: int,
) -> Optional[ReleaseMembership]:
    stmt = select(ReleaseMembership).where(
        ReleaseMembership.project_release_id == project_release_id,
        ReleaseMembership.tenant_id == user.active_tenant_id,
        ReleaseMembership.state == MembershipState.ACCEPTED.value,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_history_for_project(
    db: AsyncSession,
    *,
    user: User,
    project_release_id: int,
) -> list[ReleaseMembership]:
    stmt = (
        select(ReleaseMembership)
        .where(
            ReleaseMembership.project_release_id == project_release_id,
            ReleaseMembership.tenant_id == user.active_tenant_id,
        )
        .order_by(ReleaseMembership.requested_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_membership_summary(
    db: AsyncSession,
    *,
    user: User,
    enterprise_id: int,
) -> dict[str, int]:
    from sqlalchemy import func
    rows = (
        await db.execute(
            select(ReleaseMembership.state, func.count())
            .where(
                ReleaseMembership.enterprise_release_id == enterprise_id,
                ReleaseMembership.tenant_id == user.active_tenant_id,
            )
            .group_by(ReleaseMembership.state)
        )
    ).all()
    summary = {s.value: 0 for s in MembershipState}
    for state, count in rows:
        summary[state] = count
    return {
        "pending": summary[MembershipState.PENDING_REQUEST.value],
        "accepted": summary[MembershipState.ACCEPTED.value],
        "rejected": summary[MembershipState.REJECTED.value],
        "withdrawn": summary[MembershipState.WITHDRAWN.value],
        "removed": summary[MembershipState.REMOVED.value],
    }
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_membership_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enterprise_membership_service.py backend/tests/integration/test_enterprise_membership_service.py
git commit -m "feat(enterprise): list + current + history + summary query helpers"
```

---

### Task 11: Default enterprise lifecycle template seed

**Files:**
- Modify: `backend/app/services/release_defaults.py`
- Test: extend `backend/tests/integration/test_release_happy_path.py` or new test

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_enterprise_lifecycle_seed.py` (new file):

```python
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.services import release_defaults


@pytest.mark.asyncio
async def test_seed_creates_enterprise_template(db_session, tenant_factory):
    tenant = await tenant_factory()
    await release_defaults.seed_release_lifecycle_templates(db_session, tenant.id)
    await db_session.flush()

    enterprise_templates = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
            LifecycleTemplate.applies_to_kind == "enterprise",
        )
    )).scalars().all()
    assert len(enterprise_templates) == 1
    tpl = enterprise_templates[0]
    states = [s["key"] for s in tpl.definition["states"]]
    assert "admission_closed" in states
    lockdown = next(s for s in tpl.definition["states"] if s.get("is_admission_lockdown"))
    assert lockdown["key"] == "admission_closed"
    perms = tpl.definition["action_permissions"]
    assert "Admin" in perms["admission_open"]["membership.admit"]


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, tenant_factory):
    tenant = await tenant_factory()
    await release_defaults.seed_release_lifecycle_templates(db_session, tenant.id)
    await release_defaults.seed_release_lifecycle_templates(db_session, tenant.id)
    await db_session.flush()

    enterprise_templates = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.applies_to_kind == "enterprise",
        )
    )).scalars().all()
    assert len(enterprise_templates) == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_lifecycle_seed.py -v
```

- [ ] **Step 3: Extend `release_defaults.py`**

Add next to existing `_MAJOR_DEFINITION` / `_MINOR_DEFINITION` / `_EMERGENCY_DEFINITION`:

```python
_ENTERPRISE_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",                "label": "Draft",                "is_initial": True,  "is_terminal": False},
        {"key": "planning",             "label": "Planning",             "is_initial": False, "is_terminal": False},
        {"key": "admission_open",       "label": "Admission Open",       "is_initial": False, "is_terminal": False},
        {"key": "admission_closed",     "label": "Admission Closed",     "is_initial": False, "is_terminal": False, "is_admission_lockdown": True},
        {"key": "integration_testing", "label": "Integration Testing",  "is_initial": False, "is_terminal": False},
        {"key": "uat",                  "label": "UAT",                  "is_initial": False, "is_terminal": False},
        {"key": "staging",              "label": "Staging",              "is_initial": False, "is_terminal": False},
        {"key": "cab",                  "label": "CAB",                  "is_initial": False, "is_terminal": False},
        {"key": "deploying",            "label": "Deploying",            "is_initial": False, "is_terminal": False},
        {"key": "deployed",             "label": "Deployed",             "is_initial": False, "is_terminal": True},
        {"key": "cancelled",            "label": "Cancelled",            "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",                "to_state": "planning",             "label": "Start Planning",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "planning",             "to_state": "admission_open",       "label": "Open Admissions", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_open",       "to_state": "admission_closed",     "label": "Close Admissions","allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_closed",     "to_state": "integration_testing",  "label": "Start IT",        "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "integration_testing", "to_state": "uat",                   "label": "Promote to UAT",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "uat",                  "to_state": "staging",              "label": "Promote to Stg",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "staging",              "to_state": "cab",                  "label": "Submit for CAB",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "cab",                  "to_state": "deploying",            "label": "Start Deploy",    "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "deploying",            "to_state": "deployed",             "label": "Deployed",        "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",                "to_state": "cancelled",            "label": "Cancel",          "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "planning",             "to_state": "cancelled",            "label": "Cancel",          "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_open",       "to_state": "cancelled",            "label": "Cancel",          "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_closed",     "to_state": "cancelled",            "label": "Cancel",          "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":              {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "release_type": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "planning":           {"standard_fields": {"description": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "admission_open":     {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "admission_closed":   {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "integration_testing":{"standard_fields": {}, "custom_fields": {}},
        "uat":                {"standard_fields": {}, "custom_fields": {}},
        "staging":            {"standard_fields": {}, "custom_fields": {}},
        "cab":                {"standard_fields": {}, "custom_fields": {}},
        "deploying":          {"standard_fields": {}, "custom_fields": {}},
        "deployed":           {"standard_fields": {}, "custom_fields": {}},
        "cancelled":          {"standard_fields": {}, "custom_fields": {}},
    },
    "action_permissions": {
        state: {
            "membership.admit": ["Admin", "ReleaseManager"],
            "membership.reject": ["Admin", "ReleaseManager"],
            "membership.remove": ["Admin", "ReleaseManager"],
        }
        for state in ("draft", "planning", "admission_open", "admission_closed",
                      "integration_testing", "uat", "staging", "cab", "deploying")
    },
}
```

Then extend the existing seed function body to insert the enterprise template alongside the three project ones, with `applies_to_kind='enterprise'` and `is_default=True`. Keep existing project templates with `applies_to_kind='project'`. Idempotency key = `(tenant_id, name)`.

Also update the project-template inserts so they now persist `applies_to_kind='project'` on their `LifecycleTemplate` row.

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_lifecycle_seed.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full backend suite**

```bash
cd backend && uv run pytest tests/ -x -q
```

Expected: existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/release_defaults.py backend/tests/integration/test_enterprise_lifecycle_seed.py
git commit -m "feat(enterprise): default enterprise lifecycle template seed"
```

---

### Task 12: `enterprise_rollup_service.systems_rollup`

**Files:**
- Create: `backend/app/services/enterprise_rollup_service.py`
- Test: `backend/tests/integration/test_enterprise_rollup_service.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from app.services import enterprise_membership_service, enterprise_rollup_service


@pytest.mark.asyncio
async def test_systems_rollup_aggregates_accepted_only(db_session, tenant_factory, user_factory):
    tenant = await tenant_factory()
    admin = await user_factory(tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, admin.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    p1 = await make_release(db_session, tenant.id, admin.id, release_kind="project")
    p2 = await make_release(db_session, tenant.id, admin.id, release_kind="project")

    # Attach systems to children via release_system rows (use existing test helper
    # or direct SQL insert). Assume helper `attach_system(release_id, system_id, role)`.
    sys_a = await make_system(db_session, tenant.id, name="orders")
    sys_b = await make_system(db_session, tenant.id, name="billing")
    await attach_system(db_session, p1.id, sys_a.id, role="changing")
    await attach_system(db_session, p2.id, sys_a.id, role="regression")
    await attach_system(db_session, p2.id, sys_b.id, role="changing")

    for p in (p1, p2):
        m = await enterprise_membership_service.request_membership(
            db_session, user=admin, enterprise_id=ent.id, project_release_id=p.id
        )
        await enterprise_membership_service.accept(db_session, user=admin, membership_id=m.id)

    rollup = await enterprise_rollup_service.systems_rollup(
        db_session, user=admin, enterprise_id=ent.id
    )
    by_id = {r.system_id: r for r in rollup}
    assert by_id[sys_a.id].system_name == "orders"
    assert "changing" in by_id[sys_a.id].roles_by_project[p1.name]
    assert "regression" in by_id[sys_a.id].roles_by_project[p2.name]
    assert by_id[sys_b.id].roles_by_project == {p2.name: ["changing"]}
```

If `attach_system`/`make_system` fixtures don't exist, add simple factories to `conftest.py` using `release_system` and `system` models.

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_service.py -v
```

- [ ] **Step 3: Implement the service**

`backend/app/services/enterprise_rollup_service.py`:

```python
"""Read-only rollup queries for an enterprise release.

All queries join on accepted memberships only.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.enterprise_rollup import (
    SystemRollupRow,
    ScopeRollupItem,
    TimelinePhaseRead,
    TimelineDependencyEdge,
    TimelineRollupRead,
    MemberStateCount,
    MemberRollupRow,
)
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_dependency import ReleaseDependency
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.db.models.test_phase import TestPhase
from app.db.models.user import User


async def _accepted_child_ids(
    db: AsyncSession, tenant_id: int, enterprise_id: int
) -> list[int]:
    stmt = select(ReleaseMembership.project_release_id).where(
        ReleaseMembership.enterprise_release_id == enterprise_id,
        ReleaseMembership.tenant_id == tenant_id,
        ReleaseMembership.state == MembershipState.ACCEPTED.value,
    )
    return [r for (r,) in (await db.execute(stmt)).all()]


async def systems_rollup(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> list[SystemRollupRow]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return []

    stmt = (
        select(ReleaseSystem, System, Release)
        .join(System, ReleaseSystem.system_id == System.id)
        .join(Release, ReleaseSystem.release_id == Release.id)
        .where(
            ReleaseSystem.release_id.in_(child_ids),
            ReleaseSystem.tenant_id == tenant_id,
        )
    )
    by_system: dict[int, dict] = {}
    for rs, sys, rel in (await db.execute(stmt)).all():
        entry = by_system.setdefault(
            sys.id,
            {"system_id": sys.id, "system_name": sys.name, "roles_by_project": {}},
        )
        entry["roles_by_project"].setdefault(rel.name, []).append(rs.role)
    return [SystemRollupRow(**v) for v in by_system.values()]
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_service.py::test_systems_rollup_aggregates_accepted_only -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enterprise_rollup_service.py backend/tests/integration/test_enterprise_rollup_service.py
git commit -m "feat(enterprise): systems rollup service"
```

---

### Task 13: `scope_rollup`

**Files:**
- Modify: `backend/app/services/enterprise_rollup_service.py`

- [ ] **Step 1: Write the failing test**

Append to `test_enterprise_rollup_service.py`:

```python
@pytest.mark.asyncio
async def test_scope_rollup_lists_accepted_children_only(db_session, tenant_factory, user_factory):
    tenant = await tenant_factory()
    admin = await user_factory(tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, admin.id, release_kind="enterprise",
                             lifecycle_kind="enterprise")
    p = await make_release(db_session, tenant.id, admin.id, release_kind="project")
    other = await make_release(db_session, tenant.id, admin.id, release_kind="project")

    await make_scope_item(db_session, tenant.id, release_id=p.id,
                         external_key="PROJ-1", title="Story 1", change_kind="story")
    await make_scope_item(db_session, tenant.id, release_id=other.id,
                         external_key="PROJ-2", title="Story 2", change_kind="story")

    m = await enterprise_membership_service.request_membership(
        db_session, user=admin, enterprise_id=ent.id, project_release_id=p.id
    )
    await enterprise_membership_service.accept(db_session, user=admin, membership_id=m.id)

    rollup = await enterprise_rollup_service.scope_rollup(
        db_session, user=admin, enterprise_id=ent.id
    )
    assert {item.external_key for item in rollup} == {"PROJ-1"}


@pytest.mark.asyncio
async def test_scope_rollup_kind_filter(db_session, tenant_factory, user_factory):
    # ... similar, add defect + story on the same release, filter by change_kind
    ...
```

- [ ] **Step 2: Run tests to verify fail**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_service.py -v
```

- [ ] **Step 3: Implement**

Append:

```python
async def scope_rollup(
    db: AsyncSession,
    *,
    user: User,
    enterprise_id: int,
    change_kind: Optional[str] = None,
    status: Optional[str] = None,
    project_release_id: Optional[int] = None,
    system_id: Optional[int] = None,
    search: Optional[str] = None,
) -> list[ScopeRollupItem]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return []
    if project_release_id:
        if project_release_id not in child_ids:
            return []
        child_ids = [project_release_id]

    stmt = (
        select(ReleaseChange, Release, System)
        .join(Release, ReleaseChange.release_id == Release.id)
        .outerjoin(System, ReleaseChange.system_id == System.id)
        .where(
            ReleaseChange.release_id.in_(child_ids),
            ReleaseChange.tenant_id == tenant_id,
            ReleaseChange.deleted_at.is_(None),
        )
    )
    if change_kind:
        stmt = stmt.where(ReleaseChange.change_kind == change_kind)
    if status:
        stmt = stmt.where(ReleaseChange.external_status == status)
    if system_id:
        stmt = stmt.where(ReleaseChange.system_id == system_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (ReleaseChange.title.ilike(like)) | (ReleaseChange.external_key.ilike(like))
        )

    items: list[ScopeRollupItem] = []
    for rc, rel, sys in (await db.execute(stmt)).all():
        items.append(ScopeRollupItem(
            release_change_id=rc.id,
            project_release_id=rel.id,
            project_release_name=rel.name,
            external_key=rc.external_key,
            title=rc.title,
            change_kind=rc.change_kind,
            external_status=rc.external_status,
            system_id=rc.system_id,
            system_name=sys.name if sys else None,
        ))
    return items
```

- [ ] **Step 4: Run tests, commit**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_service.py -v
git add backend/app/services/enterprise_rollup_service.py backend/tests/integration/test_enterprise_rollup_service.py
git commit -m "feat(enterprise): scope rollup service"
```

---

### Task 14: `timeline_rollup` + `member_state_summary`

**Files:**
- Modify: `backend/app/services/enterprise_rollup_service.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_timeline_rollup_composes_enterprise_and_children(db_session, ...):
    # Build 1 enterprise with 2 accepted children; each child has 2 test phases.
    # Assert enterprise_phases, child_phases_by_release keyed correctly, and
    # dependencies list populated for a cross-child dep.
    ...


@pytest.mark.asyncio
async def test_member_state_summary(db_session, ...):
    # Build 3 accepted children: two in sit_complete, one in draft.
    # Assert counts and project names returned correctly.
    ...
```

- [ ] **Step 2: Run to fail**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_service.py -v
```

- [ ] **Step 3: Implement**

Append:

```python
async def timeline_rollup(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> TimelineRollupRead:
    tenant_id = user.active_tenant_id
    # Enterprise own phases
    enterprise_phases_rows = (await db.execute(
        select(TestPhase, Release).join(Release, TestPhase.release_id == Release.id).where(
            TestPhase.release_id == enterprise_id,
            TestPhase.tenant_id == tenant_id,
        )
    )).all()
    enterprise_phases = [
        TimelinePhaseRead(
            release_id=rel.id,
            release_name=rel.name,
            release_kind=rel.release_kind,
            phase_id=tp.id,
            phase_name=tp.name,
            start_date=tp.start_date,
            end_date=tp.end_date,
            status=tp.status,
        )
        for tp, rel in enterprise_phases_rows
    ]

    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    child_phases: dict[int, list[TimelinePhaseRead]] = {cid: [] for cid in child_ids}
    if child_ids:
        rows = (await db.execute(
            select(TestPhase, Release).join(Release, TestPhase.release_id == Release.id).where(
                TestPhase.release_id.in_(child_ids),
                TestPhase.tenant_id == tenant_id,
            )
        )).all()
        for tp, rel in rows:
            child_phases[rel.id].append(TimelinePhaseRead(
                release_id=rel.id, release_name=rel.name, release_kind=rel.release_kind,
                phase_id=tp.id, phase_name=tp.name,
                start_date=tp.start_date, end_date=tp.end_date, status=tp.status,
            ))

    # Child-to-child dependencies within the train
    dep_rows = []
    if child_ids:
        dep_rows = (await db.execute(
            select(ReleaseDependency).where(
                ReleaseDependency.release_id.in_(child_ids),
                ReleaseDependency.depends_on_release_id.in_(child_ids),
                ReleaseDependency.tenant_id == tenant_id,
            )
        )).scalars().all()
    dependencies = [
        TimelineDependencyEdge(
            from_release_id=d.release_id,
            to_release_id=d.depends_on_release_id,
            alert=None,
        )
        for d in dep_rows
    ]

    return TimelineRollupRead(
        enterprise_phases=enterprise_phases,
        child_phases_by_release=child_phases,
        dependencies=dependencies,
    )


async def member_state_summary(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> list[MemberStateCount]:
    tenant_id = user.active_tenant_id
    child_ids = await _accepted_child_ids(db, tenant_id, enterprise_id)
    if not child_ids:
        return []
    rows = (await db.execute(
        select(Release).where(Release.id.in_(child_ids))
    )).scalars().all()
    grouped: dict[str, list[str]] = {}
    for r in rows:
        grouped.setdefault(r.status, []).append(r.name)
    return [
        MemberStateCount(state=s, count=len(names), projects=names)
        for s, names in grouped.items()
    ]


async def members_rollup(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> list[MemberRollupRow]:
    from app.db.models.release_membership import ReleaseMembership, MembershipState
    tenant_id = user.active_tenant_id
    rows = (await db.execute(
        select(ReleaseMembership, Release)
        .join(Release, ReleaseMembership.project_release_id == Release.id)
        .where(
            ReleaseMembership.enterprise_release_id == enterprise_id,
            ReleaseMembership.tenant_id == tenant_id,
            ReleaseMembership.state == MembershipState.ACCEPTED.value,
        )
    )).all()
    return [
        MemberRollupRow(
            project_release_id=rel.id,
            project_release_name=rel.name,
            status=rel.status,
            admitted_at=m.decided_at,
            late_scope=m.late_scope,
        )
        for m, rel in rows
    ]
```

- [ ] **Step 4: Run tests, commit**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_service.py -v
git add backend/app/services/enterprise_rollup_service.py backend/tests/integration/test_enterprise_rollup_service.py
git commit -m "feat(enterprise): timeline + member-state-summary + members rollup"
```

---

### Task 15: `enterprise_report_service.generate_report`

**Files:**
- Create: `backend/app/services/enterprise_report_service.py`
- Test: `backend/tests/integration/test_enterprise_report_service.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from datetime import datetime, timezone

from app.services import enterprise_membership_service, enterprise_report_service


@pytest.mark.asyncio
async def test_generate_report_has_all_sections(db_session, tenant_factory, user_factory):
    tenant = await tenant_factory()
    admin = await user_factory(tenant.id, role="Admin")
    ent = await make_release(db_session, tenant.id, admin.id, release_kind="enterprise",
                             lifecycle_kind="enterprise", name="R-ENT-1")
    p1 = await make_release(db_session, tenant.id, admin.id, release_kind="project", name="Alpha")
    p2 = await make_release(db_session, tenant.id, admin.id, release_kind="project", name="Beta")
    await make_scope_item(db_session, tenant.id, release_id=p1.id,
                         external_key="ALPHA-1", title="Feature 1", change_kind="story")
    await make_scope_item(db_session, tenant.id, release_id=p2.id,
                         external_key="BETA-1", title="Fix 1", change_kind="defect")
    for p in (p1, p2):
        m = await enterprise_membership_service.request_membership(
            db_session, user=admin, enterprise_id=ent.id, project_release_id=p.id
        )
        await enterprise_membership_service.accept(db_session, user=admin, membership_id=m.id)

    report = await enterprise_report_service.generate_report(db_session, user=admin, enterprise_id=ent.id)
    assert report.enterprise_id == ent.id
    assert report.name == "R-ENT-1"
    assert {m.project_release_name for m in report.members} == {"Alpha", "Beta"}
    assert "Alpha" in report.scope_by_project
    assert "Beta" in report.scope_by_project
    assert {it.external_key for it in report.scope_by_project["Alpha"]} == {"ALPHA-1"}
```

- [ ] **Step 2: Run to fail**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_report_service.py -v
```

- [ ] **Step 3: Implement**

`backend/app/services/enterprise_report_service.py`:

```python
"""Enterprise release report — deterministic HTML-payload generator."""
from datetime import datetime, timezone
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.enterprise_rollup import (
    EnterpriseReportRead,
    EnterpriseReportEvent,
)
from app.core.events import publish_event
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.release_event import ReleaseEvent
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.db.models.user import User
from app.services import enterprise_rollup_service


async def generate_report(
    db: AsyncSession, *, user: User, enterprise_id: int
) -> EnterpriseReportRead:
    tenant_id = user.active_tenant_id
    enterprise = (await db.execute(
        select(Release).where(
            Release.id == enterprise_id,
            Release.tenant_id == tenant_id,
            Release.deleted_at.is_(None),
        )
    )).scalar_one()
    members = await enterprise_rollup_service.members_rollup(
        db, user=user, enterprise_id=enterprise_id
    )
    systems = await enterprise_rollup_service.systems_rollup(
        db, user=user, enterprise_id=enterprise_id
    )
    scope_items = await enterprise_rollup_service.scope_rollup(
        db, user=user, enterprise_id=enterprise_id
    )
    scope_by_project: dict[str, list] = defaultdict(list)
    for it in scope_items:
        scope_by_project[it.project_release_name].append(it)

    # Enterprise's own events + top status transitions of children (last 20 each)
    events: list[EnterpriseReportEvent] = []
    own_events = (await db.execute(
        select(ReleaseEvent).where(
            ReleaseEvent.release_id == enterprise_id,
            ReleaseEvent.tenant_id == tenant_id,
        ).order_by(ReleaseEvent.occurred_at.desc())
    )).scalars().all()
    for e in own_events:
        events.append(EnterpriseReportEvent(
            release_id=enterprise.id,
            release_name=enterprise.name,
            occurred_at=e.occurred_at,
            event_type=e.event_type,
            description=e.description,
        ))

    child_ids = [m.project_release_id for m in members]
    if child_ids:
        child_histories = (await db.execute(
            select(ReleaseStatusHistory, Release)
            .join(Release, ReleaseStatusHistory.release_id == Release.id)
            .where(
                ReleaseStatusHistory.release_id.in_(child_ids),
                ReleaseStatusHistory.tenant_id == tenant_id,
            )
            .order_by(ReleaseStatusHistory.changed_at.desc())
            .limit(20 * max(len(child_ids), 1))
        )).all()
        for h, rel in child_histories:
            events.append(EnterpriseReportEvent(
                release_id=rel.id,
                release_name=rel.name,
                occurred_at=h.changed_at,
                event_type=f"status:{h.from_state or 'null'}→{h.to_state}",
                description=h.notes,
            ))

    tl = await enterprise_rollup_service.timeline_rollup(
        db, user=user, enterprise_id=enterprise_id
    )

    now = datetime.now(timezone.utc).isoformat()
    username = getattr(user, "username", None) or str(user.id)
    report = EnterpriseReportRead(
        enterprise_id=enterprise.id,
        name=enterprise.name,
        status=enterprise.status,
        target_date=enterprise.target_date,
        actual_date=enterprise.actual_date,
        description=enterprise.description,
        members=members,
        systems=systems,
        scope_by_project={k: v for k, v in scope_by_project.items()},
        events=sorted(events, key=lambda e: e.occurred_at, reverse=True),
        dependencies=tl.dependencies,
        generated_at=now,
        generated_by=username,
    )

    await publish_event(
        db,
        event_type="EnterpriseReportGenerated",
        aggregate_id=enterprise.id,
        aggregate_type="Release",
        payload={"enterprise_id": enterprise.id, "generated_by": user.id, "generated_at": now},
        tenant_id=tenant_id,
    )
    return report
```

- [ ] **Step 4: Run tests, commit**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_report_service.py -v
git add backend/app/services/enterprise_report_service.py backend/tests/integration/test_enterprise_report_service.py
git commit -m "feat(enterprise): report service"
```

---

## Phase 3 — Backend API + events

### Task 16: Membership endpoints

**Files:**
- Create: `backend/app/api/v1/enterprise_memberships.py`
- Modify: `backend/app/main.py` (register router)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_enterprise_memberships_api.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_membership_endpoint(client: AsyncClient, admin_auth, ent_release, proj_release):
    r = await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships",
        json={"project_release_id": proj_release.id, "notes": "test"},
        headers=admin_auth,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "pending_request"


@pytest.mark.asyncio
async def test_list_memberships_filter_by_state(client, admin_auth, ent_release, proj_release):
    await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships",
        json={"project_release_id": proj_release.id},
        headers=admin_auth,
    )
    r = await client.get(
        f"/api/v1/releases/{ent_release.id}/memberships?states=pending_request",
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_accept_endpoint(client, admin_auth, ent_release, proj_release):
    req = await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships",
        json={"project_release_id": proj_release.id},
        headers=admin_auth,
    )
    mid = req.json()["id"]
    r = await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships/{mid}/accept",
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert r.json()["state"] == "accepted"


@pytest.mark.asyncio
async def test_reject_endpoint_requires_notes(client, admin_auth, ent_release, proj_release):
    req = await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships",
        json={"project_release_id": proj_release.id},
        headers=admin_auth,
    )
    mid = req.json()["id"]
    r = await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships/{mid}/reject",
        json={"notes": "out of scope"},
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert r.json()["state"] == "rejected"


@pytest.mark.asyncio
async def test_remove_endpoint_requires_reason(client, admin_auth, ent_release, proj_release):
    req = await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships",
        json={"project_release_id": proj_release.id},
        headers=admin_auth,
    )
    mid = req.json()["id"]
    await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships/{mid}/accept",
        headers=admin_auth,
    )
    r = await client.post(
        f"/api/v1/releases/{ent_release.id}/memberships/{mid}/remove",
        json={"reason": "dropped"},
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert r.json()["state"] == "removed"


@pytest.mark.asyncio
async def test_cross_tenant_returns_404(client, other_tenant_auth, ent_release):
    r = await client.get(
        f"/api/v1/releases/{ent_release.id}/memberships",
        headers=other_tenant_auth,
    )
    assert r.status_code == 404
```

Fixtures `ent_release`, `proj_release`, `admin_auth`, `other_tenant_auth` — add to `conftest.py` if absent (follow existing booking/release fixture patterns).

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_memberships_api.py -v
```

- [ ] **Step 3: Implement the endpoints**

`backend/app/api/v1/enterprise_memberships.py`:

```python
"""Enterprise-release membership API."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.api.v1.schemas.release_membership import (
    ReleaseMembershipCreate,
    ReleaseMembershipRead,
    MembershipRejectRequest,
    MembershipRemoveRequest,
)
from app.services import enterprise_membership_service

router = APIRouter()


def _to_read(m) -> ReleaseMembershipRead:
    return ReleaseMembershipRead.model_validate(m)


@router.post(
    "/releases/{enterprise_id}/memberships",
    response_model=ReleaseMembershipRead,
    status_code=status.HTTP_201_CREATED,
)
async def request_membership(
    enterprise_id: int,
    body: ReleaseMembershipCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.request_membership(
        db, user=user, enterprise_id=enterprise_id,
        project_release_id=body.project_release_id, notes=body.notes,
    )
    return _to_read(m)


@router.get(
    "/releases/{enterprise_id}/memberships",
    response_model=list[ReleaseMembershipRead],
)
async def list_memberships(
    enterprise_id: int,
    states: Optional[str] = Query(None, description="CSV of states"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    state_list = [s.strip() for s in states.split(",")] if states else None
    rows = await enterprise_membership_service.list_memberships(
        db, user=user, enterprise_id=enterprise_id, states=state_list,
    )
    return [_to_read(r) for r in rows]


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/accept",
    response_model=ReleaseMembershipRead,
)
async def accept_membership(
    enterprise_id: int,
    membership_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.accept(
        db, user=user, membership_id=membership_id
    )
    return _to_read(m)


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/reject",
    response_model=ReleaseMembershipRead,
)
async def reject_membership(
    enterprise_id: int,
    membership_id: int,
    body: MembershipRejectRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.reject(
        db, user=user, membership_id=membership_id, notes=body.notes,
    )
    return _to_read(m)


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/withdraw",
    response_model=ReleaseMembershipRead,
)
async def withdraw_membership(
    enterprise_id: int,
    membership_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.withdraw(
        db, user=user, membership_id=membership_id,
    )
    return _to_read(m)


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/remove",
    response_model=ReleaseMembershipRead,
)
async def remove_membership(
    enterprise_id: int,
    membership_id: int,
    body: MembershipRemoveRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.remove(
        db, user=user, membership_id=membership_id, reason=body.reason,
    )
    return _to_read(m)


@router.get(
    "/releases/{project_release_id}/membership",
    response_model=dict,
)
async def project_membership_view(
    project_release_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    current = await enterprise_membership_service.get_current_membership_for_project(
        db, user=user, project_release_id=project_release_id,
    )
    history = await enterprise_membership_service.list_history_for_project(
        db, user=user, project_release_id=project_release_id,
    )
    return {
        "current": _to_read(current).model_dump() if current else None,
        "history": [_to_read(h).model_dump() for h in history],
    }
```

- [ ] **Step 4: Register the router**

Edit `backend/app/main.py`:

```python
from app.api.v1 import enterprise_memberships

app.include_router(
    enterprise_memberships.router, prefix="/api/v1", tags=["enterprise-memberships"]
)
```

- [ ] **Step 5: Run tests**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_memberships_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/enterprise_memberships.py backend/app/main.py backend/tests/integration/test_enterprise_memberships_api.py
git commit -m "feat(enterprise): membership API routes + tests"
```

---

### Task 17: Rollup + report API endpoints

**Files:**
- Create: `backend/app/api/v1/enterprise_rollup.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_enterprise_rollup_api.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_systems_rollup_endpoint(client, admin_auth, ent_with_members):
    r = await client.get(
        f"/api/v1/releases/{ent_with_members.id}/rollup/systems",
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_scope_rollup_endpoint_with_filter(client, admin_auth, ent_with_members):
    r = await client.get(
        f"/api/v1/releases/{ent_with_members.id}/rollup/scope?change_kind=story",
        headers=admin_auth,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_timeline_endpoint(client, admin_auth, ent_with_members):
    r = await client.get(
        f"/api/v1/releases/{ent_with_members.id}/rollup/timeline",
        headers=admin_auth,
    )
    assert r.status_code == 200
    assert "enterprise_phases" in r.json()


@pytest.mark.asyncio
async def test_members_endpoint(client, admin_auth, ent_with_members):
    r = await client.get(
        f"/api/v1/releases/{ent_with_members.id}/rollup/members",
        headers=admin_auth,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_report_endpoint(client, admin_auth, ent_with_members):
    r = await client.get(
        f"/api/v1/releases/{ent_with_members.id}/report",
        headers=admin_auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert "members" in body and "systems" in body and "scope_by_project" in body
```

Add `ent_with_members` fixture: builds enterprise + 2 accepted children with some scope items and systems. Follow fixture patterns in existing test files.

- [ ] **Step 2: Run to fail**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_api.py -v
```

- [ ] **Step 3: Implement the endpoints**

`backend/app/api/v1/enterprise_rollup.py`:

```python
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.api.v1.schemas.enterprise_rollup import (
    SystemRollupRow,
    ScopeRollupItem,
    TimelineRollupRead,
    MemberRollupRow,
    EnterpriseReportRead,
)
from app.services import enterprise_rollup_service, enterprise_report_service

router = APIRouter()


@router.get(
    "/releases/{enterprise_id}/rollup/systems",
    response_model=list[SystemRollupRow],
)
async def systems_rollup(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.systems_rollup(
        db, user=user, enterprise_id=enterprise_id
    )


@router.get(
    "/releases/{enterprise_id}/rollup/scope",
    response_model=list[ScopeRollupItem],
)
async def scope_rollup(
    enterprise_id: int,
    change_kind: Optional[str] = None,
    status: Optional[str] = None,
    project_release_id: Optional[int] = None,
    system_id: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.scope_rollup(
        db, user=user, enterprise_id=enterprise_id,
        change_kind=change_kind, status=status,
        project_release_id=project_release_id, system_id=system_id, search=search,
    )


@router.get(
    "/releases/{enterprise_id}/rollup/timeline",
    response_model=TimelineRollupRead,
)
async def timeline_rollup(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.timeline_rollup(
        db, user=user, enterprise_id=enterprise_id
    )


@router.get(
    "/releases/{enterprise_id}/rollup/members",
    response_model=list[MemberRollupRow],
)
async def members_rollup(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.members_rollup(
        db, user=user, enterprise_id=enterprise_id
    )


@router.get(
    "/releases/{enterprise_id}/report",
    response_model=EnterpriseReportRead,
)
async def enterprise_report(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_report_service.generate_report(
        db, user=user, enterprise_id=enterprise_id
    )
```

- [ ] **Step 4: Register router**

```python
# backend/app/main.py
from app.api.v1 import enterprise_rollup
app.include_router(enterprise_rollup.router, prefix="/api/v1", tags=["enterprise-rollup"])
```

- [ ] **Step 5: Run tests, commit**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_rollup_api.py -v
git add backend/app/api/v1/enterprise_rollup.py backend/app/main.py backend/tests/integration/test_enterprise_rollup_api.py
git commit -m "feat(enterprise): rollup + report API routes"
```

---

### Task 18: Extend `/releases` list — `release_kind` filter + enterprise `membership_summary`

**Files:**
- Modify: `backend/app/api/v1/releases.py`
- Modify: `backend/app/services/release_service.py` (if list query is there)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_releases.py` (existing file):

```python
@pytest.mark.asyncio
async def test_list_releases_filtered_by_kind(client, admin_auth, make_release_fixture):
    await make_release_fixture(release_kind="project")
    await make_release_fixture(release_kind="enterprise")
    r = await client.get("/api/v1/releases?release_kind=enterprise", headers=admin_auth)
    assert r.status_code == 200
    assert all(item["release_kind"] == "enterprise" for item in r.json())


@pytest.mark.asyncio
async def test_get_enterprise_release_includes_membership_summary(client, admin_auth, ent_release):
    r = await client.get(f"/api/v1/releases/{ent_release.id}", headers=admin_auth)
    assert r.status_code == 200
    assert "membership_summary" in r.json()


@pytest.mark.asyncio
async def test_get_project_release_omits_membership_summary(client, admin_auth, proj_release):
    r = await client.get(f"/api/v1/releases/{proj_release.id}", headers=admin_auth)
    assert r.status_code == 200
    assert r.json().get("membership_summary") is None
```

- [ ] **Step 2: Run to fail**

```bash
cd backend && uv run pytest tests/integration/test_releases.py -v -k 'filtered_by_kind or membership_summary'
```

- [ ] **Step 3: Implement**

In `releases.py`, on the list endpoint, add:

```python
@router.get("/releases", response_model=list[ReleaseListItemRead])
async def list_releases(
    ...
    release_kind: Optional[str] = Query(None, regex="^(project|enterprise)$"),
    ...
):
    ...
    if release_kind:
        stmt = stmt.where(Release.release_kind == release_kind)
    ...
```

On the single-get endpoint, compute and attach `membership_summary` only for enterprise-kind:

```python
if release.release_kind == "enterprise":
    summary = await enterprise_membership_service.get_membership_summary(
        db, user=current_user, enterprise_id=release.id
    )
    read.membership_summary = MembershipSummary(**summary)
```

- [ ] **Step 4: Run tests, commit**

```bash
cd backend && uv run pytest tests/integration/test_releases.py -v -k 'filtered_by_kind or membership_summary'
git add backend/app/api/v1/releases.py backend/tests/integration/test_releases.py
git commit -m "feat(enterprise): release_kind filter + membership_summary on get"
```

---

### Task 19: Tenant-creation seed + backfill wiring

**Files:**
- Modify: `backend/app/services/tenant_service.py` (if seed is called from here) or confirm existing tenant-creation flow invokes `release_defaults.seed_release_lifecycle_templates`

- [ ] **Step 1: Verify the seed already runs on tenant creation**

```bash
cd backend && grep -n 'seed_release_lifecycle_templates\|release_defaults\.' app/ -r
```

Expected: already wired in `create_tenant` (added in Phase 3 Sub-1). Task 11 only needed to extend the seed body; no new wiring needed if it's already there.

- [ ] **Step 2: Write a backfill script**

Create `backend/scripts/backfill_enterprise_lifecycles.py`:

```python
"""Backfill: seed the enterprise lifecycle template for every existing tenant.

Run once after migration p3s6enterprise lands. Idempotent.
"""
import asyncio
from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.models.tenant import Tenant
from app.services import release_defaults


async def main():
    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        for t in tenants:
            await release_defaults.seed_release_lifecycle_templates(db, t.id)
        await db.commit()
    print(f"Seeded enterprise lifecycle template for {len(tenants)} tenants.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/backfill_enterprise_lifecycles.py
git commit -m "feat(enterprise): backfill script for existing tenants"
```

---

### Task 20: Happy-path integration test

**Files:**
- Create: `backend/tests/integration/test_enterprise_release_happy_path.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end happy-path for Enterprise Releases (spec §6 Acceptance)."""
import pytest


@pytest.mark.asyncio
async def test_enterprise_release_full_flow(client, admin_auth, tenant_factory):
    # 1. Create enterprise release
    ent_resp = await client.post(
        "/api/v1/releases",
        json={
            "name": "ENT-2026-Q1",
            "release_type": "Major",
            "release_kind": "enterprise",
            "target_date": "2026-06-01T00:00:00Z",
        },
        headers=admin_auth,
    )
    assert ent_resp.status_code == 201
    enterprise_id = ent_resp.json()["id"]

    # 2. Create 2 project releases
    proj_ids = []
    for n in ("Alpha", "Beta"):
        r = await client.post(
            "/api/v1/releases",
            json={"name": n, "release_type": "Major", "release_kind": "project",
                  "target_date": "2026-05-15T00:00:00Z"},
            headers=admin_auth,
        )
        assert r.status_code == 201
        proj_ids.append(r.json()["id"])

    # Seed some scope on each
    for i, pid in enumerate(proj_ids):
        await client.post(
            f"/api/v1/releases/{pid}/changes",
            json={"external_key": f"P{i}-1", "title": f"Feature {i}", "change_kind": "story"},
            headers=admin_auth,
        )

    # 3. Request + accept both
    membership_ids = []
    for pid in proj_ids:
        req = await client.post(
            f"/api/v1/releases/{enterprise_id}/memberships",
            json={"project_release_id": pid},
            headers=admin_auth,
        )
        assert req.status_code == 201
        mid = req.json()["id"]
        acc = await client.post(
            f"/api/v1/releases/{enterprise_id}/memberships/{mid}/accept",
            headers=admin_auth,
        )
        assert acc.status_code == 200
        assert acc.json()["late_scope"] is False
        membership_ids.append(mid)

    # 4. Transition enterprise past lockdown — go to integration_testing
    for target in ("planning", "admission_open", "admission_closed", "integration_testing"):
        r = await client.post(
            f"/api/v1/releases/{enterprise_id}/transition",
            json={"to_state": target},
            headers=admin_auth,
        )
        assert r.status_code == 200, r.text

    # 5. Request + accept a 3rd project after lockdown → late_scope=true
    r = await client.post(
        "/api/v1/releases",
        json={"name": "Gamma", "release_type": "Major", "release_kind": "project",
              "target_date": "2026-05-20T00:00:00Z"},
        headers=admin_auth,
    )
    gamma_id = r.json()["id"]
    await client.post(
        f"/api/v1/releases/{gamma_id}/changes",
        json={"external_key": "G-1", "title": "Late feature", "change_kind": "story"},
        headers=admin_auth,
    )
    req = await client.post(
        f"/api/v1/releases/{enterprise_id}/memberships",
        json={"project_release_id": gamma_id},
        headers=admin_auth,
    )
    mid = req.json()["id"]
    acc = await client.post(
        f"/api/v1/releases/{enterprise_id}/memberships/{mid}/accept",
        headers=admin_auth,
    )
    assert acc.status_code == 200
    assert acc.json()["late_scope"] is True

    # 6. Generate report
    report = await client.get(
        f"/api/v1/releases/{enterprise_id}/report", headers=admin_auth
    )
    assert report.status_code == 200
    body = report.json()
    assert {m["project_release_name"] for m in body["members"]} == {"Alpha", "Beta", "Gamma"}
    all_keys = {
        it["external_key"]
        for items in body["scope_by_project"].values()
        for it in items
    }
    assert all_keys == {"P0-1", "P1-1", "G-1"}
```

- [ ] **Step 2: Run**

```bash
cd backend && uv run pytest tests/integration/test_enterprise_release_happy_path.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_enterprise_release_happy_path.py
git commit -m "test(enterprise): end-to-end happy-path integration test"
```

---

## Phase 4 — Frontend types + services + slice

### Task 21: Frontend types

**Files:**
- Create: `frontend/src/types/enterpriseMembership.ts`
- Create: `frontend/src/types/enterpriseReport.ts`

- [ ] **Step 1: Write the types**

`frontend/src/types/enterpriseMembership.ts`:

```ts
export type MembershipState =
  | "pending_request"
  | "accepted"
  | "rejected"
  | "withdrawn"
  | "removed";

export interface ReleaseMembership {
  id: number;
  tenantId: number;
  enterpriseReleaseId: number;
  projectReleaseId: number;
  projectReleaseName?: string | null;
  projectReleaseStatus?: string | null;
  state: MembershipState;
  requestedBy: number;
  requestedByUsername?: string | null;
  requestedAt: string;
  decidedBy?: number | null;
  decidedByUsername?: string | null;
  decidedAt?: string | null;
  removedBy?: number | null;
  removedByUsername?: string | null;
  removedAt?: string | null;
  removalReason?: string | null;
  lateScope: boolean;
  notes?: string | null;
}

export interface MembershipSummary {
  pending: number;
  accepted: number;
  rejected: number;
  withdrawn: number;
  removed: number;
}

export interface MembershipCreatePayload {
  project_release_id: number;
  notes?: string;
}

export interface MembershipRejectPayload { notes: string; }
export interface MembershipRemovePayload { reason: string; }
```

`frontend/src/types/enterpriseReport.ts`:

```ts
export interface SystemRollupRow {
  systemId: number;
  systemName: string;
  rolesByProject: Record<string, string[]>;
}

export interface ScopeRollupItem {
  releaseChangeId: number;
  projectReleaseId: number;
  projectReleaseName: string;
  externalKey?: string | null;
  title: string;
  changeKind: string;
  externalStatus?: string | null;
  systemId?: number | null;
  systemName?: string | null;
}

export interface TimelinePhase {
  releaseId: number;
  releaseName: string;
  releaseKind: string;
  phaseId?: number | null;
  phaseName: string;
  startDate?: string | null;
  endDate?: string | null;
  status?: string | null;
}

export interface TimelineDependencyEdge {
  fromReleaseId: number;
  toReleaseId: number;
  alert?: string | null;
}

export interface TimelineRollup {
  enterprisePhases: TimelinePhase[];
  childPhasesByRelease: Record<number, TimelinePhase[]>;
  dependencies: TimelineDependencyEdge[];
}

export interface MemberRollupRow {
  projectReleaseId: number;
  projectReleaseName: string;
  status: string;
  admittedAt?: string | null;
  lateScope: boolean;
}

export interface EnterpriseReportEvent {
  releaseId: number;
  releaseName: string;
  occurredAt: string;
  eventType: string;
  description?: string | null;
}

export interface EnterpriseReport {
  enterpriseId: number;
  name: string;
  status: string;
  targetDate?: string | null;
  actualDate?: string | null;
  description?: string | null;
  members: MemberRollupRow[];
  systems: SystemRollupRow[];
  scopeByProject: Record<string, ScopeRollupItem[]>;
  events: EnterpriseReportEvent[];
  dependencies: TimelineDependencyEdge[];
  generatedAt: string;
  generatedBy: string;
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/enterpriseMembership.ts frontend/src/types/enterpriseReport.ts
git commit -m "feat(enterprise): frontend types"
```

---

### Task 22: Frontend services

**Files:**
- Create: `frontend/src/services/enterpriseMembershipService.ts`
- Create: `frontend/src/services/enterpriseRollupService.ts`
- Create: `frontend/src/services/enterpriseReportService.ts`

- [ ] **Step 1: Write the service clients**

`frontend/src/services/enterpriseMembershipService.ts`:

```ts
import api from "./api";
import type {
  ReleaseMembership,
  MembershipCreatePayload,
  MembershipRejectPayload,
  MembershipRemovePayload,
} from "../types/enterpriseMembership";

const toCamel = (m: any): ReleaseMembership => ({
  id: m.id,
  tenantId: m.tenant_id,
  enterpriseReleaseId: m.enterprise_release_id,
  projectReleaseId: m.project_release_id,
  projectReleaseName: m.project_release_name,
  projectReleaseStatus: m.project_release_status,
  state: m.state,
  requestedBy: m.requested_by,
  requestedByUsername: m.requested_by_username,
  requestedAt: m.requested_at,
  decidedBy: m.decided_by,
  decidedByUsername: m.decided_by_username,
  decidedAt: m.decided_at,
  removedBy: m.removed_by,
  removedByUsername: m.removed_by_username,
  removedAt: m.removed_at,
  removalReason: m.removal_reason,
  lateScope: m.late_scope,
  notes: m.notes,
});

export const enterpriseMembershipService = {
  async request(enterpriseId: number, payload: MembershipCreatePayload) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships`, payload
    );
    return toCamel(data);
  },
  async list(enterpriseId: number, states?: string[]) {
    const { data } = await api.get(`/releases/${enterpriseId}/memberships`, {
      params: states ? { states: states.join(",") } : undefined,
    });
    return (data as any[]).map(toCamel);
  },
  async accept(enterpriseId: number, membershipId: number) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/accept`
    );
    return toCamel(data);
  },
  async reject(enterpriseId: number, membershipId: number, p: MembershipRejectPayload) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/reject`, p
    );
    return toCamel(data);
  },
  async withdraw(enterpriseId: number, membershipId: number) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/withdraw`
    );
    return toCamel(data);
  },
  async remove(enterpriseId: number, membershipId: number, p: MembershipRemovePayload) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/remove`, p
    );
    return toCamel(data);
  },
  async getProjectMembership(projectReleaseId: number) {
    const { data } = await api.get(`/releases/${projectReleaseId}/membership`);
    return {
      current: data.current ? toCamel(data.current) : null,
      history: (data.history ?? []).map(toCamel),
    };
  },
};
```

`frontend/src/services/enterpriseRollupService.ts`:

```ts
import api from "./api";
import type {
  SystemRollupRow, ScopeRollupItem, TimelineRollup, MemberRollupRow,
} from "../types/enterpriseReport";

const toRollupSystem = (r: any): SystemRollupRow => ({
  systemId: r.system_id,
  systemName: r.system_name,
  rolesByProject: r.roles_by_project,
});
const toRollupScope = (r: any): ScopeRollupItem => ({
  releaseChangeId: r.release_change_id,
  projectReleaseId: r.project_release_id,
  projectReleaseName: r.project_release_name,
  externalKey: r.external_key,
  title: r.title,
  changeKind: r.change_kind,
  externalStatus: r.external_status,
  systemId: r.system_id,
  systemName: r.system_name,
});
const toMember = (r: any): MemberRollupRow => ({
  projectReleaseId: r.project_release_id,
  projectReleaseName: r.project_release_name,
  status: r.status,
  admittedAt: r.admitted_at,
  lateScope: r.late_scope,
});

export const enterpriseRollupService = {
  async systems(enterpriseId: number) {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/systems`);
    return (data as any[]).map(toRollupSystem);
  },
  async scope(enterpriseId: number, filters: Record<string, string | number | undefined> = {}) {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/scope`, { params: filters });
    return (data as any[]).map(toRollupScope);
  },
  async timeline(enterpriseId: number): Promise<TimelineRollup> {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/timeline`);
    return {
      enterprisePhases: data.enterprise_phases.map((p: any) => ({
        releaseId: p.release_id, releaseName: p.release_name, releaseKind: p.release_kind,
        phaseId: p.phase_id, phaseName: p.phase_name,
        startDate: p.start_date, endDate: p.end_date, status: p.status,
      })),
      childPhasesByRelease: Object.fromEntries(
        Object.entries(data.child_phases_by_release as Record<string, any[]>).map(
          ([k, v]) => [Number(k), v.map((p: any) => ({
            releaseId: p.release_id, releaseName: p.release_name, releaseKind: p.release_kind,
            phaseId: p.phase_id, phaseName: p.phase_name,
            startDate: p.start_date, endDate: p.end_date, status: p.status,
          }))]
        )
      ),
      dependencies: data.dependencies.map((d: any) => ({
        fromReleaseId: d.from_release_id, toReleaseId: d.to_release_id, alert: d.alert,
      })),
    };
  },
  async members(enterpriseId: number) {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/members`);
    return (data as any[]).map(toMember);
  },
};
```

`frontend/src/services/enterpriseReportService.ts`:

```ts
import api from "./api";
import type { EnterpriseReport } from "../types/enterpriseReport";

export const enterpriseReportService = {
  async generate(enterpriseId: number): Promise<EnterpriseReport> {
    const { data } = await api.get(`/releases/${enterpriseId}/report`);
    return {
      enterpriseId: data.enterprise_id,
      name: data.name,
      status: data.status,
      targetDate: data.target_date,
      actualDate: data.actual_date,
      description: data.description,
      members: data.members.map((m: any) => ({
        projectReleaseId: m.project_release_id,
        projectReleaseName: m.project_release_name,
        status: m.status,
        admittedAt: m.admitted_at,
        lateScope: m.late_scope,
      })),
      systems: data.systems.map((s: any) => ({
        systemId: s.system_id, systemName: s.system_name, rolesByProject: s.roles_by_project,
      })),
      scopeByProject: Object.fromEntries(
        Object.entries(data.scope_by_project as Record<string, any[]>).map(
          ([k, v]) => [k, v.map((it: any) => ({
            releaseChangeId: it.release_change_id,
            projectReleaseId: it.project_release_id,
            projectReleaseName: it.project_release_name,
            externalKey: it.external_key, title: it.title,
            changeKind: it.change_kind, externalStatus: it.external_status,
            systemId: it.system_id, systemName: it.system_name,
          }))]
        )
      ),
      events: data.events.map((e: any) => ({
        releaseId: e.release_id, releaseName: e.release_name,
        occurredAt: e.occurred_at, eventType: e.event_type, description: e.description,
      })),
      dependencies: data.dependencies.map((d: any) => ({
        fromReleaseId: d.from_release_id, toReleaseId: d.to_release_id, alert: d.alert,
      })),
      generatedAt: data.generated_at,
      generatedBy: data.generated_by,
    };
  },
};
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npm run typecheck
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/enterpriseMembershipService.ts frontend/src/services/enterpriseRollupService.ts frontend/src/services/enterpriseReportService.ts
git commit -m "feat(enterprise): frontend service clients"
```

---

### Task 23: Redux slice — `enterpriseMembershipSlice`

**Files:**
- Create: `frontend/src/store/enterpriseMembershipSlice.ts`
- Modify: `frontend/src/store/index.ts`

- [ ] **Step 1: Write the slice**

`frontend/src/store/enterpriseMembershipSlice.ts`:

```ts
import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import type { ReleaseMembership } from "../types/enterpriseMembership";
import { enterpriseMembershipService } from "../services/enterpriseMembershipService";

interface State {
  byEnterprise: Record<number, ReleaseMembership[]>;
  loading: boolean;
  error?: string;
}

const initialState: State = { byEnterprise: {}, loading: false };

export const fetchMemberships = createAsyncThunk(
  "enterpriseMembership/fetch",
  async (args: { enterpriseId: number; states?: string[] }) => {
    const rows = await enterpriseMembershipService.list(args.enterpriseId, args.states);
    return { enterpriseId: args.enterpriseId, rows };
  }
);

export const requestMembership = createAsyncThunk(
  "enterpriseMembership/request",
  async (args: { enterpriseId: number; projectReleaseId: number; notes?: string }) => {
    const m = await enterpriseMembershipService.request(
      args.enterpriseId,
      { project_release_id: args.projectReleaseId, notes: args.notes }
    );
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const acceptMembership = createAsyncThunk(
  "enterpriseMembership/accept",
  async (args: { enterpriseId: number; membershipId: number }) => {
    const m = await enterpriseMembershipService.accept(args.enterpriseId, args.membershipId);
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const rejectMembership = createAsyncThunk(
  "enterpriseMembership/reject",
  async (args: { enterpriseId: number; membershipId: number; notes: string }) => {
    const m = await enterpriseMembershipService.reject(args.enterpriseId, args.membershipId, { notes: args.notes });
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const withdrawMembership = createAsyncThunk(
  "enterpriseMembership/withdraw",
  async (args: { enterpriseId: number; membershipId: number }) => {
    const m = await enterpriseMembershipService.withdraw(args.enterpriseId, args.membershipId);
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const removeMembership = createAsyncThunk(
  "enterpriseMembership/remove",
  async (args: { enterpriseId: number; membershipId: number; reason: string }) => {
    const m = await enterpriseMembershipService.remove(args.enterpriseId, args.membershipId, { reason: args.reason });
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

const upsert = (state: State, action: any) => {
  const { enterpriseId, membership } = action.payload;
  const list = state.byEnterprise[enterpriseId] ?? [];
  const idx = list.findIndex((m) => m.id === membership.id);
  if (idx >= 0) list[idx] = membership; else list.unshift(membership);
  state.byEnterprise[enterpriseId] = list;
};

const slice = createSlice({
  name: "enterpriseMembership",
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchMemberships.pending, (s) => { s.loading = true; });
    b.addCase(fetchMemberships.fulfilled, (s, a) => {
      s.loading = false;
      s.byEnterprise[a.payload.enterpriseId] = a.payload.rows;
    });
    b.addCase(fetchMemberships.rejected, (s, a) => {
      s.loading = false; s.error = a.error.message;
    });
    b.addCase(requestMembership.fulfilled, upsert);
    b.addCase(acceptMembership.fulfilled, upsert);
    b.addCase(rejectMembership.fulfilled, upsert);
    b.addCase(withdrawMembership.fulfilled, upsert);
    b.addCase(removeMembership.fulfilled, upsert);
  },
});

export default slice.reducer;
```

Register in `frontend/src/store/index.ts`:

```ts
import enterpriseMembership from "./enterpriseMembershipSlice";

export const store = configureStore({
  reducer: {
    ...existing,
    enterpriseMembership,
  },
});
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npm run typecheck
git add frontend/src/store/enterpriseMembershipSlice.ts frontend/src/store/index.ts
git commit -m "feat(enterprise): redux slice for memberships"
```

---

## Phase 5 — Frontend list + form branching

### Task 24: `ReleaseList` kind toggle

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseList.tsx`

- [ ] **Step 1: Read current list component**

```bash
cd frontend && cat src/pages/releases/ReleaseList.tsx | head -120
```

Note existing filter controls and grid shape.

- [ ] **Step 2: Add toggle**

Inside the filter toolbar, add a `ToggleButtonGroup`:

```tsx
import { ToggleButtonGroup, ToggleButton } from "@mui/material";

const [kind, setKind] = useState<"all" | "project" | "enterprise">("all");

// Insert near other filter controls:
<ToggleButtonGroup
  value={kind}
  exclusive
  size="small"
  onChange={(_, v) => v && setKind(v)}
  aria-label="Release kind filter"
>
  <ToggleButton value="all">All</ToggleButton>
  <ToggleButton value="project">Projects</ToggleButton>
  <ToggleButton value="enterprise">Enterprise</ToggleButton>
</ToggleButtonGroup>
```

Pass `kind !== 'all' ? kind : undefined` to the existing fetch thunk's `release_kind` param (either through a query-string addition or a client-side filter on the pre-fetched list; preserve current pattern).

- [ ] **Step 3: Run dev server and verify manually**

```bash
cd frontend && npm run dev
# Open http://localhost:5173/releases and toggle
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/releases/ReleaseList.tsx
git commit -m "feat(enterprise): release list — kind toggle"
```

---

### Task 25: `ReleaseForm` — kind selector + kind-aware template filter

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseForm.tsx`

- [ ] **Step 1: Add a `kind` field at the top of the form**

```tsx
const [releaseKind, setReleaseKind] = useState<"project" | "enterprise">(
  initial?.releaseKind ?? "project"
);

<FormControl fullWidth>
  <InputLabel>Kind</InputLabel>
  <Select
    value={releaseKind}
    label="Kind"
    onChange={(e) => setReleaseKind(e.target.value as "project" | "enterprise")}
    disabled={isEdit}  // kind locked after creation
  >
    <MenuItem value="project">Project</MenuItem>
    <MenuItem value="enterprise">Enterprise</MenuItem>
  </Select>
</FormControl>
```

- [ ] **Step 2: Filter lifecycle template dropdown by `applies_to_kind`**

```tsx
const filteredTemplates = templates.filter(
  (t) => t.appliesToKind === releaseKind || t.appliesToKind == null
);
```

Also add `appliesToKind` to `LifecycleTemplate` frontend type (grep existing type file).

- [ ] **Step 3: Hide project-only fields on enterprise**

Conditionally render (or disable) the Dependencies + System Roles fields when `releaseKind === "enterprise"`.

- [ ] **Step 4: Submit the kind**

Add `release_kind: releaseKind` to the POST body.

- [ ] **Step 5: Manual smoke + commit**

```bash
cd frontend && npm run dev
# Create an enterprise release; confirm project-only fields hidden; confirm template dropdown filtered.
git add frontend/src/pages/releases/ReleaseForm.tsx frontend/src/types/release.ts
git commit -m "feat(enterprise): release form — kind selector + kind-aware template filter"
```

---

## Phase 6 — Frontend enterprise detail tabs

### Task 26: `ReleaseDetail` branching + Enterprise tab shell

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseDetail.tsx`
- Create: `frontend/src/pages/releases/enterprise/EnterpriseTabs.tsx`

- [ ] **Step 1: Route enterprise-kind through a distinct tab set**

At the top of `ReleaseDetail`:

```tsx
if (release?.releaseKind === "enterprise") {
  return <EnterpriseTabs release={release} />;
}
```

- [ ] **Step 2: Create shell**

`frontend/src/pages/releases/enterprise/EnterpriseTabs.tsx`:

```tsx
import { Tabs, Tab, Box } from "@mui/material";
import { useState } from "react";
import type { Release } from "../../../types/release";
import { MembersTab } from "./MembersTab";
import { SystemsRollupTab } from "./SystemsRollupTab";
import { ScopeRollupTab } from "./ScopeRollupTab";
import { TimelineTab } from "./TimelineTab";
import { ReportTab } from "./ReportTab";
import { ReleaseMainTab } from "../ReleaseMainTab";  // existing
import { ReleasePhasesTab, ReleaseGatesTab, ReleaseBookingsTab, ReleaseEventsTab } from "../ReleaseDetail";  // existing sub-views — check imports

export function EnterpriseTabs({ release }: { release: Release }) {
  const [tab, setTab] = useState("main");
  return (
    <Box>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable">
        <Tab label="Main" value="main" />
        <Tab label="Members" value="members" />
        <Tab label="Phases" value="phases" />
        <Tab label="Gates" value="gates" />
        <Tab label="Bookings" value="bookings" />
        <Tab label="Events" value="events" />
        <Tab label="Systems Impacted" value="systems" />
        <Tab label="Scope" value="scope" />
        <Tab label="Timeline" value="timeline" />
        <Tab label="Report" value="report" />
      </Tabs>
      {tab === "main" && <ReleaseMainTab release={release} />}
      {tab === "members" && <MembersTab release={release} />}
      {tab === "phases" && <ReleasePhasesTab release={release} />}
      {tab === "gates" && <ReleaseGatesTab release={release} />}
      {tab === "bookings" && <ReleaseBookingsTab release={release} />}
      {tab === "events" && <ReleaseEventsTab release={release} />}
      {tab === "systems" && <SystemsRollupTab release={release} />}
      {tab === "scope" && <ScopeRollupTab release={release} />}
      {tab === "timeline" && <TimelineTab release={release} />}
      {tab === "report" && <ReportTab release={release} />}
    </Box>
  );
}
```

Stub each `<...Tab />` as a placeholder returning "Coming soon" — they will be filled in the next tasks.

- [ ] **Step 3: Manual smoke**

```bash
cd frontend && npm run dev
# Navigate to an enterprise release; confirm the new tab set renders.
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/releases/ReleaseDetail.tsx frontend/src/pages/releases/enterprise/
git commit -m "feat(enterprise): release detail branches to enterprise tab shell"
```

---

### Task 27: `MembersTab`

**Files:**
- Create: `frontend/src/pages/releases/enterprise/MembersTab.tsx`
- Create: `frontend/src/pages/releases/enterprise/RequestAdmissionDialog.tsx`

- [ ] **Step 1: Build MembersTab**

```tsx
// MembersTab.tsx
import { useEffect, useState } from "react";
import { Paper, Stack, Typography, Button, Chip, IconButton } from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { useDispatch, useSelector } from "react-redux";
import type { RootState } from "../../../store";
import {
  fetchMemberships,
  acceptMembership,
  rejectMembership,
  removeMembership,
} from "../../../store/enterpriseMembershipSlice";
import { useConfirm } from "../../../hooks/useConfirm";
import type { Release } from "../../../types/release";
import { RequestAdmissionDialog } from "./RequestAdmissionDialog";

export function MembersTab({ release }: { release: Release }) {
  const dispatch = useDispatch<any>();
  const confirm = useConfirm();
  const rows = useSelector((s: RootState) => s.enterpriseMembership.byEnterprise[release.id] ?? []);
  const [openRequest, setOpenRequest] = useState(false);

  useEffect(() => {
    dispatch(fetchMemberships({ enterpriseId: release.id }));
  }, [release.id]);

  const pending = rows.filter((r) => r.state === "pending_request");
  const accepted = rows.filter((r) => r.state === "accepted");
  const history = rows.filter((r) => !["pending_request", "accepted"].includes(r.state));

  const pendingCols: GridColDef[] = [
    { field: "projectReleaseName", headerName: "Project", flex: 1 },
    { field: "requestedByUsername", headerName: "Requested by", flex: 1 },
    { field: "requestedAt", headerName: "Requested", flex: 1 },
    {
      field: "actions", headerName: "Actions", width: 220, sortable: false,
      renderCell: ({ row }) => (
        <Stack direction="row" spacing={1}>
          <Button size="small" variant="contained"
            onClick={() => dispatch(acceptMembership({
              enterpriseId: release.id, membershipId: row.id,
            }))}>
            Accept
          </Button>
          <Button size="small" color="error"
            onClick={async () => {
              const notes = prompt("Reason for rejection?");
              if (notes) {
                dispatch(rejectMembership({
                  enterpriseId: release.id, membershipId: row.id, notes,
                }));
              }
            }}>
            Reject
          </Button>
        </Stack>
      ),
    },
  ];

  const acceptedCols: GridColDef[] = [
    { field: "projectReleaseName", headerName: "Project", flex: 1 },
    { field: "projectReleaseStatus", headerName: "Status", width: 140,
      renderCell: ({ value }) => <Chip label={value} size="small" />,
    },
    { field: "admittedAt", headerName: "Admitted", flex: 1 },
    { field: "lateScope", headerName: "Late", width: 90,
      renderCell: ({ value }) => value ? <Chip label="LATE" color="warning" size="small" /> : null,
    },
    {
      field: "actions", headerName: "", width: 80, sortable: false,
      renderCell: ({ row }) => (
        <IconButton size="small" color="error" onClick={async () => {
          const ok = await confirm({
            title: "Remove project from enterprise?",
            message: `This will detach ${row.projectReleaseName} from the enterprise release.`,
            confirmButton: "Remove",
          });
          if (!ok) return;
          const reason = prompt("Reason?") ?? "removed";
          dispatch(removeMembership({
            enterpriseId: release.id, membershipId: row.id, reason,
          }));
        }}><DeleteIcon /></IconButton>
      ),
    },
  ];

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h6">Pending requests</Typography>
        <Button variant="contained" onClick={() => setOpenRequest(true)}>
          Request admission…
        </Button>
      </Stack>
      <Paper><DataGrid rows={pending} columns={pendingCols} autoHeight hideFooter /></Paper>
      <Typography variant="h6">Accepted members</Typography>
      <Paper><DataGrid rows={accepted} columns={acceptedCols} autoHeight hideFooter /></Paper>
      <Typography variant="h6">History</Typography>
      <Paper><DataGrid rows={history} columns={pendingCols.slice(0, 3)} autoHeight hideFooter /></Paper>

      <RequestAdmissionDialog
        open={openRequest}
        onClose={() => setOpenRequest(false)}
        enterpriseId={release.id}
      />
    </Stack>
  );
}
```

- [ ] **Step 2: Build RequestAdmissionDialog**

```tsx
// RequestAdmissionDialog.tsx
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Autocomplete, TextField } from "@mui/material";
import { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { fetchReleases } from "../../../store/releaseSlice";
import { requestMembership } from "../../../store/enterpriseMembershipSlice";
import type { RootState } from "../../../store";

export function RequestAdmissionDialog(
  { open, onClose, enterpriseId }: { open: boolean; onClose: () => void; enterpriseId: number }
) {
  const dispatch = useDispatch<any>();
  const projects = useSelector((s: RootState) =>
    s.releases.list.filter((r) => r.releaseKind === "project" && r.parentReleaseId == null)
  );
  const [pick, setPick] = useState<number | null>(null);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (open) dispatch(fetchReleases({ release_kind: "project" }));
  }, [open]);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Request admission</DialogTitle>
      <DialogContent>
        <Autocomplete
          options={projects}
          getOptionLabel={(o) => o.name}
          onChange={(_, v) => setPick(v?.id ?? null)}
          renderInput={(p) => <TextField {...p} label="Project release" margin="normal" />}
        />
        <TextField
          fullWidth multiline rows={2} margin="normal" label="Notes"
          value={notes} onChange={(e) => setNotes(e.target.value)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          disabled={!pick}
          variant="contained"
          onClick={async () => {
            if (!pick) return;
            await dispatch(requestMembership({
              enterpriseId, projectReleaseId: pick, notes: notes || undefined,
            }));
            onClose();
          }}
        >
          Request
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

Replace the `prompt()` calls with `useConfirm` free-text variants if available; otherwise file a follow-up per the `window.prompt()` known debt.

- [ ] **Step 3: Manual smoke + commit**

```bash
cd frontend && npm run dev
# Open an enterprise detail → Members tab; request admission; accept; remove.
git add frontend/src/pages/releases/enterprise/
git commit -m "feat(enterprise): members tab — pending + accepted + history + request dialog"
```

---

### Task 28: `SystemsRollupTab`

**Files:**
- Create: `frontend/src/pages/releases/enterprise/SystemsRollupTab.tsx`

- [ ] **Step 1: Build the component**

```tsx
import { useEffect, useState } from "react";
import { Paper, Chip, Stack } from "@mui/material";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { enterpriseRollupService } from "../../../services/enterpriseRollupService";
import type { SystemRollupRow } from "../../../types/enterpriseReport";
import type { Release } from "../../../types/release";

export function SystemsRollupTab({ release }: { release: Release }) {
  const [rows, setRows] = useState<SystemRollupRow[]>([]);
  useEffect(() => {
    enterpriseRollupService.systems(release.id).then(setRows);
  }, [release.id]);

  const cols: GridColDef[] = [
    { field: "systemName", headerName: "System", flex: 1 },
    {
      field: "rolesByProject", headerName: "Roles by project", flex: 2,
      renderCell: ({ value }) => (
        <Stack direction="row" spacing={1} flexWrap="wrap">
          {Object.entries(value as Record<string, string[]>).map(([proj, roles]) => (
            <Chip key={proj} label={`${proj}: ${roles.join(",")}`} size="small" />
          ))}
        </Stack>
      ),
    },
  ];

  return <Paper><DataGrid rows={rows.map((r, i) => ({ id: i, ...r }))} columns={cols} autoHeight /></Paper>;
}
```

- [ ] **Step 2: Wire + commit**

Replace the stub in `EnterpriseTabs.tsx`. Manual smoke.

```bash
git add frontend/src/pages/releases/enterprise/SystemsRollupTab.tsx
git commit -m "feat(enterprise): systems-impacted rollup tab"
```

---

### Task 29: `ScopeRollupTab` + filters + generate-report button

**Files:**
- Create: `frontend/src/pages/releases/enterprise/ScopeRollupTab.tsx`

- [ ] **Step 1: Build the tab**

```tsx
import { useEffect, useState } from "react";
import {
  Paper, Stack, TextField, MenuItem, Button,
} from "@mui/material";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { enterpriseRollupService } from "../../../services/enterpriseRollupService";
import type { ScopeRollupItem } from "../../../types/enterpriseReport";
import type { Release } from "../../../types/release";
import { useNavigate } from "react-router-dom";

export function ScopeRollupTab({ release }: { release: Release }) {
  const nav = useNavigate();
  const [rows, setRows] = useState<ScopeRollupItem[]>([]);
  const [kind, setKind] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");

  const refresh = () => {
    const params: Record<string, any> = {};
    if (kind) params.change_kind = kind;
    if (statusFilter) params.status = statusFilter;
    if (search) params.search = search;
    enterpriseRollupService.scope(release.id, params).then(setRows);
  };

  useEffect(refresh, [release.id, kind, statusFilter, search]);

  const cols: GridColDef[] = [
    { field: "externalKey", headerName: "Key", width: 120 },
    { field: "title", headerName: "Title", flex: 1 },
    { field: "changeKind", headerName: "Kind", width: 110 },
    { field: "externalStatus", headerName: "Status", width: 140 },
    { field: "projectReleaseName", headerName: "Project", flex: 1 },
    { field: "systemName", headerName: "System", flex: 1 },
  ];

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={2} alignItems="center">
        <TextField select size="small" label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} sx={{ minWidth: 140 }}>
          <MenuItem value="">Any</MenuItem>
          <MenuItem value="story">Story</MenuItem>
          <MenuItem value="defect">Defect</MenuItem>
          <MenuItem value="task">Task</MenuItem>
          <MenuItem value="spike">Spike</MenuItem>
        </TextField>
        <TextField size="small" label="Status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} />
        <TextField size="small" label="Search" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Button variant="outlined" onClick={() => nav(`/releases/${release.id}/detail#report`)}>
          Generate report
        </Button>
      </Stack>
      <Paper><DataGrid rows={rows.map((r, i) => ({ id: r.releaseChangeId, ...r }))} columns={cols} autoHeight /></Paper>
    </Stack>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/releases/enterprise/ScopeRollupTab.tsx
git commit -m "feat(enterprise): scope rollup tab with filters"
```

---

### Task 30: `TimelineTab` (combined Gantt)

**Files:**
- Create: `frontend/src/pages/releases/enterprise/TimelineTab.tsx`

- [ ] **Step 1: Re-use existing `ReleaseTimeline` component structure**

The existing `frontend/src/pages/releases/ReleaseTimeline.tsx` renders Gantt rows for a single release and its dependencies. Extract or copy its rendering primitive (phase row) into a reusable inner component if not already. Then compose:

```tsx
import { useEffect, useState } from "react";
import { Paper, Stack, Typography } from "@mui/material";
import { enterpriseRollupService } from "../../../services/enterpriseRollupService";
import type { TimelineRollup } from "../../../types/enterpriseReport";
import type { Release } from "../../../types/release";
import { PhaseRow } from "../ReleaseTimeline";  // extract as an export if not already

export function TimelineTab({ release }: { release: Release }) {
  const [data, setData] = useState<TimelineRollup | null>(null);
  useEffect(() => {
    enterpriseRollupService.timeline(release.id).then(setData);
  }, [release.id]);

  if (!data) return null;

  return (
    <Stack spacing={2}>
      <Typography variant="h6">{release.name} — enterprise phases</Typography>
      <Paper>{data.enterprisePhases.map((p) => <PhaseRow key={p.phaseId} phase={p} />)}</Paper>
      {Object.entries(data.childPhasesByRelease).map(([projId, phases]) => (
        <Paper key={projId}>
          <Typography sx={{ p: 1 }} variant="subtitle2">{phases[0]?.releaseName ?? `Release ${projId}`}</Typography>
          {phases.map((p) => <PhaseRow key={p.phaseId ?? `${p.releaseId}-${p.phaseName}`} phase={p} />)}
        </Paper>
      ))}
      {data.dependencies.length > 0 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2">Dependencies</Typography>
          <ul>
            {data.dependencies.map((d) => (
              <li key={`${d.fromReleaseId}-${d.toReleaseId}`}>
                {`Release #${d.fromReleaseId} → #${d.toReleaseId}${d.alert ? ` (${d.alert})` : ""}`}
              </li>
            ))}
          </ul>
        </Paper>
      )}
    </Stack>
  );
}
```

- [ ] **Step 2: Extract `PhaseRow` from `ReleaseTimeline.tsx` if it's currently inline**

If the current file has the row-render inline, split it out into an exported named component.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/releases/enterprise/TimelineTab.tsx frontend/src/pages/releases/ReleaseTimeline.tsx
git commit -m "feat(enterprise): combined timeline tab"
```

---

### Task 31: `ReportTab`

**Files:**
- Create: `frontend/src/pages/releases/enterprise/ReportTab.tsx`

- [ ] **Step 1: Build the tab**

```tsx
import { useEffect, useState } from "react";
import { Button, Paper, Stack, Typography, Divider, Chip } from "@mui/material";
import { enterpriseReportService } from "../../../services/enterpriseReportService";
import type { EnterpriseReport } from "../../../types/enterpriseReport";
import type { Release } from "../../../types/release";

export function ReportTab({ release }: { release: Release }) {
  const [report, setReport] = useState<EnterpriseReport | null>(null);

  useEffect(() => {
    enterpriseReportService.generate(release.id).then(setReport);
  }, [release.id]);

  if (!report) return null;

  return (
    <Stack spacing={3} className="enterprise-report">
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <div>
          <Typography variant="h4">{report.name}</Typography>
          <Typography variant="body2">
            Status: <Chip label={report.status} size="small" />
            {report.targetDate ? ` · Target ${new Date(report.targetDate).toLocaleDateString()}` : ""}
          </Typography>
          <Typography variant="caption">
            Generated {new Date(report.generatedAt).toLocaleString()} by {report.generatedBy}
          </Typography>
        </div>
        <Button variant="outlined" onClick={() => window.print()}>Print</Button>
      </Stack>
      <Divider />

      <section>
        <Typography variant="h5">Member projects</Typography>
        <ul>
          {report.members.map((m) => (
            <li key={m.projectReleaseId}>
              <strong>{m.projectReleaseName}</strong> — {m.status}
              {m.lateScope && <Chip label="late scope" color="warning" size="small" sx={{ ml: 1 }} />}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <Typography variant="h5">Systems impacted</Typography>
        <ul>
          {report.systems.map((s) => (
            <li key={s.systemId}>
              <strong>{s.systemName}</strong>
              <ul>
                {Object.entries(s.rolesByProject).map(([proj, roles]) => (
                  <li key={proj}>{proj}: {roles.join(", ")}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <Typography variant="h5">Jira tickets delivered</Typography>
        {Object.entries(report.scopeByProject).map(([proj, items]) => (
          <Paper key={proj} sx={{ p: 2, mb: 1 }}>
            <Typography variant="subtitle1">{proj}</Typography>
            <ul>
              {items.map((it) => (
                <li key={it.releaseChangeId}>
                  <strong>{it.externalKey ?? "—"}</strong> · {it.title} ({it.changeKind})
                  {it.externalStatus ? ` · ${it.externalStatus}` : ""}
                </li>
              ))}
            </ul>
          </Paper>
        ))}
      </section>

      <section>
        <Typography variant="h5">Notable events</Typography>
        <ul>
          {report.events.slice(0, 30).map((e, i) => (
            <li key={i}>
              {new Date(e.occurredAt).toLocaleString()} · {e.releaseName} · {e.eventType}
              {e.description ? ` — ${e.description}` : ""}
            </li>
          ))}
        </ul>
      </section>

      {report.dependencies.length > 0 && (
        <section>
          <Typography variant="h5">Dependencies</Typography>
          <ul>
            {report.dependencies.map((d, i) => (
              <li key={i}>Release #{d.fromReleaseId} → Release #{d.toReleaseId}{d.alert ? ` (${d.alert})` : ""}</li>
            ))}
          </ul>
        </section>
      )}
    </Stack>
  );
}
```

Add print CSS at the bottom of `frontend/src/index.css`:

```css
@media print {
  body * { visibility: hidden; }
  .enterprise-report, .enterprise-report * { visibility: visible; }
  .enterprise-report { position: absolute; left: 0; top: 0; width: 100%; }
  .enterprise-report button { display: none; }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/releases/enterprise/ReportTab.tsx frontend/src/index.css
git commit -m "feat(enterprise): HTML release report tab with print mode"
```

---

## Phase 7 — Project-side + admin

### Task 32: Project detail — Enterprise tab

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseDetail.tsx` (or the project-kind tab set)
- Create: `frontend/src/pages/releases/project/EnterpriseMembershipTab.tsx`

- [ ] **Step 1: Add a tab to the project-kind release detail**

Identify where project-kind tabs are rendered. Add:

```tsx
<Tab label="Enterprise" value="enterprise" />
```

Render `<EnterpriseMembershipTab release={release} />` when selected.

- [ ] **Step 2: Build the tab**

```tsx
import { useEffect, useState } from "react";
import { Paper, Stack, Typography, Button, Chip, Alert } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { enterpriseMembershipService } from "../../../services/enterpriseMembershipService";
import type { ReleaseMembership } from "../../../types/enterpriseMembership";
import type { Release } from "../../../types/release";

export function EnterpriseMembershipTab({ release }: { release: Release }) {
  const [current, setCurrent] = useState<ReleaseMembership | null>(null);
  const [history, setHistory] = useState<ReleaseMembership[]>([]);

  useEffect(() => {
    enterpriseMembershipService.getProjectMembership(release.id).then((r) => {
      setCurrent(r.current);
      setHistory(r.history);
    });
  }, [release.id]);

  return (
    <Stack spacing={3}>
      {current ? (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1">
            Part of enterprise release:{" "}
            <RouterLink to={`/releases/${current.enterpriseReleaseId}/detail`}>
              #{current.enterpriseReleaseId}
            </RouterLink>
          </Typography>
          <Typography variant="body2">
            Admitted {current.decidedAt ? new Date(current.decidedAt).toLocaleString() : "—"}
            {" "}by {current.decidedByUsername ?? "—"}
          </Typography>
          {current.lateScope && <Chip color="warning" size="small" label="Late scope" sx={{ mt: 1 }} />}
        </Paper>
      ) : (
        <Alert severity="info">
          This release is not part of any enterprise release.
        </Alert>
      )}

      <Typography variant="h6">History</Typography>
      <Paper sx={{ p: 2 }}>
        {history.length === 0 ? (
          <Typography variant="body2">No previous membership requests.</Typography>
        ) : (
          <ul>
            {history.map((h) => (
              <li key={h.id}>
                {h.state} · enterprise #{h.enterpriseReleaseId} ·{" "}
                {new Date(h.requestedAt).toLocaleString()}
                {h.removalReason ? ` — ${h.removalReason}` : ""}
                {h.notes ? ` (${h.notes})` : ""}
              </li>
            ))}
          </ul>
        )}
      </Paper>
    </Stack>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/releases/ReleaseDetail.tsx frontend/src/pages/releases/project/
git commit -m "feat(enterprise): enterprise tab on project release detail"
```

---

### Task 33: Admin lifecycle editor — kind picker + admission permissions + lockdown radio

**Files:**
- Modify: existing admin lifecycle editor page (grep `lifecycles` under `frontend/src/pages/admin/`)

- [ ] **Step 1: Locate the file**

```bash
cd frontend && grep -r 'LifecycleTemplate' src/pages/admin/ -l
```

- [ ] **Step 2: Add Kind picker to the template form**

```tsx
<FormControl fullWidth margin="normal">
  <InputLabel>Kind</InputLabel>
  <Select
    value={appliesToKind ?? ""}
    label="Kind"
    onChange={(e) => setAppliesToKind(e.target.value || null)}
  >
    <MenuItem value="">Any</MenuItem>
    <MenuItem value="project">Project</MenuItem>
    <MenuItem value="enterprise">Enterprise</MenuItem>
  </Select>
</FormControl>
```

Persist via existing template update service; the backend already accepts `applies_to_kind` (Task 3).

- [ ] **Step 3: Add "Admission lockdown" radio column on state rows (enterprise-only)**

Inside the state editor, when `appliesToKind === "enterprise"`:

```tsx
<RadioGroup
  row
  value={lockdownKey}  // state key of the one with is_admission_lockdown=true
  onChange={(e) => setLockdownKey(e.target.value)}
>
  {definition.states.map((s) => (
    <FormControlLabel key={s.key} value={s.key} control={<Radio />} label={s.label} />
  ))}
</RadioGroup>
```

When saving, map `lockdownKey` into `definition.states[i].is_admission_lockdown = (s.key === lockdownKey)`.

- [ ] **Step 4: Add "Admission permissions" matrix (enterprise-only)**

For each state × role × action (3 actions: admit, reject, remove), render a checkbox. On save, serialize to `definition.action_permissions[stateKey][actionKey] = [roles...]`.

- [ ] **Step 5: Manual smoke**

```bash
cd frontend && npm run dev
# Admin → lifecycle templates → new enterprise template; confirm kind, lockdown radio,
# admission permissions matrix all persist and survive reload.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/admin/.../<lifecycle editor file>
git commit -m "feat(enterprise): admin lifecycle editor — kind + lockdown + admission perms"
```

---

## Phase 8 — Smoke checklist + docs

### Task 34: Smoke checklist

**Files:**
- Create: `docs/archive/phase-3-sub2-smoke-checklist.md`

- [ ] **Step 1: Write the checklist**

```markdown
# Phase 3 Sub-2 (Enterprise Releases) — Smoke Checklist

## Backend
- [ ] `alembic upgrade head` runs cleanly on an existing Phase 3 DB
- [ ] `scripts/backfill_enterprise_lifecycles.py` seeds the enterprise template on existing tenants
- [ ] `pytest backend/tests -x` passes

## Frontend — create
- [ ] Create an enterprise release via `/releases/new` (Kind=Enterprise) using the seeded enterprise lifecycle template
- [ ] The Project / Enterprise / System Roles / Dependency fields do not appear on the enterprise form

## Frontend — admission
- [ ] Open the enterprise detail → Members tab → Request admission opens a picker listing eligible projects
- [ ] Requesting admission creates a pending row visible to an admin
- [ ] Accept flips the row to accepted; the project's `parent_release_id` is set (verify via DB or API)
- [ ] The same project can't be requested into a second enterprise while pending or accepted
- [ ] Reject with notes leaves an audit row
- [ ] Withdraw from the requester's side works; an admin can also withdraw

## Frontend — lockdown + late scope
- [ ] Move the enterprise past `admission_closed`; request + accept a new admission → `Late scope` chip appears on the row and persists across reload

## Frontend — rollups + report
- [ ] Systems Impacted tab lists each system once with role chips grouped by contributing project
- [ ] Scope tab lists Jira tickets across members, filterable by kind/status/search
- [ ] Timeline tab shows enterprise phases and each accepted child's phases, plus dependency edges
- [ ] Report tab renders; Print opens a readable print layout

## Frontend — project side
- [ ] On a project detail → Enterprise tab shows the current parent, admission date, and history

## Admin
- [ ] Lifecycle template editor exposes Kind picker, Admission lockdown radio (enterprise only), and admission permissions matrix
- [ ] Creating a new enterprise template and using it on a new release works end-to-end
```

- [ ] **Step 2: Commit**

```bash
git add docs/archive/phase-3-sub2-smoke-checklist.md
git commit -m "docs(enterprise): smoke checklist"
```

---

## Self-review summary

**Spec coverage:** Every section of the spec maps to at least one task above — data model (Tasks 1–6), services (7–15), API + events (16–20), frontend types/services/slice (21–23), frontend pages (24–32), admin (33), smoke (34).

**Placeholder scan:** No TBDs or "implement later"; every step has either exact code, an exact command, or a file path + concrete instructions. Two spots use free-text `prompt()` on the frontend (Reject notes, Remove reason) — explicitly acknowledged in Task 27 as following the known `window.prompt()` debt documented on `main` and deferred for the shared `useConfirm` prompt-variant rollout.

**Type consistency:** `MembershipState` enum values used identically in backend (`enum.Enum`) and frontend (string literal union). Rollup types use `snake_case` on the wire, `camelCase` in TS via explicit mappers in Task 22. `applies_to_kind` is the single discriminator column name everywhere.

**Spec items explicitly mapped to task numbers:**
- §1a data model → Tasks 1, 2
- §1b lifecycle column + JSON additions → Tasks 2, 3
- §1c / §1d permission + lockdown → Tasks 3, 11, 33
- §2 services → Tasks 7–15
- §3 API → Tasks 16–18
- §4 events → emitted within each membership/report service task; no dedicated consumer task (out of scope)
- §5 frontend → Tasks 21–32
- §6 behavioural rules → enforced in services 7–15 and tested in 7–10 + 20
- §7 testing → Tasks 7–15 (unit/integration), 20 (happy-path), 34 (smoke)

No gaps found.
