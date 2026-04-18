# Booking Admin Lifecycle Tab Design

**Date:** 2026-03-25

## Goal

Move booking configuration (booking types + lifecycle templates) into the existing Admin → Bookings page as a "Lifecycle" tab, and add a structured form for creating new lifecycle templates from scratch.

## Context

`EntityConfig` at `/admin/config/booking` already renders a tab bar with "Custom Fields" (working) and "Lifecycle" (disabled, "Coming Soon" chip). The booking types and lifecycle template management currently lives at a separate hidden route (`/tenant/booking-config`) accessible only via the user dropdown menu — discoverable only if you know it exists.

---

## Design

### 1. Navigation & Routing

- Enable the Lifecycle tab in `EntityConfig` when `entityType === 'booking'`. Other entity types keep the Lifecycle tab disabled.
- Delete the `/tenant/booking-config` route from `App.tsx`.
- Remove the "Booking Config" `MenuItem` from the user dropdown in `AppLayout.tsx`.
- Delete `frontend/src/pages/admin/BookingConfiguration.tsx` — its content is replaced by two focused components.

### 2. New Components

**`frontend/src/components/admin/BookingTypesPanel.tsx`**
Contains the Booking Types DataGrid and the "New Type" creation dialog. Functionality is identical to what exists in `BookingConfiguration.tsx` today — no behaviour changes, just extracted into its own file.

Columns: Name, Lifecycle Template (resolved by name), Status (Active/Inactive chip).
Actions: "New Type" button (top-right) opens a dialog with Name field + Lifecycle Template dropdown.

**`frontend/src/components/admin/LifecycleTemplatesPanel.tsx`**
Contains the Lifecycle Templates DataGrid and the "New Template" creation dialog.

Columns: Name, States (count from `definition.states.length`), Used By (`N type(s)` count).
Row actions: "Copy" button (existing behaviour — dispatches `copyLifecycleTemplate`).
Header action: "New Template" button opens the creation dialog.

**Note:** The "New Template" button and creation dialog are net-new functionality — today's `BookingConfiguration.tsx` has no template creation capability (only Copy).

### 3. New Template Creation Dialog

A single `Dialog` (`maxWidth="md"`, `fullWidth`) with these sections:

**Name & Description**
- `name`: text field, required
- `description`: text field, optional, multiline 2 rows

**States** — labelled section with "Add State" button. Each row in a table contains:
- `key`: text input (e.g. `draft`) — unique identifier used in transitions and field permissions
- `label`: text input (e.g. `Draft`) — display name shown in the UI
- `is_initial`: checkbox — marks the starting state; only one state may be initial
- `is_terminal`: checkbox — marks end states (no further transitions expected)
- Delete row icon button

**Transitions** — labelled section with "Add Transition" button. Each row contains:
- `from_state`: dropdown populated from the states defined above
- `to_state`: dropdown populated from the states defined above
- `label`: text input (e.g. `Submit`) — button label shown to users
- `allowed_roles`: multi-select rendered as a compact checkbox group with options: `Admin`, `Release Manager`, `Test Manager`, `Developer`, `Viewer`
- Delete row icon button

**Field permissions** are not included in the creation dialog. All states default to fully locked (no editable fields) on creation. Editing field permissions is out of scope for this change.

**Validation (enforced on submit):**
- At least one state must be defined
- Exactly one state must have `is_initial: true`
- State keys must be non-empty and unique
- All transitions must reference state keys that exist in the states list
- At least one allowed role per transition

On success: dispatches `createLifecycleTemplate` thunk, closes dialog, list refreshes automatically via Redux state update (`createLifecycleTemplate.fulfilled` pushes the new template into `state.templates`).
On error: shows an `Alert` inside the dialog with the error message.

**Create payload shape:**
```ts
{
  name: string,
  description: string | null,
  is_default: false,
  definition: {
    states: LifecycleState[],
    transitions: LifecycleTransition[],
    field_permissions: {}   // explicitly pass empty object; backend validates but accepts {}
  }
}
```

### 4. Data Fetching Responsibilities

Each panel owns its own `useEffect` fetch on mount:

- `BookingTypesPanel` dispatches both `fetchBookingTypes()` **and** `fetchLifecycleTemplates()` — it needs templates loaded for the "New Type" dialog's template dropdown.
- `LifecycleTemplatesPanel` dispatches `fetchLifecycleTemplates()` and `fetchBookingTypes()` — it needs booking types for the "Used By" count column.

Both panels read from the shared `bookingLifecycle` Redux slice, so double-dispatching is safe (idempotent fetches).

### 5. EntityConfig changes

`EntityConfig.tsx` is updated to:
- Import and render `BookingTypesPanel` and `LifecycleTemplatesPanel` when `tab === 1 && entityType === 'booking'`
- Remove the `disabled` prop and "Coming Soon" chip from the Lifecycle tab when `entityType === 'booking'`
- Keep the disabled/Coming Soon state for all other entity types

The Lifecycle tab content renders both panels stacked with a `Divider` between them, matching the visual pattern of the old `BookingConfiguration` page.

---

## Files Changed

| Action | File |
|--------|------|
| Delete | `frontend/src/pages/admin/BookingConfiguration.tsx` |
| Create | `frontend/src/components/admin/BookingTypesPanel.tsx` |
| Create | `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` |
| Modify | `frontend/src/pages/admin/EntityConfig.tsx` |
| Modify | `frontend/src/App.tsx` (remove `/tenant/booking-config` route) |
| Modify | `frontend/src/components/AppLayout.tsx` (remove "Booking Config" menu item) |

---

## What Is Not In Scope

- Editing an existing lifecycle template's definition (states/transitions)
- Editing field permissions
- Deactivating / deleting a lifecycle template
- Editing a booking type (name, description, colour, active toggle)
