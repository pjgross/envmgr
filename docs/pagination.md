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

Twenty-two endpoints now go through the primitive:

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

## Not yet bounded

This section covers the endpoints examined during the original sweep, plus four more —
`membership` (the merged current/history view), `dependency-alerts`, `bookings`, and
`change-requests`, all release sub-resources — added after a doc review on 2026-07-30 found
they'd been left out of every group despite being unbounded. It is not a claim that every list
endpoint in the codebase has been surveyed; it is what has actually been checked, group by group.

The endpoints below fall into four groups, and the distinction matters: the first is work someone
should still do, the second is a decision nobody should revisit, the third is not a problem at
all, and the fourth is work that should still happen but fell out of this sweep's scope.

**Blocked on a query restructure.** Each of these filters or merges *after* the query, so a SQL
`LIMIT` would window the wrong set. Adding `limit` before the restructure would be worse than
leaving them unbounded — the results would be quietly wrong rather than merely large.

- `GET /releases/{release_id}/raid` — `raid_service.list_items` applies its `rag` and `overdue`
  filters in Python, computed from probability/impact against tenant config and from review
  dates. `?limit=50` could return 3 rows while hundreds matched.
- `GET /systems/{system_id}/dependencies` and `GET /subsystems/{subsystem_id}/dependencies` —
  both execute two queries (outgoing and incoming) and concatenate the results in Python. A
  `LIMIT` cannot window a concatenation of two separately-executed queries; they need a single
  `UNION ALL` first.
- `GET /releases/{project_release_id}/membership` (`project_membership_view` in
  `enterprise_memberships.py`) — computes `current` (one query) and `history` (a second,
  independent query) and concatenates them in Python before returning `{"current": ..., "history":
  [...]}`. Same shape as the dependencies case above: a `LIMIT` on either underlying query cannot
  window a result that only exists after both have run and been merged. It also doesn't return a
  bare array, so it isn't a drop-in for the shared primitive even after a restructure.
- `GET /releases/{release_id}/dependency-alerts` (`release_dependency_service.get_dependency_alerts`)
  — fetches every dependency for the release, then loops and `continue`s past any dependency whose
  target date hasn't shifted, only appending the rest to `alerts`. The filter (has this date
  moved?) is computed per-row after the fetch, exactly like `raid`'s `rag`/`overdue` filters — a
  `LIMIT` on the initial fetch could return zero alerts while dozens of shifted dependencies exist
  further down the unfiltered set.

**Permanently unbounded — aggregations.** These are computed aggregate views, not row lists,
and three of them do not return arrays at all. A partial rollup is a wrong rollup, so paginating
them is not meaningful: `rollup/systems`, `rollup/members`, `rollup/timeline`, `rollup/raid`,
`report`.

`rollup/scope` is the exception and *is* bounded (see the table above): it is a genuine row list
with every filter in SQL.

**Bounded in practice by tenant configuration**, where a cap would add a knob for no benefit:
`component_types`, `release_event_types`, `release_templates`, `tenant_admin_fields`,
`booking_lifecycle`, `api_keys`, and the per-release `phases` and `gates` (both capped by the
release template).

**Missed by this sweep — genuinely growth-bearing.** Unlike the group above, nothing caps these
structurally, and unlike the "blocked" group, there is no Python filtering standing in the way —
both do every filter in SQL and only shape rows afterwards (dict construction), so each is a
clean drop-in for the shared primitive whenever someone picks it up.

- `GET /releases/{release_id}/bookings` (`list_release_bookings` in `releases.py`) — every
  `Booking` row with `release_id` matching, ordered by `start_date`. A release under test for
  months across many phases can accumulate as many bookings as the tenant-wide `/bookings/`
  endpoint (already bounded in this sweep) — nothing about being scoped to one release caps the
  count.
- `GET /releases/{release_id}/change-requests` (`list_linked_crs` in `releases.py`) — every
  `ChangeRequest` row with `release_id` matching, ordered by `id`. Same shape as the tenant-wide
  `/change-requests` endpoint (already bounded), just release-scoped; nothing here caps the count
  either.

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
