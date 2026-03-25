# Booking Custom Field — Type Scoping, State Visibility & Edit Permissions

**Date:** 2026-03-25
**Status:** Approved

## Overview

Extend booking custom fields so that:

1. A field only appears on booking types whose lifecycle template explicitly references its key
2. A field is only visible in states where the template lists it
3. Edit access is per-field per-state per-role; all other roles see the field read-only

## Background

The existing `CustomFieldDefinition` model has `entity_type = "booking"` which currently applies a field to all bookings regardless of type or state. A `lifecycle_states` column exists but is a flat list with no booking-type context.

The `BookingLifecycleTemplate.definition` JSONB already owns per-state access rules for core fields via `field_permissions`. This design extends that mechanism to cover custom fields, keeping all field-access logic in one place.

## Data Model

No database schema migrations required. The change is purely to the shape of the `definition` JSONB column on `BookingLifecycleTemplate`.

### Extended `field_permissions` structure

```json
"field_permissions": {
  "draft": {
    "editable_fields": ["project_name", "start_date", "end_date", "notes"],
    "editable_by": ["Admin", "Release Manager"],
    "custom_fields": {
      "release_notes": { "editable_by": ["Release Manager", "Admin"] },
      "sign_off_url":  { "editable_by": ["Test Manager"] }
    }
  },
  "submitted": {
    "editable_fields": [],
    "editable_by": [],
    "custom_fields": {
      "release_notes": { "editable_by": [] },
      "sign_off_url":  { "editable_by": ["Test Manager"] }
    }
  }
}
```

### Rules

| Condition | Result |
|---|---|
| Key present in state's `custom_fields` | Field is **visible** in that state |
| Key absent from state's `custom_fields` | Field is **hidden** in that state |
| User role in `editable_by` | Field is **editable** |
| User role NOT in `editable_by` | Field is **read-only** |
| `editable_by: []` | Field is visible but **read-only for all roles** |
| Field key in template but `CustomFieldDefinition` soft-deleted | Hidden (filtered out server-side) |

Booking-type scoping is implicit: a field appears only on booking types whose lifecycle template references its key in at least one state.

### `required` and state visibility

State-driven visibility supersedes the `required` flag. A custom field marked `required` is only enforced by the backend in states where it is visible (i.e. listed in that state's `custom_fields` config). If a field is hidden in the current state, it is not validated as required on save.

## Backend Changes

### `backend/app/api/v1/schemas/booking_lifecycle.py`

Add two new Pydantic models:

```python
class CustomFieldPermission(BaseModel):
    editable_by: list[str]

    @field_validator("editable_by")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}")
        return v


class LifecycleFieldPermission(BaseModel):
    editable_fields: list[str]   # validated against VALID_FIELD_NAMES
    editable_by: list[str]       # validated against VALID_ROLES
    custom_fields: Optional[dict[str, CustomFieldPermission]] = None  # new
```

Custom field keys in `custom_fields` are free-form snake_case strings — not validated against `VALID_FIELD_NAMES` since they are dynamically defined per tenant. The `Optional` means existing templates without `custom_fields` validate and round-trip correctly with no changes.

### `backend/app/services/booking_lifecycle_service.py`

Add a new helper function. It accepts the set of active (non-deleted) custom field keys for the tenant so it can exclude stale references:

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
    soft-deleted, are omitted (hidden).
    """
    perm = definition.get("field_permissions", {}).get(current_state, {})
    result = {}
    for key, entry in perm.get("custom_fields", {}).items():
        if key not in active_field_keys:
            continue  # definition was soft-deleted; skip silently
        editable_by = entry.get("editable_by", [])
        result[key] = {
            "visible": True,
            "editable": user_role in editable_by,
        }
    return result
```

The caller fetches active `CustomFieldDefinition` keys for the tenant (a single cheap query) and passes them in.

### Booking API response

`custom_field_permissions` is computed and returned on the **single-booking GET endpoint only** (`GET /bookings/{id}`). It is not included in list or calendar endpoints to avoid the N+1 template load cost.

The block is resolved server-side from the booking's current state, its type's lifecycle template, the requesting user's role, and the tenant's active custom field keys:

```json
{
  "id": 42,
  "status": "submitted",
  "custom_fields": {
    "release_notes": "v1.2 release notes",
    "sign_off_url": ""
  },
  "custom_field_permissions": {
    "release_notes": { "visible": true, "editable": false },
    "sign_off_url":  { "visible": true, "editable": true }
  }
}
```

Only keys listed in the current state's `custom_fields` template config (and not soft-deleted) appear in this map. Keys absent = hidden; the frontend does not render them.

### `backend/app/api/v1/schemas/booking.py`

Extend `BookingResponse` with:

```python
custom_field_permissions: Optional[dict[str, dict]] = None
```

## Frontend Changes

### Admin: Lifecycle Template Editor

The lifecycle template editor UI (create and edit dialogs in `LifecycleTemplatesPanel`) needs a **Custom Fields** subsection within each state's field permissions section:

- Fetches all `CustomFieldDefinition` records with `entity_type = "booking"` from the existing Redux custom fields store
- Per field: checkbox to include it in the state + multi-select chip input for `editable_by` roles
- Unchecked fields are omitted from `custom_fields` in the saved template definition (hidden in that state)

This applies to both the new-template creation dialog and any edit dialog. If a full template edit UI does not yet exist, it must be built as part of this work (the create dialog already exists from the lifecycle tab implementation).

### Booking Form — creation (`BookingForm.tsx`)

At creation time no booking ID exists yet, so `custom_field_permissions` must be derived client-side from the **selected booking type's lifecycle template for its initial state**. The Redux store already holds booking types and lifecycle templates.

- When the user selects a booking type, resolve the template's initial state and call a client-side helper equivalent to `get_custom_field_permissions` to determine which custom fields to show and in what mode
- Only definitions matching the resolved visible keys are passed to the form's custom fields section

### Booking Detail — view/edit (`BookingDetail.tsx`)

Consume `custom_field_permissions` from the booking GET response:

| `custom_field_permissions[key]` | Render |
|---|---|
| Absent (key not in map) | Do not render |
| `{ visible: true, editable: false }` | Render via `CustomFieldsDisplay` (read-only) |
| `{ visible: true, editable: true }` | Render as editable input |

The caller pre-filters the `CustomFieldDefinition[]` array to only those keys present in `custom_field_permissions` before passing it to `CustomFieldsSection` / `CustomFieldsDisplay`. No component signature changes needed.

### Type changes

**`frontend/src/types/booking.ts`**

```typescript
interface CustomFieldPermission {
  visible: boolean;
  editable: boolean;
}

// Added to BookingDetail / BookingResponse:
custom_field_permissions?: Record<string, CustomFieldPermission>;
```

**`frontend/src/types/bookingLifecycle.ts`** (or equivalent lifecycle types file)

```typescript
// Extended LifecycleFieldPermission:
interface LifecycleFieldPermission {
  editable_fields: string[];
  editable_by: string[];
  custom_fields?: Record<string, { editable_by: string[] }>; // new
}
```

## What Does NOT Change

- `CustomFieldDefinition` model and its API — no new columns, no migration
- The existing `lifecycle_states` column on `CustomFieldDefinition` — deprecated in favour of template-driven visibility but left in place for non-booking entity types
- Core field permissions (`editable_fields` / `editable_by`) — unchanged
- `CustomFieldsDisplay` and `CustomFieldsSection` component signatures — reused as-is; callers pre-filter which definitions to pass

## Out of Scope

- Migrating existing templates to add `custom_fields` config (existing templates with no `custom_fields` key simply show no custom fields — safe default)
- UI for configuring custom field definitions themselves (already exists in `CustomFieldDefinitionManager`)
- Adding `custom_field_permissions` to list/calendar booking endpoints (performance concern; single-booking GET only)
