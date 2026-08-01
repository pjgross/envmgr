# Pagination sub-project C3 — the rollout

**Status**: design, not started. The C3 pilot is merged (`main` tip `ceca103`); this is step 9 of
[the pilot's design](2026-07-31-pagination-c3-design.md), the eight remaining pages.

## What is left

The pilot converted `ReleaseList` and built the shared plumbing: the contract file
`frontend/src/constants/sortWhitelists.json`, `useServerGrid`, `serverGridParams`, `DataTable`'s
server mode and `ComputedColumnHeader`. Eight pages still fetch a capped page and filter and sort
it in the browser, which is the live bug the whole programme exists to remove:

| Page | Endpoint | Lines |
|---|---|---|
| `pages/deployments/DeploymentList.tsx` | `GET /deployments` | 115 |
| `pages/builds/BuildList.tsx` | `GET /builds` | 106 |
| `pages/bookings/BookingList.tsx` | `GET /bookings/` | 343 |
| `pages/change-requests/ChangeRequestList.tsx` | `GET /change-requests` | 233 |
| `pages/incidents/IncidentList.tsx` | `GET /incidents` | 270 |
| `pages/environments/EnvironmentList.tsx` | `GET /environments/` | 446 |
| `pages/systems/SystemCatalog.tsx` | `GET /systems/` | 381 |
| `pages/infrastructure/InfrastructureComponentList.tsx` | `GET /infrastructure-components/` | 419 |

## The pilot's open question is resolved: no backend work

The pilot's design closed with an open question — whether `ChangeRequestList`'s environment and
host filters and `IncidentList`'s system filter had server parameters, "to be resolved per page
during the rollout, not assumed". Checked against the endpoint signatures, **every filter on all
eight pages already has a server parameter.** Sub-project C1 added exactly the ones the grids
needed, so this rollout is purely frontend.

| Page | Client-side filters today | Server parameter |
|---|---|---|
| BookingList | status | `booking_status` |
| EnvironmentList | search (name), status | `search`, `status`, `environment_type` |
| ChangeRequestList | status, environment, host | `status`, `environment_id`, `host_id` |
| SystemCatalog | search (name) | `search` |
| InfrastructureComponentList | search (name/provider/region), type | `search`, `component_type` |
| IncidentList | status, severity, system | `status`, `severity`, `system_id` |
| DeploymentList | status, environment (text), release (text) | `status`, `environment_search`, `release_search` |
| BuildList | subsystem (text) | `subsystem_search` |

Two names differ from the page's local state and must be mapped rather than passed through:
`BookingList`'s `status` is `booking_status` on the wire, and `ChangeRequestList` filters a
*collection* client-side (`cr.environment_ids.includes(envFilter)`) where the server takes a scalar
`environment_id`. Neither is a behaviour change; both are places a careless conversion silently
drops the filter.

## Sequencing

A prep PR, then three page PRs in ascending difficulty. The cheapest pages go first so the pattern
is proven to repeat before the expensive ones commit to it.

| PR | Pages | Why grouped |
|---|---|---|
| **0 · prep** | — | Shared prerequisites, landed once before any page depends on them |
| **A** | DeploymentList, BuildList | Smallest, and already pass some filters server-side — largely deleting the client `.filter()` |
| **B** | BookingList, ChangeRequestList, IncidentList | Select-only filters, no inline mutations |
| **C** | EnvironmentList, SystemCatalog, InfrastructureComponentList | Text search **and** inline create/update/delete — the only three needing `refetch()` |

Rejected: grouping by domain area, which pairs a trivial page with a hard one so a regression in
one blocks the other; and hardest-first, which spends the largest diff before knowing whether the
pattern needs adjusting.

## PR 0 — the prep

Everything `docs/pagination.md` recorded as "deliberately not fixed" during the pilot, plus one bug
found while designing this rollout. These are prerequisites: each one is a trap the very first
converted page would fall into.

### 1. The `'all'` sentinel will eat a real search term

`serverGridParams.ts` drops any filter value of `''` or `'all'`, for **every** key:

```ts
const NO_FILTER = ['', 'all'];
// ...
if (!RESERVED.has(key) && !NO_FILTER.includes(value)) params[key] = value;
```

`ReleaseList` has no text input so it cannot bite yet. Five of the eight pages do, and typing `all`
into one would silently return unfiltered results while the box still reads "all" — a wrong answer
presented as a filtered one, the same class of bug C3 exists to remove.

`buildParams` gains the page's text-filter keys and treats `'all'` as absent only for keys outside
that set. `''` stays universally absent, since an empty text box and an unset select mean the same
thing.

### 2. `useServerGrid` has no `refetch()`

The fetch effect is keyed purely on the resolved params, so nothing can re-run the current query.
That is why the release slice still performs optimistic surgery on its list after a create or
delete — which server paging makes structurally wrong, because a new row need not belong on the
current page at all, and a page that had 25 rows should still have 25 after one is deleted.

`environmentSlice` is the clearest case: `createEnvironment.fulfilled` does
`state.environments.push(...)`, `deleteEnvironment.fulfilled` does `state.environments.filter(...)`,
and `updateEnvironment.fulfilled` replaces by index. All three are wrong once the array is a server
page. Add `refetch()` to the hook, and have PR C's pages call it instead of mutating the array.

### 3. One `loading` boolean per slice

Each slice has a single flag shared by roughly twenty thunks. Abort-based cancellation introduces a
thunk that can end *without* a successor raising the flag again, which during the pilot left
`loading` stuck true after an unmount and hung `/releases/calendar` and `/releases/timeline`. Every
slice converted here inherits that shape, so converted slices get a separate `listLoading` rather
than sharing the general one.

### 4. `ScopeHistoryDrawer` reads a slice that no longer means what it assumes

**A live bug on `main`, not a hazard for later.** `ScopeHistoryDrawer.tsx:44` reads
`s.release.list` to build a release-name lookup for a scope item's move history, and **never
dispatches `fetchReleases` itself** — it relies entirely on whatever another page left in the
slice. Since the pilot, that is `ReleaseList`'s current filtered page of 25, so a scope item moved
between older releases renders `Release #47` (line 81) instead of a name.

This is the third consumer of that shape. The pilot fixed `MoveScopeItemDialog`, a whole-branch
review caught `RequestAdmissionDialog`, and both sweeps missed this one. It also breaks the
standing rule that entities are rendered by name, never as `#N`. Fix it the same way as the other
two: its own fetch into local state.

The lesson is procedural and belongs in the per-page recipe below — **grep every consumer of a
slice before converting the page that owns it**, because nothing type-checks when an array's
*meaning* changes but its shape does not.

### 5. Three sibling pickers still truncated at 50

`IncidentForm`, `DoraDashboard` and `ScopeWindowsTable` each call `releaseService.list()` and
discard the `total` the pilot made available. Same shape as the two dialogs already fixed.

### 6. A stale slice `total` can clamp a legitimate deep link

The clamp effect trusts whatever `total` is in the store, which need not correspond to the request
in flight. A cold load is safe (`total === 0` short-circuits), but arriving at `?page=8` with a
narrower total already in the slice rewrites the URL to page 0. Pass `total={loading ? undefined :
total}`.

## The per-page recipe

Applied eight times. Steps 1 and 6 are the ones this repo has already paid for twice.

1. **Grep every consumer of the slice**, not just the page being converted. See PR 0 item 4.
2. **Service returns `Paged<T>`** — `{ rows, total }`, reading `x-total-count` with a
   `?? r.data.length` fallback.
3. **Slice stores `total` and `listLoading`** beside its existing array. Note the array's name
   differs per slice — there is no `state.list` convention to rely on: `bookings`, `environments`,
   `list`, `systems`, `components`, `list`, `items`, `items` across the eight.
4. **Page calls `useServerGrid`** with its endpoint key and filter keys; the client-side
   `useMemo`/`.filter()` is deleted outright. Nothing falls back to client-side filtering on
   error — a page that quietly filters a truncated set is the bug being removed.
5. **Columns** take `sortable` from `isSortable()`; columns computed after the query get
   `ComputedColumnHeader` with its explanatory tooltip.
6. **`DataTable` server mode**, which also disables the toolbar's column filter and CSV/Print
   export — both operate on the loaded page only, and doing that while the footer shows the true
   server total would show two different counts under one control.

## Testing

Per grid: a column-sortable-agreement test against the contract file, and — wherever the grid sorts
a text column — an assertion on **rendered row order over mixed-case data**.

That second one is the direct lesson of the case-sensitivity bug fixed in PR #39 on 2026-08-01. The
pilot's structural assertions pinned the emitted SQL token (`"system.name DESC NULLS FIRST"`) and
stayed green while the order users actually saw was wrong; a human found it on first sight of the
page. Assertions on row order would have caught it.

Every new test is verified by breaking the thing it covers and confirming it fails — delete the
page reset and the reset test must fail; drop `sort_dir` and its test must fail. This repo has
shipped five tests that guarded nothing, all in ordering and pagination code
(`reference_nondiscriminating_tests.md`), so a green run is not on its own evidence here.

The e2e suite runs in **no CI pipeline** and is only ever run by hand. This rollout does not change
that, but any e2e added is therefore not a gate.

**Manual browser verification of each converted page is part of the work, not a follow-up.** The
pilot's automated proof passed while a visible defect sat on the page; the one thing that found it
was opening the page.

## Out of scope, recorded not fixed

- **`ScopeWindowsTable`** — a tenth grid with the same bug, and the only one this pattern cannot
  convert: it filters `window_status` and sorts `days_to_cutoff`, both computed in Python after the
  query. Converting it needs those restructured into SQL first (a `CASE` expression and a date
  diff, with dual-engine date-arithmetic risk), which is backend work in a frontend rollout. Its
  ≤50 truncation is still fixed as a picker in PR 0, so it stops silently dropping releases even
  though its grid stays client-side.
- **Sorting by joined names** (`environment_name` on a booking, `release_name` on a deployment) —
  each needs its join shape checked for whether sorting by it changes which rows come back.
- **`GET /releases/calendar` and `/releases/timeline`** — still call `list_releases` with a
  hardcoded `limit=500` and discard the total, silently truncating past 500 releases.
- The endpoints still unbounded, and the `current`/`history` duplication in the membership view.
