# C3 Rollout — PR C1 (environments) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `EnvironmentList` to true server-side paging, sorting and filtering — after first moving the nine other components that share its slice onto a picker hook of their own.

**Architecture:** Frontend only. The conversion itself is the established pattern; what makes this PR different is the prerequisite. `state.environment.environments` is read by nine components and written by nine dispatch sites, almost all of them dropdown pickers that want *every* environment. Those must stop sharing the list before it becomes a 25-row page.

**Tech Stack:** React 18 + TypeScript, Redux Toolkit, MUI DataGrid 6.20.4 Community, vitest + @testing-library/react.

## Why this plan covers environments only

PR C was scoped as three pages: environments, systems, infrastructure-components. Measured against the code, that is too much for one PR:

| Slice | Readers outside the owning page | Dispatch sites outside it | Other |
|---|---|---|---|
| `environment.environments` | **9** | **8** | — |
| `infrastructureComponent.components` | 3 | 4 | — |
| `system.systems` | 1 | 2 | **5** components call `systemService.listSystems()` directly |

Environments alone needs a shared picker hook and nine components moved onto it before a single line of the conversion. Systems has a different problem — `listSystems()` takes **no params argument at all**, and five components bypass the slice entirely.

So: **C1 = environments** (this plan), **C2 = infrastructure-components**, **C3 = systems**, each with its own plan written against what the previous one landed. Each produces working software on its own.

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-01-pagination-c3-rollout-design.md`](../specs/2026-08-01-pagination-c3-rollout-design.md). PR B: #44, merged as `5644dde`.
- Branch `feature/c3-rollout-pr-c` already exists off `main` at `5644dde`.
- Tests from `frontend/`: `npx vitest run <path>`. Whole suite `npx vitest run`. Lint `npm run lint` (`--max-warnings 0`). Types `npx tsc --noEmit`.
- **Never fall back to client-side filtering.** The `useMemo` filter comes out; nothing replaces it.
- **Every test verified by breaking the thing it covers.** This repo has shipped five tests that guarded nothing, all in ordering and pagination code.
- `GET /environments/` whitelists `name`, `environment_type`, `status`, `created_at`; default `name` asc. Every other column — `actions`, and every per-tenant custom-field column — is `sortable: false`, written **literally**, never computed from `isSortable`.
- `EnvironmentList` uses **raw `DataGrid`**, so it needs `disableColumnFilter` explicitly. `DataTable` sets it in server mode; raw `DataGrid` does not, and MUI gates the column-menu Filter item on that prop alone rather than on whether a toolbar exists.
- `totalPending` gets `listLoading`, never the shared `loading`.
- `debounceKeys` is **also** the `'all'`-sentinel exemption list, and every entry must also appear in `filterKeys`. This page has a `search` box, so it is the first page since PR A to need it.
- Conventional commits, one per task.

## The three traps this programme keeps hitting

Every one of these has cost a review round already. Check all three on every task that touches a slice.

1. **The reader trap.** Moving a list thunk onto `listLoading` silently kills any component reading the slice's `loading` for a spinner driven by that fetch. `tsc` cannot catch it — `loading` still exists and is still a boolean.
2. **The writer trap.** A component dispatching the list thunk with **no params** after a mutation overwrites the paged slice with an endpoint-default page, and `useServerGrid` never self-corrects because its effect is keyed on the resolved URL params. Grep `fetchX(`, not just `state.X`.
3. **The grep-form trap.** These selectors are written **both** `(s: RootState) => s.environment` and `(state: RootState) => state.environment`, and both as a property read (`s.environment.environments`) and destructured (`const { environments } = useSelector(s => s.environment)`). A pattern covering only one form silently returns nothing — that is how this programme's consumer sweeps have been wrong twice. Use `grep -rnE "(s|state)\.environment\b" frontend/src` and read the hits.

---

### Task 1: a shared `useAllEnvironments()` hook

Nine components want "every environment, for a dropdown". Today they each dispatch `fetchEnvironments()` and read the shared slice. Three release-slice consumers received the same fix one at a time earlier in this programme, and a review noted at three copies that *"a fourth gets written by copy-paste and drifts"*. At nine, a shared hook is the only sane shape.

**Files:**
- Create: `frontend/src/hooks/useAllEnvironments.ts`
- Test: `frontend/src/hooks/__tests__/useAllEnvironments.test.tsx`

**Interfaces:**
- Consumes: `environmentService.listEnvironments` as it exists today — it still returns a bare array until Task 3. Write against the current signature; Task 3 updates the hook.
- Produces: `useAllEnvironments(): { environments: EnvironmentResponse[]; loading: boolean; truncated: boolean }`. Task 2 moves every picker onto it.

- [ ] **Step 1: Write the failing tests**

```tsx
  it('fetches once and returns the environments', async () => {
    mockList.mockResolvedValue([{ id: 1, name: 'SIT' }, { id: 2, name: 'UAT' }]);
    const { result } = renderHook(() => useAllEnvironments());
    await waitFor(() => expect(result.current.environments).toHaveLength(2));
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('does not read or write the shared environment slice', async () => {
    // The whole point: EnvironmentList is about to turn state.environment
    // .environments into a 25-row page. A picker must not be limited to it,
    // and must not clobber it either.
    mockList.mockResolvedValue([{ id: 1, name: 'SIT' }]);
    const store = makeStore({ environment: { environments: [], loading: false, error: null } });
    const { result } = renderHook(() => useAllEnvironments(), { wrapper: providerFor(store) });
    await waitFor(() => expect(result.current.environments).toHaveLength(1));
    expect(store.getState().environment.environments).toHaveLength(0);
  });

  it('reports a failed fetch as an empty list rather than throwing', async () => {
    mockList.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useAllEnvironments());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.environments).toEqual([]);
  });
```

Write `makeStore` / `providerFor` locally; follow the harness in `frontend/src/pages/bookings/__tests__/bookingCalendarOwnFetch.test.tsx`.

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useAllEnvironments.test.tsx
```

Expected: all three FAIL — the module does not exist.

- [ ] **Step 3: Implement**

```ts
/**
 * Every environment, for a picker.
 *
 * NOT `state.environment.environments`: since the C3 conversion that slice is
 * `EnvironmentList`'s current filtered page, so a dropdown reading it would
 * silently offer a subset. Nine components needed this; the shared hook exists
 * so a tenth is not written by copy-paste.
 *
 * `truncated` is true when the server has more than we asked for — a picker
 * that is quietly missing options is the bug this programme exists to remove,
 * so callers can say so rather than pretend the list is complete.
 */
export function useAllEnvironments(): {
  environments: EnvironmentResponse[];
  loading: boolean;
  truncated: boolean;
} { /* local state + one effect; no dispatch, no useSelector */ }
```

Request an explicit `limit`. `GET /environments/` uses the shared default of 500 — pass it explicitly rather than relying on the default, so the number is visible at the call site.

`truncated` cannot be computed until Task 3 makes the service return `total`. For now return `false` and leave a comment saying Task 3 wires it; do **not** invent a proxy for it.

- [ ] **Step 4: Run to verify they pass, then lint and types**

- [ ] **Step 5: Verify the tests discriminate**

Make the hook read `useSelector((s: RootState) => s.environment.environments)` instead of its own fetch. Expected: the first two tests fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useAllEnvironments.ts frontend/src/hooks/__tests__/
git commit -m "feat(environments): add useAllEnvironments for pickers"
```

---

### Task 2: move all nine consumers onto the hook

**Files — every one of these both reads the slice and/or dispatches the thunk:**

| File | Reads slice | Dispatches |
|---|---|---|
| `components/releases/AddPhaseBookingDialog.tsx` | :44 | :57 |
| `components/releases/BulkBookEnvironmentsDialog.tsx` | :36 | :50 |
| `pages/bookings/BookingForm.tsx` | :92 | — |
| `pages/bookings/BookingCalendar.tsx` | :65 | :87 |
| `pages/bookings/BookingDetail.tsx` | :67 | :92 |
| `pages/change-requests/ChangeRequestForm.tsx` | :126 | :162 |
| `pages/change-requests/ChangeRequestEditDialog.tsx` | :100 | :180 |
| `pages/change-requests/ChangeRequestList.tsx` | :139 | :154 |
| `pages/Dashboard.tsx` | :9 (destructured) | :12 |

Line numbers are from planning and will drift — locate by selector, not by line.

**Interfaces:**
- Consumes: Task 1's `useAllEnvironments()`.
- Produces: after this task, **nothing outside `EnvironmentList` reads or writes `state.environment.environments`.** Task 4 depends on that being true.

- [ ] **Step 1: Write the failing test**

One test, asserting the property that matters across all nine:

```tsx
  it('no component outside EnvironmentList reads or dispatches the environment list', async () => {
    // This is the precondition for converting EnvironmentList. A single
    // straggler reintroduces the whole class of bug: a picker limited to the
    // grid's page, or a bare dispatch clobbering it.
    const files = await glob('src/**/*.{ts,tsx}', { ignore: ['**/__tests__/**', 'src/pages/environments/EnvironmentList.tsx', 'src/store/environmentSlice.ts', 'src/hooks/useAllEnvironments.ts'] });
    const offenders = [];
    for (const f of files) {
      const src = await readFile(f, 'utf8');
      if (/\bfetchEnvironments\s*\(/.test(src)) offenders.push(`${f}: dispatches fetchEnvironments`);
      if (/(s|state)\.environment\b/.test(src)) offenders.push(`${f}: reads the environment slice`);
    }
    expect(offenders).toEqual([]);
  });
```

Check whether the repo already has a source-scanning test to model this on — `frontend/src/__tests__/appCodeSplitting.test.tsx` scans source, and `backend/tests/test_sort_whitelist_contract.py` is the same idea across languages. Follow whichever fits. If `glob` is not already a dependency, use `fs.readdir` recursively rather than adding one.

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL, listing all nine files.

- [ ] **Step 3: Convert the nine**

Each is the same edit: delete the `useSelector` on the environment slice, delete the `dispatch(fetchEnvironments())`, call `useAllEnvironments()` instead.

Two need care:

- **`BookingCalendar`** already has its own local booking fetch from PR B. It reads `state.environment.environments` separately — replace only that, leave its booking logic alone.
- **`ChangeRequestList`** is a converted page. It reads the environment slice **for its filter dropdown options**, which is exactly the picker case. It also reads `state.infrastructureComponent.components` for hosts — leave that; it is C2's problem.

Where a component shows a picker the user chooses from, surface truncation if the hook reports it. `MoveScopeItemDialog` already does this for releases — read it and match rather than inventing a message.

- [ ] **Step 4: Run to verify it passes, plus the full suite**

- [ ] **Step 5: Verify the test discriminates**

Restore the `useSelector` in **one** component. Expected: the scan test fails naming that file. Restore.

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor(environments): move every picker off the shared list slice"
```

---

### Task 3: `environmentService` and `environmentSlice` return and store a page

**Files:**
- Modify: `frontend/src/services/environmentService.ts:16-...` (`listEnvironments`)
- Modify: `frontend/src/store/environmentSlice.ts`
- Modify: `frontend/src/hooks/useAllEnvironments.ts` (wire `truncated`)
- Test: `frontend/src/services/__tests__/environmentServicePaged.test.ts` (create)

`listEnvironments` takes an **inline literal param type** and passes params straight to axios — there is no `toParams` mapping layer, so widening the literal is the change. Copy `frontend/src/services/bookingService.ts`, whose shape is identical.

For the slice, copy `frontend/src/store/bookingSlice.ts`: `total`, `listLoading`, the three list-thunk cases, and the `action.meta.aborted` early return **verbatim including its comment**.

- [ ] **Step 1: Write the failing tests**

Three, matching `frontend/src/services/__tests__/bookingServicePaged.test.ts`: rows+total from the header; fallback to row count when the header is absent; and params forwarded (`limit`, `offset`, `sort_by`, `sort_dir`, `search`, `status`, `environment_type`).

**The third test cannot fail at runtime** — `listEnvironments` is a passthrough, so the assertion compares an object against itself. Its only guard is TypeScript's excess-property check under `tsc`. Copy the honest comment from `bookingServicePaged.test.ts` saying exactly that. Do **not** invent a tautological runtime assertion.

- [ ] **Step 2: Run to verify the first two fail**

- [ ] **Step 3: Implement the service and slice**

Widen the literal with `limit`, `offset`, `sort_by`, `sort_dir` (`search`, `status` and `environment_type` may already be there — check). Return `Paged<EnvironmentResponse>`.

Do **not** remove the three list surgeries at `environmentSlice.ts:140,154,170` yet — Task 4 removes them together with the refetch that replaces them.

- [ ] **Step 4: Wire `truncated` in the hook**

Now that the service returns `total`, `useAllEnvironments` can report `rows.length < total`. Add a test for it and verify it discriminates.

- [ ] **Step 5: Run all three trap checks**

Reader grep, writer grep, and both grep forms — see Global Constraints. Task 2 should have left `EnvironmentList` as the only hit for each. **Report every hit.** If `EnvironmentList` reads `loading` for its list spinner, fix that here with the two-line flag swap; that call has been made four times in this programme and every time the swap shipped in the task that caused the regression.

- [ ] **Step 6: Full suite, lint, types, discrimination check, commit**

```bash
git commit -m "feat(environments): return and store a page, not a bare array"
```

---

### Task 4: convert `EnvironmentList`

The first page in this programme with **both** a text filter and inline create/update/delete.

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentList.tsx`
- Modify: `frontend/src/store/environmentSlice.ts:140,154,170` (remove the list surgery)
- Test: `frontend/src/pages/environments/__tests__/environmentListServerGrid.test.tsx` (create)

- [ ] **Step 1: Write the failing tests**

Model the harness on `frontend/src/pages/bookings/__tests__/bookingListServerGrid.test.tsx`.

```tsx
  it('sends paging, sorting and the search filter', async () => {
    renderEnvironmentList('/environments?page=1&sort_by=status&sort_dir=desc&search=prod');
    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'status', sort_dir: 'desc', search: 'prod',
    }));
  });

  it('keeps the literal search term "all"', async () => {
    // `all` is the selects' no-selection sentinel. On a text box it is a real
    // search term, and dropping it returns unfiltered results while the box
    // still reads "all". This is the first page since PR A with a text filter.
    renderEnvironmentList('/environments?search=all');
    await waitFor(() => expect(lastListParams()).toMatchObject({ search: 'all' }));
  });

  it('marks actions and custom-field columns unsortable', () => {
    const byField = Object.fromEntries(environmentColumns.map((c) => [c.field, c]));
    ['name', 'environment_type', 'status', 'created_at'].forEach((f) => expect(byField[f].sortable).not.toBe(false));
    expect(byField.actions.sortable).toBe(false);
  });

  it('disables the column filter, which would filter only the loaded page', () => {
    renderEnvironmentList('/environments');
    expect(gridProps().disableColumnFilter).toBe(true);
  });

  it('refetches after a delete instead of splicing the page', async () => {
    // Editing a 25-row window is structurally wrong: it ignores the active
    // filter/sort/page and never adjusts `total`.
    renderEnvironmentList('/environments');
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1));
    await deleteFirstRow();
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2));
  });
```

For the custom-field columns, note PR B established that a DOM assertion is **not achievable** — MUI virtualises columns by container width and jsdom reports zero width, so only the first few headers mount. `BookingList` solved it by extracting an exported `buildCustomFieldColumns()` and unit-testing that. Do the same here.

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Convert the page**

```tsx
  const { environments, total, listLoading } = useSelector((s: RootState) => s.environment);

  const grid = useServerGrid({
    endpoint: 'environments',
    filterKeys: ['search', 'status', 'environment_type'],
    // Free-text keys, and also the 'all'-sentinel exemption list. Every entry
    // must also appear in filterKeys above — there is a DEV warning if not.
    debounceKeys: ['search'],
    onFetch: (params) => dispatch(fetchEnvironments(params)),
    total,
    totalPending: listLoading,
  });
```

Delete the client `useMemo` filter. Bind the search box and the selects to `grid.filters` / `grid.setFilter`.

**Remove the three list surgeries** in `environmentSlice.ts` (`push` on create, index assign on update, `filter` on delete), keep any `currentEnvironment` handling, and have the page call `grid.refetch()` after each mutation instead. Check where each is dispatched from before deciding how — on the change-requests track some turned out to be dead code on a sibling route, and on the bookings track a dialog child needed a callback. Establish the facts here; say what you found for each.

Server-mode raw `DataGrid` props as `BookingList` uses them, including `disableColumnFilter` and `pageSizeOptions={[10, 25, 50, 100]}`.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Verify the tests discriminate**

Four mutations, each restored, all outputs reported: drop `search` from `filterKeys`; remove `search` from `debounceKeys` (the `'all'` test must fail); delete `sortable: false` from `actions`; remove `disableColumnFilter`.

- [ ] **Step 6: Full suite, lint, types, commit**

```bash
git commit -m "feat(environments): server-side paging, sorting and filtering on the list"
```

---

### Task 5: verify in a browser, document, and open the PR

Five defects in this programme have been found only by opening the page — case-sensitive sorting, `Release #47`, keystroke clobbering, a column filter contradicting its own footer, and a status dropdown that could not reach its own rows. Every one had a green suite.

- [ ] **Step 1: Run every gate**

```bash
cd frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

- [ ] **Step 2: Verify in the browser**

With `docker-compose up -d`, the backend on :8000 and `npm run dev` on :5173, sign in as `admin`/`admin123` (tenant `demo`).

On `/environments`:
- The grid renders and the spinner clears.
- **Type a multi-character term into the search box and confirm the whole term survives.** This is the first page since PR A with a text filter, and the drafts machinery exists because typing `comp` once left `p`.
- The search narrows the **footer total**, not just the visible rows.
- A sortable header sorts, first click ascending; `actions` and custom-field columns offer no sort arrow.
- The column ⋮ menu offers **no Filter item**.
- Create, rename and delete an environment: each is reflected without the row count drifting, and without a row appearing that the active filter excludes.

Then check the pickers Task 2 moved — at minimum a booking form, a change-request form, and the dashboard — and confirm each still offers the full environment list rather than a page of it.

Record what you saw. If any check fails, stop and report.

- [ ] **Step 3: Update `docs/pagination.md`**

Record environments as converted, two pages remaining, and the shared-picker-hook pattern as the answer at scale. State the counts C2 and C3 face.

- [ ] **Step 4: Commit, push, open the PR**

- [ ] **Step 5: Confirm CI is green before reporting done**

All four jobs must pass. Do not report ready on a partial result.

---

## What this plan does not cover

- **C2 — infrastructure-components.** 3 readers and 4 dispatch sites outside the owning page, all in change-request forms and a hosts dialog. Same shape as this PR at a third the scale; a `useAllHosts()` hook is the obvious counterpart.
- **C3 — systems.** Different problem: `systemService.listSystems()` takes **no params argument at all** and must grow both a signature and a `Paged` return, and **five components call it directly** into local state (`ScopeWindowsTable`, `ReleaseSystemsTab`, `ReleaseList`, `IncidentList`, `IncidentForm`) — every one breaks on the return-type change, which `tsc` will catch. Only two components read the slice. `GET /systems/` whitelists `name` alone, so almost every column on `SystemCatalog` becomes unsortable.
- **`ScopeWindowsTable`** remains unconvertible by this pattern: it filters `window_status` and sorts `days_to_cutoff`, both computed in Python after the query.
