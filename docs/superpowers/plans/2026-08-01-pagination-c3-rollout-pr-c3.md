# C3 Rollout — PR C3 (systems) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `SystemCatalog` to true server-side paging, sorting and filtering — the **last of the eleven pages** in this programme.

**Architecture:** The same five moves as C1 and C2, but the prerequisite is shaped differently: most consumers here bypass the slice entirely and call the service directly, so the hook replaces **five duplicated local fetches** rather than five slice reads.

**Tech Stack:** React 18 + TypeScript, Redux Toolkit, MUI DataGrid 6.20.4 Community, vitest + @testing-library/react.

## Read C1 and C2 first

This plan does not restate what they established:

- `docs/superpowers/plans/2026-08-01-pagination-c3-rollout-pr-c1.md` (environments, 9 consumers) and `-pr-c2.md` (infrastructure-components, 4).
- `frontend/src/hooks/useAllEnvironments.ts` and `useAllHosts.ts` — the picker hook, twice.
- `frontend/src/__tests__/environmentSliceConsumers.test.ts` — the source-scanning guard.
- `frontend/src/pages/infrastructure/InfrastructureComponentList.tsx` — the converted page: raw `DataGrid`, text filter, inline CRUD, `disableColumnFilter`, exported columns array.

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-01-pagination-c3-rollout-design.md`](../specs/2026-08-01-pagination-c3-rollout-design.md).
- Branch `feature/c3-rollout-pr-c3`, already created off `main` at `6466db4`.
- Tests from `frontend/`: `npx vitest run <path>`. Lint `npm run lint` (`--max-warnings 0`). Types `npx tsc --noEmit`.
- **Never fall back to client-side filtering.** The `useMemo` filter comes out; nothing replaces it.
- **Every test verified by breaking the thing it covers.** This repo has shipped five tests that guarded nothing, all in ordering and pagination code.
- **`GET /systems/` whitelists `name` alone.** `description`, `github_repository_url` and `actions` are all `sortable: false`, written literally, never computed from `isSortable`.
- The page uses **raw `DataGrid`**, so `disableColumnFilter` is required explicitly.
- `totalPending` gets `listLoading`; `debounceKeys: ['search']`, and every entry must also be in `filterKeys`.
- Conventional commits, one per task.

## Measured facts

Verified against the code and `App.tsx`, not inferred. (C2's plan had two wrong paths from guessing at names — routes and directories are checked here.)

**Routes:** `/systems` → `SystemCatalog`, `/systems/:id` → `SystemDetail` (`App.tsx:151-152`).

**Readers of `state.system.systems` — two, both the destructured form:**

| File | Line |
|---|---|
| `pages/systems/SystemCatalog.tsx` (the owner) | :70 |
| `pages/environments/EnvironmentDetail.tsx` | :108 |

There are **zero** property-form readers, which is why an earlier property-only grep found nothing here.

**Dispatchers of `fetchSystems()` — three:** `SystemCatalog.tsx:90`, `EnvironmentDetail.tsx:163`, `SystemDetail.tsx:297`.

**Direct callers of `systemService.listSystems()` — five components, plus the slice's thunk:**

| File | Line |
|---|---|
| `components/releases/ScopeWindowsTable.tsx` | :51 |
| `components/releases/ReleaseSystemsTab.tsx` | :62 |
| `pages/releases/ReleaseList.tsx` | :62 |
| `pages/incidents/IncidentForm.tsx` | :120 |
| `pages/incidents/IncidentList.tsx` | :183 |

Every one is `systemService.listSystems().then(setX).catch(() => setX([]))` — the own-fetch pattern, hand-rolled five times.

**Slice list surgery:** `systemSlice.ts:121` (`push`), `:135` (index assign), `:149` (`filter`).

**`SystemCatalog`:** raw `DataGrid`, three inline mutations, a `search` text filter, columns `name`, `description`, `github_repository_url`, `actions`.

## What makes this one different

**1. The service takes no params at all.**

```ts
listSystems: (): Promise<SystemResponse[]> => api.get('/systems/').then((r) => r.data),
```

Every other service in this programme had an existing param object to widen. This one needs a parameter *added*, a `params` object passed to `axios`, **and** the `Paged` return.

**2. Most consumers bypass the slice.** C1 and C2 moved slice *readers* onto a hook. Here only one reader is outside the owning page; the other five consumers already fetch for themselves — badly, five times over, each silently taking the endpoint's default limit.

**3. Three of four columns lose sorting.** `GET /systems/` whitelists `name` alone. `description` and `github_repository_url` are ordinary data columns, exactly the shape C2's `location` turned out to be: nothing about them looks unsortable, and marking one sortable 422s on first click. **Check the whitelist per column; do not infer from appearance.**

## Why the task order is what it is

Task 2 moves the five direct callers onto the hook **before** Task 3 changes the service's return type. Done in that order, the return-type change touches one file (the hook). Done the other way round, `tsc` would break all five call sites and each would get a separate `.rows` patch — five edits that Task 2 then deletes again.

---

### Task 1: a shared `useAllSystems()` hook

**Files:**
- Create: `frontend/src/hooks/useAllSystems.ts`
- Test: `frontend/src/hooks/__tests__/useAllSystems.test.tsx`

**Interfaces:**
- Consumes: `systemService.listSystems` as it exists today — **no arguments, bare array return**.
- Produces: `useAllSystems(): { systems: SystemResponse[]; loading: boolean; truncated: boolean }`.

Copy `frontend/src/hooks/useAllHosts.ts` and its test, adapting service, types and names. Do not redesign.

**The one difference:** `listSystems()` currently accepts no arguments, so you cannot pass an explicit `limit` yet. C1 and C2 both passed one and tied it by comment to the backend's `DEFAULT_LIMIT`. Here, either add a `limit?: number` param to the service now (the minimal widening C1 and C2 each needed for the same reason) or call it bare and note that Task 3 adds the limit. **Pick one, say which and why** — do not leave the hook silently relying on a server default it never states.

`truncated` returns a hardcoded `false` with a comment naming Task 3, exactly as both predecessors did. **No proxy** such as `rows.length === limit`.

- [ ] **Step 1:** Write the three tests (fetches once and returns rows; does **not** read or write the shared slice; a failed fetch yields an empty list).
- [ ] **Step 2:** Run — expect all three to fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run — expect pass. Then lint and `tsc`.
- [ ] **Step 5:** Discrimination check — make the hook read `useSelector((s: RootState) => s.system.systems)` instead of its own fetch; the slice-isolation test must fail. Restore.
- [ ] **Step 6:** Commit — `feat(systems): add useAllSystems for pickers`

---

### Task 2: move all six consumers onto the hook

Five hand-rolled local fetches plus one slice reader.

**Files:**

| File | What it does today |
|---|---|
| `components/releases/ScopeWindowsTable.tsx:51` | own fetch into local state |
| `components/releases/ReleaseSystemsTab.tsx:62` | own fetch into local state |
| `pages/releases/ReleaseList.tsx:62` | own fetch into local state |
| `pages/incidents/IncidentForm.tsx:120` | own fetch into local state |
| `pages/incidents/IncidentList.tsx:183` | own fetch into local state |
| `pages/environments/EnvironmentDetail.tsx:108,163` | reads the slice **and** dispatches `fetchSystems()` |

`SystemDetail.tsx:297` also dispatches `fetchSystems()`. Decide what to do with it and say why: it is not in the reader list, so it may be dispatching to populate a slice it never reads. Check before changing anything.

**Interfaces:**
- Consumes: Task 1's `useAllSystems()`.
- Produces: **nothing outside `SystemCatalog` reads the systems list, dispatches its thunk, or calls `listSystems()` directly.** Task 4 depends on that.

- [ ] **Step 1: Write the failing scan test**

Create `frontend/src/__tests__/systemSliceConsumers.test.ts` by copying `frontend/src/__tests__/infrastructureComponentSliceConsumers.test.ts`. Keep all of its properties:

- the **vacuity guard** (`files.length > 100`);
- **prefix-free patterns** — both were widened to accept any selector-parameter identifier after a review found `(ic: RootState) => ic.infrastructureComponent` slipping past; start widened;
- **newline-crossing** `\s*` between tokens, because the destructured form spans lines here — **both** readers of this slice use that form, so a single-line pattern would find nothing at all and the test would pass while guarding nothing.

Add a **fourth** pattern this slice needs and the previous two did not: `systemService\.listSystems\(`, to catch the five direct callers. A reader/dispatcher grep alone finds none of them.

Exclude only `SystemCatalog.tsx`, `systemSlice.ts`, the hook, and test files.

- [ ] **Step 2:** Run — expect FAIL listing all six (or seven, with `SystemDetail`).
- [ ] **Step 3:** Convert them. The five direct callers each lose a `useState` + `useEffect` + `.then/.catch` and gain one hook call. `EnvironmentDetail` loses both its selector and its dispatch.
- [ ] **Step 4:** Run — expect pass, plus the full suite.
- [ ] **Step 5:** Discrimination check — restore the direct `listSystems()` call in **one** component; the scan must fail naming that file. Restore.
- [ ] **Step 6:** Commit — `refactor(systems): move every consumer off the shared list and the direct service call`

---

### Task 3: service and slice return and store a page

**Files:**
- Modify: `frontend/src/services/systemService.ts:12`
- Modify: `frontend/src/store/systemSlice.ts`
- Modify: `frontend/src/hooks/useAllSystems.ts` (wire `truncated`)
- Test: `frontend/src/services/__tests__/systemServicePaged.test.ts` (create)

The service needs more than a widening — it needs a params argument it never had:

```ts
  listSystems: (params?: {
    search?: string;
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<SystemResponse>> =>
    api.get<SystemResponse[]>('/systems/', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
```

Check `GET /systems/`'s real signature before finalising that list — it should accept `search` plus the shared paging and sorting params, but verify rather than trusting this snippet.

For the slice, copy `frontend/src/store/infrastructureComponentSlice.ts`: `total`, `listLoading`, the three list-thunk cases, and the `action.meta.aborted` early return **verbatim including its comment**.

**Do not remove the three list surgeries** (`:121`, `:135`, `:149`) — Task 4 removes them with the `refetch()` that replaces them.

Wire `truncated` as `systems.length < total`, with a discriminating test.

**The third service test cannot fail at runtime** — a passthrough compares an object against itself; only `tsc`'s excess-property check guards it. Copy the honest comment from `infrastructureComponentServicePaged.test.ts`. **Do not invent a tautological runtime assertion.**

- [ ] **Step 1:** Write the three tests.
- [ ] **Step 2:** Run — expect the first two to fail.
- [ ] **Step 3:** Implement service, then slice.
- [ ] **Step 4:** Wire `truncated`, with a test verified to discriminate.
- [ ] **Step 5: The reader trap.** `grep -rnE "(s|state)\.system\b" frontend/src` and read every hit — remember both readers use the multi-line destructured form, so read files if in doubt. **If `SystemCatalog` reads `loading` for its list spinner, fix it here** with the two-line `listLoading` swap; that is not a conversion. This call has been made six times in this programme and every time the swap shipped in the task that caused the regression.
- [ ] **Step 6:** Fix whatever `tsc` reports, minimally. If Task 2 did its job this should be the hook and nothing else — **say so if it is not**, because a surprise here means a consumer was missed.
- [ ] **Step 7:** Full suite, lint, types, discrimination check, commit — `feat(systems): return and store a page, not a bare array`

---

### Task 4: convert `SystemCatalog`

**Files:**
- Modify: `frontend/src/pages/systems/SystemCatalog.tsx`
- Modify: `frontend/src/store/systemSlice.ts:121,135,149` (remove the surgery)
- Test: `frontend/src/pages/systems/__tests__/systemCatalogServerGrid.test.tsx` (create)

Follow `frontend/src/pages/infrastructure/InfrastructureComponentList.tsx` — same raw `DataGrid`, same text filter, same inline CRUD, converted one PR ago.

- [ ] **Step 1: Write the failing tests** — five:

```tsx
  it('sends paging, sorting and the search filter', async () => {
    renderCatalog('/systems?page=1&sort_by=name&sort_dir=desc&search=payments');
    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'name', sort_dir: 'desc', search: 'payments',
    }));
  });

  it('keeps the literal search term "all"', async () => {
    renderCatalog('/systems?search=all');
    await waitFor(() => expect(lastListParams()).toMatchObject({ search: 'all' }));
  });

  it('leaves only name sortable', () => {
    // GET /systems/ whitelists `name` ALONE. description and
    // github_repository_url are ordinary data columns that nonetheless 422
    // if marked sortable — the same shape as `location` on the hosts page.
    const byField = Object.fromEntries(systemColumns.map((c) => [c.field, c]));
    expect(byField.name.sortable).not.toBe(false);
    ['description', 'github_repository_url', 'actions'].forEach((f) =>
      expect(byField[f].sortable).toBe(false));
  });

  it('disables the column filter, which would filter only the loaded page', () => {
    renderCatalog('/systems');
    expect(gridProps().disableColumnFilter).toBe(true);
  });

  it('refetches after a delete instead of splicing the page', async () => {
    renderCatalog('/systems');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    await deleteFirstRow();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });
```

A DOM assertion on column sortability is **not achievable** — MUI virtualises columns by container width and jsdom reports zero width. Export the columns array and assert on it directly, as the previous three pages do. If this page has per-tenant custom-field columns, extract a builder and unit-test it.

- [ ] **Step 2:** Run — expect fail.
- [ ] **Step 3: Convert the page.**

```tsx
  const grid = useServerGrid({
    endpoint: 'systems',
    filterKeys: ['search'],
    debounceKeys: ['search'],
    onFetch: (params) => dispatch(fetchSystems(params)),
    total,
    totalPending: listLoading,
  });
```

**Bind the search box to `grid.filters`** — the draft-overlaid value `useServerGrid` returns. Binding to the raw URL state is what made typing `comp` leave `p` on an earlier PR, and no unit test asserting params-sent would catch it.

Delete the client-side `useMemo` filter. Remove the three slice surgeries and call `grid.refetch()` after each mutation — but **check where each is dispatched from first** (`grep -rn "createSystem(\|updateSystem(\|deleteSystem(" frontend/src`). On the previous two pages all three came from the page itself; on the bookings track a dialog child needed a callback. Establish the facts and report what you found for each.

Raw `DataGrid` server props as `InfrastructureComponentList` uses them, including `disableColumnFilter` and `pageSizeOptions={[10, 25, 50, 100]}`.

- [ ] **Step 4:** Run — expect pass.
- [ ] **Step 5: Four discrimination mutations**, each restored, all outputs reported: drop `search` from `filterKeys`; remove `search` from `debounceKeys` (the `'all'` test must fail); delete `sortable: false` from `description`; remove `disableColumnFilter`.
- [ ] **Step 6:** Full suite, lint, types, commit — `feat(systems): server-side paging, sorting and filtering on the catalog`

---

### Task 5: verify in a browser, document, and close out the programme

**This is the last page.** Five defects in this programme were found only by opening the page, every one with a green suite.

- [ ] **Step 1:** `cd frontend && npx vitest run && npm run lint && npx tsc --noEmit`
- [ ] **Step 2: Verify in the browser.** Backend on :8000, `npm run dev` on :5173, signed in as `admin`/`admin123` (tenant `demo`). At **`/systems`** (verified against `App.tsx:151`):
  - Grid renders, spinner clears, footer shows a server total.
  - **Only `name` offers a sort arrow.** `description`, `github_repository_url` and `actions` must not.
  - Type a multi-character term in the search box and confirm the whole term survives. If synthetic input does not reach the app (a known flakiness in this environment) **say so rather than implying it was checked**, and fall back to `?search=<term>` to verify the URL→input direction and that the footer total narrows.
  - `?search=all` returns results filtered on the literal term.
  - The column ⋮ menu offers **no Filter item**.
  - Create, edit and delete a system: each reflected without the row count drifting.
  - Then check the six consumers Task 2 moved — the scope-windows table, the release systems tab, the release list, and both incident surfaces — and confirm each still offers the full system list.
- [ ] **Step 3: Update `docs/pagination.md`** — **all eleven pages converted**. Close the C3 section: what the programme fixed, what it deliberately left, and the standing rules it produced (the five grep forms; check the sort whitelist per column; bind text boxes to the draft-aware value; a picker must not read a paged slice).
- [ ] **Step 4: Update `CLAUDE.md`'s header** — the pagination programme is complete. Record the remaining known gaps rather than implying none exist: `ScopeWindowsTable` still cannot be converted (it filters `window_status` and sorts `days_to_cutoff`, both computed in Python after the query), and the endpoints still listed as unbounded in `docs/pagination.md`.
- [ ] **Step 5:** Commit, push, open the PR.
- [ ] **Step 6:** Confirm all four CI jobs pass before reporting done.

---

## After this PR

The eleven-page rollout is finished. Recorded and deliberately **not** done:

- **`ScopeWindowsTable`** — a twelfth grid with the same client-side-filtering bug, unconvertible by this pattern because `window_status` and `days_to_cutoff` are computed in Python after the query. Needs those restructured into SQL first.
- **The endpoints still unbounded**, listed in `docs/pagination.md`'s "Not yet bounded" section.
- **`GET /releases/calendar` and `/releases/timeline`** still call `list_releases` with a hardcoded `limit=500` and discard the total.
