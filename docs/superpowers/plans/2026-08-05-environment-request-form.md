# Environment Request Form + Welcome Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an `environment_request` entity with two modes (request access to an environment, or request a new one), routed to the operating team that B3a introduced, on the existing lifecycle-template machinery — plus six handover fields on `Environment` and a Welcome Pack rendered from them.

**Architecture:** The request is modelled on `ChangeRequest`: a `status` VARCHAR driven by a `lifecycle_template`, with role-gated transitions. B3b adds one thing that machinery does not have — a **group** check layered on top of the role check, keyed on the target environment's `operations_group_id`. Handover fields get their own narrow endpoint rather than widening the Admin-gated `PATCH /environments/{id}`. The Welcome Pack is a read model over the environment, stored nowhere.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 (backend); React 18, TypeScript, MUI DataGrid, Redux Toolkit (frontend). Tests: pytest (SQLite + PostgreSQL), vitest.

**Spec:** [docs/superpowers/specs/2026-08-05-environment-request-form-design.md](../specs/2026-08-05-environment-request-form-design.md)

## Global Constraints

- Every query on a tenant-scoped table filters by `current_user.active_tenant_id` — **never** `.tenant_id`, which is wrong under master-admin impersonation.
- List endpoints take `page: Page = Depends(pagination())`, order by a **unique** key (append the primary key), and emit `X-Total-Count` via `set_total_count`.
- **Every filter runs in SQL.** A Python-side filter on a bounded endpoint windows the page before filtering and returns quietly wrong results.
- Migrations are hand-written. **Never** `alembic revision --autogenerate` — `init_db()` calls `create_all`, so autogenerate emits an empty migration.
- **`tests/test_migration_schema_drift.py` compares only column NAME SETS** — not types, defaults or indexes. A passing run is not evidence the migration matches its model. Check types, timezone-awareness and index names by hand against `Base` and the sibling `usergroups` migration.
- Enum-ish columns are plain `String` with `native_enum=False` if `SAEnum` is used at all.
- Entities soft-delete (`deleted_at`); junction rows hard-delete.
- Never call `db.commit()` in a service — `get_db()` auto-commits. Use `db.flush()` for an assigned id.
- Cross-tenant ids return **404**, never 403.
- Frontend thunks `rejectWithValue(formatApiError(err, '<fallback>'))`; components read `result.payload`, never `result.error.message`.
- Frontend test fixtures reject with an **AxiosError shape** — generic text on `.message`, the reason only at `response.data.detail`. A plain `Error` carrying the final text passes against broken code.
- Backend commands from `backend/` via `uv run`; frontend from `frontend/`.
- **Do not run the full test suite in a task** — run the focused tests named. The controller runs full suites.
- PostgreSQL leg: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q -p no:logging`

## File Structure

**Backend — create**
- `app/db/models/environment_request.py` — the `EnvironmentRequest` model
- `app/db/migrations/versions/20260806_1000_envrequests_add_environment_requests.py`
- `app/api/v1/schemas/environment_request.py` — request/response schemas
- `app/services/environment_request_service.py` — CRUD, filters, authorization, fulfilment
- `app/services/environment_request_defaults.py` — the seeded default lifecycle
- `app/api/v1/environment_requests.py` — endpoints
- `tests/integration/test_environment_requests_api.py`
- `tests/integration/test_environment_request_authz.py`
- `tests/integration/test_environment_request_fulfilment.py`
- `tests/integration/test_environment_handover.py`
- `tests/integration/test_welcome_pack.py`

**Backend — modify**
- `app/db/models/environment.py` — six handover columns
- `app/api/v1/schemas/booking_lifecycle.py` — register `environment_request` in `ENTITY_FIELD_SPECS`
- `app/services/tenant_service.py` — seventh seed call
- `app/api/v1/schemas/environment.py` — handover schemas (NOT on `EnvironmentUpdate`)
- `app/api/v1/environments.py` — the handover endpoint
- `app/services/environment_service.py` — `update_handover`
- `app/main.py` — register the router
- `tests/factories.py` — `ensure_environment_request`
- `tests/test_pagination.py`

**Frontend — create**
- `src/types/environmentRequest.ts`, `src/services/environmentRequestService.ts`, `src/store/environmentRequestSlice.ts`
- `src/pages/environments/EnvironmentRequestList.tsx`, `EnvironmentRequestForm.tsx`, `EnvironmentRequestDetail.tsx`
- `src/components/environments/WelcomePack.tsx`, `src/components/environments/HandoverSection.tsx`
- matching `__tests__/` files

**Frontend — modify**
- `src/App.tsx`, `src/components/navConfig.tsx`, `src/store/index.ts`
- `src/pages/environments/EnvironmentDetail.tsx` — mount `HandoverSection`
- `src/types/environment.ts` — handover fields on the response

---

### Task 1: Models, migration, factory

**Files:**
- Create: `backend/app/db/models/environment_request.py`
- Create: `backend/app/db/migrations/versions/20260806_1000_envrequests_add_environment_requests.py`
- Modify: `backend/app/db/models/environment.py`, `backend/app/db/models/__init__.py`, `backend/tests/factories.py`
- Test: `backend/tests/test_environment_request_model.py`

**Interfaces:**
- Consumes: `UserGroup`, `Environment`, `EnvironmentTier`, `LifecycleTemplate` (all existing).
- Produces: `EnvironmentRequest` with the columns below; `Environment.access_url`, `.connection_notes`, `.support_contact`, `.sla_notes`, `.known_limitations`, `.decommission_notes`; `ensure_environment_request(db, tenant_id, **overrides) -> EnvironmentRequest`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_environment_request_model.py`:

```python
"""The request table and the six handover columns B3b adds."""
import pytest
from sqlalchemy import select

from app.db.models.environment_request import EnvironmentRequest
from tests.factories import ensure_environment, ensure_environment_request


@pytest.mark.asyncio
async def test_access_request_persists(db_session, test_tenant):
    req = await ensure_environment_request(db_session, test_tenant.id)
    assert req.id is not None
    assert req.kind == "access"
    assert req.status == "draft"
    assert req.deleted_at is None
    assert req.created_environment_id is None


@pytest.mark.asyncio
async def test_new_environment_request_needs_no_environment(db_session, test_tenant):
    """kind='new_environment' has no target yet — environment_id stays null."""
    req = await ensure_environment_request(
        db_session, test_tenant.id, kind="new_environment",
        environment_id=None, proposed_name="Mortgage PERF",
    )
    assert req.environment_id is None
    assert req.proposed_name == "Mortgage PERF"


@pytest.mark.asyncio
async def test_handover_fields_default_to_null(db_session, test_tenant):
    """A newly created environment has nothing to hand over yet — that is
    correct, not a gap. The operating team fills these in after building it."""
    env = await ensure_environment(db_session, test_tenant.id)
    assert env.access_url is None
    assert env.connection_notes is None
    assert env.support_contact is None
    assert env.sla_notes is None
    assert env.known_limitations is None
    assert env.decommission_notes is None


@pytest.mark.asyncio
async def test_created_environment_link_survives_a_round_trip(db_session, test_tenant):
    """The audit link answering 'where did this environment come from?'."""
    env = await ensure_environment(db_session, test_tenant.id, slot=3)
    req = await ensure_environment_request(
        db_session, test_tenant.id, kind="new_environment",
        environment_id=None, proposed_name="Built",
    )
    req.created_environment_id = env.id
    await db_session.flush()

    stored = (await db_session.execute(
        select(EnvironmentRequest.created_environment_id)
        .where(EnvironmentRequest.id == req.id)
    )).scalar_one()
    assert stored == env.id
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_environment_request_model.py -q -p no:logging`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.environment_request'`

- [ ] **Step 3: Write the model**

Create `backend/app/db/models/environment_request.py`:

```python
"""Requests for environment access, or for a new environment.

Modelled on ChangeRequest: a `status` VARCHAR driven by a lifecycle_template,
so a tenant can add a review step by editing the template rather than needing
a schema change.

One table with a `kind` discriminator rather than two tables — the two modes
share the requester, justification, lifecycle, routing and Welcome Pack, and
differ in four fields. Mode-dependent requirements are enforced in the service,
where a violation can name the missing field; nullability here cannot explain
itself.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

REQUEST_KINDS = ("access", "new_environment")


class EnvironmentRequest(Base):
    __tablename__ = "environment_request"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")
    lifecycle_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=False, index=True
    )
    requested_by: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    needed_by: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # kind='access' — the environment being requested. Required by the service
    # for that kind; nullable here because the other kind has no target.
    environment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("environment.id"), nullable=True, index=True
    )

    # kind='new_environment' — what to build.
    proposed_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("environment_tier.id"), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Chosen by the approving Admin; becomes the created environment's team.
    operations_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True
    )
    # Set on fulfilment. The audit link answering "where did this environment
    # come from?" — the question a manual-creation flow loses.
    created_environment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("environment.id"), nullable=True, index=True
    )

    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentRequest(id={self.id}, kind='{self.kind}', "
            f"status='{self.status}')>"
        )
```

- [ ] **Step 4: Add the handover columns**

In `backend/app/db/models/environment.py`, after `operations_group_id`, add:

```python
    # Handover fields — the Welcome Pack's content, authored by the team that
    # operates this environment (see PATCH /environments/{id}/handover, which
    # is the ONLY write path for them; they are deliberately absent from
    # EnvironmentUpdate). All nullable: a newly created environment has nothing
    # to hand over until it has been built.
    #
    # Credentials are deliberately NOT here. This app has one secret store,
    # built for a single OAuth token. `connection_notes` says WHERE credentials
    # come from — a vault path, a team to ask — without this becoming the place
    # passwords live.
    access_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    connection_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    support_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sla_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    known_limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decommission_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

- [ ] **Step 5: Register the model for `create_all`**

Run: `cd backend && grep -n "user_group" app/db/models/__init__.py`

Add `EnvironmentRequest` alongside `UserGroup`, matching the import style exactly. If the model is not imported before `Base.metadata.create_all`, its table silently will not exist in tests.

- [ ] **Step 6: Add the factory**

In `backend/tests/factories.py`, add `from app.db.models.environment_request import EnvironmentRequest` beside the other model imports, then:

```python
async def ensure_environment_request(
    db: AsyncSession, tenant_id: int, **overrides
) -> EnvironmentRequest:
    """A request for `tenant_id`, defaulting to a valid access request.

    `lifecycle_id`, `requested_by` and `environment_id` are all real FKs, so a
    test must never pass a bare `1`. Pass overrides to change kind or targets.
    """
    from app.db.models.lifecycle import LifecycleTemplate

    user = await ensure_user(db, tenant_id)
    env = await ensure_environment(db, tenant_id)

    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == "environment_request",
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    if tpl is None:
        tpl = LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type="environment_request",
            name="fk-parent-request-lifecycle",
            definition={
                "states": [
                    {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                ],
                "transitions": [],
                "field_permissions": {},
            },
        )
        db.add(tpl)
        await db.flush()

    fields = {
        "tenant_id": tenant_id,
        "kind": "access",
        "status": "draft",
        "lifecycle_id": tpl.id,
        "requested_by": user.id,
        "justification": "fk-parent justification",
        "environment_id": env.id,
    }
    fields.update(overrides)
    req = EnvironmentRequest(**fields)
    db.add(req)
    await db.flush()
    return req
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_environment_request_model.py -q -p no:logging`
Expected: PASS, 4 passed

- [ ] **Step 8: Write the migration**

Create `backend/app/db/migrations/versions/20260806_1000_envrequests_add_environment_requests.py`.

Find the current head first: `cd backend && uv run alembic current` — it must print `usergroups`. Use that as `down_revision`.

```python
"""environment requests + environment handover fields

Revision ID: envrequests
Revises: usergroups
Create Date: 2026-08-06 10:00:00.000000

Purely additive: one new table and six nullable columns. No backfill — an
environment with empty handover fields is a legitimate state, not a defect.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'envrequests'
down_revision: Union[str, None] = 'usergroups'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("lifecycle_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("needed_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("proposed_name", sa.String(length=200), nullable=True),
        sa.Column("tier_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operations_group_id", sa.Integer(), nullable=True),
        sa.Column("created_environment_id", sa.Integer(), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["lifecycle_id"], ["lifecycle_template.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["tier_id"], ["environment_tier.id"]),
        sa.ForeignKeyConstraint(["operations_group_id"], ["user_group.id"]),
        sa.ForeignKeyConstraint(["created_environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id.
    # The usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_environment_request_id", "environment_request", ["id"])
    op.create_index("ix_environment_request_tenant_id", "environment_request", ["tenant_id"])
    op.create_index("ix_environment_request_lifecycle_id", "environment_request", ["lifecycle_id"])
    op.create_index("ix_environment_request_requested_by", "environment_request", ["requested_by"])
    op.create_index("ix_environment_request_environment_id", "environment_request", ["environment_id"])
    op.create_index(
        "ix_environment_request_operations_group_id", "environment_request",
        ["operations_group_id"],
    )
    op.create_index(
        "ix_environment_request_created_environment_id", "environment_request",
        ["created_environment_id"],
    )

    for column, type_ in (
        ("access_url", sa.String(length=500)),
        ("connection_notes", sa.Text()),
        ("support_contact", sa.String(length=255)),
        ("sla_notes", sa.Text()),
        ("known_limitations", sa.Text()),
        ("decommission_notes", sa.Text()),
    ):
        op.add_column("environment", sa.Column(column, type_, nullable=True))


def downgrade() -> None:
    for column in (
        "decommission_notes", "known_limitations", "sla_notes",
        "support_contact", "connection_notes", "access_url",
    ):
        op.drop_column("environment", column)

    for index in (
        "ix_environment_request_created_environment_id",
        "ix_environment_request_operations_group_id",
        "ix_environment_request_environment_id",
        "ix_environment_request_requested_by",
        "ix_environment_request_lifecycle_id",
        "ix_environment_request_tenant_id",
        "ix_environment_request_id",
    ):
        op.drop_index(index, table_name="environment_request")
    op.drop_table("environment_request")
```

- [ ] **Step 9: Verify the migration against the models BY HAND**

`tests/test_migration_schema_drift.py` compares only column **name sets**, so running it is necessary but not sufficient. Four real drifts passed it during B3a.

Build a scratch database from the migrations and one from `create_all`, then compare **types, timezone-awareness, server defaults and index names** for `environment_request` and `environment`. Report the actual observed values, not an assertion that they match.

Then run: `cd backend && uv run pytest tests/test_migration_schema_drift.py tests/test_environment_request_model.py -q -p no:logging`
Expected: PASS

- [ ] **Step 10: Apply to the dev database**

Confirm `uv run alembic current` prints `usergroups`, then `uv run alembic upgrade head`.
Expected: `Running upgrade usergroups -> envrequests`

**Do not run `alembic downgrade -1` against the dev database.** It steps back from the current head, not from your revision; doing this previously dropped `tenant_secret` and destroyed a stored credential. Step 9's scratch database covers both directions.

- [ ] **Step 11: Run both engines, then commit**

Run both legs on `tests/test_environment_request_model.py tests/test_migration_schema_drift.py`.

```bash
git add backend/app/db/models/environment_request.py \
        backend/app/db/models/environment.py \
        backend/app/db/models/__init__.py \
        backend/app/db/migrations/versions/20260806_1000_envrequests_add_environment_requests.py \
        backend/tests/factories.py \
        backend/tests/test_environment_request_model.py
git commit -m "feat(requests): add environment_request and environment handover fields"
```

---

### Task 2: Lifecycle registration and default template

**Files:**
- Create: `backend/app/services/environment_request_defaults.py`
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py`, `backend/app/services/tenant_service.py`
- Modify: the Task 1 migration (append a data-migration seeding existing tenants)
- Test: `backend/tests/test_environment_request_defaults_seed.py`

**Interfaces:**
- Consumes: `EnvironmentRequest` (Task 1).
- Produces: `seed_environment_request_defaults_for_tenant(db, tenant_id) -> None`; `ENTITY_TYPE = "environment_request"`; `DEFAULT_REQUEST_LIFECYCLE` (the definition dict); `ENTITY_FIELD_SPECS["environment_request"]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_environment_request_defaults_seed.py`:

```python
"""The seeded default lifecycle, and the entity registration that validates it."""
import pytest
from sqlalchemy import select

from app.api.v1.schemas.booking_lifecycle import (
    ENTITY_FIELD_SPECS,
    LifecycleDefinition,
    validate_definition_for_entity,
)
from app.db.models.lifecycle import LifecycleTemplate
from app.services.environment_request_defaults import (
    DEFAULT_REQUEST_LIFECYCLE,
    seed_environment_request_defaults_for_tenant,
)


def test_entity_is_registered():
    assert "environment_request" in ENTITY_FIELD_SPECS
    spec = ENTITY_FIELD_SPECS["environment_request"]
    assert {"kind", "justification", "needed_by", "environment_id",
            "proposed_name", "tier_id", "expires_at",
            "operations_group_id"} == set(spec["valid"])
    assert spec["mandatory"] == {"kind", "justification"}


def test_the_seeded_definition_validates_against_its_own_entity_spec():
    """A default the machinery would reject is worse than no default."""
    definition = LifecycleDefinition.model_validate(DEFAULT_REQUEST_LIFECYCLE)
    validate_definition_for_entity(definition, "environment_request")  # no raise


def test_the_default_has_the_states_the_service_depends_on():
    """fulfilment, submission-guard and the pack all key on these names."""
    keys = {s["key"] for s in DEFAULT_REQUEST_LIFECYCLE["states"]}
    assert {"draft", "submitted", "approved", "fulfilled",
            "rejected", "cancelled"} == keys
    terminal = {s["key"] for s in DEFAULT_REQUEST_LIFECYCLE["states"] if s["is_terminal"]}
    assert terminal == {"fulfilled", "rejected", "cancelled"}


@pytest.mark.asyncio
async def test_seeding_is_idempotent(db_session, test_tenant):
    await seed_environment_request_defaults_for_tenant(db_session, test_tenant.id)
    await seed_environment_request_defaults_for_tenant(db_session, test_tenant.id)

    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "environment_request",
            LifecycleTemplate.deleted_at.is_(None),
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_default is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_environment_request_defaults_seed.py -q -p no:logging`
Expected: FAIL — `ModuleNotFoundError: app.services.environment_request_defaults`

- [ ] **Step 3: Register the entity**

In `backend/app/api/v1/schemas/booking_lifecycle.py`, add to `ENTITY_FIELD_SPECS` after `"release"`:

```python
    "environment_request": {
        "valid": {
            "kind", "justification", "needed_by", "environment_id",
            "proposed_name", "tier_id", "expires_at", "operations_group_id",
        },
        # Only the two fields every request must carry regardless of kind.
        # Mode-dependent requirements (environment_id for 'access';
        # proposed_name/tier_id/expires_at for 'new_environment') are enforced
        # in the service, which can name the missing field in its message.
        "mandatory": {"kind", "justification"},
    },
```

- [ ] **Step 4: Write the defaults module**

Create `backend/app/services/environment_request_defaults.py`:

```python
"""The default environment-request lifecycle seeded into every tenant.

Deliberately plain. A tenant wanting a second review step edits it in the
existing admin UI — which is the entire reason B3b reuses lifecycle templates
rather than a fixed status enum.

The ROLE gate lives here. The GROUP gate does not: it is applied on top by
environment_request_service.assert_may_transition, because the template has no
way to express "a member of the target environment's operating team".
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate

ENTITY_TYPE = "environment_request"

_ALL_ROLES = ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]
_APPROVER_ROLES = ["Admin", "Release Manager", "Test Manager"]

DEFAULT_REQUEST_LIFECYCLE: dict[str, Any] = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "fulfilled", "label": "Fulfilled", "is_initial": False, "is_terminal": True},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
        {"key": "cancelled", "label": "Cancelled", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        # Anyone may raise and submit a request — including a Viewer, who is
        # exactly the person most likely to need access to an environment.
        {"from_state": "draft", "to_state": "submitted", "label": "Submit",
         "allowed_roles": _ALL_ROLES},
        {"from_state": "draft", "to_state": "cancelled", "label": "Cancel",
         "allowed_roles": _ALL_ROLES},
        {"from_state": "submitted", "to_state": "approved", "label": "Approve",
         "allowed_roles": _APPROVER_ROLES},
        {"from_state": "submitted", "to_state": "rejected", "label": "Reject",
         "allowed_roles": _APPROVER_ROLES},
        {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision",
         "allowed_roles": _APPROVER_ROLES},
        {"from_state": "approved", "to_state": "fulfilled", "label": "Mark Fulfilled",
         "allowed_roles": _APPROVER_ROLES},
    ],
    "field_permissions": {},
}

_TEMPLATE_NAME = "Standard Request"


async def seed_environment_request_defaults_for_tenant(
    db: AsyncSession, tenant_id: int
) -> None:
    """Idempotent per (tenant, template name), matching the other seeders."""
    existing = (
        await db.execute(
            select(LifecycleTemplate.id).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == ENTITY_TYPE,
                LifecycleTemplate.name == _TEMPLATE_NAME,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).first()
    if existing is not None:
        return

    db.add(
        LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type=ENTITY_TYPE,
            name=_TEMPLATE_NAME,
            description="Raise, approve and fulfil environment requests.",
            is_default=True,
            is_system=False,
            definition=DEFAULT_REQUEST_LIFECYCLE,
        )
    )
    await db.flush()
```

- [ ] **Step 5: Wire it into tenant creation**

In `backend/app/services/tenant_service.py`, add the import beside the other `seed_*` imports and call it alongside them in `create_tenant`:

```python
from app.services.environment_request_defaults import (
    seed_environment_request_defaults_for_tenant,
)
...
    await seed_environment_request_defaults_for_tenant(db, tenant.id)
```

**Check `tests/unit/test_services.py` after this.** B1 added a seed call here and broke two mock-based `create_tenant` unit tests that assert on what `create_tenant` does. Run `uv run pytest tests/unit/test_services.py -q -p no:logging` and patch the new call the way those tests already patch the others.

- [ ] **Step 6: Seed existing tenants in the migration**

Append to the Task 1 migration's `upgrade()`, after the table and columns exist:

```python
    # Seed the default lifecycle for tenants that already exist. A literal copy
    # of DEFAULT_REQUEST_LIFECYCLE rather than an import: a migration
    # reproduces the past and must not change meaning when that module gains a
    # seventh state.
    conn = op.get_bind()
    tenant_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM tenant"))]
    definition = {
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            {"key": "fulfilled", "label": "Fulfilled", "is_initial": False, "is_terminal": True},
            {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
            {"key": "cancelled", "label": "Cancelled", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "submitted", "label": "Submit",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]},
            {"from_state": "draft", "to_state": "cancelled", "label": "Cancel",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]},
            {"from_state": "submitted", "to_state": "approved", "label": "Approve",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
            {"from_state": "submitted", "to_state": "rejected", "label": "Reject",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
            {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
            {"from_state": "approved", "to_state": "fulfilled", "label": "Mark Fulfilled",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
        ],
        "field_permissions": {},
    }
    import json as _json
    for tenant_id in tenant_ids:
        conn.execute(
            sa.text(
                "INSERT INTO lifecycle_template "
                "(tenant_id, entity_type, name, description, is_default, is_system, definition) "
                "VALUES (:t, 'environment_request', 'Standard Request', "
                ":d, true, false, :def)"
            ),
            {"t": tenant_id, "d": "Raise, approve and fulfil environment requests.",
             "def": _json.dumps(definition)},
        )
```

Check `lifecycle_template`'s real column list before running this — `grep -n "class LifecycleTemplate" -A 25 app/db/models/lifecycle.py` — and adjust the INSERT if it has non-nullable columns this omits. If the table stores `definition` as JSON on PostgreSQL and TEXT on SQLite, `json.dumps` is correct for both.

`downgrade()` gains, before dropping the table:

```python
    op.get_bind().execute(
        sa.text("DELETE FROM lifecycle_template WHERE entity_type = 'environment_request'")
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_environment_request_defaults_seed.py tests/unit/test_services.py tests/test_migration_schema_drift.py -q -p no:logging`
Expected: PASS

- [ ] **Step 8: Run both engines, then commit**

```bash
git add backend/app/services/environment_request_defaults.py \
        backend/app/api/v1/schemas/booking_lifecycle.py \
        backend/app/services/tenant_service.py \
        backend/app/db/migrations/versions/20260806_1000_envrequests_add_environment_requests.py \
        backend/tests/test_environment_request_defaults_seed.py \
        backend/tests/unit/test_services.py
git commit -m "feat(requests): register environment_request as a lifecycle entity and seed its default"
```

---

### Task 3: Request CRUD service and API

**Files:**
- Create: `backend/app/api/v1/schemas/environment_request.py`, `backend/app/services/environment_request_service.py`, `backend/app/api/v1/environment_requests.py`
- Create: `backend/tests/integration/test_environment_requests_api.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `EnvironmentRequest` (Task 1), `seed_environment_request_defaults_for_tenant` and `ENTITY_TYPE` (Task 2).
- Produces: `create_request(db, data, requested_by, tenant_id) -> EnvironmentRequestView`; `get_request_view(db, request_id, tenant_id) -> EnvironmentRequestView`; `update_request(db, request_id, data, current_user, tenant_id) -> EnvironmentRequestView`. `EnvironmentRequestView` is a dataclass with `request`, `environment_name`, `requester_username`, `tier_name`, `operations_group_name`. Endpoints mount at `/api/v1/environment-requests`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_requests_api.py`:

```python
"""Request CRUD and mode validation. Authorization has its own file."""
import pytest

from tests.factories import ensure_environment, ensure_environment_tier, ensure_user_group


async def _env(db_session, tenant_id, group=True):
    env = await ensure_environment(db_session, tenant_id)
    if group:
        grp = await ensure_user_group(db_session, tenant_id)
        env.operations_group_id = grp.id
    await db_session.commit()
    return env


@pytest.mark.asyncio
async def test_create_an_access_request(client, auth_headers, db_session, test_tenant):
    env = await _env(db_session, test_tenant.id)

    created = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id,
              "justification": "Need it for UAT"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "access"
    assert body["status"] == "draft"
    # Display names travel with the row — never resolved in the browser
    # against a capped collection.
    assert body["environment_name"] == env.name
    assert body["requester_username"] == "testuser"


@pytest.mark.asyncio
async def test_access_request_without_an_environment_is_422(client, auth_headers):
    bad = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "justification": "no target"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text
    assert "environment_id" in bad.text


@pytest.mark.asyncio
async def test_new_environment_request_needs_name_tier_and_expiry(
    client, auth_headers
):
    bad = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "need a perf env"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text
    for field in ("proposed_name", "tier_id", "expires_at"):
        assert field in bad.text


@pytest.mark.asyncio
async def test_create_a_new_environment_request(
    client, auth_headers, db_session, test_tenant
):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf testing",
              "proposed_name": "Mortgage PERF", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["proposed_name"] == "Mortgage PERF"
    assert created.json()["environment_id"] is None


@pytest.mark.asyncio
async def test_cannot_target_another_tenants_environment(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """404, never 403 — a 403 confirms the environment exists."""
    # The fixture yields a FACTORY; calling it returns (Tenant, User).
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": theirs.id,
              "justification": "leaky"},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_only_a_draft_can_be_edited(
    client, auth_headers, db_session, test_tenant
):
    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "first"},
        headers=auth_headers,
    )).json()["id"]

    edited = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"justification": "revised"},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["justification"] == "revised"

    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    frozen = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"justification": "too late"},
        headers=auth_headers,
    )
    assert frozen.status_code == 409, frozen.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_requests_api.py -q -p no:logging`
Expected: FAIL — 404 on every route.

The last test depends on the transition endpoint from Task 5. Expect it to fail until then; note it in your report and re-run it at Task 5.

- [ ] **Step 3: Write the schemas**

Create `backend/app/api/v1/schemas/environment_request.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentRequestCreate(BaseModel):
    kind: str = Field(pattern="^(access|new_environment)$")
    justification: str = Field(min_length=1)
    needed_by: Optional[datetime] = None
    # kind='access'
    environment_id: Optional[int] = None
    # kind='new_environment'
    proposed_name: Optional[str] = Field(default=None, max_length=200)
    tier_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    custom_fields: Optional[dict] = None


class EnvironmentRequestUpdate(BaseModel):
    justification: Optional[str] = Field(default=None, min_length=1)
    needed_by: Optional[datetime] = None
    environment_id: Optional[int] = None
    proposed_name: Optional[str] = Field(default=None, max_length=200)
    tier_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    # Set by the approving Admin on a new-environment request; becomes the
    # created environment's operating team.
    operations_group_id: Optional[int] = None
    custom_fields: Optional[dict] = None


class EnvironmentRequestTransition(BaseModel):
    to_state: str
    notes: Optional[str] = None


class EnvironmentRequestResponse(BaseModel):
    """Display names travel with the row.

    Resolving them in the browser against separately-fetched collections is the
    failure docs/pagination.md documents: those collections are capped, so a
    `.find()` miss renders the entity as '—' and loses information no
    truncation banner can recover.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    kind: str
    status: str
    lifecycle_id: int
    requested_by: int
    requester_username: Optional[str] = None
    justification: str
    needed_by: Optional[datetime] = None
    environment_id: Optional[int] = None
    environment_name: Optional[str] = None
    proposed_name: Optional[str] = None
    tier_id: Optional[int] = None
    tier_name: Optional[str] = None
    expires_at: Optional[datetime] = None
    operations_group_id: Optional[int] = None
    operations_group_name: Optional[str] = None
    created_environment_id: Optional[int] = None
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view) -> "EnvironmentRequestResponse":
        r = view.request
        return cls(
            id=r.id, tenant_id=r.tenant_id, kind=r.kind, status=r.status,
            lifecycle_id=r.lifecycle_id, requested_by=r.requested_by,
            requester_username=view.requester_username,
            justification=r.justification, needed_by=r.needed_by,
            environment_id=r.environment_id,
            environment_name=view.environment_name,
            proposed_name=r.proposed_name, tier_id=r.tier_id,
            tier_name=view.tier_name, expires_at=r.expires_at,
            operations_group_id=r.operations_group_id,
            operations_group_name=view.operations_group_name,
            created_environment_id=r.created_environment_id,
            custom_fields=r.custom_fields,
            created_at=r.created_at, updated_at=r.updated_at,
        )
```

- [ ] **Step 4: Write the service's CRUD half**

Create `backend/app/services/environment_request_service.py`:

```python
"""Environment requests — CRUD, filtering, authorization and fulfilment.

Mode-dependent validation lives here rather than in the schema so a violation
can name the missing field. The schema cannot express "environment_id is
required when kind='access'" without a validator that produces a worse message.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_request import (
    EnvironmentRequestCreate,
    EnvironmentRequestUpdate,
)
from app.db.models.environment import Environment
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.services.environment_request_defaults import ENTITY_TYPE


@dataclass
class EnvironmentRequestView:
    """A request plus the display labels a UI needs without extra round-trips,
    following environment_service.EnvironmentView."""

    request: EnvironmentRequest
    environment_name: Optional[str]
    requester_username: Optional[str]
    tier_name: Optional[str]
    operations_group_name: Optional[str]


def _view_query(tenant_id: int):
    """The one select carrying a request's display labels.

    Every join is tenant-qualified — defence in depth matching
    environment_service._view_query: a malformed row must not surface another
    tenant's name.
    """
    return (
        select(
            EnvironmentRequest,
            Environment.name,
            User.username,
            EnvironmentTier.name,
            UserGroup.name,
        )
        .outerjoin(
            Environment,
            and_(
                Environment.id == EnvironmentRequest.environment_id,
                Environment.tenant_id == tenant_id,
            ),
        )
        .outerjoin(
            User,
            and_(
                User.id == EnvironmentRequest.requested_by,
                User.tenant_id == tenant_id,
            ),
        )
        .outerjoin(
            EnvironmentTier,
            and_(
                EnvironmentTier.id == EnvironmentRequest.tier_id,
                EnvironmentTier.tenant_id == tenant_id,
            ),
        )
        .outerjoin(
            UserGroup,
            and_(
                UserGroup.id == EnvironmentRequest.operations_group_id,
                UserGroup.tenant_id == tenant_id,
            ),
        )
        .where(
            EnvironmentRequest.tenant_id == tenant_id,
            EnvironmentRequest.deleted_at.is_(None),
        )
    )


def _to_view(row) -> EnvironmentRequestView:
    req, env_name, username, tier_name, group_name = row
    return EnvironmentRequestView(
        request=req, environment_name=env_name, requester_username=username,
        tier_name=tier_name, operations_group_name=group_name,
    )


async def get_request_view(
    db: AsyncSession, request_id: int, tenant_id: int
) -> EnvironmentRequestView:
    row = (
        await db.execute(
            _view_query(tenant_id).where(EnvironmentRequest.id == request_id)
        )
    ).first()
    if row is None:
        # 404 rather than 403 — a 403 confirms the row exists elsewhere.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return _to_view(row)


async def _assert_targets_are_ours(
    db: AsyncSession,
    tenant_id: int,
    *,
    environment_id: Optional[int] = None,
    tier_id: Optional[int] = None,
    operations_group_id: Optional[int] = None,
) -> None:
    """Every client-supplied FK is validated against the ACTIVE tenant.

    Under master-admin impersonation current_user.id and active_tenant_id
    belong to different tenants; scoping this to the wrong one 404s a
    legitimate request. This is also the IDOR class a 2026-07-16 audit of this
    repo found four instances of.
    """
    if environment_id is not None:
        found = (await db.execute(select(Environment.id).where(
            Environment.id == environment_id,
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        ))).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    if tier_id is not None:
        found = (await db.execute(select(EnvironmentTier.id).where(
            EnvironmentTier.id == tier_id,
            EnvironmentTier.tenant_id == tenant_id,
            EnvironmentTier.deleted_at.is_(None),
        ))).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment tier not found")
    if operations_group_id is not None:
        found = (await db.execute(select(UserGroup.id).where(
            UserGroup.id == operations_group_id,
            UserGroup.tenant_id == tenant_id,
            UserGroup.deleted_at.is_(None),
        ))).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User group not found")


def _assert_mode_fields(
    kind: str,
    *,
    environment_id: Optional[int],
    proposed_name: Optional[str],
    tier_id: Optional[int],
    expires_at: Optional[datetime],
) -> None:
    missing: list[str] = []
    if kind == "access":
        if environment_id is None:
            missing.append("environment_id")
    else:
        if not proposed_name:
            missing.append("proposed_name")
        if tier_id is None:
            missing.append("tier_id")
        if expires_at is None:
            missing.append("expires_at")
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"A '{kind}' request requires: {', '.join(missing)}",
        )


async def _default_lifecycle(db: AsyncSession, tenant_id: int) -> LifecycleTemplate:
    tpl = (
        await db.execute(
            select(LifecycleTemplate)
            .where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == ENTITY_TYPE,
                LifecycleTemplate.deleted_at.is_(None),
            )
            .order_by(LifecycleTemplate.is_default.desc(), LifecycleTemplate.id)
        )
    ).scalars().first()
    if tpl is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This tenant has no environment-request lifecycle configured",
        )
    return tpl


async def create_request(
    db: AsyncSession,
    data: EnvironmentRequestCreate,
    requested_by: int,
    tenant_id: int,
) -> EnvironmentRequestView:
    _assert_mode_fields(
        data.kind,
        environment_id=data.environment_id,
        proposed_name=data.proposed_name,
        tier_id=data.tier_id,
        expires_at=data.expires_at,
    )
    await _assert_targets_are_ours(
        db, tenant_id,
        environment_id=data.environment_id, tier_id=data.tier_id,
    )
    tpl = await _default_lifecycle(db, tenant_id)

    req = EnvironmentRequest(
        tenant_id=tenant_id,
        kind=data.kind,
        status="draft",
        lifecycle_id=tpl.id,
        requested_by=requested_by,
        justification=data.justification,
        needed_by=data.needed_by,
        environment_id=data.environment_id if data.kind == "access" else None,
        proposed_name=data.proposed_name if data.kind == "new_environment" else None,
        tier_id=data.tier_id if data.kind == "new_environment" else None,
        expires_at=data.expires_at if data.kind == "new_environment" else None,
        custom_fields=data.custom_fields,
    )
    db.add(req)
    await db.flush()
    return await get_request_view(db, req.id, tenant_id)


async def update_request(
    db: AsyncSession,
    request_id: int,
    data: EnvironmentRequestUpdate,
    current_user: User,
    tenant_id: int,
) -> EnvironmentRequestView:
    view = await get_request_view(db, request_id, tenant_id)
    req = view.request

    if req.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A request can only be edited while it is a draft (this one is '{req.status}')",
        )
    is_admin = current_user.role == "Admin"
    if req.requested_by != current_user.id and not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the requester or an admin can edit this request",
        )

    fields = data.model_dump(exclude_unset=True)
    await _assert_targets_are_ours(
        db, tenant_id,
        environment_id=fields.get("environment_id"),
        tier_id=fields.get("tier_id"),
        operations_group_id=fields.get("operations_group_id"),
    )
    for key, value in fields.items():
        setattr(req, key, value)

    _assert_mode_fields(
        req.kind,
        environment_id=req.environment_id, proposed_name=req.proposed_name,
        tier_id=req.tier_id, expires_at=req.expires_at,
    )
    await db.flush()
    return await get_request_view(db, request_id, tenant_id)
```

- [ ] **Step 5: Write the endpoints**

Create `backend/app/api/v1/environment_requests.py`:

```python
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_request import (
    EnvironmentRequestCreate,
    EnvironmentRequestResponse,
    EnvironmentRequestUpdate,
)
from app.core.security import get_current_user
from app.db.base import get_db
from app.services import environment_request_service

router = APIRouter()


@router.post(
    "", response_model=EnvironmentRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment_request(
    data: EnvironmentRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Any tenant member may raise a request — including a Viewer, who is the
    person most likely to need access."""
    view = await environment_request_service.create_request(
        db, data, current_user.id, current_user.active_tenant_id
    )
    return EnvironmentRequestResponse.from_view(view)


@router.get("/{request_id}", response_model=EnvironmentRequestResponse)
async def get_environment_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_request_service.get_request_view(
        db, request_id, current_user.active_tenant_id
    )
    return EnvironmentRequestResponse.from_view(view)


@router.patch("/{request_id}", response_model=EnvironmentRequestResponse)
async def update_environment_request(
    request_id: int,
    data: EnvironmentRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_request_service.update_request(
        db, request_id, data, current_user, current_user.active_tenant_id
    )
    return EnvironmentRequestResponse.from_view(view)
```

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, beside the other v1 routers:

```python
from app.api.v1 import environment_requests as environment_requests_router
...
app.include_router(
    environment_requests_router.router,
    prefix="/api/v1/environment-requests",
    tags=["Environment Requests"],
)
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && uv run pytest tests/integration/test_environment_requests_api.py -q -p no:logging`
Expected: 5 passed, 1 failed — `test_only_a_draft_can_be_edited` fails at the transition call, which arrives in Task 5. Confirm the failure is the 404 on `/transition` and nothing else.

- [ ] **Step 8: Run both engines, then commit**

```bash
git add backend/app/api/v1/schemas/environment_request.py \
        backend/app/services/environment_request_service.py \
        backend/app/api/v1/environment_requests.py \
        backend/app/main.py \
        backend/tests/integration/test_environment_requests_api.py
git commit -m "feat(requests): environment request CRUD with mode-dependent validation"
```

---

### Task 4: Bounded list and the actionable filter

**Files:**
- Modify: `backend/app/services/environment_request_service.py`, `backend/app/api/v1/environment_requests.py`
- Create: `backend/tests/integration/test_environment_request_filters.py`
- Modify: `backend/tests/test_pagination.py`

**Interfaces:**
- Consumes: `_view_query`, `EnvironmentRequestView` (Task 3).
- Produces: `list_requests(db, tenant_id, *, page=None, sort=None, status_filter=None, kind=None, environment_id=None, mine_for_user_id=None, actionable_for=None) -> tuple[list[EnvironmentRequestView], int]`; `REQUEST_SORTS`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_request_filters.py`:

```python
"""The list endpoint's filters — above all `actionable`, which carries the feature."""
import pytest

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER
from app.db.models.user_group import UserGroupMember
from tests.factories import (
    ensure_environment, ensure_environment_tier, ensure_user, ensure_user_group,
)


async def _submitted_access_request(client, headers, env_id):
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env_id, "justification": "j"},
        headers=headers,
    )).json()["id"]
    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=headers,
    )
    return rid


@pytest.mark.asyncio
async def test_list_is_bounded_and_advertises_its_total(client, auth_headers):
    listed = await client.get("/api/v1/environment-requests", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert isinstance(listed.json(), list)
    assert TOTAL_COUNT_HEADER in listed.headers

    over = await client.get(
        f"/api/v1/environment-requests?limit={MAX_LIMIT + 1}", headers=auth_headers
    )
    assert over.status_code == 422


@pytest.mark.asyncio
async def test_actionable_matches_an_independently_computed_set(
    client, auth_headers, db_session, test_tenant, test_user
):
    """Differential test: the SQL filter's result vs a set computed in Python.

    A subtly wrong filter returns a plausible list, which is why 'returns some
    rows' is not a test.
    """
    group_mine = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    group_theirs = await ensure_user_group(db_session, test_tenant.id, name="Theirs")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group_mine.id, user_id=test_user.id
    ))

    env_mine = await ensure_environment(db_session, test_tenant.id, slot=1)
    env_mine.operations_group_id = group_mine.id
    env_theirs = await ensure_environment(db_session, test_tenant.id, slot=2)
    env_theirs.operations_group_id = group_theirs.id
    await db_session.commit()

    mine = await _submitted_access_request(client, auth_headers, env_mine.id)
    theirs = await _submitted_access_request(client, auth_headers, env_theirs.id)

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    returned = {r["id"] for r in body}

    # Independently computed: submitted, not raised by me... but both WERE
    # raised by me here, so the expected set is empty. That is the point of the
    # exclusion rule — a queue is an inbox, not a mirror.
    assert returned == set()
    assert {mine, theirs} & returned == set()


@pytest.mark.asyncio
async def test_actionable_includes_another_users_request_for_my_team(
    client, auth_headers, db_session, test_tenant, test_user
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=test_user.id
    ))
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    from app.db.models.environment_request import EnvironmentRequest
    from app.services.environment_request_service import _default_lifecycle

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="theirs", environment_id=env.id,
    )
    db_session.add(req)
    await db_session.commit()

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    assert [r["id"] for r in body] == [req.id]


@pytest.mark.asyncio
async def test_actionable_excludes_terminal_requests(
    client, auth_headers, db_session, test_tenant, test_user
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=test_user.id
    ))
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    from app.db.models.environment_request import EnvironmentRequest
    from app.services.environment_request_service import _default_lifecycle

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    for state in ("rejected", "cancelled", "fulfilled"):
        db_session.add(EnvironmentRequest(
            tenant_id=test_tenant.id, kind="access", status=state,
            lifecycle_id=tpl.id, requested_by=other.id,
            justification=state, environment_id=env.id,
        ))
    await db_session.commit()

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    assert body == []


@pytest.mark.asyncio
async def test_mine_returns_only_my_requests(
    client, auth_headers, db_session, test_tenant
):
    env = await ensure_environment(db_session, test_tenant.id)
    grp = await ensure_user_group(db_session, test_tenant.id)
    env.operations_group_id = grp.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    from app.db.models.environment_request import EnvironmentRequest
    from app.services.environment_request_service import _default_lifecycle

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    db_session.add(EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="draft",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="not mine", environment_id=env.id,
    ))
    await db_session.commit()

    mine_id = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "mine"},
        headers=auth_headers,
    )).json()["id"]

    body = (await client.get(
        "/api/v1/environment-requests?mine=true", headers=auth_headers
    )).json()
    assert [r["id"] for r in body] == [mine_id]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_request_filters.py -q -p no:logging`
Expected: FAIL — the list route does not exist.

- [ ] **Step 3: Add the list function**

Append to `backend/app/services/environment_request_service.py`:

```python
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.user_group import UserGroupMember

# States in which a request needs nobody's attention. Kept here rather than
# read from the lifecycle definition because the filter runs in SQL, and a
# per-tenant terminal set cannot be expressed in one query. A tenant that
# renames these in its template gets a queue that ignores its custom terminals
# — documented as a known limitation rather than silently wrong.
TERMINAL_REQUEST_STATES = ("fulfilled", "rejected", "cancelled")

REQUEST_SORTS = {
    "status": EnvironmentRequest.status,
    "kind": EnvironmentRequest.kind,
    "needed_by": EnvironmentRequest.needed_by,
    "created_at": EnvironmentRequest.created_at,
}


def _actionable_clause(user_id: int, is_admin: bool):
    """"Requests my team must action."

    Deliberately does NOT fold in the Admin group-bypass. An Admin sees
    new-environment requests plus access requests for teams they are actually
    in; folding the bypass in would return the whole tenant for every Admin,
    making the queue useless for the one user most likely to need it. The
    bypass exists so a transition is never impossible — it is not a claim about
    whose queue a request belongs in.
    """
    member_exists = (
        select(UserGroupMember.id)
        .where(
            UserGroupMember.group_id == Environment.operations_group_id,
            UserGroupMember.user_id == user_id,
        )
        .correlate(Environment)
        .exists()
    )
    access_clause = and_(
        EnvironmentRequest.kind == "access",
        member_exists,
    )
    if is_admin:
        return or_(access_clause, EnvironmentRequest.kind == "new_environment")
    return access_clause


async def list_requests(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    status_filter: Optional[str] = None,
    kind: Optional[str] = None,
    environment_id: Optional[int] = None,
    mine_for_user_id: Optional[int] = None,
    actionable_for: Optional[tuple[int, bool]] = None,
) -> tuple[list[EnvironmentRequestView], int]:
    """Requests for a tenant, plus the unwindowed total.

    Every filter is applied in SQL. A filter applied in Python after the query
    would window the page before the filter and return quietly wrong results —
    see docs/pagination.md.
    """
    query = _view_query(tenant_id)
    if status_filter is not None:
        query = query.where(EnvironmentRequest.status == status_filter)
    if kind is not None:
        query = query.where(EnvironmentRequest.kind == kind)
    if environment_id is not None:
        query = query.where(EnvironmentRequest.environment_id == environment_id)
    if mine_for_user_id is not None:
        query = query.where(EnvironmentRequest.requested_by == mine_for_user_id)
    if actionable_for is not None:
        user_id, is_admin = actionable_for
        query = query.where(
            EnvironmentRequest.status.notin_(TERMINAL_REQUEST_STATES),
            EnvironmentRequest.requested_by != user_id,
            _actionable_clause(user_id, is_admin),
        )
    query = apply_sort(query, sort).order_by(EnvironmentRequest.id)
    rows, total = await fetch_page_rows(db, query, page)
    return [_to_view(r) for r in rows], total
```

Add `or_` to the `sqlalchemy` import at the top of the file.

- [ ] **Step 4: Add the list endpoint**

Append to `backend/app/api/v1/environment_requests.py`, **above** the `/{request_id}` routes so the literal path is matched first:

```python
@router.get("", response_model=list[EnvironmentRequestResponse])
async def list_environment_requests(
    response: Response,
    status_filter: Optional[str] = Query(None, alias="status"),
    kind: Optional[str] = Query(None),
    environment_id: Optional[int] = Query(None),
    mine: bool = Query(False, description="Only requests I raised."),
    actionable: bool = Query(False, description="Only requests my team must action."),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(
        sorting(environment_request_service.REQUEST_SORTS, default="created_at",
                default_dir="desc")
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readable by any tenant member. Only transitions are gated."""
    views, total = await environment_request_service.list_requests(
        db,
        current_user.active_tenant_id,
        page=page,
        sort=sort,
        status_filter=status_filter,
        kind=kind,
        environment_id=environment_id,
        mine_for_user_id=current_user.id if mine else None,
        actionable_for=(
            (current_user.id, current_user.role == "Admin") if actionable else None
        ),
    )
    set_total_count(response, total)
    return [EnvironmentRequestResponse.from_view(v) for v in views]
```

Extend the imports: `from typing import Optional`, `from fastapi import Query, Response`, and `from app.core.pagination import Page, Sort, pagination, set_total_count, sorting`.

- [ ] **Step 5: Add the pagination and sort-contract entries**

In `backend/tests/test_pagination.py`, add to `BOUNDED_ENDPOINTS`:

```python
    ("environment_requests", "/api/v1/environment-requests", MAX_LIMIT, "auth_headers"),
```

Task 10's grid uses `useServerGrid`, so this endpoint **is** sorted server-side and does need
the contract entries — unlike B3a's `tenant-groups`, whose client-side grid made its entry dead
weight. In `backend/tests/test_sort_whitelist_contract.py` add the import
`from app.services.environment_request_service import REQUEST_SORTS` and the entry:

```python
    "environment-requests": (REQUEST_SORTS, "created_at", "desc"),
```

and in `frontend/src/constants/sortWhitelists.json`:

```json
  "environment-requests": {
    "sortable": ["status", "kind", "needed_by", "created_at"],
    "default": "created_at",
    "default_dir": "desc"
  }
```

Note `default_dir` is `"desc"` and is **endpoint-wide**: `sorting()` takes one default direction
for the whole endpoint, so a column-header click that omits `sort_dir` resolves to descending.
Task 10's grid must always send an explicit `sort_dir` when the user chooses a sort.

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest tests/integration/test_environment_request_filters.py tests/test_pagination.py -q -p no:logging`
Expected: the filter tests that need `/transition` fail until Task 5; the rest pass. Note which in your report.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/environment_request_service.py \
        backend/app/api/v1/environment_requests.py \
        backend/tests/integration/test_environment_request_filters.py \
        backend/tests/test_pagination.py
git commit -m "feat(requests): bounded list with the actionable and mine filters"
```

---

### Task 5: Transition authorization

**Files:**
- Modify: `backend/app/services/environment_request_service.py`, `backend/app/api/v1/environment_requests.py`
- Create: `backend/tests/integration/test_environment_request_authz.py`

**Interfaces:**
- Consumes: `get_request_view` (Task 3).
- Produces: `assert_may_transition(db, request, to_state, current_user, tenant_id) -> LifecycleTemplate` (it returns the loaded template so the caller need not re-fetch it); `transition(db, request_id, to_state, current_user, tenant_id, notes=None) -> EnvironmentRequestView`; `allowed_transitions(db, request_id, current_user, tenant_id) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_request_authz.py`. This is the most important test file in B3b: B3a shipped an authorization split with **no backend test at all**, and flipping its reads left 83 tests green.

```python
"""The role × group × kind × Admin-bypass matrix.

Each test must FAIL if its rule is inverted, not merely pass today.
"""
import pytest

from app.core.security import get_password_hash
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from tests.factories import ensure_environment, ensure_user_group


async def _login(client, tenant_slug, username, password="password123"):
    r = await client.post("/api/v1/auth/login", json={
        "username": username, "password": password, "tenant_slug": tenant_slug,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _member(db_session, tenant, username, role, group=None):
    user = User(
        tenant_id=tenant.id, username=username, email=f"{username}@t.local",
        password_hash=get_password_hash("password123"), role=role, is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    if group is not None:
        db_session.add(UserGroupMember(
            tenant_id=tenant.id, group_id=group.id, user_id=user.id
        ))
    await db_session.commit()
    return user


async def _submitted_request(db_session, tenant, env, requester):
    from app.services.environment_request_service import _default_lifecycle
    tpl = await _default_lifecycle(db_session, tenant.id)
    req = EnvironmentRequest(
        tenant_id=tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=requester.id,
        justification="j", environment_id=env.id,
    )
    db_session.add(req)
    await db_session.commit()
    return req


@pytest.mark.asyncio
async def test_right_role_in_the_group_may_approve(
    client, db_session, test_tenant, test_user
):
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    approver = await _member(db_session, test_tenant, "tm-in", "Test Manager", group)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-in")
    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_right_role_NOT_in_the_group_is_refused(
    client, db_session, test_tenant, test_user
):
    """The rule that makes routing mean anything."""
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    outsider = await _member(db_session, test_tenant, "tm-out", "Test Manager", None)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-out")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_wrong_role_in_the_group_is_refused(
    client, db_session, test_tenant, test_user
):
    """Membership does not confer approval rights — the template still rules."""
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    viewer = await _member(db_session, test_tenant, "viewer-in", "Viewer", group)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "viewer-in")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_admin_bypasses_the_group_but_not_the_role(
    client, db_session, test_tenant, test_user, auth_headers
):
    """auth_headers is an Admin who is in no group."""
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text

    # The role check still applies: no transition exists from 'approved' to
    # 'submitted', so even an Admin cannot make it.
    bad = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    assert bad.status_code == 400, bad.text


@pytest.mark.asyncio
async def test_a_new_environment_request_needs_an_admin(
    client, db_session, test_tenant, test_user
):
    """There is no environment, so the group clause cannot apply."""
    from app.services.environment_request_service import _default_lifecycle
    from tests.factories import ensure_environment_tier

    tier = await ensure_environment_tier(db_session, test_tenant.id)
    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="new_environment", status="submitted",
        lifecycle_id=tpl.id, requested_by=test_user.id, justification="j",
        proposed_name="New", tier_id=tier.id,
    )
    db_session.add(req)
    await db_session.commit()
    await _member(db_session, test_tenant, "rm", "Release Manager", None)

    headers = await _login(client, test_tenant.slug, "rm")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_submitting_without_an_operations_group_is_refused(
    client, auth_headers, db_session, test_tenant
):
    """B3a's promise: B3b refuses to ROUTE a request that has no team.

    Refused at submission rather than at action — a request only an Admin can
    see is one that sits unactioned with nobody knowing why.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = None
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]

    refused = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    assert refused.status_code == 409, refused.text
    assert env.name in refused.json()["detail"]


@pytest.mark.asyncio
async def test_an_empty_group_degrades_to_admin_only(
    client, auth_headers, db_session, test_tenant, test_user
):
    """A group with no members must not make a request unactionable."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Empty")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_the_group_check_resolves_against_the_impersonated_tenant(
    client, db_session, test_tenant, test_user
):
    """Under master-admin impersonation `current_user.id` and
    `active_tenant_id` belong to DIFFERENT tenants.

    The membership lookup joins on tenant_id, so resolving it against the
    caller's home tenant finds nothing and 403s a legitimate action. This
    mismatch has already broken an owner validation in this repo and killed an
    entire spreadsheet upload.

    The acting user's role is 'Test Manager' — an approver role, so the ROLE
    gate passes on its own merits — and they are a MEMBER of the impersonated
    tenant's group. Their role is deliberately not 'Admin', so the Admin bypass
    cannot mask a broken group lookup: the only way this transition succeeds is
    if the membership query resolves against the ACTIVE tenant.
    """
    from app.core.security import create_access_token
    from app.db.models.user import Tenant
    from app.db.models.user_group import UserGroupMember

    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id

    home = Tenant(name="System Org", slug="system-req-imp")
    db_session.add(home)
    await db_session.flush()
    master = User(
        tenant_id=home.id, username="req-masteradmin", email="rm@imp.com",
        password_hash=get_password_hash("password123"), role="Test Manager",
        is_active=True, is_master_admin=True,
    )
    db_session.add(master)
    await db_session.flush()
    membership = UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=master.id
    )
    db_session.add(membership)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    token = create_access_token({
        "sub": str(master.id),
        "tenant_id": home.id,
        "impersonating_tenant_id": test_tenant.id,
    })
    headers = {"Authorization": f"Bearer {token}"}

    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_request_authz.py -q -p no:logging`
Expected: FAIL — 404 on `/transition`.

If `test_tenant` has no `.slug`, check the fixture and use whatever attribute it exposes.

- [ ] **Step 3: Write the authorization and transition**

Append to `backend/app/services/environment_request_service.py`:

```python
from app.core.events import publish_event
from app.services import lifecycle_service


async def _is_in_operations_group(
    db: AsyncSession, environment_id: Optional[int], user_id: int, tenant_id: int
) -> bool:
    if environment_id is None:
        return False
    found = (
        await db.execute(
            select(UserGroupMember.id)
            .join(Environment, Environment.operations_group_id == UserGroupMember.group_id)
            .where(
                Environment.id == environment_id,
                Environment.tenant_id == tenant_id,
                UserGroupMember.user_id == user_id,
                UserGroupMember.tenant_id == tenant_id,
            )
        )
    ).first()
    return found is not None


async def assert_may_transition(
    db: AsyncSession,
    req: EnvironmentRequest,
    to_state: str,
    current_user: User,
    tenant_id: int,
) -> LifecycleTemplate:
    """The one place in this application that reads group membership for
    authorization, alongside environment_service.assert_may_edit_handover.

        may = role AND (group OR Admin)

    Admin bypasses the GROUP check but not the ROLE check, so a request can
    never become permanently unactionable because a team was emptied — while
    the lifecycle template still means something.
    """
    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.id == req.lifecycle_id,
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lifecycle template not found")

    allowed, reason = lifecycle_service.validate_transition(
        tpl.definition, req.status, to_state, current_user.role, {}
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            reason
            or f"Transition from '{req.status}' to '{to_state}' is not allowed",
        )

    is_admin = current_user.role == "Admin"
    if not is_admin:
        in_group = await _is_in_operations_group(
            db, req.environment_id, current_user.id, tenant_id
        )
        if not in_group:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only the operating team for this environment, or an admin, "
                "can action this request",
            )
    return tpl


async def _assert_routable(db: AsyncSession, req: EnvironmentRequest, tenant_id: int) -> None:
    """B3a's promise, honoured at submission.

    A request whose environment has no operating team has nobody to route to.
    Refusing here beats letting it through: a request only an Admin can see
    sits unactioned with nobody knowing why.
    """
    if req.kind != "access" or req.environment_id is None:
        return
    row = (
        await db.execute(
            select(Environment.name, Environment.operations_group_id).where(
                Environment.id == req.environment_id,
                Environment.tenant_id == tenant_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    name, group_id = row
    if group_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{name} has no operations team, so this request cannot be routed. "
            "Ask an admin to assign one.",
        )


async def transition(
    db: AsyncSession,
    request_id: int,
    to_state: str,
    current_user: User,
    tenant_id: int,
    notes: Optional[str] = None,
) -> EnvironmentRequestView:
    view = await get_request_view(db, request_id, tenant_id)
    req = view.request

    if to_state == "submitted":
        await _assert_routable(db, req, tenant_id)

    await assert_may_transition(db, req, to_state, current_user, tenant_id)

    from_state = req.status
    req.status = to_state
    await db.flush()

    await publish_event(
        db,
        event_type="EnvironmentRequestTransitioned",
        aggregate_id=req.id,
        aggregate_type="EnvironmentRequest",
        payload={"id": req.id, "from_state": from_state, "to_state": to_state},
        tenant_id=tenant_id,
    )
    return await get_request_view(db, request_id, tenant_id)


async def allowed_transitions(
    db: AsyncSession, request_id: int, current_user: User, tenant_id: int
) -> list[dict]:
    """Transitions this actor may ACTUALLY make — role and group both applied.

    The detail page renders these as buttons. Returning role-allowed
    transitions the group check would then refuse produces a button that
    always 403s.
    """
    view = await get_request_view(db, request_id, tenant_id)
    req = view.request
    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(LifecycleTemplate.id == req.lifecycle_id)
        )
    ).scalar_one_or_none()
    if tpl is None:
        return []

    by_role = lifecycle_service.get_allowed_transitions(
        tpl.definition, req.status, current_user.role
    )
    if current_user.role == "Admin":
        return by_role
    in_group = await _is_in_operations_group(
        db, req.environment_id, current_user.id, tenant_id
    )
    return by_role if in_group else []
```

- [ ] **Step 4: Add the transition endpoint**

Append to `backend/app/api/v1/environment_requests.py`:

```python
@router.post("/{request_id}/transition", response_model=EnvironmentRequestResponse)
async def transition_environment_request(
    request_id: int,
    data: EnvironmentRequestTransition,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_request_service.transition(
        db, request_id, data.to_state, current_user,
        current_user.active_tenant_id, notes=data.notes,
    )
    return EnvironmentRequestResponse.from_view(view)


@router.get("/{request_id}/allowed-transitions")
async def get_allowed_transitions(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_request_service.allowed_transitions(
        db, request_id, current_user, current_user.active_tenant_id
    )
```

Add `EnvironmentRequestTransition` to the schema import.

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest tests/integration/test_environment_request_authz.py tests/integration/test_environment_requests_api.py tests/integration/test_environment_request_filters.py -q -p no:logging`
Expected: PASS — including the two tests deferred from Tasks 3 and 4.

- [ ] **Step 6: Prove the matrix discriminates**

For each of these, make the change, run the authz file, confirm the named test fails, then revert:

1. Remove the `if not is_admin:` group check → `test_right_role_NOT_in_the_group_is_refused` must fail.
2. Make `assert_may_transition` skip `validate_transition` → `test_wrong_role_in_the_group_is_refused` must fail.
3. Make `_is_in_operations_group` return `True` unconditionally → `test_a_new_environment_request_needs_an_admin` must fail.
4. Remove the `_assert_routable` call → `test_submitting_without_an_operations_group_is_refused` must fail.

Report the before/after for each. A matrix that passes today but survives inversion guards nothing — this is exactly how B3a's authorization split shipped untested.

- [ ] **Step 7: Run both engines, then commit**

```bash
git add backend/app/services/environment_request_service.py \
        backend/app/api/v1/environment_requests.py \
        backend/tests/integration/test_environment_request_authz.py
git commit -m "feat(requests): transition authorization on role AND operating-team membership"
```

---

### Task 6: Fulfilment

**Files:**
- Modify: `backend/app/services/environment_request_service.py`
- Create: `backend/tests/integration/test_environment_request_fulfilment.py`

**Interfaces:**
- Consumes: `transition` (Task 5), `Environment`, `EnvironmentStatus`.
- Produces: fulfilment behaviour inside `transition` — no new public function.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_request_fulfilment.py`:

```python
"""Fulfilling a new-environment request creates the environment."""
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_request import EnvironmentRequest
from tests.factories import ensure_environment_tier, ensure_user_group


async def _approved_new_env_request(client, auth_headers, db_session, test_tenant):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf",
              "proposed_name": "Mortgage PERF", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]
    await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=auth_headers,
    )
    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "approved"}, headers=auth_headers,
    )
    return rid, tier, group


@pytest.mark.asyncio
async def test_fulfilment_creates_an_inactive_environment(
    client, auth_headers, db_session, test_tenant
):
    """INACTIVE, not ACTIVE: the register must not claim an environment is
    available before anyone has built it."""
    rid, tier, group = await _approved_new_env_request(
        client, auth_headers, db_session, test_tenant
    )

    done = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "fulfilled"}, headers=auth_headers,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "fulfilled"
    assert body["created_environment_id"] is not None

    env = (await db_session.execute(
        select(Environment).where(Environment.id == body["created_environment_id"])
    )).scalar_one()
    assert env.name == "Mortgage PERF"
    assert env.status == EnvironmentStatus.INACTIVE
    assert env.tier_id == tier.id
    assert env.operations_group_id == group.id
    # The requester becomes the owner — the governance field is populated by
    # construction and can never be null on a request-created environment.
    assert env.owner_user_id is not None
    # Nothing to hand over until it is built.
    assert env.access_url is None


@pytest.mark.asyncio
async def test_fulfilling_an_access_request_creates_nothing(
    client, auth_headers, db_session, test_tenant
):
    from tests.factories import ensure_environment

    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    before = (await db_session.execute(select(Environment.id))).scalars().all()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]
    for state in ("submitted", "approved", "fulfilled"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )
        assert r.status_code == 200, r.text

    after = (await db_session.execute(select(Environment.id))).scalars().all()
    assert set(after) == set(before)
    assert r.json()["created_environment_id"] is None


@pytest.mark.asyncio
async def test_fulfilment_without_an_operations_group_is_refused(
    client, auth_headers, db_session, test_tenant
):
    """The created environment's operating team is not optional."""
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf",
              "proposed_name": "No Team", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]
    for state in ("submitted", "approved"):
        await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )

    refused = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "fulfilled"}, headers=auth_headers,
    )
    assert refused.status_code == 409, refused.text
    assert "operations" in refused.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_failed_creation_rolls_back_the_transition(
    client, auth_headers, db_session, test_tenant
):
    """All three writes land together or none do.

    Reuse an existing environment name to trip the tenant-name unique guard.
    """
    from tests.factories import ensure_environment

    existing = await ensure_environment(db_session, test_tenant.id)
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id)
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "clash",
              "proposed_name": existing.name, "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]
    await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=auth_headers,
    )
    for state in ("submitted", "approved"):
        await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )

    clash = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "fulfilled"}, headers=auth_headers,
    )
    assert clash.status_code in (400, 409), clash.text

    still = (await client.get(
        f"/api/v1/environment-requests/{rid}", headers=auth_headers
    )).json()
    assert still["status"] == "approved", "the transition must not have stuck"
    assert still["created_environment_id"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_request_fulfilment.py -q -p no:logging`
Expected: FAIL — `created_environment_id` stays null.

**If `test_a_failed_creation_rolls_back_the_transition` cannot trip a clash**, check whether a per-tenant unique name guard exists (`grep -rn "uq_environment_tenant_name" backend/`). If it does not, replace that test's trigger with one that does fail — e.g. a `proposed_name` longer than the column allows on the PostgreSQL leg — and say so in your report. Do not delete the test: the rollback property is the point.

- [ ] **Step 3: Implement fulfilment**

In `backend/app/services/environment_request_service.py`, add the helper and call it from `transition` **before** the state is written, so a failure aborts the whole thing:

```python
from app.db.models.environment import EnvironmentStatus


async def _fulfil_new_environment(
    db: AsyncSession, req: EnvironmentRequest, tenant_id: int
) -> Environment:
    """Create the environment this request asked for.

    INACTIVE, not ACTIVE: the register must not claim an environment is
    available before anyone has built it. That drift between the register and
    reality is what this product exists to prevent — an admin flips it active
    once the infrastructure exists.

    The governance fields are populated by construction, so a request-created
    environment can never appear in `?governance_gap=true`.
    """
    if req.operations_group_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This request has no operations team assigned. An admin must "
            "choose which team will operate the environment before it can be "
            "fulfilled.",
        )
    env = Environment(
        tenant_id=tenant_id,
        name=req.proposed_name,
        description=req.justification,
        tier_id=req.tier_id,
        owner_user_id=req.requested_by,
        expires_at=req.expires_at,
        operations_group_id=req.operations_group_id,
        status=EnvironmentStatus.INACTIVE,
    )
    db.add(env)
    await db.flush()
    return env
```

In `transition`, between the authorization call and the status write:

```python
    created: Optional[Environment] = None
    if to_state == "fulfilled" and req.kind == "new_environment":
        # Before the status write: a failure here must abort the transition
        # too. get_db() wraps the request in one transaction, so raising
        # rolls back the flush above with it.
        created = await _fulfil_new_environment(db, req, tenant_id)

    from_state = req.status
    req.status = to_state
    if created is not None:
        req.created_environment_id = created.id
    await db.flush()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_environment_request_fulfilment.py -q -p no:logging`
Expected: PASS, 4 passed

- [ ] **Step 5: Run both engines, then commit**

```bash
git add backend/app/services/environment_request_service.py \
        backend/tests/integration/test_environment_request_fulfilment.py
git commit -m "feat(requests): fulfilment creates the requested environment as inactive"
```

---

### Task 7: The handover endpoint

**Files:**
- Modify: `backend/app/api/v1/schemas/environment.py`, `backend/app/services/environment_service.py`, `backend/app/api/v1/environments.py`
- Create: `backend/tests/integration/test_environment_handover.py`

**Interfaces:**
- Consumes: the six handover columns (Task 1), `UserGroupMember`.
- Produces: `EnvironmentHandoverUpdate` schema; `environment_service.assert_may_edit_handover(db, environment_id, current_user, tenant_id) -> None`; `environment_service.update_handover(db, environment_id, data, current_user, tenant_id) -> EnvironmentView`; `PATCH /environments/{id}/handover`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_environment_handover.py`:

```python
"""The handover endpoint: who may write, and — more importantly — WHAT it accepts."""
import pytest

from app.core.security import get_password_hash
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from tests.factories import ensure_environment, ensure_environment_tier, ensure_user_group


async def _login(client, tenant_slug, username, password="password123"):
    r = await client.post("/api/v1/auth/login", json={
        "username": username, "password": password, "tenant_slug": tenant_slug,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _env_with_team(db_session, tenant, member_username=None, role="Developer"):
    group = await ensure_user_group(db_session, tenant.id, name="Ops")
    env = await ensure_environment(db_session, tenant.id)
    env.operations_group_id = group.id
    await db_session.flush()
    if member_username:
        user = User(
            tenant_id=tenant.id, username=member_username,
            email=f"{member_username}@t.local",
            password_hash=get_password_hash("password123"),
            role=role, is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(UserGroupMember(
            tenant_id=tenant.id, group_id=group.id, user_id=user.id
        ))
    await db_session.commit()
    return env, group


@pytest.mark.asyncio
async def test_the_operating_team_may_author_handover_fields(
    client, db_session, test_tenant
):
    """A Developer — who cannot touch PATCH /environments at all — can do this."""
    env, _ = await _env_with_team(db_session, test_tenant, "dev-in-team")
    headers = await _login(client, test_tenant.slug, "dev-in-team")

    ok = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://sit.example.com",
              "connection_notes": "VPN: corp-vpn. Credentials: ask #platform-ops."},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["access_url"] == "https://sit.example.com"


@pytest.mark.asyncio
async def test_a_non_member_is_refused(client, db_session, test_tenant):
    env, _ = await _env_with_team(db_session, test_tenant)
    outsider = User(
        tenant_id=test_tenant.id, username="outsider", email="o@t.local",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(outsider)
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "outsider")

    refused = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://nope"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_an_admin_may_author_them_without_being_in_the_team(
    client, auth_headers, db_session, test_tenant
):
    env, _ = await _env_with_team(db_session, test_tenant)
    ok = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"support_contact": "#platform-ops"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_an_environment_with_no_team_is_admin_only(
    client, auth_headers, db_session, test_tenant
):
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = None
    await db_session.commit()

    ok = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"sla_notes": "best effort"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"tier_id": 1},
        {"owner_user_id": 1},
        {"operations_group_id": 1},
        {"status": "active"},
        {"name": "renamed"},
        {"expires_at": "2030-01-01T00:00:00Z"},
    ],
)
async def test_it_rejects_every_non_handover_key(
    client, db_session, test_tenant, payload
):
    """THE test for this endpoint.

    Its safety rests on the narrow surface, not on the permission. A member of
    an operating team must not be able to change which team operates the
    environment, clear its owner, or rename it. Asserted by SENDING those keys,
    not by reading the schema.
    """
    env, _ = await _env_with_team(db_session, test_tenant, "dev-in-team")
    headers = await _login(client, test_tenant.slug, "dev-in-team")

    refused = await client.patch(
        f"/api/v1/environments/{env.id}/handover", json=payload, headers=headers,
    )
    assert refused.status_code == 422, f"{payload} was accepted: {refused.text}"


@pytest.mark.asyncio
async def test_handover_fields_are_absent_from_the_ordinary_update_path(
    client, auth_headers, db_session, test_tenant
):
    """One write path, not two to keep in step."""
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    refused = await client.patch(
        f"/api/v1/environments/{env.id}",
        json={"access_url": "https://via-the-wrong-door"}, headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_environment_handover.py -q -p no:logging`
Expected: FAIL — 404 on `/handover`.

Note: the last test also requires `EnvironmentUpdate` to forbid extra keys. If Pydantic silently ignores them, add `model_config = ConfigDict(extra="forbid")` to `EnvironmentUpdate` — and check the whole environment suite afterwards, since that is a behaviour change for every caller.

- [ ] **Step 3: Add the schema**

In `backend/app/api/v1/schemas/environment.py`, add — and **do not** add these fields to `EnvironmentUpdate`:

```python
class EnvironmentHandoverUpdate(BaseModel):
    """The Welcome Pack's content. Six keys and no others.

    `extra="forbid"` is the safety property of this endpoint, not its
    authorization: whatever the permission rule says, a request body cannot
    reach tier_id, owner_user_id, operations_group_id or status through here.
    """

    model_config = ConfigDict(extra="forbid")

    access_url: Optional[str] = Field(default=None, max_length=500)
    connection_notes: Optional[str] = None
    support_contact: Optional[str] = Field(default=None, max_length=255)
    sla_notes: Optional[str] = None
    known_limitations: Optional[str] = None
    decommission_notes: Optional[str] = None
```

Also add the six fields to `EnvironmentResponse` (read-only) and pass them through `from_view`.

- [ ] **Step 4: Add the service function**

In `backend/app/services/environment_service.py`:

```python
async def assert_may_edit_handover(
    db: AsyncSession, environment_id: int, current_user, tenant_id: int
) -> None:
    """The operating team, or an Admin.

    This is the second of exactly two places in the application that read group
    membership for authorization; the other is
    environment_request_service.assert_may_transition.
    """
    from app.db.models.user_group import UserGroupMember

    if current_user.role == "Admin":
        return
    found = (
        await db.execute(
            select(UserGroupMember.id)
            .join(Environment, Environment.operations_group_id == UserGroupMember.group_id)
            .where(
                Environment.id == environment_id,
                Environment.tenant_id == tenant_id,
                UserGroupMember.user_id == current_user.id,
                UserGroupMember.tenant_id == tenant_id,
            )
        )
    ).first()
    if found is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the operating team for this environment, or an admin, can "
            "edit its handover details",
        )


async def update_handover(
    db: AsyncSession, environment_id: int, data, current_user, tenant_id: int
) -> "EnvironmentView":
    env = await _get_environment(db, environment_id, tenant_id)
    await assert_may_edit_handover(db, environment_id, current_user, tenant_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(env, key, value)
    await db.flush()
    return await get_environment_view(db, environment_id, tenant_id)
```

Use whatever the existing single-environment fetch helper is called — check with `grep -n "async def get_environment" app/services/environment_service.py` and reuse it rather than adding another.

- [ ] **Step 5: Add the endpoint**

In `backend/app/api/v1/environments.py`:

```python
@router.patch("/{env_id}/handover", response_model=EnvironmentResponse)
async def update_environment_handover(
    env_id: int,
    data: EnvironmentHandoverUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The Welcome Pack's content, authored by the team that operates this
    environment. Deliberately NOT part of PATCH /environments/{id}, which is
    Admin-gated and also edits tier, owner, expiry, status and the operations
    group itself — fields whose control must stay with Admins.
    """
    return EnvironmentResponse.from_view(
        await environment_service.update_handover(
            db, env_id, data, current_user, current_user.active_tenant_id
        )
    )
```

Note it uses `get_current_user`, not `require_tenant_admin()` — the permission is checked in the service.

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest tests/integration/test_environment_handover.py tests/integration/test_environments.py -q -p no:logging`
Expected: PASS

- [ ] **Step 7: Prove the narrow surface holds**

Temporarily change `EnvironmentHandoverUpdate`'s `extra="forbid"` to `extra="ignore"` and re-run. `test_it_rejects_every_non_handover_key` must fail on all six parameterisations. Restore and confirm they pass. Report both.

- [ ] **Step 8: Run both engines, then commit**

```bash
git add backend/app/api/v1/schemas/environment.py \
        backend/app/services/environment_service.py \
        backend/app/api/v1/environments.py \
        backend/tests/integration/test_environment_handover.py
git commit -m "feat(environments): handover fields with a narrow, team-writable endpoint"
```

---

### Task 8: The Welcome Pack endpoint

**Files:**
- Modify: `backend/app/services/environment_request_service.py`, `backend/app/api/v1/environment_requests.py`, `backend/app/api/v1/schemas/environment_request.py`
- Create: `backend/tests/integration/test_welcome_pack.py`

**Interfaces:**
- Consumes: handover fields (Task 1/7), `UserGroupMember`.
- Produces: `WelcomePackResponse` schema; `build_welcome_pack(db, request_id, tenant_id) -> WelcomePackResponse`; `GET /environment-requests/{id}/welcome-pack`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_welcome_pack.py`:

```python
"""The Welcome Pack — a read model, stored nowhere."""
import pytest

from app.db.models.user_group import UserGroupMember
from tests.factories import ensure_environment, ensure_user, ensure_user_group


async def _fulfilled_access_request(client, headers, db_session, tenant):
    group = await ensure_user_group(db_session, tenant.id, name="Platform Ops")
    member = await ensure_user(db_session, tenant.id, username="ops-ada")
    db_session.add(UserGroupMember(
        tenant_id=tenant.id, group_id=group.id, user_id=member.id
    ))
    env = await ensure_environment(db_session, tenant.id)
    env.operations_group_id = group.id
    env.access_url = "https://sit.example.com"
    env.connection_notes = "VPN: corp-vpn. Credentials: ask #platform-ops."
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "UAT"},
        headers=headers,
    )).json()["id"]
    for state in ("submitted", "approved", "fulfilled"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=headers,
        )
        assert r.status_code == 200, r.text
    return rid, env


@pytest.mark.asyncio
async def test_pack_is_refused_before_fulfilment(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]

    early = await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )
    assert early.status_code == 409, early.text


@pytest.mark.asyncio
async def test_pack_carries_the_environment_and_its_team(
    client, auth_headers, db_session, test_tenant
):
    rid, env = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )
    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()

    assert pack["environment"]["name"] == env.name
    assert pack["access"]["access_url"] == "https://sit.example.com"
    # The member list travels WITH the response. Resolving it in the browser
    # against /tenant/users/lite — which is capped — is the `.find()`-into-a-
    # capped-collection failure that renders a miss as '—'.
    assert "ops-ada" in pack["support"]["operations_group_members"]


@pytest.mark.asyncio
async def test_unfilled_fields_read_as_not_provided(
    client, auth_headers, db_session, test_tenant
):
    """An empty section reads as 'there is nothing to do'. Absent data and
    checked-and-found-nothing must not be indistinguishable."""
    rid, _ = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )
    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()

    assert pack["support"]["sla_notes"] == "Not provided"
    assert pack["caveats"]["known_limitations"] == "Not provided"
    assert pack["offboarding"]["decommission_notes"] == "Not provided"


@pytest.mark.asyncio
async def test_pack_reads_live_from_the_environment(
    client, auth_headers, db_session, test_tenant
):
    """Nothing is frozen at fulfilment — a changed URL updates every pack."""
    rid, env = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )
    await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://moved.example.com"}, headers=auth_headers,
    )

    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()
    assert pack["access"]["access_url"] == "https://moved.example.com"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_welcome_pack.py -q -p no:logging`
Expected: FAIL — 404 on `/welcome-pack`.

- [ ] **Step 3: Add the schema**

Append to `backend/app/api/v1/schemas/environment_request.py`:

```python
NOT_PROVIDED = "Not provided"


class WelcomePackResponse(BaseModel):
    """Rendered live from the environment; stored nowhere.

    Every free-text field falls back to "Not provided" rather than null or an
    empty string. A blank "How to connect" section reads as "there is nothing
    to do", which is the absent-versus-checked-and-empty confusion this
    codebase has been burned by before.
    """

    environment: dict
    access: dict
    support: dict
    caveats: dict
    offboarding: dict
    context: dict
```

- [ ] **Step 4: Build the pack**

Append to `backend/app/services/environment_request_service.py`:

```python
from app.api.v1.schemas.environment_request import NOT_PROVIDED, WelcomePackResponse


def _or_not_provided(value: Optional[str]) -> str:
    return value if (value and value.strip()) else NOT_PROVIDED


async def build_welcome_pack(
    db: AsyncSession, request_id: int, tenant_id: int
) -> WelcomePackResponse:
    view = await get_request_view(db, request_id, tenant_id)
    req = view.request
    if req.status != "fulfilled":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The welcome pack is available once the request has been fulfilled",
        )

    # Both modes resolve here with no special case at the call site.
    env_id = req.environment_id or req.created_environment_id
    env = (
        await db.execute(
            select(Environment).where(
                Environment.id == env_id, Environment.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    tier_name = (
        await db.execute(
            select(EnvironmentTier.name).where(EnvironmentTier.id == env.tier_id)
        )
    ).scalar_one_or_none()
    owner = (
        await db.execute(select(User.username).where(User.id == env.owner_user_id))
    ).scalar_one_or_none()

    group_name = None
    members: list[str] = []
    if env.operations_group_id is not None:
        group_name = (
            await db.execute(
                select(UserGroup.name).where(UserGroup.id == env.operations_group_id)
            )
        ).scalar_one_or_none()
        members = list(
            (
                await db.execute(
                    select(User.username)
                    .join(UserGroupMember, UserGroupMember.user_id == User.id)
                    .where(
                        UserGroupMember.group_id == env.operations_group_id,
                        UserGroupMember.tenant_id == tenant_id,
                    )
                    .order_by(User.username)
                )
            ).scalars().all()
        )

    return WelcomePackResponse(
        environment={
            "id": env.id,
            "name": env.name,
            "tier": tier_name,
            "status": env.status.value if hasattr(env.status, "value") else env.status,
            "owner": owner or NOT_PROVIDED,
            "expires_at": env.expires_at.isoformat() if env.expires_at else None,
        },
        access={
            "access_url": _or_not_provided(env.access_url),
            "connection_notes": _or_not_provided(env.connection_notes),
            "support_contact": _or_not_provided(env.support_contact),
        },
        support={
            "sla_notes": _or_not_provided(env.sla_notes),
            "operations_group": group_name or NOT_PROVIDED,
            "operations_group_members": members,
        },
        caveats={"known_limitations": _or_not_provided(env.known_limitations)},
        offboarding={"decommission_notes": _or_not_provided(env.decommission_notes)},
        context={
            "requested_by": view.requester_username,
            "justification": req.justification,
            "kind": req.kind,
        },
    )
```

- [ ] **Step 5: Add the endpoint**

Append to `backend/app/api/v1/environment_requests.py`:

```python
@router.get("/{request_id}/welcome-pack", response_model=WelcomePackResponse)
async def get_welcome_pack(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_request_service.build_welcome_pack(
        db, request_id, current_user.active_tenant_id
    )
```

- [ ] **Step 6: Run the tests, then commit**

Run: `cd backend && uv run pytest tests/integration/test_welcome_pack.py -q -p no:logging`
Expected: PASS, 4 passed

Run both engines, then:

```bash
git add backend/app/services/environment_request_service.py \
        backend/app/api/v1/environment_requests.py \
        backend/app/api/v1/schemas/environment_request.py \
        backend/tests/integration/test_welcome_pack.py
git commit -m "feat(requests): welcome pack rendered live from the environment"
```

---

### Task 9: Frontend types, service and slice

**Files:**
- Create: `frontend/src/types/environmentRequest.ts`, `frontend/src/services/environmentRequestService.ts`, `frontend/src/store/environmentRequestSlice.ts`, `frontend/src/store/__tests__/environmentRequestSlice.test.ts`
- Modify: `frontend/src/store/index.ts`, `frontend/src/types/environment.ts`

**Interfaces:**
- Consumes: the API from Tasks 3–8.
- Produces: `environmentRequestService` (`listRequests`, `createRequest`, `getRequest`, `updateRequest`, `transition`, `allowedTransitions`, `getWelcomePack`, `updateHandover`); thunks `fetchEnvironmentRequests`, `createEnvironmentRequest`, `updateEnvironmentRequest`, `transitionEnvironmentRequest`, `fetchWelcomePack`, `updateEnvironmentHandover`; state at `state.environmentRequest` with `{ requests, total, current, allowedTransitions, welcomePack, loading, error }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/store/__tests__/environmentRequestSlice.test.ts`:

```typescript
import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import environmentRequestReducer, {
  fetchEnvironmentRequests,
  transitionEnvironmentRequest,
} from '../environmentRequestSlice';
import { environmentRequestService } from '../../services/environmentRequestService';

vi.mock('../../services/environmentRequestService', () => ({
  environmentRequestService: {
    listRequests: vi.fn(),
    transition: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { environmentRequest: environmentRequestReducer } });
}

describe('environmentRequestSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores the server total, not the row count', async () => {
    vi.mocked(environmentRequestService.listRequests).mockResolvedValue({
      rows: [{ id: 1 }] as never,
      total: 42,
    });

    const store = makeStore();
    await store.dispatch(fetchEnvironmentRequests({}));

    expect(store.getState().environmentRequest.requests).toHaveLength(1);
    expect(store.getState().environmentRequest.total).toBe(42);
  });

  it('surfaces the server reason when a transition is refused', async () => {
    // AxiosError SHAPE: generic text on .message, the real reason only at
    // response.data.detail. A plain Error carrying the final text would pass
    // against broken code, because miniSerializeError keeps .message.
    vi.mocked(environmentRequestService.transition).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 403',
      response: {
        status: 403,
        data: {
          detail:
            'Only the operating team for this environment, or an admin, can action this request',
        },
      },
    });

    const store = makeStore();
    const result = await store.dispatch(
      transitionEnvironmentRequest({ id: 1, toState: 'approved' })
    );

    expect(transitionEnvironmentRequest.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('operating team');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/store/__tests__/environmentRequestSlice.test.ts`
Expected: FAIL — cannot resolve `../environmentRequestSlice`

- [ ] **Step 3: Write the types**

Create `frontend/src/types/environmentRequest.ts`:

```typescript
export type EnvironmentRequestKind = 'access' | 'new_environment';

export interface EnvironmentRequestResponse {
  id: number;
  tenant_id: number;
  kind: EnvironmentRequestKind;
  status: string;
  lifecycle_id: number;
  requested_by: number;
  /** Travels with the row — never resolved against a capped collection. */
  requester_username: string | null;
  justification: string;
  needed_by: string | null;
  environment_id: number | null;
  environment_name: string | null;
  proposed_name: string | null;
  tier_id: number | null;
  tier_name: string | null;
  expires_at: string | null;
  operations_group_id: number | null;
  operations_group_name: string | null;
  created_environment_id: number | null;
  custom_fields: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface EnvironmentRequestCreate {
  kind: EnvironmentRequestKind;
  justification: string;
  needed_by?: string | null;
  environment_id?: number | null;
  proposed_name?: string | null;
  tier_id?: number | null;
  expires_at?: string | null;
}

export interface EnvironmentRequestUpdate {
  justification?: string;
  needed_by?: string | null;
  environment_id?: number | null;
  proposed_name?: string | null;
  tier_id?: number | null;
  expires_at?: string | null;
  operations_group_id?: number | null;
}

export interface AllowedTransition {
  from_state: string;
  to_state: string;
  label: string;
  allowed_roles: string[];
}

export interface WelcomePack {
  environment: Record<string, unknown>;
  access: Record<string, string>;
  support: { sla_notes: string; operations_group: string; operations_group_members: string[] };
  caveats: { known_limitations: string };
  offboarding: { decommission_notes: string };
  context: Record<string, unknown>;
}

export interface EnvironmentHandoverUpdate {
  access_url?: string | null;
  connection_notes?: string | null;
  support_contact?: string | null;
  sla_notes?: string | null;
  known_limitations?: string | null;
  decommission_notes?: string | null;
}
```

Add the six handover fields to the environment response interface in `frontend/src/types/environment.ts` as `string | null` — required, not optional, since the backend always emits them.

- [ ] **Step 4: Write the service**

Create `frontend/src/services/environmentRequestService.ts`, following `frontend/src/services/userGroupService.ts` exactly for the `Paged<T>` / `x-total-count` shape:

```typescript
import api from './api';
import type {
  AllowedTransition,
  EnvironmentHandoverUpdate,
  EnvironmentRequestCreate,
  EnvironmentRequestResponse,
  EnvironmentRequestUpdate,
  WelcomePack,
} from '../types/environmentRequest';
import type { EnvironmentResponse } from '../types/environment';
import type { Paged } from '../types/pagination';

export const environmentRequestService = {
  listRequests: (params?: {
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
    status?: string;
    kind?: string;
    environment_id?: number;
    mine?: boolean;
    actionable?: boolean;
  }): Promise<Paged<EnvironmentRequestResponse>> =>
    api.get<EnvironmentRequestResponse[]>('/environment-requests', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  getRequest: (id: number): Promise<EnvironmentRequestResponse> =>
    api.get(`/environment-requests/${id}`).then((r) => r.data),

  createRequest: (data: EnvironmentRequestCreate): Promise<EnvironmentRequestResponse> =>
    api.post('/environment-requests', data).then((r) => r.data),

  updateRequest: (
    id: number,
    data: EnvironmentRequestUpdate
  ): Promise<EnvironmentRequestResponse> =>
    api.patch(`/environment-requests/${id}`, data).then((r) => r.data),

  transition: (
    id: number,
    toState: string,
    notes?: string
  ): Promise<EnvironmentRequestResponse> =>
    api
      .post(`/environment-requests/${id}/transition`, { to_state: toState, notes })
      .then((r) => r.data),

  allowedTransitions: (id: number): Promise<AllowedTransition[]> =>
    api.get(`/environment-requests/${id}/allowed-transitions`).then((r) => r.data),

  getWelcomePack: (id: number): Promise<WelcomePack> =>
    api.get(`/environment-requests/${id}/welcome-pack`).then((r) => r.data),

  updateHandover: (
    environmentId: number,
    data: EnvironmentHandoverUpdate
  ): Promise<EnvironmentResponse> =>
    api.patch(`/environments/${environmentId}/handover`, data).then((r) => r.data),
};
```

- [ ] **Step 5: Write the slice**

Create `frontend/src/store/environmentRequestSlice.ts`:

```typescript
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { environmentRequestService } from '../services/environmentRequestService';
import { formatApiError } from '../services/apiError';
import type { EnvironmentResponse } from '../types/environment';
import type {
  AllowedTransition,
  EnvironmentHandoverUpdate,
  EnvironmentRequestCreate,
  EnvironmentRequestResponse,
  EnvironmentRequestUpdate,
  WelcomePack,
} from '../types/environmentRequest';

interface EnvironmentRequestState {
  requests: EnvironmentRequestResponse[];
  total: number;
  current: EnvironmentRequestResponse | null;
  allowedTransitions: AllowedTransition[];
  welcomePack: WelcomePack | null;
  loading: boolean;
  error: string | null;
}

const initialState: EnvironmentRequestState = {
  requests: [], total: 0, current: null, allowedTransitions: [],
  welcomePack: null, loading: false, error: null,
};

// Every thunk rejects with rejectWithValue(formatApiError(...)). Redux
// Toolkit's default miniSerializeError copies only name/message/stack/code, so
// response.data.detail — where this backend puts every 403 and 409 explanation
// — is discarded, and a real AxiosError's .message is the generic "Request
// failed with status code 403". Consumers read result.payload.

type Params = Parameters<typeof environmentRequestService.listRequests>[0];

export const fetchEnvironmentRequests = createAsyncThunk<
  { rows: EnvironmentRequestResponse[]; total: number }, Params, { rejectValue: string }
>('environmentRequest/fetchAll', async (params, { rejectWithValue }) => {
  try {
    return await environmentRequestService.listRequests(params);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load requests'));
  }
});

export const fetchEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse, number, { rejectValue: string }
>('environmentRequest/fetchOne', async (id, { rejectWithValue }) => {
  try {
    return await environmentRequestService.getRequest(id);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the request'));
  }
});

export const createEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse, EnvironmentRequestCreate, { rejectValue: string }
>('environmentRequest/create', async (data, { rejectWithValue }) => {
  try {
    return await environmentRequestService.createRequest(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create the request'));
  }
});

export const updateEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse,
  { id: number; data: EnvironmentRequestUpdate },
  { rejectValue: string }
>('environmentRequest/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await environmentRequestService.updateRequest(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update the request'));
  }
});

export const transitionEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse,
  { id: number; toState: string; notes?: string },
  { rejectValue: string }
>('environmentRequest/transition', async ({ id, toState, notes }, { rejectWithValue }) => {
  try {
    return await environmentRequestService.transition(id, toState, notes);
  } catch (err) {
    // The 403 here names WHY — "only the operating team ... can action this
    // request". Losing it leaves the user reading an HTTP status.
    return rejectWithValue(formatApiError(err, 'Failed to update the request state'));
  }
});

export const fetchAllowedTransitions = createAsyncThunk<
  AllowedTransition[], number, { rejectValue: string }
>('environmentRequest/allowedTransitions', async (id, { rejectWithValue }) => {
  try {
    return await environmentRequestService.allowedTransitions(id);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load available actions'));
  }
});

export const fetchWelcomePack = createAsyncThunk<
  WelcomePack, number, { rejectValue: string }
>('environmentRequest/welcomePack', async (id, { rejectWithValue }) => {
  try {
    return await environmentRequestService.getWelcomePack(id);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the welcome pack'));
  }
});

export const updateEnvironmentHandover = createAsyncThunk<
  EnvironmentResponse,
  { environmentId: number; data: EnvironmentHandoverUpdate },
  { rejectValue: string }
>('environmentRequest/handover', async ({ environmentId, data }, { rejectWithValue }) => {
  try {
    return await environmentRequestService.updateHandover(environmentId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to save the handover details'));
  }
});

const environmentRequestSlice = createSlice({
  name: 'environmentRequest',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchEnvironmentRequests.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchEnvironmentRequests.fulfilled, (state, action) => {
        state.loading = false;
        state.error = null;
        state.requests = action.payload.rows;
        // The server total, never rows.length — a page's length is not the set.
        state.total = action.payload.total;
      })
      .addCase(fetchEnvironmentRequests.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load requests';
      })
      .addCase(fetchEnvironmentRequest.fulfilled, (state, action) => {
        state.current = action.payload;
        state.error = null;
      })
      .addCase(fetchEnvironmentRequest.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load the request';
      })
      .addCase(transitionEnvironmentRequest.fulfilled, (state, action) => {
        // The detail page's own record, not the list — see the note below.
        state.current = action.payload;
      })
      .addCase(fetchAllowedTransitions.fulfilled, (state, action) => {
        state.allowedTransitions = action.payload;
      })
      .addCase(fetchWelcomePack.fulfilled, (state, action) => {
        state.welcomePack = action.payload;
        state.error = null;
      })
      .addCase(fetchWelcomePack.rejected, (state, action) => {
        state.welcomePack = null;
        state.error = action.payload ?? 'Failed to load the welcome pack';
      });
    // Deliberately NO fulfilled handler splicing `requests` for create, update
    // or transition: the list is one server-paged window, and local surgery
    // desynchronises the page from its total once a second page exists. The
    // pages re-dispatch fetchEnvironmentRequests instead.
  },
});

export default environmentRequestSlice.reducer;
```

- [ ] **Step 6: Register the reducer, run the test, typecheck**

Add `environmentRequest: environmentRequestReducer` to `frontend/src/store/index.ts`.

Run: `cd frontend && npx vitest run src/store/__tests__/environmentRequestSlice.test.ts && npx tsc --noEmit`
Expected: 2 passed; tsc clean.

Adding six required fields to the environment response type may break existing fixtures. Add `null` for each in any fixture that fails to typecheck — do not make the fields optional, which would make the type lie about the wire contract.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/environmentRequest.ts frontend/src/types/environment.ts \
        frontend/src/services/environmentRequestService.ts \
        frontend/src/store/environmentRequestSlice.ts frontend/src/store/index.ts \
        frontend/src/store/__tests__/environmentRequestSlice.test.ts
git commit -m "feat(requests): frontend types, service and Redux slice"
```

---

### Task 10: Request list and form

**Files:**
- Create: `frontend/src/pages/environments/EnvironmentRequestList.tsx`, `EnvironmentRequestForm.tsx`, and `__tests__/environmentRequestList.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/navConfig.tsx`

**Interfaces:**
- Consumes: the slice from Task 9.
- Produces: routes `/environment-requests` and `/environment-requests/new`; exported `environmentRequestColumns`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/environments/__tests__/environmentRequestList.test.tsx`, following `frontend/src/pages/admin/__tests__/userGroups.test.tsx` for the store/router/DataGrid-mock setup. It must cover:

```tsx
  it('marks every column the backend cannot sort as unsortable', () => {
    // The whitelist is status, kind, needed_by, created_at. environment_name,
    // requester_username and proposed_name are joined or mode-dependent
    // columns the backend does not sort — a sortable header 422s on click.
    const sortable = new Set(['status', 'kind', 'needed_by', 'created_at']);
    environmentRequestColumns.forEach((col) => {
      if (col.sortable !== false) {
        expect(sortable.has(col.field)).toBe(true);
      }
    });
  });

  it('shows the target for both kinds in one column', async () => {
    // An access request shows the environment; a new-environment request shows
    // the proposed name. A single "Target" column with a mode-aware
    // valueGetter, so the grid does not need two half-empty columns.
    renderList();
    await waitFor(() => expect(screen.getByText('Mortgage SIT')).toBeInTheDocument());
    expect(screen.getByText('Mortgage PERF (new)')).toBeInTheDocument();
  });

  it('the For my team chip sends actionable=true', async () => {
    renderList();
    await userEvent.click(screen.getByRole('button', { name: /for my team/i }));
    await waitFor(() =>
      expect(environmentRequestService.listRequests).toHaveBeenCalledWith(
        expect.objectContaining({ actionable: true })
      )
    );
  });
```

Mock `environmentRequestService.listRequests` to return one request of each kind.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/pages/environments/__tests__/environmentRequestList.test.tsx`
Expected: FAIL — cannot resolve `../EnvironmentRequestList`

- [ ] **Step 3: Write the list page**

Create `frontend/src/pages/environments/EnvironmentRequestList.tsx`. Model it on `frontend/src/pages/environments/EnvironmentList.tsx` for `useServerGrid` usage and on `frontend/src/pages/admin/UserGroups.tsx` for the dialog and error handling.

Export the columns at module level:

```tsx
// Sortable fields (whitelist-backed, see the backend's REQUEST_SORTS):
// status, kind, needed_by, created_at ONLY. `target` is computed from two
// columns, and requester_username is joined — neither is backed by a single
// column, so neither can be whitelisted. A sortable header on them 422s.
// eslint-disable-next-line react-refresh/only-export-components
export const environmentRequestColumns: GridColDef<EnvironmentRequestResponse>[] = [
  {
    field: 'target',
    headerName: 'Target',
    flex: 1,
    sortable: false,
    valueGetter: (params) =>
      params.row.kind === 'access'
        ? (params.row.environment_name ?? '—')
        : `${params.row.proposed_name ?? '—'} (new)`,
  },
  { field: 'kind', headerName: 'Kind', width: 150 },
  { field: 'requester_username', headerName: 'Requested by', width: 160, sortable: false },
  { field: 'status', headerName: 'Status', width: 130 },
  { field: 'needed_by', headerName: 'Needed by', width: 140 },
];
```

Filter chips **All / Mine / For my team** map to no filter, `mine=true` and `actionable=true`. Route them through `useServerGrid`'s `filterKeys` so they round-trip through the URL. Note the `'all'` sentinel hazard recorded in `docs/pagination.md`: `buildParams` drops a filter whose value is `all`, so if you spell the "no filter" state `all` in the URL, both states build identical params and the grid never refetches. Spell it `any` in the URL and restore at the fetch boundary, as `ScopeWindowsTable` does.

Add `disableColumnFilter` if you use a raw `DataGrid`.

- [ ] **Step 4: Write the form**

Create `frontend/src/pages/environments/EnvironmentRequestForm.tsx`: a mode toggle (Access / New environment) driving which fields render.

- Access: an Environment select sourced from a full environment fetch, plus Justification.
- New environment: Proposed name, Tier select, Expiry, plus Justification.
- Validation mirrors the service's: the submit button stays disabled until the mode's required fields are present, and a rejected create surfaces `result.payload`.

- [ ] **Step 5: Wire routes and nav**

`frontend/src/App.tsx`: `/environment-requests` → list, `/environment-requests/new` → form, `/environment-requests/:id` → detail (Task 11). Match how the neighbouring environment routes are imported (lazy or not).

`frontend/src/components/navConfig.tsx`: an **Environment Requests** entry under Environment Management.

- [ ] **Step 6: Run tests, typecheck, lint, then commit**

Run: `cd frontend && npx vitest run src/pages/environments && npx tsc --noEmit && npm run lint`

```bash
git add frontend/src/pages/environments/EnvironmentRequestList.tsx \
        frontend/src/pages/environments/EnvironmentRequestForm.tsx \
        frontend/src/pages/environments/__tests__/environmentRequestList.test.tsx \
        frontend/src/App.tsx frontend/src/components/navConfig.tsx
git commit -m "feat(requests): request list with team queue, and the two-mode form"
```

---

### Task 11: Detail page, Welcome Pack and Handover section

**Files:**
- Create: `frontend/src/pages/environments/EnvironmentRequestDetail.tsx`, `frontend/src/components/environments/WelcomePack.tsx`, `frontend/src/components/environments/HandoverSection.tsx`, and `__tests__` for each
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

**Interfaces:**
- Consumes: the slice from Task 9.
- Produces: nothing downstream.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/environments/__tests__/environmentRequestDetail.test.tsx` covering:

```tsx
  it('renders only the transitions this actor may actually make', async () => {
    // The backend already applies BOTH the role and the group check to
    // /allowed-transitions. The page renders exactly what it returns — it must
    // not render every transition disabled, which tells the user nothing about
    // why, and must not compute its own list, which would drift from the rule.
    vi.mocked(environmentRequestService.allowedTransitions).mockResolvedValue([
      { from_state: 'submitted', to_state: 'approved', label: 'Approve', allowed_roles: [] },
    ]);
    renderDetail();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();
  });

  it('surfaces the server reason when a transition is refused', async () => {
    vi.mocked(environmentRequestService.transition).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 403',
      response: { status: 403, data: { detail: 'Only the operating team ... can action this request' } },
    });
    renderDetail();
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(screen.getByText(/Only the operating team/)).toBeInTheDocument());
    expect(screen.queryByText(/request failed with status code/i)).not.toBeInTheDocument();
  });

  it('shows the welcome pack only once the request is fulfilled', async () => { /* ... */ });
```

Create `frontend/src/components/environments/__tests__/handoverSection.test.tsx` covering:

```tsx
  it('is editable for a member of the operating team who is not an admin', () => { /* ... */ });
  it('is read-only for someone outside the team', () => { /* ... */ });
  it('sends only handover keys', async () => {
    // The endpoint rejects anything else with a 422; the UI must not send
    // tier_id or owner_user_id even accidentally.
  });
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/pages/environments/__tests__/environmentRequestDetail.test.tsx src/components/environments/__tests__/handoverSection.test.tsx`
Expected: FAIL — modules do not resolve.

- [ ] **Step 3: Write the detail page**

Create `frontend/src/pages/environments/EnvironmentRequestDetail.tsx`:

- Dispatch `fetchEnvironmentRequest(id)` and `fetchAllowedTransitions(id)` on mount.
- Render the request's fields, mode-aware (target environment or proposed name/tier/expiry).
- Render one button per allowed transition, labelled from the transition's `label`. On rejection, show `result.payload` in an `Alert severity="error"`. On success, re-dispatch both fetches — the allowed set changes with the state.
- When `status === 'fulfilled'`, render `<WelcomePack requestId={id} />`.
- For a new-environment request in `submitted`, render an **Operations Group** select (Admin only) that PATCHes `operations_group_id` — without it an Admin cannot fulfil, since fulfilment 409s with no team.

- [ ] **Step 4: Write the Welcome Pack component**

Create `frontend/src/components/environments/WelcomePack.tsx`: dispatch `fetchWelcomePack(requestId)` on mount and render the six sections — Environment, How to connect, Support, Known limitations, Offboarding, Context.

The backend already substitutes `"Not provided"`, so render values verbatim. **Do not** add a falsy check that hides a section — an omitted "How to connect" heading reads as "there is nothing to do", which is the failure the backend's fallback exists to prevent.

Render `support.operations_group_members` from the response array. Do not fetch `/tenant/users/lite` to resolve names.

- [ ] **Step 5: Write the Handover section**

Create `frontend/src/components/environments/HandoverSection.tsx`, taking the environment and rendering the six fields.

```tsx
// Editable by the operating team as well as Admins — deliberately different
// from the Governance section on the same page, which is Admin-only. A member
// of the operating team sees Governance read-only and Handover editable, and
// that asymmetry is the feature working. Label it so it reads as deliberate.
const canEditHandover =
  user?.role === 'Admin' ||
  user?.is_master_admin === true ||
  operationsGroupMemberIds.includes(user?.id ?? -1);
```

Membership is not currently on the frontend's user object. Fetch the environment's group members via `userGroupService.listMembers(environment.operations_group_id)` when the id is present, and derive `canEditHandover` from that. If the fetch fails, fall back to Admin-only rather than to editable.

On save, dispatch `updateEnvironmentHandover({environmentId, data})` with only the six keys, and surface `result.payload` on rejection.

Mount it in `frontend/src/pages/environments/EnvironmentDetail.tsx` below the Governance section.

- [ ] **Step 6: Run the full frontend suite, typecheck, lint**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all pass.

- [ ] **Step 7: Open the pages**

Six defects in the pagination programme, and three more across B3a, were found only by opening the page with a fully green suite. Do this before claiming the task done.

With the stack running and logged in as `admin` / `admin123` on tenant `demo`:

1. Create a user group, add yourself, assign it as an environment's operations group.
2. `/environment-requests/new` — raise an access request against that environment. Submit it.
3. Raise a second access request against an environment with **no** operations group — submission must be refused with a message naming the environment.
4. `/environment-requests` — the **For my team** chip; confirm the URL carries the filter across a reload.
5. Approve then fulfil the first request; confirm the Welcome Pack appears and shows "Not provided" for fields nobody filled in.
6. On the environment's detail page, fill in the handover fields, then re-open the pack — the values must update, since it renders live.
7. Raise a new-environment request, approve it, set the operations group, fulfil it; confirm the created environment appears with status **inactive** and the group set.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentRequestDetail.tsx \
        frontend/src/components/environments/WelcomePack.tsx \
        frontend/src/components/environments/HandoverSection.tsx \
        frontend/src/pages/environments/EnvironmentDetail.tsx \
        frontend/src/pages/environments/__tests__/environmentRequestDetail.test.tsx \
        frontend/src/components/environments/__tests__/handoverSection.test.tsx
git commit -m "feat(requests): request detail, welcome pack and the handover section"
```

---

## Final verification

- [ ] **Backend, both engines**

`cd backend && uv run pytest -q -p no:logging`, then the PostgreSQL leg. Expected: PASS.

- [ ] **Frontend**

`cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`. Expected: all PASS.

- [ ] **Update the docs**

- `docs/phases/phase-7.md` — mark B3b shipped under the B3a/B3b split B3a introduced.
- `docs/pagination.md` — add `GET /environment-requests` to the bounded-endpoints table.
- `docs/admin-guide.md` — the request workflow, who can action what, and the handover fields.
- `docs/user-guide.md` — how to raise a request and read a Welcome Pack.

- [ ] **Open a PR**

```bash
git push -u github feature/environment-requests
gh pr create --repo pjgross/envmgr --base main \
  --title "Phase 7 B3b: environment request form + welcome pack"
```

The body should state that this completes B3, that access requests are a paperwork and audit trail rather than an access-control mechanism, and that credentials are deliberately excluded from the pack.
