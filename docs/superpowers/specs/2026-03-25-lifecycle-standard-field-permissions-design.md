# Design: Standard Field Permissions in Lifecycle Templates

**Date:** 2026-03-25
**Status:** Approved
**Branch:** phase-1

---

## Problem

The lifecycle template editor allows per-state, per-role configuration of custom field editability, but standard booking fields (project_name, start_date, end_date, booking_type, notes, exclusive_use, context_tag) have no per-state permission configuration in the editor UI. The existing data shape (`editable_fields: string[]`, `editable_by: string[]`) groups all standard fields under a single shared role set — there is no per-field role configuration. The backend also performs no enforcement of standard field permissions on booking updates.

---

## Goals

- Standard fields are always visible in all lifecycle states (no state-scoped visibility toggle).
- Each standard field has per-state, per-role editability configuration matching how custom fields work.
- Fields with no configured editable roles default to read-only for all users.
- Validation prevents saving a template where a mandatory standard field has no editable role in the initial state.
- Backend enforces standard field permissions on booking update, returning 403 for unauthorised changes.
- Frontend reflects permissions returned by the API — no client-side permission logic.

---

## Standard Fields in Scope

| Field (permission key) | Model column | Mandatory (must be editable in initial state) |
|---|---|---|
| project_name | project_name | Yes |
| start_date | start_date | Yes |
| end_date | end_date | Yes |
| booking_type | booking_type_id | Yes |
| notes | notes | No |
| exclusive_use | exclusive_use | No |
| context_tag | context_tag | No |

The permission key `booking_type` maps to the model column `booking_type_id`. The `update_standard_fields` service accepts `booking_type_id` in the PATCH body and maps it to `booking_type` internally when checking permissions.

Note: `booking_type` may be made editable in non-initial states per the admin's configuration. The consequences of changing booking_type mid-lifecycle (template switching) are out of scope for this change.

---

## Data Model

### Before

```json
{
  "editable_fields": ["start_date", "end_date", "notes"],
  "editable_by": ["Admin", "Release Manager"],
  "custom_fields": { "ticket_ref": { "editable_by": ["Admin"] } }
}
```

### After

```json
{
  "standard_fields": {
    "project_name":  { "editable_by": ["Admin", "Developer"] },
    "start_date":    { "editable_by": ["Admin", "Release Manager"] },
    "end_date":      { "editable_by": ["Admin", "Release Manager"] },
    "booking_type":  { "editable_by": ["Admin"] },
    "notes":         { "editable_by": ["Admin", "Developer"] },
    "exclusive_use": { "editable_by": ["Admin"] },
    "context_tag":   { "editable_by": ["Admin", "Release Manager"] }
  },
  "custom_fields": { "ticket_ref": { "editable_by": ["Admin"] } }
}
```

Fields absent from `standard_fields` or with an empty `editable_by` array are read-only for all users in that state. The old `editable_fields` and `editable_by` keys are removed.

### Write-time migration

Existing templates are migrated the first time they are written (create, update, or copy) after deployment. The `booking_lifecycle_service` migration helper is called before save in all three paths.

**Conversion rule:** For each field in the old `editable_fields` list, set `editable_by` to the old `editable_by` list. Fields absent from `editable_fields` (which includes `booking_type`, `exclusive_use`, `context_tag` — these were never in the old validator) get `editable_by: []` (read-only). This is a conservative migration — admins will need to configure roles for newly visible fields.

**Frontend migration shim:** Because write-time migration only covers templates that have been saved after deployment, `handleEditOpen` must handle both shapes. If the loaded definition contains `editable_fields`/`editable_by` (old shape), apply the same conversion rule client-side to initialise `fieldPerms`.

No Alembic migration is needed; the definition is stored as JSON in a single column.

### TypeScript type update (`frontend/src/types/bookingLifecycle.ts`)

```typescript
interface LifecycleFieldPermission {
  standard_fields: Record<string, { editable_by: string[] }>;
  custom_fields?: Record<string, { editable_by: string[] }>;
}
```

The old `editable_fields: string[]` and `editable_by: string[]` keys are removed.

---

## Backend Changes

### `backend/app/api/v1/schemas/booking_lifecycle.py`

Replace `LifecycleFieldPermission` and remove `VALID_FIELD_NAMES` (the old constant included a vestigial `"custom_fields"` entry and is no longer needed):

```python
VALID_STANDARD_FIELD_NAMES = {
    "project_name", "start_date", "end_date", "booking_type",
    "notes", "exclusive_use", "context_tag"
}

MANDATORY_STANDARD_FIELDS = {"project_name", "start_date", "end_date", "booking_type"}

class StandardFieldPermission(BaseModel):
    editable_by: list[str]

    @field_validator("editable_by")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}. Must be one of {VALID_ROLES}")
        return v

class LifecycleFieldPermission(BaseModel):
    standard_fields: dict[str, StandardFieldPermission] = {}
    custom_fields: Optional[dict[str, CustomFieldPermission]] = None

    @field_validator("standard_fields")
    @classmethod
    def validate_field_names(cls, v):
        invalid = set(v.keys()) - VALID_STANDARD_FIELD_NAMES
        if invalid:
            raise ValueError(f"Invalid standard field names: {invalid}")
        return v
```

Also remove the old `validate_fields` validator from `LifecycleFieldPermission` and the `VALID_FIELD_NAMES` constant.

Add a `@model_validator(mode="after")` on `LifecycleDefinition` (not a `@field_validator` — the validator needs access to both `self.states` and `self.field_permissions`): look up the initial state key from `self.states` (guaranteed unique by `validate_one_initial`), then check that each field in `MANDATORY_STANDARD_FIELDS` appears in `self.field_permissions[initial_state_key].standard_fields` with at least one role in `editable_by`.

### `backend/app/services/booking_lifecycle_service.py`

**Remove `get_editable_fields`** — this function reads the old `editable_fields`/`editable_by` shape and is currently imported by `booking_service.py` but never called (dead code). Remove the function and remove the import from `booking_service.py`.

Add migration helper:

```python
def migrate_field_permissions(definition: dict) -> dict:
    """Convert old editable_fields/editable_by shape to standard_fields per-field shape.
    A template is considered old-shape if ANY state entry in field_permissions contains
    the key 'editable_fields'. Every such state entry is converted; state entries already
    in the new shape are left untouched. Returns the mutated definition dict."""
```

Call this helper before save in `create_template`, `update_template`, and `copy_template`.

### `backend/app/services/booking_service.py`

Remove the import of `get_editable_fields` from `booking_lifecycle_service`.

Add helper in `booking_service.py`:

```python
def get_standard_field_permissions(
    definition: dict, state_key: str, user_role: str
) -> set[str]:
    """Returns the set of standard permission keys (e.g. 'start_date', 'booking_type')
    editable by user_role in state_key. Fail-closed (empty set) if state not configured."""
```

Add helper in `booking_service.py` (same module as `get_custom_field_perms_for_booking`):

```python
async def get_standard_field_perms_for_booking(
    db: AsyncSession, booking: Booking, user_role: str
) -> dict[str, dict]:
    """Load lifecycle template and return editable status for all 7 standard fields
    for the booking's current state and user role.
    Returns { "project_name": {"editable": True}, "start_date": {"editable": False}, ... }
    All 7 standard fields are always present in the response."""
```

Add service function:

```python
async def update_standard_fields(
    db: AsyncSession, booking_id: int, values: dict, current_user
) -> Booking:
    """Update standard fields on a booking subject to lifecycle permissions.
    `values` is a dict of model column names (e.g. {"booking_type_id": 3, "notes": "..."}).
    All submitted keys are treated as attempted changes regardless of whether the value
    differs from the current stored value.
    Raises HTTP 403 if any submitted key is not in VALID_STANDARD_FIELD_NAMES (unknown field)
    or is not editable for the user's role in the current state (permission denied). This matches
    the behaviour of update_custom_fields.
    Each key maps directly to a Booking model column — no JSON merge, no partial-update pattern."""
```

**Field name mapping inside `update_standard_fields`:** The permission key `booking_type` maps to the model column `booking_type_id`. When checking permissions, translate `booking_type_id` in the submitted body to `booking_type` before looking up the permission set.

### `backend/app/api/v1/bookings.py`

Add new endpoint following the existing `custom-fields` pattern:

```python
@router.patch("/{booking_id}/standard-fields", response_model=BookingResponse)
async def update_standard_fields(
    booking_id: int,
    values: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    booking = await booking_service.update_standard_fields(db, booking_id, values, current_user)
    resp = _to_response(booking)
    resp.custom_field_permissions = await booking_service.get_custom_field_perms_for_booking(
        db, booking, current_user.role
    )
    resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
        db, booking, current_user.role
    )
    return resp
```

Also update the existing `GET /{booking_id}` endpoint to populate `standard_field_permissions` alongside `custom_field_permissions`:

```python
resp.standard_field_permissions = await booking_service.get_standard_field_perms_for_booking(
    db, booking, current_user.role
)
```

### `backend/app/api/v1/schemas/booking.py`

Add to `BookingResponse`:

```python
standard_field_permissions: Optional[dict[str, dict]] = None
```

The list endpoint (`GET /bookings/`) does **not** include `standard_field_permissions` — consistent with how `custom_field_permissions` is only populated on the detail endpoint.

---

## Frontend Changes

### `frontend/src/types/bookingLifecycle.ts`

Update `LifecycleFieldPermission` as shown in Data Model section.

### `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`

**Update internal `FieldPermState` type:**

```typescript
interface FieldPermState {
  standard_fields: Record<string, { editable_by: string[] }>;
  custom_fields: Record<string, { editable_by: string[] }>;
}
```

Remove `editable_fields: string[]` and `editable_by: string[]`.

**`handleEditOpen` — migration shim for old-shape templates:**

```typescript
// If template still has old shape (never re-saved post-migration):
if (perm.editable_fields !== undefined) {
  // Convert: fields in editable_fields inherit editable_by; others get []
  const oldEditableBy = perm.editable_by ?? [];
  fp[stateKey] = {
    standard_fields: Object.fromEntries(
      STANDARD_FIELDS.map((f) => [
        f,
        { editable_by: perm.editable_fields.includes(f) ? oldEditableBy : [] }
      ])
    ),
    custom_fields: perm.custom_fields ?? {},
  };
} else {
  fp[stateKey] = {
    standard_fields: perm.standard_fields ?? {},
    custom_fields: perm.custom_fields ?? {},
  };
}
```

Where `STANDARD_FIELDS` is the constant list of the 7 standard field keys.

**Field Permissions UI section** — for each state block, render two sub-sections:

**Standard Fields** (always shown, all 7 fields, no include/exclude checkbox):
- Each field row shows the field label and role chips.
- Clicking a chip toggles that role's editability for that field in that state.
- Fields with empty `editable_by` show "read-only in this state" in muted text rather than role chips.

**Custom Fields** — unchanged; include/exclude checkbox retained since custom fields are state-scoped.

**`handleSave`** must write `standard_fields` (not `editable_fields`/`editable_by`) in the definition payload:

```typescript
field_permissions: Object.fromEntries(
  stateKeys.map((key) => {
    const perm = fieldPerms[key] ?? { standard_fields: {}, custom_fields: {} };
    return [key, { standard_fields: perm.standard_fields, custom_fields: perm.custom_fields }];
  })
)
```

**Validation on save** runs in this order:
1. Existing checks (name, at least one state, exactly one initial, unique keys, transition validity).
2. Mandatory field check: for the initial state, each of `project_name`, `start_date`, `end_date`, `booking_type` must have at least one role in `editable_by`. The initial state is unambiguously identified because step 1 already enforced exactly one initial state. An inline warning is shown per offending field; save is blocked until resolved.

### Booking detail / edit form

- `BookingResponse` gains `standard_field_permissions`.
- The booking detail Redux slice passes this through to the UI.
- Each standard field in the booking edit form renders as `readOnly` when `standard_field_permissions[fieldName]?.editable === false`.
- No client-side permission logic — the frontend reflects the API response only.
- Rendering each field type (text, date picker, dropdown for booking_type, checkbox for exclusive_use) is handled by the existing booking form; this change only adds the `readOnly` gate.

---

## Out of Scope

- Configuring field *visibility* per state for standard fields (always visible).
- Adding new standard fields beyond the 7 listed.
- Per-field validation rules (e.g., date range constraints).
- Template-switching consequences when `booking_type` is changed mid-lifecycle.
