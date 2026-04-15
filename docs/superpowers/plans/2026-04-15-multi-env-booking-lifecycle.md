# Multi-Environment Booking Requests + Inline Lifecycle Actions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a parent `booking_request` holding N environment-level `booking` children, with soft conflict acknowledgements and fully dynamic lifecycle-driven transitions everywhere — replacing the legacy hardcoded approve/reject/cancel UI.

**Architecture:**
- Two-step migration: add `booking_request` and `booking_conflict_ack` tables, add `booking.booking_request_id` (nullable → NOT NULL later), backfill existing rows, then drop moved columns in a follow-up migration once code paths are cut over.
- Services split: `booking_request_service` (request + child orchestration), `conflict_service` (overlap detection + ack upsert). `booking_service` gains a dual-read shim during the migration window.
- Frontend extracts three reusable pieces from `BookingDetail` (`TransitionButtons`, `EditStandardFieldsDialog`, `EditCustomFieldsDialog`) and reuses them on the calendar drawer + the new `EnvironmentsPanel`.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest-asyncio, httpx AsyncClient, SQLite in tests; React 18 + TypeScript + MUI + Redux Toolkit + FullCalendar + MUI DataGrid on the frontend.

**Reference spec:** `docs/superpowers/specs/2026-04-15-multi-env-booking-lifecycle-design.md`

**Notes for engineer:**
- **Recurrence:** `booking` already carries `recurrence_rule` and `recurrence_parent_id`. For this work, recurrence stays per-env: when a recurring booking is created inside a multi-env request, its occurrences inherit the same `booking_request_id` as the series parent. No spec-level change to recurrence behaviour.
- **Test patterns:** Follow `backend/tests/test_booking_lifecycle.py` and `backend/tests/test_booking_transitions.py`. Fixtures `db_session`, `test_tenant`, `test_user`, `auth_headers`, `client` are in `backend/tests/conftest.py`.
- **Migration style:** Write manual DDL — do not use `--autogenerate` (see `CLAUDE.md` "Common Pitfalls").
- **No `db.commit()` in services:** `get_db()` auto-commits. Use `await db.flush()` if you need an assigned ID mid-transaction.
- **Enum columns:** always `native_enum=False`.
- **Events:** use `publish_event()` from `app.core.events` for outbox-style event rows.
- **Frontend tests:** no automated frontend test framework is present. Frontend tasks include a manual verification checklist in place of unit tests.

---

## Phase 1 — Backend data model + migration Step 1

### Task 1: Add `booking_request` SQLAlchemy model

**Files:**
- Create: `backend/app/db/models/booking_request.py`
- Modify: `backend/app/db/models/__init__.py`

- [ ] **Step 1: Write the model**

Create `backend/app/db/models/booking_request.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY

from app.db.base import Base
from app.db.models.booking import ContextTag


class BookingRequest(Base):
    __tablename__ = "booking_request"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    booking_type_id: Mapped[int] = mapped_column(
        ForeignKey("booking_type.id"), nullable=False, index=True
    )
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_tag: Mapped[ContextTag] = mapped_column(
        SAEnum(ContextTag, native_enum=False),
        nullable=False,
        default=ContextTag.NONE,
    )
    exclusive_use_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    booked_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    # Stored as JSON array to keep SQLite (test) compatibility; Postgres accepts JSON too.
    delegate_user_ids: Mapped[Optional[list[int]]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    booking_type_ref = relationship("BookingType", foreign_keys=[booking_type_id])
    booker = relationship("User", foreign_keys=[booked_by])
    bookings = relationship(
        "Booking",
        back_populates="booking_request",
        foreign_keys="Booking.booking_request_id",
    )
```

- [ ] **Step 2: Register in `backend/app/db/models/__init__.py`**

Add the import line alongside existing model imports:

```python
from app.db.models.booking_request import BookingRequest  # noqa: F401
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models/booking_request.py backend/app/db/models/__init__.py
git commit -m "feat: add BookingRequest model"
```

---

### Task 2: Add `booking_conflict_ack` SQLAlchemy model

**Files:**
- Create: `backend/app/db/models/booking_conflict_ack.py`
- Modify: `backend/app/db/models/__init__.py`

- [ ] **Step 1: Write the model**

Create `backend/app/db/models/booking_conflict_ack.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import Text, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BookingConflictAck(Base):
    __tablename__ = "booking_conflict_ack"
    __table_args__ = (
        UniqueConstraint("booking_id", "other_booking_id", name="uq_conflict_ack_pair"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    other_booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    willing_to_share: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acknowledged_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Register in `backend/app/db/models/__init__.py`**

```python
from app.db.models.booking_conflict_ack import BookingConflictAck  # noqa: F401
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models/booking_conflict_ack.py backend/app/db/models/__init__.py
git commit -m "feat: add BookingConflictAck model"
```

---

### Task 3: Add `booking_request_id` column + relationship on `Booking`

**Files:**
- Modify: `backend/app/db/models/booking.py`

- [ ] **Step 1: Add the column and relationship**

In `backend/app/db/models/booking.py`, inside the `Booking` class add (before the existing `environment` relationship):

```python
    booking_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("booking_request.id"), nullable=True, index=True
    )

    booking_request = relationship(
        "BookingRequest",
        back_populates="bookings",
        foreign_keys=[booking_request_id],
    )
```

The column is nullable initially — migration Step 2 (Task 37) flips it to NOT NULL once backfill + dual-read shim are in place.

- [ ] **Step 2: Commit**

```bash
git add backend/app/db/models/booking.py
git commit -m "feat: add booking_request_id FK to Booking"
```

---

### Task 4: Alembic migration Step 1 (create tables + FK column + backfill)

**Files:**
- Create: `backend/app/db/migrations/versions/<new>_add_booking_request_and_conflicts.py`

- [ ] **Step 1: Generate an empty revision**

```bash
cd backend && alembic revision -m "add booking_request, booking_conflict_ack, booking.booking_request_id"
```

Record the generated filename and revision hash.

- [ ] **Step 2: Write manual DDL and backfill**

Replace the generated file's `upgrade()` / `downgrade()` with:

```python
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # booking_request
    op.create_table(
        "booking_request",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("project_name", sa.String(200), nullable=False),
        sa.Column("booking_type_id", sa.Integer, sa.ForeignKey("booking_type.id"), nullable=False, index=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("context_tag", sa.String(50), nullable=False, server_default="none"),
        sa.Column("exclusive_use_requested", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("custom_fields", sa.JSON, nullable=True),
        sa.Column("booked_by", sa.Integer, sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("delegate_user_ids", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # booking_conflict_ack
    op.create_table(
        "booking_conflict_ack",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("booking.id"), nullable=False, index=True),
        sa.Column("other_booking_id", sa.Integer, sa.ForeignKey("booking.id"), nullable=False, index=True),
        sa.Column("willing_to_share", sa.Boolean, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("acknowledged_by", sa.Integer, sa.ForeignKey("user.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("booking_id", "other_booking_id", name="uq_conflict_ack_pair"),
    )

    # booking.booking_request_id (nullable for now)
    op.add_column(
        "booking",
        sa.Column(
            "booking_request_id",
            sa.Integer,
            sa.ForeignKey("booking_request.id"),
            nullable=True,
            index=True,
        ),
    )

    # Backfill: one booking_request per existing booking. Each gets its own parent.
    op.execute(
        """
        INSERT INTO booking_request (
            tenant_id, project_name, booking_type_id, start_date, end_date,
            notes, context_tag, exclusive_use_requested, custom_fields,
            booked_by, delegate_user_ids, created_at, updated_at, deleted_at
        )
        SELECT
            tenant_id, project_name, booking_type_id, start_date, end_date,
            notes, context_tag, exclusive_use, custom_fields,
            booked_by, NULL, created_at, updated_at, deleted_at
        FROM booking
        WHERE booking_request_id IS NULL
        """
    )
    # Match each booking to the request we just inserted for it.
    # Note: this works because the backfill INSERT preserves ordering and
    # each source row gets exactly one new request row. For Postgres we
    # correlate on (tenant_id, project_name, booked_by, start_date, end_date, booking_type_id).
    op.execute(
        """
        UPDATE booking
        SET booking_request_id = (
            SELECT br.id FROM booking_request br
            WHERE br.tenant_id = booking.tenant_id
              AND br.project_name = booking.project_name
              AND br.booked_by = booking.booked_by
              AND br.booking_type_id = booking.booking_type_id
              AND br.start_date = booking.start_date
              AND br.end_date = booking.end_date
            ORDER BY br.id
            LIMIT 1
        )
        WHERE booking_request_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("booking", "booking_request_id")
    op.drop_table("booking_conflict_ack")
    op.drop_table("booking_request")
```

- [ ] **Step 3: Apply migration locally**

```bash
cd backend && alembic upgrade head
```

Expected: migration completes with no error. Confirm with `psql` or `sqlite3` that:
- `booking_request` table exists with N rows equal to existing `booking` rows
- `booking.booking_request_id` is populated on every row

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/migrations/versions/*_add_booking_request_and_conflicts.py
git commit -m "feat: migration step 1 - add booking_request, conflict ack, booking FK"
```

---

## Phase 2 — Backend services

### Task 5: Conflict service — overlap detection

**Files:**
- Create: `backend/app/services/conflict_service.py`
- Create: `backend/tests/test_conflict_service.py`

- [ ] **Step 1: Write failing test for overlap detection**

Create `backend/tests/test_conflict_service.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta

from app.services import conflict_service
from app.db.models.booking import Booking
from app.db.models.environment import Environment


async def _make_env(db_session, test_tenant) -> Environment:
    env = Environment(tenant_id=test_tenant.id, name="env1", subsystem_id=None, env_type="dev")
    db_session.add(env)
    await db_session.flush()
    return env


async def _make_booking(db_session, test_tenant, test_user, env, start, end, status="submitted") -> Booking:
    b = Booking(
        tenant_id=test_tenant.id,
        environment_id=env.id,
        project_name="p",
        booked_by=test_user.id,
        start_date=start,
        end_date=end,
        exclusive_use=False,
        booking_type_id=1,  # dummy — not traversed for overlap
        status=status,
        context_tag="none",
    )
    db_session.add(b)
    await db_session.flush()
    return b


@pytest.mark.asyncio
async def test_overlap_same_env_open_window(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    b = await _make_booking(db_session, test_tenant, test_user, env, t0 + timedelta(days=1), t0 + timedelta(days=3))

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    ids = [c.id for c in conflicts]
    assert b.id in ids


@pytest.mark.asyncio
async def test_no_overlap_when_terminal(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2), status="rejected")
    await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2), status="closed")

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    assert conflicts == []


@pytest.mark.asyncio
async def test_no_overlap_different_env(db_session, test_tenant, test_user):
    env_a = await _make_env(db_session, test_tenant)
    env_b = Environment(tenant_id=test_tenant.id, name="env2", subsystem_id=None, env_type="dev")
    db_session.add(env_b)
    await db_session.flush()

    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env_a, t0, t0 + timedelta(days=2))
    await _make_booking(db_session, test_tenant, test_user, env_b, t0, t0 + timedelta(days=2))

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    assert conflicts == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_conflict_service.py -v
```

Expected: `ModuleNotFoundError: app.services.conflict_service`.

- [ ] **Step 3: Write the service**

Create `backend/app/services/conflict_service.py`:

```python
from sqlalchemy import select, and_, or_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking

TERMINAL_STATES = {"rejected", "closed"}


async def list_conflicts(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> list[Booking]:
    """Return other bookings conflicting with booking_id — same env, overlapping window,
    neither in a lifecycle-defined terminal state."""
    me = (await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if me is None or me.status in TERMINAL_STATES:
        return []

    stmt = (
        select(Booking)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.id != me.id,
            Booking.environment_id == me.environment_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(TERMINAL_STATES)),
            # half-open overlap: [start, end)
            Booking.start_date < me.end_date,
            Booking.end_date > me.start_date,
        )
        .order_by(Booking.start_date)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd backend && uv run pytest tests/test_conflict_service.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conflict_service.py backend/tests/test_conflict_service.py
git commit -m "feat: add conflict_service.list_conflicts with overlap detection"
```

---

### Task 6: Conflict service — acknowledgement upsert + authorization

**Files:**
- Modify: `backend/app/services/conflict_service.py`
- Modify: `backend/tests/test_conflict_service.py`

- [ ] **Step 1: Write failing tests for ack upsert + authorization**

Append to `backend/tests/test_conflict_service.py`:

```python
from fastapi import HTTPException
from app.db.models.booking_request import BookingRequest
from app.db.models.booking_conflict_ack import BookingConflictAck


async def _make_request_with_owner(db_session, test_tenant, test_user, delegates=None) -> BookingRequest:
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="p",
        booking_type_id=1,
        start_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 5, tzinfo=timezone.utc),
        booked_by=test_user.id,
        context_tag="none",
        exclusive_use_requested=False,
        delegate_user_ids=delegates,
    )
    db_session.add(req)
    await db_session.flush()
    return req


@pytest.mark.asyncio
async def test_ack_upsert_creates_then_updates(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    req = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req.id
    other = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await db_session.flush()

    ack = await conflict_service.upsert_ack(
        db_session, me.id, other.id, willing_to_share=True, notes="room to share",
        current_user=test_user, tenant_id=test_tenant.id,
    )
    assert ack.willing_to_share is True
    assert ack.notes == "room to share"
    assert ack.acknowledged_by == test_user.id
    assert ack.acknowledged_at is not None

    # Update
    ack2 = await conflict_service.upsert_ack(
        db_session, me.id, other.id, willing_to_share=False, notes="actually no",
        current_user=test_user, tenant_id=test_tenant.id,
    )
    assert ack2.id == ack.id
    assert ack2.willing_to_share is False
    assert ack2.notes == "actually no"


@pytest.mark.asyncio
async def test_ack_rejects_non_owner_non_delegate(db_session, test_tenant, test_user):
    from app.db.models.user import User
    from app.core.security import get_password_hash

    other_user = User(
        tenant_id=test_tenant.id,
        username="other",
        email="other@test",
        password_hash=get_password_hash("x"),
        role="Developer",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()

    env = await _make_env(db_session, test_tenant)
    req = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req.id
    conflict = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await conflict_service.upsert_ack(
            db_session, me.id, conflict.id, willing_to_share=True, notes="",
            current_user=other_user, tenant_id=test_tenant.id,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_ack_allows_delegate(db_session, test_tenant, test_user):
    from app.db.models.user import User
    from app.core.security import get_password_hash

    delegate = User(
        tenant_id=test_tenant.id,
        username="delegate",
        email="delegate@test",
        password_hash=get_password_hash("x"),
        role="Developer",
        is_active=True,
    )
    db_session.add(delegate)
    await db_session.flush()

    env = await _make_env(db_session, test_tenant)
    req = await _make_request_with_owner(db_session, test_tenant, test_user, delegates=[delegate.id])
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req.id
    other = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await db_session.flush()

    ack = await conflict_service.upsert_ack(
        db_session, me.id, other.id, willing_to_share=True, notes="",
        current_user=delegate, tenant_id=test_tenant.id,
    )
    assert ack.acknowledged_by == delegate.id
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_conflict_service.py -v -k ack
```

Expected: 3 tests fail — `upsert_ack` not defined.

- [ ] **Step 3: Implement `upsert_ack`**

Append to `backend/app/services/conflict_service.py`:

```python
from datetime import datetime, timezone
from fastapi import HTTPException, status

from app.db.models.booking_request import BookingRequest
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.user import User


async def _authorize_ack(db: AsyncSession, booking_id: int, tenant_id: int, user: User) -> None:
    """User must be the booking's parent-request owner or a listed delegate."""
    booking = (await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if booking is None or booking.booking_request_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    req = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
    )).scalar_one()
    if user.id == req.booked_by:
        return
    if req.delegate_user_ids and user.id in req.delegate_user_ids:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the owner or a delegate may acknowledge a conflict",
    )


async def upsert_ack(
    db: AsyncSession,
    booking_id: int,
    other_booking_id: int,
    *,
    willing_to_share: bool,
    notes: str | None,
    current_user: User,
    tenant_id: int,
) -> BookingConflictAck:
    await _authorize_ack(db, booking_id, tenant_id, current_user)

    existing = (await db.execute(
        select(BookingConflictAck).where(
            BookingConflictAck.booking_id == booking_id,
            BookingConflictAck.other_booking_id == other_booking_id,
            BookingConflictAck.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is None:
        ack = BookingConflictAck(
            tenant_id=tenant_id,
            booking_id=booking_id,
            other_booking_id=other_booking_id,
            willing_to_share=willing_to_share,
            notes=notes,
            acknowledged_by=current_user.id,
            acknowledged_at=now,
        )
        db.add(ack)
        await db.flush()
        return ack

    existing.willing_to_share = willing_to_share
    existing.notes = notes
    existing.acknowledged_by = current_user.id
    existing.acknowledged_at = now
    await db.flush()
    return existing


async def get_ack(
    db: AsyncSession, booking_id: int, other_booking_id: int, tenant_id: int
) -> BookingConflictAck | None:
    return (await db.execute(
        select(BookingConflictAck).where(
            BookingConflictAck.booking_id == booking_id,
            BookingConflictAck.other_booking_id == other_booking_id,
            BookingConflictAck.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()


async def has_unacknowledged_conflicts(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> bool:
    conflicts = await list_conflicts(db, booking_id, tenant_id)
    if not conflicts:
        return False
    for other in conflicts:
        ack = await get_ack(db, booking_id, other.id, tenant_id)
        if ack is None or ack.willing_to_share is None:
            return True
    return False
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_conflict_service.py -v
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conflict_service.py backend/tests/test_conflict_service.py
git commit -m "feat: add upsert_ack + has_unacknowledged_conflicts"
```

---

### Task 7: BookingRequest service — create with N envs

**Files:**
- Create: `backend/app/services/booking_request_service.py`
- Create: `backend/tests/test_booking_request_service.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_booking_request_service.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

from app.services import booking_request_service
from app.db.models.environment import Environment
from app.db.models.booking_lifecycle import BookingType, LifecycleTemplate


async def _seed_lifecycle_and_type(db_session, tenant):
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        name="default",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(tenant_id=tenant.id, name="Standard", lifecycle_template_id=tpl.id)
    db_session.add(bt)
    await db_session.flush()
    return bt


async def _make_env(db_session, tenant, name):
    env = Environment(tenant_id=tenant.id, name=name, subsystem_id=None, env_type="dev")
    db_session.add(env)
    await db_session.flush()
    return env


@pytest.mark.asyncio
async def test_create_request_with_multiple_envs(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    env_b = await _make_env(db_session, test_tenant, "b")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    req, detected = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "p",
            "booking_type_id": bt.id,
            "start_date": t0,
            "end_date": t0 + timedelta(days=2),
            "environment_ids": [env_a.id, env_b.id],
            "notes": None,
            "context_tag": "none",
            "exclusive_use_requested": False,
            "custom_fields": None,
            "delegate_user_ids": None,
        },
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    assert req.id is not None
    assert len(req.bookings) == 2
    assert {b.environment_id for b in req.bookings} == {env_a.id, env_b.id}
    # Each child in initial state
    assert all(b.status == "draft" for b in req.bookings)
    # Dates inherited
    assert all(b.start_date == t0 for b in req.bookings)
    # No existing overlaps
    assert detected == {}


@pytest.mark.asyncio
async def test_create_request_rejects_duplicate_envs(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    with pytest.raises(HTTPException) as exc:
        await booking_request_service.create_request(
            db_session,
            data={
                "project_name": "p",
                "booking_type_id": bt.id,
                "start_date": t0,
                "end_date": t0 + timedelta(days=2),
                "environment_ids": [env_a.id, env_a.id],
                "notes": None,
                "context_tag": "none",
                "exclusive_use_requested": False,
                "custom_fields": None,
                "delegate_user_ids": None,
            },
            current_user=test_user,
            tenant_id=test_tenant.id,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_request_reports_detected_conflicts(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    # Pre-existing request on env_a overlapping
    _, _ = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "old",
            "booking_type_id": bt.id,
            "start_date": t0,
            "end_date": t0 + timedelta(days=5),
            "environment_ids": [env_a.id],
            "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user,
        tenant_id=test_tenant.id,
    )

    new_req, detected = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "new",
            "booking_type_id": bt.id,
            "start_date": t0 + timedelta(days=1),
            "end_date": t0 + timedelta(days=3),
            "environment_ids": [env_a.id],
            "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    # Creation still succeeds
    assert new_req.id is not None
    # But detected_conflicts surfaces the overlap for the one new child
    assert env_a.id in {booking.environment_id for booking in new_req.bookings}
    new_child = next(b for b in new_req.bookings if b.environment_id == env_a.id)
    assert new_child.id in detected
    assert len(detected[new_child.id]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `create_request`**

Create `backend/app/services/booking_request_service.py`:

```python
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest
from app.db.models.booking_lifecycle import BookingType, LifecycleTemplate
from app.db.models.environment import Environment
from app.db.models.user import User
from app.services import conflict_service


async def _load_initial_state(db: AsyncSession, booking_type_id: int, tenant_id: int) -> str:
    bt = (await db.execute(
        select(BookingType).where(BookingType.id == booking_type_id, BookingType.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if bt is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown booking_type_id")
    tpl = (await db.execute(
        select(LifecycleTemplate).where(LifecycleTemplate.id == bt.lifecycle_template_id)
    )).scalar_one()
    for s in tpl.definition.get("states", []):
        if s.get("is_initial"):
            return s["key"]
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lifecycle has no initial state")


async def create_request(
    db: AsyncSession,
    data: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> tuple[BookingRequest, dict[int, list[Booking]]]:
    env_ids: list[int] = data["environment_ids"]
    if len(env_ids) != len(set(env_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "environment_ids must be unique")
    if not env_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one environment_id is required")

    envs = (await db.execute(
        select(Environment).where(Environment.id.in_(env_ids), Environment.tenant_id == tenant_id)
    )).scalars().all()
    if len(envs) != len(env_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "One or more environment_ids not found")

    initial_state = await _load_initial_state(db, data["booking_type_id"], tenant_id)

    req = BookingRequest(
        tenant_id=tenant_id,
        project_name=data["project_name"],
        booking_type_id=data["booking_type_id"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        notes=data.get("notes"),
        context_tag=ContextTag(data.get("context_tag", "none")),
        exclusive_use_requested=data.get("exclusive_use_requested", False),
        custom_fields=data.get("custom_fields"),
        booked_by=current_user.id,
        delegate_user_ids=data.get("delegate_user_ids"),
    )
    db.add(req)
    await db.flush()

    children: list[Booking] = []
    for env_id in env_ids:
        child = Booking(
            tenant_id=tenant_id,
            booking_request_id=req.id,
            environment_id=env_id,
            project_name=data["project_name"],  # dual-write during migration window
            booked_by=current_user.id,
            start_date=data["start_date"],
            end_date=data["end_date"],
            exclusive_use=data.get("exclusive_use_requested", False),
            booking_type_id=data["booking_type_id"],
            status=initial_state,
            notes=data.get("notes"),
            context_tag=ContextTag(data.get("context_tag", "none")),
            custom_fields=data.get("custom_fields"),
        )
        db.add(child)
        children.append(child)
    await db.flush()

    # Detect conflicts per child (soft — informational)
    detected: dict[int, list[Booking]] = {}
    for c in children:
        others = await conflict_service.list_conflicts(db, c.id, tenant_id)
        if others:
            detected[c.id] = others

    await publish_event(
        db,
        event_type="BookingRequestCreated",
        aggregate_id=req.id,
        payload={"request_id": req.id, "child_ids": [c.id for c in children]},
        tenant_id=tenant_id,
    )
    return req, detected
```

> Note: `publish_event` signature — match the codebase's existing `app.core.events.publish_event`. If the signature differs, adapt accordingly.

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/booking_request_service.py backend/tests/test_booking_request_service.py
git commit -m "feat: booking_request_service.create_request with N env children + conflict detection"
```

---

### Task 8: BookingRequest service — preview conflicts (no side effects)

**Files:**
- Modify: `backend/app/services/booking_request_service.py`
- Modify: `backend/tests/test_booking_request_service.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_booking_request_service.py`:

```python
@pytest.mark.asyncio
async def test_preview_conflicts_reports_without_creating(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    # Existing booking occupies window
    await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "old", "booking_type_id": bt.id,
            "start_date": t0, "end_date": t0 + timedelta(days=5),
            "environment_ids": [env_a.id], "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user, tenant_id=test_tenant.id,
    )

    before = await db_session.execute(select(Booking))
    before_count = len(before.scalars().all())

    preview = await booking_request_service.preview_conflicts(
        db_session,
        environment_ids=[env_a.id],
        start_date=t0 + timedelta(days=1),
        end_date=t0 + timedelta(days=3),
        tenant_id=test_tenant.id,
    )
    assert env_a.id in preview
    assert len(preview[env_a.id]) == 1

    after = await db_session.execute(select(Booking))
    after_count = len(after.scalars().all())
    assert after_count == before_count  # no rows created
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py::test_preview_conflicts_reports_without_creating -v
```

Expected: `AttributeError: module ... has no attribute 'preview_conflicts'`.

- [ ] **Step 3: Implement `preview_conflicts`**

Append to `backend/app/services/booking_request_service.py`:

```python
async def preview_conflicts(
    db: AsyncSession,
    *,
    environment_ids: list[int],
    start_date: datetime,
    end_date: datetime,
    tenant_id: int,
) -> dict[int, list[Booking]]:
    """Return a dict keyed by environment_id listing existing bookings that would overlap.
    No database mutation."""
    from sqlalchemy import and_, not_
    results: dict[int, list[Booking]] = {}
    for env_id in environment_ids:
        stmt = (
            select(Booking)
            .where(
                Booking.tenant_id == tenant_id,
                Booking.environment_id == env_id,
                Booking.deleted_at.is_(None),
                not_(Booking.status.in_(conflict_service.TERMINAL_STATES)),
                Booking.start_date < end_date,
                Booking.end_date > start_date,
            )
            .order_by(Booking.start_date)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if rows:
            results[env_id] = list(rows)
    return results
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/booking_request_service.py backend/tests/test_booking_request_service.py
git commit -m "feat: preview_conflicts"
```

---

### Task 9: BookingRequest service — add / remove env on existing request

**Files:**
- Modify: `backend/app/services/booking_request_service.py`
- Modify: `backend/tests/test_booking_request_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_booking_request_service.py`:

```python
@pytest.mark.asyncio
async def test_add_environment_to_request(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    env_b = await _make_env(db_session, test_tenant, "b")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    req, _ = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "p", "booking_type_id": bt.id,
            "start_date": t0, "end_date": t0 + timedelta(days=2),
            "environment_ids": [env_a.id], "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user, tenant_id=test_tenant.id,
    )

    added = await booking_request_service.add_environment(
        db_session, request_id=req.id, environment_id=env_b.id,
        start_date=None, end_date=None,
        current_user=test_user, tenant_id=test_tenant.id,
    )
    assert added.environment_id == env_b.id
    assert added.start_date == t0  # inherited
    assert added.status == "draft"


@pytest.mark.asyncio
async def test_add_environment_with_override_dates(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    env_b = await _make_env(db_session, test_tenant, "b")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    t_override = t0 + timedelta(days=1)

    req, _ = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "p", "booking_type_id": bt.id,
            "start_date": t0, "end_date": t0 + timedelta(days=2),
            "environment_ids": [env_a.id], "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user, tenant_id=test_tenant.id,
    )

    added = await booking_request_service.add_environment(
        db_session, request_id=req.id, environment_id=env_b.id,
        start_date=t_override, end_date=t_override + timedelta(days=1),
        current_user=test_user, tenant_id=test_tenant.id,
    )
    assert added.start_date == t_override


@pytest.mark.asyncio
async def test_remove_environment_soft_deletes(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    env_b = await _make_env(db_session, test_tenant, "b")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    req, _ = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "p", "booking_type_id": bt.id,
            "start_date": t0, "end_date": t0 + timedelta(days=2),
            "environment_ids": [env_a.id, env_b.id], "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user, tenant_id=test_tenant.id,
    )
    child_b = next(b for b in req.bookings if b.environment_id == env_b.id)

    await booking_request_service.remove_environment(
        db_session, request_id=req.id, booking_id=child_b.id,
        current_user=test_user, tenant_id=test_tenant.id,
    )
    await db_session.refresh(child_b)
    assert child_b.deleted_at is not None
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py -v -k "add_environment or remove_environment"
```

Expected: 3 fail on attribute error.

- [ ] **Step 3: Implement `add_environment` + `remove_environment`**

Append to `backend/app/services/booking_request_service.py`:

```python
from datetime import datetime, timezone as _tz


async def _get_request(db: AsyncSession, request_id: int, tenant_id: int) -> BookingRequest:
    req = (await db.execute(
        select(BookingRequest).where(
            BookingRequest.id == request_id, BookingRequest.tenant_id == tenant_id
        )
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


async def add_environment(
    db: AsyncSession,
    *,
    request_id: int,
    environment_id: int,
    start_date: datetime | None,
    end_date: datetime | None,
    current_user: User,
    tenant_id: int,
) -> Booking:
    req = await _get_request(db, request_id, tenant_id)

    env = (await db.execute(
        select(Environment).where(Environment.id == environment_id, Environment.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    # Reject if env already has a non-deleted child in this request
    existing = (await db.execute(
        select(Booking).where(
            Booking.booking_request_id == req.id,
            Booking.environment_id == environment_id,
            Booking.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Environment already in request")

    initial_state = await _load_initial_state(db, req.booking_type_id, tenant_id)

    child = Booking(
        tenant_id=tenant_id,
        booking_request_id=req.id,
        environment_id=environment_id,
        project_name=req.project_name,
        booked_by=req.booked_by,
        start_date=start_date or req.start_date,
        end_date=end_date or req.end_date,
        exclusive_use=req.exclusive_use_requested,
        booking_type_id=req.booking_type_id,
        status=initial_state,
        notes=req.notes,
        context_tag=req.context_tag,
        custom_fields=req.custom_fields,
    )
    db.add(child)
    await db.flush()

    await publish_event(
        db,
        event_type="BookingEnvironmentAdded",
        aggregate_id=req.id,
        payload={"request_id": req.id, "booking_id": child.id, "environment_id": environment_id},
        tenant_id=tenant_id,
    )
    return child


async def remove_environment(
    db: AsyncSession,
    *,
    request_id: int,
    booking_id: int,
    current_user: User,
    tenant_id: int,
) -> None:
    req = await _get_request(db, request_id, tenant_id)
    child = (await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.booking_request_id == req.id,
            Booking.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if child is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment booking not found in request")

    child.deleted_at = datetime.now(_tz.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="BookingEnvironmentRemoved",
        aggregate_id=req.id,
        payload={"request_id": req.id, "booking_id": child.id},
        tenant_id=tenant_id,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/booking_request_service.py backend/tests/test_booking_request_service.py
git commit -m "feat: add/remove environment on existing booking request"
```

---

### Task 10: BookingRequest service — update standard / custom fields (permission-gated, cascade to children)

**Files:**
- Modify: `backend/app/services/booking_request_service.py`
- Modify: `backend/tests/test_booking_request_service.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_booking_request_service.py`:

```python
@pytest.mark.asyncio
async def test_update_standard_fields_cascades_to_children(db_session, test_tenant, test_user):
    bt = await _seed_lifecycle_and_type(db_session, test_tenant)
    env_a = await _make_env(db_session, test_tenant, "a")
    env_b = await _make_env(db_session, test_tenant, "b")
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)

    req, _ = await booking_request_service.create_request(
        db_session,
        data={
            "project_name": "old", "booking_type_id": bt.id,
            "start_date": t0, "end_date": t0 + timedelta(days=2),
            "environment_ids": [env_a.id, env_b.id], "notes": None, "context_tag": "none",
            "exclusive_use_requested": False, "custom_fields": None, "delegate_user_ids": None,
        },
        current_user=test_user, tenant_id=test_tenant.id,
    )

    updated = await booking_request_service.update_standard_fields(
        db_session,
        request_id=req.id,
        values={"project_name": "new"},
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    assert updated.project_name == "new"
    # Child dual-write also updated
    for child in updated.bookings:
        await db_session.refresh(child)
        assert child.project_name == "new"
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py::test_update_standard_fields_cascades_to_children -v
```

Expected: AttributeError.

- [ ] **Step 3: Implement updates**

Append to `backend/app/services/booking_request_service.py`:

```python
# Fields editable at the request level — must match the spec's PATCH endpoint
STANDARD_REQUEST_FIELDS = {
    "project_name",
    "booking_type_id",
    "start_date",
    "end_date",
    "notes",
    "context_tag",
    "exclusive_use_requested",
    "delegate_user_ids",
}


# Mirror columns on Booking to keep dual-reads consistent during the migration window.
_CHILD_MIRROR = {
    "project_name": "project_name",
    "booking_type_id": "booking_type_id",
    "start_date": "start_date",
    "end_date": "end_date",
    "notes": "notes",
    "context_tag": "context_tag",
    "exclusive_use_requested": "exclusive_use",
}


async def update_standard_fields(
    db: AsyncSession,
    *,
    request_id: int,
    values: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> BookingRequest:
    req = await _get_request(db, request_id, tenant_id)
    unknown = set(values) - STANDARD_REQUEST_FIELDS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown fields: {unknown}")

    # TODO permission gating using lifecycle field_permissions —
    # follow the same check used in booking_service.update_standard_fields today.
    # For now we allow the request owner to edit any standard field; sharpen in Task 16 once
    # the API wires permission checks.

    for k, v in values.items():
        if k == "context_tag" and v is not None:
            setattr(req, k, ContextTag(v))
        else:
            setattr(req, k, v)

    # Cascade to children via dual-write mirror
    children = (await db.execute(
        select(Booking).where(
            Booking.booking_request_id == req.id, Booking.deleted_at.is_(None)
        )
    )).scalars().all()
    for child in children:
        for parent_field, child_field in _CHILD_MIRROR.items():
            if parent_field in values:
                val = values[parent_field]
                if child_field == "context_tag" and val is not None:
                    val = ContextTag(val)
                setattr(child, child_field, val)
    await db.flush()

    await publish_event(
        db,
        event_type="BookingRequestUpdated",
        aggregate_id=req.id,
        payload={"request_id": req.id, "fields": list(values.keys())},
        tenant_id=tenant_id,
    )
    return req


async def update_custom_fields(
    db: AsyncSession,
    *,
    request_id: int,
    values: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> BookingRequest:
    req = await _get_request(db, request_id, tenant_id)
    req.custom_fields = values

    children = (await db.execute(
        select(Booking).where(
            Booking.booking_request_id == req.id, Booking.deleted_at.is_(None)
        )
    )).scalars().all()
    for c in children:
        c.custom_fields = values
    await db.flush()
    return req
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_booking_request_service.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/booking_request_service.py backend/tests/test_booking_request_service.py
git commit -m "feat: update_standard_fields and update_custom_fields with dual-write to children"
```

---

### Task 11: Booking service — dual-read shim + remove approve/reject/cancel

**Files:**
- Modify: `backend/app/services/booking_service.py`
- Modify: `backend/tests/test_booking_transitions.py` (delete obsolete approve/reject/cancel tests; transitions are covered by `/transition` already)

- [ ] **Step 1: Inspect the current service**

Read `backend/app/services/booking_service.py` and note where `approve_booking`, `reject_booking`, `cancel_booking` are defined. Also note where `get_booking` / `list_bookings` read shared fields (project_name, booking_type_id, notes, etc.) so the dual-read shim knows where to swap.

- [ ] **Step 2: Add dual-read helper**

Append near the top of `backend/app/services/booking_service.py` (under the imports):

```python
from app.db.models.booking_request import BookingRequest


async def _effective_shared(db, booking: Booking) -> dict:
    """Return the shared fields for a booking, preferring the parent booking_request when present.
    Used during the migration window to keep behaviour consistent once duplicate columns are dropped."""
    if booking.booking_request_id is None:
        return {
            "project_name": booking.project_name,
            "booking_type_id": booking.booking_type_id,
            "notes": booking.notes,
            "context_tag": booking.context_tag,
            "custom_fields": booking.custom_fields,
            "booked_by": booking.booked_by,
            "exclusive_use_requested": booking.exclusive_use,
        }
    req = (await db.execute(
        select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
    )).scalar_one()
    return {
        "project_name": req.project_name,
        "booking_type_id": req.booking_type_id,
        "notes": req.notes,
        "context_tag": req.context_tag,
        "custom_fields": req.custom_fields,
        "booked_by": req.booked_by,
        "exclusive_use_requested": req.exclusive_use_requested,
    }
```

- [ ] **Step 3: Replace reads of shared fields with shim calls**

In functions that serialise a `Booking` for responses (typically `get_booking`, `list_bookings`, `list_bookings_by_env`), replace direct `booking.project_name` / `booking.notes` / etc. with values from `await _effective_shared(db, booking)`. Keep the same response shape — this is a read-path swap only.

- [ ] **Step 4: Remove `approve_booking` / `reject_booking` / `cancel_booking`**

Delete these functions from `backend/app/services/booking_service.py`. Delete related imports. The `/transition` endpoint supersedes them.

- [ ] **Step 5: Narrow `update_standard_fields` on bookings to env overrides only**

If `update_standard_fields(booking_id, payload)` exists in `booking_service`, trim its accepted payload to `{"start_date", "end_date"}` (the only per-env overrides). Everything else is now on `booking_request_service.update_standard_fields`. Raise a 400 for any other key.

- [ ] **Step 6: Delete `update_custom_fields` on bookings**

Custom fields moved to the request. Remove the function; any caller must use `booking_request_service.update_custom_fields`.

- [ ] **Step 7: Update tests**

In `backend/tests/test_booking_transitions.py` and similar files, delete any tests specifically targeting `/approve` `/reject` `/cancel` legacy endpoints or the corresponding service functions. Keep `/transition` tests.

- [ ] **Step 8: Run the full backend test suite**

```bash
cd backend && uv run pytest -v
```

Expected: all pass. Failures here almost always mean a consumer still references the deleted functions — fix the consumer, not the shim.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/booking_service.py backend/tests/test_booking_transitions.py
git commit -m "refactor: dual-read shim + remove approve/reject/cancel from booking_service"
```

---

## Phase 3 — Backend API

### Task 12: Pydantic schemas for requests + conflicts

**Files:**
- Create: `backend/app/api/v1/schemas/booking_request.py`
- Create: `backend/app/api/v1/schemas/conflict.py`

- [ ] **Step 1: Create `booking_request.py` schema module**

```python
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class EnvBookingSummary(BaseModel):
    id: int
    environment_id: int
    environment_name: Optional[str] = None
    start_date: datetime
    end_date: datetime
    status: str
    has_unacknowledged_conflicts: bool = False

    class Config:
        from_attributes = True


class BookingRequestCreate(BaseModel):
    project_name: str
    booking_type_id: int
    start_date: datetime
    end_date: datetime
    environment_ids: list[int] = Field(..., min_length=1)
    notes: Optional[str] = None
    context_tag: str = "none"
    exclusive_use_requested: bool = False
    custom_fields: Optional[dict[str, Any]] = None
    delegate_user_ids: Optional[list[int]] = None


class BookingRequestUpdate(BaseModel):
    project_name: Optional[str] = None
    booking_type_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    notes: Optional[str] = None
    context_tag: Optional[str] = None
    exclusive_use_requested: Optional[bool] = None
    delegate_user_ids: Optional[list[int]] = None


class BookingRequestCustomFieldsUpdate(BaseModel):
    values: dict[str, Any]


class AddEnvironmentRequest(BaseModel):
    environment_id: int
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class BookingRequestResponse(BaseModel):
    id: int
    tenant_id: int
    project_name: str
    booking_type_id: int
    start_date: datetime
    end_date: datetime
    notes: Optional[str]
    context_tag: str
    exclusive_use_requested: bool
    custom_fields: Optional[dict[str, Any]]
    booked_by: int
    delegate_user_ids: Optional[list[int]]
    rollup_status: str
    bookings: list[EnvBookingSummary]

    class Config:
        from_attributes = True


class BookingRequestCreateResponse(BaseModel):
    request: BookingRequestResponse
    detected_conflicts: dict[int, list[EnvBookingSummary]]


class PreviewConflictsRequest(BaseModel):
    environment_ids: list[int]
    start_date: datetime
    end_date: datetime


class PreviewConflictsResponse(BaseModel):
    conflicts: dict[int, list[EnvBookingSummary]]
```

- [ ] **Step 2: Create `conflict.py` schema module**

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.api.v1.schemas.booking_request import EnvBookingSummary


class ConflictAckRead(BaseModel):
    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_by: Optional[int]
    acknowledged_at: Optional[datetime]

    class Config:
        from_attributes = True


class ConflictItem(BaseModel):
    other_booking: EnvBookingSummary
    ack: Optional[ConflictAckRead]


class ConflictAckUpsert(BaseModel):
    willing_to_share: bool
    notes: Optional[str] = None
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/schemas/booking_request.py backend/app/api/v1/schemas/conflict.py
git commit -m "feat: add booking_request + conflict Pydantic schemas"
```

---

### Task 13: `booking-requests` router

**Files:**
- Create: `backend/app/api/v1/booking_requests.py`
- Create: `backend/tests/test_booking_requests_api.py`

- [ ] **Step 1: Write the router**

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import booking_request_service
from app.api.v1.schemas.booking_request import (
    BookingRequestCreate, BookingRequestCreateResponse, BookingRequestResponse,
    BookingRequestUpdate, BookingRequestCustomFieldsUpdate,
    AddEnvironmentRequest, EnvBookingSummary,
    PreviewConflictsRequest, PreviewConflictsResponse,
)

router = APIRouter(prefix="/booking-requests", tags=["booking-requests"])


def _summaries(children) -> list[EnvBookingSummary]:
    # Basic projection — environment_name and has_unacknowledged_conflicts
    # are filled in by the caller for the detail endpoint.
    return [
        EnvBookingSummary(
            id=c.id,
            environment_id=c.environment_id,
            start_date=c.start_date,
            end_date=c.end_date,
            status=c.status,
        )
        for c in children if c.deleted_at is None
    ]


def _rollup(children) -> str:
    active = [c for c in children if c.deleted_at is None]
    if not active:
        return "empty"
    statuses = {c.status for c in active}
    if statuses == {"approved"}:
        return "all_approved"
    if statuses == {"rejected"}:
        return "all_rejected"
    if len(statuses) == 1:
        return active[0].status
    terminals = {"approved", "rejected", "closed"}
    if statuses.issubset(terminals):
        return "mixed"
    return "mixed"


def _to_response(req) -> BookingRequestResponse:
    return BookingRequestResponse(
        id=req.id, tenant_id=req.tenant_id, project_name=req.project_name,
        booking_type_id=req.booking_type_id, start_date=req.start_date, end_date=req.end_date,
        notes=req.notes, context_tag=req.context_tag.value if hasattr(req.context_tag, "value") else req.context_tag,
        exclusive_use_requested=req.exclusive_use_requested, custom_fields=req.custom_fields,
        booked_by=req.booked_by, delegate_user_ids=req.delegate_user_ids,
        rollup_status=_rollup(req.bookings),
        bookings=_summaries(req.bookings),
    )


@router.post("", response_model=BookingRequestCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_booking_request(
    data: BookingRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    req, detected = await booking_request_service.create_request(
        db, data=data.model_dump(), current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    await db.refresh(req, attribute_names=["bookings"])
    return BookingRequestCreateResponse(
        request=_to_response(req),
        detected_conflicts={
            k: [EnvBookingSummary(
                    id=b.id, environment_id=b.environment_id,
                    start_date=b.start_date, end_date=b.end_date, status=b.status,
                ) for b in v]
            for k, v in detected.items()
        },
    )


@router.post("/preview-conflicts", response_model=PreviewConflictsResponse)
async def preview_conflicts(
    data: PreviewConflictsRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    conflicts = await booking_request_service.preview_conflicts(
        db, environment_ids=data.environment_ids,
        start_date=data.start_date, end_date=data.end_date,
        tenant_id=current_user.active_tenant_id,
    )
    return PreviewConflictsResponse(
        conflicts={
            k: [EnvBookingSummary(
                    id=b.id, environment_id=b.environment_id,
                    start_date=b.start_date, end_date=b.end_date, status=b.status,
                ) for b in v]
            for k, v in conflicts.items()
        }
    )


@router.get("", response_model=list[BookingRequestResponse])
async def list_booking_requests(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    from sqlalchemy import select
    from app.db.models.booking_request import BookingRequest
    rows = (await db.execute(
        select(BookingRequest)
        .where(BookingRequest.tenant_id == current_user.active_tenant_id,
               BookingRequest.deleted_at.is_(None))
        .order_by(BookingRequest.created_at.desc())
    )).scalars().all()
    for r in rows:
        await db.refresh(r, attribute_names=["bookings"])
    return [_to_response(r) for r in rows]


@router.get("/{request_id}", response_model=BookingRequestResponse)
async def get_booking_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    req = await booking_request_service._get_request(db, request_id, current_user.active_tenant_id)
    await db.refresh(req, attribute_names=["bookings"])
    return _to_response(req)


@router.patch("/{request_id}/standard-fields", response_model=BookingRequestResponse)
async def update_request_standard_fields(
    request_id: int,
    data: BookingRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    values = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k in data.model_fields_set}
    req = await booking_request_service.update_standard_fields(
        db, request_id=request_id, values=values,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    await db.refresh(req, attribute_names=["bookings"])
    return _to_response(req)


@router.patch("/{request_id}/custom-fields", response_model=BookingRequestResponse)
async def update_request_custom_fields(
    request_id: int,
    data: BookingRequestCustomFieldsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    req = await booking_request_service.update_custom_fields(
        db, request_id=request_id, values=data.values,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    await db.refresh(req, attribute_names=["bookings"])
    return _to_response(req)


@router.post("/{request_id}/environments", response_model=EnvBookingSummary, status_code=status.HTTP_201_CREATED)
async def add_environment_to_request(
    request_id: int,
    data: AddEnvironmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    child = await booking_request_service.add_environment(
        db, request_id=request_id, environment_id=data.environment_id,
        start_date=data.start_date, end_date=data.end_date,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    return EnvBookingSummary(
        id=child.id, environment_id=child.environment_id,
        start_date=child.start_date, end_date=child.end_date, status=child.status,
    )


@router.delete("/{request_id}/environments/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_environment_from_request(
    request_id: int,
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    await booking_request_service.remove_environment(
        db, request_id=request_id, booking_id=booking_id,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
```

- [ ] **Step 2: Write happy-path API tests**

Create `backend/tests/test_booking_requests_api.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_request_endpoint(client: AsyncClient, auth_headers: dict, test_booking_type, test_environment):
    payload = {
        "project_name": "sprint-42",
        "booking_type_id": test_booking_type.id,
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2026-05-03T00:00:00Z",
        "environment_ids": [test_environment.id],
        "context_tag": "none",
    }
    resp = await client.post("/api/v1/booking-requests", headers=auth_headers, json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["request"]["project_name"] == "sprint-42"
    assert len(data["request"]["bookings"]) == 1
    assert data["detected_conflicts"] == {}


@pytest.mark.asyncio
async def test_preview_conflicts_endpoint(client: AsyncClient, auth_headers: dict, test_environment):
    resp = await client.post(
        "/api/v1/booking-requests/preview-conflicts",
        headers=auth_headers,
        json={
            "environment_ids": [test_environment.id],
            "start_date": "2026-05-01T00:00:00Z",
            "end_date": "2026-05-03T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    assert "conflicts" in resp.json()
```

> Fixture `test_booking_type` and `test_environment` will need to exist in `conftest.py`. If they don't, add them alongside the existing `test_tenant` / `test_user` fixtures, following the same pattern. The engineer should check `conftest.py` and extend as needed.

- [ ] **Step 3: Run tests to verify fail**

```bash
cd backend && uv run pytest tests/test_booking_requests_api.py -v
```

Expected: failure because the router isn't yet registered — fixed in Task 15.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/booking_requests.py backend/tests/test_booking_requests_api.py
git commit -m "feat: add booking_requests router"
```

---

### Task 14: Conflicts router

**Files:**
- Create: `backend/app/api/v1/conflicts.py`
- Create: `backend/tests/test_conflicts_api.py`

- [ ] **Step 1: Write the router**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import conflict_service
from app.api.v1.schemas.conflict import ConflictAckUpsert, ConflictAckRead, ConflictItem
from app.api.v1.schemas.booking_request import EnvBookingSummary

router = APIRouter(prefix="/bookings", tags=["conflicts"])


@router.get("/{booking_id}/conflicts", response_model=list[ConflictItem])
async def list_conflicts(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    others = await conflict_service.list_conflicts(
        db, booking_id, current_user.active_tenant_id
    )
    items: list[ConflictItem] = []
    for o in others:
        ack = await conflict_service.get_ack(db, booking_id, o.id, current_user.active_tenant_id)
        items.append(ConflictItem(
            other_booking=EnvBookingSummary(
                id=o.id, environment_id=o.environment_id,
                start_date=o.start_date, end_date=o.end_date, status=o.status,
            ),
            ack=ConflictAckRead.model_validate(ack) if ack else None,
        ))
    return items


@router.put("/{booking_id}/conflicts/{other_id}/ack", response_model=ConflictAckRead)
async def ack_conflict(
    booking_id: int,
    other_id: int,
    data: ConflictAckUpsert,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    ack = await conflict_service.upsert_ack(
        db, booking_id, other_id,
        willing_to_share=data.willing_to_share,
        notes=data.notes,
        current_user=current_user,
        tenant_id=current_user.active_tenant_id,
    )
    return ConflictAckRead.model_validate(ack)
```

- [ ] **Step 2: Write API tests**

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_conflicts_empty(client: AsyncClient, auth_headers: dict, test_booking):
    resp = await client.get(f"/api/v1/bookings/{test_booking.id}/conflicts", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_upsert_conflict_ack(client: AsyncClient, auth_headers: dict, test_booking, test_conflicting_booking):
    resp = await client.put(
        f"/api/v1/bookings/{test_booking.id}/conflicts/{test_conflicting_booking.id}/ack",
        headers=auth_headers,
        json={"willing_to_share": True, "notes": "coordinated account ranges"},
    )
    assert resp.status_code == 200
    ack = resp.json()
    assert ack["willing_to_share"] is True
    assert ack["notes"] == "coordinated account ranges"
```

> Fixtures `test_booking`, `test_conflicting_booking` may need to be added to `conftest.py`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/conflicts.py backend/tests/test_conflicts_api.py
git commit -m "feat: add conflicts router (list + upsert ack)"
```

---

### Task 15: Remove legacy endpoints, add `request` block + `has_unacknowledged_conflicts`, register routers

**Files:**
- Modify: `backend/app/api/v1/bookings.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_booking_transitions.py` and related (drop dead tests)

- [ ] **Step 1: Remove `/approve`, `/reject`, `/cancel` routes**

In `backend/app/api/v1/bookings.py`, delete the three routes at lines 126, 136, 146 (from the earlier grep). Also remove any imports that become unused.

- [ ] **Step 2: Remove the `/custom-fields` PATCH route**

Custom fields moved to the request. Delete the booking-level custom fields PATCH route from `backend/app/api/v1/bookings.py`.

- [ ] **Step 3: Narrow `/standard-fields` PATCH to env overrides only**

The route should now accept only `{start_date?, end_date?}`. If other keys are sent, return 400 (matches the service layer's validation from Task 11).

- [ ] **Step 4: Extend `GET /bookings/{id}` to include the `request` block + `has_unacknowledged_conflicts`**

After loading the booking, compose the response with:

```python
from app.services import conflict_service, booking_request_service

shared = await _effective_shared(db, booking)  # from booking_service
has_conflicts = await conflict_service.has_unacknowledged_conflicts(
    db, booking.id, current_user.active_tenant_id
)
request = None
if booking.booking_request_id is not None:
    request = await booking_request_service._get_request(db, booking.booking_request_id, current_user.active_tenant_id)
# Return response: existing shape + `request` summary + `has_unacknowledged_conflicts`
```

Update the Pydantic response schema in `backend/app/api/v1/schemas/booking.py` to include these two new fields. Existing clients ignoring unknown fields remain unaffected.

- [ ] **Step 5: Extend `GET /bookings` (list) to include `has_unacknowledged_conflicts` per row + denormalized `project_name` / `booked_by_username` / `booking_type_id` from the parent**

This is a read-path change only — same shape, enriched values using the dual-read shim.

- [ ] **Step 6: Register new routers in `backend/app/main.py`**

```python
from app.api.v1 import booking_requests, conflicts  # new imports

app.include_router(booking_requests.router, prefix="/api/v1")
app.include_router(conflicts.router, prefix="/api/v1")
```

- [ ] **Step 7: Run full backend test suite**

```bash
cd backend && uv run pytest -v
```

Expected: all pass, including the new Task 13 + 14 tests.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/bookings.py backend/app/main.py backend/app/api/v1/schemas/booking.py backend/tests/
git commit -m "feat: register request + conflict routers; extend booking responses; drop legacy approve/reject/cancel routes"
```

---

## Phase 4 — Frontend shared components (behaviour-preserving extraction)

### Task 16: Extract `TransitionButtons` from `BookingDetail`

**Files:**
- Create: `frontend/src/components/bookings/TransitionButtons.tsx`
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { Box, Button } from '@mui/material'
import type { AllowedTransition } from '../../types/bookingLifecycle'

type Props = {
  transitions: AllowedTransition[]
  onTransition: (toState: string, label: string) => void
  size?: 'small' | 'medium'
}

export default function TransitionButtons({ transitions, onTransition, size = 'small' }: Props) {
  if (transitions.length === 0) return null
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
      {transitions.map((t) => (
        <Button
          key={t.to_state}
          variant="contained"
          color={
            t.to_state === 'rejected' ? 'error' :
            t.to_state === 'approved' ? 'success' : 'primary'
          }
          size={size}
          onClick={() => onTransition(t.to_state, t.label)}
        >
          {t.label}
        </Button>
      ))}
    </Box>
  )
}
```

- [ ] **Step 2: Replace inline transition rendering in `BookingDetail.tsx`**

Replace `BookingDetail.tsx:183-203` with:

```tsx
{allowedTransitions.length > 0 && (
  <Box sx={{ mb: 3 }}>
    <TransitionButtons transitions={allowedTransitions} onTransition={handleTransition} />
  </Box>
)}
```

Add the import:

```typescript
import TransitionButtons from '../../components/bookings/TransitionButtons'
```

- [ ] **Step 3: Manual verification**

Run the app:

```bash
cd backend && uv run uvicorn app.main:app --reload &
cd frontend && npm run dev
```

Visit `/bookings/<some-id>` and confirm transitions still render and fire correctly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/bookings/TransitionButtons.tsx frontend/src/pages/bookings/BookingDetail.tsx
git commit -m "refactor: extract TransitionButtons component"
```

---

### Task 17: Extract `EditStandardFieldsDialog`

**Files:**
- Create: `frontend/src/components/bookings/EditStandardFieldsDialog.tsx`
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx`

- [ ] **Step 1: Create the component**

Copy the dialog JSX currently at `BookingDetail.tsx:363-489` into a new component. Props:

```typescript
import { useState } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Checkbox, FormControlLabel,
  FormControl, InputLabel, Select, MenuItem,
} from '@mui/material'
import type { BookingResponse } from '../../types/booking'

type BookingType = { id: number; name: string }

export type EditStandardFieldsDialogProps = {
  open: boolean
  booking: BookingResponse
  bookingTypes: BookingType[]
  onClose: () => void
  onSaved: (updated: BookingResponse) => void
  saver: (payload: Record<string, unknown>) => Promise<BookingResponse>
  onError?: (msg: string) => void
}

export default function EditStandardFieldsDialog({
  open, booking, bookingTypes, onClose, onSaved, saver, onError,
}: EditStandardFieldsDialogProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => ({
    project_name: booking.project_name,
    start_date: booking.start_date.slice(0, 10),
    end_date: booking.end_date.slice(0, 10),
    booking_type: booking.booking_type_id,
    notes: booking.notes ?? '',
    exclusive_use: booking.exclusive_use,
    context_tag: booking.context_tag,
  }))
  const [saving, setSaving] = useState(false)

  const sfPerms = booking.standard_field_permissions ?? {}
  const canEdit = (field: string) => sfPerms[field]?.editable === true

  const handleSave = async () => {
    setSaving(true)
    try {
      const fieldMap: Record<string, string> = {
        project_name: 'project_name',
        start_date: 'start_date',
        end_date: 'end_date',
        booking_type: 'booking_type_id',
        notes: 'notes',
        exclusive_use: 'exclusive_use',
        context_tag: 'context_tag',
      }
      const payload: Record<string, unknown> = {}
      for (const [key, apiKey] of Object.entries(fieldMap)) {
        if (sfPerms[key]?.editable) payload[apiKey] = values[key]
      }
      const updated = await saver(payload)
      onSaved(updated)
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed'
      onError?.(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit Standard Fields</DialogTitle>
      <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <TextField
          label="Project Name" fullWidth size="small"
          value={values.project_name as string}
          disabled={!canEdit('project_name')}
          onChange={(e) => setValues((v) => ({ ...v, project_name: e.target.value }))}
        />
        <TextField
          label="Start Date" type="date" fullWidth size="small"
          InputLabelProps={{ shrink: true }}
          value={values.start_date as string}
          disabled={!canEdit('start_date')}
          onChange={(e) => setValues((v) => ({ ...v, start_date: e.target.value }))}
        />
        <TextField
          label="End Date" type="date" fullWidth size="small"
          InputLabelProps={{ shrink: true }}
          value={values.end_date as string}
          disabled={!canEdit('end_date')}
          onChange={(e) => setValues((v) => ({ ...v, end_date: e.target.value }))}
        />
        <FormControl fullWidth size="small" disabled={!canEdit('booking_type')}>
          <InputLabel>Booking Type</InputLabel>
          <Select
            label="Booking Type"
            value={(values.booking_type as number) ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, booking_type: e.target.value }))}
          >
            {bookingTypes.map((bt) => (
              <MenuItem key={bt.id} value={bt.id}>{bt.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          label="Notes" multiline minRows={3} fullWidth size="small"
          value={values.notes as string}
          disabled={!canEdit('notes')}
          onChange={(e) => setValues((v) => ({ ...v, notes: e.target.value }))}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={Boolean(values.exclusive_use)}
              disabled={!canEdit('exclusive_use')}
              onChange={(e) => setValues((v) => ({ ...v, exclusive_use: e.target.checked }))}
            />
          }
          label="Exclusive Use"
        />
        <FormControl fullWidth size="small" disabled={!canEdit('context_tag')}>
          <InputLabel>Context Tag</InputLabel>
          <Select
            label="Context Tag"
            value={(values.context_tag as string) ?? 'none'}
            onChange={(e) => setValues((v) => ({ ...v, context_tag: e.target.value }))}
          >
            <MenuItem value="none">None</MenuItem>
            <MenuItem value="deployment">Deployment</MenuItem>
            <MenuItem value="regression">Regression</MenuItem>
          </Select>
        </FormControl>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
```

- [ ] **Step 2: Replace inline dialog in `BookingDetail.tsx`**

Delete `BookingDetail.tsx:363-489`. Replace with:

```tsx
<EditStandardFieldsDialog
  open={editingStandardFields}
  booking={booking}
  bookingTypes={bookingTypes}
  onClose={() => setEditingStandardFields(false)}
  onSaved={setBooking}
  saver={(payload) => bookingService.updateStandardFields(bookingId, payload)}
  onError={setError}
/>
```

Remove obsolete state (`sfEditValues`, `sfSaving`) from `BookingDetail`.

- [ ] **Step 3: Manual verification**

Open a booking with editable standard fields, hit Edit, save a field. Confirm behaviour unchanged.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/bookings/EditStandardFieldsDialog.tsx frontend/src/pages/bookings/BookingDetail.tsx
git commit -m "refactor: extract EditStandardFieldsDialog"
```

---

### Task 18: Extract `EditCustomFieldsDialog`

**Files:**
- Create: `frontend/src/components/bookings/EditCustomFieldsDialog.tsx`
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { useState } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button,
} from '@mui/material'
import type { BookingResponse } from '../../types/booking'
import type { CustomFieldDefinition } from '../../types/customField'
import CustomFieldsSection from '../CustomFieldsSection'

export type EditCustomFieldsDialogProps = {
  open: boolean
  booking: BookingResponse
  definitions: CustomFieldDefinition[]
  onClose: () => void
  onSaved: (updated: BookingResponse) => void
  saver: (values: Record<string, unknown>) => Promise<BookingResponse>
  onError?: (msg: string) => void
}

export default function EditCustomFieldsDialog({
  open, booking, definitions, onClose, onSaved, saver, onError,
}: EditCustomFieldsDialogProps) {
  const perms = booking.custom_field_permissions ?? {}
  const editableDefs = definitions.filter((d) => perms[d.field_key]?.editable)
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(editableDefs.map((d) => [d.field_key, booking.custom_fields?.[d.field_key] ?? '']))
  )
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await saver(values)
      onSaved(updated)
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed'
      onError?.(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Edit Custom Fields</DialogTitle>
      <DialogContent sx={{ pt: 2 }}>
        <CustomFieldsSection definitions={editableDefs} values={values} onChange={setValues} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
```

- [ ] **Step 2: Replace in `BookingDetail.tsx`**

Delete `BookingDetail.tsx:491-531` and replace with:

```tsx
<EditCustomFieldsDialog
  open={editingCustomFields}
  booking={booking}
  definitions={customFieldDefs}
  onClose={() => setEditingCustomFields(false)}
  onSaved={setBooking}
  saver={(values) => bookingRequestService.updateCustomFields(booking.booking_request_id!, values)}
  onError={setError}
/>
```

> Note: custom fields now save against the request, not the env booking. `bookingRequestService` is introduced in Task 22; wire this up properly then and leave a temporary stub reference here.

During Task 18 itself, wire the saver to the legacy `bookingService.updateCustomFields` so the refactor remains behaviour-preserving and compiles. It will be rewired to `bookingRequestService` in Task 23.

- [ ] **Step 3: Manual verification**

Edit a booking's custom fields. Confirm save works.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/bookings/EditCustomFieldsDialog.tsx frontend/src/pages/bookings/BookingDetail.tsx
git commit -m "refactor: extract EditCustomFieldsDialog"
```

---

## Phase 5 — Frontend types, services, store

### Task 19: Types for `BookingRequest` + conflict

**Files:**
- Create: `frontend/src/types/bookingRequest.ts`
- Create: `frontend/src/types/conflict.ts`
- Modify: `frontend/src/types/booking.ts`

- [ ] **Step 1: `bookingRequest.ts`**

```typescript
export type EnvBookingSummary = {
  id: number
  environment_id: number
  environment_name?: string
  start_date: string
  end_date: string
  status: string
  has_unacknowledged_conflicts?: boolean
}

export type BookingRequestResponse = {
  id: number
  tenant_id: number
  project_name: string
  booking_type_id: number
  start_date: string
  end_date: string
  notes: string | null
  context_tag: string
  exclusive_use_requested: boolean
  custom_fields: Record<string, unknown> | null
  booked_by: number
  delegate_user_ids: number[] | null
  rollup_status: string
  bookings: EnvBookingSummary[]
}

export type BookingRequestCreatePayload = {
  project_name: string
  booking_type_id: number
  start_date: string
  end_date: string
  environment_ids: number[]
  notes?: string | null
  context_tag?: string
  exclusive_use_requested?: boolean
  custom_fields?: Record<string, unknown> | null
  delegate_user_ids?: number[] | null
}

export type BookingRequestCreateResponse = {
  request: BookingRequestResponse
  detected_conflicts: Record<number, EnvBookingSummary[]>
}

export type PreviewConflictsResponse = {
  conflicts: Record<number, EnvBookingSummary[]>
}
```

- [ ] **Step 2: `conflict.ts`**

```typescript
import type { EnvBookingSummary } from './bookingRequest'

export type ConflictAck = {
  willing_to_share: boolean | null
  notes: string | null
  acknowledged_by: number | null
  acknowledged_at: string | null
}

export type ConflictItem = {
  other_booking: EnvBookingSummary
  ack: ConflictAck | null
}
```

- [ ] **Step 3: Extend `booking.ts`**

Add two optional fields to `BookingResponse`:

```typescript
has_unacknowledged_conflicts?: boolean
booking_request_id?: number | null
request?: {
  id: number
  project_name: string
  booking_type_id: number
  booked_by: number
  booked_by_username?: string
  delegate_user_ids: number[] | null
} | null
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/bookingRequest.ts frontend/src/types/conflict.ts frontend/src/types/booking.ts
git commit -m "feat: add bookingRequest + conflict types; extend BookingResponse"
```

---

### Task 20: `bookingRequestService`

**Files:**
- Create: `frontend/src/services/bookingRequestService.ts`

- [ ] **Step 1: Write the service**

```typescript
import api from './api'
import type {
  BookingRequestResponse,
  BookingRequestCreatePayload,
  BookingRequestCreateResponse,
  PreviewConflictsResponse,
  EnvBookingSummary,
} from '../types/bookingRequest'

export const bookingRequestService = {
  list: (): Promise<BookingRequestResponse[]> =>
    api.get('/booking-requests').then((r) => r.data),

  get: (id: number): Promise<BookingRequestResponse> =>
    api.get(`/booking-requests/${id}`).then((r) => r.data),

  create: (payload: BookingRequestCreatePayload): Promise<BookingRequestCreateResponse> =>
    api.post('/booking-requests', payload).then((r) => r.data),

  previewConflicts: (args: {
    environment_ids: number[]
    start_date: string
    end_date: string
  }): Promise<PreviewConflictsResponse> =>
    api.post('/booking-requests/preview-conflicts', args).then((r) => r.data),

  updateStandardFields: (
    id: number,
    values: Record<string, unknown>,
  ): Promise<BookingRequestResponse> =>
    api.patch(`/booking-requests/${id}/standard-fields`, values).then((r) => r.data),

  updateCustomFields: (id: number, values: Record<string, unknown>): Promise<BookingRequestResponse> =>
    api.patch(`/booking-requests/${id}/custom-fields`, { values }).then((r) => r.data),

  addEnvironment: (
    id: number,
    args: { environment_id: number; start_date?: string; end_date?: string },
  ): Promise<EnvBookingSummary> =>
    api.post(`/booking-requests/${id}/environments`, args).then((r) => r.data),

  removeEnvironment: (id: number, bookingId: number): Promise<void> =>
    api.delete(`/booking-requests/${id}/environments/${bookingId}`).then((r) => r.data),
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/services/bookingRequestService.ts
git commit -m "feat: add bookingRequestService"
```

---

### Task 21: `bookingRequestSlice`

**Files:**
- Create: `frontend/src/store/bookingRequestSlice.ts`
- Modify: `frontend/src/store/index.ts`

- [ ] **Step 1: Write the slice**

```typescript
import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit'
import { bookingRequestService } from '../services/bookingRequestService'
import type {
  BookingRequestResponse,
  BookingRequestCreatePayload,
  BookingRequestCreateResponse,
} from '../types/bookingRequest'

type State = {
  requests: BookingRequestResponse[]
  loading: boolean
  error: string | null
}

const initialState: State = { requests: [], loading: false, error: null }

export const fetchBookingRequests = createAsyncThunk(
  'bookingRequest/list',
  async () => await bookingRequestService.list(),
)

export const fetchBookingRequest = createAsyncThunk(
  'bookingRequest/get',
  async (id: number) => await bookingRequestService.get(id),
)

export const createBookingRequest = createAsyncThunk(
  'bookingRequest/create',
  async (payload: BookingRequestCreatePayload) => await bookingRequestService.create(payload),
)

export const addEnvironmentToRequest = createAsyncThunk(
  'bookingRequest/addEnv',
  async (args: { id: number; environment_id: number; start_date?: string; end_date?: string }) =>
    await bookingRequestService.addEnvironment(args.id, {
      environment_id: args.environment_id,
      start_date: args.start_date,
      end_date: args.end_date,
    }),
)

export const removeEnvironmentFromRequest = createAsyncThunk(
  'bookingRequest/removeEnv',
  async (args: { id: number; bookingId: number }) => {
    await bookingRequestService.removeEnvironment(args.id, args.bookingId)
    return args
  },
)

export const updateRequestStandardFields = createAsyncThunk(
  'bookingRequest/updateStandard',
  async (args: { id: number; values: Record<string, unknown> }) =>
    await bookingRequestService.updateStandardFields(args.id, args.values),
)

export const updateRequestCustomFields = createAsyncThunk(
  'bookingRequest/updateCustom',
  async (args: { id: number; values: Record<string, unknown> }) =>
    await bookingRequestService.updateCustomFields(args.id, args.values),
)

const slice = createSlice({
  name: 'bookingRequest',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchBookingRequests.pending, (s) => { s.loading = true; s.error = null })
    b.addCase(fetchBookingRequests.fulfilled, (s, a: PayloadAction<BookingRequestResponse[]>) => {
      s.loading = false; s.requests = a.payload
    })
    b.addCase(fetchBookingRequests.rejected, (s, a) => {
      s.loading = false; s.error = a.error.message ?? 'Failed to load'
    })
    b.addCase(createBookingRequest.fulfilled, (s, a: PayloadAction<BookingRequestCreateResponse>) => {
      s.requests.unshift(a.payload.request)
    })
    b.addCase(fetchBookingRequest.fulfilled, (s, a: PayloadAction<BookingRequestResponse>) => {
      const i = s.requests.findIndex((r) => r.id === a.payload.id)
      if (i === -1) s.requests.push(a.payload)
      else s.requests[i] = a.payload
    })
    b.addCase(updateRequestStandardFields.fulfilled, (s, a: PayloadAction<BookingRequestResponse>) => {
      const i = s.requests.findIndex((r) => r.id === a.payload.id)
      if (i !== -1) s.requests[i] = a.payload
    })
    b.addCase(updateRequestCustomFields.fulfilled, (s, a: PayloadAction<BookingRequestResponse>) => {
      const i = s.requests.findIndex((r) => r.id === a.payload.id)
      if (i !== -1) s.requests[i] = a.payload
    })
  },
})

export default slice.reducer
```

- [ ] **Step 2: Register in `store/index.ts`**

Add the import and reducer entry:

```typescript
import bookingRequestReducer from './bookingRequestSlice'
// …inside configureStore reducer object:
bookingRequest: bookingRequestReducer,
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/store/bookingRequestSlice.ts frontend/src/store/index.ts
git commit -m "feat: add bookingRequestSlice"
```

---

### Task 22: Update `bookingService` (remove legacy, add conflicts)

**Files:**
- Modify: `frontend/src/services/bookingService.ts`

- [ ] **Step 1: Remove `approveBooking`, `rejectBooking`, `cancelBooking`, `updateCustomFields`**

Delete those methods. Narrow `updateStandardFields` to send only env-override payloads (the engineer can keep the signature; the API rejects other keys anyway).

- [ ] **Step 2: Add conflict methods**

```typescript
import type { ConflictItem, ConflictAck } from '../types/conflict'

// …append to exports:
  getConflicts: (id: number): Promise<ConflictItem[]> =>
    api.get(`/bookings/${id}/conflicts`).then((r) => r.data),

  acknowledgeConflict: (
    id: number,
    otherId: number,
    payload: { willing_to_share: boolean; notes?: string },
  ): Promise<ConflictAck> =>
    api.put(`/bookings/${id}/conflicts/${otherId}/ack`, payload).then((r) => r.data),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/bookingService.ts
git commit -m "refactor: remove approve/reject/cancel + updateCustomFields; add conflict methods"
```

---

### Task 23: Update `bookingSlice` (remove legacy thunks, add conflict thunks)

**Files:**
- Modify: `frontend/src/store/bookingSlice.ts`

- [ ] **Step 1: Remove `approveBooking`, `rejectBooking`, `cancelBooking` thunks**

Delete the thunks and their reducer cases. Any file still importing them must be updated (covered by Tasks 25–27).

- [ ] **Step 2: Add conflict thunks**

```typescript
import type { ConflictItem } from '../types/conflict'
import { bookingService } from '../services/bookingService'

export const fetchConflicts = createAsyncThunk(
  'booking/fetchConflicts',
  async (id: number) => await bookingService.getConflicts(id),
)

export const acknowledgeConflict = createAsyncThunk(
  'booking/ackConflict',
  async (args: { id: number; otherId: number; willing_to_share: boolean; notes?: string }) => {
    const ack = await bookingService.acknowledgeConflict(args.id, args.otherId, {
      willing_to_share: args.willing_to_share,
      notes: args.notes,
    })
    return { bookingId: args.id, otherId: args.otherId, ack }
  },
)
```

Cache conflicts in the slice keyed by `bookingId` (a `Record<number, ConflictItem[]>` on state). After `acknowledgeConflict.fulfilled`, update the corresponding row's `ack` in that cache.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/store/bookingSlice.ts
git commit -m "refactor: remove approve/reject/cancel thunks; add conflict thunks"
```

---

## Phase 6 — Frontend UI

### Task 24: `EnvironmentPicker`

**Files:**
- Create: `frontend/src/components/bookings/EnvironmentPicker.tsx`

- [ ] **Step 1: Component**

```typescript
import { Autocomplete, Chip, TextField } from '@mui/material'
import type { Environment } from '../../types/environment'

type Props = {
  environments: Environment[]
  value: number[]
  onChange: (ids: number[]) => void
  disabled?: boolean
  label?: string
}

export default function EnvironmentPicker({ environments, value, onChange, disabled, label = 'Environments' }: Props) {
  const selected = environments.filter((e) => value.includes(e.id))
  return (
    <Autocomplete
      multiple
      size="small"
      disabled={disabled}
      options={environments}
      getOptionLabel={(e) => e.name}
      value={selected}
      onChange={(_, next) => onChange(next.map((e) => e.id))}
      renderTags={(vals, getTagProps) =>
        vals.map((v, idx) => <Chip key={v.id} label={v.name} size="small" {...getTagProps({ index: idx })} />)
      }
      renderInput={(params) => <TextField {...params} label={label} />}
      isOptionEqualToValue={(o, v) => o.id === v.id}
    />
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/bookings/EnvironmentPicker.tsx
git commit -m "feat: add EnvironmentPicker component"
```

---

### Task 25: `EditEnvOverridesDialog`

**Files:**
- Create: `frontend/src/components/bookings/EditEnvOverridesDialog.tsx`

- [ ] **Step 1: Component**

```typescript
import { useState } from 'react'
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField } from '@mui/material'
import type { BookingResponse } from '../../types/booking'

type Props = {
  open: boolean
  booking: BookingResponse
  onClose: () => void
  onSaved: (updated: BookingResponse) => void
  saver: (payload: { start_date?: string; end_date?: string }) => Promise<BookingResponse>
  onError?: (msg: string) => void
}

export default function EditEnvOverridesDialog({ open, booking, onClose, onSaved, saver, onError }: Props) {
  const [start, setStart] = useState(booking.start_date.slice(0, 10))
  const [end, setEnd] = useState(booking.end_date.slice(0, 10))
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await saver({ start_date: start, end_date: end })
      onSaved(updated)
      onClose()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed'
      onError?.(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Edit Environment Dates</DialogTitle>
      <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <TextField label="Start" type="date" size="small" InputLabelProps={{ shrink: true }} value={start} onChange={(e) => setStart(e.target.value)} />
        <TextField label="End" type="date" size="small" InputLabelProps={{ shrink: true }} value={end} onChange={(e) => setEnd(e.target.value)} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      </DialogActions>
    </Dialog>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/bookings/EditEnvOverridesDialog.tsx
git commit -m "feat: add EditEnvOverridesDialog"
```

---

### Task 26: `EnvironmentsPanel`

**Files:**
- Create: `frontend/src/components/bookings/EnvironmentsPanel.tsx`

- [ ] **Step 1: Component**

```typescript
import { useEffect, useState } from 'react'
import {
  Box, Button, Chip, IconButton, Paper, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import { Link as RouterLink } from 'react-router-dom'
import { bookingService } from '../../services/bookingService'
import type { EnvBookingSummary } from '../../types/bookingRequest'
import type { AllowedTransition } from '../../types/bookingLifecycle'
import TransitionButtons from './TransitionButtons'

type Props = {
  requestId: number
  envBookings: EnvBookingSummary[]
  highlightBookingId?: number
  onTransition: (bookingId: number, toState: string, label: string) => void
  onRemove: (bookingId: number) => void
  onAddClick: () => void
}

export default function EnvironmentsPanel({
  requestId: _requestId, envBookings, highlightBookingId, onTransition, onRemove, onAddClick,
}: Props) {
  const [transitionsByBooking, setTransitionsByBooking] = useState<Record<number, AllowedTransition[]>>({})

  useEffect(() => {
    // Preload allowed transitions for each env booking on mount
    let cancelled = false
    const load = async () => {
      const out: Record<number, AllowedTransition[]> = {}
      for (const b of envBookings) {
        out[b.id] = await bookingService.getAllowedTransitions(b.id)
      }
      if (!cancelled) setTransitionsByBooking(out)
    }
    load()
    return () => { cancelled = true }
  }, [envBookings])

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>Environments</Typography>
        <Button size="small" onClick={onAddClick}>+ Add Environment</Button>
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Environment</TableCell>
            <TableCell>Start</TableCell>
            <TableCell>End</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Actions</TableCell>
            <TableCell />
          </TableRow>
        </TableHead>
        <TableBody>
          {envBookings.map((b) => (
            <TableRow key={b.id} sx={b.id === highlightBookingId ? { bgcolor: 'action.hover' } : undefined}>
              <TableCell>
                <RouterLink to={`/bookings/${b.id}`}>{b.environment_name ?? `#${b.environment_id}`}</RouterLink>
              </TableCell>
              <TableCell>{new Date(b.start_date).toLocaleDateString()}</TableCell>
              <TableCell>{new Date(b.end_date).toLocaleDateString()}</TableCell>
              <TableCell><Chip size="small" label={b.status} /></TableCell>
              <TableCell>
                <TransitionButtons
                  transitions={transitionsByBooking[b.id] ?? []}
                  onTransition={(to, label) => onTransition(b.id, to, label)}
                />
              </TableCell>
              <TableCell>
                <IconButton size="small" onClick={() => onRemove(b.id)}><DeleteIcon fontSize="small" /></IconButton>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Paper>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/bookings/EnvironmentsPanel.tsx
git commit -m "feat: add EnvironmentsPanel component"
```

---

### Task 27: `ConflictsPanel`

**Files:**
- Create: `frontend/src/components/bookings/ConflictsPanel.tsx`

- [ ] **Step 1: Component**

```typescript
import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, FormControlLabel, Paper, TextField, Typography,
} from '@mui/material'
import { bookingService } from '../../services/bookingService'
import type { ConflictItem } from '../../types/conflict'

type Props = {
  bookingId: number
  canAcknowledge: boolean
}

export default function ConflictsPanel({ bookingId, canAcknowledge }: Props) {
  const [items, setItems] = useState<ConflictItem[]>([])
  const [pending, setPending] = useState<Record<number, { willing_to_share: boolean; notes: string }>>({})
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      setItems(await bookingService.getConflicts(bookingId))
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load conflicts')
    }
  }

  useEffect(() => { load() }, [bookingId])

  if (items.length === 0) return null

  const saveAck = async (otherId: number) => {
    const p = pending[otherId] ?? { willing_to_share: false, notes: '' }
    await bookingService.acknowledgeConflict(bookingId, otherId, p)
    await load()
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Typography variant="subtitle2" gutterBottom>Conflicts ({items.length})</Typography>
      {error && <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>{error}</Alert>}
      {items.map((it) => {
        const p = pending[it.other_booking.id] ?? {
          willing_to_share: it.ack?.willing_to_share ?? false,
          notes: it.ack?.notes ?? '',
        }
        return (
          <Box key={it.other_booking.id} sx={{ mb: 2, pb: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="body2">
              Booking #{it.other_booking.id} ({new Date(it.other_booking.start_date).toLocaleDateString()} – {new Date(it.other_booking.end_date).toLocaleDateString()}) — status {it.other_booking.status}
            </Typography>
            <FormControlLabel
              control={
                <Checkbox
                  checked={p.willing_to_share}
                  disabled={!canAcknowledge}
                  onChange={(e) => setPending((s) => ({ ...s, [it.other_booking.id]: { ...p, willing_to_share: e.target.checked } }))}
                />
              }
              label="Willing to share"
            />
            <TextField
              label="Notes" fullWidth size="small" multiline minRows={2}
              value={p.notes}
              disabled={!canAcknowledge}
              onChange={(e) => setPending((s) => ({ ...s, [it.other_booking.id]: { ...p, notes: e.target.value } }))}
            />
            {canAcknowledge && (
              <Button sx={{ mt: 1 }} size="small" variant="contained" onClick={() => saveAck(it.other_booking.id)}>
                Save
              </Button>
            )}
            {it.ack?.acknowledged_at && (
              <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                Last updated {new Date(it.ack.acknowledged_at).toLocaleString()}
              </Typography>
            )}
          </Box>
        )
      })}
    </Paper>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/bookings/ConflictsPanel.tsx
git commit -m "feat: add ConflictsPanel"
```

---

### Task 28: `ConflictIndicator`

**Files:**
- Create: `frontend/src/components/bookings/ConflictIndicator.tsx`

- [ ] **Step 1: Component**

```typescript
import { Tooltip } from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'

type Props = { hasUnacknowledged?: boolean; count?: number }

export default function ConflictIndicator({ hasUnacknowledged, count }: Props) {
  if (!hasUnacknowledged) return null
  const label = count ? `${count} unacknowledged conflicts` : 'Unacknowledged conflicts'
  return (
    <Tooltip title={label}>
      <WarningAmberIcon color="warning" fontSize="small" />
    </Tooltip>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/bookings/ConflictIndicator.tsx
git commit -m "feat: add ConflictIndicator"
```

---

### Task 29: Update `BookingForm` for multi-env + delegates + conflict preview

**Files:**
- Modify: `frontend/src/pages/bookings/BookingForm.tsx`

- [ ] **Step 1: Read existing form, then rewrite**

Read the current `BookingForm.tsx` to understand its props + existing fields. Then:

- Replace single-env `Select` with `EnvironmentPicker` (`environment_ids: number[]`).
- Add a delegate users multi-select (fetch users from existing user admin store / slice; reuse whatever the Tenant user management page uses).
- Rename the `exclusive_use` field's label to "Exclusive use requested" and keep it mapped to `exclusive_use_requested`.
- Swap submit to `bookingRequestService.create(...)`; on success, navigate to the first child's detail page (or the request itself — engineer's choice; prefer child so user sees env context).
- Add a debounced conflict preview panel: after env selection or date change, call `bookingRequestService.previewConflicts`; if `conflicts[envId]` is non-empty for any selected env, render an `<Alert severity="warning">` listing the conflicting bookings with a "you can proceed; conflicts will require acknowledgements after creation" hint.

- [ ] **Step 2: Manual verification**

- Create a request with 2 envs and no existing overlap → 2 child bookings appear in the list.
- Create a request with 1 env overlapping an existing booking → conflict preview shows; submit succeeds; detail page shows unacknowledged conflict indicator.
- Add a delegate user → request payload includes `delegate_user_ids`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/bookings/BookingForm.tsx
git commit -m "feat: BookingForm supports multi-env, delegates, conflict preview"
```

---

### Task 30: Update `BookingCalendar` drawer

**Files:**
- Modify: `frontend/src/pages/bookings/BookingCalendar.tsx`

- [ ] **Step 1: Replace drawer internals**

- Remove `handleApprove`, `handleReject`, `handleCancel`, `canApproveReject`, `canCancel`, and the Snackbar block that reported outcomes of those actions.
- On event click, in addition to `setSelectedBooking`, fetch `bookingService.getAllowedTransitions(id)` and store in a new state `selectedTransitions`.
- Render `TransitionButtons` inside the drawer using those transitions. `onTransition` calls `bookingService.transitionState`, refetches the booking + transitions, and refreshes calendar events.
- Event title format: if the backend provides `request` + `environment_name`, show `${request.project_name} — ${environment_name}`.
- Keep the "View full details" link → `/bookings/:id`.

- [ ] **Step 2: Manual verification**

Click an event → drawer shows transitions dynamically; clicking a transition updates the event without page reload.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/bookings/BookingCalendar.tsx
git commit -m "feat: BookingCalendar drawer uses dynamic lifecycle transitions"
```

---

### Task 31: Update `BookingList` — per-row kebab + conflict column + remove bulk bar

**Files:**
- Modify: `frontend/src/pages/bookings/BookingList.tsx`

- [ ] **Step 1: Rewrite**

- Remove `checkboxSelection`, `rowSelectionModel` state, bulk toolbar block (`BookingList.tsx:255-304`), `handleBulkApprove`, `handleBulkReject`, `isBulkLoading`, related imports (`CheckIcon`, `CloseIcon`).
- Add a new `conflicts` column (non-hideable) rendering `<ConflictIndicator hasUnacknowledged={row.has_unacknowledged_conflicts} />`.
- Add a new `actions` column with a kebab `IconButton`. On menu open, lazily call `bookingService.getAllowedTransitions(row.id)` once; cache results in component state keyed by row id. Menu items: "Open" (navigates via `useNavigate`), divider, then one `MenuItem` per allowed transition. Selecting a transition calls `bookingService.transitionState(row.id, toState)` and refreshes that row via `bookingService.getBooking(row.id)`.
- Leave filter chips / existing columns otherwise intact.

- [ ] **Step 2: Manual verification**

- Row kebab → "Open" navigates; a transition item triggers transition and updates the row in place.
- The row shows a warning icon when there's an unacknowledged conflict.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/bookings/BookingList.tsx
git commit -m "feat: BookingList inline per-row kebab + conflict indicator"
```

---

### Task 32: Restructure `BookingDetail`

**Files:**
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx`

- [ ] **Step 1: Add request context section**

At the top of the render, between the Back button and the existing status chip row, add:

```tsx
{booking.request && (
  <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Typography variant="h6">{booking.request.project_name}</Typography>
      <ConflictIndicator hasUnacknowledged={booking.has_unacknowledged_conflicts} />
      <Box sx={{ flexGrow: 1 }} />
      {/* Edit request-level standard fields */}
      <Button size="small" onClick={() => setEditingStandardFields(true)}>Edit request</Button>
    </Box>
  </Paper>
)}
```

- [ ] **Step 2: Render `EnvironmentsPanel`**

After the request context section:

```tsx
{bookingRequest && (
  <EnvironmentsPanel
    requestId={bookingRequest.id}
    envBookings={bookingRequest.bookings}
    highlightBookingId={booking.id}
    onTransition={async (id, toState, label) => {
      const notes = toState === 'draft' ? (window.prompt(`Reason for "${label}":`) ?? undefined) : undefined
      await bookingService.transitionState(id, toState, notes)
      const req = await bookingRequestService.get(bookingRequest.id)
      setBookingRequest(req)
      if (id === booking.id) {
        const b = await bookingService.getBooking(id)
        setBooking(b)
      }
    }}
    onRemove={async (id) => {
      await bookingRequestService.removeEnvironment(bookingRequest.id, id)
      const req = await bookingRequestService.get(bookingRequest.id)
      setBookingRequest(req)
    }}
    onAddClick={() => setAddEnvOpen(true)}
  />
)}
```

Add state `bookingRequest` (`BookingRequestResponse | null`) and `addEnvOpen` (`boolean`). After initial load, fetch the request via `bookingRequestService.get(booking.booking_request_id!)`.

- [ ] **Step 3: Wire `EditStandardFieldsDialog` to the request**

Change the existing `EditStandardFieldsDialog` saver to call `bookingRequestService.updateStandardFields(bookingRequest.id, payload)`. After save, refresh the local `bookingRequest` state and re-fetch the booking if its dual-mirror fields changed.

- [ ] **Step 4: Wire `EditCustomFieldsDialog` to the request**

Change its saver to `bookingRequestService.updateCustomFields(bookingRequest.id, values)`. After save refresh `bookingRequest`.

- [ ] **Step 5: Wire `EditEnvOverridesDialog`**

Use it for the per-env "edit dates" action. `saver` calls `bookingService.updateStandardFields(booking.id, { start_date, end_date })`.

- [ ] **Step 6: Render `ConflictsPanel`**

Add:

```tsx
<ConflictsPanel
  bookingId={booking.id}
  canAcknowledge={
    Boolean(currentUser) && (
      currentUser.id === bookingRequest?.booked_by ||
      (bookingRequest?.delegate_user_ids ?? []).includes(currentUser.id)
    )
  }
/>
```

Fetch `currentUser` from `state.auth.user`.

- [ ] **Step 7: "Add environment" dialog**

Minimal inline dialog: single `EnvironmentPicker` (actually a single-select is enough — filter out envs already in the request) plus optional date overrides. On confirm call `bookingRequestService.addEnvironment` and refresh.

- [ ] **Step 8: Manual verification**

- Detail page shows request name + env panel + this env highlighted.
- Edit request name → saves at request level, cascades.
- Edit env dates → saves only for this env.
- Add another env → appears in panel; remove it → disappears.
- Unack conflicts show indicator; ack via ConflictsPanel clears it after save.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/bookings/BookingDetail.tsx
git commit -m "feat: BookingDetail shows request context, EnvironmentsPanel, ConflictsPanel"
```

---

## Phase 7 — Cleanup + migration step 2

### Task 33: Remove dual-read shim + legacy duplicated columns

**Files:**
- Modify: `backend/app/services/booking_service.py`
- Modify: `backend/app/db/models/booking.py`
- Create: `backend/app/db/migrations/versions/<new>_drop_booking_legacy_columns.py`

- [ ] **Step 1: Remove `_effective_shared` helper**

In `booking_service.py`, delete `_effective_shared` and replace every caller with direct reads from the parent `BookingRequest` (loaded via relationship or explicit query). The request is guaranteed present because we're about to flip `booking_request_id` to NOT NULL.

- [ ] **Step 2: Remove duplicated columns from the model**

In `backend/app/db/models/booking.py`, delete: `project_name`, `booking_type_id`, `notes`, `exclusive_use`, `context_tag`, `custom_fields`, `booked_by` (and their relationships / `booking_type_ref`). Update `booker` / `booking_type_ref` references in `booking_service` to go via `booking.booking_request.booked_by` / `.booking_type_id`.

- [ ] **Step 3: Alembic migration Step 2**

Generate an empty revision:

```bash
cd backend && alembic revision -m "drop legacy columns from booking; NOT NULL on booking_request_id"
```

Write:

```python
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.alter_column("booking", "booking_request_id", nullable=False)
    op.drop_column("booking", "project_name")
    op.drop_column("booking", "booking_type_id")
    op.drop_column("booking", "notes")
    op.drop_column("booking", "exclusive_use")
    op.drop_column("booking", "context_tag")
    op.drop_column("booking", "custom_fields")
    op.drop_column("booking", "booked_by")


def downgrade() -> None:
    op.add_column("booking", sa.Column("booked_by", sa.Integer, sa.ForeignKey("user.id"), nullable=True))
    op.add_column("booking", sa.Column("custom_fields", sa.JSON, nullable=True))
    op.add_column("booking", sa.Column("context_tag", sa.String(50), nullable=False, server_default="none"))
    op.add_column("booking", sa.Column("exclusive_use", sa.Boolean, nullable=False, server_default=sa.text("false")))
    op.add_column("booking", sa.Column("notes", sa.Text, nullable=True))
    op.add_column("booking", sa.Column("booking_type_id", sa.Integer, sa.ForeignKey("booking_type.id"), nullable=True))
    op.add_column("booking", sa.Column("project_name", sa.String(200), nullable=True))
    op.alter_column("booking", "booking_request_id", nullable=True)
```

- [ ] **Step 4: Apply and run the full test suite**

```bash
cd backend && alembic upgrade head && uv run pytest -v
```

Expected: migration applies cleanly; every test passes.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/booking_service.py backend/app/db/models/booking.py backend/app/db/migrations/versions/*_drop_booking_legacy_columns.py
git commit -m "refactor: drop legacy booking columns; booking_request_id NOT NULL"
```

---

### Task 34: Final manual verification sweep

- [ ] **Step 1: Run everything**

```bash
docker-compose up -d
cd backend && alembic upgrade head
cd backend && uv run pytest -v
cd backend && uv run uvicorn app.main:app --reload &
cd frontend && npm run dev
```

- [ ] **Step 2: End-to-end scenarios**

Walk through each, confirming no console errors and the UI behaves as described:

1. Log in as a Developer (`admin` / `admin123` in demo tenant).
2. Create a booking request selecting 3 environments for the same window. Confirm 3 rows appear in `/bookings/list`.
3. Open one env row via its kebab → trigger `Submit` transition → row status updates in place; sibling rows are unaffected.
4. As an Admin / Release Manager, approve one env and reject another within the same request. Each transition is independent.
5. Create a second request overlapping the first on one env. Confirm:
   - The `BookingForm` preview shows conflicts before submit.
   - After submit, both bookings' rows in the list show the `ConflictIndicator`.
6. Open the detail page of the new booking → `ConflictsPanel` shows the sibling; tick "willing to share" + add notes → save. Indicator clears for this side. The other booking's indicator stays until its owner ack's.
7. Calendar: click an event → drawer shows dynamic transitions for that env; clicking "Approve" updates the event colour.
8. Add a delegate user to a request. Log in as delegate → visit the request detail → confirm ConflictsPanel form is editable for you.
9. Remove an env from a request from the detail page → it disappears from `EnvironmentsPanel` and from the list.

- [ ] **Step 3: Housekeeping commit**

If anything needed tweaks, commit those with a short message. Otherwise, no commit needed.

---

## Self-review notes

**Spec coverage:**
- Soft conflicts + acks with delegate support → Tasks 5–6, 13–14, 27.
- `booking_request` parent with dual-write to children during migration → Tasks 1–4, 7–11, 33.
- Multi-env creation with conflict preview → Tasks 7, 8, 13, 29.
- Add/remove env on existing request → Tasks 9, 13, 32.
- Request-level edits (standard + custom) cascading → Tasks 10, 13, 17–18, 20, 32.
- Inline dynamic transitions everywhere → Tasks 16, 30, 31, 32.
- Removal of `/approve` `/reject` `/cancel` — backend + frontend → Tasks 11, 15, 22, 23.
- List conflict indicator → Tasks 15 (backend `has_unacknowledged_conflicts`), 28, 31.

**Placeholder scan clean** — no "TBD"; each task has runnable code / commands; where service shapes depend on existing patterns (e.g. `publish_event` signature, `get_allowed_transitions`), the plan notes "match existing" and points at the reference file.

**Type consistency** — `AllowedTransition` and `BookingResponse` used consistently; `BookingRequestResponse.bookings` matches `EnvBookingSummary` shape; `ConflictItem.ack` is nullable everywhere.
