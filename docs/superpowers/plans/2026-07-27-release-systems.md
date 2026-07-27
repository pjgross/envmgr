# Release Systems Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a release manager record the systems a release impacts (with a role: Changing / Regression / Config only) via a new "Systems" tab on the release detail, and filter the Releases list by impacted system.

**Architecture:** The `ReleaseSystem` model + endpoints already exist; the only backend change is hydrating the system **name** onto the read model and validating the `role` string. The frontend adds a self-contained local-state CRUD tab (`ReleaseSystemsTab`), a shared role label/color map, and a Systems column + client-side system filter on the Releases list. No migration.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, PostgreSQL (SQLite for tests), React 18 + TypeScript + MUI + MUI X DataGrid.

**Spec:** `docs/superpowers/specs/2026-07-27-release-systems-design.md`

**Conventions (verified in-repo):**
- Services never `db.commit()`; use `db.flush()`. No frontend unit tests — verify with `tsc --noEmit` + `npm run build`.
- Run the FULL backend suite as the checkpoint: `cd backend && PYTHONPATH=. uv run pytest -q` (covers `tests/services/` AND `tests/integration/`).
- Shell cwd persists across commands; use `git -C /Users/peter/Developer/Code/projects/envmgr` for git.
- Backend `ReleaseSystemRead` (`schemas/release_system.py`): `id, tenant_id, release_id, system_id, role, deployment_date` (ConfigDict from_attributes). `ReleaseSystemCreate`: `system_id, role, deployment_date`.
- Endpoints (`api/v1/releases.py`): `GET /releases/{id}/systems` (`list_release_systems`, returns `list(rows)` of ORM), `POST /releases/{id}/systems` (`add_release_system`, validates `System.tenant_id==tenant_id` → 400; `IntegrityError` → 409), `DELETE /release-systems/{rs_id}`.
- Frontend `releaseService.listSystems(releaseId)` / `addSystem(releaseId, data)` / `removeSystem(releaseSystemId)` exist and are currently unused. `systemService.listSystems()` → `SystemResponse[]`.
- `ReleaseSystemResponse` (`types/release.ts`) has `role: 'changing' | 'regression' | 'config_only'` already.

---

## Task 1: Backend — `system_name` hydration + `role` validation + API tests

**Files:**
- Modify: `backend/app/api/v1/schemas/release_system.py`
- Modify: `backend/app/api/v1/releases.py` (`list_release_systems`, `add_release_system`)
- Test: `backend/tests/integration/test_release_systems_api.py`

- [ ] **Step 1: Write the failing API test**

Create `backend/tests/integration/test_release_systems_api.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.system import System


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


async def _make_system(db_session, tenant_id, name="Core") -> int:
    s = System(tenant_id=tenant_id, name=name)
    db_session.add(s)
    await db_session.flush()
    return s.id


@pytest.mark.asyncio
async def test_add_and_list_release_system_hydrates_name(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id, "Payments")

    add = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={
        "system_id": sid, "role": "regression",
    })
    assert add.status_code == 201, add.text
    assert add.json()["system_name"] == "Payments"
    assert add.json()["role"] == "regression"

    lst = await authed_client.get(f"/api/v1/releases/{rid}/systems")
    assert lst.status_code == 200
    assert [row["system_name"] for row in lst.json()] == ["Payments"]


@pytest.mark.asyncio
async def test_duplicate_system_link_conflicts(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id)
    first = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": "changing"})
    assert first.status_code == 201
    dup = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": "changing"})
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_invalid_role_rejected(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    sid = await _make_system(db_session, tenant.id)
    bad = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": "wizard"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_foreign_system_rejected(authed_client, tenant, db_session, release_lifecycle_template, second_tenant_factory):
    rid = await _make_release(authed_client, release_lifecycle_template)
    other_tenant, _ = await second_tenant_factory()
    foreign_sid = await _make_system(db_session, other_tenant.id, "Foreign")
    resp = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": foreign_sid, "role": "changing"})
    assert resp.status_code == 400
```

Note: `second_tenant_factory` is a conftest fixture returning `(tenant, user)`. If its return shape differs, adjust the unpacking; the goal is a system in a different tenant.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_release_systems_api.py -v`
Expected: FAIL — `system_name` absent; invalid role currently stored (not 422).

- [ ] **Step 3: Schema — `system_name` + role validator**

Replace `backend/app/api/v1/schemas/release_system.py` contents with:

```python
# backend/app/api/v1/schemas/release_system.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator

_VALID_ROLES = {"changing", "regression", "config_only"}


class ReleaseSystemCreate(BaseModel):
    system_id: int
    role: str  # 'changing' | 'regression' | 'config_only'
    deployment_date: Optional[datetime] = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v):
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return v


class ReleaseSystemUpdate(BaseModel):
    role: Optional[str] = None
    deployment_date: Optional[datetime] = None


class ReleaseSystemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    system_id: int
    system_name: Optional[str] = None
    role: str
    deployment_date: Optional[datetime]
```

- [ ] **Step 4: Hydrate name in `list_release_systems`**

In `backend/app/api/v1/releases.py`, replace the body of `list_release_systems` (the `@router.get("/{release_id}/systems", ...)` handler) with:

```python
async def list_release_systems(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.db.models.release_system import ReleaseSystem
    from app.db.models.system import System
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows = (
        await db.execute(
            select(ReleaseSystem, System.name)
            .join(System, System.id == ReleaseSystem.system_id)
            .where(
                ReleaseSystem.release_id == release_id,
                ReleaseSystem.tenant_id == tenant_id,
            )
            .order_by(ReleaseSystem.id)
        )
    ).all()
    out: list[ReleaseSystemRead] = []
    for rs, name in rows:
        item = ReleaseSystemRead.model_validate(rs)
        item.system_name = name
        out.append(item)
    return out
```

(`ReleaseSystemRead` is already imported at the top of `releases.py`. Keep the `@router.get(... response_model=list[ReleaseSystemRead])` decorator unchanged.)

- [ ] **Step 5: Hydrate name in `add_release_system`**

In `add_release_system`, change the tenant-validation query to also fetch the name, and set it on the returned read model. Replace the validation block + return with:

```python
    system_row = (
        await db.execute(
            select(System.id, System.name).where(
                System.id == data.system_id,
                System.tenant_id == tenant_id,
                System.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if system_row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "system_id must refer to an active system in this tenant",
        )

    rs = ReleaseSystem(
        tenant_id=tenant_id,
        release_id=release_id,
        system_id=data.system_id,
        role=data.role,
        deployment_date=data.deployment_date,
    )
    db.add(rs)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "System already linked to this release",
        )
    item = ReleaseSystemRead.model_validate(rs)
    item.system_name = system_row.name
    return item
```

(This replaces the previous `system_ok = (... select(System.id) ...).scalar_one_or_none()` block and the `return rs`. The inline imports `ReleaseSystem`, `System`, `IntegrityError` at the top of the handler stay.)

- [ ] **Step 6: Run tests to verify pass**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_release_systems_api.py -v`
Expected: 4 passed.

- [ ] **Step 7: Regression**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/ -k "release or scope or system" -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/api/v1/schemas/release_system.py backend/app/api/v1/releases.py backend/tests/integration/test_release_systems_api.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): hydrate system_name + validate role on release-systems API"
```

---

## Task 2: Frontend — types + shared role label/color map

**Files:**
- Modify: `frontend/src/types/release.ts`
- Create: `frontend/src/utils/releaseSystemRoles.ts`

- [ ] **Step 1: Add `system_name` to the type**

In `frontend/src/types/release.ts`, in `ReleaseSystemResponse`, add after `system_id`:
```typescript
  system_name: string | null;
```
And change `ReleaseSystemCreatePayload.role` from `role: string;` to:
```typescript
  role: 'changing' | 'regression' | 'config_only';
```

- [ ] **Step 2: Create the shared role map**

Create `frontend/src/utils/releaseSystemRoles.ts`:
```typescript
export type ReleaseSystemRole = 'changing' | 'regression' | 'config_only';

export const RELEASE_SYSTEM_ROLE_LABELS: Record<ReleaseSystemRole, string> = {
  changing: 'Changing',
  regression: 'Regression (needs testing)',
  config_only: 'Config only',
};

export const RELEASE_SYSTEM_ROLE_COLORS: Record<
  ReleaseSystemRole,
  'primary' | 'warning' | 'default'
> = {
  changing: 'primary',
  regression: 'warning',
  config_only: 'default',
};

/** Fixed display/sort order for the three roles. */
export const RELEASE_SYSTEM_ROLE_ORDER: ReleaseSystemRole[] = [
  'changing',
  'regression',
  'config_only',
];
```

- [ ] **Step 3: Typecheck**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/types/release.ts frontend/src/utils/releaseSystemRoles.ts
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): system_name type + shared release-system role map"
```

---

## Task 3: Frontend — `ReleaseSystemsTab` component

**Files:**
- Create: `frontend/src/components/releases/ReleaseSystemsTab.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/releases/ReleaseSystemsTab.tsx`:

```tsx
/**
 * ReleaseSystemsTab — manage the systems a release impacts, by role.
 * Local-state CRUD (no Redux), mirroring the self-contained sub-resource tabs.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import { releaseService } from '../../services/releaseService';
import { systemService } from '../../services/systemService';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import type { ReleaseSystemResponse } from '../../types/release';
import type { SystemResponse } from '../../types/system';
import {
  RELEASE_SYSTEM_ROLE_LABELS,
  RELEASE_SYSTEM_ROLE_COLORS,
  RELEASE_SYSTEM_ROLE_ORDER,
  type ReleaseSystemRole,
} from '../../utils/releaseSystemRoles';

interface Props {
  releaseId: number;
}

function extractError(err: unknown, fallback: string): string {
  const axiosErr = err as { response?: { data?: { detail?: unknown } } };
  const detail = axiosErr?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function ReleaseSystemsTab({ releaseId }: Props) {
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  const [rows, setRows] = useState<ReleaseSystemResponse[]>([]);
  const [allSystems, setAllSystems] = useState<SystemResponse[]>([]);
  const [loading, setLoading] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [systemId, setSystemId] = useState<number | ''>('');
  const [role, setRole] = useState<ReleaseSystemRole>('changing');
  const [deploymentDate, setDeploymentDate] = useState('');

  const load = () => {
    setLoading(true);
    releaseService
      .listSystems(releaseId)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    systemService.listSystems().then(setAllSystems).catch(() => setAllSystems([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [releaseId]);

  // Systems not already linked, for the add dropdown.
  const availableSystems = useMemo(() => {
    const linked = new Set(rows.map((r) => r.system_id));
    return allSystems.filter((s) => !linked.has(s.id));
  }, [rows, allSystems]);

  // Group + order by role for the table.
  const orderedRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const ra = RELEASE_SYSTEM_ROLE_ORDER.indexOf(a.role);
      const rb = RELEASE_SYSTEM_ROLE_ORDER.indexOf(b.role);
      if (ra !== rb) return ra - rb;
      return (a.system_name ?? '').localeCompare(b.system_name ?? '');
    });
  }, [rows]);

  const openAdd = () => {
    setSystemId('');
    setRole('changing');
    setDeploymentDate('');
    setAddOpen(true);
  };

  const handleAdd = async () => {
    if (systemId === '') return;
    try {
      await releaseService.addSystem(releaseId, {
        system_id: Number(systemId),
        role,
        deployment_date: deploymentDate ? new Date(`${deploymentDate}T00:00:00Z`).toISOString() : null,
      });
      snackbar.success('System added');
      setAddOpen(false);
      load();
    } catch (err) {
      snackbar.error(extractError(err, 'Failed to add system'));
    }
  };

  const handleRemove = async (row: ReleaseSystemResponse) => {
    if (!(await confirm({ message: `Remove ${row.system_name ?? 'system'} from this release?`, destructive: true }))) return;
    try {
      await releaseService.removeSystem(row.id);
      snackbar.success('System removed');
      load();
    } catch (err) {
      snackbar.error(extractError(err, 'Failed to remove system'));
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle1">Impacted Systems ({rows.length})</Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={openAdd} disabled={availableSystems.length === 0}>
          Add System
        </Button>
      </Box>

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>System</TableCell>
            <TableCell>Role</TableCell>
            <TableCell>Deployment date</TableCell>
            <TableCell align="right" />
          </TableRow>
        </TableHead>
        <TableBody>
          {orderedRows.length === 0 && !loading && (
            <TableRow>
              <TableCell colSpan={4}>
                <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
                  No systems linked yet.
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {orderedRows.map((row) => (
            <TableRow key={row.id}>
              <TableCell>{row.system_name ?? `#${row.system_id}`}</TableCell>
              <TableCell>
                <Chip
                  size="small"
                  label={RELEASE_SYSTEM_ROLE_LABELS[row.role]}
                  color={RELEASE_SYSTEM_ROLE_COLORS[row.role]}
                />
              </TableCell>
              <TableCell>
                {row.deployment_date ? new Date(row.deployment_date).toLocaleDateString() : '—'}
              </TableCell>
              <TableCell align="right">
                <IconButton size="small" color="error" onClick={() => handleRemove(row)} aria-label="remove system">
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Add impacted system</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              select label="System" fullWidth value={systemId}
              onChange={(e) => setSystemId(e.target.value === '' ? '' : Number(e.target.value))}
            >
              {availableSystems.map((s) => (
                <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
              ))}
            </TextField>
            <TextField
              select label="Role" fullWidth value={role}
              onChange={(e) => setRole(e.target.value as ReleaseSystemRole)}
            >
              {RELEASE_SYSTEM_ROLE_ORDER.map((r) => (
                <MenuItem key={r} value={r}>{RELEASE_SYSTEM_ROLE_LABELS[r]}</MenuItem>
              ))}
            </TextField>
            <TextField
              label="Deployment date (optional)" type="date" fullWidth
              value={deploymentDate} onChange={(e) => setDeploymentDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleAdd} disabled={systemId === ''}>Add</Button>
        </DialogActions>
      </Dialog>

      {confirmDialog}
    </Box>
  );
}
```

Before finalising, confirm the `useConfirm`/`useSnackbar` hook APIs match usage elsewhere (e.g. `GatesTable.tsx` uses `const { confirm, dialog: confirmDialog } = useConfirm();` and `confirm({ message, destructive })`; `useSnackbar` exposes `.success`/`.error`). Adjust minimally if the signatures differ.

- [ ] **Step 2: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/components/releases/ReleaseSystemsTab.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): ReleaseSystemsTab (manage impacted systems by role)"
```

---

## Task 4: Frontend — wire the Systems tab into ReleaseDetail

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseDetail.tsx`

- [ ] **Step 1: Import + tab + renumber**

In `frontend/src/pages/releases/ReleaseDetail.tsx`:

Add the import near the other tab imports:
```tsx
import ReleaseSystemsTab from '../../components/releases/ReleaseSystemsTab';
```

Add a `<Tab label="Systems" />` between the Environments and Linked Requests tabs, so the strip reads:
```tsx
          <Tab label="Main" />
          <Tab label="Gates & Test Phases" />
          <Tab label="Environments" />
          <Tab label="Systems" />
          <Tab label="Linked Requests" />
          <Tab label="Scope" />
          <Tab label="RAID" />
          <Tab label="Enterprise" />
          <Tab label="Deployments" />
```

Replace the tab-content block with the renumbered mapping (Systems=3; everything after shifts by one):
```tsx
      {activeTab === 0 && <ReleaseMainTab releaseId={releaseId} />}
      {activeTab === 1 && <ReleasePlanTab releaseId={releaseId} />}
      {activeTab === 2 && <ReleaseEnvironmentsTab releaseId={releaseId} />}
      {activeTab === 3 && <ReleaseSystemsTab releaseId={releaseId} />}
      {activeTab === 4 && <ReleaseLinkedRequestsTab releaseId={releaseId} />}
      {activeTab === 5 && <ReleaseScopeTab releaseId={releaseId} />}
      {activeTab === 6 && <RaidTab releaseId={releaseId} />}
      {activeTab === 7 && <EnterpriseMembershipTab releaseId={releaseId} />}
      {activeTab === 8 && <ReleaseDeploymentsTab releaseId={releaseId} />}
```

Optionally update the file's top doc comment tab list to include Systems (cosmetic).

- [ ] **Step 2: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/pages/releases/ReleaseDetail.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): add Systems tab to release detail"
```

---

## Task 5: Frontend — Releases list Systems column + system filter

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseList.tsx`

- [ ] **Step 1: Add systems fetch + filter state**

In `frontend/src/pages/releases/ReleaseList.tsx`:

Add imports:
```tsx
import { systemService } from '../../services/systemService';
import type { SystemResponse } from '../../types/system';
import { RELEASE_SYSTEM_ROLE_LABELS } from '../../utils/releaseSystemRoles';
```

Add state near the other filter state (`statusFilter`, `typeFilter`, `kindFilter`):
```tsx
  const [systemFilter, setSystemFilter] = useState<string>('all');
  const [systems, setSystems] = useState<SystemResponse[]>([]);
```

Fetch systems for the dropdown — add to the existing mount effect (or a new one):
```tsx
  useEffect(() => {
    systemService.listSystems().then(setSystems).catch(() => setSystems([]));
  }, []);
```

- [ ] **Step 2: Apply the filter client-side**

In the `filteredRows` useMemo, add a system predicate and include `systemFilter` in the deps:
```tsx
  const filteredRows = useMemo(
    () =>
      list.filter((r) => {
        if (statusFilter !== 'all' && r.status !== statusFilter) return false;
        if (typeFilter !== 'all' && r.release_type !== typeFilter) return false;
        if (kindFilter !== 'all' && r.release_kind !== kindFilter) return false;
        if (systemFilter !== 'all' && !r.systems.some((s) => s.id === Number(systemFilter))) return false;
        return true;
      }),
    [list, statusFilter, typeFilter, kindFilter, systemFilter]
  );
```

- [ ] **Step 3: Add the system filter dropdown**

In the filter toolbar `<Box>` (where the Status/Type/Kind controls are), add:
```tsx
            <TextField
              select
              label="System"
              size="small"
              value={systemFilter}
              onChange={(e) => setSystemFilter(e.target.value)}
              sx={{ minWidth: 180 }}
              disabled={systems.length === 0}
            >
              <MenuItem value="all">All systems</MenuItem>
              {systems.map((s) => (
                <MenuItem key={s.id} value={String(s.id)}>{s.name}</MenuItem>
              ))}
            </TextField>
```

- [ ] **Step 4: Add the Systems column**

In the `releaseColumns` useMemo array, add a column before `blocker_count` (or wherever reads well):
```tsx
      {
        field: 'systems',
        headerName: 'Systems',
        width: 200,
        sortable: false,
        renderCell: (params) =>
          params.row.systems.length === 0 ? (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ) : (
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {params.row.systems.map((s) => (
                <Tooltip key={s.id} title={RELEASE_SYSTEM_ROLE_LABELS[s.role] ?? s.role}>
                  <Chip label={s.name} size="small" variant="outlined" />
                </Tooltip>
              ))}
            </Box>
          ),
      },
```

(`Box`, `Chip`, `Tooltip`, `Typography`, `MenuItem`, `TextField` are already imported in this file.)

- [ ] **Step 5: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/pages/releases/ReleaseList.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): Systems column + system filter on releases list"
```

---

## Task 6: Full regression + wrap-up

- [ ] **Step 1: Full backend suite (services + integration)**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest -q`
Expected: all pass, no new failures.

- [ ] **Step 2: Frontend typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Manual smoke (optional, via /run or dev servers)**

Open a project release → **Systems** tab → add a system as *Changing* and another as *Regression (needs testing)* → both appear grouped by role; remove one. Then **Releases — List** → the release shows those systems as chips; the **System** filter narrows the list to releases impacting the chosen system. Confirm the same release appears in **Scope Windows** when filtered by that system.

---

## Self-Review Notes (spec coverage)

- `system_name` on read + role validation: Task 1. ✅
- `GET`/`POST` hydrate `system_name`, tenant scope preserved, 409/400/422 behaviour: Task 1 + tests. ✅
- Systems tab (list/add/remove, role, grouped/sorted, dedup add dropdown, error handling): Task 3. ✅
- Tab placement after Environments + renumber: Task 4. ✅
- Releases list Systems column + client-side system filter: Task 5. ✅
- Shared role label/color map reused in tab + list: Task 2, 3, 5. ✅
- Types (`system_name`, role union): Task 2. ✅
- Follow-on (env planning) intentionally excluded. ✅
- Type consistency: `ReleaseSystemRole` union = `'changing'|'regression'|'config_only'` used in the util, the payload type, and the tab; `releaseService.listSystems/addSystem/removeSystem` signatures match `releaseService.ts`; `system_name` field name identical backend↔frontend. ✅
```
