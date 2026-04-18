# Systems & Environments DataGrid + Custom Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `SystemCatalog` and `EnvironmentList` from MUI Table to MUI DataGrid, adding custom field columns and per-user persistent column visibility.

**Architecture:** Two independent single-file changes following the same pattern as `BookingList`. Replace MUI Table markup with DataGrid, add custom field columns built from `customFieldDefs`, and persist column visibility to localStorage keyed by user ID. No Redux, service, or backend changes.

**Tech Stack:** React 18, TypeScript, MUI v5, `@mui/x-data-grid` v6.20.x (already installed), Redux Toolkit, Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-03-23-systems-environments-datagrid-custom-columns-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/pages/systems/SystemCatalog.tsx` | Modify | Replace Table with DataGrid; add custom field columns + column visibility persistence |
| `frontend/src/pages/environments/EnvironmentList.tsx` | Modify | Replace Table with DataGrid; add custom field columns + column visibility persistence |
| `frontend/e2e/systems-environments.spec.ts` | Create | Playwright tests for DataGrid rendering, column headers, row navigation |

---

## Task 1: Convert SystemCatalog to DataGrid

**Files:**
- Modify: `frontend/src/pages/systems/SystemCatalog.tsx`

**Reference:** The existing `BookingList.tsx` at `frontend/src/pages/bookings/BookingList.tsx` uses the same pattern — read it as a reference for the column visibility helpers and DataGrid props.

### Current structure to replace

The current page renders a `<TableContainer component={Paper}><Table>...</Table></TableContainer>` block with four columns (Name, Description, GitHub, Actions) and skeleton loading rows. This entire block gets replaced with a `<DataGrid />`.

Everything else stays: the header, search field, create/edit/delete dialogs, and the `fetchSystems()` + `fetchDefinitions('system')` calls in `useEffect`.

- [ ] **Step 1: Update imports**

Remove from the `@mui/material` import block:
```ts
Paper, Skeleton, Table, TableBody, TableCell, TableContainer, TableHead, TableRow
```

Add a new `@mui/x-data-grid` import block (do NOT add `GridValueGetterParams` to the `@mui/material` block):
```ts
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridValueGetterParams,
} from '@mui/x-data-grid'
```

- [ ] **Step 2: Add column visibility helpers**

Add these two functions just above the `export default function SystemCatalog()` declaration:

```ts
function loadColumnModel(userId: number | string | undefined): GridColumnVisibilityModel {
  const key = `systems-list-columns-${userId ?? 'guest'}`
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    return JSON.parse(raw) ?? {}
  } catch {
    return {}
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `systems-list-columns-${userId ?? 'guest'}`
  localStorage.setItem(key, JSON.stringify(model))
}
```

- [ ] **Step 3: Add state inside the component**

Inside `SystemCatalog()`, after the existing `useState` declarations, add:

```ts
const user = useSelector((state: RootState) => state.auth.user)
const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
  () => loadColumnModel(user?.id)
)
```

- [ ] **Step 4: Add column definitions**

After the `filtered` declaration, add the column definitions:

```ts
const coreColumns: GridColDef<SystemResponse>[] = [
  {
    field: 'name',
    headerName: 'Name',
    flex: 1.5,
    hideable: false,
    renderCell: (params) => (
      <Typography variant="body2" fontWeight="medium">{params.row.name}</Typography>
    ),
  },
  {
    field: 'description',
    headerName: 'Description',
    flex: 2,
    hideable: false,
    valueGetter: (params: GridValueGetterParams<SystemResponse>) =>
      params.row.description ?? '—',
  },
  {
    field: 'github_repository_url',
    headerName: 'GitHub',
    flex: 1,
    hideable: false,
    renderCell: (params) =>
      params.row.github_repository_url ? (
        <Chip
          icon={<LinkIcon />}
          label="GitHub"
          size="small"
          component="a"
          href={params.row.github_repository_url}
          target="_blank"
          rel="noopener noreferrer"
          clickable
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <Typography variant="body2" color="text.secondary">—</Typography>
      ),
  },
  {
    field: 'actions',
    headerName: '',
    width: 100,
    sortable: false,
    hideable: false,
    disableColumnMenu: true,
    renderCell: (params) => (
      <Box onClick={(e) => e.stopPropagation()}>
        <Tooltip title="Edit">
          <IconButton size="small" onClick={() => openEdit(params.row)}>
            <EditIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Delete">
          <IconButton size="small" color="error" onClick={() => setDeleteTarget(params.row)}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    ),
  },
]

const customFieldColumns: GridColDef<SystemResponse>[] = customFieldDefs.map((def) => ({
  field: def.field_key,
  headerName: def.label,
  flex: 1,
  valueGetter: (params: GridValueGetterParams<SystemResponse>) =>
    params.row.custom_fields?.[def.field_key] ?? '—',
} as GridColDef<SystemResponse>))

const columns = [...coreColumns, ...customFieldColumns]
```

- [ ] **Step 5: Add column visibility change handler**

After the column definitions, add:

```ts
const handleColumnVisibilityChange = (model: GridColumnVisibilityModel) => {
  setColumnVisibilityModel(model)
  saveColumnModel(user?.id, model)
}
```

- [ ] **Step 6: Replace the TableContainer block with DataGrid**

Remove the entire `<TableContainer component={Paper}>...</TableContainer>` block (including the skeleton rows and empty-state row).

Replace it with:

```tsx
<DataGrid
  rows={filtered}
  columns={columns}
  loading={loading && systems.length === 0}
  onRowClick={(params) => navigate(`/systems/${params.row.id}`)}
  columnVisibilityModel={columnVisibilityModel}
  onColumnVisibilityModelChange={handleColumnVisibilityChange}
  pageSizeOptions={[25, 50, 100]}
  initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
  sx={{ border: 1, borderColor: 'divider' }}
  disableRowSelectionOnClick
/>
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors. `Paper` must be removed from the MUI imports (it is only used in the `TableContainer` block being replaced).

- [ ] **Step 8: Verify the dev server runs**

```bash
cd frontend && npm run build
```

Expected: builds successfully (chunk size warning OK).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/systems/SystemCatalog.tsx
git commit -m "feat: convert SystemCatalog to DataGrid with custom field columns"
```

---

## Task 2: Convert EnvironmentList to DataGrid

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentList.tsx`

Same pattern as Task 1. The status filter chips above the table stay unchanged — they filter the `environments` array client-side before passing to DataGrid `rows`.

- [ ] **Step 1: Update imports**

Remove from the MUI import block:
```ts
Paper, Skeleton, Table, TableBody, TableCell, TableContainer, TableHead, TableRow
```

Add a new import line:
```ts
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridValueGetterParams,
} from '@mui/x-data-grid'
```

- [ ] **Step 2: Add column visibility helpers**

Add just above `export default function EnvironmentList()`:

```ts
function loadColumnModel(userId: number | string | undefined): GridColumnVisibilityModel {
  const key = `environments-list-columns-${userId ?? 'guest'}`
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    return JSON.parse(raw) ?? {}
  } catch {
    return {}
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `environments-list-columns-${userId ?? 'guest'}`
  localStorage.setItem(key, JSON.stringify(model))
}
```

- [ ] **Step 3: Add state inside the component**

Inside `EnvironmentList()`, after the existing `useState` declarations, add:

```ts
const user = useSelector((state: RootState) => state.auth.user)
const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
  () => loadColumnModel(user?.id)
)
```

- [ ] **Step 4: Add column definitions**

After the `filtered` declaration, add:

```ts
const coreColumns: GridColDef<EnvironmentResponse>[] = [
  {
    field: 'name',
    headerName: 'Name',
    flex: 1.5,
    hideable: false,
    renderCell: (params) => (
      <Typography variant="body2" fontWeight="medium">{params.row.name}</Typography>
    ),
  },
  {
    field: 'environment_type',
    headerName: 'Type',
    flex: 1,
    hideable: false,
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 0.8,
    hideable: false,
    renderCell: (params) => (
      <Chip
        label={params.row.status}
        size="small"
        color={STATUS_COLORS[params.row.status]}
      />
    ),
  },
  {
    field: 'created_at',
    headerName: 'Created',
    flex: 0.8,
    hideable: false,
    valueGetter: (params: GridValueGetterParams<EnvironmentResponse>) =>
      new Date(params.row.created_at).toLocaleDateString(),
  },
  {
    field: 'actions',
    headerName: '',
    width: 100,
    sortable: false,
    hideable: false,
    disableColumnMenu: true,
    renderCell: (params) => (
      <Box onClick={(e) => e.stopPropagation()}>
        <Tooltip title="Edit">
          <IconButton size="small" onClick={() => openEdit(params.row)}>
            <EditIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Tooltip title="Delete">
          <IconButton size="small" color="error" onClick={() => setDeleteTarget(params.row)}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    ),
  },
]

const customFieldColumns: GridColDef<EnvironmentResponse>[] = customFieldDefs.map((def) => ({
  field: def.field_key,
  headerName: def.label,
  flex: 1,
  valueGetter: (params: GridValueGetterParams<EnvironmentResponse>) =>
    params.row.custom_fields?.[def.field_key] ?? '—',
} as GridColDef<EnvironmentResponse>))

const columns = [...coreColumns, ...customFieldColumns]
```

- [ ] **Step 5: Add column visibility change handler**

```ts
const handleColumnVisibilityChange = (model: GridColumnVisibilityModel) => {
  setColumnVisibilityModel(model)
  saveColumnModel(user?.id, model)
}
```

- [ ] **Step 6: Replace the TableContainer block with DataGrid**

Remove the entire `<TableContainer component={Paper}>...</TableContainer>` block.

Replace with:

```tsx
<DataGrid
  rows={filtered}
  columns={columns}
  loading={loading && environments.length === 0}
  onRowClick={(params) => navigate(`/environments/${params.row.id}`)}
  columnVisibilityModel={columnVisibilityModel}
  onColumnVisibilityModelChange={handleColumnVisibilityChange}
  pageSizeOptions={[25, 50, 100]}
  initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
  sx={{ border: 1, borderColor: 'divider' }}
  disableRowSelectionOnClick
/>
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 8: Verify the dev server runs**

```bash
cd frontend && npm run build
```

Expected: builds successfully.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentList.tsx
git commit -m "feat: convert EnvironmentList to DataGrid with custom field columns"
```

---

## Task 3: Write Playwright e2e tests

**Files:**
- Create: `frontend/e2e/systems-environments.spec.ts`

Note: `seed_e2e.py` seeds a tenant and admin user but no systems, environments, or custom fields. Tests verify DataGrid structure and column headers on empty grids; row click and filter tests require seeded data. Add a comment noting this so future developers know why data-dependent tests are absent.

- [ ] **Step 1: Read global-setup to confirm credentials**

```bash
cat frontend/e2e/global-setup.ts
```

Confirm the e2e tenant/username/password (should be `e2e` / `e2eadmin` / `e2epassword123`).

- [ ] **Step 2: Create the test file**

Create `frontend/e2e/systems-environments.spec.ts`:

```ts
import { test, expect, type Page } from '@playwright/test'

const TENANT = 'e2e'
const USERNAME = 'e2eadmin'
const PASSWORD = 'e2epassword123'

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Tenant').fill(TENANT)
  await page.getByLabel('Username').fill(USERNAME)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: /login/i }).click()
  await expect(page).toHaveURL(/\/dashboard/)
}

// Note: seed_e2e.py seeds only a tenant + user (no systems/environments/custom fields).
// Tests below verify DataGrid structure; data-driven tests (row click, custom columns)
// should be added when seed data is extended.

// --- Systems ---

test('Systems page renders the data grid', async ({ page }) => {
  await login(page)
  await page.goto('/systems')
  await expect(page.locator('[role="grid"]')).toBeVisible()
})

test('Systems grid has core column headers', async ({ page }) => {
  await login(page)
  await page.goto('/systems')
  await expect(page.getByRole('columnheader', { name: 'Name' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Description' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'GitHub' })).toBeVisible()
})

test('Systems page has New System button', async ({ page }) => {
  await login(page)
  await page.goto('/systems')
  await expect(page.getByRole('button', { name: /new system/i })).toBeVisible()
})

test('Systems search field is visible', async ({ page }) => {
  await login(page)
  await page.goto('/systems')
  await expect(page.getByPlaceholder(/search systems/i)).toBeVisible()
})

// --- Environments ---

test('Environments page renders the data grid', async ({ page }) => {
  await login(page)
  await page.goto('/environments')
  await expect(page.locator('[role="grid"]')).toBeVisible()
})

test('Environments grid has core column headers', async ({ page }) => {
  await login(page)
  await page.goto('/environments')
  await expect(page.getByRole('columnheader', { name: 'Name' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Type' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'Created' })).toBeVisible()
})

test('Environments status filter chips are visible', async ({ page }) => {
  await login(page)
  await page.goto('/environments')
  await expect(page.getByRole('button', { name: 'Active' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Inactive' }).first()).toBeVisible()
})

test('Environments page has New Environment button', async ({ page }) => {
  await login(page)
  await page.goto('/environments')
  await expect(page.getByRole('button', { name: /new environment/i })).toBeVisible()
})

test('Environments search field is visible', async ({ page }) => {
  await login(page)
  await page.goto('/environments')
  await expect(page.getByPlaceholder(/search environments/i)).toBeVisible()
})
```

- [ ] **Step 3: Run the e2e tests**

```bash
cd frontend && npm run test:e2e -- --grep "Systems page|Environments"
```

Expected: all tests pass. If a test fails:
- If it fails on the grid (`[role="grid"]` not visible), the DataGrid may not be rendering — check the TypeScript build and browser console for errors.
- If the Environments filter chip test is flaky (selector issues), adjust to use `page.getByText('Active').first()` with a surrounding `Box` locator.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/systems-environments.spec.ts
git commit -m "test: add Playwright e2e tests for Systems and Environments DataGrid"
```

---

## Done

Both pages now use DataGrid with custom field columns and per-user persistent column visibility. The existing search, filter, dialogs, and row navigation are unchanged.
