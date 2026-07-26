# Scope Windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a release manager find a system's releases and see, per release, whether the scope cutoff (`scope_deadline`) is still open — via a global "Scope Windows" page (system filter) and a Scope Windows tab on the System detail page.

**Architecture:** A pure `compute_scope_window` helper derives a `window_status` + `days_to_cutoff` from `scope_deadline` / `actual_date` / now. The existing `GET /releases` list is extended with a `system_id` filter and three computed fields (`window_status`, `days_to_cutoff`, `systems`). The frontend adds one shared `ScopeWindowsTable` component consumed by a new page and a new System-detail tab; it fetches via the existing `releaseService.list(filters)` into local component state (no Redux, to avoid clobbering the shared release list).

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, PostgreSQL (SQLite for tests), React 18 + TypeScript + MUI + MUI X DataGrid.

**Spec:** `docs/superpowers/specs/2026-07-26-scope-windows-design.md`

**Conventions (verified in-repo):**
- Services never `db.commit()`; use `db.flush()`. Enum-ish columns are plain `String`.
- No frontend unit tests (project convention) — verify frontend with `tsc --noEmit` + `npm run build`.
- Run the FULL backend suite as a checkpoint: `cd backend && PYTHONPATH=. uv run pytest -q` (covers BOTH `tests/services/` and `tests/integration/` — a signature/behaviour change can break callers in either).
- Shell cwd persists across commands; use `git -C /Users/peter/Developer/Code/projects/envmgr` for git when a prior `cd` changed the dir.
- `ReleaseListItemRead` extends `ReleaseRead` (`ConfigDict(from_attributes=True)`); new fields need safe defaults so other callers of the list are unaffected.
- The list handler already computes `now = datetime.now(timezone.utc)` in its overdue-criteria block and builds each row as `item = ReleaseListItemRead.model_validate(r)` in a `for r in releases:` loop — reuse both.

---

## Task 1: `compute_scope_window` helper (pure)

**Files:**
- Create: `backend/app/services/scope_window.py`
- Test: `backend/tests/services/test_scope_window.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_scope_window.py`:

```python
from datetime import datetime, timedelta, timezone

from app.services.scope_window import compute_scope_window

NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)


def test_shipped_when_actual_date_set():
    # actual_date wins even if a deadline exists and is in the past
    status, days = compute_scope_window(NOW - timedelta(days=5), NOW - timedelta(days=1), NOW)
    assert status == "shipped"
    assert days is None


def test_no_cutoff_when_no_deadline():
    status, days = compute_scope_window(None, None, NOW)
    assert status == "no_cutoff"
    assert days is None


def test_closed_when_deadline_passed():
    status, days = compute_scope_window(NOW - timedelta(days=2), None, NOW)
    assert status == "closed"
    assert days == -2


def test_closing_soon_within_threshold():
    status, days = compute_scope_window(NOW + timedelta(days=3), None, NOW)
    assert status == "closing_soon"
    assert days == 3


def test_closing_soon_at_exactly_seven_days():
    status, days = compute_scope_window(NOW + timedelta(days=7), None, NOW)
    assert status == "closing_soon"
    assert days == 7


def test_open_when_comfortably_ahead():
    status, days = compute_scope_window(NOW + timedelta(days=30), None, NOW)
    assert status == "open"
    assert days == 30


def test_naive_deadline_treated_as_utc():
    naive = (NOW + timedelta(days=10)).replace(tzinfo=None)
    status, days = compute_scope_window(naive, None, NOW)
    assert status == "open"
    assert days == 10
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/services/test_scope_window.py -v`
Expected: FAIL — module `app.services.scope_window` does not exist.

- [ ] **Step 3: Implement the helper**

Create `backend/app/services/scope_window.py`:

```python
"""Pure computation of a release's scope-window status.

A release's scope window tells a release manager whether scope can still be
added before the cutoff (`scope_deadline`). Derived from data we already have
so no new columns or queries are required.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

# A window this close to (or past) its cutoff is flagged "closing_soon".
CLOSING_SOON_DAYS = 7


def compute_scope_window(
    scope_deadline: Optional[datetime],
    actual_date: Optional[datetime],
    now: datetime,
) -> tuple[str, Optional[int]]:
    """Return (window_status, days_to_cutoff).

    window_status is one of: shipped, no_cutoff, closed, closing_soon, open.
    days_to_cutoff is a signed day count (negative once past), or None when
    there is no meaningful cutoff (shipped / no_cutoff). Checked in order:

    1. actual_date set        -> shipped   (release deployed; scope closed)
    2. scope_deadline is None -> no_cutoff (nothing to measure against)
    3. now >= scope_deadline  -> closed
    4. within CLOSING_SOON    -> closing_soon
    5. otherwise              -> open
    """
    if actual_date is not None:
        return "shipped", None
    if scope_deadline is None:
        return "no_cutoff", None

    deadline = scope_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)

    days = (deadline - now).days
    if now >= deadline:
        return "closed", days
    if deadline - now <= timedelta(days=CLOSING_SOON_DAYS):
        return "closing_soon", days
    return "open", days
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/services/test_scope_window.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/services/scope_window.py backend/tests/services/test_scope_window.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): compute_scope_window helper"
```

---

## Task 2: Schema fields (`ReleaseSystemBrief` + list fields)

**Files:**
- Modify: `backend/app/api/v1/schemas/release.py`

- [ ] **Step 1: Add the brief model + fields**

In `backend/app/api/v1/schemas/release.py`, add a `ReleaseSystemBrief` class ABOVE `ReleaseListItemRead` (after `ReleaseStatusHistoryRead` is fine):

```python
class ReleaseSystemBrief(BaseModel):
    id: int
    name: str
    role: str
```

Then add three fields to `ReleaseListItemRead` (after `scope_creep_count`):

```python
    window_status: str = "no_cutoff"
    days_to_cutoff: Optional[int] = None
    systems: list[ReleaseSystemBrief] = []
```

`Optional` and `list` typing are already imported in that file (`from typing import Optional, Any`). `BaseModel` is imported.

- [ ] **Step 2: Verify import**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run python -c "from app.api.v1.schemas.release import ReleaseListItemRead, ReleaseSystemBrief; print(ReleaseListItemRead.model_fields.keys())"`
Expected: prints field names including `window_status`, `days_to_cutoff`, `systems`; no error.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/api/v1/schemas/release.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): scope-window + systems fields on ReleaseListItemRead"
```

---

## Task 3: `system_id` filter in `list_releases` service

**Files:**
- Modify: `backend/app/services/release_service.py` (`list_releases`)

- [ ] **Step 1: Add the parameter + filter**

In `backend/app/services/release_service.py`, in `list_releases`, add `system_id: Optional[int] = None` to the keyword-only params (next to `release_kind`). Then, inside the function where the other `base_where` filters are appended (near `if release_kind is not None:`), add:

```python
    if system_id is not None:
        from app.db.models.release_system import ReleaseSystem
        base_where.append(
            Release.id.in_(
                select(ReleaseSystem.release_id).where(
                    ReleaseSystem.system_id == system_id,
                    ReleaseSystem.tenant_id == tenant_id,
                )
            )
        )
```

(`select` is already imported at the top of the module. Using a subquery avoids duplicate release rows when a system is linked in multiple roles.)

- [ ] **Step 2: Verify import/compile**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run python -c "import app.services.release_service; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/services/release_service.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): system_id filter in list_releases"
```

---

## Task 4: Endpoint wiring (`system_id` param + systems + window fields) + API test

**Files:**
- Modify: `backend/app/api/v1/releases.py` (`list_releases` handler)
- Test: `backend/tests/integration/test_scope_windows_api.py`

- [ ] **Step 1: Write the failing API test**

Create `backend/tests/integration/test_scope_windows_api.py` (copies the local `authed_client` fixture pattern used elsewhere, built on `tenant`/`user`/`release_lifecycle_template`):

```python
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.system import System
from app.db.models.release_system import ReleaseSystem


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username, "password": "password123", "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


async def _link_system(db_session, tenant_id, release_id, name="Core"):
    sys = System(tenant_id=tenant_id, name=name)
    db_session.add(sys)
    await db_session.flush()
    db_session.add(ReleaseSystem(
        tenant_id=tenant_id, release_id=release_id, system_id=sys.id, role="changing",
    ))
    await db_session.flush()
    return sys.id


@pytest.mark.asyncio
async def test_system_filter_and_window_fields(authed_client, tenant, db_session, release_lifecycle_template):
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Sysrel", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id, "scope_deadline": future,
    })
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    sid = await _link_system(db_session, tenant.id, rid)

    # Unrelated release, no system link, no deadline
    r2 = await authed_client.post("/api/v1/releases", json={
        "name": "Other", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id,
    })
    assert r2.status_code == 201

    # Filter by system → only the linked release
    resp = await authed_client.get(f"/api/v1/releases?system_id={sid}")
    assert resp.status_code == 200, resp.text
    ids = [x["id"] for x in resp.json()]
    assert ids == [rid]
    row = resp.json()[0]
    assert row["window_status"] == "open"
    assert row["days_to_cutoff"] == 29 or row["days_to_cutoff"] == 30
    assert [s["name"] for s in row["systems"]] == ["Core"]

    # No filter → both releases; the deadline-less one reports no_cutoff
    allresp = await authed_client.get("/api/v1/releases")
    other = next(x for x in allresp.json() if x["id"] == r2.json()["id"])
    assert other["window_status"] == "no_cutoff"
    assert other["days_to_cutoff"] is None
    assert other["systems"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_windows_api.py -v`
Expected: FAIL — `system_id` param not accepted / `window_status` absent or wrong.

- [ ] **Step 3: Add the query param**

In `backend/app/api/v1/releases.py`, in the `list_releases` handler signature, add after the `release_kind` query param:

```python
    system_id: Optional[int] = Query(None),
```

and pass it into the service call (add `system_id=system_id,` to the `release_service.list_releases(...)` kwargs).

- [ ] **Step 4: Hydrate systems per release**

Still in `list_releases`, after the block that builds `overdue_counts` (which defines `now`, `datetime`, `timezone`, and imports `GateCriterion`) and before `result = []`, add:

```python
    # Systems linked to each release (for the Scope Windows view)
    from app.db.models.release_system import ReleaseSystem
    from app.db.models.system import System
    from app.api.v1.schemas.release import ReleaseSystemBrief
    sys_rows = (
        await db.execute(
            select(ReleaseSystem.release_id, System.id, System.name, ReleaseSystem.role)
            .join(System, System.id == ReleaseSystem.system_id)
            .where(
                ReleaseSystem.release_id.in_(release_ids),
                ReleaseSystem.tenant_id == tenant_id,
                System.deleted_at.is_(None),
            )
        )
    ).all()
    systems_by_release: dict[int, list[ReleaseSystemBrief]] = {}
    for rid, sid, sname, role in sys_rows:
        systems_by_release.setdefault(rid, []).append(
            ReleaseSystemBrief(id=sid, name=sname, role=role)
        )
```

- [ ] **Step 5: Set window + systems fields on each item**

Add the import near the other service imports at the top of `releases.py`:

```python
from app.services.scope_window import compute_scope_window
```

Then inside the `for r in releases:` loop, after `item.scope_creep_count = creep_counts.get(r.id, 0)`, add:

```python
        window_status, days_to_cutoff = compute_scope_window(r.scope_deadline, r.actual_date, now)
        item.window_status = window_status
        item.days_to_cutoff = days_to_cutoff
        item.systems = systems_by_release.get(r.id, [])
```

(`now` is the `datetime.now(timezone.utc)` already defined in the overdue block above.)

- [ ] **Step 6: Run to verify pass**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_windows_api.py -v`
Expected: 1 passed.

- [ ] **Step 7: Regression on the releases list**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/ -k "release or scope" -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/api/v1/releases.py backend/tests/integration/test_scope_windows_api.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): system filter + scope-window fields on releases list API"
```

---

## Task 5: Frontend types

**Files:**
- Modify: `frontend/src/types/release.ts`

- [ ] **Step 1: Add the system brief + list fields + filter param**

In `frontend/src/types/release.ts`:

Add a `ReleaseSystemBrief` interface (near the top, before `ReleaseListItemResponse`):
```typescript
export interface ReleaseSystemBrief {
  id: number;
  name: string;
  role: string;
}
```
Add three fields to `ReleaseListItemResponse` (after `scope_creep_count`):
```typescript
  window_status: 'open' | 'closing_soon' | 'closed' | 'shipped' | 'no_cutoff';
  days_to_cutoff: number | null;
  systems: ReleaseSystemBrief[];
```
Add `system_id` to `ReleaseListFilters`:
```typescript
  system_id?: number;
```

- [ ] **Step 2: Typecheck**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit`
Expected: no new errors from this file.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/types/release.ts
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): frontend types for scope-window fields + system_id filter"
```

---

## Task 6: `ScopeWindowsTable` shared component

**Files:**
- Create: `frontend/src/components/releases/ScopeWindowsTable.tsx`

This component fetches releases via `releaseService.list(filters)` into local state (NOT Redux — avoids clobbering the shared release list). Used by both the global page and the System-detail tab.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/releases/ScopeWindowsTable.tsx`:

```tsx
/**
 * ScopeWindowsTable — releases for a system with their scope cutoff status.
 * Fetches into local state (no Redux) so it never clobbers the shared release list.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Chip, MenuItem, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { releaseService } from '../../services/releaseService';
import { systemService } from '../../services/systemService';
import type { ReleaseListItemResponse } from '../../types/release';
import type { SystemResponse } from '../../types/system';

const WINDOW_COLORS: Record<string, 'default' | 'success' | 'warning' | 'info'> = {
  open: 'success',
  closing_soon: 'warning',
  closed: 'default',
  shipped: 'info',
  no_cutoff: 'default',
};

const WINDOW_LABELS: Record<string, string> = {
  open: 'Open',
  closing_soon: 'Closing soon',
  closed: 'Closed',
  shipped: 'Shipped',
  no_cutoff: 'No cutoff',
};

interface Props {
  /** When set, the table is fixed to this system and the system filter is hidden. */
  systemId?: number;
  /** Show the system dropdown (global page). Ignored when systemId is set. */
  showSystemFilter?: boolean;
}

export default function ScopeWindowsTable({ systemId, showSystemFilter }: Props) {
  const navigate = useNavigate();
  const [rows, setRows] = useState<ReleaseListItemResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [systems, setSystems] = useState<SystemResponse[]>([]);
  const [selectedSystem, setSelectedSystem] = useState<number | ''>('');
  const [windowFilter, setWindowFilter] = useState<'actionable' | 'all'>('actionable');

  const effectiveSystemId = systemId ?? (selectedSystem === '' ? undefined : Number(selectedSystem));

  useEffect(() => {
    if (showSystemFilter && !systemId) {
      systemService.listSystems().then(setSystems).catch(() => setSystems([]));
    }
  }, [showSystemFilter, systemId]);

  useEffect(() => {
    setLoading(true);
    releaseService
      .list({ release_kind: 'project', system_id: effectiveSystemId })
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [effectiveSystemId]);

  const visibleRows = useMemo(() => {
    const filtered =
      windowFilter === 'actionable'
        ? rows.filter((r) => r.window_status === 'open' || r.window_status === 'closing_soon')
        : rows;
    // Soonest cutoff first; nulls (shipped / no_cutoff) last.
    return [...filtered].sort((a, b) => {
      const av = a.days_to_cutoff;
      const bv = b.days_to_cutoff;
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return av - bv;
    });
  }, [rows, windowFilter]);

  const columns = useMemo<GridColDef<ReleaseListItemResponse>[]>(
    () => [
      { field: 'name', headerName: 'Release', flex: 1, minWidth: 180 },
      {
        field: 'systems',
        headerName: 'Systems',
        width: 200,
        sortable: false,
        renderCell: (params) => (
          <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap' }}>
            {params.row.systems.length === 0 ? (
              <Typography variant="body2" color="text.secondary">—</Typography>
            ) : (
              params.row.systems.map((s) => (
                <Chip key={s.id} label={s.name} size="small" variant="outlined" />
              ))
            )}
          </Stack>
        ),
      },
      { field: 'release_type', headerName: 'Type', width: 110 },
      { field: 'status', headerName: 'Status', width: 120 },
      {
        field: 'target_date',
        headerName: 'Target',
        width: 120,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'scope_deadline',
        headerName: 'Scope deadline',
        width: 140,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'window_status',
        headerName: 'Window',
        width: 130,
        renderCell: (params) => (
          <Chip
            size="small"
            label={WINDOW_LABELS[params.row.window_status] ?? params.row.window_status}
            color={WINDOW_COLORS[params.row.window_status] ?? 'default'}
          />
        ),
      },
      {
        field: 'days_to_cutoff',
        headerName: 'Days to cutoff',
        width: 130,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) =>
          params.row.days_to_cutoff === null ? (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ) : (
            <Typography variant="body2">{params.row.days_to_cutoff}</Typography>
          ),
      },
      { field: 'scope_count', headerName: 'Scope', width: 90, align: 'center', headerAlign: 'center' },
      {
        field: 'scope_creep_count',
        headerName: 'Creep',
        width: 90,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) =>
          params.row.scope_creep_count > 0 ? (
            <Chip label={params.row.scope_creep_count} color="warning" size="small" />
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
    ],
    []
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        {showSystemFilter && !systemId && (
          <TextField
            select
            label="System"
            size="small"
            value={selectedSystem}
            onChange={(e) => setSelectedSystem(e.target.value === '' ? '' : Number(e.target.value))}
            sx={{ minWidth: 220 }}
          >
            <MenuItem value="">All systems</MenuItem>
            {systems.map((s) => (
              <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
            ))}
          </TextField>
        )}
        <ToggleButtonGroup
          value={windowFilter}
          exclusive
          size="small"
          onChange={(_, v) => v && setWindowFilter(v)}
          aria-label="Window filter"
        >
          <ToggleButton value="actionable">Open / closing soon</ToggleButton>
          <ToggleButton value="all">All</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Box sx={{ height: 560, width: '100%' }}>
        <DataTable<ReleaseListItemResponse>
          storageKey="scope-windows-table"
          rows={visibleRows}
          columns={columns}
          loading={loading}
          emptyMessage="No releases with scope windows"
          onRowClick={(params) => navigate(`/releases/${params.row.id}`)}
        />
      </Box>
    </Box>
  );
}
```

Note: confirm the import path/type name for systems. `systemService.listSystems()` returns `SystemResponse[]` (verified in `frontend/src/services/systemService.ts`). If `SystemResponse` is exported from a different module than `../../types/system`, fix the import to match the actual location (grep `export interface SystemResponse`). Also confirm `DataTable`'s `onRowClick`/`valueFormatter` param shapes match how `ReleaseList.tsx` uses them (they do — mirror that file).

- [ ] **Step 2: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean. Fix any import-path mismatch for `SystemResponse` if flagged.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/components/releases/ScopeWindowsTable.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): ScopeWindowsTable shared component"
```

---

## Task 7: Scope Windows page + route + nav

**Files:**
- Create: `frontend/src/pages/releases/ScopeWindows.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/navConfig.tsx`

- [ ] **Step 1: Create the page**

Create `frontend/src/pages/releases/ScopeWindows.tsx`:

```tsx
import { Box, Typography } from '@mui/material';
import ScopeWindowsTable from '../../components/releases/ScopeWindowsTable';

export default function ScopeWindows() {
  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Scope Windows
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Find a system's releases and see which scope cutoffs are still open.
      </Typography>
      <ScopeWindowsTable showSystemFilter />
    </Box>
  );
}
```

- [ ] **Step 2: Register the route (BEFORE `/releases/:id`)**

In `frontend/src/App.tsx`, add the import near the other release page imports:
```tsx
import ScopeWindows from './pages/releases/ScopeWindows';
```
Add the route immediately BEFORE the `<Route path="/releases/:id" ... />` line (so `scope-windows` is not captured as an `:id`):
```tsx
          <Route path="/releases/scope-windows" element={<ScopeWindows />} />
```

- [ ] **Step 3: Add the nav entry**

In `frontend/src/components/navConfig.tsx`, in the *Release Management* group's `children` array, add after the Timeline entry:
```tsx
      { label: 'Releases — Scope Windows', path: '/releases/scope-windows', icon: <ScheduleIcon /> },
```
Add the icon import at the top of `navConfig.tsx` (match the existing MUI icon import style):
```tsx
import ScheduleIcon from '@mui/icons-material/Schedule';
```

- [ ] **Step 4: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/pages/releases/ScopeWindows.tsx frontend/src/App.tsx frontend/src/components/navConfig.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): Scope Windows page + route + nav entry"
```

---

## Task 8: System detail "Scope Windows" tab

**Files:**
- Modify: `frontend/src/pages/systems/SystemDetail.tsx`

- [ ] **Step 1: Add the tab + panel**

In `frontend/src/pages/systems/SystemDetail.tsx`:

Add the import near the other component imports:
```tsx
import ScopeWindowsTable from '../../components/releases/ScopeWindowsTable';
```
Add a 6th `<Tab>` after the `<Tab label="Topology" />` line:
```tsx
        <Tab label="Scope Windows" />
```
Add a tab panel after the existing `tab === 4` (Topology) panel. Use the numeric system id already in scope (the route param `id` used elsewhere in this component — confirm its name by grepping `useParams`; it is the release/system id the page already loads). Render:
```tsx
      {tab === 5 && (
        <Paper sx={{ p: 3 }}>
          <ScopeWindowsTable systemId={Number(id)} />
        </Paper>
      )}
```
If the component names the system id differently (e.g. `systemId` or `currentSystem?.id`), use that instead of `Number(id)` — it must be the current system's numeric id. `Paper` is already imported in this file.

- [ ] **Step 2: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/pages/systems/SystemDetail.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): Scope Windows tab on system detail"
```

---

## Task 9: Full regression + wrap-up

- [ ] **Step 1: Full backend suite (services + integration)**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest -q`
Expected: all pass, no new failures (the `list_releases` service gained an optional param — confirm no positional-arg caller broke; it's keyword-only so none should).

- [ ] **Step 2: Frontend typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Manual smoke (optional, via /run or dev servers)**

Open **Release Management → Releases — Scope Windows**: pick a system → see its project releases with scope-deadline, a colored Window chip, and days-to-cutoff, defaulted to open/closing-soon and sorted soonest-first. Open a **System → Scope Windows** tab → same table scoped to that system. Row click → release detail.

---

## Self-Review Notes (spec coverage)

- Window-status computation (shipped/no_cutoff/closed/closing_soon/open + signed days, 7-day threshold, actual_date precedence, naive-datetime handling): Task 1. ✅
- `system_id` filter (subquery, tenant-scoped): Task 3 + Task 4. ✅
- `window_status` / `days_to_cutoff` / `systems` on the list response: Tasks 2, 4, 5. ✅
- Global Scope Windows page (system filter, actionable default, soonest-first sort, project default, row link): Tasks 6, 7. ✅
- System-detail Scope Windows tab (fixed system_id, shared component): Task 8. ✅
- No new columns/migration (derived fields only). ✅
- Pillar B (analytics) intentionally deferred — not in this plan. ✅
- Type consistency: `ReleaseSystemBrief` (backend `{id,name,role}`) matches the TS `ReleaseSystemBrief`; `window_status` string literal union matches the five backend statuses; `compute_scope_window` signature `(scope_deadline, actual_date, now)` used identically in Task 1 and Task 4. ✅
```
