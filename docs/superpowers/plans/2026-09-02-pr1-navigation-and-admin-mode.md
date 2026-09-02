# PR 1 — Navigation & admin mode: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two disagreeing admin menus with one admin mode, restructure the main drawer into Dashboard / Catalogue / Bookings / Releases / Insights / Administration, move every admin page under `/admin/*` inside one shell, and redirect every old path.

**Architecture:** Two declarative nav trees (`appNav`, `adminNav`) rendered by one `NavDrawer` component inside `AppLayout`, which swaps trees on the `/admin` prefix. Admin entity configuration becomes `/admin/:entity/:tab` driven by one `ENTITY_CONFIG_PAGES` table that also generates the admin drawer's items and the `/admin` hub. A `LEGACY_REDIRECTS` table turns every old path into a `<Navigate replace>`, and one structural test walks both trees and the redirect table against the real router.

**Tech Stack:** React 18, TypeScript (strict), MUI 5, react-router-dom v6, Redux Toolkit, Vitest + Testing Library (jsdom).

**Spec:** `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md` — sections 3, 4, 9, 10.

## Global Constraints

- Labels are **sentence case** everywhere ("Scope-change rules", "API keys", "User groups"); child labels never repeat their group name.
- **This PR moves pages; it moves no permissions.** User groups, Projects and Environment groups stay readable by any tenant member; every other admin route stays `PrivateRoute requiredRole="Admin"` (master admins pass that check today and keep passing).
- Nothing in the app nav may link to a route that does not exist. *My work* is PR 3 and is **not** added here.
- `localStorage` reads and writes are wrapped in `try/catch` and default to "open".
- Every step's commands run from `frontend/` unless stated. Frontend gate before every commit that touches `.tsx`: `npx tsc --noEmit && npm run lint`. The **whole** frontend suite (`npx vitest run`) runs at Task 11, not targeted files — a regression here once survived six targeted runs.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01J1FuNvkPgvc2F9iK7K1Hfq
  ```
- Branch: `feature/ia-admin-mode` off `main`.

---

## File map

| File | Responsibility |
|---|---|
| `src/store/uiSlice.ts` (modify) | `navOpenGroups` (persisted) + `lastAppRoute` |
| `src/components/navConfig.tsx` (rewrite) | Types, `userSatisfies`, `appNav`, `visibleAppNav` |
| `src/pages/admin/entityConfigTabs.ts` (create) | `ENTITY_CONFIG_PAGES` table + path helpers |
| `src/components/adminNavConfig.tsx` (create) | `adminNav` sections, `visibleAdminNav` |
| `src/components/NavDrawer.tsx` (create) | Renders one tree; `isPathActive`, `groupContaining` |
| `src/components/AppLayout.tsx` (modify) | Mode switch, back link, open-on-navigate |
| `src/pages/admin/EntityConfig.tsx` (rewrite) | `/admin/:entity/:tab` |
| `src/pages/admin/ComponentTypesPage.tsx` (create) | `/admin/component-types` |
| `src/pages/admin/AdminHome.tsx` (create) | `/admin` hub |
| `src/pages/admin/TenantSettings.tsx` (moved + modify) | Read-only name/slug, JSON under *Advanced* |
| `src/pages/projects/*`, `src/pages/environment-groups/*` (moved) | Out of admin |
| `src/components/legacyRedirects.tsx` (create) | `LEGACY_REDIRECTS` + `<LegacyRedirect>` |
| `src/App.tsx` (modify) | Route tree |
| `src/pages/admin/AdminLayout.tsx` (delete) | — |
| `src/test/renderApp.tsx` (create) | Real-router harness for structural tests |
| `docs/user-guide.md`, `docs/admin-guide.md`, `docs/ui-audit.md` | Nav docs |

---

### Task 1: `uiSlice` — persisted nav group state and last app route

**Files:**
- Modify: `src/store/uiSlice.ts`
- Test: `src/store/__tests__/uiSlice.test.ts`

**Interfaces:**
- Produces: `setNavGroupOpen({ key: string; open: boolean })`, `setLastAppRoute(path: string)`, state `ui.navOpenGroups: Record<string, boolean>`, `ui.lastAppRoute: string` (default `'/dashboard'`). Storage key `ui.navOpenGroups`.

- [ ] **Step 1: Write the failing test**

```ts
// src/store/__tests__/uiSlice.test.ts
import { beforeEach, describe, expect, it } from 'vitest';
import reducer, { setLastAppRoute, setNavGroupOpen } from '../uiSlice';

const NAV_KEY = 'ui.navOpenGroups';

describe('uiSlice nav state', () => {
  beforeEach(() => localStorage.clear());

  it('defaults lastAppRoute to /dashboard and navOpenGroups to empty', () => {
    const state = reducer(undefined, { type: 'init' });
    expect(state.lastAppRoute).toBe('/dashboard');
    expect(state.navOpenGroups).toEqual({});
  });

  it('records the last app route', () => {
    const state = reducer(undefined, setLastAppRoute('/releases/calendar?x=1'));
    expect(state.lastAppRoute).toBe('/releases/calendar?x=1');
  });

  it('persists group open state to localStorage', () => {
    const state = reducer(undefined, setNavGroupOpen({ key: 'app:Bookings', open: false }));
    expect(state.navOpenGroups['app:Bookings']).toBe(false);
    expect(JSON.parse(localStorage.getItem(NAV_KEY) ?? '{}')).toEqual({ 'app:Bookings': false });
  });

  it('survives corrupt localStorage', () => {
    localStorage.setItem(NAV_KEY, '{not json');
    const state = reducer(undefined, setNavGroupOpen({ key: 'app:Releases', open: true }));
    expect(state.navOpenGroups).toEqual({ 'app:Releases': true });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/store/__tests__/uiSlice.test.ts`
Expected: FAIL — `setNavGroupOpen` is not exported.

- [ ] **Step 3: Implement**

Replace the slice body of `src/store/uiSlice.ts` with:

```ts
import { createSlice, PayloadAction } from '@reduxjs/toolkit';

export type ThemeModePreference = 'light' | 'dark' | 'system';

interface UiState {
  themeMode: ThemeModePreference;
  /** Collapsed/expanded drawer groups, keyed `<mode>:<label>`. Absent = open. */
  navOpenGroups: Record<string, boolean>;
  /** Where "← Back to EnvManager" returns to from admin mode. */
  lastAppRoute: string;
}

const STORAGE_KEY = 'ui.themeMode';
const NAV_GROUPS_KEY = 'ui.navOpenGroups';

function readInitialMode(): ThemeModePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  return 'system';
}

// localStorage can be absent (thumbnail capture), blocked, or hold garbage —
// none of which may stop the drawer rendering. Default is "everything open".
function readNavGroups(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(NAV_GROUPS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeNavGroups(groups: Record<string, boolean>): void {
  try {
    localStorage.setItem(NAV_GROUPS_KEY, JSON.stringify(groups));
  } catch {
    /* persistence is a convenience, never a requirement */
  }
}

const initialState: UiState = {
  themeMode: readInitialMode(),
  navOpenGroups: readNavGroups(),
  lastAppRoute: '/dashboard',
};

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    setThemeMode(state, action: PayloadAction<ThemeModePreference>) {
      state.themeMode = action.payload;
      localStorage.setItem(STORAGE_KEY, action.payload);
    },
    setNavGroupOpen(state, action: PayloadAction<{ key: string; open: boolean }>) {
      state.navOpenGroups[action.payload.key] = action.payload.open;
      writeNavGroups(state.navOpenGroups);
    },
    setLastAppRoute(state, action: PayloadAction<string>) {
      state.lastAppRoute = action.payload;
    },
  },
});

export const { setThemeMode, setNavGroupOpen, setLastAppRoute } = uiSlice.actions;
export default uiSlice.reducer;
```

- [ ] **Step 4: Run tests**

Run: `npx vitest run src/store/__tests__/uiSlice.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git checkout -b feature/ia-admin-mode
git add src/store/uiSlice.ts src/store/__tests__/uiSlice.test.ts
git commit -m "feat(ui): persisted nav group state and last app route in uiSlice"
```

---

### Task 2: `navConfig.tsx` — the app tree

**Files:**
- Rewrite: `src/components/navConfig.tsx`
- Rewrite: `src/components/__tests__/navConfig.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export type NavRole = 'admin' | 'masterAdmin' | 'adminOrMaster';
  export interface NavUser { role?: string; is_master_admin?: boolean }
  export interface NavItem { label: string; path: string; icon?: ReactNode; requires?: NavRole; description?: string }
  export interface NavGroup { label: string; icon: ReactNode; requires?: NavRole; children: NavItem[] }
  export type NavEntry = NavItem | NavGroup;
  export function isNavGroup(e: NavEntry): e is NavGroup
  export function userSatisfies(user: NavUser | null, requires?: NavRole): boolean
  export const ADMIN_ROOT = '/admin';
  export const appNav: NavEntry[];
  export function visibleAppNav(user: NavUser | null): NavEntry[]
  ```
- `visibleAppNav` drops groups left with no children. The old `visibleNavGroups`/`navGroups` exports are removed; `AppLayout` is the only consumer and is rewritten in Task 4.

- [ ] **Step 1: Write the failing test** (replace the file)

```tsx
// src/components/__tests__/navConfig.test.tsx
import { describe, expect, it } from 'vitest';
import { appNav, isNavGroup, visibleAppNav, type NavUser } from '../navConfig';

const regular: NavUser = { role: 'Developer', is_master_admin: false };
const admin: NavUser = { role: 'Admin', is_master_admin: false };
const masterOnly: NavUser = { role: 'Viewer', is_master_admin: true };

const topLabels = (u: NavUser | null) => visibleAppNav(u).map((e) => e.label);
const children = (u: NavUser | null, group: string) => {
  const g = visibleAppNav(u).find((e) => e.label === group);
  return g && isNavGroup(g) ? g.children.map((c) => c.label) : [];
};

describe('appNav', () => {
  it('shows Dashboard then the four workflow groups to a regular user, no Administration', () => {
    expect(topLabels(regular)).toEqual(['Dashboard', 'Catalogue', 'Bookings', 'Releases', 'Insights']);
  });

  it('files Projects and Environment groups under Bookings for every role', () => {
    // Both are readable by any tenant member and used when booking — they are
    // not administration, whatever directory their page components once lived in.
    expect(children(regular, 'Bookings')).toEqual([
      'Calendar', 'List', 'Environment requests', 'Change requests', 'Projects',
      'Environment groups', 'Contentions', 'Decommissions',
    ]);
  });

  it('lists the catalogue and release groups in the agreed order', () => {
    expect(children(regular, 'Catalogue')).toEqual([
      'Systems', 'Environments', 'Hosts', 'Compare environments', 'Import',
    ]);
    expect(children(regular, 'Releases')).toEqual([
      'Releases', 'Calendar', 'Timeline', 'Scope windows', 'Analytics', 'Builds',
      'Deployments', 'Incidents', 'PIR actions',
    ]);
    expect(children(regular, 'Insights')).toEqual(['DORA metrics', 'Environment health']);
  });

  it('never lists Release templates in the app tree — it is admin configuration', () => {
    const all = appNav.flatMap((e) => (isNavGroup(e) ? e.children : [e])).map((i) => i.label);
    expect(all).not.toContain('Release templates');
  });

  it('shows the Administration entry to an Admin and to a master admin, not to a regular user', () => {
    expect(topLabels(admin)).toContain('Administration');
    expect(topLabels(masterOnly)).toContain('Administration');
    expect(topLabels(regular)).not.toContain('Administration');
    expect(topLabels(null)).not.toContain('Administration');
  });

  it('points Administration at /admin', () => {
    const entry = visibleAppNav(admin).find((e) => e.label === 'Administration');
    expect(entry && !isNavGroup(entry) ? entry.path : undefined).toBe('/admin');
  });

  it('uses sentence case and no group-prefixed labels', () => {
    for (const entry of appNav) {
      const labels = isNavGroup(entry) ? entry.children.map((c) => c.label) : [entry.label];
      for (const label of labels) {
        expect(label).not.toMatch(/—/);
        // second word onward is lower case unless it is an acronym (DORA, PIR)
        const words = label.split(' ').slice(1);
        for (const w of words) expect(w === w.toUpperCase() || w === w.toLowerCase()).toBe(true);
      }
    }
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/components/__tests__/navConfig.test.tsx`
Expected: FAIL — `appNav`/`visibleAppNav` not exported.

- [ ] **Step 3: Rewrite `src/components/navConfig.tsx`**

```tsx
import type { ReactNode } from 'react';
import DashboardIcon from '@mui/icons-material/Dashboard';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ComputerIcon from '@mui/icons-material/Computer';
import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import StorageIcon from '@mui/icons-material/Storage';
import UploadIcon from '@mui/icons-material/Upload';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth';
import ListIcon from '@mui/icons-material/List';
import BuildIcon from '@mui/icons-material/Build';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import TimelineIcon from '@mui/icons-material/Timeline';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import ScheduleIcon from '@mui/icons-material/Schedule';
import InsightsIcon from '@mui/icons-material/Insights';
import BugReportIcon from '@mui/icons-material/BugReport';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import HealthAndSafetyIcon from '@mui/icons-material/HealthAndSafety';
import AssignmentIcon from '@mui/icons-material/Assignment';
import GavelIcon from '@mui/icons-material/Gavel';
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';
import FolderIcon from '@mui/icons-material/Folder';
import WorkspacesIcon from '@mui/icons-material/Workspaces';

/** Minimal user shape the nav needs — decoupled from the store's User type. */
export interface NavUser {
  role?: string;
  is_master_admin?: boolean;
}

export type NavRole = 'admin' | 'masterAdmin' | 'adminOrMaster';

export interface NavItem {
  label: string;
  path: string;
  icon?: ReactNode;
  requires?: NavRole;
  /** One line for the /admin hub cards. Unused in the app tree. */
  description?: string;
}

export interface NavGroup {
  label: string;
  icon: ReactNode;
  requires?: NavRole;
  children: NavItem[];
}

export type NavEntry = NavItem | NavGroup;

export function isNavGroup(entry: NavEntry): entry is NavGroup {
  return 'children' in entry;
}

export const ADMIN_ROOT = '/admin';

export function userSatisfies(user: NavUser | null, requires?: NavRole): boolean {
  if (!requires) return true;
  const isAdmin = user?.role === 'Admin';
  const isMaster = user?.is_master_admin === true;
  if (requires === 'admin') return isAdmin;
  if (requires === 'masterAdmin') return isMaster;
  return isAdmin || isMaster;
}

/**
 * The app tree. Order here is the render order. Labels are sentence case and
 * never repeat their group's name — the group header already says it.
 *
 * Deliberately absent: "My work" (PR 3 — a nav entry with no route behind it
 * is the "connected to nothing" class) and "Release templates" (admin
 * configuration, see adminNavConfig).
 */
export const appNav: NavEntry[] = [
  { label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon /> },
  {
    label: 'Catalogue',
    icon: <AccountTreeIcon />,
    children: [
      { label: 'Systems', path: '/systems', icon: <AccountTreeIcon /> },
      { label: 'Environments', path: '/environments', icon: <ComputerIcon /> },
      { label: 'Hosts', path: '/infrastructure/hosts', icon: <StorageIcon /> },
      { label: 'Compare environments', path: '/environments/compare', icon: <CompareArrowsIcon /> },
      { label: 'Import', path: '/import', icon: <UploadIcon /> },
    ],
  },
  {
    label: 'Bookings',
    icon: <EventAvailableIcon />,
    children: [
      { label: 'Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
      { label: 'List', path: '/bookings/list', icon: <ListIcon /> },
      { label: 'Environment requests', path: '/environment-requests', icon: <AssignmentIcon /> },
      { label: 'Change requests', path: '/change-requests', icon: <BuildIcon /> },
      // Readable by any tenant member; writes stay Admin-gated on the page.
      { label: 'Projects', path: '/projects', icon: <FolderIcon /> },
      { label: 'Environment groups', path: '/environment-groups', icon: <WorkspacesIcon /> },
      // Worklists readable by any tenant member: who may ACT on a row is
      // settled on the row, not by hiding the page.
      { label: 'Contentions', path: '/contentions', icon: <GavelIcon /> },
      { label: 'Decommissions', path: '/decommissions', icon: <DeleteSweepIcon /> },
    ],
  },
  {
    label: 'Releases',
    icon: <RocketLaunchIcon />,
    children: [
      { label: 'Releases', path: '/releases', icon: <ListIcon /> },
      { label: 'Calendar', path: '/releases/calendar', icon: <CalendarMonthIcon /> },
      { label: 'Timeline', path: '/releases/timeline', icon: <TimelineIcon /> },
      { label: 'Scope windows', path: '/releases/scope-windows', icon: <ScheduleIcon /> },
      { label: 'Analytics', path: '/releases/analytics', icon: <InsightsIcon /> },
      { label: 'Builds', path: '/builds', icon: <BuildIcon /> },
      { label: 'Deployments', path: '/deployments', icon: <RocketLaunchIcon /> },
      { label: 'Incidents', path: '/incidents', icon: <BugReportIcon /> },
      { label: 'PIR actions', path: '/pir-actions', icon: <FactCheckIcon /> },
    ],
  },
  {
    label: 'Insights',
    icon: <QueryStatsIcon />,
    children: [
      { label: 'DORA metrics', path: '/insights/dora', icon: <QueryStatsIcon /> },
      { label: 'Environment health', path: '/insights/health', icon: <HealthAndSafetyIcon /> },
    ],
  },
  {
    label: 'Administration',
    path: ADMIN_ROOT,
    icon: <AdminPanelSettingsIcon />,
    // A master admin who is not role Admin still needs the Platform section.
    requires: 'adminOrMaster',
  },
];

/** Filter by role; drop any group left with no children. */
export function visibleAppNav(user: NavUser | null): NavEntry[] {
  const out: NavEntry[] = [];
  for (const entry of appNav) {
    if (!userSatisfies(user, entry.requires)) continue;
    if (isNavGroup(entry)) {
      const children = entry.children.filter((c) => userSatisfies(user, c.requires));
      if (children.length > 0) out.push({ ...entry, children });
    } else {
      out.push(entry);
    }
  }
  return out;
}
```

Note: `/releases` is the "Releases" item and `/releases/calendar` etc. are siblings. `isPathActive` (Task 4) uses prefix match, so `/releases/calendar` would light both. Task 4 handles this by choosing the **longest** matching path per tree, not every match.

- [ ] **Step 4: Run tests; expect `AppLayout` to break type-check until Task 4**

Run: `npx vitest run src/components/__tests__/navConfig.test.tsx`
Expected: 7 passed. `npx tsc --noEmit` will fail on `AppLayout.tsx` (imports `visibleNavGroups`) — expected until Task 4; do not commit yet.

---

### Task 3: Entity-config table and the admin tree

**Files:**
- Create: `src/pages/admin/entityConfigTabs.ts`
- Create: `src/components/adminNavConfig.tsx`
- Test: `src/components/__tests__/adminNavConfig.test.tsx`

**Interfaces:**
- Produces (`entityConfigTabs.ts`):
  ```ts
  export type AdminEntity = 'environments' | 'environment-requests' | 'bookings' | 'releases' | 'release-changes' | 'change-requests' | 'builds' | 'deployments' | 'incidents' | 'systems' | 'subsystems';
  export type EntityPanel = 'fields' | 'lifecycle' | 'booking-types' | 'event-types' | 'gate-types' | 'rollback-policy' | 'tiers' | 'naming-policy' | 'lifecycle-policy';
  export interface EntityConfigTab { key: string; label: string; panel: EntityPanel }
  export interface EntityConfigPage { entity: AdminEntity; label: string; entityType: EntityType; tabs: EntityConfigTab[] }
  export const ENTITY_CONFIG_PAGES: EntityConfigPage[];
  export function entityConfigPage(entity: string | undefined): EntityConfigPage | undefined;
  export function entityTabPath(entity: AdminEntity, tab: string): string; // `/admin/${entity}/${tab}`
  ```
- Produces (`adminNavConfig.tsx`): `export const adminNav: NavGroup[]`, `export function visibleAdminNav(user: NavUser | null): NavGroup[]`. Every item has a `description`.

- [ ] **Step 1: Write the failing test**

```tsx
// src/components/__tests__/adminNavConfig.test.tsx
import { describe, expect, it } from 'vitest';
import { adminNav, visibleAdminNav } from '../adminNavConfig';
import { ENTITY_CONFIG_PAGES, entityTabPath } from '../../pages/admin/entityConfigTabs';
import type { NavUser } from '../navConfig';

const regular: NavUser = { role: 'Developer', is_master_admin: false };
const admin: NavUser = { role: 'Admin', is_master_admin: false };
const masterOnly: NavUser = { role: 'Viewer', is_master_admin: true };

const sections = (u: NavUser | null) => visibleAdminNav(u).map((s) => s.label);
const items = (u: NavUser | null, section: string) =>
  visibleAdminNav(u).find((s) => s.label === section)?.children.map((c) => c.label) ?? [];

describe('adminNav', () => {
  it('shows every section but Platform to an Admin', () => {
    expect(sections(admin)).toEqual([
      'Organisation', 'Environments', 'Bookings', 'Releases', 'Delivery', 'Integrations',
    ]);
  });

  it('shows only Platform to a master admin who is not role Admin', () => {
    expect(sections(masterOnly)).toEqual(['Platform']);
    expect(items(masterOnly, 'Platform')).toEqual(['Tenants']);
  });

  it('keeps User groups readable by a regular user — the page was never Admin-gated', () => {
    // B3a: reads are open to any tenant member; only writes are Admin. A
    // Developer following a group link from a project must still land somewhere.
    expect(sections(regular)).toEqual(['Organisation']);
    expect(items(regular, 'Organisation')).toEqual(['User groups']);
  });

  it('lists the Releases section in the agreed order with Templates first', () => {
    expect(items(admin, 'Releases')).toEqual([
      'Templates', 'Gate types', 'Rollback policy', 'Event types', 'Lifecycle',
      'Scope-change rules', 'RAID settings', 'Custom fields', 'Scope item fields',
    ]);
  });

  it('points every entity-tab item at a tab that exists in ENTITY_CONFIG_PAGES', () => {
    const known = new Set(
      ENTITY_CONFIG_PAGES.flatMap((p) => p.tabs.map((t) => entityTabPath(p.entity, t.key)))
    );
    const standalone = new Set([
      '/admin/releases/templates', '/admin/releases/scope-change-rules', '/admin/releases/raid',
    ]);
    const entityPaths = adminNav
      .flatMap((s) => s.children)
      .map((c) => c.path)
      .filter((p) => /^\/admin\/[a-z-]+\/[a-z-]+$/.test(p) && !standalone.has(p));
    expect(entityPaths.length).toBeGreaterThan(10);
    for (const p of entityPaths) expect(known.has(p), p).toBe(true);
  });

  it('gives every item a description for the hub', () => {
    for (const s of adminNav) for (const c of s.children) expect(c.description, c.label).toBeTruthy();
  });

  it('has no duplicate paths', () => {
    const paths = adminNav.flatMap((s) => s.children.map((c) => c.path));
    expect(new Set(paths).size).toBe(paths.length);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/components/__tests__/adminNavConfig.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Create `src/pages/admin/entityConfigTabs.ts`**

```ts
import type { EntityType } from '../../types/customField';

/** URL segment for an admin entity page: `/admin/<entity>/<tab>`. */
export type AdminEntity =
  | 'environments'
  | 'environment-requests'
  | 'bookings'
  | 'releases'
  | 'release-changes'
  | 'change-requests'
  | 'builds'
  | 'deployments'
  | 'incidents'
  | 'systems'
  | 'subsystems';

export type EntityPanel =
  | 'fields'
  | 'lifecycle'
  | 'booking-types'
  | 'event-types'
  | 'gate-types'
  | 'rollback-policy'
  | 'tiers'
  | 'naming-policy'
  | 'lifecycle-policy';

export interface EntityConfigTab {
  key: string;
  label: string;
  panel: EntityPanel;
}

export interface EntityConfigPage {
  entity: AdminEntity;
  label: string;
  entityType: EntityType;
  tabs: EntityConfigTab[];
}

const FIELDS: EntityConfigTab = { key: 'fields', label: 'Custom fields', panel: 'fields' };
const LIFECYCLE: EntityConfigTab = { key: 'lifecycle', label: 'Lifecycle', panel: 'lifecycle' };

/**
 * The one table that says which entity has which configuration tab. The
 * admin drawer's items, the /admin hub and the EntityConfig page all derive
 * from it — replacing the seven `*_SUPPORTED` lists and the arithmetic tab
 * indices EntityConfig used to compute from them.
 */
export const ENTITY_CONFIG_PAGES: EntityConfigPage[] = [
  {
    entity: 'environments',
    label: 'Environments',
    entityType: 'environment',
    tabs: [
      FIELDS,
      { key: 'tiers', label: 'Tiers', panel: 'tiers' },
      { key: 'naming-policy', label: 'Naming policy', panel: 'naming-policy' },
      { key: 'lifecycle-policy', label: 'Lifecycle & decommissioning', panel: 'lifecycle-policy' },
    ],
  },
  {
    entity: 'environment-requests',
    label: 'Environment requests',
    entityType: 'environment_request',
    tabs: [FIELDS, LIFECYCLE],
  },
  {
    entity: 'bookings',
    label: 'Bookings',
    entityType: 'booking',
    tabs: [FIELDS, { key: 'types', label: 'Booking types', panel: 'booking-types' }, LIFECYCLE],
  },
  {
    entity: 'releases',
    label: 'Releases',
    entityType: 'release',
    tabs: [
      FIELDS,
      LIFECYCLE,
      { key: 'event-types', label: 'Event types', panel: 'event-types' },
      { key: 'gate-types', label: 'Gate types', panel: 'gate-types' },
      { key: 'rollback-policy', label: 'Rollback policy', panel: 'rollback-policy' },
    ],
  },
  { entity: 'release-changes', label: 'Release scope items', entityType: 'release_change', tabs: [FIELDS] },
  { entity: 'change-requests', label: 'Change requests', entityType: 'change_request', tabs: [FIELDS, LIFECYCLE] },
  { entity: 'builds', label: 'Builds', entityType: 'build', tabs: [FIELDS] },
  { entity: 'deployments', label: 'Deployments', entityType: 'deployment', tabs: [FIELDS] },
  { entity: 'incidents', label: 'Incidents', entityType: 'incident', tabs: [FIELDS, LIFECYCLE] },
  { entity: 'systems', label: 'Systems', entityType: 'system', tabs: [FIELDS] },
  { entity: 'subsystems', label: 'Subsystems', entityType: 'subsystem', tabs: [FIELDS] },
];

export function entityConfigPage(entity: string | undefined): EntityConfigPage | undefined {
  return ENTITY_CONFIG_PAGES.find((p) => p.entity === entity);
}

export function entityTabPath(entity: AdminEntity, tab: string): string {
  return `/admin/${entity}/${tab}`;
}
```

- [ ] **Step 4: Create `src/components/adminNavConfig.tsx`**

```tsx
import BusinessIcon from '@mui/icons-material/Business';
import ComputerIcon from '@mui/icons-material/Computer';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import ExtensionIcon from '@mui/icons-material/Extension';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import { entityTabPath } from '../pages/admin/entityConfigTabs';
import { userSatisfies, type NavGroup, type NavUser } from './navConfig';

/**
 * The admin tree. Sections group by WHAT an admin is configuring, not by
 * which table holds the setting — RAID settings and scope-change rules sit
 * beside release templates, where a release manager looks for them.
 *
 * Items carry no icons (one per section); every item has a description
 * because the /admin hub is generated from this tree.
 *
 * Role rule: everything is Admin-only except Platform (master admin) and
 * User groups (readable by any member — B3a's read/write split; a Developer
 * following a group link from a project page must still land somewhere).
 */
export const adminNav: NavGroup[] = [
  {
    label: 'Organisation',
    icon: <BusinessIcon />,
    children: [
      { label: 'Users', path: '/admin/users', requires: 'admin', description: 'Accounts, roles and access for this tenant.' },
      { label: 'User groups', path: '/admin/user-groups', description: 'Teams that operate environments and staff projects.' },
      { label: 'Tenant settings', path: '/admin/settings', requires: 'admin', description: 'Tenant name, slug and advanced settings.' },
    ],
  },
  {
    label: 'Environments',
    icon: <ComputerIcon />,
    requires: 'admin',
    children: [
      { label: 'Tiers', path: entityTabPath('environments', 'tiers'), description: 'The tier vocabulary (dev, SIT, UAT…) and per-tier idle thresholds.' },
      { label: 'Naming policy', path: entityTabPath('environments', 'naming-policy'), description: 'Name pattern, required attributes and quarantine grace.' },
      { label: 'Lifecycle & decommissioning', path: entityTabPath('environments', 'lifecycle-policy'), description: 'Idle detection, notice period and the teardown checklist.' },
      { label: 'Request lifecycle', path: entityTabPath('environment-requests', 'lifecycle'), description: 'States and transitions for environment requests.' },
      { label: 'Custom fields', path: entityTabPath('environments', 'fields'), description: 'Tenant-defined fields on every environment.' },
    ],
  },
  {
    label: 'Bookings',
    icon: <EventAvailableIcon />,
    requires: 'admin',
    children: [
      { label: 'Booking types', path: entityTabPath('bookings', 'types'), description: 'Types, default protection level and duration presets.' },
      { label: 'Lifecycle', path: entityTabPath('bookings', 'lifecycle'), description: 'States and transitions for bookings.' },
      { label: 'Custom fields', path: entityTabPath('bookings', 'fields'), description: 'Tenant-defined fields on every booking.' },
    ],
  },
  {
    label: 'Releases',
    icon: <RocketLaunchIcon />,
    requires: 'admin',
    children: [
      { label: 'Templates', path: '/admin/releases/templates', description: 'Reusable release blueprints: phases, gates and events.' },
      { label: 'Gate types', path: entityTabPath('releases', 'gate-types'), description: 'The gate vocabulary, failure behaviour and expected evidence.' },
      { label: 'Rollback policy', path: entityTabPath('releases', 'rollback-policy'), description: 'Whether a missing plan or stale rehearsal warns or blocks.' },
      { label: 'Event types', path: entityTabPath('releases', 'event-types'), description: 'Release calendar event types.' },
      { label: 'Lifecycle', path: entityTabPath('releases', 'lifecycle'), description: 'States and transitions for releases.' },
      { label: 'Scope-change rules', path: '/admin/releases/scope-change-rules', description: 'Change kinds and what counts as scope creep.' },
      { label: 'RAID settings', path: '/admin/releases/raid', description: 'RAID categories, RAG thresholds and defaults.' },
      { label: 'Custom fields', path: entityTabPath('releases', 'fields'), description: 'Tenant-defined fields on every release.' },
      { label: 'Scope item fields', path: entityTabPath('release-changes', 'fields'), description: 'Tenant-defined fields on release scope items.' },
    ],
  },
  {
    label: 'Delivery',
    icon: <LocalShippingIcon />,
    requires: 'admin',
    children: [
      { label: 'Change requests', path: entityTabPath('change-requests', 'fields'), description: 'Custom fields and lifecycle for change requests.' },
      { label: 'Builds', path: entityTabPath('builds', 'fields'), description: 'Custom fields on builds.' },
      { label: 'Deployments', path: entityTabPath('deployments', 'fields'), description: 'Custom fields on deployments.' },
      { label: 'Incidents', path: entityTabPath('incidents', 'fields'), description: 'Custom fields and lifecycle for incidents.' },
      { label: 'Systems', path: entityTabPath('systems', 'fields'), description: 'Custom fields on systems.' },
      { label: 'Subsystems', path: entityTabPath('subsystems', 'fields'), description: 'Custom fields on subsystems.' },
      { label: 'Component types', path: '/admin/component-types', description: 'Infrastructure component types and their field schemas.' },
      { label: 'Environment request fields', path: entityTabPath('environment-requests', 'fields'), description: 'Custom fields on environment requests.' },
    ],
  },
  {
    label: 'Integrations',
    icon: <ExtensionIcon />,
    requires: 'admin',
    children: [
      { label: 'API keys', path: '/admin/api-keys', description: 'Keys and scopes for pipelines and webhooks.' },
      { label: 'GitHub', path: '/admin/github', description: 'Connect GitHub for repository scanning and drift checks.' },
    ],
  },
  {
    label: 'Platform',
    icon: <AdminPanelSettingsIcon />,
    requires: 'masterAdmin',
    children: [
      { label: 'Tenants', path: '/admin/tenants', description: 'Provision tenants, their first Admin, and sign in as one.' },
    ],
  },
];

/** A child inherits its section's `requires` unless it sets its own. */
export function visibleAdminNav(user: NavUser | null): NavGroup[] {
  return adminNav
    .map((section) => ({
      ...section,
      children: section.children.filter((c) =>
        userSatisfies(user, c.requires ?? section.requires)
      ),
    }))
    .filter((section) => section.children.length > 0);
}
```

Section-level `requires` is inherited per child (not applied to the section itself) so that Organisation can show *User groups* alone to a regular user.

- [ ] **Step 5: Run tests**

Run: `npx vitest run src/components/__tests__/adminNavConfig.test.tsx src/components/__tests__/navConfig.test.tsx`
Expected: all passed.

---

### Task 4: `NavDrawer` and the `AppLayout` mode switch

**Files:**
- Create: `src/components/NavDrawer.tsx`
- Modify: `src/components/AppLayout.tsx`
- Test: `src/components/__tests__/NavDrawer.test.tsx`, `src/components/__tests__/AppLayout.test.tsx`

**Interfaces:**
- Produces (`NavDrawer.tsx`):
  ```ts
  export function isPathActive(current: string, path: string): boolean;
  /** Longest matching item path across the tree, or undefined. */
  export function activeItemPath(entries: NavEntry[], current: string): string | undefined;
  /** Label of the group holding the active item, or undefined. */
  export function groupContaining(entries: NavEntry[], current: string): string | undefined;
  export interface NavDrawerProps {
    entries: NavEntry[];
    currentPath: string;
    isGroupOpen: (label: string) => boolean;
    onToggleGroup: (label: string) => void;
    onNavigate: (path: string) => void;
    header?: ReactNode;
  }
  export default function NavDrawer(props: NavDrawerProps): JSX.Element;
  ```

- [ ] **Step 1: Write the failing NavDrawer tests**

```tsx
// src/components/__tests__/NavDrawer.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import NavDrawer, { activeItemPath, groupContaining, isPathActive } from '../NavDrawer';
import type { NavEntry } from '../navConfig';

const tree: NavEntry[] = [
  { label: 'Dashboard', path: '/dashboard' },
  {
    label: 'Releases',
    icon: <span />,
    children: [
      { label: 'Releases', path: '/releases' },
      { label: 'Calendar', path: '/releases/calendar' },
    ],
  },
];

describe('path helpers', () => {
  it('matches exact and nested paths, not prefixes of a longer segment', () => {
    expect(isPathActive('/releases', '/releases')).toBe(true);
    expect(isPathActive('/releases/7', '/releases')).toBe(true);
    expect(isPathActive('/releases-archive', '/releases')).toBe(false);
  });

  it('picks the longest matching item so siblings do not both light up', () => {
    expect(activeItemPath(tree, '/releases/calendar')).toBe('/releases/calendar');
    expect(activeItemPath(tree, '/releases/7')).toBe('/releases');
    expect(activeItemPath(tree, '/nowhere')).toBeUndefined();
  });

  it('names the group holding the active item', () => {
    expect(groupContaining(tree, '/releases/calendar')).toBe('Releases');
    expect(groupContaining(tree, '/dashboard')).toBeUndefined();
  });
});

describe('NavDrawer', () => {
  it('renders items, hides children of a closed group, and toggles', async () => {
    const onToggleGroup = vi.fn();
    const onNavigate = vi.fn();
    const { rerender } = render(
      <NavDrawer
        entries={tree}
        currentPath="/dashboard"
        isGroupOpen={() => false}
        onToggleGroup={onToggleGroup}
        onNavigate={onNavigate}
      />
    );
    expect(screen.getByRole('button', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Calendar' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Releases/ }));
    expect(onToggleGroup).toHaveBeenCalledWith('Releases');

    rerender(
      <NavDrawer
        entries={tree}
        currentPath="/releases/calendar"
        isGroupOpen={() => true}
        onToggleGroup={onToggleGroup}
        onNavigate={onNavigate}
      />
    );
    const calendar = screen.getByRole('button', { name: 'Calendar' });
    expect(calendar).toHaveClass('Mui-selected');
    expect(screen.getByRole('button', { name: 'Releases', exact: true })).not.toHaveClass('Mui-selected');
    await userEvent.click(calendar);
    expect(onNavigate).toHaveBeenCalledWith('/releases/calendar');
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/components/__tests__/NavDrawer.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `src/components/NavDrawer.tsx`**

```tsx
import type { ReactNode } from 'react';
import {
  Collapse,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { isNavGroup, type NavEntry, type NavItem } from './navConfig';

export function isPathActive(current: string, path: string): boolean {
  return current === path || current.startsWith(path + '/');
}

function allItems(entries: NavEntry[]): NavItem[] {
  return entries.flatMap((e) => (isNavGroup(e) ? e.children : [e]));
}

/** Longest matching path wins, so `/releases` and `/releases/calendar` never light together. */
export function activeItemPath(entries: NavEntry[], current: string): string | undefined {
  let best: string | undefined;
  for (const item of allItems(entries)) {
    if (isPathActive(current, item.path) && (best === undefined || item.path.length > best.length)) {
      best = item.path;
    }
  }
  return best;
}

export function groupContaining(entries: NavEntry[], current: string): string | undefined {
  const active = activeItemPath(entries, current);
  if (active === undefined) return undefined;
  for (const entry of entries) {
    if (isNavGroup(entry) && entry.children.some((c) => c.path === active)) return entry.label;
  }
  return undefined;
}

export interface NavDrawerProps {
  entries: NavEntry[];
  currentPath: string;
  isGroupOpen: (label: string) => boolean;
  onToggleGroup: (label: string) => void;
  onNavigate: (path: string) => void;
  /** Rendered above the list — admin mode's back link and heading. */
  header?: ReactNode;
}

const itemSx = { borderRadius: 1, mx: 1, mb: 0.5 };

export default function NavDrawer({
  entries,
  currentPath,
  isGroupOpen,
  onToggleGroup,
  onNavigate,
  header,
}: NavDrawerProps) {
  const active = activeItemPath(entries, currentPath);

  const renderItem = (item: NavItem, nested: boolean) => (
    <ListItemButton
      key={item.path}
      selected={item.path === active}
      onClick={() => onNavigate(item.path)}
      sx={{ ...itemSx, pl: nested ? 4 : 2 }}
    >
      {item.icon !== undefined && <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>}
      <ListItemText primary={item.label} />
    </ListItemButton>
  );

  return (
    <>
      {header}
      <List dense>
        {entries.map((entry) => {
          if (!isNavGroup(entry)) return renderItem(entry, false);
          const open = isGroupOpen(entry.label);
          return (
            <div key={entry.label}>
              <ListItemButton
                onClick={() => onToggleGroup(entry.label)}
                aria-expanded={open}
                sx={itemSx}
              >
                <ListItemIcon sx={{ minWidth: 36 }}>{entry.icon}</ListItemIcon>
                <ListItemText primary={entry.label} primaryTypographyProps={{ noWrap: true }} />
                {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </ListItemButton>
              <Collapse in={open} timeout="auto" unmountOnExit>
                <List dense disablePadding>
                  {entry.children.map((child) => renderItem(child, true))}
                </List>
              </Collapse>
            </div>
          );
        })}
      </List>
    </>
  );
}
```

- [ ] **Step 4: Run the NavDrawer tests**

Run: `npx vitest run src/components/__tests__/NavDrawer.test.tsx`
Expected: 4 passed.

- [ ] **Step 5: Write the failing AppLayout tests**

```tsx
// src/components/__tests__/AppLayout.test.tsx
import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AppLayout from '../AppLayout';
import authReducer from '../../store/authSlice';
import uiReducer from '../../store/uiSlice';

vi.mock('../../services/authService', () => ({ authService: { logout: vi.fn() } }));

function Probe() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return (
    <div>
      <div data-testid="path">{pathname}</div>
      <button onClick={() => navigate('/releases/calendar')}>go calendar</button>
      <button onClick={() => navigate('/admin/users')}>go admin users</button>
      <button onClick={() => navigate('/projects')}>go projects</button>
    </div>
  );
}

function renderAt(path: string, role = 'Admin', isMaster = false) {
  const store = configureStore({
    reducer: { auth: authReducer, ui: uiReducer },
    preloadedState: {
      auth: {
        user: { id: 1, username: 'admin', email: 'a@x', role, tenant_id: 1, is_master_admin: isMaster },
        token: 't', isAuthenticated: true, authInitialized: true,
        impersonationMode: false, impersonatingTenant: null, originalToken: null,
      },
    },
  });
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="*" element={<Probe />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </Provider>
  );
  return store;
}

describe('AppLayout', () => {
  beforeEach(() => localStorage.clear());

  it('opens the group containing the route on NAVIGATION, not only at mount', async () => {
    // The old layout computed open state once in a useState initialiser, so
    // arriving in a group later left it collapsed with nothing selected.
    renderAt('/dashboard');
    await userEvent.click(screen.getByRole('button', { name: /^Releases$/ })); // collapse it
    expect(screen.queryByRole('button', { name: 'Calendar' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('go calendar'));
    expect(await screen.findByRole('button', { name: 'Calendar' })).toHaveClass('Mui-selected');
  });

  it('remembers a collapsed group across a remount', async () => {
    renderAt('/dashboard');
    await userEvent.click(screen.getByRole('button', { name: /^Catalogue$/ }));
    expect(localStorage.getItem('ui.navOpenGroups')).toContain('"app:Catalogue":false');
  });

  it('swaps to the admin drawer under /admin and back returns to the last app route', async () => {
    renderAt('/projects');
    expect(screen.queryByText('Back to EnvManager')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('go admin users'));
    expect(await screen.findByText('Back to EnvManager')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Catalogue$/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Users' })).toHaveClass('Mui-selected');
    await userEvent.click(screen.getByText('Back to EnvManager'));
    expect(screen.getByTestId('path')).toHaveTextContent('/projects');
  });

  it('shows a master-only admin just the Platform section', async () => {
    renderAt('/admin', 'Viewer', true);
    expect(await screen.findByRole('button', { name: /^Platform$/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Organisation$/ })).not.toBeInTheDocument();
  });

  it('makes the app title a link to the dashboard', () => {
    renderAt('/projects');
    expect(screen.getByRole('link', { name: 'EnvManager' })).toHaveAttribute('href', '/dashboard');
  });
});
```

- [ ] **Step 6: Run to verify it fails**

Run: `npx vitest run src/components/__tests__/AppLayout.test.tsx`
Expected: FAIL (old layout: no "Back to EnvManager", `visibleNavGroups` import broken).

- [ ] **Step 7: Rewrite the drawer half of `src/components/AppLayout.tsx`**

Keep the AppBar, avatar menu, theme cycling and logout exactly as they are. Replace the imports of `visibleNavGroups`/`NavItem`, the `groupOpen` state, and the whole `<Drawer>` contents with:

```tsx
// imports to add / replace
import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Link, ListItemButton, ListItemIcon, ListItemText, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { setLastAppRoute, setNavGroupOpen, setThemeMode, type ThemeModePreference } from '../store/uiSlice';
import { ADMIN_ROOT, visibleAppNav } from './navConfig';
import { visibleAdminNav } from './adminNavConfig';
import NavDrawer, { groupContaining } from './NavDrawer';

// inside the component, replacing `navGroups` and `groupOpen`:
const navOpenGroups = useSelector((state: RootState) => state.ui.navOpenGroups);
const lastAppRoute = useSelector((state: RootState) => state.ui.lastAppRoute);
const adminMode =
  location.pathname === ADMIN_ROOT || location.pathname.startsWith(ADMIN_ROOT + '/');
const mode = adminMode ? 'admin' : 'app';
const entries = adminMode ? visibleAdminNav(user) : visibleAppNav(user);
const groupKey = (label: string) => `${mode}:${label}`;
const isGroupOpen = (label: string) => navOpenGroups[groupKey(label)] ?? true;
const toggleGroup = (label: string) =>
  dispatch(setNavGroupOpen({ key: groupKey(label), open: !isGroupOpen(label) }));

// Open the group holding the current route on EVERY navigation, and remember
// the last non-admin route so "Back to EnvManager" has somewhere to go.
useEffect(() => {
  if (!adminMode) dispatch(setLastAppRoute(location.pathname + location.search));
  const holder = groupContaining(entries, location.pathname);
  if (holder !== undefined && navOpenGroups[groupKey(holder)] === false) {
    dispatch(setNavGroupOpen({ key: groupKey(holder), open: true }));
  }
  // entries/navOpenGroups are derived from user + store; pathname is the trigger.
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [location.pathname, location.search, adminMode]);

const adminHeader = (
  <>
    <ListItemButton onClick={() => navigateAndClose(lastAppRoute)} sx={{ borderRadius: 1, mx: 1, mt: 0.5 }}>
      <ListItemIcon sx={{ minWidth: 36 }}><ArrowBackIcon fontSize="small" /></ListItemIcon>
      <ListItemText primary="Back to EnvManager" />
    </ListItemButton>
    <Typography variant="overline" color="text.secondary" sx={{ px: 2, display: 'block' }}>
      Administration
    </Typography>
  </>
);
```

The `<Drawer>` body becomes:

```tsx
<Toolbar />
<Box sx={{ overflow: 'auto', mt: 1 }}>
  <NavDrawer
    entries={entries}
    currentPath={location.pathname}
    isGroupOpen={isGroupOpen}
    onToggleGroup={toggleGroup}
    onNavigate={navigateAndClose}
    header={adminMode ? adminHeader : undefined}
  />
</Box>
```

And the AppBar title becomes a real link (P3-6):

```tsx
<Link
  component={RouterLink}
  to="/dashboard"
  color="inherit"
  underline="none"
  variant="h6"
  sx={{ flexGrow: 1 }}
>
  EnvManager
</Link>
```

Remove the now-unused `Chip`, `Collapse`, `List`, `Tooltip`, `ExpandLessIcon`, `ExpandMoreIcon` imports and the `comingSoon` handling (no item uses it).

- [ ] **Step 8: Run tests and type-check**

Run: `npx vitest run src/components/__tests__/ && npx tsc --noEmit && npm run lint`
Expected: all green. (`tsc` may still fail on `App.tsx`'s `AdminLayout` import only if you deleted it early — don't; that is Task 8.)

- [ ] **Step 9: Commit**

```bash
git add src/components/navConfig.tsx src/components/adminNavConfig.tsx src/components/NavDrawer.tsx src/components/AppLayout.tsx src/pages/admin/entityConfigTabs.ts src/components/__tests__/
git commit -m "feat(nav): app and admin trees on one NavDrawer; admin mode swaps the drawer"
```

---

### Task 5: `EntityConfig` on route tabs + `ComponentTypesPage`

**Files:**
- Rewrite: `src/pages/admin/EntityConfig.tsx`
- Create: `src/pages/admin/ComponentTypesPage.tsx`
- Test: `src/pages/admin/__tests__/entityConfig.test.tsx`

**Interfaces:**
- Consumes: `entityConfigPage`, `entityTabPath`, `ENTITY_CONFIG_PAGES` (Task 3).
- Produces: default-export page reading `useParams<{ entity: string; tab?: string }>()`; unknown entity → `<NotFound />`; missing/unknown tab → `<Navigate replace>` to the first tab.

- [ ] **Step 1: Write the failing test**

```tsx
// src/pages/admin/__tests__/entityConfig.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import EntityConfig from '../EntityConfig';

// Panels own their own tests; here only the routing/tab wiring is under test.
vi.mock('../../../components/admin/CustomFieldDefinitionManager', () => ({
  default: ({ entityType }: { entityType: string }) => <div>fields:{entityType}</div>,
}));
vi.mock('../../../components/admin/LifecycleTemplatesPanel', () => ({
  default: ({ entityType }: { entityType: string }) => <div>lifecycle:{entityType}</div>,
}));
vi.mock('../../../components/admin/BookingTypesPanel', () => ({ default: () => <div>booking-types</div> }));
vi.mock('../../../components/admin/ReleaseEventTypesPanel', () => ({ default: () => <div>event-types</div> }));
vi.mock('../../../components/admin/GateTypesPanel', () => ({ default: () => <div>gate-types</div> }));
vi.mock('../../../components/admin/RollbackPolicyPanel', () => ({ default: () => <div>rollback-policy</div> }));
vi.mock('../../../components/admin/EnvironmentTiersPanel', () => ({ default: () => <div>tiers</div> }));
vi.mock('../../../components/admin/EnvironmentNamingPolicyPanel', () => ({ default: () => <div>naming-policy</div> }));
vi.mock('../../../components/admin/EnvironmentLifecyclePanel', () => ({ default: () => <div>lifecycle-policy</div> }));

function Path() {
  return <div data-testid="path">{useLocation().pathname}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/admin/:entity/:tab" element={<><EntityConfig /><Path /></>} />
        <Route path="/admin/:entity" element={<><EntityConfig /><Path /></>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('EntityConfig', () => {
  it('renders the tab named in the URL', () => {
    renderAt('/admin/environments/naming-policy');
    expect(screen.getByRole('tab', { name: 'Naming policy' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('naming-policy')).toBeInTheDocument();
  });

  it('redirects a bare entity path to its first tab', () => {
    renderAt('/admin/bookings');
    expect(screen.getByTestId('path')).toHaveTextContent('/admin/bookings/fields');
    expect(screen.getByText('fields:booking')).toBeInTheDocument();
  });

  it('redirects an unknown tab to the first tab', () => {
    renderAt('/admin/releases/nope');
    expect(screen.getByTestId('path')).toHaveTextContent('/admin/releases/fields');
  });

  it('changes the URL when a tab is clicked', async () => {
    renderAt('/admin/releases/fields');
    await userEvent.click(screen.getByRole('tab', { name: 'Gate types' }));
    expect(screen.getByTestId('path')).toHaveTextContent('/admin/releases/gate-types');
    expect(screen.getByText('gate-types')).toBeInTheDocument();
  });

  it('shows Booking types as its own tab, not stacked above Lifecycle', () => {
    renderAt('/admin/bookings/types');
    expect(screen.getByText('booking-types')).toBeInTheDocument();
    expect(screen.queryByText('lifecycle:booking')).not.toBeInTheDocument();
  });

  it('renders not-found for an unknown entity', () => {
    renderAt('/admin/widgets/fields');
    expect(screen.getByText(/not found/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/pages/admin/__tests__/entityConfig.test.tsx`
Expected: FAIL (old component reads `entityType` param, numeric tabs).

- [ ] **Step 3: Rewrite `src/pages/admin/EntityConfig.tsx`**

```tsx
import { Box, Tab, Tabs, Typography } from '@mui/material';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import type { EntityType } from '../../types/customField';
import NotFound from '../../components/NotFound';
import BookingTypesPanel from '../../components/admin/BookingTypesPanel';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import EnvironmentLifecyclePanel from '../../components/admin/EnvironmentLifecyclePanel';
import EnvironmentNamingPolicyPanel from '../../components/admin/EnvironmentNamingPolicyPanel';
import EnvironmentTiersPanel from '../../components/admin/EnvironmentTiersPanel';
import GateTypesPanel from '../../components/admin/GateTypesPanel';
import LifecycleTemplatesPanel from '../../components/admin/LifecycleTemplatesPanel';
import ReleaseEventTypesPanel from '../../components/admin/ReleaseEventTypesPanel';
import RollbackPolicyPanel from '../../components/admin/RollbackPolicyPanel';
import { entityConfigPage, entityTabPath, type EntityPanel } from './entityConfigTabs';

function Panel({ panel, entityType }: { panel: EntityPanel; entityType: EntityType }) {
  switch (panel) {
    case 'fields':
      return <CustomFieldDefinitionManager entityType={entityType} />;
    case 'lifecycle':
      return <LifecycleTemplatesPanel entityType={entityType} />;
    case 'booking-types':
      return <BookingTypesPanel />;
    case 'event-types':
      return <ReleaseEventTypesPanel />;
    case 'gate-types':
      return <GateTypesPanel />;
    case 'rollback-policy':
      return <RollbackPolicyPanel />;
    case 'tiers':
      return <EnvironmentTiersPanel />;
    case 'naming-policy':
      return <EnvironmentNamingPolicyPanel />;
    case 'lifecycle-policy':
      return <EnvironmentLifecyclePanel />;
  }
}

/**
 * `/admin/:entity/:tab`. The tab is a route segment, so a drawer item can
 * point straight at "Naming policy" and a reload lands on the same tab.
 * Which tabs an entity has is `ENTITY_CONFIG_PAGES`' business, not this file's.
 */
export default function EntityConfig() {
  const { entity, tab } = useParams<{ entity: string; tab?: string }>();
  const navigate = useNavigate();
  const page = entityConfigPage(entity);
  if (!page) return <NotFound />;

  const current = page.tabs.find((t) => t.key === tab);
  if (!current) return <Navigate replace to={entityTabPath(page.entity, page.tabs[0].key)} />;

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        {page.label}
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure {page.label.toLowerCase()} for your tenant.
      </Typography>
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={current.key}
          onChange={(_, key: string) => navigate(entityTabPath(page.entity, key))}
          variant="scrollable"
          scrollButtons="auto"
        >
          {page.tabs.map((t) => (
            <Tab key={t.key} value={t.key} label={t.label} />
          ))}
        </Tabs>
      </Box>
      <Panel panel={current.panel} entityType={page.entityType} />
    </Box>
  );
}
```

Check `components/NotFound.tsx` renders text matching `/not found/i`; if it does not, adjust the test's regex to the text it renders — do not change `NotFound`.

- [ ] **Step 4: Create `src/pages/admin/ComponentTypesPage.tsx`**

```tsx
import { Box, Typography } from '@mui/material';
import ComponentTypesPanel from '../../components/admin/ComponentTypesPanel';

/** `/admin/component-types` — the one entity-config page with no custom-field tab. */
export default function ComponentTypesPage() {
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Component types
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Define component types with custom field schemas for subsystems.
      </Typography>
      <ComponentTypesPanel />
    </Box>
  );
}
```

- [ ] **Step 5: Run tests and type-check**

Run: `npx vitest run src/pages/admin/__tests__/entityConfig.test.tsx && npx tsc --noEmit`
Expected: 6 passed; tsc clean.

- [ ] **Step 6: Commit**

```bash
git add src/pages/admin/EntityConfig.tsx src/pages/admin/ComponentTypesPage.tsx src/pages/admin/__tests__/entityConfig.test.tsx
git commit -m "refactor(admin): entity config on /admin/:entity/:tab, driven by ENTITY_CONFIG_PAGES"
```

---

### Task 6: `/admin` hub

**Files:**
- Create: `src/pages/admin/AdminHome.tsx`
- Test: `src/pages/admin/__tests__/adminHome.test.tsx`

**Interfaces:**
- Consumes: `visibleAdminNav` (Task 3), `RootState.auth.user`.

- [ ] **Step 1: Write the failing test**

```tsx
// src/pages/admin/__tests__/adminHome.test.tsx
import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import AdminHome from '../AdminHome';
import authReducer from '../../../store/authSlice';

function renderAs(role: string, isMaster = false) {
  const store = configureStore({
    reducer: { auth: authReducer },
    preloadedState: {
      auth: {
        user: { id: 1, username: 'u', email: 'u@x', role, tenant_id: 1, is_master_admin: isMaster },
        token: 't', isAuthenticated: true, authInitialized: true,
        impersonationMode: false, impersonatingTenant: null, originalToken: null,
      },
    },
  });
  render(<Provider store={store}><MemoryRouter><AdminHome /></MemoryRouter></Provider>);
}

describe('AdminHome', () => {
  it('renders a card per visible section with links to every item', () => {
    renderAs('Admin');
    expect(screen.getByRole('heading', { name: 'Releases' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Naming policy/ })).toHaveAttribute(
      'href', '/admin/environments/naming-policy'
    );
    expect(screen.getByText('Name pattern, required attributes and quarantine grace.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Platform' })).not.toBeInTheDocument();
  });

  it('shows only Platform to a master-only admin', () => {
    renderAs('Viewer', true);
    expect(screen.getByRole('heading', { name: 'Platform' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Organisation' })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/pages/admin/__tests__/adminHome.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Create `src/pages/admin/AdminHome.tsx`**

```tsx
import { Box, Card, CardContent, Grid, Link, List, ListItem, ListItemText, Stack, Typography } from '@mui/material';
import { useSelector } from 'react-redux';
import { Link as RouterLink } from 'react-router-dom';
import type { RootState } from '../../store';
import { visibleAdminNav } from '../../components/adminNavConfig';

/** `/admin` — generated from adminNav so it can never disagree with the drawer. */
export default function AdminHome() {
  const user = useSelector((state: RootState) => state.auth.user);
  const sections = visibleAdminNav(user);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Administration
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Tenant configuration, people and integrations.
      </Typography>
      <Grid container spacing={2}>
        {sections.map((section) => (
          <Grid item xs={12} md={6} lg={4} key={section.label}>
            <Card variant="outlined" sx={{ height: '100%' }}>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                  {section.icon}
                  <Typography variant="h6" component="h2">
                    {section.label}
                  </Typography>
                </Stack>
                <List dense disablePadding>
                  {section.children.map((item) => (
                    <ListItem key={item.path} disableGutters>
                      <ListItemText
                        primary={
                          <Link component={RouterLink} to={item.path} underline="hover">
                            {item.label}
                          </Link>
                        }
                        secondary={item.description}
                      />
                    </ListItem>
                  ))}
                </List>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
```

- [ ] **Step 4: Run tests, commit**

Run: `npx vitest run src/pages/admin/__tests__/adminHome.test.tsx && npx tsc --noEmit`
Expected: 2 passed.

```bash
git add src/pages/admin/AdminHome.tsx src/pages/admin/__tests__/adminHome.test.tsx
git commit -m "feat(admin): /admin hub generated from adminNav"
```

---

### Task 7: Move pages out of `admin/` and `tenant/`; update in-app links and their tests

**Files:**
- Move (git mv): `src/pages/admin/Projects.tsx` → `src/pages/projects/Projects.tsx`; `src/pages/admin/ProjectDetail.tsx` → `src/pages/projects/ProjectDetail.tsx`; `src/pages/admin/EnvironmentGroups.tsx` → `src/pages/environment-groups/EnvironmentGroups.tsx`; `src/pages/admin/EnvironmentGroupDetail.tsx` → `src/pages/environment-groups/EnvironmentGroupDetail.tsx`; `src/pages/tenant/UserManagement.tsx` → `src/pages/admin/UserManagement.tsx`; `src/pages/tenant/TenantSettings.tsx` → `src/pages/admin/TenantSettings.tsx`; and their tests: `src/pages/admin/__tests__/{projects,projectDetailGapLink,projectDetailPriorityRank}.test.tsx` → `src/pages/projects/__tests__/`; `src/pages/admin/__tests__/environmentGroups.test.tsx` → `src/pages/environment-groups/__tests__/`.
- Modify: `src/components/environments/EnvironmentGroupsPanel.tsx:85`, `src/components/environments/EnvironmentProjectsPanel.tsx:124`, `src/pages/admin/UserGroups.tsx:224`, `src/pages/admin/UserGroupDetail.tsx:98`, `src/pages/admin/release-templates/ReleaseTemplateLibrary.tsx:111,152`, `src/pages/admin/release-templates/ReleaseTemplateForm.tsx:4,172,189`, the moved `Projects.tsx:47,237`, `ProjectDetail.tsx:219,247,261,294`, `EnvironmentGroups.tsx:211`, `EnvironmentGroupDetail.tsx:96`, and `src/App.tsx` lazy import paths.

All moved files sit at the same directory depth as before, so their relative imports (`../../store`, `../../../services/...`) do not change; the tests' `../Projects` style imports stay identical by construction.

- [ ] **Step 1: Move the files**

```bash
mkdir -p src/pages/projects/__tests__ src/pages/environment-groups/__tests__
git mv src/pages/admin/Projects.tsx src/pages/projects/Projects.tsx
git mv src/pages/admin/ProjectDetail.tsx src/pages/projects/ProjectDetail.tsx
git mv src/pages/admin/__tests__/projects.test.tsx src/pages/projects/__tests__/projects.test.tsx
git mv src/pages/admin/__tests__/projectDetailGapLink.test.tsx src/pages/projects/__tests__/projectDetailGapLink.test.tsx
git mv src/pages/admin/__tests__/projectDetailPriorityRank.test.tsx src/pages/projects/__tests__/projectDetailPriorityRank.test.tsx
git mv src/pages/admin/EnvironmentGroups.tsx src/pages/environment-groups/EnvironmentGroups.tsx
git mv src/pages/admin/EnvironmentGroupDetail.tsx src/pages/environment-groups/EnvironmentGroupDetail.tsx
git mv src/pages/admin/__tests__/environmentGroups.test.tsx src/pages/environment-groups/__tests__/environmentGroups.test.tsx
git mv src/pages/tenant/UserManagement.tsx src/pages/admin/UserManagement.tsx
git mv src/pages/tenant/TenantSettings.tsx src/pages/admin/TenantSettings.tsx
rmdir src/pages/tenant
```

- [ ] **Step 2: Replace old route literals in source (not tests yet)**

Run from `frontend/`:

```bash
grep -rn "/tenant/projects\|/tenant/environment-groups\|/tenant/groups\|/admin/release-templates" src --include='*.tsx' | grep -v __tests__
```
Edit each hit with these exact substitutions — **UI route literals only; never touch a `services/*.ts` API path such as `api.get('/tenant/groups')`; those are backend URLs and unchanged**:

| Old | New |
|---|---|
| `` `/tenant/projects/${...}` `` and `'/tenant/projects'` | `` `/projects/${...}` `` / `'/projects'` |
| `` `/tenant/environment-groups/${...}` `` and `'/tenant/environment-groups'` | `` `/environment-groups/${...}` `` / `'/environment-groups'` |
| `` `/tenant/groups/${...}` `` and `'/tenant/groups'` | `` `/admin/user-groups/${...}` `` / `'/admin/user-groups'` |
| `/admin/release-templates` (all forms, including the doc comment on line 4 of the form) | `/admin/releases/templates` |

Back-button labels: `ProjectDetail.tsx`'s three `Back to Projects` → `Back to projects`; `UserGroupDetail.tsx:98` → `Back to user groups`; `EnvironmentGroupDetail.tsx:96` → `Back to environment groups`. Update any test that asserts those button names.

Then update the six lazy imports in `src/App.tsx` to the new locations so the tree type-checks:

```ts
const EnvironmentGroupDetail = lazy(() => import('./pages/environment-groups/EnvironmentGroupDetail'));
const EnvironmentGroups = lazy(() => import('./pages/environment-groups/EnvironmentGroups'));
const ProjectDetail = lazy(() => import('./pages/projects/ProjectDetail'));
const Projects = lazy(() => import('./pages/projects/Projects'));
const TenantSettings = lazy(() => import('./pages/admin/TenantSettings'));
const UserManagement = lazy(() => import('./pages/admin/UserManagement'));
```

- [ ] **Step 3: Update the moved/affected tests' paths**

In `src/pages/projects/__tests__/*.test.tsx`: `'/tenant/projects'` → `'/projects'`, `'/tenant/projects/:id'` → `'/projects/:id'`, `` `/tenant/projects/${…}` `` → `` `/projects/${…}` ``; `projects.test.tsx:174` expects `href` `'/projects/1'`.
In `src/pages/environment-groups/__tests__/environmentGroups.test.tsx`: `/tenant/environment-groups` → `/environment-groups` (lines 81, 303, 305).
In `src/components/environments/__tests__/EnvironmentGroupsPanel.test.tsx:107`: expected href `'/environment-groups/5'`.
In `src/pages/admin/__tests__/userGroupDetail.test.tsx:66,68` and `userGroups.test.tsx:67`: `/tenant/groups` → `/admin/user-groups`.
In `src/pages/admin/release-templates/__tests__/ReleaseTemplateForm.test.tsx:124,126`: `/admin/release-templates/7` → `/admin/releases/templates/7`, route `/admin/releases/templates/:id`.
Lines referring to the **API** path `/tenant/users/lite` or `GET /tenant/groups` (comments and service mocks) are untouched.

- [ ] **Step 4: Run the affected tests and type-check**

```bash
npx vitest run src/pages/projects src/pages/environment-groups src/pages/admin src/components/environments && npx tsc --noEmit && npm run lint
```
Expected: all pass, tsc clean (App.tsx still imports `AdminLayout`, which still exists until Task 8).

- [ ] **Step 5: Commit**

```bash
git add -A src
git commit -m "refactor(pages): projects and environment groups out of admin; users/settings into admin"
```

---

### Task 8: Routes, redirects, delete `AdminLayout`; the structural shell test

**Files:**
- Create: `src/components/legacyRedirects.tsx`
- Create: `src/test/renderApp.tsx`
- Modify: `src/App.tsx`
- Delete: `src/pages/admin/AdminLayout.tsx`
- Test: `src/__tests__/navRoutes.test.tsx`, `src/__tests__/legacyRedirects.test.tsx`

**Interfaces:**
- Produces (`legacyRedirects.tsx`):
  ```ts
  export interface LegacyRedirect { from: string; to: string } // react-router patterns, same param names
  export const LEGACY_REDIRECTS: LegacyRedirect[];
  export function LegacyRedirect({ to }: { to: string }): JSX.Element; // generatePath(to, useParams())
  ```
- Produces (`renderApp.tsx`): `renderAppAt(path: string, user: { role: string; is_master_admin?: boolean })` — pushes `path` into `window.history`, dispatches `setCredentials` on the singleton store, renders `<App/>` inside `<Provider>`.

- [ ] **Step 1: Create `src/components/legacyRedirects.tsx`**

```tsx
import { Navigate, generatePath, useParams } from 'react-router-dom';

export interface LegacyRedirect {
  from: string;
  to: string;
}

const LEGACY_CONFIG_SLUGS: Record<string, string> = {
  system: 'systems',
  subsystem: 'subsystems',
  environment: 'environments',
  booking: 'bookings',
  'change-request': 'change-requests',
  release: 'releases',
  'release-change': 'release-changes',
  build: 'builds',
  deployment: 'deployments',
  incident: 'incidents',
  'environment-request': 'environment-requests',
};

/**
 * Old path → new path, kept for ONE release so testers' bookmarks don't 404.
 * In-app links were rewritten; nothing in src/ should navigate to a `from`.
 * Remove this file, its routes and its test together.
 */
export const LEGACY_REDIRECTS: LegacyRedirect[] = [
  { from: '/tenant/users', to: '/admin/users' },
  { from: '/tenant/settings', to: '/admin/settings' },
  { from: '/tenant/groups', to: '/admin/user-groups' },
  { from: '/tenant/groups/:id', to: '/admin/user-groups/:id' },
  { from: '/tenant/projects', to: '/projects' },
  { from: '/tenant/projects/:id', to: '/projects/:id' },
  { from: '/tenant/environment-groups', to: '/environment-groups' },
  { from: '/tenant/environment-groups/:id', to: '/environment-groups/:id' },
  { from: '/tenant/api-keys', to: '/admin/api-keys' },
  { from: '/tenant/raid-settings', to: '/admin/releases/raid' },
  { from: '/admin/config/component-types', to: '/admin/component-types' },
  ...Object.entries(LEGACY_CONFIG_SLUGS).map(([slug, entity]) => ({
    from: `/admin/config/${slug}`,
    to: `/admin/${entity}/fields`,
  })),
  { from: '/admin/scope-change-rules', to: '/admin/releases/scope-change-rules' },
  { from: '/admin/release-templates', to: '/admin/releases/templates' },
  { from: '/admin/release-templates/:id', to: '/admin/releases/templates/:id' },
];

export function LegacyRedirect({ to }: { to: string }) {
  const params = useParams();
  return <Navigate replace to={generatePath(to, params)} />;
}
```

- [ ] **Step 2: Rewrite the route tree in `src/App.tsx`**

Update the lazy imports: remove `AdminLayout`; add `AdminHome` (`./pages/admin/AdminHome`) and `ComponentTypesPage` (`./pages/admin/ComponentTypesPage`). Add `Outlet` to the `react-router-dom` import and `import { LEGACY_REDIRECTS, LegacyRedirect } from './components/legacyRedirects'`.

Replace everything between `<Route element={isAuthenticated ? <AppLayout /> : <Navigate to="/login" />}>` and its closing `</Route>` with:

```tsx
<Route path="/dashboard" element={<Dashboard />} />
<Route path="/insights/dora" element={<DoraDashboard />} />
<Route path="/insights/health" element={<HealthDashboard />} />

{/* Catalogue */}
<Route path="/systems" element={<SystemCatalog />} />
<Route path="/systems/:id" element={<SystemDetail />} />
<Route path="/environments" element={<EnvironmentList />} />
<Route path="/environments/compare" element={<EnvironmentCompare />} />
<Route path="/environments/:id" element={<EnvironmentDetail />} />
<Route path="/infrastructure/hosts" element={<InfrastructureComponentList />} />
<Route path="/import" element={<ImportPage />} />

{/* Bookings */}
<Route path="/bookings" element={<Navigate replace to="/bookings/calendar" />} />
<Route path="/bookings/calendar" element={<BookingCalendar />} />
<Route path="/bookings/list" element={<BookingList />} />
<Route path="/bookings/:id" element={<BookingDetail />} />
<Route path="/environment-requests" element={<EnvironmentRequestList />} />
<Route path="/environment-requests/new" element={<EnvironmentRequestForm />} />
<Route path="/environment-requests/:id" element={<EnvironmentRequestDetail />} />
<Route path="/change-requests" element={<ChangeRequestList />} />
<Route path="/change-requests/:id" element={<ChangeRequestDetail />} />
{/* Readable by any tenant member; writes are gated on the page. */}
<Route path="/projects" element={<Projects />} />
<Route path="/projects/:id" element={<ProjectDetail />} />
<Route path="/environment-groups" element={<EnvironmentGroups />} />
<Route path="/environment-groups/:id" element={<EnvironmentGroupDetail />} />
<Route path="/contentions" element={<ContentionEscalations />} />
<Route path="/decommissions" element={<DecommissionWorklist />} />

{/* Releases */}
<Route path="/releases" element={<ReleaseList />} />
<Route path="/releases/new" element={<ReleaseList />} />
<Route path="/releases/calendar" element={<ReleaseCalendar />} />
<Route path="/releases/timeline" element={<ReleaseTimeline />} />
<Route path="/releases/scope-windows" element={<ScopeWindows />} />
<Route path="/releases/analytics" element={<ReleaseAnalytics />} />
<Route path="/releases/:id" element={<ReleaseDetail />} />
<Route path="/builds" element={<BuildList />} />
<Route path="/builds/:id" element={<BuildDetail />} />
<Route path="/deployments" element={<DeploymentList />} />
<Route path="/deployments/:id" element={<DeploymentDetail />} />
<Route path="/incidents" element={<IncidentList />} />
<Route path="/incidents/new" element={<IncidentForm />} />
<Route path="/incidents/:id" element={<IncidentDetail />} />
<Route path="/incidents/:id/edit" element={<IncidentForm />} />
<Route path="/pir-actions" element={<PirActionList />} />

{/* Admin mode: every route under /admin renders inside the admin drawer.
    The gate is per route, not on the layout, because User groups is
    readable by any tenant member (B3a) while everything else is Admin. */}
<Route path="/admin" element={<Outlet />}>
  <Route index element={<PrivateRoute requiredRole="Admin"><AdminHome /></PrivateRoute>} />
  <Route path="users" element={<PrivateRoute requiredRole="Admin"><UserManagement /></PrivateRoute>} />
  <Route path="user-groups" element={<PrivateRoute><UserGroups /></PrivateRoute>} />
  <Route path="user-groups/:id" element={<PrivateRoute><UserGroupDetail /></PrivateRoute>} />
  <Route path="settings" element={<PrivateRoute requiredRole="Admin"><TenantSettings /></PrivateRoute>} />
  <Route path="api-keys" element={<PrivateRoute requiredRole="Admin"><ApiKeyManagement /></PrivateRoute>} />
  <Route path="github" element={<PrivateRoute requiredRole="Admin"><GitHubIntegration /></PrivateRoute>} />
  <Route path="component-types" element={<PrivateRoute requiredRole="Admin"><ComponentTypesPage /></PrivateRoute>} />
  <Route path="releases/templates" element={<PrivateRoute requiredRole="Admin"><ReleaseTemplateLibrary /></PrivateRoute>} />
  <Route path="releases/templates/:id" element={<PrivateRoute requiredRole="Admin"><ReleaseTemplateForm /></PrivateRoute>} />
  <Route path="releases/scope-change-rules" element={<PrivateRoute requiredRole="Admin"><TenantScopeChangeRules /></PrivateRoute>} />
  <Route path="releases/raid" element={<PrivateRoute requiredRole="Admin"><RaidSettings /></PrivateRoute>} />
  <Route path="tenants" element={<PrivateRoute requireMasterAdmin><TenantList /></PrivateRoute>} />
  <Route path="tenants/:tenantId" element={<PrivateRoute requireMasterAdmin><TenantDetail /></PrivateRoute>} />
  {/* Static routes above rank ahead of these params in react-router v6. */}
  <Route path=":entity/:tab" element={<PrivateRoute requiredRole="Admin"><EntityConfig /></PrivateRoute>} />
  <Route path=":entity" element={<PrivateRoute requiredRole="Admin"><EntityConfig /></PrivateRoute>} />
</Route>

{/* One release of bookmark compatibility. */}
{LEGACY_REDIRECTS.map((r) => (
  <Route key={r.from} path={r.from} element={<LegacyRedirect to={r.to} />} />
))}
```

Note `PrivateRoute` already lets a master admin through `requiredRole="Admin"` (`!user.is_master_admin` clause) — that is why the master-only user reaches `/admin` and sees only Platform.

- [ ] **Step 3: Delete `AdminLayout`**

```bash
git rm src/pages/admin/AdminLayout.tsx
npx tsc --noEmit && npm run lint
```
Expected: clean.

- [ ] **Step 4: Create the harness `src/test/renderApp.tsx`**

```tsx
import { render } from '@testing-library/react';
import { Provider } from 'react-redux';
import App from '../App';
import { store } from '../store';
import { setCredentials } from '../store/authSlice';

export interface HarnessUser {
  role: string;
  is_master_admin?: boolean;
}

/**
 * Render the real App (BrowserRouter and all) at `path` as `user`. The
 * singleton store is used deliberately: App's auth bootstrap reads it.
 *
 * Callers must `vi.mock('../services/api')` (and `authService`) so lazy
 * pages that fetch on mount get an empty answer instead of a network call.
 */
export function renderAppAt(path: string, user: HarnessUser) {
  window.history.pushState({}, '', path);
  store.dispatch(
    setCredentials({
      user: {
        id: 1,
        username: 'tester',
        email: 'tester@example.com',
        role: user.role,
        tenant_id: 1,
        is_master_admin: user.is_master_admin ?? false,
      },
      token: 'test-token',
    })
  );
  return render(
    <Provider store={store}>
      <App />
    </Provider>
  );
}
```

- [ ] **Step 5: Write the structural route test**

```tsx
// src/__tests__/navRoutes.test.tsx
import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adminNav } from '../components/adminNavConfig';
import { appNav, isNavGroup } from '../components/navConfig';
import { renderAppAt } from '../test/renderApp';

vi.mock('../services/authService', () => ({
  authService: { getCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn() },
}));
// Every page fetches on mount; answer with nothing so no page crashes and no
// request leaves jsdom. `headers` carries X-Total-Count for paged lists.
vi.mock('../services/api', () => {
  const empty = () => Promise.resolve({ data: [], headers: { 'x-total-count': '0' } });
  return { default: { get: vi.fn(empty), post: vi.fn(empty), put: vi.fn(empty), patch: vi.fn(empty), delete: vi.fn(empty) } };
});

const appPaths = appNav.flatMap((e) => (isNavGroup(e) ? e.children : [e])).map((i) => i.path);
const adminPaths = adminNav.flatMap((s) => s.children).map((c) => c.path);

describe('every nav item resolves to a real route', () => {
  afterEach(() => document.body.replaceChildren());

  it.each(appPaths)('app path %s does not 404', async (path) => {
    renderAppAt(path, { role: 'Admin' });
    await waitFor(() => expect(screen.queryByText(/page not found/i)).not.toBeInTheDocument(), { timeout: 4000 });
    // still on the requested path — no guard bounced us to /dashboard
    expect(window.location.pathname).toBe(path);
  });

  it.each(adminPaths)('admin path %s renders inside the admin shell', async (path) => {
    renderAppAt(path, { role: 'Admin', is_master_admin: true });
    expect(await screen.findByText('Back to EnvManager', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(/page not found/i)).not.toBeInTheDocument();
    expect(window.location.pathname).toBe(path);
  });

  it('a Developer can still open a user group page, inside the admin shell', async () => {
    renderAppAt('/admin/user-groups/3', { role: 'Developer' });
    expect(await screen.findByText('Back to EnvManager', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/admin/user-groups/3');
  });

  it('a Developer is bounced from an Admin-only admin page', async () => {
    renderAppAt('/admin/users', { role: 'Developer' });
    await waitFor(() => expect(window.location.pathname).toBe('/dashboard'));
  });
});
```

Check the exact text `NotFound.tsx` renders and use it in the regex if it is not "page not found".

- [ ] **Step 6: Write the redirect test**

```tsx
// src/__tests__/legacyRedirects.test.tsx
import { waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LEGACY_REDIRECTS } from '../components/legacyRedirects';
import { renderAppAt } from '../test/renderApp';

vi.mock('../services/authService', () => ({
  authService: { getCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn() },
}));
vi.mock('../services/api', () => {
  const empty = () => Promise.resolve({ data: [], headers: { 'x-total-count': '0' } });
  return { default: { get: vi.fn(empty), post: vi.fn(empty), put: vi.fn(empty), patch: vi.fn(empty), delete: vi.fn(empty) } };
});

const fill = (pattern: string) => pattern.replace(/:[a-zA-Z]+/g, '42');

describe('legacy paths redirect', () => {
  afterEach(() => document.body.replaceChildren());

  it.each(LEGACY_REDIRECTS.map((r) => [r.from, r.to]))('%s → %s', async (from, to) => {
    renderAppAt(fill(from), { role: 'Admin', is_master_admin: true });
    await waitFor(() => expect(window.location.pathname).toBe(fill(to)), { timeout: 4000 });
  });

  it('no source file navigates to a legacy path', () => {
    const files = import.meta.glob('../**/*.tsx', { as: 'raw', eager: true }) as Record<string, string>;
    const offenders: string[] = [];
    for (const [file, src] of Object.entries(files)) {
      if (file.includes('__tests__') || file.includes('legacyRedirects')) continue;
      for (const r of LEGACY_REDIRECTS) {
        const literal = r.from.replace(/\/:[a-zA-Z]+/g, '');
        if (src.includes(`'${literal}'`) || src.includes(`\`${literal}/`)) offenders.push(`${file}: ${literal}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
```

The last test is deliberately literal-based; `services/*.ts` are `.ts` and excluded by the `*.tsx` glob, so API paths like `/tenant/groups` in services are not flagged. Comments mentioning an old path are not flagged either — only quoted literals match.

- [ ] **Step 7: `appCodeSplitting.test.tsx`**

It reads `lazy()` calls from `App.tsx?raw`; the moved pages keep the same regex shape, so it should pass unchanged. Run it: `npx vitest run src/__tests__/appCodeSplitting.test.tsx`.

- [ ] **Step 8: Run the new tests**

Run: `npx vitest run src/__tests__/ && npx tsc --noEmit && npm run lint`
Expected: all pass. If an individual admin page throws on `data: []` (e.g. expects an object), extend the `api` mock in **both** test files to return `{}` for that page's URL — `vi.fn((url: string) => url.includes('/tenant/settings') ? Promise.resolve({ data: {}, headers: {} }) : empty())` — and note it in the PR: a page that cannot render on an empty answer is a page bug worth recording, not something to hide.

- [ ] **Step 9: Commit**

```bash
git add src/App.tsx src/components/legacyRedirects.tsx src/test/renderApp.tsx src/__tests__/
git commit -m "feat(routes): all admin routes under /admin in one shell; legacy redirects; AdminLayout removed"
```

---

### Task 9: Tenant settings tidy

**Files:**
- Modify: `src/pages/admin/TenantSettings.tsx`
- Test: `src/pages/admin/__tests__/tenantSettings.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/pages/admin/__tests__/tenantSettings.test.tsx
import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import TenantSettings from '../TenantSettings';
import tenantAdminReducer from '../../../store/tenantAdminSlice';
import { tenantAdminService } from '../../../services/tenantAdminService';

vi.mock('../../../services/tenantAdminService', () => ({
  tenantAdminService: { getSettings: vi.fn(), updateSettings: vi.fn() },
}));

describe('TenantSettings', () => {
  it('shows name and slug read-only, with the JSON editor collapsed under Advanced', async () => {
    vi.mocked(tenantAdminService.getSettings).mockResolvedValue({
      id: 1, name: 'Demo Org', slug: 'demo', settings: { flag: true },
    } as never);
    render(
      <Provider store={configureStore({ reducer: { tenantAdmin: tenantAdminReducer } })}>
        <TenantSettings />
      </Provider>
    );
    expect(await screen.findByLabelText('Name')).toHaveValue('Demo Org');
    expect(screen.getByLabelText('Name')).toHaveAttribute('readonly');
    expect(screen.getByLabelText('Slug')).toHaveValue('demo');
    expect(screen.queryByLabelText('Custom settings (JSON)')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /advanced/i }));
    expect(screen.getByLabelText('Custom settings (JSON)')).toHaveValue(JSON.stringify({ flag: true }, null, 2));
  });

  it('still saves the JSON document', async () => {
    vi.mocked(tenantAdminService.getSettings).mockResolvedValue({ id: 1, name: 'D', slug: 'd', settings: {} } as never);
    vi.mocked(tenantAdminService.updateSettings).mockResolvedValue({ id: 1, name: 'D', slug: 'd', settings: { a: 1 } } as never);
    render(
      <Provider store={configureStore({ reducer: { tenantAdmin: tenantAdminReducer } })}>
        <TenantSettings />
      </Provider>
    );
    await screen.findByLabelText('Name');
    await userEvent.click(screen.getByRole('button', { name: /advanced/i }));
    const editor = screen.getByLabelText('Custom settings (JSON)');
    await userEvent.clear(editor);
    await userEvent.type(editor, '{{"a": 1}');
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(tenantAdminService.updateSettings).toHaveBeenCalledWith({ a: 1 });
    expect(await screen.findByText('Settings saved')).toBeInTheDocument();
  });
});
```

Check `tenantAdminSlice`'s `updateTenantSettings` thunk calls `tenantAdminService.updateSettings(parsed)` with the object alone; if it passes something else, match the assertion to the real call shape.

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/pages/admin/__tests__/tenantSettings.test.tsx`
Expected: FAIL — no `Name` label, no Advanced accordion.

- [ ] **Step 3: Rewrite the JSX in `src/pages/admin/TenantSettings.tsx`**

Keep the state and `handleSave` as they are; replace the `return (...)` with:

```tsx
return (
  <Box sx={{ p: 3 }}>
    <Typography variant="h5" gutterBottom>
      Tenant settings
    </Typography>
    {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
    {saved && <Alert severity="success" sx={{ mb: 2 }}>Settings saved</Alert>}

    {loading && !settings ? (
      <CircularProgress />
    ) : (
      <>
        <Paper sx={{ p: 3, mb: 2 }}>
          <Stack spacing={2} sx={{ maxWidth: 480 }}>
            <TextField
              label="Name"
              value={settings?.name ?? ''}
              InputProps={{ readOnly: true }}
              helperText="Set when the tenant was provisioned; a master admin can change it under Platform → Tenants."
            />
            <TextField label="Slug" value={settings?.slug ?? ''} InputProps={{ readOnly: true }} />
          </Stack>
        </Paper>

        <Accordion variant="outlined" disableGutters>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography>Advanced</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              A free-form JSON document downstream features may read. Nothing on this page changes billing, identity or routing.
            </Typography>
            {jsonError && <Alert severity="error" sx={{ mb: 2 }}>{jsonError}</Alert>}
            <TextField
              label="Custom settings (JSON)"
              multiline
              fullWidth
              minRows={10}
              value={settingsJson}
              onChange={(e) => setSettingsJson(e.target.value)}
              inputProps={{ style: { fontFamily: 'monospace', fontSize: '14px' } }}
            />
            <Box sx={{ mt: 2 }}>
              <Button variant="contained" onClick={handleSave} disabled={loading}>
                Save settings
              </Button>
            </Box>
          </AccordionDetails>
        </Accordion>
      </>
    )}
  </Box>
);
```

Add to the MUI import: `Accordion, AccordionDetails, AccordionSummary, Stack`; add `import ExpandMoreIcon from '@mui/icons-material/ExpandMore'`.

- [ ] **Step 4: Run, type-check, commit**

Run: `npx vitest run src/pages/admin/__tests__/tenantSettings.test.tsx && npx tsc --noEmit && npm run lint`

```bash
git add src/pages/admin/TenantSettings.tsx src/pages/admin/__tests__/tenantSettings.test.tsx
git commit -m "feat(admin): tenant settings shows name/slug read-only; JSON editor under Advanced"
```

---

### Task 10: Docs

**Files:**
- Modify: `docs/user-guide.md` (§2 "The left navigation", "The top bar"), `docs/admin-guide.md` (nav table at ~150–167 and every `Administration → …` / old-path mention in the table below), `docs/ui-audit.md` (status column).

- [ ] **Step 1: Rewrite user-guide §2 "The left navigation"**

Replace the table and the sentence after it with:

```markdown
### The left navigation

The sidebar is the same for every authenticated user. *Dashboard* is a single entry; *Catalogue*, *Bookings*, *Releases* and *Insights* are collapsible groups (the sidebar remembers which you have collapsed, and opens a group automatically when you navigate into it). Admins and master admins also see *Administration*, which switches the sidebar into admin mode — see the admin guide.

| Group → entry | Route | What's there | Covered in |
|---|---|---|---|
| *Dashboard* | `/dashboard` | Landing page. | this chapter |
| *Catalogue → Systems* | `/systems` | System and subsystem catalogue. | [ch. 4](#4-browsing-systems-and-environments) |
| *Catalogue → Environments* | `/environments` | Environment inventory and detail. | [ch. 4](#4-browsing-systems-and-environments) |
| *Catalogue → Hosts* | `/infrastructure/hosts` | Infrastructure host inventory. | [`admin-guide.md` ch. 8](admin-guide.md#7-modelling-infrastructure-hosts) |
| *Catalogue → Compare environments* | `/environments/compare` | Side-by-side diff of two environments. | [ch. 4](#4-browsing-systems-and-environments) |
| *Catalogue → Import* | `/import` | Bulk Excel import (Admin write — readable nav for everyone). | [`admin-guide.md` ch. 12](admin-guide.md#12-importexport) |
| *Bookings → Calendar* | `/bookings/calendar` | Calendar view of reservations. | [ch. 5](#5-booking-environments) |
| *Bookings → List* | `/bookings/list` | Tabular view of reservations. | [ch. 5](#5-booking-environments) |
| *Bookings → Environment requests* | `/environment-requests` | Request access to an environment, or a new one. | [ch. 6](#6-requesting-environments) |
| *Bookings → Change requests* | `/change-requests` | Change-request inbox. | [ch. 7](#7-raising-change-requests) |
| *Bookings → Projects* | `/projects` | Projects, their teams, priority rank and usage agreements. | [ch. 5](#5-booking-environments) |
| *Bookings → Environment groups* | `/environment-groups` | Named sets of environments bookable as one unit. | [ch. 5](#5-booking-environments) |
| *Bookings → Contentions* | `/contentions` | Contention escalations worklist. | [ch. 5](#5-booking-environments) |
| *Bookings → Decommissions* | `/decommissions` | Decommission worklist. | [ch. 4](#4-browsing-systems-and-environments) |
| *Releases → Releases* | `/releases` | Release inventory. | [ch. 8](#8-working-with-releases) |
| *Releases → Calendar / Timeline / Scope windows / Analytics* | `/releases/…` | The other release views. | [ch. 8](#8-working-with-releases) |
| *Releases → Builds* | `/builds` | CI build feed per subsystem. | [ch. 9](#9-builds-and-deployments) |
| *Releases → Deployments* | `/deployments` | Deployment feed per environment. | [ch. 9](#9-builds-and-deployments) |
| *Releases → Incidents* | `/incidents` | Incident register. | ch. 10 |
| *Releases → PIR actions* | `/pir-actions` | Post-implementation-review action worklist. | [ch. 8](#8-working-with-releases) |
| *Insights → DORA metrics* | `/insights/dora` | DORA four-key dashboard. | ch. 11 |
| *Insights → Environment health* | `/insights/health` | Health dashboard. | ch. 11 |
```

Check each "Covered in" anchor against the guide's actual heading ids (`grep -n "^## " docs/user-guide.md`) and fix any that don't exist. Update the top-bar paragraph to "the EnvManager logo (a link back to the dashboard)". Then grep the user guide for `Environment Management →`, `Release Management →` and `Environment Definition` and rewrite each to the new group name (`Bookings →`, `Releases →`, `Catalogue →`).

- [ ] **Step 2: Rewrite the admin-guide nav table and path mentions**

Replace the nav table at ~150–167 with the user-guide table plus one extra row:

```markdown
| *Administration* (Admin / master admin) | `/admin` | Admin mode: a hub page and its own sidebar — Organisation, Environments, Bookings, Releases, Delivery, Integrations, Platform. Click *Back to EnvManager* to leave. | ch. 3–12 |
```

Then apply these replacements throughout `docs/admin-guide.md` (`grep -n` each first):

| Old text / path | New |
|---|---|
| `/tenant/users` | `/admin/users` (*Administration → Organisation → Users*) |
| `/tenant/groups` | `/admin/user-groups` |
| `/tenant/projects` | `/projects` (*Bookings → Projects*) |
| `/tenant/environment-groups` | `/environment-groups` (*Bookings → Environment groups*) |
| `/tenant/api-keys`, "left nav: *API keys*" | `/admin/api-keys` (*Administration → Integrations → API keys*) |
| `/tenant/settings` | `/admin/settings` |
| `/admin/config/environment-request` | `/admin/environment-requests/lifecycle` |
| `/admin/config/release`, tab *Gate Types* | `/admin/releases/gate-types` |
| `/admin/scope-change-rules` | `/admin/releases/scope-change-rules` |
| `/admin/release-templates` (+`/new`, `/:id`) | `/admin/releases/templates` (+`/new`, `/:id`) |
| `/tenant/booking-types` (line ~937; this UI path never existed) | `/admin/bookings/types` |
| *Administration → User Groups* | *Administration → Organisation → User groups* |
| *Tenant Settings → Entity Config* | *Administration → Environments → Custom fields* |
| *Administration → Entity Config → Environments → …* | *Administration → Environments → …* |
| *Administration → Booking Types* | *Administration → Bookings → Booking types* |
| *Administration → Projects* | *Bookings → Projects* |
| *Admin → Release Templates* | *Administration → Releases → Templates* |

*Administration → Environments → Tiers* keeps its wording — it is now literally true. Add one sentence to ch. 11 (Tenant settings): "The JSON document sits under *Advanced*, collapsed by default."

- [ ] **Step 3: Add a status column to `docs/ui-audit.md`**

Add a `Status` column to the P2 and P3 tables. Mark: P2-9 → `Closed — PR 1 (admin mode)`; P3-4 → `Closed — PR 1`; P3-6 → `Closed — PR 1 (title link; calendar cells remain)`; every other row → `Open`. Add a one-line note above the P2 table: "Status as of 2026-09-02; the open structural items are PRs 2–4 of `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md`."

- [ ] **Step 4: Commit**

```bash
git add docs/user-guide.md docs/admin-guide.md docs/ui-audit.md
git commit -m "docs: navigation and admin-mode paths in the user and admin guides; audit status column"
```

---

### Task 11: Whole-suite verification and browser pass

- [ ] **Step 1: The full frontend gate — whole suite, not targeted files**

```bash
npx tsc --noEmit && npm run lint && npx vitest run && npm run build
```
Expected: all green. If an existing test asserts an old label (`grep -rn "Environment Management\|Release Management\|Environment Definition\|Release Templates\|Tenant Settings" src --include='*.test.tsx'`), update the assertion to the new label — those are label pins, not behaviour.

- [ ] **Step 2: Backend untouched — prove it**

```bash
git diff --stat main -- ../backend
```
Expected: empty. This PR changes no backend file.

- [ ] **Step 3: Browser pass** (dev server: `npm run dev`; login `admin`/`admin123`, tenant `demo`)

Record each in the PR description as done / defect found:

1. `/dashboard`: drawer shows Dashboard, Catalogue, Bookings, Releases, Insights, Administration; no label wraps at 240 px; collapse *Releases*, reload — still collapsed; open a release from the list — *Releases* reopens and the item is selected.
2. Click *Administration*: drawer swaps in place (no second column), *Back to EnvManager* at top, six sections for Admin; `/admin` hub lists every section's items with descriptions.
3. Click *Naming policy*: URL `/admin/environments/naming-policy`, that tab selected; click the *Tiers* tab → URL changes; reload → same tab.
4. *Back to EnvManager* returns to the page you came from.
5. Open each of: Users, User groups (and a group), Tenant settings (Advanced accordion; save round-trips), Booking types, Templates (open one, save, back), Scope-change rules, RAID settings, API keys, GitHub, Component types, Environment request fields — every one keeps the admin drawer.
6. Sign in as `masteradmin`/`masteradmin123` (tenant `system`): *Administration* → only Platform → Tenants.
7. Paste each old path from `LEGACY_REDIRECTS` (one param path with a real id) — lands on the new path.
8. Resize to 1024 px wide: drawer still permanent, admin drawer scrolls, nothing overlaps.
9. Below 900 px: hamburger opens the temporary drawer in both modes; choosing an item closes it.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u github feature/ia-admin-mode
gh pr create --title "feat(ui): one navigation, admin mode, /admin routes with legacy redirects (PR 1 of the IA programme)" --body "$(cat <<'PRBODY'
Implements sections 3 and 4 of docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md.

- Main drawer: Dashboard · Catalogue · Bookings · Releases · Insights · Administration; sentence-case labels; group opens on navigation; collapsed state persisted.
- Admin mode: one drawer swapped in place, sectioned from `adminNavConfig`; `/admin` hub generated from it; every admin route under `/admin/*`; `AdminLayout` deleted.
- `EntityConfig` on `/admin/:entity/:tab`, driven by `ENTITY_CONFIG_PAGES`.
- Projects and Environment groups moved to the app nav (`/projects`, `/environment-groups`); no permission changed.
- `LEGACY_REDIRECTS` for every old path, one release.
- Docs: user guide §2, admin guide paths, ui-audit status column.

Browser pass: <fill in from Task 11 step 3>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01J1FuNvkPgvc2F9iK7K1Hfq
PRBODY
)"
```

---

## Self-review against the spec

- §3 main nav table → Task 2; behaviour bullets (open on navigation, persisted state, prefix match, title link, `md` drawer) → Tasks 1, 4. *My work* deliberately absent (PR 3) — stated in the constraints.
- §4.1 shell → Task 4. §4.2 menu → Task 3 (every row present; Delivery items point at each entity's first tab, matching the spec's `{fields,lifecycle}` notation). §4.3 entity pages → Task 5. §4.4 hub → Task 6. §4.5 routes and redirect table → Task 8 (all rows plus the 11 config slugs; `/admin/github` and `/admin/tenants` unchanged). §4.6 tenant settings → Task 9.
- §9 tests: shell-per-admin-route, nav-item-resolves, redirects, open-on-navigation (re-render, not mount), master-only sees Platform → Tasks 4 and 8. §10 docs → Task 10.
- One deviation from the spec, recorded: the `/admin` gate is **per route**, not on the layout, so *User groups* stays readable by any member (spec §2: "moves no permissions"). The admin drawer for such a user shows the Back link and Organisation → User groups only.
- Type consistency checked: `NavEntry`/`NavGroup`/`NavItem`, `visibleAppNav`, `visibleAdminNav`, `entityTabPath`, `groupContaining`, `setNavGroupOpen({ key, open })`, `LEGACY_REDIRECTS`, `renderAppAt(path, { role, is_master_admin })` are used with the same names and shapes in every task.
