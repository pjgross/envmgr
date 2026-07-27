# Guided Multi-Environment Booking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the release coverage matrix, select several environments (or the suggested set), pick common dates/phase/booking-type once, preview conflicts, and book them all — skipping any environment with a hard (exclusive) conflict.

**Architecture:** A `POST /releases/{id}/bookings/bulk` endpoint whose service loops the existing single-env `book_environment_for_phase` (which sets release/phase and derives the per-env `context_tag`), gated per environment by the existing `check_overlap` (exclusive-blocked envs are skipped and reported). Conflict preview reuses the existing `POST /booking-requests/preview-conflicts`. Frontend adds checkboxes + a toolbar to the coverage matrix and a new bulk dialog. No migration; no new booking logic beyond the loop.

**Tech Stack:** FastAPI, SQLAlchemy (async), Pydantic v2, PostgreSQL (SQLite for tests), React 18 + TypeScript + MUI.

**Spec:** `docs/superpowers/specs/2026-07-27-multi-env-booking-design.md`

**Conventions (verified in-repo):**
- Services never `db.commit()`; use `db.flush()`. No frontend unit tests — verify `tsc --noEmit` + `npm run build`.
- Full backend suite is the checkpoint: `cd backend && PYTHONPATH=. uv run pytest -q`.
- Use `git -C /Users/peter/Developer/Code/projects/envmgr` for git (cwd persists across commands).
- `release_booking_service.book_environment_for_phase(db, release_id, phase_id, environment_id, start, end, booking_type_id, tenant_id, user_id, project_name=None, notes=None, exclusive_use=False) -> Booking` — validates the release (404 if not in tenant), builds a `BookingCreate`, calls `create_booking` (raises 409 if `check_overlap` is exclusive-blocked), then `derive_and_set_context_tag`.
- `booking_service.check_overlap(db, env_id, start, end, tenant_id, exclusive_use, exclude_id=None) -> OverlapResult(blocked: bool, conflicts: list[int], warnings: list[int])`. `blocked=True` when the new booking OR any overlapping existing booking is exclusive; else `warnings` lists shared overlaps.
- `releases.py`: `_require_release`, `release_booking_service`, `select`, `Depends`, `get_db`, `get_current_user`, `AsyncSession`, `status` are in scope. Existing `class ReleaseBookingRequest(BaseModel)` (inline) + `POST /{release_id}/bookings` live near line 1151/1206.
- Frontend `bookingRequestService.previewConflicts({ environment_ids: number[], start_date: string, end_date: string }) -> { conflicts: Record<number, EnvBookingSummary[]> }` (in `services/bookingRequestService.ts`). `EnvBookingSummary` from `types/bookingRequest.ts` = `{ id, environment_id, environment_name?, project_name?, start_date, end_date, status, has_unacknowledged_conflicts? }`.
- `AddPhaseBookingDialog` reads environments from `s.environment.environments` (dispatch `fetchEnvironments()`), booking types from `bookingLifecycleService.listBookingTypes()`.

---

## Task 1: Backend — bulk booking schemas + service + endpoint + tests

**Files:**
- Create: `backend/app/api/v1/schemas/release_bulk_booking.py`
- Modify: `backend/app/services/release_booking_service.py`
- Modify: `backend/app/api/v1/releases.py`
- Test: `backend/tests/integration/test_release_bulk_booking_api.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_release_bulk_booking_api.py`:

```python
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.db.base import get_db
from app.db.models.system import System
from app.db.models.environment import Environment, EnvironmentSystem
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest

WIN_START = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
WIN_END = WIN_START + timedelta(days=1)


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


async def _make_env(db_session, tenant_id, name) -> int:
    e = Environment(tenant_id=tenant_id, name=name, environment_type="sit")
    db_session.add(e)
    await db_session.flush()
    return e.id


async def _host(db_session, tenant_id, env_id, system_id):
    db_session.add(EnvironmentSystem(tenant_id=tenant_id, environment_id=env_id, system_id=system_id))
    await db_session.flush()


async def _link(authed_client, rid, sid, role):
    resp = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": role})
    assert resp.status_code == 201, resp.text


async def _booking_type(db_session, tenant_id) -> int:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="booking", name="bt-lc",
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [], "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(tenant_id=tenant_id, name="Standard", lifecycle_template_id=tpl.id)
    db_session.add(bt)
    await db_session.flush()
    return bt.id


def _payload(env_ids, bt, **extra):
    return {
        "environment_ids": env_ids,
        "start": WIN_START.isoformat(),
        "end": WIN_END.isoformat(),
        "booking_type_id": bt,
        **extra,
    }


@pytest.mark.asyncio
async def test_bulk_books_all_free_environments(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")
    b = await _make_env(db_session, tenant.id, "B")
    c = await _make_env(db_session, tenant.id, "C")

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a, b, c], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {x["environment_id"] for x in body["created"]} == {a, b, c}
    assert body["skipped"] == []
    for item in body["created"]:
        assert item["booking_id"] > 0
        assert item["warnings"] == []


@pytest.mark.asyncio
async def test_bulk_sets_context_tag_from_role(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    sysid = await _make_system(db_session, tenant.id, "Payments")
    await _link(authed_client, rid, sysid, "changing")
    env = await _make_env(db_session, tenant.id, "A")
    await _host(db_session, tenant.id, env, sysid)

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([env], bt))
    assert resp.status_code == 200, resp.text
    booking_id = resp.json()["created"][0]["booking_id"]
    booking = (await db_session.execute(select(Booking).where(Booking.id == booking_id))).scalar_one()
    br = (await db_session.execute(
        select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
    )).scalar_one()
    assert br.context_tag == ContextTag.DEPLOYMENT  # 'changing' role -> DEPLOYMENT


@pytest.mark.asyncio
async def test_bulk_skips_exclusive_conflict(authed_client, tenant, user, db_session, release_lifecycle_template):
    from app.services.release_booking_service import book_environment_for_phase
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")
    b = await _make_env(db_session, tenant.id, "B")

    # Pre-existing EXCLUSIVE booking on env A overlapping the window.
    pre = await book_environment_for_phase(
        db_session, release_id=rid, phase_id=None, environment_id=a,
        start=WIN_START, end=WIN_END, booking_type_id=bt, tenant_id=tenant.id,
        user_id=user.id, project_name="pre", exclusive_use=True,
    )
    await db_session.flush()

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a, b], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {x["environment_id"] for x in body["created"]} == {b}
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["environment_id"] == a
    assert pre.id in body["skipped"][0]["conflicts"]


@pytest.mark.asyncio
async def test_bulk_soft_conflict_warns(authed_client, tenant, user, db_session, release_lifecycle_template):
    from app.services.release_booking_service import book_environment_for_phase
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")

    pre = await book_environment_for_phase(
        db_session, release_id=rid, phase_id=None, environment_id=a,
        start=WIN_START, end=WIN_END, booking_type_id=bt, tenant_id=tenant.id,
        user_id=user.id, project_name="pre", exclusive_use=False,
    )
    await db_session.flush()

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["skipped"] == []
    assert len(body["created"]) == 1
    assert pre.id in body["created"][0]["warnings"]


@pytest.mark.asyncio
async def test_bulk_empty_ids_422(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([], bt))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_unknown_release_404(authed_client, tenant, db_session, release_lifecycle_template):
    bt = await _booking_type(db_session, tenant.id)
    resp = await authed_client.post("/api/v1/releases/999999/bookings/bulk", json=_payload([1], bt))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_release_bulk_booking_api.py -v`
Expected: FAIL — the bulk endpoint does not exist.

- [ ] **Step 3: Create the schemas**

Create `backend/app/api/v1/schemas/release_bulk_booking.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReleaseBulkBookingRequest(BaseModel):
    environment_ids: list[int] = Field(..., min_length=1)
    phase_id: Optional[int] = None
    start: datetime
    end: datetime
    booking_type_id: int
    project_name: Optional[str] = None
    notes: Optional[str] = None
    exclusive_use: bool = False


class BulkBookCreated(BaseModel):
    environment_id: int
    booking_id: int
    warnings: list[int]


class BulkBookSkipped(BaseModel):
    environment_id: int
    conflicts: list[int]


class BulkBookResult(BaseModel):
    created: list[BulkBookCreated]
    skipped: list[BulkBookSkipped]
```

- [ ] **Step 4: Add the service function**

In `backend/app/services/release_booking_service.py`, add at the end:

```python
async def bulk_book_environments(
    db: AsyncSession,
    release_id: int,
    environment_ids: list[int],
    phase_id: Optional[int],
    start: datetime,
    end: datetime,
    booking_type_id: int,
    tenant_id: int,
    user_id: int,
    project_name: Optional[str] = None,
    notes: Optional[str] = None,
    exclusive_use: bool = False,
) -> dict:
    """Book each environment for a release in one pass. Environments with a
    hard (exclusive) conflict for the window are skipped and reported; the rest
    are booked via book_environment_for_phase (which sets release/phase and
    derives context_tag). Returns {"created": [...], "skipped": [...]}."""
    from app.services.booking_service import check_overlap

    created: list[dict] = []
    skipped: list[dict] = []
    for env_id in environment_ids:
        overlap = await check_overlap(db, env_id, start, end, tenant_id, exclusive_use)
        if overlap.blocked:
            skipped.append({"environment_id": env_id, "conflicts": overlap.conflicts})
            continue
        booking = await book_environment_for_phase(
            db,
            release_id=release_id,
            phase_id=phase_id,
            environment_id=env_id,
            start=start,
            end=end,
            booking_type_id=booking_type_id,
            tenant_id=tenant_id,
            user_id=user_id,
            project_name=project_name,
            notes=notes,
            exclusive_use=exclusive_use,
        )
        created.append({"environment_id": env_id, "booking_id": booking.id, "warnings": overlap.warnings})

    return {"created": created, "skipped": skipped}
```

- [ ] **Step 5: Add the endpoint**

In `backend/app/api/v1/releases.py`, add the schema import near the other `from app.api.v1.schemas...` imports:
```python
from app.api.v1.schemas.release_bulk_booking import (
    ReleaseBulkBookingRequest,
    BulkBookResult,
)
```
Add the handler right after the existing `POST /{release_id}/bookings` handler:
```python
@router.post("/{release_id}/bookings/bulk", response_model=BulkBookResult)
async def bulk_book_release_environments(
    release_id: int,
    data: ReleaseBulkBookingRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Book several environments for a release in one flow; environments with an
    exclusive conflict for the window are skipped and reported."""
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    return await release_booking_service.bulk_book_environments(
        db,
        release_id=release_id,
        environment_ids=data.environment_ids,
        phase_id=data.phase_id,
        start=data.start,
        end=data.end,
        booking_type_id=data.booking_type_id,
        tenant_id=tenant_id,
        user_id=current_user.id,
        project_name=data.project_name,
        notes=data.notes,
        exclusive_use=data.exclusive_use,
    )
```

- [ ] **Step 6: Run tests to verify pass**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/test_release_bulk_booking_api.py -v`
Expected: 6 passed.

- [ ] **Step 7: Regression**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/backend && PYTHONPATH=. uv run pytest tests/integration/ -k "booking or release" -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add backend/app/api/v1/schemas/release_bulk_booking.py backend/app/services/release_booking_service.py backend/app/api/v1/releases.py backend/tests/integration/test_release_bulk_booking_api.py
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): bulk multi-environment release booking endpoint"
```

---

## Task 2: Frontend — bulk booking types + service method

**Files:**
- Modify: `frontend/src/types/release.ts`
- Modify: `frontend/src/services/releaseService.ts`

- [ ] **Step 1: Add the types**

In `frontend/src/types/release.ts`, add:
```typescript
export interface ReleaseBulkBookingPayload {
  environment_ids: number[];
  phase_id?: number | null;
  start: string;
  end: string;
  booking_type_id: number;
  project_name?: string | null;
  notes?: string | null;
  exclusive_use?: boolean;
}

export interface BulkBookCreatedItem {
  environment_id: number;
  booking_id: number;
  warnings: number[];
}

export interface BulkBookSkippedItem {
  environment_id: number;
  conflicts: number[];
}

export interface BulkBookResultResponse {
  created: BulkBookCreatedItem[];
  skipped: BulkBookSkippedItem[];
}
```

- [ ] **Step 2: Add the service method**

In `frontend/src/services/releaseService.ts`:
- Add `ReleaseBulkBookingPayload, BulkBookResultResponse,` to the `from '../types/release'` import block.
- Add (after `bookForPhase`):
```typescript
  bulkBookEnvironments: (releaseId: number, payload: ReleaseBulkBookingPayload): Promise<BulkBookResultResponse> =>
    api.post(`/releases/${releaseId}/bookings/bulk`, payload).then((r) => r.data),
```

- [ ] **Step 3: Typecheck**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/types/release.ts frontend/src/services/releaseService.ts
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): bulk booking types + bulkBookEnvironments service"
```

---

## Task 3: Frontend — `BulkBookEnvironmentsDialog`

**Files:**
- Create: `frontend/src/components/releases/BulkBookEnvironmentsDialog.tsx`

- [ ] **Step 1: Create the dialog**

Create `frontend/src/components/releases/BulkBookEnvironmentsDialog.tsx`:

```tsx
/**
 * BulkBookEnvironmentsDialog — book several environments for a release at once,
 * with a conflict preview and a per-environment result summary.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  MenuItem, Stack, TextField, Typography,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchEnvironments } from '../../store/environmentSlice';
import { releaseService } from '../../services/releaseService';
import { bookingRequestService } from '../../services/bookingRequestService';
import { bookingLifecycleService } from '../../services/bookingLifecycleService';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { TestPhaseResponse, BulkBookResultResponse } from '../../types/release';
import type { BookingTypeRecord } from '../../types/bookingLifecycle';
import type { EnvBookingSummary } from '../../types/bookingRequest';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  environmentIds: number[];
  phases: TestPhaseResponse[];
  onCreated: () => void;
}

export default function BulkBookEnvironmentsDialog({
  open, onClose, releaseId, environmentIds, phases, onCreated,
}: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const environments = useSelector((s: RootState) => s.environment.environments);

  const [bookingTypes, setBookingTypes] = useState<BookingTypeRecord[]>([]);
  const [phaseId, setPhaseId] = useState<number | ''>('');
  const [bookingTypeId, setBookingTypeId] = useState<number | ''>('');
  const [projectName, setProjectName] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [conflicts, setConflicts] = useState<Record<number, EnvBookingSummary[]> | null>(null);
  const [result, setResult] = useState<BulkBookResultResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    dispatch(fetchEnvironments());
    bookingLifecycleService.listBookingTypes().then(setBookingTypes).catch(() => setBookingTypes([]));
  }, [dispatch]);

  // Reset preview/result when re-opened or the selection changes.
  useEffect(() => {
    if (open) {
      setConflicts(null);
      setResult(null);
    }
  }, [open, environmentIds]);

  const envName = useMemo(() => {
    const m = new Map<number, string>();
    environments.forEach((e) => m.set(e.id, e.name));
    return (id: number) => m.get(id) ?? `#${id}`;
  }, [environments]);

  const canPreview = !!startDate && !!endDate && environmentIds.length > 0;
  const canSubmit = canPreview && !!bookingTypeId && !!projectName.trim();

  const handlePreview = async () => {
    if (!canPreview) return;
    try {
      const resp = await bookingRequestService.previewConflicts({
        environment_ids: environmentIds,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
      });
      setConflicts(resp.conflicts);
    } catch {
      snackbar.error('Failed to check conflicts');
    }
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await releaseService.bulkBookEnvironments(releaseId, {
        environment_ids: environmentIds,
        phase_id: phaseId !== '' ? (phaseId as number) : undefined,
        start: new Date(startDate).toISOString(),
        end: new Date(endDate).toISOString(),
        booking_type_id: bookingTypeId as number,
        project_name: projectName,
      });
      setResult(res);
      onCreated();
      snackbar.success(`Booked ${res.created.length} environment(s)`);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to book environments');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Book {environmentIds.length} environment(s)</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
            {environmentIds.map((id) => (
              <Chip key={id} label={envName(id)} size="small" />
            ))}
          </Box>

          <TextField select label="Test Phase (optional)" fullWidth value={phaseId}
            onChange={(e) => setPhaseId(e.target.value === '' ? '' : Number(e.target.value))}>
            <MenuItem value="">None</MenuItem>
            {phases.map((p) => (<MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>))}
          </TextField>

          <TextField select label="Booking Type" required fullWidth value={bookingTypeId}
            onChange={(e) => setBookingTypeId(Number(e.target.value))}>
            {bookingTypes.map((bt) => (<MenuItem key={bt.id} value={bt.id}>{bt.name}</MenuItem>))}
          </TextField>

          <TextField label="Project Name" required fullWidth value={projectName}
            onChange={(e) => setProjectName(e.target.value)} />

          <TextField label="Start Date" type="date" required fullWidth InputLabelProps={{ shrink: true }}
            value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <TextField label="End Date" type="date" required fullWidth InputLabelProps={{ shrink: true }}
            value={endDate} onChange={(e) => setEndDate(e.target.value)} />

          <Button variant="outlined" onClick={handlePreview} disabled={!canPreview}>
            Check conflicts
          </Button>

          {conflicts && (
            Object.keys(conflicts).length === 0 ? (
              <Alert severity="success">No conflicts for the chosen window.</Alert>
            ) : (
              <Alert severity="warning">
                Conflicts detected:
                {Object.entries(conflicts).map(([envId, list]) => (
                  <div key={envId}>
                    <strong>{envName(Number(envId))}</strong>: {list.map((b) => b.project_name ?? `#${b.id}`).join(', ')}
                  </div>
                ))}
              </Alert>
            )
          )}

          {result && (
            <Alert severity={result.skipped.length > 0 ? 'warning' : 'success'}>
              Booked {result.created.length} environment(s).
              {result.skipped.length > 0 && (
                <div>
                  Skipped {result.skipped.length} with an exclusive conflict:{' '}
                  {result.skipped.map((s) => envName(s.environment_id)).join(', ')}
                </div>
              )}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>{result ? 'Close' : 'Cancel'}</Button>
        {!result && (
          <Button variant="contained" onClick={handleSubmit} disabled={!canSubmit || submitting}>
            {submitting ? 'Booking…' : 'Book'}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
```

Before finalising: confirm `BookingTypeRecord` is the type used by `AddPhaseBookingDialog` (`import type { BookingTypeRecord } from '../../types/bookingLifecycle';`) and that `bookingLifecycleService.listBookingTypes()` returns it — mirror `AddPhaseBookingDialog.tsx`. If `snackbar.error` on a non-Error rejection needs the axios-detail extraction, copy the small `extractError` pattern used elsewhere; otherwise the simple message is fine.

- [ ] **Step 2: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/components/releases/BulkBookEnvironmentsDialog.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): BulkBookEnvironmentsDialog (multi-env booking + conflict preview)"
```

---

## Task 4: Frontend — matrix selection + wire the bulk dialog

**Files:**
- Modify: `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx`
- Modify: `frontend/src/components/releases/ReleaseEnvironmentsTab.tsx`

- [ ] **Step 1: `ReleaseEnvironmentCoverage` — selection + toolbar + `onBookMany`**

In `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx`:

Add `Checkbox` to the MUI import list, and add `onBookMany` to the `Props`:
```tsx
interface Props {
  releaseId: number;
  onBook: (environmentId: number) => void;
  onBookMany: (environmentIds: number[]) => void;
}
```
Destructure `onBookMany` in the component signature.

Add selection state (inside the component, before the render/`return`):
```tsx
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const toggleEnv = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
```

Add a toolbar just below the `<Typography variant="subtitle1">Test Environment Coverage</Typography>` header (and above the gap Alert), giving quick actions:
```tsx
      <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
        <Button
          size="small"
          variant="contained"
          disabled={selected.size === 0}
          onClick={() => onBookMany(Array.from(selected))}
        >
          Book selected ({selected.size})
        </Button>
        {suggestion.length > 0 && (
          <Button
            size="small"
            variant="outlined"
            onClick={() => {
              const ids = data.environments
                .filter((e) => suggestion.includes(e.name))
                .map((e) => e.environment_id);
              setSelected(new Set(ids));
              onBookMany(ids);
            }}
          >
            Book suggested set
          </Button>
        )}
      </Box>
```
(`suggestion` and `data` are already computed above this point; `data` is non-null here because the empty/loading guards return earlier.)

In the environment column header cell, add a checkbox above the name/Book button:
```tsx
              <TableCell key={e.environment_id} align="center">
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5 }}>
                  <Checkbox
                    size="small"
                    checked={selected.has(e.environment_id)}
                    onChange={() => toggleEnv(e.environment_id)}
                    inputProps={{ 'aria-label': `Select ${e.name}` }}
                  />
                  <span>{e.name} ({e.covered_system_ids.length}/{data.needed_systems.length})</span>
                  <Button size="small" variant="outlined" onClick={() => onBook(e.environment_id)}>
                    Book
                  </Button>
                </Box>
              </TableCell>
```

- [ ] **Step 2: `ReleaseEnvironmentsTab` — wire the bulk dialog**

In `frontend/src/components/releases/ReleaseEnvironmentsTab.tsx`:

Add the import:
```tsx
import BulkBookEnvironmentsDialog from './BulkBookEnvironmentsDialog';
```
Add state next to `bookEnvId`:
```tsx
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkEnvIds, setBulkEnvIds] = useState<number[]>([]);
```
Pass `onBookMany` to the coverage component (alongside the existing `onBook`):
```tsx
      <ReleaseEnvironmentCoverage
        releaseId={releaseId}
        onBook={(environmentId) => {
          setBookEnvId(environmentId);
          setAddOpen(true);
        }}
        onBookMany={(environmentIds) => {
          setBulkEnvIds(environmentIds);
          setBulkOpen(true);
        }}
      />
```
Render the bulk dialog next to the existing `AddPhaseBookingDialog`:
```tsx
      <BulkBookEnvironmentsDialog
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        releaseId={releaseId}
        environmentIds={bulkEnvIds}
        phases={phases}
        onCreated={loadBookings}
      />
```

- [ ] **Step 3: Typecheck + build**

Run: `cd /Users/peter/Developer/Code/projects/envmgr/frontend && npx tsc --noEmit && npm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git -C /Users/peter/Developer/Code/projects/envmgr add frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx frontend/src/components/releases/ReleaseEnvironmentsTab.tsx
git -C /Users/peter/Developer/Code/projects/envmgr commit -m "feat(releases): matrix multi-select + bulk booking wiring"
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

On a release with Changing/Regression systems hosted across several environments: Environments tab → coverage matrix → tick a couple of environment checkboxes (or "Book suggested set") → the bulk dialog opens listing them → set dates/booking-type/project → "Check conflicts" shows any overlaps → Book → result summary shows how many were booked and which were skipped for exclusive conflicts; the Gantt + bookings table refresh.

---

## Self-Review Notes (spec coverage)

- Bulk endpoint + service looping `book_environment_for_phase` with `check_overlap` skip-gate: Task 1. ✅
- Skip exclusive-blocked envs, report them; soft conflicts as warnings; per-env `context_tag`: Task 1 + tests. ✅
- Preview reuses `preview-conflicts`: Task 3 (`bookingRequestService.previewConflicts`). ✅
- Matrix checkboxes + "Book selected" + "Book suggested set" + kept single Book: Task 4. ✅
- Bulk dialog (common fields, preview panel, result summary): Task 3. ✅
- Tab wiring for the bulk dialog: Task 4. ✅
- Types + service method: Task 2. ✅
- One-booking-per-env (not shared request): the service loops `book_environment_for_phase`. ✅
- Out-of-scope (shared request, recurring, ack flow, mock-aware) not implemented. ✅
- Type consistency: `ReleaseBulkBookingPayload`/`BulkBookResultResponse` ↔ backend `ReleaseBulkBookingRequest`/`BulkBookResult` (created:[{environment_id,booking_id,warnings}], skipped:[{environment_id,conflicts}]); `bulkBookEnvironments` path matches the endpoint; `onBookMany` prop name identical in Task 3/4 wiring; `previewConflicts` arg/response shapes match the existing service. ✅
```
