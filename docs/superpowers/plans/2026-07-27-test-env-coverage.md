# Test Environment Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a release's Environments tab, show which test environments host the systems the release must test (Changing + Regression), flag systems no environment hosts, suggest a covering set, and let the RM book via the existing dialog (pre-selected environment).

**Architecture:** A read-only `GET /releases/{id}/environment-coverage` endpoint joins `ReleaseSystem` (changing/regression) → `System` → `EnvironmentSystem` → `Environment` to return needed systems, candidate environments with their covered-system subsets, and uncovered systems. The frontend renders a coverage matrix + gap banner + greedy suggested set, and the Book button opens the existing `AddPhaseBookingDialog` with an environment pre-selected (one new optional prop). No new booking logic; no migration.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, PostgreSQL (SQLite for tests), React 18 + TypeScript + MUI.

**Spec:** `docs/superpowers/specs/2026-07-27-test-env-coverage-design.md`

**Conventions (verified in-repo):**
- Services never `db.commit()`; use `db.flush()`. No frontend unit tests — verify `tsc --noEmit` + `npm run build`.
- Full backend suite is the checkpoint: `cd backend && PYTHONPATH=. uv run pytest -q`.
- Use `git -C /Users/peter/Developer/Code/projects/envmgr` for git (cwd persists across commands).
- `EnvironmentStatus(str, enum.Enum)` in `backend/app/db/models/environment.py`: `active/inactive/maintenance/decommissioned`, column is `SAEnum(EnvironmentStatus, native_enum=False)` — reads return the enum member, so serialize `.value`.
- `EnvironmentSystem(environment_id, system_id, tenant_id)`; `Environment(name, environment_type, status, tenant_id, deleted_at)`; `ReleaseSystem(release_id, system_id, role, tenant_id)`; `System(id, name, tenant_id, deleted_at)`.
- `ReleaseEnvironmentsTab.tsx` renders the Gantt + bookings + `AddPhaseBookingDialog` (props `{ open, onClose, releaseId, phases, onCreated }`). The dialog's environment `<TextField select>` is bound to `envId` state sourced from `s.environment.environments`.
- Shared role map at `frontend/src/utils/releaseSystemRoles.ts` (`RELEASE_SYSTEM_ROLE_LABELS`, `RELEASE_SYSTEM_ROLE_COLORS`).

---

## Task 1: Backend — coverage endpoint + schemas + tests

**Files:**
- Create: `backend/app/api/v1/schemas/release_env_coverage.py`
- Modify: `backend/app/api/v1/releases.py`
- Test: `backend/tests/integration/test_release_env_coverage_api.py`

- [ ] **Step 1: Write the failing API test**

Create `backend/tests/integration/test_release_env_coverage_api.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.system import System
from app.db.models.environment import Environment, EnvironmentSystem, EnvironmentStatus


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


async def _make_release(authed_client, release_lifecycle_template) -> int:
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Rel", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_system(db_session, tenant_id, name) -> int:
    s = System(tenant_id=tenant_id, name=name)
    db_session.add(s)
    await db_session.flush()
    return s.id


async def _make_env(db_session, tenant_id, name, status=EnvironmentStatus.ACTIVE) -> int:
    e = Environment(tenant_id=tenant_id, name=name, environment_type="sit", status=status)
    db_session.add(e)
    await db_session.flush()
    return e.id


async def _host(db_session, tenant_id, env_id, system_id):
    db_session.add(EnvironmentSystem(tenant_id=tenant_id, environment_id=env_id, system_id=system_id))
    await db_session.flush()


async def _link(authed_client, rid, sid, role):
    resp = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": role})
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_coverage_matrix(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    pay = await _make_system(db_session, tenant.id, "Payments")
    ident = await _make_system(db_session, tenant.id, "Identity")
    ledger = await _make_system(db_session, tenant.id, "Ledger")
    monitor = await _make_system(db_session, tenant.id, "Monitoring")

    # roles: pay=changing, identity=regression, ledger=changing, monitor=config_only (excluded)
    await _link(authed_client, rid, pay, "changing")
    await _link(authed_client, rid, ident, "regression")
    await _link(authed_client, rid, ledger, "changing")
    await _link(authed_client, rid, monitor, "config_only")

    env_a = await _make_env(db_session, tenant.id, "SIT-A")
    env_b = await _make_env(db_session, tenant.id, "SIT-B")
    env_c = await _make_env(db_session, tenant.id, "OLD", status=EnvironmentStatus.DECOMMISSIONED)
    await _host(db_session, tenant.id, env_a, pay)
    await _host(db_session, tenant.id, env_a, ident)
    await _host(db_session, tenant.id, env_b, ident)
    await _host(db_session, tenant.id, env_c, ledger)  # only hosted by decommissioned env
    await _host(db_session, tenant.id, env_a, monitor)  # config_only, not a needed system

    resp = await authed_client.get(f"/api/v1/releases/{rid}/environment-coverage")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    needed_names = sorted(s["system_name"] for s in body["needed_systems"])
    assert needed_names == ["Identity", "Ledger", "Payments"]  # Monitoring excluded

    envs = {e["name"]: set(e["covered_system_ids"]) for e in body["environments"]}
    assert set(envs.keys()) == {"SIT-A", "SIT-B"}  # decommissioned OLD excluded
    assert envs["SIT-A"] == {pay, ident}
    assert envs["SIT-B"] == {ident}

    assert body["uncovered_system_ids"] == [ledger]  # only in decommissioned env


@pytest.mark.asyncio
async def test_coverage_empty_when_no_testable_systems(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id, "OnlyConfig")
    await _link(authed_client, rid, sid, "config_only")
    resp = await authed_client.get(f"/api/v1/releases/{rid}/environment-coverage")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"needed_systems": [], "environments": [], "uncovered_system_ids": []}


@pytest.mark.asyncio
async def test_coverage_cross_tenant_release_404(authed_client, tenant, db_session, release_lifecycle_template, second_tenant_factory):
    other_tenant, _ = await second_tenant_factory()
    # A release id that doesn't belong to the caller's tenant → 404.
    resp = await authed_client.get("/api/v1/releases/999999/environment-coverage")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_release_env_coverage_api.py -v`
Expected: FAIL — endpoint not defined (404 for the coverage path, or route missing).

- [ ] **Step 3: Create the coverage schemas**

Create `backend/app/api/v1/schemas/release_env_coverage.py`:

```python
from pydantic import BaseModel


class CoverageSystem(BaseModel):
    system_id: int
    system_name: str
    role: str  # 'changing' | 'regression'


class CoverageEnvironment(BaseModel):
    environment_id: int
    name: str
    environment_type: str
    status: str
    covered_system_ids: list[int]


class ReleaseEnvironmentCoverageRead(BaseModel):
    needed_systems: list[CoverageSystem]
    environments: list[CoverageEnvironment]
    uncovered_system_ids: list[int]
```

- [ ] **Step 4: Add the endpoint**

In `backend/app/api/v1/releases.py`, add the schema import near the other `from app.api.v1.schemas...` imports at the top:
```python
from app.api.v1.schemas.release_env_coverage import (
    ReleaseEnvironmentCoverageRead,
    CoverageSystem,
    CoverageEnvironment,
)
```

Add this handler alongside the other `@router.get("/{release_id}/...")` sub-resource handlers (e.g. right after the `list_release_systems` handler):
```python
@router.get("/{release_id}/environment-coverage", response_model=ReleaseEnvironmentCoverageRead)
async def get_environment_coverage(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Which environments host the systems this release must test (Changing +
    Regression), plus the systems no active environment hosts."""
    from app.db.models.release_system import ReleaseSystem
    from app.db.models.system import System
    from app.db.models.environment import Environment, EnvironmentSystem, EnvironmentStatus

    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)

    needed_rows = (
        await db.execute(
            select(ReleaseSystem.system_id, System.name, ReleaseSystem.role)
            .join(System, System.id == ReleaseSystem.system_id)
            .where(
                ReleaseSystem.release_id == release_id,
                ReleaseSystem.tenant_id == tenant_id,
                ReleaseSystem.role.in_(["changing", "regression"]),
                System.deleted_at.is_(None),
            )
            .order_by(System.name)
        )
    ).all()
    needed_systems = [
        CoverageSystem(system_id=sid, system_name=name, role=role)
        for sid, name, role in needed_rows
    ]
    needed_ids = [s.system_id for s in needed_systems]
    if not needed_ids:
        return ReleaseEnvironmentCoverageRead(
            needed_systems=[], environments=[], uncovered_system_ids=[]
        )

    es_rows = (
        await db.execute(
            select(
                EnvironmentSystem.environment_id,
                EnvironmentSystem.system_id,
                Environment.name,
                Environment.environment_type,
                Environment.status,
            )
            .join(Environment, Environment.id == EnvironmentSystem.environment_id)
            .where(
                EnvironmentSystem.system_id.in_(needed_ids),
                EnvironmentSystem.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
                Environment.status != EnvironmentStatus.DECOMMISSIONED,
            )
            .order_by(Environment.name)
        )
    ).all()

    env_map: dict[int, CoverageEnvironment] = {}
    covered: set[int] = set()
    for env_id, sys_id, name, etype, estatus in es_rows:
        ce = env_map.get(env_id)
        if ce is None:
            ce = CoverageEnvironment(
                environment_id=env_id,
                name=name,
                environment_type=etype,
                status=getattr(estatus, "value", str(estatus)),
                covered_system_ids=[],
            )
            env_map[env_id] = ce
        ce.covered_system_ids.append(sys_id)
        covered.add(sys_id)

    uncovered = [sid for sid in needed_ids if sid not in covered]
    return ReleaseEnvironmentCoverageRead(
        needed_systems=needed_systems,
        environments=list(env_map.values()),
        uncovered_system_ids=uncovered,
    )
```

`select`, `Depends`, `get_db`, `get_current_user`, `AsyncSession`, `_require_release` are all already available in `releases.py`.

- [ ] **Step 5: Run tests to verify pass**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_release_env_coverage_api.py -v`
Expected: 3 passed.

- [ ] **Step 6: Regression**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/ -k "release or environment or scope or system" -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/api/v1/schemas/release_env_coverage.py backend/app/api/v1/releases.py backend/tests/integration/test_release_env_coverage_api.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): environment-coverage endpoint (systems needing test vs hosting envs)"
```

---

## Task 2: Frontend — coverage types + service method

**Files:**
- Modify: `frontend/src/types/release.ts`
- Modify: `frontend/src/services/releaseService.ts`

- [ ] **Step 1: Add the coverage types**

In `frontend/src/types/release.ts`, add (near the other release response types):
```typescript
export interface CoverageSystemResponse {
  system_id: number;
  system_name: string;
  role: 'changing' | 'regression';
}

export interface CoverageEnvironmentResponse {
  environment_id: number;
  name: string;
  environment_type: string;
  status: string;
  covered_system_ids: number[];
}

export interface ReleaseEnvironmentCoverageResponse {
  needed_systems: CoverageSystemResponse[];
  environments: CoverageEnvironmentResponse[];
  uncovered_system_ids: number[];
}
```

- [ ] **Step 2: Add the service method**

In `frontend/src/services/releaseService.ts`, add the import to the existing `from '../types/release'` block:
```typescript
  ReleaseEnvironmentCoverageResponse,
```
And add a method (e.g. after `listBookings`):
```typescript
  getEnvironmentCoverage: (releaseId: number): Promise<ReleaseEnvironmentCoverageResponse> =>
    api.get(`/releases/${releaseId}/environment-coverage`).then((r) => r.data),
```

- [ ] **Step 3: Typecheck**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/types/release.ts frontend/src/services/releaseService.ts
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): coverage types + getEnvironmentCoverage service"
```

---

## Task 3: Frontend — `ReleaseEnvironmentCoverage` component

**Files:**
- Create: `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx`:

```tsx
/**
 * ReleaseEnvironmentCoverage — which environments host the systems this release
 * must test (Changing + Regression), with gaps and a suggested covering set.
 * Read-only insight; the Book button reuses the existing booking dialog.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Box, Button, Chip, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import { releaseService } from '../../services/releaseService';
import type { ReleaseEnvironmentCoverageResponse } from '../../types/release';
import {
  RELEASE_SYSTEM_ROLE_LABELS,
  RELEASE_SYSTEM_ROLE_COLORS,
  type ReleaseSystemRole,
} from '../../utils/releaseSystemRoles';

interface Props {
  releaseId: number;
  onBook: (environmentId: number) => void;
}

/** Greedy set-cover: fewest environments covering all coverable system ids. */
function greedyCover(
  environments: ReleaseEnvironmentCoverageResponse['environments'],
  coverable: Set<number>,
): ReleaseEnvironmentCoverageResponse['environments'] {
  const remaining = new Set(coverable);
  const chosen: ReleaseEnvironmentCoverageResponse['environments'] = [];
  while (remaining.size > 0) {
    let best: (typeof environments)[number] | null = null;
    let bestCount = 0;
    for (const e of environments) {
      const count = e.covered_system_ids.filter((id) => remaining.has(id)).length;
      if (count > bestCount) {
        bestCount = count;
        best = e;
      }
    }
    if (!best || bestCount === 0) break;
    chosen.push(best);
    best.covered_system_ids.forEach((id) => remaining.delete(id));
  }
  return chosen;
}

export default function ReleaseEnvironmentCoverage({ releaseId, onBook }: Props) {
  const [data, setData] = useState<ReleaseEnvironmentCoverageResponse | null>(null);

  useEffect(() => {
    releaseService.getEnvironmentCoverage(releaseId).then(setData).catch(() => setData(null));
  }, [releaseId]);

  const nameById = useMemo(() => {
    const m = new Map<number, string>();
    data?.needed_systems.forEach((s) => m.set(s.system_id, s.system_name));
    return m;
  }, [data]);

  const suggestion = useMemo(() => {
    if (!data) return [];
    const uncovered = new Set(data.uncovered_system_ids);
    const coverable = new Set(
      data.needed_systems.map((s) => s.system_id).filter((id) => !uncovered.has(id)),
    );
    return greedyCover(data.environments, coverable).map((e) => e.name);
  }, [data]);

  if (!data) return null;

  if (data.needed_systems.length === 0) {
    return (
      <Alert severity="info" variant="outlined">
        Add Changing or Regression systems on the Systems tab to plan test environments.
      </Alert>
    );
  }

  const uncoveredSet = new Set(data.uncovered_system_ids);

  return (
    <Box>
      <Typography variant="subtitle1" fontWeight="medium" sx={{ mb: 1 }}>
        Test Environment Coverage
      </Typography>

      {data.uncovered_system_ids.length > 0 && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {data.uncovered_system_ids.length} system(s) need testing but no environment hosts them:{' '}
          {data.uncovered_system_ids.map((id) => nameById.get(id) ?? `#${id}`).join(', ')}
        </Alert>
      )}

      {suggestion.length > 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Suggested: booking <strong>{suggestion.join(' + ')}</strong> covers all testable systems.
        </Typography>
      )}

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>System</TableCell>
            {data.environments.map((e) => (
              <TableCell key={e.environment_id} align="center">
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5 }}>
                  <span>{e.name} ({e.covered_system_ids.length}/{data.needed_systems.length})</span>
                  <Button size="small" variant="outlined" onClick={() => onBook(e.environment_id)}>
                    Book
                  </Button>
                </Box>
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {data.needed_systems.map((s) => {
            const isGap = uncoveredSet.has(s.system_id);
            return (
              <TableRow key={s.system_id} sx={isGap ? { bgcolor: 'warning.light' } : undefined}>
                <TableCell>
                  {s.system_name}{' '}
                  <Chip
                    size="small"
                    label={RELEASE_SYSTEM_ROLE_LABELS[s.role as ReleaseSystemRole]}
                    color={RELEASE_SYSTEM_ROLE_COLORS[s.role as ReleaseSystemRole]}
                    sx={{ ml: 0.5 }}
                  />
                  {isGap && (
                    <Typography component="span" variant="caption" color="warning.dark" sx={{ ml: 1 }}>
                      no environment
                    </Typography>
                  )}
                </TableCell>
                {data.environments.map((e) => (
                  <TableCell key={e.environment_id} align="center">
                    {e.covered_system_ids.includes(s.system_id) ? (
                      <CheckIcon fontSize="small" color="success" />
                    ) : (
                      ''
                    )}
                  </TableCell>
                ))}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Box>
  );
}
```

- [ ] **Step 2: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): ReleaseEnvironmentCoverage matrix component"
```

---

## Task 4: Frontend — wire coverage into the Environments tab + pre-select booking env

**Files:**
- Modify: `frontend/src/components/releases/ReleaseEnvironmentsTab.tsx`
- Modify: `frontend/src/components/releases/AddPhaseBookingDialog.tsx`

- [ ] **Step 1: `AddPhaseBookingDialog` — optional `initialEnvironmentId`**

In `frontend/src/components/releases/AddPhaseBookingDialog.tsx`:

Add `initialEnvironmentId?: number;` to the `Props` interface, and destructure it in the component signature:
```tsx
export default function AddPhaseBookingDialog({
  open,
  onClose,
  releaseId,
  phases,
  onCreated,
  initialEnvironmentId,
}: Props) {
```
Add an effect (after the existing mount effect) that pre-selects the environment when the dialog opens:
```tsx
  useEffect(() => {
    if (open && initialEnvironmentId != null) {
      setEnvId(initialEnvironmentId);
    }
  }, [open, initialEnvironmentId]);
```
(The existing `resetForm()` on close still clears it, so the next manual "Add Booking" starts blank.)

- [ ] **Step 2: `ReleaseEnvironmentsTab` — render coverage on top + book callback**

In `frontend/src/components/releases/ReleaseEnvironmentsTab.tsx`:

Add the import:
```tsx
import ReleaseEnvironmentCoverage from './ReleaseEnvironmentCoverage';
```
Add state next to the existing `addOpen`:
```tsx
  const [bookEnvId, setBookEnvId] = useState<number | undefined>(undefined);
```
Render the coverage section + a divider at the TOP of the returned `<Box>` (before the "Environment Timeline" block):
```tsx
      <ReleaseEnvironmentCoverage
        releaseId={releaseId}
        onBook={(environmentId) => {
          setBookEnvId(environmentId);
          setAddOpen(true);
        }}
      />

      <Divider />
```
Change the existing "Add Booking" button's onClick to clear the pre-selection:
```tsx
            onClick={() => {
              setBookEnvId(undefined);
              setAddOpen(true);
            }}
```
Pass the pre-selected env to the dialog:
```tsx
      <AddPhaseBookingDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        releaseId={releaseId}
        phases={phases}
        onCreated={loadBookings}
        initialEnvironmentId={bookEnvId}
      />
```

- [ ] **Step 3: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/components/releases/ReleaseEnvironmentsTab.tsx frontend/src/components/releases/AddPhaseBookingDialog.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): coverage section on Environments tab + pre-selected booking env"
```

---

## Task 5: Full regression + wrap-up

- [ ] **Step 1: Full backend suite**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest -q`
Expected: all pass, no new failures.

- [ ] **Step 2: Frontend typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Manual smoke (optional, via /run or dev servers)**

On a release with Changing/Regression systems (Systems tab) that are hosted in some environments: open **Environments** tab → the Coverage matrix lists the systems × hosting environments, flags any system with no environment, and suggests a covering set. Click **Book** on an environment column → the Add Booking dialog opens with that environment pre-selected. A release with no Changing/Regression systems shows the "Add … on the Systems tab" hint.

---

## Self-Review Notes (spec coverage)

- Coverage endpoint (needed_systems by changing/regression, environments with covered subsets, uncovered): Task 1. ✅
- config_only excluded; decommissioned excluded; tenant-scoped; empty when no testable systems: Task 1 + tests. ✅
- Coverage matrix + gap banner + greedy suggested set + role chips: Task 3. ✅
- Book pre-selects env in the existing dialog (new `initialEnvironmentId` prop): Task 4. ✅
- Section placed on top of the Environments tab: Task 4. ✅
- Empty state pointing to the Systems tab: Task 3. ✅
- Types + service method: Task 2. ✅
- Out-of-scope (guided booking, mock-aware, per-phase) not implemented. ✅
- Type consistency: `ReleaseEnvironmentCoverageResponse` shape matches the backend `ReleaseEnvironmentCoverageRead` (needed_systems/environments/uncovered_system_ids; covered_system_ids: number[]); `getEnvironmentCoverage` path matches the endpoint; `initialEnvironmentId` prop name identical in Task 3's `onBook` wiring and Task 4's dialog. ✅
```
