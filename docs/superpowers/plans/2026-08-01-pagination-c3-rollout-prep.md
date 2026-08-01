# C3 Rollout — PR 0 (prep) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the six shared prerequisites the eight-page C3 rollout depends on, so no page conversion has to rediscover them.

**Architecture:** Frontend only. Five changes harden the pilot's plumbing (`serverGridParams`, `useServerGrid`, `releaseSlice`, `ReleaseList`) and one fixes a live bug in a component that reads a slice whose meaning changed under it. No backend, no API, no migration.

**Tech Stack:** React 18 + TypeScript, Redux Toolkit, MUI DataGrid 6.20.4 Community, vitest + @testing-library/react, react-router-dom 7.18.2.

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-01-pagination-c3-rollout-design.md`](../specs/2026-08-01-pagination-c3-rollout-design.md).
- Branch is `feature/c3-rollout-prep`, already created, already carrying the spec commit `34bf02f`. Do not create another branch.
- Tests run from `frontend/`: `npx vitest run <path>`. The whole suite is `npx vitest run`.
- Never render an entity as `#N` or `Release #47`. Entities are shown by name — this is a standing project rule and Task 5 exists because it was broken.
- Every test in this plan must be verified by breaking the thing it covers and confirming it fails. This repo has shipped five tests that guarded nothing, all in ordering and pagination code. A green run is not on its own evidence here.
- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`). Commit at the end of each task, not between tasks.
- No page conversions in this PR. The eight pages are PRs A/B/C and get their own plans.

---

### Task 1: `buildParams` must not eat a real search term

`serverGridParams.ts` drops any filter value of `''` **or** `'all'`, for every key. `ReleaseList` has no text input so it cannot bite yet; five of the eight pages in the rollout do. Typing `all` into a search box would silently return unfiltered results while the box still reads "all".

Free-text keys are exactly the debounced keys — `debounceKeys` already means "free-text inputs" in `UseServerGridOptions`. Reusing that one list rather than introducing a parallel `textKeys` option at the call sites avoids two lists that can drift apart.

**Files:**
- Modify: `frontend/src/hooks/serverGridParams.ts:19-20,59-78`
- Modify: `frontend/src/hooks/useServerGrid.ts:107-118`
- Test: `frontend/src/hooks/__tests__/serverGridParams.test.ts:71-82`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `buildParams(args)` gains an optional `textKeys?: string[]` field. Absent or empty, behaviour is exactly as today.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/hooks/__tests__/serverGridParams.test.ts` inside the existing `describe('buildParams', ...)`:

```ts
  it('keeps the literal text "all" typed into a free-text filter', () => {
    // The sentinel means "no selection" for a select. In a text box it is a
    // search term, and dropping it returns unfiltered results while the box
    // still reads "all" — a wrong answer presented as a filtered one.
    const p = buildParams({
      endpoint: 'systems',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { search: 'all' },
      textKeys: ['search'],
    });
    expect(p.search).toBe('all');
  });

  it('still drops "all" from a select on a page that also has a text filter', () => {
    const p = buildParams({
      endpoint: 'environments',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { status: 'all', search: 'all' },
      textKeys: ['search'],
    });
    expect(p).not.toHaveProperty('status');
    expect(p.search).toBe('all');
  });

  it('drops an empty text filter, which means the box is simply empty', () => {
    const p = buildParams({
      endpoint: 'systems',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { search: '' },
      textKeys: ['search'],
    });
    expect(p).not.toHaveProperty('search');
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd frontend && npx vitest run src/hooks/__tests__/serverGridParams.test.ts
```

Expected: the first two FAIL (`search` is dropped, so `p.search` is `undefined`). The third already passes — it pins behaviour that must survive the change.

- [ ] **Step 3: Implement**

In `frontend/src/hooks/serverGridParams.ts`, replace the `NO_FILTER` constant and the `buildParams` body:

```ts
/** A select's "no selection" value. In a free-text box it is a search term. */
const SELECT_SENTINEL = 'all';

export function buildParams(args: {
  endpoint: EndpointKey;
  page: number;
  pageSize: number;
  sortBy: string | null;
  sortDir: string | null;
  filters: Record<string, string>;
  /**
   * Free-text filter keys, for which `'all'` is a real search term rather
   * than the selects' "no selection" sentinel. These are the debounced keys —
   * `useServerGrid` passes its `debounceKeys` straight through, so there is
   * one list of free-text inputs rather than two that can drift.
   */
  textKeys?: string[];
}): ServerGridParams {
  const { sort_by, sort_dir } = resolveSort(args.endpoint, args.sortBy, args.sortDir);
  const textKeys = new Set(args.textKeys ?? []);
  const params: ServerGridParams = {
    limit: args.pageSize,
    offset: args.page * args.pageSize,
    sort_by,
    sort_dir,
  };
  Object.entries(args.filters).forEach(([key, value]) => {
    if (RESERVED.has(key)) return;
    // An empty string means "unset" for both a select and a text box.
    if (value === '') return;
    if (value === SELECT_SENTINEL && !textKeys.has(key)) return;
    params[key] = value;
  });
  return params;
}
```

- [ ] **Step 4: Pass the debounced keys through from the hook**

In `frontend/src/hooks/useServerGrid.ts`, the `params` memo becomes:

```ts
  const params = useMemo(
    () =>
      buildParams({
        endpoint,
        page,
        pageSize,
        sortBy: sort.sort_by,
        sortDir: sort.sort_dir,
        filters,
        textKeys: debounceKeys,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [endpoint, page, pageSize, sort.sort_by, sort.sort_dir, filters, debounceKeysKey]
  );
```

`debounceKeysKey` is declared at line 211, below this memo. Move that one line (`const debounceKeysKey = debounceKeys.join(' ');`) up to just under `filterKeysKey` at line 96 so it is defined before both uses. Do not duplicate it.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd frontend && npx vitest run src/hooks/__tests__/serverGridParams.test.ts src/hooks/__tests__/useServerGrid.test.tsx
```

Expected: PASS, including the pre-existing `omits the pages' no-filter sentinels` test — `ReleaseList` passes no `debounceKeys`, so its selects still drop `'all'`.

- [ ] **Step 6: Verify the test discriminates**

Temporarily delete `&& !textKeys.has(key)` from the implementation and re-run. Expected: `keeps the literal text "all"` FAILS. Restore it.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/serverGridParams.ts frontend/src/hooks/useServerGrid.ts frontend/src/hooks/__tests__/serverGridParams.test.ts
git commit -m "fix(pagination): stop the 'all' sentinel eating a real search term"
```

---

### Task 2: `useServerGrid.refetch()`

The fetch effect is keyed purely on the resolved params, so nothing can re-run the current query. That is why slices still perform optimistic surgery on their arrays after a create or delete — which server paging makes structurally wrong: a new row need not belong on the current page at all, and a page that had 25 rows should still have 25 after one is deleted. PR C's three pages (environments, systems, infrastructure-components) all mutate inline and need this.

**Files:**
- Modify: `frontend/src/hooks/useServerGrid.ts:1,57-64,127-142,237-256`
- Test: `frontend/src/hooks/__tests__/useServerGrid.test.tsx`

**Interfaces:**
- Consumes: Task 1's `textKeys` plumbing (already in the file; do not revert it).
- Produces: `ServerGrid` gains `refetch: () => void`. Calling it re-issues the current query with identical params.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/hooks/__tests__/useServerGrid.test.tsx`:

```ts
describe('refetch', () => {
  it('re-issues the current query with identical params', async () => {
    // A create or delete must be able to re-ask the server, because the
    // correct next page cannot be computed in the browser: a new row need
    // not belong on the current page at all.
    const onFetch = vi.fn();
    const hook = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
      { wrapper: wrapper(['/releases']) }
    );

    expect(onFetch).toHaveBeenCalledTimes(1);
    const first = onFetch.mock.calls[0][0];

    await act(async () => {
      hook.result.current.refetch();
    });

    expect(onFetch).toHaveBeenCalledTimes(2);
    expect(onFetch.mock.calls[1][0]).toEqual(first);
  });

  it('keeps a stable identity so it can sit in an effect dependency list', () => {
    const onFetch = vi.fn();
    const hook = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
      { wrapper: wrapper(['/releases']) }
    );
    const before = hook.result.current.refetch;
    hook.rerender();
    expect(hook.result.current.refetch).toBe(before);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx -t refetch
```

Expected: FAIL with `hook.result.current.refetch is not a function`.

- [ ] **Step 3: Implement**

In `frontend/src/hooks/useServerGrid.ts`, add `useState` to the React import on line 1:

```ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
```

Add to the `ServerGrid` interface:

```ts
  /** Re-issue the current query — after a create or delete changed the set. */
  refetch: () => void;
```

Above the fetch effect, add the nonce and the callback:

```ts
  // The fetch effect is keyed on the resolved params, so an identical query
  // cannot re-run on its own. A nonce gives callers an explicit way to ask
  // for one without inventing a fake param change.
  const [refetchNonce, setRefetchNonce] = useState(0);
  const refetch = useCallback(() => setRefetchNonce((n) => n + 1), []);
```

Add `refetchNonce` to the fetch effect's dependency array:

```ts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey, refetchNonce]);
```

Add `refetch` to the returned object, beside `filters` and `setFilter`:

```ts
    filters,
    setFilter,
    refetch,
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx
```

Expected: PASS, all tests in the file — the abort-on-supersede and debounce tests must be unaffected.

- [ ] **Step 5: Verify the test discriminates**

Temporarily remove `refetchNonce` from the effect's dependency array and re-run. Expected: `re-issues the current query` FAILS with 1 call instead of 2. Restore it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useServerGrid.ts frontend/src/hooks/__tests__/useServerGrid.test.tsx
git commit -m "feat(pagination): add useServerGrid refetch for post-mutation reloads"
```

---

### Task 3: A separate `listLoading` on the converted slice

Each slice has one `loading` flag shared by roughly twenty thunks. `fetchReleases.rejected` deliberately returns early when `action.meta.aborted` (`releaseSlice.ts:327`) so a superseded request does not flicker the spinner off — but on **unmount** there is no successor to raise the flag again, so `loading` stays true forever. That is what hung `/releases/calendar` and `/releases/timeline` during the pilot.

Those two pages were fixed by giving them their own loading transitions. The structural problem remains: every slice converted in PRs A/B/C inherits the shared flag. A separate `listLoading`, written only by the list thunk, contains a stuck flag to the grid that caused it.

**Files:**
- Modify: `frontend/src/store/releaseSlice.ts:40-63,321-337`
- Modify: `frontend/src/pages/releases/ReleaseList.tsx`
- Test: `frontend/src/store/__tests__/releaseSlice.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ReleaseState.listLoading: boolean`. `state.loading` keeps its existing meaning for every non-list thunk. This is the shape PRs A/B/C copy onto the other eight slices.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/store/__tests__/releaseSlice.test.ts`:

```ts
describe('listLoading', () => {
  it('is raised and cleared by the list thunk alone', () => {
    let state = reducer(undefined, { type: fetchReleases.pending.type });
    expect(state.listLoading).toBe(true);

    state = reducer(state, {
      type: fetchReleases.fulfilled.type,
      payload: { rows: [], total: 0 },
    });
    expect(state.listLoading).toBe(false);
  });

  it('leaves the general loading flag alone when the list aborts', () => {
    // An aborted list request has no successor on unmount, so its flag stays
    // true. Isolating it means calendar and timeline — which read `loading` —
    // are not hung by a grid the user has already navigated away from.
    let state = reducer(undefined, { type: fetchReleases.pending.type });
    state = reducer(state, {
      type: fetchReleases.rejected.type,
      meta: { aborted: true },
      error: { message: 'Aborted' },
    });

    expect(state.listLoading).toBe(true);
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });
});
```

Import `fetchReleases` and the reducer at the top of the file if not already imported; follow the file's existing import style.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npx vitest run src/store/__tests__/releaseSlice.test.ts -t listLoading
```

Expected: FAIL — `state.listLoading` is `undefined`.

- [ ] **Step 3: Implement**

In `frontend/src/store/releaseSlice.ts`, add to the state interface beside `loading: boolean;`:

```ts
  /**
   * The list query's own flag. `loading` is shared by ~20 thunks, and an
   * aborted list request on unmount has no successor to clear it — isolating
   * the list keeps that from hanging every other consumer of the slice.
   */
  listLoading: boolean;
```

Add `listLoading: false,` to `initialState` beside `loading: false,`.

Replace the three `fetchReleases` cases so they write `listLoading` and stop writing `loading`:

```ts
      .addCase(fetchReleases.pending, (state) => { state.listLoading = true; state.error = null; })
      .addCase(fetchReleases.fulfilled, (state, action) => {
        state.listLoading = false;
        state.list = action.payload.rows;
        state.total = action.payload.total;
      })
      .addCase(fetchReleases.rejected, (state, action) => {
        // useServerGrid aborts a superseded request rather than merely
        // ignoring its reply. RTK dispatches `pending` for the new request
        // synchronously, then `rejected` for the aborted one on a
        // microtask — so without this guard, `listLoading` would flip back to
        // false (the grid's spinner flickers off) and `error` would be set
        // to 'Aborted' while the real request is still in flight.
        if (action.meta.aborted) return;
        state.listLoading = false;
        state.error = action.error.message ?? 'Failed to load releases';
      })
```

- [ ] **Step 4: Point `ReleaseList` at the new flag**

In `frontend/src/pages/releases/ReleaseList.tsx`, find the `useSelector` reading `loading` from the release slice and change it to read `listLoading`. Leave every other consumer of `state.release.loading` — `ReleaseCalendar`, `ReleaseTimeline`, `ScopeHistoryDrawer`, `ReleaseDetail` — untouched.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd frontend && npx vitest run src/store/__tests__/releaseSlice.test.ts
```

Expected: PASS, all tests in the file.

- [ ] **Step 6: Verify the test discriminates**

Temporarily change `fetchReleases.pending` back to writing `state.loading` and re-run. Expected: `is raised and cleared by the list thunk alone` FAILS. Restore it.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/store/releaseSlice.ts frontend/src/store/__tests__/releaseSlice.test.ts frontend/src/pages/releases/ReleaseList.tsx
git commit -m "fix(pagination): give the list query its own loading flag"
```

---

### Task 4: A stale `total` must not clamp a legitimate deep link

`useServerGrid`'s clamp effect trusts whatever `total` the caller passes, which need not correspond to the request in flight. A cold load is safe (`total === 0` short-circuits), but arriving at `?page=8` while a narrower `total` from a previous view still sits in the slice rewrites the URL to page 0 before the real response lands.

Fix at the call site, which is where the knowledge lives: while a list request is in flight, the caller does not yet know the total for it.

**Amended before execution (user-approved).** As first written, this task put the guard in `ReleaseList` as `total={listLoading ? undefined : total}` and its tests passed both before and after — the production change was untested, which contradicts this plan's own Global Constraint. The guard moves into the hook instead, where a hook test reaches it directly. That also matters for the rollout: eight pages will copy this, and a named option cannot be silently inverted the way a ternary can.

**Files:**
- Modify: `frontend/src/hooks/useServerGrid.ts:46-55,198-205`
- Modify: `frontend/src/pages/releases/ReleaseList.tsx`
- Test: `frontend/src/hooks/__tests__/useServerGrid.test.tsx`

**Interfaces:**
- Consumes: Task 3's `listLoading`.
- Produces: `UseServerGridOptions` gains `totalPending?: boolean`. While true, the clamp effect does not run. Absent, behaviour is exactly as today. PRs A/B/C pass `totalPending: <slice>.listLoading`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/hooks/__tests__/useServerGrid.test.tsx`:

```ts
describe('clamping against a stale total', () => {
  it('does not clamp while the total is unknown', () => {
    // `undefined` means "no total for this request yet". Clamping on a total
    // that belongs to a previous view rewrites a legitimate deep link to
    // page 0 before its real response has even arrived.
    const onFetch = vi.fn();
    const { Wrapper, state } = locationHarness(['/releases?page=8']);
    renderHook(
      () =>
        useServerGrid({
          endpoint: 'releases',
          filterKeys: ['status'],
          onFetch,
          total: undefined,
        }),
      { wrapper: Wrapper }
    );

    expect(state.search).toContain('page=8');
    expect(onFetch.mock.calls[0][0].offset).toBe(8 * 25);
  });

  it('clamps once a real total says the page is past the end', () => {
    const onFetch = vi.fn();
    const { Wrapper, state } = locationHarness(['/releases?page=8']);
    renderHook(
      () =>
        useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch, total: 30 }),
      { wrapper: Wrapper }
    );

    // 30 rows at 25/page is pages 0-1, so page 8 clamps to 1.
    expect(state.search).toContain('page=1');
  });

  it('does not clamp against a total that belongs to the previous request', () => {
    // THE BUG. The slice still holds the previous view's total while the
    // request for ?page=8 is in flight. Without totalPending the effect
    // clamps to page 1 on that stale 30 and the deep link is lost before
    // its own response ever arrives.
    const onFetch = vi.fn();
    const { Wrapper, state } = locationHarness(['/releases?page=8']);
    renderHook(
      () =>
        useServerGrid({
          endpoint: 'releases',
          filterKeys: ['status'],
          onFetch,
          total: 30,
          totalPending: true,
        }),
      { wrapper: Wrapper }
    );

    expect(state.search).toContain('page=8');
  });
});
```

- [ ] **Step 2: Run the tests to verify the third fails**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx -t "stale total"
```

Expected: the first two PASS (they pin the existing `total === undefined` guard, which must survive), the third FAILS — `page` has been rewritten to `1`.

- [ ] **Step 3: Implement in the hook**

In `frontend/src/hooks/useServerGrid.ts`, add to `UseServerGridOptions`:

```ts
  /**
   * True while a list request is in flight. `total` then still describes the
   * PREVIOUS view, and clamping against it rewrites a legitimate deep link
   * (`?page=8`) back to page 0 before that page's own response arrives.
   */
  totalPending?: boolean;
```

Destructure `totalPending` alongside `total` in the parameter list, and guard the clamp effect:

```ts
  useEffect(() => {
    // A row deleted elsewhere (or a filter narrowing the set) can leave the
    // current offset past the end of the result — clamp back onto the last
    // real page rather than painting an empty grid over a non-zero total.
    if (totalPending || total === undefined || total === 0) return;
    const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
    if (page > lastPage) patch({ page: String(lastPage) }, false);
  }, [totalPending, total, page, pageSize, patch]);
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx
```

Expected: PASS, all tests in the file.

- [ ] **Step 5: Verify the test discriminates**

Temporarily remove `totalPending ||` from the guard and re-run. Expected: `does not clamp against a total that belongs to the previous request` FAILS. Restore it.

- [ ] **Step 6: Wire the call site**

In `frontend/src/pages/releases/ReleaseList.tsx`, add to the `useServerGrid({ ... })` call, beside the existing `total`:

```ts
    totalPending: listLoading,
```

- [ ] **Step 7: Run the frontend suite**

```bash
cd frontend && npx vitest run
```

Expected: PASS, whole suite.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/hooks/useServerGrid.ts frontend/src/pages/releases/ReleaseList.tsx frontend/src/hooks/__tests__/useServerGrid.test.tsx
git commit -m "fix(pagination): do not clamp a deep link against a stale total"
```

---

### Task 5: `ScopeHistoryDrawer` renders `Release #47` — a live bug

`ScopeHistoryDrawer.tsx:44` reads `s.release.list` to build a release-name lookup for a scope item's move history, and **never dispatches `fetchReleases` itself** — it relies entirely on whatever another page left in the slice. Since the pilot, that is `ReleaseList`'s current filtered page of 25 rows, so a move involving any other release falls through to `Release #${id}` at line 81.

This is the third consumer of this shape. The pilot fixed `MoveScopeItemDialog`; a whole-branch review caught `RequestAdmissionDialog`; both sweeps missed this one. Fix it the same way — its own fetch into local state. The slice is one grid's current view; a component that wants "all releases" must ask for them itself.

**Files:**
- Modify: `frontend/src/components/releases/ScopeHistoryDrawer.tsx:44,48-60`
- Test: `frontend/src/components/__tests__/scopeHistoryDrawer.test.tsx` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing. Removes `ScopeHistoryDrawer` as a consumer of `state.release.list`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/scopeHistoryDrawer.test.tsx`. Mock `releaseService` and the two history thunks, render the drawer with a history entry pointing at a release that is **not** in `state.release.list`, and assert the name renders.

`releaseService` is a **named** export (`export const releaseService = {...}` at `releaseService.ts:50`), so the mock must supply `releaseService`, not `default`. Mocking it as `default` produces a module whose `releaseService` is `undefined` and the drawer throws instead of failing the assertion.

```tsx
import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi } from 'vitest';
import ScopeHistoryDrawer from '../releases/ScopeHistoryDrawer';

const list = vi.fn();
vi.mock('../../services/releaseService', () => ({
  releaseService: { list: (...args: unknown[]) => list(...args) },
}));

/**
 * `sliceReleases` is what ReleaseList happens to have left in the store —
 * deliberately empty here, standing in for a grid page that holds none of the
 * releases this history refers to.
 */
function renderDrawerWithHistory(opts: {
  sliceReleases: { id: number; name: string }[];
  history: {
    from_release_id: number | null;
    to_release_id: number | null;
    moved_at: string;
    notes: string | null;
  }[];
}) {
  const store = configureStore({
    reducer: {
      release: () => ({
        list: opts.sliceReleases,
        total: 0,
        loading: false,
        listLoading: false,
        error: null,
        detail: null,
        changeReleaseHistory: opts.history,
        changeStatusHistory: [],
      }),
    },
  });
  return render(
    <Provider store={store}>
      <ScopeHistoryDrawer open onClose={() => {}} changeId={1} itemTitle="Item" />
    </Provider>
  );
}

describe('ScopeHistoryDrawer', () => {
  it('names a release that is not on the grid current page', async () => {
    // The release slice holds ReleaseList's current 25-row page. A scope item
    // moved between older releases must still render their names, never #47.
    list.mockResolvedValue({ rows: [{ id: 47, name: 'Mortgage R2' }], total: 1 });

    renderDrawerWithHistory({
      sliceReleases: [],
      history: [
        { from_release_id: null, to_release_id: 47, moved_at: '2026-07-01T00:00:00Z', notes: null },
      ],
    });

    await waitFor(() => expect(screen.getByText(/Mortgage R2/)).toBeInTheDocument());
    expect(screen.queryByText(/Release #47/)).not.toBeInTheDocument();
  });
});
```

If the drawer dispatches its two history thunks on open and those reach the real service, add them to the mocked module the same way — run the test and let the failure tell you, rather than mocking pre-emptively.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npx vitest run src/components/__tests__/scopeHistoryDrawer.test.tsx
```

Expected: FAIL — the drawer renders `Release #47`, because the slice list is empty and nothing fetched.

- [ ] **Step 3: Implement**

In `frontend/src/components/releases/ScopeHistoryDrawer.tsx`, delete the `releases` selector on line 44 and replace it with local state fed by its own fetch:

```tsx
  // NOT from state.release.list: that slice is ReleaseList's current filtered
  // page, so any release outside it would render as "Release #47". A picker
  // or lookup that wants every release has to ask for them itself. This is
  // the third component to need this — see MoveScopeItemDialog and
  // RequestAdmissionDialog for the same fix.
  const [releases, setReleases] = useState<{ id: number; name: string }[]>([]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    releaseService
      .list({ limit: 200 })
      .then(({ rows }) => { if (!cancelled) setReleases(rows); })
      .catch(() => { if (!cancelled) setReleases([]); });
    return () => { cancelled = true; };
  }, [open]);
```

Add `useState` to the React import, and the named import `import { releaseService } from '../../services/releaseService';` — it is a named export, matching `MoveScopeItemDialog.tsx:19`.

`MoveScopeItemDialog` also captures `total` and raises a snackbar on failure, because it is a *picker*: a user choosing from a truncated list needs telling. This drawer is a read-only name lookup, so a missing name degrades to the existing `#N` fallback rather than a wrong selection — local state and a silent catch are enough. Do not copy the snackbar here; it would fire on a drawer the user only opened to read.

Leave `releaseNameById` and the `Release #${id}` fallback exactly as they are — the fallback stays as a last resort for a genuinely deleted release, it just stops being the normal path.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd frontend && npx vitest run src/components/__tests__/scopeHistoryDrawer.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Verify the test discriminates**

Temporarily change the fetch to `.list({ limit: 200 }).then(() => setReleases([]))` and re-run. Expected: FAIL with `Release #47` on screen. Restore it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/releases/ScopeHistoryDrawer.tsx frontend/src/components/__tests__/scopeHistoryDrawer.test.tsx
git commit -m "fix(releases): give ScopeHistoryDrawer its own release fetch"
```

---

### Task 6: Three pickers still silently truncated at 50

`IncidentForm:114`, `DoraDashboard:113` and `ScopeWindowsTable:58` each call `releaseService.list(...)` and take the server default of 50 rows, discarding the `total` the pilot made available. A tenant with more than 50 releases gets a picker that silently omits some, with nothing saying so.

These are the same shape as the two dialogs already fixed. `ScopeWindowsTable`'s **grid** stays client-side — converting it needs `window_status` and `days_to_cutoff` restructured into SQL, which is explicitly out of scope — but its fetch should still stop dropping releases.

**Files:**
- Modify: `frontend/src/pages/incidents/IncidentForm.tsx:114`
- Modify: `frontend/src/pages/insights/DoraDashboard.tsx:113`
- Modify: `frontend/src/components/releases/ScopeWindowsTable.tsx:56-65`
- Test: `frontend/src/services/__tests__/releaseServicePaged.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/services/__tests__/releaseServicePaged.test.ts`:

The file already has `const mockGet = vi.mocked(api.get)` and a `beforeEach(() => mockGet.mockReset())`, and imports `{ releaseService }` as a named export. Add inside the existing `describe('releaseService.list', ...)`:

```ts
  it('reports a total larger than the returned page', async () => {
    // The guard for a truncated picker: callers can tell they did not get
    // everything. Three call sites discarded this and silently showed 50.
    mockGet.mockResolvedValue({
      data: [{ id: 1, name: 'a' }],
      headers: { 'x-total-count': '312' },
    });

    const result = await releaseService.list({ limit: 200 });

    expect(result.rows).toHaveLength(1);
    expect(result.total).toBe(312);
  });
```

- [ ] **Step 2: Run the test**

```bash
cd frontend && npx vitest run src/services/__tests__/releaseServicePaged.test.ts
```

Expected: PASS — the service already reads the header. This pins the contract the three call sites are about to depend on.

- [ ] **Step 3: Raise the three call sites' limits**

In `frontend/src/pages/incidents/IncidentForm.tsx:114` and `frontend/src/pages/insights/DoraDashboard.tsx:113`, change `releaseService.list()` to:

```ts
    // Explicit limit: the server default is 50, which silently omits releases
    // from a picker with no indication any are missing.
    releaseService.list({ limit: 200 }).then((paged) => setReleases(paged.rows)).catch(() => setReleases([]));
```

In `frontend/src/components/releases/ScopeWindowsTable.tsx`, add `limit: 200` to the existing params object:

```ts
      .list({
        release_kind: kindFilter === 'all' ? undefined : kindFilter,
        system_id: effectiveSystemId,
        limit: 200,
      })
```

200 is the cap `GET /releases` declares (`pagination(default_limit=50, max_limit=200)`); asking for more is a 422.

- [ ] **Step 4: Run the frontend suite**

```bash
cd frontend && npx vitest run
```

Expected: PASS, whole suite.

- [ ] **Step 5: Record what is still truncated**

In `docs/pagination.md`, in the "Recorded during the pilot, deliberately not fixed" list, mark the `'all'` sentinel, `refetch()`, the `loading` flag, the stale-total clamp and the three pickers as fixed in this PR, and keep the `ScopeWindowsTable` grid entry as still-open with its reason. Add that these pickers are capped at 200, not paged — a tenant past 200 releases still gets a truncated picker, and the real fix is an autocomplete that queries the server.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/incidents/IncidentForm.tsx frontend/src/pages/insights/DoraDashboard.tsx frontend/src/components/releases/ScopeWindowsTable.tsx frontend/src/services/__tests__/releaseServicePaged.test.ts docs/pagination.md
git commit -m "fix(releases): stop three release pickers truncating at the server default"
```

---

### Task 7: Verify in a browser, then open the PR

The pilot's automated proof passed while a visible defect sat on the page, and the one thing that found it was opening the page. Tasks 3, 4 and 5 all change what renders.

**Files:** none.

- [ ] **Step 1: Run the full frontend suite**

```bash
cd frontend && npx vitest run
```

Expected: PASS, no unhandled rejections.

- [ ] **Step 2: Run lint**

```bash
cd frontend && npm run lint
```

Expected: clean. CI gates on this.

- [ ] **Step 3: Verify in the browser**

With `docker-compose up -d`, the backend on :8000 and `npm run dev` on :5173, log in as `admin`/`admin123` (tenant `demo`) and check:

- `/releases` — the grid still pages, sorts and filters; the spinner clears.
- `/releases?page=8` — the URL is **not** rewritten to page 0 before the response lands (Task 4).
- `/releases/calendar` and `/releases/timeline` — both still load after navigating away from the grid mid-fetch (Task 3).
- A scope item with a move history — open the history drawer and confirm release **names**, no `Release #47` (Task 5).

- [ ] **Step 4: Push and open the PR**

```bash
git push -u github feature/c3-rollout-prep
gh pr create --repo pjgross/envmgr --base main --head feature/c3-rollout-prep \
  --title "fix(pagination): C3 rollout prerequisites" --body "$(cat <<'EOF'
The six shared prerequisites the eight-page C3 rollout depends on, landed once
so no page conversion has to rediscover them. **No pages are converted here** —
those are PRs A, B and C.

Five were recorded in `docs/pagination.md` as deliberately not fixed during the
pilot. The sixth was found while designing the rollout and is a **live bug on
`main`**, not a hazard for later.

| # | Item | Why it blocks the rollout |
|---|---|---|
| 1 | `'all'` sentinel no longer eats a real search term | Five of the eight pages have a text box; typing `all` returned unfiltered results while the box still read "all" |
| 2 | `useServerGrid.refetch()` | PR C's three pages mutate inline, and optimistic list surgery is structurally wrong under server paging |
| 3 | Separate `listLoading` | An aborted list request on unmount leaves the shared flag stuck true |
| 4 | Stale `total` no longer clamps a deep link | `?page=8` was rewritten to page 0 before its response landed |
| 5 | `ScopeHistoryDrawer` gets its own fetch | **Live bug**: rendered `Release #47` for any release outside ReleaseList's current page |
| 6 | Three release pickers no longer truncate at 50 | `IncidentForm`, `DoraDashboard`, `ScopeWindowsTable` discarded the total |

Item 5 is the third consumer of this shape. The pilot fixed `MoveScopeItemDialog`,
a whole-branch review caught `RequestAdmissionDialog`, and both sweeps missed this
one — which is why the rollout's per-page recipe now starts with "grep every
consumer of the slice".

Every test here was verified by breaking the thing it covers and confirming it
fails, and each changed page was checked in a browser. `ScopeWindowsTable`'s grid
stays client-side by design — converting it needs `window_status` and
`days_to_cutoff` restructured into SQL, which is out of scope.

Design: `docs/superpowers/specs/2026-08-01-pagination-c3-rollout-design.md`
Plan: `docs/superpowers/plans/2026-08-01-pagination-c3-rollout-prep.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Confirm CI is green before reporting done**

```bash
gh pr checks <N> --repo pjgross/envmgr
```

All four jobs must pass. Do not report the PR ready on a partial result.

---

## What this plan does not cover

PRs A, B and C — the eight page conversions — get their own plans, written against this PR's landed API once it merges. In order:

- **A**: DeploymentList, BuildList
- **B**: BookingList, ChangeRequestList, IncidentList
- **C**: EnvironmentList, SystemCatalog, InfrastructureComponentList

The per-page recipe and the two non-pass-through filter mappings (`BookingList`'s `status` → `booking_status`, `ChangeRequestList`'s collection-vs-scalar `environment_id`) are in the spec.
