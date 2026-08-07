# Environment Groups and Atomic Group Bookings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an `EnvironmentGroup` entity, let a booking request name groups instead of listing environments, and make a group's member bookings transition atomically.

**Architecture:** `EnvironmentGroup` + `environment_group_member` follow `Project`/`usage_agreement` exactly — a tenant-scoped vocabulary plus a junction table, because an environment may belong to multiple groups. `booking.environment_group_id` finally gets its foreign key; it is written once at create, records **provenance not a live link**, and is the atomic-unit key. Atomicity is a new endpoint that validates every member before mutating any.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 (backend); React 18, TypeScript, MUI, Redux Toolkit (frontend). Tests: pytest (SQLite + PostgreSQL), vitest.

**Spec:** [docs/superpowers/specs/2026-08-07-environment-group-design.md](../specs/2026-08-07-environment-group-design.md)

## Global Constraints

- Every query on a tenant-scoped table filters by `current_user.active_tenant_id` — **never** `.tenant_id`, which is wrong under master-admin impersonation.
- Cross-tenant ids return **404, never 403**, on **create and on update**. Across the last three sub-projects this same missing filter appeared **eight times** and was never caught by a pre-existing test. **Assume every tenant filter you write is unguarded until you have watched a named test fail without it.**
- **Every FK validation on an update path must accept the stored value even when the referenced row is archived**, and refuse only a *new* assignment. `environment_service.py` carries this rule in a comment naming the failure mode; A1 still shipped the bug on three paths.
- List endpoints take `page: Page = Depends(pagination())`, order by a **unique** key (append the primary key), and emit `X-Total-Count` via `set_total_count`.
- **Every filter runs in SQL.** A Python-side filter on a bounded endpoint windows the page before filtering.
- Migrations are hand-written — never `--autogenerate`. **`tests/test_migration_schema_drift.py` compares only column NAME SETS**, so a passing run is not evidence the migration matches its models.
- Entities soft-delete (`deleted_at`); `environment_group_member` soft-deletes too (see Task 1).
- Services never call `db.commit()`. Use `db.flush()` for an assigned id.
- **A2 adds no enforcement and does not touch `usage_agreement`.** That table stays exactly as A1 shipped it.
- **`booking.environment_group_id` is provenance, not a live link.** Never resolve a booking's environments by re-reading the group.
- Frontend thunks `rejectWithValue(formatApiError(err, ...))`; components read `result.payload`. Test fixtures reject with an **AxiosError shape** — a plain `Error` carrying the final text passes while the app is broken.
- Pickers use a `useSharedList`-backed hook, never a page-scoped slice. A new list filter spells "no selection" `any`, never `all` — `buildParams` drops `all`, so both states build identical params and the grid never refetches.
- Backend from `backend/` via `uv run`; frontend from `frontend/`.
- **Do not run the full test suite in a task** — run the focused tests named. The controller runs full suites.
- PostgreSQL leg: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q -p no:logging`

## File Structure

**Backend — create**
- `app/db/models/environment_group.py` — `EnvironmentGroup`, `EnvironmentGroupMember`
- `app/db/migrations/versions/20260808_1000_envgroups_add_environment_groups.py`
- `app/api/v1/schemas/environment_group.py`
- `app/services/environment_group_service.py`
- `app/api/v1/environment_groups.py`
- `tests/test_environment_group_model.py`, `tests/integration/test_environment_groups_api.py`,
  `tests/integration/test_environment_group_members_api.py`,
  `tests/integration/test_environment_groups_authz.py`,
  `tests/integration/test_group_booking_create.py`, `tests/integration/test_group_transition.py`

**Backend — modify**
- `app/db/models/booking.py` — the FK on the existing column
- `app/db/models/__init__.py`, `app/main.py`, `tests/factories.py`, `tests/test_pagination.py`
- `app/api/v1/schemas/booking_request.py`, `app/services/booking_request_service.py`
- `app/services/booking_service.py`, `app/api/v1/booking_requests.py`
- `app/api/v1/environments.py` — `GET /environments/{id}/groups`

**Frontend — create**
- `src/types/environmentGroup.ts`, `src/services/environmentGroupService.ts`, `src/store/environmentGroupSlice.ts`
- `src/hooks/useAllEnvironmentGroups.ts`
- `src/pages/admin/EnvironmentGroups.tsx`, `src/pages/admin/EnvironmentGroupDetail.tsx`
- `src/components/bookings/GroupTransitionPanel.tsx`
- matching `__tests__/` files

**Frontend — modify**
- `src/App.tsx`, `src/pages/admin/AdminLayout.tsx`, `src/store/index.ts`
- `src/pages/bookings/BookingForm.tsx`, `src/pages/bookings/BookingDetail.tsx`
- `src/pages/environments/EnvironmentDetail.tsx`
- `src/types/booking.ts`, `src/types/bookingRequest.ts`

---

### Task 1: Models, migration, factories

**Files:**
- Create: `backend/app/db/models/environment_group.py`, `backend/app/db/migrations/versions/20260808_1000_envgroups_add_environment_groups.py`
- Modify: `backend/app/db/models/booking.py`, `backend/app/db/models/__init__.py`, `backend/tests/factories.py`
- Test: `backend/tests/test_environment_group_model.py`

**Interfaces:**
- Produces: `EnvironmentGroup(tenant_id, name, description, is_active, deleted_at)`; `EnvironmentGroupMember(tenant_id, group_id, environment_id, deleted_at)`; a real FK on `Booking.environment_group_id`; `ensure_environment_group(db, tenant_id, name="fk-parent-env-group") -> EnvironmentGroup`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_environment_group_model.py`:

```python
"""Environment groups, their membership junction, and the FK that column
has lacked since the March booking migration."""
import pytest
from sqlalchemy import select

from app.db.models.environment_group import EnvironmentGroup, EnvironmentGroupMember
from tests.factories import (
    ensure_environment, ensure_environment_group,
)


@pytest.mark.asyncio
async def test_group_persists_with_its_tenant(db_session, test_tenant):
    group = EnvironmentGroup(tenant_id=test_tenant.id, name="Mortgage SIT + Customer SIT")
    db_session.add(group)
    await db_session.flush()

    assert group.id is not None
    assert group.is_active is True
    assert group.deleted_at is None
    assert group.description is None


@pytest.mark.asyncio
async def test_an_environment_can_belong_to_several_groups(db_session, test_tenant):
    """requirements.md §2.1 says so explicitly, which is why membership is a
    junction table rather than a group_id column on environment."""
    env = await ensure_environment(db_session, test_tenant.id)
    a = await ensure_environment_group(db_session, test_tenant.id, name="Group A")
    b = await ensure_environment_group(db_session, test_tenant.id, name="Group B")

    for group in (a, b):
        db_session.add(EnvironmentGroupMember(
            tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id
        ))
    await db_session.flush()

    rows = (await db_session.execute(
        select(EnvironmentGroupMember.group_id).where(
            EnvironmentGroupMember.environment_id == env.id
        )
    )).scalars().all()
    assert sorted(rows) == sorted([a.id, b.id])


@pytest.mark.asyncio
async def test_a_group_holds_several_environments(db_session, test_tenant):
    group = await ensure_environment_group(db_session, test_tenant.id)
    one = await ensure_environment(db_session, test_tenant.id, slot=1)
    two = await ensure_environment(db_session, test_tenant.id, slot=2)

    for env in (one, two):
        db_session.add(EnvironmentGroupMember(
            tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id
        ))
    await db_session.flush()

    rows = (await db_session.execute(
        select(EnvironmentGroupMember.environment_id).where(
            EnvironmentGroupMember.group_id == group.id
        )
    )).scalars().all()
    assert sorted(rows) == sorted([one.id, two.id])


@pytest.mark.asyncio
async def test_booking_can_now_name_the_group_it_came_from(
    db_session, test_tenant, test_booking_type, test_user
):
    """The column has existed since the March migration with no FK and no
    table. Nothing has ever written it; this is the first row that does."""
    from datetime import datetime, timedelta, timezone
    from app.db.models.booking import Booking
    from app.db.models.booking_request import BookingRequest

    group = await ensure_environment_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=test_tenant.id, project_name="Regression sweep",
        booking_type_id=test_booking_type.id,
        start_date=now, end_date=now + timedelta(days=1), booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    booking = Booking(
        tenant_id=test_tenant.id, booking_request_id=req.id, environment_id=env.id,
        start_date=now, end_date=now + timedelta(days=1), status="draft",
        environment_group_id=group.id,
    )
    db_session.add(booking)
    await db_session.flush()

    assert booking.environment_group_id == group.id


@pytest.mark.asyncio
async def test_a_booking_need_not_come_from_a_group(
    db_session, test_tenant, test_booking_type, test_user
):
    """Hand-picked environments leave it null, and those bookings keep
    transitioning independently — the atomic unit is the group's members."""
    from datetime import datetime, timedelta, timezone
    from app.db.models.booking import Booking
    from app.db.models.booking_request import BookingRequest

    env = await ensure_environment(db_session, test_tenant.id)
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=test_tenant.id, project_name="Hand picked",
        booking_type_id=test_booking_type.id,
        start_date=now, end_date=now + timedelta(days=1), booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    booking = Booking(
        tenant_id=test_tenant.id, booking_request_id=req.id, environment_id=env.id,
        start_date=now, end_date=now + timedelta(days=1), status="draft",
    )
    db_session.add(booking)
    await db_session.flush()

    assert booking.environment_group_id is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_environment_group_model.py -q -p no:logging`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.environment_group'`

`ensure_environment(db, tenant_id, slot=1)` takes a **`slot`**, not a name — check `tests/factories.py` and use it as written.

- [ ] **Step 3: Write the models**

Create `backend/app/db/models/environment_group.py`:

```python
"""Environment groups: a named set of environments, bookable as one unit.

Membership is a junction table because requirements.md §2.1 says an
environment may belong to MULTIPLE groups — a `group_id` column on
`environment` could not express that.

`EnvironmentGroup` is shaped like `Project` and `UserGroup`, the tenant-scoped
vocabularies this codebase already configures per tenant: soft-deleted, with
name uniqueness enforced in the service rather than by a partial unique index
— such an index is inert on SQLite and would guard only the PostgreSQL leg.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentGroup(Base):
    """A tenant-scoped, bookable set of environments."""

    __tablename__ = "environment_group"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Archived groups stay referenceable but stop being offered in pickers.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentGroup(id={self.id}, name='{self.name}', "
            f"tenant_id={self.tenant_id})>"
        )


class EnvironmentGroupMember(Base):
    """"Environment E is in group G."

    Soft-deleted rather than hard-deleted, unlike the dependency junctions in
    this codebase: membership has a history worth keeping, because a booking
    made against a group records only the group id, and answering "which
    environments did this group hold when that booking was made" later needs
    the removed rows to still exist.
    """

    __tablename__ = "environment_group_member"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("environment_group.id"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentGroupMember(group_id={self.group_id}, "
            f"environment_id={self.environment_id})>"
        )
```

- [ ] **Step 4: Give the dangling column its FK**

In `backend/app/db/models/booking.py`, replace the existing line

```python
    environment_group_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # no FK yet (Phase 7)
```

with

```python
    # Which group this booking came from. PROVENANCE, NOT A LIVE LINK:
    # membership is frozen at create, so a booking's environments may
    # legitimately differ from the group's current members. Never resolve a
    # booking's environments by re-reading the group.
    #
    # It is also the atomic-unit key: bookings sharing
    # (booking_request_id, environment_group_id) transition together.
    environment_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("environment_group.id"), nullable=True, index=True
    )
```

Check whether `Integer` is still used elsewhere in that file before removing its import.

- [ ] **Step 5: Register the models for `create_all`**

Run: `cd backend && grep -n "project" app/db/models/__init__.py`

Add `EnvironmentGroup` and `EnvironmentGroupMember` in the same style. A model not imported before `Base.metadata.create_all` silently has no table in tests.

- [ ] **Step 6: Add the factory**

In `backend/tests/factories.py`, add `from app.db.models.environment_group import EnvironmentGroup` beside the other model imports, then:

```python
async def ensure_environment_group(
    db: AsyncSession, tenant_id: int, name: str = "fk-parent-env-group"
) -> EnvironmentGroup:
    """An environment group for `tenant_id`. Idempotent per (tenant, name).

    `booking.environment_group_id` and `environment_group_member.group_id` are
    both real FKs now, so tests must never pass a bare `1`.
    """
    existing = (
        await db.execute(
            select(EnvironmentGroup).where(
                EnvironmentGroup.tenant_id == tenant_id,
                EnvironmentGroup.name == name,
                EnvironmentGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    group = EnvironmentGroup(tenant_id=tenant_id, name=name)
    db.add(group)
    await db.flush()
    return group
```

Add a test that this factory is scoped per tenant, not per name — A1's review proved the equivalent filter on `ensure_project` was unguarded, and a factory that leaks a row across tenants makes later IDOR tests pass against broken code:

```python
@pytest.mark.asyncio
async def test_ensure_environment_group_is_scoped_per_tenant(
    db_session, test_tenant, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()

    mine = await ensure_environment_group(db_session, test_tenant.id, name="Shared")
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Shared")

    assert mine.id != theirs.id
    assert mine.tenant_id == test_tenant.id
    assert theirs.tenant_id == other_tenant.id
    assert (
        await ensure_environment_group(db_session, test_tenant.id, name="Shared")
    ).id == mine.id
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && uv run pytest tests/test_environment_group_model.py -q -p no:logging`
Expected: PASS, 6 passed

- [ ] **Step 8: Write the migration**

Confirm the head first: `cd backend && uv run alembic current` must print `projects`.

Create `backend/app/db/migrations/versions/20260808_1000_envgroups_add_environment_groups.py`:

```python
"""environment groups, membership, and the FK booking has lacked since March

Revision ID: envgroups
Revises: projects
Create Date: 2026-08-08 10:00:00.000000

Additive. Two new tables, plus a foreign key and index on
booking.environment_group_id — a column that has existed since
20260323_1413_0d99256c6a56_add_booking.py with no FK and no table to point at.
Every value in it is NULL and no code path has ever written it, so the
constraint cannot fail on existing data. No column is added and no backfill
is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'envgroups'
down_revision: Union[str, None] = 'projects'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id.
    # The usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_environment_group_id", "environment_group", ["id"])
    op.create_index(
        "ix_environment_group_tenant_id", "environment_group", ["tenant_id"]
    )

    op.create_table(
        "environment_group_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["environment_group.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_environment_group_member_id", "environment_group_member", ["id"]
    )
    op.create_index(
        "ix_environment_group_member_tenant_id",
        "environment_group_member", ["tenant_id"],
    )
    op.create_index(
        "ix_environment_group_member_group_id",
        "environment_group_member", ["group_id"],
    )
    op.create_index(
        "ix_environment_group_member_environment_id",
        "environment_group_member", ["environment_id"],
    )

    # The column already exists — constraint and index only.
    op.create_foreign_key(
        "fk_booking_environment_group",
        "booking", "environment_group", ["environment_group_id"], ["id"],
    )
    op.create_index(
        "ix_booking_environment_group_id", "booking", ["environment_group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_booking_environment_group_id", table_name="booking")
    op.drop_constraint(
        "fk_booking_environment_group", "booking", type_="foreignkey"
    )
    # The COLUMN stays — it predates this revision and downgrade must not
    # destroy it.

    for index in (
        "ix_environment_group_member_environment_id",
        "ix_environment_group_member_group_id",
        "ix_environment_group_member_tenant_id",
        "ix_environment_group_member_id",
    ):
        op.drop_index(index, table_name="environment_group_member")
    op.drop_table("environment_group_member")

    for index in ("ix_environment_group_tenant_id", "ix_environment_group_id"):
        op.drop_index(index, table_name="environment_group")
    op.drop_table("environment_group")
```

Note the downgrade **does not drop `booking.environment_group_id`** — that column predates this revision, and dropping it would destroy data a later re-upgrade could not restore.

- [ ] **Step 9: Verify the migration against the models BY HAND**

`tests/test_migration_schema_drift.py` compares only column **name sets**. Four real drifts passed it on B3a, including naive-vs-timezone-aware timestamps that would have reached production.

Build a scratch database from the migrations and one from `create_all`, then compare **types, timezone-awareness, server defaults, nullability and index names** for `environment_group`, `environment_group_member` and `booking`. Report the observed values, not a claim that they match.

Exercise the downgrade against a scratch database that has a booking row with a **non-null** `environment_group_id` — the FK must drop cleanly and the booking must survive with its column intact.

Then run: `cd backend && uv run pytest tests/test_migration_schema_drift.py tests/test_environment_group_model.py -q -p no:logging`

- [ ] **Step 10: Apply to the dev database**

Confirm `uv run alembic current` prints `projects`, then `uv run alembic upgrade head`.

**Do not run `alembic downgrade -1` against the dev database** — it steps back from the current head, not your revision, and doing this previously dropped a table and destroyed a stored credential. Step 9's scratch database covers both directions.

Also: if a dev server is running with `--reload`, `init_db()` calls `create_all` on every start, so writing the models before the migration can create the tables behind your back with `alembic_version` unchanged. This happened on both of the last two branches. If you find it, drop the empty tables, re-run the migration, and say so in your report.

- [ ] **Step 11: Run both engines, then commit**

```bash
git add backend/app/db/models/environment_group.py backend/app/db/models/booking.py \
        backend/app/db/models/__init__.py \
        backend/app/db/migrations/versions/20260808_1000_envgroups_add_environment_groups.py \
        backend/tests/factories.py backend/tests/test_environment_group_model.py
git commit -m "feat(env-groups): add environment_group, membership, and booking's missing FK"
```

---

### Task 2: Group CRUD service and API

**Files:**
- Create: `backend/app/api/v1/schemas/environment_group.py`, `backend/app/services/environment_group_service.py`, `backend/app/api/v1/environment_groups.py`, `backend/tests/integration/test_environment_groups_api.py`, `backend/tests/integration/test_environment_groups_authz.py`
- Modify: `backend/app/main.py`, `backend/tests/test_pagination.py`

**Interfaces:**
- Consumes: `EnvironmentGroup` (Task 1).
- Produces: `ENVIRONMENT_GROUP_SORTS`; `list_groups(db, tenant_id, *, page=None, sort=None, search=None, is_active=None) -> tuple[list[GroupView], int]`; `get_group_view(db, group_id, tenant_id) -> GroupView`; `get_group(db, group_id, tenant_id) -> EnvironmentGroup`; `create_group`, `update_group`, `delete_group`. `GroupView` is a dataclass with `group` and `member_count`. Endpoints mount at `/api/v1/environment-groups`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_groups_api.py`:

```python
"""Environment group CRUD. Membership has its own file."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_environment, ensure_environment_group


@pytest.mark.asyncio
async def test_create_and_list_a_group(client, auth_headers):
    created = await client.post(
        "/api/v1/environment-groups",
        json={"name": "Mortgage SIT + Customer SIT", "description": "End-to-end pair"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Mortgage SIT + Customer SIT"
    assert created.json()["is_active"] is True
    assert created.json()["member_count"] == 0

    listed = await client.get("/api/v1/environment-groups", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [g["name"] for g in listed.json()] == ["Mortgage SIT + Customer SIT"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_duplicate_name_is_a_409_naming_the_conflict(client, auth_headers):
    await client.post(
        "/api/v1/environment-groups", json={"name": "Mortgage SIT"}, headers=auth_headers
    )
    again = await client.post(
        "/api/v1/environment-groups", json={"name": "mortgage sit"}, headers=auth_headers
    )
    assert again.status_code == 409, again.text
    assert "already exists" in again.json()["detail"].lower()


@pytest.mark.asyncio
async def test_name_uniqueness_is_scoped_per_tenant(
    client, auth_headers, db_session, second_tenant_factory
):
    """Two tenants may each have a group called the same thing. If this filter
    were dropped, tenant B's create would 409 against tenant A's row — which
    also leaks the existence of A's group through the error message."""
    other_tenant, _other_admin = await second_tenant_factory()
    await ensure_environment_group(db_session, other_tenant.id, name="Shared Name")
    await db_session.commit()

    mine = await client.post(
        "/api/v1/environment-groups", json={"name": "Shared Name"}, headers=auth_headers
    )
    assert mine.status_code == 201, mine.text


@pytest.mark.asyncio
async def test_member_count_travels_with_the_row(
    client, auth_headers, db_session, test_tenant
):
    """Counting in the browser against a separately-fetched members list is
    the `.find()`/`.length` failure docs/pagination.md documents — that list
    is capped, so the number would simply be wrong."""
    from app.db.models.environment_group import EnvironmentGroupMember

    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    one = await ensure_environment(db_session, test_tenant.id, slot=1)
    two = await ensure_environment(db_session, test_tenant.id, slot=2)
    for env in (one, two):
        db_session.add(EnvironmentGroupMember(
            tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id
        ))
    await db_session.commit()

    got = await client.get(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert got.status_code == 200, got.text
    assert got.json()["member_count"] == 2


@pytest.mark.asyncio
async def test_another_tenants_group_is_invisible_and_unreachable(
    client, auth_headers, db_session, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    listed = await client.get("/api/v1/environment-groups", headers=auth_headers)
    assert "Theirs" not in [g["name"] for g in listed.json()]

    # 404, never 403 — a 403 confirms the row exists in another tenant.
    got = await client.get(
        f"/api/v1/environment-groups/{theirs.id}", headers=auth_headers
    )
    assert got.status_code == 404, got.text


@pytest.mark.asyncio
async def test_another_tenants_group_cannot_be_updated_or_deleted(
    client, auth_headers, db_session, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    patched = await client.patch(
        f"/api/v1/environment-groups/{theirs.id}",
        json={"name": "Hijacked"}, headers=auth_headers,
    )
    assert patched.status_code == 404, patched.text

    deleted = await client.delete(
        f"/api/v1/environment-groups/{theirs.id}", headers=auth_headers
    )
    assert deleted.status_code == 404, deleted.text


@pytest.mark.asyncio
async def test_delete_is_a_soft_delete_and_is_never_refused(
    client, auth_headers, db_session, test_tenant
):
    """Deliberately unlike user_group_service.delete_group, which 409s while
    anything references it. A group accumulates every booking ever made
    against it, so a reference check would make it permanently undeletable."""
    from sqlalchemy import select
    from app.db.models.environment_group import EnvironmentGroup

    group = await ensure_environment_group(db_session, test_tenant.id, name="Old")
    await db_session.commit()

    gone = await client.delete(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text

    row = (await db_session.execute(
        select(EnvironmentGroup).where(EnvironmentGroup.id == group.id)
    )).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is not None, "must be soft, not hard"

    listed = (await client.get(
        "/api/v1/environment-groups", headers=auth_headers
    )).json()
    assert "Old" not in [g["name"] for g in listed]


@pytest.mark.asyncio
async def test_search_and_is_active_filter_in_sql(client, auth_headers):
    for name, active in (("Mortgage SIT", True), ("Savings SIT", True), ("Old Pair", False)):
        made = await client.post(
            "/api/v1/environment-groups",
            json={"name": name, "is_active": active}, headers=auth_headers,
        )
        assert made.status_code == 201, made.text

    found = await client.get(
        "/api/v1/environment-groups?search=mortgage", headers=auth_headers
    )
    assert [g["name"] for g in found.json()] == ["Mortgage SIT"]
    # A Python-side filter would window the page BEFORE filtering, so the
    # total must describe the filtered set, not the whole one.
    assert int(found.headers[TOTAL_COUNT_HEADER]) == 1

    active_only = await client.get(
        "/api/v1/environment-groups?is_active=true", headers=auth_headers
    )
    assert "Old Pair" not in [g["name"] for g in active_only.json()]
    assert int(active_only.headers[TOTAL_COUNT_HEADER]) == 2


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get(
        "/api/v1/environment-groups?sort_by=nonsense", headers=auth_headers
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_listing_folds_case_rather_than_collating_by_byte(client, auth_headers):
    """Both engines here collate by BYTE VALUE — SQLite's default is BINARY,
    and postgres:15-alpine runs musl libc, which implements no locales. So
    'a' < 'B' is false unless the query folds case explicitly."""
    for name in ("beta pair", "Alpha Pair", "Gamma Pair"):
        await client.post(
            "/api/v1/environment-groups", json={"name": name}, headers=auth_headers
        )

    listed = await client.get("/api/v1/environment-groups", headers=auth_headers)
    assert [g["name"] for g in listed.json()] == [
        "Alpha Pair", "beta pair", "Gamma Pair",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_groups_api.py -q -p no:logging`
Expected: FAIL — every test 404s; the router does not exist.

- [ ] **Step 3: Write the schemas**

Create `backend/app/api/v1/schemas/environment_group.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnvironmentGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: bool = True


class EnvironmentGroupUpdate(BaseModel):
    """Every field optional; the service keys on model_fields_set, so an
    omitted key means "leave alone".

    `name` and `is_active` reject an explicit null rather than 500ing on it —
    A1 shipped that bug by copying UserGroupUpdate's type and dropping its
    validator. `description` genuinely accepts null, to clear it.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("name", "is_active")
    @classmethod
    def _reject_explicit_null(cls, v, info):
        if v is None:
            raise ValueError(f"{info.field_name} may not be null")
        return v


class EnvironmentGroupResponse(BaseModel):
    """`member_count` travels with the row.

    Counting in the browser against a separately-fetched members list is the
    failure docs/pagination.md documents: that list is capped, so past the cap
    the number is simply wrong — and a wrong number is worse than a hidden
    row, because nothing signals it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    member_count: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "EnvironmentGroupResponse":
        g = view.group
        return cls(
            id=g.id, tenant_id=g.tenant_id, name=g.name, description=g.description,
            member_count=view.member_count, is_active=g.is_active,
            created_at=g.created_at, updated_at=g.updated_at,
        )
```

- [ ] **Step 4: Write the service**

Create `backend/app/services/environment_group_service.py`, following `app/services/project_service.py` closely:

```python
"""Environment groups — CRUD plus the member count the UI needs.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise
it. Same call as environment_tier_service, user_group_service and
project_service.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_group import (
    EnvironmentGroupCreate, EnvironmentGroupUpdate,
)
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment import Environment
from app.db.models.environment_group import EnvironmentGroup, EnvironmentGroupMember


@dataclass
class GroupView:
    """A group plus the labels a UI needs without extra round-trips,
    following project_service.ProjectView."""

    group: EnvironmentGroup
    member_count: int


def _member_count_clause(tenant_id: int):
    """Live members only: the membership row AND its environment must both be
    undeleted, so the count agrees with what `list_members` returns. A1
    shipped a count and a list that disagreed because they were written three
    tasks apart and nobody reconciled them."""
    return (
        select(func.count(EnvironmentGroupMember.id))
        .select_from(EnvironmentGroupMember)
        .join(Environment, Environment.id == EnvironmentGroupMember.environment_id)
        .where(
            EnvironmentGroupMember.group_id == EnvironmentGroup.id,
            EnvironmentGroupMember.tenant_id == tenant_id,
            EnvironmentGroupMember.deleted_at.is_(None),
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        )
        .correlate(EnvironmentGroup)
        .scalar_subquery()
    )


def _view_query(tenant_id: int):
    return (
        select(EnvironmentGroup, _member_count_clause(tenant_id))
        .where(
            EnvironmentGroup.tenant_id == tenant_id,
            EnvironmentGroup.deleted_at.is_(None),
        )
    )


def _to_view(row) -> GroupView:
    group, member_count = row
    return GroupView(group=group, member_count=member_count)


ENVIRONMENT_GROUP_SORTS = {
    "name": EnvironmentGroup.name,
    "created_at": EnvironmentGroup.created_at,
}


async def list_groups(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> tuple[list[GroupView], int]:
    query = _view_query(tenant_id)
    if search:
        query = query.where(EnvironmentGroup.name.ilike(f"%{search}%"))
    if is_active is not None:
        query = query.where(EnvironmentGroup.is_active.is_(is_active))
    # apply_sort folds case, so two names differing only in case stop being
    # distinct keys — the id tiebreaker is what makes the order total, which
    # LIMIT/OFFSET requires.
    query = apply_sort(query, sort).order_by(
        func.lower(EnvironmentGroup.name), EnvironmentGroup.id
    )
    rows, total = await fetch_page_rows(db, query, page)
    return [_to_view(r) for r in rows], total


async def get_group_view(
    db: AsyncSession, group_id: int, tenant_id: int
) -> GroupView:
    row = (
        await db.execute(_view_query(tenant_id).where(EnvironmentGroup.id == group_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment group not found")
    return _to_view(row)


async def get_group(
    db: AsyncSession, group_id: int, tenant_id: int
) -> EnvironmentGroup:
    """The bare entity, for callers that do not need the count."""
    group = (
        await db.execute(
            select(EnvironmentGroup).where(
                EnvironmentGroup.id == group_id,
                EnvironmentGroup.tenant_id == tenant_id,
                EnvironmentGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if group is None:
        # 404 rather than 403: a 403 confirms the row exists in another tenant.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment group not found")
    return group


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(EnvironmentGroup.id).where(
        EnvironmentGroup.tenant_id == tenant_id,
        EnvironmentGroup.deleted_at.is_(None),
        func.lower(EnvironmentGroup.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(EnvironmentGroup.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An environment group named '{name.strip()}' already exists in this tenant",
        )


async def create_group(
    db: AsyncSession, data: EnvironmentGroupCreate, tenant_id: int
) -> GroupView:
    await _assert_name_free(db, tenant_id, data.name)
    group = EnvironmentGroup(
        tenant_id=tenant_id,
        name=data.name.strip(),
        description=data.description,
        is_active=data.is_active,
    )
    db.add(group)
    await db.flush()
    return await get_group_view(db, group.id, tenant_id)


async def update_group(
    db: AsyncSession, group_id: int, data: EnvironmentGroupUpdate, tenant_id: int
) -> GroupView:
    group = await get_group(db, group_id, tenant_id)
    fields = data.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"].strip().lower() != group.name.lower():
        await _assert_name_free(db, tenant_id, fields["name"], exclude_id=group_id)

    for key, value in fields.items():
        setattr(group, key, value.strip() if key == "name" else value)
    await db.flush()
    return await get_group_view(db, group_id, tenant_id)


async def delete_group(db: AsyncSession, group_id: int, tenant_id: int) -> None:
    """Soft delete, never refused.

    Deliberately unlike user_group_service.delete_group, which 409s while any
    environment references it. A group accumulates every booking ever made
    against it, so a reference check would make it permanently undeletable the
    moment someone booked it. Existing bookings keep rendering the name;
    `is_active` is what removes it from pickers going forward.

    Membership rows are soft-deleted with it — the group is gone, so its
    membership is meaningless, and leaving them live would let
    `GET /environments/{id}/groups` keep advertising a deleted group.
    """
    group = await get_group(db, group_id, tenant_id)
    now = datetime.now(timezone.utc)
    group.deleted_at = now

    from sqlalchemy import update

    await db.execute(
        update(EnvironmentGroupMember)
        .where(
            EnvironmentGroupMember.group_id == group_id,
            # Tenant-scoped: deleting our group must never touch another
            # tenant's rows, however malformed. A1's equivalent cascade
            # shipped with this filter unguarded by any test.
            EnvironmentGroupMember.tenant_id == tenant_id,
            EnvironmentGroupMember.deleted_at.is_(None),
        )
        .values(deleted_at=now)
    )
    await db.flush()
```

- [ ] **Step 5: Write the endpoints**

Create `backend/app/api/v1/environment_groups.py`, following `app/api/v1/projects.py`:

```python
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_group import (
    EnvironmentGroupCreate, EnvironmentGroupResponse, EnvironmentGroupUpdate,
)
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.services import environment_group_service

router = APIRouter()


@router.get("", response_model=list[EnvironmentGroupResponse])
async def list_environment_groups(
    response: Response,
    search: Optional[str] = Query(None, description="Case-insensitive name match."),
    is_active: Optional[bool] = Query(None),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(
        sorting(environment_group_service.ENVIRONMENT_GROUP_SORTS, default="name")
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readable by any tenant member — every booking form needs this picker."""
    views, total = await environment_group_service.list_groups(
        db, current_user.active_tenant_id,
        page=page, sort=sort, search=search, is_active=is_active,
    )
    set_total_count(response, total)
    return [EnvironmentGroupResponse.from_view(v) for v in views]


@router.post(
    "", response_model=EnvironmentGroupResponse, status_code=status.HTTP_201_CREATED
)
async def create_environment_group(
    data: EnvironmentGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await environment_group_service.create_group(
        db, data, current_user.active_tenant_id
    )
    return EnvironmentGroupResponse.from_view(view)


@router.get("/{group_id}", response_model=EnvironmentGroupResponse)
async def get_environment_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_group_service.get_group_view(
        db, group_id, current_user.active_tenant_id
    )
    return EnvironmentGroupResponse.from_view(view)


@router.patch("/{group_id}", response_model=EnvironmentGroupResponse)
async def update_environment_group(
    group_id: int,
    data: EnvironmentGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await environment_group_service.update_group(
        db, group_id, data, current_user.active_tenant_id
    )
    return EnvironmentGroupResponse.from_view(view)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_group_service.delete_group(
        db, group_id, current_user.active_tenant_id
    )
```

Declare `GET ""` **before** `GET "/{group_id}"` or the literal path is shadowed.

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, beside the other v1 routers:

```python
from app.api.v1 import environment_groups as environment_groups_router
...
app.include_router(
    environment_groups_router.router,
    prefix="/api/v1/environment-groups",
    tags=["Environment Groups"],
)
```

- [ ] **Step 7: Write the authz test**

Create `backend/tests/integration/test_environment_groups_authz.py`, copying the `_login_as` helper from `backend/tests/integration/test_projects_authz.py`. It must cover **both** directions:

- a non-Admin tenant member **CAN** `GET` the list and a single group;
- a non-Admin tenant member **CANNOT** `POST`, `PATCH` or `DELETE` (403).

Read-open/write-Admin is deliberate — every booking form needs the picker, so gating reads would break the primary journey. B3a shipped its group routes over-gated on a false analogy to `/tenant/users` and it took a review to catch. `auth_headers` is always Admin, so without this file nothing distinguishes "works because admin" from "works regardless of role".

- [ ] **Step 8: Add the pagination conformance row**

In `backend/tests/test_pagination.py`, add to `BOUNDED_ENDPOINTS`:

```python
    ("environment-groups", "/api/v1/environment-groups", MAX_LIMIT, "auth_headers"),
```

- [ ] **Step 9: Run the tests, both engines, then commit**

Run: `cd backend && uv run pytest tests/integration/test_environment_groups_api.py tests/integration/test_environment_groups_authz.py tests/test_pagination.py -q -p no:logging`

Then the PostgreSQL leg. Expected: PASS.

```bash
git add backend/app/api/v1/schemas/environment_group.py \
        backend/app/services/environment_group_service.py \
        backend/app/api/v1/environment_groups.py backend/app/main.py \
        backend/tests/integration/test_environment_groups_api.py \
        backend/tests/integration/test_environment_groups_authz.py \
        backend/tests/test_pagination.py
git commit -m "feat(env-groups): tenant-scoped environment group CRUD"
```

---

### Task 3: Membership

**Files:**
- Modify: `backend/app/services/environment_group_service.py`, `backend/app/api/v1/environment_groups.py`, `backend/app/api/v1/schemas/environment_group.py`, `backend/app/api/v1/environments.py`
- Create: `backend/tests/integration/test_environment_group_members_api.py`

**Interfaces:**
- Consumes: `get_group` (Task 2).
- Produces: `MemberCreate`/`MemberResponse`. Every row is the **three-tuple** `(member, group_name, environment_name)`, so one response model serves both directions:
  - `list_members(db, group_id, tenant_id, *, page=None) -> tuple[list[tuple[EnvironmentGroupMember, str, str]], int]`
  - `list_groups_for_environment(db, environment_id, tenant_id, *, page=None) -> tuple[list[tuple[EnvironmentGroupMember, str, str]], int]`
  - `add_member(db, group_id, data, tenant_id) -> tuple[EnvironmentGroupMember, str, str]`
  - `remove_member(db, group_id, member_id, tenant_id) -> None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_group_members_api.py`. It must cover:

```python
"""Group membership, read from both directions."""
```

- adding an environment returns 201 and the response carries the **environment's name** (never resolved in the browser against a capped list);
- `GET /environment-groups/{id}/members` and `GET /environments/{id}/groups` both list it, both bounded, both emitting `X-Total-Count`;
- adding **another tenant's** environment is 404;
- adding an environment to another tenant's group is 404;
- adding the **same environment twice** is 409 naming it — an environment is in a group or it is not, and two rows would double the member count;
- re-adding an environment whose membership was previously **removed** succeeds, and produces one live member, not two;
- removing is a **soft** delete: assert the row still exists with `deleted_at` set, not merely that it vanished from the list — a hard delete satisfies "vanished from the list" equally;
- `GET /environments/{id}/groups` for another tenant's environment is **404, not 200 with `[]`**;
- a soft-deleted group's membership no longer appears from the environment side (Task 2's `delete_group` cascade), and dropping that cascade fails a named test.

Follow `backend/tests/integration/test_usage_agreements_api.py` — it is the same junction shape read from both directions, including its three malformed-row defence-in-depth tests.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_group_members_api.py -q -p no:logging`
Expected: FAIL — the member routes 404.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/api/v1/schemas/environment_group.py`:

```python
class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: int


class MemberResponse(BaseModel):
    """Both display names travel with the row: this list is read from the
    group side AND the environment side, and neither page should resolve the
    other end against a capped collection."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    group_id: int
    group_name: str
    environment_id: int
    environment_name: str
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "MemberResponse":
        member, group_name, environment_name = row
        return cls(
            id=member.id, tenant_id=member.tenant_id,
            group_id=member.group_id, group_name=group_name,
            environment_id=member.environment_id, environment_name=environment_name,
            created_at=member.created_at,
        )
```

Both list functions and `add_member` return the three-tuple `(member, group_name, environment_name)`, matching the Interfaces block, so `MemberResponse.from_row` serves both directions unchanged.

- [ ] **Step 4: Add the service functions**

Append to `backend/app/services/environment_group_service.py`. Follow `project_service._agreement_query` exactly, including its two tenant-qualified joins:

```python
def _member_query(tenant_id: int):
    """One select carrying both ends' names, tenant-qualified on each join.

    Both joins filter deleted_at: a membership row whose group or environment
    is gone should not appear from either direction. This is the OPPOSITE
    judgement from a name-rendering lookup, where an archived thing must still
    render its name on a live row — here we are asking whether the row should
    exist at all.
    """
    return (
        select(EnvironmentGroupMember, EnvironmentGroup.name, Environment.name)
        .join(
            EnvironmentGroup,
            and_(
                EnvironmentGroup.id == EnvironmentGroupMember.group_id,
                EnvironmentGroup.tenant_id == tenant_id,
                EnvironmentGroup.deleted_at.is_(None),
            ),
        )
        .join(
            Environment,
            and_(
                Environment.id == EnvironmentGroupMember.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            ),
        )
        .where(
            EnvironmentGroupMember.tenant_id == tenant_id,
            EnvironmentGroupMember.deleted_at.is_(None),
        )
    )
```

`list_members` orders by `func.lower(Environment.name), EnvironmentGroupMember.id`; `list_groups_for_environment` by `func.lower(EnvironmentGroup.name), EnvironmentGroupMember.id`. Both call `fetch_page_rows`. Both validate their parent id first — `get_group` for one, an explicit tenant-scoped `Environment` lookup raising 404 for the other.

`add_member` validates the group via `get_group`, validates the environment with a tenant-scoped lookup raising 404, then refuses a duplicate live membership with 409 naming the environment. `remove_member` sets `deleted_at`.

Add `and_` to the SQLAlchemy import.

- [ ] **Step 5: Add the endpoints**

Append three routes to `backend/app/api/v1/environment_groups.py` — `GET`/`POST` `/{group_id}/members` and `DELETE /{group_id}/members/{member_id}` — reads on `get_current_user`, writes on `require_tenant_admin()`, the list bounded with `pagination()` and `set_total_count`.

In `backend/app/api/v1/environments.py`, add:

```python
@router.get("/{env_id}/groups", response_model=list[MemberResponse])
async def list_environment_groups_for_environment(
    env_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """"Which groups is this environment in." Answers the question a booking
    raises: why did this environment get booked?"""
    rows, total = await environment_group_service.list_groups_for_environment(
        db, env_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [MemberResponse.from_row(r) for r in rows]
```

Add the imports it needs.

- [ ] **Step 6: Run the tests, both engines, then commit**

Run: `cd backend && uv run pytest tests/integration/test_environment_group_members_api.py tests/integration/test_environment_groups_api.py -q -p no:logging`, then the PostgreSQL leg.

```bash
git add backend/app/services/environment_group_service.py \
        backend/app/api/v1/environment_groups.py \
        backend/app/api/v1/schemas/environment_group.py \
        backend/app/api/v1/environments.py \
        backend/tests/integration/test_environment_group_members_api.py
git commit -m "feat(env-groups): membership, readable from both directions"
```

---

### Task 4: Booking a group

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_request.py`, `backend/app/services/booking_request_service.py`
- Create: `backend/tests/integration/test_group_booking_create.py`

**Interfaces:**
- Consumes: `EnvironmentGroup`, `EnvironmentGroupMember` (Task 1), `get_group` (Task 2).
- Produces: `environment_group_ids` on `BookingRequestCreate`; each resulting `Booking` carries `environment_group_id`; `EnvBookingSummary`/`BookingResponse` expose `environment_group_id` and `environment_group_name`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_group_booking_create.py`. It must cover:

- **booking a group creates one booking per live member**, each carrying that `environment_group_id`, and the response names the group;
- **a hand-picked environment on the same request has `environment_group_id` null** — the two kinds coexist on one request, and that is what makes the atomic unit the group's members rather than the request;
- **an environment reached via two groups is refused**, with **both group names in the message**;
- **an environment reached via a group and by hand is refused** likewise;
- **a group alone satisfies "at least one environment"** — `environment_ids` may be empty when `environment_group_ids` is not;
- **an empty group is refused by name** — *"Mortgage SIT has no environments"*, not the generic "At least one environment_id is required";
- **another tenant's group is 404**;
- **an `inactive` or `maintenance` environment still expands into a booking** — it must not be silently dropped. Assert the member count, not just a 201;
- **membership is frozen**: create a group booking, then add an environment to the group and remove another, and assert the existing request's bookings are unchanged in both count and environment ids.

Read `backend/tests/integration/test_project_links_bookings.py` for the real create payload shape — `POST /booking-requests` returns `{request, detected_conflicts}`, not the bare body.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_group_booking_create.py -q -p no:logging`
Expected: FAIL — `environment_group_ids` is not accepted.

- [ ] **Step 3: Extend the schemas**

In `backend/app/api/v1/schemas/booking_request.py`:

- `BookingRequestCreate.environment_ids` becomes `list[int] = Field(default_factory=list)` — it may now legitimately be empty when groups are supplied. **Remove its `min_length=1`**; the service enforces the combined rule.
- add `environment_group_ids: list[int] = Field(default_factory=list)`.
- add to `EnvBookingSummary` and to whatever model `GET /bookings` returns: `environment_group_id: Optional[int] = None` and `environment_group_name: Optional[str] = None`.

- [ ] **Step 4: Expand groups in `create_request`**

In `backend/app/services/booking_request_service.py`, replace the `env_ids` preamble. The loop that creates children must iterate **pairs**, not ids:

```python
    env_ids: list[int] = data.get("environment_ids") or []
    group_ids: list[int] = data.get("environment_group_ids") or []

    if len(env_ids) != len(set(env_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "environment_ids must be unique"
        )
    if len(group_ids) != len(set(group_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "environment_group_ids must be unique"
        )

    # (environment_id, environment_group_id | None), in request order.
    # Hand-picked first so a clash names the GROUP as the newcomer, which is
    # the more useful half of the message.
    pairs: list[tuple[int, Optional[int]]] = [(e, None) for e in env_ids]
    # environment_id -> the human label of whatever put it here
    origin: dict[int, str] = {e: "the environments you picked" for e in env_ids}

    for group_id in group_ids:
        group = await environment_group_service.get_group(db, group_id, tenant_id)
        members = (await db.execute(
            select(EnvironmentGroupMember.environment_id)
            .join(
                Environment,
                Environment.id == EnvironmentGroupMember.environment_id,
            )
            .where(
                EnvironmentGroupMember.group_id == group_id,
                EnvironmentGroupMember.tenant_id == tenant_id,
                EnvironmentGroupMember.deleted_at.is_(None),
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )).scalars().all()

        if not members:
            # Refused by name. Without this the caller gets either a silently
            # partial request or the generic "at least one environment",
            # neither of which says WHICH group was empty.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Environment group '{group.name}' has no environments",
            )

        for env_id in members:
            if env_id in origin:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{origin[env_id]} and environment group '{group.name}' both "
                    f"contain the same environment; an environment can appear "
                    f"only once on a request",
                )
            origin[env_id] = f"environment group '{group.name}'"
            pairs.append((env_id, group_id))

    if not pairs:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "At least one environment_id or environment_group_id is required",
        )

    all_env_ids = [e for e, _ in pairs]
    envs = (await db.execute(
        select(Environment).where(
            Environment.id.in_(all_env_ids),
            Environment.tenant_id == tenant_id,
        )
    )).scalars().all()
    if len(envs) != len(all_env_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "One or more environment_ids not found"
        )
```

Then the child loop becomes:

```python
    children: list[Booking] = []
    for env_id, group_id in pairs:
        child = Booking(
            tenant_id=tenant_id,
            booking_request_id=req.id,
            environment_id=env_id,
            start_date=data["start_date"],
            end_date=data["end_date"],
            status=initial_state,
            environment_group_id=group_id,
        )
        db.add(child)
        children.append(child)
    await db.flush()
```

**No status filter on the member query.** An `inactive` or `maintenance` environment still expands: booking a future window on an environment that is currently down is legitimate, and the existing per-environment path performs no status check either. Silently dropping a member would hand the user a partial group with no indication which environment vanished.

Add the imports: `environment_group_service`, `EnvironmentGroupMember`, `Optional`.

- [ ] **Step 5: Carry the group name onto responses**

`project_service.get_project_names` is the pattern — a batch lookup keyed by id, **not** filtering `deleted_at`, so an archived group still renders its name on the bookings that reference it. Add the equivalent to `environment_group_service`:

```python
async def get_group_names(
    db: AsyncSession, group_ids: set[int], tenant_id: int
) -> dict[int, str]:
    """Names for a set of group ids, for rendering on rows that reference them.

    Deliberately does NOT filter deleted_at: an archived or deleted group must
    still render its name on the bookings made against it. That is the
    opposite of `get_group`, which validates a WRITE and does filter — keep
    the two apart. A1 shipped exactly this pair and a reviewer had to check
    nobody had "unified" them.
    """
    ids = {g for g in group_ids if g is not None}
    if not ids:
        return {}
    rows = (await db.execute(
        select(EnvironmentGroup.id, EnvironmentGroup.name).where(
            EnvironmentGroup.id.in_(ids),
            EnvironmentGroup.tenant_id == tenant_id,
        )
    )).all()
    return {gid: name for gid, name in rows}
```

Then populate `environment_group_name` at **every** site that builds a booking response. Run `grep -n "BookingResponse\|EnvBookingSummary\|_to_response" backend/app/api/v1/bookings.py backend/app/api/v1/booking_requests.py` and update all of them.

**Make the helper's new parameter required-positional, not defaulted.** A1's review found `_to_response(req, project_name_link=None)` left four of five call sites silently rendering `null`, because **Pydantic silently defaults a missing non-column attribute rather than raising**. A required positional turns an omission into an immediate `TypeError`.

- [ ] **Step 6: Run the tests, both engines, then commit**

Because this touches the shared create path, also run `tests/integration/test_booking_requests_api.py`, `tests/integration/test_project_links_bookings.py` and `tests/test_pagination.py`.

```bash
git add backend/app/api/v1/schemas/booking_request.py \
        backend/app/services/booking_request_service.py \
        backend/app/services/environment_group_service.py \
        backend/app/api/v1/ backend/tests/integration/test_group_booking_create.py
git commit -m "feat(env-groups): book a group, expanding it to its members at create"
```

---

### Task 5: The atomic transition

**Files:**
- Modify: `backend/app/services/booking_service.py`, `backend/app/api/v1/booking_requests.py`, `backend/app/api/v1/schemas/booking_request.py`
- Create: `backend/tests/integration/test_group_transition.py`

**Interfaces:**
- Consumes: the group bookings from Task 4.
- Produces: `transition_group(db, request_id, group_id, to_state, current_user, notes=None) -> list[Booking]`; `get_group_allowed_transitions(db, request_id, group_id, current_user) -> list[dict]`. Routes `POST /booking-requests/{request_id}/groups/{group_id}/transition` and `GET .../allowed-transitions`.

**This is the heart of A2.** Read the spec's "All-or-nothing" and "The per-booking transition endpoint stays open" sections before starting.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_group_transition.py`. Every one of these is required:

- **all members move together** — transition the group, assert every member's status changed and each has a new `BookingStatusHistory` row;
- **a hand-picked booking on the same request does NOT move**;
- **a refused member blocks the whole group, and nothing moves.** Assert the other members' statuses are **unchanged** *and* that **no `BookingStatusHistory` rows were written**. A test asserting only the HTTP status would pass against a transition that applied and then rolled back for an unrelated reason;
- **every failure is reported, not just the first** — two invalid members produce a message naming both environments;
- **role-blocked is 403, invalid-transition is 400**, matching the per-booking endpoint's convention;
- **`allowed-transitions` is the intersection** — with members in different states, a transition valid for some but not all must not appear;
- **divergence is recoverable**: transition one member individually via `POST /bookings/{id}/transition`, assert the group transition now refuses and **names that environment and its state**, repair it individually, assert the group transition then succeeds. This is the journey the design accepts in exchange for keeping the individual endpoint open, and it must be proven to work end to end;
- **another tenant's request or group is 404**;
- **a group id with no bookings on that request is 404**;
- **the per-booking endpoint still works on a group member** — it is the repair tool, and forbidding it was explicitly rejected.

Build the differing states through the individual endpoint, not by writing statuses directly — a test that hand-writes a status proves nothing about the path users take.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_group_transition.py -q -p no:logging`
Expected: FAIL — the group routes 404.

- [ ] **Step 3: Write the service functions**

Append to `backend/app/services/booking_service.py`. Reuse the existing `transition_state`'s template lookup and `record_values` construction rather than duplicating them — extract a helper if that is cleaner, but do not write a second copy of the lifecycle lookup.

```python
async def _group_bookings(
    db: AsyncSession, request_id: int, group_id: int, tenant_id: int
) -> list[Booking]:
    """The live bookings on `request_id` that came from `group_id`.

    Scoped by the (request, group) pair, which is the atomic unit. Ordered by
    id so error messages and history rows are deterministic.
    """
    rows = (await db.execute(
        select(Booking)
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
        .where(
            Booking.booking_request_id == request_id,
            Booking.environment_group_id == group_id,
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            BookingRequest.tenant_id == tenant_id,
            BookingRequest.deleted_at.is_(None),
        )
        .order_by(Booking.id)
    )).scalars().all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No bookings for that environment group on this request",
        )
    return list(rows)


async def transition_group(
    db: AsyncSession,
    request_id: int,
    group_id: int,
    to_state: str,
    current_user,
    notes: str | None = None,
) -> list[Booking]:
    """Move every member of a group booking, or none of them.

    ALL-OR-NOTHING, validated before anything mutates. A half-transitioned
    group is the shape that produced two unrecoverable states on B3b, one of
    them asserted as correct by that branch's own test.

    Every failure is reported, not just the first: an approver needs to see
    everything that is wrong at once, because the repair is manual and
    per-member.
    """
    tenant_id = current_user.active_tenant_id
    bookings = await _group_bookings(db, request_id, group_id, tenant_id)
    template = await _template_for_booking(db, bookings[0])

    failures: list[str] = []
    role_blocked = False
    for booking in bookings:
        allowed, reason = validate_transition(
            template.definition,
            booking.status,
            to_state,
            current_user.role,
            _record_values(booking.booking_request),
        )
        if not allowed:
            env_name = booking.environment.name if booking.environment else str(
                booking.environment_id
            )
            failures.append(f"{env_name} (in '{booking.status}'): {reason}")
            if reason and ("not allowed" in reason or "role" in reason.lower()):
                role_blocked = True

    if failures:
        joined = "; ".join(failures)
        if role_blocked:
            raise HTTPException(
                status_code=403,
                detail=f"Your role cannot make this transition for: {joined}",
            )
        raise HTTPException(
            status_code=400,
            detail=(
                f"The group cannot move to '{to_state}' because its members "
                f"are not all able to: {joined}"
            ),
        )

    for booking in bookings:
        old_state = booking.status
        booking.status = to_state
        db.add(BookingStatusHistory(
            booking_id=booking.id,
            from_state=old_state,
            to_state=to_state,
            changed_by=current_user.id,
            changed_at=datetime.now(timezone.utc),
            notes=notes,
        ))
        await publish_event(
            db,
            event_type="BookingStateTransitioned",
            aggregate_id=booking.id,
            aggregate_type="Booking",
            payload={
                "from_state": old_state,
                "to_state": to_state,
                "changed_by": current_user.id,
            },
            tenant_id=booking.tenant_id,
        )
    await db.flush()
    return bookings


async def get_group_allowed_transitions(
    db: AsyncSession, request_id: int, group_id: int, current_user
) -> list[dict]:
    """The INTERSECTION of what every member allows.

    A transition not valid for all members must not be offered, or the UI
    shows a button that always fails — precisely what all-or-nothing exists to
    prevent. B3b's review found the equivalent endpoint shipped with zero
    tests, and it is where the UI's buttons come from.
    """
    tenant_id = current_user.active_tenant_id
    bookings = await _group_bookings(db, request_id, group_id, tenant_id)
    template = await _template_for_booking(db, bookings[0])

    per_member: list[set[str]] = []
    by_state: dict[str, dict] = {}
    for booking in bookings:
        allowed = get_allowed_transitions(
            template.definition, booking.status, current_user.role
        )
        per_member.append({t["to_state"] for t in allowed})
        for t in allowed:
            by_state.setdefault(t["to_state"], t)

    if not per_member:
        return []
    common = set.intersection(*per_member)
    return [by_state[s] for s in sorted(common)]
```

`_template_for_booking` and `_record_values` are the two helpers to extract from the existing `transition_state`, which currently inlines both. Refactor `transition_state` to use them so there is one copy — a second copy would drift, and the whole point is that a group transition validates by **exactly** the same rule as an individual one.

**Publish per-booking events, not a group event.** Existing outbox consumers keep working unchanged, and nothing needs a group event yet.

- [ ] **Step 4: Add the endpoints**

In `backend/app/api/v1/booking_requests.py`:

```python
@router.post(
    "/{request_id}/groups/{group_id}/transition",
    response_model=list[BookingResponse],
)
async def transition_group_bookings(
    request_id: int,
    group_id: int,
    data: TransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Move every member of this group booking, or none of them."""
    bookings = await booking_service.transition_group(
        db, request_id, group_id, data.to_state, current_user, data.notes
    )
    ...


@router.get(
    "/{request_id}/groups/{group_id}/allowed-transitions",
    response_model=list[AllowedTransitionResponse],
)
async def get_group_allowed_transitions_route(
    request_id: int,
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_service.get_group_allowed_transitions(
        db, request_id, group_id, current_user
    )
```

Reuse the existing `TransitionRequest` and `AllowedTransitionResponse` schemas — check `backend/app/api/v1/bookings.py` for their real names and import them rather than defining new ones. Build the `BookingResponse` list the same way Task 4's sites do, including `environment_group_name`.

**Do not change `POST /bookings/{id}/transition`.** It keeps its exact current meaning and stays available for a group member — it is the only repair tool when members diverge.

- [ ] **Step 5: Run the tests, both engines**

Run: `cd backend && uv run pytest tests/integration/test_group_transition.py tests/integration/test_bookings.py -q -p no:logging`, then the PostgreSQL leg. `test_bookings.py` because you refactored `transition_state`.

- [ ] **Step 6: Prove the rules by mutation, then commit**

Run each of these and confirm a **named** test fails. If any survives, the rule is unguarded — add the test before committing.

- delete the `if failures:` block so refused members are skipped rather than blocking
- report only `failures[0]` instead of all of them
- make `get_group_allowed_transitions` return the **union** instead of the intersection
- drop `Booking.tenant_id` from `_group_bookings`
- drop `BookingRequest.tenant_id` from it
- key `_group_bookings` on `environment_group_id` alone, ignoring `request_id`
- move the mutation loop **above** the validation loop

```bash
git add backend/app/services/booking_service.py backend/app/api/v1/booking_requests.py \
        backend/app/api/v1/schemas/booking_request.py \
        backend/tests/integration/test_group_transition.py
git commit -m "feat(env-groups): atomic group transitions, all-or-nothing"
```

---

### Task 6: Frontend types, service, slice and picker hook

**Files:**
- Create: `frontend/src/types/environmentGroup.ts`, `frontend/src/services/environmentGroupService.ts`, `frontend/src/store/environmentGroupSlice.ts`, `frontend/src/hooks/useAllEnvironmentGroups.ts`, and `__tests__` for the slice and the hook
- Modify: `frontend/src/store/index.ts`, `frontend/src/types/booking.ts`, `frontend/src/types/bookingRequest.ts`

**Interfaces:**
- Produces: `environmentGroupService` (`listGroups`, `getGroup`, `createGroup`, `updateGroup`, `deleteGroup`, `listMembers`, `listGroupsForEnvironment`, `addMember`, `removeMember`, `transitionGroup`, `groupAllowedTransitions`); thunks mirroring them; state at `state.environmentGroup` with `{ groups, total, current, members, memberTotal, loading, error }`; `useAllEnvironmentGroups(): { groups, loading, truncated }`.

- [ ] **Step 1: Write the failing tests**

Mirror `frontend/src/store/__tests__/projectSlice.test.ts` exactly. Four cases:

- the list thunk stores the **server total from the header**, not `rows.length`;
- a refused create surfaces the **server's reason**, rejecting with an **AxiosError shape** (`{ isAxiosError: true, message: 'Request failed with status code 409', response: { status: 409, data: { detail: "..." } } }`). A plain `Error` carrying the final text passes while the app is broken, because `miniSerializeError` keeps `.message`;
- a successful create **leaves the paged list alone** — no splicing; the page refetches;
- a successful fetch **clears a stale error banner**. Note only the **read** thunks touch `state.error`; a refused mutation returns its reason via `rejectWithValue` for the dialog that caused it, so drive this test with a failed *fetch*.

And for the hook, mirror `frontend/src/hooks/__tests__/useAllProjects.test.tsx`: it requests `is_active: true`, it reports `truncated` when the server has more than it asked for, and two consumers mounting in the same commit issue **one** request.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/store/__tests__/environmentGroupSlice.test.ts src/hooks/__tests__/useAllEnvironmentGroups.test.tsx`
Expected: FAIL — modules do not resolve.

- [ ] **Step 3: Write the types, service, slice and hook**

Follow `frontend/src/services/projectService.ts` for the `Paged<T>` / `x-total-count` shape, `frontend/src/store/projectSlice.ts` for the slice, and `frontend/src/hooks/useAllProjects.ts` for the hook — copy its structure including the `truncated` signal and the `useSharedList` key.

`src/types/environmentGroup.ts` exports `EnvironmentGroupResponse` (`{id, tenant_id, name, description, member_count, is_active, created_at, updated_at}`), `EnvironmentGroupCreate`, `EnvironmentGroupUpdate`, `MemberCreate`, `MemberResponse` (`{id, tenant_id, group_id, group_name, environment_id, environment_name, created_at}`).

Add to `src/types/bookingRequest.ts` and `src/types/booking.ts`: `environment_group_id: number | null` and `environment_group_name: string | null` on the response types, and `environment_group_ids?: number[]` on the booking-request create payload.

**Every thunk returns `rejectWithValue(formatApiError(err, '<fallback>'))`.** RTK's `miniSerializeError` copies only `name`/`message`/`stack`/`code`, so `response.data.detail` is otherwise dropped and the user sees an HTTP status instead of the reason — a bug this repo has shipped in four panels.

**No `fulfilled` handler may splice the groups list.** It is a server-paged window; local surgery desynchronises the page from its total. Add the comment saying so.

Adding required fields to the booking response types will break existing fixtures' typechecking. **Add explicit `null`s to those fixtures rather than making the fields optional** — an optional field would make the type lie about the wire contract. Report how many you touched.

- [ ] **Step 4: Register the reducer, run, typecheck, commit**

Add `environmentGroup: environmentGroupReducer` to `frontend/src/store/index.ts`.

Run: `cd frontend && npx vitest run src/store src/hooks && npx tsc --noEmit`

Then prove two mutations kill a named test: replace `formatApiError(err, ...)` with `err.message` in a mutating thunk; store `rows.length` instead of the header total.

```bash
git add frontend/src/types/ frontend/src/services/environmentGroupService.ts \
        frontend/src/store/environmentGroupSlice.ts frontend/src/store/index.ts \
        frontend/src/hooks/useAllEnvironmentGroups.ts frontend/src/store/__tests__/ \
        frontend/src/hooks/__tests__/
git commit -m "feat(env-groups): frontend types, service, slice and picker hook"
```

---

### Task 7: Environment Groups admin screen

**Files:**
- Create: `frontend/src/pages/admin/EnvironmentGroups.tsx`, `frontend/src/pages/admin/EnvironmentGroupDetail.tsx`, `frontend/src/pages/admin/__tests__/environmentGroups.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/pages/admin/AdminLayout.tsx`

**Interfaces:**
- Produces: routes `/tenant/environment-groups` and `/tenant/environment-groups/:id`; exported `environmentGroupColumns`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/admin/__tests__/environmentGroups.test.tsx`, following `frontend/src/pages/admin/__tests__/projects.test.tsx` and importing the shared stand-in from `frontend/src/test/dataGridMock.tsx` (it invokes `renderCell` and `valueGetter`, and surfaces the props the grid was rendered with).

```tsx
import { describe, expect, it } from 'vitest';

import { environmentGroupColumns } from '../EnvironmentGroups';

/**
 * The backend's sort whitelist (ENVIRONMENT_GROUP_SORTS) is `name` and
 * `created_at`. `member_count` is a correlated subquery — not backed by a
 * single column, so it can never be whitelisted, and `sorting()` answers 422
 * rather than falling back silently.
 */
describe('environmentGroupColumns', () => {
  it('marks every column the backend cannot sort as unsortable', () => {
    const sortable = environmentGroupColumns
      .filter((c) => c.sortable !== false)
      .map((c) => c.field)
      .sort();
    // The whole set, so a NEW column fails this test until someone decides
    // whether the backend can sort it.
    expect(sortable).toEqual(['name']);
  });

  it('never makes the computed member count sortable', () => {
    expect(
      environmentGroupColumns.find((c) => c.field === 'member_count')?.sortable
    ).toBe(false);
  });
});
```

Plus rendering tests covering: the member count renders from the row; a refused create surfaces the **server's** reason (AxiosError shape) and the generic `"Request failed with status code"` text is absent; the create dialog **clears its error when reopened** (A1 shipped this bug in `Projects.tsx` and it was inherited from `UserGroups.tsx`); an Admin sees the write controls and a non-Admin member does not, **but can still read the list**.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/__tests__/environmentGroups.test.tsx`
Expected: FAIL — cannot resolve `../EnvironmentGroups`

- [ ] **Step 3: Write the list page**

Create `frontend/src/pages/admin/EnvironmentGroups.tsx`, modelled on `frontend/src/pages/admin/Projects.tsx`. Export the columns at module level:

```tsx
// Sortable fields (whitelist-backed, see ENVIRONMENT_GROUP_SORTS): `name` and
// `created_at` ONLY. `member_count` is a correlated subquery — not backed by a
// single column, so it can never be whitelisted, and a sortable header on it
// sends a sort_by the backend answers with 422.
//
// This grid is client-side (no sortingMode="server" / paginationMode="server"),
// matching UserGroups.tsx and Projects.tsx: a tenant's group list is small and
// bounded by configuration. `tenant-environment-groups` is therefore absent
// from sortWhitelists.json, the same ‡ convention docs/pagination.md records.
// eslint-disable-next-line react-refresh/only-export-components
export const environmentGroupColumns: GridColDef<EnvironmentGroupResponse>[] = [
  { field: 'name', headerName: 'Name', flex: 1 },
  { field: 'description', headerName: 'Description', flex: 1, sortable: false,
    renderCell: (params) => (params.value as string | null) ?? '—' },
  { field: 'member_count', headerName: 'Environments', width: 140, sortable: false },
  { field: 'is_active', headerName: 'Status', width: 110, sortable: false,
    renderCell: (params) => (params.value ? 'Active' : 'Archived') },
  { field: 'actions', headerName: '', width: 140, sortable: false, disableColumnMenu: true },
];
```

The rest follows `Projects.tsx`: fetch on mount, create/edit dialogs, a delete confirmation, `result.payload` on every rejection, `setCreateError(null)` **at dialog open** as well as at submit, `disableColumnFilter` on the grid, and a refetch after each successful mutation rather than splicing.

- [ ] **Step 4: Write the detail page**

Create `frontend/src/pages/admin/EnvironmentGroupDetail.tsx`: the group's fields, and its members in an MUI `Table` with an environment picker to add and a per-row Remove.

Environment names come **from the member rows the API returned**, never resolved against a separately-fetched environments collection — that collection is capped, and a `.find()` miss renders `—`, losing information no truncation banner can recover.

Add copy stating that **changing membership does not affect existing bookings**. Without it, an admin removing an environment will reasonably assume they have cancelled its bookings. Assert that copy in a test — it is the kind of line a later tidy-up drops.

- [ ] **Step 5: Wire routes and nav**

`frontend/src/App.tsx`: `/tenant/environment-groups` → `EnvironmentGroups`, `/tenant/environment-groups/:id` → `EnvironmentGroupDetail`. Match how `/tenant/projects` is imported.

`frontend/src/pages/admin/AdminLayout.tsx`: an **Environment Groups** entry beside Projects and User Groups.

Reads are open to any tenant member, so use a bare `<PrivateRoute>` and gate the write controls on `user?.role === 'Admin' || user?.is_master_admin === true` — matching `/tenant/projects`, and not the ten admin routes that carry `requiredRole="Admin"`.

- [ ] **Step 6: Run tests, typecheck, lint, commit**

Run: `cd frontend && npx vitest run src/pages/admin && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/pages/admin/EnvironmentGroups.tsx \
        frontend/src/pages/admin/EnvironmentGroupDetail.tsx \
        frontend/src/pages/admin/__tests__/environmentGroups.test.tsx \
        frontend/src/App.tsx frontend/src/pages/admin/AdminLayout.tsx
git commit -m "feat(env-groups): Environment Groups admin screen"
```

---

### Task 8: Booking a group from the form

**Files:**
- Modify: `frontend/src/pages/bookings/BookingForm.tsx`
- Test: the existing `frontend/src/pages/bookings/__tests__/` files

- [ ] **Step 1: Write the failing tests**

- selecting a group sends `environment_group_ids: [id]` and does **not** put its members into `environment_ids`. Expanding client-side would freeze membership in the browser and duplicate a rule the server owns;
- a group alone is a valid submission — the form must not require `environment_ids` when a group is chosen;
- the picker requests **only active groups** (`is_active: true` via `useAllEnvironmentGroups`);
- the server's refusal for an overlapping selection is surfaced from `result.payload`, with both group names visible and the generic `"Request failed with status code"` text absent. Reject with an **AxiosError shape**;
- when the hook reports `truncated`, the form says so rather than presenting a silently partial list.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/pages/bookings`

- [ ] **Step 3: Add the picker**

Add a multi-select **Environment groups** field to `BookingForm.tsx` beside the existing environment picker, sourced from `useAllEnvironmentGroups()`, sending `environment_group_ids`.

Relax the form's validation so a submission is valid when **either** `environment_ids` **or** `environment_group_ids` is non-empty — check the zod schema's current `environment_ids` rule and widen it with a `refine` across both fields rather than dropping the requirement.

Add helper text saying a group books **all of its current environments**, and that they will be approved or rejected together. That is the whole behavioural difference from picking the same environments by hand, and it is invisible otherwise.

- [ ] **Step 4: Run tests, typecheck, lint, commit**

Run: `cd frontend && npx vitest run src/pages/bookings && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/pages/bookings/
git commit -m "feat(env-groups): book a group from the booking form"
```

---

### Task 9: Group transitions in the UI

**Files:**
- Create: `frontend/src/components/bookings/GroupTransitionPanel.tsx` and its test
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx`

**This is where atomicity becomes visible.** A request can hold group bookings and hand-picked bookings side by side, behaving differently; without this the difference is invisible and users will be surprised.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/bookings/__tests__/GroupTransitionPanel.test.tsx`:

- members of one group render **together under the group's name**, with each member's environment and current state;
- the transition buttons come from `GET .../groups/{id}/allowed-transitions` — **not** from any single member's allowed transitions. Mutating the component to read one member's list must fail a named test;
- when members' states differ, the panel **says so and names the environments that are out of step**, because the group transition will refuse until they are repaired;
- a refused group transition renders the **server's** message, which names every failing member. AxiosError shape;
- a hand-picked booking on the same request renders **outside** any group panel, with its own per-booking controls.

- [ ] **Step 2: Run it, then build the panel**

`GroupTransitionPanel.tsx` takes `{ requestId, groupId, groupName, bookings }`, fetches the group's allowed transitions, renders one control set for the group and a row per member showing environment and state, and dispatches the group transition thunk. It reads a rejection from `result.payload`.

Render an error state, not an eternal skeleton — check which thunks set `state.error` and whether any sets a `loading` flag. B3b shipped a permanently blank page because a skeleton was keyed on a flag only the list thunk ever set, and A1 shipped a panel that would have rendered an empty state on a failed load.

- [ ] **Step 3: Mount it in `BookingDetail.tsx`**

Group the request's bookings by `environment_group_id`: one `GroupTransitionPanel` per distinct non-null group id, then the null-group bookings rendered as they are today.

- [ ] **Step 4: Run tests, typecheck, lint, commit**

Run: `cd frontend && npx vitest run src/components/bookings src/pages/bookings && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/components/bookings/ frontend/src/pages/bookings/BookingDetail.tsx
git commit -m "feat(env-groups): group transition controls on booking detail"
```

---

### Task 10: Environment detail, docs, and the browser pass

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`, `docs/phases/phase-7.md`, `docs/pagination.md`, `docs/admin-guide.md`, `docs/user-guide.md`

- [ ] **Step 1: Add "Member of" to environment detail**

A line listing the groups this environment belongs to, from `GET /environments/{id}/groups`, each linking to `/tenant/environment-groups/{id}`. Without it there is no way to discover why an environment got booked.

Test: the groups render from the API response; an empty state when there are none; a failed load renders an error rather than looking like "no groups".

- [ ] **Step 2: Update the four documents**

**`docs/phases/phase-7.md`** — tick **A2**, and add a "What A2 established" section on the model of the A1, B1, B3a and B3b sections already there. It must record: the atomic unit is `(request, group)`; membership is frozen at booking time so `environment_group_id` is provenance not a live link; the per-booking transition endpoint stays open and is the repair tool when members diverge; `usage_agreement` was deliberately untouched.

Also correct **A4**'s line if it does not already say so: A4 must decide whether contention resolves per environment or per group, because a group booking that loses one member is no longer a group booking.

**`docs/pagination.md`** — re-run the file's own reproducible grep and record the **delta this branch causes** rather than re-baselining. Add `GET /environment-groups`, `GET /environment-groups/{id}/members` and `GET /environments/{id}/groups` to the bounded table. Add a sortable-column row: sortable `name`, `created_at`; default `name` asc; **`member_count` permanently unsortable**. Note that the admin grid is client-side, matching the `tenant-groups` ‡ convention.

**`docs/admin-guide.md`** — the Environment Groups screen, and that **changing membership never affects existing bookings**.

**`docs/user-guide.md`** — booking a group, and that its environments are approved or rejected **together** while hand-picked environments on the same request are not.

- [ ] **Step 3: The browser pass**

Nine defects across the last four sub-projects were found only by opening the page with a fully green suite. Do this before claiming the task done.

With the stack running, as `admin` / `admin123` on tenant `demo`:

1. `/tenant/environment-groups` — create a group, add two environments, see the count.
2. Raise a booking selecting that group; confirm it creates one booking per member, each showing the group name.
3. On the booking detail, confirm members render **under the group** with one set of controls, and transition the group — all members move.
4. Add a hand-picked environment to the same request; confirm it renders **outside** the group panel and transitions independently.
5. Transition **one** member individually, then attempt the group transition — it must refuse and **name that environment**. Repair it, then confirm the group transition succeeds. This is the journey the design accepts.
6. Try to book two groups sharing an environment — the refusal must name both groups.
7. Add an environment to the group; confirm the **existing booking is unchanged**.
8. Check `/environments/{id}` shows "Member of".

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/environments/ docs/
git commit -m "feat(env-groups): environment group membership on environment detail, and document A2"
```

---

## Final verification

- [ ] **Backend, both engines** — `cd backend && uv run pytest -q -p no:logging`, then the PostgreSQL leg.
- [ ] **Frontend** — `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`.
- [ ] **Open a PR**

```bash
git push -u github feature/environment-groups
gh pr create --repo pjgross/envmgr --base main \
  --title "Phase 7 A2: environment groups and atomic group bookings"
```

The body should state that `booking.environment_group_id` finally has its FK after five months, that membership is frozen at booking time, that a group's members transition all-or-nothing while hand-picked environments on the same request stay independent, and that `usage_agreement` was deliberately untouched so A3 still owns only the check.
