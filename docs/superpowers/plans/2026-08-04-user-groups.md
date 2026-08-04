# User Groups + Environment Operations Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a generic tenant-scoped `UserGroup` with membership, plus an `operations_group_id` on `Environment` and the admin UI for both, so that B3b can route environment requests to the team that operates each environment.

**Architecture:** Two new tables (`user_group`, `user_group_member`) and one new nullable FK column on `environment`. The group is modelled on `environment_tier`, which is the closest existing tenant-scoped vocabulary — same soft-delete, same service-level name uniqueness, same CRUD shape. Membership is a junction table with hard deletes. Nothing in this plan changes authorization: group membership is data only.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 (backend); React 18, TypeScript, MUI DataGrid, Redux Toolkit (frontend). Tests: pytest (SQLite + PostgreSQL), vitest.

**Spec:** [docs/superpowers/specs/2026-08-04-user-groups-design.md](../specs/2026-08-04-user-groups-design.md)

## Global Constraints

- Every query on a tenant-scoped table filters by `current_user.active_tenant_id` — **never** `.tenant_id`, which is wrong under master-admin impersonation.
- All list endpoints take `page: Page = Depends(pagination())` and order by a **unique** key (append the primary key as a tiebreaker). Emit `X-Total-Count` via `set_total_count`.
- Enum columns use `native_enum=False`. This plan adds no enums.
- Migrations are written by hand. **Never** `alembic revision --autogenerate` — `init_db()` calls `create_all`, so autogenerate sees nothing to do.
- Entities soft-delete (`deleted_at`); junction rows hard-delete.
- Never call `db.commit()` in a service — `get_db()` auto-commits. Use `db.flush()` when you need an assigned id.
- Never point a test row at an id you did not create. Use `backend/tests/factories.py`.
- Cross-tenant ids return **404**, never 403.
- Frontend thunks reject with `rejectWithValue(formatApiError(err, '<fallback>'))`; components read `result.payload`, never `result.error.message`.
- Backend commands run from `backend/`; frontend commands from `frontend/`.
- Run the PostgreSQL leg before claiming a backend task done:
  `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`

## File Structure

**Backend — create**
- `app/db/models/user_group.py` — `UserGroup` and `UserGroupMember` models
- `app/db/migrations/versions/20260805_1000_usergroups_add_user_groups.py` — DDL
- `app/api/v1/schemas/user_group.py` — request/response schemas
- `app/services/user_group_service.py` — group CRUD + membership
- `app/api/v1/user_groups.py` — endpoints
- `tests/integration/test_user_groups_api.py`, `tests/services/test_user_group_service.py`, `tests/integration/test_user_group_isolation.py`

**Backend — modify**
- `app/db/models/environment.py` — add `operations_group_id`
- `app/main.py` — register the router
- `app/api/v1/schemas/environment.py` — add the two new fields
- `app/services/environment_service.py` — join, filter, `governance_gap`
- `app/api/v1/environments.py` — new query parameter
- `tests/factories.py` — `ensure_user_group`
- `tests/test_pagination.py`, `tests/test_sort_whitelist_contract.py`

**Frontend — create**
- `src/types/userGroup.ts`, `src/services/userGroupService.ts`, `src/store/userGroupSlice.ts`
- `src/pages/admin/UserGroups.tsx`, `src/pages/admin/UserGroupDetail.tsx`
- `src/pages/admin/__tests__/userGroups.test.tsx`, `src/pages/admin/__tests__/userGroupDetail.test.tsx`

**Frontend — modify**
- `src/constants/sortWhitelists.json`, `src/store/index.ts`, `src/App.tsx`, `src/pages/admin/AdminLayout.tsx`
- `src/types/environment.ts`, `src/pages/environments/EnvironmentList.tsx`, `src/pages/environments/EnvironmentDetail.tsx`

---

### Task 1: Models, migration, factory

**Files:**
- Create: `backend/app/db/models/user_group.py`
- Create: `backend/app/db/migrations/versions/20260805_1000_usergroups_add_user_groups.py`
- Modify: `backend/app/db/models/environment.py`
- Modify: `backend/tests/factories.py`
- Test: `backend/tests/test_user_group_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `UserGroup(tenant_id, name, description, deleted_at)`, `UserGroupMember(tenant_id, group_id, user_id)`, `Environment.operations_group_id`, and `ensure_user_group(db, tenant_id, name="fk-parent-group") -> UserGroup`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_user_group_model.py`:

```python
"""The two tables B3a adds, and the column that points at one of them."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.user_group import UserGroup, UserGroupMember
from tests.factories import ensure_environment, ensure_user, ensure_user_group


@pytest.mark.asyncio
async def test_group_persists_with_its_tenant(db_session, test_tenant):
    group = UserGroup(tenant_id=test_tenant.id, name="Platform Ops")
    db_session.add(group)
    await db_session.flush()

    assert group.id is not None
    assert group.deleted_at is None
    assert group.description is None


@pytest.mark.asyncio
async def test_a_user_cannot_join_the_same_group_twice(db_session, test_tenant):
    """UNIQUE(group_id, user_id) — the add-member endpoint relies on it."""
    group = await ensure_user_group(db_session, test_tenant.id)
    user = await ensure_user(db_session, test_tenant.id, username="member-a")

    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=user.id
    ))
    await db_session.flush()

    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=user.id
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_environment_can_name_its_operations_group(db_session, test_tenant):
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)

    env.operations_group_id = group.id
    await db_session.flush()

    stored = (await db_session.execute(
        select(UserGroup.id).where(UserGroup.id == env.operations_group_id)
    )).scalar_one()
    assert stored == group.id


@pytest.mark.asyncio
async def test_operations_group_is_nullable(db_session, test_tenant):
    """Legacy rows keep a null rather than a fabricated group — see the spec."""
    env = await ensure_environment(db_session, test_tenant.id, slot=2)
    assert env.operations_group_id is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_user_group_model.py -q -p no:logging`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.user_group'`

- [ ] **Step 3: Write the models**

Create `backend/app/db/models/user_group.py`:

```python
"""Tenant-scoped groups of users.

Deliberately generic rather than an "operations team": Phase 7 A1 adds
`Project` + members, also a container of users, and two unrelated membership
models would leave users asking which one to add someone to. Anything that
needs a group adds its own FK, the way `environment.operations_group_id` does.

Membership grants no permissions. Every authorization rule in this app is
role-based, and B3a deliberately does not add a second axis — see the spec.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserGroup(Base):
    """A named group of users within one tenant.

    Soft-deleted, because `environment.operations_group_id` and (later) B3b's
    request history keep pointing at it after retirement. Name uniqueness is
    enforced in the service, not by a constraint here: a partial unique index
    (`WHERE deleted_at IS NULL`) is inert on SQLite, so it would guard only the
    PostgreSQL leg while the SQLite leg passed regardless. Same call, and the
    same reason, as EnvironmentTier.
    """

    __tablename__ = "user_group"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<UserGroup(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class UserGroupMember(Base):
    """A user's membership of a group.

    Hard-deleted, per this codebase's convention for junction rows: removing
    someone from a team is routine and should not accumulate tombstones.

    `tenant_id` is denormalised (it is derivable through `group_id`) so this
    table obeys the same "every tenant-scoped query filters on tenant_id" rule
    as every other table here, without a join.
    """

    __tablename__ = "user_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_user_group_member"),
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<UserGroupMember(group_id={self.group_id}, user_id={self.user_id})>"
```

- [ ] **Step 4: Add the environment column**

In `backend/app/db/models/environment.py`, immediately after the `expires_at` field, add:

```python
    # The team that operates this environment. Nullable everywhere: existing
    # rows keep a null rather than a fabricated group, and `?governance_gap=`
    # reports it. B3b is where the constraint lands — it refuses to *route* a
    # request for an environment with no operating team, which is where the
    # requirement actually matters.
    operations_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True
    )
```

- [ ] **Step 5: Register the models for `create_all`**

Models must be imported before `Base.metadata.create_all` runs or the tables never exist in tests. Check how the other models are registered:

Run: `cd backend && grep -rn "environment_tier" app/db/base.py app/db/models/__init__.py app/main.py | head`

Add `user_group` alongside `environment_tier` in whichever file lists them, using the identical import style.

- [ ] **Step 6: Add the factory helper**

In `backend/tests/factories.py`, add the import `from app.db.models.user_group import UserGroup` alongside the other model imports, then add:

```python
async def ensure_user_group(
    db: AsyncSession, tenant_id: int, name: str = "fk-parent-group"
) -> UserGroup:
    """A real group for `tenant_id`. Idempotent per (tenant, name).

    `environment.operations_group_id` and `user_group_member.group_id` are both
    real FKs, so tests must never pass a bare `1`.
    """
    existing = (
        await db.execute(
            select(UserGroup).where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.name == name,
                UserGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    group = UserGroup(tenant_id=tenant_id, name=name)
    db.add(group)
    await db.flush()
    return group
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_user_group_model.py -q -p no:logging`
Expected: PASS, 4 passed

If `test_a_user_cannot_join_the_same_group_twice` fails with no `IntegrityError`, the SQLite FK/constraint pragma is not active — check `tests/conftest.py` still sets `PRAGMA foreign_keys=ON`.

- [ ] **Step 8: Write the migration**

Create `backend/app/db/migrations/versions/20260805_1000_usergroups_add_user_groups.py`:

```python
"""user groups + environment operations group

Revision ID: usergroups
Revises: envgovernance
Create Date: 2026-08-05 10:00:00.000000

Purely additive: two new tables and one nullable column. No backfill — an
environment with no operating team is a legitimate state that
`?governance_gap=` reports, not a defect to be papered over with a fabricated
group.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'usergroups'
down_revision: Union[str, None] = 'envgovernance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_group_tenant_id", "user_group", ["tenant_id"])

    op.create_table(
        "user_group_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["user_group.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_user_group_member"),
    )
    op.create_index("ix_user_group_member_tenant_id", "user_group_member", ["tenant_id"])
    op.create_index("ix_user_group_member_group_id", "user_group_member", ["group_id"])
    op.create_index("ix_user_group_member_user_id", "user_group_member", ["user_id"])

    op.add_column(
        "environment",
        sa.Column("operations_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_environment_operations_group",
        "environment", "user_group",
        ["operations_group_id"], ["id"],
    )
    op.create_index(
        "ix_environment_operations_group", "environment", ["operations_group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_environment_operations_group", table_name="environment")
    op.drop_constraint("fk_environment_operations_group", "environment", type_="foreignkey")
    op.drop_column("environment", "operations_group_id")

    op.drop_index("ix_user_group_member_user_id", table_name="user_group_member")
    op.drop_index("ix_user_group_member_group_id", table_name="user_group_member")
    op.drop_index("ix_user_group_member_tenant_id", table_name="user_group_member")
    op.drop_table("user_group_member")

    op.drop_index("ix_user_group_tenant_id", table_name="user_group")
    op.drop_table("user_group")
```

- [ ] **Step 9: Verify the migration builds the same schema the models do**

`tests/test_migration_schema_drift.py` builds a scratch database from the migrations and compares it to `create_all`. It is the guard that catches a hand-written migration disagreeing with its model.

Run: `cd backend && uv run pytest tests/test_migration_schema_drift.py -q -p no:logging`
Expected: PASS

If it reports a column-type or nullability difference, fix the **migration** to match the model, not the reverse.

- [ ] **Step 10: Apply the migration to the dev database**

Run: `cd backend && uv run alembic current` and confirm it prints `envgovernance` before continuing.

**Do not run `alembic downgrade -1` against the dev database to test the downgrade.** It steps back from the current head, not from your new revision — doing this previously dropped `tenant_secret` and destroyed a stored GitHub token. Step 9's scratch database already exercises both directions.

Run: `cd backend && uv run alembic upgrade head`
Expected: `Running upgrade envgovernance -> usergroups`

- [ ] **Step 11: Run both engines**

Run: `cd backend && uv run pytest tests/test_user_group_model.py tests/test_migration_schema_drift.py -q -p no:logging`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/test_user_group_model.py tests/test_migration_schema_drift.py -q -p no:logging`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add backend/app/db/models/user_group.py \
        backend/app/db/models/environment.py \
        backend/app/db/migrations/versions/20260805_1000_usergroups_add_user_groups.py \
        backend/tests/factories.py \
        backend/tests/test_user_group_model.py
git commit -m "feat(groups): add user_group, user_group_member and environment.operations_group_id"
```

---

### Task 2: Group CRUD service and API

**Files:**
- Create: `backend/app/api/v1/schemas/user_group.py`
- Create: `backend/app/services/user_group_service.py`
- Create: `backend/app/api/v1/user_groups.py`
- Create: `backend/tests/integration/test_user_groups_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_pagination.py`
- Modify: `backend/tests/test_sort_whitelist_contract.py`
- Modify: `frontend/src/constants/sortWhitelists.json`

**Interfaces:**
- Consumes: `UserGroup` from Task 1.
- Produces: `USER_GROUP_SORTS` (dict), and service functions `list_groups(db, tenant_id, *, page=None, sort=None, search=None) -> tuple[list[UserGroupView], int]`, `get_group(db, group_id, tenant_id) -> UserGroup`, `create_group`, `update_group`, `delete_group`. `UserGroupView` is a dataclass with `group: UserGroup`, `member_count: int`, `environment_count: int`. Endpoints are mounted at `/api/v1/tenant/groups`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_user_groups_api.py`:

```python
"""Group CRUD. Membership has its own file; environment wiring has another."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_environment, ensure_user_group


@pytest.mark.asyncio
async def test_create_and_list_a_group(client, auth_headers):
    created = await client.post(
        "/api/v1/tenant/groups",
        json={"name": "Platform Ops", "description": "Runs the SIT estate"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Platform Ops"

    listed = await client.get("/api/v1/tenant/groups", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [g["name"] for g in listed.json()] == ["Platform Ops"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_duplicate_name_is_a_409_naming_the_conflict(client, auth_headers):
    await client.post(
        "/api/v1/tenant/groups", json={"name": "Platform Ops"}, headers=auth_headers
    )
    again = await client.post(
        "/api/v1/tenant/groups", json={"name": "platform ops"}, headers=auth_headers
    )
    assert again.status_code == 409, again.text
    # Case-insensitive, like the tier vocabulary — "Platform Ops" and
    # "platform ops" are the same team to a human.
    assert "already exists" in again.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_carries_the_counts_the_grid_shows(
    client, auth_headers, db_session, test_tenant
):
    """member_count and environment_count travel with the row.

    Resolving them in the browser against a separately-fetched collection is
    the failure the pagination sweep documented — a capped collection makes a
    count silently wrong rather than absent.
    """
    group = await ensure_user_group(db_session, test_tenant.id, name="Counted")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()

    body = (await client.get("/api/v1/tenant/groups", headers=auth_headers)).json()
    row = next(g for g in body if g["name"] == "Counted")
    assert row["member_count"] == 0
    assert row["environment_count"] == 1


@pytest.mark.asyncio
async def test_detail_does_not_embed_the_member_list(
    client, auth_headers, db_session, test_tenant
):
    """An embedded list would be an unbounded nested collection — the exact
    shape `GET /releases/{id}/membership` had to have bounded after the fact."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Detail")
    await db_session.commit()

    body = (await client.get(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )).json()
    assert "members" not in body
    assert body["member_count"] == 0


@pytest.mark.asyncio
async def test_delete_names_the_environments_that_block_it(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Busy")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()

    refused = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert refused.status_code == 409, refused.text
    # The whole value of this response is *which* environments block it.
    assert env.name in refused.json()["detail"]


@pytest.mark.asyncio
async def test_delete_soft_deletes_when_nothing_references_it(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Free")
    await db_session.commit()

    gone = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text

    listed = (await client.get("/api/v1/tenant/groups", headers=auth_headers)).json()
    assert "Free" not in [g["name"] for g in listed]


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get(
        "/api/v1/tenant/groups?sort_by=nonsense", headers=auth_headers
    )
    assert bad.status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_user_groups_api.py -q -p no:logging`
Expected: FAIL — every test 404s, because the router does not exist yet.

- [ ] **Step 3: Write the schemas**

Create `backend/app/api/v1/schemas/user_group.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class UserGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None


class UserGroupResponse(BaseModel):
    """The counts travel with the row rather than being resolved in the browser.

    `member_count` is what the group detail page shows instead of an embedded
    member array; `environment_count` is the grid column. Both are computed in
    SQL, so neither is sortable — see USER_GROUP_SORTS.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    member_count: int = 0
    environment_count: int = 0
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "UserGroupResponse":
        return cls(
            id=view.group.id,
            tenant_id=view.group.tenant_id,
            name=view.group.name,
            description=view.group.description,
            member_count=view.member_count,
            environment_count=view.environment_count,
            created_at=view.group.created_at,
            updated_at=view.group.updated_at,
        )


class UserGroupMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str
    group_id: int
    created_at: datetime


class UserGroupMemberCreate(BaseModel):
    user_id: int
```

- [ ] **Step 4: Write the service**

Create `backend/app/services/user_group_service.py`:

```python
"""Tenant-scoped user groups — CRUD plus the counts the UI needs.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
Same reasoning as environment_tier_service.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.user_group import UserGroupCreate, UserGroupUpdate
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment import Environment
from app.db.models.user_group import UserGroup, UserGroupMember

# A 409 listing 200 environment names is not a message a human can read. Name
# the first few and count the rest.
_MAX_NAMED_BLOCKERS = 10


@dataclass
class UserGroupView:
    """A group plus the counts a UI needs without extra round-trips, following
    environment_service.EnvironmentView."""

    group: UserGroup
    member_count: int
    environment_count: int


def _member_count_clause():
    return (
        select(func.count(UserGroupMember.id))
        .where(UserGroupMember.group_id == UserGroup.id)
        .correlate(UserGroup)
        .scalar_subquery()
    )


def _environment_count_clause(tenant_id: int):
    return (
        select(func.count(Environment.id))
        .where(
            Environment.operations_group_id == UserGroup.id,
            Environment.tenant_id == tenant_id,
            # A soft-deleted environment is not a reference — counting it would
            # make a group undeletable forever once anything using it was
            # removed. Same call as environment_tier_service.delete_tier.
            Environment.deleted_at.is_(None),
        )
        .correlate(UserGroup)
        .scalar_subquery()
    )


def _view_query(tenant_id: int):
    return select(
        UserGroup,
        _member_count_clause(),
        _environment_count_clause(tenant_id),
    ).where(UserGroup.tenant_id == tenant_id, UserGroup.deleted_at.is_(None))


async def list_groups(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    search: Optional[str] = None,
) -> tuple[list[UserGroupView], int]:
    """Groups for a tenant, plus the unwindowed total.

    Every filter is applied in SQL. A filter applied in Python after the query
    would window the page before the filter — see docs/pagination.md.
    """
    query = _view_query(tenant_id)
    if search:
        query = query.where(UserGroup.name.ilike(f"%{search}%"))
    # Names are unique per tenant, but the case fold in apply_sort means two
    # names differing only in case stop being distinct keys — so the id
    # tiebreaker is what makes the order total.
    query = apply_sort(query, sort).order_by(func.lower(UserGroup.name), UserGroup.id)
    rows, total = await fetch_page_rows(db, query, page)
    return (
        [
            UserGroupView(group=g, member_count=m, environment_count=e)
            for g, m, e in rows
        ],
        total,
    )


async def get_group_view(
    db: AsyncSession, group_id: int, tenant_id: int
) -> UserGroupView:
    row = (
        await db.execute(_view_query(tenant_id).where(UserGroup.id == group_id))
    ).first()
    if row is None:
        # 404 rather than 403: a 403 would confirm the row exists in another
        # tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User group not found"
        )
    group, member_count, environment_count = row
    return UserGroupView(
        group=group, member_count=member_count, environment_count=environment_count
    )


async def get_group(db: AsyncSession, group_id: int, tenant_id: int) -> UserGroup:
    """The bare entity, for callers that do not need the counts."""
    group = (
        await db.execute(
            select(UserGroup).where(
                UserGroup.id == group_id,
                UserGroup.tenant_id == tenant_id,
                UserGroup.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User group not found"
        )
    return group


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(UserGroup.id).where(
        UserGroup.tenant_id == tenant_id,
        UserGroup.deleted_at.is_(None),
        func.lower(UserGroup.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(UserGroup.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A group named '{name.strip()}' already exists in this tenant",
        )


async def create_group(
    db: AsyncSession, data: UserGroupCreate, tenant_id: int
) -> UserGroupView:
    await _assert_name_free(db, tenant_id, data.name)
    group = UserGroup(
        tenant_id=tenant_id, name=data.name.strip(), description=data.description
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return UserGroupView(group=group, member_count=0, environment_count=0)


async def update_group(
    db: AsyncSession, group_id: int, data: UserGroupUpdate, tenant_id: int
) -> UserGroupView:
    group = await get_group(db, group_id, tenant_id)
    if data.name is not None and data.name.strip().lower() != group.name.lower():
        await _assert_name_free(db, tenant_id, data.name, exclude_id=group_id)
    if data.name is not None:
        group.name = data.name.strip()
    if data.description is not None:
        group.description = data.description
    await db.flush()
    return await get_group_view(db, group_id, tenant_id)


async def delete_group(db: AsyncSession, group_id: int, tenant_id: int) -> None:
    group = await get_group(db, group_id, tenant_id)
    blockers = list(
        (
            await db.execute(
                select(Environment.name)
                .where(
                    Environment.operations_group_id == group_id,
                    Environment.tenant_id == tenant_id,
                    Environment.deleted_at.is_(None),
                )
                .order_by(Environment.name)
                .limit(_MAX_NAMED_BLOCKERS + 1)
            )
        )
        .scalars()
        .all()
    )
    if blockers:
        named = blockers[:_MAX_NAMED_BLOCKERS]
        detail = (
            "This group operates "
            + ", ".join(named)
            + (
                f" and {len(blockers) - _MAX_NAMED_BLOCKERS} more"
                if len(blockers) > _MAX_NAMED_BLOCKERS
                else ""
            )
            + ". Reassign them before deleting it."
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # Membership rows are hard-deleted with the group: they are junction rows,
    # and a member of a retired group is not information anything reads.
    await db.execute(
        UserGroupMember.__table__.delete().where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.tenant_id == tenant_id,
        )
    )
    group.deleted_at = datetime.now(timezone.utc)
    await db.flush()
```

- [ ] **Step 5: Write the endpoints**

Create `backend/app/api/v1/user_groups.py`:

```python
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.user_group import (
    UserGroupCreate,
    UserGroupResponse,
    UserGroupUpdate,
)
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.db.models.user_group import UserGroup
from app.services import user_group_service

router = APIRouter()

# `member_count` and `environment_count` are deliberately absent: both are
# computed by a correlated subquery, not backed by a single column, so neither
# can be sorted server-side. The grid marks those columns sortable: false.
USER_GROUP_SORTS = {
    "name": UserGroup.name,
    "created_at": UserGroup.created_at,
}


@router.get("/groups", response_model=list[UserGroupResponse])
async def list_user_groups(
    response: Response,
    search: Optional[str] = Query(None, description="Case-insensitive name match."),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(USER_GROUP_SORTS, default="name")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Every group for the tenant. Readable by any member — B3b needs every
    user to see which team operates an environment, and the environment form
    needs the list as its picker source."""
    views, total = await user_group_service.list_groups(
        db, current_user.active_tenant_id, page=page, sort=sort, search=search
    )
    set_total_count(response, total)
    return [UserGroupResponse.from_view(v) for v in views]


@router.post(
    "/groups", response_model=UserGroupResponse, status_code=status.HTTP_201_CREATED
)
async def create_user_group(
    data: UserGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await user_group_service.create_group(
        db, data, current_user.active_tenant_id
    )
    return UserGroupResponse.from_view(view)


@router.get("/groups/{group_id}", response_model=UserGroupResponse)
async def get_user_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The group and its counts. The member list is a separate, bounded
    sub-resource — embedding it here would be an unbounded nested collection."""
    view = await user_group_service.get_group_view(
        db, group_id, current_user.active_tenant_id
    )
    return UserGroupResponse.from_view(view)


@router.patch("/groups/{group_id}", response_model=UserGroupResponse)
async def update_user_group(
    group_id: int,
    data: UserGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await user_group_service.update_group(
        db, group_id, data, current_user.active_tenant_id
    )
    return UserGroupResponse.from_view(view)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await user_group_service.delete_group(
        db, group_id, current_user.active_tenant_id
    )
```

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, add the import beside the other v1 routers:

```python
from app.api.v1 import user_groups as user_groups_router
```

and mount it under the same `/api/v1/tenant` prefix `tenant_admin_router` uses, so the paths are `/api/v1/tenant/groups`:

```python
app.include_router(
    user_groups_router.router, prefix="/api/v1/tenant", tags=["Tenant Admin"]
)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_user_groups_api.py -q -p no:logging`
Expected: PASS, 7 passed

- [ ] **Step 8: Add the pagination conformance row**

In `backend/tests/test_pagination.py`, add to the `BOUNDED_ENDPOINTS` list:

```python
    ("tenant_groups", "/api/v1/tenant/groups", MAX_LIMIT, "auth_headers"),
```

- [ ] **Step 9: Add the sort-whitelist contract entry**

In `backend/tests/test_sort_whitelist_contract.py`, add the import:

```python
from app.api.v1.user_groups import USER_GROUP_SORTS
```

and the entry in `WHITELISTS`:

```python
    "tenant-groups": (USER_GROUP_SORTS, "name", "asc"),
```

In `frontend/src/constants/sortWhitelists.json`, add the matching key:

```json
  "tenant-groups": {
    "sortable": ["name", "created_at"],
    "default": "name",
    "default_dir": "asc"
  }
```

- [ ] **Step 10: Run both engines**

Run: `cd backend && uv run pytest tests/integration/test_user_groups_api.py tests/test_pagination.py tests/test_sort_whitelist_contract.py -q -p no:logging`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/integration/test_user_groups_api.py tests/test_pagination.py tests/test_sort_whitelist_contract.py -q -p no:logging`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add backend/app/api/v1/schemas/user_group.py \
        backend/app/services/user_group_service.py \
        backend/app/api/v1/user_groups.py \
        backend/app/main.py \
        backend/tests/integration/test_user_groups_api.py \
        backend/tests/test_pagination.py \
        backend/tests/test_sort_whitelist_contract.py \
        frontend/src/constants/sortWhitelists.json
git commit -m "feat(groups): tenant-scoped user group CRUD API"
```

---

### Task 3: Membership service and API

**Files:**
- Modify: `backend/app/services/user_group_service.py`
- Modify: `backend/app/api/v1/user_groups.py`
- Create: `backend/tests/integration/test_user_group_members_api.py`
- Modify: `backend/tests/test_pagination.py`

**Interfaces:**
- Consumes: `get_group`, `UserGroupMemberResponse`, `UserGroupMemberCreate` from Task 2.
- Produces: `list_members(db, group_id, tenant_id, *, page=None) -> tuple[list[tuple[UserGroupMember, str]], int]`, `add_member(db, group_id, user_id, tenant_id) -> tuple[UserGroupMember, str]` (the member **and** the username, so the endpoint never re-queries for it), `remove_member(db, group_id, user_id, tenant_id) -> None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_user_group_members_api.py`:

```python
"""Membership add/remove/list, including the two cross-tenant write paths."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_user, ensure_user_group


@pytest.mark.asyncio
async def test_add_list_and_remove_a_member(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    added = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": user.id},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    # The username travels with the row — the browser must not resolve it
    # against a separately-fetched, capped user collection.
    assert added.json()["username"] == "ada"

    listed = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert [m["username"] for m in listed.json()] == ["ada"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1

    removed = await client.delete(
        f"/api/v1/tenant/groups/{group.id}/members/{user.id}", headers=auth_headers
    )
    assert removed.status_code == 204, removed.text

    empty = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members", headers=auth_headers
    )
    assert empty.json() == []


@pytest.mark.asyncio
async def test_adding_the_same_member_twice_is_a_409(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    payload = {"user_id": user.id}
    first = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members", json=payload, headers=auth_headers
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members", json=payload, headers=auth_headers
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_cannot_add_a_user_from_another_tenant(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """The FK-write direction of tenant isolation — the class the 2026-07-16
    audit found four of. A cross-tenant id is a 404, never a 403: a 403 would
    confirm the user exists."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    # The fixture yields a FACTORY, and the factory returns (tenant, user).
    other_tenant, _other_admin = await second_tenant_factory()
    outsider = await ensure_user(db_session, other_tenant.id, username="outsider")
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": outsider.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_cannot_touch_a_group_from_another_tenant(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    other_group = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/tenant/groups/{other_group.id}/members",
        json={"user_id": user.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_removing_a_non_member_is_a_404(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    missing = await client.delete(
        f"/api/v1/tenant/groups/{group.id}/members/{user.id}", headers=auth_headers
    )
    assert missing.status_code == 404, missing.text


@pytest.mark.asyncio
async def test_a_master_admin_can_add_members_while_impersonating(
    client, db_session, test_tenant
):
    """Under impersonation `current_user.id` and `active_tenant_id` belong to
    different tenants.

    A validation scoped to the caller's *home* tenant 404s a legitimate
    request — the bug that made an owner check fail and, in B1, escaped a
    per-row handler and killed an entire spreadsheet upload. The group and the
    user here both live in the impersonated tenant and the acting admin does
    not, so a home-tenant lookup finds neither.
    """
    from app.core.security import create_access_token, get_password_hash
    from app.db.models.user import Tenant, User

    home = Tenant(name="System Org", slug="system-groups-imp")
    db_session.add(home)
    await db_session.flush()
    master = User(
        tenant_id=home.id, username="groups-masteradmin", email="gm@imp.com",
        password_hash=get_password_hash("x"), role="Admin", is_active=True,
        is_master_admin=True,
    )
    db_session.add(master)

    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    member = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    token = create_access_token({
        "sub": str(master.id),
        "tenant_id": home.id,
        "impersonating_tenant_id": test_tenant.id,
    })
    headers = {"Authorization": f"Bearer {token}"}

    added = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": member.id},
        headers=headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["username"] == "ada"
```

- [ ] **Step 2: Fixture facts (already confirmed — do not re-derive)**

`second_tenant_factory` yields an async **factory**; calling it returns a
`(Tenant, User)` tuple, which is why the tests above unpack two names. Two
implementers on the previous plan each lost a cycle to this.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_user_group_members_api.py -q -p no:logging`
Expected: FAIL — 404 on the members routes, which do not exist.

- [ ] **Step 4: Add the membership service functions**

Append to `backend/app/services/user_group_service.py`:

```python
async def list_members(
    db: AsyncSession,
    group_id: int,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
) -> tuple[list[tuple[UserGroupMember, str]], int]:
    """Members of a group, each paired with the username.

    The username travels with the row rather than being resolved in the browser
    against `/tenant/users/lite`, which is capped — a `.find()` miss there would
    render the member as '—' and lose information no banner can recover.
    """
    await get_group(db, group_id, tenant_id)  # 404s for another tenant's group
    query = (
        select(UserGroupMember, User.username)
        .join(User, User.id == UserGroupMember.user_id)
        .where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.tenant_id == tenant_id,
        )
        # `username` is unique per tenant, but the case fold means two names
        # differing only in case stop being distinct keys — the id makes the
        # order total, which is what LIMIT/OFFSET requires.
        .order_by(func.lower(User.username), UserGroupMember.id)
    )
    return await fetch_page_rows(db, query, page)


async def add_member(
    db: AsyncSession, group_id: int, user_id: int, tenant_id: int
) -> tuple[UserGroupMember, str]:
    await get_group(db, group_id, tenant_id)

    # Validate the user against the ACTIVE tenant, not the caller's home
    # tenant: under master-admin impersonation those differ, and scoping this
    # to the wrong one 404s a legitimate request.
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    existing = (
        await db.execute(
            select(UserGroupMember.id).where(
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id == user_id,
            )
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{user.username} is already a member of this group",
        )

    member = UserGroupMember(
        tenant_id=tenant_id, group_id=group_id, user_id=user_id
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return member, user.username


async def remove_member(
    db: AsyncSession, group_id: int, user_id: int, tenant_id: int
) -> None:
    await get_group(db, group_id, tenant_id)
    member = (
        await db.execute(
            select(UserGroupMember).where(
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id == user_id,
                UserGroupMember.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This user is not a member of this group",
        )
    # Hard delete — a junction row, per this codebase's convention.
    await db.delete(member)
    await db.flush()
```

Add `from app.db.models.user import User` to the imports at the top of the file.

- [ ] **Step 5: Add the membership endpoints**

Append to `backend/app/api/v1/user_groups.py`:

```python
@router.get(
    "/groups/{group_id}/members", response_model=list[UserGroupMemberResponse]
)
async def list_user_group_members(
    group_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await user_group_service.list_members(
        db, group_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [
        UserGroupMemberResponse(
            id=m.id,
            user_id=m.user_id,
            username=username,
            group_id=m.group_id,
            created_at=m.created_at,
        )
        for m, username in rows
    ]


@router.post(
    "/groups/{group_id}/members",
    response_model=UserGroupMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_user_group_member(
    group_id: int,
    data: UserGroupMemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    member, username = await user_group_service.add_member(
        db, group_id, data.user_id, current_user.active_tenant_id
    )
    return UserGroupMemberResponse(
        id=member.id,
        user_id=member.user_id,
        username=username,
        group_id=member.group_id,
        created_at=member.created_at,
    )


@router.delete(
    "/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_user_group_member(
    group_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await user_group_service.remove_member(
        db, group_id, user_id, current_user.active_tenant_id
    )
```

Extend the schema import at the top of the file to include `UserGroupMemberCreate` and `UserGroupMemberResponse`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_user_group_members_api.py -q -p no:logging`
Expected: PASS, 6 passed

- [ ] **Step 7: Add the members endpoint to the pagination sweep**

The members route needs a real group id, so it does not fit `BOUNDED_ENDPOINTS`. Add this to `backend/tests/integration/test_user_group_members_api.py` instead:

```python
@pytest.mark.asyncio
async def test_members_endpoint_bounds_the_page(
    client, auth_headers, db_session, test_tenant
):
    from app.core.pagination import MAX_LIMIT

    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    for i in range(3):
        user = await ensure_user(db_session, test_tenant.id, username=f"member-{i}")
        await client.post(
            f"/api/v1/tenant/groups/{group.id}/members",
            json={"user_id": user.id},
            headers=auth_headers,
        )
    await db_session.commit()

    windowed = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members?limit=2", headers=auth_headers
    )
    assert len(windowed.json()) == 2
    assert int(windowed.headers[TOTAL_COUNT_HEADER]) == 3

    over = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members?limit={MAX_LIMIT + 1}",
        headers=auth_headers,
    )
    assert over.status_code == 422
```

Note: `ensure_user` flushes but the POST runs in a different session — call `await db_session.commit()` before the first POST if the users are not visible. Run the test and adjust if it fails on a missing user.

- [ ] **Step 8: Run both engines**

Run: `cd backend && uv run pytest tests/integration/test_user_group_members_api.py -q -p no:logging`
Expected: PASS, 7 passed

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/integration/test_user_group_members_api.py -q -p no:logging`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/user_group_service.py \
        backend/app/api/v1/user_groups.py \
        backend/tests/integration/test_user_group_members_api.py
git commit -m "feat(groups): group membership add, remove and bounded list"
```

---

### Task 4: Environment integration (backend)

**Files:**
- Modify: `backend/app/api/v1/schemas/environment.py`
- Modify: `backend/app/services/environment_service.py`
- Modify: `backend/app/api/v1/environments.py`
- Create: `backend/tests/integration/test_environment_operations_group.py`

**Interfaces:**
- Consumes: `UserGroup` (Task 1), `get_group` (Task 2).
- Produces: `EnvironmentResponse.operations_group_id`, `EnvironmentResponse.operations_group_name`; `?operations_group_id=` on `GET /environments/`; `?governance_gap=true` now also matches a missing operations group.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_operations_group.py`:

```python
"""The operations group as seen from the environment side."""
import pytest

from tests.factories import ensure_user_group, post_environment


@pytest.mark.asyncio
async def test_environment_read_carries_the_group_name(
    client, auth_headers, db_session, test_tenant
):
    """The name travels with the row, like tier_name and owner_username.

    Resolving it in the browser against the groups collection is the failure
    the pagination sweep documented: a `.find()` miss renders '—', which is
    information lost rather than hidden.
    """
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()

    created = await post_environment(
        client, auth_headers, "ops-env", operations_group_id=group.id
    )
    assert created.status_code == 201, created.text
    assert created.json()["operations_group_id"] == group.id
    assert created.json()["operations_group_name"] == "Platform Ops"


@pytest.mark.asyncio
async def test_operations_group_is_optional_on_create(client, auth_headers):
    created = await post_environment(client, auth_headers, "no-ops-env")
    assert created.status_code == 201, created.text
    assert created.json()["operations_group_id"] is None
    assert created.json()["operations_group_name"] is None


@pytest.mark.asyncio
async def test_explicit_null_clears_the_group(
    client, auth_headers, db_session, test_tenant
):
    """`operations_group_id` is typed `int | null`, not optional: the backend
    keys on model_fields_set, so an omitted key means 'leave alone' and only an
    explicit null can clear the field. Same contract B1 gave expires_at."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()
    env_id = (
        await post_environment(
            client, auth_headers, "clearable", operations_group_id=group.id
        )
    ).json()["id"]

    untouched = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"description": "still owned by ops"},
        headers=auth_headers,
    )
    assert untouched.json()["operations_group_id"] == group.id

    cleared = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"operations_group_id": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["operations_group_id"] is None


@pytest.mark.asyncio
async def test_cannot_point_at_another_tenants_group(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """The FK-write gap this change adds. 404, not 403."""
    # The fixture yields a FACTORY, and the factory returns (tenant, user).
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    refused = await post_environment(
        client, auth_headers, "leaky", operations_group_id=theirs.id
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_a_soft_deleted_group_still_renders_its_name(
    client, auth_headers, db_session, test_tenant
):
    """Blanking the field would make a populated control render empty while
    form state still holds the id — the MUI out-of-range warning B1 hit with
    retired tiers and deactivated owners."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Retired Ops")
    await db_session.commit()
    env_id = (
        await post_environment(
            client, auth_headers, "orphaned", operations_group_id=group.id
        )
    ).json()["id"]

    deleted = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert deleted.status_code == 409, "the environment should block the delete"

    # Soft-delete it directly to reach the state a reassign-then-delete leaves.
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.db.models.user_group import UserGroup

    stored = (await db_session.execute(
        select(UserGroup).where(UserGroup.id == group.id)
    )).scalar_one()
    stored.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    read = await client.get(f"/api/v1/environments/{env_id}", headers=auth_headers)
    assert read.json()["operations_group_name"] == "Retired Ops"


@pytest.mark.asyncio
async def test_governance_gap_reports_a_missing_operations_group(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()
    await post_environment(client, auth_headers, "has-ops", operations_group_id=group.id)
    await post_environment(client, auth_headers, "no-ops")

    gaps = await client.get(
        "/api/v1/environments/?governance_gap=true", headers=auth_headers
    )
    assert gaps.status_code == 200, gaps.text
    names = [e["name"] for e in gaps.json()]
    assert "no-ops" in names
    assert "has-ops" not in names


@pytest.mark.asyncio
async def test_filtering_by_operations_group(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()
    await post_environment(client, auth_headers, "mine", operations_group_id=group.id)
    await post_environment(client, auth_headers, "theirs")

    filtered = await client.get(
        f"/api/v1/environments/?operations_group_id={group.id}", headers=auth_headers
    )
    assert [e["name"] for e in filtered.json()] == ["mine"]
```

- [ ] **Step 2: Factory facts (already confirmed — do not re-derive)**

`post_environment(client, headers, name, **extra)` resolves a SIT tier over
HTTP, sets `owner_user_id` from `/auth/me` and an expiry a year out, then
`body.update(extra)` — so `operations_group_id=` passes straight through and
needs no change. `second_tenant_factory` returns a `(Tenant, User)` tuple, which
is why the test above unpacks two names.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_operations_group.py -q -p no:logging`
Expected: FAIL — `KeyError: 'operations_group_id'` on the response body.

- [ ] **Step 4: Extend the schemas**

In `backend/app/api/v1/schemas/environment.py`:

Add to `EnvironmentCreate`, after `owner_user_id`:

```python
    operations_group_id: Optional[int] = None
```

Add to `EnvironmentUpdate`, after `owner_user_id`:

```python
    # `int | None`, not Optional-with-default-sentinel: the service keys on
    # model_fields_set, so an omitted key means "leave alone" and only an
    # explicit null clears the group. Same contract as expires_at.
    operations_group_id: Optional[int] = None
```

Add to `EnvironmentResponse`, after `owner_username`:

```python
    operations_group_id: Optional[int] = None
    operations_group_name: Optional[str] = None
```

and pass both through in `from_view`:

```python
            operations_group_id=env.operations_group_id,
            operations_group_name=view.operations_group_name,
```

- [ ] **Step 5: Extend the service view**

In `backend/app/services/environment_service.py`:

Add to the `EnvironmentView` dataclass, after `owner_username`:

```python
    operations_group_name: Optional[str]
```

Add `from app.db.models.user_group import UserGroup` to the imports.

In `_view_query`, add `UserGroup.name` to the select list after `User.username`, and add the outer join. **The join must be tenant-qualified** for the same defence-in-depth reason the tier and owner joins are — a malformed row must not surface another tenant's name:

```python
        .outerjoin(
            UserGroup,
            and_(
                UserGroup.id == Environment.operations_group_id,
                UserGroup.tenant_id == tenant_id,
            ),
        )
```

Note this is an `outerjoin` with **no `deleted_at` filter**: a soft-deleted group must still render its name, per the spec.

Update every unpack of `_view_query`'s rows to take the extra column, and pass it into `EnvironmentView(...)`. Run `grep -n "_view_query" app/services/environment_service.py` to find them all — `get_environment` unpacks it too, not only `list_environments`.

- [ ] **Step 6: Extend the governance-gap filter**

Replace the `governance_gap` branch in `list_environments`:

```python
    if governance_gap is True:
        # A null expiry is a legitimate "no expiry planned" state, not a gap —
        # see the product decision on update_environment's compliance rule
        # below. The gaps are a missing OWNER or a missing OPERATIONS GROUP.
        query = query.where(
            or_(
                Environment.owner_user_id.is_(None),
                Environment.operations_group_id.is_(None),
            )
        )
    elif governance_gap is False:
        query = query.where(
            Environment.owner_user_id.is_not(None),
            Environment.operations_group_id.is_not(None),
        )
```

Add `or_` to the `sqlalchemy` import line if it is not already there.

- [ ] **Step 7: Add the filter parameter and the FK validation**

In `list_environments`, add the keyword argument `operations_group_id: Optional[int] = None` and the filter:

```python
    if operations_group_id is not None:
        query = query.where(Environment.operations_group_id == operations_group_id)
```

In the create and update paths, validate the group the same way the owner is validated. Find the existing owner validation with `grep -n "owner_user_id" app/services/environment_service.py` and add alongside it:

```python
    if operations_group_id is not None:
        # Scoped to the ACTIVE tenant. Under master-admin impersonation
        # current_user.id and active_tenant_id belong to different tenants, and
        # scoping this to the wrong one 404s a legitimate request — the bug
        # that killed an entire spreadsheet upload in B1.
        await user_group_service.get_group(db, operations_group_id, tenant_id)
```

Import it as `from app.services import user_group_service`. If that creates a circular import (because `user_group_service` imports `Environment`), import inside the function instead and leave a one-line comment saying why.

- [ ] **Step 8: Wire the endpoint parameter**

In `backend/app/api/v1/environments.py`, add to the list endpoint signature:

```python
    operations_group_id: Optional[int] = Query(
        None, description="Only environments operated by this group."
    ),
```

and forward it into the `environment_service.list_environments(...)` call.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_environment_operations_group.py -q -p no:logging`
Expected: PASS, 7 passed

- [ ] **Step 10: Run the full backend suite on both engines**

This task touches `_view_query`, which every environment read path uses — the regression surface is wide.

Run: `cd backend && uv run pytest -q -p no:logging`
Expected: PASS, no failures

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q -p no:logging`
Expected: PASS, no failures

- [ ] **Step 11: Commit**

```bash
git add backend/app/api/v1/schemas/environment.py \
        backend/app/services/environment_service.py \
        backend/app/api/v1/environments.py \
        backend/tests/integration/test_environment_operations_group.py
git commit -m "feat(environments): operations group field, filter and governance gap"
```

---

### Task 5: Frontend types, service and Redux slice

**Files:**
- Create: `frontend/src/types/userGroup.ts`
- Create: `frontend/src/services/userGroupService.ts`
- Create: `frontend/src/store/userGroupSlice.ts`
- Create: `frontend/src/store/__tests__/userGroupSlice.test.ts`
- Modify: `frontend/src/store/index.ts`
- Modify: `frontend/src/types/environment.ts`

**Interfaces:**
- Consumes: the API from Tasks 2–4.
- Produces: `userGroupService` with `listGroups`, `createGroup`, `updateGroup`, `deleteGroup`, `listMembers`, `addMember`, `removeMember`; thunks `fetchUserGroups`, `createUserGroup`, `updateUserGroup`, `deleteUserGroup`, `fetchGroupMembers`, `addGroupMember`, `removeGroupMember`; state at `state.userGroup` with `{ groups, total, members, memberTotal, loading, error }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/store/__tests__/userGroupSlice.test.ts`:

```typescript
import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import userGroupReducer, { deleteUserGroup, fetchUserGroups } from '../userGroupSlice';
import { userGroupService } from '../../services/userGroupService';

vi.mock('../../services/userGroupService', () => ({
  userGroupService: {
    listGroups: vi.fn(),
    deleteGroup: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { userGroup: userGroupReducer } });
}

describe('userGroupSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores the rows and the server total, not the row count', async () => {
    // The total is what tells a paged grid there is more; deriving it from
    // rows.length would report the page size as the whole set.
    vi.mocked(userGroupService.listGroups).mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'Platform Ops',
          description: null,
          member_count: 3,
          environment_count: 2,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 42,
    });

    const store = makeStore();
    await store.dispatch(fetchUserGroups({}));

    expect(store.getState().userGroup.groups).toHaveLength(1);
    expect(store.getState().userGroup.total).toBe(42);
  });

  it('surfaces the server reason when a delete is refused', async () => {
    // Shaped like a real AxiosError: `.message` is the generic HTTP-status
    // text, and the reason lives only at `response.data.detail`. Redux
    // Toolkit's miniSerializeError drops `response`, so a thunk that let the
    // error escape could only ever yield the generic string.
    vi.mocked(userGroupService.deleteGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: 'This group operates Mortgage SIT. Reassign them before deleting it.' },
      },
    });

    const store = makeStore();
    const result = await store.dispatch(deleteUserGroup(1));

    expect(deleteUserGroup.rejected.match(result)).toBe(true);
    expect(result.payload).toBe(
      'This group operates Mortgage SIT. Reassign them before deleting it.'
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/store/__tests__/userGroupSlice.test.ts`
Expected: FAIL — cannot resolve `../userGroupSlice`

- [ ] **Step 3: Write the types**

Create `frontend/src/types/userGroup.ts`:

```typescript
export interface UserGroupResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  /** Computed in SQL, so not sortable server-side — the grid column sets sortable: false. */
  member_count: number;
  environment_count: number;
  created_at: string;
  updated_at: string;
}

export interface UserGroupCreate {
  name: string;
  description?: string | null;
}

export interface UserGroupUpdate {
  name?: string;
  description?: string | null;
}

export interface UserGroupMemberResponse {
  id: number;
  user_id: number;
  /** Travels with the row — never resolved against the capped users list. */
  username: string;
  group_id: number;
  created_at: string;
}
```

Add to `frontend/src/types/environment.ts`, on the environment response interface:

```typescript
  operations_group_id: number | null;
  operations_group_name: string | null;
```

and on the create/update payload interfaces:

```typescript
  operations_group_id?: number | null;
```

- [ ] **Step 4: Write the service**

Create `frontend/src/services/userGroupService.ts`:

```typescript
import api from './api';
import type {
  UserGroupCreate,
  UserGroupMemberResponse,
  UserGroupResponse,
  UserGroupUpdate,
} from '../types/userGroup';
import type { Paged } from '../types/pagination';

export const userGroupService = {
  listGroups: (params?: {
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
    search?: string;
  }): Promise<Paged<UserGroupResponse>> =>
    api.get<UserGroupResponse[]>('/tenant/groups', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  createGroup: (data: UserGroupCreate): Promise<UserGroupResponse> =>
    api.post('/tenant/groups', data).then((r) => r.data),

  updateGroup: (id: number, data: UserGroupUpdate): Promise<UserGroupResponse> =>
    api.patch(`/tenant/groups/${id}`, data).then((r) => r.data),

  deleteGroup: (id: number): Promise<void> =>
    api.delete(`/tenant/groups/${id}`).then((r) => r.data),

  listMembers: (
    groupId: number,
    params?: { limit?: number; offset?: number }
  ): Promise<Paged<UserGroupMemberResponse>> =>
    api
      .get<UserGroupMemberResponse[]>(`/tenant/groups/${groupId}/members`, { params })
      .then((r) => ({
        rows: r.data,
        total: Number(r.headers['x-total-count'] ?? r.data.length),
      })),

  addMember: (groupId: number, userId: number): Promise<UserGroupMemberResponse> =>
    api.post(`/tenant/groups/${groupId}/members`, { user_id: userId }).then((r) => r.data),

  removeMember: (groupId: number, userId: number): Promise<void> =>
    api.delete(`/tenant/groups/${groupId}/members/${userId}`).then((r) => r.data),
};
```

- [ ] **Step 5: Write the slice**

Create `frontend/src/store/userGroupSlice.ts`:

```typescript
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { userGroupService } from '../services/userGroupService';
import { formatApiError } from '../services/apiError';
import type {
  UserGroupCreate,
  UserGroupMemberResponse,
  UserGroupResponse,
  UserGroupUpdate,
} from '../types/userGroup';

interface UserGroupState {
  groups: UserGroupResponse[];
  total: number;
  members: UserGroupMemberResponse[];
  memberTotal: number;
  loading: boolean;
  error: string | null;
}

const initialState: UserGroupState = {
  groups: [],
  total: 0,
  members: [],
  memberTotal: 0,
  loading: false,
  error: null,
};

// Every thunk rejects with `rejectWithValue(formatApiError(...))` rather than
// letting the axios error escape. Redux Toolkit serialises an escaping error
// with miniSerializeError, which copies only name/message/stack/code —
// `response.data.detail`, where the backend puts its reason, is dropped, and a
// real AxiosError's `.message` is the generic "Request failed with status code
// 409". Consumers read `result.payload`, never `result.error.message`.

export const fetchUserGroups = createAsyncThunk<
  { rows: UserGroupResponse[]; total: number },
  Parameters<typeof userGroupService.listGroups>[0],
  { rejectValue: string }
>('userGroup/fetch', async (params, { rejectWithValue }) => {
  try {
    return await userGroupService.listGroups(params);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load user groups'));
  }
});

export const createUserGroup = createAsyncThunk<
  UserGroupResponse,
  UserGroupCreate,
  { rejectValue: string }
>('userGroup/create', async (data, { rejectWithValue }) => {
  try {
    return await userGroupService.createGroup(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create user group'));
  }
});

export const updateUserGroup = createAsyncThunk<
  UserGroupResponse,
  { id: number; data: UserGroupUpdate },
  { rejectValue: string }
>('userGroup/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await userGroupService.updateGroup(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update user group'));
  }
});

export const deleteUserGroup = createAsyncThunk<number, number, { rejectValue: string }>(
  'userGroup/delete',
  async (id, { rejectWithValue }) => {
    try {
      await userGroupService.deleteGroup(id);
      return id;
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to delete user group'));
    }
  }
);

export const fetchGroupMembers = createAsyncThunk<
  { rows: UserGroupMemberResponse[]; total: number },
  number,
  { rejectValue: string }
>('userGroup/fetchMembers', async (groupId, { rejectWithValue }) => {
  try {
    return await userGroupService.listMembers(groupId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load members'));
  }
});

export const addGroupMember = createAsyncThunk<
  UserGroupMemberResponse,
  { groupId: number; userId: number },
  { rejectValue: string }
>('userGroup/addMember', async ({ groupId, userId }, { rejectWithValue }) => {
  try {
    return await userGroupService.addMember(groupId, userId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to add member'));
  }
});

export const removeGroupMember = createAsyncThunk<
  number,
  { groupId: number; userId: number },
  { rejectValue: string }
>('userGroup/removeMember', async ({ groupId, userId }, { rejectWithValue }) => {
  try {
    await userGroupService.removeMember(groupId, userId);
    return userId;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to remove member'));
  }
});

const userGroupSlice = createSlice({
  name: 'userGroup',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchUserGroups.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchUserGroups.fulfilled, (state, action) => {
        state.loading = false;
        state.groups = action.payload.rows;
        // The server total, never rows.length — a page's length is not the set.
        state.total = action.payload.total;
      })
      .addCase(fetchUserGroups.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load user groups';
      })
      .addCase(fetchGroupMembers.fulfilled, (state, action) => {
        state.members = action.payload.rows;
        state.memberTotal = action.payload.total;
      })
      .addCase(addGroupMember.fulfilled, (state, action) => {
        state.members.push(action.payload);
        state.memberTotal += 1;
      })
      .addCase(removeGroupMember.fulfilled, (state, action) => {
        state.members = state.members.filter((m) => m.user_id !== action.payload);
        state.memberTotal -= 1;
      });
    // Deliberately no fulfilled handlers for create/update/delete of groups:
    // the list is a server-paged slice, and splicing a row into or out of it
    // desynchronises the page from its total. The pages refetch instead.
  },
});

export default userGroupSlice.reducer;
```

- [ ] **Step 6: Register the reducer**

In `frontend/src/store/index.ts`, add `userGroup: userGroupReducer` to the `reducer` map, importing it the same way the neighbouring slices are imported.

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/store/__tests__/userGroupSlice.test.ts`
Expected: PASS, 2 passed

- [ ] **Step 8: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no output (exit 0)

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/userGroup.ts \
        frontend/src/types/environment.ts \
        frontend/src/services/userGroupService.ts \
        frontend/src/store/userGroupSlice.ts \
        frontend/src/store/index.ts \
        frontend/src/store/__tests__/userGroupSlice.test.ts
git commit -m "feat(groups): frontend types, service and Redux slice"
```

---

### Task 6: User Groups admin screen

**Files:**
- Create: `frontend/src/pages/admin/UserGroups.tsx`
- Create: `frontend/src/pages/admin/UserGroupDetail.tsx`
- Create: `frontend/src/pages/admin/__tests__/userGroups.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx`

**Interfaces:**
- Consumes: the slice from Task 5.
- Produces: routes `/tenant/groups` and `/tenant/groups/:id`; the exported `userGroupColumns` array for column assertions.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/admin/__tests__/userGroups.test.tsx`:

```tsx
import type { ReactNode } from 'react';
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import UserGroups, { userGroupColumns } from '../UserGroups';
import userGroupReducer from '../../../store/userGroupSlice';
import { userGroupService } from '../../../services/userGroupService';
import whitelists from '../../../constants/sortWhitelists.json';

vi.mock('../../../services/userGroupService', () => ({
  userGroupService: {
    listGroups: vi.fn(),
    createGroup: vi.fn(),
    updateGroup: vi.fn(),
    deleteGroup: vi.fn(),
  },
}));

// See environmentTiersPanel.test.tsx: the real DataGrid virtualizes columns by
// container width and jsdom reports zero width, so the actions column never
// mounts. This stand-in renders every column's cell.
vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  return {
    ...actual,
    DataGrid: (props: Record<string, unknown>) => {
      const rows = props.rows as Array<Record<string, unknown>>;
      const columns = props.columns as Array<{
        field: string;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        renderCell?: (params: any) => ReactNode;
      }>;
      return (
        <table>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)}>
                {columns.map((col) => (
                  <td key={col.field}>
                    {col.renderCell
                      ? col.renderCell({ row, value: row[col.field], id: row.id })
                      : String(row[col.field] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    },
  };
});

function renderPage() {
  const store = configureStore({ reducer: { userGroup: userGroupReducer } });
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/tenant/groups']}>
        <UserGroups />
      </MemoryRouter>
    </Provider>
  );
}

describe('UserGroups', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(userGroupService.listGroups).mockResolvedValue({
      rows: [
        {
          id: 1,
          tenant_id: 1,
          name: 'Platform Ops',
          description: 'Runs the SIT estate',
          member_count: 3,
          environment_count: 2,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
    });
  });

  it('marks every column the backend cannot sort as unsortable', () => {
    // The contract docs/pagination.md describes: a sortable header whose field
    // the backend does not whitelist looks clickable and 422s on click.
    // member_count and environment_count are correlated subqueries, not
    // columns, so they can never be whitelisted.
    const sortable = new Set(whitelists['tenant-groups'].sortable as string[]);
    userGroupColumns.forEach((col) => {
      if (col.sortable !== false) {
        expect(sortable.has(col.field)).toBe(true);
      }
    });
    const byField = Object.fromEntries(userGroupColumns.map((c) => [c.field, c]));
    expect(byField.member_count.sortable).toBe(false);
    expect(byField.environment_count.sortable).toBe(false);
  });

  it('renders the counts that came with the row', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('names the blocking environments when a delete is refused', async () => {
    // The whole value of this 409 is *which* environments block it. An admin
    // told only "in use" has to go hunting.
    vi.mocked(userGroupService.deleteGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: {
          detail: 'This group operates Mortgage SIT. Reassign them before deleting it.',
        },
      },
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('Platform Ops')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    await waitFor(() =>
      expect(screen.getByText(/This group operates Mortgage SIT/)).toBeInTheDocument()
    );
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/__tests__/userGroups.test.tsx`
Expected: FAIL — cannot resolve `../UserGroups`

- [ ] **Step 3: Write the list page**

Create `frontend/src/pages/admin/UserGroups.tsx`. Model it on `frontend/src/components/admin/EnvironmentTiersPanel.tsx` — read that file first and follow its structure for the create/edit dialog, the delete confirmation and the error `Alert` placement.

The two parts the tests assert on directly, written out in full — the columns array and the delete handler:

```tsx
// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "tenant-groups"): `name` and `created_at` ONLY. `description` is an ordinary
// visible column the backend does not whitelist. `member_count` and
// `environment_count` are correlated subqueries rather than columns, so they can
// never be whitelisted — sorting by them is a genuine capability the server-side
// grid gives up, the same trade the twelve computed columns elsewhere make. A
// sortable header on any of these 422s on first click.
// eslint-disable-next-line react-refresh/only-export-components
export const userGroupColumns: GridColDef<UserGroupResponse>[] = [
  { field: 'name', headerName: 'Name', flex: 1 },
  { field: 'description', headerName: 'Description', flex: 2, sortable: false,
    renderCell: (params) => (params.value as string | null) ?? '—' },
  { field: 'member_count', headerName: 'Members', width: 110, sortable: false },
  { field: 'environment_count', headerName: 'Environments', width: 140, sortable: false },
  { field: 'actions', headerName: '', width: 140, sortable: false, disableColumnMenu: true },
];
```

The `actions` column's `renderCell` is added inside the component (it needs the handlers), following how `EnvironmentTiersPanel` does it. Its delete button's label must be exactly `Delete` so the test's `/^delete$/i` matcher finds it.

```tsx
  const handleDeleteConfirm = async () => {
    if (deleteId === null) return;
    setDeleteError(null);
    const result = await dispatch(deleteUserGroup(deleteId));
    if (deleteUserGroup.rejected.match(result)) {
      // `payload`, not `error.message`. The server's 409 names the environments
      // that block the delete, and that is the entire value of the response —
      // miniSerializeError would replace it with "Request failed with status
      // code 409" and send the admin hunting.
      setDeleteError(result.payload ?? 'Failed to delete user group');
      return;
    }
    setDeleteOpen(false);
    setDeleteId(null);
    // Refetch rather than splicing the row out locally: the list is one
    // server-paged window, and local surgery desynchronises the page from its
    // total once a second page exists.
    dispatch(fetchUserGroups({}));
  };
```

with the dialog rendering it:

```tsx
      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete User Group</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Are you sure you want to delete this group? Its members will be removed.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteConfirm}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
```

The remaining boilerplate follows `EnvironmentTiersPanel` exactly:

- `dispatch(fetchUserGroups({}))` in a `useEffect` on mount.
- Row click navigates to `/tenant/groups/${id}`.
- Create and Edit dialogs with a required Name and an optional Description, each reading `result.payload` on rejection into an `Alert severity="error"` inside the dialog, and each re-dispatching `fetchUserGroups({})` on success.

- [ ] **Step 4: Write the detail page**

Create `frontend/src/pages/admin/UserGroupDetail.tsx`:

The picker fetch, written out because its comment carries a decision that must not be lost:

```tsx
  // GET /tenant/users/lite is bounded, but at its own larger contract
  // (default 1000, max 5000) rather than the shared 500/1000 — a truncated
  // picker loses users rather than shortening a page. A tenant past 1000
  // active users needs a type-to-search picker here; see docs/pagination.md.
  // (EnvironmentList and GatesTable call it the same way.)
  const [users, setUsers] = useState<Array<{ id: number; username: string }>>([]);
  useEffect(() => {
    api
      .get<Array<{ id: number; username: string }>>('/tenant/users/lite')
      .then((r) => setUsers(r.data))
      .catch(() => setUsers([])); // member picker stays empty on failure
  }, []);
```

and the add handler:

```tsx
  const handleAddMember = async () => {
    if (!selectedUserId) return;
    setAddError(null);
    const result = await dispatch(
      addGroupMember({ groupId, userId: Number(selectedUserId) })
    );
    if (addGroupMember.rejected.match(result)) {
      // `payload`, not `error.message` — the 409 says who is already a member.
      setAddError(result.payload ?? 'Failed to add member');
      return;
    }
    setSelectedUserId('');
  };
```

The rest:

- Reads `:id` from the route, dispatches `fetchGroupMembers(id)` on mount.
- Renders the group name and description, and the member list as a simple MUI `Table` — a DataGrid is unnecessary for a member list and harder to test.
- Each member row has a Remove button dispatching `removeGroupMember({ groupId, userId })`, surfacing `result.payload` on rejection the same way.
- The members come from the bounded `/tenant/groups/{id}/members` sub-resource via `fetchGroupMembers`, **not** from an embedded array on the group — the detail endpoint deliberately does not carry one.

- [ ] **Step 5: Wire the routes and the nav**

In `frontend/src/App.tsx`, beside the other `/tenant/*` routes:

```tsx
<Route path="/tenant/groups" element={<UserGroups />} />
<Route path="/tenant/groups/:id" element={<UserGroupDetail />} />
```

Import both lazily if the neighbouring admin routes are lazy — check how `/tenant/users` is imported and match it, since the bundle is code-split.

In `frontend/src/pages/admin/AdminLayout.tsx`, add to the nav list after the User Management entry:

```tsx
  { label: 'User Groups', path: '/tenant/groups', icon: <GroupsIcon fontSize="small" /> },
```

with `import GroupsIcon from '@mui/icons-material/Groups';` at the top.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/admin/__tests__/userGroups.test.tsx`
Expected: PASS, 3 passed

- [ ] **Step 7: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit`
Expected: no output (exit 0)

Run: `cd frontend && npm run lint`
Expected: no output beyond the npm banner

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/admin/UserGroups.tsx \
        frontend/src/pages/admin/UserGroupDetail.tsx \
        frontend/src/pages/admin/__tests__/userGroups.test.tsx \
        frontend/src/App.tsx \
        frontend/src/pages/admin/AdminLayout.tsx
git commit -m "feat(groups): User Groups admin screen with membership management"
```

---

### Task 7: Environment UI integration

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentList.tsx`
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`
- Modify: `frontend/src/pages/environments/__tests__/environmentListServerGrid.test.tsx`

**Interfaces:**
- Consumes: `userGroupService.listGroups` (Task 5), `operations_group_id` / `operations_group_name` on the environment response (Task 4).
- Produces: nothing downstream in B3a.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/environments/__tests__/environmentListServerGrid.test.tsx`, inside the existing top-level `describe`:

```tsx
  it('renders the operations group name that came with the row', async () => {
    // The name travels with the row. Resolving it against the groups
    // collection would render '—' on a miss, which is information lost.
    renderEnvironmentList('/environments');
    await waitFor(() => {
      const columns = (capturedGridProps.current?.columns ?? []) as GridColDef[];
      expect(columns.some((c) => c.field === 'operations_group_name')).toBe(true);
    });
    const byField = Object.fromEntries(
      (capturedGridProps.current?.columns as GridColDef[]).map((c) => [c.field, c])
    );
    // Not in the backend whitelist — it is a joined column, not an
    // Environment column, so a sortable header would 422 on click.
    expect(byField.operations_group_name.sortable).toBe(false);
  });
```

You will need the list fixture in that file to include `operations_group_id` and `operations_group_name` on at least one row. Read the existing mock at the top of the file and add both fields to every environment fixture object — a missing field would make the column render blank and the test's intent unclear.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/environments/__tests__/environmentListServerGrid.test.tsx`
Expected: FAIL — no column with field `operations_group_name`

- [ ] **Step 3: Add the column and filter to the list page**

In `frontend/src/pages/environments/EnvironmentList.tsx`:

- Add an `operations_group_name` column to `environmentColumns` with `sortable: false` and `headerName: 'Operations Group'`, rendering `—` when null. Update the comment above `environmentColumns` that lists the whitelist-backed fields.
- **Check the static column list assertion.** `environmentListServerGrid.test.tsx` asserts the exact set of static fields (`new Set(['name', 'tier', 'owner', ...])`). Add `operations_group_name` to that expected set, or the existing test fails.
- Fetch the groups for the picker and the filter with `dispatch(fetchUserGroups({}))`, reading `state.userGroup.groups`. Do **not** read a paged environment slice for this.
- Add an Operations Group `Select` to the create dialog, and an `operations_group_id` entry to `useServerGrid`'s `filterKeys` so the filter round-trips through the URL like the existing owner filter.
- **Relabel the governance-gap filter chip.** It currently reads `label="Missing owner"` (around line 581) with a comment stating "`governance_gap` is a missing OWNER only". Task 4 extended that filter to mean *missing owner **or** missing operations group*, so both the label and the comment are now wrong. Change the label to `Governance gap` and rewrite the comment to state the current rule. This was found by Task 4's review, which noted no task in the plan covered it — without this the feature ships with a chip that lies about what it filters.
- In the create dialog's Select, keep a soft-deleted group selectable when it is the current value, following the pattern already in the file for a retired tier and a deactivated owner. Read that block (search for `(inactive)`) and mirror it with `(deleted)`.

- [ ] **Step 4: Add the control to the detail page**

In `frontend/src/pages/environments/EnvironmentDetail.tsx`, add an Operations Group `Select` to the governance form beside Tier and Owner, following the same pattern including the keep-the-current-value-selectable branch.

The update payload must send `operations_group_id` explicitly, including `null` when cleared — an omitted key means "leave alone" to the backend. Find how the form sends `expires_at: null` and match it exactly.

- [ ] **Step 5: Run the environment tests**

Run: `cd frontend && npx vitest run src/pages/environments`
Expected: PASS — including the pre-existing static-column-set assertion you updated in Step 3

- [ ] **Step 6: Run the whole frontend suite, typecheck and lint**

Run: `cd frontend && npx vitest run`
Expected: PASS, no failures

Run: `cd frontend && npx tsc --noEmit`
Expected: no output (exit 0)

Run: `cd frontend && npm run lint`
Expected: no output beyond the npm banner

- [ ] **Step 7: Open the pages**

Six defects in the pagination programme were found only by opening the page, every one with a fully green suite. Do this before claiming the task done.

Start the app if it is not running (`docker-compose up -d`, then `uvicorn app.main:app --reload` in `backend/` and `npm run dev` in `frontend/`), log in as `admin` / `admin123` on tenant `demo`, and check:

1. `/tenant/groups` — create a group, edit it, see it in the list with a member count of 0.
2. `/tenant/groups/<id>` — add a member, see the username render, remove them.
3. `/environments` — the Operations Group column shows, the filter narrows the list, and the URL carries the filter across a reload.
4. Assign a group to an environment, then try to delete that group on `/tenant/groups` — the error must name the environment, not say "Request failed with status code 409".

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentList.tsx \
        frontend/src/pages/environments/EnvironmentDetail.tsx \
        frontend/src/pages/environments/__tests__/environmentListServerGrid.test.tsx
git commit -m "feat(environments): operations group column, filter and form control"
```

---

## Final verification

- [ ] **Backend, both engines**

Run: `cd backend && uv run pytest -q -p no:logging`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q -p no:logging`
Expected: PASS

- [ ] **Frontend**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all PASS

- [ ] **Update the phase doc**

In `docs/phases/phase-7.md`, replace the B3 line with:

```markdown
- [ ] **B3** Environment Request Form + auto-generated Welcome Pack
      - [x] **B3a** `UserGroup` + membership + `environment.operations_group_id`.
            [Spec](../superpowers/specs/2026-08-04-user-groups-design.md)
      - [ ] **B3b** The request form, routing to the operating team, approval, Welcome Pack
```

- [ ] **Open a PR**

```bash
git push -u github feature/user-groups
gh pr create --repo pjgross/envmgr --base main --title "Phase 7 B3a: user groups + environment operations group"
```

The PR body should state plainly that this ships no user-visible workflow — it is admin screens and a field, and the value arrives with B3b.
