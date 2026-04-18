# Environment-Level Component Type Assignment

**Date:** 2026-03-26
**Status:** Approved

## Problem

Component type definitions (`component_type_definition_id` and `custom_fields`) currently live on the `SubSystem` model (catalog-level). This means a subsystem has one fixed type everywhere. In practice, the same subsystem can have different deployment implementations across environments — e.g. a database subsystem might be a Docker container in local testing but a Neon managed service in production.

## Design

### Data Model Changes

**EnvironmentSubSystem** gains two new columns:

| Column | Type | Notes |
|--------|------|-------|
| `component_type_definition_id` | nullable FK to `ComponentTypeDefinition` | The deployment/component type for this subsystem in this environment |
| `custom_fields` | nullable JSON | Values matching the linked definition's `field_definitions` schema |

**SubSystem** loses:

- `component_type_definition_id` column and FK
- `component_type_definition` relationship

SubSystem **keeps** its own `custom_fields` column — these are catalog-level fields that describe the subsystem generically (e.g. language, team), unrelated to deployment type.

**Behavior:** When a system is added to an environment and `EnvironmentSubSystem` rows are auto-created, `component_type_definition_id` and `custom_fields` start as `null`. Users must explicitly set the type per environment.

**Migration:** Single Alembic migration. Add two columns to `environment_subsystem`, drop FK + column from `subsystem`. No data migration needed — the feature is new and `component_type_definition_id` on SubSystem has no production data.

### API Changes

**Updated endpoint:** `PATCH /api/v1/environments/{env_id}/subsystems/{subsystem_id}`

Current payload fields (`is_mocked`, `mock_notes`) are extended with:

- `component_type_definition_id` (nullable int) — set to `null` to clear the type
- `custom_fields` (nullable dict) — values for the selected type's field definitions

Service validates `custom_fields` against the definition's `field_definitions` schema using the existing `validate_fields_against_type()` function. Setting `component_type_definition_id` to `null` clears both the type and custom fields.

**Updated response:** `EnvironmentSubsystemResponse` gains:

- `component_type_definition_id` — the definition ID (needed by the edit form)
- `custom_fields` — the environment-specific field values

The existing `component_type_definition_name` field continues to work, now sourced from EnvironmentSubSystem's linked definition instead of SubSystem's.

No new endpoints needed. Existing component types CRUD (`/api/v1/component-types/`) handles definition management.

### Frontend Changes

**EnvironmentDetail.tsx — Components tab:**

- Add an edit (pencil) icon button on each row in the components table
- Clicking it opens a `ComponentTypeAssignDialog`

**New component: `ComponentTypeAssignDialog.tsx`**

- Props: the `EnvironmentSubsystemResponse` being edited, `onClose`, `onSave`
- Component type dropdown fetches available `ComponentTypeDefinition`s for the tenant
- When a type is selected, dynamically renders custom fields based on that definition's `field_definitions` (text inputs, number inputs, boolean switches)
- Changing the type clears previous custom field values
- Save dispatches `updateEnvSubsystem()` with `component_type_definition_id` + `custom_fields`
- A "Clear Type" option to unset the component type entirely

**Type/state updates:**

- `EnvironmentSubsystemResponse` type gains `component_type_definition_id: number | null` and `custom_fields: Record<string, any> | null`
- `updateEnvSubsystem` thunk payload extended to accept the new fields

**Table display:**

- "Type" column already shows `component_type_definition_name` — continues to work, now sourced from environment-level assignment
- Custom field values shown as tooltip on the type chip

### Files Changed

| File | Change |
|------|--------|
| `backend/app/db/models/environment.py` | Add `component_type_definition_id` FK + `custom_fields` JSON to `EnvironmentSubSystem` |
| `backend/app/db/models/system.py` | Remove `component_type_definition_id` FK + relationship from `SubSystem` |
| `backend/app/db/migrations/versions/...` | Migration: add columns to `environment_subsystem`, drop from `subsystem` |
| `backend/app/services/environment_system_service.py` | Update `update_environment_subsystem()` to handle type + custom fields with validation |
| `backend/app/api/v1/schemas/environment.py` | Update request/response schemas |
| `frontend/src/types/environment.ts` | Add `component_type_definition_id`, `custom_fields` to response type |
| `frontend/src/pages/environments/EnvironmentDetail.tsx` | Add edit button to components table rows |
| `frontend/src/components/environments/ComponentTypeAssignDialog.tsx` | New dialog for type selection + custom field entry |
