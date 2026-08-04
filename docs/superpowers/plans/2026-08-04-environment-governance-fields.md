# Environment Governance Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every environment a tenant-configurable tier, a named owner and an expiry date, and derive "reserved now" from bookings — Phase 7 sub-project B1.

**Architecture:** A new tenant-scoped `environment_tier` table replaces the free-text `environment.environment_type` column, backfilled from each tenant's existing distinct values. `owner_user_id` and `expires_at` are added nullable and enforced by the API, so legacy rows stay honest and are surfaced through a `governance_gap` filter instead of being fabricated. Reserved is a SQL `EXISTS` over live bookings computed in the same query as the list, never a stored status.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL + SQLite (dual-engine tests), pytest; React 18, TypeScript, MUI DataGrid, Redux Toolkit, Vitest.

**Spec:** [../specs/2026-08-04-environment-governance-fields-design.md](../specs/2026-08-04-environment-governance-fields-design.md)

## Global Constraints

- Every tenant-scoped query filters by `tenant_id`, taken from `current_user.active_tenant_id` (never `.tenant_id` — that breaks impersonation).
- Enum columns use `native_enum=False`. `environment_tier.category` is a plain `String(50)`, **not** an `SAEnum` — `environment.status` already demonstrates that `SAEnum` stores the member *name* (`ACTIVE`), not its value.
- Services never call `db.commit()` — `get_db()` commits on success. Use `db.flush()` when an id is needed mid-transaction.
- Soft delete via `deleted_at`; only junction rows are hard-deleted.
- Alembic migrations are written by hand. Never `--autogenerate` — `init_db()` calls `create_all`, so autogenerate sees nothing to do.
- New list endpoints take `page: Page = Depends(pagination())` and order by a **unique** key (append the primary key as a tiebreaker).
- `sorting()` is a whitelist mapping client field names to columns; an unknown `sort_by` is a 422, never a silent fallback. Chain `apply_sort(query, sort).order_by(Model.id)` — before the tiebreaker, never instead of it.
- Never assert on emitted SQL to test ordering. Assert **rendered row order over mixed-case data**.
- Run both engines before believing a schema or query change:
  `uv run pytest -q` and
  `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
- All backend commands run from `backend/`. All frontend commands run from `frontend/`.
- Branch: `feature/env-governance-fields`. Conventional commits.

## File Structure

**PR 1 — backend**

| File | Responsibility |
|---|---|
| `backend/app/db/models/environment_tier.py` (create) | `EnvironmentTier` model |
| `backend/app/db/models/__init__.py` (modify) | Register the model on `Base.metadata` |
| `backend/app/db/models/environment.py` (modify) | `tier_id`, `owner_user_id`, `expires_at`; drop `environment_type` |
| `backend/app/services/environment_tier_defaults.py` (create) | The eight standard tiers + idempotent per-tenant seeding |
| `backend/app/services/environment_tier_service.py` (create) | Tier CRUD, name uniqueness, in-use delete guard |
| `backend/app/api/v1/schemas/environment_tier.py` (create) | Tier request/response schemas |
| `backend/app/api/v1/environment_tiers.py` (create) | Tier endpoints + `ENVIRONMENT_TIER_SORTS` |
| `backend/app/core/booking_states.py` (create) | The one `INACTIVE_BOOKING_STATUSES` set |
| `backend/app/services/environment_service.py` (modify) | `EnvironmentView`, joins, filters, compliance rule |
| `backend/app/api/v1/environments.py` (modify) | Sort whitelist, new filters, response mapping |
| `backend/app/api/v1/schemas/environment.py` (modify) | New fields + `from_view` |
| `backend/app/db/migrations/versions/20260804_*_envgovernance.py` (create) | Table, columns, backfill, cutover |

**PR 2 — frontend**

| File | Responsibility |
|---|---|
| `frontend/src/types/environmentTier.ts` (create) | Tier types |
| `frontend/src/services/environmentTierService.ts` (create) | Tier API client |
| `frontend/src/store/environmentTierSlice.ts` (create) | Tier Redux slice |
| `frontend/src/hooks/useAllEnvironmentTiers.ts` (create) | Full-list picker hook over `useSharedList` |
| `frontend/src/components/admin/EnvironmentTiersPanel.tsx` (create) | Admin CRUD panel |
| `frontend/src/pages/admin/EntityConfig.tsx` (modify) | "Tiers" tab for the environment entity |
| `frontend/src/utils/dates.ts` (modify) | `formatExpiry` |
| `frontend/src/pages/environments/EnvironmentList.tsx` (modify) | Columns, filters, form |
| `frontend/src/pages/environments/EnvironmentDetail.tsx` (modify) | Form + governance panel |

---

### Task 1: `EnvironmentTier` model and default seeding

**Files:**
- Create: `backend/app/db/models/environment_tier.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: `backend/app/services/environment_tier_defaults.py`
- Modify: `backend/app/services/tenant_service.py`
- Test: `backend/tests/test_environment_tier_defaults_seed.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `app.db.models.environment_tier.EnvironmentTier` — columns `id`, `tenant_id`, `name`, `description`, `category`, `color`, `display_order`, `is_active`, `deleted_at`, `created_at`, `updated_at`
  - `app.services.environment_tier_defaults.STANDARD_TIERS: list[dict]`
  - `app.services.environment_tier_defaults.seed_environment_tier_defaults_for_tenant(db: AsyncSession, tenant_id: int) -> None`

This task is purely additive — nothing references the new table yet, so the suite must stay green throughout.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_environment_tier_defaults_seed.py`:

```python
"""The eight standard tiers are seeded per tenant, idempotently."""
import pytest
from sqlalchemy import select

from app.db.models.environment_tier import EnvironmentTier
from app.services.environment_tier_defaults import (
    STANDARD_TIERS,
    seed_environment_tier_defaults_for_tenant,
)


async def _tiers(db, tenant_id):
    return list(
        (
            await db.execute(
                select(EnvironmentTier).where(EnvironmentTier.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_seed_creates_the_eight_standard_tiers(db_session, test_tenant):
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = await _tiers(db_session, test_tenant.id)
    assert sorted(r.name for r in rows) == sorted(t["name"] for t in STANDARD_TIERS)
    assert {r.category for r in rows} == {t["category"] for t in STANDARD_TIERS}


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, test_tenant):
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = await _tiers(db_session, test_tenant.id)
    assert len(rows) == len(STANDARD_TIERS)


@pytest.mark.asyncio
async def test_display_order_is_the_tier_progression_not_alphabetical(
    db_session, test_tenant
):
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = await _tiers(db_session, test_tenant.id)
    by_order = [r.name for r in sorted(rows, key=lambda r: r.display_order)]
    assert by_order.index("Dev") < by_order.index("UAT") < by_order.index("Production")


@pytest.mark.asyncio
async def test_seed_does_not_leak_across_tenants(
    db_session, test_tenant, second_tenant_factory
):
    other = await second_tenant_factory()
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    assert await _tiers(db_session, other.id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_environment_tier_defaults_seed.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.environment_tier'`

- [ ] **Step 3: Write the model**

Create `backend/app/db/models/environment_tier.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentTier(Base):
    """Tenant-scoped environment tier vocabulary.

    Shaped like ComponentTypeDefinition and BookingType, the two vocabularies
    this codebase already configures per tenant.

    `category` is a plain VARCHAR, not an SAEnum, on purpose: SAEnum stores the
    member *name*, which is why `environment.status` holds 'ACTIVE' rather than
    'active'. It maps a tenant's own tier name onto one of the standard tiers
    (dev, sit, uat, preprod, performance, training, production, other) and is
    NULL for a tier that matches none of them.
    """

    __tablename__ = "environment_tier"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentTier(id={self.id}, name='{self.name}', "
            f"tenant_id={self.tenant_id})>"
        )
```

- [ ] **Step 4: Register the model**

In `backend/app/db/models/__init__.py`, add an import alongside the existing ones so `Base.metadata` sees the table (the file imports every model; match the surrounding style exactly):

```python
from app.db.models.environment_tier import EnvironmentTier  # noqa: F401
```

- [ ] **Step 5: Write the defaults module**

Create `backend/app/services/environment_tier_defaults.py`:

```python
"""Seed the eight standard environment tiers. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill,
following release_defaults.py and incident_defaults.py.

The tier migration carries its own literal copy of this list rather than
importing it. That is deliberate: a migration reproduces the past, so it must
not change meaning when this module gains a ninth tier.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment_tier import EnvironmentTier

STANDARD_TIERS: list[dict[str, Any]] = [
    {"name": "Dev",         "category": "dev",         "color": "#90A4AE", "display_order": 10},
    {"name": "SIT",         "category": "sit",         "color": "#42A5F5", "display_order": 20},
    {"name": "UAT",         "category": "uat",         "color": "#7E57C2", "display_order": 30},
    {"name": "Pre-Prod",    "category": "preprod",     "color": "#FFA726", "display_order": 40},
    {"name": "Performance", "category": "performance", "color": "#26A69A", "display_order": 50},
    {"name": "Training",    "category": "training",    "color": "#8D6E63", "display_order": 60},
    {"name": "Production",  "category": "production",  "color": "#EF5350", "display_order": 70},
    {"name": "Other",       "category": "other",       "color": "#BDBDBD", "display_order": 80},
]


async def seed_environment_tier_defaults_for_tenant(
    db: AsyncSession, tenant_id: int
) -> None:
    """Create any of the standard tiers this tenant does not already have.

    Matched on lowercased name so a tenant that already has 'sit' is not given a
    second 'SIT'.
    """
    existing = {
        name.lower()
        for name in (
            await db.execute(
                select(EnvironmentTier.name).where(
                    EnvironmentTier.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    }
    for tier in STANDARD_TIERS:
        if tier["name"].lower() in existing:
            continue
        db.add(
            EnvironmentTier(
                tenant_id=tenant_id,
                name=tier["name"],
                category=tier["category"],
                color=tier["color"],
                display_order=tier["display_order"],
                is_active=True,
            )
        )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_environment_tier_defaults_seed.py -q`
Expected: PASS, 4 passed

- [ ] **Step 7: Wire seeding into tenant creation**

In `backend/app/services/tenant_service.py`, add the import beside the existing defaults imports:

```python
from app.services.environment_tier_defaults import seed_environment_tier_defaults_for_tenant
```

and inside `create_tenant`, after the `seed_incident_defaults_for_tenant` call and before `await db.commit()`:

```python
    # Seed the eight standard environment tiers.
    await seed_environment_tier_defaults_for_tenant(db, tenant.id)
```

- [ ] **Step 8: Write the failing test for tenant wiring**

Append to `backend/tests/test_environment_tier_defaults_seed.py`:

```python
@pytest.mark.asyncio
async def test_creating_a_tenant_seeds_its_tiers(db_session):
    from app.api.v1.schemas.tenant import TenantCreate
    from app.services import tenant_service

    tenant = await tenant_service.create_tenant(
        db_session, TenantCreate(name="Tier Org", slug="tier-org")
    )

    rows = await _tiers(db_session, tenant.id)
    assert len(rows) == len(STANDARD_TIERS)
```

If `TenantCreate` is not at `app.api.v1.schemas.tenant`, find it with
`grep -rn "class TenantCreate" backend/app` and use that path.

- [ ] **Step 9: Run the full suite on both engines**

Run: `uv run pytest -q`
Expected: PASS, no new failures

Run: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/db/models/environment_tier.py backend/app/db/models/__init__.py \
        backend/app/services/environment_tier_defaults.py \
        backend/app/services/tenant_service.py \
        backend/tests/test_environment_tier_defaults_seed.py
git commit -m "feat: add EnvironmentTier model and per-tenant default seeding"
```

---

### Task 2: Tier CRUD service and endpoints

**Files:**
- Create: `backend/app/services/environment_tier_service.py`
- Create: `backend/app/api/v1/schemas/environment_tier.py`
- Create: `backend/app/api/v1/environment_tiers.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_environment_tiers_api.py`

**Interfaces:**
- Consumes: `EnvironmentTier` (Task 1), `STANDARD_TIERS` (Task 1)
- Produces:
  - `environment_tier_service.list_tiers(db, tenant_id, *, page=None, sort=None, include_inactive=True) -> tuple[list[EnvironmentTier], int]`
  - `environment_tier_service.get_tier(db, tier_id, tenant_id) -> EnvironmentTier`
  - `environment_tier_service.create_tier(db, data: EnvironmentTierCreate, tenant_id) -> EnvironmentTier`
  - `environment_tier_service.update_tier(db, tier_id, data: EnvironmentTierUpdate, tenant_id) -> EnvironmentTier`
  - `environment_tier_service.delete_tier(db, tier_id, tenant_id) -> None`
  - `app.api.v1.environment_tiers.ENVIRONMENT_TIER_SORTS: dict[str, SortTarget]`
  - Schemas `EnvironmentTierCreate`, `EnvironmentTierUpdate`, `EnvironmentTierResponse`
  - Routes under `/api/v1/environment-tiers`

The in-use delete guard is written here but can only be *exercised* once environments carry `tier_id` (Task 3), so its test lands in Task 3. Everything else is testable now.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_tiers_api.py`:

```python
"""Tier configuration endpoints."""
import pytest


@pytest.mark.asyncio
async def test_list_returns_the_seeded_tiers_in_progression_order(
    client, auth_headers, db_session, test_tenant
):
    from app.services.environment_tier_defaults import (
        seed_environment_tier_defaults_for_tenant,
    )

    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()

    resp = await client.get("/api/v1/environment-tiers/", headers=auth_headers)
    assert resp.status_code == 200
    names = [row["name"] for row in resp.json()]
    assert names.index("Dev") < names.index("UAT") < names.index("Production")
    assert resp.headers["X-Total-Count"] == "8"


@pytest.mark.asyncio
async def test_create_rejects_a_duplicate_name_case_insensitively(
    client, auth_headers, db_session, test_tenant
):
    from app.services.environment_tier_defaults import (
        seed_environment_tier_defaults_for_tenant,
    )

    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "sit"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_then_update_then_soft_delete(client, auth_headers):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Integration", "color": "#123456", "display_order": 25},
    )
    assert created.status_code == 201
    tier_id = created.json()["id"]
    assert created.json()["category"] is None
    assert created.json()["is_active"] is True

    updated = await client.patch(
        f"/api/v1/environment-tiers/{tier_id}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False

    deleted = await client.delete(
        f"/api/v1/environment-tiers/{tier_id}", headers=auth_headers
    )
    assert deleted.status_code == 204

    listed = await client.get("/api/v1/environment-tiers/", headers=auth_headers)
    assert tier_id not in [row["id"] for row in listed.json()]


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    resp = await client.get(
        "/api/v1/environment-tiers/?sort_by=colour", headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_another_tenants_tier_is_invisible_and_unreachable(
    client, auth_headers, db_session, second_tenant_factory
):
    from app.db.models.environment_tier import EnvironmentTier

    other = await second_tenant_factory()
    theirs = EnvironmentTier(tenant_id=other.id, name="Their Tier")
    db_session.add(theirs)
    await db_session.commit()

    listed = await client.get("/api/v1/environment-tiers/", headers=auth_headers)
    assert theirs.id not in [row["id"] for row in listed.json()]

    fetched = await client.get(
        f"/api/v1/environment-tiers/{theirs.id}", headers=auth_headers
    )
    assert fetched.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_environment_tiers_api.py -q`
Expected: FAIL — every test 404s, no such route

- [ ] **Step 3: Write the schemas**

Create `backend/app/api/v1/schemas/environment_tier.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentTierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=7)
    display_order: int = 0
    is_active: bool = True


class EnvironmentTierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=7)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class EnvironmentTierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
```

`category` is deliberately absent from Create and Update: it identifies a
standard tier and is set by seeding, not by an admin renaming things.

- [ ] **Step 4: Write the service**

Create `backend/app/services/environment_tier_service.py`:

```python
"""Environment tier vocabulary — tenant-scoped CRUD.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.api.v1.schemas.environment_tier import (
    EnvironmentTierCreate,
    EnvironmentTierUpdate,
)
from app.db.models.environment import Environment
from app.db.models.environment_tier import EnvironmentTier


async def list_tiers(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    include_inactive: bool = True,
) -> tuple[list[EnvironmentTier], int]:
    query = select(EnvironmentTier).where(
        EnvironmentTier.tenant_id == tenant_id,
        EnvironmentTier.deleted_at.is_(None),
    )
    if not include_inactive:
        query = query.where(EnvironmentTier.is_active.is_(True))
    # display_order defaults to 0, so ties are the normal case, not the
    # exception — the id tiebreaker is what stops LIMIT/OFFSET duplicating and
    # dropping rows across pages.
    query = apply_sort(query, sort).order_by(
        EnvironmentTier.display_order, EnvironmentTier.id
    )
    return await fetch_page(db, query, page)


async def get_tier(db: AsyncSession, tier_id: int, tenant_id: int) -> EnvironmentTier:
    tier = (
        await db.execute(
            select(EnvironmentTier).where(
                EnvironmentTier.id == tier_id,
                EnvironmentTier.tenant_id == tenant_id,
                EnvironmentTier.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if tier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Environment tier not found"
        )
    return tier


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(EnvironmentTier.id).where(
        EnvironmentTier.tenant_id == tenant_id,
        EnvironmentTier.deleted_at.is_(None),
        func.lower(EnvironmentTier.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(EnvironmentTier.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tier with this name already exists in this tenant",
        )


async def create_tier(
    db: AsyncSession, data: EnvironmentTierCreate, tenant_id: int
) -> EnvironmentTier:
    await _assert_name_free(db, tenant_id, data.name)
    tier = EnvironmentTier(
        tenant_id=tenant_id,
        name=data.name.strip(),
        description=data.description,
        category=None,
        color=data.color,
        display_order=data.display_order,
        is_active=data.is_active,
    )
    db.add(tier)
    await db.flush()
    await db.refresh(tier)
    return tier


async def update_tier(
    db: AsyncSession, tier_id: int, data: EnvironmentTierUpdate, tenant_id: int
) -> EnvironmentTier:
    tier = await get_tier(db, tier_id, tenant_id)
    if data.name is not None and data.name.strip().lower() != tier.name.lower():
        await _assert_name_free(db, tenant_id, data.name, exclude_id=tier_id)
    if data.name is not None:
        tier.name = data.name.strip()
    if data.description is not None:
        tier.description = data.description
    if data.color is not None:
        tier.color = data.color
    if data.display_order is not None:
        tier.display_order = data.display_order
    if data.is_active is not None:
        tier.is_active = data.is_active
    await db.flush()
    await db.refresh(tier)
    return tier


async def delete_tier(db: AsyncSession, tier_id: int, tenant_id: int) -> None:
    tier = await get_tier(db, tier_id, tenant_id)
    in_use = (
        await db.execute(
            select(Environment.id).where(
                Environment.tier_id == tier_id,
                Environment.tenant_id == tenant_id,
                # A soft-deleted environment is not a reference. Counting it
                # would make a tier unretirable forever once anything that used
                # it was deleted.
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This tier is in use by one or more environments",
        )
    tier.deleted_at = datetime.now(timezone.utc)
    await db.flush()
```

`Environment.tier_id` does not exist yet — this module will not import cleanly
until Task 3. That is expected and is why Task 3 immediately follows.

- [ ] **Step 5: Write the endpoints**

Create `backend/app/api/v1/environment_tiers.py`:

```python
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.db.models.environment_tier import EnvironmentTier
from app.api.v1.schemas.environment_tier import (
    EnvironmentTierCreate,
    EnvironmentTierResponse,
    EnvironmentTierUpdate,
)
from app.services import environment_tier_service

router = APIRouter()

ENVIRONMENT_TIER_SORTS = {
    "name": EnvironmentTier.name,
    "display_order": EnvironmentTier.display_order,
    "created_at": EnvironmentTier.created_at,
}


@router.get("/", response_model=list[EnvironmentTierResponse])
async def list_environment_tiers(
    response: Response,
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(ENVIRONMENT_TIER_SORTS, default="display_order")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Every tier for the tenant. Readable by any member — every environment
    form needs it."""
    rows, total = await environment_tier_service.list_tiers(
        db, current_user.active_tenant_id, page=page, sort=sort
    )
    set_total_count(response, total)
    return rows


@router.post(
    "/", response_model=EnvironmentTierResponse, status_code=status.HTTP_201_CREATED
)
async def create_environment_tier(
    data: EnvironmentTierCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_tier_service.create_tier(
        db, data, current_user.active_tenant_id
    )


@router.get("/{tier_id}", response_model=EnvironmentTierResponse)
async def get_environment_tier(
    tier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_tier_service.get_tier(
        db, tier_id, current_user.active_tenant_id
    )


@router.patch("/{tier_id}", response_model=EnvironmentTierResponse)
async def update_environment_tier(
    tier_id: int,
    data: EnvironmentTierUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_tier_service.update_tier(
        db, tier_id, data, current_user.active_tenant_id
    )


@router.delete("/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment_tier(
    tier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_tier_service.delete_tier(
        db, tier_id, current_user.active_tenant_id
    )
```

Note `sorting(..., default="display_order")` with no `default_dir` — ascending,
which is the progression order.

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, beside the other environment routers (near
`environments_router`), add the import in the same import block and the
registration:

```python
app.include_router(
    environment_tiers_router.router,
    prefix="/api/v1/environment-tiers",
    tags=["Environment Tiers"],
)
```

Import it as `from app.api.v1 import environment_tiers as environment_tiers_router`,
matching how `environments_router` is imported in that file.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/integration/test_environment_tiers_api.py -q`
Expected: PASS, 5 passed

(If it fails on `Environment.tier_id` not existing, that is Task 3's column —
proceed to Task 3 and re-run this file at Task 3 Step 12.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/environment_tier_service.py \
        backend/app/api/v1/schemas/environment_tier.py \
        backend/app/api/v1/environment_tiers.py backend/app/main.py \
        backend/tests/integration/test_environment_tiers_api.py
git commit -m "feat: add environment tier configuration endpoints"
```

---

### Task 3: Environment cutover — tier, owner, expiry

**Files:**
- Modify: `backend/app/db/models/environment.py`
- Create: `backend/app/db/migrations/versions/20260804_1000_envgovernance.py`
- Modify: `backend/app/api/v1/schemas/environment.py`
- Modify: `backend/app/services/environment_service.py`
- Modify: `backend/app/api/v1/environments.py`
- Modify: `backend/app/api/v1/releases.py:840-880`
- Modify: `backend/app/api/v1/schemas/release_env_coverage.py:13`
- Modify: `backend/app/services/excel_import_service.py:96`
- Modify: `backend/tests/factories.py`, `backend/tests/conftest.py`, and every test constructing `Environment(...)`
- Test: `backend/tests/integration/test_environment_governance_api.py`

**Interfaces:**
- Consumes: `EnvironmentTier` (Task 1), `environment_tier_service` (Task 2)
- Produces:
  - `Environment.tier_id: int` (not null), `Environment.owner_user_id: Optional[int]`, `Environment.expires_at: Optional[datetime]`; `Environment.environment_type` **removed**
  - `environment_service.EnvironmentView` dataclass with fields `environment`, `tier_name`, `tier_color`, `owner_username`, `reserved_now`
  - `environment_service.get_environment_view(db, env_id, tenant_id) -> EnvironmentView`
  - `EnvironmentResponse.from_view(view: EnvironmentView) -> EnvironmentResponse`
  - `tests.factories.ensure_environment_tier(db, tenant_id, name="SIT") -> EnvironmentTier`

This is a cutover: the column disappears, so it cannot be landed in halves. Its
size is real, not accidental — **54 sites across ~30 test files construct
`Environment(environment_type=...)`** and every one must change whichever way
the design had gone, because the column is gone either way.

`reserved_now` is **not** added here — it is Task 4, so this task's diff stays
about the columns.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_governance_api.py`:

```python
"""Tier, owner and expiry on the environment API."""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.environment_tier import EnvironmentTier


async def _tier(db_session, tenant_id, name="SIT", **kwargs):
    tier = EnvironmentTier(tenant_id=tenant_id, name=name, **kwargs)
    db_session.add(tier)
    await db_session.commit()
    await db_session.refresh(tier)
    return tier


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()


@pytest.mark.asyncio
async def test_create_requires_tier_owner_and_expiry(
    client, auth_headers, db_session, test_tenant
):
    tier = await _tier(db_session, test_tenant.id)

    missing = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "no-owner", "tier_id": tier.id},
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_create_returns_tier_and_owner_names_on_the_row(
    client, auth_headers, db_session, test_tenant, test_user
):
    tier = await _tier(db_session, test_tenant.id, color="#42A5F5")

    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "sit-1",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    # Display names travel with the row — never resolved client-side against a
    # capped collection.
    assert body["tier_name"] == "SIT"
    assert body["tier_color"] == "#42A5F5"
    assert body["owner_username"] == test_user.username


@pytest.mark.asyncio
async def test_a_tier_from_another_tenant_is_rejected(
    client, auth_headers, db_session, test_tenant, test_user, second_tenant_factory
):
    other = await second_tenant_factory()
    theirs = await _tier(db_session, other.id, name="Theirs")

    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "cross-tenant",
            "tier_id": theirs.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    assert resp.status_code in (404, 422)


@pytest.mark.asyncio
async def test_patching_a_legacy_environment_requires_filling_the_gap(
    client, auth_headers, db_session, test_tenant, test_user
):
    """A legacy row (null owner, null expiry) cannot be patched at all until the
    patch supplies them. Every edit is an opportunity to close the gap."""
    tier = await _tier(db_session, test_tenant.id)
    from app.db.models.environment import Environment

    legacy = Environment(
        tenant_id=test_tenant.id, name="legacy", tier_id=tier.id
    )
    db_session.add(legacy)
    await db_session.commit()
    await db_session.refresh(legacy)

    refused = await client.patch(
        f"/api/v1/environments/{legacy.id}",
        headers=auth_headers,
        json={"description": "just a note"},
    )
    assert refused.status_code == 422

    accepted = await client.patch(
        f"/api/v1/environments/{legacy.id}",
        headers=auth_headers,
        json={
            "description": "just a note",
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["owner_username"] == test_user.username


@pytest.mark.asyncio
async def test_patching_a_compliant_environment_needs_nothing_extra(
    client, auth_headers, db_session, test_tenant, test_user
):
    tier = await _tier(db_session, test_tenant.id)
    created = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "compliant",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    env_id = created.json()["id"]

    patched = await client.patch(
        f"/api/v1/environments/{env_id}",
        headers=auth_headers,
        json={"description": "fine"},
    )
    assert patched.status_code == 200


@pytest.mark.asyncio
async def test_deleting_a_tier_in_use_is_refused(
    client, auth_headers, db_session, test_tenant, test_user
):
    tier = await _tier(db_session, test_tenant.id)
    await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "uses-the-tier",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )

    resp = await client.delete(
        f"/api/v1/environment-tiers/{tier.id}", headers=auth_headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_a_tier_becomes_deletable_once_its_environment_is_soft_deleted(
    client, auth_headers, db_session, test_tenant, test_user
):
    """A soft-deleted environment is not a reference — otherwise a tier could
    never be retired once anything that used it had been deleted."""
    tier = await _tier(db_session, test_tenant.id)
    created = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "short-lived",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    env_id = created.json()["id"]

    blocked = await client.delete(
        f"/api/v1/environment-tiers/{tier.id}", headers=auth_headers
    )
    assert blocked.status_code == 409

    await client.delete(f"/api/v1/environments/{env_id}", headers=auth_headers)

    allowed = await client.delete(
        f"/api/v1/environment-tiers/{tier.id}", headers=auth_headers
    )
    assert allowed.status_code == 204


@pytest.mark.asyncio
async def test_spreadsheet_import_falls_back_to_other_and_creates_no_tier(
    db_session, test_tenant
):
    """A vocabulary the admin configures must not be extendable by uploading a
    spreadsheet. Counted before and after, because 'it used Other' and 'it
    invented a tier called Other' look identical from the row alone."""
    from sqlalchemy import func, select

    from app.db.models.environment_tier import EnvironmentTier
    from app.services.environment_tier_defaults import (
        seed_environment_tier_defaults_for_tenant,
    )

    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    async def _tier_count():
        return (
            await db_session.execute(
                select(func.count())
                .select_from(EnvironmentTier)
                .where(EnvironmentTier.tenant_id == test_tenant.id)
            )
        ).scalar_one()

    before = await _tier_count()

    # Drive excel_import_service with one row whose type is not a known tier.
    # Use whatever entry point tests/integration already uses for imports —
    # check `grep -rn "excel_import_service" tests/` and follow that call
    # shape rather than inventing one.
    from app.services import excel_import_service

    env = await excel_import_service.import_environment_row(
        db_session,
        test_tenant.id,
        {"name": "from-spreadsheet", "environment_type": "wibble"},
    )

    after = await _tier_count()
    assert after == before, "the import created a tier"

    tier = (
        await db_session.execute(
            select(EnvironmentTier).where(EnvironmentTier.id == env.tier_id)
        )
    ).scalar_one()
    assert tier.category == "other"
```

`import_environment_row` is a stand-in name. Open
`backend/app/services/excel_import_service.py`, find the function that
constructs `Environment(...)` around line 96, and call **that** — with the
argument shape it actually takes. If it only accepts a whole workbook, build a
one-row workbook with the same helper the existing import tests use rather than
adding a new entry point for the test's convenience.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_environment_governance_api.py -q`
Expected: FAIL — `EnvironmentCreate` has no `tier_id`; 422 on every create

- [ ] **Step 3: Change the model**

In `backend/app/db/models/environment.py`, inside `class Environment`, replace
the `environment_type` line:

```python
    environment_type: Mapped[str] = mapped_column(String(100), nullable=False)
```

with:

```python
    tier_id: Mapped[int] = mapped_column(
        ForeignKey("environment_tier.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True, index=True
    )
    # Nullable so legacy rows stay honest rather than carrying a fabricated
    # owner/expiry; the API requires both going forward and the gap is
    # reportable via ?governance_gap=true.
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

`ForeignKey`, `DateTime` and `Optional` are already imported in that file.

- [ ] **Step 4: Write the migration**

Create `backend/app/db/migrations/versions/20260804_1000_envgovernance.py`.
Confirm the current head first with `uv run alembic heads` and use it as
`down_revision` (expected: `subsystemsource`).

```python
"""environment governance — tier table, owner, expiry

Revision ID: envgovernance
Revises: subsystemsource
Create Date: 2026-08-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'envgovernance'
down_revision: Union[str, None] = 'subsystemsource'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A literal copy of app.services.environment_tier_defaults.STANDARD_TIERS,
# deliberately not an import: a migration reproduces the past and must not
# change meaning when that module gains a ninth tier.
STANDARD_TIERS = [
    {"name": "Dev",         "category": "dev",         "color": "#90A4AE", "display_order": 10},
    {"name": "SIT",         "category": "sit",         "color": "#42A5F5", "display_order": 20},
    {"name": "UAT",         "category": "uat",         "color": "#7E57C2", "display_order": 30},
    {"name": "Pre-Prod",    "category": "preprod",     "color": "#FFA726", "display_order": 40},
    {"name": "Performance", "category": "performance", "color": "#26A69A", "display_order": 50},
    {"name": "Training",    "category": "training",    "color": "#8D6E63", "display_order": 60},
    {"name": "Production",  "category": "production",  "color": "#EF5350", "display_order": 70},
    {"name": "Other",       "category": "other",       "color": "#BDBDBD", "display_order": 80},
]

_tier_table = sa.table(
    "environment_tier",
    sa.column("id", sa.Integer),
    sa.column("tenant_id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("category", sa.String),
    sa.column("color", sa.String),
    sa.column("display_order", sa.Integer),
    sa.column("is_active", sa.Boolean),
)


def _backfill(conn) -> None:
    """Per tenant: seed the standard tiers, fold existing environment_type
    values onto them case-insensitively, and point every environment at one."""
    tenant_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM tenant"))]

    for tenant_id in tenant_ids:
        conn.execute(
            sa.insert(_tier_table),
            [
                {
                    "tenant_id": tenant_id,
                    "name": t["name"],
                    "category": t["category"],
                    "color": t["color"],
                    "display_order": t["display_order"],
                    "is_active": True,
                }
                for t in STANDARD_TIERS
            ],
        )

        by_lower_name = {
            name.lower(): tier_id
            for tier_id, name in conn.execute(
                sa.text(
                    "SELECT id, name FROM environment_tier WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        }
        other_id = by_lower_name["other"]

        existing_types = [
            r[0]
            for r in conn.execute(
                sa.text(
                    "SELECT DISTINCT environment_type FROM environment "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ]

        for raw in existing_types:
            key = (raw or "").strip().lower()
            if not key:
                tier_id = other_id
            elif key in by_lower_name:
                # 'SIT' and 'sit' both land here — the standard spelling wins
                # and no tenant-specific duplicate is created.
                tier_id = by_lower_name[key]
            else:
                # A value the standard vocabulary does not cover — e.g. the
                # literal "imported" that excel_import_service used to write.
                # Kept as a tenant-specific tier with a NULL category so
                # nothing is silently bucketed into Other.
                conn.execute(
                    sa.insert(_tier_table).values(
                        tenant_id=tenant_id,
                        name=raw.strip(),
                        category=None,
                        color=None,
                        display_order=100,
                        is_active=True,
                    )
                )
                tier_id = conn.execute(
                    sa.text(
                        "SELECT id FROM environment_tier "
                        "WHERE tenant_id = :t AND name = :n"
                    ),
                    {"t": tenant_id, "n": raw.strip()},
                ).scalar_one()
                by_lower_name[key] = tier_id

            conn.execute(
                sa.text(
                    "UPDATE environment SET tier_id = :tier "
                    "WHERE tenant_id = :t AND environment_type = :v"
                ),
                {"tier": tier_id, "t": tenant_id, "v": raw},
            )


def upgrade() -> None:
    op.create_table(
        "environment_tier",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_environment_tier_tenant_id", "environment_tier", ["tenant_id"])

    with op.batch_alter_table("environment") as batch:
        batch.add_column(sa.Column("tier_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_environment_tier_id", "environment_tier", ["tier_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_environment_owner_user_id", "user", ["owner_user_id"], ["id"]
        )

    _backfill(op.get_bind())

    with op.batch_alter_table("environment") as batch:
        batch.alter_column("tier_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("environment_type")

    op.create_index("ix_environment_tier_id", "environment", ["tier_id"])
    op.create_index("ix_environment_owner_user_id", "environment", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_environment_owner_user_id", table_name="environment")
    op.drop_index("ix_environment_tier_id", table_name="environment")

    with op.batch_alter_table("environment") as batch:
        batch.add_column(sa.Column("environment_type", sa.String(length=100), nullable=True))

    op.get_bind().execute(
        sa.text(
            "UPDATE environment SET environment_type = "
            "(SELECT name FROM environment_tier WHERE environment_tier.id = environment.tier_id)"
        )
    )
    op.get_bind().execute(
        sa.text(
            "UPDATE environment SET environment_type = 'unknown' "
            "WHERE environment_type IS NULL"
        )
    )

    with op.batch_alter_table("environment") as batch:
        batch.alter_column("environment_type", existing_type=sa.String(length=100), nullable=False)
        batch.drop_constraint("fk_environment_owner_user_id", type_="foreignkey")
        batch.drop_constraint("fk_environment_tier_id", type_="foreignkey")
        batch.drop_column("expires_at")
        batch.drop_column("owner_user_id")
        batch.drop_column("tier_id")

    op.drop_index("ix_environment_tier_tenant_id", table_name="environment_tier")
    op.drop_table("environment_tier")
```

**Do not run `alembic downgrade -1` against the dev database to test this.** It
steps back from the current head, not from your new revision — doing exactly
that during the GitHub work dropped `tenant_secret` and wiped the dev tenant's
stored token. The migration test in Task 5 builds a scratch database instead.

- [ ] **Step 5: Update the environment schemas**

In `backend/app/api/v1/schemas/environment.py`, replace `EnvironmentCreate`,
`EnvironmentUpdate` and `EnvironmentResponse` with:

```python
class EnvironmentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tier_id: int
    owner_user_id: int
    expires_at: datetime
    status: EnvironmentStatus = EnvironmentStatus.ACTIVE
    custom_fields: Optional[dict] = None


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tier_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    status: Optional[EnvironmentStatus] = None
    custom_fields: Optional[dict] = None


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    tier_id: int
    tier_name: str
    tier_color: Optional[str] = None
    owner_user_id: Optional[int] = None
    owner_username: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: EnvironmentStatus
    tenant_id: int
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "EnvironmentResponse":
        """Build from an environment_service.EnvironmentView.

        Display names travel with the row rather than being resolved by the
        browser against a separately-fetched collection — that collection is
        capped, so a `.find()` miss renders the entity as '—' and loses
        information no truncation banner can recover.
        """
        env = view.environment
        return cls(
            id=env.id,
            name=env.name,
            description=env.description,
            tier_id=env.tier_id,
            tier_name=view.tier_name,
            tier_color=view.tier_color,
            owner_user_id=env.owner_user_id,
            owner_username=view.owner_username,
            expires_at=env.expires_at,
            status=env.status,
            tenant_id=env.tenant_id,
            custom_fields=env.custom_fields,
            created_at=env.created_at,
            updated_at=env.updated_at,
        )
```

- [ ] **Step 6: Update the environment service**

In `backend/app/services/environment_service.py`, add these imports at the top:

```python
from dataclasses import dataclass

from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.user import User
```

(keep the existing `fetch_page` import — other call sites may still use it; drop
it only if the file no longer references it.)

Add the view dataclass above `list_environments`:

```python
@dataclass
class EnvironmentView:
    """An environment plus the display labels a UI needs without extra
    round-trips, following conflict_service.ConflictingBooking."""

    environment: Environment
    tier_name: str
    tier_color: Optional[str]
    owner_username: Optional[str]
```

Replace `list_environments` with:

```python
async def list_environments(
    db: AsyncSession,
    tenant_id: int,
    status_filter: Optional[EnvironmentStatus] = None,
    tier_id: Optional[int] = None,
    page: Optional[Page] = None,
    *,
    search: Optional[str] = None,
    owner_user_id: Optional[int] = None,
    expiring_within_days: Optional[int] = None,
    governance_gap: Optional[bool] = None,
    sort: Optional[Sort] = None,
) -> tuple[list[EnvironmentView], int]:
    """Environments for a tenant, plus the unwindowed total.

    Every filter is applied in SQL. A filter applied in Python after the query
    would window the page before the filter and return quietly wrong results —
    see docs/pagination.md.
    """
    query = (
        select(Environment, EnvironmentTier.name, EnvironmentTier.color, User.username)
        .join(EnvironmentTier, EnvironmentTier.id == Environment.tier_id)
        .outerjoin(User, User.id == Environment.owner_user_id)
        .where(Environment.tenant_id == tenant_id, Environment.deleted_at.is_(None))
    )
    if status_filter is not None:
        query = query.where(Environment.status == status_filter)
    if tier_id is not None:
        query = query.where(Environment.tier_id == tier_id)
    if owner_user_id is not None:
        query = query.where(Environment.owner_user_id == owner_user_id)
    if expiring_within_days is not None:
        cutoff = datetime.now(timezone.utc) + timedelta(days=expiring_within_days)
        # A null expiry is not "expiring soon" — it is a governance gap, which
        # is a different question with its own filter.
        query = query.where(
            Environment.expires_at.is_not(None), Environment.expires_at <= cutoff
        )
    if governance_gap is True:
        query = query.where(
            or_(
                Environment.owner_user_id.is_(None),
                Environment.expires_at.is_(None),
            )
        )
    elif governance_gap is False:
        query = query.where(
            Environment.owner_user_id.is_not(None),
            Environment.expires_at.is_not(None),
        )
    if search:
        query = query.where(Environment.name.ilike(f"%{search}%"))
    query = apply_sort(query, sort).order_by(Environment.name, Environment.id)
    rows, total = await fetch_page_rows(db, query, page)
    return (
        [
            EnvironmentView(
                environment=env,
                tier_name=tier_name,
                tier_color=tier_color,
                owner_username=owner_username,
            )
            for env, tier_name, tier_color, owner_username in rows
        ],
        total,
    )


async def get_environment_view(
    db: AsyncSession, env_id: int, tenant_id: int
) -> EnvironmentView:
    """The enriched shape the API returns. `get_environment` keeps returning the
    ORM entity for internal callers that mutate it."""
    row = (
        await db.execute(
            select(Environment, EnvironmentTier.name, EnvironmentTier.color, User.username)
            .join(EnvironmentTier, EnvironmentTier.id == Environment.tier_id)
            .outerjoin(User, User.id == Environment.owner_user_id)
            .where(
                Environment.id == env_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found"
        )
    env, tier_name, tier_color, owner_username = row
    return EnvironmentView(
        environment=env,
        tier_name=tier_name,
        tier_color=tier_color,
        owner_username=owner_username,
    )
```

Add `timedelta` to the `datetime` import at the top of the file:

```python
from datetime import datetime, timedelta, timezone
```

Add a tenant-scoped validation helper above `create_environment`:

```python
async def _validate_tier_and_owner(
    db: AsyncSession,
    tenant_id: int,
    tier_id: Optional[int],
    owner_user_id: Optional[int],
) -> None:
    """Both are client-supplied foreign keys, so both are checked against the
    caller's tenant — this is the IDOR-class gap the 2026-07-16 isolation audit
    found four of."""
    if tier_id is not None:
        found = (
            await db.execute(
                select(EnvironmentTier.id).where(
                    EnvironmentTier.id == tier_id,
                    EnvironmentTier.tenant_id == tenant_id,
                    EnvironmentTier.deleted_at.is_(None),
                )
            )
        ).first()
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Environment tier not found",
            )
    if owner_user_id is not None:
        found = (
            await db.execute(
                select(User.id).where(
                    User.id == owner_user_id, User.tenant_id == tenant_id
                )
            )
        ).first()
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Owner not found"
            )
```

In `create_environment`, after the `validate_custom_fields` call, add the
validation and change the constructor:

```python
    await _validate_tier_and_owner(db, tenant_id, data.tier_id, data.owner_user_id)
    env = Environment(
        name=data.name,
        description=data.description,
        tier_id=data.tier_id,
        owner_user_id=data.owner_user_id,
        expires_at=data.expires_at,
        status=data.status,
        tenant_id=tenant_id,
        custom_fields=data.custom_fields,
    )
```

In `update_environment`, replace the `data.environment_type` block with the
compliance rule and the new assignments — put this immediately after the name
uniqueness block:

```python
    # An environment must be compliant AFTER the patch. A compliant one can be
    # patched freely; a legacy one cannot be patched at all until the patch
    # supplies an owner and an expiry. Deliberate: a rule that exempts "small"
    # edits never closes the gap.
    fields_set = data.model_fields_set
    effective_owner = (
        data.owner_user_id if "owner_user_id" in fields_set else env.owner_user_id
    )
    effective_expiry = (
        data.expires_at if "expires_at" in fields_set else env.expires_at
    )
    if effective_owner is None or effective_expiry is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "An environment must have a named owner and an expiry date. "
                "Supply owner_user_id and expires_at with this change."
            ),
        )
    await _validate_tier_and_owner(db, tenant_id, data.tier_id, effective_owner)

    if data.tier_id is not None:
        env.tier_id = data.tier_id
    if "owner_user_id" in fields_set:
        env.owner_user_id = data.owner_user_id
    if "expires_at" in fields_set:
        env.expires_at = data.expires_at
```

- [ ] **Step 7: Update the environment endpoints**

In `backend/app/api/v1/environments.py`, replace `ENVIRONMENT_SORTS`:

```python
ENVIRONMENT_SORTS = {
    "name": Environment.name,
    "tier": EnvironmentTier.name,
    "status": Environment.status,
    "owner": User.username,
    "expires_at": Environment.expires_at,
    "created_at": Environment.created_at,
}
```

with these imports added:

```python
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.user import User
```

Replace `list_environments` and the three single-environment endpoints:

```python
@router.get("/", response_model=list[EnvironmentResponse])
async def list_environments(
    response: Response,
    status: Optional[EnvironmentStatus] = None,
    tier_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    expiring_within_days: Optional[int] = Query(None, ge=0),
    governance_gap: Optional[bool] = None,
    search: Optional[str] = None,
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(ENVIRONMENT_SORTS, default="name")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    views, total = await environment_service.list_environments(
        db,
        current_user.active_tenant_id,
        status_filter=status,
        tier_id=tier_id,
        page=page,
        search=search,
        owner_user_id=owner_user_id,
        expiring_within_days=expiring_within_days,
        governance_gap=governance_gap,
        sort=sort,
    )
    set_total_count(response, total)
    return [EnvironmentResponse.from_view(v) for v in views]


@router.post("/", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    data: EnvironmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    env = await environment_service.create_environment(
        db, data, current_user.active_tenant_id
    )
    return EnvironmentResponse.from_view(
        await environment_service.get_environment_view(
            db, env.id, current_user.active_tenant_id
        )
    )
```

and the `GET /{env_id}` / `PATCH /{env_id}` handlers' bodies:

```python
    return EnvironmentResponse.from_view(
        await environment_service.get_environment_view(
            db, env_id, current_user.active_tenant_id
        )
    )
```

For PATCH, call `environment_service.update_environment(...)` first, then
return the view as above.

- [ ] **Step 8: Update the other two backend consumers**

In `backend/app/api/v1/releases.py` around line 850, the coverage query selects
`Environment.environment_type`. Join the tier and select its name instead:

```python
    es_rows = (
        await db.execute(
            select(
                EnvironmentSystem.environment_id,
                EnvironmentSystem.system_id,
                Environment.name,
                EnvironmentTier.name,
                Environment.status,
            )
            .join(Environment, Environment.id == EnvironmentSystem.environment_id)
            .join(EnvironmentTier, EnvironmentTier.id == Environment.tier_id)
            .where(
```

Add `from app.db.models.environment_tier import EnvironmentTier` to that
module's imports. The unpacking below (`for env_id, sys_id, name, etype, estatus
in es_rows`) is unchanged — rename `etype` to `tier_name` and pass it as
`tier_name=tier_name`.

In `backend/app/api/v1/schemas/release_env_coverage.py`, rename the field:

```python
class CoverageEnvironment(BaseModel):
    environment_id: int
    name: str
    tier_name: str
    status: str
    covered_system_ids: list[int]
```

In `backend/app/services/excel_import_service.py` line 96, the import wrote the
literal `"imported"`. Resolve a tier instead — add near the top of the import
routine, before the environment loop:

```python
    from app.db.models.environment_tier import EnvironmentTier

    tiers = list(
        (
            await db.execute(
                select(EnvironmentTier).where(
                    EnvironmentTier.tenant_id == tenant_id,
                    EnvironmentTier.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    tier_by_name = {t.name.strip().lower(): t for t in tiers}
    other_tier = next((t for t in tiers if t.category == "other"), None)
```

and replace the constructor argument:

```python
                # A blank or unrecognised type falls back to Other and is
                # reported. A spreadsheet upload must not extend a vocabulary
                # the admin configures.
                tier_id=(
                    tier_by_name.get((env_type or "").strip().lower(), other_tier).id
                    if other_tier is not None
                    else tier_by_name[(env_type or "").strip().lower()].id
                ),
```

If `other_tier` is None the tenant has no Other tier, which only happens if
seeding never ran — raise a clear `HTTPException(422, "This tenant has no
environment tiers configured")` rather than an `AttributeError`.

- [ ] **Step 9: Add the tier factory and update the fixtures**

In `backend/tests/factories.py`, add:

```python
async def ensure_environment_tier(
    db: AsyncSession, tenant_id: int, name: str = "SIT"
) -> EnvironmentTier:
    """A real tier for `tenant_id`. Idempotent per (tenant, name).

    Environment.tier_id is NOT NULL, so every test that builds an environment
    needs one of these.
    """
    existing = (
        await db.execute(
            select(EnvironmentTier).where(
                EnvironmentTier.tenant_id == tenant_id, EnvironmentTier.name == name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    tier = EnvironmentTier(tenant_id=tenant_id, name=name, category=name.lower())
    db.add(tier)
    await db.flush()
    return tier
```

with `from app.db.models.environment_tier import EnvironmentTier` added to its
imports, and change `ensure_environment` to use it:

```python
    tier = await ensure_environment_tier(db, tenant_id)
    environment = Environment(tenant_id=tenant_id, name=name, tier_id=tier.id)
```

In `backend/tests/conftest.py`, change the `test_environment` fixture:

```python
@pytest_asyncio.fixture(scope="function")
async def test_environment(db_session, test_tenant) -> Environment:
    """A persisted environment in test_tenant."""
    tier = EnvironmentTier(tenant_id=test_tenant.id, name="Dev", category="dev")
    db_session.add(tier)
    await db_session.flush()
    env = Environment(
        tenant_id=test_tenant.id,
        name="test-env",
        tier_id=tier.id,
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)
    return env
```

with `from app.db.models.environment_tier import EnvironmentTier` added to
conftest's imports.

- [ ] **Step 10: Sweep the remaining test construction sites**

Find them:

```bash
grep -rn "environment_type" tests/ | grep -v "\.pyc"
```

Expect roughly 54 hits across ~30 files. For each `Environment(...)`
construction, delete the `environment_type=...` argument and add a tier. The
mechanical form, using the factory:

```python
from tests.factories import ensure_environment_tier

tier = await ensure_environment_tier(db_session, tenant.id)
env = Environment(tenant_id=tenant.id, name="whatever", tier_id=tier.id)
```

Where a test creates several environments in one tenant, call the factory once
and reuse `tier.id` — it is idempotent per (tenant, name), so repeated calls
return the same row.

Re-run the grep afterwards and confirm it returns **no hits under `tests/`**.

- [ ] **Step 11: Run the governance tests**

Run: `uv run pytest tests/integration/test_environment_governance_api.py -q`
Expected: PASS, 8 passed

- [ ] **Step 12: Run the tier tests deferred from Task 2**

Run: `uv run pytest tests/integration/test_environment_tiers_api.py -q`
Expected: PASS, 5 passed

- [ ] **Step 13: Run the full suite on both engines**

Run: `uv run pytest -q`
Expected: PASS

Run: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

The PostgreSQL leg matters here beyond habit: SQLite does not enforce column
widths at all, so a `String(200)` overflow in the tier backfill fails only on
PostgreSQL.

- [ ] **Step 14: Commit**

```bash
git add -A backend/
git commit -m "feat: replace environment_type with a tier FK, owner and expiry

The tier vocabulary is per-tenant, so the migration loses nothing: each
tenant's distinct environment_type values become tier rows, folded
case-insensitively onto the eight standard tiers so SIT and sit collapse
to one.

Owner and expiry are nullable in the database and required by the API.
Legacy rows keep a null owner rather than a fabricated one — which
environments have no accountable owner is the signal, not the noise."
```

---

### Task 4: `reserved_now` derived from bookings

**Files:**
- Create: `backend/app/core/booking_states.py`
- Modify: `backend/app/services/environment_health_service.py:19`
- Modify: `backend/app/services/environment_utilization_service.py:19`
- Modify: `backend/app/services/environment_service.py`
- Modify: `backend/app/api/v1/schemas/environment.py`
- Test: `backend/tests/services/test_environment_reserved_now.py`

**Interfaces:**
- Consumes: `EnvironmentView` (Task 3)
- Produces:
  - `app.core.booking_states.INACTIVE_BOOKING_STATUSES: frozenset[str]`
  - `EnvironmentView.reserved_now: bool`
  - `EnvironmentResponse.reserved_now: bool`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_environment_reserved_now.py`:

```python
"""Reserved is derived from live bookings, never stored.

An environment that is reserved is still active — that is why this is a second
axis and not an EnvironmentStatus value.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.booking import Booking
from app.services import environment_service
from tests.factories import ensure_booking_type, ensure_environment_tier, ensure_user


async def _booking(db, tenant_id, env_id, status: str, *, covers_now: bool = True):
    from app.db.models.booking_request import BookingRequest

    user = await ensure_user(db, tenant_id)
    booking_type = await ensure_booking_type(db, tenant_id)
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1) if covers_now else now + timedelta(days=7)
    end = now + timedelta(hours=1) if covers_now else now + timedelta(days=8)

    request = BookingRequest(
        tenant_id=tenant_id,
        project_name="proj",
        booking_type_id=booking_type.id,
        start_date=start,
        end_date=end,
        booked_by=user.id,
    )
    db.add(request)
    await db.flush()

    booking = Booking(
        tenant_id=tenant_id,
        environment_id=env_id,
        booking_request_id=request.id,
        start_date=start,
        end_date=end,
        status=status,
    )
    db.add(booking)
    await db.flush()
    return booking


async def _environment(db, tenant_id, name):
    from app.db.models.environment import Environment

    tier = await ensure_environment_tier(db, tenant_id)
    env = Environment(tenant_id=tenant_id, name=name, tier_id=tier.id)
    db.add(env)
    await db.flush()
    return env


@pytest.mark.asyncio
@pytest.mark.parametrize("dead_status", ["draft", "rejected", "closed"])
async def test_a_booking_that_is_not_a_live_claim_does_not_reserve(
    db_session, test_tenant, dead_status
):
    env = await _environment(db_session, test_tenant.id, f"env-{dead_status}")
    await _booking(db_session, test_tenant.id, env.id, dead_status)

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is False


@pytest.mark.asyncio
async def test_an_approved_booking_covering_now_reserves(db_session, test_tenant):
    env = await _environment(db_session, test_tenant.id, "env-approved")
    await _booking(db_session, test_tenant.id, env.id, "approved")

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is True


@pytest.mark.asyncio
async def test_a_future_booking_does_not_reserve_now(db_session, test_tenant):
    env = await _environment(db_session, test_tenant.id, "env-future")
    await _booking(db_session, test_tenant.id, env.id, "approved", covers_now=False)

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is False


@pytest.mark.asyncio
async def test_a_soft_deleted_booking_does_not_reserve(db_session, test_tenant):
    env = await _environment(db_session, test_tenant.id, "env-deleted")
    booking = await _booking(db_session, test_tenant.id, env.id, "approved")
    booking.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    views, _ = await environment_service.list_environments(db_session, test_tenant.id)
    view = next(v for v in views if v.environment.id == env.id)
    assert view.reserved_now is False
```

If `ensure_user` / `ensure_booking_type` have different signatures, check
`backend/tests/factories.py` and adapt the calls — do not fabricate ids.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_environment_reserved_now.py -q`
Expected: FAIL — `AttributeError: 'EnvironmentView' object has no attribute 'reserved_now'`

- [ ] **Step 3: Create the shared constant**

Create `backend/app/core/booking_states.py`:

```python
"""Which booking statuses count as a live claim on an environment.

This set was already duplicated in environment_health_service and
environment_utilization_service. The third consumer (reserved_now) is the point
at which it becomes one constant rather than three copies that can drift.

Deliberately NOT the same as conflict_service.TERMINAL_STATES ({rejected,
closed}): that one counts drafts *as* conflicts, which is a different question.
Do not merge them.
"""

# draft is uncommitted; rejected and closed are terminal.
INACTIVE_BOOKING_STATUSES = frozenset({"draft", "rejected", "closed"})
```

- [ ] **Step 4: Point the two existing consumers at it**

In `backend/app/services/environment_health_service.py`, delete the local
definition on line 19 and import instead:

```python
from app.core.booking_states import INACTIVE_BOOKING_STATUSES
```

In `backend/app/services/environment_utilization_service.py`, delete
`_INACTIVE_BOOKING_STATES` on line 19, import the shared name, and update its
one use (line ~108) to `INACTIVE_BOOKING_STATUSES`:

```python
from app.core.booking_states import INACTIVE_BOOKING_STATUSES
...
            not_(Booking.status.in_(INACTIVE_BOOKING_STATUSES)),
```

- [ ] **Step 5: Compute `reserved_now` in the query**

In `backend/app/services/environment_service.py`, add the imports:

```python
from app.core.booking_states import INACTIVE_BOOKING_STATUSES
from app.db.models.booking import Booking
```

Add the field to the dataclass:

```python
@dataclass
class EnvironmentView:
    environment: Environment
    tier_name: str
    tier_color: Optional[str]
    owner_username: Optional[str]
    reserved_now: bool
```

Add the correlated EXISTS above `list_environments`:

```python
def _reserved_now_clause():
    """True when a live booking's window covers now.

    Computed in SQL, not in Python afterwards: a Python-side derivation could
    not be filtered or sorted on without windowing the page before the filter.
    Half-open [start, end), matching conflict_service's overlap convention.
    """
    now = datetime.now(timezone.utc)
    return (
        select(Booking.id)
        .where(
            Booking.environment_id == Environment.id,
            Booking.tenant_id == Environment.tenant_id,
            Booking.deleted_at.is_(None),
            Booking.status.notin_(INACTIVE_BOOKING_STATUSES),
            Booking.start_date <= now,
            Booking.end_date > now,
        )
        .exists()
        .label("reserved_now")
    )
```

In both `list_environments` and `get_environment_view`, add the clause to the
select list and to the unpacking:

```python
    query = (
        select(
            Environment,
            EnvironmentTier.name,
            EnvironmentTier.color,
            User.username,
            _reserved_now_clause(),
        )
```

```python
        for env, tier_name, tier_color, owner_username, reserved_now in rows
```

and pass `reserved_now=bool(reserved_now)` into each `EnvironmentView(...)`.

- [ ] **Step 6: Expose it on the response**

In `backend/app/api/v1/schemas/environment.py`, add to `EnvironmentResponse`:

```python
    reserved_now: bool = False
```

and to `from_view`:

```python
            reserved_now=view.reserved_now,
```

There is deliberately **no `idle` field** — not even an always-false one. A
field reading "not idle" when it means "never checked" is the failure the drift
work had to fix. Idle arrives in B5 with its detection rules.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/services/test_environment_reserved_now.py -q`
Expected: PASS, 6 passed

- [ ] **Step 8: Verify the two hoisted consumers still pass**

Run: `uv run pytest tests/services/test_environment_health_service.py tests/services/test_environment_utilization_service.py -q`
Expected: PASS

- [ ] **Step 9: Run the full suite on both engines**

Run: `uv run pytest -q`
Expected: PASS

Run: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/core/booking_states.py backend/app/services/ \
        backend/app/api/v1/schemas/environment.py \
        backend/tests/services/test_environment_reserved_now.py
git commit -m "feat: derive reserved_now from live bookings in SQL"
```

---

### Task 5: Migration test, sort whitelist and filter tests

**Files:**
- Create: `backend/tests/test_environment_tier_migration.py`
- Modify: `backend/tests/test_sort_whitelist_contract.py`
- Modify: `frontend/src/constants/sortWhitelists.json`
- Test: `backend/tests/integration/test_environment_governance_filters.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4
- Produces: no new production interfaces

The migration is the one piece the rest of the suite never exercises —
`init_db()` builds test schemas with `create_all`. Note also that
`test_migration_schema_drift` only compares **table and column names present in
the model**, so it would *not* catch a forgotten `drop_column`. Assert the drop
explicitly.

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/test_environment_tier_migration.py`:

```python
"""The tier backfill, exercised against a real migrated database.

Skipped without PostgreSQL, like test_migration_schema_drift — migrations are
never run by the rest of the suite, which builds its schema with create_all.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

BACKEND_DIR = Path(__file__).resolve().parents[1]

ADMIN_URL = os.environ.get(
    "MIGRATION_TEST_ADMIN_URL",
    "postgresql+psycopg2://envmgr:envmgr_dev_password@localhost:5432/postgres",
)
SCRATCH_DB = "envmgr_tier_migration_check"


def _url(driver: str, name: str) -> str:
    base = ADMIN_URL.replace("postgresql+psycopg2://", f"postgresql+{driver}://")
    return base.rsplit("/", 1)[0] + f"/{name}"


def _alembic(target: str, name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": ".", "DATABASE_URL": _url("asyncpg", name)},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def scratch_database():
    name = SCRATCH_DB
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.skip(f"no PostgreSQL server for the tier migration check: {exc}")

    yield name

    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


@pytest.fixture
def migrated(scratch_database):
    """Two tenants with mixed-case environment types, migrated to head."""
    before = _alembic("subsystemsource", scratch_database)
    assert before.returncode == 0, before.stderr

    engine = create_engine(_url("psycopg2", scratch_database), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant (name, slug, is_active, created_at, updated_at) "
                "VALUES ('One', 'one', true, now(), now()), "
                "('Two', 'two', true, now(), now())"
            )
        )
        one, two = [r[0] for r in conn.execute(text("SELECT id FROM tenant ORDER BY id"))]
        for tenant_id, env_type, name in [
            (one, "SIT", "a"),
            (one, "sit", "b"),
            (one, "uat", "c"),
            (one, "imported", "d"),
            (two, "SIT", "e"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO environment "
                    "(tenant_id, name, environment_type, status, created_at, updated_at) "
                    "VALUES (:t, :n, :e, 'ACTIVE', now(), now())"
                ),
                {"t": tenant_id, "n": name, "e": env_type},
            )
    engine.dispose()

    after = _alembic("head", scratch_database)
    assert after.returncode == 0, f"upgrade to head failed:\n{after.stderr}"

    engine = create_engine(_url("psycopg2", scratch_database))
    yield engine, one, two
    engine.dispose()


def test_mixed_case_values_collapse_to_one_tier(migrated):
    engine, one, _ = migrated
    with engine.connect() as conn:
        names = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT et.name FROM environment e "
                    "JOIN environment_tier et ON et.id = e.tier_id "
                    "WHERE e.tenant_id = :t AND e.name IN ('a', 'b')"
                ),
                {"t": one},
            )
        ]
    assert names == ["SIT", "SIT"]


def test_an_unrecognised_value_survives_as_a_tenant_tier_with_no_category(migrated):
    engine, one, _ = migrated
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT et.name, et.category FROM environment e "
                "JOIN environment_tier et ON et.id = e.tier_id "
                "WHERE e.tenant_id = :t AND e.name = 'd'"
            ),
            {"t": one},
        ).one()
    assert row[0] == "imported"
    assert row[1] is None


def test_every_environment_has_a_tier(migrated):
    engine, _, _ = migrated
    with engine.connect() as conn:
        orphans = conn.execute(
            text("SELECT count(*) FROM environment WHERE tier_id IS NULL")
        ).scalar_one()
    assert orphans == 0


def test_no_tier_crosses_a_tenant_boundary(migrated):
    engine, _, _ = migrated
    with engine.connect() as conn:
        leaked = conn.execute(
            text(
                "SELECT count(*) FROM environment e "
                "JOIN environment_tier et ON et.id = e.tier_id "
                "WHERE et.tenant_id <> e.tenant_id"
            )
        ).scalar_one()
    assert leaked == 0


def test_the_old_column_is_gone(migrated):
    """test_migration_schema_drift compares only columns the models declare, so
    a forgotten drop_column would pass it. Assert the drop directly."""
    engine, _, _ = migrated
    with engine.connect() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("environment")}
    assert "environment_type" not in columns
    assert {"tier_id", "owner_user_id", "expires_at"} <= columns
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_environment_tier_migration.py -q`
Expected: PASS, 5 passed (or SKIPPED if no PostgreSQL is running — start it
with `docker-compose up -d postgres` and re-run; a skip here proves nothing)

- [ ] **Step 3: Update the frontend sort whitelist**

In `frontend/src/constants/sortWhitelists.json`, replace the `environments`
entry:

```json
  "environments": {
    "sortable": ["name", "tier", "status", "owner", "expires_at", "created_at"],
    "default": "name",
    "default_dir": "asc"
  },
```

- [ ] **Step 4: Run the contract test**

Run: `uv run pytest tests/test_sort_whitelist_contract.py -q`
Expected: PASS — it reads `ENVIRONMENT_SORTS` and this JSON and asserts they match

- [ ] **Step 5: Write the filter and ordering tests**

Create `backend/tests/integration/test_environment_governance_filters.py`:

```python
"""Governance filters and the new sortable columns.

Ordering is asserted on rendered row order over mixed-case data. An assertion
on the emitted SQL stays green while the order users see is wrong — that is
exactly what happened to the pagination pilot.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.environment import Environment
from app.db.models.environment_tier import EnvironmentTier


async def _seed(db_session, tenant_id, owner_id):
    tiers = {}
    for name in ("apple", "Banana", "cherry"):
        tier = EnvironmentTier(tenant_id=tenant_id, name=name)
        db_session.add(tier)
        tiers[name] = tier
    await db_session.flush()

    soon = datetime.now(timezone.utc) + timedelta(days=5)
    later = datetime.now(timezone.utc) + timedelta(days=200)

    rows = [
        Environment(tenant_id=tenant_id, name="owned-soon", tier_id=tiers["apple"].id,
                    owner_user_id=owner_id, expires_at=soon),
        Environment(tenant_id=tenant_id, name="owned-later", tier_id=tiers["Banana"].id,
                    owner_user_id=owner_id, expires_at=later),
        Environment(tenant_id=tenant_id, name="no-owner", tier_id=tiers["cherry"].id,
                    owner_user_id=None, expires_at=later),
        Environment(tenant_id=tenant_id, name="no-expiry", tier_id=tiers["apple"].id,
                    owner_user_id=owner_id, expires_at=None),
    ]
    for row in rows:
        db_session.add(row)
    await db_session.commit()
    return tiers


@pytest.mark.asyncio
async def test_governance_gap_returns_the_rows_missing_owner_or_expiry(
    client, auth_headers, db_session, test_tenant, test_user
):
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?governance_gap=true", headers=auth_headers
    )
    assert resp.status_code == 200
    assert sorted(r["name"] for r in resp.json()) == ["no-expiry", "no-owner"]
    # The header is the true total, not the page length.
    assert resp.headers["X-Total-Count"] == "2"


@pytest.mark.asyncio
async def test_expiring_within_days_excludes_a_null_expiry(
    client, auth_headers, db_session, test_tenant, test_user
):
    """'Expiring soon' and 'never given an expiry' are different problems."""
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?expiring_within_days=30", headers=auth_headers
    )
    assert [r["name"] for r in resp.json()] == ["owned-soon"]


@pytest.mark.asyncio
async def test_filtering_by_tier(client, auth_headers, db_session, test_tenant, test_user):
    tiers = await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        f"/api/v1/environments/?tier_id={tiers['apple'].id}", headers=auth_headers
    )
    assert sorted(r["name"] for r in resp.json()) == ["no-expiry", "owned-soon"]


@pytest.mark.asyncio
async def test_sorting_by_tier_folds_case(
    client, auth_headers, db_session, test_tenant, test_user
):
    """Both engines here collate by byte value, which would put 'Banana' before
    'apple'. apply_sort folds case, so the rendered order is alphabetical."""
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?sort_by=tier&sort_dir=asc", headers=auth_headers
    )
    assert [r["tier_name"] for r in resp.json()] == [
        "apple",
        "apple",
        "Banana",
        "cherry",
    ]


@pytest.mark.asyncio
async def test_sorting_by_expiry_pins_nulls_last_on_asc(
    client, auth_headers, db_session, test_tenant, test_user
):
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?sort_by=expires_at&sort_dir=asc", headers=auth_headers
    )
    assert [r["name"] for r in resp.json()][-1] == "no-expiry"


@pytest.mark.asyncio
async def test_an_unwhitelisted_sort_field_is_422(client, auth_headers):
    resp = await client.get(
        "/api/v1/environments/?sort_by=environment_type", headers=auth_headers
    )
    assert resp.status_code == 422
```

- [ ] **Step 6: Run them**

Run: `uv run pytest tests/integration/test_environment_governance_filters.py -q`
Expected: PASS, 6 passed

- [ ] **Step 7: Run the full suite on both engines**

Run: `uv run pytest -q`
Expected: PASS

Run: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/tests/ frontend/src/constants/sortWhitelists.json
git commit -m "test: cover the tier backfill, governance filters and case-folded tier sort"
```

---

### Task 6: Correct `docs/phases/phase-7.md`

**Files:**
- Modify: `docs/phases/phase-7.md`

**Interfaces:**
- Consumes: nothing
- Produces: nothing

`phase-7.md` currently lists only programme A and says "detailed task breakdown
to be added when Phase 6 is complete". Phase 6 *is* complete, and leaving it is
how the next person plans against half a phase — which is exactly what happened
with `phase-6.md`.

- [ ] **Step 1: Rewrite the phase document**

Replace the body of `docs/phases/phase-7.md` (keep the title) with:

```markdown
# Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance

> Status: 🟡 **In progress** — sub-project B1 shipped | Roadmap: [../plan.md](../plan.md)

Phase 7 is two independent programmes. Each sub-project gets its own spec, plan
and PR.

## A — Multi-Project Coordination

- [ ] **A1** `Project` entity + members; promote the free-text
      `BookingRequest.project_name` to an FK (the concept also leaks as
      `ReleaseChange.project_code`/`project_name`, `release_kind="project"` and
      `release_membership.project_release_id`)
- [ ] **A2** `EnvironmentGroup` + booking a group as one unit — gives
      `Booking.environment_group_id` the FK it has lacked since the March
      booking migration
- [ ] **A3** `UsageAgreement` (project A may use environment E in window W),
      checked by `BookingService`
- [ ] **A4** Project-aware contention: priority-ordered resolution and
      escalation with a named owner + response window

A1 gates A3 and A4.

## B — Environment Lifecycle & Governance ([requirements.md §2.12](../requirements.md))

- [x] **B1** Governance fields — tier, Reserved, named owner, expiry.
      [Spec](../superpowers/specs/2026-08-04-environment-governance-fields-design.md)
- [ ] **B2** Naming & tagging conventions + untagged quarantine after a grace period
- [ ] **B3** Environment Request Form + auto-generated Welcome Pack
- [ ] **B4** Soft (preemptible) vs hard (protected) reservations + time-slot bookings
- [ ] **B5** Decommissioning workflow + idle auto-detection (ghost environments)
- [ ] **B6** Forward contention as a calendar leading indicator

B1 gates B2, B3 and B5.

## What B1 established

- **Tier is a tenant-configurable table** (`environment_tier`), not an enum, and
  it *replaced* the free-text `environment_type` rather than sitting beside it.
  Each tenant's distinct values were folded onto the eight standard tiers
  case-insensitively; unrecognised values survive as tenant-specific tiers with
  a NULL `category`.
- **Reserved is derived, not stored.** An environment that is reserved is still
  active, so it is a second axis computed as a SQL `EXISTS` over live bookings —
  never an `EnvironmentStatus` value.
- **No `idle` field ships until B5.** A field reading "not idle" when it means
  "never checked" is the failure the drift work had to fix.
- **Owner and expiry are nullable in the database and required by the API.**
  Legacy rows keep a null owner rather than a fabricated one, and the gap is
  reportable via `?governance_gap=true`.
- `{draft, rejected, closed}` — "not a live claim on an environment" — now lives
  once, in `app/core/booking_states.py`. `conflict_service.TERMINAL_STATES` is
  deliberately different and must not be merged into it.
```

- [ ] **Step 2: Commit**

```bash
git add docs/phases/phase-7.md
git commit -m "docs: decompose Phase 7 and record B1 as shipped"
```

- [ ] **Step 3: Open PR 1**

```bash
git push -u github feature/env-governance-fields
gh pr create --repo pjgross/envmgr --base main \
  --title "Phase 7 B1 (backend): environment tier, owner and expiry" \
  --body "$(cat <<'EOF'
Replaces the free-text `environment_type` with a tenant-configurable
`environment_tier` table, and adds a named owner and an expiry date.

- Tier vocabulary seeded per tenant (eight standard tiers), backfilled from
  each tenant's existing distinct values folded case-insensitively — `SIT` and
  `sit` collapse to one.
- Owner and expiry are nullable in the database and required by the API, so
  legacy rows stay honest; `?governance_gap=true` reports them.
- `reserved_now` is derived in SQL from live bookings, not a stored status.
- `{draft, rejected, closed}` hoisted to one shared constant.

Spec: docs/superpowers/specs/2026-08-04-environment-governance-fields-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_013QbxUbUk3kgkp5DsUcK3Kt
EOF
)"
```

---

### Task 7: Frontend tier types, service, slice and picker hook

**Files:**
- Create: `frontend/src/types/environmentTier.ts`
- Create: `frontend/src/services/environmentTierService.ts`
- Create: `frontend/src/store/environmentTierSlice.ts`
- Modify: `frontend/src/store/index.ts`
- Create: `frontend/src/hooks/useAllEnvironmentTiers.ts`
- Test: `frontend/src/hooks/__tests__/useAllEnvironmentTiers.test.tsx`

**Interfaces:**
- Consumes: `/api/v1/environment-tiers` (Task 2)
- Produces:
  - `EnvironmentTierResponse { id, tenant_id, name, description, category, color, display_order, is_active, created_at, updated_at }`
  - `EnvironmentTierCreate`, `EnvironmentTierUpdate`
  - `environmentTierService.listTiers/createTier/updateTier/deleteTier`
  - `fetchEnvironmentTiers`, `createEnvironmentTier`, `updateEnvironmentTier`, `deleteEnvironmentTier` thunks; slice key `environmentTier`
  - `useAllEnvironmentTiers(): { tiers, loading, truncated }`

- [ ] **Step 1: Write the types**

Create `frontend/src/types/environmentTier.ts`:

```typescript
export interface EnvironmentTierResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  /** The standard tier this maps onto, or null for a tenant-specific one. */
  category: string | null;
  color: string | null;
  display_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface EnvironmentTierCreate {
  name: string;
  description?: string | null;
  color?: string | null;
  display_order?: number;
  is_active?: boolean;
}

export interface EnvironmentTierUpdate {
  name?: string;
  description?: string | null;
  color?: string | null;
  display_order?: number;
  is_active?: boolean;
}
```

- [ ] **Step 2: Write the service**

Create `frontend/src/services/environmentTierService.ts`:

```typescript
import api from './api';
import type {
  EnvironmentTierResponse,
  EnvironmentTierCreate,
  EnvironmentTierUpdate,
} from '../types/environmentTier';
import type { Paged } from '../types/pagination';

export const environmentTierService = {
  listTiers: (params?: {
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<EnvironmentTierResponse>> =>
    api.get<EnvironmentTierResponse[]>('/environment-tiers/', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  createTier: (data: EnvironmentTierCreate): Promise<EnvironmentTierResponse> =>
    api.post('/environment-tiers/', data).then((r) => r.data),

  updateTier: (
    id: number,
    data: EnvironmentTierUpdate
  ): Promise<EnvironmentTierResponse> =>
    api.patch(`/environment-tiers/${id}`, data).then((r) => r.data),

  deleteTier: (id: number): Promise<void> =>
    api.delete(`/environment-tiers/${id}`).then((r) => r.data),
};
```

- [ ] **Step 3: Write the slice**

Create `frontend/src/store/environmentTierSlice.ts`:

```typescript
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { environmentTierService } from '../services/environmentTierService';
import type {
  EnvironmentTierResponse,
  EnvironmentTierCreate,
  EnvironmentTierUpdate,
} from '../types/environmentTier';

interface EnvironmentTierState {
  tiers: EnvironmentTierResponse[];
  total: number;
  loading: boolean;
  error: string | null;
}

const initialState: EnvironmentTierState = {
  tiers: [],
  total: 0,
  loading: false,
  error: null,
};

export const fetchEnvironmentTiers = createAsyncThunk(
  'environmentTier/fetch',
  () => environmentTierService.listTiers()
);

export const createEnvironmentTier = createAsyncThunk(
  'environmentTier/create',
  (data: EnvironmentTierCreate) => environmentTierService.createTier(data)
);

export const updateEnvironmentTier = createAsyncThunk(
  'environmentTier/update',
  ({ id, data }: { id: number; data: EnvironmentTierUpdate }) =>
    environmentTierService.updateTier(id, data)
);

export const deleteEnvironmentTier = createAsyncThunk(
  'environmentTier/delete',
  async (id: number) => {
    await environmentTierService.deleteTier(id);
    return id;
  }
);

const environmentTierSlice = createSlice({
  name: 'environmentTier',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchEnvironmentTiers.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchEnvironmentTiers.fulfilled, (state, action) => {
        state.loading = false;
        state.tiers = action.payload.rows;
        state.total = action.payload.total;
      })
      .addCase(fetchEnvironmentTiers.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load tiers';
      })
      .addCase(createEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = [...state.tiers, action.payload].sort(
          (a, b) => a.display_order - b.display_order || a.id - b.id
        );
        state.total += 1;
      })
      .addCase(updateEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = state.tiers.map((t) =>
          t.id === action.payload.id ? action.payload : t
        );
      })
      .addCase(deleteEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = state.tiers.filter((t) => t.id !== action.payload);
        state.total -= 1;
      });
  },
});

export default environmentTierSlice.reducer;
```

The list surgery in the fulfilled cases is safe here specifically because the
tier list is a small admin vocabulary this panel fetches whole — unlike a paged
grid slice, where splicing a created row into one window is wrong.

- [ ] **Step 4: Register the reducer**

In `frontend/src/store/index.ts`, import the reducer and add it to the
`configureStore` reducer map with the key `environmentTier`, matching the
surrounding entries exactly.

- [ ] **Step 5: Write the picker hook**

Create `frontend/src/hooks/useAllEnvironmentTiers.ts`:

```typescript
import { environmentTierService } from '../services/environmentTierService';
import { useSharedList } from './useSharedList';
import type { EnvironmentTierResponse } from '../types/environmentTier';

// `GET /environment-tiers/` defaults to 500 server-side; asked for explicitly
// so the number a picker can see is visible at this call site.
const LIMIT = 500;

const load = () => environmentTierService.listTiers({ limit: LIMIT });

/**
 * Every tier, for a picker.
 *
 * NOT `state.environmentTier.tiers`: that is the admin panel's list, which may
 * not be loaded on an environment page at all. A picker reading a paged slice
 * silently offers a subset — the class of bug the pagination programme exists
 * to remove.
 */
export function useAllEnvironmentTiers(): {
  tiers: EnvironmentTierResponse[];
  loading: boolean;
  truncated: boolean;
} {
  const { rows, loading, truncated } = useSharedList<EnvironmentTierResponse>(
    'environment-tiers',
    load
  );
  return { tiers: rows, loading, truncated };
}
```

- [ ] **Step 6: Write the hook test**

Create `frontend/src/hooks/__tests__/useAllEnvironmentTiers.test.tsx`. Copy the
structure of the existing `useAllEnvironments` test if one exists
(`ls frontend/src/hooks/__tests__/`); otherwise:

```typescript
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { useAllEnvironmentTiers } from '../useAllEnvironmentTiers';
import { environmentTierService } from '../../services/environmentTierService';

vi.mock('../../services/environmentTierService', () => ({
  environmentTierService: { listTiers: vi.fn() },
}));

describe('useAllEnvironmentTiers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns every tier and reports truncation honestly', async () => {
    vi.mocked(environmentTierService.listTiers).mockResolvedValue({
      rows: [{ id: 1, name: 'SIT' }] as never,
      total: 9,
    });

    const { result } = renderHook(() => useAllEnvironmentTiers());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.tiers).toHaveLength(1);
    expect(result.current.truncated).toBe(true);
  });

  it('coalesces two consumers mounting in the same commit into one request', async () => {
    vi.mocked(environmentTierService.listTiers).mockResolvedValue({
      rows: [],
      total: 0,
    });

    const { result: a } = renderHook(() => useAllEnvironmentTiers());
    const { result: b } = renderHook(() => useAllEnvironmentTiers());

    await waitFor(() => expect(a.current.loading).toBe(false));
    await waitFor(() => expect(b.current.loading).toBe(false));
    expect(environmentTierService.listTiers).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 7: Run the test**

Run: `npm test -- useAllEnvironmentTiers`
Expected: PASS, 2 passed

- [ ] **Step 8: Typecheck and commit**

Run: `npm run build`
Expected: no TypeScript errors

```bash
git add frontend/src/types/environmentTier.ts frontend/src/services/environmentTierService.ts \
        frontend/src/store/environmentTierSlice.ts frontend/src/store/index.ts \
        frontend/src/hooks/useAllEnvironmentTiers.ts \
        frontend/src/hooks/__tests__/useAllEnvironmentTiers.test.tsx
git commit -m "feat: add environment tier types, service, slice and picker hook"
```

---

### Task 8: Admin tier configuration panel

**Files:**
- Create: `frontend/src/components/admin/EnvironmentTiersPanel.tsx`
- Modify: `frontend/src/pages/admin/EntityConfig.tsx`
- Test: `frontend/src/components/admin/__tests__/environmentTiersPanel.test.tsx`

**Interfaces:**
- Consumes: the slice and types from Task 7
- Produces: `EnvironmentTiersPanel` default export

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/admin/__tests__/environmentTiersPanel.test.tsx`:

```typescript
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnvironmentTiersPanel from '../EnvironmentTiersPanel';
import environmentTierReducer from '../../../store/environmentTierSlice';
import { environmentTierService } from '../../../services/environmentTierService';

vi.mock('../../../services/environmentTierService', () => ({
  environmentTierService: {
    listTiers: vi.fn(),
    createTier: vi.fn(),
    updateTier: vi.fn(),
    deleteTier: vi.fn(),
  },
}));

function renderPanel() {
  const store = configureStore({
    reducer: { environmentTier: environmentTierReducer },
  });
  return render(
    <Provider store={store}>
      <EnvironmentTiersPanel />
    </Provider>
  );
}

const TIERS = [
  {
    id: 1,
    tenant_id: 1,
    name: 'Dev',
    description: null,
    category: 'dev',
    color: '#90A4AE',
    display_order: 10,
    is_active: true,
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
  },
  {
    id: 2,
    tenant_id: 1,
    name: 'Production',
    description: null,
    category: 'production',
    color: '#EF5350',
    display_order: 70,
    is_active: false,
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
  },
];

describe('EnvironmentTiersPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(environmentTierService.listTiers).mockResolvedValue({
      rows: TIERS,
      total: 2,
    });
  });

  it('lists tiers in progression order with their active state', async () => {
    renderPanel();

    await waitFor(() => expect(screen.getByText('Dev')).toBeInTheDocument());
    expect(screen.getByText('Production')).toBeInTheDocument();
    expect(screen.getByText('Inactive')).toBeInTheDocument();
  });

  it('surfaces the in-use conflict when a delete is refused', async () => {
    vi.mocked(environmentTierService.deleteTier).mockRejectedValue(
      new Error('This tier is in use by one or more environments')
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('Dev')).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole('button', { name: /delete/i })[0]);
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(
        screen.getByText(/in use by one or more environments/i)
      ).toBeInTheDocument()
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- environmentTiersPanel`
Expected: FAIL — cannot resolve `../EnvironmentTiersPanel`

- [ ] **Step 3: Write the panel**

Create `frontend/src/components/admin/EnvironmentTiersPanel.tsx`:

```typescript
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchEnvironmentTiers,
  createEnvironmentTier,
  updateEnvironmentTier,
  deleteEnvironmentTier,
} from '../../store/environmentTierSlice';
import type { EnvironmentTierResponse } from '../../types/environmentTier';

export default function EnvironmentTiersPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { tiers, loading } = useSelector((s: RootState) => s.environmentTier);

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('#90A4AE');
  const [newOrder, setNewOrder] = useState(100);
  const [createError, setCreateError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<EnvironmentTierResponse | null>(null);
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState('');
  const [editOrder, setEditOrder] = useState(0);
  const [editActive, setEditActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<EnvironmentTierResponse | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchEnvironmentTiers());
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreateError(null);
    const result = await dispatch(
      createEnvironmentTier({
        name: newName.trim(),
        color: newColor,
        display_order: newOrder,
        is_active: true,
      })
    );
    if (createEnvironmentTier.rejected.match(result)) {
      setCreateError(result.error.message ?? 'Failed to create tier');
      return;
    }
    setCreateOpen(false);
    setNewName('');
  };

  const openEdit = (row: EnvironmentTierResponse) => {
    setEditTarget(row);
    setEditName(row.name);
    setEditColor(row.color ?? '#90A4AE');
    setEditOrder(row.display_order);
    setEditActive(row.is_active);
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!editTarget || !editName.trim()) return;
    setEditError(null);
    const result = await dispatch(
      updateEnvironmentTier({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          color: editColor,
          display_order: editOrder,
          is_active: editActive,
        },
      })
    );
    if (updateEnvironmentTier.rejected.match(result)) {
      setEditError(result.error.message ?? 'Failed to update tier');
      return;
    }
    setEditTarget(null);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    const result = await dispatch(deleteEnvironmentTier(deleteTarget.id));
    if (deleteEnvironmentTier.rejected.match(result)) {
      // The backend refuses 409 while environments still reference the tier.
      setDeleteError(result.error.message ?? 'Failed to delete tier');
      return;
    }
    setDeleteTarget(null);
  };

  const columns: GridColDef<EnvironmentTierResponse>[] = [
    {
      field: 'name',
      headerName: 'Tier',
      flex: 1,
      renderCell: (params) => (
        <Chip
          label={params.row.name}
          size="small"
          sx={{
            bgcolor: params.row.color ?? undefined,
            color: params.row.color ? 'common.white' : undefined,
          }}
        />
      ),
    },
    { field: 'display_order', headerName: 'Order', width: 100 },
    {
      field: 'category',
      headerName: 'Standard tier',
      flex: 1,
      renderCell: (params) => params.row.category ?? '—',
    },
    {
      field: 'is_active',
      headerName: 'Status',
      width: 120,
      renderCell: (params) => (
        <Chip
          label={params.row.is_active ? 'Active' : 'Inactive'}
          color={params.row.is_active ? 'success' : 'default'}
          size="small"
        />
      ),
    },
    {
      field: 'actions',
      headerName: '',
      width: 160,
      sortable: false,
      renderCell: (params) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Button size="small" onClick={() => openEdit(params.row)}>
            Edit
          </Button>
          <Button size="small" color="error" onClick={() => setDeleteTarget(params.row)}>
            Delete
          </Button>
        </Box>
      ),
    },
  ];

  return (
    <Box sx={{ mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Environment Tiers</Typography>
        <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
          + New Tier
        </Button>
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        An inactive tier is hidden from pickers but still shown on environments
        already using it. A tier in use cannot be deleted.
      </Typography>

      <DataGrid
        rows={tiers}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Environment Tier</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {createError && <Alert severity="error">{createError}</Alert>}
          <TextField
            label="Name"
            required
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <TextField
            label="Colour"
            type="color"
            value={newColor}
            onChange={(e) => setNewColor(e.target.value)}
          />
          <TextField
            label="Display order"
            type="number"
            value={newOrder}
            onChange={(e) => setNewOrder(Number(e.target.value))}
            helperText="Lower numbers sort first — tiers have a progression, not an alphabet."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={!newName.trim()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editTarget)} onClose={() => setEditTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Environment Tier</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {editError && <Alert severity="error">{editError}</Alert>}
          <TextField
            label="Name"
            required
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <TextField
            label="Colour"
            type="color"
            value={editColor}
            onChange={(e) => setEditColor(e.target.value)}
          />
          <TextField
            label="Display order"
            type="number"
            value={editOrder}
            onChange={(e) => setEditOrder(Number(e.target.value))}
          />
          <TextField
            select
            label="Status"
            value={editActive ? 'active' : 'inactive'}
            onChange={(e) => setEditActive(e.target.value === 'active')}
          >
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="inactive">Inactive</MenuItem>
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleEditSave} disabled={!editName.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Environment Tier</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Delete <strong>{deleteTarget?.name}</strong>? Environments still using
            it will block this.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteConfirm}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
```

- [ ] **Step 4: Run the test**

Run: `npm test -- environmentTiersPanel`
Expected: PASS, 2 passed

- [ ] **Step 5: Add the tab**

In `frontend/src/pages/admin/EntityConfig.tsx`:

Import the panel beside the other panel imports:

```typescript
import EnvironmentTiersPanel from '../../components/admin/EnvironmentTiersPanel';
```

Add a constant beside `LIFECYCLE_SUPPORTED` and `EVENT_TYPES_SUPPORTED`:

```typescript
// Entities that have a tier vocabulary.
const TIERS_SUPPORTED: EntityType[] = ['environment'];
```

Compute `hasTiers` the same way the file computes `hasLifecycle` / `hasEventTypes`,
add the tab to the `<Tabs>` strip after "Custom Fields":

```tsx
          {hasTiers && <Tab label="Tiers" />}
```

and render `<EnvironmentTiersPanel />` for that tab index, following exactly how
the file selects between `CustomFieldDefinitionManager`, `LifecycleTemplatesPanel`
and `ReleaseEventTypesPanel`. Because tab indices are positional, place the
Tiers tab and its panel branch in the same position in both lists.

- [ ] **Step 6: Verify in the browser**

Start the app if it is not running (`docker-compose up -d`, then `uvicorn` and
`npm run dev` per CLAUDE.md), log in as `admin` / `admin123` (tenant `demo`) and
open http://localhost:5173/admin/config/environment

Confirm: the Tiers tab exists; the eight standard tiers are listed in
progression order (Dev before UAT before Production); creating a tier works;
deleting one that an environment uses shows the in-use error rather than
succeeding.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/admin/EnvironmentTiersPanel.tsx \
        frontend/src/components/admin/__tests__/environmentTiersPanel.test.tsx \
        frontend/src/pages/admin/EntityConfig.tsx
git commit -m "feat: add environment tier admin panel"
```

---

### Task 9: Environment list — columns, filters and form

**Files:**
- Modify: `frontend/src/types/environment.ts`
- Modify: `frontend/src/services/environmentService.ts`
- Modify: `frontend/src/store/environmentSlice.ts:42-53`
- Modify: `frontend/src/utils/dates.ts`
- Modify: `frontend/src/pages/environments/EnvironmentList.tsx`
- Modify: `frontend/src/pages/environments/__tests__/environmentListServerGrid.test.tsx`
- Test: `frontend/src/utils/__tests__/expiry.test.ts`

**Interfaces:**
- Consumes: `useAllEnvironmentTiers` (Task 7), the API from Tasks 3–4
- Produces: `formatExpiry(iso: string | null): string`

- [ ] **Step 1: Update the types**

In `frontend/src/types/environment.ts`, replace `environment_type` in the three
interfaces:

```typescript
export interface EnvironmentResponse {
  id: number;
  name: string;
  description: string | null;
  tier_id: number;
  tier_name: string;
  tier_color: string | null;
  owner_user_id: number | null;
  owner_username: string | null;
  expires_at: string | null;
  reserved_now: boolean;
  status: EnvironmentStatus;
  tenant_id: number;
  custom_fields: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface EnvironmentCreate {
  name: string;
  description?: string;
  tier_id: number;
  owner_user_id: number;
  expires_at: string;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}

export interface EnvironmentUpdate {
  name?: string;
  description?: string;
  tier_id?: number;
  owner_user_id?: number;
  expires_at?: string;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}
```

In `frontend/src/types/release.ts:280`, rename `environment_type: string;` to
`tier_name: string;` on the coverage environment type.

- [ ] **Step 2: Update the service and slice params**

In `frontend/src/services/environmentService.ts`, replace the
`environment_type?: string;` param on `listEnvironments` with:

```typescript
    tier_id?: number;
    owner_user_id?: number;
    expiring_within_days?: number;
    governance_gap?: boolean;
```

Make the identical change to the `fetchEnvironments` thunk's param type in
`frontend/src/store/environmentSlice.ts:44-52`.

- [ ] **Step 3: Write the failing expiry test**

Create `frontend/src/utils/__tests__/expiry.test.ts`:

```typescript
import { describe, expect, it, vi, afterEach } from 'vitest';

import { formatExpiry } from '../dates';

describe('formatExpiry', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('says how long is left rather than making the reader do the arithmetic', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T00:00:00Z'));
    expect(formatExpiry('2026-08-16T00:00:00Z')).toBe('in 12 days');
  });

  it('marks an expiry in the past as overdue', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T00:00:00Z'));
    expect(formatExpiry('2026-08-01T00:00:00Z')).toBe('overdue by 3 days');
  });

  it('distinguishes "no expiry set" from "expires today"', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-04T00:00:00Z'));
    expect(formatExpiry(null)).toBe('Not set');
    expect(formatExpiry('2026-08-04T12:00:00Z')).toBe('today');
  });
});
```

- [ ] **Step 4: Run it to verify it fails**

Run: `npm test -- expiry`
Expected: FAIL — `formatExpiry` is not exported from `../dates`

- [ ] **Step 5: Implement `formatExpiry`**

Append to `frontend/src/utils/dates.ts`:

```typescript
/**
 * Relative expiry copy.
 *
 * An absolute date alone makes the reader do the arithmetic the field exists
 * to prompt — "2026-11-02" does not read as urgent, "in 4 days" does. Null is
 * "Not set", never "today": no expiry and an expiry that lands now are
 * different facts.
 */
export function formatExpiry(iso: string | null): string {
  if (!iso) return 'Not set';
  const MS_PER_DAY = 24 * 60 * 60 * 1000;
  const days = Math.floor(
    (new Date(iso).getTime() - Date.now()) / MS_PER_DAY
  );
  if (days === 0) return 'today';
  if (days > 0) return `in ${days} day${days === 1 ? '' : 's'}`;
  const overdue = Math.abs(days);
  return `overdue by ${overdue} day${overdue === 1 ? '' : 's'}`;
}
```

- [ ] **Step 6: Run it to verify it passes**

Run: `npm test -- expiry`
Expected: PASS, 3 passed

- [ ] **Step 7: Update the list columns**

In `frontend/src/pages/environments/EnvironmentList.tsx`, replace the
`environment_type` column in `environmentColumns` with these four, keeping
`name`, `status`, `created_at` and `actions` as they are:

```tsx
  {
    field: 'tier',
    headerName: 'Tier',
    flex: 1,
    hideable: false,
    renderCell: (params) => (
      <Chip
        label={params.row.tier_name}
        size="small"
        sx={{
          bgcolor: params.row.tier_color ?? undefined,
          color: params.row.tier_color ? 'common.white' : undefined,
        }}
      />
    ),
  },
  {
    field: 'owner',
    headerName: 'Owner',
    flex: 1,
    renderCell: (params) => params.row.owner_username ?? '— unowned',
  },
  {
    field: 'expires_at',
    headerName: 'Expires',
    flex: 0.9,
    renderCell: (params) => (
      <Typography
        variant="body2"
        color={
          params.row.expires_at && new Date(params.row.expires_at) < new Date()
            ? 'error.main'
            : 'text.primary'
        }
      >
        {formatExpiry(params.row.expires_at)}
      </Typography>
    ),
  },
  {
    field: 'reserved_now',
    headerName: 'Reserved',
    flex: 0.7,
    sortable: false,
    renderCell: (params) =>
      params.row.reserved_now ? (
        <Chip label="Reserved" size="small" color="info" />
      ) : (
        '—'
      ),
  },
```

`reserved_now` is `sortable: false`: it is not in the backend's sort whitelist,
and a header that looks clickable and 422s on click is the exact failure
`test_sort_whitelist_contract` exists to prevent.

Also update the comment block above `environmentColumns` — it names the old
sortable set — to: `name, tier, status, owner, expires_at, created_at`.

Add the import:

```typescript
import { formatExpiry } from '../../utils/dates';
```

- [ ] **Step 8: Update the filters**

Change the `useServerGrid` call:

```typescript
  const grid = useServerGrid({
    endpoint: 'environments',
    filterKeys: ['search', 'status', 'tier_id', 'governance_gap'],
    debounceKeys: ['search'],
    onFetch: (params) => dispatch(fetchEnvironments(params)),
    total,
    totalPending: listLoading,
  });
```

Add a tier filter and a governance-gap toggle next to the status chips:

```tsx
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        {STATUS_FILTERS.map((f) => (
          <Chip
            key={f.value}
            label={f.label}
            clickable
            color={(grid.filters.status ?? 'all') === f.value ? 'primary' : 'default'}
            variant={(grid.filters.status ?? 'all') === f.value ? 'filled' : 'outlined'}
            onClick={() => grid.setFilter('status', f.value)}
          />
        ))}
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Tier</InputLabel>
          <Select
            label="Tier"
            value={grid.filters.tier_id ?? ''}
            onChange={(e) => grid.setFilter('tier_id', e.target.value)}
          >
            {/* '' is the no-selection value, NOT 'all': a filter vocabulary
                containing 'all' collides with buildParams' own sentinel, and
                both states then build byte-identical params so the grid never
                refetches. */}
            <MenuItem value="">Any tier</MenuItem>
            {tiers
              .filter((t) => t.is_active)
              .map((t) => (
                <MenuItem key={t.id} value={t.id}>
                  {t.name}
                </MenuItem>
              ))}
          </Select>
        </FormControl>
        <Chip
          label="Missing owner or expiry"
          clickable
          color={grid.filters.governance_gap === 'true' ? 'warning' : 'default'}
          variant={grid.filters.governance_gap === 'true' ? 'filled' : 'outlined'}
          onClick={() =>
            grid.setFilter(
              'governance_gap',
              grid.filters.governance_gap === 'true' ? '' : 'true'
            )
          }
        />
      </Box>
```

with `const { tiers } = useAllEnvironmentTiers();` added near the other hooks and
the import:

```typescript
import { useAllEnvironmentTiers } from '../../hooks/useAllEnvironmentTiers';
```

Check `frontend/src/hooks/serverGridParams.ts` for how `buildParams` treats
empty-string values before relying on `''` as the no-selection value; if it
requires `undefined`, use that instead and keep the comment.

- [ ] **Step 9: Update the create/edit form**

Replace `EnvFormValues`, `emptyForm`, the `openEdit` body, the validation in
`handleSave`, the two payload objects, and the Environment Type text field:

```typescript
interface EnvFormValues {
  name: string;
  description: string;
  tier_id: number | '';
  owner_user_id: number | '';
  expires_at: string;
  status: EnvironmentStatus;
}

const emptyForm: EnvFormValues = {
  name: '',
  description: '',
  tier_id: '',
  owner_user_id: '',
  expires_at: '',
  status: 'active',
};
```

`openEdit`:

```typescript
    setForm({
      name: env.name,
      description: env.description ?? '',
      tier_id: env.tier_id,
      owner_user_id: env.owner_user_id ?? '',
      expires_at: env.expires_at ? env.expires_at.slice(0, 10) : '',
      status: env.status,
    });
```

`handleSave` validation, replacing the `environment_type` check:

```typescript
    if (!form.tier_id) {
      setFormError('Tier is required');
      return;
    }
    if (!form.owner_user_id) {
      setFormError('A named owner is required');
      return;
    }
    if (!form.expires_at) {
      setFormError('An expiry date is required');
      return;
    }
```

and both payloads use:

```typescript
          tier_id: Number(form.tier_id),
          owner_user_id: Number(form.owner_user_id),
          expires_at: new Date(`${form.expires_at}T00:00:00Z`).toISOString(),
```

The form fields, replacing the Environment Type `TextField`:

```tsx
          <FormControl fullWidth required>
            <InputLabel>Tier</InputLabel>
            <Select
              label="Tier"
              value={form.tier_id}
              onChange={(e) => setForm({ ...form, tier_id: Number(e.target.value) })}
            >
              {tiers
                .filter((t) => t.is_active || t.id === form.tier_id)
                .map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    {t.name}
                  </MenuItem>
                ))}
            </Select>
          </FormControl>
          <FormControl fullWidth required>
            <InputLabel>Owner</InputLabel>
            <Select
              label="Owner"
              value={form.owner_user_id}
              onChange={(e) =>
                setForm({ ...form, owner_user_id: Number(e.target.value) })
              }
            >
              {users.map((u) => (
                <MenuItem key={u.id} value={u.id}>
                  {u.username}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Expires"
            type="date"
            required
            value={form.expires_at}
            onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
            InputLabelProps={{ shrink: true }}
            fullWidth
          />
```

An inactive tier stays selectable **only** when it is the one already on this
environment, so editing an environment on a retired tier does not silently
change its tier.

For `users`, fetch the picker list in this component:

```typescript
  const [users, setUsers] = useState<Array<{ id: number; username: string }>>([]);
  useEffect(() => {
    // GET /tenant/users/lite is knowingly unbounded — one of the five
    // growth-bearing endpoints docs/pagination.md lists as not yet bounded.
    // Adding a consumer here is deliberate; bounding it is that item's job.
    api
      .get<Array<{ id: number; username: string }>>('/tenant/users/lite')
      .then((r) => setUsers(r.data))
      .catch(() => setUsers([]));
  }, []);
```

with `import api from '../../services/api';` added. (`GatesTable.tsx` calls this
endpoint the same way — match it.)

- [ ] **Step 10: Update the grid test**

In `frontend/src/pages/environments/__tests__/environmentListServerGrid.test.tsx`,
the fixture row at line ~19 uses `environment_type`. Replace it with the new
shape, and change the sortable-field loop at line ~159:

```typescript
    ['name', 'tier', 'status', 'owner', 'expires_at', 'created_at'].forEach((f) =>
```

Add a test asserting the reserved column is not sortable:

```typescript
  it('leaves reserved_now unsortable — it is not in the backend whitelist', () => {
    const col = environmentColumns.find((c) => c.field === 'reserved_now');
    expect(col?.sortable).toBe(false);
  });
```

- [ ] **Step 11: Run the frontend suite**

Run: `npm test -- environmentList`
Expected: PASS

Run: `npm test`
Expected: PASS, no new failures

Run: `npm run build`
Expected: no TypeScript errors

- [ ] **Step 12: Commit**

```bash
git add frontend/src/types/ frontend/src/services/environmentService.ts \
        frontend/src/store/environmentSlice.ts frontend/src/utils/dates.ts \
        frontend/src/utils/__tests__/expiry.test.ts \
        frontend/src/pages/environments/
git commit -m "feat: show tier, owner, expiry and reserved on the environment list"
```

---

### Task 10: Environment detail — form and governance panel

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

**Interfaces:**
- Consumes: `useAllEnvironmentTiers` (Task 7), `formatExpiry` (Task 9)
- Produces: nothing new

`EnvironmentDetail.tsx` carries its own copy of the environment form (lines
~87, ~129, ~177, ~193, ~648, ~701), so all of it changes the same way the list's
did.

- [ ] **Step 1: Update the form state and handlers**

At line ~87 the local form interface declares `environment_type: string`.
Replace it and the `emptyForm`-equivalent at ~129 with the same shape used in
Task 9:

```typescript
  tier_id: number | '';
  owner_user_id: number | '';
  expires_at: string;
```

At ~177 (populating the form from `currentEnvironment`) use:

```typescript
        tier_id: currentEnvironment.tier_id,
        owner_user_id: currentEnvironment.owner_user_id ?? '',
        expires_at: currentEnvironment.expires_at
          ? currentEnvironment.expires_at.slice(0, 10)
          : '',
```

At ~193 (the save payload):

```typescript
        tier_id: Number(envForm.tier_id),
        owner_user_id: Number(envForm.owner_user_id),
        expires_at: new Date(`${envForm.expires_at}T00:00:00Z`).toISOString(),
```

- [ ] **Step 2: Replace the form field**

At ~648, replace the Environment Type `TextField` with the Tier select, Owner
select and Expires date field exactly as written in Task 9 Step 9, using
`envForm`/`setEnvForm` instead of `form`/`setForm`, and the same
`useAllEnvironmentTiers()` and `/tenant/users/lite` sources.

- [ ] **Step 3: Replace the read-only render with a governance panel**

At ~701, `<Typography>{currentEnvironment?.environment_type}</Typography>`
becomes a governance block:

```tsx
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Chip
                      label={currentEnvironment?.tier_name}
                      size="small"
                      sx={{
                        bgcolor: currentEnvironment?.tier_color ?? undefined,
                        color: currentEnvironment?.tier_color ? 'common.white' : undefined,
                      }}
                    />
                    {currentEnvironment?.reserved_now && (
                      <Chip label="Reserved now" size="small" color="info" />
                    )}
                  </Box>
                  <Typography variant="body2">
                    Owner: {currentEnvironment?.owner_username ?? '— unowned'}
                  </Typography>
                  <Typography
                    variant="body2"
                    color={
                      currentEnvironment?.expires_at &&
                      new Date(currentEnvironment.expires_at) < new Date()
                        ? 'error.main'
                        : 'text.secondary'
                    }
                  >
                    Expires: {formatExpiry(currentEnvironment?.expires_at ?? null)}
                  </Typography>
                </Box>
```

with `import { formatExpiry } from '../../utils/dates';` added.

- [ ] **Step 4: Typecheck and run the suite**

Run: `npm run build`
Expected: no TypeScript errors

Run: `npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentDetail.tsx
git commit -m "feat: add the governance panel and fields to environment detail"
```

---

### Task 11: Open the pages

**Files:** none — this is verification, and it is not optional.

Six defects in the pagination programme were found **only** by opening the page,
every one of them with a fully green suite. One was found by the user, not by
the implementer.

- [ ] **Step 1: Start the app**

```bash
docker-compose up -d
cd backend && alembic upgrade head && uvicorn app.main:app --reload
```

and in another terminal:

```bash
cd frontend && npm run dev
```

Log in at http://localhost:5173 as `admin` / `admin123`, tenant `demo`.

- [ ] **Step 2: Verify the migration ran against real data**

The dev database held four environments typed `SIT`, `SIT`, `uat`, `sit`.
Confirm the fold:

```bash
docker exec envmgr-postgres psql -U envmgr -d envmgr -c \
  "SELECT e.name, t.name AS tier, t.category FROM environment e JOIN environment_tier t ON t.id = e.tier_id ORDER BY e.name;"
```

Expected: three environments on tier `SIT` (the two `SIT` rows and the `sit`
one), one on `UAT`; no tier named `sit`.

- [ ] **Step 3: Walk the environment list**

At http://localhost:5173/environments confirm:
- the Tier column renders coloured badges, not raw text
- Owner reads "— unowned" for the four legacy rows, not blank
- Expires reads "Not set" for them, not "overdue"
- clicking the **Tier** header re-sorts and does not 422 (check the network tab)
- clicking **Reserved** does nothing — it is not sortable
- the tier filter changes the result set, and switching it back to "Any tier"
  **refetches** (this is the `all`-sentinel collision: if both states build the
  same params, the grid silently keeps the old rows)
- "Missing owner or expiry" returns the legacy rows and the footer count matches

- [ ] **Step 4: Walk the forms**

- Create an environment: the tier and owner pickers are populated, all three
  fields are required, and the new row appears with its badge and owner.
- Edit one of the **legacy** environments and change only the description: the
  form must refuse to save until an owner and expiry are supplied. This is the
  compliance rule and it is the single most likely thing to be wrong.
- Edit a compliant environment and change only the description: it saves.

- [ ] **Step 5: Check reserved**

Find or create a booking that covers now on one environment, in a status that is
not draft/rejected/closed. Its row must show the Reserved chip; a draft booking
on another environment must not.

- [ ] **Step 6: Walk the admin panel**

At http://localhost:5173/admin/config/environment → Tiers: the eight standard
tiers plus any tenant-specific ones from the backfill; create, edit, deactivate;
deleting a tier in use shows the in-use error.

- [ ] **Step 7: Record what you saw**

Note anything surprising in the PR description. If a defect turns up, fix it
with a test that would have caught it — the point of this task is that the suite
was green and the page was still wrong.

- [ ] **Step 8: Open PR 2**

```bash
git push
gh pr create --repo pjgross/envmgr --base main \
  --title "Phase 7 B1 (frontend): tier, owner, expiry and reserved" \
  --body "$(cat <<'EOF'
Frontend half of Phase 7 B1.

- Admin tier configuration on /admin/config/environment
- Tier badge, Owner, Expires and Reserved on the environment list, with tier
  and governance-gap filters
- Tier / owner / expiry required in both copies of the environment form
- Governance panel on environment detail

Verified in the browser, not only by the suite — see the checklist in the plan.

Spec: docs/superpowers/specs/2026-08-04-environment-governance-fields-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_013QbxUbUk3kgkp5DsUcK3Kt
EOF
)"
```

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| `environment_tier` table with the eight standard tiers | 1 |
| `category` a plain VARCHAR, not SAEnum | 1 |
| Seeding via `environment_tier_defaults.py` from `create_tenant` | 1 |
| Name uniqueness in the service, not a partial index | 2 |
| Tier CRUD, pagination, `display_order` + `id` tiebreaker | 2 |
| `is_active` hides from pickers but still renders | 8, 9 |
| Delete refused while referenced; soft-deleted envs don't count | 2, 3 |
| `tier_id` NOT NULL, `environment_type` dropped | 3 |
| Owner + expiry nullable in DB, required by API | 3 |
| PATCH compliance rule | 3 |
| Migration with case-insensitive fold and `Other` fallback | 3, 5 |
| Consumer sweep (releases, coverage schema, excel import) | 3 |
| Display names travel with the row | 3 |
| `reserved_now` in SQL, half-open window | 4 |
| Shared `INACTIVE_BOOKING_STATUSES`; `TERMINAL_STATES` untouched | 4 |
| No `idle` field | 4 |
| `expiring_within_days` excludes null expiry | 3, 5 |
| `governance_gap` filter | 3, 5 |
| `environment_type` query param dropped | 3, 5 |
| Sort whitelist: tier, owner, expires_at | 3, 5 |
| Contract JSON updated | 5 |
| Migration test on a scratch database | 5 |
| Case-folded sort asserted on rendered order | 5 |
| Tenant isolation on the new FKs | 2, 3 |
| Spreadsheet import falls back to Other, creates no tier | 3 (implementation + test) |
| Tier deletable once its only environment is soft-deleted | 3 |
| Admin Tiers tab on the existing config page | 8 |
| List columns, filters, `all`-sentinel avoidance | 9 |
| Both copies of the environment form | 9, 10 |
| Governance panel on detail | 10 |
| `phase-7.md` corrected | 6 |
| Open the pages | 11 |
