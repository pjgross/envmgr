# Booking Lifecycle & Booking Types — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin-configurable booking types with reusable JSONB lifecycle templates, role-gated state transitions, field-level permissions per state, and a full audit trail to the booking system.

**Architecture:** Three new DB tables (`booking_lifecycle_templates`, `booking_types`, `booking_status_history`) plus changes to the `booking` table. Lifecycle templates store states/transitions/field-permissions as validated JSONB — always consumed as a whole, atomic updates propagate to all booking types referencing a template. A central `transition_state()` service method validates role+lifecycle and writes history. Existing `/approve` and `/reject` endpoints become shortcuts to `transition_state`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL + Pydantic v2 (backend); pytest-asyncio + in-memory SQLite (tests); React 18 + TypeScript + MUI DataGrid + Redux Toolkit (frontend).

---

## File Map

### New Backend Files
| File | Purpose |
|------|---------|
| `backend/app/db/models/booking_lifecycle.py` | SQLAlchemy models: BookingLifecycleTemplate, BookingType, BookingStatusHistory |
| `backend/app/api/v1/schemas/booking_lifecycle.py` | Pydantic: LifecycleDefinition + request/response schemas |
| `backend/app/services/booking_lifecycle_service.py` | Template/type CRUD + validate_transition, get_allowed_transitions, get_editable_fields |
| `backend/app/services/booking_type_service.py` | Booking type CRUD |
| `backend/app/api/v1/booking_lifecycle.py` | Tenant-admin API: lifecycle templates + booking types (mounted at `/api/v1/tenant/`) |
| `backend/app/db/migrations/versions/<ts>_add_booking_lifecycle.py` | Alembic migration |
| `backend/tests/test_booking_lifecycle.py` | Integration tests |

### Modified Backend Files
| File | Changes |
|------|---------|
| `backend/app/db/models/booking.py` | Remove BookingType enum; add `exclusive_use` bool, `booking_type_id` FK; change `status` to `String` |
| `backend/app/api/v1/schemas/booking.py` | Update BookingCreate (add booking_type_id, exclusive_use; remove booking_type), update BookingResponse |
| `backend/app/services/booking_service.py` | Add `transition_state()`, `get_status_history()`; update create/approve/reject/update |
| `backend/app/api/v1/bookings.py` | Add /transition, /history, /allowed-transitions endpoints |
| `backend/app/main.py` | Register new booking_lifecycle router |
| `backend/tests/test_bookings.py` | Fix tests broken by model/schema changes |

### New Frontend Files
| File | Purpose |
|------|---------|
| `frontend/src/types/bookingLifecycle.ts` | TypeScript types for lifecycle templates, booking types, history |
| `frontend/src/services/bookingLifecycleService.ts` | API client for lifecycle templates and booking types |
| `frontend/src/store/bookingLifecycleSlice.ts` | Redux slice |
| `frontend/src/pages/admin/BookingConfiguration.tsx` | Admin settings page |

### Modified Frontend Files
| File | Changes |
|------|---------|
| `frontend/src/types/booking.ts` | Update status type to string; add BookingStatusHistory; remove BookingTypeEnum |
| `frontend/src/services/bookingService.ts` | Add transitionState(), getHistory(), getAllowedTransitions() |
| `frontend/src/pages/BookingForm.tsx` | Add booking type dropdown, exclusive_use toggle |
| `frontend/src/pages/BookingDetail.tsx` | Add state badge, dynamic action buttons, history timeline |

---

## Task 1: New SQLAlchemy Models

**Files:**
- Create: `backend/app/db/models/booking_lifecycle.py`

- [ ] **Step 1: Create the models file**

```python
# backend/app/db/models/booking_lifecycle.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BookingLifecycleTemplate(Base):
    __tablename__ = "booking_lifecycle_template"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Use JSON for SQLite compat in tests; PostgreSQL uses JSONB via migration DDL
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    booking_types: Mapped[list["BookingType"]] = relationship(
        "BookingType", back_populates="lifecycle_template"
    )


class BookingType(Base):
    __tablename__ = "booking_type"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lifecycle_template_id: Mapped[int] = mapped_column(
        ForeignKey("booking_lifecycle_template.id"), nullable=False, index=True
    )
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    lifecycle_template: Mapped["BookingLifecycleTemplate"] = relationship(
        "BookingLifecycleTemplate", back_populates="booking_types"
    )


class BookingStatusHistory(Base):
    __tablename__ = "booking_status_history"

    booking_id: Mapped[int] = mapped_column(ForeignKey("booking.id"), nullable=False, index=True)
    from_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    to_state: Mapped[str] = mapped_column(String(100), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # No deleted_at — history rows are immutable audit records
```

> **Note:** `JSON` type is used instead of `JSONB` in the ORM model so SQLite (used in tests) works. The Alembic migration uses `JSONB` for PostgreSQL.

- [ ] **Step 2: Add models to `__init__.py` so `Base.metadata.create_all` finds them**

In `backend/app/db/models/__init__.py` (or wherever models are imported), add:
```python
from app.db.models.booking_lifecycle import BookingLifecycleTemplate, BookingType, BookingStatusHistory
```

Run `grep -r "from app.db.models" backend/app/db/base.py backend/app/db/models/__init__.py` to find the right place, then add the import.

- [ ] **Step 3: Verify models are loadable**

```bash
cd backend && python -c "from app.db.models.booking_lifecycle import BookingLifecycleTemplate, BookingType, BookingStatusHistory; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/booking_lifecycle.py backend/app/db/models/__init__.py
git commit -m "feat: add BookingLifecycleTemplate, BookingType, BookingStatusHistory models"
```

---

## Task 2: Pydantic Schemas for Lifecycle Definition

**Files:**
- Create: `backend/app/api/v1/schemas/booking_lifecycle.py`

- [ ] **Step 1: Write the schemas**

```python
# backend/app/api/v1/schemas/booking_lifecycle.py
from typing import Optional
from pydantic import BaseModel, field_validator


# ── JSONB definition sub-schemas ────────────────────────────────────────────

VALID_FIELD_NAMES = {
    "project_name", "start_date", "end_date", "notes", "exclusive_use", "custom_fields"
}

VALID_ROLES = {"Admin", "ReleaseManager", "User"}


class LifecycleState(BaseModel):
    key: str
    label: str
    is_initial: bool = False
    is_terminal: bool = False


class LifecycleTransition(BaseModel):
    from_state: str
    to_state: str
    label: str
    allowed_roles: list[str]

    @field_validator("allowed_roles")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}. Must be one of {VALID_ROLES}")
        return v


class LifecycleFieldPermission(BaseModel):
    editable_fields: list[str]
    editable_by: list[str]

    @field_validator("editable_fields")
    @classmethod
    def validate_fields(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_FIELD_NAMES
        if invalid:
            raise ValueError(f"Invalid field names: {invalid}. Must be one of {VALID_FIELD_NAMES}")
        return v

    @field_validator("editable_by")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}")
        return v


class LifecycleDefinition(BaseModel):
    states: list[LifecycleState]
    transitions: list[LifecycleTransition]
    field_permissions: dict[str, LifecycleFieldPermission]

    @field_validator("states")
    @classmethod
    def validate_one_initial(cls, v: list[LifecycleState]) -> list[LifecycleState]:
        initial = [s for s in v if s.is_initial]
        if len(initial) != 1:
            raise ValueError("Exactly one state must have is_initial=True")
        return v


# ── Request/Response schemas ─────────────────────────────────────────────────

class LifecycleTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = False
    definition: LifecycleDefinition


class LifecycleTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    definition: Optional[LifecycleDefinition] = None


class LifecycleTemplateCopy(BaseModel):
    name: str


class LifecycleTemplateResponse(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    is_default: bool
    definition: dict
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class BookingTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    lifecycle_template_id: int
    color: Optional[str] = None
    is_active: bool = True


class BookingTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    lifecycle_template_id: Optional[int] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


class BookingTypeResponse(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    lifecycle_template_id: int
    color: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Verify schemas import cleanly**

```bash
cd backend && python -c "from app.api.v1.schemas.booking_lifecycle import LifecycleDefinition, BookingTypeResponse; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/schemas/booking_lifecycle.py
git commit -m "feat: add Pydantic schemas for lifecycle definition and booking types"
```

---

## Task 3: Alembic Migration

**Files:**
- Create: `backend/app/db/migrations/versions/<ts>_add_booking_lifecycle.py`

Generate the file first, then write DDL manually:

- [ ] **Step 1: Generate empty migration**

```bash
cd backend && alembic revision -m "add_booking_lifecycle"
```
Note the generated filename (e.g. `20260325_1000_abc123_add_booking_lifecycle.py`).

- [ ] **Step 2: Write the upgrade() function**

```python
def upgrade() -> None:
    # 1. Create booking_lifecycle_template table
    op.create_table(
        "booking_lifecycle_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booking_lifecycle_template_id", "booking_lifecycle_template", ["id"])
    op.create_index("ix_booking_lifecycle_template_tenant_id", "booking_lifecycle_template", ["tenant_id"])

    # 2. Create booking_type table
    op.create_table(
        "booking_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lifecycle_template_id", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["lifecycle_template_id"], ["booking_lifecycle_template.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booking_type_id", "booking_type", ["id"])
    op.create_index("ix_booking_type_tenant_id", "booking_type", ["tenant_id"])
    op.create_index("ix_booking_type_lifecycle_template_id", "booking_type", ["lifecycle_template_id"])

    # 3. Create booking_status_history table
    op.create_table(
        "booking_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(100), nullable=True),
        sa.Column("to_state", sa.String(100), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["booking.id"]),
        sa.ForeignKeyConstraint(["changed_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booking_status_history_id", "booking_status_history", ["id"])
    op.create_index("ix_booking_status_history_booking_id", "booking_status_history", ["booking_id"])

    # 4. Add new columns to booking (nullable first for backfill)
    op.add_column("booking", sa.Column("exclusive_use", sa.Boolean(), nullable=True))
    op.add_column("booking", sa.Column("booking_type_id", sa.Integer(), nullable=True))
    op.add_column("booking", sa.Column("status_new", sa.String(100), nullable=True))
    op.create_index("ix_booking_booking_type_id", "booking", ["booking_type_id"])

    # 5. Seed default lifecycle template per tenant
    # Using raw SQL for the seed so it runs inside the migration transaction
    op.execute("""
        INSERT INTO booking_lifecycle_template (tenant_id, name, is_default, definition, created_at, updated_at)
        SELECT
            t.id,
            'Default Lifecycle',
            true,
            '{
                "states": [
                    {"key": "draft", "label": "Draft", "is_initial": true, "is_terminal": false},
                    {"key": "submitted", "label": "Submitted", "is_initial": false, "is_terminal": false},
                    {"key": "approved", "label": "Approved", "is_initial": false, "is_terminal": false},
                    {"key": "rejected", "label": "Rejected", "is_initial": false, "is_terminal": true},
                    {"key": "extension_requested", "label": "Extension Request", "is_initial": false, "is_terminal": false},
                    {"key": "closed", "label": "Closed", "is_initial": false, "is_terminal": true}
                ],
                "transitions": [
                    {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin", "ReleaseManager", "User"]},
                    {"from_state": "submitted", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "submitted", "to_state": "rejected", "label": "Reject", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "approved", "to_state": "extension_requested", "label": "Request Extension", "allowed_roles": ["Admin", "ReleaseManager", "User"]},
                    {"from_state": "extension_requested", "to_state": "approved", "label": "Approve Extension", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "extension_requested", "to_state": "rejected", "label": "Reject Extension", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "approved", "to_state": "closed", "label": "Close", "allowed_roles": ["Admin", "ReleaseManager"]}
                ],
                "field_permissions": {
                    "draft": {"editable_fields": ["project_name", "start_date", "end_date", "notes", "exclusive_use", "custom_fields"], "editable_by": ["Admin", "ReleaseManager", "User"]},
                    "submitted": {"editable_fields": ["notes"], "editable_by": ["Admin", "ReleaseManager"]},
                    "approved": {"editable_fields": ["notes"], "editable_by": ["Admin", "ReleaseManager"]},
                    "rejected": {"editable_fields": [], "editable_by": []},
                    "extension_requested": {"editable_fields": ["notes", "end_date"], "editable_by": ["Admin", "ReleaseManager"]},
                    "closed": {"editable_fields": [], "editable_by": []}
                }
            }'::jsonb,
            now(),
            now()
        FROM tenant t
        WHERE t.id NOT IN (SELECT tenant_id FROM booking_lifecycle_template)
    """)

    # 6. Seed default booking type per tenant
    op.execute("""
        INSERT INTO booking_type (tenant_id, name, lifecycle_template_id, is_active, created_at, updated_at)
        SELECT
            blt.tenant_id,
            'Standard Booking',
            blt.id,
            true,
            now(),
            now()
        FROM booking_lifecycle_template blt
        WHERE blt.is_default = true
          AND blt.tenant_id NOT IN (SELECT tenant_id FROM booking_type)
    """)

    # 7. Backfill booking.exclusive_use (EXCLUSIVE -> true, SHARED -> false)
    op.execute("""
        UPDATE booking
        SET exclusive_use = CASE WHEN booking_type = 'exclusive' THEN true ELSE false END
        WHERE exclusive_use IS NULL
    """)

    # 8. Backfill booking.booking_type_id with default type for each tenant
    op.execute("""
        UPDATE booking b
        SET booking_type_id = bt.id
        FROM booking_type bt
        WHERE bt.tenant_id = b.tenant_id
          AND bt.name = 'Standard Booking'
          AND b.booking_type_id IS NULL
    """)

    # 9. Backfill booking.status_new mapping old status values
    op.execute("""
        UPDATE booking
        SET status_new = CASE
            WHEN status = 'pending'  THEN 'submitted'
            WHEN status = 'approved' THEN 'approved'
            WHEN status = 'rejected' THEN 'rejected'
            ELSE status
        END
        WHERE status_new IS NULL
    """)

    # 10. Seed booking_status_history (one row per existing booking)
    op.execute("""
        INSERT INTO booking_status_history (booking_id, from_state, to_state, changed_by, changed_at, created_at, updated_at)
        SELECT
            b.id,
            NULL,
            b.status_new,
            b.booked_by,
            b.created_at,
            now(),
            now()
        FROM booking b
        WHERE b.deleted_at IS NULL
    """)

    # 11. Make new columns NOT NULL and drop old columns
    op.alter_column("booking", "exclusive_use", nullable=False, server_default=sa.text("false"))
    op.alter_column("booking", "booking_type_id", nullable=False)

    # Rename status_new -> status: drop old status column, rename new one
    op.drop_column("booking", "status")
    op.alter_column("booking", "status_new", new_column_name="status")
    op.alter_column("booking", "status", nullable=False)

    # Drop booking_type column (replaced by exclusive_use + booking_type_id)
    # Note: verify the actual index name first: in psql run `\d booking` and look for an index on booking_type.
    # Use if_exists=True to prevent migration failure if the index name differs.
    try:
        op.drop_index("ix_booking_booking_type", table_name="booking")
    except Exception:
        pass  # Index may not exist or have a different name — safe to continue
    op.drop_column("booking", "booking_type")

    # Add FK constraint for booking_type_id
    op.create_foreign_key(
        "fk_booking_booking_type_id", "booking", "booking_type",
        ["booking_type_id"], ["id"]
    )
```

- [ ] **Step 3: Write the downgrade() function**

```python
def downgrade() -> None:
    op.drop_constraint("fk_booking_booking_type_id", "booking", type_="foreignkey")
    op.add_column("booking", sa.Column("booking_type", sa.String(), nullable=True))
    op.execute("UPDATE booking SET booking_type = CASE WHEN exclusive_use THEN 'exclusive' ELSE 'shared' END")
    op.alter_column("booking", "booking_type", nullable=False)

    op.add_column("booking", sa.Column("status_old", sa.String(), nullable=True))
    op.execute("""
        UPDATE booking SET status_old = CASE
            WHEN status = 'submitted' THEN 'pending'
            WHEN status = 'approved' THEN 'approved'
            WHEN status = 'rejected' THEN 'rejected'
            ELSE 'pending'
        END
    """)
    op.drop_column("booking", "status")
    op.alter_column("booking", "status_old", new_column_name="status")
    op.alter_column("booking", "status", nullable=False, server_default=sa.text("'pending'"))

    op.drop_index("ix_booking_booking_type_id", table_name="booking")
    op.drop_column("booking", "booking_type_id")
    op.drop_column("booking", "exclusive_use")

    op.drop_index("ix_booking_status_history_booking_id", table_name="booking_status_history")
    op.drop_table("booking_status_history")
    op.drop_index("ix_booking_type_lifecycle_template_id", table_name="booking_type")
    op.drop_table("booking_type")
    op.drop_index("ix_booking_lifecycle_template_tenant_id", table_name="booking_lifecycle_template")
    op.drop_table("booking_lifecycle_template")
```

Add the required imports at the top of the migration file:
```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
```

- [ ] **Step 4: Run migration**

```bash
cd backend && alembic upgrade head
```
Expected: No errors, migration completes.

- [ ] **Step 5: Verify new tables and backfill**

```bash
cd backend && python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os

async def check():
    url = os.environ.get('DATABASE_URL', 'postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr')
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        r = await conn.execute(text('SELECT COUNT(*) FROM booking_lifecycle_template'))
        print('templates:', r.scalar())
        r = await conn.execute(text('SELECT COUNT(*) FROM booking_type'))
        print('types:', r.scalar())
        r = await conn.execute(text('SELECT COUNT(*) FROM booking_status_history'))
        print('history rows:', r.scalar())

asyncio.run(check())
"
```
Expected: templates ≥ 1, types ≥ 1, history rows ≥ 0.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/migrations/versions/
git commit -m "feat: add migration for booking lifecycle, types, and status history"
```

---

## Task 4: BookingLifecycleService

**Files:**
- Create: `backend/app/services/booking_lifecycle_service.py`
- Create: `backend/tests/test_booking_lifecycle.py` (tests written first)

- [ ] **Step 1: Write failing tests for validate_transition and get_allowed_transitions**

```python
# backend/tests/test_booking_lifecycle.py
import pytest
from httpx import AsyncClient


DEFAULT_DEFINITION = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin", "ReleaseManager", "User"]},
        {"from_state": "submitted", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "submitted", "to_state": "rejected", "label": "Reject", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "submitted", "to_state": "draft", "label": "Return", "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft": {"editable_fields": ["project_name", "notes"], "editable_by": ["Admin", "ReleaseManager", "User"]},
        "submitted": {"editable_fields": ["notes"], "editable_by": ["Admin", "ReleaseManager"]},
        "approved": {"editable_fields": [], "editable_by": []},
        "rejected": {"editable_fields": [], "editable_by": []},
    }
}


@pytest.mark.asyncio
async def test_create_lifecycle_template(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Test Lifecycle", "definition": DEFAULT_DEFINITION},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Test Lifecycle"
    assert data["tenant_id"] is not None


@pytest.mark.asyncio
async def test_update_template_propagates(client: AsyncClient, auth_headers: dict):
    """Updating a template is reflected on booking types that reference it."""
    t_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Propagation Test", "definition": DEFAULT_DEFINITION},
    )
    template_id = t_resp.json()["id"]

    # Create booking type referencing this template
    bt_resp = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "My Type", "lifecycle_template_id": template_id},
    )
    assert bt_resp.status_code == 201, bt_resp.text

    # Update template name
    upd = await client.put(
        f"/api/v1/tenant/lifecycle-templates/{template_id}",
        headers=auth_headers,
        json={"name": "Updated Name"},
    )
    assert upd.status_code == 200

    # Booking type still references updated template
    bt_get = await client.get(f"/api/v1/tenant/booking-types/{bt_resp.json()['id']}", headers=auth_headers)
    assert bt_get.json()["lifecycle_template_id"] == template_id


@pytest.mark.asyncio
async def test_copy_template_is_independent(client: AsyncClient, auth_headers: dict):
    """Copying a template creates an independent copy — updating the original does not affect the copy."""
    t_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Original", "definition": DEFAULT_DEFINITION},
    )
    original_id = t_resp.json()["id"]

    copy_resp = await client.post(
        f"/api/v1/tenant/lifecycle-templates/{original_id}/copy",
        headers=auth_headers,
        json={"name": "Copy"},
    )
    assert copy_resp.status_code == 201
    copy_id = copy_resp.json()["id"]
    assert copy_id != original_id

    # Update original — copy should still have old name
    await client.put(
        f"/api/v1/tenant/lifecycle-templates/{original_id}",
        headers=auth_headers,
        json={"name": "Original Modified"},
    )
    copy_get = await client.get(f"/api/v1/tenant/lifecycle-templates/{copy_id}", headers=auth_headers)
    assert copy_get.json()["name"] == "Copy"


@pytest.mark.asyncio
async def test_invalid_lifecycle_definition_rejected(client: AsyncClient, auth_headers: dict):
    """Definition with zero initial states is rejected with 422."""
    bad_definition = {**DEFAULT_DEFINITION, "states": [
        {"key": "draft", "label": "Draft", "is_initial": False, "is_terminal": False},
    ]}
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Bad", "definition": bad_definition},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_booking_type(client: AsyncClient, auth_headers: dict):
    t_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "TL", "definition": DEFAULT_DEFINITION},
    )
    resp = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "My Type", "lifecycle_template_id": t_resp.json()["id"], "color": "#FF5733"},
    )
    assert resp.status_code == 201
    assert resp.json()["color"] == "#FF5733"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_booking_lifecycle.py -v 2>&1 | head -30
```
Expected: `ImportError` or `404` errors — endpoints don't exist yet.

- [ ] **Step 3: Implement BookingLifecycleService**

```python
# backend/app/services/booking_lifecycle_service.py
import copy
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.booking_lifecycle import BookingLifecycleTemplate, BookingType
from app.api.v1.schemas.booking_lifecycle import (
    LifecycleDefinition, LifecycleTemplateCreate, LifecycleTemplateUpdate,
)


async def create_template(
    db: AsyncSession, data: LifecycleTemplateCreate, tenant_id: int
) -> BookingLifecycleTemplate:
    # Validate JSONB definition via Pydantic (raises ValidationError -> 422)
    LifecycleDefinition.model_validate(data.definition.model_dump())
    template = BookingLifecycleTemplate(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        is_default=data.is_default,
        definition=data.definition.model_dump(),
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def list_templates(db: AsyncSession, tenant_id: int) -> list[BookingLifecycleTemplate]:
    result = await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.tenant_id == tenant_id,
            BookingLifecycleTemplate.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def get_template(
    db: AsyncSession, template_id: int, tenant_id: int
) -> BookingLifecycleTemplate:
    result = await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.id == template_id,
            BookingLifecycleTemplate.tenant_id == tenant_id,
            BookingLifecycleTemplate.deleted_at.is_(None),
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lifecycle template not found")
    return template


async def update_template(
    db: AsyncSession, template_id: int, data: LifecycleTemplateUpdate, tenant_id: int
) -> BookingLifecycleTemplate:
    template = await get_template(db, template_id, tenant_id)
    if data.name is not None:
        template.name = data.name
    if data.description is not None:
        template.description = data.description
    if data.is_default is not None:
        template.is_default = data.is_default
    if data.definition is not None:
        LifecycleDefinition.model_validate(data.definition.model_dump())
        template.definition = data.definition.model_dump()
    await db.flush()
    await db.refresh(template)
    return template


async def copy_template(
    db: AsyncSession, template_id: int, new_name: str, tenant_id: int
) -> BookingLifecycleTemplate:
    original = await get_template(db, template_id, tenant_id)
    new_template = BookingLifecycleTemplate(
        tenant_id=tenant_id,
        name=new_name,
        description=original.description,
        is_default=False,
        definition=copy.deepcopy(original.definition),
    )
    db.add(new_template)
    await db.flush()
    await db.refresh(new_template)
    return new_template


def validate_transition(definition: dict, from_state: str, to_state: str, user_role: str) -> bool:
    """Return True if the transition is allowed for this role."""
    for t in definition.get("transitions", []):
        if t["from_state"] == from_state and t["to_state"] == to_state:
            return user_role in t["allowed_roles"]
    return False


def get_allowed_transitions(definition: dict, current_state: str, user_role: str) -> list[dict]:
    """Return all transitions from current_state that this role can make."""
    return [
        t for t in definition.get("transitions", [])
        if t["from_state"] == current_state and user_role in t["allowed_roles"]
    ]


def get_editable_fields(definition: dict, current_state: str, user_role: str) -> list[str]:
    """Return fields editable in this state for this role. Fail-closed (empty list) if state not defined."""
    perm = definition.get("field_permissions", {}).get(current_state)
    if not perm:
        return []
    if user_role not in perm.get("editable_by", []):
        return []
    return perm.get("editable_fields", [])
```

- [ ] **Step 4: Implement BookingTypeService**

```python
# backend/app/services/booking_type_service.py
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking_lifecycle import BookingType
from app.api.v1.schemas.booking_lifecycle import BookingTypeCreate, BookingTypeUpdate
from app.services.booking_lifecycle_service import get_template


async def create_type(
    db: AsyncSession, data: BookingTypeCreate, tenant_id: int
) -> BookingType:
    # Verify template belongs to this tenant
    await get_template(db, data.lifecycle_template_id, tenant_id)
    bt = BookingType(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        lifecycle_template_id=data.lifecycle_template_id,
        color=data.color,
        is_active=data.is_active,
    )
    db.add(bt)
    await db.flush()
    await db.refresh(bt)
    return bt


async def list_types(db: AsyncSession, tenant_id: int) -> list[BookingType]:
    result = await db.execute(
        select(BookingType).where(
            BookingType.tenant_id == tenant_id,
            BookingType.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def get_type(db: AsyncSession, type_id: int, tenant_id: int) -> BookingType:
    result = await db.execute(
        select(BookingType).where(
            BookingType.id == type_id,
            BookingType.tenant_id == tenant_id,
            BookingType.deleted_at.is_(None),
        )
    )
    bt = result.scalar_one_or_none()
    if not bt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking type not found")
    return bt


async def update_type(
    db: AsyncSession, type_id: int, data: BookingTypeUpdate, tenant_id: int
) -> BookingType:
    bt = await get_type(db, type_id, tenant_id)
    if data.name is not None:
        bt.name = data.name
    if data.description is not None:
        bt.description = data.description
    if data.lifecycle_template_id is not None:
        await get_template(db, data.lifecycle_template_id, tenant_id)
        bt.lifecycle_template_id = data.lifecycle_template_id
    if data.color is not None:
        bt.color = data.color
    if data.is_active is not None:
        bt.is_active = data.is_active
    await db.flush()
    await db.refresh(bt)
    return bt
```

- [ ] **Step 5: Implement API endpoints**

```python
# backend/app/api/v1/booking_lifecycle.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.services import booking_lifecycle_service, booking_type_service
from app.api.v1.schemas.booking_lifecycle import (
    LifecycleTemplateCreate, LifecycleTemplateUpdate, LifecycleTemplateCopy,
    LifecycleTemplateResponse, BookingTypeCreate, BookingTypeUpdate, BookingTypeResponse,
)

router = APIRouter()


# ── Lifecycle Templates ──────────────────────────────────────────────────────

@router.get("/lifecycle-templates", response_model=list[LifecycleTemplateResponse])
async def list_lifecycle_templates(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_lifecycle_service.list_templates(db, current_user.active_tenant_id)


@router.post("/lifecycle-templates", response_model=LifecycleTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_lifecycle_template(
    data: LifecycleTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_lifecycle_service.create_template(db, data, current_user.active_tenant_id)


@router.get("/lifecycle-templates/{template_id}", response_model=LifecycleTemplateResponse)
async def get_lifecycle_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_lifecycle_service.get_template(db, template_id, current_user.active_tenant_id)


@router.put("/lifecycle-templates/{template_id}", response_model=LifecycleTemplateResponse)
async def update_lifecycle_template(
    template_id: int,
    data: LifecycleTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_lifecycle_service.update_template(db, template_id, data, current_user.active_tenant_id)


@router.post("/lifecycle-templates/{template_id}/copy", response_model=LifecycleTemplateResponse, status_code=status.HTTP_201_CREATED)
async def copy_lifecycle_template(
    template_id: int,
    data: LifecycleTemplateCopy,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_lifecycle_service.copy_template(db, template_id, data.name, current_user.active_tenant_id)


# ── Booking Types ────────────────────────────────────────────────────────────

@router.get("/booking-types", response_model=list[BookingTypeResponse])
async def list_booking_types(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_type_service.list_types(db, current_user.active_tenant_id)


@router.post("/booking-types", response_model=BookingTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_booking_type(
    data: BookingTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_type_service.create_type(db, data, current_user.active_tenant_id)


@router.get("/booking-types/{type_id}", response_model=BookingTypeResponse)
async def get_booking_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_type_service.get_type(db, type_id, current_user.active_tenant_id)


@router.put("/booking-types/{type_id}", response_model=BookingTypeResponse)
async def update_booking_type(
    type_id: int,
    data: BookingTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_type_service.update_type(db, type_id, data, current_user.active_tenant_id)
```

- [ ] **Step 6: Register router in main.py**

In `backend/app/main.py`, add after the existing imports:
```python
from app.api.v1 import booking_lifecycle as booking_lifecycle_router
app.include_router(booking_lifecycle_router.router, prefix="/api/v1/tenant", tags=["Booking Lifecycle"])
```

> **Path convention note:** The codebase uses `/api/v1/admin` for master-admin operations and `/api/v1/tenant` for per-tenant admin operations (see `tenant_admin.py`). These endpoints are per-tenant so they use the `/api/v1/tenant/` prefix. The spec document incorrectly lists them under `/api/v1/admin/` — use `/api/v1/tenant/` as implemented here.

- [ ] **Step 7: Run tests — expect them to pass**

```bash
cd backend && pytest tests/test_booking_lifecycle.py -v
```
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/booking_lifecycle_service.py backend/app/services/booking_type_service.py backend/app/api/v1/booking_lifecycle.py backend/app/main.py backend/tests/test_booking_lifecycle.py
git commit -m "feat: add booking lifecycle template and booking type services and API"
```

---

## Task 5: Update Booking Model

**Files:**
- Modify: `backend/app/db/models/booking.py`

- [ ] **Step 1: Update the model**

In `backend/app/db/models/booking.py`:

1. Remove `BookingType` enum class (SHARED/EXCLUSIVE) — it is replaced by `exclusive_use: bool`
2. Remove `BookingStatus` enum class — status is now a plain string
3. Replace the `booking_type` column with `exclusive_use`:

```python
# Remove:
booking_type: Mapped[BookingType] = mapped_column(
    SAEnum(BookingType, native_enum=False), nullable=False
)
status: Mapped[BookingStatus] = mapped_column(
    SAEnum(BookingStatus, native_enum=False), nullable=False, default=BookingStatus.PENDING
)

# Add:
exclusive_use: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
booking_type_id: Mapped[int] = mapped_column(
    ForeignKey("booking_type.id"), nullable=False, index=True
)
status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")
```

4. Add import: `from sqlalchemy import Boolean`
5. Add relationship:
```python
from app.db.models.booking_lifecycle import BookingType as BookingTypeModel
booking_type: Mapped["BookingTypeModel"] = relationship("BookingType", foreign_keys=[booking_type_id])
```

> **Note:** Keep `ContextTag` enum as-is. Keep all other fields unchanged.

- [ ] **Step 2: Verify model loads**

```bash
cd backend && python -c "from app.db.models.booking import Booking; print(Booking.__table__.columns.keys())"
```
Expected output includes: `exclusive_use`, `booking_type_id`, `status` (and does NOT include old `booking_type` enum column).

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models/booking.py
git commit -m "refactor: update Booking model — exclusive_use bool, booking_type_id FK, status varchar"
```

---

## Task 6: Update Booking Pydantic Schemas

**Files:**
- Modify: `backend/app/api/v1/schemas/booking.py`

- [ ] **Step 1: Update BookingCreate and BookingResponse**

Replace `booking_type: BookingType` with:
```python
booking_type_id: int
exclusive_use: bool = False
```

In `BookingResponse`, update `status` to `str` and add:
```python
booking_type_id: int
exclusive_use: bool
```

Add a new schema for the transition endpoint:
```python
class BookingTransitionRequest(BaseModel):
    to_state: str
    notes: Optional[str] = None
```

Add a schema for history:
```python
class BookingStatusHistoryResponse(BaseModel):
    id: int
    from_state: Optional[str]
    to_state: str
    changed_by: int
    changed_at: str
    notes: Optional[str]

    model_config = {"from_attributes": True}
```

Add a schema for allowed transitions response:
```python
class AllowedTransitionResponse(BaseModel):
    from_state: str
    to_state: str
    label: str
```

- [ ] **Step 2: Verify schemas load**

```bash
cd backend && python -c "from app.api.v1.schemas.booking import BookingCreate, BookingTransitionRequest, BookingStatusHistoryResponse; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/schemas/booking.py
git commit -m "refactor: update booking schemas for lifecycle — booking_type_id, exclusive_use, transition/history schemas"
```

---

## Task 7: Update BookingService

**Files:**
- Modify: `backend/app/services/booking_service.py`

- [ ] **Step 1: Write failing tests for transition_state**

Add to `backend/tests/test_bookings.py` (or a new `test_booking_transitions.py`):

```python
@pytest.mark.asyncio
async def test_transition_state_valid(client: AsyncClient, auth_headers: dict, test_booking_id: int):
    """A user can submit a draft booking."""
    resp = await client.post(
        f"/api/v1/bookings/{test_booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_transition_state_invalid_role(client: AsyncClient, user_headers: dict, test_booking_id: int):
    """A regular User cannot approve a booking."""
    # First submit it
    await client.post(
        f"/api/v1/bookings/{test_booking_id}/transition",
        headers=user_headers,
        json={"to_state": "submitted"},
    )
    resp = await client.post(
        f"/api/v1/bookings/{test_booking_id}/transition",
        headers=user_headers,  # User role, not Admin/RM
        json={"to_state": "approved"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_transition_state_invalid_transition(client: AsyncClient, auth_headers: dict, test_booking_id: int):
    """Cannot jump from draft directly to approved."""
    resp = await client.post(
        f"/api/v1/bookings/{test_booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "approved"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_history_written_on_transition(client: AsyncClient, auth_headers: dict, test_booking_id: int):
    """A history row is written for each transition."""
    await client.post(
        f"/api/v1/bookings/{test_booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted", "notes": "Ready for review"},
    )
    history_resp = await client.get(f"/api/v1/bookings/{test_booking_id}/history", headers=auth_headers)
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert len(history) >= 2  # initial creation row + this transition
    last = history[-1]
    assert last["to_state"] == "submitted"
    assert last["notes"] == "Ready for review"


@pytest.mark.asyncio
async def test_allowed_transitions_returns_role_filtered_list(client: AsyncClient, auth_headers: dict, test_booking_id: int):
    """GET /allowed-transitions returns only transitions valid for current user role."""
    resp = await client.get(f"/api/v1/bookings/{test_booking_id}/allowed-transitions", headers=auth_headers)
    assert resp.status_code == 200
    transitions = resp.json()
    to_states = [t["to_state"] for t in transitions]
    assert "submitted" in to_states  # Admin can submit


@pytest.mark.asyncio
async def test_field_permission_blocks_update_in_submitted_state(client: AsyncClient, auth_headers: dict, user_headers: dict, test_booking_id: int):
    """User cannot edit start_date after submitting."""
    # Submit the booking
    await client.post(
        f"/api/v1/bookings/{test_booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )
    # Try to update start_date as a User
    resp = await client.put(
        f"/api/v1/bookings/{test_booking_id}",
        headers=user_headers,
        json={"start_date": "2026-05-01T10:00:00Z"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_shortcut_only_works_from_submitted(client: AsyncClient, auth_headers: dict, test_booking_id: int):
    """POST /approve returns 400 if booking is not in submitted state."""
    resp = await client.post(f"/api/v1/bookings/{test_booking_id}/approve", headers=auth_headers)
    assert resp.status_code == 400  # booking is in draft, not submitted
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && pytest tests/test_bookings.py -k "transition or history or allowed" -v 2>&1 | head -20
```
Expected: 404 or attribute errors.

- [ ] **Step 3: Add transition_state() and get_status_history() to booking_service.py**

```python
# Add imports at top of booking_service.py
from datetime import datetime, timezone
from app.db.models.booking_lifecycle import BookingStatusHistory, BookingType as BookingTypeModel
from app.db.models.booking_lifecycle import BookingLifecycleTemplate
from app.services.booking_lifecycle_service import validate_transition, get_allowed_transitions, get_editable_fields
from app.api.v1.schemas.booking import BookingTransitionRequest


async def transition_state(
    db: AsyncSession,
    booking_id: int,
    to_state: str,
    current_user,
    notes: str | None = None,
) -> Booking:
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)

    # Load lifecycle template via booking type
    result = await db.execute(
        select(BookingTypeModel).where(BookingTypeModel.id == booking.booking_type_id)
    )
    booking_type_obj = result.scalar_one_or_none()
    if not booking_type_obj:
        raise HTTPException(status_code=404, detail="Booking type not found")

    tmpl_result = await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.id == booking_type_obj.lifecycle_template_id
        )
    )
    template = tmpl_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Lifecycle template not found")

    user_role = current_user.role
    if not validate_transition(template.definition, booking.status, to_state, user_role):
        # Check if transition exists at all (regardless of role)
        all_transitions = template.definition.get("transitions", [])
        transition_exists = any(
            t["from_state"] == booking.status and t["to_state"] == to_state
            for t in all_transitions
        )
        if transition_exists:
            raise HTTPException(status_code=403, detail="Your role cannot make this transition")
        raise HTTPException(status_code=400, detail=f"Invalid transition: {booking.status} -> {to_state}")

    old_state = booking.status
    booking.status = to_state

    history = BookingStatusHistory(
        booking_id=booking.id,
        from_state=old_state,
        to_state=to_state,
        changed_by=current_user.id,
        changed_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(history)
    await db.flush()

    await publish_event(
        event_type="BookingStateTransitioned",
        aggregate_id=booking.id,
        payload={"from_state": old_state, "to_state": to_state, "changed_by": current_user.id},
    )
    await db.refresh(booking)
    return booking


async def get_status_history(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> list[BookingStatusHistory]:
    # Verify booking belongs to tenant
    await get_booking(db, booking_id, tenant_id)
    result = await db.execute(
        select(BookingStatusHistory)
        .where(BookingStatusHistory.booking_id == booking_id)
        .order_by(BookingStatusHistory.changed_at.asc())
    )
    return list(result.scalars().all())


async def get_booking_allowed_transitions(
    db: AsyncSession, booking_id: int, current_user
) -> list[dict]:
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)
    result = await db.execute(
        select(BookingTypeModel).where(BookingTypeModel.id == booking.booking_type_id)
    )
    booking_type_obj = result.scalar_one()
    tmpl_result = await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.id == booking_type_obj.lifecycle_template_id
        )
    )
    template = tmpl_result.scalar_one()
    return get_allowed_transitions(template.definition, booking.status, current_user.role)
```

- [ ] **Step 4: Update create_booking to use new fields**

In `create_booking()`, replace `booking_type=data.booking_type` with:
```python
exclusive_use=data.exclusive_use,
booking_type_id=data.booking_type_id,
status="draft",
```

Then immediately write the initial history row:
```python
history = BookingStatusHistory(
    booking_id=booking.id,
    from_state=None,
    to_state="draft",
    changed_by=current_user.id,
    changed_at=datetime.now(timezone.utc),
)
db.add(history)
await db.flush()
```

- [ ] **Step 5: Update approve_booking and reject_booking to call transition_state**

```python
async def approve_booking(db: AsyncSession, booking_id: int, current_user) -> Booking:
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)
    if booking.status != "submitted":
        raise HTTPException(status_code=400, detail="Can only approve bookings in 'submitted' state")
    return await transition_state(db, booking_id, "approved", current_user)


async def reject_booking(db: AsyncSession, booking_id: int, current_user) -> Booking:
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)
    if booking.status != "submitted":
        raise HTTPException(status_code=400, detail="Can only reject bookings in 'submitted' state")
    return await transition_state(db, booking_id, "rejected", current_user)
```

- [ ] **Step 6: Add field permission check to update_booking**

At the start of the `update_booking` service function, after fetching the booking:
```python
# Load template for field permission check
bt_result = await db.execute(select(BookingTypeModel).where(BookingTypeModel.id == booking.booking_type_id))
bt = bt_result.scalar_one()
tmpl_result = await db.execute(select(BookingLifecycleTemplate).where(BookingLifecycleTemplate.id == bt.lifecycle_template_id))
tmpl = tmpl_result.scalar_one()

user_role = current_user.role
allowed_fields = get_editable_fields(tmpl.definition, booking.status, user_role)

# Check each submitted field
FIELD_MAP = {
    "project_name": data.project_name,
    "start_date": data.start_date,
    "end_date": data.end_date,
    "notes": data.notes,
    "exclusive_use": data.exclusive_use,
    # custom_fields only included if BookingUpdate schema defines it — check schema before adding
    **({"custom_fields": data.custom_fields} if hasattr(data, "custom_fields") else {}),
}
for field_name, value in FIELD_MAP.items():
    if value is not None and field_name not in allowed_fields:
        raise HTTPException(
            status_code=403,
            detail=f"Field '{field_name}' cannot be edited in state '{booking.status}'"
        )
```

- [ ] **Step 7: Add new endpoints to bookings.py**

In `backend/app/api/v1/bookings.py`, add:

```python
from app.api.v1.schemas.booking import BookingTransitionRequest, BookingStatusHistoryResponse, AllowedTransitionResponse

@router.post("/{booking_id}/transition", response_model=BookingResponse)
async def transition_booking_state(
    booking_id: int,
    data: BookingTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.transition_state(db, booking_id, data.to_state, current_user, data.notes)
    return _to_response(booking)


@router.get("/{booking_id}/history", response_model=list[BookingStatusHistoryResponse])
async def get_booking_history(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_service.get_status_history(db, booking_id, current_user.active_tenant_id)


@router.get("/{booking_id}/allowed-transitions", response_model=list[AllowedTransitionResponse])
async def get_allowed_transitions_for_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_service.get_booking_allowed_transitions(db, booking_id, current_user)
```

- [ ] **Step 8: Run all transition tests**

```bash
cd backend && pytest tests/test_bookings.py -v
```
Expected: New tests pass. Note any pre-existing tests that break (from model/schema changes) — those are fixed in Task 8.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/booking_service.py backend/app/api/v1/bookings.py
git commit -m "feat: add transition_state, history, allowed-transitions to booking service and API"
```

---

## Task 8: Fix Existing Booking Tests

**Files:**
- Modify: `backend/tests/test_bookings.py`

- [ ] **Step 1: Run existing tests and list failures**

```bash
cd backend && pytest tests/test_bookings.py -v 2>&1 | grep FAILED
```

- [ ] **Step 2: Update test fixtures and helpers**

Every test that creates a booking must now include `booking_type_id`. Add a `default_booking_type_id` fixture:

```python
@pytest_asyncio.fixture
async def default_booking_type_id(client: AsyncClient, auth_headers: dict) -> int:
    """Get or create a default booking type for tests."""
    resp = await client.get("/api/v1/tenant/booking-types", headers=auth_headers)
    types = resp.json()
    if types:
        return types[0]["id"]
    # Create minimal lifecycle template + booking type
    tmpl = await client.post("/api/v1/tenant/lifecycle-templates", headers=auth_headers, json={
        "name": "Test Lifecycle",
        "definition": {
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin", "ReleaseManager", "User"]},
            ],
            "field_permissions": {
                "draft": {"editable_fields": ["project_name", "start_date", "end_date", "notes", "exclusive_use", "custom_fields"], "editable_by": ["Admin", "ReleaseManager", "User"]},
                "submitted": {"editable_fields": ["notes"], "editable_by": ["Admin", "ReleaseManager"]},
            }
        }
    })
    bt = await client.post("/api/v1/tenant/booking-types", headers=auth_headers, json={
        "name": "Test Type", "lifecycle_template_id": tmpl.json()["id"]
    })
    return bt.json()["id"]
```

- [ ] **Step 3: Update create_booking calls in tests**

Replace all occurrences of `"booking_type": "shared"` or `"booking_type": "exclusive"` with:
```python
"booking_type_id": <default_booking_type_id>,
"exclusive_use": False,  # or True
```

Also update any assertions that check `booking["status"] == "pending"` to check `booking["status"] == "draft"`.

- [ ] **Step 4: Run all tests — all must pass**

```bash
cd backend && pytest tests/ -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/
git commit -m "test: update booking tests for new lifecycle model and schema"
```

---

## Task 9: Frontend Types

**Files:**
- Create: `frontend/src/types/bookingLifecycle.ts`
- Modify: `frontend/src/types/booking.ts`

- [ ] **Step 1: Create bookingLifecycle.ts**

```typescript
// frontend/src/types/bookingLifecycle.ts

export interface LifecycleState {
  key: string;
  label: string;
  is_initial: boolean;
  is_terminal: boolean;
}

export interface LifecycleTransition {
  from_state: string;
  to_state: string;
  label: string;
  allowed_roles: string[];
}

export interface LifecycleFieldPermission {
  editable_fields: string[];
  editable_by: string[];
}

export interface LifecycleDefinition {
  states: LifecycleState[];
  transitions: LifecycleTransition[];
  field_permissions: Record<string, LifecycleFieldPermission>;
}

export interface BookingLifecycleTemplate {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  definition: LifecycleDefinition;
  created_at: string;
  updated_at: string;
}

export interface BookingTypeRecord {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  lifecycle_template_id: number;
  color: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BookingStatusHistory {
  id: number;
  from_state: string | null;
  to_state: string;
  changed_by: number;
  changed_at: string;
  notes: string | null;
}

export interface AllowedTransition {
  from_state: string;
  to_state: string;
  label: string;
}
```

- [ ] **Step 2: Update booking.ts**

```typescript
// Replace:
export type BookingType = 'shared' | 'exclusive';
export type BookingStatus = 'pending' | 'approved' | 'rejected';

// With:
export type BookingStatus = string; // lifecycle state key e.g. 'draft', 'submitted', 'approved'

// In BookingResponse, replace:
booking_type: BookingType;
status: BookingStatus;

// With:
booking_type_id: number;
exclusive_use: boolean;
status: BookingStatus;

// In BookingCreate, replace:
booking_type: BookingType;

// With:
booking_type_id: number;
exclusive_use?: boolean;
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Fix any type errors before continuing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/
git commit -m "feat: add frontend types for booking lifecycle, booking types, and history"
```

---

## Task 10: Frontend Service Layer

**Files:**
- Create: `frontend/src/services/bookingLifecycleService.ts`
- Modify: `frontend/src/services/bookingService.ts`

- [ ] **Step 1: Create bookingLifecycleService.ts**

```typescript
// frontend/src/services/bookingLifecycleService.ts
import api from './api'; // or however axios/fetch is configured
import type { BookingLifecycleTemplate, BookingTypeRecord } from '../types/bookingLifecycle';

export const bookingLifecycleService = {
  // Lifecycle templates
  listTemplates: (): Promise<BookingLifecycleTemplate[]> =>
    api.get('/api/v1/lifecycle-templates').then(r => r.data),

  getTemplate: (id: number): Promise<BookingLifecycleTemplate> =>
    api.get(`/api/v1/lifecycle-templates/${id}`).then(r => r.data),

  createTemplate: (data: Omit<BookingLifecycleTemplate, 'id' | 'tenant_id' | 'created_at' | 'updated_at'>): Promise<BookingLifecycleTemplate> =>
    api.post('/api/v1/lifecycle-templates', data).then(r => r.data),

  updateTemplate: (id: number, data: Partial<BookingLifecycleTemplate>): Promise<BookingLifecycleTemplate> =>
    api.put(`/api/v1/lifecycle-templates/${id}`, data).then(r => r.data),

  copyTemplate: (id: number, name: string): Promise<BookingLifecycleTemplate> =>
    api.post(`/api/v1/lifecycle-templates/${id}/copy`, { name }).then(r => r.data),

  // Booking types
  listBookingTypes: (): Promise<BookingTypeRecord[]> =>
    api.get('/api/v1/booking-types').then(r => r.data),

  getBookingType: (id: number): Promise<BookingTypeRecord> =>
    api.get(`/api/v1/booking-types/${id}`).then(r => r.data),

  createBookingType: (data: Omit<BookingTypeRecord, 'id' | 'tenant_id' | 'created_at' | 'updated_at'>): Promise<BookingTypeRecord> =>
    api.post('/api/v1/booking-types', data).then(r => r.data),

  updateBookingType: (id: number, data: Partial<BookingTypeRecord>): Promise<BookingTypeRecord> =>
    api.put(`/api/v1/booking-types/${id}`, data).then(r => r.data),
};
```

> **Note:** Check how existing services (e.g. `bookingService.ts`) import the `api` client and follow the same pattern.

- [ ] **Step 2: Add methods to bookingService.ts**

```typescript
// Add to existing bookingService object:
transitionState: (id: number, to_state: string, notes?: string): Promise<BookingResponse> =>
  api.post(`/api/v1/bookings/${id}/transition`, { to_state, notes }).then(r => r.data),

getHistory: (id: number): Promise<BookingStatusHistory[]> =>
  api.get(`/api/v1/bookings/${id}/history`).then(r => r.data),

getAllowedTransitions: (id: number): Promise<AllowedTransition[]> =>
  api.get(`/api/v1/bookings/${id}/allowed-transitions`).then(r => r.data),
```

Add the necessary type imports at the top of the file.

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/services/
git commit -m "feat: add frontend service clients for booking lifecycle and transitions"
```

---

## Task 11: Frontend Redux Slice

**Files:**
- Create: `frontend/src/store/bookingLifecycleSlice.ts`

- [ ] **Step 1: Create the slice**

```typescript
// frontend/src/store/bookingLifecycleSlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { BookingLifecycleTemplate, BookingTypeRecord } from '../types/bookingLifecycle';
import { bookingLifecycleService } from '../services/bookingLifecycleService';

interface BookingLifecycleState {
  templates: BookingLifecycleTemplate[];
  bookingTypes: BookingTypeRecord[];
  loading: boolean;
  error: string | null;
}

const initialState: BookingLifecycleState = {
  templates: [],
  bookingTypes: [],
  loading: false,
  error: null,
};

export const fetchLifecycleTemplates = createAsyncThunk(
  'bookingLifecycle/fetchTemplates',
  () => bookingLifecycleService.listTemplates()
);

export const fetchBookingTypes = createAsyncThunk(
  'bookingLifecycle/fetchBookingTypes',
  () => bookingLifecycleService.listBookingTypes()
);

export const createLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/createTemplate',
  (data: Parameters<typeof bookingLifecycleService.createTemplate>[0]) =>
    bookingLifecycleService.createTemplate(data)
);

export const updateLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/updateTemplate',
  ({ id, data }: { id: number; data: Partial<BookingLifecycleTemplate> }) =>
    bookingLifecycleService.updateTemplate(id, data)
);

export const copyLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/copyTemplate',
  ({ id, name }: { id: number; name: string }) =>
    bookingLifecycleService.copyTemplate(id, name)
);

export const createBookingType = createAsyncThunk(
  'bookingLifecycle/createBookingType',
  (data: Parameters<typeof bookingLifecycleService.createBookingType>[0]) =>
    bookingLifecycleService.createBookingType(data)
);

export const updateBookingType = createAsyncThunk(
  'bookingLifecycle/updateBookingType',
  ({ id, data }: { id: number; data: Partial<BookingTypeRecord> }) =>
    bookingLifecycleService.updateBookingType(id, data)
);

const bookingLifecycleSlice = createSlice({
  name: 'bookingLifecycle',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchLifecycleTemplates.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchLifecycleTemplates.fulfilled, (state, action) => { state.loading = false; state.templates = action.payload; })
      .addCase(fetchLifecycleTemplates.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed to load templates'; })

      .addCase(fetchBookingTypes.fulfilled, (state, action) => { state.bookingTypes = action.payload; })

      .addCase(createLifecycleTemplate.fulfilled, (state, action) => { state.templates.push(action.payload); })
      .addCase(updateLifecycleTemplate.fulfilled, (state, action) => {
        const idx = state.templates.findIndex(t => t.id === action.payload.id);
        if (idx !== -1) state.templates[idx] = action.payload;
      })
      .addCase(copyLifecycleTemplate.fulfilled, (state, action) => { state.templates.push(action.payload); })
      .addCase(createBookingType.fulfilled, (state, action) => { state.bookingTypes.push(action.payload); })
      .addCase(updateBookingType.fulfilled, (state, action) => {
        const idx = state.bookingTypes.findIndex(bt => bt.id === action.payload.id);
        if (idx !== -1) state.bookingTypes[idx] = action.payload;
      });
  },
});

export default bookingLifecycleSlice.reducer;
```

- [ ] **Step 2: Register reducer in store**

Find `frontend/src/store/index.ts` (or `store.ts`) and add:
```typescript
import bookingLifecycleReducer from './bookingLifecycleSlice';
// In combineReducers:
bookingLifecycle: bookingLifecycleReducer,
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/store/
git commit -m "feat: add bookingLifecycle Redux slice"
```

---

## Task 12: Admin Booking Configuration Page

**Files:**
- Create: `frontend/src/pages/admin/BookingConfiguration.tsx`

- [ ] **Step 1: Create the page component**

This page lives in the tenant admin settings area. It has two MUI DataGrid sections — Booking Types and Lifecycle Templates — with create/edit actions.

```typescript
// frontend/src/pages/admin/BookingConfiguration.tsx
import React, { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Box, Button, Typography, Chip, Dialog, DialogTitle, DialogContent, DialogActions, TextField, MenuItem } from '@mui/material';
import { DataGrid, GridColDef } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  createBookingType,
  updateBookingType,
  createLifecycleTemplate,
  copyLifecycleTemplate,
} from '../../store/bookingLifecycleSlice';
import type { BookingTypeRecord, BookingLifecycleTemplate } from '../../types/bookingLifecycle';

export default function BookingConfiguration() {
  const dispatch = useDispatch<AppDispatch>();
  const { templates, bookingTypes, loading } = useSelector((s: RootState) => s.bookingLifecycle);
  const [createTypeOpen, setCreateTypeOpen] = useState(false);
  const [newTypeName, setNewTypeName] = useState('');
  const [newTypeTemplateId, setNewTypeTemplateId] = useState<number | ''>('');

  const handleCreateType = async () => {
    if (!newTypeName || !newTypeTemplateId) return;
    await dispatch(createBookingType({ name: newTypeName, lifecycle_template_id: Number(newTypeTemplateId), is_active: true }));
    setCreateTypeOpen(false);
    setNewTypeName('');
    setNewTypeTemplateId('');
  };

  useEffect(() => {
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates());
  }, [dispatch]);

  // ── Booking Types DataGrid ────────────────────────────────────────────────
  const typeColumns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'lifecycle_template_id',
      headerName: 'Lifecycle Template',
      flex: 1,
      renderCell: (params) => {
        const tmpl = templates.find(t => t.id === params.value);
        return tmpl?.name ?? params.value;
      },
    },
    {
      field: 'is_active',
      headerName: 'Status',
      width: 110,
      renderCell: (params) => (
        <Chip
          label={params.value ? 'Active' : 'Inactive'}
          color={params.value ? 'success' : 'default'}
          size="small"
        />
      ),
    },
  ];

  // ── Lifecycle Templates DataGrid ──────────────────────────────────────────
  const templateColumns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'definition',
      headerName: 'States',
      width: 90,
      renderCell: (params) => params.value?.states?.length ?? 0,
    },
    {
      field: 'id',
      headerName: 'Used by',
      width: 100,
      renderCell: (params) =>
        bookingTypes.filter(bt => bt.lifecycle_template_id === params.value).length + ' type(s)',
    },
    {
      field: 'actions',
      headerName: '',
      width: 120,
      sortable: false,
      renderCell: (params) => (
        <Button
          size="small"
          onClick={() => dispatch(copyLifecycleTemplate({ id: params.row.id, name: `${params.row.name} (copy)` }))}
        >
          Copy
        </Button>
      ),
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>Booking Configuration</Typography>

      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="h6">Booking Types</Typography>
          <Button variant="contained" size="small" onClick={() => setCreateTypeOpen(true)}>+ New Type</Button>
        </Box>
        <DataGrid
          rows={bookingTypes}
          columns={typeColumns}
          loading={loading}
          autoHeight
          disableRowSelectionOnClick
          pageSizeOptions={[10, 25]}
        />
      </Box>

      {/* Create Booking Type Dialog */}
      <Dialog open={createTypeOpen} onClose={() => setCreateTypeOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Booking Type</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          <TextField label="Name" required value={newTypeName} onChange={e => setNewTypeName(e.target.value)} />
          <TextField
            select label="Lifecycle Template" required
            value={newTypeTemplateId}
            onChange={e => setNewTypeTemplateId(Number(e.target.value))}
          >
            {templates.map(t => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateTypeOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreateType} disabled={!newTypeName || !newTypeTemplateId}>Create</Button>
        </DialogActions>
      </Dialog>

      <Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="h6">Lifecycle Templates</Typography>
        </Box>
        <DataGrid
          rows={templates}
          columns={templateColumns}
          loading={loading}
          autoHeight
          disableRowSelectionOnClick
          pageSizeOptions={[10, 25]}
        />
      </Box>
    </Box>
  );
}
```

- [ ] **Step 2: Add route in the admin/settings area**

Find where tenant admin settings routes are defined (likely `frontend/src/App.tsx` or a settings router) and add:
```typescript
import BookingConfiguration from './pages/admin/BookingConfiguration';
// In routes:
<Route path="/settings/booking-configuration" element={<BookingConfiguration />} />
```

Add a nav link in the settings sidebar pointing to `/settings/booking-configuration`.

- [ ] **Step 3: Verify page renders without TypeScript errors**

```bash
cd frontend && npx tsc --noEmit && npm run dev
```
Navigate to `/settings/booking-configuration`. Expected: DataGrids render (may be empty if no types defined yet).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/admin/BookingConfiguration.tsx frontend/src/App.tsx
git commit -m "feat: add admin Booking Configuration page with DataGrids for types and templates"
```

---

## Task 13: Update BookingForm

**Files:**
- Modify: `frontend/src/pages/BookingForm.tsx` (or wherever the booking creation form lives)

- [ ] **Step 1: Add booking type fetch on mount**

```typescript
const dispatch = useDispatch<AppDispatch>();
const { bookingTypes } = useSelector((s: RootState) => s.bookingLifecycle);

useEffect(() => {
  dispatch(fetchBookingTypes());
}, [dispatch]);
```

- [ ] **Step 2: Replace booking_type field with booking_type_id + exclusive_use**

Replace the existing `booking_type` select/radio with:

```typescript
// Booking Type dropdown (required)
<TextField
  select
  label="Booking Type"
  required
  value={formData.booking_type_id ?? ''}
  onChange={e => setFormData(f => ({ ...f, booking_type_id: Number(e.target.value) }))}
  error={bookingTypes.length === 0}
  helperText={bookingTypes.length === 0 ? 'No booking types configured — contact your admin' : undefined}
  disabled={bookingTypes.length === 0}
>
  {bookingTypes.filter(bt => bt.is_active).map(bt => (
    <MenuItem key={bt.id} value={bt.id}>{bt.name}</MenuItem>
  ))}
</TextField>

// Exclusive Use toggle
<FormControlLabel
  control={
    <Switch
      checked={formData.exclusive_use ?? false}
      onChange={e => setFormData(f => ({ ...f, exclusive_use: e.target.checked }))}
    />
  }
  label="Request exclusive use of environment"
/>
```

- [ ] **Step 3: Update form submission to use new fields**

Replace `booking_type` in the POST body with `booking_type_id` and `exclusive_use`.

- [ ] **Step 4: Update initial state hints**

Add an info alert below the form header:
```typescript
<Alert severity="info" sx={{ mb: 2 }}>
  Booking will be saved as <strong>Draft</strong>. Submit when ready for approval.
</Alert>
```

- [ ] **Step 5: Verify form submits and booking is created in draft state**

Start the dev server, log in, and create a new booking. Confirm `status === "draft"` in the response.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/BookingForm.tsx  # adjust path as needed
git commit -m "feat: update booking form — booking type dropdown and exclusive use toggle"
```

---

## Task 14: Update BookingDetail

**Files:**
- Modify: `frontend/src/pages/BookingDetail.tsx` (or equivalent)

- [ ] **Step 1: Fetch allowed transitions and history on load**

```typescript
const [allowedTransitions, setAllowedTransitions] = useState<AllowedTransition[]>([]);
const [history, setHistory] = useState<BookingStatusHistory[]>([]);

useEffect(() => {
  if (bookingId) {
    bookingService.getAllowedTransitions(bookingId).then(setAllowedTransitions);
    bookingService.getHistory(bookingId).then(setHistory);
    // Also ensure booking types are loaded for field permission derivation
    dispatch(fetchBookingTypes());
  }
}, [bookingId]);
```

- [ ] **Step 2: Add status badge**

```typescript
// Map state keys to MUI chip colours
const STATE_COLOURS: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  extension_requested: 'warning',
  closed: 'info',
};

<Chip
  label={booking.status}
  color={STATE_COLOURS[booking.status] ?? 'default'}
  sx={{ ml: 2, textTransform: 'capitalize' }}
/>
```

- [ ] **Step 3: Add dynamic action buttons from allowed transitions**

Replace static Approve/Reject buttons with:
```typescript
{allowedTransitions.map(t => (
  <Button
    key={t.to_state}
    variant="contained"
    color={t.to_state === 'rejected' ? 'error' : t.to_state === 'approved' ? 'success' : 'primary'}
    onClick={() => handleTransition(t.to_state, t.label)}
    sx={{ mr: 1 }}
  >
    {t.label}
  </Button>
))}
```

Implement `handleTransition`:
```typescript
const handleTransition = async (toState: string, label: string) => {
  const notes = toState === 'draft'
    ? prompt(`Reason for "${label}":`) ?? undefined
    : undefined;
  await bookingService.transitionState(booking.id, toState, notes);
  // Refresh booking, transitions, history
  refetchBooking();
  bookingService.getAllowedTransitions(booking.id).then(setAllowedTransitions);
  bookingService.getHistory(booking.id).then(setHistory);
};
```

- [ ] **Step 4: Add field-level disable based on lifecycle permissions**

```typescript
const { bookingTypes } = useSelector((s: RootState) => s.bookingLifecycle);
const { templates } = useSelector((s: RootState) => s.bookingLifecycle);

const editableFields = useMemo(() => {
  if (!booking) return [];
  const bt = bookingTypes.find(t => t.id === booking.booking_type_id);
  const tmpl = templates.find(t => t.id === bt?.lifecycle_template_id);
  if (!tmpl || !currentUserRole) return [];
  const perm = tmpl.definition.field_permissions[booking.status];
  if (!perm || !perm.editable_by.includes(currentUserRole)) return [];
  return perm.editable_fields;
}, [booking, bookingTypes, templates, currentUserRole]);

// Then on each editable field, add:
// disabled={!editableFields.includes('start_date')}
```

- [ ] **Step 5: Add history timeline**

```typescript
<Box sx={{ mt: 3 }}>
  <Typography variant="subtitle1" fontWeight="bold" gutterBottom>History</Typography>
  <Timeline>
    {history.map((row, i) => (
      <TimelineItem key={row.id}>
        <TimelineContent>
          <Typography variant="body2" color="text.secondary">
            {new Date(row.changed_at).toLocaleString()}
          </Typography>
          <Typography variant="body2">
            {row.from_state
              ? <><Chip label={row.from_state} size="small" /> → <Chip label={row.to_state} size="small" color="primary" /></>
              : <>Created as <Chip label={row.to_state} size="small" /></>
            }
          </Typography>
          {row.notes && <Typography variant="caption" color="text.secondary">{row.notes}</Typography>}
        </TimelineContent>
      </TimelineItem>
    ))}
  </Timeline>
</Box>
```

> MUI Timeline is in `@mui/lab`. Check if it's already a dependency: `grep "@mui/lab" frontend/package.json`. If not, add it: `npm install @mui/lab`.

- [ ] **Step 6: Verify end-to-end in browser**

1. Open a booking — status badge shows `draft`
2. Action buttons show "Submit" (based on allowed transitions for your role)
3. Click Submit — status changes to `submitted`, history timeline updates
4. As Admin, action buttons show "Approve", "Reject", "Return for Revision"
5. Fields are disabled in submitted state for non-admin users

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/BookingDetail.tsx  # adjust path
git commit -m "feat: update booking detail — state badge, dynamic action buttons, field permissions, history timeline"
```

---

## Verification Checklist

- [ ] `alembic upgrade head` completes without errors
- [ ] Existing bookings have `booking_type_id` set and `status` in `{submitted, approved, rejected}`
- [ ] `pytest tests/` — all tests pass
- [ ] POST `/api/v1/bookings/{id}/transition` with valid role + state → 200
- [ ] Same call with invalid role → 403; invalid state → 400
- [ ] PUT `/api/v1/bookings/{id}` editing `start_date` while in `submitted` state as User → 403
- [ ] GET `/api/v1/bookings/{id}/history` returns rows in chronological order
- [ ] GET `/api/v1/bookings/{id}/allowed-transitions` returns only transitions valid for current role
- [ ] POST `/api/v1/bookings/{id}/approve` when status is `draft` → 400
- [ ] Updating a lifecycle template → all booking types using it reflect change on next API call
- [ ] Copying a template → updates to original do not affect the copy
- [ ] Admin settings page shows Booking Types and Lifecycle Templates DataGrids
- [ ] Booking form has Type dropdown + Exclusive Use toggle; submit blocked if no types exist
- [ ] Booking detail shows correct action buttons per role; fields disabled per lifecycle state
