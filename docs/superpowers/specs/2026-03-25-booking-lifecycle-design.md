# Booking Lifecycle & Booking Types — Design Spec

**Date:** 2026-03-25
**Status:** Approved

---

## Context

EnvManager currently has a hardcoded 3-state booking lifecycle (PENDING → APPROVED / REJECTED). The `booking_type` field controls concurrency (SHARED vs EXCLUSIVE), not workflow. There is no concept of named booking types with configurable workflows.

This spec introduces:
- **Admin-defined booking types** (e.g. "Standard Booking", "Emergency Booking") — each references a reusable lifecycle template
- **Lifecycle templates** stored as JSONB — defining states, role-gated transitions, and field-level edit permissions per state
- **Full audit trail** via `booking_status_history` — powering KPI reporting (time-in-state) and per-booking history timeline
- **Migration** of existing bookings to the new model

---

## Design Decisions

| Decision | Resolution |
|----------|-----------|
| Lifecycle definition storage | JSONB on `booking_lifecycle_templates` — consumed as a whole unit; atomic updates propagate to all booking types referencing the template |
| Shared vs exclusive | Rename `booking_type` (SHARED/EXCLUSIVE) → `exclusive_use: bool` — concurrency is orthogonal to booking type |
| Template vs copy | Lifecycle templates are shared references — multiple booking types can use the same template; updating it propagates automatically. Copying creates a new independent template as a starting point |
| Role guards | Use existing roles: Admin, ReleaseManager, User |
| Audit trail | Dedicated `booking_status_history` table — `from_state`, `to_state`, `changed_by`, `changed_at` |
| Backward compatibility | Existing `/approve` and `/reject` endpoints kept as shortcuts that call `transition_state` internally |

---

## Default Lifecycle

### States

| Key | Label | Initial | Terminal |
|-----|-------|---------|---------|
| `draft` | Draft | ✓ | |
| `submitted` | Submitted | | |
| `approved` | Approved | | |
| `rejected` | Rejected | | ✓ |
| `extension_requested` | Extension Request | | |
| `closed` | Closed | | ✓ |

### Transitions

| From | To | Label | Allowed Roles |
|------|----|-------|---------------|
| draft | submitted | Submit | Admin, ReleaseManager, User |
| submitted | approved | Approve | Admin, ReleaseManager |
| submitted | rejected | Reject | Admin, ReleaseManager |
| submitted | draft | Return for Revision | Admin, ReleaseManager |
| approved | extension_requested | Request Extension | Admin, ReleaseManager, User |
| extension_requested | approved | Approve Extension | Admin, ReleaseManager |
| extension_requested | rejected | Reject Extension | Admin, ReleaseManager |
| approved | closed | Close | Admin, ReleaseManager |

### Field Permissions per State

| State | Editable Fields | Who Can Edit |
|-------|----------------|-------------|
| draft | All fields + custom_fields | Admin, ReleaseManager, User |
| submitted | notes only | Admin, ReleaseManager |
| approved | notes only | Admin, ReleaseManager |
| rejected | none (locked) | — |
| extension_requested | notes, end_date | Admin, ReleaseManager |
| closed | none (locked) | — |

---

## Data Model

### New Table: `booking_lifecycle_templates`

| Column | Type | Notes |
|--------|------|-------|
| id | integer PK | |
| tenant_id | integer FK | |
| name | varchar(200) | |
| description | text | nullable |
| is_default | boolean | |
| definition | JSONB | validated by `LifecycleDefinition` Pydantic model |
| created_at, updated_at | timestamptz | |
| deleted_at | timestamptz | nullable, soft delete |

### New Table: `booking_types`

| Column | Type | Notes |
|--------|------|-------|
| id | integer PK | |
| tenant_id | integer FK | |
| name | varchar(200) | |
| description | text | nullable |
| lifecycle_template_id | integer FK | → `booking_lifecycle_templates` |
| color | varchar(7) | nullable, hex colour for UI badge |
| is_active | boolean | default true |
| created_at, updated_at | timestamptz | |
| deleted_at | timestamptz | nullable |

### New Table: `booking_status_history`

| Column | Type | Notes |
|--------|------|-------|
| id | integer PK | |
| booking_id | integer FK | |
| from_state | varchar | nullable (null = initial creation) |
| to_state | varchar | |
| changed_by | integer FK | → users |
| changed_at | timestamptz | |
| notes | text | nullable |

No `tenant_id` on this table — tenant isolation is enforced via the `booking_id` FK join to `bookings` (which has `tenant_id`). All history queries join through `bookings` to filter by tenant. History rows are never deleted (no `deleted_at`) — they are an immutable audit trail.

Time-in-state for KPIs = `next_row.changed_at − this_row.changed_at`.

### Changes to `bookings`

**Remove:**
- `booking_type` enum column (SHARED/EXCLUSIVE) — replaced by `exclusive_use` bool

**Replace in-place (same column name, different type):**
- `status` enum (PENDING/APPROVED/REJECTED) → `status` varchar — migration adds new varchar column, backfills, then drops enum column. Column name stays `status`.

**Add:**
- `exclusive_use` boolean — replaces `booking_type` SHARED/EXCLUSIVE
- `booking_type_id` integer FK → `booking_types`

### JSONB Schema (Pydantic models)

Valid `editable_fields` values (field name vocabulary): `project_name`, `start_date`, `end_date`, `notes`, `exclusive_use`, `custom_fields`. Admins may only reference these known field names when defining field permissions.

```python
class LifecycleState(BaseModel):
    key: str
    label: str
    is_initial: bool = False
    is_terminal: bool = False

class LifecycleTransition(BaseModel):
    from_state: str
    to_state: str
    label: str
    allowed_roles: list[str]

class LifecycleFieldPermission(BaseModel):
    editable_fields: list[str]
    editable_by: list[str]  # role names

class LifecycleDefinition(BaseModel):
    states: list[LifecycleState]
    transitions: list[LifecycleTransition]
    field_permissions: dict[str, LifecycleFieldPermission]  # keyed by state key
```

---

## Migration Plan

**All steps run in a single Alembic migration script** — seeding and backfill must be in the same migration to guarantee FK integrity.

1. Create new tables (`booking_lifecycle_templates`, `booking_types`, `booking_status_history`)
2. Add new nullable columns to `bookings` (`exclusive_use`, `booking_type_id`, new `status_new` varchar)
3. Seed one default `BookingLifecycleTemplate` per tenant (6-state default lifecycle above)
4. Seed one "Standard Booking" `BookingType` per tenant referencing the default template *(must precede step 5 so the FK target exists)*
5. Backfill `bookings`:
   - `exclusive_use`: EXCLUSIVE → true, SHARED → false
   - `booking_type_id`: set to the seeded default type
   - `status`: PENDING → `"submitted"`, APPROVED → `"approved"`, REJECTED → `"rejected"`
6. Backfill `booking_status_history`: one row per booking (`from_state=null`, `to_state=current migrated status`, `changed_at=bookings.created_at`, `changed_by=bookings.booked_by` — the `booked_by` integer FK column on `bookings` that references `users`)
7. Drop old `booking_type` enum column; drop old `status` enum column (after renaming new varchar column to `status`); make new `status` varchar and `booking_type_id` both NOT NULL. **Note:** steps 3–4 (seeding templates and default booking type) must complete before step 5 backfills `booking_type_id`, ensuring the FK target exists for all tenants.

---

## Services

### New: `BookingLifecycleService`

- `create_template(db, data, tenant_id)` — validates JSONB definition via Pydantic
- `update_template(db, id, data, tenant_id)` — propagates to all booking types via FK reference
- `copy_template(db, id, new_name, tenant_id)` — creates independent new template
- `list_templates(db, tenant_id)`
- `get_template(db, id, tenant_id)`
- `validate_transition(definition, from_state, to_state, user_role) → bool`
- `get_allowed_transitions(definition, current_state, user_role) → list[LifecycleTransition]`
- `get_editable_fields(definition, current_state, user_role) → list[str]`

### New: `BookingTypeService`

- `create_type(db, data, tenant_id)`
- `update_type(db, id, data, tenant_id)`
- `list_types(db, tenant_id)`
- `get_type(db, id, tenant_id)`

### Updated: `BookingService`

**New methods:**
- `transition_state(db, booking_id, to_state, current_user, notes=None)` — validates lifecycle + role; writes `booking_status_history` row; publishes event
- `get_status_history(db, booking_id, tenant_id) → list[BookingStatusHistory]`

**Updated methods:**
- `create_booking` — requires `booking_type_id` and `exclusive_use` (bool, default false); starts in initial state (`draft`); writes initial history row
- `approve_booking` / `reject_booking` — call `transition_state` internally
- `update_booking` — checks `get_editable_fields` for current state + user role; raises 403 if field not permitted. If a state has no entry in `field_permissions`, the default is **fail-closed** (all fields locked)

---

## API Endpoints

### Admin Settings (require_tenant_admin)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/admin/lifecycle-templates` | List all templates for tenant |
| POST | `/api/v1/admin/lifecycle-templates` | Create new template |
| PUT | `/api/v1/admin/lifecycle-templates/{id}` | Update template (auto-propagates) |
| POST | `/api/v1/admin/lifecycle-templates/{id}/copy` | Copy template as new independent template |
| GET | `/api/v1/admin/booking-types` | List booking types |
| POST | `/api/v1/admin/booking-types` | Create booking type |
| PUT | `/api/v1/admin/booking-types/{id}` | Update booking type |

> **Out of scope this phase:** DELETE endpoints for lifecycle templates and booking types. Both tables have `deleted_at` for future soft-delete support but no delete endpoint is included here.

### Bookings (new/updated)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/bookings/{id}/transition` | Role-gated by lifecycle | Move booking to new state |
| GET | `/api/v1/bookings/{id}/history` | Any | Audit trail + KPI data |
| GET | `/api/v1/bookings/{id}/allowed-transitions` | Any | Transitions available to current user |
| POST | `/api/v1/bookings/{id}/approve` | Admin/RM | Shortcut for `submitted → approved` only; calls transition_state("approved"); returns 400 if booking is not in `submitted` state |
| POST | `/api/v1/bookings/{id}/reject` | Admin/RM | Shortcut for `submitted → rejected` only; calls transition_state("rejected"); returns 400 if booking is not in `submitted` state |

---

## Frontend Changes

### New Pages / Components

- `frontend/src/pages/admin/BookingConfiguration.tsx` — Settings sub-page with two sections:
  - **Booking Types** — DataGrid list with Name, Lifecycle Template, Status (Active/Inactive); create/edit actions
  - **Lifecycle Templates** — DataGrid list with Name, State count, Used by count; create/edit/copy actions

### Updated Pages

- `frontend/src/pages/BookingForm.tsx` — Add Booking Type dropdown (required); rename `booking_type` to `exclusive_use` boolean toggle. The migration seeds at least one default booking type per tenant, so the dropdown always has at least one option. The frontend should still guard against an empty list (disable the submit button and show "No booking types configured — contact your admin").
- `frontend/src/pages/BookingDetail.tsx` — Add state badge; dynamic action buttons from `/allowed-transitions`; history timeline showing state transitions with actor and timestamp. Edit fields are disabled client-side using the lifecycle template definition: when the detail page loads, dispatch `fetchBookingTypes` (if not already in Redux store) to get the booking's type and its embedded lifecycle template definition. Use `field_permissions[current_state]` from that definition to disable fields the current user's role cannot edit. The backend is the authoritative guard (returns 403 if a disallowed field is submitted).

### New Service / Store

- `frontend/src/services/bookingLifecycleService.ts` — API client for templates and types
- `frontend/src/store/bookingLifecycleSlice.ts` — Redux slice for lifecycle templates and booking types

### Updated Types

- `frontend/src/types/booking.ts` — `BookingStatus` becomes `string` (state key); add `BookingType`, `BookingLifecycleTemplate`, `BookingStatusHistory` interfaces; remove `BookingTypeEnum`

---

## Verification

1. **Migration**: `alembic upgrade head` completes cleanly; existing bookings have `booking_type_id` set and `status` in `{submitted, approved, rejected}`
2. **Transition validation**: POST `/bookings/{id}/transition` with valid role → 200; invalid role → 403; invalid transition → 400
3. **Field permissions**: PUT `/bookings/{id}` editing `start_date` in `submitted` state → 403 for all roles; Admin editing `notes` in `submitted` state → 200
4. **Template propagation**: Update a lifecycle template → booking types using it reflect the change immediately
5. **Copy template**: POST `/admin/lifecycle-templates/{id}/copy` → creates independent template; updating original does not affect copy
6. **History**: GET `/bookings/{id}/history` returns rows with `from_state`, `to_state`, `changed_by`, `changed_at` in chronological order
7. **Allowed transitions**: GET `/bookings/{id}/allowed-transitions` returns only transitions valid for current user's role and current booking state
8. **Frontend**: Admin settings shows Booking Configuration; booking form has Type dropdown + Exclusive Use toggle; booking detail shows correct action buttons per role
9. **Tests**: All existing booking tests pass; new unit tests for `validate_transition`, `get_editable_fields`, `get_allowed_transitions`; new integration tests for transition endpoint, history endpoint, admin CRUD endpoints
