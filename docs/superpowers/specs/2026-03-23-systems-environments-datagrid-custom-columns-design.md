# Systems & Environments — DataGrid + Custom Field Columns Design Spec

**Date:** 2026-03-23
**Status:** Approved

---

## Overview

Convert `SystemCatalog` and `EnvironmentList` from MUI `Table` to MUI DataGrid (`@mui/x-data-grid` v6), adding custom field columns and per-user persistent column visibility. This is consistent with `BookingList` which was built the same way.

No Redux, service, or backend changes required. `@mui/x-data-grid@^6` is already installed.

---

## Shared Patterns

Both pages follow the same approach:

**Custom field columns** — built dynamically from `state.customField.definitions[entityType]`. Each `CustomFieldDefinition` (with `field_key: string` and `label: string`) produces one `GridColDef`:

```ts
{
  field: def.field_key,
  headerName: def.label,
  flex: 1,
  valueGetter: (params: GridValueGetterParams<RowType>) =>
    params.row.custom_fields?.[def.field_key] ?? '—',
}
```

**Column visibility persistence** — localStorage, per user, per entity:
- Key: `systems-list-columns-${user?.id ?? 'guest'}` / `environments-list-columns-${user?.id ?? 'guest'}`
- Load on mount with null-check + try/catch fallback to `{}`
- Save on `onColumnVisibilityModelChange`

**Loading** — `loading={loading && rows.length === 0}` (initial load only; avoids flicker during background operations).

**Error** — `state.[entity].error` renders as `<Alert severity="error">` above the DataGrid.

**No `checkboxSelection`** — neither page requires bulk actions.

**Row navigation** — `onRowClick={(params) => navigate('/${entity}/${params.row.id}')}`. Action cell buttons call `e.stopPropagation()` to prevent triggering row navigation.

---

## 1. SystemCatalog (`frontend/src/pages/systems/SystemCatalog.tsx`)

### What changes

Replace the `TableContainer`/`Table`/`TableHead`/`TableBody`/`TableRow`/`TableCell`/`Skeleton` block with a DataGrid. Remove the skeleton loading rows (DataGrid loading overlay replaces them). All other UI (header, search field, create/edit/delete dialogs) stays unchanged.

### Core columns (`hideable: false`)

| field | headerName | notes |
|-------|------------|-------|
| `name` | Name | `flex: 1.5`, `fontWeight: medium` via `renderCell` |
| `description` | Description | `flex: 2`, `valueGetter` → `params.row.description ?? '—'` |
| `github_repository_url` | GitHub | `flex: 1`, renders `LinkIcon` chip if present, `'—'` if null |
| `actions` | (empty) | `width: 100`, `sortable: false`, `hideable: false`, `disableColumnMenu: true`, `renderCell` → Edit + Delete icon buttons |

The GitHub column stops propagation on chip click (`e.stopPropagation()`) so it doesn't trigger row navigation.

### Custom field columns

Appended after core columns, built from `state.customField.definitions['system']`.

### MUI Table imports removed

Remove: `Table`, `TableBody`, `TableCell`, `TableContainer`, `TableHead`, `TableRow`, `Paper`, `Skeleton` (if no longer used elsewhere in the file).

### Files changed

| File | Change |
|------|--------|
| `frontend/src/pages/systems/SystemCatalog.tsx` | Replace Table with DataGrid; add column visibility persistence |

---

## 2. EnvironmentList (`frontend/src/pages/environments/EnvironmentList.tsx`)

### What changes

Replace the `TableContainer`/`Table` block with a DataGrid. Status filter chips above the DataGrid stay unchanged (they filter the `environments` array client-side before passing to DataGrid `rows`). All dialogs stay unchanged.

### Core columns (`hideable: false`)

| field | headerName | notes |
|-------|------------|-------|
| `name` | Name | `flex: 1.5`, `fontWeight: medium` via `renderCell` |
| `environment_type` | Type | `flex: 1` |
| `status` | Status | `flex: 0.8`, `renderCell` → coloured `Chip` using existing `STATUS_COLORS` map |
| `created_at` | Created | `flex: 0.8`, `valueGetter` → `new Date(params.row.created_at).toLocaleDateString()` |
| `actions` | (empty) | `width: 100`, `sortable: false`, `hideable: false`, `disableColumnMenu: true`, `renderCell` → Edit + Delete icon buttons |

### Custom field columns

Appended after core columns, built from `state.customField.definitions['environment']`.

### MUI Table imports removed

Remove: `Table`, `TableBody`, `TableCell`, `TableContainer`, `TableHead`, `TableRow`, `Paper`, `Skeleton` (if not used elsewhere).

### Files changed

| File | Change |
|------|--------|
| `frontend/src/pages/environments/EnvironmentList.tsx` | Replace Table with DataGrid; add column visibility persistence |

---

## 3. Files Changed Summary

| File | Change |
|------|--------|
| `frontend/src/pages/systems/SystemCatalog.tsx` | Replace MUI Table with DataGrid + custom field columns + column visibility persistence |
| `frontend/src/pages/environments/EnvironmentList.tsx` | Replace MUI Table with DataGrid + custom field columns + column visibility persistence |

No other files require modification. `@mui/x-data-grid@^6` is already installed.
