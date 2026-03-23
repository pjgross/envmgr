# Custom Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow tenant admins to define custom fields (text/number/boolean) per entity type, with those fields appearing on create/edit forms for all users.

**Architecture:** A `custom_field_definition` table stores field schemas per tenant+entity_type. Entity records already store values in their existing `custom_fields: JSON` column (except Booking which needs one added). A new tenant-admin API manages definitions; a reusable `CustomFieldsSection` React component renders them dynamically in all create/edit forms. A new top-level Admin area with per-entity config pages hosts the admin UI.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Alembic (manual DDL), pytest-asyncio, React 18, TypeScript, MUI, Redux Toolkit.

---

## File Map

**Backend — new files:**
- `backend/app/db/models/custom_field.py` — SQLAlchemy model (moved + updated from user.py)
- `backend/app/api/v1/schemas/custom_field.py` — Pydantic schemas
- `backend/app/services/custom_field_service.py` — CRUD + validate_custom_fields
- `backend/app/api/v1/tenant_admin_fields.py` — router (GET/POST/PATCH/DELETE)
- `backend/app/db/migrations/versions/<timestamp>_update_custom_field_definition.py`
- `backend/app/db/migrations/versions/<timestamp>_add_booking_custom_fields.py`
- `backend/tests/integration/test_custom_fields.py`

**Backend — modified files:**
- `backend/app/db/models/user.py` — remove CustomFieldDefinition class
- `backend/app/db/models/__init__.py` — update import to new module
- `backend/app/main.py` — register new router
- `backend/app/api/v1/schemas/booking.py` — add `custom_fields` to BookingCreate + BookingResponse
- `backend/app/services/booking_service.py` — call validate_custom_fields on create/update
- `backend/app/services/system_service.py` — call validate_custom_fields on create/update
- `backend/app/services/environment_service.py` — call validate_custom_fields on create/update

**Frontend — new files:**
- `frontend/src/types/customField.ts`
- `frontend/src/services/customFieldService.ts`
- `frontend/src/store/customFieldSlice.ts`
- `frontend/src/components/CustomFieldsSection.tsx`
- `frontend/src/components/admin/CustomFieldDefinitionDialog.tsx`
- `frontend/src/components/admin/CustomFieldDefinitionManager.tsx`
- `frontend/src/pages/admin/EntityConfig.tsx`
- `frontend/src/pages/admin/AdminLayout.tsx`

**Frontend — modified files:**
- `frontend/src/store/index.ts` — register customField reducer
- `frontend/src/App.tsx` — add admin routes
- `frontend/src/components/AppLayout.tsx` — add Admin nav item for tenant admins
- `frontend/src/pages/bookings/BookingForm.tsx` — add CustomFieldsSection
- `frontend/src/pages/systems/SystemCatalog.tsx` — add CustomFieldsSection
- `frontend/src/pages/systems/SystemDetail.tsx` — add CustomFieldsSection for subsystems
- `frontend/src/pages/environments/EnvironmentList.tsx` — add CustomFieldsSection

---

## Task 1: Update SQLAlchemy model for CustomFieldDefinition

The existing `CustomFieldDefinition` class in `backend/app/db/models/user.py` is missing several columns from the spec. Move it to its own file and add the missing fields.

**Files:**
- Create: `backend/app/db/models/custom_field.py`
- Modify: `backend/app/db/models/user.py` (remove CustomFieldDefinition class)
- Modify: `backend/app/db/models/__init__.py` (update import)

- [ ] **Step 1: Create the updated model file**

```python
# backend/app/db/models/custom_field.py
from sqlalchemy import String, Boolean, Integer, JSON, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from datetime import datetime

from app.db.base import Base


class CustomFieldDefinition(Base):
    """Tenant-scoped custom field schema for an entity type."""

    __tablename__ = "custom_field_definition"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # system, subsystem, environment, booking
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)   # snake_case JSON key; immutable after creation
    label: Mapped[str] = mapped_column(String(200), nullable=False)       # display name; editable
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)   # text, number, boolean; immutable after creation
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # reserved for future select types
    lifecycle_states: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # null = always visible
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "field_key", name="uq_custom_field_def"),
    )

    def __repr__(self) -> str:
        return f"<CustomFieldDefinition(id={self.id}, entity_type='{self.entity_type}', field_key='{self.field_key}')>"
```

- [ ] **Step 2: Remove CustomFieldDefinition from user.py**

Delete lines 48–61 from `backend/app/db/models/user.py` (the entire `CustomFieldDefinition` class).

- [ ] **Step 3: Update `__init__.py` import**

In `backend/app/db/models/__init__.py`, change:
```python
from app.db.models.user import Tenant, User, CustomFieldDefinition
```
to:
```python
from app.db.models.user import Tenant, User
from app.db.models.custom_field import CustomFieldDefinition
```
Also update `__all__` — it already includes `"CustomFieldDefinition"` so no change needed there.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/custom_field.py backend/app/db/models/user.py backend/app/db/models/__init__.py
git commit -m "refactor: move CustomFieldDefinition to own model file with updated schema"
```

---

## Task 2: Write Alembic migrations

Two migrations: one to update the `custom_field_definition` table (it exists from `init_db` with the old schema), one to add `custom_fields` to the `booking` table.

**Files:**
- Create: `backend/app/db/migrations/versions/<timestamp>_update_custom_field_definition.py`
- Create: `backend/app/db/migrations/versions/<timestamp>_add_booking_custom_fields.py`

Run these from `backend/`:
```bash
cd backend
alembic revision -m "update_custom_field_definition"
alembic revision -m "add_booking_custom_fields"
```

Note the generated filenames (format: `YYYYMMDD_HHMM_<hash>_<description>.py`).

- [ ] **Step 1: Write the custom_field_definition migration**

Open the first generated file and replace its `upgrade`/`downgrade` with:

```python
def upgrade() -> None:
    # Drop and recreate — no production data exists yet in this table
    op.drop_table("custom_field_definition")
    op.create_table(
        "custom_field_definition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("field_type", sa.String(20), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("lifecycle_states", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "entity_type", "field_key", name="uq_custom_field_def"),
    )
    op.create_index("ix_custom_field_definition_tenant_id", "custom_field_definition", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("custom_field_definition")
```

- [ ] **Step 2: Write the booking custom_fields migration**

Open the second generated file:

```python
def upgrade() -> None:
    op.add_column("booking", sa.Column("custom_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("booking", "custom_fields")
```

- [ ] **Step 3: Run migrations**

```bash
cd backend
alembic upgrade head
```

Expected: two new migrations applied without error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/migrations/
git commit -m "feat: add migrations for custom_field_definition update and booking custom_fields"
```

---

## Task 3: Pydantic schemas

**Files:**
- Create: `backend/app/api/v1/schemas/custom_field.py`

- [ ] **Step 1: Write the schema file**

```python
# backend/app/api/v1/schemas/custom_field.py
import re
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


VALID_ENTITY_TYPES = {"system", "subsystem", "environment", "booking"}
VALID_FIELD_TYPES = {"text", "number", "boolean"}
FIELD_KEY_RE = re.compile(r'^[a-z][a-z0-9_]*$')


class CustomFieldDefinitionCreate(BaseModel):
    entity_type: str
    field_key: Optional[str] = None   # auto-generated from label if omitted
    label: str
    field_type: str
    required: bool = False
    display_order: int = 0

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        if v not in VALID_ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of: {', '.join(sorted(VALID_ENTITY_TYPES))}")
        return v

    @field_validator("field_type")
    @classmethod
    def validate_field_type(cls, v: str) -> str:
        if v not in VALID_FIELD_TYPES:
            raise ValueError(f"field_type must be one of: {', '.join(sorted(VALID_FIELD_TYPES))}")
        return v

    @field_validator("field_key")
    @classmethod
    def validate_field_key(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not FIELD_KEY_RE.match(v):
            raise ValueError("field_key must match ^[a-z][a-z0-9_]*$")
        return v


class CustomFieldDefinitionUpdate(BaseModel):
    # field_key and field_type are intentionally excluded — immutable after creation
    label: Optional[str] = None
    required: Optional[bool] = None
    display_order: Optional[int] = None


class CustomFieldDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    entity_type: str
    field_key: str
    label: str
    field_type: str
    required: bool
    display_order: int
    options: Optional[dict] = None
    lifecycle_states: Optional[list] = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/v1/schemas/custom_field.py
git commit -m "feat: add Pydantic schemas for custom field definitions"
```

---

## Task 4: Custom field service — CRUD

**Files:**
- Create: `backend/app/services/custom_field_service.py`

- [ ] **Step 1: Write the failing tests first**

Create `backend/tests/integration/test_custom_fields.py`:

```python
"""Integration tests for custom field definition CRUD (tenant admin API)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.core.security import get_password_hash


# ---------------------------------------------------------------------------
# Second-tenant fixtures for isolation tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def other_tenant(db_session) -> Tenant:
    tenant = Tenant(name="Other CF Org", slug="other-cf-org")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def other_user(db_session, other_tenant) -> User:
    user = User(
        tenant_id=other_tenant.id,
        username="othercfadmin",
        email="admin@othercf.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def other_auth_headers(client, other_tenant, other_user) -> dict:
    response = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_field(client, auth_headers, **overrides) -> dict:
    payload = {
        "entity_type": "booking",
        "label": "Ticket Reference",
        "field_type": "text",
        "required": True,
        "display_order": 1,
        **overrides,
    }
    resp = await client.post("/api/v1/tenant/fields", headers=auth_headers, json=payload)
    return resp


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_field_definition(client: AsyncClient, auth_headers: dict):
    resp = await _create_field(client, auth_headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["label"] == "Ticket Reference"
    assert data["field_key"] == "ticket_reference"   # auto-generated from label
    assert data["field_type"] == "text"
    assert data["required"] is True
    assert data["entity_type"] == "booking"


@pytest.mark.asyncio
async def test_create_field_with_explicit_key(client: AsyncClient, auth_headers: dict):
    resp = await _create_field(client, auth_headers, label="My Label", field_key="my_key")
    assert resp.status_code == 201
    assert resp.json()["field_key"] == "my_key"


@pytest.mark.asyncio
async def test_create_field_duplicate_key_returns_409(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, label="A", field_key="dup_key")
    resp = await _create_field(client, auth_headers, label="B", field_key="dup_key")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_fields(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, label="Field One", display_order=2)
    await _create_field(client, auth_headers, label="Field Two", display_order=1)
    resp = await client.get("/api/v1/tenant/fields?entity_type=booking", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["label"] == "Field Two"   # ordered by display_order


@pytest.mark.asyncio
async def test_list_fields_requires_entity_type(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/v1/tenant/fields", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_field(client: AsyncClient, auth_headers: dict):
    create_resp = await _create_field(client, auth_headers)
    field_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/tenant/fields/{field_id}",
        headers=auth_headers,
        json={"label": "Updated Label", "required": False},
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "Updated Label"
    assert resp.json()["required"] is False


@pytest.mark.asyncio
async def test_update_ignores_immutable_fields(client: AsyncClient, auth_headers: dict):
    create_resp = await _create_field(client, auth_headers, field_key="orig_key")
    field_id = create_resp.json()["id"]
    # Sending field_key and field_type in body — should be ignored
    resp = await client.patch(
        f"/api/v1/tenant/fields/{field_id}",
        headers=auth_headers,
        json={"label": "New Label", "field_key": "hacked_key", "field_type": "number"},
    )
    assert resp.status_code == 200
    assert resp.json()["field_key"] == "orig_key"
    assert resp.json()["field_type"] == "text"


@pytest.mark.asyncio
async def test_delete_field(client: AsyncClient, auth_headers: dict):
    create_resp = await _create_field(client, auth_headers)
    field_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/api/v1/tenant/fields/{field_id}", headers=auth_headers)
    assert del_resp.status_code == 204
    # Should not appear in list anymore
    list_resp = await client.get("/api/v1/tenant/fields?entity_type=booking", headers=auth_headers)
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, auth_headers: dict, other_auth_headers: dict):
    await _create_field(client, auth_headers, label="Tenant A Field")
    # Tenant B should see no fields
    resp = await client.get("/api/v1/tenant/fields?entity_type=booking", headers=other_auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_cannot_access_other_tenants_field(client: AsyncClient, auth_headers: dict, other_auth_headers: dict):
    create_resp = await _create_field(client, auth_headers)
    field_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/api/v1/tenant/fields/{field_id}",
        headers=other_auth_headers,
        json={"label": "Stolen"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_fields(client: AsyncClient, db_session, test_tenant):
    viewer = User(
        tenant_id=test_tenant.id,
        username="viewer1",
        email="viewer@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(viewer)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", json={
        "username": "viewer1", "password": "password123", "tenant_slug": test_tenant.slug
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await _create_field(client, headers)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests — expect failures (service/router not yet built)**

```bash
cd backend && python -m pytest tests/integration/test_custom_fields.py -v 2>&1 | head -40
```

Expected: multiple ERRORS (ImportError or 404s — routes not registered yet).

- [ ] **Step 3: Write the service**

```python
# backend/app/services/custom_field_service.py
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.custom_field import CustomFieldDefinition
from app.api.v1.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
)


def _slugify(label: str) -> str:
    """Convert a label to a snake_case field_key."""
    slug = label.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if slug and slug[0].isdigit():
        slug = "f_" + slug
    return slug or "field"


async def list_definitions(
    db: AsyncSession, tenant_id: int, entity_type: str
) -> list[CustomFieldDefinition]:
    result = await db.execute(
        select(CustomFieldDefinition)
        .where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == entity_type,
            CustomFieldDefinition.deleted_at.is_(None),
        )
        .order_by(CustomFieldDefinition.display_order, CustomFieldDefinition.id)
    )
    return list(result.scalars().all())


async def create_definition(
    db: AsyncSession, tenant_id: int, data: CustomFieldDefinitionCreate
) -> CustomFieldDefinition:
    field_key = data.field_key or _slugify(data.label)

    # Enforce unique (tenant_id, entity_type, field_key)
    existing = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == data.entity_type,
            CustomFieldDefinition.field_key == field_key,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A field with key '{field_key}' already exists for this entity type",
        )

    definition = CustomFieldDefinition(
        tenant_id=tenant_id,
        entity_type=data.entity_type,
        field_key=field_key,
        label=data.label,
        field_type=data.field_type,
        required=data.required,
        display_order=data.display_order,
    )
    db.add(definition)
    await db.flush()
    await db.refresh(definition)
    return definition


async def update_definition(
    db: AsyncSession, tenant_id: int, definition_id: int, data: CustomFieldDefinitionUpdate
) -> CustomFieldDefinition:
    result = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.id == definition_id,
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    definition = result.scalar_one_or_none()
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field definition not found")

    if data.label is not None:
        definition.label = data.label
    if data.required is not None:
        definition.required = data.required
    if data.display_order is not None:
        definition.display_order = data.display_order

    await db.flush()
    await db.refresh(definition)
    return definition


async def delete_definition(
    db: AsyncSession, tenant_id: int, definition_id: int
) -> None:
    result = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.id == definition_id,
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    definition = result.scalar_one_or_none()
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field definition not found")

    definition.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def validate_custom_fields(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str,
    values: Optional[dict],
) -> None:
    """Validate custom_fields dict against active definitions for this tenant+entity_type.

    Raises HTTPException(422) if required fields are missing or types are wrong.
    Unknown keys are permitted (soft-deleted fields may still have stored values).
    """
    definitions = await list_definitions(db, tenant_id, entity_type)
    if not definitions:
        return

    values = values or {}

    for defn in definitions:
        if not defn.required:
            continue
        val = values.get(defn.field_key)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Required custom field '{defn.label}' ({defn.field_key}) is missing",
            )

    for defn in definitions:
        val = values.get(defn.field_key)
        if val is None:
            continue
        if defn.field_type == "number":
            try:
                float(val)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Custom field '{defn.label}' ({defn.field_key}) must be a number",
                )
        elif defn.field_type == "boolean":
            if not isinstance(val, bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Custom field '{defn.label}' ({defn.field_key}) must be a boolean",
                )
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/custom_field_service.py
git commit -m "feat: add custom_field_service (CRUD + validate)"
```

---

## Task 5: Tenant admin fields router + register in main.py

**Files:**
- Create: `backend/app/api/v1/tenant_admin_fields.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the router**

```python
# backend/app/api/v1/tenant_admin_fields.py
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import require_tenant_admin
from app.services import custom_field_service
from app.api.v1.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
    CustomFieldDefinitionResponse,
)

router = APIRouter()


@router.get("/fields", response_model=list[CustomFieldDefinitionResponse])
async def list_fields(
    entity_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.list_definitions(db, current_user.active_tenant_id, entity_type)


@router.post("/fields", response_model=CustomFieldDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_field(
    data: CustomFieldDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.create_definition(db, current_user.active_tenant_id, data)


@router.patch("/fields/{field_id}", response_model=CustomFieldDefinitionResponse)
async def update_field(
    field_id: int,
    data: CustomFieldDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.update_definition(db, current_user.active_tenant_id, field_id, data)


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    field_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await custom_field_service.delete_definition(db, current_user.active_tenant_id, field_id)
```

- [ ] **Step 2: Register in main.py**

Add after the existing `tenant_admin_router` import and include:

```python
from app.api.v1 import tenant_admin_fields as tenant_admin_fields_router
# ...
app.include_router(tenant_admin_fields_router.router, prefix="/api/v1/tenant", tags=["Tenant Admin"])
```

- [ ] **Step 3: Run the CRUD tests**

```bash
cd backend && python -m pytest tests/integration/test_custom_fields.py -v
```

Expected: all CRUD and isolation tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/tenant_admin_fields.py backend/app/main.py
git commit -m "feat: add tenant admin fields router and register in main"
```

---

## Task 6: Validation tests + wire validate_custom_fields into entity services

**Files:**
- Modify: `backend/tests/integration/test_custom_fields.py` (add validation tests)
- Modify: `backend/app/api/v1/schemas/booking.py`
- Modify: `backend/app/services/booking_service.py`
- Modify: `backend/app/services/system_service.py`
- Modify: `backend/app/services/environment_service.py`

- [ ] **Step 1: Add validation tests to test_custom_fields.py**

Append to `backend/tests/integration/test_custom_fields.py`:

```python
# ---------------------------------------------------------------------------
# Validation tests (requires entity creation endpoints)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_required_field_blocks_booking_creation(client: AsyncClient, auth_headers: dict):
    # Define a required text field on bookings
    await _create_field(client, auth_headers, label="Ticket Ref", field_key="ticket_ref", required=True)
    # Create an environment to book
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    # Attempt to create booking without the required custom field
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type": "shared",
    })
    assert resp.status_code == 422
    assert "ticket_ref" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_required_field_passes_when_provided(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, label="Ticket Ref", field_key="ticket_ref", required=True)
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env 2", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type": "shared",
        "custom_fields": {"ticket_ref": "JIRA-123"},
    })
    assert resp.status_code == 201
    assert resp.json()["booking"]["custom_fields"]["ticket_ref"] == "JIRA-123"


@pytest.mark.asyncio
async def test_number_field_rejects_non_numeric(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, label="Team Size", field_key="team_size", field_type="number", required=False)
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env 3", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type": "shared",
        "custom_fields": {"team_size": "not-a-number"},
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unknown_custom_field_keys_are_accepted(client: AsyncClient, auth_headers: dict):
    """Unknown keys (e.g. from soft-deleted fields) must not cause errors."""
    env_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CF Test Env 4", "environment_type": "test"},
    )
    env_id = env_resp.json()["id"]
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_id,
        "project_name": "Test",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type": "shared",
        "custom_fields": {"orphaned_old_key": "some value"},
    })
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_required_field_blocks_system_creation(client: AsyncClient, auth_headers: dict):
    await _create_field(client, auth_headers, entity_type="system", label="Owner", field_key="owner", required=True)
    resp = await client.post("/api/v1/systems/", headers=auth_headers, json={"name": "MySys"})
    assert resp.status_code == 422
    assert "owner" in resp.json()["detail"]
```

- [ ] **Step 2: Run validation tests — expect failures**

```bash
cd backend && python -m pytest tests/integration/test_custom_fields.py::test_required_field_blocks_booking_creation -v
```

Expected: FAIL (422 not returned — service doesn't call validate yet).

- [ ] **Step 3: Add `custom_fields` to BookingCreate and BookingResponse**

In `backend/app/api/v1/schemas/booking.py`:

Add `from typing import Optional` if not present (it is already), then add to `BookingCreate`:
```python
custom_fields: Optional[dict] = None
```
And to `BookingResponse`:
```python
custom_fields: Optional[dict] = None
```

- [ ] **Step 4: Wire validate into booking_service.py**

At the top of `backend/app/services/booking_service.py`, add the import:
```python
from app.services.custom_field_service import validate_custom_fields
```

In `create_booking` (or wherever the booking is persisted), add **before** the `db.add(booking)` line:
```python
await validate_custom_fields(db, tenant_id, "booking", data.custom_fields)
```

Also pass `custom_fields=data.custom_fields` when constructing the `Booking` object. Find the `Booking(...)` constructor call and add:
```python
custom_fields=data.custom_fields,
```

For recurrence children (if the service creates child occurrences), they inherit the parent's `custom_fields` — pass the same dict to child `Booking` constructors.

- [ ] **Step 5: Wire validate into system_service.py**

Note: `SystemCreate`, `SystemUpdate`, `SubSystemCreate`, and `SubSystemUpdate` in `backend/app/api/v1/schemas/system.py` already have `custom_fields: Optional[dict] = None` — no schema change needed here.

In `backend/app/services/system_service.py`:

Add import:
```python
from app.services.custom_field_service import validate_custom_fields
```

In `create_system`, add before `db.add(system)`:
```python
await validate_custom_fields(db, tenant_id, "system", data.custom_fields)
```

In `update_system` (find the update function), add before the flush:
```python
await validate_custom_fields(db, tenant_id, "system", data.custom_fields)
```

Do the same for `create_subsystem` and `update_subsystem` using entity type `"subsystem"`.

- [ ] **Step 6: Wire validate into environment_service.py**

First, open `backend/app/api/v1/schemas/environment.py` and verify that `EnvironmentCreate` and `EnvironmentUpdate` have `custom_fields: Optional[dict] = None`. If either is missing the field, add it (same pattern as the system schemas).

Then in `backend/app/services/environment_service.py`, add import and call `validate_custom_fields` in `create_environment` and `update_environment` with entity type `"environment"`.

- [ ] **Step 7: Run all validation tests**

```bash
cd backend && python -m pytest tests/integration/test_custom_fields.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Run full test suite to catch regressions**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 9: Commit**

```bash
git add backend/tests/integration/test_custom_fields.py \
        backend/app/api/v1/schemas/booking.py \
        backend/app/services/booking_service.py \
        backend/app/services/system_service.py \
        backend/app/services/environment_service.py
git commit -m "feat: wire validate_custom_fields into entity services + add custom_fields to booking schema"
```

---

## Task 7: Frontend types and service

**Files:**
- Create: `frontend/src/types/customField.ts`
- Create: `frontend/src/services/customFieldService.ts`

- [ ] **Step 1: Create TypeScript types**

```typescript
// frontend/src/types/customField.ts
export type EntityType = 'system' | 'subsystem' | 'environment' | 'booking';
export type FieldType = 'text' | 'number' | 'boolean';

export interface CustomFieldDefinition {
  id: number;
  tenant_id: number;
  entity_type: EntityType;
  field_key: string;
  label: string;
  field_type: FieldType;
  required: boolean;
  display_order: number;
  options: Record<string, unknown>[] | null;
  lifecycle_states: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface CustomFieldDefinitionCreate {
  entity_type: EntityType;
  field_key?: string;
  label: string;
  field_type: FieldType;
  required?: boolean;
  display_order?: number;
}

export interface CustomFieldDefinitionUpdate {
  label?: string;
  required?: boolean;
  display_order?: number;
}
```

- [ ] **Step 2: Create the service**

```typescript
// frontend/src/services/customFieldService.ts
import api from './api';
import type {
  CustomFieldDefinition,
  CustomFieldDefinitionCreate,
  CustomFieldDefinitionUpdate,
  EntityType,
} from '../types/customField';

export const customFieldService = {
  listDefinitions: (entityType: EntityType): Promise<CustomFieldDefinition[]> =>
    api.get('/tenant/fields', { params: { entity_type: entityType } }).then((r) => r.data),

  createDefinition: (data: CustomFieldDefinitionCreate): Promise<CustomFieldDefinition> =>
    api.post('/tenant/fields', data).then((r) => r.data),

  updateDefinition: (id: number, data: CustomFieldDefinitionUpdate): Promise<CustomFieldDefinition> =>
    api.patch(`/tenant/fields/${id}`, data).then((r) => r.data),

  deleteDefinition: (id: number): Promise<void> =>
    api.delete(`/tenant/fields/${id}`).then((r) => r.data),
};
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/customField.ts frontend/src/services/customFieldService.ts
git commit -m "feat: add TypeScript types and service for custom field definitions"
```

---

## Task 8: Redux slice for custom field definitions

**Files:**
- Create: `frontend/src/store/customFieldSlice.ts`
- Modify: `frontend/src/store/index.ts`

- [ ] **Step 1: Write the slice**

```typescript
// frontend/src/store/customFieldSlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { customFieldService } from '../services/customFieldService';
import type {
  CustomFieldDefinition,
  CustomFieldDefinitionCreate,
  CustomFieldDefinitionUpdate,
  EntityType,
} from '../types/customField';

interface CustomFieldState {
  definitions: Partial<Record<EntityType, CustomFieldDefinition[]>>;
  loading: boolean;
  error: string | null;
}

const initialState: CustomFieldState = {
  definitions: {},
  loading: false,
  error: null,
};

export const fetchDefinitions = createAsyncThunk(
  'customField/fetchDefinitions',
  (entityType: EntityType) => customFieldService.listDefinitions(entityType)
);

export const createDefinition = createAsyncThunk(
  'customField/createDefinition',
  (data: CustomFieldDefinitionCreate) => customFieldService.createDefinition(data)
);

export const updateDefinition = createAsyncThunk(
  'customField/updateDefinition',
  ({ id, data }: { id: number; data: CustomFieldDefinitionUpdate }) =>
    customFieldService.updateDefinition(id, data)
);

export const deleteDefinition = createAsyncThunk(
  'customField/deleteDefinition',
  async (id: number, { getState }) => {
    await customFieldService.deleteDefinition(id);
    return id;
  }
);

const customFieldSlice = createSlice({
  name: 'customField',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchDefinitions.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchDefinitions.fulfilled, (state, action) => {
        state.loading = false;
        const entityType = action.meta.arg;
        state.definitions[entityType] = action.payload;
      })
      .addCase(fetchDefinitions.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load fields';
      })
      .addCase(createDefinition.fulfilled, (state, action) => {
        const et = action.payload.entity_type;
        const list = state.definitions[et] ?? [];
        state.definitions[et] = [...list, action.payload].sort(
          (a, b) => a.display_order - b.display_order || a.id - b.id
        );
      })
      .addCase(updateDefinition.fulfilled, (state, action) => {
        const et = action.payload.entity_type;
        state.definitions[et] = (state.definitions[et] ?? []).map((d) =>
          d.id === action.payload.id ? action.payload : d
        );
      })
      .addCase(deleteDefinition.fulfilled, (state, action) => {
        const deletedId = action.payload;
        for (const et of Object.keys(state.definitions) as EntityType[]) {
          state.definitions[et] = (state.definitions[et] ?? []).filter((d) => d.id !== deletedId);
        }
      });
  },
});

export default customFieldSlice.reducer;
```

- [ ] **Step 2: Register in store/index.ts**

```typescript
import customFieldReducer from './customFieldSlice'
// ...
customField: customFieldReducer,
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/store/customFieldSlice.ts frontend/src/store/index.ts
git commit -m "feat: add customFieldSlice and register in Redux store"
```

---

## Task 9: CustomFieldsSection component

This reusable component renders a set of custom fields inside any create/edit form.

**Files:**
- Create: `frontend/src/components/CustomFieldsSection.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/CustomFieldsSection.tsx
import { Box, FormControlLabel, Switch, TextField, Typography } from '@mui/material';
import type { CustomFieldDefinition } from '../types/customField';

interface CustomFieldsSectionProps {
  definitions: CustomFieldDefinition[];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function CustomFieldsSection({ definitions, values, onChange }: CustomFieldsSectionProps) {
  if (definitions.length === 0) return null;

  const handleChange = (key: string, value: unknown) => {
    onChange({ ...values, [key]: value });
  };

  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Additional Fields
      </Typography>

      {definitions.map((defn) => {
        const val = values[defn.field_key];
        const label = defn.required ? `${defn.label} *` : defn.label;

        if (defn.field_type === 'boolean') {
          return (
            <FormControlLabel
              key={defn.field_key}
              sx={{ display: 'block', mb: 1 }}
              control={
                <Switch
                  checked={!!val}
                  onChange={(e) => handleChange(defn.field_key, e.target.checked)}
                />
              }
              label={label}
            />
          );
        }

        return (
          <TextField
            key={defn.field_key}
            label={label}
            type={defn.field_type === 'number' ? 'number' : 'text'}
            fullWidth
            size="small"
            sx={{ mb: 1.5 }}
            value={val ?? ''}
            onChange={(e) =>
              handleChange(
                defn.field_key,
                defn.field_type === 'number'
                  ? e.target.value === '' ? null : Number(e.target.value)
                  : e.target.value
              )
            }
          />
        );
      })}
    </Box>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/CustomFieldsSection.tsx
git commit -m "feat: add reusable CustomFieldsSection component"
```

---

## Task 10: Admin UI — CustomFieldDefinitionDialog and CustomFieldDefinitionManager

**Files:**
- Create: `frontend/src/components/admin/CustomFieldDefinitionDialog.tsx`
- Create: `frontend/src/components/admin/CustomFieldDefinitionManager.tsx`

- [ ] **Step 1: Write CustomFieldDefinitionDialog**

```tsx
// frontend/src/components/admin/CustomFieldDefinitionDialog.tsx
import { useEffect, useState } from 'react';
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, Switch, TextField, ToggleButton, ToggleButtonGroup,
  Typography, Alert,
} from '@mui/material';
import { useDispatch } from 'react-redux';
import type { AppDispatch } from '../../store';
import { createDefinition, updateDefinition } from '../../store/customFieldSlice';
import type { CustomFieldDefinition, CustomFieldDefinitionCreate, EntityType, FieldType } from '../../types/customField';

const FIELD_KEY_RE = /^[a-z][a-z0-9_]*$/;

function slugify(label: string): string {
  return label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'field';
}

interface Props {
  open: boolean;
  onClose: () => void;
  entityType: EntityType;
  editTarget: CustomFieldDefinition | null;
}

export default function CustomFieldDefinitionDialog({ open, onClose, entityType, editTarget }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const isEdit = editTarget !== null;

  const [label, setLabel] = useState('');
  const [fieldKey, setFieldKey] = useState('');
  const [keyManuallyEdited, setKeyManuallyEdited] = useState(false);
  const [fieldType, setFieldType] = useState<FieldType>('text');
  const [required, setRequired] = useState(false);
  const [displayOrder, setDisplayOrder] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      if (editTarget) {
        setLabel(editTarget.label);
        setFieldKey(editTarget.field_key);
        setFieldType(editTarget.field_type);
        setRequired(editTarget.required);
        setDisplayOrder(editTarget.display_order);
        setKeyManuallyEdited(true); // lock key on edit
      } else {
        setLabel('');
        setFieldKey('');
        setKeyManuallyEdited(false);
        setFieldType('text');
        setRequired(false);
        setDisplayOrder(0);
      }
      setError('');
    }
  }, [open, editTarget]);

  const handleLabelChange = (v: string) => {
    setLabel(v);
    if (!keyManuallyEdited && !isEdit) {
      setFieldKey(slugify(v));
    }
  };

  const handleSave = async () => {
    setError('');
    if (!label.trim()) { setError('Label is required'); return; }
    if (!isEdit && !FIELD_KEY_RE.test(fieldKey)) {
      setError('Field key must match ^[a-z][a-z0-9_]*$');
      return;
    }
    try {
      if (isEdit) {
        await dispatch(updateDefinition({
          id: editTarget!.id,
          data: { label, required, display_order: displayOrder },
        })).unwrap();
      } else {
        const payload: CustomFieldDefinitionCreate = {
          entity_type: entityType,
          field_key: fieldKey || undefined,
          label,
          field_type: fieldType,
          required,
          display_order: displayOrder,
        };
        await dispatch(createDefinition(payload)).unwrap();
      }
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed');
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{isEdit ? 'Edit Field' : 'Add Custom Field'}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
        {error && <Alert severity="error">{error}</Alert>}

        <TextField label="Label *" value={label} onChange={(e) => handleLabelChange(e.target.value)} fullWidth />

        <TextField
          label="Field Key"
          value={fieldKey}
          onChange={(e) => { setFieldKey(e.target.value); setKeyManuallyEdited(true); }}
          fullWidth
          disabled={isEdit}
          helperText={isEdit ? 'Field key cannot be changed after creation' : 'Auto-generated; lowercase letters, digits, underscores'}
          inputProps={{ style: { fontFamily: 'monospace' } }}
        />

        <div>
          <Typography variant="caption" color="text.secondary">Field Type</Typography>
          <ToggleButtonGroup
            value={fieldType}
            exclusive
            onChange={(_, v) => v && setFieldType(v)}
            disabled={isEdit}
            size="small"
            sx={{ display: 'flex', mt: 0.5 }}
          >
            <ToggleButton value="text" sx={{ flex: 1 }}>Text</ToggleButton>
            <ToggleButton value="number" sx={{ flex: 1 }}>Number</ToggleButton>
            <ToggleButton value="boolean" sx={{ flex: 1 }}>Boolean</ToggleButton>
          </ToggleButtonGroup>
          {isEdit && <Typography variant="caption" color="text.secondary">Field type cannot be changed after creation</Typography>}
        </div>

        <TextField
          label="Display Order"
          type="number"
          value={displayOrder}
          onChange={(e) => setDisplayOrder(Number(e.target.value))}
          fullWidth
          size="small"
        />

        <FormControlLabel
          control={<Switch checked={required} onChange={(e) => setRequired(e.target.checked)} />}
          label="Required field"
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={handleSave} variant="contained">Save Field</Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 2: Write CustomFieldDefinitionManager**

```tsx
// frontend/src/components/admin/CustomFieldDefinitionManager.tsx
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert, Box, Button, Chip, IconButton, Paper, Skeleton,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Tooltip, Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';

import type { AppDispatch, RootState } from '../../store';
import { fetchDefinitions, deleteDefinition } from '../../store/customFieldSlice';
import CustomFieldDefinitionDialog from './CustomFieldDefinitionDialog';
import type { CustomFieldDefinition, EntityType } from '../../types/customField';

const TYPE_COLORS: Record<string, 'primary' | 'warning' | 'success'> = {
  text: 'primary',
  number: 'warning',
  boolean: 'success',
};

interface Props {
  entityType: EntityType;
}

export default function CustomFieldDefinitionManager({ entityType }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { definitions, loading, error } = useSelector((state: RootState) => state.customField);
  const defs = definitions[entityType] ?? [];

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<CustomFieldDefinition | null>(null);

  useEffect(() => {
    dispatch(fetchDefinitions(entityType));
  }, [dispatch, entityType]);

  const openCreate = () => { setEditTarget(null); setDialogOpen(true); };
  const openEdit = (d: CustomFieldDefinition) => { setEditTarget(d); setDialogOpen(true); };
  const handleDelete = (id: number) => dispatch(deleteDefinition(id));

  if (loading && defs.length === 0) return <Skeleton variant="rectangular" height={120} />;

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="body2" color="text.secondary">{defs.length} field{defs.length !== 1 ? 's' : ''} defined</Typography>
        <Button startIcon={<AddIcon />} variant="contained" size="small" onClick={openCreate}>
          Add Field
        </Button>
      </Box>

      {defs.length === 0 ? (
        <Typography color="text.secondary" variant="body2">No custom fields yet.</Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Label</TableCell>
                <TableCell>Key</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Required</TableCell>
                <TableCell>Order</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {defs.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>{d.label}</TableCell>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{d.field_key}</TableCell>
                  <TableCell>
                    <Chip label={d.field_type} color={TYPE_COLORS[d.field_type]} size="small" />
                  </TableCell>
                  <TableCell>{d.required ? '● Yes' : '○ No'}</TableCell>
                  <TableCell>{d.display_order}</TableCell>
                  <TableCell align="right">
                    <Tooltip title="Edit">
                      <IconButton size="small" onClick={() => openEdit(d)}><EditIcon fontSize="small" /></IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                      <IconButton size="small" onClick={() => handleDelete(d.id)}><DeleteIcon fontSize="small" /></IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <CustomFieldDefinitionDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        entityType={entityType}
        editTarget={editTarget}
      />
    </Box>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/
git commit -m "feat: add CustomFieldDefinitionDialog and CustomFieldDefinitionManager components"
```

---

## Task 11: Admin area — EntityConfig page and AdminLayout

**Files:**
- Create: `frontend/src/pages/admin/EntityConfig.tsx`
- Create: `frontend/src/pages/admin/AdminLayout.tsx`

- [ ] **Step 1: Write EntityConfig**

```tsx
// frontend/src/pages/admin/EntityConfig.tsx
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Box, Tab, Tabs, Typography, Chip } from '@mui/material';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import type { EntityType } from '../../types/customField';

const ENTITY_LABELS: Record<string, string> = {
  system: 'Systems',
  subsystem: 'Subsystems',
  environment: 'Environments',
  booking: 'Bookings',
};

export default function EntityConfig() {
  const { entityType } = useParams<{ entityType: string }>();
  const [tab, setTab] = useState(0);
  const et = entityType as EntityType;

  if (!ENTITY_LABELS[et]) {
    return <Typography>Unknown entity type.</Typography>;
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>{ENTITY_LABELS[et]} Configuration</Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure custom fields and other {ENTITY_LABELS[et].toLowerCase()} settings for your tenant.
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label="Custom Fields" />
          <Tab label={<Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>Lifecycle <Chip label="Coming Soon" size="small" /></Box>} disabled />
        </Tabs>
      </Box>

      {tab === 0 && <CustomFieldDefinitionManager entityType={et} />}
    </Box>
  );
}
```

- [ ] **Step 2: Write AdminLayout**

This replaces the separate TenantSettings / UserManagement pages as the shell for all tenant admin pages. It adds a sidebar nav.

```tsx
// frontend/src/pages/admin/AdminLayout.tsx
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import {
  Box, Divider, Drawer, List, ListItemButton,
  ListItemIcon, ListItemText, Toolbar, Typography,
} from '@mui/material';
import SettingsIcon from '@mui/icons-material/Settings';
import PeopleIcon from '@mui/icons-material/People';
import StorageIcon from '@mui/icons-material/Storage';
import MemoryIcon from '@mui/icons-material/Memory';
import LanguageIcon from '@mui/icons-material/Language';
import EventIcon from '@mui/icons-material/Event';

const DRAWER_WIDTH = 220;

const adminNavItems = [
  { label: 'General Settings', path: '/tenant/settings', icon: <SettingsIcon fontSize="small" /> },
  { label: 'User Management', path: '/tenant/users', icon: <PeopleIcon fontSize="small" /> },
];

const entityNavItems = [
  { label: 'Systems', path: '/admin/config/system', icon: <StorageIcon fontSize="small" /> },
  { label: 'Subsystems', path: '/admin/config/subsystem', icon: <MemoryIcon fontSize="small" /> },
  { label: 'Environments', path: '/admin/config/environment', icon: <LanguageIcon fontSize="small" /> },
  { label: 'Bookings', path: '/admin/config/booking', icon: <EventIcon fontSize="small" /> },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <Box sx={{ display: 'flex' }}>
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box', position: 'relative', height: '100%' },
        }}
      >
        <Toolbar />
        <Box sx={{ overflow: 'auto', p: 1 }}>
          <Typography variant="overline" color="text.secondary" sx={{ px: 1 }}>Admin</Typography>
          <List dense>
            {adminNavItems.map((item) => (
              <ListItemButton
                key={item.path}
                selected={pathname === item.path}
                onClick={() => navigate(item.path)}
              >
                <ListItemIcon sx={{ minWidth: 32 }}>{item.icon}</ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            ))}
          </List>
          <Divider sx={{ my: 1 }} />
          <Typography variant="overline" color="text.secondary" sx={{ px: 1 }}>Entity Config</Typography>
          <List dense>
            {entityNavItems.map((item) => (
              <ListItemButton
                key={item.path}
                selected={pathname === item.path}
                onClick={() => navigate(item.path)}
              >
                <ListItemIcon sx={{ minWidth: 32 }}>{item.icon}</ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            ))}
          </List>
        </Box>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, overflow: 'auto' }}>
        <Outlet />
      </Box>
    </Box>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/admin/EntityConfig.tsx frontend/src/pages/admin/AdminLayout.tsx
git commit -m "feat: add EntityConfig page and AdminLayout for tenant admin area"
```

---

## Task 12: Wire admin routes into App.tsx and AppLayout.tsx nav

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`

- [ ] **Step 1: Add admin routes to App.tsx**

Import the new pages and add routes. In `App.tsx`, add imports:

```tsx
import AdminLayout from './pages/admin/AdminLayout'
import EntityConfig from './pages/admin/EntityConfig'
```

Add a nested route group for the admin area (inside the existing authenticated route wrapper):

```tsx
<Route
  path="/admin/config"
  element={<PrivateRoute requiredRole="Admin"><AdminLayout /></PrivateRoute>}
>
  <Route path=":entityType" element={<EntityConfig />} />
</Route>
```

- [ ] **Step 2: Add "Admin" nav item to AppLayout for tenant admins**

In `frontend/src/components/AppLayout.tsx`, the `navItems` array is conditionally extended. After the existing `navItems` const, add logic to show an Admin item for users with `role === 'Admin'`:

In the component body, retrieve the user:
```tsx
const user = useSelector((state: RootState) => state.auth.user)
```
(This is already done — `user` is already selected.)

Add a conditional nav item. Find the rendered list of nav items and add:
```tsx
{user?.role === 'Admin' && (
  <ListItemButton
    selected={location.pathname.startsWith('/admin/config')}
    onClick={() => navigate('/admin/config/booking')}
  >
    <ListItemIcon><AdminPanelSettingsIcon /></ListItemIcon>
    <ListItemText primary="Admin" />
  </ListItemButton>
)}
```
Place this after the existing nav items list, before the user avatar menu section. `AdminPanelSettingsIcon` is already imported in `AppLayout.tsx`.

- [ ] **Step 3: Start dev servers and verify admin navigation works**

```bash
# Terminal 1
cd backend && uvicorn app.main:app --reload

# Terminal 2
cd frontend && npm run dev
```

Log in as `admin` / `admin123` (tenant: `demo`), confirm:
- "Admin" nav item appears in sidebar
- Clicking it navigates to `/admin/config/booking`
- The entity config sidebar shows Systems / Subsystems / Environments / Bookings
- The Custom Fields tab renders with empty state and "Add Field" button

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/AppLayout.tsx
git commit -m "feat: add admin config routes and nav item for tenant admins"
```

---

## Task 13: Integrate CustomFieldsSection into BookingForm

**Files:**
- Modify: `frontend/src/pages/bookings/BookingForm.tsx`

- [ ] **Step 1: Add imports and state for custom fields**

At the top of `BookingForm.tsx`, add:

```tsx
import { useEffect } from 'react';  // already imported as useState is — add useEffect if not present
import { fetchDefinitions } from '../../store/customFieldSlice';
import type { RootState } from '../../store';
import CustomFieldsSection from '../../components/CustomFieldsSection';
```

Inside the component, add:

```tsx
const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['booking'] ?? []);
const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

useEffect(() => {
  dispatch(fetchDefinitions('booking'));
}, [dispatch]);
```

If `BookingForm` supports editing an existing booking (check whether the component receives an `editTarget` prop or similar), pre-populate `customFieldValues` when the dialog opens in edit mode:
```tsx
// In the useEffect or handler that opens the form for editing:
setCustomFieldValues(existingBooking.custom_fields ?? {});
```
This prevents custom field values from being silently cleared when a booking is edited.

- [ ] **Step 2: Render CustomFieldsSection in the form**

In the JSX, find the end of the standard form fields (before `DialogActions`) and add:

```tsx
<CustomFieldsSection
  definitions={customFieldDefs}
  values={customFieldValues}
  onChange={setCustomFieldValues}
/>
```

- [ ] **Step 3: Include custom_fields in submit payload**

Find where `createBooking` is dispatched. Add `custom_fields: customFieldValues` to the payload object (inside the `BookingCreate` data). The booking schema already accepts `custom_fields`.

- [ ] **Step 4: Verify in browser**

Create a required text custom field on Bookings via the Admin area, then open the Booking form — the field should appear under "Additional Fields".

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/bookings/BookingForm.tsx
git commit -m "feat: integrate CustomFieldsSection into BookingForm"
```

---

## Task 14: Integrate CustomFieldsSection into SystemCatalog (systems)

**Files:**
- Modify: `frontend/src/pages/systems/SystemCatalog.tsx`

- [ ] **Step 1: Add custom fields to the system create/edit dialog**

Same pattern as BookingForm (Task 13):
1. Import `fetchDefinitions`, `CustomFieldsSection`, `RootState` in `SystemCatalog.tsx`
2. In the component, select `state.customField.definitions['system'] ?? []`
3. Add `customFieldValues` state, reset it in `openCreate` and populate from `system.custom_fields` in `openEdit`
4. Add `useEffect` to dispatch `fetchDefinitions('system')`
5. Render `<CustomFieldsSection>` inside the system create/edit dialog, before the DialogActions
6. Include `custom_fields: customFieldValues` in the `createSystem` and `updateSystem` dispatch payloads

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/systems/SystemCatalog.tsx
git commit -m "feat: integrate CustomFieldsSection into SystemCatalog"
```

---

## Task 15: Integrate CustomFieldsSection into SystemDetail (subsystems)

**Files:**
- Modify: `frontend/src/pages/systems/SystemDetail.tsx`

- [ ] **Step 1: Add custom fields to the subsystem create/edit dialog**

Same pattern as Task 13/14 but using entity type `'subsystem'`:
1. Import and select `state.customField.definitions['subsystem'] ?? []`
2. Dispatch `fetchDefinitions('subsystem')` on mount
3. Add `customFieldValues` state, reset/populate in dialog open handlers
4. Render `<CustomFieldsSection>` in the subsystem dialog
5. Include `custom_fields: customFieldValues` in subsystem create/update payloads

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/systems/SystemDetail.tsx
git commit -m "feat: integrate CustomFieldsSection into SystemDetail subsystem forms"
```

---

## Task 16: Integrate CustomFieldsSection into EnvironmentList

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentList.tsx`

- [ ] **Step 1: Add custom fields to the environment create/edit dialog**

Same pattern as Tasks 13–15 but using entity type `'environment'`:
1. Import and select `state.customField.definitions['environment'] ?? []`
2. Dispatch `fetchDefinitions('environment')` on mount
3. Add `customFieldValues` state, reset/populate in dialog handlers
4. Render `<CustomFieldsSection>` in the environment dialog
5. Include `custom_fields: customFieldValues` in environment create/update payloads

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentList.tsx
git commit -m "feat: integrate CustomFieldsSection into EnvironmentList"
```

---

## Task 17: Final verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 2: Manual smoke test in browser**

Log in as `admin` / `admin123` (tenant: `demo`).

1. Navigate to Admin → Bookings → Custom Fields
2. Create a required text field "Ticket Reference" (key: `ticket_ref`)
3. Create an optional boolean field "Requires Downtime" (key: `requires_downtime`)
4. Navigate to Bookings — open the booking form
5. Verify "Additional Fields" section appears with the two fields and `*` on Ticket Reference
6. Try submitting without filling Ticket Reference — expect a 422 error
7. Fill in Ticket Reference and submit — booking created successfully

Repeat steps 1–7 for Systems (Admin → Systems → Custom Fields).

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete custom fields implementation — Phase 2"
```
