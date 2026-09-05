# Frontend IA PR 5 — iPad Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every table in the app scrolls inside its own container, so no page ever scrolls sideways — and a mechanical guard stops the next unwrapped `<Table>` reaching `main`.

**Architecture:** The 1024 px width check found the app clean everywhere MUI's `DataGrid` renders: it owns a virtual scroller and its column headers translate with it, so all 30 migrated grids scroll internally at 784 px of content width. The defect is in the **21 raw `<Table>` sites** the PR 4 migration never touched, because a bare MUI `<Table>` has no scroll container of its own — it simply grows and pushes the document. Five of those sites already wrap in `TableContainer` (which sets `overflowX: 'auto'`); **sixteen do not**, and two were proved to overflow with ordinary data. The fix is one line at each site — wrap the `<Table>` in a bare `<TableContainer>` — plus a source sweep that keeps the count of `<Table>` and `<TableContainer>` equal in every file, the same shape as the `storageKey` sweep PR 4 introduced.

**Tech Stack:** React 18, TypeScript (strict), MUI v7, Redux Toolkit, Vitest + Testing Library, ESLint 8 (`.eslintrc.cjs`, eslintrc format — **not** flat config).

**Spec:** [docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md](../specs/2026-09-02-frontend-ia-and-shell-design.md) §7 ("iPad Pro pass"), PR 5 in §8's sequencing table.

---

## What the width check actually found

Recorded here because the spec anticipated "fixes found" without knowing what they would be, and because two of these facts are the reason the defects survived four PRs of review.

**Method.** A Chrome tab at exactly `innerWidth === 1024` (verified, not assumed), driven through ~60 route/tab combinations by `history.pushState` + a synthetic `popstate`, measuring `documentElement.scrollWidth - clientWidth` after each and naming every element whose right edge passed the viewport.

**Clean, with evidence:**

- All 17 list pages, all 11 release-detail tabs, all 8 environment-detail tabs, all 7 system-detail tabs, all 11 enterprise tabs, the admin pages, the four URL-reachable forms, and the New Change Request dialog (32 → 992 px in a 1024 px viewport): **zero document overflow**.
- Wide grids scroll internally exactly as §7 requires — `/environments/:id?tab=components` overflows its own container by 616 px and the page by 0.
- The `MuiDataGrid-columnHeaders` element reports as "clipped content in an `overflow: hidden` box" and **is not a defect**: scrolling the virtual scroller to 400 px moved the header container to `matrix(1, 0, 0, 1, -400, 0)`. Headers track the scroller. Do not "fix" this.
- `BookingScheduleGantt` already wraps itself in `<Box sx={{ overflowX: 'auto' }}>` with a `minWidth` inner track — the correct pattern, and the model for this PR.
- `PhaseGanttEditor`'s `minWidth: 500` is below the 784 px content width and cannot overflow at this breakpoint.

**Defective — the raw-`<Table>` class.** MUI's `<Table>` renders `<table style="width: 100%">`, which still expands past its parent when the content's *minimum* width does. Nothing scrolls it, so the **document** scrolls, and because the drawer and app bar are `position: fixed`, scrolling right slides the content *under* them: the leftmost column — the one holding the row's identity — disappears behind the 240 px drawer. That makes page-level overflow information loss, not untidiness. Two instances were proved, not argued:

| Site | Trigger | Measured |
|---|---|---|
| `ReleaseEnvironmentCoverage` | column count — the head is `data.environments.map(...)`, one column per environment | fits at 4 environments (736 px); **overflows the page by 91 px at 5**, then ~131 px per environment; 1267 px over at 14 |
| `UserManagement` | one long unbreakable token — an enterprise email address | `admin@demo.com` fits; `christopher.fetherstonhaugh@global-payments-platform.example.com` takes min-content to 873 px and **overflows the page by 112 px** |

**Why four PRs of review missed both.** The dev tenant has three environments and one user whose email is `admin@demo.com`. This is the same blindness that hid PR 4's `hideFooter` truncation ("the dev tenant has fewer than 25 of each"). Neither defect is visible without either more data than the dev estate holds or a deliberate probe.

**The fix, proved live before being planned.** Wrapping the `/admin/users` table in `width: 100%; overflow-x: auto` took page overflow **112 → 0** while the table kept its 873 px width and its wrapper scrolled by 137 px. `frontend/node_modules/@mui/material/TableContainer/TableContainer.js:29` is `overflowX: 'auto'`, so `<TableContainer>` is exactly that wrapper.

---

## Global Constraints

- **Working directory for every command in this plan is `frontend/`.** Paths in **Files:** blocks are relative to the repository root.
- **The frontend suite runs WHOLE, never targeted files.** `npm test -- --run`. A regression on this programme survived six verification steps because every one ran a targeted file. A task is not done until the whole suite is green.
- **Three checks, every task:** `npm run lint` (`--max-warnings 0`, so a warning fails), `npm run build` (this is `tsc && vite build` — the only type check), and `npm test -- --run`. This PR touches no backend code, so the SQLite and PostgreSQL legs are not in scope; that is the one time in this repository "three runs" does not mean SQLite + PostgreSQL + frontend.
- **Wrap with a bare `<TableContainer>`, never `component={Paper}`.** `SystemDetail.tsx` uses `<TableContainer component={Paper}>`, but every table in this PR already sits on a surface — inside a `<Paper>`, a `<Paper variant="outlined">`, or a section `<Box>` on the page's own Paper. Adding `component={Paper}` nests a second Paper, which is a visible double surface in dark mode. A bare `<TableContainer>` renders a `<div>` with `width: 100%; overflow-x: auto` and no background, which is all that is wanted.
- **Where a `<Paper>` already wraps the `<Table>`, the `<TableContainer>` goes INSIDE the Paper**, not around it — the surface should not scroll, only its contents. This applies to `UserManagement.tsx` and `ProjectDetail.tsx`.
- **Import `TableContainer` from `@mui/material`**, added to the existing multi-line import block each file already has. Do not add a second import statement.
- **Change nothing else.** No column removal, no `size` changes, no restyling. A wrapped table renders byte-identically until it needs to scroll.
- Commit per task, conventional-commit prefix (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`). Branch: `feature/ia-ipad` (already created from `main` at `8ccabdf3`).

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `frontend/src/__tests__/tableScrollContainers.test.ts` | Source sweep: in every production file, the number of `<Table` elements equals the number of `<TableContainer` elements. Carries the shrinking allowlist of not-yet-wrapped files, which Task 6 empties. |

**Modified — the sixteen unwrapped tables (17 `<Table>` instances)**

| File | `<Table>` at | Already inside |
|---|---|---|
| `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx` | 135 | section `<Box>` |
| `frontend/src/pages/admin/UserManagement.tsx` | 155 | `<Paper>` |
| `frontend/src/components/releases/RollbackPanel.tsx` | 244, 338 | section `<Box>` (both) |
| `frontend/src/components/releases/ScopeImportDialog.tsx` | 146 | dialog content |
| `frontend/src/components/releases/ReleaseSystemsTab.tsx` | 126 | section `<Box>` |
| `frontend/src/components/releases/pir/PirActionsTable.tsx` | 53 | section `<Box>` |
| `frontend/src/components/bookings/EnvironmentsPanel.tsx` | 70 | section `<Box>` |
| `frontend/src/components/bookings/GroupTransitionPanel.tsx` | 193 | section `<Box>` |
| `frontend/src/components/environments/ComparisonTable.tsx` | 96 | section `<Box>` |
| `frontend/src/components/environments/EnvironmentProjectsPanel.tsx` | 112 | section `<Box>` |
| `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` | 1046 | nested panel |
| `frontend/src/components/systems/RehearsalsPanel.tsx` | 161 | section `<Box>` |
| `frontend/src/pages/environment-groups/EnvironmentGroupDetail.tsx` | 181 | section `<Box>` |
| `frontend/src/pages/projects/ProjectDetail.tsx` | 483 | `<Paper variant="outlined">` |
| `frontend/src/pages/admin/UserGroupDetail.tsx` | 159 | section `<Box>` |
| `frontend/src/pages/admin/TenantDetail.tsx` | 216 | section `<Box>` |

Line numbers are from `main` at `8ccabdf3` and shift as earlier tasks edit a file. Locate the `<Table` by search, not by line.

**Modified — tests and docs**

| File | Change |
|---|---|
| `frontend/src/components/releases/__tests__/releaseEnvironmentCoverage.test.tsx` | **New.** Rendered regression test for the matrix — the proven-severe case. |
| `frontend/src/pages/admin/__tests__/userManagement.test.tsx` | **New.** Rendered regression test for the long-email case. |
| `docs/ui-audit.md` | New P2 row for the overflow class, marked closed by this PR. |
| `CLAUDE.md` | The programme's closing banner paragraph (spec §10: "CLAUDE.md gets one banner paragraph at the end of PR 5"). |
| `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md` | §7's iPad paragraph gains the findings, so the spec records what the check actually returned. |

---

### Task 1: The sweep guard, with the debt written down

The guard lands **first**, allowlisting the sixteen files it currently fails on. Every later task deletes its files from the allowlist, so the suite is green at every commit and the remaining debt is always legible in one place.

**Files:**
- Create: `frontend/src/__tests__/tableScrollContainers.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `UNWRAPPED` — the allowlist constant Tasks 2–6 shorten and Task 7 empties. Its entries are the glob keys `import.meta.glob` produces, i.e. paths relative to `frontend/src/__tests__/` and therefore starting `../`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/tableScrollContainers.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

// `import.meta.glob` enumerates AND reads every source file, with no Node
// builtins — this package has no `@types/node`, so `fs`/`path` would fail
// `tsc --noEmit`. Same technique as storageKeys.test.ts.
const files = import.meta.glob<string>('../**/*.{ts,tsx}', {
  eager: true,
  query: '?raw',
  import: 'default',
});

/**
 * A bare MUI `<Table>` has no scroll container. It renders
 * `<table style="width: 100%">`, which still grows past its parent when the
 * content's *minimum* width does — a column per environment, or a single
 * unbreakable token like an email address. Nothing scrolls it, so the
 * DOCUMENT scrolls; and because the drawer and app bar are `position: fixed`,
 * the content slides underneath them and the leftmost column — the row's
 * identity — is hidden behind the 240px drawer. `<TableContainer>` is
 * `width: 100%; overflow-x: auto` (TableContainer.js:29), which confines the
 * scroll to the table.
 *
 * jsdom performs no layout, so no rendered test can measure this. It is
 * asserted on the source, the same call storageKeys.test.ts makes.
 */
describe('every raw <Table> has a scroll container', () => {
  const isProductionFile = (path: string) =>
    !path.includes('__tests__') && !path.includes('/test/');

  // `<Table[\s>]` cannot match `<TableContainer`, `<TableHead`, `<TableRow`
  // or `<TableCell` — the character after "Table" must be whitespace or `>`.
  const TABLE = /<Table[\s>]/g;
  const CONTAINER = /<TableContainer[\s>]/g;

  const count = (source: string, re: RegExp) => [...source.matchAll(re)].length;

  it('no production file renders more <Table> elements than <TableContainer>', () => {
    const offenders: string[] = [];
    for (const [path, source] of Object.entries(files)) {
      if (!isProductionFile(path)) continue;
      if (UNWRAPPED.has(path)) continue;
      const tables = count(source, TABLE);
      if (tables === 0) continue;
      const containers = count(source, CONTAINER);
      if (containers < tables) offenders.push(`${path} (${tables} tables, ${containers} containers)`);
    }
    expect(offenders, `a <Table> with no <TableContainer>: ${offenders.join(', ')}`).toEqual([]);
  });

  it('every allowlisted file still exists and still needs wrapping', () => {
    // A stale allowlist entry is worse than none: it silently exempts a file
    // that was fixed, or names one that no longer exists, and the guard reads
    // as passing either way.
    const stale: string[] = [];
    for (const path of UNWRAPPED) {
      const source = files[path];
      if (source === undefined) {
        stale.push(`${path} (no such file)`);
        continue;
      }
      if (count(source, CONTAINER) >= count(source, TABLE)) {
        stale.push(`${path} (already wrapped — delete this entry)`);
      }
    }
    expect(stale, `stale allowlist entries: ${stale.join(', ')}`).toEqual([]);
  });
});
```

- [ ] **Step 2: Run it to watch the first assertion fail**

Run: `npm test -- --run src/__tests__/tableScrollContainers.test.ts`
Expected: FAIL — `UNWRAPPED` is not defined. This proves the file is being executed before you add the constant that makes it pass.

- [ ] **Step 3: Add the allowlist**

Insert immediately above the `describe` block:

```ts
/**
 * PR 5's remaining debt, emptied task by task. Every entry is a file whose
 * `<Table>` has no `<TableContainer>` yet. Delete an entry in the same commit
 * that wraps its table — the second test below fails if you forget, and fails
 * again if you delete an entry without doing the work.
 */
const UNWRAPPED = new Set<string>([
  '../components/releases/ReleaseEnvironmentCoverage.tsx',
  '../pages/admin/UserManagement.tsx',
  '../components/releases/RollbackPanel.tsx',
  '../components/releases/ScopeImportDialog.tsx',
  '../components/releases/ReleaseSystemsTab.tsx',
  '../components/releases/pir/PirActionsTable.tsx',
  '../components/bookings/EnvironmentsPanel.tsx',
  '../components/bookings/GroupTransitionPanel.tsx',
  '../components/environments/ComparisonTable.tsx',
  '../components/environments/EnvironmentProjectsPanel.tsx',
  '../components/admin/LifecycleTemplatesPanel.tsx',
  '../components/systems/RehearsalsPanel.tsx',
  '../pages/environment-groups/EnvironmentGroupDetail.tsx',
  '../pages/projects/ProjectDetail.tsx',
  '../pages/admin/UserGroupDetail.tsx',
  '../pages/admin/TenantDetail.tsx',
]);
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm test -- --run src/__tests__/tableScrollContainers.test.ts`
Expected: PASS, 2 tests.

- [ ] **Step 5: Prove the guard is not vacuous**

Temporarily delete `'../pages/admin/TenantDetail.tsx'` from `UNWRAPPED` and re-run.
Expected: FAIL on the first test, naming `../pages/admin/TenantDetail.tsx (1 tables, 0 containers)`.
Then restore the entry and re-run: PASS.

A guard that cannot be made to fail on demand is not a guard. Do not skip this step — six of seven mutation survivors on A4 were rules the code explained at length and nothing checked.

- [ ] **Step 6: Run the whole suite, lint and build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/__tests__/tableScrollContainers.test.ts
git commit -m "test: guard that every raw <Table> has a scroll container"
```

---

### Task 2: The coverage matrix — the proven column-count overflow

The one table in the app whose column count is data-driven (`data.environments.map(...)` in both head and body). It overflows the page at five environments; every real tenant has more.

**Files:**
- Create: `frontend/src/components/releases/__tests__/releaseEnvironmentCoverage.test.tsx`
- Modify: `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx` (the `<Table size="small">` near line 135, and the `@mui/material` import block ending near line 9)
- Modify: `frontend/src/__tests__/tableScrollContainers.test.ts` (delete one allowlist entry)

**Interfaces:**
- Consumes: `UNWRAPPED` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/releases/__tests__/releaseEnvironmentCoverage.test.tsx`:

```tsx
/**
 * Frontend IA PR 5 — the coverage matrix is the one table in the app whose
 * COLUMN COUNT is data-driven: `data.environments.map(...)` renders a column
 * per environment. Measured at 1024px: it fits at four environments (736px)
 * and overflows the page by 91px at five, then ~131px per environment. jsdom
 * performs no layout, so this asserts the STRUCTURE that makes the overflow
 * scroll inside the table instead of moving the document.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import ReleaseEnvironmentCoverage from '../ReleaseEnvironmentCoverage';
import { releaseService } from '../../../services/releaseService';
import type { ReleaseEnvironmentCoverageResponse } from '../../../types/release';

vi.mock('../../../services/releaseService', () => ({
  releaseService: { getEnvironmentCoverage: vi.fn() },
}));

const coverage = (environmentCount: number): ReleaseEnvironmentCoverageResponse => ({
  needed_systems: [
    { system_id: 1, system_name: 'Customer', role: 'changing' },
    { system_id: 2, system_name: 'Mortgage', role: 'regression' },
  ],
  environments: Array.from({ length: environmentCount }, (_, i) => ({
    environment_id: i + 1,
    name: `Env_${i + 1}`,
    tier_name: 'SIT',
    status: 'active',
    covered_system_ids: [1, 2],
  })),
  uncovered_system_ids: [],
});

describe('ReleaseEnvironmentCoverage scrolls inside itself', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders its matrix inside a TableContainer, so a wide estate scrolls the table and not the page', async () => {
    vi.mocked(releaseService.getEnvironmentCoverage).mockResolvedValue(coverage(8));

    render(<ReleaseEnvironmentCoverage releaseId={1} onBook={vi.fn()} onBookMany={vi.fn()} />);

    const table = await screen.findByRole('table');
    expect(
      table.closest('.MuiTableContainer-root'),
      'the coverage matrix has no scroll container: at five or more environments it widens the DOCUMENT, ' +
        'and the fixed drawer then covers the System column that names each row',
    ).not.toBeNull();
  });

  it('still renders one column per environment', async () => {
    vi.mocked(releaseService.getEnvironmentCoverage).mockResolvedValue(coverage(8));

    render(<ReleaseEnvironmentCoverage releaseId={1} onBook={vi.fn()} onBookMany={vi.fn()} />);

    await waitFor(() => expect(screen.getByText('Env_8')).toBeInTheDocument());
    // 8 environments + the leading "System" column.
    expect(screen.getAllByRole('columnheader')).toHaveLength(9);
  });
});
```

- [ ] **Step 2: Run it to verify the first test fails**

Run: `npm test -- --run src/components/releases/__tests__/releaseEnvironmentCoverage.test.tsx`
Expected: the first test FAILS on `.MuiTableContainer-root` being null; the second PASSES (it describes existing behaviour, and is here so the wrap cannot quietly change the matrix).

- [ ] **Step 3: Wrap the table**

In `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx`, add `TableContainer` to the existing `@mui/material` import block (alphabetical, beside `Table`, `TableBody`, `TableCell`, `TableHead`, `TableRow`), then wrap:

```tsx
      <TableContainer>
        <Table size="small">
          {/* …head and body unchanged, re-indented one level… */}
        </Table>
      </TableContainer>
```

Re-indent the table's existing children by two spaces. Change nothing else.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- --run src/components/releases/__tests__/releaseEnvironmentCoverage.test.tsx`
Expected: PASS, 2 tests.

- [ ] **Step 5: Shorten the allowlist**

Delete `'../components/releases/ReleaseEnvironmentCoverage.tsx',` from `UNWRAPPED` in `frontend/src/__tests__/tableScrollContainers.test.ts`.

- [ ] **Step 6: Run the whole suite, lint and build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all green — including `tableScrollContainers.test.ts`, whose second test would fail had you deleted the entry without wrapping the table.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx \
        frontend/src/components/releases/__tests__/releaseEnvironmentCoverage.test.tsx \
        frontend/src/__tests__/tableScrollContainers.test.ts
git commit -m "fix: scroll the release environment-coverage matrix inside its own container"
```

---

### Task 3: The users table — the proven long-token overflow

`admin@demo.com` fits; a real corporate email does not. An email address is one unbreakable token, so the table cannot shrink below it.

**Files:**
- Create: `frontend/src/pages/admin/__tests__/userManagement.test.tsx`
- Modify: `frontend/src/pages/admin/UserManagement.tsx` (the `<Table>` near line 155, inside `<Paper>`; and the `@mui/material` import block ending near line 23)
- Modify: `frontend/src/__tests__/tableScrollContainers.test.ts` (delete one allowlist entry)

**Interfaces:**
- Consumes: `UNWRAPPED` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

`UserManagement` reads `state.tenantAdmin.users` (a `UserResponse[]`) and dispatches `fetchUsers()` on mount, which calls `tenantAdminService.listUsers()` and expects `{ rows, total }`. It also uses `useSnackbar` (needs notistack's `SnackbarProvider`) and `PageHeader` (needs a Router). The render harness below is the house pattern from `incidentPirCitations.test.tsx:222-246`.

Create `frontend/src/pages/admin/__tests__/userManagement.test.tsx`:

```tsx
/**
 * Frontend IA PR 5 — measured at 1024px: this table fits with the dev
 * tenant's `admin@demo.com` and overflows the page by 112px with
 * `christopher.fetherstonhaugh@global-payments-platform.example.com`. An
 * email address is a single unbreakable token, so the table cannot shrink
 * below it and, with no scroll container, the DOCUMENT widens instead.
 * jsdom performs no layout, so this asserts the structure that confines it.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import UserManagement from '../UserManagement';
import tenantAdminReducer from '../../../store/tenantAdminSlice';
import { tenantAdminService } from '../../../services/tenantAdminService';
import type { UserResponse } from '../../../types';

vi.mock('../../../services/tenantAdminService', () => ({
  tenantAdminService: { listUsers: vi.fn() },
}));

const user = (id: number, username: string, email: string): UserResponse => ({
  id,
  username,
  email,
  role: 'Developer',
  tenant_id: 1,
  is_active: true,
  is_master_admin: false,
  created_at: '2026-09-05T00:00:00Z',
  notification_preferences: null,
});

// One ordinary corporate address — the value is the point of the test, not
// decoration. This is the string that produced the measured 112px overflow.
const users = [
  user(1, 'admin', 'admin@demo.com'),
  user(
    2,
    'christopher.fetherstonhaugh',
    'christopher.fetherstonhaugh@global-payments-platform.example.com',
  ),
];

const renderUserManagement = () => {
  const store = configureStore({
    reducer: { tenantAdmin: tenantAdminReducer },
    preloadedState: {
      tenantAdmin: { users, usersTotal: users.length, settings: null, loading: false, error: null },
    },
  } as Parameters<typeof configureStore>[0]);
  return render(
    <Provider store={store}>
      <SnackbarProvider>
        <MemoryRouter initialEntries={['/admin/users']}>
          <UserManagement />
        </MemoryRouter>
      </SnackbarProvider>
    </Provider>,
  );
};

describe('UserManagement scrolls inside itself', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    // The mount-time fetch must resolve, or its rejection replaces the
    // preloaded rows with an error state and the table never renders.
    vi.mocked(tenantAdminService.listUsers).mockResolvedValue({
      rows: users,
      total: users.length,
    } as Awaited<ReturnType<typeof tenantAdminService.listUsers>>);
  });

  it('renders its table inside a TableContainer, so a long email scrolls the table and not the page', async () => {
    renderUserManagement();

    const table = await screen.findByRole('table');
    expect(
      table.closest('.MuiTableContainer-root'),
      'the users table has no scroll container: one ordinary corporate email address widens the DOCUMENT, ' +
        'and the fixed drawer then covers the Username column',
    ).not.toBeNull();
  });

  it('still renders every user', async () => {
    renderUserManagement();

    expect(await screen.findByText('admin')).toBeInTheDocument();
    expect(screen.getByText('christopher.fetherstonhaugh')).toBeInTheDocument();
  });
});
```

If `tenantAdminSlice`'s default export is not the reducer, import the reducer by whatever name that file exports — check with `grep -n "export default\|export const tenantAdminSlice" frontend/src/store/tenantAdminSlice.ts` rather than assuming.

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- --run src/pages/admin/__tests__/userManagement.test.tsx`
Expected: FAIL on `.MuiTableContainer-root` being null. If it instead fails to find a `table` role at all, the mock seam is wrong — fix that before continuing, because a test that never renders the component cannot detect the fix either.

- [ ] **Step 3: Wrap the table, inside the Paper**

In `frontend/src/pages/admin/UserManagement.tsx`, add `TableContainer` to the existing `@mui/material` import block, then:

```tsx
        <Paper>
          <TableContainer>
            <Table>
              {/* …head and body unchanged, re-indented one level… */}
            </Table>
          </TableContainer>
        </Paper>
```

The container goes **inside** the Paper: the surface should not scroll, only its contents.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- --run src/pages/admin/__tests__/userManagement.test.tsx`
Expected: PASS, 2 tests.

- [ ] **Step 5: Shorten the allowlist**

Delete `'../pages/admin/UserManagement.tsx',` from `UNWRAPPED`.

- [ ] **Step 6: Run the whole suite, lint and build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/admin/UserManagement.tsx \
        frontend/src/pages/admin/__tests__/userManagement.test.tsx \
        frontend/src/__tests__/tableScrollContainers.test.ts
git commit -m "fix: scroll the users table inside its own container"
```

---

### Task 4: The five release-module tables

Six `<Table>` instances across five files (`RollbackPanel` has two: the plans table at ~244 and the rehearsals table at ~338). No new rendered tests — Task 1's sweep is the guard for these, and `rollbackPanel.test.tsx` already covers the panel's behaviour and will catch a broken wrap.

**Files:**
- Modify: `frontend/src/components/releases/RollbackPanel.tsx` (two tables)
- Modify: `frontend/src/components/releases/ScopeImportDialog.tsx`
- Modify: `frontend/src/components/releases/ReleaseSystemsTab.tsx`
- Modify: `frontend/src/components/releases/pir/PirActionsTable.tsx`
- Modify: `frontend/src/__tests__/tableScrollContainers.test.ts` (delete four allowlist entries)

**Interfaces:**
- Consumes: `UNWRAPPED` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Wrap each table**

For each file: add `TableContainer` to the existing `@mui/material` import block, wrap every `<Table …>` … `</Table>` in `<TableContainer>` … `</TableContainer>`, and re-indent the contents by two spaces. Bare container, no `component={Paper}`. `RollbackPanel.tsx` needs this twice.

`PirActionsTable.tsx`'s table carries `sx={{ mt: 1 }}`. **Move that `sx` to the `TableContainer`**, not the `Table` — the margin belongs to the block in the page flow, and leaving it on a table that now sits inside a scrolling box puts the gap inside the scroll region.

- [ ] **Step 2: Shorten the allowlist**

Delete these four entries from `UNWRAPPED`:

```
  '../components/releases/RollbackPanel.tsx',
  '../components/releases/ScopeImportDialog.tsx',
  '../components/releases/ReleaseSystemsTab.tsx',
  '../components/releases/pir/PirActionsTable.tsx',
```

- [ ] **Step 3: Run the sweep and the release tests**

Run: `npm test -- --run src/__tests__/tableScrollContainers.test.ts src/components/releases`
Expected: PASS. If the sweep reports one of these four as still unwrapped, a file has more `<Table>` instances than you wrapped — `RollbackPanel.tsx` is the one with two.

- [ ] **Step 4: Run the whole suite, lint and build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/releases frontend/src/__tests__/tableScrollContainers.test.ts
git commit -m "fix: scroll the release-module tables inside their own containers"
```

---

### Task 5: The bookings and environments tables

**Files:**
- Modify: `frontend/src/components/bookings/EnvironmentsPanel.tsx`
- Modify: `frontend/src/components/bookings/GroupTransitionPanel.tsx`
- Modify: `frontend/src/components/environments/ComparisonTable.tsx`
- Modify: `frontend/src/components/environments/EnvironmentProjectsPanel.tsx`
- Modify: `frontend/src/__tests__/tableScrollContainers.test.ts` (delete four allowlist entries)

**Interfaces:**
- Consumes: `UNWRAPPED` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Wrap each table**

Same edit as Task 4, once per file. Bare `<TableContainer>`, import added to the existing block, contents re-indented.

`ComparisonTable.tsx` is reached from `/environments/compare` only after two environments are picked, which is why the width sweep never rendered it. It has a fixed four-column head, so it is lower risk than the matrix — wrap it anyway; the guard admits no exceptions and its content (environment names, version strings) is exactly the unbreakable-token shape that broke the users table.

- [ ] **Step 2: Shorten the allowlist**

Delete these four entries from `UNWRAPPED`:

```
  '../components/bookings/EnvironmentsPanel.tsx',
  '../components/bookings/GroupTransitionPanel.tsx',
  '../components/environments/ComparisonTable.tsx',
  '../components/environments/EnvironmentProjectsPanel.tsx',
```

- [ ] **Step 3: Run the sweep and the affected suites**

Run: `npm test -- --run src/__tests__/tableScrollContainers.test.ts src/components/bookings src/components/environments`
Expected: PASS.

- [ ] **Step 4: Run the whole suite, lint and build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/bookings frontend/src/components/environments \
        frontend/src/__tests__/tableScrollContainers.test.ts
git commit -m "fix: scroll the booking and environment tables inside their own containers"
```

---

### Task 6: The remaining admin and detail-page tables

The last six, which empties the allowlist.

**Files:**
- Modify: `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`
- Modify: `frontend/src/components/systems/RehearsalsPanel.tsx`
- Modify: `frontend/src/pages/environment-groups/EnvironmentGroupDetail.tsx`
- Modify: `frontend/src/pages/projects/ProjectDetail.tsx`
- Modify: `frontend/src/pages/admin/UserGroupDetail.tsx`
- Modify: `frontend/src/pages/admin/TenantDetail.tsx`
- Modify: `frontend/src/__tests__/tableScrollContainers.test.ts` (delete the last six entries and the now-empty allowlist)

**Interfaces:**
- Consumes: `UNWRAPPED` from Task 1.
- Produces: a `tableScrollContainers.test.ts` with no allowlist — the guard now covers every production file unconditionally.

- [ ] **Step 1: Wrap each table**

Same edit as Task 4, once per file.

`ProjectDetail.tsx`'s table is inside `<Paper variant="outlined">` — the `<TableContainer>` goes **inside** that Paper, as in Task 3.

`LifecycleTemplatesPanel.tsx`'s table is deeply nested (~line 1046) inside a per-template panel. Wrap the `<Table size="small">` itself; do not restructure the panel around it.

- [ ] **Step 2: Empty the allowlist and delete it**

Remove the last six entries, then delete the now-empty `UNWRAPPED` constant and its docstring, and delete the `if (UNWRAPPED.has(path)) continue;` line and the entire second test (`'every allowlisted file still exists and still needs wrapping'`) — a stale-entry check over an allowlist that no longer exists guards nothing. Leave the first test and its docstring, which is now the whole guard.

- [ ] **Step 3: Prove the guard still bites with no allowlist**

Temporarily unwrap one table — delete the `<TableContainer>` open and close tags in `frontend/src/pages/admin/TenantDetail.tsx` — and run:

Run: `npm test -- --run src/__tests__/tableScrollContainers.test.ts`
Expected: FAIL, naming `../pages/admin/TenantDetail.tsx (1 tables, 0 containers)`.

Restore the wrap and re-run: PASS. Without this step the emptied guard is a test that has never failed.

- [ ] **Step 4: Run the whole suite, lint and build**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/admin frontend/src/components/systems frontend/src/pages \
        frontend/src/__tests__/tableScrollContainers.test.ts
git commit -m "fix: scroll the last unwrapped tables, and drop the guard's allowlist"
```

---

### Task 7: The browser pass — verify at 1024 px, in the app

Every programme in this repository found its worst defects only by opening the page, and this PR's own two findings came from measurement rather than from tests. The suite cannot see layout; jsdom performs no layout at all. This task is the verification, and it is not optional.

**Files:** none modified unless the pass finds something.

- [ ] **Step 1: Restart the dev server**

Run: `npm run dev -- --force`

A dev server that has been running across a branch's worth of edits produces HMR artifacts that look exactly like application bugs (recorded twice in CLAUDE.md). Start clean before judging anything.

- [ ] **Step 2: Set the viewport to exactly 1024 px and confirm it**

Resize the browser, then confirm `window.innerWidth === 1024` in the console. Do not assume the window size equals the viewport size — window chrome is not part of it.

- [ ] **Step 3: Re-measure the two proven pages**

Visit `/admin/users` and `/releases/5?tab=environments`. In the console:

```js
document.documentElement.scrollWidth - document.documentElement.clientWidth
```

Expected: `0` on both.

Then confirm the fix is real rather than incidental, by reproducing the conditions that broke each one:

```js
// The matrix: clone environment columns up to a realistic estate.
const t = document.querySelector('table');
const clone = () => {
  const hr = t.querySelector('thead tr');
  hr.appendChild(hr.lastElementChild.cloneNode(true));
  t.querySelectorAll('tbody tr').forEach(r => r.appendChild(r.lastElementChild.cloneNode(true)));
};
for (let i = 0; i < 10; i++) clone();
document.documentElement.scrollWidth - document.documentElement.clientWidth;  // expect 0
t.closest('.MuiTableContainer-root').scrollWidth
  - t.closest('.MuiTableContainer-root').clientWidth;                          // expect > 0
```

The page must stay at `0` while the container's own overflow grows. That is the whole claim of this PR: the scroll moved from the document to the table.

- [ ] **Step 4: Walk the wrapped tables and confirm nothing was restyled**

Open each of these and compare against `git stash`-ing the branch if anything looks off — a `TableContainer` must be visually inert until it needs to scroll:

- `/admin/users`, `/admin/tenants` (master admin), `/admin/user-groups/1`
- `/projects/2`, `/environment-groups/3`
- `/releases/5?tab=rollback` (two tables), `/releases/5?tab=environments`, `/releases/5?tab=systems`
- `/bookings/1` (Environments panel; a grouped booking for the Group transition panel)
- `/environments/compare?left=1&right=2` — pick two environments and confirm the comparison table renders
- `/systems/2?tab=rollback` (Rehearsals panel)
- `/admin/bookings?tab=lifecycle` (Lifecycle templates panel — expand a template to reach its table)
- `/pir-actions` and a release's PIR tab (PIR actions table)

Watch for one specific regression: **a doubled surface**. If any table now sits on a second, slightly lighter Paper in dark mode, a `component={Paper}` slipped in — remove it.

- [ ] **Step 5: Record the pass in the PR description**

Write down which pages were opened, at what viewport, and what was measured. "Browser pass per PR, recorded in the PR description" is a spec §9 requirement, and an unrecorded pass is indistinguishable from a skipped one.

- [ ] **Step 6: Commit anything the pass fixed**

If the pass found nothing, there is nothing to commit — say so explicitly in the PR description rather than leaving it silent.

---

### Task 8: Docs, and the programme's closing banner

**Files:**
- Modify: `docs/ui-audit.md` (new P2 row)
- Modify: `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md` (§7's iPad paragraph)
- Modify: `CLAUDE.md` (the programme banner — spec §10)

- [ ] **Step 1: Record the finding in the UI audit**

Add a row to the P2 table in `docs/ui-audit.md`, following the existing column shape (`# | Finding | Where | Fix | Status`) and the house habit of recording what the finding got *wrong* as well as what it got right:

```markdown
| P2-8 | **A bare `<Table>` widens the document, and the fixed drawer then hides the row labels.** MUI's `<Table>` has no scroll container: it renders `<table style="width:100%">`, which still grows past its parent when the content's minimum width does. 16 of 21 raw-`<Table>` sites had no `TableContainer`. Because the drawer and app bar are `position: fixed`, scrolling right slides content underneath them — the leftmost column, which names the row, disappears behind the 240px drawer. Two instances measured at 1024px: `ReleaseEnvironmentCoverage` renders one column per environment and overflows the page by 91px at **five** environments (~131px each thereafter); `UserManagement` overflows by 112px on one ordinary corporate email address, an unbreakable token the table cannot shrink below. | 16 files — see `docs/superpowers/plans/2026-09-05-pr5-ipad-pass.md` | Wrap every raw `<Table>` in a bare `<TableContainer>` (`width:100%; overflow-x:auto`, TableContainer.js:29). | ✅ Closed (PR 5). All 16 wrapped; `src/__tests__/tableScrollContainers.test.ts` keeps `<Table>` and `<TableContainer>` counts equal in every production file. Note what the width check did **not** find: all 30 `DataGrid`s scroll internally and were clean at 1024px, as were all 17 list pages and every detail tab — the `MuiDataGrid-columnHeaders` box reports as clipped but its headers translate with the scroller (`matrix(1,0,0,1,-400,0)` at `scrollLeft: 400`) and is not a defect. |
```

- [ ] **Step 2: Record what the check returned, in the spec**

In §7 of `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md`, append to the **iPad Pro pass** paragraph:

```markdown
**What it found (2026-09-05).** Clean everywhere `DataGrid` renders — all 17
list pages, all 11 release tabs, all 8 environment tabs, all 7 system tabs,
the enterprise tabs, the admin pages and the dialogs measured zero document
overflow at a verified 1024px viewport. The defect was the 21 raw `<Table>`
sites PR 4 never touched: 16 had no `TableContainer`, and a bare `<Table>`
has no scroll container of its own, so it widens the DOCUMENT — and the
`position: fixed` drawer then covers the leftmost column. Proven, not
argued: the coverage matrix overflows by 91px at five environments (one
column per environment), and the users table by 112px on one corporate
email address. Both were invisible in the dev tenant, which has three
environments and `admin@demo.com` — the same blindness that hid PR 4's
`hideFooter` truncation.
```

- [ ] **Step 3: Write the programme banner in CLAUDE.md**

Add one paragraph to the banner block at the top of `CLAUDE.md`, in the house style — what shipped, then what will bite if forgotten. Place it above the PIR paragraph, following the newest-first ordering the banner already uses:

```markdown
> **Frontend IA programme — ✅ COMPLETE 2026-09-05, five PRs.** PR 1 navigation + admin mode, PR 2 page shell + URL tabs + breadcrumbs, PR 3 dashboard + *My work* + `GET /me/work`, PR 4 all 30 grids onto `DataTable`, PR 5 the iPad pass. Spec: [docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md](docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md).
>
> What PR 5 established, and what will bite if forgotten:
>
> - **A BARE `<Table>` WIDENS THE DOCUMENT; `DataGrid` DOES NOT.** MUI's `<Table>` renders `<table style="width:100%">` with nothing to scroll it, so when the content's minimum width exceeds its parent the PAGE scrolls — and because the drawer and app bar are `position: fixed`, the content slides underneath them and the leftmost column, which names the row, is hidden behind the 240px drawer. Page-level overflow here is **information loss, not untidiness**. Every raw `<Table>` is now wrapped in a bare `<TableContainer>`, and `frontend/src/__tests__/tableScrollContainers.test.ts` keeps the two counts equal in every production file.
> - **NEVER `<TableContainer component={Paper}>` IN THESE SIXTEEN.** Every one already sits on a surface; `component={Paper}` nests a second Paper, which is a visible doubled surface in dark mode. `SystemDetail.tsx`'s pre-existing `component={Paper}` usage is correct for its own bare context and is not the pattern to copy.
> - **THE TWO DEFECTS WERE INVISIBLE IN THE DEV TENANT, AND THAT IS THE TRANSFERABLE PART.** `ReleaseEnvironmentCoverage` renders one column per environment and overflows by 91px at **five** environments — the dev tenant has three. `UserManagement` overflows by 112px on one corporate email address — the dev tenant's admin is `admin@demo.com`. Same blindness as PR 4's `hideFooter` truncation ("fewer than 25 of each"). **A layout check against dev data proves nothing about a real estate; vary the data, or measure `min-content`.**
> - **jsdom PERFORMS NO LAYOUT, SO NO RENDERED TEST CAN SEE ANY OF THIS.** The guard is a source sweep and the two regression tests assert the STRUCTURE (`table.closest('.MuiTableContainer-root')`), never a width. The measurement lives in the browser pass, and that is the only place it can live.
> - **WHAT THE CHECK CLEARED, so nobody re-audits it:** all 30 `DataGrid`s scroll internally at 784px of content width; the `MuiDataGrid-columnHeaders` box reports as clipped content but its headers translate with the scroller (`matrix(1,0,0,1,-400,0)` at `scrollLeft: 400`) and is **not** a defect; `BookingScheduleGantt` already wraps itself in `overflowX: 'auto'`; `PhaseGanttEditor`'s `minWidth: 500` is under the 784px budget; the 11-tab release strip scrolls (PR C4's `variant="scrollable"`); and the New Change Request dialog fits at 32→992px in a 1024px viewport.
```

- [ ] **Step 4: Verify the docs build nothing and break nothing**

Run: `npm test -- --run && npm run lint && npm run build`
Expected: all green (docs changes touch no code, but the banner edit is in a file some tests read paths from — run it anyway).

- [ ] **Step 5: Commit**

```bash
git add docs/ui-audit.md docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md CLAUDE.md
git commit -m "docs: record the iPad pass findings and close the frontend IA programme"
```

---

## Self-review notes

**Spec coverage.** §7's iPad paragraph asks for three things: every list page checked at 1024 px (done in discovery, recorded in Task 8 Step 2), wide grids scrolling in their own container rather than the page (verified clean; the raw-`<Table>` class is the part that was not, and Tasks 2–6 fix it), and multi-tab detail pages relying on §6's scrollable tabs (verified: the 11-tab release strip scrolls). §9's "browser pass per PR, recorded in the PR description" is Task 7. §10's "CLAUDE.md gets one banner paragraph at the end of PR 5" is Task 8 Step 3.

**Deliberately not in scope.** A sticky first column on the coverage matrix would keep the System name visible while scrolling the environment columns — a real improvement for a matrix specifically, but it is new behaviour rather than a width fix, and it should be judged on its own rather than folded into a PR whose promise is "nothing renders differently until it needs to scroll". Recorded here as a follow-up, not built. Likewise the eight pages with an unconditional `emptyMessage` beside an error Alert (ui-audit P2-2's uncovered remainder), the client-mode export button on three capped-fetch pages, and the client-mode default page size of 100 — all PR 4 leftovers, none of them width-related.

**Type consistency.** `UNWRAPPED` is the one symbol crossing task boundaries; Tasks 2–6 only delete entries from it and Task 6 deletes the constant itself along with the test that reads it. The rendered tests share no helpers.
