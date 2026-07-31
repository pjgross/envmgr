# Pagination sub-project C3 — server-side list pages

**Status**: design, not started. Backend halves A, B and C1 are merged (`main` tip `d1303c5`).

## The bug this fixes

Every list page fetches a capped page and then filters it *in the browser*. `ReleaseList`
dispatches `fetchReleases({})` with no parameters, receives the newest 50 releases, and filters
those 50 by status, type, kind and system in a `useMemo`. A tenant with more than 50 releases
gets answers computed from a truncated set, with nothing in the UI saying so. Eight other pages
have the identical shape: local filter state, one client-side `.filter()`, a `DataTable` doing
client-side paging and sorting over whatever arrived.

The backend halves removed the server's part of this. C3 is the half that makes the browser stop
lying: the server does the filtering, sorting and windowing, and the grid renders exactly what it
is given.

`X-Total-Count` is currently read nowhere in the frontend — every service ends
`.then((r) => r.data)`, discarding headers. That is the first thing to change.

## Scope

Nine list pages, matching the nine endpoints C1 wired to `sorting()`:

| Page | Endpoint |
|---|---|
| `pages/releases/ReleaseList.tsx` | `GET /releases` |
| `pages/bookings/BookingList.tsx` | `GET /bookings/` |
| `pages/environments/EnvironmentList.tsx` | `GET /environments/` |
| `pages/change-requests/ChangeRequestList.tsx` | `GET /change-requests` |
| `pages/systems/SystemCatalog.tsx` | `GET /systems/` |
| `pages/infrastructure/InfrastructureComponentList.tsx` | `GET /infrastructure-components/` |
| `pages/incidents/IncidentList.tsx` | `GET /incidents` |
| `pages/deployments/DeploymentList.tsx` | `GET /deployments` |
| `pages/builds/BuildList.tsx` | `GET /builds` |

Delivered in two parts. **Pilot**: the shared plumbing plus `ReleaseList` converted end to end.
**Rollout**: the remaining eight against the proven pattern.

Out of scope, recorded and unchanged: the `limit=500` truncation in `/releases/calendar` and
`/releases/timeline`; sorting by joined names (`environment_name`, `release_name`); the endpoints
still unbounded; and the `current`/`history` duplication in the membership view.

## The contract file

`frontend/src/constants/sortWhitelists.json` — one checked-in transcription of the nine whitelists
and their default directions:

```json
{
  "releases": {
    "sortable": ["name", "release_type", "release_kind", "status", "target_date", "created_at"],
    "default": "created_at",
    "default_dir": "desc"
  },
  "environments": {
    "sortable": ["name", "environment_type", "status", "created_at"],
    "default": "name",
    "default_dir": "asc"
  }
}
```

…and so on for `bookings`, `change-requests`, `systems`, `infrastructure-components`,
`incidents`, `deployments`, `builds`.

It is consumed from both sides:

- **Backend test** asserts the file matches `RELEASE_SORTS`, `ENVIRONMENT_SORTS`, `BOOKING_SORTS`,
  `CHANGE_REQUEST_SORTS`, `SYSTEM_SORTS`, `INFRASTRUCTURE_SORTS`, `INCIDENT_SORTS`,
  `DEPLOYMENT_SORTS` and `BUILD_SORTS` — key sets and `default`/`default_dir` — in
  `backend/app/api/v1/`. It resolves the path repo-relative and **fails** if the file is missing
  rather than skipping; a silently skipped contract test enforces nothing.
- **Frontend** imports it to set `sortable` on grid columns, to validate `sort_by` arriving from a
  URL, and as the subject of a per-grid test.

It lives under `frontend/src/` rather than `docs/` because the frontend image's Docker build
context is `./frontend` (see `docker-compose.yml`). A JSON file outside that directory is absent at
image-build time, so importing it from frontend source would build locally and fail in the image.
The backend reads it across directories instead, which is safe: it is touched only by a test, and
the backend image never runs tests.

This is the point of the file. `docs/pagination.md` states that a grid column left sortable whose
field the backend doesn't whitelist "gives the user a header that looks clickable and 422s the
moment they click it", and that **nothing in either codebase enforces this**. A hand-mirrored
TypeScript constant would enforce the frontend half while staying silently wrong if a Python
whitelist changed. One file read by tests on both sides makes cross-language drift a CI failure:
CI already runs a backend job and a frontend job on every push.

## `useServerGrid`

`frontend/src/hooks/useServerGrid.ts`. Owns the mechanics; the request itself still goes through
the existing Redux thunk and service, so `CLAUDE.md`'s "no API calls in components" rule holds and
other call sites that refetch a list (for example `ReleaseForm` after a create) keep working.

```ts
const grid = useServerGrid({
  endpoint: 'releases',            // key into the contract file
  filterKeys: ['status', 'release_type', 'release_kind', 'system_id'],
  fetch: (params) => dispatch(fetchReleases(params)),
});
```

Responsibilities:

**URL as the source of truth.** `page`, `page_size`, `sort_by`, `sort_dir` and that page's filter
keys live in the query string via `useSearchParams` (not currently used anywhere in the app;
`react-router-dom` is already a dependency). Refresh and back/forward restore the view, and a
filtered list can be sent to a colleague as a link.

**Validation before the network.** A `sort_by` read from the URL is checked against the contract
file first. Unknown field → fall back to that endpoint's default and strip it from the URL. Without
this, a bookmarked `?sort_by=phase_count` is a 422 on page load — the whitelist is a 422, not a
silent fallback, by design.

**`sort_dir` is always explicit.** Whenever a sort is active the hook sends both parameters, never
`sort_by` alone. `sorting()` takes one endpoint-wide `default_dir`, and four of the nine use
`"desc"`, so `?sort_by=title` with no direction resolves to descending — a first click on a column
header would render descending, which is not what a user expects. The omitted-direction default is
only ever correct for "no sort requested at all".

**Translation.** DataGrid's `{ page, pageSize }` ⇄ the API's `limit`/`offset`, where
`offset = page * pageSize`. Every option in `pageSizeOptions` (10/25/50/100) sits under every
endpoint cap, including the tightest — `GET /releases` at 200.

**Debounce and staleness.** Free-text filters fire 300 ms after typing stops; selects and toggles
fire immediately. Each dispatch carries a sequence number and a response whose number is no longer
current is discarded, so out-of-order replies cannot paint stale rows.

**Page reset.** Changing a filter or a sort resets `page` to 0. Without this a user on page 5 who
narrows the result set to 10 rows sends `offset=100` and gets an empty grid over a non-zero total.

## Service and slice shape

Services stop discarding headers:

```ts
list: (params: ReleaseListParams = {}): Promise<Paged<ReleaseListItemResponse>> =>
  api.get('/releases', { params }).then((r) => ({
    rows: r.data,
    total: Number(r.headers['x-total-count'] ?? r.data.length),
  })),
```

`Paged<T> = { rows: T[]; total: number }` in `types/pagination.ts`. Slices store `total` beside
`list`; `fetchX.fulfilled` sets both.

The `?? r.data.length` fallback keeps the grid coherent when the header is absent rather than
reporting `total: NaN` — which is what a cross-origin deployment produces today (see below).

Filter params gain `limit`, `offset`, `sort_by`, `sort_dir` alongside each page's existing keys.
`ReleaseListFilters` already carries `status`, `release_type`, `release_kind` and `system_id`, and
`GET /releases` already accepts all four, so `ReleaseList` needs no new backend parameter.

## `DataTable`

Gains optional pass-through props: `rowCount`, `paginationMode`, `sortingMode`, `paginationModel`,
`onPaginationModelChange`, `sortModel`, `onSortModelChange`. Omitted, behaviour is exactly as
today — the twelve other `DataGrid` call sites (admin panels, release tabs, enterprise rollups)
are untouched.

DataGrid 6.20.4 Community supports all three server modes; no version bump and no Pro licence.
Community is single-column sort only, which matches the backend's single `sort_by`.

## The twelve columns that lose sorting

`phase_count`, `scope_count`, `scope_change_count`, `blocker_count`, `overdue_criterion_count`,
`conflicts`, `pir_status`, `latest_step`, `has_outage`, `systems`, `environments`, `hosts` are
computed after the page is fetched — most in Python from batch queries keyed on the page's row
ids, `latest_step` in the browser from a JSON field. None can be sorted server-side, and
restructuring them is out of scope for C3 as it was for C1.

Users can sort these columns today, because the grid holds the whole truncated page and sorts
that. What they have is a sort of the wrong set, not a correct one — but the capability visibly
disappears, so it gets an explanation rather than a silently dead header. Each renders with
`sortable: false` and a tooltip:

> Computed after the page is fetched — not sortable across all results.

A small shared `ComputedColumnHeader` component carries it. Five of the twelve are on
`ReleaseList` (`phase_count`, `scope_count`, `scope_change_count`, `blocker_count`, `systems`) so
the pilot exercises it.

## Failure handling

A 422 should be unreachable once URL validation is in place, so treating it as an ordinary error
would hide a contract bug. The hook resets to the endpoint's default sort, refetches, and raises a
snackbar via the existing `useSnackbar`.

Network and 5xx failures keep the current per-slice `error` behaviour: loading stops, the page
shows its existing error UI, the grid keeps its last rows.

If a response is empty with `offset > 0` and `total > 0` — a row deleted in another tab — the hook
clamps to the last valid page and refetches once.

Nothing falls back to client-side filtering on failure. A page that quietly filters a truncated
set is the bug being removed.

## CORS

Add `expose_headers=["X-Total-Count"]` to the `CORSMiddleware` in `backend/app/main.py`.
`allow_headers=["*"]` governs *request* headers and does not expose response headers to JavaScript.

Nothing is broken today: `src/services/api.ts` uses a relative `/api/v1` baseURL, so the bundle is
always same-origin with the API (Vite proxy in dev, nginx in prod). But after C3 the entire
frontend depends on reading that header, and the failure mode if the origins are ever split is a
grid that believes `total` equals the current page length — silently confident and wrong, the same
class of bug C3 exists to remove.

## Testing

**Backend**
- Contract file matches all nine `*_SORTS` dicts, including `default` and `default_dir`.

**Frontend unit (vitest + testing-library)**
- URL round-trip: state → query string → state.
- `sort_dir` is always sent alongside `sort_by`.
- An out-of-whitelist `sort_by` from the URL never reaches the network and is stripped.
- Debounce: text filters coalesce; selects fire immediately.
- A stale response (superseded sequence number) is discarded.
- Filter and sort changes reset `page` to 0.
- Empty page with `offset > 0` clamps and refetches once.
- Per grid: every column's `sortable` agrees with the contract file.

**E2E (Playwright)**
- ReleaseList page 2 returns different ids than page 1.
- A column-header click issues a request and the order changes.
- A filter change narrows `rowCount`, not just the visible rows.

Ordering and pagination are exactly where this repo has previously shipped tests that guarded
nothing — see `reference_nondiscriminating_tests.md`. Every test above is to be checked by
breaking the thing it covers and confirming it fails: delete the page reset and the reset test must
fail; drop `sort_dir` and its test must fail; add a sortable computed column and the agreement test
must fail.

## Order of work

1. Contract file + backend agreement test.
2. `Paged<T>`, service and slice changes for releases.
3. `useServerGrid` + unit tests.
4. `DataTable` server props.
5. `ReleaseList` converted; `ComputedColumnHeader` on its five computed columns.
6. CORS `expose_headers`.
7. E2E pass.
8. — pilot reviewed here —
9. The remaining eight pages.

## Open question for the rollout

`ChangeRequestList` filters by environment and host, and `IncidentList` by system. Whether those
have server parameters is unverified — only `ReleaseList`'s four were checked during design. Any
that don't will need either a backend filter parameter (a small addition in C3's shape, since C1
established the pattern) or an explicit decision to drop the filter. To be resolved per page
during the rollout, not assumed.
