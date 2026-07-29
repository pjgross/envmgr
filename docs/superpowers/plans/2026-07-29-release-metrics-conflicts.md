# Release Metrics + Booking Conflicts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add release-level metrics (success rate, emergency %, average cycle time) and per-environment-per-month booking-conflict counts, exposed via the existing metrics API and surfaced on the existing `Releases — Analytics` page.

**Architecture:** A new pure, tenant-scoped, on-demand service (`release_metrics_service.py`) aggregates over existing `Release`/`ReleaseStatusHistory`/`Deployment`/`Booking` data — no new models, no migration. `success_rate` reuses SP2's `dora_service.change_failure_rate` so it stays the exact complement of the DORA Change Failure Rate. Two new JWT endpoints hang off the existing `/api/v1/metrics` router. The frontend extends the existing `ReleaseAnalytics` page (local-state + direct-service, cards + `DataTable`, no chart library) with a metrics card row and a conflicts table.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), pytest / httpx (tests), React 18 + TypeScript + MUI + `@mui/x-data-grid` (frontend), vitest + Testing Library.

---

## Context for the implementer (read once)

You have zero context for this codebase. Read these before starting — they are the patterns you must mirror exactly:

- **Service to reuse:** `backend/app/services/dora_service.py` — `change_failure_rate(db, tenant_id, date_from, date_to) -> {"rate", "failed_count", "shipped_count"}`. "shipped" = a release that reached a **terminal** lifecycle state (per its template's `definition.states[].is_terminal`) whose **close date** is in the window AND has ≥1 deployment. "failed" = a shipped release in an `is_failed` terminal state OR causal of an incident in the window. You will call this verbatim for `success_rate`.
- **Close-date resolution (you will replicate this small block):** for a release, close date = latest `ReleaseStatusHistory.changed_at` where `to_state == release.status`, falling back to `release.actual_date`. SQLite returns naive datetimes — normalise to UTC (`.replace(tzinfo=timezone.utc)`) before comparing. See `dora_service.change_failure_rate` lines ~135-146.
- **API pattern:** `backend/app/api/v1/metrics.py` — router `prefix="/metrics"`, JWT via `Depends(get_current_user)`, tenant via `current_user.active_tenant_id`, `date`-typed query params converted with the module-local `_as_dt(d, end_of_day=True)` helper so `date_to` is inclusive of the whole day. The router is already registered in `app/main.py` (line ~159) — no wiring needed.
- **Service test pattern:** `backend/tests/services/test_dora_service.py` — module-level counter helpers `_build`/`_deploy`/`_user`/`_release_template`/`_closed_release`, fixtures `db_session` + `tenant` (short-name fixtures in `tests/conftest.py`). Environment ids 1 and 2 exist implicitly (deployments reference `environment_id=1/2` without a real row because there's no FK enforcement in SQLite tests) — but `booking_conflicts` **joins `Environment`**, so its tests MUST create real `Environment` rows.
- **API test pattern:** `backend/tests/integration/test_dora_api.py` — `authed_client` fixture logs in as `user`/`tenant` (password `password123`), overrides `get_db`.
- **Frontend service/type pattern:** `frontend/src/services/doraService.ts` + `frontend/src/types/dora.ts` — thin `api.get(...).then(r => r.data)`.
- **Frontend page pattern:** `frontend/src/pages/releases/ReleaseAnalytics.tsx` — local `useState` for `from`/`to`, `useEffect` fetch, `DataTable`, MUI `Card`. `formatDuration(seconds)` helper lives in `frontend/src/pages/insights/DoraDashboard.tsx` (NOT exported — you will add a local copy).
- **Frontend render-test pattern:** `frontend/src/pages/insights/__tests__/HealthDashboard.test.tsx` — `vi.mock('../../../services/…')` with a self-contained factory, render inside `<MemoryRouter>`, assert with `findByText`.

**Booking status semantics:** active/counted bookings are those whose `status` is NOT in `{"draft", "cancelled", "rejected"}` (matches the SP3 health-service definition). Overlap is half-open: two windows overlap iff `a.start < b.end AND a.end > b.start`.

---

## File Structure

**Backend — create:**
- `app/services/release_metrics_service.py` — the aggregation service (two public functions + two private helpers).
- `tests/services/test_release_metrics_service.py` — service unit tests.
- `tests/integration/test_release_metrics_api.py` — API integration tests.

**Backend — modify:**
- `app/api/v1/metrics.py` — add two endpoints (`/metrics/releases`, `/metrics/bookings/conflicts`); import the new service.

**Frontend — create:**
- `src/types/releaseMetrics.ts` — response + param types.
- `src/services/releaseMetricsService.ts` — `releases(params)` + `conflicts(params)`.
- `src/pages/releases/__tests__/ReleaseAnalytics.test.tsx` — render test for the new sections.

**Frontend — modify:**
- `src/pages/releases/ReleaseAnalytics.tsx` — add the metrics card row + conflicts table.

---

## Task 1: Booking-conflicts aggregation (`booking_conflicts`)

**Files:**
- Create: `backend/app/services/release_metrics_service.py`
- Test: `backend/tests/services/test_release_metrics_service.py`

`booking_conflicts` is self-contained (no dependency on `dora_service`), so build it first.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_release_metrics_service.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta

from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.user import User, Tenant
from app.core.security import get_password_hash
from app.services import release_metrics_service

UTC = timezone.utc

_user_counter = 0


async def _user(db, tenant_id):
    global _user_counter
    _user_counter += 1
    u = User(tenant_id=tenant_id, username=f"rmuser{_user_counter}",
             email=f"rmuser{_user_counter}@test.com",
             password_hash=get_password_hash("x"), role="Viewer", is_active=True)
    db.add(u); await db.flush(); return u


async def _env(db, tenant_id, name):
    e = Environment(tenant_id=tenant_id, name=name)
    db.add(e); await db.flush(); return e


async def _booking_request(db, tenant_id, user_id):
    # Required non-defaulted columns: tenant_id, project_name, booking_type_id (FK — any int
    # is fine, SQLite tests don't enforce FKs), start_date, end_date, booked_by. context_tag
    # and exclusive_use_requested have model defaults. The request-level dates are placeholders;
    # conflict overlap is computed from the Booking rows, not the request.
    req = BookingRequest(
        tenant_id=tenant_id, project_name="Proj", booked_by=user_id, booking_type_id=1,
        start_date=datetime(2026, 6, 1, tzinfo=UTC), end_date=datetime(2026, 6, 30, tzinfo=UTC),
    )
    db.add(req); await db.flush(); return req


async def _booking(db, tenant_id, env_id, req_id, start, end, status="approved"):
    b = Booking(tenant_id=tenant_id, environment_id=env_id, booking_request_id=req_id,
                start_date=start, end_date=end, status=status)
    db.add(b); await db.flush(); return b


@pytest.mark.asyncio
async def test_conflicts_counts_one_overlapping_pair(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Two bookings that overlap (b2 starts before b1 ends)
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["environment_id"] == env.id
    assert rows[0]["environment_name"] == "SIT"
    assert rows[0]["month"] == "2026-06"
    assert rows[0]["conflict_count"] == 1


@pytest.mark.asyncio
async def test_conflicts_non_overlapping_is_zero(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=1))
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=2), t0 + timedelta(days=3))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []


@pytest.mark.asyncio
async def test_conflicts_excludes_draft_and_cancelled(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Overlapping window, but one booking is draft and one is cancelled → no counted pair
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=3), status="draft")
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4), status="cancelled")
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []


@pytest.mark.asyncio
async def test_conflicts_per_env_grouping(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env_a = await _env(db_session, tenant.id, "SIT")
    env_b = await _env(db_session, tenant.id, "UAT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Overlapping pair on env_a; overlapping pair on env_b
    await _booking(db_session, tenant.id, env_a.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env_a.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await _booking(db_session, tenant.id, env_b.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env_b.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert len(rows) == 2
    by_env = {r["environment_name"]: r["conflict_count"] for r in rows}
    assert by_env == {"SIT": 1, "UAT": 1}


@pytest.mark.asyncio
async def test_conflicts_tenant_isolation(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Second tenant with its own overlapping pair
    t2 = Tenant(name="Other Org", slug="other-org-rm")
    db_session.add(t2); await db_session.flush()
    u2 = await _user(db_session, t2.id)
    env2 = await _env(db_session, t2.id, "SIT2")
    req2 = await _booking_request(db_session, t2.id, u2.id)
    await _booking(db_session, t2.id, env2.id, req2.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, t2.id, env2.id, req2.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    # Query the FIRST tenant (which has no bookings) → empty
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []
```

> **Note on `BookingRequest` fields (already accounted for above):** the model's non-defaulted required columns are `tenant_id, project_name, booking_type_id, start_date, end_date, booked_by` (`context_tag` defaults to `NONE`, `exclusive_use_requested` defaults to `False`). The `_booking_request` fixture supplies all of them. If the model gains a new required column later, add a minimal valid value here.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_release_metrics_service.py -q`
Expected: FAIL — `AttributeError: module 'app.services.release_metrics_service' has no attribute 'booking_conflicts'` (or ModuleNotFoundError for the not-yet-created module).

- [ ] **Step 3: Write the minimal implementation**

Create `backend/app/services/release_metrics_service.py`:

```python
"""Release/utilization metrics (Phase 5 SP5b).

Pure, tenant-scoped, on-demand aggregation over existing Release / Deployment /
Booking data. No new models. success_rate reuses dora_service.change_failure_rate
so it is the exact complement of the DORA Change Failure Rate.
"""
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.db.models.environment import Environment
from app.db.models.deployment import Deployment
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.services import dora_service

# Booking statuses that do NOT represent a live claim on an environment.
_INACTIVE_BOOKING_STATES = {"draft", "cancelled", "rejected"}


def _utc(dt: datetime | None) -> datetime | None:
    """Normalise a possibly-naive (SQLite) datetime to UTC-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def booking_conflicts(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime
) -> list[dict]:
    """Per-environment, per-month count of overlapping active-booking pairs.

    A "conflict" is an overlapping pair of active bookings (status not draft/
    cancelled/rejected) on the same environment. Each pair is counted once, in
    the calendar month of its overlap start (max of the two start dates).
    """
    rows = (await db.execute(
        select(
            Booking.environment_id, Booking.start_date, Booking.end_date, Environment.name
        )
        .join(Environment, Environment.id == Booking.environment_id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(_INACTIVE_BOOKING_STATES)),
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
            # window overlap: the booking touches [date_from, date_to]
            Booking.start_date < date_to,
            Booking.end_date > date_from,
        )
    )).all()

    # group bookings by environment
    by_env: dict[tuple[int, str], list[tuple[datetime, datetime]]] = defaultdict(list)
    for env_id, start, end, env_name in rows:
        by_env[(env_id, env_name)].append((_utc(start), _utc(end)))

    # count overlapping pairs per env, bucketed by overlap-start month
    counts: dict[tuple[int, str, str], int] = defaultdict(int)
    for (env_id, env_name), bookings in by_env.items():
        n = len(bookings)
        for i in range(n):
            s1, e1 = bookings[i]
            for j in range(i + 1, n):
                s2, e2 = bookings[j]
                if s1 < e2 and e1 > s2:  # half-open overlap
                    overlap_start = max(s1, s2)
                    month = overlap_start.strftime("%Y-%m")
                    counts[(env_id, env_name, month)] += 1

    result = [
        {"environment_id": env_id, "environment_name": env_name,
         "month": month, "conflict_count": count}
        for (env_id, env_name, month), count in counts.items()
    ]
    result.sort(key=lambda r: (r["environment_name"], r["month"]))
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_release_metrics_service.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_metrics_service.py backend/tests/services/test_release_metrics_service.py
git commit -m "feat(metrics): booking-conflicts aggregation service (Phase 5 SP5b)"
```

---

## Task 2: Release-metrics aggregation (`release_metrics`)

**Files:**
- Modify: `backend/app/services/release_metrics_service.py`
- Test: `backend/tests/services/test_release_metrics_service.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/services/test_release_metrics_service.py`:

```python
# ---------------------------------------------------------------------------
# release_metrics
# ---------------------------------------------------------------------------

from app.db.models.release import Release, ReleaseStatusHistory  # noqa: E402
from app.db.models.lifecycle import LifecycleTemplate  # noqa: E402
from app.db.models.deployment import Deployment  # noqa: E402
from app.db.models.build import Build  # noqa: E402
from app.db.models.incident import Incident  # noqa: E402

_build_counter = 0
_deploy_counter = 0


async def _build(db, tenant_id, commit_dt, subsystem_id=1):
    global _build_counter
    _build_counter += 1
    sha = f"rm{_build_counter:038d}"
    b = Build(tenant_id=tenant_id, subsystem_id=subsystem_id, git_sha=sha,
              build_number=str(_build_counter), commit_timestamp=commit_dt)
    db.add(b); await db.flush(); return b


async def _deploy(db, tenant_id, build_id, env_id, deployed_dt, release_id):
    global _deploy_counter
    _deploy_counter += 1
    d = Deployment(tenant_id=tenant_id, build_id=build_id, environment_id=env_id,
                   release_id=release_id, change_request_id=1,
                   event_id=f"rm-e{deployed_dt.timestamp()}-{_deploy_counter}",
                   deployed_at=deployed_dt, status="success", custom_fields={})
    db.add(d); await db.flush(); return d


async def _release_template(db, tenant_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="RT",
        description="", is_default=True, is_system=True,
        definition={"states": [
            {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            {"key": "backed_out", "label": "Backed Out", "is_initial": False, "is_terminal": True, "is_failed": True},
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        ], "transitions": [], "field_permissions": {}},
    )
    db.add(tpl); await db.flush(); return tpl


async def _release(db, tenant_id, tpl_id, status, close_dt, *, release_type="Major",
                   created_at=None, actual_date=None, with_deploy=True):
    u = await _user(db, tenant_id)
    r = Release(tenant_id=tenant_id, name="R", release_type=release_type, release_kind="project",
                lifecycle_template_id=tpl_id, status=status, raised_by=u.id,
                actual_date=actual_date)
    if created_at is not None:
        r.created_at = created_at  # override server_default so cycle-time is deterministic
    db.add(r); await db.flush()
    db.add(ReleaseStatusHistory(release_id=r.id, to_state=status, changed_at=close_dt, changed_by=u.id))
    if with_deploy:
        b = await _build(db, tenant_id, close_dt - timedelta(days=1))
        await _deploy(db, tenant_id, b.id, 1, close_dt, r.id)
    await db.flush(); return r


@pytest.mark.asyncio
async def test_success_rate_half_when_one_of_two_failed(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    await _release(db_session, tenant.id, tpl.id, "completed", t0)                     # clean
    await _release(db_session, tenant.id, tpl.id, "backed_out", t0 + timedelta(days=1))  # failed
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["shipped_count"] == 2
    assert res["failed_count"] == 1
    assert abs(res["success_rate"] - 0.5) < 1e-9


@pytest.mark.asyncio
async def test_causal_incident_counts_as_failed(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    r = await _release(db_session, tenant.id, tpl.id, "completed", t0)
    db_session.add(Incident(tenant_id=tenant.id, title="x", severity="P1", status="new",
                            detected_at=t0, release_id=r.id, source="manual"))
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["shipped_count"] == 1
    assert res["failed_count"] == 1
    assert res["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_empty_window_zeroes(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0, t0 + timedelta(days=1))
    assert res["shipped_count"] == 0
    assert res["success_rate"] == 0.0
    assert res["emergency_pct"] == 0.0
    assert res["closed_count"] == 0
    assert res["avg_cycle_time_seconds"] == 0.0
    assert res["cycle_time_count"] == 0


@pytest.mark.asyncio
async def test_emergency_pct(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # 1 Emergency + 3 non-Emergency closed releases → 25%
    await _release(db_session, tenant.id, tpl.id, "completed", t0, release_type="Emergency")
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=1), release_type="Major")
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=2), release_type="Minor")
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=3), release_type="Major")
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["closed_count"] == 4
    assert res["emergency_count"] == 1
    assert abs(res["emergency_pct"] - 0.25) < 1e-9


@pytest.mark.asyncio
async def test_avg_cycle_time_over_shipped(db_session, tenant):
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # created 2 days before ship → 2-day cycle; created 4 days before → 4-day cycle. mean = 3 days.
    await _release(db_session, tenant.id, tpl.id, "completed", t0,
                   created_at=t0 - timedelta(days=2), actual_date=t0)
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=1),
                   created_at=(t0 + timedelta(days=1)) - timedelta(days=4),
                   actual_date=t0 + timedelta(days=1))
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["cycle_time_count"] == 2
    assert abs(res["avg_cycle_time_seconds"] - 3 * 86400) < 1


@pytest.mark.asyncio
async def test_avg_cycle_time_excludes_null_actual_date_and_clamps_negative(db_session, tenant):
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # shipped, actual_date present, but created AFTER actual_date → clamp to 0
    await _release(db_session, tenant.id, tpl.id, "completed", t0,
                   created_at=t0 + timedelta(days=1), actual_date=t0)
    # shipped but NO actual_date → excluded from the cycle-time average
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=1),
                   created_at=t0 - timedelta(days=2), actual_date=None)
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    # only the first (clamped to 0) contributes
    assert res["cycle_time_count"] == 1
    assert res["avg_cycle_time_seconds"] == 0.0


@pytest.mark.asyncio
async def test_release_metrics_tenant_isolation(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    t2 = Tenant(name="Other Org2", slug="other-org-rm2")
    db_session.add(t2); await db_session.flush()
    tpl2 = await _release_template(db_session, t2.id)
    await _release(db_session, t2.id, tpl2.id, "completed", t0, release_type="Emergency")
    await db_session.flush()
    # Query the first tenant → nothing counted
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["closed_count"] == 0
    assert res["shipped_count"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_release_metrics_service.py -q -k release_metrics or success_rate or emergency or cycle or causal or empty_window`

Simpler — run the whole file: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_release_metrics_service.py -q`
Expected: the 7 new tests FAIL — `AttributeError: module 'app.services.release_metrics_service' has no attribute 'release_metrics'`. (The 5 Task-1 tests still pass.)

- [ ] **Step 3: Write the minimal implementation**

Add to `backend/app/services/release_metrics_service.py` (after `booking_conflicts`). Note: `select`, `Release`, `ReleaseStatusHistory`, `LifecycleTemplate`, `Deployment`, `dora_service`, and `_utc` are already imported at the top of the file from Task 1.

```python
async def _closed_releases_in_window(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime
) -> tuple[list[Release], set[int]]:
    """Releases in a terminal lifecycle state whose close date is in the window,
    plus the set of release ids that have >=1 deployment ("shipped").

    Close-date resolution replicates dora_service.change_failure_rate (latest
    ReleaseStatusHistory into the current status, fallback actual_date) so the
    "closed in window" set is consistent with the DORA CFR denominator.
    """
    releases = (await db.execute(
        select(Release).where(Release.tenant_id == tenant_id, Release.deleted_at.is_(None))
    )).scalars().all()

    shipped_ids = set((await db.execute(
        select(Deployment.release_id).where(
            Deployment.tenant_id == tenant_id,
            Deployment.deleted_at.is_(None),
            Deployment.release_id.isnot(None),
        )
    )).scalars().all())

    tpl_cache: dict[int, dict] = {}

    async def _definition(tid: int) -> dict:
        if tid not in tpl_cache:
            tpl = (await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.id == tid,
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            tpl_cache[tid] = tpl.definition if tpl else {"states": []}
        return tpl_cache[tid]

    closed: list[Release] = []
    for r in releases:
        definition = await _definition(r.lifecycle_template_id)
        state = next((s for s in definition.get("states", []) if s.get("key") == r.status), None)
        if state is None or not state.get("is_terminal"):
            continue
        close_at = (await db.execute(
            select(ReleaseStatusHistory.changed_at).where(
                ReleaseStatusHistory.release_id == r.id,
                ReleaseStatusHistory.to_state == r.status,
            ).order_by(ReleaseStatusHistory.changed_at.desc()).limit(1)
        )).scalars().first() or r.actual_date
        close_at = _utc(close_at)
        if close_at is None or not (date_from <= close_at <= date_to):
            continue
        closed.append(r)
    return closed, shipped_ids


async def release_metrics(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime
) -> dict:
    """Release-level success rate, emergency %, and average cycle time over the window.

    success_rate is derived from dora_service.change_failure_rate (exact complement
    of the DORA CFR). emergency_pct and avg_cycle_time are computed from the
    closed-in-window release set.
    """
    cfr = await dora_service.change_failure_rate(db, tenant_id, date_from, date_to)
    shipped_count = cfr["shipped_count"]
    failed_count = cfr["failed_count"]
    success_rate = (1.0 - cfr["rate"]) if shipped_count else 0.0

    closed, shipped_ids = await _closed_releases_in_window(db, tenant_id, date_from, date_to)
    closed_count = len(closed)
    emergency_count = sum(1 for r in closed if r.release_type == "Emergency")
    emergency_pct = (emergency_count / closed_count) if closed_count else 0.0

    cycle_secs: list[float] = []
    for r in closed:
        if r.id in shipped_ids and r.actual_date is not None:
            created = _utc(r.created_at)
            actual = _utc(r.actual_date)
            cycle_secs.append(max(0.0, (actual - created).total_seconds()))
    avg_cycle = (sum(cycle_secs) / len(cycle_secs)) if cycle_secs else 0.0

    return {
        "success_rate": success_rate,
        "shipped_count": shipped_count,
        "failed_count": failed_count,
        "emergency_pct": emergency_pct,
        "emergency_count": emergency_count,
        "closed_count": closed_count,
        "avg_cycle_time_seconds": avg_cycle,
        "cycle_time_count": len(cycle_secs),
    }
```

- [ ] **Step 4: Run the full service test file to verify all pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_release_metrics_service.py -q`
Expected: PASS (12 tests total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_metrics_service.py backend/tests/services/test_release_metrics_service.py
git commit -m "feat(metrics): release success-rate / emergency% / cycle-time service (Phase 5 SP5b)"
```

---

## Task 3: API endpoints (`/metrics/releases`, `/metrics/bookings/conflicts`)

**Files:**
- Modify: `backend/app/api/v1/metrics.py`
- Test: `backend/tests/integration/test_release_metrics_api.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_release_metrics_api.py`:

```python
"""Integration tests for the Release Metrics API (Phase 5 SP5b)."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.user import Tenant

UTC = timezone.utc


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username,
            "password": "password123",
            "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_release_metrics_shape(authed_client):
    r = await authed_client.get("/api/v1/metrics/releases",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "success_rate", "shipped_count", "failed_count",
        "emergency_pct", "emergency_count", "closed_count",
        "avg_cycle_time_seconds", "cycle_time_count",
    }


@pytest.mark.asyncio
async def test_release_metrics_requires_dates(authed_client):
    r = await authed_client.get("/api/v1/metrics/releases")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_booking_conflicts_shape(authed_client, db_session, tenant, user):
    env = Environment(tenant_id=tenant.id, name="SIT")
    db_session.add(env); await db_session.flush()
    req = BookingRequest(
        tenant_id=tenant.id, project_name="Proj", booked_by=user.id, booking_type_id=1,
        start_date=datetime(2026, 6, 1, tzinfo=UTC), end_date=datetime(2026, 6, 30, tzinfo=UTC),
    )
    db_session.add(req); await db_session.flush()
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    db_session.add(Booking(tenant_id=tenant.id, environment_id=env.id, booking_request_id=req.id,
                           start_date=t0, end_date=t0 + timedelta(days=3), status="approved"))
    db_session.add(Booking(tenant_id=tenant.id, environment_id=env.id, booking_request_id=req.id,
                           start_date=t0 + timedelta(days=1), end_date=t0 + timedelta(days=4), status="approved"))
    await db_session.flush()

    r = await authed_client.get("/api/v1/metrics/bookings/conflicts",
                                params={"date_from": "2026-06-01", "date_to": "2026-06-30"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["environment_name"] == "SIT"
    assert body[0]["month"] == "2026-06"
    assert body[0]["conflict_count"] == 1


@pytest.mark.asyncio
async def test_booking_conflicts_requires_dates(authed_client):
    r = await authed_client.get("/api/v1/metrics/bookings/conflicts")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_release_metrics_is_tenant_scoped(authed_client, db_session, tenant):
    # Second tenant with an overlapping booking pair — must not leak into this tenant.
    t2 = Tenant(name="Other Org3", slug="other-org-rm-api")
    db_session.add(t2); await db_session.flush()
    r = await authed_client.get("/api/v1/metrics/bookings/conflicts",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/integration/test_release_metrics_api.py -q`
Expected: FAIL — 404 responses (routes not defined), so the shape/`==1` assertions fail and `test_*_requires_dates` get 404 instead of 422.

- [ ] **Step 3: Add the endpoints**

In `backend/app/api/v1/metrics.py`, add the service import next to the existing `dora_service` import:

```python
from app.services import dora_service, release_metrics_service
```

Then append these two endpoints at the end of the file (after `export_dora`):

```python
@router.get("/releases")
async def get_release_metrics(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_metrics_service.release_metrics(
        db, current_user.active_tenant_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
    )


@router.get("/bookings/conflicts")
async def get_booking_conflicts(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_metrics_service.booking_conflicts(
        db, current_user.active_tenant_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/integration/test_release_metrics_api.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/metrics.py backend/tests/integration/test_release_metrics_api.py
git commit -m "feat(metrics): /metrics/releases + /metrics/bookings/conflicts endpoints (Phase 5 SP5b)"
```

---

## Task 4: Frontend types + service

**Files:**
- Create: `frontend/src/types/releaseMetrics.ts`
- Create: `frontend/src/services/releaseMetricsService.ts`

- [ ] **Step 1: Create the types**

Create `frontend/src/types/releaseMetrics.ts`:

```typescript
export interface ReleaseMetrics {
  success_rate: number;      // 0..1
  shipped_count: number;
  failed_count: number;
  emergency_pct: number;     // 0..1
  emergency_count: number;
  closed_count: number;
  avg_cycle_time_seconds: number;
  cycle_time_count: number;
}

export interface BookingConflictRow {
  environment_id: number;
  environment_name: string;
  month: string;             // "YYYY-MM"
  conflict_count: number;
}

export interface ReleaseMetricsParams {
  date_from: string;         // "YYYY-MM-DD"
  date_to: string;           // "YYYY-MM-DD"
}
```

- [ ] **Step 2: Create the service**

Create `frontend/src/services/releaseMetricsService.ts`:

```typescript
import api from './api';
import type { ReleaseMetrics, BookingConflictRow, ReleaseMetricsParams } from '../types/releaseMetrics';

export const releaseMetricsService = {
  releases: (params: ReleaseMetricsParams) =>
    api.get<ReleaseMetrics>('/metrics/releases', { params }).then((r) => r.data),
  conflicts: (params: ReleaseMetricsParams) =>
    api.get<BookingConflictRow[]>('/metrics/bookings/conflicts', { params }).then((r) => r.data),
};
```

> **Contract note:** send **plain `YYYY-MM-DD`** strings for `date_from`/`date_to` (the backend `_as_dt` already makes `date_to` end-of-day inclusive). Do NOT send `...T23:59:59Z` datetime strings — the endpoint params are typed `date` and would 422. This mirrors the SP2 fix.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/releaseMetrics.ts frontend/src/services/releaseMetricsService.ts
git commit -m "feat(metrics): frontend release-metrics types + service (Phase 5 SP5b)"
```

---

## Task 5: Extend the Releases — Analytics page

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseAnalytics.tsx`
- Test: `frontend/src/pages/releases/__tests__/ReleaseAnalytics.test.tsx`

- [ ] **Step 1: Write the failing render test**

Create `frontend/src/pages/releases/__tests__/ReleaseAnalytics.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import ReleaseAnalytics from '../ReleaseAnalytics';

// The page fetches scope-churn (existing) + release-metrics + conflicts (new).
// Mock all three services so no HTTP is made.
vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    getScopeChurnAnalytics: vi.fn().mockResolvedValue({
      scope_changed: { count: 0, delayed_count: 0, delayed_pct: 0, issue_count: 0, issue_pct: 0 },
      stable: { count: 0, delayed_count: 0, delayed_pct: 0, issue_count: 0, issue_pct: 0 },
      releases: [],
    }),
  },
}));

vi.mock('../../../services/releaseMetricsService', () => ({
  releaseMetricsService: {
    releases: vi.fn().mockResolvedValue({
      success_rate: 0.75,
      shipped_count: 4,
      failed_count: 1,
      emergency_pct: 0.25,
      emergency_count: 1,
      closed_count: 4,
      avg_cycle_time_seconds: 3 * 86400,
      cycle_time_count: 4,
    }),
    conflicts: vi.fn().mockResolvedValue([
      { environment_id: 1, environment_name: 'SIT', month: '2026-06', conflict_count: 2 },
    ]),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <ReleaseAnalytics />
    </MemoryRouter>,
  );
}

describe('ReleaseAnalytics release-metrics section', () => {
  it('renders the success-rate card value', async () => {
    renderPage();
    expect(await screen.findByText('75.0%')).toBeInTheDocument();
  });

  it('renders the emergency-% card value', async () => {
    renderPage();
    expect(await screen.findByText('25.0%')).toBeInTheDocument();
  });

  it('renders the average cycle-time card value', async () => {
    renderPage();
    expect(await screen.findByText('3d')).toBeInTheDocument();
  });

  it('renders a booking-conflict row naming the environment', async () => {
    renderPage();
    expect(await screen.findByText('SIT')).toBeInTheDocument();
  });
});
```

> Before writing the implementation, open `frontend/src/services/releaseService.ts` and confirm the `getScopeChurnAnalytics` mock's resolved shape matches `ScopeChurnAnalyticsResponse` closely enough that the existing page code doesn't throw (it reads `data.scope_changed`, `data.stable`, `data.releases`). If `ChurnCohortResponse` has more required fields, add them to the mock cohorts.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/releases/__tests__/ReleaseAnalytics.test.tsx`
Expected: FAIL — `Unable to find an element with the text: 75.0%` (the cards don't exist yet).

- [ ] **Step 3: Implement the page additions**

Edit `frontend/src/pages/releases/ReleaseAnalytics.tsx`. Make these four changes:

**(a)** Add imports for the new service/types, plus a `GridColDef` for the conflicts table (already imported) and `Card`/`CardContent`/`Typography` (already imported). Add after the existing `releaseService` import (line ~10):

```tsx
import { releaseMetricsService } from '../../services/releaseMetricsService';
import type { ReleaseMetrics, BookingConflictRow } from '../../types/releaseMetrics';
```

**(b)** Add a local `formatDuration` helper (copied from `DoraDashboard`) below the existing `isoDate` helper (after line ~19):

```tsx
function formatDuration(seconds: number): string {
  if (seconds <= 0) return '0m';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0 || parts.length === 0) parts.push(`${minutes}m`);
  return parts.join(' ');
}

function MetricCard({ title, primary, secondary }: { title: string; primary: string; secondary: string }) {
  return (
    <Card variant="outlined" sx={{ flex: 1, minWidth: 220 }}>
      <CardContent>
        <Typography variant="subtitle2" color="text.secondary" gutterBottom>{title}</Typography>
        <Typography variant="h4" sx={{ mt: 0.5, fontWeight: 'bold' }}>{primary}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{secondary}</Typography>
      </CardContent>
    </Card>
  );
}
```

**(c)** Inside the `ReleaseAnalytics` component, add two state hooks next to the existing `const [data, setData] = ...` (line ~45):

```tsx
  const [metrics, setMetrics] = useState<ReleaseMetrics | null>(null);
  const [conflicts, setConflicts] = useState<BookingConflictRow[]>([]);
```

Then add a second `useEffect` right after the existing scope-churn `useEffect` (after line ~55). Note: the new endpoints take **plain `YYYY-MM-DD`** params (unlike the scope-churn call which sends ISO datetimes):

```tsx
  useEffect(() => {
    if (!from || !to) return;
    const params = { date_from: from, date_to: to };
    releaseMetricsService.releases(params).then(setMetrics).catch(() => setMetrics(null));
    releaseMetricsService.conflicts(params).then(setConflicts).catch(() => setConflicts([]));
  }, [from, to]);
```

Add a `conflictColumns` memo next to the existing `columns` memo (after line ~90):

```tsx
  const conflictColumns = useMemo<GridColDef<BookingConflictRow>[]>(
    () => [
      { field: 'environment_name', headerName: 'Environment', flex: 1, minWidth: 180 },
      { field: 'month', headerName: 'Month', width: 120 },
      { field: 'conflict_count', headerName: 'Conflicts', width: 120, type: 'number' },
    ],
    []
  );
```

**(d)** Render the new sections. Add this block inside the returned JSX, immediately after the closing `</Box>` of the date-range filter row (after line ~105, before the `{data && (` block). This makes the metrics cards + conflicts table always visible once loaded, above the existing scope-churn content:

```tsx
      {metrics && (
        <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
          <MetricCard
            title="Release Success Rate"
            primary={metrics.shipped_count === 0 ? 'No data' : `${(metrics.success_rate * 100).toFixed(1)}%`}
            secondary={metrics.shipped_count === 0
              ? 'No shipped releases in range'
              : `${metrics.shipped_count - metrics.failed_count} of ${metrics.shipped_count} shipped OK`}
          />
          <MetricCard
            title="Emergency Releases"
            primary={metrics.closed_count === 0 ? 'No data' : `${(metrics.emergency_pct * 100).toFixed(1)}%`}
            secondary={metrics.closed_count === 0
              ? 'No closed releases in range'
              : `${metrics.emergency_count} of ${metrics.closed_count} closed`}
          />
          <MetricCard
            title="Avg Cycle Time"
            primary={metrics.cycle_time_count === 0 ? 'No data' : formatDuration(metrics.avg_cycle_time_seconds)}
            secondary={metrics.cycle_time_count === 0
              ? 'No shipped releases with a ship date'
              : `created → shipped, ${metrics.cycle_time_count} release${metrics.cycle_time_count !== 1 ? 's' : ''}`}
          />
        </Box>
      )}

      <Typography variant="subtitle1" sx={{ mb: 1 }}>Booking Conflicts (by environment / month)</Typography>
      <Box sx={{ height: 300, width: '100%', mb: 3 }}>
        <DataTable<BookingConflictRow>
          storageKey="release-analytics-conflicts"
          rows={conflicts}
          columns={conflictColumns}
          emptyMessage="No booking conflicts in range"
          getRowId={(row) => `${row.environment_id}-${row.month}`}
        />
      </Box>
```

> Line numbers are approximate — locate the anchors by content (the filter-row `</Box>`, the `const [data, setData]` line, the `columns` memo). The `MetricCard` helper is defined at module scope in step (b); do not redefine it inside the component.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/releases/__tests__/ReleaseAnalytics.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/releases/ReleaseAnalytics.tsx frontend/src/pages/releases/__tests__/ReleaseAnalytics.test.tsx
git commit -m "feat(metrics): surface release metrics + booking conflicts on Analytics page (Phase 5 SP5b)"
```

---

## Task 6: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest -q`
Expected: all pass (previous baseline was 803 pass / 1 skip; this adds ~17 tests → ~820 pass / 1 skip). If any pre-existing test broke, fix it before continuing.

- [ ] **Step 2: Run the full frontend unit suite**

Run: `cd frontend && npx vitest run`
Expected: all pass (previous baseline + 4 new).

- [ ] **Step 3: Frontend type-check + lint**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Confirm no stray files / clean tree**

Run: `git status`
Expected: clean working tree (all changes committed across Tasks 1-5).

---

## Self-Review (completed by plan author)

**Spec coverage:**
- success_rate (reuse CFR) → Task 2. ✅
- emergency_pct → Task 2. ✅
- avg_cycle_time (mean actual_date − created_at over shipped, null-excluded, negatives clamped) → Task 2. ✅
- booking_conflicts per env/month → Task 1. ✅
- `GET /metrics/releases` + `GET /metrics/bookings/conflicts` (422 on missing dates, `_as_dt` end-of-day) → Task 3. ✅
- Frontend types + service (`releases`, `conflicts`) → Task 4. ✅
- Extend Releases — Analytics (cards + conflicts DataTable, `formatDuration`, no chart lib, no new nav) → Task 5. ✅
- Tests: service (success_rate, emergency, cycle-time incl. null/negative, conflicts overlap/exclusion/grouping, tenant isolation), API (shape + 422), frontend render → Tasks 1-5. ✅
- Non-goals respected: no new model/migration, no CSV export, no per-project filter. ✅

**Type consistency:** `ReleaseMetrics` fields returned by the service (Task 2) exactly match the TS interface (Task 4) and the API shape assertion (Task 3): `success_rate, shipped_count, failed_count, emergency_pct, emergency_count, closed_count, avg_cycle_time_seconds, cycle_time_count`. `BookingConflictRow` fields (`environment_id, environment_name, month, conflict_count`) match across service, API test, TS type, and the DataTable columns.

**Placeholder scan:** no TBD/TODO/"add error handling"/"similar to Task N"; every code step shows full code. Approximate line numbers are flagged as content-anchored, not placeholders.

**Known replication (documented, DRY-considered):** `_closed_releases_in_window` replicates the close-date + terminal resolution from `dora_service.change_failure_rate` rather than refactoring `dora_service` — the spec explicitly permits this ("replicate the small logic") and it avoids destabilising the SP2 tests; `success_rate` still reuses `change_failure_rate` directly so it stays the exact CFR complement.
```