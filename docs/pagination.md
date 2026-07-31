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
