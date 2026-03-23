# Bookings Navigation & List View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Bookings sidebar entry into an expandable group with Calendar and List sub-views; build the List view with status filtering, bulk approve/reject, and per-user persistent custom field columns.

**Architecture:** Four file changes — install `@mui/x-data-grid@^6`, update `AppLayout.tsx` for collapsible nav groups, update `App.tsx` routing, and create `BookingList.tsx` as a new page. No backend changes. Playwright e2e tests cover navigation and list view behaviour.

**Tech Stack:** React 18, TypeScript, MUI v5, `@mui/x-data-grid` v6, Redux Toolkit, React Router v6, Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-03-23-bookings-nav-and-list-view-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/package.json` | Modify | Add `@mui/x-data-grid@^6` dependency |
| `frontend/src/components/AppLayout.tsx` | Modify | Collapsible nav group support + Bookings group entry |
| `frontend/src/App.tsx` | Modify | Replace `/bookings` route with redirect + calendar + list routes |
| `frontend/src/pages/bookings/BookingList.tsx` | Create | New list view page |
| `frontend/e2e/bookings.spec.ts` | Create | Playwright tests for nav and list view |

---

## Task 1: Install @mui/x-data-grid

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install the package**

```bash
cd frontend && npm install @mui/x-data-grid@^6
```

Expected: resolves and installs without peer dependency errors (v6 is compatible with `@mui/material` v5).

- [ ] **Step 2: Verify TypeScript build still passes**

```bash
cd frontend && npm run build
```

Expected: builds successfully with no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "feat: install @mui/x-data-grid v6"
```

---

## Task 2: Update AppLayout — collapsible nav groups

**Files:**
- Modify: `frontend/src/components/AppLayout.tsx`

This task updates the nav to support expandable groups. The Bookings entry becomes a group with Calendar and List children.

- [ ] **Step 1: Update the `NavItem` interface**

In `AppLayout.tsx`, change:

```ts
interface NavItem {
  label: string
  path: string
  icon: React.ReactNode
  comingSoon?: boolean
}
```

to:

```ts
interface NavItem {
  label: string
  path?: string           // optional: group items have no path
  icon: React.ReactNode
  comingSoon?: boolean
  children?: NavItem[]    // sub-items for expandable groups
}
```

- [ ] **Step 2: Update navItems — replace flat Bookings with a group**

Add these imports at the top of the file (with the other MUI icon imports):

```ts
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth'
import ListIcon from '@mui/icons-material/List'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import Collapse from '@mui/material/Collapse'
```

Replace:

```ts
{ label: 'Bookings', path: '/bookings', icon: <EventAvailableIcon /> },
```

with:

```ts
{
  label: 'Bookings',
  icon: <EventAvailableIcon />,
  children: [
    { label: 'Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
    { label: 'List',     path: '/bookings/list',     icon: <ListIcon /> },
  ],
},
```

- [ ] **Step 3: Add groupOpen state to the AppLayout component**

Inside the `AppLayout` function body, after the existing `useState` calls, add:

```ts
const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>(() => {
  const initial: Record<string, boolean> = {}
  for (const item of navItems) {
    if (item.children) {
      initial[item.label] = item.children.some(
        (child) => child.path !== undefined && location.pathname.startsWith(child.path)
      )
    }
  }
  return initial
})
```

- [ ] **Step 4: Update the nav render loop**

Replace the existing `{navItems.map((item) => { ... })}` block with this updated version that handles both leaf items and group items:

```tsx
{navItems.map((item) => {
  if (item.children) {
    // Group item — expandable, no navigation on parent click
    const isOpen = groupOpen[item.label] ?? false
    return (
      <div key={item.label}>
        <ListItemButton
          selected={false}
          onClick={() =>
            setGroupOpen((prev) => ({ ...prev, [item.label]: !prev[item.label] }))
          }
          sx={{ borderRadius: 1, mx: 1, mb: 0.5 }}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
          <ListItemText primary={item.label} />
          {isOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </ListItemButton>
        <Collapse in={isOpen} timeout="auto" unmountOnExit>
          <List dense disablePadding>
            {item.children.map((child) => {
              const isChildActive = child.path !== undefined && location.pathname === child.path
              return (
                <ListItemButton
                  key={child.label}
                  selected={isChildActive}
                  onClick={() => child.path && navigate(child.path)}
                  sx={{ borderRadius: 1, mx: 1, mb: 0.5, pl: 4 }}
                >
                  <ListItemIcon sx={{ minWidth: 36 }}>{child.icon}</ListItemIcon>
                  <ListItemText primary={child.label} />
                </ListItemButton>
              )
            })}
          </List>
        </Collapse>
      </div>
    )
  }

  // Leaf item — original behaviour
  const isActive =
    item.path !== undefined &&
    (location.pathname === item.path ||
      (item.path !== '/dashboard' && location.pathname.startsWith(item.path)))
  return (
    <Tooltip
      key={item.label}
      title={item.comingSoon ? 'Coming soon' : ''}
      placement="right"
    >
      <span>
        <ListItemButton
          selected={isActive}
          disabled={item.comingSoon}
          onClick={() => !item.comingSoon && item.path && navigate(item.path)}
          sx={{ borderRadius: 1, mx: 1, mb: 0.5 }}
        >
          <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
          <ListItemText primary={item.label} />
          {item.comingSoon && (
            <Chip label="Soon" size="small" sx={{ height: 18, fontSize: 10 }} />
          )}
        </ListItemButton>
      </span>
    </Tooltip>
  )
})}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AppLayout.tsx
git commit -m "feat: add collapsible nav group support; Bookings becomes Calendar+List group"
```

---

## Task 3: Update App.tsx routing

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add the BookingList import**

Add at the top of `App.tsx` alongside the other booking import:

```ts
import BookingList from './pages/bookings/BookingList'
```

(This import will fail until Task 4 creates the file — that is fine; the TypeScript error resolves once the file exists.)

- [ ] **Step 2: Replace the `/bookings` route**

Remove:

```tsx
<Route path="/bookings" element={<BookingCalendar />} />
```

Add in its place (inside the authenticated layout `<Route>` block):

```tsx
<Route path="/bookings" element={<Navigate replace to="/bookings/calendar" />} />
<Route path="/bookings/calendar" element={<BookingCalendar />} />
<Route path="/bookings/list" element={<BookingList />} />
```

`Navigate` is already imported from `react-router-dom`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: add /bookings/calendar and /bookings/list routes"
```

---

## Task 4: Create BookingList page

**Files:**
- Create: `frontend/src/pages/bookings/BookingList.tsx`

Write the complete file in one pass. The component structure is:

```
BookingList
├── useEffect — fetch bookings + custom field definitions on mount
├── Status filter chips (client-side filter)
├── New Booking button → BookingForm dialog
├── Selection toolbar (conditional on selection)
│   ├── Count label
│   ├── Approve button (disabled during isBulkLoading)
│   ├── Reject button (disabled during isBulkLoading)
│   └── Clear link
├── Error alert (if state.booking.error)
└── DataGrid
    ├── Core columns (hideable: false)
    ├── Custom field columns (from customFieldSlice)
    └── Column visibility persisted to localStorage
```

- [ ] **Step 1: Create the file**

Create `frontend/src/pages/bookings/BookingList.tsx` with this content:

```tsx
import { useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Chip,
  Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridRowSelectionModel,
} from '@mui/x-data-grid'
import { format } from 'date-fns'
import { AppDispatch, RootState } from '../../store'
import {
  fetchBookings,
  approveBooking,
  rejectBooking,
} from '../../store/bookingSlice'
import { fetchDefinitions } from '../../store/customFieldSlice'
import type { BookingResponse, BookingStatus } from '../../types/booking'
import BookingForm from './BookingForm'

// --- Status filter -----------------------------------------------------------

const STATUS_OPTIONS: Array<{ label: string; value: BookingStatus | 'all' }> = [
  { label: 'All',      value: 'all' },
  { label: 'Pending',  value: 'pending' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
]

const STATUS_COLORS: Record<BookingStatus, 'warning' | 'success' | 'error'> = {
  pending:  'warning',
  approved: 'success',
  rejected: 'error',
}

// --- Column visibility localStorage ------------------------------------------

function loadColumnModel(userId: number | string | undefined): GridColumnVisibilityModel {
  const key = `bookings-list-columns-${userId ?? 'guest'}`
  try {
    return JSON.parse(localStorage.getItem(key) ?? '') ?? {}
  } catch {
    return {}
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `bookings-list-columns-${userId ?? 'guest'}`
  localStorage.setItem(key, JSON.stringify(model))
}

// --- Component ---------------------------------------------------------------

export default function BookingList() {
  const dispatch = useDispatch<AppDispatch>()
  const { bookings, loading, error } = useSelector((state: RootState) => state.booking)
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  )
  const user = useSelector((state: RootState) => state.auth.user)

  const [statusFilter, setStatusFilter] = useState<BookingStatus | 'all'>('all')
  const [rowSelectionModel, setRowSelectionModel] = useState<GridRowSelectionModel>([])
  const [isBulkLoading, setIsBulkLoading] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadColumnModel(user?.id)
  )

  useEffect(() => {
    dispatch(fetchBookings())
    dispatch(fetchDefinitions('booking'))
  }, [dispatch])

  // --- Filtered rows ---

  const filteredBookings =
    statusFilter === 'all'
      ? bookings
      : bookings.filter((b) => b.status === statusFilter)

  // --- Columns ---

  const coreColumns: GridColDef<BookingResponse>[] = [
    {
      field: 'project_name',
      headerName: 'Project',
      flex: 1.5,
      hideable: false,
    },
    {
      field: 'environment_name',
      headerName: 'Environment',
      flex: 1,
      hideable: false,
      valueGetter: (_value: unknown, row: BookingResponse) =>
        row.environment_name ?? '—',
    },
    {
      field: 'booked_by_username',
      headerName: 'Booked By',
      flex: 1,
      hideable: false,
      valueGetter: (_value: unknown, row: BookingResponse) =>
        row.booked_by_username ?? '—',
    },
    {
      field: 'start_date',
      headerName: 'Start',
      flex: 0.8,
      hideable: false,
      valueGetter: (_value: unknown, row: BookingResponse) =>
        format(new Date(row.start_date), 'dd MMM yyyy'),
    },
    {
      field: 'end_date',
      headerName: 'End',
      flex: 0.8,
      hideable: false,
      valueGetter: (_value: unknown, row: BookingResponse) =>
        format(new Date(row.end_date), 'dd MMM yyyy'),
    },
    {
      field: 'booking_type',
      headerName: 'Type',
      flex: 0.8,
      hideable: false,
      renderCell: ({ row }) => (
        <Chip
          label={row.booking_type}
          size="small"
          color={row.booking_type === 'exclusive' ? 'error' : 'primary'}
          variant="outlined"
        />
      ),
    },
    {
      field: 'status',
      headerName: 'Status',
      flex: 0.8,
      hideable: false,
      renderCell: ({ row }) => (
        <Chip
          label={row.status}
          size="small"
          color={STATUS_COLORS[row.status]}
        />
      ),
    },
  ]

  const customFieldColumns: GridColDef<BookingResponse>[] = customFieldDefs.map((def) => ({
    field: def.field_key,
    headerName: def.label,
    flex: 1,
    valueGetter: (_value: unknown, row: BookingResponse) =>
      row.custom_fields?.[def.field_key] ?? '—',
  }))

  const columns = [...coreColumns, ...customFieldColumns]

  // --- Bulk actions ---

  const handleBulkApprove = async () => {
    setIsBulkLoading(true)
    await Promise.allSettled(
      rowSelectionModel.map((id) => dispatch(approveBooking(Number(id))))
    )
    setRowSelectionModel([])
    setIsBulkLoading(false)
  }

  const handleBulkReject = async () => {
    setIsBulkLoading(true)
    await Promise.allSettled(
      rowSelectionModel.map((id) => dispatch(rejectBooking(Number(id))))
    )
    setRowSelectionModel([])
    setIsBulkLoading(false)
  }

  // --- Column visibility ---

  const handleColumnVisibilityChange = (model: GridColumnVisibilityModel) => {
    setColumnVisibilityModel(model)
    saveColumnModel(user?.id, model)
  }

  // Only show loading overlay on initial load (not during bulk operations)
  const isInitialLoading = loading && bookings.length === 0

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="body2" color="text.secondary" sx={{ mr: 1 }}>
          Status:
        </Typography>
        {STATUS_OPTIONS.map((opt) => (
          <Chip
            key={opt.value}
            label={opt.label}
            clickable
            color={statusFilter === opt.value ? 'primary' : 'default'}
            variant={statusFilter === opt.value ? 'filled' : 'outlined'}
            onClick={() => setStatusFilter(opt.value)}
            size="small"
          />
        ))}
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="contained" size="small" onClick={() => setFormOpen(true)}>
          + New Booking
        </Button>
      </Box>

      {/* Error */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Selection toolbar */}
      {rowSelectionModel.length > 0 && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: 2,
            py: 1,
            mb: 0,
            bgcolor: 'primary.50',
            border: '1px solid',
            borderColor: 'primary.200',
            borderBottom: 'none',
            borderRadius: '4px 4px 0 0',
          }}
        >
          <Typography variant="body2" color="primary" fontWeight={500}>
            {rowSelectionModel.length} selected
          </Typography>
          <Button
            size="small"
            color="success"
            variant="contained"
            startIcon={<CheckIcon />}
            disabled={isBulkLoading}
            onClick={handleBulkApprove}
          >
            Approve
          </Button>
          <Button
            size="small"
            color="error"
            variant="contained"
            startIcon={<CloseIcon />}
            disabled={isBulkLoading}
            onClick={handleBulkReject}
          >
            Reject
          </Button>
          <Box sx={{ flexGrow: 1 }} />
          <Button
            size="small"
            color="inherit"
            onClick={() => setRowSelectionModel([])}
          >
            Clear
          </Button>
        </Box>
      )}

      {/* DataGrid */}
      <DataGrid
        rows={filteredBookings}
        columns={columns}
        loading={isInitialLoading}
        checkboxSelection
        rowSelectionModel={rowSelectionModel}
        onRowSelectionModelChange={setRowSelectionModel}
        columnVisibilityModel={columnVisibilityModel}
        onColumnVisibilityModelChange={handleColumnVisibilityChange}
        pageSizeOptions={[25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />

      {/* New Booking dialog */}
      <BookingForm open={formOpen} onClose={() => setFormOpen(false)} />
    </Box>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles with no errors**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors. If `DataGrid` v6 type errors appear on `valueGetter` signature, confirm you're on v6 (v5 uses a params object; v6 uses `(value, row, column, apiRef)`).

- [ ] **Step 3: Run the dev server and manually verify**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173 and verify:
- Bookings nav item expands to show Calendar and List
- `/bookings` redirects to `/bookings/calendar`
- `/bookings/list` renders the data grid
- Status filter chips filter the rows
- Selecting rows shows the toolbar with Approve/Reject
- Column visibility panel appears via the DataGrid's built-in button

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/bookings/BookingList.tsx
git commit -m "feat: add BookingList page with status filter, bulk actions, and column picker"
```

---

## Task 5: Write Playwright e2e tests

**Files:**
- Create: `frontend/e2e/bookings.spec.ts`

- [ ] **Step 1: Check the existing global-setup for the e2e seed data**

Read `frontend/e2e/global-setup.ts` to confirm:
- What credentials are available (tenant, username, password)
- Whether any bookings are seeded for the e2e tenant

```bash
cat frontend/e2e/global-setup.ts
```

If no bookings are seeded, the grid will be empty. The nav and routing tests still work; bulk-action tests require at least one pending booking. Check `backend/scripts/seed_e2e.py` too.

- [ ] **Step 2: Create the test file**

Create `frontend/e2e/bookings.spec.ts`:

```ts
import { test, expect } from '@playwright/test'

const TENANT = 'e2e'
const USERNAME = 'e2eadmin'
const PASSWORD = 'e2epassword123'

async function login(page: any) {
  await page.goto('/login')
  await page.getByLabel('Tenant').fill(TENANT)
  await page.getByLabel('Username').fill(USERNAME)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: /login/i }).click()
  await expect(page).toHaveURL(/\/dashboard/)
}

// --- Navigation ---

test('Bookings nav group expands on click', async ({ page }) => {
  await login(page)

  // Verify sub-items are not visible initially (group collapsed)
  await expect(page.getByRole('button', { name: 'Calendar' })).not.toBeVisible()

  // Click the parent group item
  await page.getByRole('button', { name: 'Bookings' }).click()

  // Sub-items should now be visible
  await expect(page.getByRole('button', { name: 'Calendar' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'List' })).toBeVisible()
})

test('/bookings redirects to /bookings/calendar', async ({ page }) => {
  await login(page)
  await page.goto('/bookings')
  await expect(page).toHaveURL(/\/bookings\/calendar/)
})

test('clicking Bookings > Calendar navigates to calendar view', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: 'Bookings' }).click()
  await page.getByRole('button', { name: 'Calendar' }).click()
  await expect(page).toHaveURL(/\/bookings\/calendar/)
})

test('clicking Bookings > List navigates to list view', async ({ page }) => {
  await login(page)
  await page.getByRole('button', { name: 'Bookings' }).click()
  await page.getByRole('button', { name: 'List' }).click()
  await expect(page).toHaveURL(/\/bookings\/list/)
})

// --- List view ---

test('Bookings list renders the data grid', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  // DataGrid renders a table
  await expect(page.locator('[role="grid"]')).toBeVisible()

  // Core column headers are present
  await expect(page.getByRole('columnheader', { name: 'Project' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible()
})

test('status filter chips are visible on the list view', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  await expect(page.getByText('All')).toBeVisible()
  await expect(page.getByText('Pending')).toBeVisible()
  await expect(page.getByText('Approved')).toBeVisible()
  await expect(page.getByText('Rejected')).toBeVisible()
})

test('New Booking button opens the booking form dialog', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  await page.getByRole('button', { name: /new booking/i }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
})

test('Bookings group auto-expands when navigating directly to /bookings/list', async ({ page }) => {
  await login(page)
  await page.goto('/bookings/list')

  // Both sub-items should be visible without clicking the group
  await expect(page.getByRole('button', { name: 'Calendar' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'List' })).toBeVisible()
})
```

- [ ] **Step 3: Run the e2e tests**

```bash
cd frontend && npm run test:e2e -- --grep "bookings"
```

Expected: all tests pass. If the Bookings group starts collapsed (auto-expand not working), revisit the `groupOpen` lazy init in `AppLayout.tsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/bookings.spec.ts
git commit -m "test: add Playwright e2e tests for bookings nav and list view"
```

---

## Done

All tasks complete. The Bookings section now has:
- Expandable sidebar group with Calendar and List sub-items
- `/bookings` redirects to `/bookings/calendar`
- List view with status filter, bulk approve/reject, and per-user persistent column picker
