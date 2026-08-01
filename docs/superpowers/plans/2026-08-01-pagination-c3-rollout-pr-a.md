# C3 Rollout — PR A (DeploymentList, BuildList) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the two smallest list pages to true server-side paging, sorting and filtering, proving the prep PR's pattern repeats before the harder six pages copy it.

**Architecture:** Frontend only. Each page follows the same four moves: its service returns `Paged<T>` instead of a bare array, its slice stores `total` and `listLoading`, its page drives a `useServerGrid` instead of a local `useMemo` filter, and its grid runs in server mode. No backend changes — every filter these pages offer already has a server parameter.

**Tech Stack:** React 18 + TypeScript, Redux Toolkit, MUI DataGrid 6.20.4 Community, vitest + @testing-library/react, react-router-dom 7.18.2.

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-01-pagination-c3-rollout-design.md`](../specs/2026-08-01-pagination-c3-rollout-design.md). Prep PR: #41, branch `feature/c3-rollout-prep`.
- **This plan assumes PR #41 is merged to `main`.** It depends on `textKeys`, `refetch()`, `totalPending` and the `debounceKeys ⊆ filterKeys` DEV warning. Branch from `main` after #41 lands; do not stack.
- Tests run from `frontend/`: `npx vitest run <path>`. Whole suite: `npx vitest run`. Lint: `npm run lint` (`--max-warnings 0`). Types: `npx tsc --noEmit`.
- **Never fall back to client-side filtering.** A page that quietly filters a truncated set is the bug this programme removes. The `useMemo` filters come out; nothing replaces them.
- **Every test must be verified by breaking the thing it covers and confirming it fails.** This repo has shipped five tests that guarded nothing, all in ordering and pagination code. A green run is not evidence on its own.
- `sort_dir` is always sent alongside `sort_by`. Both these endpoints declare `default_dir="desc"`, so an omitted direction makes a first header click descending.
- A column not in its endpoint's whitelist gets `sortable: false`. A sortable header the server 422s on is worse than no header.
- Conventional commits. Commit at the end of each task.

## Two decisions already made

**These pages keep raw `DataGrid`; they are not migrated to `DataTable`.** `DataTable`'s server-mode additions exist to stop a *toolbar* lying — it disables the column filter and suppresses CSV/Print export, because those act on the loaded page while the footer shows the true server total. Neither of these pages renders a toolbar, so those guards buy nothing, and migrating would *add* a toolbar as a side effect of a pagination change. `DataTable`'s other server-mode guard (skipping the forced `initialState` `pageSize: 25`) is moot here too, because `useServerGrid` supplies a controlled `paginationModel`, which takes precedence over `initialState` either way.

The cost of this decision is that these two pages diverge from the other six, which do use `DataTable`. That is recorded deliberately: converting them to `DataTable` is a UI change that deserves its own decision, not a rider on this one.

**`BuildList`'s "Branch" filter stays an exact match.** `backend/app/api/v1/builds.py:83-84` is `Build.git_branch == branch`, not a contains-search. Typing `ma` for `main` returns nothing today and will still return nothing. That is pre-existing, is not what this PR is fixing, and turning it into a search is a backend change. Debounce it — currently it fires a request per keystroke — but do not change its semantics.

---

### Task 1: `deploymentService` and `deploymentSlice` return and store a page

The service currently ends `.then((r) => r.data)`, discarding `X-Total-Count`. Its `toParams` is a **whitelist that silently drops anything it does not name** — including `sort_by`, `sort_dir`, `environment_search` and `release_search`. That is the trap in this task: leave it as-is and the grid renders a sort arrow over data the server never sorted, with no error anywhere.

**Files:**
- Modify: `frontend/src/services/deploymentService.ts:9-25`
- Modify: `frontend/src/types/deployment.ts` (the `DeploymentFilters` type)
- Modify: `frontend/src/store/deploymentSlice.ts`
- Test: `frontend/src/services/__tests__/deploymentServicePaged.test.ts` (create)

**Interfaces:**
- Consumes: `Paged<T>` from `frontend/src/types/pagination.ts` (added by the pilot); `releaseService.list` in `frontend/src/services/releaseService.ts` is the reference implementation.
- Produces: `deploymentService.list(filters)` resolves `Paged<Deployment>`. `DeploymentState` gains `total: number` and `listLoading: boolean`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/services/__tests__/deploymentServicePaged.test.ts`. Model it on `frontend/src/services/__tests__/releaseServicePaged.test.ts` — read that file first and match its mock style (`vi.mock('../api', ...)`, `const mockGet = vi.mocked(api.get)`, `beforeEach(() => mockGet.mockReset())`).

```ts
  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }],
      headers: { 'x-total-count': '412' },
    });

    const result = await deploymentService.list({});

    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(412);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await deploymentService.list({})).total).toBe(1);
  });

  it('forwards the sort and search params the grid depends on', async () => {
    // toParams is a whitelist. Anything it does not name is dropped in
    // silence — so an unforwarded sort_by renders a sort arrow over data the
    // server never ordered, with no error to notice.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await deploymentService.list({
      limit: 25,
      offset: 50,
      sort_by: 'deployer_name',
      sort_dir: 'asc',
      environment_search: 'prod',
      release_search: 'mortgage',
      status: 'success',
    });

    expect(mockGet).toHaveBeenCalledWith('/deployments', {
      params: {
        limit: 25,
        offset: 50,
        sort_by: 'deployer_name',
        sort_dir: 'asc',
        environment_search: 'prod',
        release_search: 'mortgage',
        status: 'success',
      },
    });
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd frontend && npx vitest run src/services/__tests__/deploymentServicePaged.test.ts
```

Expected: all three FAIL — the first two because `list` resolves a bare array so `result.rows` is `undefined`, the third because `toParams` drops the four unknown keys.

- [ ] **Step 3: Widen the filter type**

In `frontend/src/types/deployment.ts`, add to `DeploymentFilters`:

```ts
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  environment_search?: string;
  release_search?: string;
```

`limit` and `offset` are already there.

- [ ] **Step 4: Implement the service**

In `frontend/src/services/deploymentService.ts`, add the four new keys to `toParams` in the same style as the existing ones, and change `list`:

```ts
  list: (filters?: DeploymentFilters): Promise<Paged<Deployment>> =>
    api.get<Deployment[]>('/deployments', { params: toParams(filters) }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
```

Import `Paged` from `../types/pagination`.

Leave `forEnvironment` alone — `GET /environments/{id}/deployments` is a different, still-unbounded endpoint and is out of scope.

- [ ] **Step 5: Update the slice**

In `frontend/src/store/deploymentSlice.ts`, add `total: number` and `listLoading: boolean` to the state interface and `total: 0, listLoading: false` to `initialState`. Change the three `fetchDeployments` cases so they write `listLoading` (not the shared `loading`) and store the page:

```ts
      .addCase(fetchDeployments.pending, (state) => { state.listLoading = true; state.error = null; })
      .addCase(fetchDeployments.fulfilled, (state, action) => {
        state.listLoading = false;
        state.items = action.payload.rows;
        state.total = action.payload.total;
      })
      .addCase(fetchDeployments.rejected, (state, action) => {
        // useServerGrid aborts a superseded request rather than ignoring its
        // reply. RTK dispatches `pending` for the new request synchronously,
        // then `rejected` for the aborted one on a microtask — without this
        // guard the spinner flickers off and `error` is set to 'Aborted'
        // while the real request is still in flight.
        if (action.meta.aborted) return;
        state.listLoading = false;
        state.error = action.error.message ?? 'Failed to load deployments';
      })
```

Every other thunk in the slice keeps writing `loading`. Copy the abort guard exactly — it is why `listLoading` exists.

- [ ] **Step 6: Fix any other consumer the type change breaks**

`tsc` will name them. `fetchDeployments`'s payload type changes from `Deployment[]` to `Paged<Deployment>`, so anything reading `action.payload` as an array needs `.rows`. Run `npx tsc --noEmit` and fix what it reports.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cd frontend && npx vitest run src/services/__tests__/deploymentServicePaged.test.ts && npx tsc --noEmit
```

Expected: 3 passed, tsc clean.

- [ ] **Step 8: Verify the tests discriminate**

Temporarily delete the `sort_by` line from `toParams` and re-run. Expected: `forwards the sort and search params` FAILS. Restore it.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/services/deploymentService.ts frontend/src/types/deployment.ts frontend/src/store/deploymentSlice.ts frontend/src/services/__tests__/deploymentServicePaged.test.ts
git commit -m "feat(deployments): return and store a page, not a bare array"
```

---

### Task 2: convert `DeploymentList`

**Files:**
- Modify: `frontend/src/pages/deployments/DeploymentList.tsx`
- Test: `frontend/src/pages/deployments/__tests__/deploymentListServerGrid.test.tsx` (create)

**Interfaces:**
- Consumes: Task 1's `Paged<Deployment>` service and the slice's `total`/`listLoading`. `useServerGrid` and `isSortable` from `frontend/src/hooks/`.
- Produces: nothing later tasks depend on.

**Corrected before execution.** This section originally claimed a planning sweep had found no consumers of `state.deployment` outside `pages/deployments/`. **That was wrong.** The sweep grepped `state\.deployment`, but these selectors are written `(s: RootState) => s.deployment` — the parameter is named `s`, not `state`, so the pattern matched nothing. Grep the slice *name*, not a guessed parameter name.

There are two other consumers, and they are not passive readers:

- `frontend/src/components/releases/ReleaseDeploymentsTab.tsx:18`
- `frontend/src/pages/environments/EnvironmentDeploymentsTab.tsx:18`

Each dispatches `fetchDeployments({ release_id })` / `({ environment_id })` on mount **and** reads the shared `items`, then client-side filters it by that id. So they write the same array this page is about to page and sort, and they are themselves unconverted client-side-filtering grids sharing a slice with a converted one.

Task 1 already repaired the half of this that was a live regression: both tabs now read `listLoading`, so their spinners work again.

What remains is coupling, not breakage, and this task must **not** try to fix it: each tab refetches on mount and defensively re-filters by id, so the rows it displays stay correct. What changes is that the shared array is now a 25-row sorted page between a tab's mount and its own fetch resolving. Record it in Task 5's docs update as a follow-on — the honest fix is for each tab to hold its own state rather than share the slice, which is the same fix three release-slice consumers received, and it belongs in its own change.

**Still grep before you convert**, with a pattern that will actually match: `grep -rnE "s\.deployment|state\.deployment" frontend/src`. If you find a consumer beyond the two named above, stop and report it rather than converting silently.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/deployments/__tests__/deploymentListServerGrid.test.tsx`. Two properties matter, and both must fail before the change:

```tsx
  it('sends paging, sorting and both filter params to the server', async () => {
    // The whole point of the conversion: filtering happens in SQL, not in a
    // useMemo over whatever page happened to arrive.
    renderDeploymentList('/deployments?page=1&sort_by=deployer_name&sort_dir=asc&environment_search=prod');

    await waitFor(() => expect(dispatchedParams()).toMatchObject({
      limit: 25,
      offset: 25,
      sort_by: 'deployer_name',
      sort_dir: 'asc',
      environment_search: 'prod',
    }));
  });

  it('marks joined and derived columns unsortable', () => {
    // GET /deployments whitelists status, deployer_name and deployed_at only.
    // A sortable header on anything else is a 422 the moment a user clicks it.
    const byField = Object.fromEntries(deploymentColumns.map((c) => [c.field, c]));

    expect(byField.status.sortable).not.toBe(false);
    expect(byField.deployer_name.sortable).not.toBe(false);
    expect(byField.deployed_at.sortable).not.toBe(false);

    expect(byField.environment_name.sortable).toBe(false);
    expect(byField.build_sha_short.sortable).toBe(false);
    expect(byField.release_name.sortable).toBe(false);
    expect(byField.change_request_title.sortable).toBe(false);
  });
```

Write `renderDeploymentList(url)` as a local helper that renders the page inside a `MemoryRouter` at `url` and a real store with a mocked `deploymentService`, and `dispatchedParams()` returning the params the mocked `list` was last called with. Follow the store-building style in `frontend/src/pages/releases/__tests__/`.

The second test requires the columns to be exported. Extract the `cols` array to a module-level `export const deploymentColumns` in `DeploymentList.tsx` (the pilot did the same for releases, in `releaseColumns.tsx`) — a separate file is not needed at this size.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd frontend && npx vitest run src/pages/deployments/__tests__/deploymentListServerGrid.test.tsx
```

Expected: both FAIL — the first because the page dispatches only `{ status }` and never `limit`/`offset`/`sort_by`, the second because `deploymentColumns` does not exist yet.

- [ ] **Step 3: Convert the page**

Replace the local filter state, the `filters` memo, the fetch effect and the `filteredItems` memo with `useServerGrid`:

```tsx
  const { items, total, listLoading } = useSelector((s: RootState) => s.deployment);

  const grid = useServerGrid({
    endpoint: 'deployments',
    filterKeys: ['status', 'environment_search', 'release_search'],
    // Free-text keys. This list is also the 'all'-sentinel exemption list —
    // every entry must appear in filterKeys above.
    debounceKeys: ['environment_search', 'release_search'],
    onFetch: (params) => dispatch(fetchDeployments(params)),
    total,
    totalPending: listLoading,
  });
```

The three inputs read from and write to `grid.filters` / `grid.setFilter` instead of local `useState`. The Status select keeps `''` as its "Any" value — `buildParams` drops `''` for every key, so it needs no sentinel handling.

`rows` maps `items` directly, with no `.filter()` anywhere.

Mark the four unsortable columns explicitly. Do not compute this from `isSortable` at render time — write it out, so the test above reads a static array and a mismatch is a test failure rather than a tautology:

```tsx
    { field: 'environment_name', headerName: 'Environment', width: 180, sortable: false },
```

Put the grid in server mode:

```tsx
        <DataGrid
          rows={rows}
          columns={deploymentColumns}
          autoHeight
          loading={listLoading}
          rowCount={total}
          paginationMode="server"
          sortingMode="server"
          paginationModel={grid.paginationModel}
          onPaginationModelChange={grid.onPaginationModelChange}
          sortModel={grid.sortModel}
          onSortModelChange={grid.onSortModelChange}
          pageSizeOptions={[10, 25, 50, 100]}
          onRowClick={(p: GridRowParams) => navigate(`/deployments/${p.id}`)}
          disableRowSelectionOnClick
        />
```

`pageSizeOptions` must be exactly `[10, 25, 50, 100]` — it mirrors `ALLOWED_PAGE_SIZES` in `useServerGrid.ts`, and a `page_size` outside the options renders a blank page-size select.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd frontend && npx vitest run src/pages/deployments/__tests__/deploymentListServerGrid.test.tsx
```

Expected: both PASS.

- [ ] **Step 5: Verify the tests discriminate**

Two mutations, each restored afterwards:

1. Remove `sort_by` from the params `useServerGrid` sends (temporarily hard-code `sortBy: null` at the call site or drop it in `buildParams`). Expected: the first test FAILS.
2. Delete `sortable: false` from `environment_name`. Expected: the second test FAILS.

Report both failing outputs. If either mutation leaves the tests green, the test is not measuring what it claims and must be rewritten before you continue.

- [ ] **Step 6: Run the full suite, lint and types**

```bash
cd frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/deployments/
git commit -m "feat(deployments): server-side paging, sorting and filtering on the list"
```

---

### Task 3: `buildService` and `buildSlice` return and store a page

Identical shape to Task 1. `buildService`'s `toParams` is the same kind of silent whitelist and drops `sort_by`, `sort_dir` and `subsystem_search`.

**Files:**
- Modify: `frontend/src/services/buildService.ts:5-20`
- Modify: `frontend/src/types/build.ts` (the `BuildFilters` type)
- Modify: `frontend/src/store/buildSlice.ts`
- Test: `frontend/src/services/__tests__/buildServicePaged.test.ts` (create)

**Interfaces:**
- Consumes: `Paged<T>` from `frontend/src/types/pagination.ts`.
- Produces: `buildService.list(filters)` resolves `Paged<Build>`. `BuildState` gains `total` and `listLoading`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/services/__tests__/buildServicePaged.test.ts`, same structure as Task 1's, with the build endpoint's own params:

```ts
  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }],
      headers: { 'x-total-count': '208' },
    });

    const result = await buildService.list({});

    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(208);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await buildService.list({})).total).toBe(1);
  });

  it('forwards the sort and search params the grid depends on', async () => {
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await buildService.list({
      limit: 25,
      offset: 25,
      sort_by: 'git_branch',
      sort_dir: 'asc',
      subsystem_search: 'auth',
      branch: 'main',
    });

    expect(mockGet).toHaveBeenCalledWith('/builds', {
      params: {
        limit: 25,
        offset: 25,
        sort_by: 'git_branch',
        sort_dir: 'asc',
        subsystem_search: 'auth',
        branch: 'main',
      },
    });
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd frontend && npx vitest run src/services/__tests__/buildServicePaged.test.ts
```

Expected: all three FAIL.

- [ ] **Step 3: Widen the filter type**

In `frontend/src/types/build.ts`, add to `BuildFilters`:

```ts
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  subsystem_search?: string;
```

- [ ] **Step 4: Implement the service**

Add the three keys to `toParams`, and:

```ts
  list: (filters?: BuildFilters): Promise<Paged<Build>> =>
    api.get<Build[]>('/builds', { params: toParams(filters) }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
```

- [ ] **Step 5: Update the slice**

Same as Task 1 Step 5, against `frontend/src/store/buildSlice.ts` and its `fetchBuilds` cases: add `total` and `listLoading`, move the three `fetchBuilds` cases onto `listLoading`, keep the `action.meta.aborted` early return, leave every other thunk on `loading`.

- [ ] **Step 6: Run the tests and types**

```bash
cd frontend && npx vitest run src/services/__tests__/buildServicePaged.test.ts && npx tsc --noEmit
```

Expected: 3 passed, tsc clean (fix any consumer the payload type change breaks).

- [ ] **Step 7: Verify the tests discriminate**

Temporarily delete the `subsystem_search` line from `toParams` and re-run. Expected: `forwards the sort and search params` FAILS. Restore it.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/services/buildService.ts frontend/src/types/build.ts frontend/src/store/buildSlice.ts frontend/src/services/__tests__/buildServicePaged.test.ts
git commit -m "feat(builds): return and store a page, not a bare array"
```

---

### Task 4: convert `BuildList`

`BuildList` has one column the other page does not: `latest_step` is computed **in the browser** from each row's `pipeline_steps` JSON. It can never be sorted server-side, so it gets the `ComputedColumnHeader` the pilot built for exactly this — a header whose tooltip explains why the column is not sortable, rather than a silently dead header.

**Files:**
- Modify: `frontend/src/pages/builds/BuildList.tsx`
- Test: `frontend/src/pages/builds/__tests__/buildListServerGrid.test.tsx` (create)

**Interfaces:**
- Consumes: Task 3's service and slice; `useServerGrid`; `ComputedColumnHeader` from `frontend/src/components/`.
- Produces: nothing later tasks depend on.

**Before you start:** grep for consumers of the build slice — `grep -rnE "s\.build\b|state\.build\b" frontend/src`. Note the pattern: these selectors are written `(s: RootState) => s.build`, so a grep for `state\.build` alone matches nothing. That mistake is why Task 2's original consumer sweep was wrong.

Re-verified with the corrected pattern, this slice is genuinely clean: the only consumer outside `pages/builds/` is `frontend/src/pages/deployments/DeploymentDetail.tsx:39`, and it reads `s.build.current` — a single fetched build — not the `items` array this task converts. Nothing else shares the list.

Confirm that yourself rather than taking it on trust, and report anything beyond it instead of converting silently.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/builds/__tests__/buildListServerGrid.test.tsx`, mirroring Task 2's helper style:

```tsx
  it('sends paging, sorting and the subsystem search to the server', async () => {
    renderBuildList('/builds?page=2&sort_by=git_branch&sort_dir=asc&subsystem_search=auth');

    await waitFor(() => expect(dispatchedParams()).toMatchObject({
      limit: 25,
      offset: 50,
      sort_by: 'git_branch',
      sort_dir: 'asc',
      subsystem_search: 'auth',
    }));
  });

  it('marks joined, derived and computed columns unsortable', () => {
    // GET /builds whitelists git_branch, build_number and commit_timestamp only.
    const byField = Object.fromEntries(buildColumns.map((c) => [c.field, c]));

    expect(byField.git_branch.sortable).not.toBe(false);
    expect(byField.build_number.sortable).not.toBe(false);
    expect(byField.commit_timestamp.sortable).not.toBe(false);

    expect(byField.subsystem_name.sortable).toBe(false);
    expect(byField.git_sha_short.sortable).toBe(false);
    expect(byField.release_name.sortable).toBe(false);
    expect(byField.latest_step.sortable).toBe(false);
  });

  it('explains why the computed column cannot be sorted', () => {
    // latest_step is derived in the browser from pipeline_steps. A header that
    // simply stops working reads as a bug; this one says why.
    const latestStep = buildColumns.find((c) => c.field === 'latest_step');
    expect(latestStep?.renderHeader).toBeDefined();
  });
```

Export the columns as `export const buildColumns` from `BuildList.tsx`, as Task 2 did.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd frontend && npx vitest run src/pages/builds/__tests__/buildListServerGrid.test.tsx
```

Expected: all three FAIL.

- [ ] **Step 3: Convert the page**

```tsx
  const { items, total, listLoading } = useSelector((s: RootState) => s.build);

  const grid = useServerGrid({
    endpoint: 'builds',
    filterKeys: ['subsystem_search', 'branch', 'date_from', 'date_to'],
    // Free-text keys, and also the 'all'-sentinel exemption list. `branch`
    // belongs here because it is typed character by character — today it
    // fires a request per keystroke.
    debounceKeys: ['subsystem_search', 'branch'],
    onFetch: (params) => dispatch(fetchBuilds(params)),
    total,
    totalPending: listLoading,
  });
```

The four inputs read from `grid.filters` and write via `grid.setFilter`. The two date inputs stay `type="date"` and are not debounced — a date picker commits a whole value at once.

Keep converting the date strings to ISO exactly as the current `filters` memo does (`new Date(\`${dateFrom}T00:00:00Z\`).toISOString()`) — the server expects a datetime, and the input yields `YYYY-MM-DD`. Do that conversion where the value is written into `setFilter`, so the URL carries the same string the server gets.

Delete the `filteredItems` memo. `rows` maps `items` directly.

Give `latest_step` the computed header:

```tsx
    {
      field: 'latest_step',
      headerName: 'Latest step',
      flex: 1,
      sortable: false,
      renderHeader: () => <ComputedColumnHeader label="Latest step" />,
    },
```

Read `ComputedColumnHeader`'s actual props before wiring it — match its existing usage in `frontend/src/pages/releases/releaseColumns.tsx` rather than assuming this signature.

Server-mode `DataGrid` props exactly as Task 2 Step 3, with `pageSizeOptions={[10, 25, 50, 100]}`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd frontend && npx vitest run src/pages/builds/__tests__/buildListServerGrid.test.tsx
```

- [ ] **Step 5: Verify the tests discriminate**

Restore each mutation afterwards:

1. Drop `subsystem_search` from `filterKeys`. Expected: the first test FAILS.
2. Delete `sortable: false` from `latest_step`. Expected: the second test FAILS.
3. Delete `renderHeader` from `latest_step`. Expected: the third test FAILS.

Report all three failing outputs.

- [ ] **Step 6: Run the full suite, lint and types**

```bash
cd frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/builds/
git commit -m "feat(builds): server-side paging, sorting and filtering on the list"
```

---

### Task 5: verify in a browser, document, and open the PR

The prep PR's automated proof passed while a visible defect sat on a page; opening the page is what found it. Both pages here changed how every row is fetched.

**Files:**
- Modify: `docs/pagination.md`

- [ ] **Step 1: Run every gate**

```bash
cd frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

All three clean.

- [ ] **Step 2: Verify in the browser**

With `docker-compose up -d`, the backend on :8000 and `npm run dev` on :5173, log in as `admin`/`admin123` (tenant `demo`). On **both** `/deployments` and `/builds`:

- The grid renders and the spinner clears.
- A sortable column header sorts, and the first click is **ascending** — both endpoints default to `desc`, so a first click landing descending means `sort_dir` is not being sent.
- An unsortable header (Environment, Release, Latest step) does not offer a sort arrow, and `latest_step`'s header explains why on hover **and on keyboard focus**.
- Typing in a text filter narrows the footer's total, not just the visible rows — that is the difference between server-side filtering and the bug being removed.
- Paging to page 2 issues a request rather than slicing rows already in the browser (watch the Network tab for `offset=`).
- The URL carries the state, and a refresh reproduces the same view.

Record what you saw for each page. If any check fails, stop and report — do not open the PR.

- [ ] **Step 3: Update `docs/pagination.md`**

In the C3 section, record that PRs A's two pages are converted and six remain (bookings, change-requests, incidents, environments, systems, infrastructure-components). Note the two decisions this PR made, since the remaining six will meet both:

- These two pages kept raw `DataGrid` rather than migrating to `DataTable`, and why — plus the resulting divergence from the other six.
- `toParams` in each service is a silent whitelist, so **every** converted service needs its new params added there or sorting fails invisibly. This is the single trap most likely to recur, since six services still have this shape.

- [ ] **Step 4: Commit and open the PR**

```bash
git add docs/pagination.md
git commit -m "docs(pagination): record PR A's two converted pages"
git push -u github <branch>
```

Open the PR against `main` with a body covering: the two pages converted; the `toParams` trap and that six services still have it; the raw-`DataGrid` decision and its divergence; the browser checks performed; and the test counts.

- [ ] **Step 5: Confirm CI is green before reporting done**

```bash
gh pr checks <N> --repo pjgross/envmgr
```

All four jobs must pass. Do not report the PR ready on a partial result.

---

## What this plan does not cover

PRs B and C, which get their own plans:

- **B**: BookingList, ChangeRequestList, IncidentList — select-only filters, no inline mutations. Two filter mappings there are not pass-throughs: `BookingList`'s `status` is `booking_status` on the wire, and `ChangeRequestList` filters a *collection* client-side (`cr.environment_ids.includes(...)`) where the server takes a scalar `environment_id`.
- **C**: EnvironmentList, SystemCatalog, InfrastructureComponentList — text search **and** inline create/update/delete, so they are the first to need `refetch()` and the first that must delete their slices' optimistic list surgery. Their blast radius is far larger than anything in PR A: `state.environment.environments` has 8 non-page consumers and `state.infrastructureComponent.components` has 4.
