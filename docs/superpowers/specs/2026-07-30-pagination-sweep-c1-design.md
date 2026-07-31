# Pagination Sub-project C1 — Server-Side Sorting and the Missing Filters

> Date: 2026-07-30 | Status: approved, not yet implemented
> Backend half of sub-project **C**. Branches off `feature/pagination-sweep-b` (PR #37), which stacks on A (PR #36).
> Frontend half — moving the grids to server mode — is **C3**, a separate spec that depends on this one.

## Problem

Every list page in this app fetches a page of rows and then filters it **in the browser**.
`ReleaseList` is the clearest case: it dispatches `fetchReleases({})` with no filters at
all, receives at most 50 releases (the endpoint's long-standing default), and then filters
those 50 by status, type, kind and system in JavaScript. All four filters have always
existed server-side. A tenant with more than 50 releases gets filter results computed from
the newest 50 only, with nothing in the UI indicating the rest were never considered.

Eleven other list pages have the same shape. This predates the pagination programme —
sub-projects A and B did not cause it; they made the caps explicit and documented.

The fix is to move filtering and sorting to the server and let the grids page against it.
That is sub-project C. **C1 is the backend half**: the query capabilities the frontend
needs before it can safely switch. C3 does the frontend.

C1 must land first. Moving a grid to server mode before its filters and sort exist would
reproduce the same truncation bug in a new form.

## The rule that governs this work

The programme's existing rule is *enrichment after the query is safe to window; filtering
is not*. C1 adds its sibling:

> **A column the client can sort by must be sortable in SQL. If it cannot be, the grid must
> not offer to sort it.**

A column header that silently sorts only the visible page is the same class of defect as a
`LIMIT` applied before a filter — plausible output, quietly wrong. So the sort whitelist
and the grids' `sortable` flags are two halves of one contract, and C3 is responsible for
making the grids match what C1 declares.

## Part 1 — the `sorting()` primitive

A sibling to `pagination()` in [`app/core/pagination.py`](../../../backend/app/core/pagination.py).

```python
@dataclass(frozen=True)
class Sort:
    column: InstrumentedAttribute
    descending: bool


def sorting(
    allowed: Mapping[str, InstrumentedAttribute], default: str
) -> Callable[..., Sort]:
    """Build a FastAPI dependency resolving `sort_by`/`sort_dir` against a whitelist.

    `allowed` maps the client-facing field name to the column it sorts by. An
    unknown `sort_by` is a 422, never a silent fallback: a client asking for a
    sort it does not get is worse off than one told it asked for something
    impossible.
    """
```

Three properties that matter:

**The whitelist is the whole security boundary.** `sort_by` is a client-supplied string and
must never reach the query as a column name. It is looked up in `allowed`; a miss is a 422.
There is no dynamic attribute access and no string interpolation into SQL anywhere in this
design.

**An unknown sort is a 422, not a silent default.** This mirrors the existing decision that
`?limit=` past the cap is a 422 rather than a clamp. Silently returning a different order
than asked for is how a client ends up displaying "sorted by name" over rows that are not.

**Sorting composes with the total-ordering rule, it does not replace it.** Sub-project A
established that every bounded query ends in a unique tiebreaker, and demonstrated
empirically that removing one breaks pagination deterministically on PostgreSQL. A sort
column is almost never unique, so the applied ordering is **the requested sort, then the
existing tiebreaker** — never the sort alone. `fetch_page`/`fetch_page_rows` are the natural
place to enforce that, but the tiebreaker must remain visible in each service rather than
becoming implicit.

## Part 2 — which columns are sortable, and which are honestly not

Each grid's columns fall into three kinds. Only the first is sortable server-side.

**Plain columns on the queried table** — sortable directly.

**Joined names** — `environment_name`, `system_name`, `subsystem_name`, `release_name`,
`booked_by_username`, `change_request_title`. Sortable, but only where the query already
joins that table, or can without changing which rows come back. Adding a join purely to sort
risks changing row multiplicity; where the join is not already present and is not a
many-to-one on a primary key, the column is **not** offered.

**Python-computed aggregates** — `phase_count`, `scope_count`, `scope_change_count`,
`blocker_count`, `overdue_criterion_count`, `conflicts`, `pir_status`, `latest_step`,
`has_outage`, `systems`, `environments`, `hosts`. These are computed after the page is
fetched, by batch queries keyed on the page's ids. They **cannot** be sorted server-side
without restructuring each into the main query, which is out of scope. They are declared
non-sortable, and C3 must set `sortable: false` on them.

That last group is the honest cost of this design, and it should be stated plainly in the
docs rather than discovered: **users lose the ability to sort by those columns**. They can
sort by them today, because today the whole (truncated) set is in the browser. What they
have today is a sort of the wrong set; what they will have is no sort at all. That is a
real reduction in capability, traded for correctness.

### Proposed whitelists

| Endpoint | Sortable | Default |
|---|---|---|
| `GET /releases` | `name`, `release_type`, `release_kind`, `status`, `target_date`, `created_at` | `created_at` desc |
| `GET /bookings/` | `start_date`, `end_date`, `status` | `start_date` asc |
| `GET /environments/` | `name`, `environment_type`, `status`, `created_at` | `name` asc |
| `GET /change-requests` | `title`, `change_type`, `status`, `scheduled_start` | `scheduled_start` desc |
| `GET /systems/` | `name` | `name` asc |
| `GET /infrastructure-components/` | `name`, `component_type`, `provider`, `region`, `source` | `name` asc |
| `GET /incidents` | `title`, `severity`, `status`, `detected_at`, `resolved_at` | `detected_at` desc |
| `GET /deployments` | `status`, `deployer_name`, `deployed_at` | `deployed_at` desc |
| `GET /builds` | `git_branch`, `build_number`, `commit_timestamp` | per current ordering |

Joined-name columns are deliberately absent from this first pass — every one of them sits
on a query whose join shape needs checking individually, and getting that wrong changes
which rows come back. They are recorded as follow-on work. Each default must match the
endpoint's **current** ordering, so behaviour is unchanged when no `sort_by` is supplied.

## Part 3 — the missing filter parameters

Five pages filter on something their endpoint does not accept. Each needs a new query
parameter, expressed in SQL.

| Endpoint | New parameter | Notes |
|---|---|---|
| `GET /environments/` | `search` | case-insensitive `name` contains, matching the client's behaviour |
| `GET /systems/` | `search` | same |
| `GET /infrastructure-components/` | extend `search` | the client searches name **or** provider **or** region; the server currently searches name only, so the existing parameter is widened to match rather than a new one added |
| `GET /deployments` | `environment_search`, `release_search` | the client filters on the joined *names*; the endpoint currently takes ids. The join is already present in `_select_with_joins`, so these are `ilike` predicates on already-joined columns — no new join, no multiplicity change |
| `GET /builds` | `subsystem_search` | client filters on the joined subsystem name; check whether the query already joins subsystem before adding the predicate |

Every one is a case-insensitive contains, matching what the browser does today, so switching
a page from client to server filtering does not change which rows match.

**`ilike` on an unindexed column is a sequential scan.** At the volumes this app is bounding
for, that is acceptable and preferable to shipping wrong results; it is noted so a future
performance pass knows where to look, not as a reason to defer.

## Testing

**Whitelist enforcement** is the security-relevant test: an unknown `sort_by` returns 422,
and no input reaches the query as a column name. Include a case with a SQL-injection-shaped
string to prove it is rejected by the whitelist rather than escaped somewhere downstream.

**Order correctness**, per bounded endpoint with a whitelist: seed rows whose sort column
deliberately disagrees with insertion order, request each sortable field ascending and
descending, and assert the returned sequence. A test that seeds already-ordered rows proves
nothing — the same defect found in sub-project B's first ordering test.

**Sort composes with the tiebreaker**: seed rows that tie on the sort column, page through
the whole set, and assert every row appears exactly once. This is the sort-aware version of
`tests/test_pagination_ordering.py`, and it is the test that catches a sort replacing the
tiebreaker rather than preceding it.

**Default ordering is unchanged**: for each endpoint, assert that omitting `sort_by` returns
the same order as before this change. This is what makes C1 safe to merge ahead of C3.

**Filter equivalence**: for each new search parameter, seed rows that the client-side
predicate would and would not match, and assert the SQL agrees — the differential-test
pattern established in sub-project B, embedding the JavaScript predicate's semantics
(case-insensitive contains) as the reference.

Cadence, measured across A and B: the full suite is ~6 min on SQLite and ~15 min on
PostgreSQL. Targeted tests per task; full dual-engine at two checkpoints. Only one agent
may use the shared `envmgr_test` database at a time — concurrent runs deadlock it.

## Risk

**The whitelist and the grids must agree, and nothing enforces that across the boundary.**
C1 declares which fields are sortable; C3 must set `sortable: false` on every column not in
the list. Nothing in either codebase checks the two match. A column left sortable in a grid
whose field is absent from the whitelist gives the user a header that 422s or silently does
nothing. The mitigation is that C3's spec takes the whitelists from this document as its
input, and its review checks them column by column.

**Capability loss.** Sorting by computed columns goes away. Stated above, and it must appear
in the user-facing docs rather than being discovered.

**Behaviour must not change until C3 lands.** C1 only adds optional parameters. Every
endpoint's default ordering and unfiltered result must be identical afterwards, which the
default-ordering tests exist to prove.

## Out of scope

- Sorting by joined names — recorded as follow-on; each needs its join shape checked.
- Sorting by Python-computed aggregates — would require restructuring each into the main query.
- The frontend (C3).
- `GET /releases/{id}/raid`'s sort — RAID rows are ordered `item_type, seq, id`, which is a
  domain ordering the grid presents as-is.
