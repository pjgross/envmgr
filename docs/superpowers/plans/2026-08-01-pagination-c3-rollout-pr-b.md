# C3 Rollout — PR B (bookings, change-requests, incidents) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the three select-filtered list pages to true server-side paging, sorting and filtering.

**Architecture:** Frontend only. Each page follows the pattern PR A established: its service returns `Paged<T>`, its slice stores `total` and a `listLoading` written only by the list thunk, its page drives `useServerGrid` instead of a local `useMemo` filter, and its grid runs in server mode. **One prerequisite comes first** — `BookingCalendar` must stop sharing the booking slice's list before `BookingList` turns it into a page.

**Tech Stack:** React 18 + TypeScript, Redux Toolkit, MUI DataGrid 6.20.4 Community, vitest + @testing-library/react, react-router-dom 7.18.2.

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-01-pagination-c3-rollout-design.md`](../specs/2026-08-01-pagination-c3-rollout-design.md). PR A: #43, merged as `b546ebe`.
- Branch `feature/c3-rollout-pr-b`, already created off `main` at `b546ebe`.
- Tests from `frontend/`: `npx vitest run <path>`. Whole suite `npx vitest run`. Lint `npm run lint` (`--max-warnings 0`). Types `npx tsc --noEmit`.
- **Never fall back to client-side filtering.** The `useMemo` filters come out; nothing replaces them.
- **Every test verified by breaking the thing it covers.** This repo has shipped five tests that guarded nothing, all in ordering and pagination code. A green run is not evidence on its own.
- `sort_dir` is always sent with `sort_by`. Change-requests and incidents both declare `default_dir="desc"`; bookings is `asc`.
- A column not in its endpoint's whitelist gets `sortable: false`. Write the flags out literally — never compute them from `isSortable` at render time, or the column test becomes a tautology.
- `totalPending` gets `<slice>.listLoading`, never the shared `loading`.
- `debounceKeys` is **also** the `'all'`-sentinel exemption list, and every entry must also appear in `filterKeys`. A DEV warning fires if not. None of these three pages has a text filter, so all three pass no `debounceKeys` at all.
- Conventional commits, one per task.

## What PR A established that this PR inherits

- `useServerGrid` supplies `paginationModel`/`sortModel`/`filters`/`setFilter`/`refetch`/`totalPending`, and keeps a drafts map for debounced text inputs.
- `Paged<T> = { rows, total }` in `frontend/src/types/pagination.ts`; `releaseService.list` and `deploymentService.list` are reference implementations.
- The abort guard in every list slice's `rejected` case (`if (action.meta.aborted) return;`) — not optional, see any converted slice.
- **Raw `DataGrid` needs `disableColumnFilter` explicitly.** MUI gates the column-menu Filter item only on that prop, not on whether a toolbar exists, so without it the menu filters the loaded page while the footer shows the server total. `DataTable` already sets it in server mode.

## The three services are three different shapes

There is no `toParams` whitelist here — that existed only in the two services PR A converted. What remains is a typed hazard the compiler catches, except where there is no parameter to widen:

| Service | Shape | What it needs |
|---|---|---|
| `bookingService.listBookings(params?: {...})` | inline literal type | widen the literal, return `Paged` |
| `changeRequestService.list(filters: ChangeRequestListFilters)` | typed interface | widen the interface, return `Paged` |
| `incidentService.list(params: Record<string, unknown>)` | fully permissive | **no type change** — only the `Paged` return |

## Two filter mappings that are not pass-throughs

Both silently drop a filter if converted carelessly.

- **`BookingList`'s status is `booking_status` on the wire.** The page's local state is `statusFilter`; the server parameter is `booking_status` (`bookingService.listBookings`, and `GET /bookings/`).
- **`ChangeRequestList` filters collections client-side.** It does `cr.environment_ids.includes(envFilter)` and `cr.host_ids.includes(hostFilter)`, where the server takes **scalar** `environment_id` and `host_id`. The server parameters exist and do the same job; the page must send a scalar rather than testing an array.

## Grid types differ across the three

Only `BookingList` uses raw `DataGrid`. `ChangeRequestList` and `IncidentList` already use the shared `DataTable`, so they get its server-mode guards (column filter disabled, CSV/Print export suppressed) for free and must **not** hand-roll them.

---

### Task 1: `BookingCalendar` stops sharing the booking slice's list

**This is a prerequisite, not a cleanup.** `BookingCalendar.tsx:61` reads `state.booking.bookings` — the same array Task 3 turns into a 25-row sorted page — and dispatches `fetchBookings()` itself on mount and whenever its environment filter changes. A calendar renders a month; 25 rows of a page is visibly wrong, and the two components would fight over one array.

This is the precondition the final PR A review recorded for exactly this situation: **convert a slice's other consumers off the shared list before converting the page that owns it, not after.**

**Files:**
- Modify: `frontend/src/pages/bookings/BookingCalendar.tsx:61,74-83`
- Test: `frontend/src/pages/bookings/__tests__/bookingCalendarOwnFetch.test.tsx` (create)

**Interfaces:**
- Consumes: `bookingService.listBookings` as it exists today (still returns a bare array until Task 2).
- Produces: `BookingCalendar` no longer reads `state.booking`. Task 3 can then reshape that slice freely.

- [ ] **Step 1: Write the failing test**

Create the test. Model the harness on `frontend/src/pages/deployments/__tests__/deploymentListServerGrid.test.tsx` — mock the service module, render inside `<Provider store={store}>` and `<MemoryRouter>`, assert on the mocked service's calls.

```tsx
  it('renders bookings the shared slice does not contain', async () => {
    // The slice is about to become BookingList's current 25-row page. A
    // calendar showing a month must not be limited to whatever that page
    // holds, so it has to fetch for itself.
    mockListBookings.mockResolvedValue([
      { id: 91, project_name: 'Only via own fetch', start_date: '2026-08-03T00:00:00Z', end_date: '2026-08-04T00:00:00Z', status: 'approved', environment_id: 1 },
    ]);

    renderCalendarWithSliceBookings([]);   // shared slice deliberately empty

    await waitFor(() => expect(screen.getByText(/Only via own fetch/)).toBeInTheDocument());
  });

  it('does not read the shared booking slice', () => {
    // Guards the regression directly: if the component goes back to the
    // slice, a booking present ONLY there would render.
    renderCalendarWithSliceBookings([
      { id: 92, project_name: 'Only in the slice', start_date: '2026-08-05T00:00:00Z', end_date: '2026-08-06T00:00:00Z', status: 'approved', environment_id: 1 },
    ]);

    expect(screen.queryByText(/Only in the slice/)).not.toBeInTheDocument();
  });
```

Write `renderCalendarWithSliceBookings(bookings)` as a local helper building a store whose `booking` reducer returns `{ bookings, loading: false, error: null }`, plus the `environment` and `customField` slices the component reads (`state.environment.environments`, `state.customField.definitions['booking']`) — give both empty defaults. Mock `bookingService`, `environmentService` and the custom-field service as needed; run the test and let the failures tell you which, rather than mocking pre-emptively.

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npx vitest run src/pages/bookings/__tests__/bookingCalendarOwnFetch.test.tsx
```

Expected: the first FAILS (nothing fetches into local state), the second FAILS (the slice booking renders).

- [ ] **Step 3: Implement**

Replace the `state.booking` selector with local state fed by the component's own fetch. Keep its existing environment-filter behaviour — that filter must now re-run the local fetch rather than dispatching:

```tsx
  // NOT from state.booking: that slice is BookingList's current filtered page
  // since the C3 conversion, and a calendar needs a month of bookings rather
  // than one grid page. Same fix three release-slice consumers received.
  const [bookings, setBookings] = useState<BookingResponse[]>([]);
  const [loading, setLoading] = useState(false);

  const loadBookings = useCallback((environmentId?: number) => {
    setLoading(true);
    bookingService
      .listBookings(environmentId !== undefined ? { environment_id: environmentId } : undefined)
      .then(setBookings)
      .catch(() => setBookings([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    dispatch(fetchEnvironments());
    dispatch(fetchDefinitions('booking'));
    loadBookings();
  }, [dispatch, loadBookings]);
```

`handleEnvFilter` calls `loadBookings(envId === '' ? undefined : envId)` instead of dispatching `fetchBookings`. Anywhere the component currently re-dispatches `fetchBookings` after a transition (see around line 109) calls `loadBookings` with the active filter instead.

Do **not** delete the `fetchBookings` thunk — `BookingList` still uses it.

- [ ] **Step 4: Run to verify it passes, then check the whole file still compiles**

```bash
cd frontend && npx vitest run src/pages/bookings/__tests__/bookingCalendarOwnFetch.test.tsx && npx tsc --noEmit
```

- [ ] **Step 5: Verify the tests discriminate**

Temporarily restore `const { bookings } = useSelector((s: RootState) => s.booking)` in place of the local state. Expected: **both** tests fail. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/bookings/
git commit -m "fix(bookings): give BookingCalendar its own fetch before the list is paged"
```

---

### Task 2: `bookingService` and `bookingSlice` return and store a page

**Files:**
- Modify: `frontend/src/services/bookingService.ts:7-12`
- Modify: `frontend/src/store/bookingSlice.ts`
- Test: `frontend/src/services/__tests__/bookingServicePaged.test.ts` (create)

**Interfaces:**
- Consumes: `Paged<T>` from `frontend/src/types/pagination.ts`.
- Produces: `bookingService.listBookings(params)` resolves `Paged<BookingResponse>`. `BookingState` gains `total: number` and `listLoading: boolean`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/services/__tests__/bookingServicePaged.test.ts`, modelled on `frontend/src/services/__tests__/deploymentServicePaged.test.ts` (read it first; it uses `vi.mock('../api')`, `const mockGet = vi.mocked(api.get)`, `beforeEach(() => mockGet.mockReset())`).

```ts
  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: { 'x-total-count': '640' } });
    const result = await bookingService.listBookings({});
    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(640);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await bookingService.listBookings({})).total).toBe(1);
  });

  it('forwards paging, sorting and the wire-named status filter', async () => {
    // `booking_status`, NOT `status` — the page's local state is called
    // statusFilter and the wire name differs, which is where a careless
    // conversion drops the filter silently.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await bookingService.listBookings({
      limit: 25, offset: 50, sort_by: 'end_date', sort_dir: 'desc', booking_status: 'approved',
    });

    expect(mockGet).toHaveBeenCalledWith('/bookings/', {
      params: { limit: 25, offset: 50, sort_by: 'end_date', sort_dir: 'desc', booking_status: 'approved' },
    });
  });
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/services/__tests__/bookingServicePaged.test.ts
```

Expected: all three FAIL — the first two because `listBookings` resolves a bare array, the third because the param type rejects the new keys.

- [ ] **Step 3: Implement the service**

Widen the inline literal and return a page. There is no `toParams` here — params pass straight through — so widening the type is the whole change:

```ts
  listBookings: (params?: {
    environment_id?: number;
    start?: string;
    end?: string;
    booking_status?: string;
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<BookingResponse>> =>
    api.get<BookingResponse[]>('/bookings/', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
```

- [ ] **Step 4: Update the slice**

In `frontend/src/store/bookingSlice.ts`, add `total: number` and `listLoading: boolean` to the state and `total: 0, listLoading: false` to `initialState`. Move the three `fetchBookings` cases onto `listLoading`, storing `action.payload.rows` and `action.payload.total`, and keep the abort guard — copy the comment verbatim from `frontend/src/store/deploymentSlice.ts`:

```ts
      .addCase(fetchBookings.rejected, (state, action) => {
        if (action.meta.aborted) return;
        state.listLoading = false;
        state.error = action.error.message ?? 'Failed to load bookings';
      })
```

Every other thunk on the slice keeps writing `loading`.

- [ ] **Step 5: Fix what `tsc` reports**

`fetchBookings`'s payload type changed. Run `npx tsc --noEmit` and fix each consumer minimally — do **not** convert `BookingList` here, that is Task 3.

**Then check for the trap `tsc` cannot see:** any component reading `state.booking.loading` for a spinner driven by `fetchBookings` now has a dead spinner, because `loading` still exists and is still boolean. Task 1 already moved `BookingCalendar` off the slice entirely. Run `grep -rnE "s\.booking\b|state\.booking\b" frontend/src` and report every hit with your judgement on it.

- [ ] **Step 6: Run tests, verify discrimination, commit**

```bash
cd frontend && npx vitest run src/services/__tests__/bookingServicePaged.test.ts && npx tsc --noEmit
```

Then delete `booking_status` from the widened param type, confirm the third test fails to compile or fails, and restore.

```bash
git add frontend/src/services/bookingService.ts frontend/src/store/bookingSlice.ts frontend/src/services/__tests__/bookingServicePaged.test.ts
git commit -m "feat(bookings): return and store a page, not a bare array"
```

---

### Task 3: convert `BookingList`

`BookingList` uses **raw `DataGrid`**, so it needs `disableColumnFilter` explicitly — see Global Constraints.

**Files:**
- Modify: `frontend/src/pages/bookings/BookingList.tsx`
- Test: `frontend/src/pages/bookings/__tests__/bookingListServerGrid.test.tsx` (create)

**Interfaces:**
- Consumes: Task 2's `Paged` service and the slice's `total`/`listLoading`.
- Produces: nothing later tasks depend on.

**Before you start:** `grep -rnE "s\.booking\b|state\.booking\b" frontend/src`. Task 1 moved `BookingCalendar` off this slice; confirm nothing else reads its list, and report anything you find rather than converting silently.

- [ ] **Step 1: Write the failing tests**

Follow `frontend/src/pages/deployments/__tests__/deploymentListServerGrid.test.tsx` for the harness.

```tsx
  it('sends paging, sorting and the wire-named status filter', async () => {
    renderBookingList('/bookings?page=2&sort_by=end_date&sort_dir=desc&booking_status=approved');

    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 50, sort_by: 'end_date', sort_dir: 'desc', booking_status: 'approved',
    }));
  });

  it('marks joined and computed columns unsortable', () => {
    // GET /bookings/ whitelists start_date, end_date and status only.
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));

    expect(byField.start_date.sortable).not.toBe(false);
    expect(byField.end_date.sortable).not.toBe(false);
    expect(byField.status.sortable).not.toBe(false);

    ['project_name', 'environment_name', 'booked_by_username', 'booking_type_id', 'conflicts', 'actions']
      .forEach((field) => expect(byField[field].sortable).toBe(false));
  });

  it('disables the column filter, which would filter only the loaded page', () => {
    // Raw DataGrid gates the column-menu Filter item on this prop alone, not
    // on whether a toolbar is rendered. Without it the menu filters 25 rows
    // while the footer shows the server total.
    renderBookingList('/bookings');
    expect(gridProps().disableColumnFilter).toBe(true);
  });
```

Export the columns as `export const bookingColumns` from `BookingList.tsx`, with the scoped `// eslint-disable-next-line react-refresh/only-export-components` PR A's pages needed. For `gridProps()`, follow whatever PR A's equivalent `disableColumnFilter` test does — read `frontend/src/pages/deployments/__tests__/deploymentListServerGrid.test.tsx` and copy that approach rather than inventing one.

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/pages/bookings/__tests__/bookingListServerGrid.test.tsx
```

- [ ] **Step 3: Convert the page**

```tsx
  const { bookings, total, listLoading } = useSelector((s: RootState) => s.booking);

  const grid = useServerGrid({
    endpoint: 'bookings',
    // `booking_status`, not `status` — the wire name differs from the label.
    filterKeys: ['booking_status'],
    onFetch: (params) => dispatch(fetchBookings(params)),
    total,
    totalPending: listLoading,
  });
```

No `debounceKeys` — this page has no text filter. The Status select reads `grid.filters.booking_status` and writes via `grid.setFilter('booking_status', value)`.

Delete the client-side `.filter(...)` entirely; `rows` maps `bookings` directly.

`conflicts` is computed after the page is fetched, so it gets `sortable: false` **and** `ComputedColumnHeader` — match its usage in `frontend/src/pages/builds/BuildList.tsx`.

Server-mode `DataGrid` props exactly as `DeploymentList` uses them, including `disableColumnFilter` and `pageSizeOptions={[10, 25, 50, 100]}`.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Verify the tests discriminate**

Three mutations, each restored: drop `booking_status` from `filterKeys` (first test fails); delete `sortable: false` from `project_name` (second fails); remove `disableColumnFilter` (third fails). Report all three failing outputs.

- [ ] **Step 6: Full suite, lint, types, commit**

```bash
cd frontend && npx vitest run && npm run lint && npx tsc --noEmit
git add frontend/src/pages/bookings/
git commit -m "feat(bookings): server-side paging, sorting and filtering on the list"
```

---

### Task 4: `changeRequestService` and `changeRequestSlice` return and store a page

**Files:**
- Modify: `frontend/src/services/changeRequestService.ts:15-16`
- Modify: `frontend/src/types/changeRequest.ts` (`ChangeRequestListFilters`)
- Modify: `frontend/src/store/changeRequestSlice.ts`
- Test: `frontend/src/services/__tests__/changeRequestServicePaged.test.ts` (create)

**Interfaces:**
- Produces: `changeRequestService.list(filters)` resolves `Paged<ChangeRequestResponse>`. `ChangeRequestState` gains `total` and `listLoading`.

- [ ] **Step 1: Write the failing tests**

Same three-test shape as Task 2, against `/change-requests`, with this third case:

```ts
  it('forwards paging, sorting and the scalar collection filters', async () => {
    // The page filters cr.environment_ids/host_ids client-side today; the
    // server takes scalars. Sending an array here would not filter.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await changeRequestService.list({
      limit: 25, offset: 0, sort_by: 'title', sort_dir: 'asc',
      status: 'approved', environment_id: 4, host_id: 9,
    });

    expect(mockGet).toHaveBeenCalledWith('/change-requests', {
      params: { limit: 25, offset: 0, sort_by: 'title', sort_dir: 'asc', status: 'approved', environment_id: 4, host_id: 9 },
    });
  });
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Add `limit`, `offset`, `sort_by`, `sort_dir` to `ChangeRequestListFilters` (`environment_id`, `host_id` and `status` may already be there — check before adding). Params pass straight through to axios, so no mapping layer is involved:

```ts
  list: (filters: ChangeRequestListFilters = {}): Promise<Paged<ChangeRequestResponse>> =>
    api.get<ChangeRequestResponse[]>('/change-requests', { params: filters }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
```

- [ ] **Step 4: Update the slice**

As Task 2 Step 4, against `changeRequestSlice.ts` and its list thunk: `total`, `listLoading`, the three cases, the abort guard verbatim, every other thunk left on `loading`.

- [ ] **Step 5: `tsc`, then the spinner grep**

`grep -rnE "s\.changeRequest\b|state\.changeRequest\b" frontend/src` and report each hit. A sweep during planning found only `ChangeRequestDetail`, which reads `detail` and not the list — confirm rather than assume.

- [ ] **Step 6: Discrimination check and commit**

Delete `environment_id` from the filter interface, confirm the third test fails, restore.

```bash
git commit -m "feat(change-requests): return and store a page, not a bare array"
```

---

### Task 5: convert `ChangeRequestList`

This page uses the shared **`DataTable`**, which already sets `disableColumnFilter` and suppresses CSV/Print export in server mode. Do **not** hand-roll those.

**Files:**
- Modify: `frontend/src/pages/change-requests/ChangeRequestList.tsx`
- Test: `frontend/src/pages/change-requests/__tests__/changeRequestListServerGrid.test.tsx` (create)

- [ ] **Step 1: Write the failing tests**

```tsx
  it('sends paging, sorting and the collection filters as scalars', async () => {
    renderChangeRequestList('/change-requests?page=1&sort_by=title&sort_dir=asc&environment_id=4');

    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'title', sort_dir: 'asc', environment_id: '4',
    }));
  });

  it('marks id and computed columns unsortable', () => {
    // GET /change-requests whitelists title, change_type, status and
    // scheduled_start only. `id` is in no endpoint's whitelist.
    const byField = Object.fromEntries(changeRequestColumns.map((c) => [c.field, c]));

    ['title', 'change_type', 'status', 'scheduled_start']
      .forEach((f) => expect(byField[f].sortable).not.toBe(false));
    ['id', 'environments', 'hosts', 'has_outage']
      .forEach((f) => expect(byField[f].sortable).toBe(false));
  });
```

Note the expected `environment_id` is the **string** `'4'` — filter values come from the URL. If the page needs a number, convert at the call site and assert what actually reaches the service.

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Convert the page**

```tsx
  const { list, total, listLoading } = useSelector((s: RootState) => s.changeRequest);

  const grid = useServerGrid({
    endpoint: 'change-requests',
    filterKeys: ['status', 'environment_id', 'host_id'],
    onFetch: (params) => dispatch(fetchChangeRequests(params)),
    total,
    totalPending: listLoading,
  });
```

The three selects read from `grid.filters` and write via `grid.setFilter`. **The environment and host selects change meaning**: they used to test membership of `cr.environment_ids` / `cr.host_ids` in the browser; they now send a scalar id the server filters on. Delete the `filteredRows` memo.

`environments`, `hosts` and `has_outage` are computed after the page is fetched — `sortable: false` plus `ComputedColumnHeader` on each.

Pass `DataTable` the server props (`rowCount`, `paginationMode="server"`, `sortingMode="server"`, `paginationModel`, `onPaginationModelChange`, `sortModel`, `onSortModelChange`, `pageSizeOptions={[10, 25, 50, 100]}`) and `loading={listLoading}`.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Verify the tests discriminate**

Drop `environment_id` from `filterKeys` (first fails); delete `sortable: false` from `has_outage` (second fails). Restore both, report the output.

- [ ] **Step 6: Full suite, lint, types, commit**

```bash
git commit -m "feat(change-requests): server-side paging, sorting and filtering on the list"
```

---

### Task 6: `incidentService` and `incidentSlice` return and store a page

**The service needs no type change** — `list(params: Record<string, unknown> = {})` already accepts anything. Only the return shape changes.

**Files:**
- Modify: `frontend/src/services/incidentService.ts:5-6`
- Modify: `frontend/src/store/incidentSlice.ts`
- Test: `frontend/src/services/__tests__/incidentServicePaged.test.ts` (create)

- [ ] **Step 1: Write the failing tests**

Same three-test shape; the third:

```ts
  it('forwards paging, sorting and the three select filters', async () => {
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await incidentService.list({
      limit: 25, offset: 0, sort_by: 'severity', sort_dir: 'asc',
      status: 'open', severity: 'P1', system_id: 3,
    });

    expect(mockGet).toHaveBeenCalledWith('/incidents', {
      params: { limit: 25, offset: 0, sort_by: 'severity', sort_dir: 'asc', status: 'open', severity: 'P1', system_id: 3 },
    });
  });
```

- [ ] **Step 2: Run to verify the first two fail and the third passes**

The third passes already — the permissive signature forwards everything. That is deliberate: it pins the contract the page depends on. If it fails, stop and re-read the service.

- [ ] **Step 3: Implement**

```ts
  list: (params: Record<string, unknown> = {}): Promise<Paged<IncidentListRow>> =>
    api.get<IncidentListRow[]>('/incidents', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
```

- [ ] **Step 4: Update the slice** — as Task 2 Step 4, against `incidentSlice.ts`.

- [ ] **Step 5: `tsc`, then the spinner grep**

`grep -rnE "s\.incident\b|state\.incident\b" frontend/src`. Planning found `IncidentDetail` and `IncidentForm` reading `detail`, not the list — confirm and report.

Note `frontend/src/store/__tests__/incidentSlice.test.ts` already exists. If the payload change breaks it, that is expected — but say exactly what you changed and why, because a pre-existing test that stops discriminating is the most serious thing that can go wrong here.

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(incidents): return and store a page, not a bare array"
```

---

### Task 7: convert `IncidentList`

Uses the shared **`DataTable`** — same as Task 5, do not hand-roll its guards.

**Files:**
- Modify: `frontend/src/pages/incidents/IncidentList.tsx`
- Test: `frontend/src/pages/incidents/__tests__/incidentListServerGrid.test.tsx` (create)

- [ ] **Step 1: Write the failing tests**

```tsx
  it('sends paging, sorting and all three select filters', async () => {
    renderIncidentList('/incidents?page=1&sort_by=severity&sort_dir=asc&status=open&severity=P1&system_id=3');

    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 25, sort_by: 'severity', sort_dir: 'asc',
      status: 'open', severity: 'P1', system_id: '3',
    }));
  });

  it('marks joined and computed columns unsortable', () => {
    // GET /incidents whitelists title, severity, status, detected_at,
    // resolved_at only.
    const byField = Object.fromEntries(incidentColumns.map((c) => [c.field, c]));

    ['title', 'severity', 'status', 'detected_at', 'resolved_at']
      .forEach((f) => expect(byField[f].sortable).not.toBe(false));
    ['system_name', 'environment_name', 'release_name', 'fix_release', 'pir_status']
      .forEach((f) => expect(byField[f].sortable).toBe(false));
  });
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Convert the page**

```tsx
  const { list, total, listLoading } = useSelector((s: RootState) => s.incident);

  const grid = useServerGrid({
    endpoint: 'incidents',
    filterKeys: ['status', 'severity', 'system_id'],
    onFetch: (params) => dispatch(fetchIncidents(params)),
    total,
    totalPending: listLoading,
  });
```

Delete the `filteredRows` memo. `pir_status` is computed after the page is fetched — `sortable: false` plus `ComputedColumnHeader`.

**Check how the status options are built.** The page derives `statusOptions` with a `useMemo` (around line 39). If that memo derives options *from the rows currently loaded*, it now only offers statuses present on the current page — which would make a filter unable to reach the rows it needs. If so, source the options from a static list or the lifecycle definition instead, and say what you found in your report.

Pass `DataTable` the same server props as Task 5.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Verify the tests discriminate**

Drop `system_id` from `filterKeys` (first fails); delete `sortable: false` from `pir_status` (second fails). Restore, report output.

- [ ] **Step 6: Full suite, lint, types, commit**

```bash
git commit -m "feat(incidents): server-side paging, sorting and filtering on the list"
```

---

### Task 8: verify in a browser, document, and open the PR

Four defects in this programme have been found only by opening the page — case-sensitive sorting, `Release #47`, keystroke clobbering, and a column filter that contradicted its own footer — every one with a fully green suite. This step is not a formality.

- [ ] **Step 1: Run every gate**

```bash
cd frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

- [ ] **Step 2: Verify in the browser**

With `docker-compose up -d`, the backend on :8000 and `npm run dev` on :5173, sign in as `admin`/`admin123` (tenant `demo`). On **each** of `/bookings`, `/change-requests` and `/incidents`:

- The grid renders and the spinner clears.
- A sortable header sorts. First click is **ascending** — change-requests and incidents default to `desc`, so a first click landing descending means `sort_dir` is not being sent.
- An unsortable header offers no sort arrow, and a computed column's header explains why on hover **and on keyboard focus**.
- Opening a column's ⋮ menu offers **no Filter item**.
- Changing a select narrows the **footer total**, not just the visible rows — that is the difference between server-side filtering and the bug being removed.
- Paging to page 2 issues a request (watch the Network tab for `offset=`).
- The URL carries the state and a refresh reproduces the view.

Then on `/bookings/calendar` (Task 1): the calendar still shows a full month of bookings, and its environment filter still works.

Record what you saw per page. If any check fails, stop and report — do not open the PR.

- [ ] **Step 3: Update `docs/pagination.md`**

Record that PR B's three pages are converted and **three remain** (environments, systems, infrastructure-components). Note that `BookingCalendar` had to be moved off the shared slice first, and that this is the same precondition PR C faces at much larger scale — `state.environment.environments` has 8 non-page consumers and `state.infrastructureComponent.components` has 4.

- [ ] **Step 4: Commit, push, open the PR**

Body should cover: the three pages; the two non-pass-through filter mappings; that `BookingCalendar` was a prerequisite not a cleanup; that two pages used `DataTable` and one raw `DataGrid`; the browser checks performed; and test counts.

- [ ] **Step 5: Confirm CI is green before reporting done**

```bash
gh pr checks <N> --repo pjgross/envmgr
```

All four jobs must pass. Do not report ready on a partial result.

---

## What this plan does not cover

**PR C** — EnvironmentList, SystemCatalog, InfrastructureComponentList — gets its own plan. It is the hardest of the three:

- All three have **text search**, so they are the first to exercise the drafts machinery on a page other than PR A's.
- All three do **inline create/update/delete**, so they are the first to need `refetch()` and the first that must delete their slices' optimistic list surgery. Keeping both double-counts `total` and shows a row twice for one round trip.
- `systemService.listSystems()` takes **no params argument at all** and must grow both a signature and a `Paged` return.
- The blast radius is the largest in the programme: `state.environment.environments` has 8 non-page consumers, `state.infrastructureComponent.components` has 4. Task 1 of this plan is the small version of what PR C needs at 3× the scale — **convert those consumers off the shared list before converting the pages that own them.**
