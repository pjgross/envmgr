# Pagination C3 Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ReleaseList` fetch, filter, sort and page entirely on the server, and build the shared plumbing the other eight list pages will reuse.

**Architecture:** A checked-in JSON file transcribes the nine backend sort whitelists and is asserted from both sides, so cross-language drift fails CI. Pure helpers translate DataGrid state into API parameters; a `useServerGrid` hook wraps them with URL state, debounce and staleness guarding. Services stop discarding `X-Total-Count`; the fetch still goes through existing Redux thunks.

**Tech Stack:** React 18, TypeScript (strict), MUI 5 + `@mui/x-data-grid` 6.20.4 Community, Redux Toolkit, axios, react-router-dom, vitest + @testing-library/react, Playwright. Backend: FastAPI, pytest.

## Global Constraints

- **`sort_dir` is always sent alongside `sort_by`.** Four endpoints declare `default_dir="desc"`; omitting the direction makes a first header click render descending.
- **`sort_by` is validated against the whitelist before any request.** An unknown field is a 422 on the server by design, so it must never leave the browser.
- **Never fall back to client-side filtering.** A page that filters a truncated set is the bug being removed.
- **`sortable: false` on every column not in that endpoint's whitelist** — including `id` and action columns.
- **Filter and sort changes reset `page` to 0.**
- **`'all'` and `''` are the pages' existing "no filter" sentinels** and must be omitted from the request, not sent.
- **TypeScript is strict**; `npm run lint` runs with `--max-warnings 0`.
- Backend tests run from the repo root: `cd backend && uv run pytest -q`.

---

### Task 1: Sort-whitelist contract file + backend agreement test

**Files:**
- Create: `frontend/src/constants/sortWhitelists.json`
- Test: `backend/tests/test_sort_whitelist_contract.py`

**Interfaces:**
- Consumes: the nine `*_SORTS` dicts in `backend/app/api/v1/`.
- Produces: `frontend/src/constants/sortWhitelists.json`, keyed by endpoint slug, each `{ sortable: string[], default: string, default_dir: "asc" | "desc" }`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sort_whitelist_contract.py`:

```python
"""The frontend and backend must agree on which fields are sortable.

`docs/pagination.md` warns that a grid column left sortable whose field the
backend does not whitelist gives the user a header that looks clickable and 422s
the moment they click it — and that nothing in either codebase enforces it. This
file is that enforcement on the backend side; the frontend asserts its grids
against the same JSON.
"""
import json
from pathlib import Path

import pytest

from app.api.v1.bookings import BOOKING_SORTS
from app.api.v1.builds import BUILD_SORTS
from app.api.v1.change_requests import CHANGE_REQUEST_SORTS
from app.api.v1.deployments import DEPLOYMENT_SORTS
from app.api.v1.environments import ENVIRONMENT_SORTS
from app.api.v1.incidents import INCIDENT_SORTS
from app.api.v1.infrastructure_components import INFRASTRUCTURE_SORTS
from app.api.v1.releases import RELEASE_SORTS
from app.api.v1.systems import SYSTEM_SORTS

CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "constants"
    / "sortWhitelists.json"
)

# endpoint slug -> (whitelist, sorting() default, sorting() default_dir)
WHITELISTS = {
    "releases": (RELEASE_SORTS, "created_at", "desc"),
    "bookings": (BOOKING_SORTS, "start_date", "asc"),
    "environments": (ENVIRONMENT_SORTS, "name", "asc"),
    "change-requests": (CHANGE_REQUEST_SORTS, "scheduled_start", "desc"),
    "systems": (SYSTEM_SORTS, "name", "asc"),
    "infrastructure-components": (INFRASTRUCTURE_SORTS, "name", "asc"),
    "incidents": (INCIDENT_SORTS, "detected_at", "desc"),
    "deployments": (DEPLOYMENT_SORTS, "deployed_at", "desc"),
    "builds": (BUILD_SORTS, "commit_timestamp", "desc"),
}


def _contract() -> dict:
    # Fail rather than skip: a contract test that skips itself enforces nothing.
    assert CONTRACT.is_file(), f"contract file missing at {CONTRACT}"
    return json.loads(CONTRACT.read_text())


@pytest.mark.parametrize("endpoint", sorted(WHITELISTS))
def test_contract_matches_backend_whitelist(endpoint):
    sorts, default, default_dir = WHITELISTS[endpoint]
    entry = _contract()[endpoint]
    assert sorted(entry["sortable"]) == sorted(sorts)
    assert entry["default"] == default
    assert entry["default_dir"] == default_dir


def test_contract_declares_the_default_as_sortable():
    for endpoint, entry in _contract().items():
        assert entry["default"] in entry["sortable"], endpoint


def test_contract_has_exactly_the_expected_endpoints():
    # An endpoint in the file that the backend doesn't have would let a grid
    # offer sorts no server accepts.
    assert set(_contract()) == set(WHITELISTS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_sort_whitelist_contract.py -q`
Expected: FAIL — `AssertionError: contract file missing at .../frontend/src/constants/sortWhitelists.json`

- [ ] **Step 3: Create the contract file**

Create `frontend/src/constants/sortWhitelists.json`:

```json
{
  "releases": {
    "sortable": ["name", "release_type", "release_kind", "status", "target_date", "created_at"],
    "default": "created_at",
    "default_dir": "desc"
  },
  "bookings": {
    "sortable": ["start_date", "end_date", "status"],
    "default": "start_date",
    "default_dir": "asc"
  },
  "environments": {
    "sortable": ["name", "environment_type", "status", "created_at"],
    "default": "name",
    "default_dir": "asc"
  },
  "change-requests": {
    "sortable": ["title", "change_type", "status", "scheduled_start"],
    "default": "scheduled_start",
    "default_dir": "desc"
  },
  "systems": {
    "sortable": ["name"],
    "default": "name",
    "default_dir": "asc"
  },
  "infrastructure-components": {
    "sortable": ["name", "component_type", "provider", "region", "source"],
    "default": "name",
    "default_dir": "asc"
  },
  "incidents": {
    "sortable": ["title", "severity", "status", "detected_at", "resolved_at"],
    "default": "detected_at",
    "default_dir": "desc"
  },
  "deployments": {
    "sortable": ["status", "deployer_name", "deployed_at"],
    "default": "deployed_at",
    "default_dir": "desc"
  },
  "builds": {
    "sortable": ["git_branch", "build_number", "commit_timestamp"],
    "default": "commit_timestamp",
    "default_dir": "desc"
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_sort_whitelist_contract.py -q`
Expected: PASS — 11 passed

- [ ] **Step 5: Prove the test discriminates**

Temporarily delete `"target_date"` from the `releases.sortable` array, re-run.
Expected: FAIL on `test_contract_matches_backend_whitelist[releases]`. Restore the line and confirm PASS again.

This repo has shipped ordering tests that guarded nothing (`reference_nondiscriminating_tests.md`). Do not skip this step on any task in this plan.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/constants/sortWhitelists.json backend/tests/test_sort_whitelist_contract.py
git commit -m "feat(pagination): checked-in sort-whitelist contract, asserted from the backend"
```

---

### Task 2: Pure parameter helpers

**Files:**
- Create: `frontend/src/hooks/serverGridParams.ts`
- Test: `frontend/src/hooks/__tests__/serverGridParams.test.ts`

**Interfaces:**
- Consumes: `frontend/src/constants/sortWhitelists.json` (Task 1).
- Produces:
  - `type SortDir = 'asc' | 'desc'`
  - `type EndpointKey` (keys of the contract file)
  - `type ServerGridParams = { limit: number; offset: number; sort_by: string; sort_dir: SortDir } & Record<string, string | number>`
  - `isSortable(endpoint: EndpointKey, field: string): boolean`
  - `resolveSort(endpoint, sortBy: string | null, sortDir: string | null): { sort_by: string; sort_dir: SortDir }`
  - `buildParams(args: { endpoint; page: number; pageSize: number; sortBy: string | null; sortDir: string | null; filters: Record<string, string> }): ServerGridParams`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/__tests__/serverGridParams.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { buildParams, isSortable, resolveSort } from '../serverGridParams';

describe('resolveSort', () => {
  it('keeps a whitelisted field', () => {
    expect(resolveSort('releases', 'name', 'asc')).toEqual({ sort_by: 'name', sort_dir: 'asc' });
  });

  it('falls back to the endpoint default for a field outside the whitelist', () => {
    // A bookmarked ?sort_by=phase_count must never reach the server: it is a 422.
    expect(resolveSort('releases', 'phase_count', 'asc')).toEqual({
      sort_by: 'created_at',
      sort_dir: 'asc',
    });
  });

  it('always returns a direction, even when none was supplied', () => {
    // sorting() applies an endpoint-wide default_dir when sort_dir is omitted,
    // so releases would resolve to desc. The direction is never left implicit.
    expect(resolveSort('releases', 'name', null)).toEqual({
      sort_by: 'name',
      sort_dir: 'desc',
    });
    expect(resolveSort('environments', 'name', null)).toEqual({
      sort_by: 'name',
      sort_dir: 'asc',
    });
  });

  it('ignores a junk direction', () => {
    expect(resolveSort('releases', 'name', 'sideways').sort_dir).toBe('desc');
  });
});

describe('isSortable', () => {
  it('is true for whitelisted fields and false for computed ones', () => {
    expect(isSortable('releases', 'target_date')).toBe(true);
    expect(isSortable('releases', 'phase_count')).toBe(false);
    expect(isSortable('releases', 'systems')).toBe(false);
    expect(isSortable('releases', 'id')).toBe(false);
  });
});

describe('buildParams', () => {
  it('translates page/pageSize into limit/offset', () => {
    const p = buildParams({
      endpoint: 'releases',
      page: 2,
      pageSize: 25,
      sortBy: 'name',
      sortDir: 'asc',
      filters: {},
    });
    expect(p.limit).toBe(25);
    expect(p.offset).toBe(50);
  });

  it('always includes both sort parameters', () => {
    const p = buildParams({
      endpoint: 'releases',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: {},
    });
    expect(p.sort_by).toBe('created_at');
    expect(p.sort_dir).toBe('desc');
  });

  it("omits the pages' no-filter sentinels", () => {
    const p = buildParams({
      endpoint: 'releases',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { status: 'all', release_type: '', system_id: '3' },
    });
    expect(p).not.toHaveProperty('status');
    expect(p).not.toHaveProperty('release_type');
    expect(p.system_id).toBe('3');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/__tests__/serverGridParams.test.ts`
Expected: FAIL — cannot resolve `../serverGridParams`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/hooks/serverGridParams.ts`:

```ts
import whitelists from '../constants/sortWhitelists.json';

export type SortDir = 'asc' | 'desc';
export type EndpointKey = keyof typeof whitelists;

interface WhitelistEntry {
  sortable: string[];
  default: string;
  default_dir: SortDir;
}

export type ServerGridParams = {
  limit: number;
  offset: number;
  sort_by: string;
  sort_dir: SortDir;
} & Record<string, string | number>;

/** The pages' existing "no filter selected" values. */
const NO_FILTER = ['', 'all'];

function whitelistFor(endpoint: EndpointKey): WhitelistEntry {
  return whitelists[endpoint] as WhitelistEntry;
}

export function isSortable(endpoint: EndpointKey, field: string): boolean {
  return whitelistFor(endpoint).sortable.includes(field);
}

/**
 * Resolve a possibly-untrusted sort — typically straight out of a URL — into one
 * the server will accept. An unknown `sort_by` is a 422 by design, so it must be
 * replaced here rather than sent and handled.
 *
 * A direction is always returned. `sorting()` takes one endpoint-wide
 * `default_dir` used only when the client sends nothing, and four endpoints set
 * it to "desc" — so a first click on a header that omitted the direction would
 * render descending.
 */
export function resolveSort(
  endpoint: EndpointKey,
  sortBy: string | null,
  sortDir: string | null
): { sort_by: string; sort_dir: SortDir } {
  const wl = whitelistFor(endpoint);
  return {
    sort_by: sortBy && wl.sortable.includes(sortBy) ? sortBy : wl.default,
    sort_dir: sortDir === 'asc' || sortDir === 'desc' ? sortDir : wl.default_dir,
  };
}

export function buildParams(args: {
  endpoint: EndpointKey;
  page: number;
  pageSize: number;
  sortBy: string | null;
  sortDir: string | null;
  filters: Record<string, string>;
}): ServerGridParams {
  const { sort_by, sort_dir } = resolveSort(args.endpoint, args.sortBy, args.sortDir);
  const params: ServerGridParams = {
    limit: args.pageSize,
    offset: args.page * args.pageSize,
    sort_by,
    sort_dir,
  };
  Object.entries(args.filters).forEach(([key, value]) => {
    if (!NO_FILTER.includes(value)) params[key] = value;
  });
  return params;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/hooks/__tests__/serverGridParams.test.ts`
Expected: PASS — 8 passed

- [ ] **Step 5: Prove the tests discriminate**

Change `resolveSort` to return `sort_dir: sortDir as SortDir` (dropping the fallback), re-run.
Expected: FAIL on "always returns a direction". Revert and confirm PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/serverGridParams.ts frontend/src/hooks/__tests__/serverGridParams.test.ts
git commit -m "feat(pagination): pure helpers translating grid state into API parameters"
```

---

### Task 3: Read `X-Total-Count` in the release service and slice

**Files:**
- Create: `frontend/src/types/pagination.ts`
- Modify: `frontend/src/services/releaseService.ts:51-52`
- Modify: `frontend/src/store/releaseSlice.ts` (`ReleaseState`, `initialState`, `fetchReleases` thunk + `fulfilled` reducer)
- Modify: `frontend/src/types/release.ts:146-153` (`ReleaseListFilters`)
- Modify: `backend/app/main.py:51-57` (CORS)
- Test: `frontend/src/services/__tests__/releaseServicePaged.test.ts`
- Test: `backend/tests/test_cors_exposes_total_count.py`

**Interfaces:**
- Consumes: `ServerGridParams` (Task 2).
- Produces:
  - `interface Paged<T> { rows: T[]; total: number }` in `frontend/src/types/pagination.ts`
  - `releaseService.list(params): Promise<Paged<ReleaseListItemResponse>>`
  - `state.release.total: number`

- [ ] **Step 1: Write the failing frontend test**

Create `frontend/src/services/__tests__/releaseServicePaged.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { releaseService } from '../releaseService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('releaseService.list', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }],
      headers: { 'x-total-count': '317' },
    });

    const result = await releaseService.list({ limit: 25, offset: 0 });

    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(317);
  });

  it('falls back to the row count when the header is absent', async () => {
    // A cross-origin deployment without expose_headers produces exactly this.
    // Reporting NaN would make the grid claim an unknown number of pages.
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });

    const result = await releaseService.list({});

    expect(result.total).toBe(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/services/__tests__/releaseServicePaged.test.ts`
Expected: FAIL — `result.rows` is undefined (the service currently returns the bare array)

- [ ] **Step 3: Add the `Paged` type**

Create `frontend/src/types/pagination.ts`:

```ts
/**
 * A windowed list response. Endpoints return a bare JSON array with the
 * unwindowed total in `X-Total-Count`, so the total has to be lifted out of the
 * headers before the rows reach Redux.
 */
export interface Paged<T> {
  rows: T[];
  total: number;
}
```

- [ ] **Step 4: Change the service**

In `frontend/src/services/releaseService.ts`, replace the `list` method (currently lines 51-52):

```ts
  list: (params: ReleaseListFilters = {}): Promise<Paged<ReleaseListItemResponse>> =>
    api.get('/releases', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
```

Add the import at the top of the file:

```ts
import type { Paged } from '../types/pagination';
```

- [ ] **Step 5: Widen the filter type**

In `frontend/src/types/release.ts`, replace `ReleaseListFilters` (currently lines 146-153):

```ts
export interface ReleaseListFilters {
  status?: string;
  release_type?: string;
  release_kind?: ReleaseKind;
  from_date?: string;
  to_date?: string;
  system_id?: number | string;
  search?: string;
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/services/__tests__/releaseServicePaged.test.ts`
Expected: PASS — 2 passed

- [ ] **Step 7: Store the total in the slice**

In `frontend/src/store/releaseSlice.ts`:

Add `total: number;` to `interface ReleaseState`, directly after `list`.
Add `total: 0,` to `initialState`, directly after `list: []`.
Replace the `fetchReleases.fulfilled` case (currently line 323):

```ts
      .addCase(fetchReleases.fulfilled, (state, action) => {
        state.loading = false;
        state.list = action.payload.rows;
        state.total = action.payload.total;
      })
```

- [ ] **Step 8: Verify the app still compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors ONLY in files that read `state.release.list` expecting the old shape, if any. Fix any that appear by reading `.rows`/`.total` from the slice rather than the thunk payload. Re-run until clean.

- [ ] **Step 9: Write the failing CORS test**

Create `backend/tests/test_cors_exposes_total_count.py`:

```python
"""`X-Total-Count` must be readable by JavaScript.

`allow_headers=["*"]` governs *request* headers; it does not expose response
headers to the browser. Nothing is broken today because the bundle is served
same-origin with the API, but the whole frontend now depends on reading this
header, and the failure mode if the origins are ever split is a grid that
believes the total equals the current page length.
"""
from app.main import app


def test_cors_exposes_the_total_count_header():
    cors = [m for m in app.user_middleware if "CORSMiddleware" in str(m)]
    assert cors, "CORSMiddleware is not installed"
    assert "X-Total-Count" in cors[0].kwargs["expose_headers"]
```

- [ ] **Step 10: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_cors_exposes_total_count.py -q`
Expected: FAIL — `KeyError: 'expose_headers'`

- [ ] **Step 11: Expose the header**

In `backend/app/main.py`, add one line to the `add_middleware` call (currently lines 51-57):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)
```

- [ ] **Step 12: Run both test suites**

Run: `cd backend && uv run pytest tests/test_cors_exposes_total_count.py -q`
Expected: PASS — 1 passed

Run: `cd frontend && npx vitest run`
Expected: PASS — all existing tests still green

- [ ] **Step 13: Commit**

```bash
git add frontend/src/types/pagination.ts frontend/src/services/releaseService.ts \
        frontend/src/services/__tests__/releaseServicePaged.test.ts \
        frontend/src/store/releaseSlice.ts frontend/src/types/release.ts \
        backend/app/main.py backend/tests/test_cors_exposes_total_count.py
git commit -m "feat(pagination): lift X-Total-Count into the release slice, expose it via CORS"
```

---

### Task 4: `useServerGrid` — URL state, validation, page reset

**Files:**
- Create: `frontend/src/hooks/useServerGrid.ts`
- Test: `frontend/src/hooks/__tests__/useServerGrid.test.tsx`

**Interfaces:**
- Consumes: `buildParams`, `resolveSort`, `EndpointKey`, `ServerGridParams` (Task 2).
- Produces:

```ts
interface UseServerGridOptions {
  endpoint: EndpointKey;
  filterKeys: string[];
  onFetch: (params: ServerGridParams) => void;
}

interface ServerGrid {
  paginationModel: { page: number; pageSize: number };
  sortModel: { field: string; sort: 'asc' | 'desc' }[];
  onPaginationModelChange: (m: { page: number; pageSize: number }) => void;
  onSortModelChange: (m: { field: string; sort: 'asc' | 'desc' | null | undefined }[]) => void;
  filters: Record<string, string>;
  setFilter: (key: string, value: string) => void;
}
```

- [ ] **Step 1: Write the failing test**

Create `frontend/src/hooks/__tests__/useServerGrid.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useServerGrid } from '../useServerGrid';

function wrapper(initialEntries: string[]) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
  );
}

function setup(url = '/releases') {
  const onFetch = vi.fn();
  const hook = renderHook(
    () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
    { wrapper: wrapper([url]) }
  );
  return { ...hook, onFetch };
}

describe('useServerGrid', () => {
  it('fetches the endpoint default sort on mount', () => {
    const { onFetch } = setup();
    expect(onFetch).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 25, offset: 0, sort_by: 'created_at', sort_dir: 'desc' })
    );
  });

  it('restores page, sort and filters from the URL', () => {
    const { result } = setup('/releases?page=2&page_size=50&sort_by=name&sort_dir=asc&status=draft');
    expect(result.current.paginationModel).toEqual({ page: 2, pageSize: 50 });
    expect(result.current.sortModel).toEqual([{ field: 'name', sort: 'asc' }]);
    expect(result.current.filters.status).toBe('draft');
  });

  it('never sends a sort_by outside the whitelist, even from a URL', () => {
    const { onFetch } = setup('/releases?sort_by=phase_count');
    expect(onFetch).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'created_at' })
    );
    expect(onFetch).not.toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'phase_count' })
    );
  });

  it('resets to page 0 when a filter changes', () => {
    const { result, onFetch } = setup('/releases?page=3');
    onFetch.mockClear();
    act(() => result.current.setFilter('status', 'draft'));
    expect(result.current.paginationModel.page).toBe(0);
    expect(onFetch).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it('resets to page 0 when the sort changes', () => {
    const { result, onFetch } = setup('/releases?page=3');
    onFetch.mockClear();
    act(() => result.current.onSortModelChange([{ field: 'name', sort: 'asc' }]));
    expect(result.current.paginationModel.page).toBe(0);
    expect(onFetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'name', sort_dir: 'asc' })
    );
  });

  it('falls back to the default sort when the grid clears the sort model', () => {
    const { result, onFetch } = setup();
    onFetch.mockClear();
    act(() => result.current.onSortModelChange([]));
    expect(onFetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort_by: 'created_at', sort_dir: 'desc' })
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx`
Expected: FAIL — cannot resolve `../useServerGrid`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/hooks/useServerGrid.ts`:

```ts
import { useCallback, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  buildParams,
  resolveSort,
  type EndpointKey,
  type ServerGridParams,
  type SortDir,
} from './serverGridParams';

const DEFAULT_PAGE_SIZE = 25;

export interface UseServerGridOptions {
  endpoint: EndpointKey;
  filterKeys: string[];
  onFetch: (params: ServerGridParams) => void;
}

export interface ServerGrid {
  paginationModel: { page: number; pageSize: number };
  sortModel: { field: string; sort: SortDir }[];
  onPaginationModelChange: (model: { page: number; pageSize: number }) => void;
  onSortModelChange: (model: { field: string; sort?: SortDir | null }[]) => void;
  filters: Record<string, string>;
  setFilter: (key: string, value: string) => void;
}

/**
 * Drives a server-side DataGrid from the URL.
 *
 * The URL is the source of truth so a refresh, a back button or a shared link
 * all reproduce the same view. Anything read out of it is untrusted: `sort_by`
 * is validated against the whitelist before a request is built, because the
 * server answers an unknown field with a 422 rather than a silent fallback.
 */
export function useServerGrid({
  endpoint,
  filterKeys,
  onFetch,
}: UseServerGridOptions): ServerGrid {
  const [searchParams, setSearchParams] = useSearchParams();

  const page = Number(searchParams.get('page') ?? 0);
  const pageSize = Number(searchParams.get('page_size') ?? DEFAULT_PAGE_SIZE);
  const sort = resolveSort(endpoint, searchParams.get('sort_by'), searchParams.get('sort_dir'));

  const filters = useMemo(() => {
    const out: Record<string, string> = {};
    filterKeys.forEach((key) => {
      const value = searchParams.get(key);
      if (value !== null) out[key] = value;
    });
    return out;
  }, [searchParams, filterKeys]);

  const params = useMemo(
    () =>
      buildParams({
        endpoint,
        page,
        pageSize,
        sortBy: sort.sort_by,
        sortDir: sort.sort_dir,
        filters,
      }),
    [endpoint, page, pageSize, sort.sort_by, sort.sort_dir, filters]
  );

  const paramsKey = JSON.stringify(params);
  useEffect(() => {
    onFetch(params);
    // onFetch is a fresh dispatch closure on every render; the parameters are
    // what decide whether a refetch is warranted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  const patch = useCallback(
    (changes: Record<string, string | null>, resetPage: boolean) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(changes).forEach(([key, value]) => {
        if (value === null) next.delete(key);
        else next.set(key, value);
      });
      // A narrowed result set with a stale offset paints an empty grid over a
      // non-zero total.
      if (resetPage) next.delete('page');
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  return {
    paginationModel: { page, pageSize },
    sortModel: [{ field: sort.sort_by, sort: sort.sort_dir }],
    onPaginationModelChange: useCallback(
      (model) => patch({ page: String(model.page), page_size: String(model.pageSize) }, false),
      [patch]
    ),
    onSortModelChange: useCallback(
      (model) => {
        const first = model[0];
        // The grid clears its sort model on a third header click; the endpoint
        // default is the honest answer, and it still travels with a direction.
        const resolved = resolveSort(endpoint, first?.field ?? null, first?.sort ?? null);
        patch({ sort_by: resolved.sort_by, sort_dir: resolved.sort_dir }, true);
      },
      [endpoint, patch]
    ),
    filters,
    setFilter: useCallback((key, value) => patch({ [key]: value }, true), [patch]),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx`
Expected: PASS — 6 passed

- [ ] **Step 5: Prove the tests discriminate**

Change `patch({ ... }, true)` to `patch({ ... }, false)` in `setFilter`, re-run.
Expected: FAIL on "resets to page 0 when a filter changes". Revert and confirm PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useServerGrid.ts frontend/src/hooks/__tests__/useServerGrid.test.tsx
git commit -m "feat(pagination): useServerGrid drives a server-side grid from the URL"
```

---

### Task 5: `useServerGrid` — debounce, staleness, page clamp

**Files:**
- Modify: `frontend/src/hooks/useServerGrid.ts`
- Modify: `frontend/src/hooks/__tests__/useServerGrid.test.tsx`

**Interfaces:**
- Consumes: everything from Task 4.
- Produces: `UseServerGridOptions` gains `debounceKeys?: string[]` and `total?: number`; `onFetch` returns the value of `dispatch(thunk(params))` — an RTK promise carrying `.abort()` — typed as `{ abort: () => void } | void`.

**Cancellation, not counting.** The hook does not apply responses; the thunk's
`fulfilled` reducer writes the slice. So a hook that merely *notices* a superseded
response cannot stop it painting — the store is written either way. The guard has to
prevent the write: keep the promise returned by the previous `dispatch` and `.abort()`
it when the parameters change. An aborted RTK thunk dispatches `rejected` with
`meta.aborted`, so `fulfilled` never runs and `list`/`total` are never touched. This
also keeps the test honest — it asserts the store was not updated, rather than reading
a counter the hook exposed for the test's benefit.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/hooks/__tests__/useServerGrid.test.tsx`:

```tsx
describe('useServerGrid resilience', () => {
  it('debounces a text filter but not a select', async () => {
    vi.useFakeTimers();
    const onFetch = vi.fn();
    const { result } = renderHook(
      () =>
        useServerGrid({
          endpoint: 'releases',
          filterKeys: ['search', 'status'],
          debounceKeys: ['search'],
          onFetch,
        }),
      { wrapper: wrapper(['/releases']) }
    );
    onFetch.mockClear();

    act(() => result.current.setFilter('search', 'pay'));
    expect(onFetch).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(300));
    expect(onFetch).toHaveBeenCalledTimes(1);

    onFetch.mockClear();
    act(() => result.current.setFilter('status', 'draft'));
    expect(onFetch).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('aborts the previous request when the parameters change', () => {
    // The hook does not apply responses — the thunk's fulfilled reducer writes
    // the slice. Noticing a superseded response therefore cannot stop it
    // painting; only aborting it can, because an aborted RTK thunk never
    // reaches fulfilled.
    const aborts: number[] = [];
    let call = 0;
    const onFetch = vi.fn(() => {
      const id = call++;
      return { abort: () => aborts.push(id) };
    });
    const { result } = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: [], onFetch }),
      { wrapper: wrapper(['/releases']) }
    );

    act(() => result.current.onPaginationModelChange({ page: 1, pageSize: 25 }));
    act(() => result.current.onPaginationModelChange({ page: 2, pageSize: 25 }));

    // The mount request and the page-1 request are both superseded; the
    // in-flight page-2 request is not aborted.
    expect(aborts).toEqual([0, 1]);
  });

  it('aborts the in-flight request on unmount', () => {
    let aborted = false;
    const onFetch = vi.fn(() => ({ abort: () => { aborted = true; } }));
    const { unmount } = renderHook(
      () => useServerGrid({ endpoint: 'releases', filterKeys: [], onFetch }),
      { wrapper: wrapper(['/releases']) }
    );

    unmount();

    expect(aborted).toBe(true);
  });

  it('clamps to the last valid page when the offset runs past the total', () => {
    const onFetch = vi.fn();
    const { result, rerender } = renderHook(
      ({ total }) =>
        useServerGrid({ endpoint: 'releases', filterKeys: [], onFetch, total }),
      { wrapper: wrapper(['/releases?page=4&page_size=25']), initialProps: { total: 200 } }
    );
    onFetch.mockClear();

    // A row deleted elsewhere shrinks the set under the current offset.
    rerender({ total: 30 });

    expect(result.current.paginationModel.page).toBe(1);
    expect(onFetch).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 }));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx`
Expected: FAIL — 4 new failures (`debounceKeys` not accepted, no abort on parameter change, no abort on unmount, page not clamped)

- [ ] **Step 3: Add debounce, abort-based cancellation and clamping**

In `frontend/src/hooks/useServerGrid.ts`, extend the options and return type:

```ts
/** What `dispatch(someThunk())` returns in Redux Toolkit: a promise with `.abort()`. */
export interface Abortable {
  abort: () => void;
}

export interface UseServerGridOptions {
  endpoint: EndpointKey;
  filterKeys: string[];
  /** Return the value of `dispatch(thunk(params))` so the hook can cancel it. */
  onFetch: (params: ServerGridParams) => Abortable | void;
  /** Filter keys whose changes should be debounced — free-text inputs. */
  debounceKeys?: string[];
  /** Latest known total, used to clamp an offset that has run past the end. */
  total?: number;
}
```

`ServerGrid` is unchanged — cancellation is not observable through the interface, and
a field existing only so a test can read it would be.

Add `useRef` to the `react` import.

Replace the fetch effect with a cancelling one:

```ts
  const inFlight = useRef<Abortable | void>();

  const paramsKey = JSON.stringify(params);
  useEffect(() => {
    // Abort the previous request rather than merely ignoring its reply: the
    // response is applied by the thunk's fulfilled reducer, which this hook
    // never sees. An aborted RTK thunk dispatches rejected with meta.aborted,
    // so the slice is never written with rows the user has moved past.
    inFlight.current?.abort();
    inFlight.current = onFetch(params);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  useEffect(() => () => inFlight.current?.abort(), []);
```

Add the clamp effect immediately after it:

```ts
  useEffect(() => {
    if (total === undefined || total === 0) return;
    const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
    if (page > lastPage) patch({ page: String(lastPage) }, false);
  }, [total, page, pageSize, patch]);
```

Debounce `setFilter` for the nominated keys:

```ts
  const debounceTimer = useRef<ReturnType<typeof setTimeout>>();
  const setFilter = useCallback(
    (key: string, value: string) => {
      if (!debounceKeys.includes(key)) {
        patch({ [key]: value }, true);
        return;
      }
      clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => patch({ [key]: value }, true), 300);
    },
    [debounceKeys, patch]
  );

  useEffect(() => () => clearTimeout(debounceTimer.current), []);
```

Destructure `debounceKeys = []` and `total` from the options, and return the debounced
`setFilter` in place of the Task 4 version.

Hoist `debounceKeys = []` to a module-level `const NO_DEBOUNCE: string[] = []` default, or
memoise it — a fresh array literal per render would rebuild `setFilter` every render.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/hooks/__tests__/useServerGrid.test.tsx`
Expected: PASS — 10 passed

- [ ] **Step 5: Prove the tests discriminate**

Run all three mutations, restoring after each and confirming PASS again:

1. Remove `inFlight.current?.abort()` from the fetch effect.
   Expected: FAIL on "aborts the previous request when the parameters change".
2. Remove the unmount effect.
   Expected: FAIL on "aborts the in-flight request on unmount".
3. Make `setFilter` debounce every key (drop the `debounceKeys.includes` check).
   Expected: FAIL on "debounces a text filter but not a select".

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useServerGrid.ts frontend/src/hooks/__tests__/useServerGrid.test.tsx
git commit -m "feat(pagination): debounce text filters, abort superseded requests, clamp overshot pages"
```

---

### Task 6: `DataTable` server-mode props

**Files:**
- Modify: `frontend/src/components/DataTable.tsx:11-23` (props type), `:84-104` (render)
- Test: `frontend/src/components/__tests__/dataTableServerMode.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `DataTable` accepts `rowCount`, `paginationMode`, `sortingMode`, `paginationModel`, `onPaginationModelChange`, `sortModel`, `onSortModelChange` — all already part of `DataGridProps`, so the change is to stop `Omit`-ing them and to skip the client-side `initialState` default when in server mode.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/dataTableServerMode.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import DataTable from '../DataTable';

const columns = [{ field: 'name', headerName: 'Name' }];
const rows = [{ id: 1, name: 'alpha' }];

describe('DataTable server mode', () => {
  it('reports the server total rather than the row count', () => {
    render(
      <DataTable
        storageKey="test-grid"
        rows={rows}
        columns={columns}
        paginationMode="server"
        rowCount={317}
        paginationModel={{ page: 0, pageSize: 25 }}
        onPaginationModelChange={vi.fn()}
      />
    );
    // The footer must say 317, not 1 — that difference is the whole point.
    expect(screen.getByText(/317/)).toBeInTheDocument();
  });

  it('still works as a client-side grid when server props are omitted', () => {
    render(<DataTable storageKey="test-grid" rows={rows} columns={columns} />);
    expect(screen.getByText('alpha')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/dataTableServerMode.test.tsx`
Expected: FAIL — TypeScript rejects `paginationMode`/`rowCount`, or the footer shows 1

- [ ] **Step 3: Widen the props and guard the default `initialState`**

In `frontend/src/components/DataTable.tsx`, the `Omit` list stays as it is (it never excluded these props) — the change is to stop forcing a client-side page size when the caller drives pagination. Replace the `initialState` block in the render (currently lines 89-92):

```tsx
      initialState={
        rest.paginationMode === 'server'
          ? rest.initialState
          : {
              pagination: { paginationModel: { pageSize: 25 } },
              ...rest.initialState,
            }
      }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/dataTableServerMode.test.tsx`
Expected: PASS — 2 passed

- [ ] **Step 5: Verify the twelve existing callers are unaffected**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, no type errors. The existing grids pass no `paginationMode`, so they take the unchanged branch.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DataTable.tsx frontend/src/components/__tests__/dataTableServerMode.test.tsx
git commit -m "feat(pagination): let DataTable run in server pagination/sorting mode"
```

---

### Task 7: `ComputedColumnHeader`

**Files:**
- Create: `frontend/src/components/ComputedColumnHeader.tsx`
- Test: `frontend/src/components/__tests__/computedColumnHeader.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `<ComputedColumnHeader label="Phases" />` — a header cell rendering the label with a tooltip explaining why it cannot be sorted.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/__tests__/computedColumnHeader.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import ComputedColumnHeader from '../ComputedColumnHeader';

describe('ComputedColumnHeader', () => {
  it('renders the label', () => {
    render(<ComputedColumnHeader label="Phases" />);
    expect(screen.getByText('Phases')).toBeInTheDocument();
  });

  it('explains why the column cannot be sorted', async () => {
    render(<ComputedColumnHeader label="Phases" />);
    await userEvent.hover(screen.getByText('Phases'));
    expect(
      await screen.findByText(/not sortable across all results/i)
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/computedColumnHeader.test.tsx`
Expected: FAIL — cannot resolve `../ComputedColumnHeader`

- [ ] **Step 3: Write the component**

Create `frontend/src/components/ComputedColumnHeader.tsx`:

```tsx
import { Tooltip, Typography } from '@mui/material';

/**
 * Header for a column computed after the page is fetched.
 *
 * Twelve such columns exist across the list pages — counts and roll-ups built in
 * Python from batch queries keyed on the page's row ids, or in the browser from a
 * JSON field. None is backed by a column the database could order by, so none can
 * be sorted server-side.
 *
 * Users could sort these before server-side paging arrived, but only within the
 * truncated page they happened to hold — a sort of the wrong set. The capability
 * genuinely goes away, so it is explained rather than left as a dead header.
 */
export default function ComputedColumnHeader({ label }: { label: string }) {
  return (
    <Tooltip title="Computed after the page is fetched — not sortable across all results.">
      <Typography variant="body2" fontWeight={500} component="span">
        {label}
      </Typography>
    </Tooltip>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/computedColumnHeader.test.tsx`
Expected: PASS — 2 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ComputedColumnHeader.tsx frontend/src/components/__tests__/computedColumnHeader.test.tsx
git commit -m "feat(pagination): header explaining why computed columns cannot be sorted"
```

---

### Task 8: Convert `ReleaseList` to server-side paging, sorting and filtering

**Files:**
- Create: `frontend/src/pages/releases/releaseColumns.tsx` (extracted from `ReleaseList.tsx:94-253`)
- Modify: `frontend/src/pages/releases/ReleaseList.tsx`
- Test: `frontend/src/pages/releases/__tests__/releaseColumnsSortable.test.ts`

**Interfaces:**
- Consumes: `useServerGrid` (Tasks 4-5), `DataTable` server props (Task 6), `ComputedColumnHeader` (Task 7), `state.release.total` (Task 3).
- Produces: `releaseColumns: GridColDef<ReleaseListItemResponse>[]` exported from `releaseColumns.tsx`.

`ReleaseList.tsx` is 429 lines and holds two column definitions inline. Extracting the release columns is what makes them testable, and shrinks the page at the same time.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/releases/__tests__/releaseColumnsSortable.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { releaseColumns } from '../releaseColumns';
import { isSortable } from '../../../hooks/serverGridParams';

describe('release grid columns', () => {
  it('marks exactly the whitelisted columns sortable', () => {
    releaseColumns.forEach((col) => {
      // DataGrid treats an omitted `sortable` as true.
      const declared = col.sortable ?? true;
      expect({ field: col.field, sortable: declared }).toEqual({
        field: col.field,
        sortable: isSortable('releases', col.field),
      });
    });
  });

  it('covers the computed columns that lose sorting', () => {
    const computed = ['phase_count', 'scope_count', 'scope_change_count', 'blocker_count', 'systems'];
    computed.forEach((field) => {
      const col = releaseColumns.find((c) => c.field === field);
      expect(col, `${field} column missing`).toBeDefined();
      expect(col?.sortable).toBe(false);
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/releases/__tests__/releaseColumnsSortable.test.ts`
Expected: FAIL — cannot resolve `../releaseColumns`

- [ ] **Step 3: Extract the columns**

Create `frontend/src/pages/releases/releaseColumns.tsx` containing the array currently built in the `releaseColumns` `useMemo` at `ReleaseList.tsx:94-253`, moved verbatim, then amended:

- Add `sortable: false` to `id`, `phase_count`, `scope_count`, `scope_change_count`, `blocker_count`, `overdue_criterion_count`, and `systems`. (`systems` already has it.)
- Give `phase_count`, `scope_count`, `scope_change_count`, `blocker_count`, `overdue_criterion_count` and `systems` a `renderHeader`:

```tsx
        renderHeader: () => <ComputedColumnHeader label="Phases" />,
```

  …with the matching label per column: `Phases`, `Scope`, `Scope Changes`, `Blockers`, `Overdue`, `Systems`.
- Leave `name`, `release_type`, `release_kind`, `status`, `target_date` and `created_at` sortable — they are the six whitelisted fields.

Export it as a module-level constant (it closes over nothing):

```tsx
export const releaseColumns: GridColDef<ReleaseListItemResponse>[] = [ /* … */ ];
```

Note `id` is **not** in the release whitelist, so the ID column stops being sortable. That is correct and the test asserts it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/releases/__tests__/releaseColumnsSortable.test.ts`
Expected: PASS — 2 passed

- [ ] **Step 5: Wire the page to the server**

In `frontend/src/pages/releases/ReleaseList.tsx`:

Delete the `releaseColumns` `useMemo` and import the extracted constant. Delete the `filteredRows` `useMemo` (lines 82-92) and the four `useState` filter declarations (lines 58-61) entirely — the hook owns that state now.

Replace the mount effect (lines 68-70) and the grid with:

```tsx
  const { list, total, loading } = useSelector((s: RootState) => s.release);

  const grid = useServerGrid({
    endpoint: 'releases',
    filterKeys: ['status', 'release_type', 'release_kind', 'system_id'],
    total,
    onFetch: (params) => dispatch(fetchReleases(params)),
  });
```

Point each filter control at the hook — for example the Status select:

```tsx
              value={grid.filters.status ?? 'all'}
              onChange={(e) => grid.setFilter('status', e.target.value)}
```

…and identically for `release_type` (the Type select), `release_kind` (the kind ToggleButtonGroup, whose `onChange` passes the value directly) and `system_id` (the System select).

Replace the grid:

```tsx
            <DataTable<ReleaseListItemResponse>
              storageKey="releases-list"
              userId={currentUserId}
              rows={list}
              columns={releaseColumns}
              loading={loading}
              emptyMessage="No releases yet"
              onRowClick={(params) => navigate(`/releases/${params.row.id}`)}
              paginationMode="server"
              sortingMode="server"
              rowCount={total}
              paginationModel={grid.paginationModel}
              onPaginationModelChange={grid.onPaginationModelChange}
              sortModel={grid.sortModel}
              onSortModelChange={grid.onSortModelChange}
            />
```

The Backlog tab is untouched — `fetchBacklogChanges` is a different endpoint and out of scope.

- [ ] **Step 6: Verify the whole frontend suite and types**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all PASS, no type errors, zero warnings.

- [ ] **Step 7: Verify by hand against a running app**

Start the stack per `CLAUDE.md` (`docker-compose up -d`, then backend and frontend dev servers). Log in as `admin`/`admin123`, tenant `demo`, and confirm on `/releases`:

1. The footer total matches `X-Total-Count` in the Network tab, not the row count.
2. Changing a filter issues a new request with the filter as a **query parameter** — not a request without it.
3. Clicking `Name` sorts **ascending** on the first click. This is the `default_dir="desc"` trap: if it sorts descending, `sort_dir` is not being sent.
4. Page 2 shows different ids from page 1.
5. Hovering `Phases` shows the tooltip; the header does not sort.
6. Reloading the page preserves the filters, sort and page from the URL.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/releases/releaseColumns.tsx frontend/src/pages/releases/ReleaseList.tsx \
        frontend/src/pages/releases/__tests__/releaseColumnsSortable.test.ts
git commit -m "feat(releases): server-side paging, sorting and filtering on the release list"
```

---

### Task 9: End-to-end coverage

**Files:**
- Create: `frontend/e2e/releases-pagination.spec.ts`

**Interfaces:**
- Consumes: the converted page (Task 8). Follows the existing Playwright setup in `frontend/e2e/` (`global-setup.ts` handles auth).

- [ ] **Step 1: Write the spec**

Create `frontend/e2e/releases-pagination.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

test.describe('release list server-side pagination', () => {
  test('page 2 asks the server for the next window', async ({ page }) => {
    await page.goto('/releases');
    const request = page.waitForRequest(
      (r) => r.url().includes('/api/v1/releases') && r.url().includes('offset=25')
    );
    await page.getByRole('button', { name: /next page/i }).click();
    expect(await request).toBeTruthy();
  });

  test('sorting by name sends both sort parameters, ascending first', async ({ page }) => {
    await page.goto('/releases');
    const request = page.waitForRequest((r) => r.url().includes('sort_by=name'));
    await page.getByRole('columnheader', { name: 'Name' }).click();
    const url = (await request).url();
    expect(url).toContain('sort_by=name');
    // The endpoint's default_dir is desc; an omitted direction would silently
    // invert a first click.
    expect(url).toContain('sort_dir=asc');
  });

  test('a filter narrows the total, not just the visible rows', async ({ page }) => {
    await page.goto('/releases');
    const before = await page.locator('.MuiTablePagination-displayedRows').innerText();
    await page.getByLabel('Status').click();
    await page.getByRole('option', { name: 'Draft' }).click();
    await expect(page.locator('.MuiTablePagination-displayedRows')).not.toHaveText(before);
  });
});
```

- [ ] **Step 2: Run the e2e suite**

Run: `cd frontend && npm run test:e2e -- releases-pagination.spec.ts`
Expected: 3 passed. The suite needs the backend and frontend running — see `frontend/e2e/global-setup.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/releases-pagination.spec.ts
git commit -m "test(releases): e2e coverage for server-side paging, sorting and filtering"
```

---

### Task 10: Documentation

**Files:**
- Modify: `docs/pagination.md` (add a "C3 pilot" section after "What sub-project C3 must honour")
- Modify: `CLAUDE.md` (pagination banner)

- [ ] **Step 1: Record what the pilot established**

Add to `docs/pagination.md`, after the C3 contract section: the contract file's path and that it is asserted from both sides; that `useServerGrid` always sends `sort_dir`; that `id` is not sortable on any grid unless whitelisted; and that eight pages remain on the client-side pattern until the rollout.

- [ ] **Step 2: Update the CLAUDE.md banner**

Change the pagination programme paragraph to record C3's pilot as landed and name the eight pages still outstanding.

- [ ] **Step 3: Commit**

```bash
git add docs/pagination.md CLAUDE.md
git commit -m "docs: record the C3 pilot and what the rollout still owes"
```

---

## Self-Review

**Spec coverage.** Contract file → Task 1. Pure helpers and whitelist validation → Task 2. `Paged<T>`, service, slice, CORS → Task 3. URL state, explicit `sort_dir`, page reset → Task 4. Debounce, staleness, clamp → Task 5. `DataTable` server props → Task 6. Tooltip on computed columns → Task 7. `ReleaseList` conversion and the per-grid agreement test → Task 8. E2E → Task 9. Docs → Task 10.

**Deliberately deferred.** The spec's 422-resets-to-default-sort-and-snackbars behaviour is not implemented here: Task 4 makes an out-of-whitelist `sort_by` unable to leave the browser, so the 422 path is unreachable from the UI. Adding a recovery path for an unreachable state would be untestable through the interface. It belongs with the rollout, where a second page might reach it by another route — noted so it is not mistaken for an oversight.

**Not covered because it is not the pilot's job.** The eight remaining pages, and the open question in the spec about whether `ChangeRequestList`'s environment/host filters and `IncidentList`'s system filter have server parameters. That must be checked per page during the rollout.

**Type consistency.** `ServerGridParams`, `EndpointKey`, `SortDir`, `Paged<T>`, `releaseColumns`, `isSortable`, `resolveSort`, `buildParams` and `useServerGrid` are each defined once and used with the same names and signatures throughout.
