# Project Scope Deadline + Scope-Signoff Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give non-enterprise (project) releases a `scope_deadline` that (a) auto-creates a "Scope Sign-off" gate assigned to the Release Manager role and (b) flags scope items added after the deadline as scope creep.

**Architecture:** New nullable `release.scope_deadline` column + new nullable `gate_criterion.assigned_role` column. `release_service` orchestrates idempotent gate creation on deadline-set and due-date sync on deadline-change. Scope creep is computed (not stored) by comparing each scope item's "entered-release time" against the deadline, surfaced as `scope_creep_count` (release) and `is_scope_creep` (per item). Role-assigned criteria may only be completed by a user holding that role or an Admin.

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, Pydantic v2, PostgreSQL (SQLite for tests), React 18 + TypeScript + MUI + Redux Toolkit.

**Spec:** `docs/superpowers/specs/2026-07-26-project-scope-deadline-design.md`

**Conventions (verified in-repo):**
- Criterion statuses are `"open"` / `"done"` (NOT "completed").
- Services never call `db.commit()`; use `db.flush()`. `get_db()` auto-commits.
- Enum-ish columns use plain `String`, `native_enum=False` convention (here just `String`).
- Migrations are hand-written (no `--autogenerate`); current head is `raidlogtables`.
- Role constants live in `app/core/security.py` → `Role` (e.g. `Role.RELEASE_MANAGER == "Release Manager"`).
- Run backend tests: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest <path> -v` (match how existing tests run — most use an in-memory SQLite via conftest; if a plain `uv run pytest <path> -v` works in this repo, use that).

---

## Task 1: Migration — add `release.scope_deadline` + `gate_criterion.assigned_role`

**Files:**
- Create: `backend/app/db/migrations/versions/20260726_1200_scopedeadline_scope_deadline_assigned_role.py`

- [ ] **Step 1: Write the migration**

```python
"""project release scope_deadline + gate_criterion assigned_role

Revision ID: scopedeadline
Revises: raidlogtables
Create Date: 2026-07-26 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "scopedeadline"
down_revision: Union[str, None] = "raidlogtables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "release", "scope_deadline"):
        op.add_column(
            "release",
            sa.Column("scope_deadline", sa.DateTime(timezone=True), nullable=True),
        )
    if not _column_exists(conn, "gate_criterion", "assigned_role"):
        op.add_column(
            "gate_criterion",
            sa.Column("assigned_role", sa.String(length=50), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "gate_criterion", "assigned_role"):
        op.drop_column("gate_criterion", "assigned_role")
    if _column_exists(conn, "release", "scope_deadline"):
        op.drop_column("release", "scope_deadline")
```

- [ ] **Step 2: Verify the migration chains from the current head**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run alembic history | head -3`
Expected: `scopedeadline` appears above `raidlogtables`, no "multiple heads" error.

- [ ] **Step 3: Apply the migration**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run alembic upgrade head`
Expected: upgrade runs, ends at `scopedeadline`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/migrations/versions/20260726_1200_scopedeadline_scope_deadline_assigned_role.py
git commit -m "feat(releases): migration for scope_deadline + criterion assigned_role"
```

---

## Task 2: Model columns

**Files:**
- Modify: `backend/app/db/models/release.py:34` (after `deleted_at`)
- Modify: `backend/app/db/models/gate_criterion.py:22` (after `assigned_to_user_id`)

- [ ] **Step 1: Add `scope_deadline` to the Release model**

In `backend/app/db/models/release.py`, inside `class Release`, after the `deleted_at` line, add:

```python
    scope_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Add `assigned_role` to the GateCriterion model**

In `backend/app/db/models/gate_criterion.py`, inside `class GateCriterion`, immediately after the `assigned_to_user_id` mapped_column block, add:

```python
    assigned_role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 3: Verify models import cleanly**

Run: `cd backend && PYTHONPATH=. uv run python -c "from app.db.models.release import Release; from app.db.models.gate_criterion import GateCriterion; print(Release.scope_deadline, GateCriterion.assigned_role)"`
Expected: prints two column objects, no error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/release.py backend/app/db/models/gate_criterion.py
git commit -m "feat(releases): add scope_deadline + assigned_role model columns"
```

---

## Task 3: Pydantic schemas

**Files:**
- Modify: `backend/app/api/v1/schemas/release.py`
- Modify: `backend/app/api/v1/schemas/gate_criterion.py`
- Modify: `backend/app/api/v1/schemas/release_change.py:55-57`
- Test: `backend/tests/integration/test_scope_deadline_schemas.py`

- [ ] **Step 1: Write failing schema tests**

Create `backend/tests/integration/test_scope_deadline_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from app.api.v1.schemas.gate_criterion import GateCriterionCreate


def test_criterion_accepts_valid_role():
    c = GateCriterionCreate(title="Scope signed off", assigned_role="Release Manager")
    assert c.assigned_role == "Release Manager"


def test_criterion_rejects_unknown_role():
    with pytest.raises(ValidationError):
        GateCriterionCreate(title="x", assigned_role="Wizard")


def test_criterion_rejects_role_and_user_together():
    with pytest.raises(ValidationError):
        GateCriterionCreate(title="x", assigned_role="Release Manager", assigned_to_user_id=5)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_deadline_schemas.py -v`
Expected: FAIL — `GateCriterionCreate` has no `assigned_role`.

- [ ] **Step 3: Update the release schemas**

In `backend/app/api/v1/schemas/release.py`:

Add `scope_deadline` to `ReleaseCreate` (after `target_date`):
```python
    scope_deadline: Optional[datetime] = None
```
Add `scope_deadline` to `ReleaseUpdate` (after `target_date`):
```python
    scope_deadline: Optional[datetime] = None
```
Add both fields to `ReleaseRead` (after `actual_date`):
```python
    scope_deadline: Optional[datetime] = None
```
Add the creep KPI to `ReleaseListItemRead` (after `scope_change_count`):
```python
    scope_creep_count: int = 0
```
Also add `scope_creep_count` to `ReleaseRead` so the single-release GET carries it (after `scope_deadline`):
```python
    scope_creep_count: int = 0
```

- [ ] **Step 4: Update the gate criterion schemas**

Replace the whole `backend/app/api/v1/schemas/gate_criterion.py` create/update/read section with:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security import Role

_VALID_ROLES = {
    Role.ADMIN, Role.RELEASE_MANAGER, Role.TEST_MANAGER, Role.DEVELOPER, Role.VIEWER,
}


class GateCriterionCreate(BaseModel):
    title: str = Field(..., max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None
    assigned_role: Optional[str] = Field(None, max_length=50)

    @field_validator("assigned_role")
    @classmethod
    def _valid_role(cls, v):
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"assigned_role must be one of {sorted(_VALID_ROLES)}")
        return v

    @model_validator(mode="after")
    def _one_assignee(self):
        if self.assigned_role is not None and self.assigned_to_user_id is not None:
            raise ValueError("A criterion cannot be assigned to both a user and a role")
        return self


class GateCriterionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None
    assigned_role: Optional[str] = Field(None, max_length=50)

    @field_validator("assigned_role")
    @classmethod
    def _valid_role(cls, v):
        if v is not None and v not in _VALID_ROLES:
            raise ValueError(f"assigned_role must be one of {sorted(_VALID_ROLES)}")
        return v

    @model_validator(mode="after")
    def _one_assignee(self):
        if self.assigned_role is not None and self.assigned_to_user_id is not None:
            raise ValueError("A criterion cannot be assigned to both a user and a role")
        return self


class GateCriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    title: str
    notes: Optional[str]
    assigned_to_user_id: Optional[int]
    assigned_to_username: Optional[str] = None
    assigned_role: Optional[str] = None
    status: str
    completed_at: Optional[datetime]
    completed_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime
```

Keep the existing `GateCriterionWithGate` subclass unchanged (it already extends `GateCriterionRead`).

- [ ] **Step 5: Add `is_scope_creep` to the scope-item read schema**

In `backend/app/api/v1/schemas/release_change.py`, inside `ReleaseChangeRead`, after `time_in_current_status_seconds`:
```python
    is_scope_creep: bool = False
```

- [ ] **Step 6: Run tests to verify pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_deadline_schemas.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/schemas/release.py backend/app/api/v1/schemas/gate_criterion.py backend/app/api/v1/schemas/release_change.py backend/tests/integration/test_scope_deadline_schemas.py
git commit -m "feat(releases): scope_deadline + assigned_role + is_scope_creep schemas"
```

---

## Task 4: Release service — deadline handling + scope-signoff gate orchestration

**Files:**
- Modify: `backend/app/services/release_service.py`
- Test: `backend/tests/integration/test_scope_deadline_gate.py`

Note: `create_gate` (in `release_gate_service`) takes `ReleaseGateCreate(name, due_date)` and returns the gate. `create_criterion` (in `gate_criterion_service`) takes `GateCriterionCreate` and `user_id`. Import both lazily inside the helper to avoid circular imports (existing pattern in this module).

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/integration/test_scope_deadline_gate.py`:

```python
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.release_gate import ReleaseGate
from app.db.models.gate_criterion import GateCriterion
from app.services import release_service
from app.services.release_service import SCOPE_SIGNOFF_GATE_NAME
from app.api.v1.schemas.release import ReleaseCreate, ReleaseUpdate


async def _gates(db, release_id, tenant_id):
    return (await db.execute(
        select(ReleaseGate).where(
            ReleaseGate.release_id == release_id,
            ReleaseGate.tenant_id == tenant_id,
            ReleaseGate.deleted_at.is_(None),
        )
    )).scalars().all()


@pytest.mark.asyncio
async def test_setting_deadline_at_create_makes_gate(db_session, tenant, user, release_lifecycle_template):
    deadline = datetime.now(timezone.utc) + timedelta(days=7)
    rel = await release_service.create_release(
        db_session,
        ReleaseCreate(name="R1", release_type="Test Major", release_kind="project", scope_deadline=deadline),
        tenant.id, user.id,
    )
    await db_session.flush()
    gates = await _gates(db_session, rel.id, tenant.id)
    assert len(gates) == 1
    assert gates[0].name == SCOPE_SIGNOFF_GATE_NAME
    assert gates[0].due_date == deadline
    crits = (await db_session.execute(
        select(GateCriterion).where(GateCriterion.gate_id == gates[0].id)
    )).scalars().all()
    assert len(crits) == 1
    assert crits[0].title == "Scope signed off"
    assert crits[0].assigned_role == "Release Manager"


@pytest.mark.asyncio
async def test_setting_deadline_on_update_makes_gate_idempotently(db_session, tenant, user, release_lifecycle_template):
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R2", release_type="Test Major", release_kind="project"),
        tenant.id, user.id,
    )
    await db_session.flush()
    d1 = datetime.now(timezone.utc) + timedelta(days=3)
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=d1), tenant.id, user.id)
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=d1), tenant.id, user.id)
    gates = await _gates(db_session, rel.id, tenant.id)
    assert len(gates) == 1  # idempotent — not two gates


@pytest.mark.asyncio
async def test_changing_deadline_syncs_pending_gate_due_date(db_session, tenant, user, release_lifecycle_template):
    d1 = datetime.now(timezone.utc) + timedelta(days=3)
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R3", release_type="Test Major", release_kind="project", scope_deadline=d1),
        tenant.id, user.id,
    )
    await db_session.flush()
    d2 = d1 + timedelta(days=5)
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=d2), tenant.id, user.id)
    gates = await _gates(db_session, rel.id, tenant.id)
    assert gates[0].due_date == d2


@pytest.mark.asyncio
async def test_clearing_deadline_keeps_gate(db_session, tenant, user, release_lifecycle_template):
    d1 = datetime.now(timezone.utc) + timedelta(days=3)
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R4", release_type="Test Major", release_kind="project", scope_deadline=d1),
        tenant.id, user.id,
    )
    await db_session.flush()
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=None), tenant.id, user.id)
    gates = await _gates(db_session, rel.id, tenant.id)
    assert len(gates) == 1  # kept


@pytest.mark.asyncio
async def test_enterprise_release_rejects_deadline(db_session, tenant, user, release_lifecycle_template):
    with pytest.raises(HTTPException) as ei:
        await release_service.create_release(
            db_session,
            ReleaseCreate(name="ENT", release_type="Test Major", release_kind="enterprise",
                          scope_deadline=datetime.now(timezone.utc)),
            tenant.id, user.id,
        )
    assert ei.value.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_deadline_gate.py -v`
Expected: FAIL — `SCOPE_SIGNOFF_GATE_NAME` / `scope_deadline` handling not implemented.

- [ ] **Step 3: Add the gate constant + orchestration helpers**

In `backend/app/services/release_service.py`, after the `_DEPLOYED_TERMINAL_STATES` line, add:

```python
SCOPE_SIGNOFF_GATE_NAME = "Scope Sign-off"
_SCOPE_SIGNOFF_CRITERION_TITLE = "Scope signed off"
```

Add these helpers in the "Internal helpers" section:

```python
async def _find_scope_signoff_gate(db: AsyncSession, release_id: int, tenant_id: int):
    from app.db.models.release_gate import ReleaseGate
    return (
        await db.execute(
            select(ReleaseGate).where(
                ReleaseGate.release_id == release_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.name == SCOPE_SIGNOFF_GATE_NAME,
                ReleaseGate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _ensure_scope_signoff_gate(
    db: AsyncSession, release: Release, tenant_id: int, user_id: int
) -> None:
    """Idempotently create the Scope Sign-off gate + its role-assigned criterion.
    No-op if a gate with that name already exists on the release."""
    from app.core.security import Role
    from app.services import release_gate_service, gate_criterion_service
    from app.api.v1.schemas.release_gate import ReleaseGateCreate
    from app.api.v1.schemas.gate_criterion import GateCriterionCreate

    if release.scope_deadline is None:
        return
    if await _find_scope_signoff_gate(db, release.id, tenant_id) is not None:
        return

    gate = await release_gate_service.create_gate(
        db, release.id,
        ReleaseGateCreate(name=SCOPE_SIGNOFF_GATE_NAME, due_date=release.scope_deadline),
        tenant_id,
    )
    await gate_criterion_service.create_criterion(
        db, gate_id=gate.id, tenant_id=tenant_id, user_id=user_id,
        data=GateCriterionCreate(
            title=_SCOPE_SIGNOFF_CRITERION_TITLE,
            assigned_role=Role.RELEASE_MANAGER,
        ),
    )


async def _sync_scope_signoff_due_date(
    db: AsyncSession, release: Release, tenant_id: int
) -> None:
    """If a pending Scope Sign-off gate exists, re-sync its due_date to the
    current scope_deadline. Decided gates are left untouched."""
    if release.scope_deadline is None:
        return
    gate = await _find_scope_signoff_gate(db, release.id, tenant_id)
    if gate is not None and gate.status == "pending":
        gate.due_date = release.scope_deadline
        await db.flush()
```

- [ ] **Step 4: Wire deadline handling into `create_release`**

In `create_release`, immediately after `tpl = await _resolve_lifecycle_template(...)` add the enterprise guard:

```python
    if data.scope_deadline is not None and data.release_kind == "enterprise":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "scope_deadline is only valid on project releases",
        )
```

Add `scope_deadline=data.scope_deadline,` to the `Release(...)` constructor (after `target_date=data.target_date,`).

After the `publish_event(...)` call and before `return release`, add:

```python
    await _ensure_scope_signoff_gate(db, release, tenant_id, user_id)
```

- [ ] **Step 5: Wire deadline handling into `update_release`**

In `update_release`, replace the body from `update_data = data.model_dump(exclude_unset=True)` down to (but not including) the `if target_date_changed:` block with:

```python
    old_scope_deadline = release.scope_deadline

    update_data = data.model_dump(exclude_unset=True)

    if (
        "scope_deadline" in update_data
        and update_data["scope_deadline"] is not None
        and release.release_kind == "enterprise"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "scope_deadline is only valid on project releases",
        )

    for field, value in update_data.items():
        setattr(release, field, value)

    await db.flush()
    await db.refresh(release)

    if "scope_deadline" in update_data:
        new_deadline = release.scope_deadline
        if old_scope_deadline is None and new_deadline is not None:
            await _ensure_scope_signoff_gate(db, release, tenant_id, user_id)
        elif (
            old_scope_deadline is not None
            and new_deadline is not None
            and old_scope_deadline != new_deadline
        ):
            await _sync_scope_signoff_due_date(db, release, tenant_id)
        # cleared (set → None): keep the gate, do nothing
```

(The existing `target_date_changed` computation above this block and the `if target_date_changed:` event block below it stay unchanged.)

- [ ] **Step 6: Run tests to verify pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_deadline_gate.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/release_service.py backend/tests/integration/test_scope_deadline_gate.py
git commit -m "feat(releases): auto-create scope-signoff gate on scope_deadline set"
```

---

## Task 5: Scope-creep computation

**Files:**
- Modify: `backend/app/services/release_scope_service.py`
- Test: `backend/tests/integration/test_scope_creep.py`

"Entered-release time" = earliest `ReleaseChangeReleaseHistory.moved_at` where `to_release_id == change.release_id`, falling back to `change.created_at`.

- [ ] **Step 1: Write failing creep tests**

Create `backend/tests/integration/test_scope_creep.py`:

```python
from datetime import datetime, timezone, timedelta

import pytest

from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.services import release_scope_service


async def _release(db, tenant_id, template_id, deadline):
    r = Release(
        tenant_id=tenant_id, name="Creep R", release_type="Test Major",
        release_kind="project", lifecycle_template_id=template_id,
        status="draft", raised_by=1, scope_deadline=deadline,
    )
    db.add(r)
    await db.flush()
    return r


@pytest.mark.asyncio
async def test_item_created_after_deadline_is_creep(db_session, tenant, release_lifecycle_template):
    deadline = datetime.now(timezone.utc) - timedelta(days=1)  # deadline in the past
    rel = await _release(db_session, tenant.id, release_lifecycle_template.id, deadline)
    # create_change writes an initial history row (moved_at = now, i.e. after the deadline)
    from app.api.v1.schemas.release_change import ReleaseChangeCreate
    ch = await release_scope_service.create_change(
        db_session, rel.id, ReleaseChangeCreate(title="late story", change_kind="story"),
        tenant.id, user_id=1,
    )
    ids = await release_scope_service.scope_creep_change_ids(db_session, rel, tenant.id)
    assert ch.id in ids
    counts = await release_scope_service.scope_creep_counts(db_session, [rel.id], tenant.id)
    assert counts.get(rel.id) == 1


@pytest.mark.asyncio
async def test_no_deadline_means_no_creep(db_session, tenant, release_lifecycle_template):
    rel = await _release(db_session, tenant.id, release_lifecycle_template.id, None)
    from app.api.v1.schemas.release_change import ReleaseChangeCreate
    await release_scope_service.create_change(
        db_session, rel.id, ReleaseChangeCreate(title="s", change_kind="story"), tenant.id, user_id=1,
    )
    ids = await release_scope_service.scope_creep_change_ids(db_session, rel, tenant.id)
    assert ids == set()
    counts = await release_scope_service.scope_creep_counts(db_session, [rel.id], tenant.id)
    assert counts.get(rel.id, 0) == 0


@pytest.mark.asyncio
async def test_item_entered_before_deadline_is_not_creep(db_session, tenant, release_lifecycle_template):
    deadline = datetime.now(timezone.utc) + timedelta(days=30)  # deadline far in the future
    rel = await _release(db_session, tenant.id, release_lifecycle_template.id, deadline)
    from app.api.v1.schemas.release_change import ReleaseChangeCreate
    ch = await release_scope_service.create_change(
        db_session, rel.id, ReleaseChangeCreate(title="early", change_kind="story"), tenant.id, user_id=1,
    )
    ids = await release_scope_service.scope_creep_change_ids(db_session, rel, tenant.id)
    assert ch.id not in ids
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_creep.py -v`
Expected: FAIL — `scope_creep_change_ids` / `scope_creep_counts` not defined.

- [ ] **Step 3: Add the creep helpers**

In `backend/app/services/release_scope_service.py`, add near the top-level imports (they are already imported except `func`; ensure `from sqlalchemy import func, select`):

```python
from sqlalchemy import func, select
```

Then add these functions at the end of the file:

```python
def _entered_time_expr():
    """SQLAlchemy expression: the time a ReleaseChange entered ITS current
    release. = earliest history moved_at into that release, else created_at."""
    entered = (
        select(func.min(ReleaseChangeReleaseHistory.moved_at))
        .where(
            ReleaseChangeReleaseHistory.change_id == ReleaseChange.id,
            ReleaseChangeReleaseHistory.to_release_id == ReleaseChange.release_id,
        )
        .correlate(ReleaseChange)
        .scalar_subquery()
    )
    return func.coalesce(entered, ReleaseChange.created_at)


async def scope_creep_counts(
    db: AsyncSession, release_ids: list[int], tenant_id: int
) -> dict[int, int]:
    """Map release_id -> count of scope items that entered after that release's
    scope_deadline. Releases without a deadline contribute nothing."""
    if not release_ids:
        return {}
    entered_time = _entered_time_expr()
    stmt = (
        select(ReleaseChange.release_id, func.count().label("cnt"))
        .join(Release, Release.id == ReleaseChange.release_id)
        .where(
            ReleaseChange.release_id.in_(release_ids),
            ReleaseChange.tenant_id == tenant_id,
            ReleaseChange.deleted_at.is_(None),
            Release.scope_deadline.is_not(None),
            entered_time > Release.scope_deadline,
        )
        .group_by(ReleaseChange.release_id)
    )
    rows = (await db.execute(stmt)).all()
    return {row[0]: row[1] for row in rows}


async def scope_creep_change_ids(
    db: AsyncSession, release: Release, tenant_id: int
) -> set[int]:
    """Set of ReleaseChange ids on `release` that entered after its deadline."""
    if release.scope_deadline is None:
        return set()
    entered_time = _entered_time_expr()
    stmt = select(ReleaseChange.id).where(
        ReleaseChange.release_id == release.id,
        ReleaseChange.tenant_id == tenant_id,
        ReleaseChange.deleted_at.is_(None),
        entered_time > release.scope_deadline,
    )
    return set((await db.execute(stmt)).scalars().all())
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_creep.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_scope_service.py backend/tests/integration/test_scope_creep.py
git commit -m "feat(releases): scope-creep computation helpers"
```

---

## Task 6: Surface creep in the release list + single-release changes endpoints

**Files:**
- Modify: `backend/app/api/v1/releases.py` (list endpoint ~line 256-269; changes endpoint ~line 858-866)
- Test: `backend/tests/integration/test_scope_creep_api.py`

- [ ] **Step 1: Write failing API test**

Create `backend/tests/integration/test_scope_creep_api.py`. Reuse the `authed_client` fixture pattern (copy the local `authed_client` fixture from `tests/integration/test_release_happy_path.py:18-35` into this file, since it's file-local there):

```python
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username, "password": "password123", "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_creep_surfaced_in_list_and_changes(authed_client, release_lifecycle_template):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Creepy", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id, "scope_deadline": past,
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    c = await authed_client.post(f"/api/v1/releases/{rid}/changes", json={
        "title": "late item", "change_kind": "story",
    })
    assert c.status_code == 201, c.text

    lst = await authed_client.get("/api/v1/releases")
    assert lst.status_code == 200
    mine = next(x for x in lst.json() if x["id"] == rid)
    assert mine["scope_creep_count"] == 1

    ch = await authed_client.get(f"/api/v1/releases/{rid}/changes")
    assert ch.status_code == 200
    assert ch.json()[0]["is_scope_creep"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_creep_api.py -v`
Expected: FAIL — `scope_creep_count` is 0 / `is_scope_creep` absent or False.

- [ ] **Step 3: Populate `scope_creep_count` in the list endpoint**

In `backend/app/api/v1/releases.py`, in `list_releases`, after the `removals = {...}` block (~line 254) and before `result = []`, add:

```python
    creep_counts = await release_scope_service.scope_creep_counts(db, release_ids, tenant_id)
```

Then in the per-release loop, after `item.scope_change_count = adds + rems`, add:

```python
        item.scope_creep_count = creep_counts.get(r.id, 0)
```

- [ ] **Step 4: Populate `is_scope_creep` in the single-release changes endpoint**

In `backend/app/api/v1/releases.py`, replace the body of `list_changes` (the `@router.get("/{release_id}/changes")` handler, ~line 858) with:

```python
async def list_changes(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await _require_release(db, release_id, tenant_id)
    rows = await release_scope_service.list_changes(db, release_id, tenant_id)
    creep_ids = await release_scope_service.scope_creep_change_ids(db, release, tenant_id)
    out: list[ReleaseChangeRead] = []
    for r in rows:
        item = ReleaseChangeRead.model_validate(r)
        item.is_scope_creep = r.id in creep_ids
        out.append(item)
    return out
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_creep_api.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/releases.py backend/tests/integration/test_scope_creep_api.py
git commit -m "feat(releases): surface scope_creep_count + is_scope_creep in API"
```

---

## Task 7: Role-based criterion completion authz + assigned_role plumbing

**Files:**
- Modify: `backend/app/services/gate_criterion_service.py` (`create_criterion`, `complete_criterion`, `reopen_criterion`)
- Modify: `backend/app/api/v1/gate_criteria.py` (`_crit_to_dict`, complete/reopen endpoints)
- Modify: `backend/app/services/release_gate_service.py` (`list_gates` criterion dict ~line 134)
- Test: `backend/tests/integration/test_criterion_role_authz.py`

- [ ] **Step 1: Write failing authz test**

Create `backend/tests/integration/test_criterion_role_authz.py`:

```python
import pytest
from fastapi import HTTPException

from app.core.security import Role
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import gate_criterion_service
from app.api.v1.schemas.gate_criterion import GateCriterionCreate


async def _gate_with_role_criterion(db, tenant_id, template_id):
    r = Release(tenant_id=tenant_id, name="AZ", release_type="Test Major", release_kind="project",
                lifecycle_template_id=template_id, status="draft", raised_by=1)
    db.add(r)
    await db.flush()
    from datetime import datetime, timezone
    g = ReleaseGate(tenant_id=tenant_id, release_id=r.id, name="Scope Sign-off",
                    due_date=datetime.now(timezone.utc), status="pending")
    db.add(g)
    await db.flush()
    crit = await gate_criterion_service.create_criterion(
        db, gate_id=g.id, tenant_id=tenant_id, user_id=1,
        data=GateCriterionCreate(title="Scope signed off", assigned_role=Role.RELEASE_MANAGER),
    )
    return crit


@pytest.mark.asyncio
async def test_release_manager_can_complete(db_session, tenant, release_lifecycle_template):
    crit = await _gate_with_role_criterion(db_session, tenant.id, release_lifecycle_template.id)
    done = await gate_criterion_service.complete_criterion(
        db_session, crit.id, tenant.id, user_id=1, user_role=Role.RELEASE_MANAGER,
    )
    assert done.status == "done"


@pytest.mark.asyncio
async def test_admin_can_complete(db_session, tenant, release_lifecycle_template):
    crit = await _gate_with_role_criterion(db_session, tenant.id, release_lifecycle_template.id)
    done = await gate_criterion_service.complete_criterion(
        db_session, crit.id, tenant.id, user_id=1, user_role=Role.ADMIN,
    )
    assert done.status == "done"


@pytest.mark.asyncio
async def test_developer_cannot_complete_role_criterion(db_session, tenant, release_lifecycle_template):
    crit = await _gate_with_role_criterion(db_session, tenant.id, release_lifecycle_template.id)
    with pytest.raises(HTTPException) as ei:
        await gate_criterion_service.complete_criterion(
            db_session, crit.id, tenant.id, user_id=1, user_role=Role.DEVELOPER,
        )
    assert ei.value.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_criterion_role_authz.py -v`
Expected: FAIL — `complete_criterion` has no `user_role` param.

- [ ] **Step 3: Persist `assigned_role` in `create_criterion`**

In `backend/app/services/gate_criterion_service.py`, in `create_criterion`, add `assigned_role=data.assigned_role,` to the `GateCriterion(...)` constructor (after `assigned_to_user_id=data.assigned_to_user_id,`).

- [ ] **Step 4: Add role authz to `complete_criterion` and `reopen_criterion`**

Change the `complete_criterion` signature to accept `user_role`:

```python
async def complete_criterion(
    db: AsyncSession,
    criterion_id: int,
    tenant_id: int,
    user_id: int,
    user_role: str,
) -> GateCriterion:
```

Immediately after `crit = await get_criterion(db, criterion_id, tenant_id)` (and before the `if crit.status == "done":` line), add:

```python
    from app.core.security import Role
    if crit.assigned_role is not None:
        if user_role != crit.assigned_role and user_role != Role.ADMIN:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Only a {crit.assigned_role} or Admin can complete this criterion",
            )
```

Apply the same signature change and same guard block to `reopen_criterion` (add `user_role: str` param; insert the identical guard right after its `crit = await get_criterion(...)` line).

- [ ] **Step 5: Thread `user_role` from the endpoints**

In `backend/app/api/v1/gate_criteria.py`:

In `_crit_to_dict`, add `"assigned_role": c.assigned_role,` to the returned dict (next to `assigned_to_user_id`).

In the `complete_criterion` endpoint, change the service call to:
```python
    crit = await gate_criterion_service.complete_criterion(
        db, criterion_id, tenant_id, current_user.id, current_user.role,
    )
```

In the `reopen_criterion` endpoint, change the service call to:
```python
    crit = await gate_criterion_service.reopen_criterion(
        db, criterion_id, tenant_id, current_user.role,
    )
```

Note: `reopen_criterion`'s current signature is `(db, criterion_id, tenant_id)`. After Step 4 it is `(db, criterion_id, tenant_id, user_role)`.

- [ ] **Step 6: Include `assigned_role` in `list_gates` criterion dicts**

In `backend/app/services/release_gate_service.py`, in `list_gates`, in the `by_gate[c.gate_id].append({...})` dict (~line 134), add:
```python
            "assigned_role": c.assigned_role,
```

- [ ] **Step 7: Run tests to verify pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_criterion_role_authz.py -v`
Expected: 3 passed.

- [ ] **Step 8: Run the full gate/criterion/scope suite for regressions**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/ -k "gate or criter or scope or release" -q`
Expected: all pass (the pre-existing `complete_criterion` callers are only the endpoint, now updated).

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/gate_criterion_service.py backend/app/api/v1/gate_criteria.py backend/app/services/release_gate_service.py backend/tests/integration/test_criterion_role_authz.py
git commit -m "feat(releases): role-assigned criteria + completion authz"
```

---

## Task 8: Frontend types

**Files:**
- Modify: `frontend/src/types/release.ts`
- Modify: `frontend/src/types/gateCriterion.ts`
- Modify: `frontend/src/types/releaseChange.ts`

- [ ] **Step 1: Extend release types**

In `frontend/src/types/release.ts`:

Add to `ReleaseResponse` (after `actual_date`):
```typescript
  scope_deadline: string | null;
  scope_creep_count?: number;
```
Add to `ReleaseListItemResponse` (after `scope_change_count`):
```typescript
  scope_creep_count: number;
```
Add to `ReleaseCreatePayload` (after `target_date`):
```typescript
  scope_deadline?: string | null;
```
Add to `ReleaseUpdatePayload` (after `target_date`):
```typescript
  scope_deadline?: string | null;
```

- [ ] **Step 2: Extend criterion types**

In `frontend/src/types/gateCriterion.ts`:

Add to `GateCriterion` (after `assigned_to_username`):
```typescript
  assigned_role: string | null;
```
Add to `GateCriterionCreatePayload` and `GateCriterionUpdatePayload` (after `assigned_to_user_id`):
```typescript
  assigned_role?: string | null;
```

- [ ] **Step 3: Extend the scope-item type**

In `frontend/src/types/releaseChange.ts`, add to the `ReleaseChangeResponse` interface (alongside the other computed fields):
```typescript
  is_scope_creep?: boolean;
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors from these files (unrelated pre-existing errors, if any, are out of scope).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/release.ts frontend/src/types/gateCriterion.ts frontend/src/types/releaseChange.ts
git commit -m "feat(releases): frontend types for scope_deadline/assigned_role/is_scope_creep"
```

---

## Task 9: ReleaseForm — scope_deadline field (project releases only)

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseForm.tsx`

- [ ] **Step 1: Seed the field into local form state**

In `initialStandardValues` (`ReleaseForm.tsx:56`), add after the `actual_date` entry:
```typescript
    scope_deadline: release?.scope_deadline
      ? new Date(release.scope_deadline).toISOString().slice(0, 10)
      : '',
```

- [ ] **Step 2: Render the field (project only)**

In the create/edit JSX, immediately after the closing `</TextField>`/chip `Stack` block for Type+Kind and BEFORE the `{/* Lifecycle-driven fields */}` comment (~line 303), add:

```tsx
          {kind === 'project' && (
            <TextField
              label="Scope deadline"
              type="date"
              fullWidth
              value={(standardValues.scope_deadline as string) ?? ''}
              onChange={(e) =>
                setStandardValues((v) => ({ ...v, scope_deadline: e.target.value }))
              }
              InputLabelProps={{ shrink: true }}
              helperText="Baseline for scope creep. Setting this adds a Scope Sign-off gate for the Release Manager."
            />
          )}
```

Note: on edit, `kind` is initialised from `release.release_kind` (`ReleaseForm.tsx:95`), so this correctly hides for enterprise releases in both create and edit.

- [ ] **Step 3: Send `scope_deadline` in both payloads**

In `handleSubmit`, in the edit `payload` object (`ReleaseUpdatePayload`), add:
```typescript
          scope_deadline: toIsoDatetime(standardValues.scope_deadline),
```
In the create `payload` object (`ReleaseCreatePayload`), add (only meaningful for project kind; enterprise hides the field so it stays empty → null):
```typescript
          scope_deadline:
            kind === 'project' ? toIsoDatetime(standardValues.scope_deadline) : undefined,
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/releases/ReleaseForm.tsx
git commit -m "feat(releases): scope_deadline field on project release form"
```

---

## Task 10: Criterion UI — render role assignee + role option in dialog

**Files:**
- Modify: `frontend/src/components/releases/CriterionRow.tsx`
- Modify: `frontend/src/components/releases/CriterionDialog.tsx`

- [ ] **Step 1: Render the role on the criterion row**

In `frontend/src/components/releases/CriterionRow.tsx`, replace the assignee chip block (`criterion.assigned_to_username && (...)`, lines 31-33) with:

```tsx
      {criterion.assigned_role ? (
        <Chip size="small" label={`${criterion.assigned_role} (role)`} variant="outlined" color="info" />
      ) : (
        criterion.assigned_to_username && (
          <Chip size="small" label={criterion.assigned_to_username} variant="outlined" />
        )
      )}
```

- [ ] **Step 2: Inspect CriterionDialog to add a role option**

Read `frontend/src/components/releases/CriterionDialog.tsx`. It renders a user-assignee select from the `users` prop and submits `GateCriterionCreatePayload`/`GateCriterionUpdatePayload`.

Add an "Assign to" mode toggle so the user can pick EITHER a specific user OR a role. Concretely:
- Add local state `const [assignRole, setAssignRole] = useState<string>(initial?.assigned_role ?? '')`.
- Add a role `<TextField select>` with options `['', 'Release Manager', 'Test Manager', 'Admin', 'Developer', 'Viewer']` (label "Assign to role"). When a non-empty role is chosen, clear the user select; when a user is chosen, clear the role (enforce the backend's mutual-exclusion so the request never sends both).
- In the submit handler, include `assigned_role: assignRole || null` and set `assigned_to_user_id` to `null` when a role is chosen.

Keep the existing user-select control; the two controls are mutually exclusive in the UI. Match the file's existing prop/handler patterns (do not introduce a new submit signature).

- [ ] **Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/releases/CriterionRow.tsx frontend/src/components/releases/CriterionDialog.tsx
git commit -m "feat(releases): criterion UI supports role assignment"
```

---

## Task 11: Scope tab — tag creep items + header count

**Files:**
- Modify: `frontend/src/components/releases/ScopeTable.tsx`

- [ ] **Step 1: Add a "Scope" creep column**

In `frontend/src/components/releases/ScopeTable.tsx`, add a column to the `columns` array (before the `_actions` column):

```tsx
      {
        field: 'is_scope_creep',
        headerName: 'Scope',
        width: 110,
        renderCell: (params) =>
          params.row.is_scope_creep ? (
            <Chip label="Creep" color="warning" size="small" />
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
```

- [ ] **Step 2: Add a creep count to the header**

Replace the `Scope Items ({filteredChanges.length})` Typography (line 227-229) with:

```tsx
        <Typography variant="subtitle2">
          Scope Items ({filteredChanges.length})
          {(() => {
            const creep = filteredChanges.filter((c) => c.is_scope_creep).length;
            return creep > 0 ? ` — ${creep} added after scope deadline` : '';
          })()}
        </Typography>
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/releases/ScopeTable.tsx
git commit -m "feat(releases): tag scope-creep items in the scope tab"
```

---

## Task 12: Full-suite regression + wrap-up

- [ ] **Step 1: Run the backend release/gate/scope suites**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/ -k "release or gate or criter or scope" -q`
Expected: all pass.

- [ ] **Step 2: Run the full backend test suite (catch wider regressions)**

Run: `cd backend && PYTHONPATH=. uv run pytest -q`
Expected: no new failures attributable to these changes.

- [ ] **Step 3: Frontend typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 4: Manual smoke (optional, via /run or dev servers)**

Create a project release, set a scope deadline → confirm a "Scope Sign-off" gate appears with a "Scope signed off" criterion showing "Release Manager (role)". Add a scope item → it shows a "Creep" tag if the deadline is in the past. Confirm the field is hidden when Kind = Enterprise.

---

## Self-Review Notes (spec coverage)

- Data model: `scope_deadline` (Task 2) + `assigned_role` (Task 2), migration (Task 1). ✅
- Enterprise 422 reject: create + update (Task 4). ✅
- Auto-create gate on set, idempotent, kept if cleared: `_ensure_scope_signoff_gate` (Task 4). ✅
- Due-date sync while pending: `_sync_scope_signoff_due_date` (Task 4). ✅
- Creep baseline = deadline, entered-time definition: `_entered_time_expr` (Task 5). ✅
- `scope_creep_count` (list + read) + `is_scope_creep` (changes): Tasks 3, 6. ✅
- Role completion authz (RM/Admin allowed, others 403): Task 7. ✅
- Mutual exclusion role/user: schema validators (Task 3) + UI (Task 10). ✅
- Frontend: form field (Task 9), criterion render/dialog (Task 10), scope tab (Task 11), types (Task 8). ✅
- Type consistency: `SCOPE_SIGNOFF_GATE_NAME` used in service + tests; `scope_creep_change_ids`/`scope_creep_counts` names consistent across service + endpoint + tests; criterion status `"done"`/`"open"` (not "completed"). ✅
