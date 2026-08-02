# ScopeWindowsTable — server-side paging, sorting and filtering

**Status**: design, not started. Branch `feature/scope-windows-server-side`, off `main` at `ac3660e`.

## What this fixes

`ScopeWindowsTable` is the twelfth grid with the bug the C3 rollout removed from the other
eleven: it fetches a capped page (`releaseService.list({ limit: 200 })`) and then filters
and sorts it in the browser. A tenant with more than 200 releases gets a scope-window
worklist computed from a truncated set, with nothing in the UI saying so.

It was excluded from the rollout because `window_status` and `days_to_cutoff` are computed
in Python after the query (`releases.py:328-330`), so neither could be filtered or sorted in
SQL. `docs/pagination.md` records it as needing "a `CASE` expression and a date diff, with
dual-engine date-arithmetic risk".

**That assessment was too pessimistic. No date arithmetic is required at all.**

## The two insights this design rests on

Both follow from reading `backend/app/services/scope_window.py`, which is a pure function of
`(scope_deadline, actual_date, now)`.

### 1. The "actionable" filter is a comparison, not a computation

`actionable` means `window_status` is `open` or `closing_soon`. Working back through
`compute_scope_window`, both of those mean exactly:

```
actual_date IS NULL AND scope_deadline IS NOT NULL AND scope_deadline > :now
```

`closed` is `now >= scope_deadline`; `shipped` and `no_cutoff` are excluded by the two null
checks. The `closing_soon` / `open` split is irrelevant to the filter, because both are
actionable — so `CLOSING_SOON_DAYS` never enters the SQL.

One bound parameter, three comparisons. No `EXTRACT`, no `julianday`, no dialect divergence.

### 2. Sorting by `days_to_cutoff` is sorting by `scope_deadline`

`days_to_cutoff` is `(scope_deadline - now).days` for a fixed `now`, so it is monotonic in
`scope_deadline`: ordering by one is ordering by the other.

This matters because Python's `timedelta.days` **floors** toward negative infinity, while
PostgreSQL's `EXTRACT` and SQLite's `CAST(julianday(...) AS INTEGER)` both truncate toward
zero. A literal port would silently change the value for past deadlines. Sorting by the
deadline sidesteps the mismatch entirely — we never compute a day count in SQL.

## The design

### Null-ness carries the grouping

Today's order is "soonest cutoff first, shipped and no-cutoff last", because
`days_to_cutoff` is `NULL` for both of those states. Rather than reproduce that with a
`CASE` bucket in the `ORDER BY` — which `apply_sort` cannot express, and which would give
this page custom ordering code the other eleven don't have — map the whitelist entry to an
expression that is **null exactly when `days_to_cutoff` is null**:

```python
"scope_deadline": case((Release.actual_date.isnot(None), null()), else_=Release.scope_deadline)
```

`apply_sort` already pins NULLs last on ascending and first on descending. So shipped and
no-cutoff releases group at the end automatically — today's exact order — with no custom
ordering, and descending mirrors it consistently with every other nullable column in the app.

This is the whole trick: the grouping the UI wants *is* null-ordering, once "shipped" is
folded into the null.

**Verified before writing this spec**, rather than assumed — the design rests entirely on
this expression composing with the existing primitive:

- `expr.type` infers as `DateTime(timezone=True)` from the `else_` branch, so `_sort_key`'s
  `isinstance(column.type, String)` check is **False** and the expression is not wrapped in
  `lower()`. Case-folding a datetime would have been wrong.
- Both dialects emit the same thing, with the tiebreaker intact:

  ```sql
  ORDER BY CASE WHEN (release.actual_date IS NOT NULL) THEN NULL
                ELSE release.scope_deadline END ASC NULLS LAST, release.id
  ```

(A bare `None` in place of `null()` also works and infers the same type; `null()` is used
for explicitness.)

### Backend

- **`RELEASE_SORTS` gains `scope_deadline`**, mapped to the expression above.
- **`sorting()`'s type hint widens** from `Mapping[str, InstrumentedAttribute]` to accept a
  SQL expression. It already works at runtime — `apply_sort` only calls `.asc()`/`.desc()`
  and `.nullsfirst()`/`.nullslast()`, and `_sort_key`'s `isinstance(column.type, String)`
  check is satisfied by any typed expression. Only the annotation is too narrow.
- **`GET /releases` gains `scope_window: Optional[str]`**, pattern `^(actionable|all)$`.
  `actionable` applies the three-comparison filter with `now` bound from Python; `all` and
  omitted apply nothing. Placed with the other filters at `releases.py:150-166`.
- **`window_status` and `days_to_cutoff` keep being computed in Python** for display
  (`releases.py:328-330`). They stop being what we filter and sort on, which is the point.
  `window_status` remains permanently unsortable.

`compute_scope_window` itself is not touched. The SQL filter and the Python display value
must agree, which is what the boundary tests below exist to prove.

### Frontend

- **`sortWhitelists.json`** gains `scope_deadline` under `releases`.
  `backend/tests/test_sort_whitelist_contract.py` asserts both sides agree, so drift is a CI
  failure. `releaseColumnsSortable.test.ts` iterates `ReleaseList`'s own columns only, so a
  whitelist entry with no corresponding column there is fine.
- **The Cutoff column becomes `field: 'scope_deadline'`** while still rendering
  `row.days_to_cutoff` via `renderCell`. This matters: MUI keys its sort model off `field`,
  and `useServerGrid` resolves an unknown field to the endpoint default *silently*. A column
  left as `field: 'days_to_cutoff'` and marked sortable would appear to sort and quietly
  return `created_at desc`. Sorting by deadline is sorting by days, so the display stays
  honest.
- **`window_status`** gets `sortable: false` and `ComputedColumnHeader`.
- **`ScopeWindowsTable` converts to `useServerGrid`**: the `visibleRows` `useMemo` — both the
  filter and the sort — is deleted outright, `DataTable` runs in server mode, and the
  window toggle writes `scope_window` through `grid.setFilter`.

### One extension to the shared hook

This is the first converted page whose default order differs from its endpoint's. `GET
/releases` declares `default="created_at", default_dir="desc"`; this table must open on
cutoff-ascending.

`useServerGrid` gains an optional `defaultSort?: { field: string; dir: SortDir }`, used by
`resolveSort` when the URL carries no `sort_by`. An explicit URL sort always wins, and the
field is still validated against the whitelist — an invalid `defaultSort` falls back to the
endpoint default rather than reaching the server, matching how an invalid URL sort is
already handled.

Rejected: seeding the URL from an effect on mount. That fires a second navigation and a
second fetch on every visit and puts a junk entry in history — the same class of problem the
drafts machinery was added to fix.

## Testing

**Backend, dual-engine** — the filter and the sort are now SQL, so both legs must run:

- `scope_window=actionable` returns exactly the releases whose Python-computed
  `window_status` is `open` or `closing_soon`, and excludes `closed`, `shipped` and
  `no_cutoff`. Assert against `compute_scope_window`'s own output rather than a hardcoded
  list, so the SQL filter and the display value cannot drift apart.
- Boundary: a release whose `scope_deadline` is a second in the future is actionable; one a
  second in the past is not. This is where a naive date-diff port would have failed.
- **A shipped release with a `scope_deadline` set sorts last**, alongside no-cutoff releases
  — the case that motivated the whole null-folding design, and the one a plain
  `ORDER BY scope_deadline` would get wrong.
- Descending mirrors it: those rows come first.
- Sorting composes with the `id` tiebreaker, per the standing rule.

**Frontend:**

- The window toggle sends `scope_window`, and the page opens on `scope_deadline` ascending
  without the URL having said so.
- `defaultSort` is overridden by an explicit URL sort, and an invalid `defaultSort` falls
  back to the endpoint default.
- Column sortability matches the whitelist; `window_status` is unsortable and carries the
  computed header.
- No client-side filtering or sorting survives.

Every test verified by breaking what it covers. This repo has shipped five tests that
guarded nothing, all in ordering and pagination code.

**Browser:** both call sites — `/releases/scope-windows` (with the system filter) and the
Scope Windows tab of a system's detail page (`systemId` fixed, filter hidden). The toggle
must narrow the footer total, not just the visible rows.

## Out of scope

- `compute_scope_window`'s own semantics, including the docstring's claim that
  `days_to_cutoff == 0` spans "just passed" — Python's `timedelta.days` floors, so a
  just-passed deadline gives `-1`. Wrong comment, correct code; not this change's business.
- The `useAllX` hooks' lack of request dedup, which makes the Scope Windows tab of a system
  page fetch `/systems/` twice. Recorded in `docs/pagination.md`.
- The other items listed there as still open: `/releases/calendar` and `/releases/timeline`
  truncating at 500, and the endpoints under *Not yet bounded*.
