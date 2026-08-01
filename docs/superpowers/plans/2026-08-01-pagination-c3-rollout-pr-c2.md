# C3 Rollout — PR C2 (infrastructure-components) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `InfrastructureComponentList` to true server-side paging, sorting and filtering, after moving the four components that share its slice onto a picker hook of their own.

**Architecture:** Structurally identical to PR C1 (environments, merged as `52b878c`) at under half the scale. Same five moves: a shared picker hook, move the consumers, service returns `Paged<T>`, slice gains `total`/`listLoading`, page converted with its optimistic surgery replaced by `refetch()`.

**Tech Stack:** React 18 + TypeScript, Redux Toolkit, MUI DataGrid 6.20.4 Community, vitest + @testing-library/react.

## Read PR C1 first

This plan deliberately does not restate what C1 established. Before starting, read:

- `docs/superpowers/plans/2026-08-01-pagination-c3-rollout-pr-c1.md` — the same five tasks, one page earlier.
- `frontend/src/hooks/useAllEnvironments.ts` — the picker hook this PR's counterpart copies.
- `frontend/src/__tests__/environmentSliceConsumers.test.ts` — the source-scanning guard this PR's counterpart copies.
- `frontend/src/pages/environments/EnvironmentList.tsx` — the converted page, including `buildCustomFieldColumns()` and the raw-`DataGrid` server props.

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-01-pagination-c3-rollout-design.md`](../specs/2026-08-01-pagination-c3-rollout-design.md).
- Branch `feature/c3-rollout-pr-c2`, already created off `main` at `52b878c`.
- Tests from `frontend/`: `npx vitest run <path>`. Lint `npm run lint` (`--max-warnings 0`). Types `npx tsc --noEmit`.
- **Never fall back to client-side filtering.** The `useMemo` filter comes out; nothing replaces it.
- **Every test verified by breaking the thing it covers.** This repo has shipped five tests that guarded nothing, all in ordering and pagination code.
- `GET /infrastructure-components/` whitelists `name`, `component_type`, `provider`, `region`, `source`; default `name` asc. **`location` and `actions` are the only unsortable columns** — written literally, never computed from `isSortable`.
- The page uses **raw `DataGrid`**, so it needs `disableColumnFilter` explicitly. MUI gates the column-menu Filter item on that prop alone, not on toolbar presence; shipping without it was a regression caught in review on PR A.
- `totalPending` gets `listLoading`, never the shared `loading`.
- The page has a `search` box, so `debounceKeys: ['search']` — and every `debounceKeys` entry must also appear in `filterKeys`.
- Conventional commits, one per task.

## Measured facts

Gathered with the patterns that actually match (see the grep note below), not from memory.

**Readers of `state.infrastructureComponent.components` — four, all outside the owning page:**

| File | Line | Uses it for |
|---|---|---|
| `components/EnvSubsystemHostsDialog.tsx` | :50 | host picker |
| `pages/change-requests/ChangeRequestEditDialog.tsx` | :104 | host picker |
| `pages/change-requests/ChangeRequestList.tsx` | :144 | host **filter dropdown** |
| `pages/change-requests/ChangeRequestForm.tsx` | :132 | host picker |

**Dispatchers of `fetchInfrastructureComponents()` — the same four, plus the owning page** at `pages/infrastructure/InfrastructureComponentList.tsx:83`.

**No component calls `infrastructureComponentService.listComponents()` directly** — only the slice's thunk does.

**Slice list surgery** at `infrastructureComponentSlice.ts:80` (`push`), `:84` (index assign), `:87` (`filter`).

**The owning page** reads `const { components, loading, error } = useSelector(...)` at `InfrastructureComponentList.tsx:69` — note this is **destructured across two lines**.

## The grep note that keeps mattering

Consumer sweeps in this programme have been wrong three times. The forms to cover:

```
(s|state)\.infrastructureComponent\.components        property read, either param name
{ components } = useSelector(...)                     destructured — and it may span lines
fetchInfrastructureComponents(                         a WRITER, invisible to any reader grep
infrastructureComponentService\.listComponents(        a direct service call, bypassing the slice
```

The owning page's own selector is the two-line destructured form, which a single-line grep misses. C1's scan test handles this correctly because its pattern uses `\s*` between tokens, which crosses newlines — copy that, do not rewrite it tighter.

---

### Task 1: a shared `useAllHosts()` hook

Four components want "every infrastructure component, for a picker". C1 built `useAllEnvironments()` for the same reason at nine consumers; a review noted at three copies that a fourth gets written by copy-paste and drifts. This is that fourth.

**Files:**
- Create: `frontend/src/hooks/useAllHosts.ts`
- Test: `frontend/src/hooks/__tests__/useAllHosts.test.tsx`

**Interfaces:**
- Consumes: `infrastructureComponentService.listComponents` as it exists today — still a bare array until Task 3.
- Produces: `useAllHosts(): { hosts: InfrastructureComponentResponse[]; loading: boolean; truncated: boolean }`.

Copy `frontend/src/hooks/useAllEnvironments.ts` and its test almost verbatim — same shape, same `LIMIT` tied by comment to the backend's `DEFAULT_LIMIT`, same three tests (fetches once and returns rows; does **not** read or write the shared slice; a failed fetch yields an empty list).

`truncated` cannot be computed until Task 3 makes the service return `total`. Return `false` with a comment naming Task 3, exactly as `useAllEnvironments` did. **Do not invent a proxy** such as `rows.length === limit` — it is wrong the moment a tenant's count lands on the limit, and C1 rejected it explicitly.

**Name it for what callers call these things.** Every consumer names the variable `hosts` (or `allHosts`), not `components`, so `useAllHosts` returning `hosts` reads correctly at the call sites. Say in your report if you find that misleading against the slice's own naming.

- [ ] **Step 1:** Write the three tests (copy `useAllEnvironments.test.tsx`, adapt names/service).
- [ ] **Step 2:** Run — expect all three to fail (module does not exist).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run — expect pass. Then lint and `tsc`.
- [ ] **Step 5:** Discrimination check — make the hook read `useSelector((s: RootState) => s.infrastructureComponent.components)` instead of its own fetch; the first two tests must fail. Restore.
- [ ] **Step 6:** Commit — `feat(infrastructure): add useAllHosts for pickers`

---

### Task 2: move the four consumers onto the hook

**Files:** the four listed under *Measured facts*, plus a new scan test.

**Interfaces:**
- Consumes: Task 1's `useAllHosts()`.
- Produces: **nothing outside `InfrastructureComponentList` reads or dispatches the component list.** Task 4 depends on that holding.

**Two files need care:**

- **`ChangeRequestList`** is an already-converted page. It reads this slice for its **host filter dropdown**, which is the picker case, so it moves onto the hook. It also uses `useAllEnvironments()` from C1 — leave that alone.
- **`ChangeRequestForm` and `ChangeRequestEditDialog`** likewise already use `useAllEnvironments()`. Only their host read moves.

Where a component shows a picker the user chooses from, surface truncation if the hook reports it — match how C1's pickers do it. (`truncated` is always `false` until Task 3, so this is wiring ahead.)

- [ ] **Step 1: Write the failing scan test**

Create `frontend/src/__tests__/infrastructureComponentSliceConsumers.test.ts` by copying `environmentSliceConsumers.test.ts` and adapting the patterns. Keep both of its properties:

- the **vacuity guard** (`files.length > 100`) — without it a broken file-walk makes the test pass while scanning nothing;
- the **prefix-free** property-read pattern. C1's first pattern originally required the selector parameter to be named `s` or `state` and was widened afterwards, because `(ic: RootState) => ic.infrastructureComponent.components` would have slipped through. Start widened.

Exclude only: `InfrastructureComponentList.tsx`, `infrastructureComponentSlice.ts`, the hook itself, and test files. An over-broad exclusion list lets a real straggler through.

- [ ] **Step 2:** Run — expect FAIL listing all four files.
- [ ] **Step 3:** Convert the four. Delete the `useSelector`, delete the `dispatch(fetchInfrastructureComponents())`, call `useAllHosts()`. Watch for a component that ends up calling the hook *and* keeping its dispatch — that is a double fetch.
- [ ] **Step 4:** Run — expect pass, plus the full suite.
- [ ] **Step 5:** Discrimination check — restore the `useSelector` in **one** component; the scan test must fail naming that file. Restore.
- [ ] **Step 6:** Commit — `refactor(infrastructure): move every picker off the shared list slice`

---

### Task 3: service and slice return and store a page

**Files:**
- Modify: `frontend/src/services/infrastructureComponentService.ts:14-21` (`listComponents`)
- Modify: `frontend/src/store/infrastructureComponentSlice.ts`
- Modify: `frontend/src/hooks/useAllHosts.ts` (wire `truncated`)
- Test: `frontend/src/services/__tests__/infrastructureComponentServicePaged.test.ts` (create)

`listComponents` takes an **inline literal param type** and passes params straight to axios — no mapping layer, so widening the literal is the change. It already has `component_type`, `provider`, `region`, `source`, `search`; add `limit`, `offset`, `sort_by`, `sort_dir`, and return `Paged<InfrastructureComponentResponse>`.

For the slice, copy `frontend/src/store/environmentSlice.ts`: `total`, `listLoading`, the three list-thunk cases, and the `action.meta.aborted` early return **verbatim including its comment**.

**Do not remove the three list surgeries** (`:80`, `:84`, `:87`) — Task 4 removes them with the `refetch()` that replaces them.

Wire `truncated` as `hosts.length < total` once the service returns a total, with a test verified to discriminate. C1's picker copy says "Only the first N of TOTAL shown" once a total exists — match it.

**The third service test cannot fail at runtime.** `listComponents` is a passthrough, so an assertion that the params reached axios compares an object against itself; its only guard is TypeScript's excess-property check under `tsc`. Copy the honest comment from `environmentServicePaged.test.ts`. **Do not invent a tautological runtime assertion.**

- [ ] **Step 1:** Write three tests (rows+total from `X-Total-Count`; fallback to row count when absent; params forwarded).
- [ ] **Step 2:** Run — expect the first two to fail.
- [ ] **Step 3:** Implement service, then slice.
- [ ] **Step 4:** Wire `truncated` in the hook, with a discriminating test.
- [ ] **Step 5: The reader trap.** Run `grep -rnE "(s|state)\.infrastructureComponent\b" frontend/src` and read every hit. **If `InfrastructureComponentList` reads `loading` for its list spinner, fix it here** with the two-line `listLoading` swap — that is not a conversion. That call has been made five times in this programme and every time the swap shipped in the task that caused the regression. Report every hit.
- [ ] **Step 6:** Fix whatever `tsc` reports from the return-type change, minimally, and say what you changed.
- [ ] **Step 7:** Full suite, lint, types, discrimination check, commit — `feat(infrastructure): return and store a page, not a bare array`

---

### Task 4: convert `InfrastructureComponentList`

Second page in the programme with **both** a text filter and inline create/update/delete. C1's `EnvironmentList` was the first — read it and follow it.

**Files:**
- Modify: `frontend/src/pages/infrastructure/InfrastructureComponentList.tsx`
- Modify: `frontend/src/store/infrastructureComponentSlice.ts:80,84,87` (remove the surgery)
- Test: `frontend/src/pages/infrastructure/__tests__/infraComponentListServerGrid.test.tsx` (create)

- [ ] **Step 1: Write the failing tests** — five, mirroring `environmentListServerGrid.test.tsx`:

```tsx
  it('sends paging, sorting and both filters', async () => {
    renderList('/infrastructure-components?page=1&sort_by=provider&sort_dir=desc&search=db&component_type=host');
    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'provider', sort_dir: 'desc', search: 'db', component_type: 'host',
    }));
  });

  it('keeps the literal search term "all"', async () => {
    // 'all' is the selects' no-selection sentinel; in a text box it is a real
    // search term. Dropping it returns unfiltered results while the box reads
    // "all". Only pages with a text filter can exercise this.
    renderList('/infrastructure-components?search=all');
    await waitFor(() => expect(lastListParams()).toMatchObject({ search: 'all' }));
  });

  it('marks location and actions unsortable', () => {
    // GET /infrastructure-components/ whitelists name, component_type,
    // provider, region, source. `location` is a real column that is NOT
    // whitelisted — a sortable header on it 422s on first click.
    const byField = Object.fromEntries(infraComponentColumns.map((c) => [c.field, c]));
    ['name', 'component_type', 'provider', 'region', 'source'].forEach((f) => expect(byField[f].sortable).not.toBe(false));
    expect(byField.location.sortable).toBe(false);
    expect(byField.actions.sortable).toBe(false);
  });

  it('disables the column filter, which would filter only the loaded page', () => {
    renderList('/infrastructure-components');
    expect(gridProps().disableColumnFilter).toBe(true);
  });

  it('refetches after a delete instead of splicing the page', async () => {
    renderList('/infrastructure-components');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    await deleteFirstRow();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });
```

`location` is the one to watch — it is a real, visible column that the backend does not whitelist, unlike the other pages where the unsortable columns were obviously computed or joined.

C1 found that a DOM assertion on column sortability is **not achievable** (MUI virtualises columns by container width; jsdom reports zero width), and solved it by exporting the columns array and asserting on it directly. Do the same. If this page has per-tenant custom-field columns, extract a builder and unit-test it as `EnvironmentList`/`BookingList` do.

- [ ] **Step 2:** Run — expect fail.
- [ ] **Step 3: Convert the page.**

```tsx
  const grid = useServerGrid({
    endpoint: 'infrastructure-components',
    filterKeys: ['search', 'component_type'],
    debounceKeys: ['search'],
    onFetch: (params) => dispatch(fetchInfrastructureComponents(params)),
    total,
    totalPending: listLoading,
  });
```

**Bind the search box to `grid.filters`**, which `useServerGrid` returns as the draft-overlaid value. Binding to the raw URL state is what made typing `comp` leave `p` on PR A, and **no unit test asserting params-sent would catch it**.

Delete the client-side `useMemo` filter. Remove the three slice surgeries and call `grid.refetch()` after each mutation instead — but **check where each is dispatched from first**. On C1 all three came from the page itself; on the bookings track a dialog child co-mounted with the list and needed an `onCreated` callback. Establish the facts (`grep -rn "createComponent(\|updateComponent(\|deleteComponent(" frontend/src`) and report what you found for each.

Raw `DataGrid` server props exactly as `EnvironmentList` uses them, including `disableColumnFilter` and `pageSizeOptions={[10, 25, 50, 100]}`.

- [ ] **Step 4:** Run — expect pass.
- [ ] **Step 5: Four discrimination mutations**, each restored, all outputs reported: drop `search` from `filterKeys`; remove `search` from `debounceKeys` (the `'all'` test must fail); delete `sortable: false` from `location`; remove `disableColumnFilter`.
- [ ] **Step 6:** Full suite, lint, types, commit — `feat(infrastructure): server-side paging, sorting and filtering on the list`

---

### Task 5: verify in a browser, document, and open the PR

Five defects in this programme have been found only by opening the page, every one with a green suite.

- [ ] **Step 1:** `cd frontend && npx vitest run && npm run lint && npx tsc --noEmit`
- [ ] **Step 2: Verify in the browser.** With `docker-compose up -d`, backend on :8000, `npm run dev` on :5173, signed in as `admin`/`admin123` (tenant `demo`), on `/infrastructure-components`:
  - Grid renders, spinner clears, footer shows a server total.
  - Sortable headers are **exactly** `name`, `component_type`, `provider`, `region`, `source` — `location` and `actions` offer no sort arrow.
  - Type a multi-character term into the search box and confirm **the whole term survives**. If synthetic input does not reach the app (a known flakiness in this environment) say so rather than implying it was checked, and fall back to `?search=<term>` to verify the URL→input direction and that the footer total narrows.
  - `?search=all` returns results filtered on the literal term rather than unfiltered.
  - The column ⋮ menu offers **no Filter item**.
  - Create, edit and delete a component: each reflected without the row count drifting and without a row appearing that the active filter excludes.
  - Then check the four pickers Task 2 moved — the hosts dialog and the three change-request surfaces — and confirm each still offers the full list.
- [ ] **Step 3:** Update `docs/pagination.md` — ten of eleven pages converted, one remaining (systems), and what C2 confirmed or contradicted from C1.
- [ ] **Step 4:** Commit, push, open the PR.
- [ ] **Step 5:** Confirm all four CI jobs pass before reporting done.

---

## What this plan does not cover

**C3 — systems**, the last page, and a different problem from C1/C2:

- `systemService.listSystems()` takes **no params argument at all** — it needs both a signature and a `Paged` return.
- **Five components call it directly** into local state (`ScopeWindowsTable`, `ReleaseSystemsTab`, `ReleaseList`, `IncidentList`, `IncidentForm`); every one breaks on the return-type change, which `tsc` will catch. That is a different shape from C1/C2, where consumers went through the slice.
- Only two components read the slice (`SystemCatalog`, `EnvironmentDetail`).
- `GET /systems/` whitelists **`name` alone**, so almost every column on `SystemCatalog` becomes unsortable — the largest sortability reduction in the programme.

**`ScopeWindowsTable`** remains unconvertible by this pattern: it filters `window_status` and sorts `days_to_cutoff`, both computed in Python after the query. Converting it needs those restructured into SQL first.
