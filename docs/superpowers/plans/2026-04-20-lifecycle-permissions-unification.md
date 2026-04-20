# Lifecycle Permissions Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift per-state field-permissions computation into `lifecycle_service`, then surface `custom_field_permissions` + `standard_field_permissions` on both `ReleaseRead` and `BookingResponse` with the same shape — so clients get the permissions in a single round-trip for either entity.

**Architecture:** Introduce a single shared core `get_field_permissions_for_state(definition, state_key, user_role, active_field_keys, valid_standard_fields) -> dict` in `lifecycle_service`. Refactor existing booking helpers to delegate to it (behavior preserved). Add a parallel release helper that loads the release's lifecycle template and active custom-field keys, then calls the core. Extend `ReleaseRead` with two new optional fields and attach them in `GET /releases/{id}`, `PUT /releases/{id}`, and `POST /releases/{id}/transition`. Out of scope for this plan: event-name alignment (`ReleaseStateChanged` vs `BookingStateTransitioned`) and state-driven custom-field *visibility enforcement* on release transitions — tracked separately.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Pydantic v2, pytest-asyncio. Follow existing repo conventions: services return ORM, endpoints shape responses, `get_db()` auto-commits, `native_enum=False`, no `db.commit()` in services.

---

## File Structure

**Backend — modify:**
- `backend/app/services/lifecycle_service.py` — add shared core `get_field_permissions_for_state()` and keep existing `get_custom_field_permissions()` as the thin custom-fields-only variant it already is (or make it delegate to the core).
- `backend/app/services/booking_service.py` — refactor `get_custom_field_perms_for_booking()` and `get_standard_field_perms_for_booking()` to share a single template loader and delegate to the new core. No behavior change.
- `backend/app/services/release_service.py` — add `get_release_field_permissions(db, release, user_role) -> dict` returning `{"custom_field_permissions": {...}, "standard_field_permissions": {...}}`.
- `backend/app/api/v1/schemas/release.py` — add two `Optional[dict[str, dict]]` fields to `ReleaseRead`.
- `backend/app/api/v1/releases.py` — add `_attach_field_permissions()` helper; call it in `GET /releases/{id}`, `PUT /releases/{id}`, `POST /releases/{id}/transition`. Update the docstring at top of file.

**Backend — create:**
- `backend/tests/test_release_field_permissions.py` — integration + unit tests covering the new release permissions shape.

**No frontend changes in this plan.** Follow-up (documented at end) can migrate `ReleaseMainTab.tsx` to consume the embedded permissions instead of re-deriving from `definition.field_permissions`.

---

## Conventions the engineer MUST follow

- **Tenant scoping:** use `current_user.active_tenant_id`, never `.tenant_id`.
- **No `db.commit()` in services** — use `db.flush()` if you need an assigned id.
- **Enum columns:** `native_enum=False` (not touched in this plan, just noted).
- **Run tests from `backend/`:** `cd backend && pytest ...` (or use `uv run pytest ...` if that's what the repo already uses). The repo uses SQLite for tests via the existing `conftest.py`.
- **Commit per step.** Conventional commits: `feat:`, `refactor:`, `test:`.
- **Do not push to `main`** — branch name `feature/lifecycle-permissions-unify`.

---

## Task 1: Add shared core `get_field_permissions_for_state()` in `lifecycle_service`

**Files:**
- Modify: `backend/app/services/lifecycle_service.py` (append after `get_custom_field_permissions`, around line 245)
- Test: `backend/tests/test_lifecycle_field_permissions.py` (NEW)

- [ ] **Step 1: Write the failing unit test**

Create `backend/tests/test_lifecycle_field_permissions.py`:

```python
from app.services.lifecycle_service import get_field_permissions_for_state


DEFINITION = {
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "name": {"editable_by": ["Admin", "Release Manager"]},
                "description": {"editable_by": ["Admin"]},
                "target_date": {"editable_by": []},
            },
            "custom_fields": {
                "sign_off": {"editable_by": ["Admin"]},
                "release_notes": {"editable_by": ["Admin", "Release Manager"]},
            },
        },
        "approved": {
            "standard_fields": {
                "name": {"editable_by": []},
            },
            "custom_fields": {},
        },
    }
}

VALID_STANDARD = {"name", "description", "target_date", "release_type"}
ACTIVE_CUSTOM = {"sign_off", "release_notes", "retired_field"}


def test_returns_both_maps_for_configured_state():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Admin", ACTIVE_CUSTOM, VALID_STANDARD
    )
    assert set(result.keys()) == {"custom_field_permissions", "standard_field_permissions"}
    # Standard fields: all valid fields always present
    sp = result["standard_field_permissions"]
    assert sp["name"] == {"editable": True}
    assert sp["description"] == {"editable": True}
    assert sp["target_date"] == {"editable": False}
    assert sp["release_type"] == {"editable": False}  # not listed in state → not editable
    # Custom fields: only configured + active
    cp = result["custom_field_permissions"]
    assert cp["sign_off"] == {"visible": True, "editable": True}
    assert cp["release_notes"] == {"visible": True, "editable": True}
    assert "retired_field" not in cp  # active but not in state config


def test_readonly_role_sees_editable_false():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Developer", ACTIVE_CUSTOM, VALID_STANDARD
    )
    assert all(v == {"editable": False} for v in result["standard_field_permissions"].values())
    assert result["custom_field_permissions"]["sign_off"] == {"visible": True, "editable": False}


def test_soft_deleted_custom_field_excluded():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Admin", {"release_notes"}, VALID_STANDARD
    )
    assert "sign_off" not in result["custom_field_permissions"]
    assert "release_notes" in result["custom_field_permissions"]


def test_unknown_state_returns_all_fields_not_editable():
    result = get_field_permissions_for_state(
        DEFINITION, "unknown_state", "Admin", ACTIVE_CUSTOM, VALID_STANDARD
    )
    assert result["custom_field_permissions"] == {}
    # Standard fields always present, all not editable
    assert all(v == {"editable": False} for v in result["standard_field_permissions"].values())
    assert set(result["standard_field_permissions"].keys()) == VALID_STANDARD


def test_empty_valid_standard_returns_empty_standard_map():
    result = get_field_permissions_for_state(
        DEFINITION, "draft", "Admin", ACTIVE_CUSTOM, set()
    )
    assert result["standard_field_permissions"] == {}
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `cd backend && uv run pytest tests/test_lifecycle_field_permissions.py -v`
Expected: ImportError / ModuleNotFoundError for `get_field_permissions_for_state`.

- [ ] **Step 3: Implement the shared core**

Append to `backend/app/services/lifecycle_service.py` (after the existing `get_custom_field_permissions` function, end of file):

```python
def get_field_permissions_for_state(
    definition: dict,
    state_key: str,
    user_role: str,
    active_custom_field_keys: set[str],
    valid_standard_field_names: set[str],
) -> dict:
    """Return {custom_field_permissions, standard_field_permissions} for state+role.

    Shape (matches the existing booking response contract):
      {
        "custom_field_permissions": {field_key: {"visible": bool, "editable": bool}},
        "standard_field_permissions": {field_name: {"editable": bool}},
      }

    Behavior:
      - Custom fields: only keys configured for this state AND present in
        active_custom_field_keys appear. Missing state entry → empty dict.
      - Standard fields: every name in valid_standard_field_names appears in
        the output (always). `editable` is True only when the role is in the
        state's standard_fields[name].editable_by list; False otherwise.
      - Missing state config fails closed (everything not editable).
    """
    state_perm = definition.get("field_permissions", {}).get(state_key, {}) or {}

    # Custom fields — reuse the existing helper so its rules stay single-sourced.
    custom = get_custom_field_permissions(
        definition, state_key, user_role, active_custom_field_keys
    )

    # Standard fields — always include every valid name so clients can render
    # a stable field list; editability is role/state derived.
    standard_config = state_perm.get("standard_fields", {}) or {}
    standard: dict[str, dict] = {}
    for name in valid_standard_field_names:
        entry = standard_config.get(name) or {}
        editable_by = entry.get("editable_by", [])
        standard[name] = {"editable": user_role in editable_by}

    return {
        "custom_field_permissions": custom,
        "standard_field_permissions": standard,
    }
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `cd backend && uv run pytest tests/test_lifecycle_field_permissions.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/lifecycle_service.py backend/tests/test_lifecycle_field_permissions.py
git commit -m "feat(lifecycle): add shared get_field_permissions_for_state core"
```

---

## Task 2: Refactor booking helpers to delegate to the new core

No behavior change. We're proving the shared core is equivalent.

**Files:**
- Modify: `backend/app/services/booking_service.py:462-529`

- [ ] **Step 1: Run the existing booking permissions test suite — confirm green baseline**

Run: `cd backend && uv run pytest tests/test_booking_custom_field_permissions.py tests/test_booking_standard_field_permissions.py -v`
Expected: all pass. Note the count — it must match after refactor.

- [ ] **Step 2: Refactor to use the new core**

Open `backend/app/services/booking_service.py`. Replace the existing helper block at lines 462-529 with:

```python
async def _load_booking_template(
    db: AsyncSession, booking: "Booking"
) -> LifecycleTemplate | None:
    """Resolve the lifecycle template for a booking via its booking_type."""
    booking_type_id = booking.booking_request.booking_type_id
    bt = (
        await db.execute(
            select(BookingTypeModel).where(BookingTypeModel.id == booking_type_id)
        )
    ).scalar_one_or_none()
    if not bt:
        return None
    return (
        await db.execute(
            select(LifecycleTemplate).where(LifecycleTemplate.id == bt.lifecycle_template_id)
        )
    ).scalar_one_or_none()


async def _booking_field_permissions(
    db: AsyncSession, booking: "Booking", user_role: str
) -> dict:
    """Return {custom_field_permissions, standard_field_permissions} for a booking.
    Fail-closed: returns empty custom map + all-not-editable standard map if the
    booking type or template cannot be loaded."""
    template = await _load_booking_template(db, booking)
    if template is None:
        return {
            "custom_field_permissions": {},
            "standard_field_permissions": {f: {"editable": False} for f in VALID_STANDARD_FIELD_NAMES},
        }
    active_keys = await get_active_field_keys(db, booking.tenant_id, "booking")
    return lifecycle_service.get_field_permissions_for_state(
        template.definition,
        booking.status,
        user_role,
        active_keys,
        VALID_STANDARD_FIELD_NAMES,
    )


async def get_custom_field_perms_for_booking(
    db: AsyncSession, booking: "Booking", user_role: str
) -> dict[str, dict]:
    """Return the resolved custom_field_permissions map for a booking.
    Preserved for backward compatibility with existing callers."""
    perms = await _booking_field_permissions(db, booking, user_role)
    return perms["custom_field_permissions"]


def get_standard_field_permissions(
    definition: dict, state_key: str, user_role: str
) -> set[str]:
    """Return the set of standard permission keys editable by user_role in state_key.
    Fail-closed: returns empty set if state not configured.
    Preserved: some callers import this directly."""
    perm = definition.get("field_permissions", {}).get(state_key)
    if not perm:
        return set()
    standard_fields = perm.get("standard_fields", {})
    return {
        field_key
        for field_key, config in standard_fields.items()
        if user_role in config.get("editable_by", [])
    }


async def get_standard_field_perms_for_booking(
    db: AsyncSession, booking: "Booking", user_role: str
) -> dict[str, dict]:
    """Return editable status for all 7 standard fields for this booking's state+role."""
    perms = await _booking_field_permissions(db, booking, user_role)
    return perms["standard_field_permissions"]
```

Check the top of `booking_service.py` has `from app.services import lifecycle_service` — if it only imports specific names, add `import lifecycle_service` or use the direct name. Check with:

Run: `cd backend && grep -n "lifecycle_service\|get_custom_field_permissions" app/services/booking_service.py | head -20`

If `lifecycle_service` module isn't already imported, add at the top of the file (after existing imports):

```python
from app.services import lifecycle_service
```

If `get_custom_field_permissions` is imported as a bare name (it is — used at line 488 of the pre-refactor code), keep that import line. The refactored code above uses `lifecycle_service.get_field_permissions_for_state` explicitly, so the bare import is no longer required for the public helpers. However, `_booking_field_permissions` still calls into the lifecycle service, and the old `get_custom_field_permissions` bare import may still be used elsewhere in the file — leave it alone if present.

- [ ] **Step 3: Run the booking permissions tests — must still pass with same count**

Run: `cd backend && uv run pytest tests/test_booking_custom_field_permissions.py tests/test_booking_standard_field_permissions.py -v`
Expected: identical pass count as in Step 1.

- [ ] **Step 4: Run the full booking test suite as a safety net**

Run: `cd backend && uv run pytest tests/test_booking_lifecycle.py tests/test_booking_transitions.py tests/integration/test_bookings.py -v`
Expected: all pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/booking_service.py
git commit -m "refactor(bookings): route field-permissions through shared lifecycle core"
```

---

## Task 3: Add permissions fields to `ReleaseRead` schema

**Files:**
- Modify: `backend/app/api/v1/schemas/release.py:28-46`

- [ ] **Step 1: Write the failing schema test**

Create `backend/tests/test_release_schemas_permissions.py`:

```python
from app.api.v1.schemas.release import ReleaseRead


def test_release_read_accepts_permissions_fields():
    """ReleaseRead must accept custom_field_permissions and standard_field_permissions."""
    data = {
        "id": 1, "tenant_id": 1, "name": "R1", "description": None,
        "release_type": "project", "release_kind": "project",
        "parent_release_id": None, "template_id": None,
        "lifecycle_template_id": 2, "status": "draft",
        "target_date": None, "actual_date": None,
        "custom_fields": None, "raised_by": 3,
        "created_at": "2026-04-20T00:00:00Z", "updated_at": "2026-04-20T00:00:00Z",
        "custom_field_permissions": {"sign_off": {"visible": True, "editable": True}},
        "standard_field_permissions": {"name": {"editable": True}},
    }
    obj = ReleaseRead.model_validate(data)
    assert obj.custom_field_permissions == {"sign_off": {"visible": True, "editable": True}}
    assert obj.standard_field_permissions == {"name": {"editable": True}}


def test_release_read_permissions_fields_optional():
    """Both permissions fields default to None when omitted."""
    data = {
        "id": 1, "tenant_id": 1, "name": "R1", "description": None,
        "release_type": "project", "release_kind": "project",
        "parent_release_id": None, "template_id": None,
        "lifecycle_template_id": 2, "status": "draft",
        "target_date": None, "actual_date": None,
        "custom_fields": None, "raised_by": 3,
        "created_at": "2026-04-20T00:00:00Z", "updated_at": "2026-04-20T00:00:00Z",
    }
    obj = ReleaseRead.model_validate(data)
    assert obj.custom_field_permissions is None
    assert obj.standard_field_permissions is None
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `cd backend && uv run pytest tests/test_release_schemas_permissions.py -v`
Expected: AttributeError or validation error — fields not defined.

- [ ] **Step 3: Add fields to ReleaseRead**

Edit `backend/app/api/v1/schemas/release.py`. In the `ReleaseRead` class, insert the two new fields after `updated_at: datetime` (line 46):

```python
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
    custom_field_permissions: Optional[dict[str, dict]] = None
    standard_field_permissions: Optional[dict[str, dict]] = None
```

`ReleaseListItemRead` inherits from `ReleaseRead` so it picks up the fields automatically — list endpoints will keep them `None` (we don't compute permissions in list views, same as booking list behavior).

- [ ] **Step 4: Run the test, verify it passes**

Run: `cd backend && uv run pytest tests/test_release_schemas_permissions.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run existing release schema tests to confirm no regressions**

Run: `cd backend && uv run pytest tests/test_release_schemas.py tests/test_release_subresource_schemas.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/schemas/release.py backend/tests/test_release_schemas_permissions.py
git commit -m "feat(releases): add optional permissions fields to ReleaseRead"
```

---

## Task 4: Add `get_release_field_permissions` in `release_service`

**Files:**
- Modify: `backend/app/services/release_service.py`

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/test_release_field_permissions.py`:

```python
import pytest
from httpx import AsyncClient


RELEASE_DEF = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "name": {"editable_by": ["Admin", "Release Manager"]},
                "description": {"editable_by": ["Admin"]},
            },
            "custom_fields": {
                "sign_off": {"editable_by": ["Admin"]},
            },
        },
        "approved": {
            "standard_fields": {
                "name": {"editable_by": []},
            },
            "custom_fields": {
                "sign_off": {"editable_by": []},
            },
        },
    },
}


async def _setup_release(client: AsyncClient, headers: dict) -> int:
    """Create a release-entity lifecycle template, a release custom-field def,
    then create a release on that template. Returns release_id."""
    tmpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=headers,
        json={"name": "R Tmpl", "entity_type": "release", "definition": RELEASE_DEF},
    )
    assert tmpl.status_code == 201, tmpl.text
    tmpl_id = tmpl.json()["id"]

    cf = await client.post(
        "/api/v1/tenant/fields",
        headers=headers,
        json={"entity_type": "release", "label": "Sign Off", "field_key": "sign_off", "field_type": "text"},
    )
    assert cf.status_code in (200, 201), cf.text

    release = await client.post(
        "/api/v1/releases",
        headers=headers,
        json={
            "name": "Perm Test Release",
            "release_type": "project",
            "lifecycle_template_id": tmpl_id,
            "custom_fields": {"sign_off": "pending"},
        },
    )
    assert release.status_code == 201, release.text
    return release.json()["id"]


@pytest.mark.asyncio
async def test_get_release_includes_permissions(client: AsyncClient, auth_headers: dict):
    """GET /releases/{id} must include custom_field_permissions and standard_field_permissions."""
    release_id = await _setup_release(client, auth_headers)

    resp = await client.get(f"/api/v1/releases/{release_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "custom_field_permissions" in data
    assert "standard_field_permissions" in data

    # Admin in draft state can edit sign_off
    assert data["custom_field_permissions"]["sign_off"] == {"visible": True, "editable": True}
    # Admin in draft state can edit name + description
    assert data["standard_field_permissions"]["name"] == {"editable": True}
    assert data["standard_field_permissions"]["description"] == {"editable": True}
    # target_date is a valid standard field but not listed in state → not editable
    assert data["standard_field_permissions"]["target_date"] == {"editable": False}


@pytest.mark.asyncio
async def test_transition_release_returns_updated_permissions(client: AsyncClient, auth_headers: dict):
    """POST /releases/{id}/transition response has permissions reflecting the NEW state."""
    release_id = await _setup_release(client, auth_headers)

    resp = await client.post(
        f"/api/v1/releases/{release_id}/transition",
        headers=auth_headers,
        json={"to_state": "approved"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "approved"
    # In approved state, name has empty editable_by → not editable
    assert data["standard_field_permissions"]["name"] == {"editable": False}
    assert data["custom_field_permissions"]["sign_off"] == {"visible": True, "editable": False}


@pytest.mark.asyncio
async def test_update_release_returns_permissions(client: AsyncClient, auth_headers: dict):
    """PUT /releases/{id} response includes permissions (same shape as GET)."""
    release_id = await _setup_release(client, auth_headers)

    resp = await client.put(
        f"/api/v1/releases/{release_id}",
        headers=auth_headers,
        json={"description": "updated"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "custom_field_permissions" in data
    assert "standard_field_permissions" in data
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd backend && uv run pytest tests/test_release_field_permissions.py -v`
Expected: the three tests all fail because the response doesn't include `custom_field_permissions` / `standard_field_permissions` yet.

- [ ] **Step 3: Add the release service helper**

Edit `backend/app/services/release_service.py`. Add these imports if not already present (check the existing imports at top of the file):

```python
from app.api.v1.schemas.booking_lifecycle import ENTITY_FIELD_SPECS
from app.services.custom_field_service import get_active_field_keys
```

Append to the end of `backend/app/services/release_service.py`:

```python
async def get_release_field_permissions(
    db: AsyncSession, release: Release, user_role: str
) -> dict:
    """Return {custom_field_permissions, standard_field_permissions} for this release.

    Loads the release's lifecycle template and the tenant's active release
    custom-field definitions, then delegates to lifecycle_service. Fail-closed
    if the template can't be loaded (empty custom map, all-not-editable standard
    map)."""
    template = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.id == release.lifecycle_template_id
            )
        )
    ).scalar_one_or_none()

    valid_standard = ENTITY_FIELD_SPECS["release"]["valid"]

    if template is None:
        return {
            "custom_field_permissions": {},
            "standard_field_permissions": {f: {"editable": False} for f in valid_standard},
        }

    active_keys = await get_active_field_keys(db, release.tenant_id, "release")
    return lifecycle_service.get_field_permissions_for_state(
        template.definition,
        release.status,
        user_role,
        active_keys,
        valid_standard,
    )
```

- [ ] **Step 4: Add a focused service-level unit test**

Append to `backend/tests/test_release_field_permissions.py`:

```python
from app.db.models.release import Release
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.custom_field import CustomFieldDefinition
from app.services.release_service import get_release_field_permissions


@pytest.mark.asyncio
async def test_get_release_field_permissions_missing_template_fail_closed(db_session):
    """If the release's lifecycle_template_id doesn't resolve, return fail-closed maps."""
    release = Release(
        tenant_id=1,
        name="ghost",
        description=None,
        release_type="project",
        release_kind="project",
        lifecycle_template_id=9999,  # does not exist
        status="draft",
        raised_by=1,
        custom_fields={},
    )
    result = await get_release_field_permissions(db_session, release, "Admin")
    assert result["custom_field_permissions"] == {}
    # All valid release standard fields present, all not editable
    assert all(v == {"editable": False} for v in result["standard_field_permissions"].values())
    assert "name" in result["standard_field_permissions"]
```

Note: `db_session` is the async session fixture in the repo's `conftest.py`. If the fixture name differs, grep `backend/tests/conftest.py` for the async session fixture and use that name. Do NOT invent a new fixture.

Verify by running:

Run: `cd backend && grep -n "def db_session\|async def db_session\|@pytest.fixture" tests/conftest.py | head -20`

If the fixture is called something else (e.g., `session`, `async_session`), rename the parameter in the test accordingly.

- [ ] **Step 5: Do NOT run the new test yet**

The fail-closed test will pass, but the three integration tests will still fail until Task 5 wires up the endpoints. We run them after Task 5. For this step, only run the unit test:

Run: `cd backend && uv run pytest tests/test_release_field_permissions.py::test_get_release_field_permissions_missing_template_fail_closed -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/release_service.py backend/tests/test_release_field_permissions.py
git commit -m "feat(releases): add get_release_field_permissions service helper"
```

---

## Task 5: Wire permissions into release endpoints

**Files:**
- Modify: `backend/app/api/v1/releases.py` (imports, new helper, three endpoint call sites, top-of-file docstring)

- [ ] **Step 1: Add attach-permissions helper + update imports**

Edit `backend/app/api/v1/releases.py`. The existing top-of-file docstring (lines 1-10) mentions field permissions but doesn't match current behavior. Replace that docstring with:

```python
"""Releases API — CRUD, lifecycle transition, calendar, timeline, history,
and all release sub-resources (phases, gates, systems, dependencies, events,
scope/changes, bookings, linked CRs).

Field-permissions contract (GET/PUT/transition on a single release):
  Responses include `custom_field_permissions` and `standard_field_permissions`
  computed for the caller's role at the release's current state. This mirrors
  the booking endpoints — clients get permissions in a single round-trip and do
  not need to call GET /releases/{id}/lifecycle just to determine editability.
  The dedicated /lifecycle endpoint remains available for clients that need the
  full state-machine definition (e.g. to drive transition UIs).
"""
```

Add a module-level helper directly after the helpers section (after `_require_phase` around line 94):

```python
async def _release_with_permissions(
    db: AsyncSession, release: Release, user_role: str
) -> ReleaseRead:
    """Materialize a ReleaseRead response with permissions attached."""
    perms = await release_service.get_release_field_permissions(db, release, user_role)
    resp = ReleaseRead.model_validate(release)
    resp.custom_field_permissions = perms["custom_field_permissions"]
    resp.standard_field_permissions = perms["standard_field_permissions"]
    return resp
```

- [ ] **Step 2: Call the helper from `GET /releases/{id}`**

Replace the body of `get_release` (around lines 308-323) with:

```python
@router.get("/{release_id}", response_model=ReleaseRead)
async def get_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return a single release with field_permissions attached for the caller's role."""
    tenant_id = current_user.active_tenant_id
    release = await _require_release(db, release_id, tenant_id)
    return await _release_with_permissions(db, release, current_user.role)
```

- [ ] **Step 3: Call the helper from `PUT /releases/{id}`**

Replace the body of `update_release` (around lines 326-337):

```python
@router.put("/{release_id}", response_model=ReleaseRead)
async def update_release(
    release_id: int,
    data: ReleaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await release_service.update_release(
        db, release_id, data, tenant_id, current_user.id
    )
    return await _release_with_permissions(db, release, current_user.role)
```

- [ ] **Step 4: Call the helper from `POST /releases/{id}/transition`**

Replace the body of `transition_release` (around lines 351-368):

```python
@router.post("/{release_id}/transition", response_model=ReleaseRead)
async def transition_release(
    release_id: int,
    data: ReleaseTransition,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await release_service.transition_release(
        db,
        release_id,
        to_state=data.to_state,
        notes=data.notes,
        tenant_id=tenant_id,
        user_id=current_user.id,
        user_role=current_user.role,
    )
    return await _release_with_permissions(db, release, current_user.role)
```

- [ ] **Step 5: Run the release permissions tests — all four must pass now**

Run: `cd backend && uv run pytest tests/test_release_field_permissions.py -v`
Expected: 4 passed (3 integration + 1 unit).

- [ ] **Step 6: Run the broader release suite — catch regressions**

Run: `cd backend && uv run pytest tests/test_releases_api.py tests/services/test_release_service.py tests/integration/test_release_happy_path.py tests/test_release_schemas.py -v`
Expected: all pass.

- [ ] **Step 7: Run the full backend test suite as final safety net**

Run: `cd backend && uv run pytest -q`
Expected: all pass. If any previously-green test breaks, stop and investigate — do not silently skip.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/releases.py
git commit -m "feat(releases): attach field permissions to GET/PUT/transition responses"
```

---

## Task 6: Push branch

- [ ] **Step 1: Push**

```bash
git push -u origin feature/lifecycle-permissions-unify
```

- [ ] **Step 2: Report the branch name + commit list to the user.**

Do NOT open a merge request automatically — per project workflow memory, the user drives the GitLab MR flow into `main`.

---

## Out of scope (document in commit message / PR description)

1. **State-driven custom-field visibility enforcement on release transitions.** Booking resolves visible fields per state at create time; Release does not. This plan exposes the permissions but does not enforce visibility on `transition_release` / `update_release`. Tracked separately.
2. **Event-name alignment.** `ReleaseStateChanged` vs `BookingStateTransitioned` remain divergent. Renaming touches consumers and is a separate change.
3. **Frontend migration.** `ReleaseMainTab.tsx:121` still reads `lifecycleTpl.definition.field_permissions` from the `/lifecycle` endpoint. A follow-up can simplify this to consume the embedded `release.custom_field_permissions` + `release.standard_field_permissions`, matching `BookingDetail.tsx`. Kept out of this plan so backend and frontend ship independently.

---

## Self-review checklist

- [x] **Spec coverage** — every inconsistency (1) and (3) from the review is addressed by Tasks 3-5 and Tasks 1-2 respectively. Inconsistencies (2), (4), (5) are explicitly deferred in "Out of scope".
- [x] **Placeholders** — none. Every code block is complete; all commands are exact.
- [x] **Type consistency** — `get_field_permissions_for_state` signature is identical across Tasks 1, 2, 4. Return shape `{custom_field_permissions, standard_field_permissions}` is the same at every layer. `ReleaseRead.custom_field_permissions: Optional[dict[str, dict]]` matches `BookingResponse.custom_field_permissions: Optional[dict[str, dict]]` (both `booking.py:65`).
- [x] **Tenant scoping** — every new DB query either goes through existing helpers (`get_active_field_keys` already filters by tenant) or operates on already-scoped objects (the release passed in was loaded via `_require_release` which scopes to tenant).
- [x] **No `db.commit()` in services** — new code uses reads only; no writes introduced.
