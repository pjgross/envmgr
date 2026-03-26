# Component Type Definitions

## Context

SubSystems (components) currently have a hard-coded `ComponentType` enum with 8 broad categories (WEB_SERVICE, DATABASE, CACHE, etc.) and an optional free-text `technology` field. This is too coarse for real-world use: a local Docker container and a managed Neon database are both "DATABASE" but need entirely different metadata fields (image name vs. connection string, local port vs. region, etc.).

This feature adds tenant-configurable component type definitions, each with their own custom field schemas. The existing enum stays as a broad "category" for grouping/filtering, while the new type definition captures the specific technology profile and its relevant fields.

## Data Model

### New table: `component_type_definition`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | Integer | PK, auto | |
| `tenant_id` | Integer | FK → `tenant.id`, NOT NULL, indexed | Tenant scope |
| `name` | String(200) | NOT NULL | Display name, e.g., "Docker Container", "Neon Database" |
| `description` | Text | nullable | Optional explanation of what this type represents |
| `category` | String(50) | nullable | Optional mapping to existing ComponentType enum values (`web_service`, `database`, `cache`, etc.) |
| `icon` | String(50) | nullable | Optional MUI icon name for UI display |
| `field_definitions` | JSON | nullable | Array of field definition objects (see below) |
| `deleted_at` | DateTime(tz) | nullable | Soft delete |

### Field definition schema (stored in `field_definitions` JSON)

Each element in the array:

```json
{
  "field_key": "image_name",       // snake_case, unique within type
  "label": "Docker Image",         // display label
  "field_type": "text",            // text | number | boolean
  "required": false,
  "display_order": 0
}
```

This mirrors the existing `CustomFieldDefinition` model's shape, keeping the system consistent.

### SubSystem table change

Add column to `subsystem`:

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `component_type_definition_id` | Integer | FK → `component_type_definition.id`, nullable | Links subsystem to its specific type |

The existing `component_type` enum column (category) remains unchanged. Both can coexist:
- `component_type` = broad category (DATABASE) — kept for grouping, filtering, topology coloring
- `component_type_definition_id` = specific type ("Neon Database") — provides type-specific custom fields

### Validation behavior

When a subsystem has a `component_type_definition_id`:
- On create/update, validate `custom_fields` against the type's `field_definitions`
- Required fields must be present and non-empty
- Field types must match (text→string, number→numeric, boolean→bool)
- Extra fields (not in the definition) are allowed (preserves any existing custom field data)

When a subsystem has no `component_type_definition_id`:
- No type-specific validation on `custom_fields` (current behavior)

## API Endpoints

All under `/api/v1/component-types`, tenant-scoped via `current_user.active_tenant_id`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | Any role | List all component type definitions for tenant |
| `POST` | `/` | Admin | Create a new component type definition |
| `GET` | `/{id}` | Any role | Get single definition |
| `PATCH` | `/{id}` | Admin | Update definition (name, description, category, icon, field_definitions) |
| `DELETE` | `/{id}` | Admin | Soft-delete definition |

### Request/Response schemas

**Create/Update request:**
```json
{
  "name": "Docker Container",
  "description": "A containerized service running via Docker",
  "category": "web_service",
  "icon": "Docker",
  "field_definitions": [
    {"field_key": "image_name", "label": "Image Name", "field_type": "text", "required": true, "display_order": 0},
    {"field_key": "exposed_port", "label": "Exposed Port", "field_type": "number", "required": false, "display_order": 1},
    {"field_key": "persistent_volume", "label": "Has Persistent Volume", "field_type": "boolean", "required": false, "display_order": 2}
  ]
}
```

**Response:**
```json
{
  "id": 1,
  "tenant_id": 1,
  "name": "Docker Container",
  "description": "A containerized service running via Docker",
  "category": "web_service",
  "icon": "Docker",
  "field_definitions": [...],
  "created_at": "2026-03-26T...",
  "updated_at": "2026-03-26T..."
}
```

### SubSystem endpoint changes

`POST /api/v1/systems/{system_id}/subsystems` and `PATCH .../subsystems/{id}` accept optional `component_type_definition_id`. When provided, custom fields are validated against the type's field definitions.

The subsystem response includes the resolved type name:
```json
{
  "id": 1,
  "name": "envmgr-db",
  "component_type": "database",
  "component_type_definition_id": 3,
  "component_type_definition_name": "Neon Database",
  "technology": "PostgreSQL",
  "custom_fields": {
    "region": "us-east-1",
    "connection_pooling": true
  }
}
```

## Service Layer

### New: `component_type_service.py`

- `list_component_types(db, tenant_id)` — list all non-deleted
- `get_component_type(db, tenant_id, type_id)` — get single
- `create_component_type(db, tenant_id, data)` — create with field definition validation
- `update_component_type(db, tenant_id, type_id, data)` — update
- `delete_component_type(db, tenant_id, type_id)` — soft delete
- `validate_fields_against_type(db, tenant_id, type_id, custom_fields)` — validate custom field values against a type's field definitions

### Modified: `system_service.py`

- `create_subsystem` and `update_subsystem` call `validate_fields_against_type` when `component_type_definition_id` is provided

## Admin UI

### New nav item in AdminLayout

Add "Component Types" to the `entityNavItems` array in `AdminLayout.tsx`, between "Subsystems" and "Environments":

```typescript
{ label: 'Component Types', path: '/admin/config/component-types', icon: <CategoryIcon fontSize="small" /> }
```

### New: `ComponentTypesPanel.tsx`

Following the same pattern as `BookingTypesPanel.tsx` and `LifecycleTemplatesPanel.tsx`:

- **DataGrid** listing all component types: columns for name, category (chip), field count, description
- **Create button** opens a dialog
- **Row click** opens edit dialog
- **Delete** with confirmation

### New: `ComponentTypeDialog.tsx`

Create/edit dialog with:
- Name (text input, required)
- Description (text input, optional)
- Category (select dropdown, optional — populated from the ComponentType enum values)
- Icon (text input, optional)
- **Field Definitions editor**: a mini-table/list where users can add/remove/reorder fields, each with field_key, label, field_type dropdown, required checkbox

### Redux: `componentTypeSlice.ts`

Standard slice following existing patterns:
- State: `componentTypes[]`, `loading`, `error`
- Thunks: `fetchComponentTypes`, `createComponentType`, `updateComponentType`, `deleteComponentType`

### Service: `componentTypeService.ts`

API client mapping to the backend endpoints.

## SubSystem UI Changes

### System detail / subsystem create-edit

When creating or editing a subsystem (in the Systems page):
- Add optional "Component Type" dropdown below the existing "Category" (component_type) dropdown
- Populated from `componentTypeSlice` data, optionally filtered by the selected category
- When a type is selected, render its `field_definitions` as form fields below the dropdown
- Field values are stored in the subsystem's `custom_fields` JSON

### Environment detail / subsystems tab

In the subsystems DataGrid on `EnvironmentDetail.tsx`:
- Add a "Type" column showing the component type definition name (if set)
- Existing "Category" column continues showing the enum value

## Migration

Alembic migration (manual DDL per project conventions):
1. `CREATE TABLE component_type_definition` with all columns
2. `ALTER TABLE subsystem ADD COLUMN component_type_definition_id INTEGER REFERENCES component_type_definition(id)`

## Verification

1. **Backend**: Create a component type via API with field definitions, then create a subsystem with that type and verify custom field validation works (required fields enforced, type checking)
2. **Admin UI**: Navigate to Component Types in admin, create/edit/delete types, verify DataGrid and dialog work
3. **SubSystem UI**: Create a subsystem, select a component type, fill in type-specific fields, save, reload, verify fields persist
4. **Environment Detail**: Verify the type name appears in the subsystems tab
5. **Edge cases**: Delete a component type that has subsystems using it (subsystems keep their data, just lose the type link); update field definitions on a type that already has subsystems (existing data preserved, new required fields only enforced on next save)
