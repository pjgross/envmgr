# Scope-Churn Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Release Analytics" page showing whether shipped project releases whose scope changed tend to be delayed / have issues more than those whose scope held — via a read-only aggregation endpoint.

**Architecture:** `GET /releases/scope-churn-analytics` → a pure `scope_churn_service` that, over shipped project releases in a date window, computes three booleans per release (`scope_changed`, `delayed`, `had_issue`) from existing data (scope creep, `'Scope Change'`/`'Reschedule Reason'` events, deployment statuses) and splits them into scope-changed vs stable cohorts with % delayed / % issue. Frontend adds a page with two cohort cards + a drill-down table. No migration.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, PostgreSQL (SQLite for tests), React 18 + TypeScript + MUI.

**Spec:** `docs/superpowers/specs/2026-07-27-scope-churn-analytics-design.md`

**Conventions (verified in-repo):**
- Services never `db.commit()`; use `db.flush()`. No frontend unit tests — verify `tsc --noEmit` + `npm run build`.
- Full backend suite is the checkpoint: `cd backend && PYTHONPATH=. uv run pytest -q`.
- Use `git -C /Users/peter/Developer/Code/projects/envmgr` for git (cwd persists across commands).
- `Release`: `tenant_id, name, release_type, release_kind(default 'project'), lifecycle_template_id, status(default 'draft'), raised_by, target_date, actual_date, scope_deadline, deleted_at`.
- `Deployment` (`app/db/models/deployment.py`): `tenant_id, build_id, environment_id, change_request_id, event_id, deployed_at, status, release_id (nullable), deleted_at`. Statuses: `pending/in_progress/success/failed/rolled_back`.
- `ReleaseEvent` (`app/db/models/release_event.py`): `tenant_id, release_id, event_type_id, description, occurred_at, recorded_by`; `ReleaseEventType`: `tenant_id, name`. Canonical event names include `'Scope Change'` and `'Reschedule Reason'`.
- `ReleaseChange` (`app/db/models/release_change.py`): `tenant_id, release_id, title, change_kind, source`; `created_at` auto-set.
- `release_scope_service.scope_creep_counts(db, release_ids, tenant_id) -> dict[int,int]` returns creep count per release (items entered after `scope_deadline`).
- In `releases.py`: `router`, `Query`, `Depends`, `get_db`, `get_current_user`, `AsyncSession`, `select`, `Optional`, `datetime` are in scope. Static release routes (`/calendar`, `/timeline`) are registered BEFORE `/{release_id}` (the `get_release` handler) — the new analytics route must go there too.
- The SQLite test DB does not enforce FKs (no `PRAGMA foreign_keys` in `tests/conftest.py`), so a test `Deployment` can use placeholder `build_id`/`environment_id`/`change_request_id` values; the analytics query never joins those tables.

---

## Task 1: Backend — schemas + `scope_churn_service` + endpoint + tests

**Files:**
- Create: `backend/app/api/v1/schemas/scope_churn_analytics.py`
- Create: `backend/app/services/scope_churn_service.py`
- Modify: `backend/app/api/v1/releases.py`
- Test: `backend/tests/integration/test_scope_churn_analytics_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_scope_churn_analytics_api.py`:

```python
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.db.base import get_db
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.deployment import Deployment

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


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


async def _release(db, tenant, user, template, name, *, kind="project",
                   scope_deadline=None, target_date=None, actual_date=None):
    r = Release(
        tenant_id=tenant.id, name=name, release_type="Test Major", release_kind=kind,
        lifecycle_template_id=template.id, status="completed", raised_by=user.id,
        scope_deadline=scope_deadline, target_date=target_date, actual_date=actual_date,
    )
    db.add(r)
    await db.flush()
    return r


async def _scope_item(db, tenant, release_id):
    db.add(ReleaseChange(tenant_id=tenant.id, release_id=release_id, title="s", change_kind="story", source="manual"))
    await db.flush()


async def _event(db, tenant, user, release_id, type_name):
    et = (await db.execute(
        select(ReleaseEventType).where(
            ReleaseEventType.tenant_id == tenant.id, ReleaseEventType.name == type_name,
        )
    )).scalar_one_or_none()
    if et is None:
        et = ReleaseEventType(tenant_id=tenant.id, name=type_name)
        db.add(et)
        await db.flush()
    db.add(ReleaseEvent(
        tenant_id=tenant.id, release_id=release_id, event_type_id=et.id,
        description="x", occurred_at=NOW, recorded_by=user.id,
    ))
    await db.flush()


async def _failed_deploy(db, tenant, release_id):
    db.add(Deployment(
        tenant_id=tenant.id, build_id=1, environment_id=1, change_request_id=1,
        event_id=f"evt-{release_id}", deployed_at=NOW, status="failed", release_id=release_id,
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_scope_churn_cohorts(authed_client, tenant, user, db_session, release_lifecycle_template):
    tpl = release_lifecycle_template
    # R1: scope creep + reschedule event + failed deploy -> all three flags true
    r1 = await _release(db_session, tenant, user, tpl, "R1",
                        scope_deadline=NOW - timedelta(days=10), target_date=NOW + timedelta(days=1),
                        actual_date=NOW)
    await _scope_item(db_session, tenant, r1.id)           # entered now > deadline -> creep
    await _event(db_session, tenant, user, r1.id, "Reschedule Reason")
    await _failed_deploy(db_session, tenant, r1.id)

    # R2: clean, on time, stable
    await _release(db_session, tenant, user, tpl, "R2",
                   target_date=NOW + timedelta(days=1), actual_date=NOW)

    # R3: scope-change event (fallback, no deadline) + late vs target (no reschedule)
    r3 = await _release(db_session, tenant, user, tpl, "R3",
                        target_date=NOW - timedelta(days=1), actual_date=NOW)
    await _event(db_session, tenant, user, r3.id, "Scope Change")

    # Excluded: not shipped, enterprise, and out-of-window
    await _release(db_session, tenant, user, tpl, "R4-unshipped", actual_date=None)
    await _release(db_session, tenant, user, tpl, "R5-ent", kind="enterprise", actual_date=NOW)
    await _release(db_session, tenant, user, tpl, "R6-old", actual_date=NOW - timedelta(days=400))

    date_from = (NOW - timedelta(days=90)).isoformat()
    date_to = (NOW + timedelta(days=1)).isoformat()
    resp = await authed_client.get(
        f"/api/v1/releases/scope-churn-analytics?date_from={date_from}&date_to={date_to}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    names = sorted(row["name"] for row in body["releases"])
    assert names == ["R1", "R2", "R3"]  # unshipped/enterprise/old excluded

    changed = body["scope_changed"]
    assert changed["count"] == 2                 # R1, R3
    assert changed["delayed_count"] == 2         # R1 (reschedule), R3 (late vs target)
    assert changed["delayed_pct"] == 100.0
    assert changed["issue_count"] == 1           # R1
    assert changed["issue_pct"] == 50.0

    stable = body["stable"]
    assert stable["count"] == 1                  # R2
    assert stable["delayed_count"] == 0
    assert stable["issue_count"] == 0
    assert stable["delayed_pct"] == 0.0


@pytest.mark.asyncio
async def test_scope_churn_empty_window(authed_client, tenant, user, db_session, release_lifecycle_template):
    await _release(db_session, tenant, user, release_lifecycle_template, "R", actual_date=NOW)
    # window that excludes everything
    date_from = (NOW + timedelta(days=10)).isoformat()
    resp = await authed_client.get(f"/api/v1/releases/scope-churn-analytics?date_from={date_from}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["releases"] == []
    assert body["scope_changed"]["count"] == 0
    assert body["scope_changed"]["delayed_pct"] == 0.0
    assert body["stable"]["count"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_churn_analytics_api.py -v`
Expected: FAIL — the endpoint does not exist.

- [ ] **Step 3: Create the schemas**

Create `backend/app/api/v1/schemas/scope_churn_analytics.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ChurnCohort(BaseModel):
    count: int
    delayed_count: int
    delayed_pct: float
    issue_count: int
    issue_pct: float


class ChurnReleaseRow(BaseModel):
    release_id: int
    name: str
    shipped_at: datetime
    scope_changed: bool
    delayed: bool
    had_issue: bool


class ScopeChurnAnalyticsRead(BaseModel):
    date_from: Optional[datetime]
    date_to: Optional[datetime]
    scope_changed: ChurnCohort
    stable: ChurnCohort
    releases: list[ChurnReleaseRow]
```

- [ ] **Step 4: Create the service**

Create `backend/app/services/scope_churn_service.py`:

```python
"""Scope-churn analytics — does changing a release's scope correlate with
delays / issues? Read-only aggregation over shipped project releases."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.release import Release
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.deployment import Deployment
from app.services import release_scope_service

_ISSUE_STATUSES = ("failed", "rolled_back")


def _cohort(rows: list[dict]) -> dict:
    count = len(rows)
    delayed = sum(1 for r in rows if r["delayed"])
    issue = sum(1 for r in rows if r["had_issue"])
    return {
        "count": count,
        "delayed_count": delayed,
        "delayed_pct": round(100 * delayed / count, 1) if count else 0.0,
        "issue_count": issue,
        "issue_pct": round(100 * issue / count, 1) if count else 0.0,
    }


async def compute_scope_churn(
    db: AsyncSession,
    tenant_id: int,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict:
    where = [
        Release.tenant_id == tenant_id,
        Release.deleted_at.is_(None),
        Release.release_kind == "project",
        Release.actual_date.is_not(None),
    ]
    if date_from is not None:
        where.append(Release.actual_date >= date_from)
    if date_to is not None:
        where.append(Release.actual_date <= date_to)

    releases = (
        await db.execute(select(Release).where(*where).order_by(Release.actual_date.desc()))
    ).scalars().all()
    ids = [r.id for r in releases]

    if not ids:
        empty = _cohort([])
        return {
            "date_from": date_from, "date_to": date_to,
            "scope_changed": empty, "stable": dict(empty), "releases": [],
        }

    creep = await release_scope_service.scope_creep_counts(db, ids, tenant_id)

    async def _event_release_ids(name: str) -> set[int]:
        rows = (
            await db.execute(
                select(ReleaseEvent.release_id)
                .join(ReleaseEventType, ReleaseEventType.id == ReleaseEvent.event_type_id)
                .where(
                    ReleaseEvent.release_id.in_(ids),
                    ReleaseEvent.tenant_id == tenant_id,
                    ReleaseEventType.name == name,
                )
            )
        ).scalars().all()
        return set(rows)

    scope_change_ids = await _event_release_ids("Scope Change")
    reschedule_ids = await _event_release_ids("Reschedule Reason")
    issue_ids = set(
        (
            await db.execute(
                select(Deployment.release_id).where(
                    Deployment.release_id.in_(ids),
                    Deployment.tenant_id == tenant_id,
                    Deployment.deleted_at.is_(None),
                    Deployment.status.in_(_ISSUE_STATUSES),
                )
            )
        ).scalars().all()
    )

    rows: list[dict] = []
    for r in releases:
        scope_changed = creep.get(r.id, 0) > 0 or r.id in scope_change_ids
        delayed = r.id in reschedule_ids or (
            r.target_date is not None and r.actual_date > r.target_date
        )
        rows.append({
            "release_id": r.id, "name": r.name, "shipped_at": r.actual_date,
            "scope_changed": scope_changed, "delayed": delayed,
            "had_issue": r.id in issue_ids,
        })

    changed = [x for x in rows if x["scope_changed"]]
    stable = [x for x in rows if not x["scope_changed"]]
    return {
        "date_from": date_from, "date_to": date_to,
        "scope_changed": _cohort(changed), "stable": _cohort(stable), "releases": rows,
    }
```

- [ ] **Step 5: Add the endpoint**

In `backend/app/api/v1/releases.py`, add the schema import near the other `from app.api.v1.schemas...` imports:
```python
from app.api.v1.schemas.scope_churn_analytics import ScopeChurnAnalyticsRead
```
Add this handler immediately AFTER the `get_releases_timeline` handler and BEFORE the `get_release` (`@router.get("/{release_id}", ...)`) handler — so the static path is not captured as an id:
```python
@router.get("/scope-churn-analytics", response_model=ScopeChurnAnalyticsRead)
async def get_scope_churn_analytics(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Correlate scope change with delays/issues across shipped project releases."""
    from app.services import scope_churn_service
    return await scope_churn_service.compute_scope_churn(
        db, current_user.active_tenant_id, date_from, date_to
    )
```

- [ ] **Step 6: Run tests to verify pass**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_scope_churn_analytics_api.py -v`
Expected: 2 passed.

- [ ] **Step 7: Regression**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/ -k "release or scope or deployment" -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/api/v1/schemas/scope_churn_analytics.py backend/app/services/scope_churn_service.py backend/app/api/v1/releases.py backend/tests/integration/test_scope_churn_analytics_api.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): scope-churn analytics endpoint"
```

---

## Task 2: Frontend — types + service

**Files:**
- Modify: `frontend/src/types/release.ts`
- Modify: `frontend/src/services/releaseService.ts`

- [ ] **Step 1: Add the types**

In `frontend/src/types/release.ts`, add:
```typescript
export interface ChurnCohortResponse {
  count: number;
  delayed_count: number;
  delayed_pct: number;
  issue_count: number;
  issue_pct: number;
}

export interface ChurnReleaseRowResponse {
  release_id: number;
  name: string;
  shipped_at: string;
  scope_changed: boolean;
  delayed: boolean;
  had_issue: boolean;
}

export interface ScopeChurnAnalyticsResponse {
  date_from: string | null;
  date_to: string | null;
  scope_changed: ChurnCohortResponse;
  stable: ChurnCohortResponse;
  releases: ChurnReleaseRowResponse[];
}
```

- [ ] **Step 2: Add the service method**

In `frontend/src/services/releaseService.ts`:
- Add `ScopeChurnAnalyticsResponse,` to the `from '../types/release'` import block.
- Add (after `getEnvironmentCoverage`, or with the other list-level GETs):
```typescript
  getScopeChurnAnalytics: (
    params: { date_from?: string; date_to?: string } = {}
  ): Promise<ScopeChurnAnalyticsResponse> =>
    api.get('/releases/scope-churn-analytics', { params }).then((r) => r.data),
```

- [ ] **Step 3: Typecheck**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/types/release.ts frontend/src/services/releaseService.ts
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): scope-churn analytics types + service"
```

---

## Task 3: Frontend — Release Analytics page + route + nav

**Files:**
- Create: `frontend/src/pages/releases/ReleaseAnalytics.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/navConfig.tsx`

- [ ] **Step 1: Create the page**

Create `frontend/src/pages/releases/ReleaseAnalytics.tsx`:

```tsx
/**
 * ReleaseAnalytics — does changing a release's scope correlate with delays/issues?
 * Descriptive correlation over shipped project releases in a date window.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Card, CardContent, Chip, Grid, TextField, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import { releaseService } from '../../services/releaseService';
import type {
  ScopeChurnAnalyticsResponse,
  ChurnCohortResponse,
  ChurnReleaseRowResponse,
} from '../../types/release';

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function CohortCard({ title, cohort }: { title: string; cohort: ChurnCohortResponse }) {
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="subtitle1" fontWeight="medium">
          {title} ({cohort.count})
        </Typography>
        <Typography variant="h4" sx={{ mt: 1 }}>
          {cohort.delayed_pct}%
        </Typography>
        <Typography variant="body2" color="text.secondary">
          delayed ({cohort.delayed_count}/{cohort.count})
        </Typography>
        <Typography variant="h4" sx={{ mt: 1 }}>
          {cohort.issue_pct}%
        </Typography>
        <Typography variant="body2" color="text.secondary">
          had an issue ({cohort.issue_count}/{cohort.count})
        </Typography>
      </CardContent>
    </Card>
  );
}

export default function ReleaseAnalytics() {
  const navigate = useNavigate();
  const [from, setFrom] = useState(() => isoDate(new Date(Date.now() - 90 * 864e5)));
  const [to, setTo] = useState(() => isoDate(new Date()));
  const [data, setData] = useState<ScopeChurnAnalyticsResponse | null>(null);

  useEffect(() => {
    releaseService
      .getScopeChurnAnalytics({
        date_from: from ? new Date(`${from}T00:00:00Z`).toISOString() : undefined,
        date_to: to ? new Date(`${to}T23:59:59Z`).toISOString() : undefined,
      })
      .then(setData)
      .catch(() => setData(null));
  }, [from, to]);

  const columns = useMemo<GridColDef<ChurnReleaseRowResponse>[]>(
    () => [
      { field: 'name', headerName: 'Release', flex: 1, minWidth: 180 },
      {
        field: 'shipped_at',
        headerName: 'Shipped',
        width: 130,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'scope_changed',
        headerName: 'Scope changed',
        width: 140,
        renderCell: (params) =>
          params.row.scope_changed ? <Chip label="Yes" color="warning" size="small" /> : <span>—</span>,
      },
      {
        field: 'delayed',
        headerName: 'Delayed',
        width: 110,
        renderCell: (params) =>
          params.row.delayed ? <Chip label="Yes" color="error" size="small" /> : <span>—</span>,
      },
      {
        field: 'had_issue',
        headerName: 'Issue',
        width: 110,
        renderCell: (params) =>
          params.row.had_issue ? <Chip label="Yes" color="error" size="small" /> : <span>—</span>,
      },
    ],
    []
  );

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Release Analytics
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Descriptive correlation between scope change and delays / issues across shipped project
        releases in the selected window — not a causal claim.
      </Typography>

      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
        <TextField
          label="From" type="date" size="small" value={from}
          onChange={(e) => setFrom(e.target.value)} InputLabelProps={{ shrink: true }}
        />
        <TextField
          label="To" type="date" size="small" value={to}
          onChange={(e) => setTo(e.target.value)} InputLabelProps={{ shrink: true }}
        />
      </Box>

      {data && (
        <>
          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid item xs={12} sm={6}>
              <CohortCard title="Scope changed" cohort={data.scope_changed} />
            </Grid>
            <Grid item xs={12} sm={6}>
              <CohortCard title="Stable scope" cohort={data.stable} />
            </Grid>
          </Grid>

          <Box sx={{ height: 480, width: '100%' }}>
            <DataTable<ChurnReleaseRowResponse>
              storageKey="release-analytics"
              rows={data.releases}
              columns={columns}
              getRowId={(row) => row.release_id}
              emptyMessage="No shipped releases in this window"
              onRowClick={(params) => navigate(`/releases/${params.row.release_id}`)}
            />
          </Box>
        </>
      )}
    </Box>
  );
}
```

Note: confirm `DataTable`'s props against `ScopeWindowsTable.tsx` / `ReleaseList.tsx` usage — especially whether a `getRowId` prop is supported (the rows use `release_id`, not `id`). If `DataTable` derives the id from a fixed `id` field and has no `getRowId` passthrough, either map the rows to include an `id` (`data.releases.map(r => ({ ...r, id: r.release_id }))`) or add the row-id handling the same way other DataTable callers do. Also confirm MUI `Grid` is the version in use (if the project is on MUI v6 `Grid2`, mirror how other pages lay out cards). Fix minimally to match the codebase.

- [ ] **Step 2: Add the route (before `/releases/:id`)**

In `frontend/src/App.tsx`, add the import with the other release pages:
```tsx
import ReleaseAnalytics from './pages/releases/ReleaseAnalytics';
```
Add the route immediately BEFORE `<Route path="/releases/:id" ... />`:
```tsx
          <Route path="/releases/analytics" element={<ReleaseAnalytics />} />
```

- [ ] **Step 3: Add the nav entry**

In `frontend/src/components/navConfig.tsx`, in the *Release Management* group's `children`, add after the Scope Windows entry (import an icon at the top, matching the existing icon-import style):
```tsx
import InsightsIcon from '@mui/icons-material/Insights';
```
```tsx
      { label: 'Releases — Analytics', path: '/releases/analytics', icon: <InsightsIcon /> },
```

- [ ] **Step 4: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean. Fix any `DataTable`/`Grid`/row-id mismatch flagged by tsc, minimally, to match the codebase.

- [ ] **Step 5: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/pages/releases/ReleaseAnalytics.tsx frontend/src/App.tsx frontend/src/components/navConfig.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): Release Analytics page (scope-churn correlation)"
```

---

## Task 4: Full regression + wrap-up

- [ ] **Step 1: Full backend suite**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest -q`
Expected: all pass.

- [ ] **Step 2: Frontend typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Manual smoke (optional, via /run or dev servers)**

Release Management → **Releases — Analytics** → pick a window covering some shipped releases → two cohort cards show % delayed / % had-issue for scope-changed vs stable releases; the table lists each release with Yes/— chips; row-click opens the release.

---

## Self-Review Notes (spec coverage)

- Cohort = shipped project releases in a window (actual_date not null, kind project, date filter): Task 1 service + tests. ✅
- `scope_changed` = creep>0 OR Scope Change event; `delayed` = reschedule event OR actual>target; `had_issue` = failed/rolled_back deploy: Task 1 + tests (all three flags; fallback; exclusions; percentages; empty). ✅
- Endpoint before `/{release_id}`: Task 1 Step 5. ✅
- Two cohort cards + drill-down table + date filter + honest caption: Task 3. ✅
- Route + nav: Task 3. ✅
- Types + service: Task 2. ✅
- Project-only; tenant-scoped (all queries filter tenant_id; another tenant's release excluded by the cohort query). ✅
- Out-of-scope (trends, breakdowns, significance, exports, DORA) not built. ✅
- Type consistency: `ScopeChurnAnalyticsResponse`/`ChurnCohortResponse`/`ChurnReleaseRowResponse` ↔ backend `ScopeChurnAnalyticsRead`/`ChurnCohort`/`ChurnReleaseRow` (count/delayed_count/delayed_pct/issue_count/issue_pct; release_id/name/shipped_at/scope_changed/delayed/had_issue); `getScopeChurnAnalytics` path matches the endpoint. ✅
```
