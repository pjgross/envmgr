# Bookings Navigation & List View — Design Spec

**Date:** 2026-03-23
**Status:** Approved

---

## Overview

Restructure the Bookings section from a single flat nav item (pointing at the calendar) into an expandable sidebar group with two sub-views: the existing Calendar and a new List view. The List view adds multi-select bulk approve/reject, status filtering, and a per-user persistent custom field column picker.

No backend changes are required.

---

## 1. Navigation (`AppLayout.tsx`)

### Changes

The `NavItem` interface gains an optional `children` field:

```ts
interface NavItem {
  label: string
  path: string
  icon: React.ReactNode
  comingSoon?: boolean
  children?: NavItem[]
}
```

The flat `Bookings` entry is replaced with a group entry:

```ts
{
  label: 'Bookings',
  path: '/bookings',
  icon: <EventAvailableIcon />,
  children: [
    { label: 'Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
    { label: 'List',     path: '/bookings/list',     icon: <ListIcon /> },
  ],
}
```

### Behaviour

- Clicking the parent item toggles expand/collapse.
- The group auto-expands when `location.pathname.startsWith('/bookings')`.
- Sub-items render as indented `ListItemButton` entries beneath the parent (same `mx: 1, mb: 0.5, borderRadius: 1` style, with additional left padding).
- Active highlight applies to the matched sub-item, not the parent.

### Routes (`App.tsx`)

| Path | Component |
|------|-----------|
| `/bookings` | Redirect to `/bookings/calendar` |
| `/bookings/calendar` | `BookingCalendar` (unchanged) |
| `/bookings/list` | `BookingList` (new) |

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
│  ☐ │ Project │ Environment │ Start │ End │ Type │ Status │ CF… │
│  ☑ │ …       │ …           │ …     │ …   │ …    │pending │ …   │
│    │ …                                                         │
└────────────────────────────────────────────────────────────────┘
```

### Status Filter

- Chip group: **All / Pending / Approved / Rejected**
- Filters client-side against the loaded `bookings` array — no re-fetch on change.
- Default: **All**.

### DataGrid

- `checkboxSelection` enabled.
- **Core columns** (always visible, `hideable: false`): Project, Environment, Booked By, Start, End, Type, Status.
- **Custom field columns** (toggleable): built from `state.customField.definitions['booking']`. Each definition produces one column, keyed by field name, labelled as the definition's display name.
- Sorting and pagination use DataGrid defaults.

### Selection Toolbar

- Renders conditionally above the grid when `selectionModel.length > 0`.
- Shows selected count, **Approve** (green) and **Reject** (red) buttons, and a **Clear** link.
- Bulk action: dispatches existing `approveBooking(id)` / `rejectBooking(id)` thunks for each selected ID in sequence using `Promise.all`.
- On completion (all settled), selection model clears.
- Approve/Reject respect existing role guards — the buttons are shown to all users but the API will 403 for non-admins (same behaviour as the calendar today).

### Column Visibility Persistence

- **Storage:** `localStorage`, key `bookings-list-columns-${user.id}`.
- **Value:** DataGrid `GridColumnVisibilityModel` (object mapping column field → boolean).
- **On mount:** read from localStorage, pass as `columnVisibilityModel` prop.
- **On change:** `onColumnVisibilityModelChange` handler saves the new model to localStorage.
- Core columns have `hideable: false` — they never appear in the column panel and cannot be hidden.

### Data Loading

- On mount: `dispatch(fetchBookings())` — same as `BookingCalendar`.
- Also dispatches `fetchDefinitions('booking')` for custom field definitions (same as calendar).
- No new thunks; no service changes; no backend changes.

---

## 3. Redux / Store

No changes to `bookingSlice.ts`, `bookingService.ts`, or any backend code.

The `BookingList` component reads:
- `state.booking.bookings` — full list, filtered client-side by status chip.
- `state.booking.loading` — for DataGrid loading overlay.
- `state.customField.definitions['booking']` — to build custom field columns.
- `state.auth.user.id` — for localStorage key scoping.

---

## 4. Files Changed

| File | Change |
|------|--------|
| `frontend/src/components/AppLayout.tsx` | Add collapsible group support; update Bookings nav entry |
| `frontend/src/App.tsx` | Add `/bookings/calendar` and `/bookings/list` routes; redirect `/bookings` |
| `frontend/src/pages/bookings/BookingList.tsx` | **New** — list view component |

No other files require modification.
