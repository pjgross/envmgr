# Navigation Menu Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat sidebar in `AppLayout.tsx` with five workflow-lifecycle groups (Insights, Environment Definition, Environment Management, Release Management, Administration), driven by a declarative, unit-tested nav config.

**Architecture:** Extract the nav data structure and role-filtering into a new pure module `navConfig.tsx` (easy to unit-test with no rendering). `AppLayout.tsx` consumes `visibleNavGroups(user)` and renders each group with the existing MUI `Collapse` pattern. No routes, pages, or backend change. All existing URLs are preserved.

**Tech Stack:** React 18 + TypeScript (strict, `noUnusedLocals`), MUI, Redux Toolkit, Vitest + React Testing Library.

**Design spec:** `docs/superpowers/specs/2026-07-23-nav-menu-grouping-design.md`

---

## File Structure

- **Create** `frontend/src/components/navConfig.tsx` — `NavItem` type, `NavUser` type, `navGroups` data (the 5 groups), `userSatisfies()` predicate, and `visibleNavGroups(user)` pure filter. Owns *what* appears and *who* sees it.
- **Create** `frontend/src/components/__tests__/navConfig.test.tsx` — unit tests for `visibleNavGroups` across roles.
- **Modify** `frontend/src/components/AppLayout.tsx` — consume `visibleNavGroups`; default-open logic; `comingSoon` support inside group children; remove the standalone Admin block (lines ~327–338); shrink the avatar dropdown to Theme + Logout (remove lines ~202–218); remove now-unused icon imports.

### Role model (important correctness detail)

Current behavior gates two things **independently**: Platform Admin shows when `is_master_admin === true`; the tenant-admin items show when `role === 'Admin'`. A master admin is not necessarily `role === 'Admin'`. To preserve this, the **Administration group carries no `requires`** — it is shown whenever it has ≥1 visible child. Each child carries its own `requires`. So a master-admin-only user still sees Administration containing just Platform Admin.

`Release Templates` gains `requires: 'admin'` (today it renders for everyone but the route `/admin/release-templates` is Admin-gated, so non-admins hit a block — gating the link is an improvement).

---

### Task 1: Create the nav config module (pure, TDD)

**Files:**
- Create: `frontend/src/components/navConfig.tsx`
- Test: `frontend/src/components/__tests__/navConfig.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/navConfig.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { visibleNavGroups, type NavUser } from '../navConfig';

const regular: NavUser = { role: 'User', is_master_admin: false };
const admin: NavUser = { role: 'Admin', is_master_admin: false };
const masterOnly: NavUser = { role: 'User', is_master_admin: true };

const labels = (user: NavUser) => visibleNavGroups(user).map((g) => g.label);
const childLabels = (user: NavUser, group: string) =>
  visibleNavGroups(user).find((g) => g.label === group)?.children?.map((c) => c.label) ?? [];

describe('visibleNavGroups', () => {
  it('shows the four workflow groups to a regular user, no Administration', () => {
    expect(labels(regular)).toEqual([
      'Insights',
      'Environment Definition',
      'Environment Management',
      'Release Management',
    ]);
  });

  it('hides Release Templates from a regular user', () => {
    expect(childLabels(regular, 'Release Management')).not.toContain('Release Templates');
  });

  it('shows Administration (without Platform Admin) to an Admin, plus Release Templates', () => {
    expect(labels(admin)).toContain('Administration');
    expect(childLabels(admin, 'Release Management')).toContain('Release Templates');
    const adminChildren = childLabels(admin, 'Administration');
    expect(adminChildren).toContain('Users');
    expect(adminChildren).toContain('API Keys');
    expect(adminChildren).not.toContain('Platform Admin');
  });

  it('shows Administration with only Platform Admin to a master-admin who is not role Admin', () => {
    expect(childLabels(masterOnly, 'Administration')).toEqual(['Platform Admin']);
  });

  it('marks Insights as default-open', () => {
    const insights = visibleNavGroups(regular).find((g) => g.label === 'Insights');
    expect(insights?.defaultOpen).toBe(true);
  });

  it('handles a null user by showing only non-privileged groups', () => {
    expect(visibleNavGroups(null).map((g) => g.label)).not.toContain('Administration');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/navConfig.test.tsx`
Expected: FAIL — cannot resolve `../navConfig`.

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/navConfig.tsx`:

```tsx
import type { ReactNode } from 'react';
import DashboardIcon from '@mui/icons-material/Dashboard';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ComputerIcon from '@mui/icons-material/Computer';
import StorageIcon from '@mui/icons-material/Storage';
import UploadIcon from '@mui/icons-material/Upload';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth';
import ListIcon from '@mui/icons-material/List';
import BuildIcon from '@mui/icons-material/Build';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import TimelineIcon from '@mui/icons-material/Timeline';
import LibraryBooksIcon from '@mui/icons-material/LibraryBooks';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts';
import SettingsIcon from '@mui/icons-material/Settings';
import TuneIcon from '@mui/icons-material/Tune';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import VpnKeyIcon from '@mui/icons-material/VpnKey';

/** Minimal user shape the nav needs — decoupled from the store's User type. */
export interface NavUser {
  role?: string;
  is_master_admin?: boolean;
}

export type NavRole = 'admin' | 'masterAdmin';

export interface NavItem {
  label: string;
  path?: string; // group headers have no path
  icon: ReactNode;
  comingSoon?: boolean;
  requires?: NavRole;
  defaultOpen?: boolean; // group starts expanded
  children?: NavItem[];
}

/** The full, unfiltered menu. Order here is the render order. */
export const navGroups: NavItem[] = [
  {
    label: 'Insights',
    icon: <QueryStatsIcon />,
    defaultOpen: true,
    children: [
      { label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon /> },
      { label: 'DORA Metrics', path: '/insights/dora', icon: <QueryStatsIcon />, comingSoon: true },
    ],
  },
  {
    label: 'Environment Definition',
    icon: <AccountTreeIcon />,
    children: [
      { label: 'Systems', path: '/systems', icon: <AccountTreeIcon /> },
      { label: 'Environments', path: '/environments', icon: <ComputerIcon /> },
      { label: 'Hosts', path: '/infrastructure/hosts', icon: <StorageIcon /> },
      { label: 'Import', path: '/import', icon: <UploadIcon /> },
    ],
  },
  {
    label: 'Environment Management',
    icon: <EventAvailableIcon />,
    children: [
      { label: 'Bookings — Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
      { label: 'Bookings — List', path: '/bookings/list', icon: <ListIcon /> },
      { label: 'Change Requests', path: '/change-requests', icon: <BuildIcon /> },
    ],
  },
  {
    label: 'Release Management',
    icon: <RocketLaunchIcon />,
    children: [
      { label: 'Releases — List', path: '/releases', icon: <ListIcon /> },
      { label: 'Releases — Calendar', path: '/releases/calendar', icon: <CalendarMonthIcon /> },
      { label: 'Releases — Timeline', path: '/releases/timeline', icon: <TimelineIcon /> },
      {
        label: 'Release Templates',
        path: '/admin/release-templates',
        icon: <LibraryBooksIcon />,
        requires: 'admin',
      },
      { label: 'Builds', path: '/builds', icon: <BuildIcon /> },
      { label: 'Deployments', path: '/deployments', icon: <RocketLaunchIcon /> },
    ],
  },
  {
    label: 'Administration',
    icon: <AdminPanelSettingsIcon />,
    // No `requires` — visible whenever it has >=1 visible child, so a
    // master-admin who is not role 'Admin' still sees Platform Admin.
    children: [
      { label: 'Users', path: '/tenant/users', icon: <ManageAccountsIcon />, requires: 'admin' },
      { label: 'Tenant Settings', path: '/tenant/settings', icon: <SettingsIcon />, requires: 'admin' },
      { label: 'Change Config', path: '/admin/config/booking', icon: <TuneIcon />, requires: 'admin' },
      { label: 'RAID Settings', path: '/tenant/raid-settings', icon: <WarningAmberIcon />, requires: 'admin' },
      { label: 'API Keys', path: '/tenant/api-keys', icon: <VpnKeyIcon />, requires: 'admin' },
      { label: 'Platform Admin', path: '/admin/tenants', icon: <AdminPanelSettingsIcon />, requires: 'masterAdmin' },
    ],
  },
];

export function userSatisfies(user: NavUser | null, requires?: NavRole): boolean {
  if (!requires) return true;
  if (requires === 'admin') return user?.role === 'Admin';
  return user?.is_master_admin === true;
}

/** Filter groups + children by role. Drops any group left with no children. */
export function visibleNavGroups(user: NavUser | null): NavItem[] {
  return navGroups
    .map((group) => ({
      ...group,
      children: (group.children ?? []).filter((child) => userSatisfies(user, child.requires)),
    }))
    .filter((group) => userSatisfies(user, group.requires) && group.children.length > 0);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/navConfig.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/navConfig.tsx frontend/src/components/__tests__/navConfig.test.tsx
git commit -m "feat(ui): declarative nav config with role filtering"
```

---

### Task 2: Wire AppLayout to the grouped nav

**Files:**
- Modify: `frontend/src/components/AppLayout.tsx`

- [ ] **Step 1: Replace the inline `navItems` and its imports**

Delete the local `NavItem` interface (lines ~54–60) and the `navItems` array (lines ~62–89). Replace with an import near the other local imports (after the `ErrorFallback` import, line ~50):

```tsx
import { visibleNavGroups, type NavItem } from './navConfig';
```

- [ ] **Step 2: Compute visible groups and fix the default-open initializer**

Replace the `groupOpen` initializer (lines ~101–111) with:

```tsx
  const navGroups = visibleNavGroups(user);
  const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const group of navGroups) {
      initial[group.label] =
        group.defaultOpen === true ||
        (group.children ?? []).some(
          (child) => child.path !== undefined && location.pathname.startsWith(child.path)
        );
    }
    return initial;
  });
```

- [ ] **Step 3: Render groups (with `comingSoon` child support) and drop the standalone Admin block**

Replace the entire `<List dense> … </List>` block (lines ~252–339) with:

```tsx
          <List dense>
            {navGroups.map((group) => {
              const isOpen = groupOpen[group.label] ?? false;
              return (
                <div key={group.label}>
                  <ListItemButton
                    selected={false}
                    onClick={() =>
                      setGroupOpen((prev) => ({ ...prev, [group.label]: !prev[group.label] }))
                    }
                    sx={{ borderRadius: 1, mx: 1, mb: 0.5 }}
                  >
                    <ListItemIcon sx={{ minWidth: 36 }}>{group.icon}</ListItemIcon>
                    <ListItemText primary={group.label} />
                    {isOpen ? (
                      <ExpandLessIcon fontSize="small" />
                    ) : (
                      <ExpandMoreIcon fontSize="small" />
                    )}
                  </ListItemButton>
                  <Collapse in={isOpen} timeout="auto" unmountOnExit>
                    <List dense disablePadding>
                      {(group.children ?? []).map((child: NavItem) => {
                        const isChildActive =
                          child.path !== undefined &&
                          (location.pathname === child.path ||
                            location.pathname.startsWith(child.path + '/'));
                        return (
                          <Tooltip
                            key={child.label}
                            title={child.comingSoon ? 'Coming soon' : ''}
                            placement="right"
                          >
                            <span>
                              <ListItemButton
                                selected={isChildActive}
                                disabled={child.comingSoon}
                                onClick={() =>
                                  !child.comingSoon && child.path && navigateAndClose(child.path)
                                }
                                sx={{ borderRadius: 1, mx: 1, mb: 0.5, pl: 4 }}
                              >
                                <ListItemIcon sx={{ minWidth: 36 }}>{child.icon}</ListItemIcon>
                                <ListItemText primary={child.label} />
                                {child.comingSoon && (
                                  <Chip label="Soon" size="small" sx={{ height: 18, fontSize: 10 }} />
                                )}
                              </ListItemButton>
                            </span>
                          </Tooltip>
                        );
                      })}
                    </List>
                  </Collapse>
                </div>
              );
            })}
          </List>
```

- [ ] **Step 4: Typecheck (catches unused imports under `noUnusedLocals`)**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors listing unused icon imports now only referenced in `navConfig.tsx` (e.g. `DashboardIcon`, `ComputerIcon`, `AccountTreeIcon`, `EventAvailableIcon`, `UploadIcon`, `CalendarMonthIcon`, `ListIcon`, `BuildIcon`, `StorageIcon`, `RocketLaunchIcon`, `TimelineIcon`, `LibraryBooksIcon`). Note the exact list from the output — Step 5 removes them.

- [ ] **Step 5: Remove the now-unused icon imports from AppLayout**

Delete each import line flagged in Step 4 from the import block (lines ~30–41). Keep icons still used directly in `AppLayout.tsx`: `MenuIcon`, `LogoutIcon`, the three theme icons (`Brightness4Icon`, `Brightness7Icon`, `SettingsBrightnessIcon`), and `ExpandLessIcon`/`ExpandMoreIcon`. **Do not remove `AdminPanelSettingsIcon` and `ManageAccountsIcon` yet** — they are still used by the avatar dropdown until Task 3.

- [ ] **Step 6: Re-run typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS (no errors).

- [ ] **Step 7: Run the full test suite**

Run: `cd frontend && npx vitest run`
Expected: PASS (existing tests + navConfig tests).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/AppLayout.tsx
git commit -m "feat(ui): render sidebar as workflow-lifecycle groups"
```

---

### Task 3: Shrink the avatar dropdown to Theme + Logout

The Platform Admin and Tenant Admin links now live in the Administration group, so remove them from the avatar menu.

**Files:**
- Modify: `frontend/src/components/AppLayout.tsx`

- [ ] **Step 1: Remove the two admin MenuItems and their conditional Divider**

Delete the `is_master_admin` Platform Admin `MenuItem` (lines ~202–209), the `role === 'Admin'` Tenant Admin `MenuItem` (lines ~210–217), and the `{(user?.is_master_admin || user?.role === 'Admin') && <Divider />}` line (line ~218). The dropdown should now contain: the user-info `Box`, a `Divider`, the theme-toggle `MenuItem`, a `Divider`, and the Logout `MenuItem`.

- [ ] **Step 2: Remove the now-unused `handleMenuNav`, `AdminPanelSettingsIcon`, and `ManageAccountsIcon`**

`handleMenuNav` (lines ~128–131) is no longer referenced — delete it. Delete the `AdminPanelSettingsIcon` and `ManageAccountsIcon` import lines. If `tsc` reports `ManageAccountsIcon`/`AdminPanelSettingsIcon` as still-used, keep them — but they should be unused now.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS (no unused-local errors).

- [ ] **Step 4: Build to confirm production compile**

Run: `cd frontend && npm run build`
Expected: build succeeds (tsc + vite).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AppLayout.tsx
git commit -m "refactor(ui): slim avatar menu to theme + logout"
```

---

### Task 4: Manual verification

Full-shell render tests (Redux store + router + media-query mocks) are high-cost/low-value for this mechanical wiring; the design's testing section specifies manual verification for the rendered nav. The pure role logic is covered by Task 1's unit tests.

- [ ] **Step 1: Start the app**

Run: `cd frontend && npm run dev` (backend + docker per CLAUDE.md if not already up). Log in as `admin` / `admin123` (tenant `demo`).

- [ ] **Step 2: Verify group structure and behavior**

Confirm:
- Five groups appear: Insights, Environment Definition, Environment Management, Release Management, Administration.
- Insights is expanded on load; Dashboard is visible without a click; DORA Metrics is disabled with a "Soon" chip.
- Each group expands/collapses on header click.
- Navigating directly to `/releases/timeline` (paste in address bar + refresh) auto-expands Release Management and highlights Timeline.
- Every child links to a working page (spot-check Systems, Import, Change Requests, Builds, Deployments, API Keys).
- Avatar dropdown shows only Theme toggle + Logout.

- [ ] **Step 3: Verify role gating**

- As a **regular (non-admin) user**: only the top four groups appear; no Administration group; no Release Templates row under Release Management.
- As **Admin**: Administration shows Users / Tenant Settings / Change Config / RAID Settings / API Keys (no Platform Admin); Release Templates appears under Release Management.
- As **Master Admin** (`masteradmin` / `masteradmin123`, tenant `system`): Administration shows Platform Admin.

- [ ] **Step 4 (optional): open a PR**

```bash
gh pr create --repo github.com/pjgross/envmgr --base main \
  --title "feat(ui): group sidebar navigation by workflow lifecycle" \
  --body "Implements docs/superpowers/specs/2026-07-23-nav-menu-grouping-design.md"
```

---

## Notes / Known Limitations

- **Sibling highlight on shared prefixes** (pre-existing): on `/releases/calendar`, the `Releases — List` row (path `/releases`) also highlights because `/releases/calendar` starts with `/releases/`. This matches the current app's behavior and is out of scope for this change; fix separately if desired.
- **DORA Metrics** is a disabled placeholder (no route). When Phase 5 lands the page, remove `comingSoon` and point `path` at the real route.
- **URLs unchanged** — Release Templates still lives at `/admin/release-templates`; only its menu placement moved.
