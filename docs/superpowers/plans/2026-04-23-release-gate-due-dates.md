# Release Gate Due Dates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the phase-link on release gates with a required `due_date`; make criteria inherit it; render gates as status-coloured diamonds on the per-project Gantt timeline.

**Architecture:** One alembic migration drops `release_gate.test_phase_id` + `gate_criterion.due_date` and adds `release_gate.due_date` (NOT NULL after backfill). The service layer rewires "overdue" logic to compare gate-level dates against `now()`. The `/releases/timeline` endpoint returns a new `gates[]` array, and `ReleaseTimeline.tsx` renders a diamond per gate using the same polygon primitive as the existing `target_date` diamond.

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, Pydantic v2, React 18, MUI, Redux Toolkit.

**Spec:** `docs/superpowers/specs/2026-04-23-release-gate-due-dates-design.md`

---

## Task 1: Failing service test — `create_gate` requires `due_date`

**Files:**
- Modify: `backend/tests/services/test_release_scope_lifecycle.py` — add a new test module next to existing service tests
- Create: `backend/tests/services/test_release_gate_due_date.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_release_gate_due_date.py
"""Service-level tests for ReleaseGate.due_date migration — post-spec
2026-04-23. Covers create/update/list behaviours."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.gate_criterion import GateCriterion
from app.db.models.release_gate import ReleaseGate
from app.api.v1.schemas.release_gate import ReleaseGateCreate
from app.services import release_gate_service


@pytest.mark.asyncio
async def test_create_gate_persists_due_date(db_session, test_tenant, test_release):
    due = datetime(2026, 5, 1, tzinfo=timezone.utc)
    gate = await release_gate_service.create_gate(
        db_session,
        release_id=test_release.id,
        data=ReleaseGateCreate(name="UAT", due_date=due),
        tenant_id=test_tenant.id,
    )
    await db_session.flush()

    row = (await db_session.execute(
        select(ReleaseGate).where(ReleaseGate.id == gate.id)
    )).scalar_one()
    assert row.due_date == due


@pytest.mark.asyncio
async def test_list_gates_overdue_count_is_gate_level(
    db_session, test_tenant, test_release,
):
    """overdue_criterion_count == number of open criteria when gate.due_date < now."""
    past = datetime.now(timezone.utc) - timedelta(days=2)
    future = datetime.now(timezone.utc) + timedelta(days=7)

    overdue_gate = await release_gate_service.create_gate(
        db_session, release_id=test_release.id,
        data=ReleaseGateCreate(name="Past", due_date=past),
        tenant_id=test_tenant.id,
    )
    fresh_gate = await release_gate_service.create_gate(
        db_session, release_id=test_release.id,
        data=ReleaseGateCreate(name="Future", due_date=future),
        tenant_id=test_tenant.id,
    )
    # Two open + one done criterion on each gate.
    for g in (overdue_gate, fresh_gate):
        db_session.add_all([
            GateCriterion(tenant_id=test_tenant.id, gate_id=g.id, title="a", status="open"),
            GateCriterion(tenant_id=test_tenant.id, gate_id=g.id, title="b", status="open"),
            GateCriterion(tenant_id=test_tenant.id, gate_id=g.id, title="c", status="done"),
        ])
    await db_session.flush()

    rows = await release_gate_service.list_gates(
        db_session, release_id=test_release.id, tenant_id=test_tenant.id,
    )
    by_name = {r["name"]: r for r in rows}
    assert by_name["Past"]["overdue_criterion_count"] == 2
    assert by_name["Future"]["overdue_criterion_count"] == 0
    assert by_name["Past"]["due_date"] == past
    assert "test_phase_id" not in by_name["Past"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_release_gate_due_date.py -v`
Expected: FAIL — `ReleaseGateCreate` does not accept `due_date`, `ReleaseGate` has no `due_date` column, and the list dict still contains `test_phase_id`.

- [ ] **Step 3: Commit the failing test**

```bash
git add backend/tests/services/test_release_gate_due_date.py
git commit -m "test(gates): failing tests for gate due_date + gate-level overdue count"
```

---

## Task 2: Update `ReleaseGate` + `GateCriterion` models

**Files:**
- Modify: `backend/app/db/models/release_gate.py`
- Modify: `backend/app/db/models/gate_criterion.py`

- [ ] **Step 1: Replace `test_phase_id` with `due_date` on the gate model**

Open `backend/app/db/models/release_gate.py` and replace the file's body:

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
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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

- [ ] **Step 2: Drop `due_date` from the criterion model**

In `backend/app/db/models/gate_criterion.py`, remove the `due_date` line so the class body reads:

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
    assigned_to_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models/release_gate.py backend/app/db/models/gate_criterion.py
git commit -m "feat(gates): replace test_phase_id with due_date on ReleaseGate; drop GateCriterion.due_date"
```

---

## Task 3: Update gate + criterion Pydantic schemas

**Files:**
- Modify: `backend/app/api/v1/schemas/release_gate.py`
- Modify: `backend/app/api/v1/schemas/gate_criterion.py`

- [ ] **Step 1: Rewrite gate schemas with `due_date`**

Replace the contents of `backend/app/api/v1/schemas/release_gate.py`:

```python
# backend/app/api/v1/schemas/release_gate.py
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.schemas.gate_criterion import GateCriterionRead


class ReleaseGateCreate(BaseModel):
    name: str = Field(..., max_length=150)
    due_date: datetime


class ReleaseGateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    due_date: Optional[datetime] = None


class ReleaseGateDecision(BaseModel):
    notes: Optional[str] = None


class ReleaseGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    name: str
    due_date: datetime
    status: str
    decided_by: Optional[int]
    decided_at: Optional[datetime]
    decision_notes: Optional[str]
    criteria: List[GateCriterionRead] = []
    overdue_criterion_count: int = 0
```

- [ ] **Step 2: Strip `due_date` and `is_overdue` from the criterion schema**

Replace `backend/app/api/v1/schemas/gate_criterion.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GateCriterionCreate(BaseModel):
    title: str = Field(..., max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=250)
    notes: Optional[str] = None
    assigned_to_user_id: Optional[int] = None


class GateCriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    title: str
    notes: Optional[str]
    assigned_to_user_id: Optional[int]
    assigned_to_username: Optional[str] = None
    status: str
    completed_at: Optional[datetime]
    completed_by_user_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class GateCriterionWithGate(GateCriterionRead):
    """List-item variant used by /releases/{id}/overdue-criteria.

    `gate_name` and `gate_due_date` are hydrated by the endpoint from the
    parent ReleaseGate — criteria no longer carry their own due date."""
    gate_name: str
    gate_due_date: datetime
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/schemas/release_gate.py backend/app/api/v1/schemas/gate_criterion.py
git commit -m "feat(gates): align Pydantic schemas with due_date on gate, drop due_date on criterion"
```

---

## Task 4: Update `release_gate_service` to the new shape

**Files:**
- Modify: `backend/app/services/release_gate_service.py`

- [ ] **Step 1: Replace `list_gates` — gate-level overdue + include `due_date`**

In `backend/app/services/release_gate_service.py`, replace the body of `list_gates` so the returned dicts carry `due_date` and `overdue_criterion_count` comes from the gate's date, and no criterion carries a per-row date:

```python
async def list_gates(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
) -> list[dict]:
    """Return gates plus nested criteria + overdue_criterion_count per gate.

    overdue_criterion_count is N for a gate whose due_date < now (count of its
    open criteria) and 0 otherwise — criteria no longer carry their own date.
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

    from app.db.models.user import User
    assignee_ids = {c.assigned_to_user_id for c in crit_rows if c.assigned_to_user_id is not None}
    username_by_id: dict[int, str] = {}
    if assignee_ids:
        user_rows = (
            await db.execute(select(User.id, User.username).where(User.id.in_(assignee_ids)))
        ).all()
        username_by_id = {row.id: row.username for row in user_rows}

    now = datetime.now(timezone.utc)
    open_counts: dict[int, int] = {gid: 0 for gid in gate_ids}
    by_gate: dict[int, list[dict]] = {gid: [] for gid in gate_ids}
    for c in crit_rows:
        by_gate[c.gate_id].append({
            "id": c.id, "gate_id": c.gate_id, "title": c.title, "notes": c.notes,
            "assigned_to_user_id": c.assigned_to_user_id,
            "assigned_to_username": username_by_id.get(c.assigned_to_user_id) if c.assigned_to_user_id else None,
            "status": c.status,
            "completed_at": c.completed_at, "completed_by_user_id": c.completed_by_user_id,
            "created_at": c.created_at, "updated_at": c.updated_at,
        })
        if c.status == "open":
            open_counts[c.gate_id] += 1

    def _overdue(gate: ReleaseGate) -> int:
        due = gate.due_date
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        return open_counts[gate.id] if due < now else 0

    return [
        {
            "id": g.id, "tenant_id": g.tenant_id, "release_id": g.release_id,
            "name": g.name, "due_date": g.due_date, "status": g.status,
            "decided_by": g.decided_by, "decided_at": g.decided_at,
            "decision_notes": g.decision_notes,
            "criteria": by_gate[g.id],
            "overdue_criterion_count": _overdue(g),
        }
        for g in gate_rows
    ]
```

- [ ] **Step 2: Replace `create_gate` to persist `due_date`**

```python
async def create_gate(
    db: AsyncSession,
    release_id: int,
    data: ReleaseGateCreate,
    tenant_id: int,
) -> ReleaseGate:
    gate = ReleaseGate(
        tenant_id=tenant_id,
        release_id=release_id,
        name=data.name,
        due_date=data.due_date,
        status="pending",
    )
    db.add(gate)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseGateCreated",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": release_id,
            "name": gate.name,
            "due_date": gate.due_date.isoformat(),
        },
        tenant_id=tenant_id,
    )
    return gate
```

- [ ] **Step 3: Extend `update_gate` payload with `due_date`**

Replace the `publish_event` payload in `update_gate` so it includes `due_date`:

```python
    await publish_event(
        db,
        event_type="ReleaseGateUpdated",
        aggregate_id=gate.id,
        aggregate_type="ReleaseGate",
        payload={
            "id": gate.id,
            "release_id": gate.release_id,
            "name": gate.name,
            "due_date": gate.due_date.isoformat(),
        },
        tenant_id=tenant_id,
    )
```

No change needed to the `update_data` loop — `model_dump(exclude_unset=True)` already picks up `due_date` from `ReleaseGateUpdate`.

- [ ] **Step 4: Run Task 1's tests to verify they pass**

Run: `cd backend && uv run pytest tests/services/test_release_gate_due_date.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_gate_service.py
git commit -m "feat(gates): service layer — persist gate due_date, gate-level overdue count"
```

---

## Task 5: Rewire `list_overdue_for_release` + `gate_criteria` endpoint

**Files:**
- Modify: `backend/app/services/gate_criterion_service.py`
- Modify: `backend/app/api/v1/gate_criteria.py`

- [ ] **Step 1: Replace the overdue query — join on gate due_date**

In `backend/app/services/gate_criterion_service.py`, replace `list_overdue_for_release`:

```python
async def list_overdue_for_release(
    db: AsyncSession, release_id: int, tenant_id: int
) -> list[tuple[GateCriterion, ReleaseGate]]:
    """Overdue = criterion is open AND its gate's due_date < now()."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(GateCriterion, ReleaseGate)
            .join(ReleaseGate, ReleaseGate.id == GateCriterion.gate_id)
            .where(
                ReleaseGate.release_id == release_id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
                GateCriterion.status == "open",
                ReleaseGate.deleted_at.is_(None),
                ReleaseGate.due_date < now,
            )
            .order_by(ReleaseGate.due_date, GateCriterion.id)
        )
    ).all()
    return [(c, g) for c, g in rows]
```

- [ ] **Step 2: Update the endpoint hydration**

In `backend/app/api/v1/gate_criteria.py`, replace the `list_overdue` handler body so it uses the new tuple shape (and the `_crit_to_dict` helper no longer emits `due_date`):

```python
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
    for crit, gate in rows:
        out.append(GateCriterionWithGate.model_validate({
            **_crit_to_dict(crit),
            "gate_name": gate.name,
            "gate_due_date": gate.due_date,
        }))
    return out
```

Then open `_crit_to_dict` (same file) and remove any `"due_date": c.due_date` line if present. If the helper lives elsewhere, grep for it and apply the same change.

- [ ] **Step 3: Run affected API tests**

Run: `cd backend && uv run pytest tests/test_gate_criteria_api.py -v`
Expected: PASS. If a test asserted `c["due_date"]` on a criterion row, update it to assert `gate_due_date` at the list level. Leave the assertion count the same — don't delete tests.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/gate_criterion_service.py backend/app/api/v1/gate_criteria.py backend/tests/test_gate_criteria_api.py
git commit -m "feat(gates): overdue query joins on gate.due_date; endpoint returns gate_due_date"
```

---

## Task 6: Alembic migration — backfill + drop

**Files:**
- Create: `backend/app/db/migrations/versions/20260423_1200_p3s8_gate_due_date.py`

- [ ] **Step 1: Write the migration**

Create `backend/app/db/migrations/versions/20260423_1200_p3s8_gate_due_date.py`:

```python
"""phase 3 sub-project 8: release_gate due_date replaces phase link

Revision ID: p3s8gateduedate
Revises: p3s7membershipunique
Create Date: 2026-04-23 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s8gateduedate"
down_revision: Union[str, None] = "p3s7membershipunique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def _index_exists(conn, table: str, name: str) -> bool:
    return any(i["name"] == name for i in Inspector.from_engine(conn).get_indexes(table))


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add due_date nullable.
    if not _column_exists(conn, "release_gate", "due_date"):
        op.add_column(
            "release_gate",
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        )

    # 2. Backfill: priority chain phase.end_date → MAX(criterion.due_date) → release.target_date → release.created_at.
    # Written as four UPDATEs; each one fills only rows where due_date is still NULL.
    dialect = conn.dialect.name

    if _column_exists(conn, "release_gate", "test_phase_id"):
        op.execute("""
            UPDATE release_gate AS rg
               SET due_date = tp.end_date
              FROM test_phase AS tp
             WHERE rg.due_date IS NULL
               AND rg.test_phase_id = tp.id
               AND tp.end_date IS NOT NULL
        """ if dialect == "postgresql" else """
            UPDATE release_gate
               SET due_date = (
                   SELECT tp.end_date FROM test_phase tp
                    WHERE tp.id = release_gate.test_phase_id
                      AND tp.end_date IS NOT NULL
               )
             WHERE due_date IS NULL
               AND test_phase_id IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM test_phase tp
                    WHERE tp.id = release_gate.test_phase_id
                      AND tp.end_date IS NOT NULL
               )
        """)

    if _column_exists(conn, "gate_criterion", "due_date"):
        op.execute("""
            UPDATE release_gate AS rg
               SET due_date = (
                   SELECT MAX(gc.due_date) FROM gate_criterion gc
                    WHERE gc.gate_id = rg.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
             WHERE rg.due_date IS NULL
               AND EXISTS (
                   SELECT 1 FROM gate_criterion gc
                    WHERE gc.gate_id = rg.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
        """ if dialect == "postgresql" else """
            UPDATE release_gate
               SET due_date = (
                   SELECT MAX(gc.due_date) FROM gate_criterion gc
                    WHERE gc.gate_id = release_gate.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
             WHERE due_date IS NULL
               AND EXISTS (
                   SELECT 1 FROM gate_criterion gc
                    WHERE gc.gate_id = release_gate.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
        """)

    op.execute("""
        UPDATE release_gate
           SET due_date = (
               SELECT r.target_date FROM release r
                WHERE r.id = release_gate.release_id
                  AND r.target_date IS NOT NULL
           )
         WHERE due_date IS NULL
           AND EXISTS (
               SELECT 1 FROM release r
                WHERE r.id = release_gate.release_id
                  AND r.target_date IS NOT NULL
           )
    """)

    op.execute("""
        UPDATE release_gate
           SET due_date = (
               SELECT r.created_at FROM release r
                WHERE r.id = release_gate.release_id
           )
         WHERE due_date IS NULL
    """)

    # 3. NOT NULL.
    op.alter_column("release_gate", "due_date", nullable=False)

    # 4. Drop the phase FK + index + column.
    if _index_exists(conn, "release_gate", "ix_release_gate_test_phase_id"):
        op.drop_index("ix_release_gate_test_phase_id", table_name="release_gate")
    if _column_exists(conn, "release_gate", "test_phase_id"):
        op.drop_column("release_gate", "test_phase_id")

    # 5. Drop gate_criterion.due_date.
    if _column_exists(conn, "gate_criterion", "due_date"):
        op.drop_column("gate_criterion", "due_date")


def downgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "gate_criterion", "due_date"):
        op.add_column(
            "gate_criterion",
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists(conn, "release_gate", "test_phase_id"):
        op.add_column(
            "release_gate",
            sa.Column("test_phase_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            None, "release_gate", "test_phase",
            ["test_phase_id"], ["id"], ondelete="SET NULL",
        )
        op.create_index(
            "ix_release_gate_test_phase_id", "release_gate", ["test_phase_id"]
        )

    if _column_exists(conn, "release_gate", "due_date"):
        op.drop_column("release_gate", "due_date")
```

> **Note:** confirm the `down_revision` value. Run `ls backend/app/db/migrations/versions | sort | tail -3` and point `down_revision` at the most recent existing revision's `revision` string. The template above assumes `p3s7membershipunique`.

- [ ] **Step 2: Apply the migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: runs cleanly; schema now has `release_gate.due_date NOT NULL`, no `test_phase_id`, and no `gate_criterion.due_date`.

- [ ] **Step 3: Run the full backend test suite**

```bash
cd backend && uv run pytest -x -q
```

Expected: PASS. If any test still seeds `test_phase_id` or `c.due_date`, update it to the new shape.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/migrations/versions/20260423_1200_p3s8_gate_due_date.py
git commit -m "feat(db): migrate release_gate to due_date and drop phase link + criterion.due_date"
```

---

## Task 7: Extend the `/timeline` endpoint with `gates[]`

**Files:**
- Modify: `backend/app/api/v1/releases.py` (around the `get_releases_timeline` handler, ~line 320)
- Create/modify: `backend/tests/integration/test_releases_timeline.py` (create if not present)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_releases_timeline.py` (or extend if it exists):

```python
"""Integration test — /releases/timeline returns gate milestones."""
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_timeline_includes_gates(
    client, auth_headers, db_session, test_tenant, release_lifecycle,
):
    from app.api.v1.schemas.release_gate import ReleaseGateCreate
    from app.services import release_gate_service

    # Minimal release.
    resp = await client.post(
        "/api/v1/releases",
        headers=auth_headers,
        json={"name": "TL", "release_type": "minor"},
    )
    rid = resp.json()["id"]

    due = datetime(2026, 5, 15, tzinfo=timezone.utc)
    await release_gate_service.create_gate(
        db_session,
        release_id=rid,
        data=ReleaseGateCreate(name="UAT", due_date=due),
        tenant_id=test_tenant.id,
    )
    await db_session.commit()

    resp = await client.get("/api/v1/releases/timeline", headers=auth_headers)
    assert resp.status_code == 200
    entry = next(e for e in resp.json() if e["id"] == rid)
    assert isinstance(entry["gates"], list)
    assert len(entry["gates"]) == 1
    gate = entry["gates"][0]
    assert gate["name"] == "UAT"
    assert gate["status"] == "pending"
    assert gate["due_date"].startswith("2026-05-15")
    assert "id" in gate
```

- [ ] **Step 2: Run it — confirm failure**

```bash
cd backend && uv run pytest tests/integration/test_releases_timeline.py -v
```

Expected: FAIL — `entry["gates"]` is missing.

- [ ] **Step 3: Update the handler to emit `gates[]`**

In `backend/app/api/v1/releases.py`, inside the per-release loop of `get_releases_timeline` (after the `phases` query and before appending `result`), add:

```python
        gates = (
            await db.execute(
                select(ReleaseGate).where(
                    ReleaseGate.release_id == r.id,
                    ReleaseGate.tenant_id == tenant_id,
                    ReleaseGate.deleted_at.is_(None),
                ).order_by(ReleaseGate.due_date)
            )
        ).scalars().all()
```

Then extend the dict appended to `result` with:

```python
                "gates": [
                    {
                        "id": g.id,
                        "name": g.name,
                        "due_date": g.due_date.isoformat(),
                        "status": g.status,
                    }
                    for g in gates
                ],
```

(`ReleaseGate` is already imported near the top of the file at line 24 — no new import needed.)

- [ ] **Step 4: Re-run the test**

```bash
cd backend && uv run pytest tests/integration/test_releases_timeline.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/releases.py backend/tests/integration/test_releases_timeline.py
git commit -m "feat(releases): timeline endpoint returns per-release gates array"
```

---

## Task 8: Frontend types — gates on timeline + `due_date` on gate

**Files:**
- Modify: `frontend/src/types/release.ts`
- Modify: `frontend/src/types/gateCriterion.ts`

- [ ] **Step 1: Add a `TimelineGate` interface + extend `ReleaseTimelineEntry`**

Open `frontend/src/types/release.ts`. Locate the existing `ReleaseTimelineEntry` interface (line ~185). Replace it with:

```typescript
export interface TimelineGate {
  id: number;
  name: string;
  due_date: string;
  status: 'pending' | 'passed' | 'failed' | 'overridden';
}

export interface ReleaseTimelineEntry {
  id: number;
  name: string;
  status: string;
  target_date: string | null;
  actual_date: string | null;
  phases: TestPhaseResponse[];
  gates: TimelineGate[];
  /** Backend may omit this when a release has no dependencies. */
  dependencies?: ReleaseDependencyResponse[];
}
```

- [ ] **Step 2: Update `ReleaseGateResponse`**

In the same file, locate `ReleaseGateResponse` (grep for it). Replace `test_phase_id: number | null;` with `due_date: string;`. Example final fields:

```typescript
export interface ReleaseGateResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  name: string;
  due_date: string;
  status: 'pending' | 'passed' | 'failed' | 'overridden';
  decided_by: number | null;
  decided_at: string | null;
  decision_notes: string | null;
  criteria: GateCriterion[];
  overdue_criterion_count: number;
}
```

Also update `ReleaseGateCreatePayload` / `ReleaseGateUpdatePayload` if present — remove `test_phase_id`, add `due_date: string`.

- [ ] **Step 3: Drop `due_date` + `is_overdue` from `GateCriterion`**

Open `frontend/src/types/gateCriterion.ts` and remove `due_date` and `is_overdue` from both the `GateCriterion` interface and any `GateCriterionCreatePayload` / `GateCriterionUpdatePayload`. The overdue-row response type gains a `gate_due_date: string` and `gate_name: string`.

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: Several existing references will fail (GatesTable, CriterionDialog, ReleaseTimeline). That's fine — subsequent tasks fix them. Note down which files fail so the next task matches the list.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/release.ts frontend/src/types/gateCriterion.ts
git commit -m "chore(types): gates carry due_date + timeline carries gates[]"
```

---

## Task 9: Update gate create/edit dialog — due_date picker, no phase

**Files:**
- Modify: `frontend/src/components/releases/GatesTable.tsx`
- Modify: `frontend/src/services/releaseService.ts` (whichever module holds `createGate`)
- Modify: `frontend/src/store/releaseSlice.ts` (if `createGate` payload is typed there)

- [ ] **Step 1: Replace the create-dialog state + fields**

In `GatesTable.tsx`, inside the component body, replace the gate-create state:

```typescript
  const [createOpen, setCreateOpen] = useState(false);
  const [gateName, setGateName] = useState('');
  const [gateDueDate, setGateDueDate] = useState<string>('');  // yyyy-mm-dd
```

Also remove `gatePhaseId` / `setGatePhaseId` and the `phases` / `phaseNameMap` imports/props if they are no longer used by the file. If `phases` is still passed in for other reasons, keep the prop but stop reading it.

- [ ] **Step 2: Replace `handleCreate`**

```typescript
  const handleCreate = async () => {
    if (!gateName.trim() || !gateDueDate) return;
    try {
      // Picker gives yyyy-mm-dd — send as midnight UTC ISO string.
      const iso = new Date(`${gateDueDate}T00:00:00Z`).toISOString();
      await dispatch(
        createGate({
          releaseId,
          data: { name: gateName.trim(), due_date: iso },
        })
      ).unwrap();
      snackbar.success('Gate created');
      setCreateOpen(false);
      setGateName('');
      setGateDueDate('');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create gate');
    }
  };
```

- [ ] **Step 3: Replace the create-dialog JSX**

Find the `<Dialog open={createOpen}>` block and replace the `<DialogContent>` and `<DialogActions>` bodies with:

```tsx
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="Name"
              required
              fullWidth
              value={gateName}
              onChange={(e) => setGateName(e.target.value)}
            />
            <TextField
              label="Due date"
              type="date"
              required
              fullWidth
              value={gateDueDate}
              onChange={(e) => setGateDueDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={!gateName.trim() || !gateDueDate}
          >
            Add
          </Button>
        </DialogActions>
```

Remove any `MenuItem`/`Phase (optional)` `TextField select` entirely.

- [ ] **Step 4: Show due date on the gate header row + drop the phase chip**

In the same file, find the gate header JSX (`{gate.test_phase_id && <Chip .../>}`). Replace that block with a due-date chip:

```tsx
                <Chip
                  size="small"
                  variant="outlined"
                  label={`Due ${gate.due_date.slice(0, 10)}`}
                />
```

- [ ] **Step 5: Update service + slice types to match**

`createGate` is wired in `frontend/src/services/releaseService.ts:94` and the async thunk in `frontend/src/store/releaseSlice.ts:151-154`. Both use the shared `ReleaseGateCreatePayload` type declared in `frontend/src/types/release.ts`. Task 8 Step 2 already removed `test_phase_id` and added `due_date: string` to that payload type, so no code change is needed in these files — verify by re-running the typecheck below. If the payload type still uses `test_phase_id`, go back to Task 8 Step 2 and finish the edit.

- [ ] **Step 6: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: this file clean. `CriterionDialog`/`CriterionRow`/`ReleaseTimeline` may still be red — next tasks fix them.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/releases/GatesTable.tsx frontend/src/services/releaseService.ts frontend/src/store/releaseSlice.ts
git commit -m "feat(gates-ui): due-date picker on create dialog, due-date chip on row"
```

---

## Task 10: Criterion dialog + row — drop due_date field

**Files:**
- Modify: `frontend/src/components/releases/CriterionDialog.tsx`
- Modify: `frontend/src/components/releases/CriterionRow.tsx`

- [ ] **Step 1: Rewrite `CriterionDialog` to drop the date field**

Replace the body of `frontend/src/components/releases/CriterionDialog.tsx` with:

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
  const [assignee, setAssignee] = useState<number | ''>('');

  useEffect(() => {
    setTitle(initial?.title ?? '');
    setNotes(initial?.notes ?? '');
    setAssignee(initial?.assigned_to_user_id ?? '');
  }, [initial, open]);

  const handleSubmit = () => {
    onSubmit({
      title: title.trim(),
      notes: notes.trim() || null,
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

- [ ] **Step 2: Rewrite `CriterionRow` — drop the date chip + overdue styling**

Replace the body of `frontend/src/components/releases/CriterionRow.tsx` with (the overdue state now lives on the parent gate's header via `overdue_criterion_count`):

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

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: these two files clean. `ReleaseTimeline` still pending.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/releases/CriterionDialog.tsx frontend/src/components/releases/CriterionRow.tsx
git commit -m "feat(criteria-ui): criteria no longer carry their own due date"
```

---

## Task 11: Render gate diamonds on the release timeline

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseTimeline.tsx`

- [ ] **Step 1: Add a colour map + extend `computeDateRange`**

At the top of the file, after `PHASE_STATUS_COLORS`, add:

```typescript
const GATE_STATUS_COLORS: Record<string, string> = {
  pending: '#607d8b',
  passed: '#43a047',
  failed: '#e53935',
  overridden: '#ffb300',
};
```

In `computeDateRange`, after the `for (const p of e.phases)` loop, add:

```typescript
    for (const g of e.gates ?? []) {
      dates.push(new Date(g.due_date));
    }
```

- [ ] **Step 2: Render a diamond per gate**

Inside the `{timeline.map((entry, rowIndex) => (…))}` block, next to the existing `Target date diamond` rendering, add:

```tsx
                    {/* Gate diamonds */}
                    {(entry.gates ?? []).map((gate) => {
                      const gx = dateToX(new Date(gate.due_date), minDate, totalDays, chartWidth);
                      const cy = rowIndex * ROW_HEIGHT + ROW_HEIGHT / 2 + HEADER_HEIGHT;
                      const s = 7;
                      const fill = GATE_STATUS_COLORS[gate.status] ?? '#607d8b';
                      return (
                        <Tooltip
                          key={`gate-${gate.id}`}
                          title={`${gate.name} — ${gate.status} — due ${gate.due_date.slice(0, 10)}`}
                          placement="top"
                        >
                          <polygon
                            points={`${gx},${cy - s} ${gx + s},${cy} ${gx},${cy + s} ${gx - s},${cy}`}
                            fill={fill}
                            opacity={0.95}
                            stroke="#fff"
                            strokeWidth={1}
                          />
                        </Tooltip>
                      );
                    })}
```

- [ ] **Step 3: Extend the legend**

Inside the legend `<Box>` at the bottom, after the `target date` entry, add:

```tsx
            {(['pending', 'passed', 'failed', 'overridden'] as const).map((s) => (
              <Box key={`gate-${s}`} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box
                  sx={{
                    width: 0,
                    height: 0,
                    borderLeft: '6px solid transparent',
                    borderRight: '6px solid transparent',
                    borderBottom: `12px solid ${GATE_STATUS_COLORS[s]}`,
                  }}
                />
                <Typography variant="caption">gate {s}</Typography>
              </Box>
            ))}
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean across the whole project.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/releases/ReleaseTimeline.tsx
git commit -m "feat(timeline): render gate milestones as status-coloured diamonds"
```

---

## Task 12: Full verification pass

- [ ] **Step 1: Backend — full suite**

```bash
cd backend && uv run pytest -x -q
```

Expected: PASS.

- [ ] **Step 2: Frontend — full typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean (no output).

- [ ] **Step 3: Smoke in the dev environment**

Start the stack, log in as `admin/admin123` on the `demo` tenant, open a release with at least one gate, and verify:

1. The gate create dialog shows a `Due date` picker (required) and no phase selector.
2. The gate row shows a `Due yyyy-mm-dd` chip.
3. Criterion rows have no per-row date.
4. Set a gate's `due_date` to yesterday → the "X overdue" chip appears on the gate header (count = number of open criteria).
5. Open the Release Timeline page → the release row shows diamonds for each gate at its due-date x-coordinate, coloured by status; the orange `target_date` diamond is still there.
6. Legend shows four new gate-status swatches.

Record any UI glitch as a follow-up. No extra commits unless a bug turns up.

- [ ] **Step 4: Final commit (docs)**

If anything in the spec needs a note ("shipped on MR !XX"), update
`docs/superpowers/specs/2026-04-23-release-gate-due-dates-design.md` header to
"Status: Shipped" and commit:

```bash
git add docs/superpowers/specs/2026-04-23-release-gate-due-dates-design.md
git commit -m "docs(spec): mark release-gate due-date spec as shipped"
```
