# PR 2 — Page shell, URL tabs & breadcrumbs: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every page one header, one breadcrumb trail and a real `document.title`, and make every tabbed page address its tab through `?tab=<key>` so a tab can be linked to and survives a reload.

**Architecture:** Two presentational components (`PageHeader`, `DetailPageHeader`) that every list/admin and every `*Detail` page composes through. One static `routeMeta` table maps path pattern → `{ label, parent }` and drives both breadcrumbs and `document.title`; a page passes its entity's name to `usePageTitle` rather than putting fetched state in the table. One `useUrlTab(keys, defaultKey, param?)` hook replaces numeric tab indices on all five tabbed surfaces, including the admin entity-config pages, which stop taking the tab from a route segment.

**Tech Stack:** React 18, TypeScript (strict), MUI 5, react-router-dom v6, Redux Toolkit, Vitest + Testing Library (jsdom).

**Spec:** `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md` — §6, plus the §9 bullets for `useUrlTab`, the one-mechanism sweep and the segment redirect. Read §6 in full before Task 1; it was amended 2026-09-03 and the amendments are the parts most likely to be got wrong.

## Global Constraints

- **THE TAB IS A QUERY PARAM, EVERYWHERE.** No route pattern may end in `:tab`. `/admin/:entity/:tab` survives only as a `<Navigate replace>` to `/admin/:entity?tab=<tab>`. This is the whole point of the PR's riskiest task; §6 and §11 explain why keeping both was rejected.
- **`routeMeta` is static.** It never holds fetched state. A dynamic name reaches the title through `usePageTitle(name)`, never through the table.
- **`back` is an explicit target, never `navigate(-1)`.** A create flow lands on the form otherwise. There is currently no `navigate(-1)` anywhere in `src/` — keep it that way.
- **This PR moves no permissions and changes no data.** Every route keeps the exact `PrivateRoute` gate it has today.
- Labels are **sentence case**; the title is the page's `<h1>`, rendered at `h5` size (audit P3-8).
- Every step's commands run from `frontend/`. Gate before every commit touching `.tsx`/`.ts`: `npx tsc --noEmit && npm run lint` (lint is `--max-warnings 0`).
- **A function or constant exported from a component file fails `react-refresh/only-export-components`.** Hooks, tables and helpers go in their own file. This cost a lint failure on the dark-mode branch; do not rediscover it.
- The **whole** frontend suite (`npx vitest run`) runs at Task 10, not targeted files — a regression in this codebase once survived six targeted runs.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ld4MWKmSqoYRbsSpm9WpTR
  ```
- Branch: `feature/ia-page-shell-url-tabs` off `main` (already created; the §6 spec amendment is its first commit).

---

## File map

**Created**

| File | Responsibility |
|---|---|
| `src/components/layout/PageHeader.tsx` | Title (`<h1>` at `h5`), optional subtitle, breadcrumbs, right-aligned actions. List and admin pages. |
| `src/components/layout/DetailPageHeader.tsx` | Back link to an explicit target, title, optional status chip, right-aligned actions. `*Detail` pages. |
| `src/components/layout/routeMeta.ts` | Static path-pattern → `{ label, parent }` map + `breadcrumbsFor(pathname)`. No React. |
| `src/hooks/usePageTitle.ts` | Sets `document.title` from `routeMeta` plus an optional leading override. Restores on unmount. |
| `src/hooks/useUrlTab.ts` | Reads/writes `?tab=`, `replace` not `push`, unknown key → default. |
| `src/__tests__/tabMechanism.test.ts` | Structural sweep: no route ends in `:tab`; `entityTabPath` emits a query param. |
| `src/hooks/__tests__/useUrlTab.test.tsx` | Fallback, replace-not-push, round trip. |
| `src/components/layout/__tests__/routeMeta.test.ts` | Breadcrumb trails; every `routeMeta` pattern resolves against the real router. |
| `src/components/layout/__tests__/pageHeaders.test.tsx` | `<h1>` present; back target explicit; actions render. |

**Modified**

| File | Change |
|---|---|
| `src/pages/admin/entityConfigTabs.ts:277-279` | `entityTabPath` emits `/admin/${entity}?tab=${tab}`. |
| `src/pages/admin/EntityConfig.tsx` | Tab from `useUrlTab`, not `useParams`. |
| `src/App.tsx:211` | `:entity/:tab` route becomes a redirect to the query form. |
| `src/components/adminNavConfig.tsx:22,37` | Follows `entityTabPath` (no change if it already calls it — verify). |
| `src/pages/releases/ReleaseDetail.tsx:72,159-169` | 11 numeric tabs → keys. |
| `src/pages/environments/EnvironmentDetail.tsx:146,700-707` | 8 numeric tabs → keys. |
| `src/pages/systems/SystemDetail.tsx:213,793-799` | 7 numeric tabs → keys. |
| `src/pages/releases/enterprise/EnterpriseTabs.tsx` | Already keyed; lift its state to `useUrlTab`. |
| `src/pages/releases/ReleaseCalendar.tsx:26,77,88` | Correct a header comment and a subtitle that both describe a phase deep link the data cannot support. **No behaviour change.** |
| ~40 list/admin pages | Adopt `PageHeader`. |
| 13 `*Detail` pages | Adopt `DetailPageHeader`. |
| 11 call sites | Confirm messages name their entity (audit P2-7). |
| `docs/ui-audit.md` | Status column: P2-6, P2-7, P3-5, P3-8 closed. |

**Deliberately NOT in this PR:** `DataTable` migration and the `DataGrid` lint rule (PR 4), the dashboard and *My work* (PR 3), the 1024 px pass (PR 5), and any splitting of the 1.4–1.9k-line detail pages (§2 non-goal).

---

## Task 1: `useUrlTab`

**Files:**
- Create: `src/hooks/useUrlTab.ts`
- Test: `src/hooks/__tests__/useUrlTab.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `useUrlTab(keys: readonly string[], defaultKey: string, param?: string): [string, (key: string) => void]`, `param` defaulting to `'tab'`. Every later tab task consumes exactly this signature — `EnterpriseTabs` renders **inside** `ReleaseDetail`'s `enterprise` tab and so shares one URL with it, which is why the param name is a parameter from the start rather than being widened later.

- [ ] **Step 1: Write the failing test**

```tsx
// src/hooks/__tests__/useUrlTab.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { useUrlTab } from '../useUrlTab';

const KEYS = ['main', 'gates', 'raid'] as const;

function Probe() {
  const [tab, setTab] = useUrlTab(KEYS, 'main');
  const location = useLocation();
  return (
    <div>
      <span data-testid="tab">{tab}</span>
      <span data-testid="search">{location.search}</span>
      <button onClick={() => setTab('raid')}>go raid</button>
    </div>
  );
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/r/:id" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );

describe('useUrlTab', () => {
  it('reads the tab from ?tab=', () => {
    renderAt('/r/7?tab=gates');
    expect(screen.getByTestId('tab')).toHaveTextContent('gates');
  });

  it('falls back to the default when ?tab= is absent', () => {
    renderAt('/r/7');
    expect(screen.getByTestId('tab')).toHaveTextContent('main');
  });

  it('falls back to the default when ?tab= is not a known key', () => {
    // A stale bookmark from before a tab was renamed must not render a blank
    // page — it lands on the default, exactly as if no tab had been named.
    renderAt('/r/7?tab=does-not-exist');
    expect(screen.getByTestId('tab')).toHaveTextContent('main');
  });

  it('writes the tab into the URL', async () => {
    renderAt('/r/7');
    await userEvent.click(screen.getByRole('button', { name: 'go raid' }));
    expect(screen.getByTestId('tab')).toHaveTextContent('raid');
    expect(screen.getByTestId('search')).toHaveTextContent('tab=raid');
  });

  it('preserves other query params when it changes the tab', () => {
    // A list filter, a selected row — switching tabs must not silently drop a
    // param another feature owns.
    renderAt('/r/7?tab=main&status=open');
    expect(screen.getByTestId('search')).toHaveTextContent('status=open');
  });

  it('two hooks with different param names do not overwrite each other', async () => {
    // EnterpriseTabs renders inside ReleaseDetail's `enterprise` tab, so both
    // are live on one URL. Without a distinct param they fight, and the inner
    // strip silently drives the outer one.
    render(
      <MemoryRouter initialEntries={['/r/7?tab=enterprise&etab=members']}>
        <Routes>
          <Route path="/r/:id" element={<TwoTabProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('outer')).toHaveTextContent('enterprise');
    expect(screen.getByTestId('inner')).toHaveTextContent('members');
    await userEvent.click(screen.getByRole('button', { name: 'inner report' }));
    expect(screen.getByTestId('outer')).toHaveTextContent('enterprise');
    expect(screen.getByTestId('inner')).toHaveTextContent('report');
  });
});

function TwoTabProbe() {
  const [outer] = useUrlTab(['main', 'enterprise'], 'main');
  const [inner, setInner] = useUrlTab(['main', 'members', 'report'], 'main', 'etab');
  return (
    <div>
      <span data-testid="outer">{outer}</span>
      <span data-testid="inner">{inner}</span>
      <button onClick={() => setInner('report')}>inner report</button>
    </div>
  );
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/hooks/__tests__/useUrlTab.test.tsx`
Expected: FAIL — `Failed to resolve import "../useUrlTab"`.

- [ ] **Step 3: Write the implementation**

```ts
// src/hooks/useUrlTab.ts
import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Which tab a page is on, held in `?tab=<key>` so it can be linked to and
 * survives a reload.
 *
 * `replace`, not `push`: clicking through five tabs then pressing Back should
 * leave the page, not walk back through the five tabs.
 *
 * An unknown key falls back to the default rather than rendering nothing — a
 * bookmark taken before a tab was renamed must still land somewhere.
 */
export function useUrlTab(
  keys: readonly string[],
  defaultKey: string,
  param = 'tab',
): [string, (key: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get(param);
  const tab = requested && keys.includes(requested) ? requested : defaultKey;

  const setTab = useCallback(
    (key: string) => {
      // Mutate a copy of the CURRENT params: other features own params on this
      // URL (ReleaseCalendar's ?phase=) and must survive a tab change.
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set(param, key);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams, param],
  );

  return [tab, setTab];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/hooks/__tests__/useUrlTab.test.tsx`
Expected: PASS, 6 tests.

- [ ] **Step 5: Gate and commit**

```bash
npx tsc --noEmit && npm run lint
git add src/hooks/useUrlTab.ts src/hooks/__tests__/useUrlTab.test.tsx
git commit -m "feat(nav): useUrlTab holds the active tab in ?tab="
```

---

## Task 2: Admin entity config moves to `?tab=`, and the segment form redirects

This is the task most likely to be got wrong, and the one §6 was amended for. Read §6's "ONE MECHANISM" and "route-level redirect" paragraphs before starting.

**Files:**
- Modify: `src/pages/admin/entityConfigTabs.ts:277-279`, `src/pages/admin/EntityConfig.tsx`, `src/App.tsx` (the `:entity/:tab` route)
- Create: `src/__tests__/tabMechanism.test.ts`
- Test: existing `src/__tests__/navRoutes.test.tsx` must stay green unchanged

**Interfaces:**
- Consumes: `useUrlTab` from Task 1.
- Produces: `entityTabPath(entity, tab) === "/admin/<entity>?tab=<tab>"`. `adminNavConfig` and the `/admin` hub already call it, so they follow automatically — **verify, do not assume**.

- [ ] **Step 1: Write the failing structural test**

```ts
// src/__tests__/tabMechanism.test.ts
import { describe, expect, it } from 'vitest';
import { entityTabPath } from '../pages/admin/entityConfigTabs';

// The REAL files, as text. `?raw` is Vite's own primitive (typed by
// `vite/client`) — deliberately NOT `node:fs` + `__dirname`, which work at
// runtime but are untyped in this package's tsconfig (no `@types/node`,
// `lib: ES2020`) and fail `tsc --noEmit`. The same note is on
// `src/pages/projects/__tests__/projectDetailGapLink.test.tsx`, which is
// where this pattern is established.
import appSource from '../App.tsx?raw';
import releaseDetailSource from '../pages/releases/ReleaseDetail.tsx?raw';
import environmentDetailSource from '../pages/environments/EnvironmentDetail.tsx?raw';
import systemDetailSource from '../pages/systems/SystemDetail.tsx?raw';
import enterpriseTabsSource from '../pages/releases/enterprise/EnterpriseTabs.tsx?raw';
import entityConfigSource from '../pages/admin/EntityConfig.tsx?raw';

/**
 * §6: the tab is a query param, everywhere. PR 1 shipped the admin config tab
 * as a route segment; converting it left the segment form reachable as a
 * redirect, so a page could quietly go back to addressing tabs that way and
 * every behavioural test would stay green. Hence a structural sweep.
 */
describe('one tab mechanism', () => {
  it('entityTabPath emits a query param, not a path segment', () => {
    expect(entityTabPath('environments', 'naming-policy')).toBe(
      '/admin/environments?tab=naming-policy',
    );
  });

  it('every tab strip with more than six tabs is scrollable', () => {
    // §6. ReleaseDetail rendered an eleventh tab entirely off-screen until C4
    // caught it, and only a synthetic click could reach it — automation
    // scrolls its target into view, so no test noticed and no mouse could.
    const strips: Array<[string, string]> = [
      ['ReleaseDetail', releaseDetailSource],
      ['EnvironmentDetail', environmentDetailSource],
      ['SystemDetail', systemDetailSource],
      ['EnterpriseTabs', enterpriseTabsSource],
      ['EntityConfig', entityConfigSource],
    ];
    for (const [name, src] of strips) {
      expect(src, `${name} renders a tab strip that cannot scroll`).toMatch(
        /variant="scrollable"/,
      );
    }
  });

  it('no route pattern addresses a tab as a path segment', () => {
    // Every `path="…"` that ends in a :tab segment, EXCEPT the one that renders
    // a redirect. Matching on the file is deliberate: this is a rule about the
    // route table's shape, which no rendered assertion can observe.
    const tabSegmentRoutes = [...appSource.matchAll(/path="([^"]*:tab)"/g)].map((m) => m[1]);
    expect(tabSegmentRoutes).toEqual([':entity/:tab']);
    // …and that one must be a redirect, not a page.
    const redirectLine = appSource
      .split('\n')
      .find((l) => l.includes('path=":entity/:tab"'));
    expect(redirectLine).toMatch(/Navigate/);
    expect(redirectLine).not.toMatch(/EntityConfig/);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/__tests__/tabMechanism.test.ts`
Expected: FAIL on both — `entityTabPath` returns `/admin/environments/naming-policy`, and the `:entity/:tab` route renders `EntityConfig`.

- [ ] **Step 3: Change `entityTabPath`**

```ts
// src/pages/admin/entityConfigTabs.ts — replace lines 277-279
/**
 * Where an entity's configuration tab lives. The tab is a QUERY PARAM, not a
 * path segment (spec §6): one mechanism app-wide, so a drawer item, a tab
 * click and a bookmark all say the same thing. `/admin/:entity/:tab` still
 * resolves, as a redirect registered in App.tsx.
 */
export function entityTabPath(entity: AdminEntity, tab: string): string {
  return `/admin/${entity}?tab=${tab}`;
}
```

- [ ] **Step 4: Move `EntityConfig` onto `useUrlTab`**

Replace the `useParams`/`navigate` tab handling (currently lines 49-72). The entity still comes from the route; only the tab moves.

```tsx
// src/pages/admin/EntityConfig.tsx
const { entity } = useParams<{ entity: string }>();
const page = entityConfigPage(entity);
if (!page) return <Navigate replace to={ADMIN_ROOT} />;
const [tab, setTab] = useUrlTab(page.tabs.map((t) => t.key), page.tabs[0].key);
const current = page.tabs.find((t) => t.key === tab) ?? page.tabs[0];
```

and the `<Tabs>`:

```tsx
<Tabs
  value={tab}
  onChange={(_, key: string) => setTab(key)}
  variant="scrollable"
  scrollButtons="auto"
>
```

Delete the `<Navigate replace to={entityTabPath(...)} />` fallback for an unknown tab — `useUrlTab` already falls back, and a redirect would now fight it. Keep the `Navigate` for an unknown **entity**.

- [ ] **Step 5: Turn the segment route into a redirect**

In `src/App.tsx`, replace the `:entity/:tab` route (line 211). Add the component next to the other route helpers:

```tsx
/**
 * `/admin/:entity/:tab` was PR 1's form. The tab is a query param now (§6), so
 * this is a redirect and NOT a LEGACY_REDIRECTS entry: that table answers
 * "this page moved" and is scheduled for deletion one release after PR 1;
 * this answers "a tab is addressed differently". Folding them together would
 * leave the next reader unable to delete either safely.
 */
function EntityTabRedirect() {
  const { entity, tab } = useParams<{ entity: string; tab: string }>();
  return <Navigate replace to={`/admin/${entity}?tab=${tab}`} />;
}
```

```tsx
<Route path=":entity/:tab" element={<PrivateRoute requiredRole="Admin"><EntityTabRedirect /></PrivateRoute>} />
```

Keep the existing comment about react-router ranking static segments above dynamic ones — it still explains why these two catch-alls are last.

- [ ] **Step 6: Verify the drawer follows**

Run: `grep -n "entityTabPath" src/components/adminNavConfig.tsx`
Expected: both call sites (lines 22 and 37) call `entityTabPath` and need **no** edit. If either builds a path by hand, fix it now — the drawer must never emit a URL that immediately redirects.

- [ ] **Step 7: Run the tests**

Run: `npx vitest run src/__tests__/tabMechanism.test.ts src/__tests__/navRoutes.test.tsx src/__tests__/legacyRedirects.test.tsx`
Expected: PASS. `navRoutes` walks the drawer against the real router, so it proves the query-form links resolve.

- [ ] **Step 8: Gate and commit**

```bash
npx tsc --noEmit && npm run lint
git add src/pages/admin/entityConfigTabs.ts src/pages/admin/EntityConfig.tsx src/App.tsx src/__tests__/tabMechanism.test.ts
git commit -m "refactor(admin): the entity-config tab is a query param, not a route segment"
```

---

## Task 3: `ReleaseDetail`, `EnvironmentDetail`, `SystemDetail` and `EnterpriseTabs` on `useUrlTab`

**Files:**
- Modify: `src/pages/releases/ReleaseDetail.tsx:72,159-169`, `src/pages/environments/EnvironmentDetail.tsx:146,700-707`, `src/pages/systems/SystemDetail.tsx:213,793-799`, `src/pages/releases/enterprise/EnterpriseTabs.tsx`
- Test: `src/pages/releases/__tests__/releaseDetailTabs.test.tsx` (create)

**Interfaces:**
- Consumes: `useUrlTab` (Task 1).
- Produces: the tab key vocabularies other tasks and deep links use. Keys are lower-kebab, derived from the label:
  - **Release** (default `main`): `main`, `gates`, `systems`, `environments`, `requests`, `scope`, `raid`, `enterprise`, `deployments`, `pir`, `rollback`
  - **Environment** (default `overview`): `overview`, `systems`, `components`, `topology`, `schedule`, `deployments`, `health`, `operating-hours`
  - **System** (default `overview`): `overview`, `subsystems`, `dependencies`, `component-deps`, `topology`, `scope-windows`, `rollback`
  - **Enterprise** (default `main`): unchanged — it already uses `main`, `members`, `phases`, `environments`, `requests`, `scope`, `systems`, `scope_rollup`, `raid_rollup`, `timeline`, `report`. **Do not rename these to kebab**: they are already in use and renaming buys nothing.

- [ ] **Step 1: Write the failing test**

**No existing test renders `ReleaseDetail`** — checked, the directory holds
tests for `ReleaseList`, `ReleaseForm` and `ReleaseAnalytics` only. So there is
no sibling pattern to copy and the harness is written here. `ReleaseDetail`
takes its data from `releaseSlice` via `fetchRelease`, so mock the slice's
thunk and seed the reducer's state directly; that keeps the test about tabs
rather than about the network.

```tsx
// src/pages/releases/__tests__/releaseDetailTabs.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import releaseReducer from '../../../store/releaseSlice';
import ReleaseDetail from '../ReleaseDetail';

// fetchRelease is a thunk that hits the API; the page only needs `detail` to
// be present for the tab strip to render. Mock the thunk to a no-op and seed
// the state — the subject here is which tab is selected, not loading.
vi.mock('../../../store/releaseSlice', async () => {
  const actual = await vi.importActual<typeof import('../../../store/releaseSlice')>(
    '../../../store/releaseSlice',
  );
  return { ...actual, fetchRelease: Object.assign(() => ({ type: 'noop' }), { pending: { type: 'noop/pending' } }) };
});

const makeStore = () =>
  configureStore({
    reducer: { release: releaseReducer },
    preloadedState: {
      release: {
        // Seed only what the tab strip needs; widen if the page demands more
        // once it is running — do NOT stub the whole slice speculatively.
        detail: { id: 7, name: 'R1', status: 'draft' },
        loading: false,
        error: null,
      } as never,
    },
  });

const renderAt = (search: string) =>
  render(
    <Provider store={makeStore()}>
      <MemoryRouter initialEntries={[`/releases/7${search}`]}>
        <Routes>
          <Route path="/releases/:id" element={<ReleaseDetail />} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  );

describe('ReleaseDetail — the tab is in the URL', () => {
  it('opens the tab named by ?tab=', async () => {
    renderAt('?tab=rollback');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Rollback' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when no tab is named', async () => {
    renderAt('');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when ?tab= names a tab that no longer exists', async () => {
    renderAt('?tab=gone');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('puts the tab in the URL when one is clicked', async () => {
    renderAt('');
    await userEvent.click(await screen.findByRole('tab', { name: 'RAID' }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'RAID' })).toHaveAttribute('aria-selected', 'true'),
    );
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/pages/releases/__tests__/releaseDetailTabs.test.tsx`
Expected: FAIL — `?tab=rollback` currently selects Main, because the page holds a numeric index.

- [ ] **Step 3: Convert `ReleaseDetail`**

Replace `const [activeTab, setActiveTab] = useState(0);` (line 72) with the keyed form. Declare the vocabulary next to the tabs, not inline in the hook call, so the tab strip and the vocabulary cannot drift:

```tsx
const RELEASE_TABS = [
  { key: 'main', label: 'Main' },
  { key: 'gates', label: 'Gates & Test Phases' },
  { key: 'systems', label: 'Systems' },
  { key: 'environments', label: 'Environments' },
  { key: 'requests', label: 'Linked Requests' },
  { key: 'scope', label: 'Scope' },
  { key: 'raid', label: 'RAID' },
  { key: 'enterprise', label: 'Enterprise' },
  { key: 'deployments', label: 'Deployments' },
  { key: 'pir', label: 'PIR' },
  { key: 'rollback', label: 'Rollback' },
] as const;
```

```tsx
const [activeTab, setActiveTab] = useUrlTab(RELEASE_TABS.map((t) => t.key), 'main');
```

```tsx
<Tabs
  value={activeTab}
  onChange={(_, key: string) => setActiveTab(key)}
  variant="scrollable"
  scrollButtons="auto"
>
  {RELEASE_TABS.map((t) => (
    <Tab key={t.key} value={t.key} label={t.label} />
  ))}
</Tabs>
```

Then change every panel guard from an index to a key: `{activeTab === 0 && …}` becomes `{activeTab === 'main' && …}`, in the order listed above. **Convert them one at a time and count them** — there are eleven, and an off-by-one here renders the wrong panel silently.

- [ ] **Step 4: Run the test**

Run: `npx vitest run src/pages/releases/__tests__/releaseDetailTabs.test.tsx`
Expected: PASS, 4 tests.

- [ ] **Step 5: Convert `EnvironmentDetail` and `SystemDetail` the same way**

`EnvironmentDetail`: `useState(0)` at line 146, tabs at 700-707, keys as listed in Interfaces, default `overview`. `SystemDetail`: `useState(0)` at line 213, tabs at 793-799, default `overview`. Both get `variant="scrollable" scrollButtons="auto"`. Grep each file for `tab === ` afterwards and confirm no numeric comparison survives:

```bash
grep -n "tab === [0-9]" src/pages/environments/EnvironmentDetail.tsx src/pages/systems/SystemDetail.tsx src/pages/releases/ReleaseDetail.tsx
```
Expected: no output.

- [ ] **Step 6: Lift `EnterpriseTabs` onto the hook**

It already uses string `value=` keys, so only its state moves to `useUrlTab`. It is rendered **inside** `ReleaseDetail`'s `enterprise` tab, so both strips are live on one URL — pass the third argument Task 1 already provides so they do not fight over `?tab=`:

```tsx
const ENTERPRISE_KEYS = [
  'main', 'members', 'phases', 'environments', 'requests', 'scope',
  'systems', 'scope_rollup', 'raid_rollup', 'timeline', 'report',
] as const;

const [tab, setTab] = useUrlTab(ENTERPRISE_KEYS, 'main', 'etab');
```

The two-hook case is already covered by Task 1's last test; no new test is needed here.

- [ ] **Step 7: Run the tab tests**

Run: `npx vitest run src/hooks/__tests__/useUrlTab.test.tsx src/pages/releases/__tests__/releaseDetailTabs.test.tsx`
Expected: PASS.

- [ ] **Step 8: Gate and commit**

```bash
npx tsc --noEmit && npm run lint
git add src/hooks/useUrlTab.ts src/hooks/__tests__/useUrlTab.test.tsx src/pages/releases/ReleaseDetail.tsx src/pages/environments/EnvironmentDetail.tsx src/pages/systems/SystemDetail.tsx src/pages/releases/enterprise/EnterpriseTabs.tsx src/pages/releases/__tests__/releaseDetailTabs.test.tsx
git commit -m "feat(nav): detail-page tabs live in the URL"
```

---

## Task 4: Correct the release calendar's false deep-link prose

§6 originally asked PR 2 to point the calendar's phase click at
`?tab=phases&phase=:phaseId`. **That link cannot be built**, and the spec has
been amended to say so. `GET /releases/calendar` returns
`ReleaseCalendarEntry` — `{ id, title, start, end, status, release_type }` —
so the events on that calendar are **releases, not phases**, and no phase id
exists to link with. `handleEventClick` navigates to `/releases/:id`, which is
the only thing it could do.

Two pieces of prose claim otherwise and are the actual defect: the file's
header comment (line 26) and the page's own subtitle (line 88, "Phase timeline
for all active releases. Click a phase to open the release."). Both are read
by users or maintainers as statements of fact. This task fixes the words and
changes no behaviour.

**Files:**
- Modify: `src/pages/releases/ReleaseCalendar.tsx` (comment at line 26, subtitle at line 88)

**Interfaces:**
- Consumes: nothing. **Produces: nothing.** No other task depends on this one.

- [ ] **Step 1: Confirm the claim before changing anything**

```bash
sed -n '242,252p' src/types/release.ts
grep -n "handleEventClick" -A3 src/pages/releases/ReleaseCalendar.tsx
```
Expected: `ReleaseCalendarEntry` has no phase field, and the handler navigates
to `` `/releases/${entry.id}` ``. **If either is untrue, stop — the spec
amendment was wrong and needs revisiting before this task proceeds.**

- [ ] **Step 2: Correct the header comment**

Replace the `Click a phase event → /releases/:releaseId?tab=phases&phase=:phaseId`
line with:

```tsx
// Click a release → /releases/:releaseId. The endpoint returns one entry per
// RELEASE (ReleaseCalendarEntry has no phase id), so there is nothing finer to
// link to; a phase-level calendar would need a different endpoint.
```

- [ ] **Step 3: Correct the subtitle**

```tsx
<Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
  Target and actual dates for all active releases. Click a release to open it.
</Typography>
```

- [ ] **Step 4: Check nothing else repeats the claim**

```bash
grep -rn "tab=phases\|Click a phase" src
```
Expected: no output.

- [ ] **Step 5: Run the calendar's tests and gate**

```bash
npx vitest run src/pages/releases
npx tsc --noEmit && npm run lint
git add src/pages/releases/ReleaseCalendar.tsx
git commit -m "docs(releases): the calendar shows releases, not phases"
```

---

## Task 5: `routeMeta` and `usePageTitle`

**Files:**
- Create: `src/components/layout/routeMeta.ts`, `src/hooks/usePageTitle.ts`, `src/components/layout/__tests__/routeMeta.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `type RouteMeta = { label: string; parent?: string }`
  - `ROUTE_META: Record<string, RouteMeta>` — keys are **route patterns** (`/environments/:id`), not concrete paths.
  - `breadcrumbsFor(pathname: string): Array<{ label: string; to?: string }>` — last crumb has no `to`.
  - `usePageTitle(override?: string): void` — sets `document.title`.

- [ ] **Step 1: Write the failing test**

```ts
// src/components/layout/__tests__/routeMeta.test.ts
import { describe, expect, it } from 'vitest';
import { ROUTE_META, breadcrumbsFor } from '../routeMeta';

describe('breadcrumbsFor', () => {
  it('walks parents to the root', () => {
    expect(breadcrumbsFor('/admin/environments')).toEqual([
      { label: 'Administration', to: '/admin' },
      { label: 'Environments' },
    ]);
  });

  it('leaves the last crumb unlinked', () => {
    const crumbs = breadcrumbsFor('/environments');
    expect(crumbs[crumbs.length - 1].to).toBeUndefined();
  });

  it('matches a dynamic segment against its pattern', () => {
    expect(breadcrumbsFor('/environments/42').map((c) => c.label)).toEqual([
      'Environments',
      'Environment',
    ]);
  });

  it('returns nothing for a path it does not know', () => {
    // A breadcrumb trail that guesses is worse than none: it would state a
    // parent that may not exist.
    expect(breadcrumbsFor('/nonsense/path')).toEqual([]);
  });
});

describe('ROUTE_META', () => {
  it('every parent is itself a known pattern', () => {
    for (const [pattern, meta] of Object.entries(ROUTE_META)) {
      if (meta.parent) {
        expect(ROUTE_META[meta.parent], `${pattern}'s parent ${meta.parent}`).toBeDefined();
      }
    }
  });

  it('holds no dynamic data', () => {
    // §6: the map is static. A label containing a template placeholder would
    // mean someone started resolving entity names in here.
    for (const meta of Object.values(ROUTE_META)) {
      expect(meta.label).not.toMatch(/[${}]/);
    }
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/layout/__tests__/routeMeta.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `routeMeta.ts`**

Populate `ROUTE_META` from `navConfig`'s and `adminNavConfig`'s paths plus the detail routes. Use `matchPath` from react-router to resolve a concrete pathname to a pattern. Keep it free of React so it stays unit-testable.

```ts
// src/components/layout/routeMeta.ts
import { matchPath } from 'react-router-dom';

export type RouteMeta = { label: string; parent?: string };

/**
 * Path pattern → where it sits. STATIC by design (spec §6): a page's entity
 * name reaches document.title through usePageTitle(name), never through here.
 * A table that depended on fetched state would have two sources of truth and
 * could not be unit-tested.
 */
export const ROUTE_META: Record<string, RouteMeta> = {
  '/dashboard': { label: 'Dashboard' },
  '/environments': { label: 'Environments' },
  '/environments/:id': { label: 'Environment', parent: '/environments' },
  // …one entry per route in App.tsx. Labels match the drawer's labels exactly:
  // two names for one page is the drift PR 1 existed to remove.
  '/admin': { label: 'Administration' },
  '/admin/environments': { label: 'Environments', parent: '/admin' },
};

export function breadcrumbsFor(pathname: string): Array<{ label: string; to?: string }> {
  const pattern = Object.keys(ROUTE_META).find((p) => matchPath(p, pathname));
  if (!pattern) return [];
  const trail: Array<{ label: string; to?: string }> = [];
  for (let p: string | undefined = pattern; p; p = ROUTE_META[p]?.parent) {
    trail.unshift({ label: ROUTE_META[p].label, to: p });
  }
  delete trail[trail.length - 1].to;
  return trail;
}
```

Note `delete` on the last crumb's `to` — or build it without the key; either is fine, but the last crumb must not be a link.

- [ ] **Step 4: Write `usePageTitle.ts`**

```ts
// src/hooks/usePageTitle.ts
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { breadcrumbsFor } from '../components/layout/routeMeta';

const APP = 'EnvManager';

/**
 * Sets document.title from the route's breadcrumb trail, innermost first:
 * "Naming policy · Administration · EnvManager".
 *
 * `override` is how a DETAIL page contributes its entity's name — the one
 * piece of a title no static table can hold (spec §6).
 */
export function usePageTitle(override?: string): void {
  const { pathname } = useLocation();
  useEffect(() => {
    const crumbs = breadcrumbsFor(pathname).map((c) => c.label).reverse();
    const parts = override ? [override, ...crumbs.slice(1)] : crumbs;
    document.title = [...parts, APP].join(' · ');
    return () => {
      document.title = APP;
    };
  }, [pathname, override]);
}
```

- [ ] **Step 5: Run the tests**

Run: `npx vitest run src/components/layout/__tests__/routeMeta.test.ts`
Expected: PASS, 6 tests.

- [ ] **Step 6: Gate and commit**

```bash
npx tsc --noEmit && npm run lint
git add src/components/layout/routeMeta.ts src/hooks/usePageTitle.ts src/components/layout/__tests__/routeMeta.test.ts
git commit -m "feat(nav): routeMeta drives breadcrumbs and document.title"
```

---

## Task 6: `PageHeader` and `DetailPageHeader`

**Files:**
- Create: `src/components/layout/PageHeader.tsx`, `src/components/layout/DetailPageHeader.tsx`, `src/components/layout/__tests__/pageHeaders.test.tsx`

**Interfaces:**
- Consumes: `breadcrumbsFor`, `usePageTitle` (Task 5).
- Produces:
  - `<PageHeader title actions? subtitle? />`
  - `<DetailPageHeader back={{ to, label }} title status? actions? />`
  Both render the title as `<h1>` at `h5` size and call `usePageTitle`.

- [ ] **Step 1: Write the failing test**

```tsx
// src/components/layout/__tests__/pageHeaders.test.tsx
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PageHeader from '../PageHeader';
import DetailPageHeader from '../DetailPageHeader';

// `ReactNode`, not `React.ReactNode`: the new JSX transform does not bring the
// React namespace into scope for types.
const at = (path: string, ui: ReactNode) =>
  render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);

describe('PageHeader', () => {
  it('renders the title as the page h1 (audit P3-8)', () => {
    at('/environments', <PageHeader title="Environments" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Environments' })).toBeInTheDocument();
  });

  it('renders breadcrumbs from the route, not from props', () => {
    at('/admin/environments', <PageHeader title="Environments" />);
    expect(screen.getByRole('link', { name: 'Administration' })).toHaveAttribute('href', '/admin');
  });

  it('renders actions', () => {
    at('/environments', <PageHeader title="Environments" actions={<button>New</button>} />);
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument();
  });
});

describe('DetailPageHeader', () => {
  it('links back to an explicit target', () => {
    // Never history.back(): after a create, that lands on the form.
    at('/environments/2', <DetailPageHeader back={{ to: '/environments', label: 'Environments' }} title="Mortgage_SIT" />);
    // Named, and a real link: an icon with only a click handler has no
    // accessible name and no keyboard route.
    expect(screen.getByRole('link', { name: 'Back to Environments' })).toHaveAttribute(
      'href',
      '/environments',
    );
  });

  it('renders the entity name as h1', () => {
    at('/environments/2', <DetailPageHeader back={{ to: '/environments', label: 'Environments' }} title="Mortgage_SIT" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Mortgage_SIT' })).toBeInTheDocument();
  });

  it('puts the entity name in the document title', () => {
    at('/environments/2', <DetailPageHeader back={{ to: '/environments', label: 'Environments' }} title="Mortgage_SIT" />);
    expect(document.title).toContain('Mortgage_SIT');
    expect(document.title).toContain('EnvManager');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/components/layout/__tests__/pageHeaders.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write both components**

```tsx
// src/components/layout/PageHeader.tsx
import type { ReactNode } from 'react';
import { Box, Breadcrumbs, Link, Stack, Typography } from '@mui/material';
import { Link as RouterLink, useLocation } from 'react-router-dom';
import { breadcrumbsFor } from './routeMeta';
import { usePageTitle } from '../../hooks/usePageTitle';

export interface PageHeaderProps {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}

/**
 * The header every list and admin page composes through. The title is the
 * page's ONLY <h1> (audit P3-8), and breadcrumbs come from the route, not
 * from props — a page that could pass its own trail could disagree with the
 * drawer about where it sits.
 */
export default function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  const { pathname } = useLocation();
  const crumbs = breadcrumbsFor(pathname);
  usePageTitle();

  return (
    <Box sx={{ mb: 3 }}>
      {crumbs.length > 1 && (
        <Breadcrumbs sx={{ mb: 1 }}>
          {crumbs.map((c) =>
            c.to ? (
              <Link key={c.to} component={RouterLink} to={c.to} underline="hover" color="inherit">
                {c.label}
              </Link>
            ) : (
              <Typography key={c.label} color="text.primary">
                {c.label}
              </Typography>
            ),
          )}
        </Breadcrumbs>
      )}
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
        <Typography component="h1" variant="h5">
          {title}
        </Typography>
        {actions && (
          <Stack direction="row" spacing={1}>
            {actions}
          </Stack>
        )}
      </Stack>
      {subtitle && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {subtitle}
        </Typography>
      )}
    </Box>
  );
}
```

```tsx
// src/components/layout/DetailPageHeader.tsx
import type { ReactNode } from 'react';
import { Box, IconButton, Stack, Tooltip, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { Link as RouterLink } from 'react-router-dom';
import { usePageTitle } from '../../hooks/usePageTitle';

export interface DetailPageHeaderProps {
  /** An EXPLICIT target. Never history.back(): after a create, that is the form. */
  back: { to: string; label: string };
  title: string;
  status?: ReactNode;
  actions?: ReactNode;
}

export default function DetailPageHeader({ back, title, status, actions }: DetailPageHeaderProps) {
  // The entity's name is the one part of the title no static table can hold.
  usePageTitle(title);

  return (
    <Box sx={{ mb: 3 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ minWidth: 0 }}>
          <Tooltip title={`Back to ${back.label}`}>
            <IconButton component={RouterLink} to={back.to} aria-label={`Back to ${back.label}`} size="small">
              <ArrowBackIcon />
            </IconButton>
          </Tooltip>
          <Typography component="h1" variant="h5" noWrap>
            {title}
          </Typography>
          {status}
        </Stack>
        {actions && (
          <Stack direction="row" spacing={1}>
            {actions}
          </Stack>
        )}
      </Stack>
    </Box>
  );
}
```

Note the back control is an `IconButton` rendered as a router `Link` with an
`aria-label` — a bare `<ArrowBackIcon>` inside a click handler has no
accessible name and is not reachable by keyboard, the shape the PIR work hit
with MUI's `<Chip onDelete>`.

- [ ] **Step 4: Run the tests**

Run: `npx vitest run src/components/layout/__tests__/pageHeaders.test.tsx`
Expected: PASS, 6 tests.

- [ ] **Step 5: Gate and commit**

```bash
npx tsc --noEmit && npm run lint
git add src/components/layout/PageHeader.tsx src/components/layout/DetailPageHeader.tsx src/components/layout/__tests__/pageHeaders.test.tsx
git commit -m "feat(layout): PageHeader and DetailPageHeader"
```

---

## Task 7: Adopt `DetailPageHeader` on the thirteen detail pages

Do detail pages before list pages: there are fewer of them, they are the ones with a back link and a status chip, and getting the pattern right here makes the ~40 list pages mechanical.

**Files:** the 13 `*Detail.tsx` under `src/pages/` (listed in the file map). `TenantDetail.tsx:174-179`'s ad-hoc `<Breadcrumbs>` is deleted in favour of the shared trail.

- [ ] **Step 1: Convert `EnvironmentDetail` first, and screenshot it**

One page, then look at it in the browser at `/environments/2` before doing the other twelve. A shared header adopted wrongly twelve times is twelve reverts.

- [ ] **Step 2: Convert the remaining twelve**

For each: replace the hand-rolled title/back row with `<DetailPageHeader>`; keep the page's own status chip by passing it as `status`; keep its action buttons by passing them as `actions`. Where a page has no back link today, give it the explicit parent list route — not `navigate(-1)`.

- [ ] **Step 3: Delete `TenantDetail`'s ad-hoc breadcrumbs**

Remove lines 174-179 and the now-unused `Breadcrumbs` import (line 22). The trail comes from `routeMeta`.

- [ ] **Step 4: Check no page still hand-rolls a title**

```bash
grep -rn 'variant="h4"' src/pages/*/*Detail.tsx
```
Expected: no output.

- [ ] **Step 5: Run the affected suites and gate**

```bash
npx vitest run src/pages
npx tsc --noEmit && npm run lint
git add src/pages
git commit -m "refactor(pages): detail pages adopt DetailPageHeader"
```

---

## Task 8: Adopt `PageHeader` on the list and admin pages

**Files:** every non-detail page under `src/pages/` (~40), excluding `Login.tsx` (its own centred layout) and `NotFound`.

- [ ] **Step 1: Convert, one group at a time, committing per group**

Order: `catalogue` (systems, environments, hosts, compare, import) → `bookings` → `releases` → `insights` → `admin`. Each group is one commit, so a bad pattern is one revert.

- [ ] **Step 2: Check every page now has exactly one `<h1>`**

Add to `src/components/layout/__tests__/pageHeaders.test.tsx` a sweep asserting no page module contains `variant="h4"` as a page title, and run:

```bash
grep -rln "PageHeader\|DetailPageHeader" src/pages | wc -l
```
Expected: ≥ 50.

- [ ] **Step 3: Gate and commit**

```bash
npx tsc --noEmit && npm run lint
git add src/pages
git commit -m "refactor(pages): list and admin pages adopt PageHeader"
```

---

## Task 9: The eleven generic confirm messages (audit P2-7)

**Note:** P2-6 (focus *Cancel* when destructive) is **already implemented** in `ConfirmDialog.tsx` — `autoFocus={destructive}`, with a comment saying why. This task adds the test that pins it and fixes the messages only.

**Locate every site by SEARCHING for its message text, not by the line numbers below.** Tasks 7 and 8 edit these same files first, so the numbers are true only at the branch point.

**Files:** `src/hooks/useConfirm.tsx` (test only), and the 11 call sites:
`UserManagement.tsx:115`, `TenantList.tsx:68`, `TenantDetail.tsx:125`, `ApiKeyManagement.tsx:44`, `ChangeRequestDetail.tsx:102`, `ScopeTable.tsx:90`, `GatesTable.tsx:195`, `GatesTable.tsx:281`, `PhasesTable.tsx:123`, `LinkedChangeRequestsSection.tsx:42`, `CustomFieldDefinitionManager.tsx` ("Delete this field?").

- [ ] **Step 1: Write the failing test for the focus rule**

```tsx
// in src/hooks/__tests__/useConfirm.test.tsx (create if absent)
it('focuses Cancel for a destructive confirm so a stray Enter does not delete', async () => {
  // render a probe that calls confirm({ message: 'x', destructive: true })
  expect(await screen.findByRole('button', { name: 'Cancel' })).toHaveFocus();
});

it('focuses Confirm for a non-destructive confirm', async () => {
  expect(await screen.findByRole('button', { name: 'Confirm' })).toHaveFocus();
});
```

- [ ] **Step 2: Run it**

Run: `npx vitest run src/hooks/__tests__/useConfirm.test.tsx`
Expected: PASS immediately — the behaviour exists; this test is the guard that was missing. If it FAILS, the audit's P2-6 is not actually closed and that is a finding to report before continuing.

- [ ] **Step 3: Name the entity in all eleven messages**

Each becomes specific, using data already in scope at the call site. For example:
- `'Deactivate this user?'` → `` `Deactivate ${user.username}? They will lose access immediately.` ``
- `'Revoke this API key?'` → `` `Revoke API key "${key.name}"? Anything using it will stop working.` ``
- `'Delete this gate?'` → `` `Delete gate "${gate.name}"?` ``
- `'Delete this phase?'` → `` `Delete phase "${phase.name}"?` ``
- `'Delete this scope item?'` → `` `Delete scope item "${item.title}"?` ``
- `'Delete this criterion?'` → `` `Delete criterion "${criterion.name}"?` ``
- `'Delete this change request?'` → `` `Delete change request "${cr.title}"?` ``
- `'Unlink this change request from the release?'` → `` `Unlink "${cr.title}" from this release? The change request itself is not deleted.` ``
- `'Delete this field? This cannot be undone.'` → `` `Delete custom field "${def.label}"? This cannot be undone.` ``
- `'Disable this tenant? All users will lose access.'` → `` `Disable tenant "${tenant.name}"? All its users will lose access.` ``
- `TenantDetail.tsx:125` → `` `Deactivate ${user.username}? They will lose access immediately.` ``

Where the object might be missing, fall back to the generic wording rather than rendering `undefined` — and never to `#<id>` (see the display-names rule in this repo).

- [ ] **Step 4: Verify none are left**

```bash
grep -rn "confirm({" src -A2 | grep "message: '" | grep -v '\${'
```
Expected: no output.

- [ ] **Step 5: Gate and commit**

```bash
npx tsc --noEmit && npm run lint
git add src
git commit -m "fix(ui): confirm dialogs name what they are about (P2-7)"
```

---

## Task 10: Whole-suite run, browser pass, docs

- [ ] **Step 1: Run the WHOLE frontend suite**

Run: `npx vitest run`
Expected: all files pass. Targeted runs do not count — a regression here once survived six of them.

- [ ] **Step 2: Build**

Run: `npx tsc --noEmit && npm run lint && npm run build`
Expected: all three clean.

- [ ] **Step 3: Browser pass, recorded in the PR description**

Restart the dev server first (`npm run dev`); a long-running one serves stale optimized deps and produces errors that look exactly like app bugs. Then check, in **both** light and dark:

1. `/releases/7?tab=rollback` — opens on Rollback; reload keeps it; Back leaves the page rather than walking the tabs.
2. `/releases/7?tab=nonsense` — opens on Main, no blank page.
3. `/admin/environments/naming-policy` — redirects to `/admin/environments?tab=naming-policy` and shows that tab.
4. The admin drawer's *Naming policy* item — goes straight there, with **no** intermediate redirect.
5. An event on `/releases/calendar` — opens that release, and the subtitle no longer promises a phase link (Task 4).
6. Breadcrumbs and the browser tab title on one list page, one detail page, one admin page.
7. `/environments/2` — back link goes to `/environments`, not into history.

- [ ] **Step 4: Docs**

`docs/ui-audit.md`: mark P2-6, P2-7, P3-5 and P3-8 closed in the status column PR 1 added. Note in the P2-6 row that the fix predated this PR and that PR 2 added its guard.

- [ ] **Step 5: Commit and open the PR**

```bash
git add docs/ui-audit.md
git commit -m "docs: mark the audit findings PR 2 closes"
git push -u github feature/ia-page-shell-url-tabs
```

PR description records the browser pass above, and states plainly which of §6 is done and what remains for PRs 3–5.

---

## Appendix: carried forward, not this PR's work

`src/__tests__/navRoutes.test.tsx` carries a comment block naming **five pages that throw on an unexpected GET shape** — `EnvironmentNamingPolicyPanel`, `RaidSettings`, `ReleaseAnalytics` (two endpoints) and `DoraDashboard`. One root cause: the handler trusts the response is an object. Not reachable through the real API contract, so not a live outage, and deliberately out of scope here.

Their only record is that comment. **Raise a GitHub issue for them before it is tidied away** — that is the whole reason this appendix exists.
