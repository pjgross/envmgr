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
would multiply real work, not just serialisation.

## Bounded so far

Twenty-seven endpoints now go through the primitive — the original twenty-two plus five that
a follow-on sub-project restructured out of "blocked" (see below):

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
| `GET /releases/{id}/dependency-alerts` | `release_dependency_service.get_dependency_alerts`, row variant | 1000 |
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

That returns **51**, unchanged by the restructure below — no endpoint was added or removed, only
made bound-able. Of those, **27** are now bounded (the table above) and **24** are not — every one
of the 24 is named below, sorted into whichever group its code actually justifies. If a future
change adds or removes a list endpoint, re-run the count above and re-check this file against it;
this doc has now drifted out of sync with the code three times.

`membership` still never appears in that 51: it returns a dict, not a bare array, so the count
never saw it before the fix and doesn't now. It is documented in the bounded table above (flagged
as a special case) precisely because a query that isn't in the reproducible count is easy to lose
track of.

The endpoints below fall into five groups, and the distinction matters: the first is work someone
should still do, the second is a decision nobody should revisit, the third is not a problem at
all, the fourth already has a cap of its own that just isn't the shared one, and the fifth is work
that should still happen but fell out of this sweep's scope.

**Blocked on a query restructure — now empty.** As of this pass, every endpoint that used to be
in this group has been restructured so its filtering happens in SQL before the page is taken, and
each moved into the bounded table above. The group is kept here, empty, rather than deleted:
a future reader should be able to see that this category existed, what was in it, and how each
case was cleared, instead of finding six endpoints in the bounded table with no record of why they
were harder than the rest. One line per restructure technique:

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
- `GET /releases/{release_id}/dependency-alerts` — fetched every dependency for the release, then
  issued a second query per row for its target release (an N+1) and skipped any whose date hadn't
  shifted. It's now one query: an inner join to the target release plus
  `Release.target_date.is_distinct_from(ReleaseDependency.last_dependency_target_date)`, which
  reproduces "current != prior" including the both-NULL case the old code also skipped as
  unchanged. The per-dependency N+1 query is gone along with the Python filter.
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
These were missed by earlier passes because "unbounded" was read as "returns everything with no
cap"; these two already had a cap, just not the shared one, so a scan for a bare `list(...)`
return missed them.

- `GET /builds` (`builds.py`) — takes its own `limit: int = Query(100, le=500)` and
  `offset: int = Query(0)`, ordered by `commit_timestamp DESC`. Every filter (`subsystem_id`,
  `release_id`, `branch`, date range) runs in SQL before the `LIMIT`, so it windows correctly — it
  just never learned about `X-Total-Count`, so a client has no way to tell 100 rows returned from
  100 rows total.
- `GET /environments/{env_id}/health/history` (`environment_health.py`) — takes
  `limit: int = Query(50, ge=1, le=500)`. Same story: correctly windowed, no total exposed.

Both are one `fetch_page`/`set_total_count` swap away from the shared primitive; the remaining
work is wiring, not a query restructure.

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
memberships` (requested_at).

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
