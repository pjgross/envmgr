# Booking Custom Field Type/State Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend booking custom fields so they are scoped to lifecycle template states (visible only when listed, editable only by configured roles) with the template owning all access rules.

**Architecture:** Add `custom_fields` subsection to each state's `field_permissions` in the lifecycle template JSONB. A new `get_custom_field_permissions` service helper resolves visibility+editability per user role. `GET /bookings/{id}` attaches the resolved permissions map; the frontend uses it to filter and mode-select custom field rendering. A new `PATCH /bookings/{id}/custom-fields` endpoint allows in-context updates. The lifecycle template admin UI gains a field permissions editor and edit dialog.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, React 18, TypeScript, MUI, Redux Toolkit. Tests: pytest + httpx AsyncClient against in-memory SQLite.

**Spec:** `docs/superpowers/specs/2026-03-25-booking-custom-field-type-state-permissions-design.md`

---

## File Map

| Action | File | Change |
|---|---|---|
| Modify | `backend/app/api/v1/schemas/booking_lifecycle.py` | Add `CustomFieldPermission`; extend `LifecycleFieldPermission` |
| Modify | `backend/app/services/booking_lifecycle_service.py` | Add `get_custom_field_permissions` helper |
| Modify | `backend/app/services/custom_field_service.py` | Add `get_active_field_keys`; update `validate_custom_fields` |
| Modify | `backend/app/api/v1/schemas/booking.py` | Add `custom_field_permissions` to `BookingResponse` |
| Modify | `backend/app/api/v1/bookings.py` | Extend GET `/{booking_id}`; add PATCH `/{booking_id}/custom-fields` |
| Modify | `backend/app/services/booking_service.py` | Add `get_custom_field_perms_for_booking`; add `update_custom_fields` |
| Create | `backend/tests/test_booking_custom_field_permissions.py` | Integration tests |
| Modify | `frontend/src/types/bookingLifecycle.ts` | Extend `LifecycleFieldPermission` |
| Modify | `frontend/src/types/booking.ts` | Add `CustomFieldPermission`; extend `BookingResponse` |
| Modify | `frontend/src/pages/bookings/BookingForm.tsx` | Filter custom fields by selected type's initial state |
| Modify | `frontend/src/pages/bookings/BookingDetail.tsx` | Display+edit custom fields per `custom_field_permissions` |
| Modify | `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` | Field permissions editor + edit dialog |

---

## Task 1: Backend Schema — Add CustomFieldPermission and extend LifecycleFieldPermission

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py`
- Test: `backend/tests/test_booking_custom_field_permissions.py` (create file)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_booking_custom_field_permissions.py`:

```python
import pytest
from httpx import AsyncClient

DEFINITION_WITH_CUSTOM_FIELDS = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "editable_fields": ["project_name"],
            "editable_by": ["Admin"],
            "custom_fields": {
                "release_notes": {"editable_by": ["Admin", "Release Manager"]},
                "sign_off": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "editable_fields": [],
            "editable_by": [],
            "custom_fields": {
                "sign_off": {"editable_by": []},
            },
        },
    },
}


@pytest.mark.asyncio
async def test_create_template_with_custom_field_permissions(client: AsyncClient, auth_headers: dict):
    """Template with custom_fields in field_permissions creates successfully."""
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "CF Test", "definition": DEFINITION_WITH_CUSTOM_FIELDS},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    draft_perms = data["definition"]["field_permissions"]["draft"]
    assert "custom_fields" in draft_perms
    assert draft_perms["custom_fields"]["release_notes"]["editable_by"] == ["Admin", "Release Manager"]


@pytest.mark.asyncio
async def test_create_template_with_invalid_role_in_custom_field(client: AsyncClient, auth_headers: dict):
    """custom_fields.editable_by with an invalid role returns 422."""
    bad_def = {
        "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
        "transitions": [],
        "field_permissions": {
            "draft": {
                "editable_fields": [],
                "editable_by": [],
                "custom_fields": {
                    "my_field": {"editable_by": ["NotARealRole"]},
                },
            }
        },
    }
    resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Bad Roles", "definition": bad_def},
    )
    assert resp.status_code == 422, resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_booking_custom_field_permissions.py -v
```

Expected: FAIL — `custom_fields` key is not accepted by `LifecycleFieldPermission` (422 on create, not 201).

- [ ] **Step 3: Add CustomFieldPermission and extend LifecycleFieldPermission**

In `backend/app/api/v1/schemas/booking_lifecycle.py`, add after the `VALID_ROLES` constant:

```python
class CustomFieldPermission(BaseModel):
    editable_by: list[str]

    @field_validator("editable_by")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}. Must be one of {VALID_ROLES}")
        return v
```

Then extend the existing `LifecycleFieldPermission`:

```python
class LifecycleFieldPermission(BaseModel):
    editable_fields: list[str]
    editable_by: list[str]
    custom_fields: Optional[dict[str, CustomFieldPermission]] = None  # new

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
```

Also add `Optional` to the imports at the top of the file if not present:
```python
from typing import Optional
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_booking_custom_field_permissions.py -v
```

Expected: PASS — both tests.

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
cd backend && uv run pytest -v
```

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/schemas/booking_lifecycle.py backend/tests/test_booking_custom_field_permissions.py
git commit -m "feat: extend LifecycleFieldPermission schema with per-custom-field edit permissions"
```

---

## Task 2: Backend Service — get_custom_field_permissions helper

**Files:**
- Modify: `backend/app/services/booking_lifecycle_service.py`
- Modify: `backend/app/services/custom_field_service.py`
- Modify: `backend/tests/test_booking_custom_field_permissions.py`

- [ ] **Step 1: Write unit tests for the helper function**

Append to `backend/tests/test_booking_custom_field_permissions.py`:

```python
from app.services.booking_lifecycle_service import get_custom_field_permissions

DEFINITION = {
    "field_permissions": {
        "draft": {
            "editable_fields": [],
            "editable_by": [],
            "custom_fields": {
                "release_notes": {"editable_by": ["Admin", "Release Manager"]},
                "sign_off": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "editable_fields": [],
            "editable_by": [],
            "custom_fields": {
                "sign_off": {"editable_by": []},
            },
        },
    }
}

ACTIVE_KEYS = {"release_notes", "sign_off", "other_field"}


def test_get_custom_field_permissions_editable_role():
    """Admin in draft can edit release_notes."""
    result = get_custom_field_permissions(DEFINITION, "draft", "Admin", ACTIVE_KEYS)
    assert result["release_notes"] == {"visible": True, "editable": True}
    assert result["sign_off"] == {"visible": True, "editable": True}


def test_get_custom_field_permissions_readonly_role():
    """Developer in draft cannot edit — not in any editable_by."""
    result = get_custom_field_permissions(DEFINITION, "draft", "Developer", ACTIVE_KEYS)
    assert result["release_notes"] == {"visible": True, "editable": False}
    assert result["sign_off"] == {"visible": True, "editable": False}


def test_get_custom_field_permissions_field_hidden_in_state():
    """release_notes not listed in submitted → absent from result."""
    result = get_custom_field_permissions(DEFINITION, "submitted", "Admin", ACTIVE_KEYS)
    assert "release_notes" not in result
    assert result["sign_off"] == {"visible": True, "editable": False}  # editable_by: []


def test_get_custom_field_permissions_soft_deleted_field_excluded():
    """Field key in template but not in active_field_keys is excluded."""
    result = get_custom_field_permissions(DEFINITION, "draft", "Admin", {"release_notes"})
    assert "release_notes" in result
    assert "sign_off" not in result  # not in active_keys


def test_get_custom_field_permissions_state_not_in_template():
    """State with no field_permissions entry returns empty dict."""
    result = get_custom_field_permissions(DEFINITION, "approved", "Admin", ACTIVE_KEYS)
    assert result == {}


def test_get_custom_field_permissions_no_custom_fields_in_state():
    """State entry with no custom_fields key returns empty dict."""
    definition = {
        "field_permissions": {
            "draft": {"editable_fields": ["project_name"], "editable_by": ["Admin"]},
        }
    }
    result = get_custom_field_permissions(definition, "draft", "Admin", {"any_key"})
    assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_booking_custom_field_permissions.py::test_get_custom_field_permissions_editable_role -v
```

Expected: FAIL — `get_custom_field_permissions` not yet imported (ImportError or wrong signature).

- [ ] **Step 3: Implement get_custom_field_permissions in booking_lifecycle_service.py**

Add at the end of `backend/app/services/booking_lifecycle_service.py`:

```python
def get_custom_field_permissions(
    definition: dict,
    current_state: str,
    user_role: str,
    active_field_keys: set[str],
) -> dict[str, dict]:
    """
    Return {field_key: {visible, editable}} for all custom fields visible in this state.
    Fields absent from the state config, or whose CustomFieldDefinition has been
    soft-deleted (not in active_field_keys), are omitted (treated as hidden).
    """
    perm = definition.get("field_permissions", {}).get(current_state, {})
    result = {}
    for key, entry in (perm.get("custom_fields") or {}).items():
        if key not in active_field_keys:
            continue  # definition was soft-deleted; skip silently
        editable_by = entry.get("editable_by", [])
        result[key] = {
            "visible": True,
            "editable": user_role in editable_by,
        }
    return result
```

- [ ] **Step 4: Add get_active_booking_field_keys to custom_field_service.py**

Add after `list_definitions` in `backend/app/services/custom_field_service.py`:

```python
async def get_active_field_keys(
    db: AsyncSession, tenant_id: int, entity_type: str
) -> set[str]:
    """Return the set of field_key values for active (non-deleted) definitions."""
    result = await db.execute(
        select(CustomFieldDefinition.field_key).where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == entity_type,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    return set(result.scalars().all())
```

- [ ] **Step 5: Update validate_custom_fields to be state-aware**

In `backend/app/services/custom_field_service.py`, update the `validate_custom_fields` signature and body to accept an optional `visible_field_keys` parameter. When provided, only enforce `required` for keys that are visible:

```python
async def validate_custom_fields(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str,
    values: Optional[dict],
    visible_field_keys: Optional[set[str]] = None,
) -> None:
    """Validate custom_fields dict against active definitions for this tenant+entity_type.

    Raises HTTPException(422) if required fields are missing or types are wrong.
    Unknown keys are permitted (soft-deleted fields may still have stored values).
    If visible_field_keys is provided, required validation is only enforced for
    fields in that set (state-driven visibility supersedes required).
    """
    definitions = await list_definitions(db, tenant_id, entity_type)
    if not definitions:
        return

    values = values or {}

    for defn in definitions:
        if not defn.required:
            continue
        # Skip required check if field is not visible in current state
        if visible_field_keys is not None and defn.field_key not in visible_field_keys:
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

- [ ] **Step 6: Run all new unit tests**

```bash
cd backend && uv run pytest tests/test_booking_custom_field_permissions.py -v
```

Expected: All pass.

- [ ] **Step 7: Run full test suite**

```bash
cd backend && uv run pytest -v
```

Expected: All pass — `validate_custom_fields` new param defaults to `None` so existing callers are unchanged.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/booking_lifecycle_service.py backend/app/services/custom_field_service.py backend/tests/test_booking_custom_field_permissions.py
git commit -m "feat: add get_custom_field_permissions helper and state-aware custom field validation"
```

---

## Task 3: Backend API — BookingResponse + GET /bookings/{id} + PATCH /bookings/{id}/custom-fields

**Files:**
- Modify: `backend/app/api/v1/schemas/booking.py`
- Modify: `backend/app/services/booking_service.py`
- Modify: `backend/app/api/v1/bookings.py`
- Modify: `backend/tests/test_booking_custom_field_permissions.py`

- [ ] **Step 1: Write integration tests**

Append to `backend/tests/test_booking_custom_field_permissions.py`:

```python
# Note: uses a different constant name to avoid clash with DEFINITION_WITH_CUSTOM_FIELDS from Task 1
BOOKING_DEF = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "editable_fields": ["project_name"],
            "editable_by": ["Admin"],
            "custom_fields": {
                "release_notes": {"editable_by": ["Admin"]},
            },
        },
        "submitted": {
            "editable_fields": [],
            "editable_by": [],
            "custom_fields": {},
        },
    },
}


async def _setup_booking_with_cf_template(client, auth_headers):
    """Create template, booking type, environment, and booking. Return booking_id."""
    tmpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "CF Template", "definition": BOOKING_DEF},
    )
    template_id = tmpl.json()["id"]
    bt = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "CF Type", "lifecycle_template_id": template_id},
    )
    bt_id = bt.json()["id"]

    # Create custom field definition
    await client.post(
        "/api/v1/tenant/fields",
        headers=auth_headers,
        json={"entity_type": "booking", "label": "Release Notes", "field_key": "release_notes", "field_type": "text"},
    )

    env = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "CFTestEnv", "env_type": "testing"},
    )
    env_id = env.json()["id"]

    booking = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "CF Project",
            "start_date": "2026-04-01T09:00:00Z",
            "end_date": "2026-04-01T17:00:00Z",
            "booking_type_id": bt_id,
            "custom_fields": {"release_notes": "initial notes"},
        },
    )
    return booking.json()["booking"]["id"]


@pytest.mark.asyncio
async def test_get_booking_includes_custom_field_permissions(client: AsyncClient, auth_headers: dict):
    """GET /bookings/{id} includes custom_field_permissions resolved for current state+role."""
    booking_id = await _setup_booking_with_cf_template(client, auth_headers)

    resp = await client.get(f"/api/v1/bookings/{booking_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "custom_field_permissions" in data
    # Booking is in draft; Admin can edit release_notes
    assert data["custom_field_permissions"]["release_notes"] == {"visible": True, "editable": True}


@pytest.mark.asyncio
async def test_patch_custom_fields_updates_booking(client: AsyncClient, auth_headers: dict):
    """PATCH /bookings/{id}/custom-fields updates the custom_fields JSON."""
    booking_id = await _setup_booking_with_cf_template(client, auth_headers)

    resp = await client.patch(
        f"/api/v1/bookings/{booking_id}/custom-fields",
        headers=auth_headers,
        json={"release_notes": "updated notes"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_fields"]["release_notes"] == "updated notes"


@pytest.mark.asyncio
async def test_patch_custom_fields_hidden_field_rejected(client: AsyncClient, auth_headers: dict):
    """PATCH /bookings/{id}/custom-fields rejects update for a field not visible in current state."""
    booking_id = await _setup_booking_with_cf_template(client, auth_headers)

    # Transition to submitted where release_notes is hidden
    await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )

    resp = await client.patch(
        f"/api/v1/bookings/{booking_id}/custom-fields",
        headers=auth_headers,
        json={"release_notes": "trying to edit hidden field"},
    )
    assert resp.status_code == 403, resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_booking_custom_field_permissions.py::test_get_booking_includes_custom_field_permissions tests/test_booking_custom_field_permissions.py::test_patch_custom_fields_updates_booking -v
```

Expected: FAIL — `custom_field_permissions` absent from response; PATCH endpoint does not exist.

- [ ] **Step 3: Extend BookingResponse schema**

In `backend/app/api/v1/schemas/booking.py`, add `custom_field_permissions` to `BookingResponse`:

```python
class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    environment_name: Optional[str] = None
    project_name: str
    booked_by: int
    booked_by_username: Optional[str] = None
    start_date: datetime
    end_date: datetime
    booking_type_id: int
    exclusive_use: bool
    status: str
    notes: Optional[str] = None
    recurrence_rule: Optional[str] = None
    recurrence_parent_id: Optional[int] = None
    release_id: Optional[int] = None
    test_phase_id: Optional[int] = None
    context_tag: ContextTag
    custom_fields: Optional[dict] = None
    custom_field_permissions: Optional[dict[str, dict]] = None  # new
    tenant_id: int
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add service helpers to booking_service.py**

Add these two functions at the bottom of `backend/app/services/booking_service.py`:

First, add the imports at the top of the file (if not already present):
```python
from app.db.models.custom_field import CustomFieldDefinition
from app.services.booking_lifecycle_service import get_custom_field_permissions
from app.services.custom_field_service import get_active_field_keys
```

Then add the functions:
```python
async def get_custom_field_perms_for_booking(
    db: AsyncSession, booking: Booking, user_role: str
) -> dict[str, dict]:
    """
    Load the lifecycle template for a booking and return the resolved
    custom_field_permissions map for the booking's current state and user role.
    Returns empty dict if the booking type or template is not found.
    """
    bt_result = await db.execute(
        select(BookingTypeModel).where(BookingTypeModel.id == booking.booking_type_id)
    )
    booking_type_obj = bt_result.scalar_one_or_none()
    if not booking_type_obj:
        return {}

    tmpl_result = await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.id == booking_type_obj.lifecycle_template_id
        )
    )
    template = tmpl_result.scalar_one_or_none()
    if not template:
        return {}

    active_keys = await get_active_field_keys(db, booking.tenant_id, "booking")
    return get_custom_field_permissions(
        template.definition, booking.status, user_role, active_keys
    )


async def update_custom_fields(
    db: AsyncSession,
    booking_id: int,
    values: dict,
    current_user,
) -> Booking:
    """
    Update the custom_fields JSON on a booking.
    Only fields that are visible AND editable for the current user's role in the
    current state are permitted. Raises 403 if any submitted key is not editable.
    """
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)
    perms = await get_custom_field_perms_for_booking(db, booking, current_user.role)

    for key in values:
        entry = perms.get(key)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Field '{key}' is not visible in state '{booking.status}'",
            )
        if not entry["editable"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Field '{key}' is not editable in state '{booking.status}' for your role",
            )

    # Merge into existing values (partial update — do not wipe unlisted keys)
    existing = booking.custom_fields or {}
    booking.custom_fields = {**existing, **values}
    await db.flush()
    await db.refresh(booking)
    return booking
```

- [ ] **Step 5: Update the GET endpoint and add PATCH endpoint in bookings.py**

In `backend/app/api/v1/bookings.py`, update the `get_booking` endpoint:

```python
@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.get_booking(db, booking_id, current_user.active_tenant_id)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp
```

Add the new PATCH endpoint (place it after the GET endpoint). Import `Body` from `fastapi` at the top of `bookings.py` if not already present:

```python
@router.patch("/{booking_id}/custom-fields", response_model=BookingResponse)
async def update_custom_fields(
    booking_id: int,
    values: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.update_custom_fields(db, booking_id, values, current_user)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp
```

- [ ] **Step 6: Run integration tests**

```bash
cd backend && uv run pytest tests/test_booking_custom_field_permissions.py -v
```

Expected: All pass.

- [ ] **Step 7: Run full test suite**

```bash
cd backend && uv run pytest -v
```

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/schemas/booking.py backend/app/services/booking_service.py backend/app/api/v1/bookings.py backend/tests/test_booking_custom_field_permissions.py
git commit -m "feat: add custom_field_permissions to booking GET response and PATCH /custom-fields endpoint"
```

---

## Task 4: Frontend Types

**Files:**
- Modify: `frontend/src/types/bookingLifecycle.ts`
- Modify: `frontend/src/types/booking.ts`

- [ ] **Step 1: Extend LifecycleFieldPermission in bookingLifecycle.ts**

Update the `LifecycleFieldPermission` interface (currently at line 15–18):

```typescript
export interface LifecycleFieldPermission {
  editable_fields: string[];
  editable_by: string[];
  custom_fields?: Record<string, { editable_by: string[] }>; // new
}
```

- [ ] **Step 2: Add CustomFieldPermission and extend BookingResponse in booking.ts**

Add at the top of `frontend/src/types/booking.ts`:

```typescript
export interface CustomFieldPermission {
  visible: boolean;
  editable: boolean;
}
```

Add `custom_field_permissions` to the existing `BookingResponse` interface. The current interface ends with `updated_at: string;` — add after `custom_fields`:

```typescript
export interface BookingResponse {
  id: number;
  environment_id: number;
  environment_name: string | null;
  project_name: string;
  booked_by: number;
  booked_by_username: string | null;
  start_date: string;
  end_date: string;
  booking_type_id: number;
  exclusive_use: boolean;
  status: string;
  notes: string | null;
  recurrence_rule: string | null;
  recurrence_parent_id: number | null;
  release_id: number | null;
  test_phase_id: number | null;
  context_tag: ContextTag;
  custom_fields: Record<string, unknown> | null;
  custom_field_permissions?: Record<string, CustomFieldPermission>; // new
  tenant_id: number;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 3: Add customFieldService method for PATCH**

In `frontend/src/services/customFieldService.ts` — check if a `patchBookingCustomFields` function exists. If not, note that we can call it via the booking service.

Add to `frontend/src/services/bookingService.ts` inside the `bookingService` object (matching the existing arrow-function style):

```typescript
  updateCustomFields: (id: number, values: Record<string, unknown>): Promise<BookingResponse> =>
    api.patch(`/bookings/${id}/custom-fields`, values).then((r) => r.data),
```

- [ ] **Step 4: Run TypeScript check**

```bash
cd frontend && npm run type-check 2>&1 | head -50
```

If `type-check` script doesn't exist, use: `npx tsc --noEmit 2>&1 | head -50`

Expected: No new type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/bookingLifecycle.ts frontend/src/types/booking.ts frontend/src/services/bookingService.ts
git commit -m "feat: add CustomFieldPermission types and extend BookingResponse"
```

---

## Task 5: Frontend BookingForm — Filter Custom Fields by Initial State

**Files:**
- Modify: `frontend/src/pages/bookings/BookingForm.tsx`

The form currently shows ALL booking custom field definitions regardless of selected type. We need to filter to only those visible in the selected type's initial state.

- [ ] **Step 1: Add templates selector**

In `BookingForm.tsx`, add `templates` to the Redux selectors (currently around line 64–67):

```typescript
const { bookingTypes, templates } = useSelector((s: RootState) => s.bookingLifecycle);
```

Ensure `fetchLifecycleTemplates` is dispatched on mount (add alongside `fetchBookingTypes` around line 87–89):

```typescript
useEffect(() => {
  dispatch(fetchDefinitions('booking'));
  dispatch(fetchBookingTypes());
  dispatch(fetchLifecycleTemplates());
}, [dispatch]);
```

- [ ] **Step 2: Derive visible custom field definitions**

Add a derived value after the booking type auto-select `useEffect` (around line 96):

```typescript
const visibleCustomFieldDefs = useMemo(() => {
  if (!bookingTypeId) return [];
  const bt = bookingTypes.find((t) => t.id === bookingTypeId);
  if (!bt) return [];
  const template = templates.find((t) => t.id === bt.lifecycle_template_id);
  if (!template) return [];
  const initialState = template.definition.states.find((s) => s.is_initial);
  if (!initialState) return [];
  const cfPerms = template.definition.field_permissions[initialState.key]?.custom_fields ?? {};
  const visibleKeys = new Set(Object.keys(cfPerms));
  return customFieldDefs.filter((d) => visibleKeys.has(d.field_key));
}, [bookingTypeId, bookingTypes, templates, customFieldDefs]);
```

Add `useMemo` to the import from React at the top of the file.

- [ ] **Step 3: Use visibleCustomFieldDefs in CustomFieldsSection**

Find the existing `<CustomFieldsSection>` render call in `BookingForm.tsx` and replace it:

```tsx
{/* Custom Fields */}
<CustomFieldsSection
  definitions={visibleCustomFieldDefs}
  values={customFieldValues}
  onChange={setCustomFieldValues}
/>
```

- [ ] **Step 4: Verify in browser**

Start the dev server and open a "New Booking" dialog. Switch booking types — custom fields should change to show only those configured for the selected type's initial state. If no types have `custom_fields` configured yet (templates were created before this feature), no custom fields appear, which is the safe default.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/bookings/BookingForm.tsx
git commit -m "feat: filter booking form custom fields by selected type's initial state"
```

---

## Task 6: Frontend BookingDetail — Display and Edit Custom Fields Per Permissions

**Files:**
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx`

BookingDetail currently shows no custom fields. We add a section that:
1. Shows visible custom fields read-only via `CustomFieldsDisplay`
2. For fields that are editable, shows an "Edit Custom Fields" button that opens an inline edit dialog

- [ ] **Step 1: Add imports and custom field definitions selector**

At the top of `BookingDetail.tsx`, add:
```typescript
import { useSelector } from 'react-redux';
import type { RootState } from '../../store';
import { fetchDefinitions } from '../../store/customFieldSlice';
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay';
import CustomFieldsSection from '../../components/CustomFieldsSection';
```

Add the selector in the component body after the existing Redux hooks:
```typescript
const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['booking'] ?? []);
```

Add to the `useEffect` that calls `dispatch`:
```typescript
dispatch(fetchDefinitions('booking'));
```

- [ ] **Step 2: Add edit dialog state**

After the existing `useState` declarations add:
```typescript
const [editingCustomFields, setEditingCustomFields] = useState(false);
const [cfEditValues, setCfEditValues] = useState<Record<string, unknown>>({});
const [cfSaving, setCfSaving] = useState(false);
```

- [ ] **Step 3: Add custom fields section to the render**

After the closing `</Paper>` that contains booking details (around line 235), and before the `<Divider />`, add:

```tsx
{/* Custom Fields */}
{(() => {
  const perms = booking.custom_field_permissions ?? {};
  const visibleDefs = customFieldDefs.filter((d) => d.field_key in perms);
  const editableDefs = visibleDefs.filter((d) => perms[d.field_key]?.editable);
  if (visibleDefs.length === 0) return null;
  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle2">Custom Fields</Typography>
        {editableDefs.length > 0 && (
          <Button
            size="small"
            onClick={() => {
              setCfEditValues(
                Object.fromEntries(
                  editableDefs.map((d) => [d.field_key, booking.custom_fields?.[d.field_key] ?? ''])
                )
              );
              setEditingCustomFields(true);
            }}
          >
            Edit
          </Button>
        )}
      </Box>
      <CustomFieldsDisplay definitions={visibleDefs} values={booking.custom_fields} />
    </Paper>
  );
})()}
```

- [ ] **Step 4: Add edit dialog**

Add the edit dialog just before the closing `</Box>` of the component:

```tsx
{/* Edit Custom Fields Dialog */}
<Dialog open={editingCustomFields} onClose={() => setEditingCustomFields(false)} maxWidth="sm" fullWidth>
  <DialogTitle>Edit Custom Fields</DialogTitle>
  <DialogContent sx={{ pt: 2 }}>
    {(() => {
      const perms = booking?.custom_field_permissions ?? {};
      const editableDefs = customFieldDefs.filter((d) => perms[d.field_key]?.editable);
      return (
        <CustomFieldsSection
          definitions={editableDefs}
          values={cfEditValues}
          onChange={setCfEditValues}
        />
      );
    })()}
  </DialogContent>
  <DialogActions>
    <Button onClick={() => setEditingCustomFields(false)}>Cancel</Button>
    <Button
      variant="contained"
      disabled={cfSaving}
      onClick={async () => {
        setCfSaving(true);
        try {
          const updated = await bookingService.updateCustomFields(bookingId, cfEditValues);
          setBooking(updated);
          setEditingCustomFields(false);
        } catch (err: unknown) {
          const msg =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Save failed';
          setError(msg);
        } finally {
          setCfSaving(false);
        }
      }}
    >
      {cfSaving ? 'Saving...' : 'Save'}
    </Button>
  </DialogActions>
</Dialog>
```

Add `Dialog`, `DialogTitle`, `DialogContent`, `DialogActions` to the MUI imports at the top.

- [ ] **Step 5: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -50
```

Expected: No errors.

- [ ] **Step 6: Verify in browser**

Open a booking detail. Custom fields should now appear in a "Custom Fields" paper section below the main details. If the booking is in a state where fields are editable for the current user, an "Edit" button appears.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/bookings/BookingDetail.tsx
git commit -m "feat: add custom fields display and edit to booking detail page"
```

---

## Task 7: Frontend LifecycleTemplatesPanel — Field Permissions Editor + Edit Dialog

> **Prerequisite:** Task 4 must be completed first so that `LifecycleFieldPermission` includes `custom_fields?` in TypeScript types.

**Files:**
- Modify: `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`

This is the largest frontend task. We add:
1. A `FieldPermissions` editor section in the create dialog (per-state: custom fields visibility + editable_by roles)
2. An "Edit" button on each template row that opens the same form pre-populated

- [ ] **Step 1: Add FieldPermState type and state**

At the top of the file (after the existing `interface TransitionRow`), add:

```typescript
interface FieldPermState {
  editable_fields: string[];
  editable_by: string[];
  custom_fields: Record<string, { editable_by: string[] }>;
}
```

In the component, add these new state variables (after the existing `useState` declarations):

```typescript
const [fieldPerms, setFieldPerms] = useState<Record<string, FieldPermState>>({});
```

And add the custom fields selector:
```typescript
const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['booking'] ?? []);
```

Add to the `useEffect`: `dispatch(fetchDefinitions('booking'));`

Import `fetchDefinitions` from `customFieldSlice` and add `RootState` to imports.

- [ ] **Step 2: Sync fieldPerms when states change**

When a state is added or its key changes, we need to keep `fieldPerms` in sync. Update the `updateState` helper:

```typescript
const updateState = (i: number, patch: Partial<StateRow>) => {
  setStates((prev) => {
    const oldKey = prev[i].key;
    const newStates = prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s));
    if (patch.key !== undefined && patch.key !== oldKey) {
      setFieldPerms((fp) => {
        const updated = { ...fp };
        if (oldKey in updated) {
          updated[patch.key!] = updated[oldKey];
          delete updated[oldKey];
        }
        return updated;
      });
    }
    return newStates;
  });
};
```

Update `removeState` to also clean up fieldPerms:
```typescript
const removeState = (i: number) => {
  const key = states[i].key;
  setStates((prev) => prev.filter((_, idx) => idx !== i));
  setFieldPerms((fp) => {
    const updated = { ...fp };
    delete updated[key];
    return updated;
  });
};
```

- [ ] **Step 3: Add Field Permissions editor section to the dialog**

After the closing `</Box>` of the Transitions section and before `</DialogContent>`, add:

```tsx
<Divider />

{/* Field Permissions */}
<Box>
  <Typography variant="subtitle2" sx={{ mb: 1 }}>Field Permissions (per state)</Typography>
  {stateKeys.length === 0 ? (
    <Typography variant="body2" color="text.secondary">Add states first.</Typography>
  ) : stateKeys.map((stateKey) => {
    const perm = fieldPerms[stateKey] ?? { editable_fields: [], editable_by: [], custom_fields: {} };
    const cfPerms = perm.custom_fields ?? {};
    return (
      <Box key={stateKey} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5, mb: 1 }}>
        <Typography variant="caption" fontWeight="bold">{stateKey}</Typography>

        {/* Custom fields */}
        {customFieldDefs.length > 0 && (
          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">Custom Fields</Typography>
            {customFieldDefs.map((defn) => {
              const included = defn.field_key in cfPerms;
              const editableBy = cfPerms[defn.field_key]?.editable_by ?? [];
              return (
                <Box key={defn.field_key} sx={{ ml: 1, mt: 0.5 }}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        size="small"
                        checked={included}
                        onChange={(e) => {
                          setFieldPerms((fp) => {
                            const statePerm = fp[stateKey] ?? { editable_fields: [], editable_by: [], custom_fields: {} };
                            const cf = { ...statePerm.custom_fields };
                            if (e.target.checked) {
                              cf[defn.field_key] = { editable_by: [] };
                            } else {
                              delete cf[defn.field_key];
                            }
                            return { ...fp, [stateKey]: { ...statePerm, custom_fields: cf } };
                          });
                        }}
                      />
                    }
                    label={defn.label}
                  />
                  {included && (
                    <Box sx={{ ml: 3, display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 0.5 }}>
                      {ROLES.map((role) => (
                        <Chip
                          key={role}
                          label={role}
                          size="small"
                          clickable
                          color={editableBy.includes(role) ? 'primary' : 'default'}
                          variant={editableBy.includes(role) ? 'filled' : 'outlined'}
                          onClick={() => {
                            setFieldPerms((fp) => {
                              const statePerm = fp[stateKey] ?? { editable_fields: [], editable_by: [], custom_fields: {} };
                              const cf = { ...statePerm.custom_fields };
                              const current = cf[defn.field_key]?.editable_by ?? [];
                              cf[defn.field_key] = {
                                editable_by: current.includes(role)
                                  ? current.filter((r) => r !== role)
                                  : [...current, role],
                              };
                              return { ...fp, [stateKey]: { ...statePerm, custom_fields: cf } };
                            });
                          }}
                        />
                      ))}
                    </Box>
                  )}
                </Box>
              );
            })}
          </Box>
        )}
      </Box>
    );
  })}
</Box>
```

- [ ] **Step 4: Wire fieldPerms into handleCreate**

Update `handleCreate` to include `field_permissions` built from `fieldPerms`. Replace the `field_permissions: {}` line in `handleCreate` with:

```typescript
field_permissions: Object.fromEntries(
  stateKeys.map((key) => {
    const perm = fieldPerms[key] ?? { editable_fields: [], editable_by: [], custom_fields: {} };
    return [key, {
      editable_fields: perm.editable_fields,
      editable_by: perm.editable_by,
      custom_fields: perm.custom_fields,
    }];
  })
),
```

Also reset `fieldPerms` in `handleOpen`:
```typescript
setFieldPerms({});
```

- [ ] **Step 5: Add edit dialog state and open-for-edit logic**

Add state:
```typescript
const [editTemplateId, setEditTemplateId] = useState<number | null>(null);
```

Add a helper to open the dialog pre-populated from an existing template:
```typescript
const handleEditOpen = (template: BookingLifecycleTemplate) => {
  setEditTemplateId(template.id);
  setName(template.name);
  setDescription(template.description ?? '');
  setStates(template.definition.states.map((s) => ({
    key: s.key, label: s.label, is_initial: s.is_initial, is_terminal: s.is_terminal,
  })));
  setTransitions(template.definition.transitions.map((t) => ({
    from_state: t.from_state, to_state: t.to_state, label: t.label, allowed_roles: t.allowed_roles,
  })));
  const fp: Record<string, FieldPermState> = {};
  for (const [stateKey, perm] of Object.entries(template.definition.field_permissions ?? {})) {
    fp[stateKey] = {
      editable_fields: perm.editable_fields ?? [],
      editable_by: perm.editable_by ?? [],
      custom_fields: (perm.custom_fields as Record<string, { editable_by: string[] }>) ?? {},
    };
  }
  setFieldPerms(fp);
  setError(null);
  setOpen(true);
};
```

- [ ] **Step 6: Add handleEdit action and update handleCreate to branch**

```typescript
const handleSave = async () => {
  const err = validate();
  if (err) { setError(err); return; }
  setError(null);
  setSaving(true);
  const definition = {
    states: states.map((s) => ({ key: s.key.trim(), label: s.label.trim(), is_initial: s.is_initial, is_terminal: s.is_terminal })),
    transitions: transitions.map((t) => ({ from_state: t.from_state, to_state: t.to_state, label: t.label.trim(), allowed_roles: t.allowed_roles })),
    field_permissions: Object.fromEntries(
      stateKeys.map((key) => {
        const perm = fieldPerms[key] ?? { editable_fields: [], editable_by: [], custom_fields: {} };
        return [key, { editable_fields: perm.editable_fields, editable_by: perm.editable_by, custom_fields: perm.custom_fields }];
      })
    ),
  };

  let result;
  if (editTemplateId !== null) {
    result = await dispatch(updateLifecycleTemplate({ id: editTemplateId, data: { name: name.trim(), description: description.trim() || null, definition } }));
  } else {
    result = await dispatch(createLifecycleTemplate({ name: name.trim(), description: description.trim() || null, is_default: false, definition }));
  }
  setSaving(false);
  if ('error' in result) {
    setError(result.error.message ?? 'Failed to save template');
    return;
  }
  setEditTemplateId(null);
  handleClose();
};
```

Replace `handleCreate` with `handleSave` throughout and update the dialog button to call `handleSave`.

Also reset `editTemplateId` to `null` in `handleOpen` and `handleClose`.

- [ ] **Step 7: Add "Edit" button to DataGrid columns**

Update the `actions` column in the DataGrid `columns` array to include an Edit button alongside Copy:

```typescript
{
  field: 'actions',
  headerName: '',
  width: 140,
  sortable: false,
  renderCell: (params) => (
    <Box sx={{ display: 'flex', gap: 0.5 }}>
      <Button
        size="small"
        onClick={() => handleEditOpen(params.row as BookingLifecycleTemplate)}
      >
        Edit
      </Button>
      <Button
        size="small"
        onClick={() =>
          dispatch(copyLifecycleTemplate({ id: params.row.id as number, name: `${params.row.name as string} (copy)` }))
        }
      >
        Copy
      </Button>
    </Box>
  ),
},
```

Import `BookingLifecycleTemplate` type if not already imported.

Update the `DialogTitle` to be dynamic:
```tsx
<DialogTitle>{editTemplateId !== null ? 'Edit Lifecycle Template' : 'New Lifecycle Template'}</DialogTitle>
```

Update the save button label:
```tsx
<Button variant="contained" onClick={handleSave} disabled={saving}>
  {saving ? 'Saving...' : editTemplateId !== null ? 'Save Changes' : 'Create'}
</Button>
```

- [ ] **Step 8: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -50
```

Expected: No errors.

- [ ] **Step 9: Verify in browser**

1. Go to Booking Admin → Lifecycle Templates
2. Click "New Template" — after adding states, a "Field Permissions" section should appear listing booking custom fields with checkboxes and role chips
3. Click "Edit" on an existing template — dialog opens pre-populated
4. Save — template updates in the list

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/admin/LifecycleTemplatesPanel.tsx
git commit -m "feat: add field permissions editor and edit dialog to lifecycle templates panel"
```

---

## Final Verification

- [ ] **Run all backend tests**

```bash
cd backend && uv run pytest -v
```

Expected: All pass.

- [ ] **Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **End-to-end smoke test**

1. Create a custom field (`entity_type = "booking"`, key = `release_notes`, type = `text`)
2. Create a lifecycle template with `field_permissions.draft.custom_fields.release_notes.editable_by = ["Admin"]`
3. Assign the template to a booking type
4. Create a booking of that type
5. Open booking detail → custom fields section shows `release_notes` (editable for Admin)
6. Click Edit → save a value
7. Transition booking to `submitted` (where `release_notes` is not listed)
8. Booking detail no longer shows `release_notes`
9. `PATCH /api/v1/bookings/{id}/custom-fields` with `{"release_notes": "..."}` returns 403

- [ ] **Final commit if any loose ends**

```bash
git add -p  # review and stage any remaining changes
git commit -m "feat: complete booking custom field type/state permissions"
```
