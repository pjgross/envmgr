# Bookings Navigation & List View — Design Spec

**Date:** 2026-03-23
**Status:** Approved

---

## Overview

Restructure the Bookings section from a single flat nav item (pointing at the calendar) into an expandable sidebar group with two sub-views: the existing Calendar and a new List view. The List view adds multi-select bulk approve/reject, status filtering, and a per-user persistent custom field column picker.

No backend changes are required.

---

## 0. New Dependency

Install `@mui/x-data-grid` v6 (compatible with the project's existing `@mui/material` v5):

```bash
cd frontend && npm install @mui/x-data-grid@^6
```

All DataGrid prop names in this spec are v6 names.

---

## 1. Navigation (`AppLayout.tsx`)

### NavItem interface

`path` becomes optional to support group entries that have no navigation target:

```ts
interface NavItem {
  label: string
  path?: string              // optional — group items have no path
  icon: React.ReactNode
  comingSoon?: boolean
  children?: NavItem[]       // sub-items for expandable groups
}
```

### Nav data

Replace the flat Bookings entry with a group:

```ts
{
  label: 'Bookings',
  icon: <EventAvailableIcon />,
  children: [
    { label: 'Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
    { label: 'List',     path: '/bookings/list',     icon: <ListIcon /> },
  ],
}
```

### Render logic

Group items (those with `children`) are handled separately from leaf items.

**Open state:** Use `useState<Record<string, boolean>>` to track which groups are expanded, keyed by group label. Initialise lazily from the current location to avoid a flash of collapsed state:

```ts
const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>(() => {
  const initial: Record<string, boolean> = {}
  for (const item of navItems) {
    if (item.children) {
      initial[item.label] = item.children.some(
        (child) => child.path && location.pathname.startsWith(child.path)
      )
    }
  }
  return initial
})
```

**Key prop:** Use `item.label` as the React key for all nav items (leaf and group). Do not use `item.path` as the key since group items have no path.

**Group item click:** Toggle `groupOpen[item.label]` — do NOT call `navigate()`. The `path` field is absent on group items.

**Leaf item click:** `item.path && navigate(item.path)` — guard required since `path` is now optional in the type.

**`selected` prop on group `ListItemButton`:** always `false` — active highlight must not apply to the parent, only to the matched child.

**Sub-item rendering:** Wrap child items in a MUI `Collapse` component (for animation) controlled by `groupOpen[item.label]`. Render children as indented `ListItemButton` entries with `pl: 4`. Apply `selected` to the child whose `path` matches `location.pathname`.

### Routes (`App.tsx`)

**Remove** the existing `<Route path="/bookings" element={<BookingCalendar />} />` line.

**Add** the following three routes **inside the existing authenticated layout route** (the `<Route element={isAuthenticated ? <AppLayout /> : ...}>` block), so `AppLayout`'s `<Outlet />` wraps them:

```tsx
<Route path="/bookings" element={<Navigate replace to="/bookings/calendar" />} />
<Route path="/bookings/calendar" element={<BookingCalendar />} />
<Route path="/bookings/list" element={<BookingList />} />
```

---

## 2. `BookingList` Page (`frontend/src/pages/bookings/BookingList.tsx`)

### Layout

```
┌─ Page header ──────────────────────────────────────────────────┐
│  Status filter chips: [All] [Pending] [Approved] [Rejected]    │
│                                              [+ New Booking]   │
├─ Selection toolbar (conditional) ──────────────────────────────│
│  3 selected   [✓ Approve]  [✗ Reject]           [Clear]        │
├─ DataGrid ─────────────────────────────────────────────────────│
│  ☐ │ Project │ Environment │ Booked By │ Start │ End │ Type │ Status │ CF… │
└────────────────────────────────────────────────────────────────┘
```

### Status Filter

- Chip group: **All / Pending / Approved / Rejected**
- `Cancelled` is not included. `cancelBooking` does a soft delete on the backend (`deleted_at = now()`); the list endpoint filters `deleted_at IS NULL`, so cancelled bookings are never returned by the API.
- Filters client-side against the loaded `bookings` array — no re-fetch on change.
- Default: **All**.

### New Booking button

Opens `BookingForm` via a local `formOpen` boolean:

```tsx
const [formOpen, setFormOpen] = useState(false)
// ...
<Button variant="contained" onClick={() => setFormOpen(true)}>+ New Booking</Button>
<BookingForm open={formOpen} onClose={() => setFormOpen(false)} />
```

`BookingForm` props: `open: boolean`, `onClose: () => void`, `defaultEnvId?: number` (omit `defaultEnvId` from the list view).

### DataGrid columns

**Core columns** (`hideable: false` in their `GridColDef`):

| field | headerName | notes |
|-------|------------|-------|
| `project_name` | Project | |
| `environment_name` | Environment | `string \| null` — use `valueGetter: (_v, row) => row.environment_name ?? '—'` |
| `booked_by_username` | Booked By | `string \| null` — use `valueGetter: (_v, row) => row.booked_by_username ?? '—'` |
| `start_date` | Start | format with `date-fns` |
| `end_date` | End | format with `date-fns` |
| `booking_type` | Type | render as Chip |
| `status` | Status | render as coloured Chip |

**Custom field columns** (built dynamically from `state.customField.definitions['booking']`):

Each `CustomFieldDefinition` has `field_key` (machine key) and `label` (human name). Build one `GridColDef` per definition:

```ts
{
  field: definition.field_key,
  headerName: definition.label,
  valueGetter: (_value: unknown, row: BookingResponse) =>
    row.custom_fields?.[definition.field_key] ?? '—',
}
```

Note: In MUI X DataGrid v6, `valueGetter` receives `(value, row, column, apiRef)` — not a params object. The first argument is the raw cell value (unused here); the second is the full row.

### Row selection

- DataGrid props: `checkboxSelection`, `rowSelectionModel`, `onRowSelectionModelChange`
- `GridRowSelectionModel` is `GridRowId[]` where `GridRowId = string | number`. DataGrid uses the `id` field of each row (`BookingResponse.id: number`) as the row identifier by default — no `getRowId` needed.
- In the bulk handler, cast safely: `Number(id)` rather than `id as number` since `GridRowId` is `string | number`.

### Selection toolbar

Renders conditionally (`rowSelectionModel.length > 0`) above the DataGrid:

- Shows count: `{rowSelectionModel.length} selected`
- **Approve** button (green, `color="success"`): disabled when `isBulkLoading`
- **Reject** button (red, `color="error"`): disabled when `isBulkLoading`
- **Clear** link/button: resets `rowSelectionModel` to `[]`

### Bulk action flow

Use a local `isBulkLoading: boolean` state — **not** `state.booking.loading`. The `approveBooking`/`rejectBooking` thunks set `state.booking.loading = true` on each dispatch, which would cause the DataGrid loading overlay to flicker per row. Instead:

```ts
const handleBulkApprove = async () => {
  setIsBulkLoading(true)
  await Promise.allSettled(
    rowSelectionModel.map((id) => dispatch(approveBooking(Number(id))))
  )
  setRowSelectionModel([])
  setIsBulkLoading(false)
}
```

Pass the DataGrid `loading` prop as `isInitialLoading` (see Data Loading below) — not `state.booking.loading`, which flickers during bulk operations.

`Promise.allSettled` ensures all dispatches complete even if some fail. Approve/Reject are visible to all authenticated users; the backend enforces role checks (403 for non-admins), consistent with the calendar's behaviour.

### Column visibility persistence

- **Storage:** `localStorage`
- **Key:** `bookings-list-columns-${user?.id ?? 'guest'}`
- **Value:** `GridColumnVisibilityModel` (maps column field name → boolean)
- **On mount:** read and parse from localStorage. Wrap in try/catch with `?? {}` fallback in case of missing or corrupted data:
  ```ts
  const savedModel = (() => {
    try {
      return JSON.parse(localStorage.getItem(key) ?? '') ?? {}
    } catch {
      return {}
    }
  })()
  ```
- **On change:** `onColumnVisibilityModelChange` handler saves the new model with `JSON.stringify`.
- Core columns have `hideable: false` — they do not appear in the column visibility panel. Any entries for core column field names in a saved model are silently ignored by DataGrid.

### Error handling

If `state.booking.error` is set, display a MUI `<Alert severity="error">` above the DataGrid. Consistent with other pages in the project.

### Data loading

On mount, dispatch:
1. `fetchBookings()` — populates `state.booking.bookings`
2. `fetchDefinitions('booking')` — populates custom field column definitions

Pass `loading={isInitialLoading}` to the DataGrid, where:
```ts
const isInitialLoading = loading && bookings.length === 0
```
This avoids flickering the loading overlay during bulk operations (which also set `loading = true` in the slice).

---

## 3. Redux / Store

No changes to `bookingSlice.ts`, `bookingService.ts`, or any backend code.

`BookingList` reads from Redux:
- `state.booking.bookings`
- `state.booking.loading`
- `state.booking.error`
- `state.customField.definitions['booking']`
- `state.auth.user`

---

## 4. Files Changed

| File | Change |
|------|--------|
| `frontend/package.json` | Add `@mui/x-data-grid@^6` dependency |
| `frontend/src/components/AppLayout.tsx` | Add collapsible group support (Collapse, open state, key fix); update Bookings nav entry |
| `frontend/src/App.tsx` | Remove existing `/bookings` route; add `/bookings`, `/bookings/calendar`, `/bookings/list` inside layout route |
| `frontend/src/pages/bookings/BookingList.tsx` | **New** — list view component |

No other files require modification.
