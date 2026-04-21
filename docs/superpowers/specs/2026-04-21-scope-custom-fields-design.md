# Scope Item Custom Fields — Design

**Date:** 2026-04-21
**Status:** Approved by user — ready for implementation planning
**Related plan:** (to be created) `docs/superpowers/plans/2026-04-21-scope-custom-fields.md`

## Problem

Scope items (`ReleaseChange`) have a `custom_fields` JSON column but no infrastructure to define, validate, or render fields on them. We want tenant admins to attach custom fields to scope items — some that apply to every scope item regardless of kind (e.g. "Theme"), others that apply to a single `change_kind` only (e.g. "Production bug reference" for defects).

## Scope

In scope:
- Add `"release_change"` as a valid `entity_type` for `CustomFieldDefinition`.
- Use the existing nullable `entity_subtype` column to scope a field to a specific `change_kind` (`story` / `defect` / `task` / `spike`). `entity_subtype = null` means "applies to every scope item".
- Validate custom fields on `POST /releases/{id}/changes` and `PUT /release-changes/{id}` using the existing `validate_custom_fields` helper.
- Filter visible fields per change_kind on both backend validation and frontend render.
- Admin UI: expose "Release scope item" as an option in the custom-field-definition manager, with a subtype select revealing `(Any) / story / defect / task / spike`.
- `ScopeItemDialog`: render a `<CustomFieldsSection />` that re-filters reactively as the user picks a `change_kind` at create time (edit time is a no-op since `change_kind` is locked after creation).

Explicitly out of scope (YAGNI):
- Admin-configurable `change_kind` values — stays hardcoded in the frontend (`story | defect | task | spike`). Flag as follow-up.
- State-driven visibility (`lifecycle_states` on the field definition). Scope items don't have a per-item lifecycle, so the existing `lifecycle_states` column stays unused on `release_change` definitions. Any `lifecycle_states` value set on a `release_change` field is ignored at runtime.
- Scope-item-level overdue / assignment (handled by gate criteria; scope items intentionally stay simple).
- New columns on `custom_field_definition` or `release_change` — both tables already have what's needed.
- Migrations — no schema changes.
- Backfilling historical scope items (the `custom_fields` JSON column already exists; existing rows have `null` and will be read as empty `{}` by the UI).

## Data model

No schema changes. Reuse existing tables.

### `custom_field_definition` (existing)

Relevant columns:
- `entity_type` (String 50) — **add `"release_change"` to the allowed set.**
- `entity_subtype` (String 50, nullable) — `null` → applies to every scope item; a value in `{"story", "defect", "task", "spike"}` → applies only to scope items of that kind.
- `field_key`, `label`, `field_type`, `required`, `display_order`, `options`, `deleted_at` — unchanged.
- Existing uniqueness constraint `(tenant_id, entity_type, field_key)` — **unchanged**. A `field_key` is unique per entity_type across all subtypes. Admins naming two different defect-only fields as `defect_ref` will still get a uniqueness error — acceptable, matches how booking/release definitions behave today.

### `release_change` (existing)

- `custom_fields` (JSON, nullable) — already present; this feature starts populating it.
- `change_kind` (String 20, required) — unchanged. Remains the discriminator the frontend filters against. Locked on edit, consistent with existing behaviour.

## Behaviour

### Visibility rule (backend and frontend)

A definition `D` is visible for a scope item with `change_kind = K` iff:

```
D.entity_type == "release_change"
AND D.deleted_at IS NULL
AND (D.entity_subtype IS NULL OR D.entity_subtype == K)
```

No ordering change from the base definition (display_order is respected within the filtered set).

### Validation at create / update

`release_scope_service.create_change` and `release_scope_service.update_change` call `validate_custom_fields(db, tenant_id, "release_change", payload.custom_fields, visible_field_keys=<keys_for_this_kind>)` before assigning values.

- `visible_field_keys` is computed by a small service helper (see §Backend API).
- Fields marked `required=True` must be present and non-empty in the submitted dict if they are visible for this item's `change_kind`. Non-visible required fields are ignored.
- Type checks (`number`, `boolean`) and soft-delete handling follow the existing `validate_custom_fields` behaviour — no change.
- Unknown keys in the submitted dict are accepted silently (consistent with booking/release behaviour — covers soft-deleted fields).

### Source-aware update guard

`release_scope_service.update_change` today rejects title/description/external_status/external_key edits on `source = "jira"` items but allows `custom_fields` and `system_id`. This stays unchanged — `custom_fields` is still editable on jira-sourced items.

### change_kind on edit

`ScopeItemDialog` already disables the `changeKind` select on edit. That behaviour is preserved — custom fields entered for one kind cannot be orphaned by a kind switch because a kind switch is not possible post-create.

### Events

No new event types. Existing `ReleaseScopeItemAdded` / `ReleaseScopeItemUpdated` payloads already serialize the whole row, so custom_fields will flow through without change.

## Backend API

### New helper

```python
# backend/app/services/custom_field_service.py
async def list_definitions_for_subtype(
    db: AsyncSession, tenant_id: int, entity_type: str, subtype: Optional[str]
) -> list[CustomFieldDefinition]:
    """Return active definitions matching entity_type, AND where entity_subtype
    is NULL or equals the given subtype. Ordered by display_order, field_key."""
```

Used internally by `release_scope_service` for validation, and called from the admin GET list endpoint when the frontend needs to render only the subtype-relevant set. (Optional fanout — may be exposed as a query param on the existing list endpoint instead of a new helper — see alternatives.)

### Endpoints

No new endpoints. Three touched:

- `POST /releases/{release_id}/changes` — adds validation before create.
- `PUT /release-changes/{change_id}` — adds validation before update.
- `GET /tenant/fields?entity_type=release_change[&entity_subtype=defect]` — existing admin list endpoint. Frontend calls it from `ScopeItemDialog` to fetch the right set. We extend it to accept an optional `entity_subtype` query param that applies the visibility rule above.

### Validation schema update

- `backend/app/api/v1/schemas/custom_field.py:9-16` — add `"release_change"` to `VALID_ENTITY_TYPES`.
- `ReleaseChangeCreate` and `ReleaseChangeUpdate` already carry `custom_fields: Optional[dict[str, Any]]`. No schema change.

## Frontend

### Components touched

| File | Change |
|---|---|
| `frontend/src/components/admin/CustomFieldDefinitionManager.tsx` | Add "Release scope item" to the entity-type dropdown. When selected, reveal a subtype select populated with `(Any) / story / defect / task / spike`. Reuse the existing subtype form control pattern. |
| `frontend/src/components/releases/ScopeItemDialog.tsx` | On mount, dispatch `fetchDefinitions("release_change")`. When `changeKind` changes, re-filter client-side. Render `<CustomFieldsSection />` between "Description" and the dialog actions. Add `customFields` state + include it in create/update payloads. |
| `frontend/src/components/releases/ScopeTable.tsx` | **No changes.** Custom field values are only viewed/edited in the dialog (matches booking/release pattern). |
| `frontend/src/services/releaseService.ts` | No changes — `createChange` / `updateChange` already forward the payload. Confirm `custom_fields` is on the payload type. |
| `frontend/src/store/customFieldSlice.ts` | No code change — already keyed by `entity_type`. `fetchDefinitions("release_change")` will just work after the backend accepts the value. |

### Client-side filter

```ts
const visibleDefs = definitions.filter(
  (d) => d.entity_subtype == null || d.entity_subtype === changeKind
);
```

Applied reactively on every render. Definitions without a subtype always show; subtype-specific definitions only show when the chosen `changeKind` matches.

### Required-field UX

`<CustomFieldsSection />` already shows a required indicator and reports empty required values to the parent form. The parent (`ScopeItemDialog`) uses that signal to disable the submit button — same pattern as booking/release dialogs. No new UI surface.

## Admin UX detail: the subtype select

The dropdown surfaces the hardcoded `CHANGE_KINDS = ["story", "defect", "task", "spike"]` list plus an `(Any)` option that maps to `entity_subtype = null`. This mirrors the release-type subtype select that already exists for `entity_type="release"` in the same admin component.

When the admin later needs to add a new kind, updating the hardcoded array in two places (the frontend `CHANGE_KINDS` and the subtype admin select — typically the same constant) is a one-line change. If this friction becomes meaningful, that's the follow-up to make kinds admin-configurable.

## Testing

### Backend

- `backend/tests/services/test_release_scope_service.py` — new cases:
  - Creating a scope item with a valid custom field value succeeds and persists the value.
  - Creating a scope item omitting a required field that applies to its change_kind returns 422.
  - Creating a scope item with a required field that only applies to a *different* kind does NOT require the field.
  - Updating custom_fields is allowed on source=jira items (preserves current behaviour).
  - Update with type-invalid value (string for a number field) returns 422.
- `backend/tests/test_custom_field_entity_subtype.py` (existing) — extend with a case for `entity_type="release_change"` and `entity_subtype="defect"`.

### Frontend

- `ScopeItemDialog` component test: renders subtype-scoped fields only for the current `changeKind`; switching `changeKind` before submit re-filters.
- Admin dialog: selecting entity_type=release_change reveals the subtype select.

## Migration / rollout

No database migrations. No data backfill. Ships alongside frontend in a single branch + MR.

## Risks and follow-ups

- **`options` JSON column is still reserved** — the design ignores it, consistent with every other entity_type today. A future "select" field_type pass is orthogonal.
- **`lifecycle_states` on `release_change` field definitions** — UI will let admins set it, but it will have no effect because scope items don't have a per-item lifecycle. A later tightening could reject `lifecycle_states` at the schema layer for `entity_type="release_change"`. Not doing it now; the inert flag is harmless.
- **Admin-configurable change_kind** — raised, deferred. If and when it happens, the subtype select becomes a dynamic list instead of a hardcoded one.
- **Existing uniqueness on `field_key`** is per entity_type, not per (entity_type, entity_subtype). Two subtype-specific fields cannot share a key. This is consistent with all existing entity_types and keeps the API simple.
