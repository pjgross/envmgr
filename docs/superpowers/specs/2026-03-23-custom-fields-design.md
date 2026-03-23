# Custom Fields — Design Spec

**Date:** 2026-03-23
**Phase:** 2
**Status:** Approved

---

## Overview

Tenant admins can define custom fields for four entity types: Systems, Subsystems, Environments, and Bookings. End users fill in those fields when creating or editing records. This is the first feature in a broader per-entity configuration system — the Admin area will grow to include lifecycle configuration and other entity-specific settings over time.

---

## Scope

**In scope (Phase 2):**
- Field types: `text`, `number`, `boolean`
- Entities: System, SubSystem, Environment, Booking
- Mandatory field flag with indicator on create/edit forms
- Tenant admin UI to define, edit, reorder, and soft-delete fields
- Validation on write: required fields present, type coercion
- New top-level Admin area with per-entity config sections

**Out of scope (future phases):**
- Field types: select, multi-select, date picker, URL
- Conditional/linked fields (choice in one field changes another)
- Lifecycle-conditional visibility (field only appears in specific lifecycle states — column is included in the schema but unused in Phase 2)

---

## Data Model

### New table: `custom_field_definition`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | auto-increment (from Base) |
| `tenant_id` | FK → tenant | scoped per tenant; indexed |
| `entity_type` | VARCHAR (native_enum=False) | `system`, `subsystem`, `environment`, `booking` |
| `field_key` | VARCHAR(100) | snake_case; used as JSON key in entity `custom_fields`; auto-generated from label, editable |
| `label` | VARCHAR(200) | display name shown to users |
| `field_type` | VARCHAR(20) | `text`, `number`, `boolean`; extensible to `select`, `date`, etc. |
| `required` | BOOLEAN | drives mandatory indicator and validation on write |
| `display_order` | INTEGER | ordering within the form section |
| `options` | JSON | null in Phase 2; used for select/multi-select options later |
| `lifecycle_states` | JSON | null = always visible; list of state names = only show in those states (unused in Phase 2) |
| `deleted_at` | DATETIME(timezone=True) | soft delete |

**Constraints:**
- Unique: `(tenant_id, entity_type, field_key)` — field keys must be unique per entity type per tenant
- `native_enum=False` on `entity_type` column (VARCHAR, keeps SQLite test compat)

### Entity changes

- `System`, `SubSystem`, `Environment` — already have `custom_fields: JSON` column, no change
- `Booking` — requires migration to add `custom_fields: JSON NULL`

---

## Backend

### New service: `backend/app/services/custom_field_service.py`

- `list_definitions(db, tenant_id, entity_type)` — fetch active (non-deleted) definitions ordered by `display_order`
- `create_definition(db, tenant_id, data)` — validate unique `field_key`, create record
- `update_definition(db, tenant_id, id, data)` — update mutable fields (label, required, display_order, field_type; field_key is immutable after creation)
- `delete_definition(db, tenant_id, id)` — soft delete
- `validate_custom_fields(db, tenant_id, entity_type, values: dict)` — called by entity services on create/update:
  - Check all required fields are present and non-empty/non-null
  - Type coercion check: number fields must be numeric, boolean fields must be bool
  - Unknown keys are permitted (forward-compatibility)

### New router: `backend/app/api/v1/tenant_admin_fields.py`

Mounted under `/api/v1/tenant-admin/fields`, protected by `require_tenant_admin()`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/fields?entity_type=booking` | List active field definitions for an entity type |
| `POST` | `/fields` | Create a field definition |
| `PATCH` | `/fields/{id}` | Update label, required, display_order |
| `DELETE` | `/fields/{id}` | Soft delete |

### Entity service changes

Each entity service's create and update methods call `validate_custom_fields(...)` before flushing. Raises `HTTP 422` with a descriptive message if validation fails.

---

## Frontend

### New: Admin area

**`frontend/src/pages/admin/`** — new top-level admin area, accessible to tenant admins.

- **`AdminLayout.tsx`** — layout with sidebar nav:
  - General Settings (links to existing TenantSettings)
  - User Management (links to existing UserManagement)
  - Entity Config section: Systems, Subsystems, Environments, Bookings
- **`EntityConfig.tsx`** — generic page for an entity type; renders tabs (Custom Fields | Lifecycle [coming soon])

### New: Redux slice

**`frontend/src/store/customFieldSlice.ts`**
- State: `definitions` keyed by `entity_type`, `loading`, `error`
- Thunks: `fetchDefinitions(entityType)`, `createDefinition`, `updateDefinition`, `deleteDefinition`

### New: Service layer

**`frontend/src/services/customFieldService.ts`** — API client wrapping the four tenant-admin field endpoints.

### New: Reusable components

**`CustomFieldDefinitionManager`** (`frontend/src/components/admin/CustomFieldDefinitionManager.tsx`)
- Table of field definitions with edit and delete actions
- "Add Field" button opens `CustomFieldDefinitionDialog`
- Used on each entity config tab

**`CustomFieldDefinitionDialog`** (`frontend/src/components/admin/CustomFieldDefinitionDialog.tsx`)
- Create/edit dialog
- Label input → auto-generates `field_key` (slug, editable, locked after first save)
- Type picker: Text / Number / Boolean
- Required toggle
- Validates `field_key` format client-side

**`CustomFieldsSection`** (`frontend/src/components/CustomFieldsSection.tsx`)
- Reusable form section rendered dynamically from a list of `CustomFieldDefinition` objects
- Renders: `TextField` for text, `TextField type="number"` for number, MUI `Switch` for boolean
- Shows `*` required indicator on mandatory fields
- Exposed as `<CustomFieldsSection entityType="booking" values={...} onChange={...} />`
- Integrated into: `BookingForm`, `SystemCatalog` create/edit dialog, `SystemDetail` subsystem dialog, `EnvironmentList` create/edit dialog

### Form integration

Each create/edit form:
1. Dispatches `fetchDefinitions(entityType)` on mount (or reads from Redux cache)
2. Renders `<CustomFieldsSection>` below the standard fields in an "Additional Fields" section (hidden if no definitions exist for the tenant)
3. Includes `custom_fields` values in the create/update payload

---

## Migration

Two Alembic migrations required (written manually — no `--autogenerate`):

1. **`add_custom_field_definition_table`** — `op.create_table('custom_field_definition', ...)` with all columns and the unique constraint
2. **`add_booking_custom_fields`** — `op.add_column('booking', sa.Column('custom_fields', JSON, nullable=True))`

---

## Future Extensibility

The schema is deliberately forward-compatible:
- `field_type` is a VARCHAR — new types (`select`, `date`, `url`) are added by populating `options` and updating the service/UI, no schema change
- `lifecycle_states` JSON array is already in the schema; entity services can filter definitions by current state when lifecycle is built
- `options` JSON column is already present for future select/multi-select
- The Admin area tab structure (`Custom Fields | Lifecycle | ...`) is established now, making it straightforward to add new config tabs per entity
