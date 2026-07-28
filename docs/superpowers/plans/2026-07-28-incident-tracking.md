# Incident Tracking (Phase 5 SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a first-class, lifecycle-driven, custom-field-capable, ITSM-import-ready `Incident` entity linked to causal/fix releases and the failed system/subsystem, with CRUD + transition API and List/Form/Detail UI.

**Architecture:** Incident plugs into the existing generic `LifecycleTemplate` state-machine framework and `CustomFieldDefinition` framework as `entity_type="incident"` (exactly as `Release` does), reusing `lifecycle_service` and `custom_field_service`. Backend is thin API → `incident_service` → SQLAlchemy; frontend follows the established service/slice/page pattern.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + PostgreSQL/SQLite-test; React 18 + TypeScript strict + MUI + Redux Toolkit; pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-07-28-incident-tracking-design.md`

---

## Reference facts (verified against the codebase)

- **Roles** (`app/core/security.py`): `Admin`, `Release Manager`, `Test Manager`, `Developer`, `Viewer`. `current_user.role` is the role string. Any authenticated tenant user may CRUD/transition incidents → every incident transition lists all five roles in `allowed_roles`.
- **Lifecycle definition JSON** shape (from `app/services/release_defaults.py`): `{states:[{key,label,is_initial,is_terminal,...}], transitions:[{from_state,to_state,label,allowed_roles}], field_permissions:{<state>:{standard_fields:{...},custom_fields:{},required_fields:[...]}}}`. A custom per-state flag (e.g. `is_resolved: true`) is allowed — the service ignores unknown state keys.
- **`lifecycle_service`**: `validate_transition(definition, from_state, to_state, user_role, record_values=None) -> (ok, reason)`; `get_allowed_transitions(definition, current_state, user_role) -> list[dict]`; template CRUD/copy funcs.
- **`custom_field_service.validate_custom_fields(db, tenant_id, entity_type, values, visible_field_keys=None)`** raises HTTP 422 on bad/missing.
- **Seeding**: `app/services/tenant_service.create_tenant()` calls `seed_release_defaults_for_tenant`, `change_request_service.seed_default_lifecycles`, etc. Add `seed_incident_defaults_for_tenant` there.
- **FK targets**: `environment`, `deployment`, `release` (causal + fix), `system`, `subsystem`. `ReleaseChange.epic_id` groups the fix-release panel.
- **Convention**: enum cols use `native_enum=False`; migrations are **manual DDL** (`op.create_table`); services use `db.flush()` not `commit()`; every tenant-scoped query filters `current_user.active_tenant_id`; validate FK ownership to prevent IDOR.
- All `npx` commands run from `frontend/`; all `pytest`/`alembic`/`uv` commands from `backend/`.

---

## File Structure

**Backend — create:**
- `app/db/models/incident.py` — `Incident`, `IncidentStatusHistory`
- `app/services/incident_defaults.py` — default `incident` lifecycle template + seed
- `app/schemas/incident.py` — request/response schemas
- `app/services/incident_service.py` — business logic
- `app/api/v1/incidents.py` — endpoints
- `alembic/versions/<rev>_incident_tables.py` — migration
- tests: `tests/services/test_incident_service.py`, `tests/services/test_incident_transition.py`, `tests/integration/test_incidents_api.py`, `tests/integration/test_incident_tenant_isolation.py`

**Backend — modify:**
- `app/db/models/__init__.py` — export the models
- `app/services/tenant_service.py` — call the incident seed
- `app/main.py` (or router aggregator) — mount the incidents router

**Frontend — create:**
- `src/types/incident.ts`, `src/services/incidentService.ts`, `src/store/incidentSlice.ts`
- `src/utils/incidentSeverity.ts`
- `src/pages/incidents/IncidentList.tsx`, `IncidentForm.tsx`, `IncidentDetail.tsx`
- test: `src/store/__tests__/incidentSlice.test.ts`

**Frontend — modify:**
- `src/store/index.ts` (register reducer), router config, nav menu, tenant-admin entity-type lists (add `incident`).

---

## Task 1: Incident models + migration

**Files:**
- Create: `backend/app/db/models/incident.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: `backend/alembic/versions/<rev>_incident_tables.py`

- [ ] **Step 1: Write the models**

`backend/app/db/models/incident.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Incident(Base):
    __tablename__ = "incident"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(2), nullable=False)  # P1|P2|P3|P4

    lifecycle_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # current lifecycle state

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    environment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("environment.id"), nullable=True)
    deployment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("deployment.id"), nullable=True)
    release_id: Mapped[Optional[int]] = mapped_column(ForeignKey("release.id"), nullable=True)       # causal
    fix_release_id: Mapped[Optional[int]] = mapped_column(ForeignKey("release.id"), nullable=True)   # fix
    system_id: Mapped[Optional[int]] = mapped_column(ForeignKey("system.id"), nullable=True)
    subsystem_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subsystem.id"), nullable=True)

    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    external_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_incident_tenant_status", "tenant_id", "status"),
        Index("ix_incident_tenant_release", "tenant_id", "release_id"),
        Index("ix_incident_tenant_system", "tenant_id", "system_id"),
        Index("ix_incident_tenant_source_ref", "tenant_id", "source", "external_ref"),
    )


class IncidentStatusHistory(Base):
    __tablename__ = "incident_status_history"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incident.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 2: Register models** in `backend/app/db/models/__init__.py` — add alongside the existing imports:

```python
from app.db.models.incident import Incident, IncidentStatusHistory  # noqa: F401
```

(Match the file's existing import/`__all__` style; if it has an `__all__`, add `"Incident"`, `"IncidentStatusHistory"`.)

- [ ] **Step 3: Create the migration**

Run: `alembic revision -m "incident tables"` then replace the generated `upgrade`/`downgrade` with manual DDL:

```python
def upgrade() -> None:
    op.create_table(
        "incident",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=2), nullable=False),
        sa.Column("lifecycle_template_id", sa.Integer(), sa.ForeignKey("lifecycle_template.id"), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=True),
        sa.Column("deployment_id", sa.Integer(), sa.ForeignKey("deployment.id"), nullable=True),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=True),
        sa.Column("fix_release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=True),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=True),
        sa.Column("subsystem_id", sa.Integer(), sa.ForeignKey("subsystem.id"), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("external_ref", sa.String(length=200), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_incident_tenant_id", "incident", ["tenant_id"])
    op.create_index("ix_incident_tenant_status", "incident", ["tenant_id", "status"])
    op.create_index("ix_incident_tenant_release", "incident", ["tenant_id", "release_id"])
    op.create_index("ix_incident_tenant_system", "incident", ["tenant_id", "system_id"])
    op.create_index("ix_incident_tenant_source_ref", "incident", ["tenant_id", "source", "external_ref"])
    op.create_table(
        "incident_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_state", sa.String(length=50), nullable=True),
        sa.Column("to_state", sa.String(length=50), nullable=False),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_incident_status_history_tenant_id", "incident_status_history", ["tenant_id"])
    op.create_index("ix_incident_status_history_incident_id", "incident_status_history", ["incident_id"])


def downgrade() -> None:
    op.drop_table("incident_status_history")
    op.drop_table("incident")
```

- [ ] **Step 4: Apply + verify**

Run: `alembic upgrade head`
Expected: completes without error.
Run: `python -c "from app.db.models import Incident, IncidentStatusHistory; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/incident.py backend/app/db/models/__init__.py backend/alembic/versions/
git commit -m "feat(incidents): Incident + IncidentStatusHistory models & migration (Phase 5 SP1)"
```

---

## Task 2: Default incident lifecycle template + tenant seeding (TDD)

**Files:**
- Create: `backend/app/services/incident_defaults.py`
- Modify: `backend/app/services/tenant_service.py`
- Test: `backend/tests/services/test_incident_defaults.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import select
from app.db.models.lifecycle import LifecycleTemplate
from app.services.incident_defaults import seed_incident_defaults_for_tenant


@pytest.mark.asyncio
async def test_seeds_default_incident_template(db_session, tenant):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "incident",
        )
    )).scalars().all()
    assert len(rows) == 1
    tpl = rows[0]
    assert tpl.is_default is True
    keys = {s["key"] for s in tpl.definition["states"]}
    assert {"new", "investigating", "identified", "fix_scheduled", "resolved", "closed", "cancelled"} <= keys
    initial = [s for s in tpl.definition["states"] if s.get("is_initial")]
    assert len(initial) == 1 and initial[0]["key"] == "new"
    resolved = [s for s in tpl.definition["states"] if s.get("is_resolved")]
    assert resolved and resolved[0]["key"] == "resolved"


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, tenant):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "incident",
        )
    )).scalars().all()
    assert len(rows) == 1
```

Use the existing test fixtures for `db_session` and `tenant` (copy the fixture usage from `tests/services/test_incident_service.py` siblings such as `tests/services/test_raid_config_service.py` — match how they obtain a tenant).

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/services/test_incident_defaults.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.incident_defaults`.

- [ ] **Step 3: Implement the seed**

`backend/app/services/incident_defaults.py`:

```python
"""Seed the default incident lifecycle template. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate

ALL_ROLES = ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]


def _t(frm: str, to: str, label: str) -> dict:
    return {"from_state": frm, "to_state": to, "label": label, "allowed_roles": ALL_ROLES}


_INCIDENT_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "new",           "label": "New",           "is_initial": True,  "is_terminal": False},
        {"key": "investigating", "label": "Investigating", "is_initial": False, "is_terminal": False},
        {"key": "identified",    "label": "Identified",    "is_initial": False, "is_terminal": False},
        {"key": "fix_scheduled", "label": "Fix Scheduled", "is_initial": False, "is_terminal": False},
        {"key": "resolved",      "label": "Resolved",      "is_initial": False, "is_terminal": False, "is_resolved": True},
        {"key": "closed",        "label": "Closed",        "is_initial": False, "is_terminal": True},
        {"key": "cancelled",     "label": "Cancelled",     "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        _t("new", "investigating", "Start Investigating"),
        _t("investigating", "identified", "Root Cause Identified"),
        _t("identified", "fix_scheduled", "Schedule Fix"),
        _t("fix_scheduled", "resolved", "Mark Resolved"),
        _t("identified", "resolved", "Mark Resolved"),
        _t("investigating", "resolved", "Mark Resolved"),
        _t("resolved", "closed", "Close"),
        _t("resolved", "investigating", "Reopen"),
        _t("new", "cancelled", "Cancel"),
        _t("investigating", "cancelled", "Cancel"),
        _t("identified", "cancelled", "Cancel"),
    ],
    "field_permissions": {
        s: {
            "standard_fields": {
                "title": {"editable_by": ALL_ROLES},
                "description": {"editable_by": ALL_ROLES},
                "severity": {"editable_by": ALL_ROLES},
            },
            "custom_fields": {},
        }
        for s in ("new", "investigating", "identified", "fix_scheduled", "resolved", "closed", "cancelled")
    },
}


async def seed_incident_defaults_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    existing = {
        r.name for r in (
            await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.entity_type == "incident",
                )
            )
        ).scalars().all()
    }
    if "Default Incident Lifecycle" in existing:
        return
    db.add(LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="incident",
        name="Default Incident Lifecycle",
        description="Default incident state machine",
        is_default=True,
        is_system=True,
        definition=_INCIDENT_DEFINITION,
    ))
```

- [ ] **Step 4: Wire into tenant creation** — in `backend/app/services/tenant_service.py`, import and call alongside the other seeds inside `create_tenant`:

```python
from app.services.incident_defaults import seed_incident_defaults_for_tenant
# ... inside create_tenant, after seed_release_defaults_for_tenant(...):
await seed_incident_defaults_for_tenant(db, tenant.id)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/services/test_incident_defaults.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/incident_defaults.py backend/app/services/tenant_service.py backend/tests/services/test_incident_defaults.py
git commit -m "feat(incidents): default incident lifecycle template + tenant seeding (Phase 5 SP1)"
```

---

## Task 3: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/incident.py`

- [ ] **Step 1: Write the schemas**

`backend/app/schemas/incident.py` (mirror the style of a sibling schema file such as `app/schemas/release.py` — `from_attributes = True` on response configs):

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

SEVERITIES = {"P1", "P2", "P3", "P4"}


class IncidentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str
    detected_at: Optional[datetime] = None          # defaults to now in the service
    environment_id: Optional[int] = None
    deployment_id: Optional[int] = None
    release_id: Optional[int] = None
    fix_release_id: Optional[int] = None
    system_id: Optional[int] = None
    subsystem_id: Optional[int] = None
    source: str = "manual"
    external_ref: Optional[str] = None
    lifecycle_template_id: Optional[int] = None
    custom_fields: Optional[dict] = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(SEVERITIES)}")
        return v


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    detected_at: Optional[datetime] = None
    environment_id: Optional[int] = None
    deployment_id: Optional[int] = None
    release_id: Optional[int] = None
    fix_release_id: Optional[int] = None
    system_id: Optional[int] = None
    subsystem_id: Optional[int] = None
    external_ref: Optional[str] = None
    custom_fields: Optional[dict] = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v):
        if v is not None and v not in SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(SEVERITIES)}")
        return v


class IncidentTransition(BaseModel):
    to_state: str


class ReleaseSummary(BaseModel):
    id: int
    name: str
    target_date: Optional[datetime] = None
    status: str
    model_config = ConfigDict(from_attributes=True)


class ReleaseChangeRow(BaseModel):
    id: int
    title: str
    epic_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class TransitionOption(BaseModel):
    to_state: str
    label: str


class StatusHistoryRow(BaseModel):
    from_state: Optional[str]
    to_state: str
    changed_by: Optional[int]
    changed_at: datetime
    model_config = ConfigDict(from_attributes=True)


class IncidentListRow(BaseModel):
    id: int
    title: str
    severity: str
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime]
    system_id: Optional[int]
    system_name: Optional[str] = None
    environment_id: Optional[int]
    environment_name: Optional[str] = None
    release_id: Optional[int]
    release_name: Optional[str] = None
    fix_release: Optional[ReleaseSummary] = None
    model_config = ConfigDict(from_attributes=True)


class IncidentDetail(BaseModel):
    id: int
    title: str
    description: Optional[str]
    severity: str
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime]
    source: str
    external_ref: Optional[str]
    environment_id: Optional[int]
    environment_name: Optional[str] = None
    deployment_id: Optional[int]
    release_id: Optional[int]
    release: Optional[ReleaseSummary] = None
    fix_release_id: Optional[int]
    fix_release: Optional[ReleaseSummary] = None
    fix_release_changes_by_epic: dict[str, list[ReleaseChangeRow]] = {}
    system_id: Optional[int]
    system_name: Optional[str] = None
    subsystem_id: Optional[int]
    subsystem_name: Optional[str] = None
    custom_fields: Optional[dict]
    allowed_transitions: list[TransitionOption] = []
    status_history: list[StatusHistoryRow] = []
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Verify it imports**

Run: `python -c "import app.schemas.incident; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/incident.py
git commit -m "feat(incidents): pydantic schemas (Phase 5 SP1)"
```

---

## Task 4: incident_service — create / get / list / update / delete (TDD)

**Files:**
- Create: `backend/app/services/incident_service.py`
- Test: `backend/tests/services/test_incident_service.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from datetime import datetime, timezone
from app.services import incident_service
from app.services.incident_defaults import seed_incident_defaults_for_tenant
from app.schemas.incident import IncidentCreate, IncidentUpdate


@pytest.mark.asyncio
async def test_create_resolves_default_template_and_initial_state(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="DB outage", severity="P1"), tenant.id, user.id
    )
    assert inc.status == "new"
    assert inc.lifecycle_template_id is not None
    assert inc.detected_at is not None
    hist = await incident_service.get_status_history(db_session, inc.id, tenant.id)
    assert len(hist) == 1 and hist[0].to_state == "new" and hist[0].from_state is None


@pytest.mark.asyncio
async def test_create_defaults_detected_at_to_now(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="x", severity="P3"), tenant.id, user.id
    )
    assert inc.detected_at is not None


@pytest.mark.asyncio
async def test_update_changes_fields_but_not_status(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="x", severity="P3"), tenant.id, user.id
    )
    updated = await incident_service.update_incident(
        db_session, inc.id, IncidentUpdate(title="y", severity="P2"), tenant.id
    )
    assert updated.title == "y" and updated.severity == "P2" and updated.status == "new"


@pytest.mark.asyncio
async def test_soft_delete_hides_from_list_and_get(db_session, tenant, user):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    inc = await incident_service.create_incident(
        db_session, IncidentCreate(title="x", severity="P3"), tenant.id, user.id
    )
    await incident_service.delete_incident(db_session, inc.id, tenant.id)
    assert await incident_service.get_incident(db_session, inc.id, tenant.id) is None
    rows = await incident_service.list_incidents(db_session, tenant.id, {})
    assert all(r.id != inc.id for r in rows)
```

Match the `db_session`/`tenant`/`user` fixtures used by existing `tests/services/*` files.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/services/test_incident_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.incident_service`.

- [ ] **Step 3: Implement the service (CRUD portion)**

`backend/app/services/incident_service.py`:

```python
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import Incident, IncidentStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.environment import Environment
from app.db.models.deployment import Deployment
from app.db.models.release import Release
from app.db.models.system import System, SubSystem
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.services import custom_field_service

_FK_MODELS = {
    "environment_id": Environment,
    "deployment_id": Deployment,
    "release_id": Release,
    "fix_release_id": Release,
    "system_id": System,
    "subsystem_id": SubSystem,
}


async def _validate_fk_tenant(db: AsyncSession, field: str, value: Optional[int], tenant_id: int) -> None:
    """Reject a FK that points at another tenant's row (IDOR guard)."""
    if value is None:
        return
    model = _FK_MODELS[field]
    row = (await db.execute(select(model).where(model.id == value))).scalar_one_or_none()
    if row is None or getattr(row, "tenant_id", None) != tenant_id or getattr(row, "deleted_at", None) is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"{field} does not reference a valid record for this tenant")


async def _resolve_template(db: AsyncSession, template_id: Optional[int], tenant_id: int) -> LifecycleTemplate:
    stmt = select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == tenant_id,
        LifecycleTemplate.entity_type == "incident",
        LifecycleTemplate.deleted_at.is_(None),
    )
    if template_id is not None:
        tpl = (await db.execute(stmt.where(LifecycleTemplate.id == template_id))).scalar_one_or_none()
        if tpl is None:
            raise HTTPException(status_code=422, detail="lifecycle_template_id must be an active incident template for this tenant")
        return tpl
    tpl = (await db.execute(stmt.where(LifecycleTemplate.is_default.is_(True)))).scalars().first()
    if tpl is None:
        raise HTTPException(status_code=422, detail="No default incident lifecycle template. Seed defaults for this tenant.")
    return tpl


def _initial_state(definition: dict) -> str:
    for s in definition.get("states", []):
        if s.get("is_initial"):
            return s["key"]
    raise HTTPException(status_code=500, detail="Incident lifecycle template has no initial state")


async def create_incident(db: AsyncSession, data: IncidentCreate, tenant_id: int, user_id: int) -> Incident:
    for field in _FK_MODELS:
        await _validate_fk_tenant(db, field, getattr(data, field), tenant_id)
    tpl = await _resolve_template(db, data.lifecycle_template_id, tenant_id)
    initial = _initial_state(tpl.definition)
    await custom_field_service.validate_custom_fields(db, tenant_id, "incident", data.custom_fields)

    now = datetime.now(timezone.utc)
    inc = Incident(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        severity=data.severity,
        lifecycle_template_id=tpl.id,
        status=initial,
        detected_at=data.detected_at or now,
        environment_id=data.environment_id,
        deployment_id=data.deployment_id,
        release_id=data.release_id,
        fix_release_id=data.fix_release_id,
        system_id=data.system_id,
        subsystem_id=data.subsystem_id,
        source=data.source,
        external_ref=data.external_ref,
        custom_fields=data.custom_fields,
    )
    db.add(inc)
    await db.flush()
    db.add(IncidentStatusHistory(
        tenant_id=tenant_id, incident_id=inc.id, from_state=None, to_state=initial,
        changed_by=user_id, changed_at=now,
    ))
    await db.flush()
    return inc


async def get_incident(db: AsyncSession, incident_id: int, tenant_id: int) -> Optional[Incident]:
    return (await db.execute(select(Incident).where(
        Incident.id == incident_id, Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None)
    ))).scalar_one_or_none()


async def list_incidents(db: AsyncSession, tenant_id: int, filters: dict) -> list[Incident]:
    conds = [Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None)]
    for f in ("status", "severity", "system_id", "environment_id", "release_id", "source"):
        if filters.get(f) not in (None, ""):
            conds.append(getattr(Incident, f) == filters[f])
    if filters.get("date_from"):
        conds.append(Incident.detected_at >= filters["date_from"])
    if filters.get("date_to"):
        conds.append(Incident.detected_at <= filters["date_to"])
    return list((await db.execute(
        select(Incident).where(and_(*conds)).order_by(Incident.detected_at.desc())
    )).scalars().all())


async def update_incident(db: AsyncSession, incident_id: int, data: IncidentUpdate, tenant_id: int) -> Incident:
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    payload = data.model_dump(exclude_unset=True)
    for field in _FK_MODELS:
        if field in payload:
            await _validate_fk_tenant(db, field, payload[field], tenant_id)
    if "custom_fields" in payload:
        await custom_field_service.validate_custom_fields(db, tenant_id, "incident", payload["custom_fields"])
    for k, v in payload.items():
        setattr(inc, k, v)
    await db.flush()
    return inc


async def delete_incident(db: AsyncSession, incident_id: int, tenant_id: int) -> None:
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    inc.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def get_status_history(db: AsyncSession, incident_id: int, tenant_id: int) -> list[IncidentStatusHistory]:
    return list((await db.execute(
        select(IncidentStatusHistory).where(
            IncidentStatusHistory.incident_id == incident_id,
            IncidentStatusHistory.tenant_id == tenant_id,
        ).order_by(IncidentStatusHistory.changed_at.asc())
    )).scalars().all())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/services/test_incident_service.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/incident_service.py backend/tests/services/test_incident_service.py
git commit -m "feat(incidents): incident_service CRUD (Phase 5 SP1)"
```

---

## Task 5: incident_service — transition (TDD)

**Files:**
- Modify: `backend/app/services/incident_service.py`
- Test: `backend/tests/services/test_incident_transition.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from app.services import incident_service
from app.services.incident_defaults import seed_incident_defaults_for_tenant
from app.schemas.incident import IncidentCreate
from fastapi import HTTPException


async def _make(db, tenant, user):
    await seed_incident_defaults_for_tenant(db, tenant.id)
    await db.flush()
    return await incident_service.create_incident(db, IncidentCreate(title="x", severity="P2"), tenant.id, user.id)


@pytest.mark.asyncio
async def test_valid_transition_updates_status_and_history(db_session, tenant, user):
    inc = await _make(db_session, tenant, user)
    out = await incident_service.transition(db_session, inc.id, "investigating", tenant.id, user.id, "Viewer")
    assert out.status == "investigating"
    hist = await incident_service.get_status_history(db_session, inc.id, tenant.id)
    assert hist[-1].from_state == "new" and hist[-1].to_state == "investigating"


@pytest.mark.asyncio
async def test_invalid_transition_rejected(db_session, tenant, user):
    inc = await _make(db_session, tenant, user)
    with pytest.raises(HTTPException) as e:
        await incident_service.transition(db_session, inc.id, "closed", tenant.id, user.id, "Viewer")
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_entering_resolved_sets_resolved_at_leaving_clears(db_session, tenant, user):
    inc = await _make(db_session, tenant, user)
    await incident_service.transition(db_session, inc.id, "investigating", tenant.id, user.id, "Viewer")
    inc = await incident_service.transition(db_session, inc.id, "resolved", tenant.id, user.id, "Viewer")
    assert inc.resolved_at is not None
    inc = await incident_service.transition(db_session, inc.id, "investigating", tenant.id, user.id, "Viewer")
    assert inc.resolved_at is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/services/test_incident_transition.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'transition'`.

- [ ] **Step 3: Implement `transition`** — append to `incident_service.py` (add imports at top: `from datetime import datetime, timezone` is already present; add `from app.services import lifecycle_service`):

```python
async def transition(db: AsyncSession, incident_id: int, to_state: str,
                     tenant_id: int, user_id: int, user_role: str) -> Incident:
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    tpl = await _resolve_template(db, inc.lifecycle_template_id, tenant_id)
    record_values = {
        "title": inc.title, "description": inc.description, "severity": inc.severity,
        "custom_fields": inc.custom_fields or {},
    }
    ok, reason = lifecycle_service.validate_transition(
        tpl.definition, inc.status, to_state, user_role, record_values
    )
    if not ok:
        raise HTTPException(status_code=422, detail=reason)
    from_state = inc.status
    inc.status = to_state
    resolved_keys = {s["key"] for s in tpl.definition["states"] if s.get("is_resolved")}
    now = datetime.now(timezone.utc)
    if to_state in resolved_keys:
        inc.resolved_at = now
    elif from_state in resolved_keys:
        inc.resolved_at = None
    db.add(IncidentStatusHistory(
        tenant_id=tenant_id, incident_id=inc.id, from_state=from_state, to_state=to_state,
        changed_by=user_id, changed_at=now,
    ))
    await db.flush()
    return inc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/services/test_incident_transition.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/incident_service.py backend/tests/services/test_incident_transition.py
git commit -m "feat(incidents): lifecycle transition with resolved_at handling (Phase 5 SP1)"
```

---

## Task 6: incident_service — detail hydration (TDD)

**Files:**
- Modify: `backend/app/services/incident_service.py`
- Test: append to `backend/tests/services/test_incident_service.py`

- [ ] **Step 1: Write the failing test** (append):

```python
@pytest.mark.asyncio
async def test_detail_hydrates_links_transitions_and_epic_grouping(db_session, tenant, user, make_release, make_release_change, make_system):
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    sysrow = await make_system(tenant.id, name="Payments")
    fix = await make_release(tenant.id, name="Fix R1")
    await make_release_change(tenant.id, release_id=fix.id, title="story A", epic_id=7)
    await make_release_change(tenant.id, release_id=fix.id, title="story B", epic_id=7)
    inc = await incident_service.create_incident(
        db_session,
        IncidentCreate(title="x", severity="P1", system_id=sysrow.id, fix_release_id=fix.id),
        tenant.id, user.id,
    )
    detail = await incident_service.get_incident_detail(db_session, inc.id, tenant.id, "Viewer")
    assert detail["system_name"] == "Payments"
    assert detail["fix_release"]["name"] == "Fix R1"
    assert [c.title for c in detail["fix_release_changes_by_epic"]["7"]] == ["story A", "story B"]
    assert any(t["to_state"] == "investigating" for t in detail["allowed_transitions"])
    assert len(detail["status_history"]) == 1
```

If `make_release`/`make_release_change`/`make_system` fixtures don't exist, create the rows inline using the models (`Release`, `ReleaseChange`, `System`) the way sibling integration tests do — check `tests/services/test_release_service.py` for the pattern and reuse it.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/services/test_incident_service.py -k detail -q`
Expected: FAIL — no attribute `get_incident_detail`.

- [ ] **Step 3: Implement `get_incident_detail`** — append to `incident_service.py` (add imports: `from app.db.models.release_change import ReleaseChange`):

```python
async def _name(db, model, row_id):
    if row_id is None:
        return None
    row = (await db.execute(select(model).where(model.id == row_id))).scalar_one_or_none()
    return getattr(row, "name", None) if row else None


async def _release_summary(db, release_id, tenant_id):
    if release_id is None:
        return None
    r = (await db.execute(select(Release).where(Release.id == release_id, Release.tenant_id == tenant_id))).scalar_one_or_none()
    if r is None:
        return None
    return {"id": r.id, "name": r.name, "target_date": r.target_date, "status": r.status}


async def get_incident_detail(db: AsyncSession, incident_id: int, tenant_id: int, user_role: str) -> Optional[dict]:
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        return None
    tpl = await _resolve_template(db, inc.lifecycle_template_id, tenant_id)
    transitions = lifecycle_service.get_allowed_transitions(tpl.definition, inc.status, user_role)

    changes_by_epic: dict[str, list] = {}
    if inc.fix_release_id is not None:
        rows = (await db.execute(select(ReleaseChange).where(
            ReleaseChange.release_id == inc.fix_release_id,
            ReleaseChange.tenant_id == tenant_id,
        ).order_by(ReleaseChange.id.asc()))).scalars().all()
        for rc in rows:
            changes_by_epic.setdefault(str(rc.epic_id) if rc.epic_id is not None else "ungrouped", []).append(rc)

    return {
        "id": inc.id, "title": inc.title, "description": inc.description, "severity": inc.severity,
        "status": inc.status, "detected_at": inc.detected_at, "resolved_at": inc.resolved_at,
        "source": inc.source, "external_ref": inc.external_ref,
        "environment_id": inc.environment_id, "environment_name": await _name(db, Environment, inc.environment_id),
        "deployment_id": inc.deployment_id,
        "release_id": inc.release_id, "release": await _release_summary(db, inc.release_id, tenant_id),
        "fix_release_id": inc.fix_release_id, "fix_release": await _release_summary(db, inc.fix_release_id, tenant_id),
        "fix_release_changes_by_epic": changes_by_epic,
        "system_id": inc.system_id, "system_name": await _name(db, System, inc.system_id),
        "subsystem_id": inc.subsystem_id, "subsystem_name": await _name(db, SubSystem, inc.subsystem_id),
        "custom_fields": inc.custom_fields,
        "allowed_transitions": [{"to_state": t["to_state"], "label": t["label"]} for t in transitions],
        "status_history": await get_status_history(db, inc.id, tenant_id),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/services/test_incident_service.py -k detail -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/incident_service.py backend/tests/services/test_incident_service.py
git commit -m "feat(incidents): detail hydration with fix-release epic grouping (Phase 5 SP1)"
```

---

## Task 7: API endpoints + router mount (TDD)

**Files:**
- Create: `backend/app/api/v1/incidents.py`
- Modify: `backend/app/main.py` (or the router aggregator that includes other v1 routers)
- Test: `backend/tests/integration/test_incidents_api.py`

- [ ] **Step 1: Write the failing integration test** (mirror an existing integration test's `client`/auth fixture, e.g. `tests/integration/test_releases_api.py`):

```python
import pytest


@pytest.mark.asyncio
async def test_incident_crud_and_transition_flow(auth_client):
    # create
    r = await auth_client.post("/api/v1/incidents", json={"title": "Outage", "severity": "P1"})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    assert r.json()["status"] == "new"
    # list
    r = await auth_client.get("/api/v1/incidents")
    assert r.status_code == 200 and any(i["id"] == iid for i in r.json())
    # transition
    r = await auth_client.post(f"/api/v1/incidents/{iid}/transition", json={"to_state": "investigating"})
    assert r.status_code == 200 and r.json()["status"] == "investigating"
    # detail
    r = await auth_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "investigating"
    assert any(t["to_state"] in ("identified", "resolved") for t in body["allowed_transitions"])
    # delete
    r = await auth_client.delete(f"/api/v1/incidents/{iid}")
    assert r.status_code == 204
    r = await auth_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_transition_returns_422(auth_client):
    iid = (await auth_client.post("/api/v1/incidents", json={"title": "x", "severity": "P3"})).json()["id"]
    r = await auth_client.post(f"/api/v1/incidents/{iid}/transition", json={"to_state": "closed"})
    assert r.status_code == 422
```

Use the project's existing authenticated-client fixture name (check `tests/integration/` for `auth_client`/`client` + how tenant defaults get seeded; the test tenant must have incident defaults — if the fixture creates tenants via `tenant_service.create_tenant`, the seed from Task 2 runs automatically; otherwise call `seed_incident_defaults_for_tenant` in the fixture/test setup).

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_incidents_api.py -q`
Expected: FAIL — 404 (route not mounted).

- [ ] **Step 3: Implement the router**

`backend/app/api/v1/incidents.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import incident_service
from app.schemas.incident import (
    IncidentCreate, IncidentUpdate, IncidentTransition, IncidentDetail, IncidentListRow,
)

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


async def _row(db, inc, tenant_id):
    # Build an IncidentListRow with hydrated names/fix-release summary.
    from app.services.incident_service import _name, _release_summary
    from app.db.models.system import System
    from app.db.models.environment import Environment
    from app.db.models.release import Release
    return IncidentListRow(
        id=inc.id, title=inc.title, severity=inc.severity, status=inc.status,
        detected_at=inc.detected_at, resolved_at=inc.resolved_at,
        system_id=inc.system_id, system_name=await _name(db, System, inc.system_id),
        environment_id=inc.environment_id, environment_name=await _name(db, Environment, inc.environment_id),
        release_id=inc.release_id, release_name=await _name(db, Release, inc.release_id),
        fix_release=await _release_summary(db, inc.fix_release_id, tenant_id),
    )


@router.get("", response_model=list[IncidentListRow])
async def list_incidents(
    status_: str | None = Query(None, alias="status"),
    severity: str | None = None, system_id: int | None = None,
    environment_id: int | None = None, release_id: int | None = None, source: str | None = None,
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user),
):
    filters = {"status": status_, "severity": severity, "system_id": system_id,
               "environment_id": environment_id, "release_id": release_id, "source": source}
    rows = await incident_service.list_incidents(db, current_user.active_tenant_id, filters)
    return [await _row(db, r, current_user.active_tenant_id) for r in rows]


@router.post("", response_model=IncidentDetail, status_code=status.HTTP_201_CREATED)
async def create_incident(data: IncidentCreate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    inc = await incident_service.create_incident(db, data, current_user.active_tenant_id, current_user.id)
    return await incident_service.get_incident_detail(db, inc.id, current_user.active_tenant_id, current_user.role)


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(incident_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    detail = await incident_service.get_incident_detail(db, incident_id, current_user.active_tenant_id, current_user.role)
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return detail


@router.patch("/{incident_id}", response_model=IncidentDetail)
async def update_incident(incident_id: int, data: IncidentUpdate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    await incident_service.update_incident(db, incident_id, data, current_user.active_tenant_id)
    return await incident_service.get_incident_detail(db, incident_id, current_user.active_tenant_id, current_user.role)


@router.post("/{incident_id}/transition", response_model=IncidentDetail)
async def transition_incident(incident_id: int, data: IncidentTransition, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    await incident_service.transition(db, incident_id, data.to_state, current_user.active_tenant_id, current_user.id, current_user.role)
    return await incident_service.get_incident_detail(db, incident_id, current_user.active_tenant_id, current_user.role)


@router.delete("/{incident_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_incident(incident_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    await incident_service.delete_incident(db, incident_id, current_user.active_tenant_id)
```

- [ ] **Step 4: Mount the router** — in `backend/app/main.py` (find where other v1 routers are `include_router`'d) add:

```python
from app.api.v1 import incidents as incidents_router
app.include_router(incidents_router.router)
```

(Match the existing include pattern — some routers there may use a shared `api_router`. Follow whichever the file uses.)

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/integration/test_incidents_api.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/incidents.py backend/app/main.py backend/tests/integration/test_incidents_api.py
git commit -m "feat(incidents): REST API (CRUD + transition) (Phase 5 SP1)"
```

---

## Task 8: Tenant-isolation tests (TDD — hardening)

**Files:**
- Test: `backend/tests/integration/test_incident_tenant_isolation.py`

- [ ] **Step 1: Write the tests**

```python
import pytest


@pytest.mark.asyncio
async def test_cannot_reference_other_tenant_release(auth_client, other_tenant_release_id):
    r = await auth_client.post("/api/v1/incidents",
        json={"title": "x", "severity": "P1", "release_id": other_tenant_release_id})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_cannot_reference_other_tenant_system(auth_client, other_tenant_system_id):
    r = await auth_client.post("/api/v1/incidents",
        json={"title": "x", "severity": "P1", "system_id": other_tenant_system_id})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_cannot_read_other_tenant_incident(auth_client, other_tenant_incident_id):
    r = await auth_client.get(f"/api/v1/incidents/{other_tenant_incident_id}")
    assert r.status_code == 404
```

Build the `other_tenant_*` fixtures by creating a second tenant + rows via the services (mirror how existing isolation tests in `tests/integration/` set up a second tenant — the tenant-isolation memory notes these exist for other entities; copy that fixture pattern).

- [ ] **Step 2: Run**

Run: `pytest tests/integration/test_incident_tenant_isolation.py -q`
Expected: PASS (the guards from Task 4 make these pass; if any fail, fix the guard, not the test).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_incident_tenant_isolation.py
git commit -m "test(incidents): tenant isolation on FK writes + reads (Phase 5 SP1)"
```

- [ ] **Step 4: Full backend suite**

Run: `pytest tests/services tests/integration -q`
Expected: PASS (no regressions).

---

## Task 9: Frontend types + service

**Files:**
- Create: `frontend/src/types/incident.ts`, `frontend/src/services/incidentService.ts`

- [ ] **Step 1: Types** — `frontend/src/types/incident.ts`:

```ts
export type Severity = 'P1' | 'P2' | 'P3' | 'P4';

export interface ReleaseSummary { id: number; name: string; target_date: string | null; status: string; }
export interface ReleaseChangeRow { id: number; title: string; epic_id: number | null; }
export interface TransitionOption { to_state: string; label: string; }
export interface StatusHistoryRow { from_state: string | null; to_state: string; changed_by: number | null; changed_at: string; }

export interface IncidentListRow {
  id: number; title: string; severity: Severity; status: string;
  detected_at: string; resolved_at: string | null;
  system_id: number | null; system_name: string | null;
  environment_id: number | null; environment_name: string | null;
  release_id: number | null; release_name: string | null;
  fix_release: ReleaseSummary | null;
}

export interface IncidentDetail {
  id: number; title: string; description: string | null; severity: Severity; status: string;
  detected_at: string; resolved_at: string | null; source: string; external_ref: string | null;
  environment_id: number | null; environment_name: string | null; deployment_id: number | null;
  release_id: number | null; release: ReleaseSummary | null;
  fix_release_id: number | null; fix_release: ReleaseSummary | null;
  fix_release_changes_by_epic: Record<string, ReleaseChangeRow[]>;
  system_id: number | null; system_name: string | null;
  subsystem_id: number | null; subsystem_name: string | null;
  custom_fields: Record<string, unknown> | null;
  allowed_transitions: TransitionOption[];
  status_history: StatusHistoryRow[];
}

export interface IncidentCreate {
  title: string; description?: string; severity: Severity; detected_at?: string;
  environment_id?: number | null; deployment_id?: number | null;
  release_id?: number | null; fix_release_id?: number | null;
  system_id?: number | null; subsystem_id?: number | null;
  source?: string; external_ref?: string | null; custom_fields?: Record<string, unknown> | null;
}
export type IncidentUpdate = Partial<Omit<IncidentCreate, 'source'>>;
```

- [ ] **Step 2: Service** — `frontend/src/services/incidentService.ts` (mirror `releaseService.ts`'s axios/base-client usage):

```ts
import { api } from './api';  // use whatever the sibling services import (check releaseService.ts)
import type { IncidentListRow, IncidentDetail, IncidentCreate, IncidentUpdate } from '../types/incident';

export const incidentService = {
  list: (params: Record<string, unknown> = {}) =>
    api.get<IncidentListRow[]>('/api/v1/incidents', { params }).then((r) => r.data),
  get: (id: number) => api.get<IncidentDetail>(`/api/v1/incidents/${id}`).then((r) => r.data),
  create: (data: IncidentCreate) => api.post<IncidentDetail>('/api/v1/incidents', data).then((r) => r.data),
  update: (id: number, data: IncidentUpdate) => api.patch<IncidentDetail>(`/api/v1/incidents/${id}`, data).then((r) => r.data),
  transition: (id: number, to_state: string) =>
    api.post<IncidentDetail>(`/api/v1/incidents/${id}/transition`, { to_state }).then((r) => r.data),
  remove: (id: number) => api.delete(`/api/v1/incidents/${id}`).then((r) => r.data),
};
```

- [ ] **Step 3: Type-check + commit**

Run: `npx tsc --noEmit`  → PASS

```bash
git add frontend/src/types/incident.ts frontend/src/services/incidentService.ts
git commit -m "feat(incidents): frontend types + API service (Phase 5 SP1)"
```

---

## Task 10: Redux slice (TDD)

**Files:**
- Create: `frontend/src/store/incidentSlice.ts`, `frontend/src/store/__tests__/incidentSlice.test.ts`
- Modify: `frontend/src/store/index.ts`

- [ ] **Step 1: Write the failing test** (mirror an existing slice test, e.g. a sibling in `src/store/__tests__/`):

```ts
import reducer, { fetchIncidents } from '../incidentSlice';

describe('incidentSlice', () => {
  it('has an empty initial state', () => {
    const s = reducer(undefined, { type: '@@INIT' });
    expect(s.list).toEqual([]);
    expect(s.loading).toBe(false);
  });
  it('stores incidents on fulfilled', () => {
    const rows = [{ id: 1, title: 'x', severity: 'P1', status: 'new' }] as any;
    const s = reducer(undefined, { type: fetchIncidents.fulfilled.type, payload: rows });
    expect(s.list).toHaveLength(1);
  });
  it('sets loading on pending', () => {
    const s = reducer(undefined, { type: fetchIncidents.pending.type });
    expect(s.loading).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/store/__tests__/incidentSlice.test.ts`
Expected: FAIL — cannot resolve `../incidentSlice`.

- [ ] **Step 3: Implement the slice** — `frontend/src/store/incidentSlice.ts` (mirror the shape of an existing slice such as `releaseSlice.ts`; keep `list`, `detail`, `loading`, `error`):

```ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { incidentService } from '../services/incidentService';
import type { IncidentListRow, IncidentDetail, IncidentCreate, IncidentUpdate } from '../types/incident';

export const fetchIncidents = createAsyncThunk('incidents/list',
  (params: Record<string, unknown> = {}) => incidentService.list(params));
export const fetchIncident = createAsyncThunk('incidents/get', (id: number) => incidentService.get(id));
export const createIncident = createAsyncThunk('incidents/create', (data: IncidentCreate) => incidentService.create(data));
export const updateIncident = createAsyncThunk('incidents/update',
  ({ id, data }: { id: number; data: IncidentUpdate }) => incidentService.update(id, data));
export const transitionIncident = createAsyncThunk('incidents/transition',
  ({ id, to_state }: { id: number; to_state: string }) => incidentService.transition(id, to_state));
export const deleteIncident = createAsyncThunk('incidents/delete', async (id: number) => { await incidentService.remove(id); return id; });

interface IncidentState { list: IncidentListRow[]; detail: IncidentDetail | null; loading: boolean; error: string | null; }
const initialState: IncidentState = { list: [], detail: null, loading: false, error: null };

const slice = createSlice({
  name: 'incidents', initialState, reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchIncidents.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchIncidents.fulfilled, (s, a) => { s.loading = false; s.list = a.payload; });
    b.addCase(fetchIncidents.rejected, (s, a) => { s.loading = false; s.error = a.error.message ?? 'Failed to load incidents'; });
    b.addCase(fetchIncident.fulfilled, (s, a) => { s.detail = a.payload; });
    b.addCase(transitionIncident.fulfilled, (s, a) => { s.detail = a.payload; });
    b.addCase(updateIncident.fulfilled, (s, a) => { s.detail = a.payload; });
  },
});
export default slice.reducer;
```

- [ ] **Step 4: Register the reducer** — in `frontend/src/store/index.ts`, add `incidents: incidentReducer` to the root reducer (import `incidentReducer from './incidentSlice'`), matching the existing registration style.

- [ ] **Step 5: Run to verify pass**

Run: `npx vitest run src/store/__tests__/incidentSlice.test.ts` → PASS. Then `npx tsc --noEmit` → PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/incidentSlice.ts frontend/src/store/__tests__/incidentSlice.test.ts frontend/src/store/index.ts
git commit -m "feat(incidents): redux slice (Phase 5 SP1)"
```

---

## Task 11: IncidentList page + severity helper + route + nav

**Files:**
- Create: `frontend/src/utils/incidentSeverity.ts`, `frontend/src/pages/incidents/IncidentList.tsx`
- Modify: router config + nav menu

- [ ] **Step 1: Severity helper** — `frontend/src/utils/incidentSeverity.ts`:

```ts
import type { Severity } from '../types/incident';
export const SEVERITY_COLOR: Record<Severity, 'error' | 'warning' | 'info' | 'default'> = {
  P1: 'error', P2: 'warning', P3: 'info', P4: 'default',
};
export const SEVERITIES: Severity[] = ['P1', 'P2', 'P3', 'P4'];
```

- [ ] **Step 2: IncidentList** — `frontend/src/pages/incidents/IncidentList.tsx`. Mirror the structure of an existing DataGrid list page (e.g. `pages/releases/ReleaseList.tsx`): dispatch `fetchIncidents` in `useEffect`, render a MUI `DataGrid` with columns: title, severity (Chip via `SEVERITY_COLOR`), status (Chip), system_name, environment_name, release_name, **Fix ETA** (`fix_release?.target_date` formatted, else "—"), detected_at, resolved_at. Row click → navigate to `/incidents/:id`. Include a filter bar (status, severity, system) that re-dispatches `fetchIncidents(params)`, and a "New Incident" button → `/incidents/new`. Follow the display-name convention (never render `#id`).

- [ ] **Step 3: Route + nav** — add routes `/incidents`, `/incidents/new`, `/incidents/:id` to the router (mirror release routes), and an "Incidents" nav entry under Release Management (or Insights) in the nav menu component.

- [ ] **Step 4: Verify**

Run: `npx tsc --noEmit` → PASS.
Run: `npx vitest run src/components/topology src/store` (sanity — no regressions) → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/incidentSeverity.ts frontend/src/pages/incidents/IncidentList.tsx frontend/src/  # router + nav files
git commit -m "feat(incidents): IncidentList page + route + nav (Phase 5 SP1)"
```

---

## Task 12: IncidentForm page

**Files:**
- Create: `frontend/src/pages/incidents/IncidentForm.tsx`

- [ ] **Step 1: Implement** — create/edit form. Fields: title (required), description, severity (Select of `SEVERITIES`), searchable pickers for environment / deployment / causal release / fix release / system → subsystem (reuse existing picker components used elsewhere — e.g. the release/system Autocomplete pickers used on the release Systems tab; find them under `src/components/`), `source`/`external_ref` (plain text, default source "manual"), and custom fields via the existing `LifecycleAwareFieldsPanel` (pass `entityType="incident"` + current `status` — inspect its props where releases use it). On submit: dispatch `createIncident` or `updateIncident`, then navigate to the detail page. Follow the form pattern of `AddPhaseBookingDialog.tsx` / a release edit form for structure and error handling (snackbar on failure).

- [ ] **Step 2: Verify + commit**

Run: `npx tsc --noEmit` → PASS.

```bash
git add frontend/src/pages/incidents/IncidentForm.tsx
git commit -m "feat(incidents): IncidentForm create/edit page (Phase 5 SP1)"
```

---

## Task 13: IncidentDetail page

**Files:**
- Create: `frontend/src/pages/incidents/IncidentDetail.tsx`

- [ ] **Step 1: Implement** — dispatch `fetchIncident(id)` on mount. Render:
  - Header: title, severity chip, **status chip**, and a **transition button** per `detail.allowed_transitions` (each dispatches `transitionIncident({id, to_state})`).
  - Details block: description, detected_at, resolved_at, source/external_ref, environment_name, causal release link (`/releases/:release_id`), system/subsystem names.
  - **Fix-Release panel**: if `fix_release`, show name (link to `/releases/:fix_release_id`), target_date ("Fix ETA"), status; then list `fix_release_changes_by_epic` — one subheader per epic key with its `ReleaseChangeRow[]` beneath (mirror the epic-grouping rendering used on the Release Scope tab).
  - **Custom fields** panel (render `custom_fields` values; read-only here or via `LifecycleAwareFieldsPanel` in read mode).
  - **Status-history timeline**: `status_history` in order (`from_state → to_state`, `changed_at`).
  - An "Edit" button → `/incidents/:id/edit` and a delete action (guarded confirm) dispatching `deleteIncident`.
  - **No PIR panel** (sub-project 4).

- [ ] **Step 2: Verify + commit**

Run: `npx tsc --noEmit` → PASS.

```bash
git add frontend/src/pages/incidents/IncidentDetail.tsx
git commit -m "feat(incidents): IncidentDetail page with lifecycle + fix-release panel (Phase 5 SP1)"
```

---

## Task 14: Admin entity-type wiring + full verification

**Files:**
- Modify: tenant-admin custom-fields screen + lifecycle-template admin screen (frontend) to include `incident` in their entity-type lists.

- [ ] **Step 1: Add `incident` to admin entity-type lists** — find the frontend admin screens that enumerate entity types for custom fields and lifecycle templates (search `src/` for `entity_type` / an array containing `'release'`, `'booking'`, `'change_request'`). Add `incident` (label "Incident") so admins can configure incident custom fields + lifecycle. If the backend `tenant_admin_fields` needs no allowlist (confirmed — it takes `entity_type` freely), no backend change is required; verify there is no hard-coded allowlist in `app/api/v1/tenant_admin_fields.py` or its service, and if one exists add `incident`.

- [ ] **Step 2: Full verification**

Run (backend): `pytest tests/services tests/integration -q` → PASS.
Run (frontend): `npx tsc --noEmit` → PASS; `npx vitest run` → PASS (ignore the pre-existing `e2e/*.spec.ts` Playwright-under-vitest failures — unrelated).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/  # admin screen files
git commit -m "feat(incidents): expose incident entity-type in tenant-admin config (Phase 5 SP1)"
```

---

## Task 15: Manual verification (human eyeball)

> Browser automation is flaky here — human check. If you are an agent, hand this to the user.

- [ ] Start app; go to **Incidents** nav → **New Incident**; create one with severity, a system, and a fix release.
- [ ] Confirm it lands in the list with the **Fix ETA** column populated and status **New**.
- [ ] Open detail; step it through **Start Investigating → Root Cause Identified → Schedule Fix → Mark Resolved** using the transition buttons; confirm the status chip updates, `resolved_at` sets on Resolved, and the status-history timeline grows.
- [ ] Confirm the Fix-Release panel shows the release + its ReleaseChanges grouped by epic.
- [ ] In tenant admin, add an `incident` custom field + confirm it appears on the form/detail.

---

## Self-Review Notes

- **Spec coverage:** model incl. causal+fix release, system/subsystem, source/external_ref, custom_fields, history (Task 1); configurable lifecycle + seeded default (Task 2); schemas (Task 3); CRUD + FK-tenant validation + custom-field validation (Task 4); transition + resolved_at (Task 5); detail hydration incl. fix-release epic grouping + allowed_transitions (Task 6); API (Task 7); tenant isolation (Task 8); frontend types/service/slice/list/form/detail (Tasks 9–13); admin entity-type wiring (Task 14); manual eyeball (Task 15). Non-goals (DORA math, PIR, ITSM connector, health, analytics) are excluded. ✅
- **Type consistency:** `get_incident_detail` returns a dict matching `IncidentDetail` fields; `_release_summary`/`_name` reused across service + API `_row`; `transition(...)` signature `(db, id, to_state, tenant_id, user_id, user_role)` consistent between service, tests, and the API route; `fix_release_changes_by_epic` keyed by `str(epic_id)` in both service and TS type (`Record<string,…>`). ✅
- **Assumptions to confirm during execution (flagged in-task, not blockers):** exact test-fixture names (`db_session`/`tenant`/`user`/`auth_client`) and how the test tenant seeds incident defaults; the router-include idiom in `main.py`; the exact `LifecycleAwareFieldsPanel` props and picker components to reuse; whether any admin entity-type list is hard-coded. Each task says to mirror a named existing file to resolve these.
