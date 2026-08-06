# Project Entity, Members and Usage Agreements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `Project` entity whose team is an existing `UserGroup`, link bookings, releases and environments to it, and record usage agreements — so that A3 can enforce them and A4 can order contention by project.

**Architecture:** `Project` follows `user_group` and `environment_tier` — a tenant-scoped vocabulary with soft delete and service-enforced name uniqueness. Its team is `team_group_id → user_group.id`, the same shape as `environment.operations_group_id`, so this codebase gains no second membership model. `usage_agreement` is a project↔environment junction carrying a window; **A1 records it and nothing reads it.**

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 (backend); React 18, TypeScript, MUI DataGrid, Redux Toolkit (frontend). Tests: pytest (SQLite + PostgreSQL), vitest.

**Spec:** [docs/superpowers/specs/2026-08-06-project-entity-design.md](../specs/2026-08-06-project-entity-design.md)

## Global Constraints

- Every query on a tenant-scoped table filters by `current_user.active_tenant_id` — **never** `.tenant_id`, which is wrong under master-admin impersonation.
- **Cross-tenant ids return 404, never 403.** Applies to every client-supplied FK, on **create and on update**. Across the last two sub-projects the same missing `tenant_id` filter appeared four times and was never caught by an existing test.
- List endpoints take `page: Page = Depends(pagination())`, order by a **unique** key (append the primary key), and emit `X-Total-Count` via `set_total_count`.
- **Every filter runs in SQL.** A Python-side filter on a bounded endpoint windows the page before filtering.
- Migrations are hand-written — never `--autogenerate`. **`tests/test_migration_schema_drift.py` compares only column NAME SETS**, so a passing run is not evidence the migration matches its models. Check types, timezone-awareness, server defaults and index names by hand.
- Entities soft-delete (`deleted_at`); junction rows hard-delete.
- Services never call `db.commit()`. Use `db.flush()` for an assigned id.
- **A1 adds no enforcement.** `BookingService` is untouched.
- Frontend thunks `rejectWithValue(formatApiError(err, ...))`; components read `result.payload`. Test fixtures reject with an **AxiosError shape**.
- Backend from `backend/` via `uv run`; frontend from `frontend/`.
- **Do not run the full test suite in a task** — run the focused tests named. The controller runs full suites.
- PostgreSQL leg: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q -p no:logging`

## File Structure

**Backend — create**
- `app/db/models/project.py` — `Project` and `UsageAgreement`
- `app/db/migrations/versions/20260807_1000_projects_add_projects.py`
- `app/api/v1/schemas/project.py`
- `app/services/project_service.py` — CRUD + agreements
- `app/api/v1/projects.py`
- `tests/test_project_model.py`, `tests/integration/test_projects_api.py`,
  `tests/integration/test_usage_agreements_api.py`, `tests/integration/test_project_links.py`

**Backend — modify**
- `app/db/models/booking_request.py`, `app/db/models/release.py` — the two FKs
- `app/api/v1/schemas/booking_request.py`, `app/api/v1/schemas/release.py`
- `app/services/booking_request_service.py`, `app/services/release_service.py`
- `app/api/v1/bookings.py` (or wherever the booking-request list lives), `app/api/v1/releases.py`
- `app/api/v1/environments.py` — the environment-direction agreements route
- `app/main.py`, `tests/factories.py`, `tests/test_pagination.py`

**Frontend — create**
- `src/types/project.ts`, `src/services/projectService.ts`, `src/store/projectSlice.ts`
- `src/pages/admin/Projects.tsx`, `src/pages/admin/ProjectDetail.tsx`
- `src/components/environments/EnvironmentProjectsPanel.tsx`
- matching `__tests__/` files

**Frontend — modify**
- `src/App.tsx`, `src/pages/admin/AdminLayout.tsx`, `src/store/index.ts`
- `src/pages/bookings/BookingForm.tsx`, `BookingList.tsx` — picker, filter, relabel
- `src/components/releases/ReleaseBookingsTable.tsx` — relabel only
- `src/pages/releases/ReleaseForm.tsx`, `ReleaseList.tsx` — picker, filter
- `src/pages/environments/EnvironmentDetail.tsx` — mount the panel
- `src/types/booking.ts`, `src/types/release.ts`, `src/types/environment.ts`

---

### Task 1: Models, migration, factories

**Files:**
- Create: `backend/app/db/models/project.py`, `backend/app/db/migrations/versions/20260807_1000_projects_add_projects.py`
- Modify: `backend/app/db/models/booking_request.py`, `backend/app/db/models/release.py`, `backend/app/db/models/__init__.py`, `backend/tests/factories.py`
- Test: `backend/tests/test_project_model.py`

**Interfaces:**
- Consumes: `UserGroup` (B3a), `Environment`, `BookingRequest`, `Release`.
- Produces: `Project(tenant_id, name, code, description, team_group_id, is_active, deleted_at)`; `UsageAgreement(tenant_id, project_id, environment_id, starts_at, ends_at, notes, deleted_at)`; `BookingRequest.project_id`; `Release.owning_project_id`; `ensure_project(db, tenant_id, name="fk-parent-project") -> Project`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_project_model.py`:

```python
"""The project entity, its agreement table, and the two links A1 adds."""
import pytest
from sqlalchemy import select

from app.db.models.project import Project, UsageAgreement
from tests.factories import (
    ensure_environment, ensure_project, ensure_user_group,
)


@pytest.mark.asyncio
async def test_project_persists_with_its_tenant(db_session, test_tenant):
    project = Project(tenant_id=test_tenant.id, name="Mortgage Replatform")
    db_session.add(project)
    await db_session.flush()

    assert project.id is not None
    assert project.is_active is True
    assert project.deleted_at is None
    assert project.code is None
    # A project need not have a team — one can be assigned later.
    assert project.team_group_id is None


@pytest.mark.asyncio
async def test_a_projects_team_is_a_user_group(db_session, test_tenant):
    """No project_member table: B3a's UserGroup is deliberately generic so a
    person's group memberships answer both 'which environments do you operate'
    and 'which projects are you on'."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Mortgage Team")
    project = await ensure_project(db_session, test_tenant.id)
    project.team_group_id = group.id
    await db_session.flush()

    stored = (await db_session.execute(
        select(Project.team_group_id).where(Project.id == project.id)
    )).scalar_one()
    assert stored == group.id


@pytest.mark.asyncio
async def test_usage_agreement_links_a_project_to_an_environment(
    db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)

    agreement = UsageAgreement(
        tenant_id=test_tenant.id, project_id=project.id, environment_id=env.id
    )
    db_session.add(agreement)
    await db_session.flush()

    assert agreement.id is not None
    # The window is optional: "this project uses this environment" is a
    # legitimate statement without dates.
    assert agreement.starts_at is None
    assert agreement.ends_at is None


@pytest.mark.asyncio
async def test_one_environment_can_serve_several_projects(db_session, test_tenant):
    """Shared estates are the normal case — this is why the link is a junction
    and not an owning FK on environment."""
    env = await ensure_environment(db_session, test_tenant.id)
    a = await ensure_project(db_session, test_tenant.id, name="Project A")
    b = await ensure_project(db_session, test_tenant.id, name="Project B")

    for project in (a, b):
        db_session.add(UsageAgreement(
            tenant_id=test_tenant.id, project_id=project.id, environment_id=env.id
        ))
    await db_session.flush()

    rows = (await db_session.execute(
        select(UsageAgreement.project_id).where(
            UsageAgreement.environment_id == env.id
        )
    )).scalars().all()
    assert sorted(rows) == sorted([a.id, b.id])


@pytest.mark.asyncio
async def test_booking_request_keeps_its_free_text_alongside_the_link(
    db_session, test_tenant, test_booking_type, test_user
):
    """project_name is NOT migrated or removed. In real data it holds a booking
    label — 'Health Demo Booking', 'Reserved check' — so promoting it would
    manufacture junk projects. project_id arrives beside it, nullable."""
    from datetime import datetime, timedelta, timezone
    from app.db.models.booking_request import BookingRequest

    project = await ensure_project(db_session, test_tenant.id)
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="Health Demo Booking",   # still free text, still required
        project_id=project.id,                 # the new link
        booking_type_id=test_booking_type.id,
        start_date=now,
        end_date=now + timedelta(days=1),
        booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    assert req.project_name == "Health Demo Booking"
    assert req.project_id == project.id


@pytest.mark.asyncio
async def test_release_link_is_named_to_avoid_the_release_kind_collision(
    db_session, tenant, user, release_lifecycle_template
):
    """`release_kind='project'` already lives in this table meaning 'not an
    enterprise release'. Two things called project on one row is how a future
    reader gets it wrong, so the FK is owning_project_id."""
    from app.db.models.release import Release

    project = await ensure_project(db_session, tenant.id)
    release = Release(
        tenant_id=tenant.id, name="R1", release_type="Major",
        release_kind="project", lifecycle_template_id=release_lifecycle_template.id,
        status="draft", raised_by=user.id, owning_project_id=project.id,
    )
    db_session.add(release)
    await db_session.flush()

    assert release.owning_project_id == project.id
    assert release.release_kind == "project"  # unrelated, and untouched
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_project_model.py -q -p no:logging`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.project'`

The last test uses the `tenant`, `user` and `release_lifecycle_template` fixtures rather than `test_tenant`/`test_user` — check `tests/conftest.py` and use whichever fixtures actually exist for building a `Release`; `tests/test_pagination_b.py` builds one and is a working reference.

- [ ] **Step 3: Write the models**

Create `backend/app/db/models/project.py`:

```python
"""Projects, their teams, and which environments they have agreed to use.

A project's members are NOT a table here. `team_group_id` points at B3a's
`UserGroup`, which was deliberately generic — not called `OperationsTeam` —
precisely so this sub-project could reuse it. One membership model, one admin
screen, and a person's group memberships answer both "which environments do you
operate" and "which projects are you on".

`UsageAgreement` records that a project may use an environment, optionally
within a window. **A1 records it and nothing reads it**: no booking is
rejected, nothing warns. Enforcement is A3, with its own rules — keeping a
behaviour change out of the sub-project that introduces the schema is the same
call B3a made with group membership.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Project(Base):
    """A tenant-scoped project.

    Shaped like `UserGroup` and `EnvironmentTier`, the two vocabularies this
    codebase already configures per tenant: soft-deleted, with name uniqueness
    enforced in the service rather than by a partial unique index — such an
    index is inert on SQLite and would guard only the PostgreSQL leg.
    """

    __tablename__ = "project"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True
    )
    # Archived projects stay referenceable but stop being offered in pickers.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class UsageAgreement(Base):
    """"Project P may use environment E, optionally between two dates."

    A junction rather than an owning FK on `environment`: shared estates are the
    normal case, and requirements.md §2.12 frames these as how projects
    "cooperate in a shared environment".

    Soft-deleted rather than hard-deleted despite being a junction: an agreement
    is a statement of intent with a history worth keeping, and A3 will want to
    know an agreement was withdrawn rather than find it silently absent.
    """

    __tablename__ = "usage_agreement"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    starts_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<UsageAgreement(project_id={self.project_id}, "
            f"environment_id={self.environment_id})>"
        )
```

- [ ] **Step 4: Add the two links**

In `backend/app/db/models/booking_request.py`, after `project_name`:

```python
    # The project this booking belongs to. Nullable, and deliberately BESIDE
    # project_name rather than replacing it: in real data that field holds a
    # booking label ("Health Demo Booking", "Reserved check"), so promoting it
    # would manufacture projects nobody wants. The UI relabels it "Purpose".
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("project.id"), nullable=True, index=True
    )
```

In `backend/app/db/models/release.py`, after `release_kind`:

```python
    # `owning_project_id`, not `project_id`: `release_kind='project'` above
    # already means "not an enterprise release", and two things called project
    # on one row is how a future reader gets it wrong.
    owning_project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("project.id"), nullable=True, index=True
    )
```

- [ ] **Step 5: Register the models for `create_all`**

Run: `cd backend && grep -n "user_group" app/db/models/__init__.py`

Add `Project` and `UsageAgreement` in the same style. If a model is not imported before `Base.metadata.create_all`, its table silently will not exist in tests.

- [ ] **Step 6: Add the factory**

In `backend/tests/factories.py`, add `from app.db.models.project import Project` beside the other model imports, then:

```python
async def ensure_project(
    db: AsyncSession, tenant_id: int, name: str = "fk-parent-project"
) -> Project:
    """A project for `tenant_id`. Idempotent per (tenant, name).

    `booking_request.project_id`, `release.owning_project_id` and
    `usage_agreement.project_id` are all real FKs, so tests must never pass a
    bare `1`.
    """
    existing = (
        await db.execute(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.name == name,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    project = Project(tenant_id=tenant_id, name=name)
    db.add(project)
    await db.flush()
    return project
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && uv run pytest tests/test_project_model.py -q -p no:logging`
Expected: PASS, 6 passed

- [ ] **Step 8: Write the migration**

Confirm the head first: `cd backend && uv run alembic current` must print `envrequests`.

Create `backend/app/db/migrations/versions/20260807_1000_projects_add_projects.py`:

```python
"""projects, usage agreements, and the booking/release links

Revision ID: projects
Revises: envrequests
Create Date: 2026-08-07 10:00:00.000000

Purely additive: two new tables and two nullable columns. No backfill —
booking_request.project_name is deliberately kept, so there is nothing to
migrate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'projects'
down_revision: Union[str, None] = 'envrequests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("team_group_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["team_group_id"], ["user_group.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id. The
    # usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_project_id", "project", ["id"])
    op.create_index("ix_project_tenant_id", "project", ["tenant_id"])
    op.create_index("ix_project_team_group_id", "project", ["team_group_id"])

    op.create_table(
        "usage_agreement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_agreement_id", "usage_agreement", ["id"])
    op.create_index("ix_usage_agreement_tenant_id", "usage_agreement", ["tenant_id"])
    op.create_index("ix_usage_agreement_project_id", "usage_agreement", ["project_id"])
    op.create_index(
        "ix_usage_agreement_environment_id", "usage_agreement", ["environment_id"]
    )

    op.add_column("booking_request", sa.Column("project_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_booking_request_project", "booking_request", "project", ["project_id"], ["id"]
    )
    op.create_index("ix_booking_request_project_id", "booking_request", ["project_id"])

    op.add_column("release", sa.Column("owning_project_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_release_owning_project", "release", "project", ["owning_project_id"], ["id"]
    )
    op.create_index("ix_release_owning_project_id", "release", ["owning_project_id"])


def downgrade() -> None:
    op.drop_index("ix_release_owning_project_id", table_name="release")
    op.drop_constraint("fk_release_owning_project", "release", type_="foreignkey")
    op.drop_column("release", "owning_project_id")

    op.drop_index("ix_booking_request_project_id", table_name="booking_request")
    op.drop_constraint("fk_booking_request_project", "booking_request", type_="foreignkey")
    op.drop_column("booking_request", "project_id")

    for index in (
        "ix_usage_agreement_environment_id",
        "ix_usage_agreement_project_id",
        "ix_usage_agreement_tenant_id",
        "ix_usage_agreement_id",
    ):
        op.drop_index(index, table_name="usage_agreement")
    op.drop_table("usage_agreement")

    for index in ("ix_project_team_group_id", "ix_project_tenant_id", "ix_project_id"):
        op.drop_index(index, table_name="project")
    op.drop_table("project")
```

Note the drop order: the two referencing columns go before `project`, or the FK blocks the table drop.

- [ ] **Step 9: Verify the migration against the models BY HAND**

`tests/test_migration_schema_drift.py` compares only column **name sets**. Four real drifts passed it during B3a — including `created_at`/`updated_at` declared naive where `Base` declares `DateTime(timezone=True)` with `server_default=func.now()`, which would have given production naive timestamps.

Build a scratch database from the migrations and one from `create_all`, then compare **types, timezone-awareness, server defaults and index names** for `project`, `usage_agreement`, `booking_request` and `release`. Report the observed values, not a claim that they match.

Then run: `cd backend && uv run pytest tests/test_migration_schema_drift.py tests/test_project_model.py -q -p no:logging`

- [ ] **Step 10: Apply to the dev database**

Confirm `uv run alembic current` prints `envrequests`, then `uv run alembic upgrade head`.

**Do not run `alembic downgrade -1` against the dev database** — it steps back from the current head, not your revision, and doing this previously dropped a table and destroyed a stored credential. Step 9's scratch database covers both directions.

Also note: if a dev server is running with `--reload`, `app/main.py`'s lifespan calls `init_db()` → `create_all` on every start, so writing the models before the migration can create the tables behind your back with `alembic_version` unchanged. If you find that, say so plainly.

- [ ] **Step 11: Run both engines, then commit**

```bash
git add backend/app/db/models/project.py backend/app/db/models/booking_request.py \
        backend/app/db/models/release.py backend/app/db/models/__init__.py \
        backend/app/db/migrations/versions/20260807_1000_projects_add_projects.py \
        backend/tests/factories.py backend/tests/test_project_model.py
git commit -m "feat(projects): add project, usage_agreement and the booking/release links"
```

---

### Task 2: Project CRUD service and API

**Files:**
- Create: `backend/app/api/v1/schemas/project.py`, `backend/app/services/project_service.py`, `backend/app/api/v1/projects.py`, `backend/tests/integration/test_projects_api.py`
- Modify: `backend/app/main.py`, `backend/tests/test_pagination.py`

**Interfaces:**
- Consumes: `Project` (Task 1).
- Produces: `PROJECT_SORTS`; `list_projects(db, tenant_id, *, page=None, sort=None, search=None, is_active=None) -> tuple[list[ProjectView], int]`; `get_project_view(db, project_id, tenant_id) -> ProjectView`; `get_project(db, project_id, tenant_id) -> Project`; `create_project`, `update_project`, `delete_project`. `ProjectView` is a dataclass with `project`, `team_group_name`, `environment_count`. Endpoints mount at `/api/v1/projects`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_projects_api.py`:

```python
"""Project CRUD. Usage agreements and the entity links have their own files."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_project, ensure_user_group


@pytest.mark.asyncio
async def test_create_and_list_a_project(client, auth_headers):
    created = await client.post(
        "/api/v1/projects",
        json={"name": "Mortgage Replatform", "code": "MTG", "description": "2026 programme"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Mortgage Replatform"
    assert created.json()["is_active"] is True

    listed = await client.get("/api/v1/projects", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [p["name"] for p in listed.json()] == ["Mortgage Replatform"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_duplicate_name_is_a_409_naming_the_conflict(client, auth_headers):
    await client.post("/api/v1/projects", json={"name": "Mortgage"}, headers=auth_headers)
    again = await client.post(
        "/api/v1/projects", json={"name": "mortgage"}, headers=auth_headers
    )
    assert again.status_code == 409, again.text
    assert "already exists" in again.json()["detail"].lower()


@pytest.mark.asyncio
async def test_the_team_name_travels_with_the_row(
    client, auth_headers, db_session, test_tenant
):
    """Resolving it in the browser against a capped groups collection is the
    `.find()` failure docs/pagination.md documents — a miss renders '—'."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Mortgage Team")
    await db_session.commit()

    created = await client.post(
        "/api/v1/projects",
        json={"name": "Mortgage", "team_group_id": group.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["team_group_name"] == "Mortgage Team"


@pytest.mark.asyncio
async def test_cannot_point_at_another_tenants_group(
    client, auth_headers, db_session, second_tenant_factory
):
    """404, never 403 — a 403 confirms the group exists."""
    # The fixture yields a FACTORY, and the factory returns (Tenant, User).
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    refused = await client.post(
        "/api/v1/projects",
        json={"name": "Leaky", "team_group_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_the_update_path_guards_the_team_too(
    client, auth_headers, db_session, second_tenant_factory
):
    """The create path is the obvious one; the UPDATE path is where this gap
    has hidden before — a prior sub-project's review found exactly that."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()
    pid = (await client.post(
        "/api/v1/projects", json={"name": "Mine"}, headers=auth_headers
    )).json()["id"]

    refused = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"team_group_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_delete_is_a_soft_delete_and_is_never_refused(
    client, auth_headers, db_session, test_tenant
):
    """Deliberately unlike delete_group, which 409s while anything references
    it. A project accumulates every booking it ever had, so a reference check
    would make every project permanently undeletable."""
    from sqlalchemy import select
    from app.db.models.project import Project

    project = await ensure_project(db_session, test_tenant.id, name="Old")
    await db_session.commit()

    gone = await client.delete(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert gone.status_code == 204, gone.text

    row = (await db_session.execute(
        select(Project).where(Project.id == project.id)
    )).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is not None, "must be soft, not hard"

    listed = (await client.get("/api/v1/projects", headers=auth_headers)).json()
    assert "Old" not in [p["name"] for p in listed]


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get("/api/v1/projects?sort_by=nonsense", headers=auth_headers)
    assert bad.status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_projects_api.py -q -p no:logging`
Expected: FAIL — every test 404s; the router does not exist.

- [ ] **Step 3: Write the schemas**

Create `backend/app/api/v1/schemas/project.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    is_active: bool = True


class ProjectUpdate(BaseModel):
    """Every field optional. `team_group_id` is `int | None`: the service keys
    on model_fields_set, so an omitted key means "leave alone" and only an
    explicit null clears the team — the same contract B1 gave expires_at.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    """`team_group_name` and `environment_count` travel with the row.

    Resolving them in the browser against separately-fetched collections is the
    failure docs/pagination.md documents: those collections are capped, so a
    `.find()` miss renders the entity as '—' and loses information no
    truncation banner can recover.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    team_group_id: Optional[int] = None
    team_group_name: Optional[str] = None
    environment_count: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "ProjectResponse":
        p = view.project
        return cls(
            id=p.id, tenant_id=p.tenant_id, name=p.name, code=p.code,
            description=p.description, team_group_id=p.team_group_id,
            team_group_name=view.team_group_name,
            environment_count=view.environment_count,
            is_active=p.is_active,
            created_at=p.created_at, updated_at=p.updated_at,
        )
```

- [ ] **Step 4: Write the service**

Create `backend/app/services/project_service.py`:

```python
"""Projects — CRUD plus the counts the UI needs.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
Same reasoning as environment_tier_service and user_group_service.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.project import ProjectCreate, ProjectUpdate
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.project import Project, UsageAgreement
from app.db.models.user_group import UserGroup


@dataclass
class ProjectView:
    """A project plus the labels a UI needs without extra round-trips,
    following environment_service.EnvironmentView."""

    project: Project
    team_group_name: Optional[str]
    environment_count: int


def _environment_count_clause(tenant_id: int):
    return (
        select(func.count(UsageAgreement.id))
        .where(
            UsageAgreement.project_id == Project.id,
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.deleted_at.is_(None),
        )
        .correlate(Project)
        .scalar_subquery()
    )


def _view_query(tenant_id: int):
    """The one select carrying a project's display labels.

    The join is tenant-qualified — defence in depth matching
    environment_service._view_query: a malformed row must not surface another
    tenant's name. It does NOT filter the group's deleted_at, so an archived
    team still renders its name rather than blanking.
    """
    return (
        select(Project, UserGroup.name, _environment_count_clause(tenant_id))
        .outerjoin(
            UserGroup,
            and_(
                UserGroup.id == Project.team_group_id,
                UserGroup.tenant_id == tenant_id,
            ),
        )
        .where(Project.tenant_id == tenant_id, Project.deleted_at.is_(None))
    )


def _to_view(row) -> ProjectView:
    project, team_name, env_count = row
    return ProjectView(
        project=project, team_group_name=team_name, environment_count=env_count
    )


PROJECT_SORTS = {
    "name": Project.name,
    "code": Project.code,
    "created_at": Project.created_at,
}


async def list_projects(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> tuple[list[ProjectView], int]:
    """Projects for a tenant, plus the unwindowed total.

    Every filter is applied in SQL. A filter applied in Python after the query
    would window the page before the filter — see docs/pagination.md.
    """
    query = _view_query(tenant_id)
    if search:
        query = query.where(Project.name.ilike(f"%{search}%"))
    if is_active is not None:
        query = query.where(Project.is_active.is_(is_active))
    # Names are unique per tenant, but apply_sort folds case, so two names
    # differing only in case stop being distinct keys — the id tiebreaker is
    # what makes the order total, which LIMIT/OFFSET requires.
    query = apply_sort(query, sort).order_by(func.lower(Project.name), Project.id)
    rows, total = await fetch_page_rows(db, query, page)
    return [_to_view(r) for r in rows], total


async def get_project_view(
    db: AsyncSession, project_id: int, tenant_id: int
) -> ProjectView:
    row = (
        await db.execute(_view_query(tenant_id).where(Project.id == project_id))
    ).first()
    if row is None:
        # 404 rather than 403: a 403 confirms the row exists in another tenant.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return _to_view(row)


async def get_project(db: AsyncSession, project_id: int, tenant_id: int) -> Project:
    """The bare entity, for callers that do not need the labels."""
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


async def _assert_team_is_ours(
    db: AsyncSession, tenant_id: int, team_group_id: Optional[int]
) -> None:
    """Validated against the ACTIVE tenant on create AND update.

    Under master-admin impersonation current_user.id and active_tenant_id
    belong to different tenants. This is also the IDOR class a 2026-07-16 audit
    found four instances of, and which the last two sub-projects' reviews found
    four more of — every time on a path nothing tested.
    """
    if team_group_id is None:
        return
    found = (
        await db.execute(
            select(UserGroup.id).where(
                UserGroup.id == team_group_id,
                UserGroup.tenant_id == tenant_id,
                UserGroup.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User group not found")


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(Project.id).where(
        Project.tenant_id == tenant_id,
        Project.deleted_at.is_(None),
        func.lower(Project.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(Project.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A project named '{name.strip()}' already exists in this tenant",
        )


async def create_project(
    db: AsyncSession, data: ProjectCreate, tenant_id: int
) -> ProjectView:
    await _assert_name_free(db, tenant_id, data.name)
    await _assert_team_is_ours(db, tenant_id, data.team_group_id)
    project = Project(
        tenant_id=tenant_id,
        name=data.name.strip(),
        code=data.code,
        description=data.description,
        team_group_id=data.team_group_id,
        is_active=data.is_active,
    )
    db.add(project)
    await db.flush()
    return await get_project_view(db, project.id, tenant_id)


async def update_project(
    db: AsyncSession, project_id: int, data: ProjectUpdate, tenant_id: int
) -> ProjectView:
    project = await get_project(db, project_id, tenant_id)
    fields = data.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"].strip().lower() != project.name.lower():
        await _assert_name_free(db, tenant_id, fields["name"], exclude_id=project_id)
    if "team_group_id" in fields:
        await _assert_team_is_ours(db, tenant_id, fields["team_group_id"])

    for key, value in fields.items():
        setattr(project, key, value.strip() if key == "name" else value)
    await db.flush()
    return await get_project_view(db, project_id, tenant_id)


async def delete_project(db: AsyncSession, project_id: int, tenant_id: int) -> None:
    """Soft delete, never refused.

    Deliberately unlike user_group_service.delete_group, which 409s while any
    environment references it. A group operates a handful of environments; a
    project accumulates every booking and release it ever had, so a reference
    check would make every project permanently undeletable the moment someone
    booked against it. Existing references keep rendering the name; `is_active`
    is what removes it from pickers going forward.
    """
    project = await get_project(db, project_id, tenant_id)
    project.deleted_at = datetime.now(timezone.utc)
    await db.flush()
```

- [ ] **Step 5: Write the endpoints**

Create `backend/app/api/v1/projects.py`:

```python
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.services import project_service

router = APIRouter()


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    response: Response,
    search: Optional[str] = Query(None, description="Case-insensitive name match."),
    is_active: Optional[bool] = Query(None),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(project_service.PROJECT_SORTS, default="name")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readable by any tenant member — every booking form needs the picker, and
    everyone needs to see which project a booking belongs to."""
    views, total = await project_service.list_projects(
        db, current_user.active_tenant_id,
        page=page, sort=sort, search=search, is_active=is_active,
    )
    set_total_count(response, total)
    return [ProjectResponse.from_view(v) for v in views]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await project_service.create_project(db, data, current_user.active_tenant_id)
    return ProjectResponse.from_view(view)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await project_service.get_project_view(
        db, project_id, current_user.active_tenant_id
    )
    return ProjectResponse.from_view(view)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await project_service.update_project(
        db, project_id, data, current_user.active_tenant_id
    )
    return ProjectResponse.from_view(view)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await project_service.delete_project(db, project_id, current_user.active_tenant_id)
```

Declare `GET ""` **before** `GET "/{project_id}"` or the literal path is shadowed.

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, beside the other v1 routers:

```python
from app.api.v1 import projects as projects_router
...
app.include_router(projects_router.router, prefix="/api/v1/projects", tags=["Projects"])
```

- [ ] **Step 7: Add the pagination conformance row**

In `backend/tests/test_pagination.py`, add to `BOUNDED_ENDPOINTS`:

```python
    ("projects", "/api/v1/projects", MAX_LIMIT, "auth_headers"),
```

- [ ] **Step 8: Run the tests, both engines, then commit**

Run: `cd backend && uv run pytest tests/integration/test_projects_api.py tests/test_pagination.py -q -p no:logging`
Expected: PASS, 7 project tests

```bash
git add backend/app/api/v1/schemas/project.py backend/app/services/project_service.py \
        backend/app/api/v1/projects.py backend/app/main.py \
        backend/tests/integration/test_projects_api.py backend/tests/test_pagination.py
git commit -m "feat(projects): tenant-scoped project CRUD API"
```

---

### Task 3: Usage agreements

**Files:**
- Modify: `backend/app/services/project_service.py`, `backend/app/api/v1/projects.py`, `backend/app/api/v1/schemas/project.py`, `backend/app/api/v1/environments.py`
- Create: `backend/tests/integration/test_usage_agreements_api.py`

**Interfaces:**
- Consumes: `UsageAgreement` (Task 1), `get_project` (Task 2).
- Produces: `UsageAgreementCreate`/`UsageAgreementResponse`; `list_agreements_for_project(db, project_id, tenant_id, *, page=None) -> tuple[list[tuple[UsageAgreement, str, str]], int]` returning `(agreement, project_name, environment_name)`; `list_agreements_for_environment(db, environment_id, tenant_id, *, page=None)` with the same row shape; `create_agreement(db, project_id, data, tenant_id) -> tuple[UsageAgreement, str, str]`; `delete_agreement(db, project_id, agreement_id, tenant_id) -> None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_usage_agreements_api.py`:

```python
"""Usage agreements: recorded, and — in A1 — read by nothing."""
import pytest

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER
from tests.factories import ensure_environment, ensure_project


@pytest.mark.asyncio
async def test_record_an_agreement_and_read_it_from_both_directions(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id, "notes": "shared for UAT"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    # Both names travel with the row — never resolved against a capped list.
    assert created.json()["environment_name"] == env.name
    assert created.json()["project_name"] == "Mortgage"

    by_project = await client.get(
        f"/api/v1/projects/{project.id}/usage-agreements", headers=auth_headers
    )
    assert [a["environment_name"] for a in by_project.json()] == [env.name]
    assert int(by_project.headers[TOTAL_COUNT_HEADER]) == 1

    by_env = await client.get(
        f"/api/v1/environments/{env.id}/usage-agreements", headers=auth_headers
    )
    assert [a["project_name"] for a in by_env.json()] == ["Mortgage"]
    assert int(by_env.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_an_agreement_changes_no_booking_behaviour(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """A1 records; A3 enforces. Booking an environment the project has NO
    agreement for must still succeed.

    If this ever starts failing, someone has added enforcement without the
    rules — and A3 should be a deliberate change, not a surprise.
    """
    from datetime import datetime, timedelta, timezone

    project = await ensure_project(db_session, test_tenant.id, name="Unagreed")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    booked = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "no agreement anywhere",
            "project_id": project.id,
            "booking_type_id": test_booking_type.id,
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
            "environment_ids": [env.id],
        },
        headers=auth_headers,
    )
    assert booked.status_code in (200, 201), booked.text


@pytest.mark.asyncio
async def test_overlapping_windows_are_allowed_but_an_exact_duplicate_is_not(
    client, auth_headers, db_session, test_tenant
):
    """Deciding what an overlap MEANS is A3's job, once something reads them."""
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    url = f"/api/v1/projects/{project.id}/usage-agreements"

    first = await client.post(
        url,
        json={"environment_id": env.id,
              "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-06-30T00:00:00Z"},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text

    overlapping = await client.post(
        url,
        json={"environment_id": env.id,
              "starts_at": "2026-04-01T00:00:00Z", "ends_at": "2026-12-31T00:00:00Z"},
        headers=auth_headers,
    )
    assert overlapping.status_code == 201, overlapping.text

    exact = await client.post(
        url,
        json={"environment_id": env.id,
              "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-06-30T00:00:00Z"},
        headers=auth_headers,
    )
    assert exact.status_code == 409, exact.text


@pytest.mark.asyncio
async def test_ends_before_starts_is_422(client, auth_headers, db_session, test_tenant):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    bad = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id,
              "starts_at": "2026-06-30T00:00:00Z", "ends_at": "2026-01-01T00:00:00Z"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_cannot_agree_against_another_tenants_environment(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    project = await ensure_project(db_session, test_tenant.id)
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id)
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_both_list_endpoints_are_bounded(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    for url in (
        f"/api/v1/projects/{project.id}/usage-agreements",
        f"/api/v1/environments/{env.id}/usage-agreements",
    ):
        ok = await client.get(url, headers=auth_headers)
        assert ok.status_code == 200, ok.text
        assert TOTAL_COUNT_HEADER in ok.headers
        over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
        assert over.status_code == 422, over.text


@pytest.mark.asyncio
async def test_deleting_an_agreement_soft_deletes_it(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    aid = (await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id}, headers=auth_headers,
    )).json()["id"]

    gone = await client.delete(
        f"/api/v1/projects/{project.id}/usage-agreements/{aid}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text

    listed = (await client.get(
        f"/api/v1/projects/{project.id}/usage-agreements", headers=auth_headers
    )).json()
    assert listed == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_usage_agreements_api.py -q -p no:logging`
Expected: FAIL — 404 on the agreement routes.

The booking-request POST in the second test must match this repo's actual create shape — check `backend/app/api/v1/schemas/booking_request.py` and an existing test in `tests/integration/test_booking_requests_api.py`, and adjust the body. **Do not weaken that test**: the property it pins is that A1 changed no booking behaviour.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/api/v1/schemas/project.py`:

```python
class UsageAgreementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: int
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    notes: Optional[str] = None


class UsageAgreementResponse(BaseModel):
    """Both display names travel with the row: this list is read from the
    project side AND the environment side, and neither page should resolve the
    other end against a capped collection."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    project_name: str
    environment_id: int
    environment_name: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "UsageAgreementResponse":
        agreement, project_name, environment_name = row
        return cls(
            id=agreement.id, tenant_id=agreement.tenant_id,
            project_id=agreement.project_id, project_name=project_name,
            environment_id=agreement.environment_id,
            environment_name=environment_name,
            starts_at=agreement.starts_at, ends_at=agreement.ends_at,
            notes=agreement.notes, created_at=agreement.created_at,
        )
```

- [ ] **Step 4: Add the service functions**

Append to `backend/app/services/project_service.py`:

```python
from app.api.v1.schemas.project import UsageAgreementCreate
from app.db.models.environment import Environment


def _agreement_query(tenant_id: int):
    """One select carrying both ends' names, tenant-qualified on each join."""
    return (
        select(UsageAgreement, Project.name, Environment.name)
        .join(
            Project,
            and_(Project.id == UsageAgreement.project_id,
                 Project.tenant_id == tenant_id),
        )
        .join(
            Environment,
            and_(Environment.id == UsageAgreement.environment_id,
                 Environment.tenant_id == tenant_id),
        )
        .where(
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.deleted_at.is_(None),
        )
    )


async def list_agreements_for_project(
    db: AsyncSession, project_id: int, tenant_id: int, *, page: Optional[Page] = None
):
    await get_project(db, project_id, tenant_id)  # 404s for another tenant's project
    query = (
        _agreement_query(tenant_id)
        .where(UsageAgreement.project_id == project_id)
        .order_by(func.lower(Environment.name), UsageAgreement.id)
    )
    return await fetch_page_rows(db, query, page)


async def list_agreements_for_environment(
    db: AsyncSession, environment_id: int, tenant_id: int, *, page: Optional[Page] = None
):
    found = (
        await db.execute(
            select(Environment.id).where(
                Environment.id == environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    query = (
        _agreement_query(tenant_id)
        .where(UsageAgreement.environment_id == environment_id)
        .order_by(func.lower(Project.name), UsageAgreement.id)
    )
    return await fetch_page_rows(db, query, page)


async def create_agreement(
    db: AsyncSession, project_id: int, data: UsageAgreementCreate, tenant_id: int
):
    await get_project(db, project_id, tenant_id)

    if (
        data.starts_at is not None
        and data.ends_at is not None
        and data.ends_at < data.starts_at
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ends_at must not be earlier than starts_at",
        )

    env = (
        await db.execute(
            select(Environment.id).where(
                Environment.id == data.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    # Only an EXACT duplicate is refused. Overlapping windows are a statement
    # about intent, not a contradiction the system must resolve — deciding what
    # an overlap means is A3's job, once something reads them.
    duplicate = (
        await db.execute(
            select(UsageAgreement.id).where(
                UsageAgreement.tenant_id == tenant_id,
                UsageAgreement.project_id == project_id,
                UsageAgreement.environment_id == data.environment_id,
                UsageAgreement.starts_at.is_(data.starts_at)
                if data.starts_at is None
                else UsageAgreement.starts_at == data.starts_at,
                UsageAgreement.ends_at.is_(data.ends_at)
                if data.ends_at is None
                else UsageAgreement.ends_at == data.ends_at,
                UsageAgreement.deleted_at.is_(None),
            )
        )
    ).first()
    if duplicate is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This project already has an agreement for that environment over "
            "exactly that window",
        )

    agreement = UsageAgreement(
        tenant_id=tenant_id,
        project_id=project_id,
        environment_id=data.environment_id,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        notes=data.notes,
    )
    db.add(agreement)
    await db.flush()

    row = (
        await db.execute(
            _agreement_query(tenant_id).where(UsageAgreement.id == agreement.id)
        )
    ).first()
    return row


async def delete_agreement(
    db: AsyncSession, project_id: int, agreement_id: int, tenant_id: int
) -> None:
    await get_project(db, project_id, tenant_id)
    agreement = (
        await db.execute(
            select(UsageAgreement).where(
                UsageAgreement.id == agreement_id,
                UsageAgreement.project_id == project_id,
                UsageAgreement.tenant_id == tenant_id,
                UsageAgreement.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if agreement is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usage agreement not found")
    # Soft, not hard: an agreement is a statement of intent with a history, and
    # A3 will want to know one was withdrawn rather than find it absent.
    agreement.deleted_at = datetime.now(timezone.utc)
    await db.flush()
```

- [ ] **Step 5: Add the endpoints**

Append to `backend/app/api/v1/projects.py`:

```python
@router.get("/{project_id}/usage-agreements", response_model=list[UsageAgreementResponse])
async def list_project_usage_agreements(
    project_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await project_service.list_agreements_for_project(
        db, project_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [UsageAgreementResponse.from_row(r) for r in rows]


@router.post(
    "/{project_id}/usage-agreements",
    response_model=UsageAgreementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_usage_agreement(
    project_id: int,
    data: UsageAgreementCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    row = await project_service.create_agreement(
        db, project_id, data, current_user.active_tenant_id
    )
    return UsageAgreementResponse.from_row(row)


@router.delete(
    "/{project_id}/usage-agreements/{agreement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_usage_agreement(
    project_id: int,
    agreement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await project_service.delete_agreement(
        db, project_id, agreement_id, current_user.active_tenant_id
    )
```

Extend the schema import to include `UsageAgreementCreate` and `UsageAgreementResponse`.

In `backend/app/api/v1/environments.py`, add the environment-direction route:

```python
@router.get("/{env_id}/usage-agreements", response_model=list[UsageAgreementResponse])
async def list_environment_usage_agreements(
    env_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """"Which projects have agreed to use this environment." A1 records these;
    nothing checks them — that is A3."""
    rows, total = await project_service.list_agreements_for_environment(
        db, env_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [UsageAgreementResponse.from_row(r) for r in rows]
```

Add the necessary imports there (`Page`, `pagination`, `set_total_count`, `project_service`, and the schema).

- [ ] **Step 6: Run the tests, both engines, then commit**

Run: `cd backend && uv run pytest tests/integration/test_usage_agreements_api.py -q -p no:logging`
Expected: PASS, 7 passed

```bash
git add backend/app/services/project_service.py backend/app/api/v1/projects.py \
        backend/app/api/v1/schemas/project.py backend/app/api/v1/environments.py \
        backend/tests/integration/test_usage_agreements_api.py
git commit -m "feat(projects): usage agreements, readable from both directions"
```

---

### Task 4: Booking and release links

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_request.py`, `backend/app/api/v1/schemas/release.py`, `backend/app/services/booking_request_service.py`, `backend/app/services/release_service.py`, and the two list endpoints
- Create: `backend/tests/integration/test_project_links_bookings.py`, `backend/tests/integration/test_project_links_releases.py`

**Interfaces:**
- Consumes: `Project` (Task 1), `get_project` (Task 2).
- Produces: `project_id` on booking-request create/update/response plus `project_name_link` on the response; `owning_project_id` and `owning_project_name` on release create/update/response; `?project_id=` on both list endpoints.

**Two test files, not one**, because the two halves use different fixture families: booking-request tests use `client` + `auth_headers` + `test_tenant`, while every release test in this repo defines a local `authed_client` over the `tenant`/`user` fixtures. Mixing `tenant` and `test_tenant` in one file produces cross-tenant 404s that look like the bug under test.

- [ ] **Step 1a: Write the failing booking test**

Create `backend/tests/integration/test_project_links_bookings.py`:

```python
"""booking_request.project_id — the link, and the IDOR surface it adds.

Two new FK write paths arrive here (create and update). Across the two
preceding sub-projects the same missing tenant_id filter appeared four times
and was never once caught by a test that already existed, so each path gets one
written for it deliberately.
"""
from datetime import datetime, timedelta, timezone

import pytest

from tests.factories import ensure_environment, ensure_project


def _payload(booking_type_id: int, environment_id: int, **extra) -> dict:
    now = datetime.now(timezone.utc)
    body = {
        "project_name": "Regression sweep",   # free text — the UI calls it Purpose
        "booking_type_id": booking_type_id,
        "start_date": now.isoformat(),
        "end_date": (now + timedelta(days=1)).isoformat(),
        "environment_ids": [environment_id],
    }
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_the_project_name_travels_with_the_booking(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """`project_name_link`, NOT `project_name` — that key is already taken on
    this model by the free text, and shadowing it would silently change what
    every existing client reads."""
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body["project_id"] == project.id
    assert body["project_name_link"] == "Mortgage"
    # The two fields are different values and must stay distinguishable.
    assert body["project_name"] == "Regression sweep"


@pytest.mark.asyncio
async def test_a_booking_without_a_project_is_still_valid(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """The link is optional everywhere — A1 reports the gap, never blocks."""
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id),
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["project_id"] is None
    assert created.json()["project_name_link"] is None


@pytest.mark.asyncio
async def test_cannot_book_against_another_tenants_project_on_create(
    client, auth_headers, db_session, test_tenant, test_booking_type,
    second_tenant_factory,
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=theirs.id),
        headers=auth_headers,
    )
    # 404, never 403 — a 403 confirms the project exists in another tenant.
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_cannot_book_against_another_tenants_project_on_update(
    client, auth_headers, db_session, test_tenant, test_booking_type,
    second_tenant_factory,
):
    """The create path is the obvious one. The UPDATE path is where this class
    of gap has actually hidden in this codebase."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id),
        headers=auth_headers,
    )).json()["id"]

    refused = await client.patch(
        f"/api/v1/booking-requests/{rid}",
        json={"project_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_the_list_filters_by_project_in_sql(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    mortgage = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    savings = await ensure_project(db_session, test_tenant.id, name="Savings")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    for project in (mortgage, savings):
        made = await client.post(
            "/api/v1/booking-requests",
            json=_payload(test_booking_type.id, env.id, project_id=project.id),
            headers=auth_headers,
        )
        assert made.status_code in (200, 201), made.text

    filtered = await client.get(
        f"/api/v1/booking-requests?project_id={mortgage.id}", headers=auth_headers
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["project_name_link"] == "Mortgage"
    # A Python-side filter would window the page BEFORE filtering, so the total
    # must describe the filtered set, not the whole one.
    assert int(filtered.headers["X-Total-Count"]) == 1


@pytest.mark.asyncio
async def test_an_archived_projects_name_still_renders_on_its_bookings(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """Blanking the name would lose information the row still carries — the
    same call B3b made for a soft-deleted operating group."""
    project = await ensure_project(db_session, test_tenant.id, name="Wound Down")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )).json()["id"]

    gone = await client.delete(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert gone.status_code == 204, gone.text

    still = await client.get(f"/api/v1/booking-requests/{rid}", headers=auth_headers)
    assert still.status_code == 200, still.text
    assert still.json()["project_name_link"] == "Wound Down"
```

- [ ] **Step 1b: Write the failing release test**

Create `backend/tests/integration/test_project_links_releases.py`:

```python
"""release.owning_project_id — the link, and the IDOR surface it adds.

Named owning_project_id, not project_id: `release_kind='project'` already lives
on this table meaning "not an enterprise release", and two things called
project on one row is how a future reader gets it wrong.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.base import get_db
from app.main import app
from tests.factories import ensure_project


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Copied from tests/integration/test_release_systems_api.py — every
    release test in this repo builds its client this way, over the `tenant`
    and `user` fixtures rather than `test_tenant`/`test_user`."""
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username, "password": "password123",
            "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


def _payload(lifecycle_template_id: int, **extra) -> dict:
    body = {
        "name": "Rel",
        "release_type": "Test Major",
        "release_kind": "project",
        "lifecycle_template_id": lifecycle_template_id,
    }
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_the_owning_projects_name_travels_with_the_release(
    authed_client, db_session, tenant, release_lifecycle_template
):
    project = await ensure_project(db_session, tenant.id, name="Mortgage")
    await db_session.commit()

    created = await authed_client.post(
        "/api/v1/releases",
        json=_payload(release_lifecycle_template.id, owning_project_id=project.id),
    )
    assert created.status_code == 201, created.text
    assert created.json()["owning_project_id"] == project.id
    assert created.json()["owning_project_name"] == "Mortgage"
    # release_kind is a different concept and stays untouched.
    assert created.json()["release_kind"] == "project"


@pytest.mark.asyncio
async def test_a_release_without_an_owning_project_is_still_valid(
    authed_client, release_lifecycle_template
):
    created = await authed_client.post(
        "/api/v1/releases", json=_payload(release_lifecycle_template.id)
    )
    assert created.status_code == 201, created.text
    assert created.json()["owning_project_id"] is None
    assert created.json()["owning_project_name"] is None


@pytest.mark.asyncio
async def test_cannot_own_a_release_with_another_tenants_project_on_create(
    authed_client, db_session, release_lifecycle_template, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    refused = await authed_client.post(
        "/api/v1/releases",
        json=_payload(release_lifecycle_template.id, owning_project_id=theirs.id),
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_cannot_own_a_release_with_another_tenants_project_on_update(
    authed_client, db_session, release_lifecycle_template, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()
    rid = (await authed_client.post(
        "/api/v1/releases", json=_payload(release_lifecycle_template.id)
    )).json()["id"]

    refused = await authed_client.patch(
        f"/api/v1/releases/{rid}", json={"owning_project_id": theirs.id}
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_the_release_list_filters_by_project_in_sql(
    authed_client, db_session, tenant, release_lifecycle_template
):
    mortgage = await ensure_project(db_session, tenant.id, name="Mortgage")
    savings = await ensure_project(db_session, tenant.id, name="Savings")
    await db_session.commit()

    for index, project in enumerate((mortgage, savings)):
        made = await authed_client.post(
            "/api/v1/releases",
            json=_payload(
                release_lifecycle_template.id,
                name=f"Rel {index}",
                owning_project_id=project.id,
            ),
        )
        assert made.status_code == 201, made.text

    filtered = await authed_client.get(f"/api/v1/releases?project_id={mortgage.id}")
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["owning_project_name"] == "Mortgage"
    assert int(filtered.headers["X-Total-Count"]) == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_project_links_bookings.py tests/integration/test_project_links_releases.py -q -p no:logging`
Expected: FAIL — `project_id` and `owning_project_id` are not accepted by either schema.

Two things to check rather than assume. The booking-request PATCH route may not be `PATCH /api/v1/booking-requests/{id}` — confirm the verb and path in `app/api/v1/` and correct the test if it differs. And `GET /api/v1/booking-requests` may return a rollup shape rather than the create response — confirm `project_name_link` is on whatever model that list returns, and put it there if not. **Do not weaken either test to fit**: the properties they pin — an update-path tenant check, and a filter that moves the total — are the point.

- [ ] **Step 3: Extend the schemas**

In `backend/app/api/v1/schemas/booking_request.py`, add to the create, update and response models:

```python
    # The project this booking belongs to. Distinct from `project_name`, which
    # is free text the UI now labels "Purpose" — see the spec.
    project_id: Optional[int] = None
```

and on the response only:

```python
    project_name_link: Optional[str] = None  # the Project's name, if linked
```

**Name it `project_name_link`, not `project_name`** — that key is already taken on this model by the free-text field, and shadowing it would silently change what every existing client reads.

In `backend/app/api/v1/schemas/release.py`, add `owning_project_id: Optional[int] = None` to create, update and response, plus `owning_project_name: Optional[str] = None` on the response.

- [ ] **Step 4: Validate and carry the names in the services**

In both services, wherever client-supplied FKs are already validated, add the project — on **create and update**:

```python
    if project_id is not None:
        # Scoped to the ACTIVE tenant: under master-admin impersonation
        # current_user.id and active_tenant_id belong to different tenants, and
        # scoping to the wrong one 404s a legitimate request.
        await project_service.get_project(db, project_id, tenant_id)
```

Then extend each service's existing view query with a tenant-qualified **outer** join to `Project`, carrying `Project.name` onto the response. Do **not** filter `Project.deleted_at` on that join — a soft-deleted project must still render its name, exactly as B3b does with a soft-deleted operating group.

Run `grep -n "_view_query\|_select_with_joins" <service>` and update **every** row-unpack site, not just the list one — B3b's review found `get_environment` unpacked the same query and would have broken silently.

- [ ] **Step 5: Add the filters**

Add `project_id: Optional[int] = Query(None)` to both list endpoints and forward it into the service, which applies it in SQL:

```python
    if project_id is not None:
        query = query.where(BookingRequest.project_id == project_id)
```

- [ ] **Step 6: Run the tests, both engines, then commit**

Because this touches shared view queries, also run `tests/integration/test_booking_requests_api.py`, `tests/integration/test_releases_api.py` and `tests/test_pagination.py`.

```bash
git add backend/app/api/v1/schemas/booking_request.py backend/app/api/v1/schemas/release.py \
        backend/app/services/booking_request_service.py backend/app/services/release_service.py \
        backend/app/api/v1/ backend/tests/integration/test_project_links.py
git commit -m "feat(projects): link bookings and releases to a project"
```

---

### Task 5: Frontend types, service and slice

**Files:**
- Create: `frontend/src/types/project.ts`, `frontend/src/services/projectService.ts`, `frontend/src/store/projectSlice.ts`, `frontend/src/store/__tests__/projectSlice.test.ts`
- Modify: `frontend/src/store/index.ts`, `frontend/src/types/booking.ts`, `frontend/src/types/release.ts`

**Interfaces:**
- Consumes: the API from Tasks 2–4.
- Produces: `projectService` (`listProjects`, `getProject`, `createProject`, `updateProject`, `deleteProject`, `listAgreementsForProject`, `listAgreementsForEnvironment`, `createAgreement`, `deleteAgreement`); thunks `fetchProjects`, `fetchProject`, `createProject`, `updateProject`, `deleteProject`, `fetchProjectAgreements`, `fetchEnvironmentAgreements`, `createUsageAgreement`, `deleteUsageAgreement`; state at `state.project` with `{ projects, total, current, agreements, agreementTotal, loading, error }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/store/__tests__/projectSlice.test.ts` covering two behaviours, following `frontend/src/store/__tests__/userGroupSlice.test.ts` exactly for structure:

```typescript
  it('stores the server total, not the row count', async () => {
    vi.mocked(projectService.listProjects).mockResolvedValue({
      rows: [{ id: 1, name: 'Mortgage' }] as never,
      total: 42,
    });
    const store = makeStore();
    await store.dispatch(fetchProjects({}));
    expect(store.getState().project.projects).toHaveLength(1);
    expect(store.getState().project.total).toBe(42);
  });

  it('surfaces the server reason when a create is refused', async () => {
    // AxiosError SHAPE: generic text on .message, the reason only at
    // response.data.detail. A plain Error carrying the final text would pass
    // against broken code, because miniSerializeError keeps .message.
    vi.mocked(projectService.createProject).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 409',
      response: {
        status: 409,
        data: { detail: "A project named 'Mortgage' already exists in this tenant" },
      },
    });
    const store = makeStore();
    const result = await store.dispatch(createProject({ name: 'Mortgage' }));
    expect(createProject.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('already exists');
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/store/__tests__/projectSlice.test.ts`
Expected: FAIL — cannot resolve `../projectSlice`

- [ ] **Step 3: Write the types, service and slice**

Follow `frontend/src/services/userGroupService.ts` for the `Paged<T>` / `x-total-count` shape and `frontend/src/store/userGroupSlice.ts` for the slice. Every thunk wraps its call in `try/catch` and returns `rejectWithValue(formatApiError(err, '<fallback>'))`.

`src/types/project.ts` exports `ProjectResponse` (`{id, tenant_id, name, code, description, team_group_id, team_group_name, environment_count, is_active, created_at, updated_at}`), `ProjectCreate`, `ProjectUpdate`, `UsageAgreementCreate`, `UsageAgreementResponse` (`{id, tenant_id, project_id, project_name, environment_id, environment_name, starts_at, ends_at, notes, created_at}`).

Add to `src/types/booking.ts`: `project_id: number | null` and `project_name_link: string | null` on the response, `project_id?: number | null` on the create/update payloads. Add to `src/types/release.ts`: `owning_project_id: number | null` and `owning_project_name: string | null` on the response, `owning_project_id?: number | null` on the payloads.

**No `fulfilled` handler may splice the projects list** for create, update or delete — it is a server-paged window and local surgery desynchronises the page from its total. Pages refetch. Include the comment saying so.

Adding required fields to the booking and release response types may break existing fixtures' typechecking. Add explicit `null`s to those fixtures rather than making the fields optional — an optional field would make the type lie about the wire contract.

- [ ] **Step 4: Register the reducer, run the test, typecheck, commit**

Add `project: projectReducer` to `frontend/src/store/index.ts`.

Run: `cd frontend && npx vitest run src/store/__tests__/projectSlice.test.ts && npx tsc --noEmit`

```bash
git add frontend/src/types/project.ts frontend/src/types/booking.ts frontend/src/types/release.ts \
        frontend/src/services/projectService.ts frontend/src/store/projectSlice.ts \
        frontend/src/store/index.ts frontend/src/store/__tests__/projectSlice.test.ts
git commit -m "feat(projects): frontend types, service and Redux slice"
```

---

### Task 6: Projects admin screen

**Files:**
- Create: `frontend/src/pages/admin/Projects.tsx`, `frontend/src/pages/admin/ProjectDetail.tsx`, `frontend/src/pages/admin/__tests__/projects.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/pages/admin/AdminLayout.tsx`

**Interfaces:**
- Consumes: the slice from Task 5.
- Produces: routes `/tenant/projects` and `/tenant/projects/:id`; exported `projectColumns`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/admin/__tests__/projects.test.tsx`, following `frontend/src/pages/admin/__tests__/userGroups.test.tsx` for the store/router setup and importing the shared DataGrid stand-in from `frontend/src/test/dataGridMock.tsx` (it invokes both `renderCell` and `valueGetter`).

```tsx
import { describe, expect, it } from 'vitest';

import { projectColumns } from '../Projects';

/**
 * The backend's sort whitelist (PROJECT_SORTS) is `name`, `code`, `created_at`.
 * A sortable header on anything else sends a sort_by the whitelist rejects, and
 * `sorting()` answers 422 rather than falling back silently — so the grid shows
 * an error instead of a sorted list.
 */
describe('projectColumns', () => {
  it('marks every column the backend cannot sort as unsortable', () => {
    const sortable = projectColumns
      .filter((c) => c.sortable !== false)
      .map((c) => c.field)
      .sort();
    // Exactly the whitelist. Asserting the whole set — rather than checking a
    // few columns individually — is what makes a NEW column fail this test
    // until someone decides whether the backend can sort it.
    expect(sortable).toEqual(['code', 'name']);
  });

  it('never makes the joined and computed columns sortable', () => {
    // team_group_name comes from an outer join and environment_count from a
    // correlated subquery. Neither is backed by a single column, so neither can
    // ever be whitelisted — this is permanent, not a gap to fill later.
    for (const field of ['team_group_name', 'environment_count']) {
      expect(projectColumns.find((c) => c.field === field)?.sortable).toBe(false);
    }
  });

  it('renders a missing team as prose rather than a blank cell', () => {
    const column = projectColumns.find((c) => c.field === 'team_group_name');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rendered = column?.renderCell?.({ value: null } as any);
    expect(rendered).toBe('— no team');
  });
});
```

Then a rendering test in the same file, following `userGroups.test.tsx`'s setup, covering:

- the team name and environment count render from the row the API returned, not from any separately-fetched collection;
- a refused create surfaces the **server's** reason. Reject with an AxiosError shape — `{ isAxiosError: true, message: 'Request failed with status code 409', response: { status: 409, data: { detail: "A project named 'Mortgage' already exists in this tenant" } } }` — and assert both that "already exists" is on screen and that "Request failed with status code" is not. A plain `Error` carrying the final text would pass against broken code, because `miniSerializeError` keeps `.message`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/__tests__/projects.test.tsx`
Expected: FAIL — cannot resolve `../Projects`

- [ ] **Step 3: Write the list page**

Create `frontend/src/pages/admin/Projects.tsx`, modelled on `frontend/src/pages/admin/UserGroups.tsx`. Export the columns at module level:

```tsx
// Sortable fields (whitelist-backed, see the backend's PROJECT_SORTS): `name`,
// `code`, `created_at` ONLY. `team_group_name` is joined and
// `environment_count` is a correlated subquery — neither is backed by a single
// column, so neither can be whitelisted, and a sortable header on them 422s.
// eslint-disable-next-line react-refresh/only-export-components
export const projectColumns: GridColDef<ProjectResponse>[] = [
  { field: 'name', headerName: 'Name', flex: 1 },
  { field: 'code', headerName: 'Code', width: 120,
    renderCell: (params) => (params.value as string | null) ?? '—' },
  { field: 'team_group_name', headerName: 'Team', width: 180, sortable: false,
    renderCell: (params) => (params.value as string | null) ?? '— no team' },
  { field: 'environment_count', headerName: 'Environments', width: 140, sortable: false },
  { field: 'is_active', headerName: 'Status', width: 110, sortable: false,
    renderCell: (params) => (params.value ? 'Active' : 'Archived') },
  { field: 'actions', headerName: '', width: 140, sortable: false, disableColumnMenu: true },
];
```

The rest follows `UserGroups.tsx`: fetch on mount, create/edit dialogs with a Name, Code, Description and a Team picker sourced from `state.userGroup.groups`, a delete confirmation, `result.payload` on every rejection, and a refetch after each successful mutation rather than splicing the row. Set `disableColumnFilter` on the grid.

Make the **Environments count link** to `/environments?project_id=<id>` — the filter Task 7 adds makes it work, and a count with no way to see what it counts is a dead end.

- [ ] **Step 4: Write the detail page**

Create `frontend/src/pages/admin/ProjectDetail.tsx`: the project's fields, its team (linking through to `/tenant/groups/<id>`), and its usage agreements in a simple MUI `Table` with an add form (environment picker plus optional start/end dates and notes) and a per-row remove.

**The agreements section needs copy saying it is a record, not a rule** — nothing in A1 stops a project booking an environment it has no agreement for, and without that line the first person to see it will assume it is enforced.

- [ ] **Step 5: Wire routes and nav**

`frontend/src/App.tsx`: `/tenant/projects` → `Projects`, `/tenant/projects/:id` → `ProjectDetail`. Match how `/tenant/groups` is imported — check whether it is lazy.

`frontend/src/pages/admin/AdminLayout.tsx`: a **Projects** entry beside User Groups.

Reads are open to any tenant member, so use a bare `<PrivateRoute>` and gate the write controls on `user?.role === 'Admin' || user?.is_master_admin === true` — B3a shipped these routes admin-gated on a false analogy and it took a review to catch.

- [ ] **Step 6: Run tests, typecheck, lint, commit**

Run: `cd frontend && npx vitest run src/pages/admin && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/pages/admin/Projects.tsx frontend/src/pages/admin/ProjectDetail.tsx \
        frontend/src/pages/admin/__tests__/projects.test.tsx \
        frontend/src/App.tsx frontend/src/pages/admin/AdminLayout.tsx
git commit -m "feat(projects): Projects admin screen with usage agreements"
```

---

### Task 7: Booking and release pickers, filters, and the relabel

**Files:**
- Modify: `frontend/src/pages/bookings/BookingForm.tsx`, `frontend/src/pages/bookings/BookingList.tsx`, `frontend/src/components/releases/ReleaseBookingsTable.tsx`, `frontend/src/pages/releases/ReleaseForm.tsx`, `frontend/src/pages/releases/ReleaseList.tsx`
- Test: the existing `__tests__` beside each, plus a new booking-form case

**Interfaces:**
- Consumes: the slice from Task 5.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/pages/bookings/__tests__/` (follow whatever file already covers `BookingForm`):

- the form sends `project_id` when a project is chosen, and omits it when none is;
- the free-text field is labelled **"Purpose"**, not "Project Name";
- a booking row renders `project_name_link` for the project column, **not** `project_name` — they are different fields and conflating them is the bug this test exists to prevent.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/pages/bookings`
Expected: FAIL on the label and on the new field.

- [ ] **Step 3: The relabel — exactly these sites, and no others**

The word "Project" appears in many places that are **not** this field. Change only:

- `frontend/src/pages/bookings/BookingForm.tsx:56` — the zod message `'Project name is required'` → `'Purpose is required'`
- `frontend/src/pages/bookings/BookingForm.tsx:303` — the `{/* Project Name */}` comment
- `frontend/src/pages/bookings/BookingForm.tsx:306` — `label="Project Name"` → `label="Purpose"`
- `frontend/src/pages/bookings/BookingList.tsx:100` — `headerName: 'Project'` → `'Purpose'`
- `frontend/src/components/releases/ReleaseBookingsTable.tsx:28` — `headerName: 'Project'` → `'Purpose'`

**Do NOT touch** these, which look identical but are different concepts:
- `ScopeTable.tsx:140,249` — `ReleaseChange.project_name`, an external tracker field owned by the deferred Phase 3 Sub-3
- `ScopeWindowsTable.tsx:244`, `LifecycleTemplatesPanel.tsx:639`, `ReleaseForm.tsx:275` — `release_kind='project'` toggles, meaning "not enterprise"
- `MembersTab.tsx:39,81` — the *project release* name inside an enterprise release

The API field name `project_name` is unchanged throughout; this is copy only.

- [ ] **Step 4: Add the pickers and filters**

`BookingForm.tsx`: an optional **Project** select above the Purpose field, sourced from `state.project.projects` via `fetchProjects({ is_active: true })`, sending `project_id` in the payload.

`ReleaseForm.tsx`: an optional **Owning project** select, sending `owning_project_id`. Place it away from the existing release-kind toggle so the two are not confused.

`BookingList.tsx` and `ReleaseList.tsx`: a Project column rendering `project_name_link` / `owning_project_name` (`sortable: false` — joined), and a Project filter through `useServerGrid`'s `filterKeys`.

**The filter's "no selection" state must not be spelled `all` in the URL.** `buildParams` drops a filter valued `all`, so both states would build identical params and the grid would never refetch — a defect that shipped once already. Spell it `any` and restore at the fetch boundary, as `ScopeWindowsTable` does.

- [ ] **Step 5: Run the suite, typecheck, lint, commit**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/pages/bookings/ frontend/src/pages/releases/ \
        frontend/src/components/releases/ReleaseBookingsTable.tsx
git commit -m "feat(projects): project pickers and filters, and relabel the booking free-text field"
```

---

### Task 8: Environment panel, docs, and the browser pass

**Files:**
- Create: `frontend/src/components/environments/EnvironmentProjectsPanel.tsx` and its test
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`, `docs/phases/phase-7.md`, `docs/pagination.md`, `docs/admin-guide.md`, `docs/user-guide.md`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/environments/__tests__/EnvironmentProjectsPanel.test.tsx`, following the store/render setup in `frontend/src/pages/admin/__tests__/userGroups.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import * as projectService from '../../../services/projectService';
import EnvironmentProjectsPanel from '../EnvironmentProjectsPanel';
// renderWithStore: the same helper the admin tests use — mount with a real
// store and a MemoryRouter.
import { renderWithStore } from '../../../test/renderWithStore';

vi.mock('../../../services/projectService');

const agreement = {
  id: 1, tenant_id: 1, project_id: 7, project_name: 'Mortgage Replatform',
  environment_id: 3, environment_name: 'UAT-1',
  starts_at: null, ends_at: null, notes: null,
  created_at: '2026-08-06T00:00:00Z',
};

describe('EnvironmentProjectsPanel', () => {
  it('names projects from the response, never from a fetched list', async () => {
    // The name arrives ON the row. Resolving project_id against a separately
    // fetched, capped projects collection is the `.find()` failure
    // docs/pagination.md documents: a miss renders '—' and loses information.
    vi.mocked(projectService.listAgreementsForEnvironment).mockResolvedValue({
      rows: [agreement], total: 1,
    });
    renderWithStore(<EnvironmentProjectsPanel environmentId={3} />);
    await waitFor(() =>
      expect(screen.getByText('Mortgage Replatform')).toBeInTheDocument()
    );
  });

  it('says an agreement is a record and not a rule', async () => {
    // A1 records agreements and enforces nothing — no booking is refused, no
    // warning is raised. Without this line the first person to see the panel
    // will assume the opposite. Asserted so a later tidy-up cannot drop it.
    vi.mocked(projectService.listAgreementsForEnvironment).mockResolvedValue({
      rows: [agreement], total: 1,
    });
    renderWithStore(<EnvironmentProjectsPanel environmentId={3} />);
    await waitFor(() =>
      expect(screen.getByText(/not enforced/i)).toBeInTheDocument()
    );
  });

  it('shows an empty state rather than a bare table head', async () => {
    vi.mocked(projectService.listAgreementsForEnvironment).mockResolvedValue({
      rows: [], total: 0,
    });
    renderWithStore(<EnvironmentProjectsPanel environmentId={3} />);
    await waitFor(() =>
      expect(screen.getByText(/no projects/i)).toBeInTheDocument()
    );
  });
});
```

Check what the admin tests actually import for `renderWithStore` — if no such helper exists, inline the store/router setup they use instead of inventing one.

- [ ] **Step 2: Run it, then build the panel**

`EnvironmentProjectsPanel.tsx` dispatches `fetchEnvironmentAgreements(environmentId)` on mount and renders a simple MUI `Table`: project name (linking to `/tenant/projects/<id>`), window, notes. Project names come **from the response**, never resolved against a fetched projects list.

Mount it in `frontend/src/pages/environments/EnvironmentDetail.tsx` below the Handover section.

- [ ] **Step 3: Update the four documents**

**`docs/phases/phase-7.md`** — two corrections that are wrong today, not optional:
- the **A1** line claims the project concept leaks through four places; three of them are not references (see the spec's table). Rewrite it.
- the **A3** line still claims ownership of the `UsageAgreement` schema, which A1 now ships. Rewrite it to the enforcement plus the cooperation rules.

Then mark A1 shipped and add a "What A1 established" section on the model of B1's and B3a's.

**`docs/pagination.md`** — re-run the file's own reproducible grep and record the delta this branch causes rather than re-baselining; the figure was already stale before B3b. Add `GET /projects`, `GET /projects/{id}/usage-agreements` and `GET /environments/{id}/usage-agreements` to the bounded table, and a sortable-column row for projects: sortable `name`, `code`, `created_at`; default `name` asc. State that `team_group_name` and `environment_count` are **permanently unsortable**.

**`docs/admin-guide.md`** — the Projects screen, what a team group buys, and that usage agreements are recorded but not enforced in this release.

**`docs/user-guide.md`** — the Project picker on bookings and releases, and that the booking field formerly called "Project Name" is now "Purpose".

- [ ] **Step 4: The browser pass**

Nine defects across the last three sub-projects were found only by opening the page with a fully green suite. Do this before claiming the task done.

With the stack running, logged in as `admin` / `admin123` on tenant `demo`:

1. `/tenant/projects` — create a project, give it a team, see the team name in the list.
2. Add a usage agreement for an environment; confirm it appears on the project detail **and** on that environment's detail panel.
3. `/environments?project_id=<id>` from the Environments count link — confirm the filter survives a reload.
4. Raise a booking with a Project selected; confirm the list shows both the project and the Purpose column, and that they are different values.
5. **Book an environment the project has no agreement for — it must succeed.** That is A1's central promise.
6. Archive the project (`is_active = false`); confirm it drops out of the pickers but existing bookings still show its name.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/environments/ frontend/src/pages/environments/EnvironmentDetail.tsx docs/
git commit -m "feat(projects): environment projects panel, and document A1"
```

---

## Final verification

- [ ] **Backend, both engines** — `cd backend && uv run pytest -q -p no:logging`, then the PostgreSQL leg. Expected: PASS.
- [ ] **Frontend** — `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`.
- [ ] **Open a PR**

```bash
git push -u github feature/project-entity
gh pr create --repo pjgross/envmgr --base main --title "Phase 7 A1: project entity, members and usage agreements"
```

The body should state that A1 records usage agreements and enforces nothing, that `booking_request.project_name` was deliberately kept and relabelled rather than migrated, and that the roadmap's A1 and A3 lines were both corrected.
