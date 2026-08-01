# Pagination

Most list endpoints returned every matching row for the tenant. That is fine at demo scale and
a problem at real scale: a tenant with 50k bookings gets one query that loads 50k ORM objects,
serialises them all, and hands the browser a response it renders into a DataGrid. Nothing in
the stack said no.

## The primitive

[`app/core/pagination.py`](../backend/app/core/pagination.py):

```python
@router.get("/", response_model=list[EnvironmentResponse])
async def list_environments(
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await environment_service.list_environments(
        db, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return rows
```

`pagination()` is a factory, not the dependency itself — most endpoints call it with no
arguments to get the shared 500/1000 window; the two with their own contract (below) pass
`default_limit=`/`max_limit=` overrides.

Services take `page: Optional[Page] = None` and end with `return await fetch_page(db, query, page)`,
returning `(rows, total)`. Passing `page=None` returns everything, so non-request callers keep
their old behaviour. Use `fetch_page` for a query that selects a single ORM entity; a query that
selects multiple columns (`select(Deployment, Build.git_sha, Environment.name)`) comes back from
`.scalars()` with only the first column, so it needs `fetch_page_rows` instead — same signature,
same `(rows, total)` return, but keeps whole rows.

**Deliberately backward compatible.** Endpoints still return a bare JSON array — no client
change was needed — and the unwindowed total goes in `X-Total-Count`. A client that ignores the
header behaves exactly as before up to the cap; one that reads it can tell there is more and
walk it with `?offset=`.

`limit` defaults to 500 and is capped at 1000: generous enough that no realistic current page
truncates, low enough that one pathological tenant cannot take the API down with a single
request. Asking for more than the cap is a 422, not a silent clamp.

The total is counted with a separate query against the same filters rather than a window
function, so it stays correct for queries with joins or `DISTINCT` where a window count would
double-count.

Two endpoints predate the shared primitive and keep their own limits, because both do per-row
work after the query: `GET /releases` (50/200) and `GET /deployments` (100/500). They pass
overrides to `pagination()` rather than adopting the shared 500/1000 — raising their defaults
would multiply real work, not just serialisation. `GET /builds` (100/500) is a third, added by
sub-project C1: it already had its own hand-rolled `100`/`500` limit (see *Not yet bounded*
below for what it looked like before), so C1 wired it onto `pagination()` with those same
numbers rather than widening it to the shared default — raising an endpoint's cap is a product
decision, not a side effect of giving it a total-count header.

## Sorting

Bounding the page settled *how many* rows come back; it said nothing about *which* rows. Without
an explicit order, whatever the window keeps is arbitrary, and a grid whose column headers claim
to sort needs the server to actually guarantee that order rather than re-sort whatever the
current page happens to contain. [`sorting()`](../backend/app/core/pagination.py) is the
primitive sub-project C1 added for that — a whitelist-based dependency, structurally a sibling of
`pagination()` rather than a replacement, now wired into the nine endpoints below alongside the
filter parameters they were missing.

```python
sort: Sort = Depends(sorting(ENVIRONMENT_SORTS, default="name")),
...
query = apply_sort(query, sort).order_by(Environment.name, Environment.id)
```

**The whitelist is the entire security boundary.** `allowed` maps a client-facing field name —
the string that arrives as `?sort_by=`— to the ORM column it sorts by. `sorting()` does nothing
with that string except look it up in the mapping: no `getattr`, no f-string built into an
`ORDER BY`, no path from client input to a column name at all. A `sort_by` outside the whitelist
is a **422**, not a silent fallback to the default order — the same reasoning that makes
`?limit=` past the pagination cap a 422 rather than a clamp. A client that receives a different
order than it asked for, with no error, has no reason to suspect the response isn't what it
requested.

**`apply_sort` precedes the tiebreaker; it never replaces it.**
`apply_sort(query, sort).order_by(Model.id)` still ends in `Model.id` — SQLAlchemy appends rather
than overwrites. A sort column is almost never unique (two releases share a `status`, two
bookings share a `start_date`), and sub-project A already proved, on PostgreSQL, that dropping
the tiebreaker breaks `LIMIT`/`OFFSET` paging deterministically: ties get ordered arbitrarily
between the query that produces page 1 and the one that produces page 2, so a row can appear on
both or on neither. Sorting has to compose with the total-ordering rule in *Ordering must be
total* below, not stand in for it.

**NULLs are pinned, which changes SQLite's behaviour.** SQLite orders `NULL` first on `ASC`;
PostgreSQL orders it last — so an unqualified `ORDER BY` on a nullable sortable column returned a
different page per engine before this pass. `apply_sort` now always sorts NULLs last on
ascending and first on descending, on both engines. That's a deliberate, documented behaviour
change on SQLite for the seven nullable whitelisted columns: `deployer_name`, `target_date`,
`resolved_at`, `provider`, `region`, `git_branch`, `build_number`. PostgreSQL's own default
already matched, so it is unaffected.

### The nine endpoints

| Endpoint | Sortable fields | Default | New filters |
|---|---|---|---|
| `GET /releases` | `name`, `release_type`, `release_kind`, `status`, `target_date`, `created_at` | `created_at` desc | — |
| `GET /bookings/` | `start_date`, `end_date`, `status` | `start_date` asc | — |
| `GET /environments/` | `name`, `environment_type`, `status`, `created_at` | `name` asc | `search` |
| `GET /change-requests` | `title`, `change_type`, `status`, `scheduled_start` | `scheduled_start` desc | — |
| `GET /systems/` | `name` | `name` asc | `search` |
| `GET /infrastructure-components/` | `name`, `component_type`, `provider`, `region`, `source` | `name` asc | `search` (widened to name/provider/region) |
| `GET /incidents` | `title`, `severity`, `status`, `detected_at`, `resolved_at` | `detected_at` desc | — |
| `GET /deployments` | `status`, `deployer_name`, `deployed_at` | `deployed_at` desc | `environment_search`, `release_search` |
| `GET /builds` | `git_branch`, `build_number`, `commit_timestamp` | `commit_timestamp` desc | `subsystem_search` |

Four of the nine — releases, incidents, change-requests, deployments — declare
`default_dir="desc"` because that was each endpoint's pre-existing default order, and adopting
`sorting()` was not allowed to change a default page's contents. That has a sharp edge for
anyone building a client against this table; see point 3 under *What sub-project C3 must
honour* below.

Every whitelisted field is a plain column reachable directly off the queried entity. No joined
column (`environment_name` on a booking, `release_name` on a deployment) is sortable yet — each
would need its join shape checked individually for whether sorting by it could change which rows
come back, and that check didn't happen in this pass. Nor is any column that a service computes
after the page is fetched; see point 2 below for exactly which those are and why.

### Filters that came along for the ride

Five pages filtered client-side on something their endpoint didn't accept as a parameter. Each
gained one, and every one is a case-insensitive `ilike("%...%")` — the same match the browser
already performed, so a page that later switches from client- to server-side filtering returns
the identical matching set.

| Endpoint | New parameter | Matches |
|---|---|---|
| `GET /environments/` | `search` | `name` contains |
| `GET /systems/` | `search` | `name` contains |
| `GET /infrastructure-components/` | `search` (widened) | `name` **or** `provider` **or** `region` contains — the parameter already existed but matched `name` only; the client was already searching all three |
| `GET /deployments` | `environment_search`, `release_search` | the already-joined `Environment.name` / `Release.name`, distinct from the id filters the endpoint already had |
| `GET /builds` | `subsystem_search` | the already-joined `SubSystem.name` |

## What sub-project C3 must honour

C1 produced findings that are inputs to C3's design, not just notes on its own implementation.
The working ledger they were tracked in as the sub-project progressed is a local, gitignored
file that does not ship with the repository, so they're recorded here instead — this section
**is** the contract between the two halves, not a summary of one side of it.

1. **The whitelist table above is the sortable-column contract.** C3 must set `sortable: false`
   on every grid column whose field is not a key in that endpoint's whitelist. Nothing in either
   codebase enforces this — a grid column left sortable whose field the backend doesn't
   recognise gives the user a header that looks clickable and 422s the moment they click it.
   C3's review must walk this table column by column against each grid's `columns` array, not
   spot-check it.

2. **Twelve columns can never be sorted server-side, and that is a real capability loss.**
   `phase_count`, `scope_count`, `scope_change_count`, `blocker_count`,
   `overdue_criterion_count`, `conflicts`, `pir_status`, `latest_step`, `has_outage`, `systems`,
   `environments`, `hosts` are computed after the page is fetched — most in Python from batch
   queries keyed on the page's row ids, `latest_step` in the browser from a JSON field on the
   build. They're absent from every whitelist above by necessity, not oversight; restructuring
   any of them into their query is out of scope for both C1 and C3. Users can sort by these
   columns **today**, because today's grids hold the whole (truncated) page in the browser and
   sort that — what they have today is a sort of the wrong set, not a correct one. After C3
   lands, they will have no sort on these columns at all. That is a genuine reduction in
   capability, traded for correctness, and belongs in release notes or the UI copy rather than
   being discovered by a confused user.

3. **`default_dir` is endpoint-wide, not per-field — C3 must always send `sort_dir` explicitly.**
   `sorting()` takes one `default_dir` for the whole endpoint, used only when the client sends no
   `sort_dir` at all. Four endpoints set it to `"desc"` (see the table above), so
   `GET /change-requests?sort_by=title` with no `sort_dir` resolves to **descending**, not
   ascending. A naive grid handler that omits `sort_dir` on a column-header click would therefore
   render that column descending on first click, which is not what a user expects. C3 must
   always send an explicit `sort_dir` whenever the user has chosen a sort; the omitted-direction
   default is only correct for "no sort requested at all".

4. **NULL ordering changed, deliberately, and only on SQLite.** See *Sorting* above: `apply_sort`
   now pins NULLs last on ascending sorts and first on descending, on both engines. PostgreSQL's
   default already matched; SQLite's did not, so its behaviour changed for the seven nullable
   whitelisted columns (`deployer_name`, `target_date`, `resolved_at`, `provider`, `region`,
   `git_branch`, `build_number`). This is intentional — don't mistake it for a regression if it's
   noticed during C3's manual testing against a dev SQLite database.

5. **Two enum-storage conventions coexist; check before whitelisting a new one.**
   `EnvironmentStatus` is `Enum(native_enum=False)` **without** `values_callable`, so its column
   stores the enum **name** (`"ACTIVE"`). `InfrastructureComponentType` and
   `InfrastructureComponentSource` use `values_callable`, so theirs store `.value` (lowercase).
   Sorting by `environments.status` therefore orders by the name-string; sorting by
   `infrastructure-components.component_type`/`.source` orders by the value-string. For every
   member of both enums today, name-order and value-order happen to coincide — the names and
   values differ only in case — which is member-specific luck, not a property either pattern
   guarantees. Anyone whitelisting a future enum column, in C3 or elsewhere, must check which
   convention it uses before assuming its sort order matches what the UI displays.

6. **C1 made three changes that alter existing behaviour; everything else is additive.** Every
   new query parameter above is optional, and every endpoint's default, unfiltered result is
   unchanged by C1 — that's what makes the backend half safe to merge ahead of C3. The three
   exceptions: `GET /builds` is now bounded and gained an `id` tiebreaker it never had (rows with
   distinct `commit_timestamp`s are unaffected; only true ties gain a defined order — see
   *Ordering must be total* below); NULL ordering on SQLite changed for the seven columns in
   point 4; and `GET /infrastructure-components/`'s existing `search` parameter widened from
   matching `name` only to `name` **or** `provider` **or** `region` — a change to an existing
   parameter's semantics, though inert today since no frontend page passes `search` to that
   endpoint.

## The C3 pilot

Sub-project C3 converted one page — `ReleaseList` — from the client-side pattern (fetch a
capped page, filter and sort it in the browser) to true server-side paging, sorting and
filtering, on `feature/pagination-sweep-c3`. It exists to prove the pattern once, on the
hardest of the nine grids (six sortable columns, six permanently-unsortable computed ones,
tab-scoped filters), before repeating it eight more times. What it built:

- **[`frontend/src/constants/sortWhitelists.json`](../frontend/src/constants/sortWhitelists.json)**
  — a checked-in transcription of all nine endpoints' `sortable`/`default`/`default_dir`. It
  lives under `frontend/src/`, not `docs/`, because the frontend image's Docker build context is
  `./frontend` and the file has to ship in the bundle. Enforcement is two-sided, not a
  hand-maintained copy trusted to stay in sync:
  [`backend/tests/test_sort_whitelist_contract.py`](../backend/tests/test_sort_whitelist_contract.py)
  asserts the JSON against the nine `*_SORTS` dicts directly, and
  `frontend/src/pages/releases/__tests__/releaseColumnsSortable.test.ts` asserts `releaseColumns`
  against the same JSON via `isSortable`. Cross-language drift — someone widening a backend
  whitelist without telling the frontend, or the reverse — is now a CI failure on either side,
  not something a reviewer has to notice by eye.
- **`frontend/src/hooks/serverGridParams.ts`** and **`useServerGrid.ts`** — pure param-building
  plus a hook that makes the URL the source of truth (refresh, back button, and a shared link all
  reproduce the same view), with per-key debounce, abort-based cancellation of superseded
  requests, and page clamping when a filter narrows the result set past the current offset.
- **`DataTable`** gained an optional server mode, which also turns off the toolbar's column
  filter and CSV/Print export — both operate on whatever page is loaded in the browser, and doing
  that silently while the footer shows the true server-side total would be showing the user two
  different counts under one control.
- **`ComputedColumnHeader`** — a header with a keyboard-reachable tooltip explaining *why* a
  column can't be sorted, for the six computed columns on the release grid.

Two rules the pattern depends on, not obvious from reading either hook in isolation:

**`sort_dir` is always sent explicitly, never omitted.** `resolveSort` in `serverGridParams.ts`
always returns a direction, even when the user hasn't chosen a sort — because four of the nine
endpoints declare `default_dir="desc"` (see the table above), an omitted direction on a first
header click would render that column descending, not ascending, which is not what a user
expects from a first click.

**`id` is not sortable on any converted grid.** It is not a key in any endpoint's whitelist, so
`releaseColumns` declares `id: { sortable: false }` and the same will be true of every remaining
page — there is no ID column to reclaim by whitelisting it later without a backend change.

**The hazard the rollout must not relearn: converting a page changes what its Redux slice
*means*.** Before this pilot, `state.release.list` held the newest N releases the last unbounded
fetch happened to return. After it, the same slice holds whatever page `ReleaseList`'s grid
currently has open — 25 rows, filtered and sorted however the user last left the grid. Nothing
about the slice's shape changed, only its contents' meaning, so nothing type-checks to catch a
consumer still assuming the old one. This broke `MoveScopeItemDialog`'s target-release dropdown
during this pilot: it read `state.release.list` for "every release", and started offering only
whatever subset matched the grid's active filter. The fix was to give the dialog its own
unfiltered fetch into local state rather than reading the shared slice at all (see the comment in
`frontend/src/components/releases/MoveScopeItemDialog.tsx`). **Before converting each remaining
page, grep for every other consumer of that page's list slice** — they were written against a
large, unfiltered batch, and a converted slice will quietly stop being one.

**Eight pages remain on the old client-side pattern**, unconverted until the rollout picks them
up: bookings, environments, change-requests, systems, infrastructure-components, incidents,
deployments, builds. Each fetches a capped page today and filters/sorts it in the browser —
the same live bug `ReleaseList` had, still present on all eight.

The grep advice above is necessary but was **not sufficient** — a whole-branch review found a
second consumer the pilot's own sweep had missed, `RequestAdmissionDialog`, doing the same thing
in the same way. Two dialogs now fetch their own release list into local state
(`releaseService.list({ limit: 200 })`) rather than reading the shared slice. That is the rule
for pickers: **the slice is one grid's current view; a picker that wants "all releases" must ask
for them itself.** Nothing enforces it but this paragraph.

**Manual browser verification of `ReleaseList` is done** (2026-07-31). The pilot's automated
proof — unit tests, the contract test, and
[`frontend/e2e/releases-pagination.spec.ts`](../frontend/e2e/releases-pagination.spec.ts) — passed
without catching one real defect, which a human found on the first look at the page: see
"Case-insensitive text sorting" below. Note also that the e2e suite runs in **no CI pipeline**, so
that spec — the pilot's only end-to-end evidence — is currently only ever run by hand.

### Case-insensitive text sorting (found by that verification, fixed)

Sorting the grid by name put `mortgage r1` after `Q3 2026 Enterprise Bundle` instead of next to
`Mortgage R2`. The root cause was not in the release endpoint but in `apply_sort` itself: a bare
`ORDER BY release.name` delegates ordering to the column's collation, and **every engine this app
runs on collates by byte value**, so every capitalised name sorts before every lowercase one.

- SQLite's default collation is `BINARY`.
- The app's PostgreSQL is `postgres:15-alpine` (`docker-compose.yml`), and **musl libc implements
  no locales** — the database reports `datcollate = en_US.utf8`, but `SELECT 'a' < 'B'` returns
  false. `docker-compose.prod.yml` only remaps ports, so **prod collated identically**; this was
  never a dev-only artifact.

Before C3 the grid sorted in the browser with MUI's `Intl.Collator`, which is case-insensitive, so
moving the sort into SQL is what made it visible. `apply_sort` now folds case for text columns
explicitly (`lower(col)`), applied by column type so a `DateTime` is never wrapped — for the same
reason it already pins NULLs explicitly: **row order must not depend on which engine or base image
happens to be deployed.** It also aligns sorting with filtering, where every `search` already
matches case-insensitively via `ILIKE`.

Because the fix is in the primitive, **all nine `sorting()` endpoints get it** — `name` on
environments/systems/infrastructure-components, `title` on change-requests/incidents,
`deployer_name` on deployments — so the eight pages still to be converted inherit it rather than
each rediscovering the bug. Enum-backed columns (`status`, `severity`, …) are `String` subclasses
and so are folded too, which is a no-op because they store consistent case.

Trade-off accepted: `ORDER BY lower(name)` cannot use a plain btree index on `name`. At this app's
page sizes, under a tenant filter, that is not worth a functional index — add
`CREATE INDEX ... ON tbl (lower(col))` if a list endpoint ever appears in slow queries.

Rejected alternative: swapping to a glibc `postgres:15` image. Changing a database's collation
needs a dump/restore rather than a redeploy, it would not fix SQLite, and it would leave row order
depending on which base image is running — the failure mode the NULL-pinning already exists to
prevent.

The lesson for the rollout is about the tests, not the sort: the pilot's structural assertions
pinned the *emitted SQL token* (`"system.name DESC NULLS FIRST"`), which is exactly the kind of
assertion that stays green while the user-visible ordering is wrong. The guards added with the fix
assert **rendered row order over mixed-case data** instead, and discriminate on both engines.

### Recorded during the pilot

These were found by review during the pilot. Five of the six are now fixed by this PR; the
reasoning behind each is kept below because it is exactly what the eight remaining page
conversions still need to know — why each was a trap, not just that it is gone. The one item still
open is marked as such.

- **The `'all'` sentinel eating a real search term — fixed in `c8caa4e`.** `buildParams` used to
  drop any filter value of `''` or `'all'`, for every key. That was safe only because `ReleaseList`
  had no text input — environments, systems and infrastructure-components all gain a `search`
  parameter in the rollout, and typing `all` into one of those boxes would have silently returned
  unfiltered results while the box still read "all". `buildParams` now takes an optional
  `textKeys`, and `'all'` is dropped only for keys outside it; `useServerGrid` passes its
  `debounceKeys` through as `textKeys`, so the free-text keys are identified by the single list
  that already means "free-text inputs" rather than a second one that could drift from it. An
  empty string is still treated as unset everywhere.
- **A stale slice `total` could clamp a legitimate deep link — fixed in `47ac9d7`.** The clamp
  effect trusted whatever `total` was in the store, which need not correspond to the request in
  flight. A cold load was safe (`total === 0` short-circuits), but arriving at `?page=8` with a
  narrower total already in the slice rewrote the URL back to page 0. `useServerGrid` gained a
  `totalPending` option — while true, the clamp effect does not run — and `ReleaseList` passes the
  release slice's `listLoading` (see below) as that flag.
- **`useServerGrid` had no `refetch()` — added in `ef81e9e`, not yet wired up anywhere.** The
  fetch effect is keyed purely on the resolved params, so nothing could re-run the current query.
  The hook now returns a `refetch()`, implemented with a nonce in the fetch effect's dependency
  array, so an identical query can be re-issued after a create or delete. What is **not** yet
  done: no slice has actually dropped its optimistic list surgery — `createRelease.fulfilled`
  still `unshift`s onto `state.list` and `deleteRelease.fulfilled` still filters it back out,
  which server-side paging makes structurally wrong, since the new or removed row need not belong
  on the current page at all. The capability exists; the call sites that need it are added in the
  page PRs, one per rollout page with an inline create or delete.
- **Three sibling pickers were silently truncated at the server default of 50 — fixed.**
  `IncidentForm`, `DoraDashboard` and `ScopeWindowsTable` each called `releaseService.list()` and
  discarded the `total` the pilot made available. They were the same shape as the two dialogs
  fixed earlier, and now raise the limit to `200` the same way — but not fixed the *same way*:
  `MoveScopeItemDialog` and `RequestAdmissionDialog` also capture `total` and raise a snackbar
  when `rows.length < total`, while these three only raise the limit and still discard the total,
  so a truncated picker here fails silently. That is not a full fix either way: 200 is the
  endpoint's hard cap (`pagination(default_limit=50, max_limit=200)`), not a page size, so a
  tenant with more than 200 releases still gets a truncated picker with nothing saying so. The
  real fix is an autocomplete that queries the server per keystroke instead of pulling a fixed
  batch up front.
- **`IncidentForm`'s deployment picker truncates at 100 — not fixed, not previously recorded.**
  The same form also calls `deploymentService.list()` for its deployment picker, with no `limit`
  override, so it takes `GET /deployments`'s default of 100
  (`backend/app/api/v1/deployments.py`, `pagination(default_limit=100, max_limit=500)`) and
  silently drops the rest — one line below the release picker this branch fixed, in the same
  file, discovered but not fixed here. Releases (50/200) and deployments (100/500) are the only
  two endpoints with a low default; `systemService.listSystems()` and
  `environmentService.listEnvironments()` use the shared `DEFAULT_LIMIT = 500`
  (`backend/app/core/pagination.py`) and are far less exposed to this class of bug.
- **`ScopeWindowsTable` is a tenth grid with the live bug, and the hardest one — still open.** It
  now fetches up to 200 releases (raised from 50 alongside the other three pickers, above) and
  then filters `window_status` and sorts by `days_to_cutoff` in the browser. Both are computed
  after the query, so unlike the eight pages above it **cannot** be converted by this pattern at
  all without restructuring those into SQL first; that restructure is out of scope here. Its grid
  can still drop rows past 200 releases, same as the pickers.
- **One `loading` boolean per slice was the structural weak point — fixed for the release slice
  in `5eed49a`.** Each slice had a single flag shared by roughly twenty thunks. Abort-based
  cancellation introduces a thunk that can end *without* a successor raising the flag again, which
  is how the pilot left `loading` stuck true after an unmount and hung `/releases/calendar` and
  `/releases/timeline` — both of which had no loading transitions of their own. The release slice
  now has its own `listLoading`, written only by the three `fetchReleases` cases; every other
  thunk on that slice (`fetchRelease`, the calendar/timeline pair, create/update/transition/delete)
  still writes the shared `loading`. This is fixed for the release slice only — it establishes the
  shape the other eight slices copy as each is converted in the rollout, not a repo-wide fix.

## The rollout: PR A (deployments, builds)

Two of the eight pages are converted. **Six remain**: bookings, change-requests, incidents,
environments, systems, infrastructure-components. `DeploymentList` and `BuildList` went first
because they are the smallest and already passed some filters server-side, so the pattern could be
proven to repeat cheaply before the harder six copy it.

### The trap that *was* in six more services — corrected

This section originally claimed every remaining service had a `toParams` whitelist like
`deploymentService`'s and `buildService`'s, silently dropping any param it didn't name. **That
claim does not hold**: `grep -rn "toParams" frontend/src/services` now returns only
`buildService.ts` and `deploymentService.ts` — the two services this PR converts. No other service
in the codebase ever had this shape. The six remaining services are three different shapes, and
none of them silently drops a key:

- **`incidentService.list(params: Record<string, unknown> = {})`** — fully permissive pass-through.
  Whatever the grid sends reaches the server as-is; there is no whitelist to update.
- **`changeRequestService.list(filters: ChangeRequestListFilters = {})`** — pass-through of a typed
  filter interface. A new filter needs a new field on that interface, but nothing already flowing
  through is at risk of being silently dropped.
- **`bookingService.listBookings(params?: {...})`, `environmentService.listEnvironments(params?: {...})`,
  `infrastructureComponentService.listComponents(params?: {...})`** — inline literal param object
  types. An extra key still reaches axios fine at runtime (`api.get(url, { params })` doesn't
  inspect the object's shape), but the *type* doesn't declare it, so a call site passing an
  undeclared param fails `tsc`, not silently — the compiler is the guard here, not a test.
- **`systemService.listSystems()`** — takes **no** params argument at all. Converting
  `SystemCatalog` means adding a params argument and a `Paged<SystemResponse>` return to this
  signature from scratch, not widening an existing one.

**The transferable lesson is the opposite of what this section used to say.** The silent-drop
failure mode was specific to a hand-rolled whitelist function, and it left the codebase with the
two services this PR converts. What the six remaining conversions actually risk is a *typed*
hazard the compiler catches at the call site — except `systemService`, which has no existing
signature to widen and needs one written.

Two of the six filter mappings are not simple pass-throughs and are worth knowing before they're
hit:

- **`bookingService`'s status filter is `booking_status` on the wire.** `BookingList`'s `status`
  state must map to that param name; it does not travel through unchanged.
- **`ChangeRequestList` filters a *collection* client-side**
  (`cr.environment_ids.includes(envFilter)`) **where the server takes a scalar `environment_id`.**
  The multi-membership-against-one-selection UX this filter currently offers has no direct
  server-side equivalent — converting it needs its own decision, not a mechanical param rename.

### Two decisions worth knowing before converting the rest

- **These two pages kept raw `DataGrid`; they were not migrated to `DataTable`.** `DataTable`'s
  server-mode additions guard two different things, and the toolbar argument for skipping it holds
  for only one of them. **Export**: `GridToolbarExport`'s CSV/print buttons act on whatever page is
  currently loaded while the footer advertises the true server total, but that guard only matters
  when a toolbar is rendered at all — neither page does, so it buys nothing here, and migrating
  would *add* a toolbar as a side effect of a pagination change. **Column filtering is not the
  same kind of guard and this reasoning does not extend to it**: MUI gates the column-menu "Filter"
  item on `disableColumnFilter` (and a column's own `filterable`) alone — not on whether a toolbar
  exists — so every header's own ⋮ menu offers it regardless of `showToolbar`. Skipping `DataTable`
  does not skip this hazard; it means the page must set `disableColumnFilter` on its `DataGrid`
  itself, or every column filters the loaded 25-row page while the footer keeps showing the true
  server `rowCount` — the exact lie this whole programme exists to stop telling. **Both pages set
  it explicitly** (see "A regression caught in review" below — it was missing on the first pass).
  Treat `disableColumnFilter` as a required part of the raw-`DataGrid` route, the same way
  `DataTable` treats it as a required default for server mode: a page that opts out of `DataTable`
  inherits none of its guards for free and must set this one by hand, every time.
- **`BuildList`'s Branch filter is an exact match, not a search** (`Build.git_branch == branch`).
  Typing `ma` for `main` returns nothing, before and after. It is now debounced — it used to fire a
  request per keystroke — but its semantics are unchanged, because turning it into a contains-search
  is a backend change.

### A regression caught in review

Both pages' `DataGrid` shipped without `disableColumnFilter` in this branch's first pass —
`filterMode` defaults to `'client'`, and every column header's ⋮ menu offered "Filter" regardless,
which would have filtered only the 25 loaded rows while the footer kept showing the true server
`rowCount`. The class of bug this whole programme exists to delete, reintroduced on the two pages
meant to demonstrate the fix. Both pages now set `disableColumnFilter` (see the corrected bullet
above), and each has a test that opens a column's header menu and asserts no "Filter" item is
present — a test asserting the prop is merely set would not catch a future change that keeps the
prop but breaks what it does (e.g. a MUI upgrade regating the item on something else).

### A shared bug these pages exposed, fixed in `77ffd61`

`ReleaseList` has no text input, so the pilot never exercised one. These two do, and the pattern
was wrong: the boxes were controlled components bound to the **debounced URL state**, so for 300ms
after a keystroke `grid.filters[key]` still held the old value and React reset the input to it.
Typing `comp` left `p`.

`useServerGrid` now keeps a drafts map that `setFilter` writes synchronously and overlays on the
URL-derived `filters`, so the box shows keystrokes immediately while the URL still drives the
request. External navigation — Back/Forward or a pasted link — wipes drafts *and cancels the
pending debounce timer*; without that cancel an abandoned timer fired later and silently rewrote
the URL back to the stale text.

**No unit test caught the original bug**: they asserted the params *sent*, not the typing
experience. Opening the page did. That is the second defect in this programme found only by a
human looking at it, after the case-sensitive sorting in PR #39 — both on pages whose suites were
entirely green.

### Also found here, fixed separately in PR #42

`GET /deployments` returned **500 for the entire list** whenever any row's `event_id` was not
UUID-shaped. `DeploymentRead` declared `event_id: UUID` while the column is `String(36)` and
`deployment_service` stores `str(payload.event_id)`. The response model is applied per row while
serialising the page, so one unparseable id took out the whole endpoint rather than producing one
odd-looking cell — which is what made a page of five dev rows permanently empty. The webhook input
schema still requires a UUID, so the supported ingest path is unchanged.

Unrelated to the conversion, but it had been invisible precisely because the old client-side page
also rendered an empty grid on a rejected fetch.

### Not fixed here: the two deployment tabs still share `state.deployment` with this page

`ReleaseDeploymentsTab` and `EnvironmentDeploymentsTab` each dispatch `fetchDeployments({
release_id })` / `({ environment_id })` on mount and read the same slice `DeploymentList` now
pages, sorts and filters — `items`, and, new in this PR, `total`. Each tab defensively re-filters
`items` by its own id client-side, so the rows it renders stay correct regardless of what else last
wrote the slice. What neither tab defends against is `total`, which `DeploymentList`'s
`useServerGrid` reads for the grid's `rowCount` **and** for its page-clamping effect.

Concrete sequence: open an environment's Deployments tab — `total` becomes the count of *that
environment's* deployments (say 3) — then SPA-navigate to `/deployments?page=5`. `DeploymentList`
mounts and dispatches its own `fetchDeployments`, but on its first render `useServerGrid`'s clamp
effect still sees the stale `total` (3) left over from the tab, and `totalPending` still `false`
(also stale — nothing has told the effect a new answer is coming yet, because the pending action
from this mount's own dispatch hasn't been reflected back into props by the time this render's
effects run). The effect duly clamps `?page=5` back to `?page=0` before the real response, and the
real `total`, ever arrives — silently discarding the deep link.

This is deliberately **not fixed here**: the page conversion's own plan flagged the tabs as a
follow-on rather than a blocker (each still renders correct rows, just via a slice whose *meaning*
this PR changed under them — see "the hazard the rollout must not relearn" above), and this entry
is that follow-on, written down. The honest fix is for each tab to hold its own fetch in local
state instead of reading the shared slice at all — the same fix `MoveScopeItemDialog` and
`RequestAdmissionDialog` received against the release slice (above) — and it belongs in its own
change, not folded into a page conversion.

**The precondition this implies for PR C**: `state.environment.environments` has 8 non-page
consumers and `state.infrastructureComponent.components` has 4 — larger than deployment's 2, and
on slices whose owning pages (`EnvironmentList`, `InfrastructureComponentList`) also do inline
create/update/delete, unlike this PR's read-only pages. **Convert a slice's other consumers off
the shared list before converting the page that owns it, not after** — converting the page first
and cleaning up consumers afterward is exactly how this PR ended up with two tabs whose slice
changed meaning under them without either tab being touched.

## The rollout: PR B (bookings, change-requests, incidents)

Three more pages converted; **three remain** — environments, systems, infrastructure-components.
These three were grouped because they filter by select only, have no text input, and do no inline
create/update/delete from the page itself.

### PR A's precondition was applied here, and it was needed

`BookingCalendar` read `state.booking.bookings` — the array `BookingList` was about to turn into a
25-row sorted page — and dispatched `fetchBookings()` itself. A calendar renders a month; a page
of 25 is visibly wrong. It was moved to its own local fetch **before** the list was converted,
rather than after. That is the ordering PR A recommended after learning it the hard way, and it
cost one small task instead of a regression.

### The consumer sweep has to look for writers, not just readers

The standing rule — grep every consumer of a slice before converting the page that owns it — finds
components that **read** the slice. It does not find components that **write** it.

`BookingForm` dispatched a bare `fetchBookings()` (no paging, sort or filter params) after creating
a booking. Once the slice holds a server page that overwrites it with an endpoint-default page 1,
and `useServerGrid`'s fetch effect is keyed on the resolved URL params, so it never re-issues the
correct query and never self-corrects. `BookingForm` is an in-place dialog child of `BookingList`,
so the list is mounted and reading the slice when it lands.

**Grep `fetchX(` as well as `state.X` / `s.X`.** Note both selector spellings too — these are
written `(s: RootState) => s.booking` as often as `(state: RootState) => state.booking`, and a grep
for one form silently finds nothing.

The fix is a callback, not a dispatch: `BookingForm` gained `onCreated`, `BookingList` passes
`grid.refetch()`, `BookingCalendar` passes its own local reload.

### Optimistic list surgery is now removed on both converted slices

`createChangeRequest.fulfilled` did `state.list.unshift(...)`; `update`/`transition`/`delete` on
both the change-request and incident slices did index splices and `.filter(...)`. All are
structurally wrong once the slice holds a server page — they edit a 25-row window regardless of the
active filter, sort or page, and never adjust `total`.

All were removed. Where the dispatching component turned out to live on a **sibling route** that
never co-mounts with the list (verified against `App.tsx`, not assumed), the removal is a no-op
today and was done anyway so the shape stops being available to copy as working precedent.

### A filter that could not reach its own rows

`IncidentList` built its status dropdown from the lifecycle template, with a **fallback deriving
the options from the currently loaded rows**. Client-side that was harmless. Server-side it would
offer only statuses present on the current 25-row page — so a user could not filter to a status
that exists only on page 3. The fallback is gone; the options come from the template alone.

**Worth checking on every remaining conversion**: any control whose options are derived from the
rows on screen becomes unable to reach the rows it is meant to fetch.

### Where `ComputedColumnHeader` goes, settled across the programme

Scalar name-lookup columns (`system_name`, `environment_name`, `release_name`, `project_name`,
`subsystem_name`) get `sortable: false` **alone**. Counts, rollups and derived values
(`latest_step`, `conflicts`, `environments`, `hosts`, `has_outage`, `pir_status`) get
`sortable: false` **and** the header, because a header that simply stops working reads as a bug
whereas those need an explanation.

### Two service shapes that are not the PR A shape

Neither of these had the `toParams` whitelist PR A closed, which is why that section above was
corrected. `changeRequestService.list` is a pure passthrough of a typed interface — widening
`ChangeRequestListFilters` is the whole change. `incidentService.list` takes
`Record<string, unknown>` and needed **no type change at all**.

That permissiveness has a cost worth stating: the service tests asserting "the params I passed
reached axios" **cannot fail at runtime** on either service, because there is no mapping layer for
the assertion to catch going wrong. On change-requests, TypeScript's excess-property check still
guards a dropped key; on incidents, `Record<string, unknown>` means **not even `tsc` catches it**.
Both tests carry a comment saying so rather than implying protection they do not provide.

## Bounded so far

Twenty-eight endpoints now go through the primitive — the original twenty-two, five that a
follow-on sub-project restructured out of "blocked" (see below), and `GET /builds`, moved here
by sub-project C1 from the "own ad hoc limit" group further down:

| Endpoint | Service | Cap |
|---|---|---|
| `GET /environments/` | `environment_service.list_environments` | 1000 |
| `GET /systems/` | `system_service.list_systems` | 1000 |
| `GET /incidents` | `incident_service.list_incidents` | 1000 |
| `GET /bookings/` | `booking_service.list_bookings` | 1000 |
| `GET /change-requests` | `change_request_service.list_change_requests` | 1000 |
| `GET /infrastructure-components/` | `infrastructure_component_service.list_infrastructure_components` | 1000 |
| `GET /environments/health` | `environment_health_service.health_overview` | 1000 |
| `GET /admin/tenants` | `tenant_service.list_tenants` (master admin) | 1000 |
| `GET /tenant/users` | `user_admin_service.list_users` | 1000 |
| `GET /admin/tenants/{tenant_id}/users` | `user_admin_service.list_users` (master admin) | 1000 |
| `GET /release-changes` | `release_scope_service.list_changes` — flat scope/backlog list, not the per-release view | 1000 |
| `GET /releases` | `release_service.list_releases` | **200** (own 50/200 contract) |
| `GET /deployments` | built inline in the endpoint (`app/api/v1/deployments.py`), row variant | **500** (own 100/500 contract) |
| `GET /builds` | built inline in the endpoint (`app/api/v1/builds.py`), row variant | **500** (own 100/500 contract, preserved from before it had `X-Total-Count`) |
| `GET /booking-requests` | `booking_request_service.list_booking_requests` — extracted to a service; N+1 removed in the same pass | 1000 |
| `GET /releases/{id}/events` | release sub-resource | 1000 |
| `GET /releases/{id}/changes` | release sub-resource | 1000 |
| `GET /releases/{id}/dependencies` | release sub-resource | 1000 |
| `GET /releases/{id}/systems` | row variant, extracted to its own service | 1000 |
| `GET /releases/{id}/history` | extracted to its own service | 1000 |
| `GET /bookings/{id}/conflicts` | `conflict_service.list_conflicts`, row variant | 1000 |
| `GET /releases/{enterprise_id}/rollup/scope` | `enterprise_rollup_service.scope_rollup`, row variant | 1000 |
| `GET /releases/{enterprise_id}/memberships` | `enterprise_membership_service.list_memberships` | 1000 |
| `GET /releases/{id}/raid` | `raid_service.list_items` — `rag`/`overdue` restructured into SQL (below) | 1000 |
| `GET /systems/{id}/dependencies` | `dependency_service.list_system_dependencies`, row variant | 1000 |
| `GET /subsystems/{id}/dependencies` | `dependency_service.list_component_dependencies`, row variant | 1000 |
| `GET /environments/{id}/versions` | `version_service.list_versions` — both `current_only` values, row variant | 1000 |
| `GET /releases/{id}/membership` **†** | `enterprise_membership_service.list_history_for_project` — bounds the `history` list only | 1000 |

**†** `membership` is a special case: the endpoint returns `{"current": ..., "history": [...]}`,
not a bare array, so it was never part of the `list[...]` count above or below. `current` is at
most one row and stays unbounded (there's nothing to page). Only `history` goes through
`fetch_page`, and the `X-Total-Count` header on this response describes **the `history` list's
total, not a combined count of `current` + `history`**. A header whose subject is ambiguous is
worse than no header, so treat any consumer of this endpoint as needing to know that explicitly
rather than inferring it from the shape of other endpoints in this table.

Pre-existing and deliberately left alone: `list_history_for_project` filters `history` only by
`project_release_id`/`tenant_id`, with no `state` exclusion, so an accepted membership shows up in
both `current` (which specifically queries `state == ACCEPTED`) and in `history`. That's a
semantic question about what "history" should mean, not a pagination bug, and changing it is out
of scope for a query-restructure pass — noted here so it isn't mistaken for a side effect of the
bounding work.

## Not yet bounded

This section originally covered the endpoints examined during the first sweep, then gained four
more — `membership` (the merged current/history view), `dependency-alerts`, `bookings`, and
`change-requests`, all release sub-resources — added after a 2026-07-30 doc review found they'd
been left out of every group despite being unbounded. That review was itself incomplete: a third
pass, also on 2026-07-30, enumerated every `GET` endpoint under `backend/app/api/v1/` declaring
`response_model=list[...]` and checked each one against this file rather than trusting the
existing groups to already be exhaustive. The reproducible count:

    grep -rn -B3 'response_model=list\[' backend/app/api/v1 | grep -v __pycache__ | grep -E '\.get\(' | wc -l

That returns **51**, unchanged by the restructure below or by sub-project C1 — no endpoint was
added or removed, only made bound-able. Of those, **27** are now bounded (the table above) and
**24** are not — every one of the 24 is named below, sorted into whichever group its code
actually justifies. `GET /builds` moved from "own ad hoc limit" (below) into the bounded table in
this latest pass, which is the one count that changed since the number was last 26/25. If a
future change adds or removes a list endpoint, re-run the count above and re-check this file
against it; this doc has now drifted out of sync with the code three times.

Note the second count does not match the first: counting call sites of `set_total_count(response`
under `backend/app/api/v1/` returns **28**, one more than the 27 bounded list endpoints, because
`membership` sets the header without being a `list[...]` endpoint. Expect that off-by-one.

`membership` still never appears in that 51: it returns a dict, not a bare array, so the count
never saw it before the fix and doesn't now. It is documented in the bounded table above (flagged
as a special case) precisely because a query that isn't in the reproducible count is easy to lose
track of.

The endpoints below fall into five groups, and the distinction matters: the first is work someone
should still do, the second is a decision nobody should revisit, the third is not a problem at
all, the fourth already has a cap of its own that just isn't the shared one, and the fifth is work
that should still happen but fell out of this sweep's scope.

**Blocked on a query restructure — all but one cleared.** Five of the six endpoints in this group
have been restructured so their filtering happens in SQL before the page is taken, and each moved
into the bounded table above. The sixth, `dependency-alerts`, turned out not to be expressible and
stays here. The cleared cases are kept below rather than deleted: a future reader should be able
to see that this category existed, what was in it, and how each case was resolved, instead of
finding five endpoints in the bounded table with no record of why they were harder than the rest.

> **Still blocked: `GET /releases/{release_id}/dependency-alerts`.** Its N+1 was fixed (see
> below) but it is **not** bounded, deliberately. After computing `diff_days` the service applies
> `if diff_days == 0: continue`, which drops rows *after* the query. That filter is asymmetric —
> `timedelta.days` floors toward negative infinity, so a same-day forward shift of a few hours
> gives `0` and is suppressed while the same-magnitude backward shift gives `-1` and is reported —
> and it has no clean equivalent that renders on both SQLite and PostgreSQL. Adding a `page` here
> would window the pre-filter set and return quietly wrong results, which is exactly what this
> whole effort exists to prevent. Bounding it means first deciding whether that sub-day
> suppression is wanted behaviour at all; until then, unbounded and correct beats bounded and
> wrong.

One line per restructure technique for the five that were cleared:

- `GET /releases/{release_id}/raid` — `rag` and `overdue` were filtered in Python. `overdue` became
  a straightforward SQL predicate on `review_date`/`status`. `rag` was the harder case: `rag()`
  resolves a severity score to a band by *first match* against tenant-configured bands, and
  probability/impact/bands carry no validated upper bound, so there's no safe severity domain to
  enumerate in SQL. The fix evaluates each band's range directly as a SQL predicate and excludes
  any severity already claimed by an earlier band with `NOT`, reproducing first-match-wins without
  enumerating a domain.
- `GET /systems/{system_id}/dependencies` and `GET /subsystems/{subsystem_id}/dependencies` — both
  used to run two queries (outgoing and incoming) and concatenate the results in Python. Each is
  now a single query with an `OR` across the two directions; self-dependencies are rejected at
  creation, so the `OR` cannot double-match a row. A `CASE` in the `ORDER BY` reproduces the
  previous outgoing-then-incoming grouping.
- `GET /environments/{env_id}/versions` — `current_only=True` fetched every version row and kept
  only the first per `subsystem_id` in Python. It's now a `ROW_NUMBER() OVER (PARTITION BY
  subsystem_id ORDER BY installed_at DESC, id DESC)` window, filtered to `rn = 1`, so the "keep the
  latest per subsystem" rule is expressed in the query the `LIMIT` applies to instead of after it.
- `GET /releases/{release_id}/dependency-alerts` — **partially cleared, still unbounded.** It
  fetched every dependency for the release, then issued a second query per row for its target
  release (an N+1) and skipped any whose date hadn't shifted. It's now one query: an inner join to
  the target release plus
  `Release.target_date.is_distinct_from(ReleaseDependency.last_dependency_target_date)`, which
  reproduces "current != prior" including the both-NULL case the old code also skipped as
  unchanged. So the N+1 is gone and one of its two filters moved into SQL — but the second,
  `diff_days == 0`, did not, for the reason in the call-out above. The endpoint keeps a
  post-query Python filter and therefore cannot take a `page`.
- `GET /releases/{project_release_id}/membership` — computed `current` (one query) and `history`
  (a second, independent query) and concatenated them in Python. `current` is at most one row and
  isn't paginated; `history`, which is genuinely growth-bearing, now goes through `fetch_page` like
  any other bounded list. The response still isn't a bare array, so — unlike the other five — it
  needed a documentation call-out rather than a drop-in, which is the special case flagged above.

**Permanently unbounded — aggregations.** These are computed aggregate views, not row lists,
and three of them do not return arrays at all. A partial rollup is a wrong rollup, so paginating
them is not meaningful: `rollup/systems`, `rollup/members`, `rollup/timeline`, `rollup/raid`,
`report`.

`rollup/scope` is the exception and *is* bounded (see the table above): it is a genuine row list
with every filter in SQL.

**Bounded in practice by tenant configuration or by the entity's own structure**, where a cap
would add a knob for no benefit. Two different reasons land an endpoint in this group: some return
a tenant-wide catalogue that is itself configuration; others return the history or sub-parts of a
*single* entity, so the row count is capped by that one entity's own lifecycle rather than by
tenant-wide data growth — a booking has a handful of status transitions and a handful of allowed
next-transitions, a system is decomposed into a handful of subsystems, a scope item moves between
releases or has its external status changed only occasionally.

Tenant-wide catalogues: `component_types`, `release_event_types`, `release_templates`,
`tenant_admin_fields` (`/fields`), `booking_lifecycle` (`/lifecycle-templates` and
`/booking-types`), `api_keys`, and the per-release `phases` and `gates` (both capped by the release
template) — unchanged from the previous sweep. Added by this pass:

- `GET /tenant/scope-change-rules` and `GET /tenant/scope-change-rules/kinds`
  (`scope_change_rule_service.list_rules`) — one row per `change_kind` a tenant has configured;
  seeded with four (`story`, `defect`, `task`, `spike`) at tenant creation and grown only when an
  admin adds another from the settings page.

Single-entity structure or history, added by this pass:

- `GET /systems/{system_id}/subsystems` (`system_service.list_subsystems`) and
  `GET /environments/{env_id}/subsystems`
  (`environment_system_service.get_environment_subsystems`) — inventory structure: how many
  subsystems a system is decomposed into, or how many of those are attached to one environment.
  The environment variant runs two more batch lookups afterward (system names, latest versions per
  subsystem) but neither drops nor reorders the primary rows, so a `LIMIT` on the first query would
  be safe whenever someone gets to it — it just isn't worth it at inventory scale.
- `GET /bookings/{booking_id}/history` (`booking_service.get_status_history`) — the state
  transitions of one booking; bounded by that booking's own lifecycle template, not by tenant data
  volume.
- `GET /bookings/{booking_id}/allowed-transitions`
  (`booking_service.get_booking_allowed_transitions`) — not really a database list: it reads the
  lifecycle template's state-machine definition and returns the outbound edges from the booking's
  current state for the caller's role. Bounded by how many transitions a state can have, typically
  single digits.
- `GET /release-changes/{change_id}/release-history` and
  `GET /release-changes/{change_id}/status-history`
  (`release_scope_service.list_release_history` / `list_status_history`) — chronological audit
  trails for one scope item: every release it has been moved to, and every external-status change
  ingested for it. Both writers are no-ops when nothing actually changed (`list_status_history`'s
  writer returns early if `from_status == to_status`), so row count tracks genuine transitions of
  that one item, not tenant volume.

**Already capped by their own ad hoc limit — not the shared primitive, and no `X-Total-Count`.**
This was missed by earlier passes because "unbounded" was read as "returns everything with no
cap"; it already had a cap, just not the shared one, so a scan for a bare `list(...)` return
missed it. `GET /builds` used to be the other member of this group — it took its own
`limit: int = Query(100, le=500)` with every filter running in SQL before the `LIMIT`, so it
windowed correctly but never learned about `X-Total-Count` — until sub-project C1 wired it onto
`pagination(default_limit=100, max_limit=500)` and moved it into the bounded table above. It's
kept as the model for what "wiring, not a query restructure" looks like for the one endpoint
still in this group:

- `GET /environments/{env_id}/health/history` (`environment_health.py`) — takes
  `limit: int = Query(50, ge=1, le=500)`. Correctly windowed, no total exposed. One
  `fetch_page`/`set_total_count` swap away from the shared primitive, exactly as `GET /builds`
  was before this pass.

**Growth-bearing, not yet bounded.** Unlike the groups above, nothing caps these structurally, and
unlike the "blocked" group, there is no Python filtering standing in the way — every one does its
filtering in SQL and only shapes rows afterwards, so each is a clean drop-in for the shared
primitive whenever someone picks it up.

- `GET /releases/{release_id}/bookings` (`list_release_bookings` in `releases.py`) — every
  `Booking` row with `release_id` matching, ordered by `start_date`. A release under test for
  months across many phases can accumulate as many bookings as the tenant-wide `/bookings/`
  endpoint (already bounded in this sweep) — nothing about being scoped to one release caps the
  count.
- `GET /releases/{release_id}/change-requests` (`list_linked_crs` in `releases.py`) — every
  `ChangeRequest` row with `release_id` matching, ordered by `id`. Same shape as the tenant-wide
  `/change-requests` endpoint (already bounded), just release-scoped; nothing here caps the count
  either.
- `GET /environments/{environment_id}/deployments` (`list_environment_deployments` in
  `deployments.py`) — every `Deployment` row for one environment, newest first, no limit anywhere.
  Its sibling `GET /deployments` **is** bounded (own 100/500 contract, above) and already accepts
  the same `environment_id` filter, so `GET /deployments?environment_id=N` returns the identical,
  paginated data today. This route is a separate query path that just never got the cap its
  sibling has — deployments accumulate for the life of an environment, exactly the kind of history
  that motivated bounding the tenant-wide route in the first place.
- `GET /tenant/users/lite` (`list_users_lite` in `tenant_admin.py`) — every active user in the
  tenant, `{id, username}` only, no limit. It mirrors `GET /tenant/users`, which needed real
  pagination in this sweep because headcount is data, not configuration; the `/lite` variant reads
  the same table with the same growth profile and currently has no cap at all.
- `GET /bookings/{booking_id}/received-feedback` (`list_received_feedback` in `conflicts.py`) —
  every ack left by another booking's owner about a conflict with this one, one query, no
  post-fetch filtering. Its sibling on the same `booking_id`, `GET /bookings/{id}/conflicts`, was
  bounded through the shared primitive in this sweep; this endpoint has the same growth driver
  (however many other bookings overlapped this one and left feedback) and was simply missed.

## Ordering must be total

`LIMIT`/`OFFSET` is only correct over a total order. If the `ORDER BY` leaves ties, the database
may break them differently between two queries — a row comes back on page 1 and page 2, another
never appears, and nothing errors. Under SQLite this usually looks fine; it shows up on
PostgreSQL under concurrent writes and larger result sets. See
[`backend/tests/test_pagination_ordering.py`](../backend/tests/test_pagination_ordering.py), which
proves this by walking pages over 30 environments that all share a sort key — a genuine
demonstration of the failure mode, since SQLite tends to pass by luck and the PostgreSQL leg is
the one that actually exercises it.

So every bounded endpoint ends its ordering with a unique tiebreaker, in practice the primary
key:

    query.order_by(Booking.start_date.asc(), Booking.id)

Endpoints that needed one added because their existing sort column was not unique: `environments`
(name), `systems` (name), `incidents` (detected_at), `bookings` (start_date), `change-requests`
(scheduled_start), `environment_health` (Environment.name), `infrastructure-components` (name),
`releases` (created_at), `deployments` (deployed_at), `booking-requests` (created_at), `release
events` (occurred_at), `release history` (changed_at), `conflicts` (start_date), `enterprise
memberships` (requested_at). `builds` (commit_timestamp) joined this list in sub-project C1 — see
the next paragraph, since unlike the rest it's a genuine behaviour change rather than a gap this
sweep merely found and closed at the same time as everything else.

`builds` is worth calling out on its own: before sub-project C1 it had no tiebreaker at all —
`order_by(commit_timestamp.desc())` and nothing else — which is exactly the bug this section
describes, just on an endpoint that predated the sweep that fixed it everywhere else. It now ends
in `Build.id`. Rows with distinct `commit_timestamp`s are unaffected; only true ties (same
millisecond) gain a defined order they didn't have before.

Two endpoints, `tenant/users` and `rollup/scope`, are a step worse: they had **no `ORDER BY` at
all** before this sweep. Their pages were undefined even before a window was applied — not
merely non-deterministic under ties, but arbitrary on every request.

Already total, no tiebreaker needed: `GET /release-changes` (the flat scope/backlog list),
`release changes`, `release dependencies`, `release systems` (all ordered by `id`).

`admin/tenants` orders by `Tenant.name, Tenant.id` — `name` is unique on its own, but
`tenant_service.list_tenants` appends `Tenant.id` as a tiebreaker anyway, so it isn't
relying on that uniqueness in practice.

## Known gap: calendar and timeline silently truncate

`GET /releases/calendar` and `GET /releases/timeline` call `release_service.list_releases` with
a hardcoded `limit=500` and discard the total. A tenant with more than 500 releases in the
requested date range gets a calendar or Gantt view that silently drops rows past the 500th, with
no header or error to say so. This was found during the sweep and is out of its scope — it needs
the same `page`/`X-Total-Count` treatment as everything else in the table above, or at minimum a
truncation signal to the client.
