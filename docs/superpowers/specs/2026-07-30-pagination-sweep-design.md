# Backend Pagination Sweep — Design

> Date: 2026-07-30 | Status: approved, not yet implemented
> Sub-project **A** of a three-part programme. See [Programme context](#programme-context).

## Problem

[docs/pagination.md](../../pagination.md) introduced a shared pagination primitive and applied it
to three endpoints (`environments`, `systems`, `incidents`). Forty-four list endpoints still
return every matching row for the tenant. A tenant with 50k bookings gets one query that loads
50k ORM objects, serialises them all, and hands the browser a response it renders into a
DataGrid.

This sub-project bounds the endpoints that can be bounded mechanically, and identifies the ones
that cannot.

## Programme context

The full request was "bound everything, refactor RAID, wire the frontend grids". That decomposes
into three sub-projects with different risk profiles, sequenced A → B → C:

| | Sub-project | Risk | Depends on |
|---|---|---|---|
| **A** | Backend sweep (this document) | Low — mechanical, backward compatible | — |
| **B** | Restructure queries that filter after execution, then bound them: `releases/{id}/raid`, `systems/{id}/dependencies`, `subsystems/{id}/dependencies` | Medium — changes filter semantics | — |
| **C** | Frontend server-side pagination across 13 DataGrid pages | High — user-visible behaviour change on every list page | A |

C depends on A because several grids filter client-side today and must push those filters to
endpoints that accept them. B is independent of both.

## The central distinction

**Enrichment after the query is safe. Filtering or merging after the query is not.**

A service that runs a query and then decorates each row — computing a derived field, looking up a
label — can be windowed correctly, because every row that the query returned still appears in the
output. `releases/{id}/changes` is this shape: it sets `is_scope_creep` per row and drops nothing.

A service that runs a query and then *removes* rows, or concatenates two separately-executed
queries, cannot be windowed. `LIMIT` would take the first N rows of the pre-filter set and then
filter within that page, so `?limit=50` could return 3 rows while hundreds matched — results that
are quietly wrong rather than merely large.

Every endpoint in this sweep gets its service read before conversion. Anything that filters or
merges post-query moves to sub-project B.

## Deterministic ordering is a precondition

`LIMIT`/`OFFSET` paging is only correct over a **total** order. If the `ORDER BY` leaves ties, the
database is free to break them differently between two queries, so a row can appear on both page 1
and page 2 while another is never returned at all. Nothing errors; the client just sees
duplicates and silent omissions. On PostgreSQL this surfaces under concurrent writes and larger
result sets — precisely the conditions this work exists to handle — while SQLite will usually look
fine, so the default test leg would not reveal it.

Auditing the endpoints in scope, most current orderings are **not** total:

| Ordering today | Endpoints |
|---|---|
| No `ORDER BY` at all | `tenant/users` |
| Non-unique sort column | `bookings` (`start_date`), `change-requests` (`scheduled_start`), `releases/{id}/events` (`occurred_at`), `releases/{id}/history` (`changed_at`), `infrastructure-components` (`name`), `environments/health` (`Environment.name`) |
| Already total | `releases/{id}/changes`, `releases/{id}/dependencies`, `releases/{id}/systems` (all `id`), `admin/tenants` (`name`, unique) |

So every endpoint bounded by this sweep gets a unique tiebreaker appended to its existing
ordering — in practice the primary key, e.g. `.order_by(Booking.start_date.asc(), Booking.id)`.
The visible sort order is unchanged; only the tie-breaking becomes deterministic.

This is a precondition rather than an enhancement: converting an endpoint to take a `Page` without
it substitutes one silent correctness bug for another. Endpoints that keep no `Page` are left
alone.

## Changes to the primitive

Two additions to [`app/core/pagination.py`](../../../backend/app/core/pagination.py).

### `pagination()` becomes a factory

Two endpoints already have hand-rolled windows whose defaults disagree with the shared primitive:
`GET /releases` uses 50/200, `GET /deployments` uses 100/500. Both do per-row enrichment after the
query (`releases` runs extra phase-count and gate queries per page; `deployments` selects a
five-column join), so raising their defaults to 500 would multiply real work, not just
serialisation.

```python
def pagination(
    *, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT
) -> Callable[..., Page]:
    """Build a FastAPI dependency supplying the window for a list endpoint."""
```

Endpoints wanting the standard window use `Depends(pagination())`. The two with existing
contracts keep them: `Depends(pagination(default_limit=50, max_limit=200))`.

The three existing call sites change from `Depends(pagination)` to `Depends(pagination())`.

### `fetch_page_rows` for multi-column selects

`fetch_page` ends `.scalars().all()`, so it cannot serve queries that select tuples.
`deployments`, `bookings/{id}/conflicts` and `rollup/scope` all select multiple entities per row.

```python
async def fetch_page_rows(db, query, page) -> tuple[list[Row], int]:
    """Run `query` windowed by `page`, returning raw Rows and the unwindowed total."""
```

`fetch_page` becomes a thin wrapper that maps `.scalars()` over the result, so the count logic
lives in exactly one place and the three current callers are untouched.

## Scope

### Drop-in — scalar select, all filters in SQL

`Page` parameter plus `set_total_count`. No other change.

| Endpoint | Service |
|---|---|
| `GET /bookings/` | `booking_service.list_bookings` |
| `GET /change-requests` | `change_request_service.list_change_requests` |
| `GET /infrastructure-components/` | `infrastructure_component_service.list_infrastructure_components` |
| `GET /environments/health` | `environment_health_service.health_overview` |
| `GET /admin/tenants` | `tenant_service.list_tenants` |
| `GET /tenant/users` | `user_admin_service.list_users` |
| `GET /releases/{id}/events` | `release_event_service.list_events` |
| `GET /releases/{id}/changes` | `release_scope_service.list_changes` |
| `GET /releases/{id}/scope` | `release_scope_service.list_changes` (backlog mode) |
| `GET /releases/{id}/dependencies` | `release_dependency_service.list_dependencies` |

`environments/health` deserves a note: it produces exactly one row per environment and enriches
each with three sub-queries. The enrichment never drops a row, so windowing the environment query
is correct.

`releases/{id}/phases` and `releases/{id}/gates` are deliberately **excluded**. They are
structurally capped by the release template — a handful of rows each — so a limit would add a knob
with no benefit. This is the same reasoning [docs/pagination.md](../../pagination.md) already
applies to the tenant-configuration lists.

### Header-only

`GET /releases` already windows correctly and `release_service.list_releases` already returns
`(rows, total)`; the endpoint discards the total and never sets the header
([`app/api/v1/releases.py:152`](../../../backend/app/api/v1/releases.py)). It needs the shared
`Page` and a `set_total_count` call — two lines.

### Needs `fetch_page_rows`

| Endpoint | Shape |
|---|---|
| `GET /deployments` | `select(Deployment, sha, env_name, rel_name, cr_title)`; also converts its inline limit/offset to the factory |
| `GET /bookings/{id}/conflicts` | `select(Booking, BookingRequest.project_name, Environment.name)` |
| `GET /releases/{id}/rollup/scope` | `select(ReleaseChange, Release, System)` |
| `GET /releases/{id}/systems` | `select(ReleaseSystem, System.name)` — also needs the service extraction below |

### Needs service extraction

Three endpoints have their queries written inline in the endpoint function, contrary to the
"keep endpoints thin, put logic in services" convention in CLAUDE.md. Each moves to a service
following the established signature (`page: Optional[Page] = None`, returns `(rows, total)`).

**`GET /booking-requests`**
([`app/api/v1/booking_requests.py:115`](../../../backend/app/api/v1/booking_requests.py)) — the
query is followed by `await db.refresh(r, attribute_names=["bookings"])` per row. It moves to
`booking_request_service.list_booking_requests`, and the per-row refresh is replaced with
`selectinload(BookingRequest.bookings)` in the query. Bounding the page alone would not fix that
N+1 — it would cap it at 500 round-trips instead of unlimited — and the move rewrites the query
anyway.

**`GET /releases/{id}/systems`**
([`app/api/v1/releases.py:749`](../../../backend/app/api/v1/releases.py)) — there is no
`release_system_service`; the query is inline and is a **tuple select**
(`select(ReleaseSystem, System.name)`), so it needs `fetch_page_rows` as well as a new service
module.

**`GET /releases/{id}/history`**
([`app/api/v1/releases.py:573`](../../../backend/app/api/v1/releases.py)) — inline scalar select,
moves alongside the other release history helpers.

> **Corrected 2026-07-30, during implementation planning.** An earlier draft of this spec proposed
> adding a `tenant_id` predicate to the `history` query as defence in depth, on the grounds that it
> filtered on `release_id` alone. That is not possible and the premise was wrong:
> `ReleaseStatusHistory` ([`app/db/models/release.py:40`](../../../backend/app/db/models/release.py))
> has no `tenant_id` column. Its columns are `release_id`, `from_state`, `to_state`, `changed_by`,
> `changed_at`, `notes`. The table is scoped transitively through its release, so the preceding
> `_require_release` check is not the first of two defences — it is the only one available, and it
> is the correct one. This endpoint is a plain extraction.

## Explicitly out of scope

### Deferred to sub-project B

`GET /systems/{id}/dependencies` and `GET /subsystems/{id}/dependencies` execute two queries and
concatenate the results in Python:

```python
outgoing, incoming = await dependency_service.list_system_dependencies(db, system_id, tenant_id)
```

A `LIMIT` cannot window a concatenation of two separately-executed queries. Bounding these
requires restructuring the pair into a single `UNION ALL` first — the same class of work as the
RAID refactor, so it belongs with it.

`GET /releases/{id}/raid` remains blocked for the reason already documented: `raid_service.list_items`
applies its `rag` and `overdue` filters in Python after the query.

### Permanently unbounded

The enterprise rollup aggregations are computed aggregate views, not row lists:
`rollup/systems`, `rollup/members`, `rollup/timeline`, `rollup/raid`, and `report`. Three of them
do not return arrays at all. Paginating an aggregate is not meaningful — a partial rollup is a
wrong rollup. These stay unbounded, and `docs/pagination.md` gains a section saying so, so the
next person does not re-litigate it.

`rollup/scope` is the exception: it is a genuine row list with every filter in SQL, so it is in
scope above.

The tenant-configuration lists (`component_types`, `release_event_types`, `release_templates`,
`tenant_admin_fields`, `booking_lifecycle`, `api_keys`) remain unbounded per the existing
reasoning in `docs/pagination.md`.

## Testing

Both engines, per CLAUDE.md — the default SQLite leg and
`TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test`.
All fixture rows go through [`backend/tests/factories.py`](../../../backend/tests/factories.py);
no fabricated foreign keys.

**Conformance sweep.** One parametrised test over every bounded endpoint, asserting four
invariants:

1. the response is a bare JSON array (backward compatibility),
2. `X-Total-Count` is present,
3. `?limit=<max+1>` returns 422 rather than silently clamping,
4. the default page size does not exceed the endpoint's configured default.

All four hold on an empty tenant — request validation and the count query do not need rows — so
this test needs no fixtures.

**Windowing semantics.** Extends the existing primitive tests in `tests/test_pagination.py` to
cover `fetch_page_rows` and the `pagination()` factory's per-endpoint overrides.

**Paging over ties.** For each endpoint whose ordering needed a tiebreaker, seed rows sharing an
identical sort key, walk the whole result set with `?limit=N&offset=…`, and assert every row
appears exactly once across the pages. This is the test that would fail if a tiebreaker were
dropped, and it must run on the PostgreSQL leg to be meaningful — SQLite's plans are stable enough
to pass it by luck.

**Targeted tests.** Where an endpoint has real logic rather than a mechanical conversion:

- `booking_requests` — the extraction preserves the response shape and the `bookings` relation is
  still populated on every row.
- `releases/{id}/systems` — the extraction preserves `system_name` enrichment through the row
  variant.
- `releases/{id}/history` — the extraction preserves the rows and their oldest-first order.
- `deployments` — the row variant returns the same five-tuple shape the response builder expects,
  and the endpoint still honours its 100/500 contract.

### What the tests cannot prove

The conformance sweep asserts *shape*, not *correctness of the window*. An endpoint whose service
filters in Python after the query would pass all four invariants and still return wrong results.
Nothing in the suite catches that. The control is the classification above, which was established
by reading each service, and the rule that anything filtering post-query moves to B.

This matches the lesson already recorded in the project's verification notes: a green suite has
repeatedly failed to catch this codebase's real bugs, and the mitigation is reading the code, not
adding assertions.

## Risk

The sweep is backward compatible by construction. Endpoints keep returning bare arrays, the total
is header-only, and the two endpoints with existing limit contracts keep them. No frontend change
is required by A; that is sub-project C.

Two real risks, both addressed above:

1. **Misclassification** — an endpoint that filters in Python after the query gets a `Page` and is
   silently windowed wrong. Controlled by reading each service before converting it; the
   conformance test cannot catch this.
2. **Non-total ordering** — a bounded endpoint whose sort leaves ties returns duplicate and
   missing rows across pages. Controlled by the tiebreaker rule and the paging-over-ties test on
   the PostgreSQL leg.

Both failure modes are silent, produce plausible-looking output, and would survive a green SQLite
run. That is the same pattern as the bugs already recorded in the project's verification notes,
which is why the controls here are code review and a PostgreSQL-specific test rather than more
assertions on the default leg.

## Documentation

[docs/pagination.md](../../pagination.md) is updated to reflect the outcome:

- move the newly bounded endpoints into the "Bounded so far" table,
- correct the claim that `GET /releases` is unbounded — it has always had its own window,
- add the "permanently unbounded" section covering the rollup aggregations,
- record that the two `dependencies` endpoints are blocked on the same restructuring as RAID,
- record the total-ordering rule, so the next person adding a bounded endpoint appends a unique
  tiebreaker rather than rediscovering the duplicate-row symptom in production.

The corresponding CLAUDE.md pitfall entry ("Unbounded list endpoints") gains the same rule.
