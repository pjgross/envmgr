# ScopeWindowsTable — Server-Side Conversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `ScopeWindowsTable` — the twelfth and last grid still filtering a truncated page in the browser — to true server-side paging, sorting and filtering.

**Architecture:** Two small backend additions (a `scope_deadline` sort key whose expression folds "shipped" into NULL, and a `scope_window=actionable` filter that is three comparisons against one bound `now`), one extension to the shared `useServerGrid` hook (a page-level default sort), then the established page conversion. No date arithmetic in SQL anywhere.

**Tech Stack:** FastAPI + SQLAlchemy 2 (async), PostgreSQL and SQLite; React 18 + TypeScript, Redux Toolkit, MUI DataGrid 6.20.4, vitest + @testing-library/react.

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-02-scope-windows-server-side-design.md`](../specs/2026-08-02-scope-windows-server-side-design.md). Read it first.
- Branch `feature/scope-windows-server-side`, already created off `main` at `ac3660e` and carrying the spec commit `a6754eb`. Do not create another branch.
- Backend tests: `cd backend && PYTHONPATH=. uv run pytest -q`. **Both engines must pass** — PostgreSQL with `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test`. The filter and the sort are now SQL, so a SQLite-only run is not evidence.
- Frontend tests: from `frontend/`, `npx vitest run <path>`. Lint `npm run lint` (`--max-warnings 0`). Types `npx tsc --noEmit`.
- **Never fall back to client-side filtering.** The `visibleRows` memo — both its filter and its sort — comes out entirely.
- **Every test verified by breaking the thing it covers.** This repo has shipped five tests that guarded nothing, all in ordering and pagination code.
- `compute_scope_window` in `backend/app/services/scope_window.py` is **not** modified. The SQL filter and the Python display value must agree; the tests prove it rather than the code sharing a path.
- Conventional commits, one per task.

## The two facts the design rests on

Both are derived in the spec; repeated here because every task depends on them.

1. **`actionable` = `open` or `closing_soon`, and both mean `now < scope_deadline`.** So the filter is `actual_date IS NULL AND scope_deadline IS NOT NULL AND scope_deadline > :now`. The `CLOSING_SOON_DAYS` threshold never enters SQL.
2. **Sorting by `days_to_cutoff` is sorting by `scope_deadline`** — one is monotonic in the other. This avoids porting Python's `timedelta.days`, which **floors**, where PostgreSQL's `EXTRACT` and SQLite's `CAST(julianday(...) AS INTEGER)` **truncate toward zero**. A literal port would silently change the value for past deadlines.

---

### Task 1: the `scope_deadline` sort key

`GET /releases` whitelists `name`, `release_type`, `release_kind`, `status`, `target_date`, `created_at`. The Cutoff column needs a seventh entry — and it must reproduce today's "shipped and no-cutoff last" grouping.

Rather than a `CASE` bucket in the `ORDER BY` (which `apply_sort` cannot express, and which would give this page ordering code the other eleven don't have), map the entry to an expression that is **NULL exactly when `days_to_cutoff` is NULL**. `apply_sort` already pins NULLs last on ascending, so the grouping falls out for free.

**Files:**
- Modify: `backend/app/core/pagination.py:109-111` (the `Sort` dataclass) and `:173` (`_sort_key`)
- Modify: `backend/app/api/v1/releases.py:93-100` (`RELEASE_SORTS`)
- Modify: `frontend/src/constants/sortWhitelists.json`
- Test: `backend/tests/test_scope_window_sorting.py` (create)

**Interfaces:**
- Consumes: `apply_sort`, `Sort` from `app.core.pagination`.
- Produces: `RELEASE_SORTS["scope_deadline"]`, a sortable field usable as `?sort_by=scope_deadline`. Task 4 uses it as the page's default sort.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scope_window_sorting.py`. Model the fixtures on the release helpers in `backend/tests/test_sorting.py` — read `_tied_releases` there for how a release is built (it needs a `LifecycleTemplate` and a user via `ensure_user`).

```python
"""Sorting by the scope-window cutoff.

`days_to_cutoff` is computed in Python after the query, so it cannot be
sorted on directly. It is monotonic in `scope_deadline`, so the whitelist
sorts by the deadline instead — and it is NULL exactly when the release is
shipped or has no deadline, which the mapped expression reproduces by
folding "shipped" into NULL. `apply_sort` then pins those rows last on
ascending, which is the order the UI has always shown.
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.api.v1.releases import RELEASE_SORTS
from app.core.pagination import Sort, apply_sort
from app.db.models.release import Release


@pytest.mark.asyncio
async def test_a_shipped_release_sorts_last_even_with_a_deadline(
    db_session, test_tenant
):
    """The case that motivated the design. A plain `ORDER BY scope_deadline`
    would sort this release by its date; the UI has always shown it last,
    because its days_to_cutoff is None."""
    early = await _release(db_session, test_tenant.id, "early-open",
                           deadline=datetime(2026, 3, 1, tzinfo=timezone.utc))
    shipped = await _release(db_session, test_tenant.id, "shipped-with-deadline",
                             deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
                             actual=datetime(2026, 1, 5, tzinfo=timezone.utc))
    later = await _release(db_session, test_tenant.id, "later-open",
                           deadline=datetime(2026, 4, 1, tzinfo=timezone.utc))

    names = await _sorted_names(db_session, test_tenant.id, descending=False)

    assert names == ["early-open", "later-open", "shipped-with-deadline"]
    assert (early.id, later.id, shipped.id)  # keep the fixtures referenced


@pytest.mark.asyncio
async def test_a_release_with_no_deadline_also_sorts_last(db_session, test_tenant):
    await _release(db_session, test_tenant.id, "has-deadline",
                   deadline=datetime(2026, 3, 1, tzinfo=timezone.utc))
    await _release(db_session, test_tenant.id, "no-deadline", deadline=None)

    names = await _sorted_names(db_session, test_tenant.id, descending=False)

    assert names == ["has-deadline", "no-deadline"]


@pytest.mark.asyncio
async def test_descending_mirrors_the_grouping(db_session, test_tenant):
    """Consistent with every other nullable column: NULLs first on DESC."""
    await _release(db_session, test_tenant.id, "has-deadline",
                   deadline=datetime(2026, 3, 1, tzinfo=timezone.utc))
    await _release(db_session, test_tenant.id, "no-deadline", deadline=None)

    names = await _sorted_names(db_session, test_tenant.id, descending=True)

    assert names == ["no-deadline", "has-deadline"]


@pytest.mark.asyncio
async def test_the_sort_precedes_the_id_tiebreaker(test_tenant):
    """Standing rule: a sort composes with the unique tiebreaker, never
    replaces it, or LIMIT/OFFSET duplicates and drops rows across pages."""
    from sqlalchemy.dialects import postgresql

    query = apply_sort(
        select(Release).where(Release.tenant_id == test_tenant.id),
        Sort(column=RELEASE_SORTS["scope_deadline"], descending=False),
    ).order_by(Release.id)

    order_by = str(query.compile(dialect=postgresql.dialect())).split("ORDER BY", 1)[1]
    assert "CASE" in order_by
    assert "NULLS LAST" in order_by
    assert order_by.rstrip().endswith("release.id")
```

Write `_release(db_session, tenant_id, name, *, deadline, actual=None)` and `_sorted_names(db_session, tenant_id, *, descending)` as local helpers. `_sorted_names` applies `apply_sort(select(Release).where(tenant, deleted_at is None), Sort(column=RELEASE_SORTS["scope_deadline"], descending=...)).order_by(Release.id)` and returns the names. Create the `LifecycleTemplate` once per test as `test_sorting.py` does.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scope_window_sorting.py -q -p no:logging
```

Expected: all four FAIL with `KeyError: 'scope_deadline'`.

- [ ] **Step 3: Widen the type hints**

`app/core/pagination.py`. A sort target is no longer always a mapped column — it can be any SQL expression. Add an alias near the top of the sorting section and use it in the three places that currently say `InstrumentedAttribute`:

```python
from sqlalchemy.sql.elements import ColumnElement

# A sort target is usually a mapped column, but it may be any typed SQL
# expression — `RELEASE_SORTS["scope_deadline"]` is a CASE that folds a
# shipped release's deadline into NULL so `apply_sort`'s NULL pinning
# reproduces the UI's "shipped last" grouping.
SortTarget = Union[InstrumentedAttribute, ColumnElement]
```

Then `Sort.column: SortTarget`, `sorting(allowed: Mapping[str, SortTarget], ...)`, and `_sort_key(column: SortTarget)`.

No behaviour changes. `_sort_key`'s `isinstance(column.type, String)` already works on an expression — the spec verified that a `case()` over a `DateTime` column infers `DateTime(timezone=True)`, so it is correctly **not** wrapped in `lower()`.

- [ ] **Step 4: Add the whitelist entry**

`app/api/v1/releases.py`, in `RELEASE_SORTS`:

```python
from sqlalchemy import case, null

RELEASE_SORTS = {
    "name": Release.name,
    "release_type": Release.release_type,
    "release_kind": Release.release_kind,
    "status": Release.status,
    "target_date": Release.target_date,
    "created_at": Release.created_at,
    # Sorting by the scope-window cutoff. `days_to_cutoff` is computed in
    # Python after the query so it cannot be sorted on, but it is monotonic
    # in `scope_deadline` — and NULL exactly when the release is shipped or
    # has no deadline. Folding "shipped" into NULL here lets apply_sort's
    # existing NULL pinning reproduce the UI's "shipped and no-cutoff last"
    # grouping, with no CASE bucket in the ORDER BY and no date arithmetic.
    "scope_deadline": case(
        (Release.actual_date.isnot(None), null()),
        else_=Release.scope_deadline,
    ),
}
```

- [ ] **Step 5: Add it to the frontend whitelist**

`frontend/src/constants/sortWhitelists.json`, the `releases` entry: append `"scope_deadline"` to `sortable`. Leave `default` and `default_dir` alone — the endpoint's default stays `created_at` / `desc`; the page overrides it in Task 3.

`backend/tests/test_sort_whitelist_contract.py` asserts the JSON matches `RELEASE_SORTS`, so this must land in the same commit or that test fails.

- [ ] **Step 6: Run the tests to verify they pass, on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scope_window_sorting.py tests/test_sort_whitelist_contract.py tests/test_sorting.py -q -p no:logging
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest tests/test_scope_window_sorting.py -q -p no:logging
```

Expected: PASS on both.

- [ ] **Step 7: Verify the tests discriminate**

Temporarily change the entry to a plain `Release.scope_deadline` (dropping the `case`). Expected: `test_a_shipped_release_sorts_last_even_with_a_deadline` FAILS — the shipped release sorts first, by its January date. Restore.

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/pagination.py backend/app/api/v1/releases.py frontend/src/constants/sortWhitelists.json backend/tests/test_scope_window_sorting.py
git commit -m "feat(releases): sort by scope-window cutoff, shipped last"
```

---

### Task 2: the `scope_window` filter

**Files:**
- Modify: `backend/app/services/release_service.py:240-256` (signature) and `:257-285` (`base_where`)
- Modify: `backend/app/api/v1/releases.py` — the endpoint signature and the `now` hoist
- Test: `backend/tests/test_scope_window_filter.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `GET /releases?scope_window=actionable`. `list_releases` gains `scope_window: Optional[str] = None` and `now: Optional[datetime] = None`.

**One `now`, passed down.** The endpoint currently computes `now = datetime.now(timezone.utc)` at `releases.py:235`, *after* the service call, for `compute_scope_window`. The filter needs the same instant, so hoist that line above the `list_releases` call and pass it in. Two separately-sampled clocks would let the SQL filter and the displayed status disagree for a release sitting on the boundary — rare, but exactly the kind of thing that produces an unreproducible bug report.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scope_window_filter.py`:

```python
"""`scope_window=actionable` filters in SQL, not in the browser.

`actionable` means window_status is `open` or `closing_soon`. Both mean
`now < scope_deadline`, so the filter is three comparisons against one
bound `now` — the closing-soon threshold never enters SQL. These tests
assert against `compute_scope_window`'s own output rather than a
hardcoded list, so the SQL filter and the displayed status cannot drift
apart.
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.services import release_service
from app.services.scope_window import compute_scope_window


@pytest.mark.asyncio
async def test_actionable_returns_exactly_the_open_and_closing_soon_releases(
    db_session, test_tenant
):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "open", deadline=now + timedelta(days=30))
    await _release(db_session, test_tenant.id, "closing-soon", deadline=now + timedelta(days=3))
    await _release(db_session, test_tenant.id, "closed", deadline=now - timedelta(days=1))
    await _release(db_session, test_tenant.id, "no-cutoff", deadline=None)
    await _release(db_session, test_tenant.id, "shipped", deadline=now + timedelta(days=10),
                   actual=now - timedelta(days=2))

    rows, total = await release_service.list_releases(
        db_session, test_tenant.id, scope_window="actionable", now=now, limit=50
    )

    # Cross-check against the Python computation rather than a literal list.
    expected = {
        r.name for r in await _all(db_session, test_tenant.id)
        if compute_scope_window(r.scope_deadline, r.actual_date, now)[0]
        in ("open", "closing_soon")
    }
    assert {r.name for r in rows} == expected == {"open", "closing-soon"}
    assert total == 2


@pytest.mark.asyncio
async def test_the_boundary_is_strict_and_matches_the_python_rule(
    db_session, test_tenant
):
    """`compute_scope_window` returns "closed" when `now >= deadline`, so a
    release sitting exactly ON its deadline is NOT actionable. The SQL
    comparison must therefore be strict `>`, not `>=`.

    This is also where a naive date-diff port would have gone wrong:
    Python's timedelta.days floors while both engines' date functions
    truncate toward zero, so the two would disagree about a just-passed
    deadline. Comparing timestamps sidesteps that entirely.
    """
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "just-open", deadline=now + timedelta(seconds=1))
    await _release(db_session, test_tenant.id, "exactly-now", deadline=now)
    await _release(db_session, test_tenant.id, "just-closed", deadline=now - timedelta(seconds=1))

    rows, _ = await release_service.list_releases(
        db_session, test_tenant.id, scope_window="actionable", now=now, limit=50
    )

    assert {r.name for r in rows} == {"just-open"}
    # And the SQL agrees with the Python rule for each of the three.
    for r in await _all(db_session, test_tenant.id):
        actionable = compute_scope_window(r.scope_deadline, r.actual_date, now)[0] in (
            "open", "closing_soon"
        )
        assert actionable == (r.name in {row.name for row in rows}), r.name


@pytest.mark.asyncio
async def test_all_and_omitted_apply_no_filter(db_session, test_tenant):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    await _release(db_session, test_tenant.id, "open", deadline=now + timedelta(days=30))
    await _release(db_session, test_tenant.id, "closed", deadline=now - timedelta(days=1))

    for kwargs in ({"scope_window": "all", "now": now}, {}):
        rows, total = await release_service.list_releases(
            db_session, test_tenant.id, limit=50, **kwargs
        )
        assert total == 2, kwargs


@pytest.mark.asyncio
async def test_the_total_reflects_the_filter_not_the_page(db_session, test_tenant):
    """The footer count must describe the filtered set. The count query
    shares `base_where`, so this fails if the filter is applied to the row
    query alone."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(5):
        await _release(db_session, test_tenant.id, f"open-{i}", deadline=now + timedelta(days=30))
    for i in range(3):
        await _release(db_session, test_tenant.id, f"closed-{i}", deadline=now - timedelta(days=1))

    rows, total = await release_service.list_releases(
        db_session, test_tenant.id, scope_window="actionable", now=now, limit=2
    )

    assert len(rows) == 2
    assert total == 5
```

Write `_release(...)` and `_all(...)` as local helpers, same shape as Task 1's.

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scope_window_filter.py -q -p no:logging
```

Expected: FAIL with `TypeError: list_releases() got an unexpected keyword argument 'scope_window'`.

- [ ] **Step 3: Implement the service filter**

`release_service.py`. Add to the keyword-only signature:

```python
    scope_window: Optional[str] = None,
    now: Optional[datetime] = None,
```

And to `base_where`, after the `search` clause:

```python
    if scope_window == "actionable":
        # `open` or `closing_soon` — both mean the cutoff has not passed.
        # `closed` is now >= scope_deadline; `shipped` and `no_cutoff` are
        # excluded by the two null checks. CLOSING_SOON_DAYS never enters
        # SQL, so there is no date arithmetic here and nothing that differs
        # between PostgreSQL and SQLite.
        cutoff = now if now is not None else datetime.now(timezone.utc)
        base_where.append(Release.actual_date.is_(None))
        base_where.append(Release.scope_deadline.isnot(None))
        base_where.append(Release.scope_deadline > cutoff)
```

`base_where` feeds both the count and the row query, so the total describes the filtered set automatically.

- [ ] **Step 4: Wire the endpoint**

`app/api/v1/releases.py`. Add to `list_releases`'s signature, beside the other filters:

```python
    scope_window: Optional[str] = Query(None, pattern="^(actionable|all)$"),
```

Hoist `now = datetime.now(timezone.utc)` from its current position (around line 235) to **above** the `release_service.list_releases(...)` call, and pass `scope_window=scope_window, now=now` into it. The enrichment loop keeps using the same `now`, so the filter and the displayed `window_status` are computed against one instant.

- [ ] **Step 5: Run the tests, both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scope_window_filter.py -q -p no:logging
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest tests/test_scope_window_filter.py -q -p no:logging
```

- [ ] **Step 6: Verify the tests discriminate**

Two mutations, each restored, both outputs reported:

1. Change `Release.scope_deadline > cutoff` to `>=`. Expected: `test_the_boundary_is_strict_and_matches_the_python_rule` FAILS — `exactly-now` is returned, but `compute_scope_window` calls it `closed`.
2. Move the filter out of `base_where` and onto the row query only. Expected: `test_the_total_reflects_the_filter_not_the_page` FAILS with `total == 8`.

- [ ] **Step 7: Full backend suite, both engines, then commit**

```bash
git add backend/app/services/release_service.py backend/app/api/v1/releases.py backend/tests/test_scope_window_filter.py
git commit -m "feat(releases): filter by scope window in SQL"
```

---

### Task 3: `useServerGrid` gains a page-level default sort

Every converted page so far has been happy with its endpoint's declared default. `GET /releases` declares `created_at` / `desc`; this table must open on cutoff-ascending.

**Files:**
- Modify: `frontend/src/hooks/serverGridParams.ts` (`resolveSort`)
- Modify: `frontend/src/hooks/useServerGrid.ts` (options, and the two `resolveSort` calls)
- Test: `frontend/src/hooks/__tests__/serverGridParams.test.ts`, `frontend/src/hooks/__tests__/useServerGrid.test.tsx`

**Interfaces:**
- Produces: `resolveSort(endpoint, sortBy, sortDir, defaultSort?)` and `UseServerGridOptions.defaultSort?: { field: string; dir: SortDir }`. Task 4 passes `{ field: 'scope_deadline', dir: 'asc' }`.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/hooks/__tests__/serverGridParams.test.ts`, inside `describe('resolveSort', ...)`:

```ts
  it('uses a page default when the URL is silent', () => {
    // GET /releases declares created_at/desc, but the scope-windows table
    // opens on cutoff-ascending.
    expect(resolveSort('releases', null, null, { field: 'scope_deadline', dir: 'asc' }))
      .toEqual({ sort_by: 'scope_deadline', sort_dir: 'asc' });
  });

  it('lets an explicit URL sort beat the page default', () => {
    expect(resolveSort('releases', 'name', 'desc', { field: 'scope_deadline', dir: 'asc' }))
      .toEqual({ sort_by: 'name', sort_dir: 'desc' });
  });

  it('falls back to the endpoint default when the page default is not whitelisted', () => {
    // Same contract as an unknown sort_by from the URL: never send a field
    // the server answers with a 422.
    expect(resolveSort('releases', null, null, { field: 'not_a_column', dir: 'asc' }))
      .toEqual({ sort_by: 'created_at', sort_dir: 'desc' });
  });
```

And to `frontend/src/hooks/__tests__/useServerGrid.test.tsx`:

```tsx
  it('opens on the page default sort without the URL saying so', async () => {
    const onFetch = vi.fn();
    renderHook(
      () => useServerGrid({
        endpoint: 'releases',
        filterKeys: ['scope_window'],
        onFetch,
        defaultSort: { field: 'scope_deadline', dir: 'asc' },
      }),
      { wrapper: wrapper(['/releases/scope-windows']) }
    );

    await waitFor(() => expect(onFetch).toHaveBeenCalled());
    expect(onFetch.mock.calls[0][0]).toMatchObject({
      sort_by: 'scope_deadline', sort_dir: 'asc',
    });
  });
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/hooks/__tests__/serverGridParams.test.ts src/hooks/__tests__/useServerGrid.test.tsx
```

Expected: the four new tests FAIL — `resolveSort` takes three arguments, so the default is ignored and `created_at`/`desc` comes back.

- [ ] **Step 3: Implement**

`serverGridParams.ts`:

```ts
export interface DefaultSort {
  field: string;
  dir: SortDir;
}

export function resolveSort(
  endpoint: EndpointKey,
  sortBy: string | null,
  sortDir: string | null,
  defaultSort?: DefaultSort
): { sort_by: string; sort_dir: SortDir } {
  const wl = whitelistFor(endpoint);
  // A page default only applies when the URL is silent, and is validated
  // against the whitelist exactly like a URL-supplied sort_by — an unknown
  // field is a 422 at the server, so it must never leave the browser.
  const pageDefault = defaultSort && wl.sortable.includes(defaultSort.field)
    ? defaultSort
    : undefined;
  return {
    sort_by: sortBy && wl.sortable.includes(sortBy)
      ? sortBy
      : pageDefault?.field ?? wl.default,
    sort_dir: sortDir === 'asc' || sortDir === 'desc'
      ? sortDir
      : pageDefault?.dir ?? wl.default_dir,
  };
}
```

`buildParams` takes `defaultSort` too and forwards it to `resolveSort`.

`useServerGrid.ts`: add `defaultSort?: DefaultSort` to `UseServerGridOptions` with a comment saying it applies only when the URL is silent and is whitelist-validated. Pass it to **both** `resolveSort` call sites — the one computing `sort` near the top, and the one inside `onSortModelChange` (which resolves a cleared sort model on the third header click; without it, clearing the sort would jump to the endpoint default rather than back to the page's).

Add `defaultSort?.field` and `defaultSort?.dir` to the `params` memo's dependency array.

- [ ] **Step 4: Run to verify they pass**

```bash
cd frontend && npx vitest run src/hooks/__tests__/ && npx tsc --noEmit
```

Expected: PASS, including every pre-existing hook test — pages that pass no `defaultSort` must behave exactly as before.

- [ ] **Step 5: Verify the tests discriminate**

Remove the `wl.sortable.includes(defaultSort.field)` guard. Expected: `falls back to the endpoint default when the page default is not whitelisted` FAILS. Restore.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/
git commit -m "feat(pagination): let a page declare its own default sort"
```

---

### Task 4: convert `ScopeWindowsTable`

**Files:**
- Modify: `frontend/src/components/releases/ScopeWindowsTable.tsx`
- Test: `frontend/src/components/releases/__tests__/scopeWindowsTableServerGrid.test.tsx` (create)

**Interfaces:**
- Consumes: Task 1's `scope_deadline` sort key, Task 2's `scope_window` param, Task 3's `defaultSort`.

**This component holds its own state — there is no Redux slice.** It calls `releaseService.list()` directly into local `rows`. So `onFetch` returns `void` rather than an abortable, which the hook's type already allows; this table simply does not get abort-on-supersede. Note it and move on.

**The `field` trap.** MUI keys its sort model off the column `field`, and `useServerGrid` resolves an unknown field to the endpoint default **silently**. The Cutoff column must become `field: 'scope_deadline'` while still rendering `row.days_to_cutoff` through `renderCell` — otherwise the header looks sortable and quietly returns `created_at desc`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/releases/__tests__/scopeWindowsTableServerGrid.test.tsx`. Follow the harness in `frontend/src/pages/releases/__tests__/ReleaseList.test.tsx` — mock `releaseService`, render inside `<Provider store={store}>` and `<MemoryRouter>`.

```tsx
  it('opens on cutoff-ascending with the actionable filter, without the URL saying so', async () => {
    renderTable();
    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 0, sort_by: 'scope_deadline', sort_dir: 'asc',
      scope_window: 'actionable',
    }));
  });

  it('sends scope_window=all when the toggle is switched', async () => {
    renderTable();
    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    await userEvent.click(screen.getByRole('button', { name: /^All$/ }));

    await waitFor(() => expect(lastListParams()).toMatchObject({ scope_window: 'all' }));
  });

  it('marks window_status unsortable and keys the cutoff column on scope_deadline', () => {
    const byField = Object.fromEntries(scopeWindowColumns.map((c) => [c.field, c]));
    // GET /releases whitelists scope_deadline, not days_to_cutoff. A column
    // keyed on days_to_cutoff would resolve to the endpoint default silently.
    expect(byField.scope_deadline).toBeDefined();
    expect(byField.days_to_cutoff).toBeUndefined();
    expect(byField.window_status.sortable).toBe(false);
    expect(byField.window_status.renderHeader).toBeDefined();
  });

  it('renders the day count in the cutoff column, not the raw date', () => {
    const col = scopeWindowColumns.find((c) => c.field === 'scope_deadline');
    const cell = col!.renderCell!({ row: { days_to_cutoff: -3 } } as never);
    render(<>{cell}</>);
    expect(screen.getByText('-3')).toBeInTheDocument();
  });
```

Export the columns as `export const scopeWindowColumns` with the scoped `// eslint-disable-next-line react-refresh/only-export-components`, as the converted pages do.

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Convert the component**

Replace the `rows`/`loading` state, the fetch effect and the `visibleRows` memo with:

```tsx
  const [rows, setRows] = useState<ReleaseListItemResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const grid = useServerGrid({
    endpoint: 'releases',
    filterKeys: ['scope_window', 'release_kind', 'system_id'],
    defaultSort: { field: 'scope_deadline', dir: 'asc' },
    onFetch: (params) => {
      setLoading(true);
      releaseService
        .list(params)
        .then(({ rows: r, total: t }) => { setRows(r); setTotal(t); })
        .catch(() => { setRows([]); setTotal(0); })
        .finally(() => setLoading(false));
    },
    total,
    totalPending: loading,
  });
```

No `debounceKeys` — this table has no text input.

The window toggle reads `grid.filters.scope_window ?? 'actionable'` and writes `grid.setFilter('scope_window', value)`. The kind and system selects move onto `grid.filters` / `grid.setFilter` the same way. **Delete the `visibleRows` memo entirely** — both its filter and its sort.

When `systemId` is a fixed prop (the system-detail tab), keep passing it as the `system_id` filter value rather than exposing the picker, matching today's `effectiveSystemId` behaviour.

Columns: `window_status` gets `sortable: false` plus `ComputedColumnHeader` (match its usage in `frontend/src/pages/builds/BuildList.tsx`); the Cutoff column becomes `field: 'scope_deadline'`, `headerName: 'Cutoff'`, rendering `row.days_to_cutoff` via `renderCell`.

`DataTable` gets the server props: `rowCount={total}`, `paginationMode="server"`, `sortingMode="server"`, `paginationModel`, `onPaginationModelChange`, `sortModel`, `onSortModelChange`, `pageSizeOptions={[10, 25, 50, 100]}`, `loading={loading}`. `DataTable` sets `disableColumnFilter` itself in server mode — do not hand-roll it.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Verify the tests discriminate**

Three mutations, each restored, all outputs reported:

1. Remove `defaultSort`. Expected: the first test fails — `sort_by` comes back `created_at`.
2. Drop `scope_window` from `filterKeys`. Expected: the second test fails.
3. Rename the cutoff column's field back to `days_to_cutoff`. Expected: the third test fails.

- [ ] **Step 6: Full suite, lint, types, commit**

```bash
cd frontend && npx vitest run && npm run lint && npx tsc --noEmit
git add frontend/src/components/releases/
git commit -m "feat(releases): server-side paging on the scope-windows table"
```

---

### Task 5: verify in a browser, document, and open the PR

Six defects in this programme have been found only by opening the page, every one with a green suite. The most recent was found by the user, not by a test.

- [ ] **Step 1: Every gate, both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest -q
cd ../frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

- [ ] **Step 2: Verify in the browser**

Backend on :8000, `npm run dev` on :5173, signed in as `admin`/`admin123` (tenant `demo`). **Both call sites**:

- **`/releases/scope-windows`** (system filter shown)
- **A system's Scope Windows tab** — `/systems/:id`, tab index 5, where `systemId` is fixed and the picker is hidden

On each:
- The grid renders, the spinner clears, the footer shows a server total.
- **Only `name`, `release_type`, `release_kind`, `status`, `target_date`, `created_at` and the Cutoff column offer sort arrows.** `window_status` must not.
- The page opens on **cutoff ascending** without the URL saying so, and shipped / no-cutoff releases appear **last**.
- Toggling to **All** widens the **footer total**, not just the visible rows — that is the difference between server-side filtering and the bug being removed.
- A click on the Cutoff header re-sorts and issues a request (watch the Network tab for `sort_by=scope_deadline`).
- The URL carries the state and a refresh reproduces the view.

If the dev tenant has too few releases with deadlines to be meaningful, say so rather than reporting a check you could not really make.

- [ ] **Step 3: Update `docs/pagination.md`**

`ScopeWindowsTable` is currently recorded under "Still open after the programme" as needing a `CASE` expression and a date diff. Replace that entry: it is converted, and record **why the recorded assessment was wrong** — the actionable filter is three comparisons, and sorting by the deadline replaces sorting by the day count because one is monotonic in the other. That correction is the transferable part.

Note the twelfth grid is now converted, and that the `useAllX` dedup item and the calendar/timeline `limit=500` remain open.

- [ ] **Step 4: Update `CLAUDE.md`'s header** — the pagination programme's "still open" list no longer includes `ScopeWindowsTable`.

- [ ] **Step 5: Commit, push, open the PR**

- [ ] **Step 6: Confirm all four CI jobs pass before reporting done.** Do not report ready on a partial result.
