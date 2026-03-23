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
- Mandatory field flag with `*` indicator on create/edit forms
- Tenant admin UI to define, edit, and soft-delete fields
- Display order: admins set an integer order on each field (no drag-and-drop in Phase 2)
- Validation on write: required fields present, type coercion
- New top-level Admin area with per-entity config sections

**Out of scope (future phases):**
- Field types: select, multi-select, date picker, URL, linked/conditional fields
- Lifecycle-conditional visibility (column included in schema, unused in Phase 2)
- Bulk reorder endpoint (Phase 2 uses single-field PATCH for order changes)

---

## Data Model

### New table: `custom_field_definition`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | auto-increment (from Base) |
| `tenant_id` | FK → tenant | scoped per tenant; indexed |
| `entity_type` | VARCHAR (native_enum=False) | `system`, `subsystem`, `environment`, `booking` |
| `field_key` | VARCHAR(100) | snake_case; used as JSON key in entity `custom_fields`; auto-generated from label on creation, immutable after that |
| `label` | VARCHAR(200) | display name shown to users |
| `field_type` | VARCHAR(20) | `text`, `number`, `boolean`; immutable after creation (changing type would invalidate existing stored values) |
| `required` | BOOLEAN | drives mandatory indicator and validation on write |
| `display_order` | INTEGER | ordering within the form section |
| `options` | JSON | null in Phase 2; shape for future select: `[{"value": "x", "label": "X"}]` |
| `lifecycle_states` | JSON | null = always visible; list of state names = only show in those states (unused in Phase 2) |
| `deleted_at` | DATETIME(timezone=True) | soft delete |

**Constraints:**
- Unique: `(tenant_id, entity_type, field_key)` — field keys must be unique per entity type per tenant
- `native_enum=False` on all enum-like columns (VARCHAR, keeps SQLite test compat)
- `field_key` and `field_type` are immutable after creation — the PATCH service silently ignores them if included in the request body

### Entity changes

- `System`, `SubSystem`, `Environment` — already have `custom_fields: JSON` column, no change
- `Booking` — requires migration to add `custom_fields: JSON NULL`

### Soft-deleted field behaviour

When a field definition is soft-deleted, existing entity records retain the key/value in their `custom_fields` JSON. On the **read side**, the frontend renders only fields that have an active (non-deleted) definition — orphaned keys are silently suppressed. If an admin creates a new field with the same `field_key`, existing values become visible again.

---

## Backend

### Pydantic schemas: `backend/app/api/v1/schemas/custom_field.py`

- `CustomFieldDefinitionCreate` — `entity_type`, `field_key` (optional, auto-generated if omitted), `label`, `field_type`, `required`, `display_order`
- `CustomFieldDefinitionUpdate` — `label`, `required`, `display_order` (all optional; `field_key` and `field_type` excluded — immutable)
- `CustomFieldDefinitionResponse` — all columns except `deleted_at`

### New service: `backend/app/services/custom_field_service.py`

- `list_definitions(db, tenant_id, entity_type)` — fetch active (non-deleted) definitions ordered by `display_order`
- `create_definition(db, tenant_id, data: CustomFieldDefinitionCreate)` — validate unique `field_key`, auto-generate `field_key` from label if not provided (lowercase, spaces→underscores, strip non-alphanumeric except underscores); create record; use `db.flush()` if ID is needed
- `update_definition(db, tenant_id, id, data: CustomFieldDefinitionUpdate)` — update label, required, display_order only; raise `HTTPException(404)` if not found or wrong tenant
- `delete_definition(db, tenant_id, id)` — soft delete; raise `HTTPException(404)` if not found or wrong tenant
- `validate_custom_fields(db, tenant_id, entity_type, values: dict)` — called by entity services on create/update:
  - Fetch active definitions for the entity type
  - Check all `required=True` fields are present and non-null/non-empty in `values`
  - Type coercion check: `number` fields must be numeric, `boolean` fields must be bool
  - Unknown keys in `values` are permitted (forward-compatibility — soft-deleted fields may still have stored values)
  - Raises `HTTPException(422, detail=...)` with a descriptive message on failure
  - Note: for recurrence bookings, validate once on the parent; child occurrences inherit the same `custom_fields` dict

All services use `current_user.active_tenant_id` (not `.tenant_id`) passed in as `tenant_id`. Services never call `db.commit()` — `get_db()` auto-commits on success.

### New router: `backend/app/api/v1/tenant_admin_fields.py`

Mounted in `main.py` at `prefix="/api/v1/tenant"` (same prefix as existing tenant admin router), tagged `["Tenant Admin"]`. Protected by `require_tenant_admin()`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/tenant/fields` | List active definitions; `entity_type` is a **required** `Query(...)` param — omitting it returns HTTP 422 automatically |
| `POST` | `/api/v1/tenant/fields` | Create a field definition |
| `PATCH` | `/api/v1/tenant/fields/{id}` | Update label, required, display_order |
| `DELETE` | `/api/v1/tenant/fields/{id}` | Soft delete |

Registration in `main.py`:
```python
from app.api.v1 import tenant_admin_fields as tenant_admin_fields_router
app.include_router(tenant_admin_fields_router.router, prefix="/api/v1/tenant", tags=["Tenant Admin"])
```

### Entity service changes

Each entity service's create and update methods call `validate_custom_fields(db, current_user.active_tenant_id, entity_type, data.custom_fields or {})` before flushing. Raises `HTTPException(422)` if validation fails.

---

## Frontend

### New: Admin area

**`frontend/src/pages/admin/`** — new top-level admin area, accessible to tenant admins.

- **`AdminLayout.tsx`** — layout with sidebar nav:
  - General Settings (links to existing TenantSettings)
  - User Management (links to existing UserManagement)
  - Entity Config section: Systems, Subsystems, Environments, Bookings
- **`EntityConfig.tsx`** — page parameterised by `entityType`; renders tabs (Custom Fields | Lifecycle [coming soon])

### New: Service layer

**`frontend/src/services/customFieldService.ts`** — API client for the four tenant-admin field endpoints.

### New: Redux slice

**`frontend/src/store/customFieldSlice.ts`**
- State: `definitions: Record<EntityType, CustomFieldDefinition[]>`, `loading`, `error`
- Thunks: `fetchDefinitions(entityType)`, `createDefinition`, `updateDefinition`, `deleteDefinition`
- After each mutation thunk completes, the slice updates the relevant `definitions[entityType]` array in-place (no re-fetch needed). Cache is keyed by entity type and persists for the session.

### New: Reusable components

**`CustomFieldDefinitionManager`** (`frontend/src/components/admin/CustomFieldDefinitionManager.tsx`)
- Table of active field definitions: label, field_key, type badge, required indicator, display_order, edit/delete actions
- "Add Field" button opens `CustomFieldDefinitionDialog`
- Dispatches `fetchDefinitions(entityType)` on mount

**`CustomFieldDefinitionDialog`** (`frontend/src/components/admin/CustomFieldDefinitionDialog.tsx`)
- Create/edit dialog (edit only allows label, required, display_order)
- Label input → auto-generates `field_key` slug (lowercase, spaces→underscores, strip non-alphanumeric) — shown to admin, editable before first save, read-only thereafter
- Type picker (Text / Number / Boolean) — disabled on edit
- Required toggle
- Client-side validation: `field_key` must match `/^[a-z][a-z0-9_]*$/`

**`CustomFieldsSection`** (`frontend/src/components/CustomFieldsSection.tsx`)
- Reusable form section rendered from a `CustomFieldDefinition[]` list
- Renders only definitions with active status (no `deleted_at`) — orphaned keys in `custom_fields` values are not displayed
- Renders: `TextField` for text, `TextField type="number"` for number, MUI `Switch` for boolean
- Shows `*` required indicator on mandatory fields
- Hidden entirely if the definitions list is empty (tenant has no custom fields for this entity type)
- Props: `entityType`, `definitions`, `values: Record<string, unknown>`, `onChange: (values) => void`

### Form integration

Each create/edit form (BookingForm, SystemCatalog dialog, SystemDetail subsystem dialog, EnvironmentList dialog):
1. Dispatches `fetchDefinitions(entityType)` on mount (reads from Redux cache if already loaded)
2. Renders `<CustomFieldsSection>` below standard fields under an "Additional Fields" heading
3. Includes `custom_fields` in the create/update payload

---

## Migrations

Two Alembic migrations, written manually (`alembic revision -m "..."`, no `--autogenerate`):

1. **`add_custom_field_definition_table`**
   ```python
   op.create_table('custom_field_definition',
       sa.Column('id', sa.Integer, primary_key=True),
       sa.Column('tenant_id', sa.Integer, sa.ForeignKey('tenant.id'), nullable=False, index=True),
       sa.Column('entity_type', sa.String(50), nullable=False),
       sa.Column('field_key', sa.String(100), nullable=False),
       sa.Column('label', sa.String(200), nullable=False),
       sa.Column('field_type', sa.String(20), nullable=False),
       sa.Column('required', sa.Boolean, nullable=False, server_default='false'),
       sa.Column('display_order', sa.Integer, nullable=False, server_default='0'),
       sa.Column('options', sa.JSON, nullable=True),
       sa.Column('lifecycle_states', sa.JSON, nullable=True),
       sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
       sa.UniqueConstraint('tenant_id', 'entity_type', 'field_key', name='uq_custom_field_def'),
   )
   ```

2. **`add_booking_custom_fields`**
   ```python
   op.add_column('booking', sa.Column('custom_fields', sa.JSON, nullable=True))
   ```

---

## Testing

Integration tests in `backend/tests/integration/test_custom_fields.py`:
- CRUD for field definitions (create, list, update, soft-delete)
- Tenant isolation: tenant A cannot see or modify tenant B's definitions
- Required field validation: create/update entity with missing required field returns 422
- Type coercion: number field with string value returns 422
- Unknown keys in `custom_fields` are accepted
- `field_key` and `field_type` ignored in PATCH body
- Orphaned keys (soft-deleted definition) accepted on read/write without error

---

## Future Extensibility

The schema is deliberately forward-compatible:
- `field_type` is a VARCHAR — new types (`select`, `date`, `url`) added by populating `options` and updating service/UI, no schema change
- `lifecycle_states` JSON array already in schema; entity services can filter definitions by current state when lifecycle is built
- `options` column present with a documented shape: `[{"value": "...", "label": "..."}]`
- The Admin area tab structure (Custom Fields | Lifecycle | ...) is established now — straightforward to add new config tabs per entity
