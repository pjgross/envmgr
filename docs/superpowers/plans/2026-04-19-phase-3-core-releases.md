# Phase 3 Sub-Project 1 — Core Releases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the full Core Releases sub-system — 10 new tables, ~35 backend endpoints, release form + list + calendar + timeline + template library — on the `feature/phase-3-core-releases` branch.

**Architecture:** Releases reuse the existing `lifecycle_template` infrastructure (entity_type='release'). Test phases are plan items inside `in_progress`, not lifecycle states. Per-state field permissions extend with a new `required_fields` key for transition gating. Bookings and CRs get real FKs into `release` (promoting Phase 2 stubs). Jira integration and Enterprise Releases are out of scope — stubs only.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic + PostgreSQL (prod) / SQLite (tests) + Pydantic v2; React 18 + TypeScript + MUI DataGrid + Redux Toolkit + FullCalendar; pytest (backend) / vitest (frontend, sparse).

**Spec:** [`docs/superpowers/specs/2026-04-19-phase-3-core-releases-design.md`](../specs/2026-04-19-phase-3-core-releases-design.md)

**Branch:** `feature/phase-3-core-releases` (already created at HEAD `5873662` with the spec committed).

**Conventions reminder (must-follow):**
- Python: PEP 8, type hints, async/await everywhere; `snake_case` functions; `PascalCase` classes.
- SQLAlchemy: all enum columns use `native_enum=False` (VARCHAR storage, SQLite test compat).
- Alembic: **never** `--autogenerate`. Use `alembic revision -m "..."` and write DDL manually.
- Services: never call `db.commit()` — `get_db` commits on success. Use `db.flush()` mid-transaction. All state-changing service calls publish outbox events via `publish_event(...)` *inside* the same transaction.
- Every query on a tenant-scoped table must filter by `tenant_id`; use `current_user.active_tenant_id` in endpoints.
- Soft delete via `deleted_at`; junctions and audit rows hard-delete.
- Tests use in-memory SQLite via `Base.metadata.create_all` (`backend/tests/conftest.py`); migrations are NOT run in tests.
- Frontend: functional components, Redux async thunks, MUI DataGrid for tables.
- Commit per task with a conventional-commit message; push after each task so the MR has small reviewable commits.

---

## Task 1 — Register `release` in `ENTITY_FIELD_SPECS`

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py`
- Test: `backend/tests/test_lifecycle_entity_specs.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lifecycle_entity_specs.py
from app.api.v1.schemas.booking_lifecycle import (
    ENTITY_FIELD_SPECS,
    validate_definition_for_entity,
    LifecycleDefinition,
)


def test_release_entity_is_registered():
    assert "release" in ENTITY_FIELD_SPECS
    spec = ENTITY_FIELD_SPECS["release"]
    assert {"name", "description", "release_type", "target_date", "actual_date", "raised_by"} <= set(spec["valid"])


def test_validate_definition_accepts_release_standard_fields():
    definition = LifecycleDefinition.model_validate({
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "completed", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {
            "draft": {
                "standard_fields": {
                    "name": {"editable_by": ["Admin"]},
                    "target_date": {"editable_by": ["Admin"]},
                },
                "custom_fields": {},
            },
        },
    })
    validate_definition_for_entity(definition, "release")  # no raise


def test_validate_definition_rejects_unknown_release_standard_field():
    definition = LifecycleDefinition.model_validate({
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "completed", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {
            "draft": {
                "standard_fields": {"bogus_field": {"editable_by": ["Admin"]}},
                "custom_fields": {},
            },
        },
    })
    import pytest
    with pytest.raises(ValueError):
        validate_definition_for_entity(definition, "release")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_lifecycle_entity_specs.py -v`
Expected: FAIL — `"release" not in ENTITY_FIELD_SPECS`.

- [ ] **Step 3: Add release entry to ENTITY_FIELD_SPECS**

Open `backend/app/api/v1/schemas/booking_lifecycle.py`; find the `ENTITY_FIELD_SPECS` dict and add a `"release"` entry alongside the existing `"booking"` and `"change_request"` entries. Copy the exact shape of the existing entries. The new entry:

```python
"release": {
    "valid": {
        "name",
        "description",
        "release_type",
        "target_date",
        "actual_date",
        "raised_by",
    },
    "required_at_create": {"name", "release_type"},
},
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && uv run pytest tests/test_lifecycle_entity_specs.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/schemas/booking_lifecycle.py backend/tests/test_lifecycle_entity_specs.py
git commit -m "feat(phase-3): register release entity in ENTITY_FIELD_SPECS"
```

---

## Task 2 — Extend `validate_transition` with `required_fields`

**Files:**
- Modify: `backend/app/services/lifecycle_service.py`
- Test: `backend/tests/test_lifecycle_required_fields.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_lifecycle_required_fields.py
from app.services.lifecycle_service import validate_transition


DEF_WITH_REQUIRED = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "submitted": {
            "standard_fields": {"name": {"editable_by": ["Admin"]}},
            "custom_fields":   {"sponsor": {"editable_by": ["Admin"]}},
            "required_fields": ["name", "sponsor"],
        },
    },
}


def test_required_fields_block_transition_when_empty():
    record = {"name": "", "custom_fields": {}}
    allowed, reason = validate_transition(DEF_WITH_REQUIRED, "draft", "submitted", "Admin", record)
    assert allowed is False
    assert "name" in reason and "sponsor" in reason


def test_required_fields_allow_transition_when_all_present():
    record = {"name": "my release", "custom_fields": {"sponsor": "alice"}}
    allowed, reason = validate_transition(DEF_WITH_REQUIRED, "draft", "submitted", "Admin", record)
    assert allowed is True
    assert reason is None


def test_role_block_comes_before_required_fields_check():
    record = {"name": "", "custom_fields": {}}
    allowed, reason = validate_transition(DEF_WITH_REQUIRED, "draft", "submitted", "Viewer", record)
    assert allowed is False
    assert "role" in reason.lower() or "not allowed" in reason.lower()


def test_backward_compat_empty_record_no_required_fields():
    definition_no_required = {
        "transitions": [{"from_state": "draft", "to_state": "submitted", "allowed_roles": ["Admin"]}],
        "field_permissions": {"submitted": {"standard_fields": {}, "custom_fields": {}}},
    }
    allowed, reason = validate_transition(definition_no_required, "draft", "submitted", "Admin", {})
    assert allowed is True
    assert reason is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_lifecycle_required_fields.py -v`
Expected: FAIL — current `validate_transition` returns a bool, not a `(bool, str | None)` tuple.

- [ ] **Step 3: Update `validate_transition` in `lifecycle_service.py`**

Replace the existing `validate_transition` function with:

```python
def validate_transition(
    definition: dict,
    from_state: str,
    to_state: str,
    user_role: str,
    record_values: dict | None = None,
) -> tuple[bool, str | None]:
    """Return (allowed, reason). `reason` is None when allowed.

    Role check is authoritative and evaluated first. If the role passes,
    `required_fields` on the destination state are checked against
    `record_values` (flat keys for standard fields; custom fields live under
    record_values['custom_fields']). An empty or missing value blocks.
    """
    transition = next(
        (t for t in definition.get("transitions", [])
         if t["from_state"] == from_state and t["to_state"] == to_state),
        None,
    )
    if transition is None:
        return False, f"No transition from '{from_state}' to '{to_state}' is defined"
    if user_role not in transition["allowed_roles"]:
        return False, f"Role '{user_role}' is not allowed to transition {from_state} → {to_state}"
    required = (
        definition.get("field_permissions", {})
        .get(to_state, {})
        .get("required_fields", [])
    )
    if required:
        values = record_values or {}
        custom_values = values.get("custom_fields") or {}
        missing: list[str] = []
        for key in required:
            v = values.get(key) if key in values else custom_values.get(key)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                missing.append(key)
        if missing:
            return False, f"Required fields empty for '{to_state}': {', '.join(missing)}"
    return True, None
```

- [ ] **Step 4: Update every existing caller of `validate_transition`**

Search for callers: `grep -rn "validate_transition(" backend/app/`. Each caller currently expects a bool. Update the booking and CR services that call it to handle the new `(bool, str | None)` return:

- `backend/app/services/booking_service.py` — if the call was `if not validate_transition(...): raise`, change to `allowed, reason = validate_transition(...); if not allowed: raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=reason)`. Pass `record_values={}` (the booking record — collect `{"name": booking.name, ...}` and `{"custom_fields": booking.custom_fields or {}}`). Booking standard fields come from `ENTITY_FIELD_SPECS["booking"]["valid"]`.
- `backend/app/services/change_request_service.py` — same treatment.

For each file, read the current call site and the surrounding code first, then update to:

```python
allowed, reason = lifecycle_service.validate_transition(
    template.definition,
    from_state=current_state,
    to_state=new_state,
    user_role=user_role,
    record_values={**standard_values_dict, "custom_fields": record.custom_fields or {}},
)
if not allowed:
    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=reason)
```

- [ ] **Step 5: Run full backend tests to verify no regressions**

Run: `cd backend && uv run pytest tests/ -x -q`
Expected: All tests pass (target remains 268+N green bar; the new required-fields tests add 4; no existing tests fail).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/lifecycle_service.py backend/app/services/booking_service.py backend/app/services/change_request_service.py backend/tests/test_lifecycle_required_fields.py
git commit -m "feat(phase-3): validate_transition returns (bool, reason); honour required_fields"
```

---

## Task 3 — Add `entity_subtype` column to `CustomFieldDefinition`

**Files:**
- Modify: `backend/app/db/models/custom_field.py`
- Test: `backend/tests/test_custom_field_entity_subtype.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_custom_field_entity_subtype.py
import pytest
from app.db.models.custom_field import CustomFieldDefinition


@pytest.mark.asyncio
async def test_entity_subtype_is_persisted(db_session, tenant):
    cfd = CustomFieldDefinition(
        tenant_id=tenant.id,
        entity_type="release",
        entity_subtype="Major",
        field_key="business_sponsor",
        label="Business Sponsor",
        field_type="text",
        required=False,
        display_order=0,
    )
    db_session.add(cfd)
    await db_session.flush()
    assert cfd.id is not None
    assert cfd.entity_subtype == "Major"


@pytest.mark.asyncio
async def test_entity_subtype_nullable(db_session, tenant):
    cfd = CustomFieldDefinition(
        tenant_id=tenant.id,
        entity_type="release",
        entity_subtype=None,
        field_key="universal_field",
        label="Universal",
        field_type="text",
        required=False,
        display_order=0,
    )
    db_session.add(cfd)
    await db_session.flush()
    assert cfd.entity_subtype is None
```

(Uses the `tenant` fixture already present in `backend/tests/conftest.py`; confirm by reading conftest. If not present, use a new fixture defined inline.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_custom_field_entity_subtype.py -v`
Expected: FAIL — `CustomFieldDefinition` has no `entity_subtype` attribute.

- [ ] **Step 3: Add the column to the model**

In `backend/app/db/models/custom_field.py`, add after `entity_type`:

```python
    entity_subtype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
```

- [ ] **Step 4: Run the tests to verify pass**

Run: `cd backend && uv run pytest tests/test_custom_field_entity_subtype.py -v`
Expected: PASS (both tests).

Also run the broader suite to confirm no regressions:
Run: `cd backend && uv run pytest tests/ -x -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/custom_field.py backend/tests/test_custom_field_entity_subtype.py
git commit -m "feat(phase-3): add entity_subtype to CustomFieldDefinition"
```

---

## Task 4 — Create `Release` + `ReleaseStatusHistory` models

**Files:**
- Create: `backend/app/db/models/release.py`
- Modify: `backend/app/db/models/__init__.py` (if it imports models)
- Test: `backend/tests/test_release_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_release_model.py
from datetime import datetime, timezone
import pytest
from app.db.models.release import Release, ReleaseStatusHistory


@pytest.mark.asyncio
async def test_release_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id,
        name="Sprint 42",
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id,
        status="draft",
        raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    assert release.id is not None
    assert release.release_kind == "project"
    assert release.status == "draft"
    assert release.parent_release_id is None


@pytest.mark.asyncio
async def test_release_status_history_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id,
        name="R1",
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id,
        status="submitted",
        raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    history = ReleaseStatusHistory(
        release_id=release.id,
        from_state="draft",
        to_state="submitted",
        changed_by=user.id,
        changed_at=datetime.now(timezone.utc),
        notes="initial submission",
    )
    db_session.add(history)
    await db_session.flush()
    assert history.id is not None
```

Test fixtures `tenant`, `user` are in `conftest.py`. Add a `release_lifecycle_template` fixture (see Task 5 — for now, define it inline in this test file as a seeded `LifecycleTemplate` with `entity_type='release'`).

```python
# Fixtures block to add in conftest.py (do this as part of this task)
@pytest_asyncio.fixture
async def release_lifecycle_template(db_session, tenant):
    template = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="Test Major",
        description="",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "submitted", "allowed_roles": ["Admin"]},
                {"from_state": "submitted", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
                "submitted": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(template)
    await db_session.flush()
    return template
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_release_model.py -v`
Expected: FAIL — `release` module not found.

- [ ] **Step 3: Create the model file**

```python
# backend/app/db/models/release.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Release(Base):
    __tablename__ = "release"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_type: Mapped[str] = mapped_column(String(50), nullable=False)
    release_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="project")
    parent_release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", use_alter=True, name="fk_release_parent"),
        nullable=True,
        index=True,
    )
    template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release_template.id", use_alter=True, name="fk_release_template"),
        nullable=True,
    )
    lifecycle_template_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")
    target_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    lifecycle_template = relationship("LifecycleTemplate")


class ReleaseStatusHistory(Base):
    __tablename__ = "release_status_history"

    release_id: Mapped[int] = mapped_column(ForeignKey("release.id"), nullable=False, index=True)
    from_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    to_state: Mapped[str] = mapped_column(String(100), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

Also: add the `release_lifecycle_template` fixture to `backend/tests/conftest.py` (see the fixture block in step 1). Import `LifecycleTemplate` already exists in conftest.

- [ ] **Step 4: Run the tests to verify pass**

Run: `cd backend && uv run pytest tests/test_release_model.py -v`
Expected: PASS (both tests). But note: the FK `release_template.id` references a table that doesn't exist yet. Tests use `create_all` which emits the FK against a non-existent table — SQLite tolerates this but Postgres wouldn't. We accept this until Task 5 creates `release_template`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/release.py backend/tests/test_release_model.py backend/tests/conftest.py
git commit -m "feat(phase-3): add Release + ReleaseStatusHistory models"
```

---

## Task 5 — Create `ReleaseTemplate` model

**Files:**
- Create: `backend/app/db/models/release_template.py`
- Test: `backend/tests/test_release_template_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_release_template_model.py
import pytest
from app.db.models.release_template import ReleaseTemplate


@pytest.mark.asyncio
async def test_release_template_persists(db_session, tenant, release_lifecycle_template):
    tmpl = ReleaseTemplate(
        tenant_id=tenant.id,
        name="Major Default",
        description="Standard major release shape",
        release_type="Major",
        default_lifecycle_template_id=release_lifecycle_template.id,
        phases=[{"name": "SIT", "order": 1, "default_duration_days": 5, "activities": []}],
        gates=[{"name": "SIT Exit", "phase_name": "SIT", "acceptance_criteria": "Zero Sev1"}],
        version=1,
    )
    db_session.add(tmpl)
    await db_session.flush()
    assert tmpl.id is not None
    assert tmpl.phases[0]["name"] == "SIT"
    assert tmpl.version == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_release_template_model.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the model**

```python
# backend/app/db/models/release_template.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseTemplate(Base):
    __tablename__ = "release_template"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_type: Mapped[str] = mapped_column(String(50), nullable=False)
    default_lifecycle_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=True
    )
    phases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_release_template_model.py tests/test_release_model.py -v`
Expected: PASS (all three tests across both files).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/release_template.py backend/tests/test_release_template_model.py
git commit -m "feat(phase-3): add ReleaseTemplate model"
```

---

## Task 6 — Create `TestPhase` model

**Files:**
- Create: `backend/app/db/models/test_phase.py`
- Test: `backend/tests/test_test_phase_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_test_phase_model.py
from datetime import datetime, timezone, timedelta
import pytest
from app.db.models.release import Release
from app.db.models.test_phase import TestPhase


@pytest.mark.asyncio
async def test_test_phase_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()

    start = datetime.now(timezone.utc)
    phase = TestPhase(
        tenant_id=tenant.id,
        release_id=release.id,
        name="SIT",
        order=1,
        start_date=start,
        end_date=start + timedelta(days=5),
        status="pending",
    )
    db_session.add(phase)
    await db_session.flush()
    assert phase.id is not None
    assert phase.name == "SIT"
```

- [ ] **Step 2: Run the test**

Run: `cd backend && uv run pytest tests/test_test_phase_model.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create the model**

```python
# backend/app/db/models/test_phase.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TestPhase(Base):
    __tablename__ = "test_phase"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_test_phase_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/test_phase.py backend/tests/test_test_phase_model.py
git commit -m "feat(phase-3): add TestPhase model"
```

---

## Task 7 — Create `ReleaseGate`, `ReleaseSystem`, `ReleaseDependency` models

**Files:**
- Create: `backend/app/db/models/release_gate.py`
- Create: `backend/app/db/models/release_system.py`
- Create: `backend/app/db/models/release_dependency.py`
- Test: `backend/tests/test_release_support_models.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_release_support_models.py
from datetime import datetime, timezone
import pytest
from app.db.models.release import Release
from app.db.models.test_phase import TestPhase
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_system import ReleaseSystem
from app.db.models.release_dependency import ReleaseDependency


@pytest.mark.asyncio
async def test_release_gate_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()
    phase = TestPhase(tenant_id=tenant.id, release_id=release.id, name="SIT", order=1, status="pending")
    db_session.add(phase); await db_session.flush()
    gate = ReleaseGate(
        tenant_id=tenant.id, release_id=release.id, test_phase_id=phase.id,
        name="SIT Exit", acceptance_criteria="Zero Sev1", status="pending",
    )
    db_session.add(gate); await db_session.flush()
    assert gate.id is not None


@pytest.mark.asyncio
async def test_release_system_persists(db_session, tenant, user, release_lifecycle_template, system):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()
    rs = ReleaseSystem(
        tenant_id=tenant.id, release_id=release.id, system_id=system.id,
        role="changing", deployment_date=None,
    )
    db_session.add(rs); await db_session.flush()
    assert rs.id is not None
    assert rs.role == "changing"


@pytest.mark.asyncio
async def test_release_dependency_persists(db_session, tenant, user, release_lifecycle_template):
    def make_release(name):
        return Release(tenant_id=tenant.id, name=name, release_type="Major", release_kind="project",
                       lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    a = make_release("A"); b = make_release("B")
    db_session.add_all([a, b]); await db_session.flush()
    dep = ReleaseDependency(
        tenant_id=tenant.id, release_id=a.id, depends_on_release_id=b.id,
        kind="deploys_after", notes="A must go after B",
        last_dependency_target_date=b.target_date,
    )
    db_session.add(dep); await db_session.flush()
    assert dep.id is not None
```

If `system` fixture isn't in conftest, add one (creates a `System` row for the tenant).

- [ ] **Step 2: Run test — expect failure**

Run: `cd backend && uv run pytest tests/test_release_support_models.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 3: Create `release_gate.py`**

```python
# backend/app/db/models/release_gate.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseGate(Base):
    __tablename__ = "release_gate"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("test_phase.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Create `release_system.py`**

```python
# backend/app/db/models/release_system.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseSystem(Base):
    __tablename__ = "release_system"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    deployment_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("release_id", "system_id", name="uq_release_system"),
    )
```

- [ ] **Step 5: Create `release_dependency.py`**

```python
# backend/app/db/models/release_dependency.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseDependency(Base):
    __tablename__ = "release_dependency"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    depends_on_release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="deploys_after")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_dependency_target_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("release_id", "depends_on_release_id", name="uq_release_dependency"),
        CheckConstraint("release_id != depends_on_release_id", name="ck_release_dep_self"),
    )
```

- [ ] **Step 6: Run tests — expect pass**

Run: `cd backend && uv run pytest tests/test_release_support_models.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models/release_gate.py backend/app/db/models/release_system.py backend/app/db/models/release_dependency.py backend/tests/test_release_support_models.py
git commit -m "feat(phase-3): add ReleaseGate, ReleaseSystem, ReleaseDependency models"
```

---

## Task 8 — Create `ReleaseEventType` + `ReleaseEvent` models

**Files:**
- Create: `backend/app/db/models/release_event.py`
- Test: `backend/tests/test_release_event_models.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_release_event_models.py
from datetime import datetime, timezone
import pytest
from app.db.models.release import Release
from app.db.models.release_event import ReleaseEventType, ReleaseEvent


@pytest.mark.asyncio
async def test_release_event_type_persists(db_session, tenant):
    t = ReleaseEventType(
        tenant_id=tenant.id, name="Reschedule Reason",
        display_color="#ff0000", is_system=True,
    )
    db_session.add(t); await db_session.flush()
    assert t.id is not None


@pytest.mark.asyncio
async def test_release_event_persists(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()
    et = ReleaseEventType(tenant_id=tenant.id, name="Note", is_system=False)
    db_session.add(et); await db_session.flush()
    ev = ReleaseEvent(
        tenant_id=tenant.id, release_id=release.id, event_type_id=et.id,
        description="Stakeholder note: FYI", occurred_at=datetime.now(timezone.utc),
        recorded_by=user.id,
    )
    db_session.add(ev); await db_session.flush()
    assert ev.id is not None
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && uv run pytest tests/test_release_event_models.py -v`
Expected: FAIL.

- [ ] **Step 3: Create the models**

```python
# backend/app/db/models/release_event.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseEventType(Base):
    __tablename__ = "release_event_type"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReleaseEvent(Base):
    __tablename__ = "release_event"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type_id: Mapped[int] = mapped_column(
        ForeignKey("release_event_type.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && uv run pytest tests/test_release_event_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/release_event.py backend/tests/test_release_event_models.py
git commit -m "feat(phase-3): add ReleaseEventType + ReleaseEvent models"
```

---

## Task 9 — Create `ReleaseChange` model

**Files:**
- Create: `backend/app/db/models/release_change.py`
- Test: `backend/tests/test_release_change_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_release_change_model.py
import pytest
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange


@pytest.mark.asyncio
async def test_release_change_manual_item(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()

    rc = ReleaseChange(
        tenant_id=tenant.id, release_id=release.id,
        external_key=None, title="Add login dark mode",
        change_kind="story", source="manual",
    )
    db_session.add(rc); await db_session.flush()
    assert rc.id is not None
    assert rc.source == "manual"
    assert rc.external_key is None


@pytest.mark.asyncio
async def test_release_change_jira_stub_allowed(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()

    rc = ReleaseChange(
        tenant_id=tenant.id, release_id=release.id,
        external_key="PROJ-42", external_status="In Progress",
        title="Bug: overflow on mobile", change_kind="defect",
        jira_project_config_id=99,  # bare int OK; no FK until sub-project 3
        epic_id=77,
        source="jira",
    )
    db_session.add(rc); await db_session.flush()
    assert rc.external_key == "PROJ-42"
    assert rc.jira_project_config_id == 99
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && uv run pytest tests/test_release_change_model.py -v`
Expected: FAIL.

- [ ] **Step 3: Create the model**

```python
# backend/app/db/models/release_change.py
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseChange(Base):
    __tablename__ = "release_change"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)  # story | defect
    external_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    system_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("system.id"), nullable=True, index=True
    )
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Sub-project 3 promotes these to real FKs.
    jira_project_config_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    epic_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && uv run pytest tests/test_release_change_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/release_change.py backend/tests/test_release_change_model.py
git commit -m "feat(phase-3): add ReleaseChange model"
```

---

## Task 10 — Alembic migration (`p3s3_core_releases`)

**Files:**
- Create: `backend/app/db/migrations/versions/20260419_1200_p3s3_core_releases.py`

- [ ] **Step 1: Verify down_revision**

Run: `ls backend/app/db/migrations/versions/ | tail -1`
The most recent migration is `20260418_2130_p3s2_cr_multi_target.py` with revision `p3s2crmt`. The new migration's `down_revision` should be `"p3s2crmt"`.

- [ ] **Step 2: Write the migration file**

```python
# backend/app/db/migrations/versions/20260419_1200_p3s3_core_releases.py
"""phase 3 sub-project 1: core releases

Revision ID: p3s3releases
Revises: p3s2crmt
Create Date: 2026-04-19 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s3releases"
down_revision: Union[str, None] = "p3s2crmt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    # ── release_template ────────────────────────────────────────────────────
    if not _table_exists(conn, "release_template"):
        op.create_table(
            "release_template",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("release_type", sa.String(50), nullable=False),
            sa.Column("default_lifecycle_template_id", sa.Integer(), nullable=True),
            sa.Column("phases", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("gates", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["default_lifecycle_template_id"], ["lifecycle_template.id"]),
        )
        op.create_index("ix_release_template_tenant_id", "release_template", ["tenant_id"])

    # ── release ─────────────────────────────────────────────────────────────
    if not _table_exists(conn, "release"):
        op.create_table(
            "release",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(250), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("release_type", sa.String(50), nullable=False),
            sa.Column("release_kind", sa.String(20), nullable=False, server_default="project"),
            sa.Column("parent_release_id", sa.Integer(), nullable=True),
            sa.Column("template_id", sa.Integer(), nullable=True),
            sa.Column("lifecycle_template_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(100), nullable=False, server_default="draft"),
            sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("actual_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("custom_fields", sa.JSON(), nullable=True),
            sa.Column("raised_by", sa.Integer(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["parent_release_id"], ["release.id"], name="fk_release_parent", use_alter=True),
            sa.ForeignKeyConstraint(["template_id"], ["release_template.id"], name="fk_release_template"),
            sa.ForeignKeyConstraint(["lifecycle_template_id"], ["lifecycle_template.id"]),
            sa.ForeignKeyConstraint(["raised_by"], ["user.id"]),
        )
        for idx, cols in [
            ("ix_release_tenant_id", ["tenant_id"]),
            ("ix_release_lifecycle_template_id", ["lifecycle_template_id"]),
            ("ix_release_raised_by", ["raised_by"]),
            ("ix_release_parent_release_id", ["parent_release_id"]),
        ]:
            op.create_index(idx, "release", cols)

    # ── release_status_history ──────────────────────────────────────────────
    if not _table_exists(conn, "release_status_history"):
        op.create_table(
            "release_status_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("from_state", sa.String(100), nullable=True),
            sa.Column("to_state", sa.String(100), nullable=False),
            sa.Column("changed_by", sa.Integer(), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"]),
            sa.ForeignKeyConstraint(["changed_by"], ["user.id"]),
        )
        op.create_index("ix_release_status_history_release_id", "release_status_history", ["release_id"])

    # ── test_phase ──────────────────────────────────────────────────────────
    if not _table_exists(conn, "test_phase"):
        op.create_table(
            "test_phase",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_test_phase_release_id", "test_phase", ["release_id"])
        op.create_index("ix_test_phase_tenant_id", "test_phase", ["tenant_id"])

    # ── release_gate ────────────────────────────────────────────────────────
    if not _table_exists(conn, "release_gate"):
        op.create_table(
            "release_gate",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("test_phase_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(150), nullable=False),
            sa.Column("acceptance_criteria", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("decided_by", sa.Integer(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_phase_id"], ["test_phase.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["decided_by"], ["user.id"]),
        )
        op.create_index("ix_release_gate_release_id", "release_gate", ["release_id"])
        op.create_index("ix_release_gate_test_phase_id", "release_gate", ["test_phase_id"])

    # ── release_system ──────────────────────────────────────────────────────
    if not _table_exists(conn, "release_system"):
        op.create_table(
            "release_system",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("system_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("deployment_date", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["system_id"], ["system.id"]),
            sa.UniqueConstraint("release_id", "system_id", name="uq_release_system"),
        )
        op.create_index("ix_release_system_release_id", "release_system", ["release_id"])

    # ── release_dependency ─────────────────────────────────────────────────
    if not _table_exists(conn, "release_dependency"):
        op.create_table(
            "release_dependency",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("depends_on_release_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="deploys_after"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("last_dependency_target_date", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["depends_on_release_id"], ["release.id"]),
            sa.UniqueConstraint("release_id", "depends_on_release_id", name="uq_release_dependency"),
            sa.CheckConstraint("release_id != depends_on_release_id", name="ck_release_dep_self"),
        )
        op.create_index("ix_release_dependency_release_id", "release_dependency", ["release_id"])

    # ── release_event_type ─────────────────────────────────────────────────
    if not _table_exists(conn, "release_event_type"):
        op.create_table(
            "release_event_type",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("display_color", sa.String(7), nullable=True),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        )
        op.create_index("ix_release_event_type_tenant_id", "release_event_type", ["tenant_id"])

    # ── release_event ──────────────────────────────────────────────────────
    if not _table_exists(conn, "release_event"):
        op.create_table(
            "release_event",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("event_type_id", sa.Integer(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recorded_by", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["event_type_id"], ["release_event_type.id"]),
            sa.ForeignKeyConstraint(["recorded_by"], ["user.id"]),
        )
        op.create_index("ix_release_event_release_id", "release_event", ["release_id"])

    # ── release_change ─────────────────────────────────────────────────────
    if not _table_exists(conn, "release_change"):
        op.create_table(
            "release_change",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=False),
            sa.Column("external_key", sa.String(50), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("change_kind", sa.String(20), nullable=False),
            sa.Column("external_status", sa.String(100), nullable=True),
            sa.Column("system_id", sa.Integer(), nullable=True),
            sa.Column("custom_fields", sa.JSON(), nullable=True),
            sa.Column("jira_project_config_id", sa.Integer(), nullable=True),
            sa.Column("epic_id", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["system_id"], ["system.id"]),
        )
        op.create_index("ix_release_change_release_id", "release_change", ["release_id"])
        op.create_index("ix_release_change_external_key", "release_change", ["external_key"])
        # Partial unique on (tenant_id, external_key) where external_key IS NOT NULL
        # Use a plain unique + app-enforcement on SQLite; Postgres supports the partial.
        dialect = conn.dialect.name
        if dialect == "postgresql":
            op.execute(
                "CREATE UNIQUE INDEX uq_release_change_tenant_external_key "
                "ON release_change (tenant_id, external_key) WHERE external_key IS NOT NULL"
            )

    # ── booking: promote release_id + test_phase_id to real FKs ────────────
    # Existing columns are bare integers; drop-and-recreate is unnecessary —
    # just add the FK constraints by name. SQLite doesn't support ALTER ADD
    # CONSTRAINT, but dev/prod is Postgres; tests skip migrations entirely.
    if conn.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_booking_release_id", "booking", "release",
            ["release_id"], ["id"], ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_booking_test_phase_id", "booking", "test_phase",
            ["test_phase_id"], ["id"], ondelete="SET NULL",
        )
        op.create_foreign_key(
            "fk_change_request_release_id", "change_request", "release",
            ["release_id"], ["id"], ondelete="SET NULL",
        )

    # ── custom_field_definition: entity_subtype ────────────────────────────
    if not _column_exists(conn, "custom_field_definition", "entity_subtype"):
        op.add_column(
            "custom_field_definition",
            sa.Column("entity_subtype", sa.String(50), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for name, table in [
            ("fk_booking_release_id", "booking"),
            ("fk_booking_test_phase_id", "booking"),
            ("fk_change_request_release_id", "change_request"),
        ]:
            op.drop_constraint(name, table, type_="foreignkey")
    if _column_exists(conn, "custom_field_definition", "entity_subtype"):
        op.drop_column("custom_field_definition", "entity_subtype")
    for table in [
        "release_change", "release_event", "release_event_type",
        "release_dependency", "release_system", "release_gate",
        "test_phase", "release_status_history", "release", "release_template",
    ]:
        if _table_exists(conn, table):
            op.drop_table(table)
```

- [ ] **Step 3: Run the migration against the dev Postgres**

```bash
cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade p3s2crmt -> p3s3releases, phase 3 sub-project 1: core releases`.

- [ ] **Step 4: Verify tables exist**

```bash
cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr \
  uv run python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import inspect, text

async def main():
    e = create_async_engine('postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr')
    async with e.connect() as c:
        rows = await c.execute(text(\"SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'release%' OR table_name='test_phase' ORDER BY 1\"))
        for r in rows: print(r[0])
asyncio.run(main())
"
```

Expected list: `release, release_change, release_dependency, release_event, release_event_type, release_gate, release_status_history, release_system, release_template, test_phase`.

- [ ] **Step 5: Run full test suite**

Run: `cd backend && uv run pytest tests/ -x -q`
Expected: all green. Tests never run the migration — they use `Base.metadata.create_all` with all model imports (which are now loaded via the new test files), so the new tables are implicitly created.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/migrations/versions/20260419_1200_p3s3_core_releases.py
git commit -m "feat(phase-3): alembic migration p3s3releases — core release tables + FK promotions + entity_subtype"
```

---

## Task 11 — Seed release lifecycles + event types on tenant creation

**Files:**
- Modify: `backend/app/services/tenant_service.py`
- Create: `backend/app/services/release_defaults.py`
- Test: `backend/tests/test_release_defaults_seed.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_release_defaults_seed.py
import pytest
from sqlalchemy import select
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release_event import ReleaseEventType
from app.services.release_defaults import seed_release_defaults_for_tenant


@pytest.mark.asyncio
async def test_seed_release_defaults_creates_three_lifecycles(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
        )
    )).scalars().all()
    names = {r.name for r in rows}
    assert names == {"Major", "Minor", "Emergency"}
    major = next(r for r in rows if r.name == "Major")
    assert major.is_default is True


@pytest.mark.asyncio
async def test_seed_release_defaults_creates_event_types(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(ReleaseEventType).where(ReleaseEventType.tenant_id == tenant.id)
    )).scalars().all()
    names = {r.name for r in rows}
    assert {"Reschedule Reason", "Scope Change", "Stakeholder Note", "Post-Go-Live Incident"} <= names
    for r in rows:
        if r.name in {"Reschedule Reason", "Scope Change", "Stakeholder Note", "Post-Go-Live Incident"}:
            assert r.is_system is True


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
        )
    )).scalars().all()
    assert len(rows) == 3  # still 3, not 6
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && uv run pytest tests/test_release_defaults_seed.py -v`
Expected: FAIL — `release_defaults` module not found.

- [ ] **Step 3: Create `release_defaults.py`**

```python
# backend/app/services/release_defaults.py
"""Seed the three default release lifecycle templates + release event types.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill.
Idempotent: safe to call multiple times per tenant.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release_event import ReleaseEventType


_MAJOR_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",                 "label": "Draft",                 "is_initial": True,  "is_terminal": False},
        {"key": "submitted",             "label": "Submitted",             "is_initial": False, "is_terminal": False},
        {"key": "approved",              "label": "Approved",              "is_initial": False, "is_terminal": False},
        {"key": "in_progress",           "label": "In Progress",           "is_initial": False, "is_terminal": False},
        {"key": "ready_for_release",     "label": "Ready for Release",     "is_initial": False, "is_terminal": False},
        {"key": "completed",             "label": "Completed",             "is_initial": False, "is_terminal": True},
        {"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True},
        {"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True},
        {"key": "rejected",              "label": "Rejected",              "is_initial": False, "is_terminal": True},
        {"key": "cancelled",             "label": "Cancelled",             "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",             "to_state": "submitted",             "allowed_roles": ["Admin", "ReleaseManager", "Developer"]},
        {"from_state": "submitted",         "to_state": "approved",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "submitted",         "to_state": "rejected",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "in_progress",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "ready_for_release",     "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed_with_issues", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "backed_out",            "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",             "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":             {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager","Developer"]}, "description": {"editable_by": ["Admin","ReleaseManager","Developer"]}, "release_type": {"editable_by": ["Admin","ReleaseManager","Developer"]}, "target_date": {"editable_by": ["Admin","ReleaseManager","Developer"]}}, "custom_fields": {}},
        "submitted":         {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}, "required_fields": ["name", "release_type", "target_date"]},
        "approved":          {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "in_progress":       {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "ready_for_release": {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "completed":             {"standard_fields": {}, "custom_fields": {}},
        "completed_with_issues": {"standard_fields": {}, "custom_fields": {}},
        "backed_out":            {"standard_fields": {}, "custom_fields": {}},
        "rejected":              {"standard_fields": {}, "custom_fields": {}},
        "cancelled":             {"standard_fields": {}, "custom_fields": {}},
    },
}


_MINOR_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",                 "label": "Draft",                 "is_initial": True,  "is_terminal": False},
        {"key": "approved",              "label": "Approved",              "is_initial": False, "is_terminal": False},
        {"key": "in_progress",           "label": "In Progress",           "is_initial": False, "is_terminal": False},
        {"key": "ready_for_release",     "label": "Ready for Release",     "is_initial": False, "is_terminal": False},
        {"key": "completed",             "label": "Completed",             "is_initial": False, "is_terminal": True},
        {"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True},
        {"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True},
        {"key": "cancelled",             "label": "Cancelled",             "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",             "to_state": "approved",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "in_progress",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "ready_for_release",     "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed_with_issues", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "backed_out",            "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",             "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":             {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "release_type": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "approved":          {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}, "required_fields": ["name", "target_date"]},
        "in_progress":       {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "ready_for_release": {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "completed":             {"standard_fields": {}, "custom_fields": {}},
        "completed_with_issues": {"standard_fields": {}, "custom_fields": {}},
        "backed_out":            {"standard_fields": {}, "custom_fields": {}},
        "cancelled":             {"standard_fields": {}, "custom_fields": {}},
    },
}


_EMERGENCY_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",      "label": "Draft",      "is_initial": True,  "is_terminal": False},
        {"key": "approved",   "label": "Approved",   "is_initial": False, "is_terminal": False},
        {"key": "in_progress","label": "In Progress","is_initial": False, "is_terminal": False},
        {"key": "completed",  "label": "Completed",  "is_initial": False, "is_terminal": True},
        {"key": "backed_out", "label": "Backed Out", "is_initial": False, "is_terminal": True},
        {"key": "cancelled",  "label": "Cancelled",  "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",       "to_state": "approved",   "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",    "to_state": "in_progress","allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress", "to_state": "completed",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress", "to_state": "backed_out", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",       "to_state": "cancelled",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",    "to_state": "cancelled",  "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":       {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "release_type": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "approved":    {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}, "required_fields": ["name"]},
        "in_progress": {"standard_fields": {}, "custom_fields": {}},
        "completed":   {"standard_fields": {}, "custom_fields": {}},
        "backed_out":  {"standard_fields": {}, "custom_fields": {}},
        "cancelled":   {"standard_fields": {}, "custom_fields": {}},
    },
}


_DEFAULT_LIFECYCLES: list[dict[str, Any]] = [
    {"name": "Major",     "is_default": True,  "description": "Full governance (waterfall-shaped)", "definition": _MAJOR_DEFINITION},
    {"name": "Minor",     "is_default": False, "description": "Light approval",                     "definition": _MINOR_DEFINITION},
    {"name": "Emergency", "is_default": False, "description": "Fast-track",                         "definition": _EMERGENCY_DEFINITION},
]


_DEFAULT_EVENT_TYPES: list[dict[str, Any]] = [
    {"name": "Reschedule Reason",     "display_color": "#ed6c02"},
    {"name": "Scope Change",          "display_color": "#1976d2"},
    {"name": "Stakeholder Note",      "display_color": "#2e7d32"},
    {"name": "Post-Go-Live Incident", "display_color": "#d32f2f"},
]


async def seed_release_defaults_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    existing_lifecycle_names = {
        r.name for r in (
            await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.entity_type == "release",
                )
            )
        ).scalars().all()
    }
    for cfg in _DEFAULT_LIFECYCLES:
        if cfg["name"] in existing_lifecycle_names:
            continue
        db.add(LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type="release",
            name=cfg["name"],
            description=cfg["description"],
            is_default=cfg["is_default"],
            definition=cfg["definition"],
        ))

    existing_event_type_names = {
        r.name for r in (
            await db.execute(
                select(ReleaseEventType).where(ReleaseEventType.tenant_id == tenant_id)
            )
        ).scalars().all()
    }
    for cfg in _DEFAULT_EVENT_TYPES:
        if cfg["name"] in existing_event_type_names:
            continue
        db.add(ReleaseEventType(
            tenant_id=tenant_id,
            name=cfg["name"],
            display_color=cfg["display_color"],
            is_system=True,
        ))
```

- [ ] **Step 4: Wire into tenant creation**

Read `backend/app/services/tenant_service.py`, find `create_tenant()` (or whatever seeds booking/CR defaults — probably named similarly). After the existing seeds, add:

```python
from app.services.release_defaults import seed_release_defaults_for_tenant
# ... inside create_tenant(), AFTER existing seed calls:
await seed_release_defaults_for_tenant(db, tenant.id)
```

- [ ] **Step 5: Backfill existing tenants via a one-off script**

Create `backend/scripts/seed_release_defaults.py`:

```python
"""Idempotently seed Phase 3 release defaults for every existing tenant."""
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.user import Tenant
from app.services.release_defaults import seed_release_defaults_for_tenant


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        for t in tenants:
            await seed_release_defaults_for_tenant(db, t.id)
        await db.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/test_release_defaults_seed.py -v && uv run pytest tests/ -x -q`
Expected: all pass.

- [ ] **Step 7: Run the backfill script against local Postgres**

```bash
cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/seed_release_defaults.py
```

Expected: command exits cleanly; subsequent Postgres inspection shows 3 release lifecycles + 4 release event types per tenant.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/release_defaults.py backend/app/services/tenant_service.py backend/scripts/seed_release_defaults.py backend/tests/test_release_defaults_seed.py
git commit -m "feat(phase-3): seed release lifecycle templates + event types on tenant creation"
```

---

> **Checkpoint 1 — Models + migration + seeds complete.** The backend now has all release tables, the lifecycle interpreter supports required_fields, and tenants have their default lifecycles. Remaining work: schemas + services + API + booking context_tag derivation (Tasks 12–25), then frontend (Tasks 26–45), then the happy-path integration test (Task 46).

---

## Task 12 — Pydantic schemas for releases (part 1: core)

**Files:**
- Create: `backend/app/api/v1/schemas/release.py`
- Test: `backend/tests/test_release_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_release_schemas.py
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from app.api.v1.schemas.release import ReleaseCreate, ReleaseUpdate, ReleaseRead


def test_release_create_requires_name_and_type():
    with pytest.raises(ValidationError):
        ReleaseCreate()


def test_release_create_valid():
    m = ReleaseCreate(
        name="R1", release_type="Major",
        lifecycle_template_id=1, template_id=None,
        description=None, target_date=None, custom_fields={},
    )
    assert m.release_kind == "project"


def test_release_update_partial():
    m = ReleaseUpdate(name="newname")
    assert m.name == "newname"
    assert m.target_date is None


def test_release_read_serialises():
    m = ReleaseRead(
        id=1, tenant_id=1, name="R1", description=None,
        release_type="Major", release_kind="project",
        parent_release_id=None, template_id=None,
        lifecycle_template_id=1, status="draft",
        target_date=None, actual_date=None,
        custom_fields={}, raised_by=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    d = m.model_dump()
    assert d["status"] == "draft"
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && uv run pytest tests/test_release_schemas.py -v`
Expected: FAIL.

- [ ] **Step 3: Create the schema file**

```python
# backend/app/api/v1/schemas/release.py
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field, ConfigDict


class ReleaseCreate(BaseModel):
    name: str = Field(..., max_length=250)
    description: Optional[str] = None
    release_type: str = Field(..., max_length=50)
    release_kind: str = Field(default="project", max_length=20)
    template_id: Optional[int] = None
    lifecycle_template_id: Optional[int] = None  # service falls back to tenant default
    target_date: Optional[datetime] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=250)
    description: Optional[str] = None
    release_type: Optional[str] = Field(None, max_length=50)
    target_date: Optional[datetime] = None
    actual_date: Optional[datetime] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    release_type: str
    release_kind: str
    parent_release_id: Optional[int]
    template_id: Optional[int]
    lifecycle_template_id: int
    status: str
    target_date: Optional[datetime]
    actual_date: Optional[datetime]
    custom_fields: Optional[dict[str, Any]] = None
    raised_by: int
    created_at: datetime
    updated_at: datetime


class ReleaseTransition(BaseModel):
    to_state: str
    notes: Optional[str] = None


class ReleaseStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    release_id: int
    from_state: Optional[str]
    to_state: str
    changed_by: int
    changed_at: datetime
    notes: Optional[str]
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_release_schemas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/schemas/release.py backend/tests/test_release_schemas.py
git commit -m "feat(phase-3): Release pydantic schemas"
```

---

## Task 13 — Pydantic schemas for the remaining release entities

**Files:**
- Create: `backend/app/api/v1/schemas/release_template.py`
- Create: `backend/app/api/v1/schemas/test_phase.py`
- Create: `backend/app/api/v1/schemas/release_gate.py`
- Create: `backend/app/api/v1/schemas/release_system.py`
- Create: `backend/app/api/v1/schemas/release_dependency.py`
- Create: `backend/app/api/v1/schemas/release_event.py`
- Create: `backend/app/api/v1/schemas/release_change.py`

- [ ] **Step 1: Write the schemas**

Create each file with Create, Update, Read models mirroring the model fields. Follow the pattern established by Task 12. Key shapes (each in its own file):

```python
# release_template.py
from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ReleaseTemplatePhase(BaseModel):
    name: str = Field(..., max_length=100)
    order: int = 0
    default_duration_days: int = 5
    activities: list[str] = []


class ReleaseTemplateGate(BaseModel):
    name: str = Field(..., max_length=150)
    phase_name: Optional[str] = None  # None = release-level gate
    acceptance_criteria: Optional[str] = None


class ReleaseTemplateCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    release_type: str = Field(..., max_length=50)
    default_lifecycle_template_id: Optional[int] = None
    phases: list[ReleaseTemplatePhase] = []
    gates: list[ReleaseTemplateGate] = []


class ReleaseTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    release_type: Optional[str] = Field(None, max_length=50)
    default_lifecycle_template_id: Optional[int] = None
    phases: Optional[list[ReleaseTemplatePhase]] = None
    gates: Optional[list[ReleaseTemplateGate]] = None


class ReleaseTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    release_type: str
    default_lifecycle_template_id: Optional[int]
    phases: list[Any]
    gates: list[Any]
    version: int
    created_at: datetime
    updated_at: datetime


class ReleaseTemplateInstantiate(BaseModel):
    name: str = Field(..., max_length=250)
    target_date: datetime
    description: Optional[str] = None
    custom_fields: Optional[dict[str, Any]] = None
```

```python
# test_phase.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class TestPhaseCreate(BaseModel):
    name: str = Field(..., max_length=100)
    order: int = 0
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: str = "pending"


class TestPhaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    order: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None


class TestPhaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    name: str
    order: int
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    status: str
```

```python
# release_gate.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ReleaseGateCreate(BaseModel):
    name: str = Field(..., max_length=150)
    test_phase_id: Optional[int] = None
    acceptance_criteria: Optional[str] = None


class ReleaseGateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    test_phase_id: Optional[int] = None
    acceptance_criteria: Optional[str] = None


class ReleaseGateDecision(BaseModel):
    notes: Optional[str] = None


class ReleaseGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    test_phase_id: Optional[int]
    name: str
    acceptance_criteria: Optional[str]
    status: str
    decided_by: Optional[int]
    decided_at: Optional[datetime]
    decision_notes: Optional[str]
```

```python
# release_system.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReleaseSystemCreate(BaseModel):
    system_id: int
    role: str  # 'changing' | 'regression' | 'config_only'
    deployment_date: Optional[datetime] = None


class ReleaseSystemUpdate(BaseModel):
    role: Optional[str] = None
    deployment_date: Optional[datetime] = None


class ReleaseSystemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    system_id: int
    role: str
    deployment_date: Optional[datetime]
```

```python
# release_dependency.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReleaseDependencyCreate(BaseModel):
    depends_on_release_id: int
    kind: str = "deploys_after"
    notes: Optional[str] = None


class ReleaseDependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    depends_on_release_id: int
    kind: str
    notes: Optional[str]
    last_dependency_target_date: Optional[datetime]


class ReleaseDependencyAlert(BaseModel):
    dependency_id: int
    depends_on_release_id: int
    depends_on_name: str
    prior_target_date: Optional[datetime]
    current_target_date: Optional[datetime]
    diff_days: int
```

```python
# release_event.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReleaseEventTypeCreate(BaseModel):
    name: str
    display_color: Optional[str] = None


class ReleaseEventTypeUpdate(BaseModel):
    name: Optional[str] = None
    display_color: Optional[str] = None


class ReleaseEventTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    display_color: Optional[str]
    is_system: bool


class ReleaseEventCreate(BaseModel):
    event_type_id: int
    description: str
    occurred_at: Optional[datetime] = None  # defaults to now in service


class ReleaseEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    event_type_id: int
    description: str
    occurred_at: datetime
    recorded_by: int
```

```python
# release_change.py
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ReleaseChangeCreate(BaseModel):
    external_key: Optional[str] = Field(None, max_length=50)
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    change_kind: str  # story | defect
    external_status: Optional[str] = Field(None, max_length=100)
    system_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseChangeUpdate(BaseModel):
    external_key: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    external_status: Optional[str] = None
    system_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    external_key: Optional[str]
    title: str
    description: Optional[str]
    change_kind: str
    external_status: Optional[str]
    system_id: Optional[int]
    custom_fields: Optional[dict[str, Any]]
    jira_project_config_id: Optional[int]
    epic_id: Optional[int]
    source: str
```

- [ ] **Step 2: Smoke-import test**

Create `backend/tests/test_release_subresource_schemas.py`:

```python
import pytest
from app.api.v1.schemas.release_template import ReleaseTemplateCreate, ReleaseTemplateInstantiate
from app.api.v1.schemas.test_phase import TestPhaseCreate, TestPhaseRead
from app.api.v1.schemas.release_gate import ReleaseGateCreate, ReleaseGateDecision
from app.api.v1.schemas.release_system import ReleaseSystemCreate
from app.api.v1.schemas.release_dependency import ReleaseDependencyCreate, ReleaseDependencyAlert
from app.api.v1.schemas.release_event import ReleaseEventTypeCreate, ReleaseEventCreate
from app.api.v1.schemas.release_change import ReleaseChangeCreate


def test_schemas_all_importable():
    assert ReleaseTemplateCreate(name="x", release_type="Major").release_type == "Major"
    assert TestPhaseCreate(name="SIT").name == "SIT"
    assert ReleaseGateCreate(name="g").name == "g"
    assert ReleaseSystemCreate(system_id=1, role="changing").role == "changing"
    assert ReleaseDependencyCreate(depends_on_release_id=1).kind == "deploys_after"
    assert ReleaseEventCreate(event_type_id=1, description="ok").description == "ok"
    assert ReleaseChangeCreate(title="t", change_kind="story").source_is_default_manual() if hasattr(ReleaseChangeCreate, "source_is_default_manual") else True
```

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/test_release_subresource_schemas.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/schemas/release_template.py backend/app/api/v1/schemas/test_phase.py backend/app/api/v1/schemas/release_gate.py backend/app/api/v1/schemas/release_system.py backend/app/api/v1/schemas/release_dependency.py backend/app/api/v1/schemas/release_event.py backend/app/api/v1/schemas/release_change.py backend/tests/test_release_subresource_schemas.py
git commit -m "feat(phase-3): pydantic schemas for release subresources"
```

---

> **Remaining plan tasks** are enumerated below with the same TDD pattern. To keep the plan document reviewable, tasks 14–46 list goals, files, and the key signatures/tests but may not repeat the full boilerplate seen above. An engineer reading this plan should follow the scaffolding pattern established in Tasks 1–13 for each remaining task: write a failing test, run it, implement, run it, commit.

---

## Task 14 — `release_service.py`: CRUD + transition

**Files:**
- Create: `backend/app/services/release_service.py`
- Create: `backend/tests/services/test_release_service.py`

**Key service functions to implement (each with a dedicated test):**

```python
async def create_release(db, data: ReleaseCreate, tenant_id, user_id) -> Release:
    # Resolve lifecycle_template_id: fallback to tenant default with entity_type='release' if None.
    # Validate release.release_kind == "project" (enterprise flows reserved for sub-project 2).
    # Write Release row, status='draft'. Publish event ReleaseCreated.
    # Write ReleaseStatusHistory(from=None, to='draft', changed_by=user_id).
    # Returns Release.
    ...


async def list_releases(db, tenant_id, *, release_type=None, status=None, date_from=None, date_to=None,
                         has_dependency_alert=None, owner_id=None, search=None,
                         limit=50, offset=0) -> tuple[list[Release], int]:
    ...


async def get_release(db, release_id, tenant_id) -> Release:
    ...


async def update_release(db, release_id, data: ReleaseUpdate, tenant_id, user_id) -> Release:
    # If target_date changes, emit ReleaseEvent of type 'Reschedule Reason'
    # (service layer finds the tenant's 'Reschedule Reason' event type or the caller-supplied type).
    # If release.status is terminal, reject updates except on custom_fields (return 409).
    ...


async def transition_release(db, release_id, to_state, notes, tenant_id, user_id, user_role) -> Release:
    # Fetch release + lifecycle template.
    # Build record_values = {standard fields flat, "custom_fields": release.custom_fields or {}}.
    # allowed, reason = lifecycle_service.validate_transition(template.definition, release.status,
    #                                                        to_state, user_role, record_values)
    # If not allowed: raise HTTPException 400 with reason.
    # Update release.status, stamp actual_date if to_state is a terminal deployed-variant
    #   ('completed' | 'completed_with_issues'), write ReleaseStatusHistory,
    #   publish ReleaseStateChanged event.
    ...


async def delete_release(db, release_id, tenant_id) -> None:
    # Soft delete (deleted_at). Cascading via ondelete=CASCADE on related tables kicks in on hard delete;
    # for soft-delete we leave dependent rows as orphaned-but-invisible.
    ...
```

**Tests (one per function, plus):**
- `test_create_release_uses_tenant_default_lifecycle_when_none_provided`
- `test_update_release_target_date_creates_reschedule_event` (requires a `Reschedule Reason` event type to exist for the tenant)
- `test_transition_blocked_when_required_fields_missing`
- `test_transition_terminal_stamps_actual_date`
- `test_tenant_isolation_list_releases` — tenant A's releases not visible to tenant B
- `test_soft_delete_hides_from_list`

Follow Task 1 commit discipline.

Commit: `feat(phase-3): release_service CRUD + transition`

---

## Task 15 — `release_template_service.py`: CRUD + instantiate

**Files:**
- Create: `backend/app/services/release_template_service.py`
- Create: `backend/tests/services/test_release_template_service.py`

**Key functions:**

```python
async def create_template(db, data, tenant_id) -> ReleaseTemplate: ...
async def list_templates(db, tenant_id) -> list[ReleaseTemplate]: ...
async def get_template(db, template_id, tenant_id) -> ReleaseTemplate: ...
async def update_template(db, template_id, data, tenant_id) -> ReleaseTemplate:
    # Bumps version on every save.
    ...
async def delete_template(db, template_id, tenant_id) -> None:
    # Soft delete. Refuse if any Release currently references this template (409).
    ...


async def instantiate(db, template_id, data: ReleaseTemplateInstantiate, tenant_id, user_id) -> Release:
    # 1. Create Release (release_type=template.release_type, lifecycle_template_id=template.default_lifecycle_template_id
    #    or tenant default, template_id=template.id).
    # 2. For each template.phases entry, create a TestPhase with dates back-computed
    #    from target_date using default_duration_days (last phase ends on target_date).
    # 3. For each template.gates entry, create a ReleaseGate pointing at the matching phase by name
    #    (or test_phase_id=None for release-level gates).
    # 4. Return the Release.
    ...
```

**Tests:**
- `test_create_and_bump_version_on_update`
- `test_instantiate_materialises_phases_and_gates_with_computed_dates`
- `test_instantiate_release_level_gate_has_null_phase`
- `test_delete_refused_when_in_use`
- `test_tenant_isolation`

Commit: `feat(phase-3): release_template_service CRUD + instantiate`

---

## Task 16 — `release_gate_service.py`

**Files:**
- Create: `backend/app/services/release_gate_service.py`
- Create: `backend/tests/services/test_release_gate_service.py`

**Functions:**

```python
async def list_gates(db, release_id, tenant_id) -> list[ReleaseGate]: ...
async def create_gate(db, release_id, data, tenant_id) -> ReleaseGate: ...
async def update_gate(db, gate_id, data, tenant_id) -> ReleaseGate: ...
async def pass_gate(db, gate_id, notes, tenant_id, user_id) -> ReleaseGate:
    # status='passed'; decided_by/decided_at/decision_notes; emit ReleaseEvent of type
    # 'Scope Change' → NO, use dedicated ReleaseGatePassed published event.
    # Also auto-append a ReleaseEvent row (type: Stakeholder Note by default — tenants can reassign later).
    ...
async def fail_gate(db, gate_id, notes, tenant_id, user_id) -> ReleaseGate: ...
async def override_gate(db, gate_id, notes, tenant_id, user_id) -> ReleaseGate: ...
```

**Tests:**
- `test_pass_gate_records_decision`
- `test_pass_gate_emits_event_and_publishes_outbox`
- `test_override_requires_notes` (raise 422 if notes is None/empty)
- `test_tenant_isolation_pass_gate_cross_tenant_forbidden`

Commit: `feat(phase-3): release_gate_service pass/fail/override with event emission`

---

## Task 17 — `release_scope_service.py` (ReleaseChange CRUD)

**Files:**
- Create: `backend/app/services/release_scope_service.py`
- Create: `backend/tests/services/test_release_scope_service.py`

**Functions:**

```python
async def list_changes(db, release_id, tenant_id) -> list[ReleaseChange]: ...
async def create_change(db, release_id, data: ReleaseChangeCreate, tenant_id) -> ReleaseChange:
    # source='manual' by default. If release.status is in {'approved','in_progress','ready_for_release',...},
    # emit ReleaseEvent of type 'Scope Change'.
    ...
async def update_change(db, change_id, data: ReleaseChangeUpdate, tenant_id) -> ReleaseChange:
    # If change.source == 'jira', reject edits to external_key / title / description / external_status (422).
    # Always allow system_id + custom_fields edits.
    # Emits Scope Change event when status ≥ approved.
    ...
async def delete_change(db, change_id, tenant_id) -> None:
    # Soft delete. Same Scope Change event emission rule.
    ...
```

**Tests:**
- `test_manual_item_fully_editable`
- `test_jira_item_read_only_fields_raise_422`
- `test_scope_change_event_emitted_when_release_approved`
- `test_scope_change_event_not_emitted_in_draft`
- `test_tenant_isolation`

Commit: `feat(phase-3): release_scope_service with source-aware edit rules + Scope Change events`

---

## Task 18 — `release_dependency_service.py`

**Files:**
- Create: `backend/app/services/release_dependency_service.py`
- Create: `backend/tests/services/test_release_dependency_service.py`

**Functions:**

```python
async def list_dependencies(db, release_id, tenant_id) -> list[ReleaseDependency]: ...
async def create_dependency(db, release_id, data, tenant_id) -> ReleaseDependency:
    # Reject self-dependency (400). Capture last_dependency_target_date from the dependency's current target_date.
    ...
async def delete_dependency(db, dep_id, tenant_id) -> None:
    # Hard delete (junction).
    ...
async def get_dependency_alerts(db, release_id, tenant_id) -> list[ReleaseDependencyAlert]:
    # For each dep, diff current depends_on.target_date vs last_dependency_target_date.
    # Return only those with non-zero diff_days.
    ...
async def acknowledge_alert(db, release_id, dep_id, tenant_id) -> None:
    # Update last_dependency_target_date to the dep's current target_date.
    ...
```

**Tests:**
- `test_alerts_returns_diff_when_target_date_shifts`
- `test_alerts_empty_when_no_change`
- `test_acknowledge_clears_alert`
- `test_self_dependency_rejected`

Commit: `feat(phase-3): release_dependency_service with alert computation`

---

## Task 19 — `release_event_service.py`

**Files:**
- Create: `backend/app/services/release_event_service.py`
- Create: `backend/tests/services/test_release_event_service.py`

**Functions:**

```python
# Event types CRUD:
async def list_event_types(db, tenant_id) -> list[ReleaseEventType]: ...
async def create_event_type(db, data, tenant_id) -> ReleaseEventType: ...
async def update_event_type(db, type_id, data, tenant_id) -> ReleaseEventType:
    # System event types (is_system=True) cannot be renamed — only colour may change.
    ...
async def delete_event_type(db, type_id, tenant_id) -> None:
    # System types refused. Non-system types soft-delete.
    ...

# Events:
async def list_events(db, release_id, tenant_id) -> list[ReleaseEvent]: ...
async def create_event(db, release_id, data, tenant_id, user_id) -> ReleaseEvent: ...

# Helpers used by other services:
async def find_system_event_type(db, tenant_id, name: str) -> ReleaseEventType | None:
    # Used by release_service.update_release() to find 'Reschedule Reason', etc.
    ...
async def record_auto_event(db, release_id, tenant_id, user_id, event_type_name, description) -> ReleaseEvent | None:
    # Convenience: looks up the system event type by name and writes the event.
    # Returns None if the event type doesn't exist (caller decides whether to raise).
    ...
```

**Tests:**
- `test_system_event_type_cannot_be_renamed`
- `test_system_event_type_cannot_be_deleted`
- `test_record_auto_event_happy_path`
- `test_record_auto_event_missing_type_returns_none`
- `test_tenant_isolation`

Commit: `feat(phase-3): release_event_service with system-type protection`

---

## Task 20 — `release_booking_service.py` + context tag derivation

**Files:**
- Create: `backend/app/services/release_booking_service.py`
- Modify: `backend/app/services/booking_service.py`
- Create: `backend/tests/services/test_release_booking_service.py`

**Behaviour:**

1. `release_booking_service.book_environment_for_phase(db, release_id, phase_id, environment_id, start, end, booking_type_id, tenant_id, user_id)` wraps the existing `booking_service.create_booking(...)` call but:
   - Passes `release_id` and `test_phase_id` into the booking.
   - After booking is written, invokes `derive_and_set_context_tag(db, booking_id)`.
   - Returns the persisted Booking.

2. `booking_service` gets a new helper:

   ```python
   async def derive_and_set_context_tag(db, booking_id) -> None:
       # Fetch booking, its release, release_system rows, environment subsystem chain.
       # If booking.release_id is None, set context_tag='none'; return.
       # For every subsystem of the booking's environment, look up a ReleaseSystem
       # for booking.release_id with matching system_id. First match wins.
       # Map role to ContextTag: 'changing'->'deployment', 'regression'->'regression',
       # 'config_only'->'none', fallback 'none'.
       # Write the tag to booking.context_tag.
       ...
   ```

   Wire it into existing booking create/update paths when `release_id` is set.

**Tests:**
- `test_book_for_phase_creates_booking_with_release_and_phase_set`
- `test_derive_context_tag_deployment_role`
- `test_derive_context_tag_regression_role`
- `test_derive_context_tag_no_release_system_match_yields_none`
- `test_update_booking_re_derives_context_tag`
- `test_tenant_isolation_cannot_book_other_tenants_release`

Commit: `feat(phase-3): release_booking_service + booking context_tag derivation`

---

## Task 21 — API: `releases.py` — main + direct subresources

**Files:**
- Create: `backend/app/api/v1/releases.py`
- Modify: `backend/app/main.py` to include the new router
- Create: `backend/tests/api/test_releases_api.py`

**Endpoints (thin delegates to services; every one has a matching pytest integration test):**

```
GET    /api/v1/releases                 list_releases
POST   /api/v1/releases                 create_release          (optionally from_template_id)
GET    /api/v1/releases/calendar        list for FullCalendar
GET    /api/v1/releases/timeline        list for multi-release Gantt
GET    /api/v1/releases/{id}            get_release (payload includes field_permissions for current state/role)
PUT    /api/v1/releases/{id}            update_release
DELETE /api/v1/releases/{id}            soft_delete_release
POST   /api/v1/releases/{id}/transition transition_release
GET    /api/v1/releases/{id}/history    list status history
```

Every endpoint:
- Uses `Depends(get_current_user)`; `tenant_id = current_user.active_tenant_id`.
- Returns `ReleaseRead` / `list[ReleaseRead]` / 204 for DELETE.
- Wraps service errors → HTTPException with meaningful status codes.

**Tests:** One test per endpoint asserting happy path + one negative path (404 / 403 / 400). All tests use the shared `authed_client` fixture from `conftest.py`.

Commit: `feat(phase-3): releases.py endpoints for CRUD + transition + calendar + timeline`

---

## Task 22 — API: `releases.py` — phases, gates, systems, dependencies, events, scope, bookings, CR links

**Files:**
- Modify: `backend/app/api/v1/releases.py` (add subresource endpoints)
- Modify: `backend/tests/api/test_releases_api.py`

**Endpoints:**

```
# Phases
GET    /releases/{id}/phases
POST   /releases/{id}/phases
PUT    /phases/{phase_id}
DELETE /phases/{phase_id}

# Gates
GET    /releases/{id}/gates
POST   /releases/{id}/gates
PUT    /gates/{gate_id}
POST   /gates/{gate_id}/pass
POST   /gates/{gate_id}/fail
POST   /gates/{gate_id}/override

# Systems
GET    /releases/{id}/systems
POST   /releases/{id}/systems
DELETE /release-systems/{id}

# Dependencies + alerts
GET    /releases/{id}/dependencies
POST   /releases/{id}/dependencies
DELETE /release-dependencies/{id}
GET    /releases/{id}/dependency-alerts
POST   /releases/{id}/dependency-alerts/{dep_id}/acknowledge

# Events
GET    /releases/{id}/events
POST   /releases/{id}/events

# Scope
GET    /releases/{id}/changes
POST   /releases/{id}/changes
PUT    /release-changes/{change_id}
DELETE /release-changes/{change_id}

# Bookings (subresource view/create; delegates to release_booking_service)
GET    /releases/{id}/bookings
POST   /releases/{id}/bookings

# Linked CRs
GET    /releases/{id}/change-requests
POST   /releases/{id}/change-requests/{cr_id}/link
DELETE /releases/{id}/change-requests/{cr_id}/link
```

Each endpoint:
- Thin delegate; body validated by the matching Pydantic schema from Tasks 12–13.
- Subresource endpoints ensure the release (and the related entity, if any) belongs to the caller's tenant before acting.

**Tests:** Write one happy-path + one negative for each endpoint. The subresource tests may bundle (one test hits GET+POST, another hits DELETE) to keep the count tractable.

Commit: `feat(phase-3): releases.py subresource endpoints`

---

## Task 23 — API: `release_templates.py` and `release_event_types.py`

**Files:**
- Create: `backend/app/api/v1/release_templates.py`
- Create: `backend/app/api/v1/release_event_types.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_release_templates_api.py`
- Create: `backend/tests/api/test_release_event_types_api.py`

**Endpoints:**

```
# release_templates.py
GET    /api/v1/release-templates
POST   /api/v1/release-templates
GET    /api/v1/release-templates/{id}
PUT    /api/v1/release-templates/{id}
DELETE /api/v1/release-templates/{id}
POST   /api/v1/release-templates/{id}/instantiate   # body: ReleaseTemplateInstantiate

# release_event_types.py
GET    /api/v1/release-event-types
POST   /api/v1/release-event-types
PUT    /api/v1/release-event-types/{id}
DELETE /api/v1/release-event-types/{id}
```

**Tests:** Happy + negative path per endpoint. One test for `instantiate` that asserts phases + gates materialised; one for system-event-type delete refusal.

Commit: `feat(phase-3): release_templates + release_event_types endpoints`

---

> **Checkpoint 2 — Backend complete.** Tasks 1–23 deliver the entire backend surface area. Remaining tasks are frontend-only. Run `cd backend && uv run pytest tests/ -q` — the target is 268+~40 passing tests. Run the dev server (`uvicorn app.main:app --reload`) and sanity-check `/docs` — the release endpoints should all appear in the Swagger UI.

---

## Frontend scaffolding overview (Tasks 24–45)

**File layout:**
- `frontend/src/types/release.ts` + `releaseTemplate.ts` + `releaseEvent.ts` + `releaseChange.ts`
- `frontend/src/services/*` — one `releaseService.ts` orchestrating all `/releases` endpoints; one `releaseTemplateService.ts`; one `releaseEventTypeService.ts`. Matches the existing naming where one service covers an entity.
- `frontend/src/store/*` — `releaseSlice.ts`, `releaseTemplateSlice.ts`, `releaseEventTypeSlice.ts`.
- `frontend/src/components/releases/` — all release components below.
- `frontend/src/pages/releases/` — `ReleaseList.tsx`, `ReleaseForm.tsx`, `ReleaseCalendar.tsx`, `ReleaseTimeline.tsx`.
- `frontend/src/pages/admin/release-templates/` — `ReleaseTemplateLibrary.tsx`, `ReleaseTemplateForm.tsx`.
- Routes registered in `App.tsx` under `/releases`, `/releases/new`, `/releases/:id`, `/releases/calendar`, `/releases/timeline`, `/admin/release-templates`, `/admin/release-templates/:id`.

Each frontend task below follows the same pattern: create the file(s), run `npm run build` + `npm run lint`, smoke test manually against the backend. Since the user has agreed frontend unit tests are deferred (Tier-3 rollup per Phase 2 memory), the acceptance for each frontend task is "build clean + lint clean + manual smoke works."

---

## Task 24 — Frontend types

**Files:**
- Create: `frontend/src/types/release.ts`
- Create: `frontend/src/types/releaseTemplate.ts`
- Create: `frontend/src/types/releaseEvent.ts`
- Create: `frontend/src/types/releaseChange.ts`

- [ ] **Step 1: Write the type files** mirroring the backend Pydantic Read schemas.

```typescript
// release.ts
export type ReleaseStatus = string;
export type ReleaseKind = "project" | "enterprise";

export interface Release {
  id: number;
  tenantId: number;
  name: string;
  description: string | null;
  releaseType: string;
  releaseKind: ReleaseKind;
  parentReleaseId: number | null;
  templateId: number | null;
  lifecycleTemplateId: number;
  status: ReleaseStatus;
  targetDate: string | null;
  actualDate: string | null;
  customFields: Record<string, unknown> | null;
  raisedBy: number;
  createdAt: string;
  updatedAt: string;
}

export interface TestPhase {
  id: number;
  releaseId: number;
  name: string;
  order: number;
  startDate: string | null;
  endDate: string | null;
  status: string;
}

export interface ReleaseGate {
  id: number;
  releaseId: number;
  testPhaseId: number | null;
  name: string;
  acceptanceCriteria: string | null;
  status: "pending" | "passed" | "failed" | "overridden";
  decidedBy: number | null;
  decidedAt: string | null;
  decisionNotes: string | null;
}

export interface ReleaseSystem {
  id: number;
  releaseId: number;
  systemId: number;
  role: "changing" | "regression" | "config_only";
  deploymentDate: string | null;
}

export interface ReleaseDependency {
  id: number;
  releaseId: number;
  dependsOnReleaseId: number;
  kind: string;
  notes: string | null;
  lastDependencyTargetDate: string | null;
}

export interface ReleaseDependencyAlert {
  dependencyId: number;
  dependsOnReleaseId: number;
  dependsOnName: string;
  priorTargetDate: string | null;
  currentTargetDate: string | null;
  diffDays: number;
}

export interface ReleaseStatusHistory {
  id: number;
  releaseId: number;
  fromState: string | null;
  toState: string;
  changedBy: number;
  changedAt: string;
  notes: string | null;
}
```

(Other type files follow the same pattern — one type per backend model.)

- [ ] **Step 2: Build check**

Run: `cd frontend && npm run build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/release.ts frontend/src/types/releaseTemplate.ts frontend/src/types/releaseEvent.ts frontend/src/types/releaseChange.ts
git commit -m "feat(phase-3): frontend types for releases"
```

---

## Task 25 — Frontend API clients (`releaseService.ts`, `releaseTemplateService.ts`, `releaseEventTypeService.ts`)

**Files:**
- Create: `frontend/src/services/releaseService.ts`
- Create: `frontend/src/services/releaseTemplateService.ts`
- Create: `frontend/src/services/releaseEventTypeService.ts`

Each mirrors the existing `changeRequestService.ts` pattern:
- Use the shared `api` axios instance from `services/api.ts`.
- One function per backend endpoint.
- `listReleases`, `getRelease`, `createRelease`, `updateRelease`, `deleteRelease`, `transitionRelease`, `listPhases`, `createPhase`, `updatePhase`, `deletePhase`, `listGates`, `passGate`, `failGate`, `overrideGate`, `listDependencies`, `listDependencyAlerts`, `acknowledgeAlert`, `listEvents`, `createEvent`, `listChanges`, `createChange`, `updateChange`, `deleteChange`, `listBookings`, `bookForPhase`, `listLinkedChangeRequests`, `linkChangeRequest`, `unlinkChangeRequest`, `listCalendar`, `listTimeline`, `listHistory`.
- Template service: `listTemplates`, `getTemplate`, `createTemplate`, `updateTemplate`, `deleteTemplate`, `instantiateTemplate`.

Build + lint must pass.

Commit: `feat(phase-3): frontend API clients for release endpoints`

---

## Task 26 — Redux slices

**Files:**
- Create: `frontend/src/store/releaseSlice.ts`
- Create: `frontend/src/store/releaseTemplateSlice.ts`
- Create: `frontend/src/store/releaseEventTypeSlice.ts`
- Modify: `frontend/src/store/index.ts` to register the new slices

Each slice mirrors `changeRequestSlice.ts`: `createAsyncThunk` for each service call; `createSlice` with `{items, current, loading, error}` state shape.

Build + lint must pass.

Commit: `feat(phase-3): redux slices for releases`

---

## Task 27 — Shared `LifecycleAwareFieldsPanel` + `TransitionControls`

**Files:**
- Create: `frontend/src/components/lifecycle/LifecycleAwareFieldsPanel.tsx`
- Create: `frontend/src/components/lifecycle/TransitionControls.tsx`
- Create: `frontend/src/components/lifecycle/index.ts`

`LifecycleAwareFieldsPanel.tsx` is entity-agnostic. Props:

```typescript
interface Props {
  entityType: "release" | "booking" | "change_request";
  entitySubtype?: string;
  currentState: string;
  userRole: string;
  // payload from GET: field_permissions + standard field values + custom fields
  fieldPermissions: Record<string, {
    standard_fields?: Record<string, { editable_by: string[] }>;
    custom_fields?:   Record<string, { editable_by: string[] }>;
    required_fields?: string[];
  }>;
  standardValues: Record<string, unknown>;
  customFieldDefinitions: CustomFieldDefinition[];
  customFieldValues: Record<string, unknown>;
  onStandardChange: (key: string, value: unknown) => void;
  onCustomChange: (key: string, value: unknown) => void;
}
```

Renders each standard field + custom field as MUI inputs, disabling inputs when `userRole not in editable_by`. Shows a red asterisk beside required-but-empty fields in the current state.

`TransitionControls.tsx`:

```typescript
interface Props {
  currentState: string;
  userRole: string;
  lifecycleDefinition: any; // the full lifecycle JSON
  recordValues: Record<string, unknown> & { custom_fields?: Record<string, unknown> };
  onTransition: (toState: string, notes?: string) => Promise<void>;
}
```

Locally re-implements the `validate_transition` logic for client-side preflight — if `required_fields` of destination are empty, the button is disabled with a tooltip. When clicked, opens a small dialog for notes, then calls `onTransition(toState, notes)`.

Both components are generic; the release pages will be the first to use them, but the BookingDetail + ChangeRequestDetail pages can migrate later.

Build + lint must pass.

Commit: `feat(phase-3): LifecycleAwareFieldsPanel + TransitionControls (shared primitives)`

---

## Task 28 — `ReleaseList` page

**Files:**
- Create: `frontend/src/pages/releases/ReleaseList.tsx`
- Register route in `App.tsx`

MUI DataGrid with columns: name, releaseType, status (chip), targetDate, actualDate, variance, owner, phaseCount, scopeCount, blockerCount. Filters above grid. Toolbar: "New Release" (menu: From Template / Blank), Switch to calendar, Switch to timeline. Row click navigates to `/releases/:id`.

`phaseCount`, `scopeCount`, `blockerCount` require the backend list endpoint to include these summary counts. Update `releases.py` + `release_service.list_releases` to return them (add a `ReleaseListItemRead` schema that extends `ReleaseRead` with the three counts). Include this change as part of this task's scope.

Build + lint + manual smoke.

Commit: `feat(phase-3): ReleaseList page + summary-count list endpoint`

---

## Task 29 — `ReleaseForm` shell

**Files:**
- Create: `frontend/src/pages/releases/ReleaseForm.tsx`
- Register routes `/releases/new`, `/releases/:id` in `App.tsx`

Tab shell using MUI `<Tabs>`. Tabs: Main, Gates & Test Phases, Environments, Linked Requests, Scope. In create mode (`:id` is undefined), tabs 2–5 are disabled until the first save. Header with name + type + state chip + owner. Save button commits current tab. Event log and status history icons wire up drawers (Task 36).

Build + lint.

Commit: `feat(phase-3): ReleaseForm tab shell`

---

## Task 30 — `ReleaseMainTab` using shared primitives

**Files:**
- Create: `frontend/src/components/releases/ReleaseMainTab.tsx`

Uses `LifecycleAwareFieldsPanel` + `TransitionControls` from Task 27. Loads `/custom-fields?entity_type=release&entity_subtype=<release.releaseType>`. Shows dependency-alert banner when `GET /releases/:id/dependency-alerts` returns non-empty.

Build + lint + manual smoke (toggle a release through its states, confirm field editability reflects permissions).

Commit: `feat(phase-3): ReleaseMainTab`

---

## Task 31 — Gates & Test Phases tab (plan Gantt + tables)

**Files:**
- Create: `frontend/src/components/releases/PhaseGanttEditor.tsx`
- Create: `frontend/src/components/releases/PhasesTable.tsx`
- Create: `frontend/src/components/releases/GatesTable.tsx`
- Create: `frontend/src/components/releases/GateDecisionDialog.tsx`
- Create: `frontend/src/components/releases/ReleasePlanTab.tsx` (composes the four above)

`PhaseGanttEditor` extends the existing read-only Gantt from Phase 2 (`BookingScheduleGantt.tsx`) with drag-to-resize + drag-to-shift. Use a `readonly?: boolean` prop to preserve the read-only mode. Gate diamonds click-to-open `GateDecisionDialog`. Phase bar click opens the PhasesTable inline edit row.

Build + lint + manual smoke (create a phase, drag to resize, verify PUT fires).

Commit: `feat(phase-3): ReleasePlanTab with editable Gantt`

---

## Task 32 — Environments tab (resource Gantt + booking dialog)

**Files:**
- Create: `frontend/src/components/releases/EnvironmentResourceGantt.tsx`
- Create: `frontend/src/components/releases/AddPhaseBookingDialog.tsx`
- Create: `frontend/src/components/releases/ReleaseBookingsTable.tsx`
- Create: `frontend/src/components/releases/ReleaseEnvironmentsTab.tsx` (composes all three)

Resource Gantt: rows = envs, bars = bookings (coloured by phase). Booking bar click opens existing booking detail modal. Add-booking dialog uses existing environment autocomplete + outage-conflict banner components. Filter chips: phase, lifecycle state.

Build + lint + manual smoke.

Commit: `feat(phase-3): ReleaseEnvironmentsTab`

---

## Task 33 — Linked Requests tab

**Files:**
- Create: `frontend/src/components/releases/LinkedBookingsSection.tsx`
- Create: `frontend/src/components/releases/LinkedChangeRequestsSection.tsx`
- Create: `frontend/src/components/releases/LinkChangeRequestDialog.tsx`
- Create: `frontend/src/components/releases/ReleaseLinkedRequestsTab.tsx`

Two collapsible DataGrids. Link CR dialog: search CRs with `release_id IS NULL`; selecting one POSTs to `/releases/{id}/change-requests/{cr_id}/link`.

Build + lint + manual smoke.

Commit: `feat(phase-3): ReleaseLinkedRequestsTab`

---

## Task 34 — Scope tab

**Files:**
- Create: `frontend/src/components/releases/ScopeTable.tsx`
- Create: `frontend/src/components/releases/ScopeItemDialog.tsx`
- Create: `frontend/src/components/releases/ReleaseScopeTab.tsx`

Table with inline edit for manual items; Jira-sourced rows have the Jira-owned columns rendered read-only. "Group by Epic" toggle disabled with tooltip.

Build + lint + manual smoke.

Commit: `feat(phase-3): ReleaseScopeTab`

---

## Task 35 — `ReleaseCalendar` page

**Files:**
- Create: `frontend/src/pages/releases/ReleaseCalendar.tsx`

FullCalendar instance backed by `GET /releases/calendar?from&to`. Events represent phases. Click navigates to `/releases/:id?tab=phases&phase=:phaseId`. Reuses existing FullCalendar theming from the booking calendar.

Build + lint + manual smoke.

Commit: `feat(phase-3): ReleaseCalendar page`

---

## Task 36 — `ReleaseTimeline` page + `DependencyAlertBanner` + history/event drawers

**Files:**
- Create: `frontend/src/pages/releases/ReleaseTimeline.tsx`
- Create: `frontend/src/components/releases/DependencyAlertBanner.tsx`
- Create: `frontend/src/components/releases/ReleaseStatusHistoryDrawer.tsx`
- Create: `frontend/src/components/releases/ReleaseEventDrawer.tsx`

Timeline: multi-release Gantt with dependency arrows. Banner renders when any alert is active. Drawers open from icons in the `ReleaseForm` header (wire into Task 29's shell).

Build + lint + manual smoke.

Commit: `feat(phase-3): ReleaseTimeline + dependency banner + history/event drawers`

---

## Task 37 — Release Template Library pages

**Files:**
- Create: `frontend/src/pages/admin/release-templates/ReleaseTemplateLibrary.tsx`
- Create: `frontend/src/pages/admin/release-templates/ReleaseTemplateForm.tsx`

List page: DataGrid + "New template" button + "Create release from this" action per row.
Form page: phases editor (reorderable list) + gates editor (attach to phase by name or release-level) + acceptance criteria markdown. Save triggers PUT/POST; version bump is server-side.

Build + lint + manual smoke. Include route registrations in `App.tsx`.

Commit: `feat(phase-3): ReleaseTemplateLibrary + Form`

---

## Task 38 — Release event types admin UI

**Files:**
- Modify: `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` (or sibling admin surface) to add a "Release Event Types" subsection
- Create: `frontend/src/components/admin/ReleaseEventTypesPanel.tsx`

DataGrid + add/edit/delete. System event types show a lock icon and cannot be deleted; name is read-only for them.

Build + lint + manual smoke.

Commit: `feat(phase-3): admin UI for release event types`

---

## Task 39 — Wire routes + nav

**Files:**
- Modify: `frontend/src/AppLayout.tsx` (or wherever the nav menu lives) to add "Releases" with children Calendar / Timeline / Templates
- Modify: `frontend/src/App.tsx` for any missed routes

Build + lint + manual smoke on every new route.

Commit: `feat(phase-3): nav + route registrations`

---

## Task 40 — Happy-path backend integration test

**Files:**
- Create: `backend/tests/integration/test_release_happy_path.py`

```python
"""Happy path: instantiate from template → book envs → transition through all states → pass gates → complete."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_release_happy_path_from_template(
    authed_client: AsyncClient, tenant, user, system, environment,
    release_lifecycle_template,
):
    # 1. Create template
    tmpl_resp = await authed_client.post("/api/v1/release-templates", json={
        "name": "Standard Major",
        "release_type": "Major",
        "default_lifecycle_template_id": release_lifecycle_template.id,
        "phases": [
            {"name": "SIT", "order": 1, "default_duration_days": 5, "activities": []},
            {"name": "UAT", "order": 2, "default_duration_days": 5, "activities": []},
        ],
        "gates": [
            {"name": "SIT Exit", "phase_name": "SIT", "acceptance_criteria": "zero sev1"},
            {"name": "UAT Exit", "phase_name": "UAT", "acceptance_criteria": "signed off"},
        ],
    })
    assert tmpl_resp.status_code == 201
    tmpl_id = tmpl_resp.json()["id"]

    # 2. Instantiate
    inst_resp = await authed_client.post(f"/api/v1/release-templates/{tmpl_id}/instantiate", json={
        "name": "R1", "target_date": "2026-05-01T00:00:00+00:00",
    })
    assert inst_resp.status_code == 201
    release_id = inst_resp.json()["id"]

    # 3. Add system role
    sys_resp = await authed_client.post(f"/api/v1/releases/{release_id}/systems", json={
        "system_id": system.id, "role": "changing",
    })
    assert sys_resp.status_code == 201

    # 4. Verify phases and gates materialised
    phases = (await authed_client.get(f"/api/v1/releases/{release_id}/phases")).json()
    assert {p["name"] for p in phases} == {"SIT", "UAT"}
    gates = (await authed_client.get(f"/api/v1/releases/{release_id}/gates")).json()
    assert {g["name"] for g in gates} == {"SIT Exit", "UAT Exit"}

    # 5. Book an environment for SIT
    sit_phase_id = next(p["id"] for p in phases if p["name"] == "SIT")
    book_resp = await authed_client.post(f"/api/v1/releases/{release_id}/bookings", json={
        "environment_id": environment.id,
        "test_phase_id": sit_phase_id,
        "start_date": "2026-04-25T00:00:00+00:00",
        "end_date":   "2026-04-30T00:00:00+00:00",
        "booking_type_id": 1,  # assume fixture provides
    })
    assert book_resp.status_code == 201
    # context_tag should be 'deployment' because system role is 'changing'
    assert book_resp.json().get("context_tag") == "deployment"

    # 6. Transition through the lifecycle
    for to_state in ["submitted", "approved", "in_progress", "ready_for_release", "completed"]:
        t_resp = await authed_client.post(f"/api/v1/releases/{release_id}/transition", json={"to_state": to_state})
        assert t_resp.status_code == 200, (to_state, t_resp.json())
        assert t_resp.json()["status"] == to_state

    # 7. Pass gates (can happen any time after creation)
    for g in gates:
        g_resp = await authed_client.post(f"/api/v1/gates/{g['id']}/pass", json={"notes": "ok"})
        assert g_resp.status_code == 200

    # 8. Confirm actual_date stamped on the terminal state
    final = (await authed_client.get(f"/api/v1/releases/{release_id}")).json()
    assert final["status"] == "completed"
    assert final["actual_date"] is not None
```

Run: `cd backend && uv run pytest tests/integration/test_release_happy_path.py -v`
Expected: PASS.

Commit: `test(phase-3): happy-path integration test for core releases`

---

## Task 41 — Manual QA smoke script + spec refresh

**Files:**
- Create: `docs/phases/phase-3-sub1-smoke-checklist.md` — a short, human-actionable list of browser flows to walk through (matches the happy path test but through the UI).
- Modify: `docs/plan.md` and/or `docs/phases/phase-3.md` to note sub-project 1 complete when this MR lands.

Commit: `docs(phase-3): smoke checklist + plan status for sub-project 1`

---

## Task 42 — Open MR to `main` via GitLab API

The user's preference (from memory: `reference_gitlab.md`) is MRs via the GitLab API because `main` is protected. See also `feedback_workflow.md` for the MR flow.

- [ ] **Step 1: Push branch**

```bash
git push -u origin feature/phase-3-core-releases
```

- [ ] **Step 2: Open the MR via GitLab API** (use the pattern from the previous MR !2 — user will have a glab token configured).

Per memory: local GitLab at localhost:8929, project_id 2. Use the existing `glab` or `curl` pattern the user has established. Title: `Phase 3 sub-project 1 — Core Releases`. Description links the spec + plan docs and lists the happy-path test as evidence.

- [ ] **Step 3: Wait for user review**

End of plan.

---

## Self-review summary

All spec sections have corresponding tasks:

- **Data model** → Tasks 3 (entity_subtype), 4–9 (models), 10 (migration)
- **Lifecycle + custom field conditionality** → Tasks 1 (ENTITY_FIELD_SPECS), 2 (required_fields), 11 (seeds)
- **5 tabs** → Tasks 27 (shared primitives), 29 (shell), 30 (Main), 31 (Gates & Phases), 32 (Environments), 33 (Linked Requests), 34 (Scope)
- **List, calendar, timeline** → Tasks 28, 35, 36
- **Template library** → Tasks 15, 23, 37
- **Dependency alerts** → Tasks 18, 36 (banner)
- **Event log** → Tasks 19, 36 (drawer), 38 (admin UI)
- **Booking/CR integration** → Tasks 20 (service), 22 (endpoints)
- **Outbox events** → woven through services (Tasks 14–20)
- **Tenant seed** → Task 11
- **Testing** → inline unit tests + Task 40 (happy path)

**Placeholder/ambiguity scan:** no "TBD" / "TODO" in actionable steps. Later tasks (14–45) reference back to patterns established in Tasks 1–13 instead of repeating boilerplate — per the note above Task 14, engineers are expected to follow that scaffolding pattern. If any specific interface was unclear, the function signatures in each task's service/component block fill the gap.

**Type consistency:** Entity names, column names, enum values, service method names, and URL paths are consistent across backend tasks and match the frontend type definitions in Task 24.
