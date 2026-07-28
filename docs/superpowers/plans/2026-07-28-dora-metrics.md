# DORA Metrics (Phase 5 SP2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute the four DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, MTTR) on-demand from existing deployment/build/release/incident data, plus an admin `is_failed` lifecycle-state flag that drives release-based CFR, exposed via API + CSV and a dashboard page.

**Architecture:** A pure, tenant-scoped `dora_service` runs live SQL queries over a date window and buckets results in Python; thin `metrics` API endpoints expose a summary + CSV export. CFR reads a new optional `is_failed` flag on lifecycle-template terminal states (seeded on release defaults, admin-editable, backfilled). Frontend is a dashboard page with stat cards + a trend `DataTable` (no charting library — mirrors `ReleaseAnalytics`, which uses local `useState` + a direct service call, NOT a Redux slice).

**Tech Stack:** FastAPI + SQLAlchemy async + pytest; React 18 + TS strict + MUI + `@mui/x-data-grid`; vitest.

**Spec:** `docs/superpowers/specs/2026-07-28-dora-metrics-design.md`

---

## Reference facts (verified against the codebase)

- **Deployment** (`app/db/models/deployment.py`): `build_id`, `environment_id`, `release_id?`, `deployed_at`, `status` ∈ {pending, in_progress, success, failed, rolled_back}, `tenant_id`, `deleted_at`.
- **Build**: `build_id → Build.commit_timestamp` for lead time.
- **Release** (`app/db/models/release.py`): `status`, `actual_date`, `lifecycle_template_id`; `ReleaseStatusHistory` (`release_status_history`): `release_id`, `to_state`, `changed_at`.
- **Incident** (`app/db/models/incident.py`): `deployment_id?`, causal `release_id?`, `detected_at`, `resolved_at?`, `deleted_at`.
- **LifecycleTemplate.definition** JSON `states` entries carry `key/label/is_initial/is_terminal`; this plan adds an optional `is_failed`. `lifecycle_service` has no terminal helper — read `definition.states` directly.
- **Router mount** (`app/main.py`): follow the incidents pattern — router declares `prefix="/metrics"`, mounted via `app.include_router(metrics_router.router, prefix="/api/v1")`.
- **Analytics frontend precedent** (`src/pages/releases/ReleaseAnalytics.tsx`): local `useState` for filters + fetched data, `useEffect` calling the service directly, cards + `DataTable`. **No Redux slice.** Follow this.
- **Nav placeholder** (`src/components/navConfig.tsx`): `{ label: 'DORA Metrics', path: '/insights/dora', icon: <QueryStatsIcon />, comingSoon: true }` — un-gate it.
- Conventions: `db.flush()` not commit; every query filters `tenant_id` + `deleted_at IS NULL`; migrations manual (none needed here — `is_failed` lives in the JSON `definition`, no schema change); any authenticated user may read metrics.
- Backend cmds from `backend/` (`uv run pytest`, `uv run python`); frontend from `frontend/` (`npx`).

---

## File Structure

**Backend — create:** `app/services/dora_service.py`, `app/api/v1/metrics.py`, `scripts/backfill_release_failed_flags.py`, tests `tests/services/test_dora_service.py`, `tests/integration/test_dora_api.py`.
**Backend — modify:** `app/services/release_defaults.py` (add `is_failed` to default states), `app/main.py` (mount router).
**Frontend — create:** `src/types/dora.ts`, `src/services/doraService.ts`, `src/pages/insights/DoraDashboard.tsx`.
**Frontend — modify:** `src/components/admin/LifecycleTemplatesPanel.tsx` ("Counts as failure" checkbox), `src/components/navConfig.tsx` (un-gate), `src/App.tsx` (route).

---

## Task 1: Seed `is_failed` on default release lifecycle states (TDD)

**Files:**
- Modify: `backend/app/services/release_defaults.py`
- Test: `backend/tests/services/test_release_defaults_failed_flag.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import select
from app.db.models.lifecycle import LifecycleTemplate
from app.services.release_defaults import seed_release_defaults_for_tenant


def _failed_keys(definition):
    return {s["key"] for s in definition["states"] if s.get("is_failed")}


@pytest.mark.asyncio
async def test_default_release_templates_flag_failed_states(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
        )
    )).scalars().all()
    by_name = {r.name: r for r in rows}
    # Major/Minor: completed_with_issues + backed_out are failures; completed is not.
    for name in ("Major", "Minor"):
        fk = _failed_keys(by_name[name].definition)
        assert "completed_with_issues" in fk
        assert "backed_out" in fk
        assert "completed" not in fk
        assert "cancelled" not in fk
    # Emergency: backed_out is a failure.
    assert "backed_out" in _failed_keys(by_name["Emergency"].definition)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/services/test_release_defaults_failed_flag.py -q`
Expected: FAIL — `is_failed` not present, `"completed_with_issues" in fk` is False.

- [ ] **Step 3: Add `is_failed` to the default definitions**

In `backend/app/services/release_defaults.py`, in `_MAJOR_DEFINITION` and `_MINOR_DEFINITION` `states`, add `"is_failed": True` to the `completed_with_issues` and `backed_out` state dicts. In `_EMERGENCY_DEFINITION` `states`, add `"is_failed": True` to the `backed_out` state dict. Example (Major, the two lines change from):

```python
{"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True},
{"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True},
```

to:

```python
{"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True, "is_failed": True},
{"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True, "is_failed": True},
```

(Do the same for `backed_out` in Minor and Emergency, and `completed_with_issues` in Minor. Leave `completed`, `rejected`, `cancelled`, and the Enterprise template unchanged.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/services/test_release_defaults_failed_flag.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_defaults.py backend/tests/services/test_release_defaults_failed_flag.py
git commit -m "feat(dora): flag failed terminal states on default release lifecycles (Phase 5 SP2)"
```

---

## Task 2: `dora_service` — Deployment Frequency + Lead Time (TDD)

**Files:**
- Create: `backend/app/services/dora_service.py`
- Test: `backend/tests/services/test_dora_service.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from datetime import datetime, timezone, timedelta
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.services import dora_service

UTC = timezone.utc

async def _build(db, tenant_id, commit_dt, subsystem_id=1):
    b = Build(tenant_id=tenant_id, subsystem_id=subsystem_id, git_sha="a"*40,
              build_number="1", commit_timestamp=commit_dt, status="success")
    db.add(b); await db.flush(); return b

async def _deploy(db, tenant_id, build_id, env_id, deployed_dt, status="success", release_id=None):
    d = Deployment(tenant_id=tenant_id, build_id=build_id, environment_id=env_id,
                   release_id=release_id, change_request_id=1, event_id=f"e{deployed_dt.timestamp()}",
                   deployed_at=deployed_dt, status=status, custom_fields={})
    db.add(d); await db.flush(); return d


@pytest.mark.asyncio
async def test_deployment_frequency_counts_only_success_in_window(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b = await _build(db_session, tenant.id, t0 - timedelta(days=1))
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success")
    await _deploy(db_session, tenant.id, b.id, 1, t0 + timedelta(days=1), "success")
    await _deploy(db_session, tenant.id, b.id, 1, t0 + timedelta(days=2), "failed")     # excluded
    await _deploy(db_session, tenant.id, b.id, 1, t0 + timedelta(days=40), "success")   # out of window
    res = await dora_service.deployment_frequency(
        db_session, tenant.id, t0, t0 + timedelta(days=7), granularity="week")
    assert res["total"] == 2
    assert sum(p["count"] for p in res["series"]) == 2


@pytest.mark.asyncio
async def test_deployment_frequency_env_filter(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b = await _build(db_session, tenant.id, t0 - timedelta(days=1))
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success")
    await _deploy(db_session, tenant.id, b.id, 2, t0, "success")
    res = await dora_service.deployment_frequency(
        db_session, tenant.id, t0, t0 + timedelta(days=7), environment_id=1)
    assert res["total"] == 1


@pytest.mark.asyncio
async def test_lead_time_median_over_success(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b1 = await _build(db_session, tenant.id, t0 - timedelta(hours=2))
    b2 = await _build(db_session, tenant.id, t0 - timedelta(hours=4))
    await _deploy(db_session, tenant.id, b1.id, 1, t0, "success")   # 2h
    await _deploy(db_session, tenant.id, b2.id, 1, t0, "success")   # 4h
    res = await dora_service.lead_time(db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=1))
    assert res["count"] == 2
    assert res["median_seconds"] == 3 * 3600  # median of 2h,4h


@pytest.mark.asyncio
async def test_lead_time_clamps_clock_skew(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b = await _build(db_session, tenant.id, t0 + timedelta(hours=1))  # commit AFTER deploy
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success")
    res = await dora_service.lead_time(db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=1))
    assert res["median_seconds"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/services/test_dora_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.dora_service`.

- [ ] **Step 3: Implement DF + Lead Time**

Create `backend/app/services/dora_service.py`:

```python
from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.build import Build
from app.db.models.deployment import Deployment


def _bucket_start(dt: datetime, granularity: str) -> str:
    d = dt.date()
    if granularity == "day":
        start = d
    elif granularity == "month":
        start = d.replace(day=1)
    else:  # week, Monday-start
        start = d - timedelta(days=d.weekday())
    return start.isoformat()


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


async def deployment_frequency(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    conds = [
        Deployment.tenant_id == tenant_id, Deployment.deleted_at.is_(None),
        Deployment.status == "success",
        Deployment.deployed_at >= date_from, Deployment.deployed_at <= date_to,
    ]
    if environment_id is not None:
        conds.append(Deployment.environment_id == environment_id)
    if release_id is not None:
        conds.append(Deployment.release_id == release_id)
    rows = (await db.execute(select(Deployment.deployed_at).where(*conds))).scalars().all()
    buckets: dict[str, int] = {}
    for dep_at in rows:
        buckets[_bucket_start(dep_at, granularity)] = buckets.get(_bucket_start(dep_at, granularity), 0) + 1
    series = [{"period": k, "count": v} for k, v in sorted(buckets.items())]
    return {"total": len(rows), "series": series}


async def lead_time(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    conds = [
        Deployment.tenant_id == tenant_id, Deployment.deleted_at.is_(None),
        Deployment.status == "success",
        Deployment.deployed_at >= date_from, Deployment.deployed_at <= date_to,
    ]
    if environment_id is not None:
        conds.append(Deployment.environment_id == environment_id)
    if release_id is not None:
        conds.append(Deployment.release_id == release_id)
    rows = (await db.execute(
        select(Deployment.deployed_at, Build.commit_timestamp)
        .join(Build, Build.id == Deployment.build_id)
        .where(*conds)
    )).all()
    per_bucket: dict[str, list[float]] = {}
    all_vals: list[float] = []
    for deployed_at, commit_ts in rows:
        lead = max(0.0, (deployed_at - commit_ts).total_seconds())
        all_vals.append(lead)
        per_bucket.setdefault(_bucket_start(deployed_at, granularity), []).append(lead)
    all_sorted = sorted(all_vals)
    series = [
        {"period": k, "median_seconds": median(v)} for k, v in sorted(per_bucket.items())
    ]
    return {
        "median_seconds": median(all_sorted) if all_sorted else 0,
        "p90_seconds": _percentile(all_sorted, 0.9),
        "count": len(all_vals),
        "series": series,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/services/test_dora_service.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/dora_service.py backend/tests/services/test_dora_service.py
git commit -m "feat(dora): deployment frequency + lead time calculators (Phase 5 SP2)"
```

---

## Task 3: `dora_service` — Change Failure Rate (TDD)

**Files:**
- Modify: `backend/app/services/dora_service.py`
- Test: append to `backend/tests/services/test_dora_service.py`

- [ ] **Step 1: Write the failing tests** (append; add imports at top of the test file)

```python
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.incident import Incident

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

async def _closed_release(db, tenant_id, tpl_id, status, close_dt, with_deploy=True):
    r = Release(tenant_id=tenant_id, name="R", release_kind="project",
                lifecycle_template_id=tpl_id, status=status)
    db.add(r); await db.flush()
    db.add(ReleaseStatusHistory(tenant_id=tenant_id, release_id=r.id, to_state=status, changed_at=close_dt))
    if with_deploy:
        b = await _build(db, tenant_id, close_dt - timedelta(days=1))
        await _deploy(db, tenant_id, b.id, 1, close_dt, "success", release_id=r.id)
    await db.flush(); return r


@pytest.mark.asyncio
async def test_cfr_counts_failed_state_and_causal_incident(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # shipped + completed cleanly -> denominator only
    await _closed_release(db_session, tenant.id, tpl.id, "completed", t0)
    # shipped + backed_out (is_failed) -> failure
    await _closed_release(db_session, tenant.id, tpl.id, "backed_out", t0 + timedelta(days=1))
    # shipped + completed but has a causal incident -> failure
    r3 = await _closed_release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=2))
    db_session.add(Incident(tenant_id=tenant.id, title="x", severity="P1", status="new",
                            detected_at=t0 + timedelta(days=2), release_id=r3.id, source="manual"))
    # closed but NO deployment -> excluded from denominator
    await _closed_release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=3), with_deploy=False)
    await db_session.flush()
    res = await dora_service.change_failure_rate(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["shipped_count"] == 3
    assert res["failed_count"] == 2
    assert abs(res["rate"] - (2/3)) < 1e-9


@pytest.mark.asyncio
async def test_cfr_zero_when_no_shipped(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    res = await dora_service.change_failure_rate(db_session, tenant.id, t0, t0 + timedelta(days=1))
    assert res == {"rate": 0.0, "failed_count": 0, "shipped_count": 0}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/services/test_dora_service.py -k cfr -q`
Expected: FAIL — no attribute `change_failure_rate`.

- [ ] **Step 3: Implement CFR** (append to `dora_service.py`; add imports)

```python
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.incident import Incident


async def change_failure_rate(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
) -> dict:
    # Terminal-close date per release: latest history row whose to_state == release.status.
    rel_conds = [Release.tenant_id == tenant_id, Release.deleted_at.is_(None)]
    if release_id is not None:
        rel_conds.append(Release.id == release_id)
    releases = (await db.execute(select(Release).where(*rel_conds))).scalars().all()

    # Memoize template definitions by id.
    tpl_cache: dict[int, dict] = {}
    async def _definition(tid: int) -> dict:
        if tid not in tpl_cache:
            tpl = (await db.execute(select(LifecycleTemplate).where(LifecycleTemplate.id == tid))).scalar_one_or_none()
            tpl_cache[tid] = tpl.definition if tpl else {"states": []}
        return tpl_cache[tid]

    # Releases with >=1 deployment (shipped), optionally env-filtered.
    dep_conds = [Deployment.tenant_id == tenant_id, Deployment.deleted_at.is_(None), Deployment.release_id.isnot(None)]
    if environment_id is not None:
        dep_conds.append(Deployment.environment_id == environment_id)
    shipped_ids = set((await db.execute(select(Deployment.release_id).where(*dep_conds))).scalars().all())

    shipped = 0
    failed = 0
    for r in releases:
        if r.id not in shipped_ids:
            continue
        definition = await _definition(r.lifecycle_template_id)
        state = next((s for s in definition.get("states", []) if s["key"] == r.status), None)
        if state is None or not state.get("is_terminal"):
            continue  # not closed
        # close date = latest history changed_at into the current status; fallback actual_date
        close_at = (await db.execute(
            select(ReleaseStatusHistory.changed_at).where(
                ReleaseStatusHistory.release_id == r.id,
                ReleaseStatusHistory.to_state == r.status,
            ).order_by(ReleaseStatusHistory.changed_at.desc()).limit(1)
        )).scalars().first() or r.actual_date
        if close_at is None or not (date_from <= close_at <= date_to):
            continue
        shipped += 1
        is_failed_state = bool(state.get("is_failed"))
        has_causal_incident = (await db.execute(
            select(Incident.id).where(
                Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None),
                Incident.release_id == r.id,
                Incident.detected_at >= date_from, Incident.detected_at <= date_to,
            ).limit(1)
        )).scalars().first() is not None
        if is_failed_state or has_causal_incident:
            failed += 1
    rate = (failed / shipped) if shipped else 0.0
    return {"rate": rate, "failed_count": failed, "shipped_count": shipped}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/services/test_dora_service.py -k cfr -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/dora_service.py backend/tests/services/test_dora_service.py
git commit -m "feat(dora): release-based change failure rate (Phase 5 SP2)"
```

---

## Task 4: `dora_service` — MTTR + summary (TDD)

**Files:**
- Modify: `backend/app/services/dora_service.py`
- Test: append to `backend/tests/services/test_dora_service.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
@pytest.mark.asyncio
async def test_mttr_mean_over_resolved_in_window(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    db_session.add(Incident(tenant_id=tenant.id, title="a", severity="P1", status="resolved",
                            detected_at=t0, resolved_at=t0 + timedelta(hours=2), source="manual"))
    db_session.add(Incident(tenant_id=tenant.id, title="b", severity="P2", status="resolved",
                            detected_at=t0, resolved_at=t0 + timedelta(hours=4), source="manual"))
    db_session.add(Incident(tenant_id=tenant.id, title="c", severity="P3", status="new",
                            detected_at=t0, resolved_at=None, source="manual"))  # unresolved -> excluded
    await db_session.flush()
    res = await dora_service.mttr(db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=1))
    assert res["count"] == 2
    assert res["mean_seconds"] == 3 * 3600


@pytest.mark.asyncio
async def test_summary_bundles_all_four(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    res = await dora_service.dora_summary(db_session, tenant.id, t0, t0 + timedelta(days=1))
    assert set(res) == {"deployment_frequency", "lead_time", "change_failure_rate", "mttr"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/services/test_dora_service.py -k "mttr or summary" -q`
Expected: FAIL — no attribute `mttr`.

- [ ] **Step 3: Implement MTTR + summary** (append)

```python
async def mttr(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    conds = [
        Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None),
        Incident.resolved_at.isnot(None),
        Incident.resolved_at >= date_from, Incident.resolved_at <= date_to,
    ]
    if release_id is not None:
        conds.append(Incident.release_id == release_id)
    rows = (await db.execute(
        select(Incident.detected_at, Incident.resolved_at).where(*conds)
    )).all()
    per_bucket: dict[str, list[float]] = {}
    vals: list[float] = []
    for detected_at, resolved_at in rows:
        secs = max(0.0, (resolved_at - detected_at).total_seconds())
        vals.append(secs)
        per_bucket.setdefault(_bucket_start(resolved_at, granularity), []).append(secs)
    series = [{"period": k, "mean_seconds": sum(v) / len(v)} for k, v in sorted(per_bucket.items())]
    return {
        "mean_seconds": (sum(vals) / len(vals)) if vals else 0,
        "median_seconds": median(sorted(vals)) if vals else 0,
        "count": len(vals),
        "series": series,
    }


async def dora_summary(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    return {
        "deployment_frequency": await deployment_frequency(db, tenant_id, date_from, date_to, environment_id, release_id, granularity),
        "lead_time": await lead_time(db, tenant_id, date_from, date_to, environment_id, release_id, granularity),
        "change_failure_rate": await change_failure_rate(db, tenant_id, date_from, date_to, environment_id, release_id),
        "mttr": await mttr(db, tenant_id, date_from, date_to, environment_id, release_id, granularity),
    }
```

Note: MTTR intentionally ignores `environment_id` (incidents aren't environment-filtered in this sub-project); the param is accepted for signature symmetry. Document this in a comment.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/services/test_dora_service.py -q`
Expected: PASS (all — 8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/dora_service.py backend/tests/services/test_dora_service.py
git commit -m "feat(dora): mttr + summary bundler (Phase 5 SP2)"
```

---

## Task 5: API endpoints + router mount + tenant isolation (TDD)

**Files:**
- Create: `backend/app/api/v1/metrics.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_dora_api.py`

- [ ] **Step 1: Write the failing integration tests** (mirror the auth-client fixture used by `tests/integration/test_incidents_api.py`)

```python
import pytest


@pytest.mark.asyncio
async def test_dora_summary_endpoint(authed_client):
    r = await authed_client.get("/api/v1/metrics/dora",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"deployment_frequency", "lead_time", "change_failure_rate", "mttr"}


@pytest.mark.asyncio
async def test_dora_requires_dates(authed_client):
    r = await authed_client.get("/api/v1/metrics/dora")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dora_export_csv(authed_client):
    r = await authed_client.get("/api/v1/metrics/dora/export",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_dora_api.py -q`
Expected: FAIL — 404 (router not mounted).

- [ ] **Step 3: Implement the router**

Create `backend/app/api/v1/metrics.py`:

```python
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import dora_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/dora")
async def get_dora(
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    environment_id: int | None = None,
    release_id: int | None = None,
    granularity: str = "week",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await dora_service.dora_summary(
        db, current_user.active_tenant_id, date_from, date_to,
        environment_id, release_id, granularity,
    )


@router.get("/dora/export")
async def export_dora(
    date_from: datetime = Query(...),
    date_to: datetime = Query(...),
    environment_id: int | None = None,
    release_id: int | None = None,
    granularity: str = "week",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    summary = await dora_service.dora_summary(
        db, current_user.active_tenant_id, date_from, date_to,
        environment_id, release_id, granularity,
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["metric", "period", "value"])
    for p in summary["deployment_frequency"]["series"]:
        w.writerow(["deployment_frequency", p["period"], p["count"]])
    for p in summary["lead_time"]["series"]:
        w.writerow(["lead_time_median_seconds", p["period"], p["median_seconds"]])
    for p in summary["mttr"]["series"]:
        w.writerow(["mttr_mean_seconds", p["period"], p["mean_seconds"]])
    cfr = summary["change_failure_rate"]
    w.writerow(["change_failure_rate", "window", cfr["rate"]])
    w.writerow(["cfr_failed_count", "window", cfr["failed_count"]])
    w.writerow(["cfr_shipped_count", "window", cfr["shipped_count"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dora-metrics.csv"},
    )
```

- [ ] **Step 4: Mount the router** — in `backend/app/main.py`, alongside the incidents mount:

```python
from app.api.v1 import metrics as metrics_router
app.include_router(metrics_router.router, prefix="/api/v1")
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/integration/test_dora_api.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Add a tenant-isolation test** (append to the test file)

```python
@pytest.mark.asyncio
async def test_dora_is_tenant_scoped(authed_client, other_tenant_deployment_in_window):
    # A deployment belonging to another tenant must not affect this tenant's DF total.
    r = await authed_client.get("/api/v1/metrics/dora",
                                params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert r.status_code == 200
    assert r.json()["deployment_frequency"]["total"] == 0
```

Build `other_tenant_deployment_in_window` by creating a second tenant + a success deployment via the models/services (mirror the second-tenant fixture pattern from `tests/integration/test_incident_tenant_isolation.py`). If that fixture pattern isn't readily reusable, assert isolation at the service layer instead (call `dora_service.deployment_frequency` with `tenant.id` after inserting another tenant's deployment) — keep the isolation assertion.

- [ ] **Step 7: Run + commit**

Run: `uv run pytest tests/integration/test_dora_api.py -q` → PASS.

```bash
git add backend/app/api/v1/metrics.py backend/app/main.py backend/tests/integration/test_dora_api.py
git commit -m "feat(dora): metrics API (summary + CSV export) with tenant isolation (Phase 5 SP2)"
```

---

## Task 6: Backfill script for `is_failed` on existing tenants

**Files:**
- Create: `backend/scripts/backfill_release_failed_flags.py`

- [ ] **Step 1: Implement** (mirror `scripts/backfill_incident_lifecycles.py`)

```python
"""Backfill: set is_failed on default release lifecycle terminal states for existing tenants.

Run once after Phase 5 SP2 lands. Idempotent — only touches the known default state keys
(completed_with_issues, backed_out) on release templates; leaves customized states alone.

Usage:
    cd backend
    uv run python scripts/backfill_release_failed_flags.py
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.lifecycle import LifecycleTemplate

FAILED_KEYS = {"completed_with_issues", "backed_out"}


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    updated = 0
    async with sessionmaker() as db:
        tpls = (await db.execute(
            select(LifecycleTemplate).where(LifecycleTemplate.entity_type == "release")
        )).scalars().all()
        for tpl in tpls:
            definition = dict(tpl.definition or {})
            states = definition.get("states", [])
            changed = False
            for s in states:
                if s.get("key") in FAILED_KEYS and s.get("is_terminal") and not s.get("is_failed"):
                    s["is_failed"] = True
                    changed = True
            if changed:
                definition["states"] = states
                tpl.definition = definition
                # JSON column: reassign so SQLAlchemy detects the change
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(tpl, "definition")
                updated += 1
        await db.commit()
    await engine.dispose()
    print(f"Updated is_failed on {updated} release lifecycle templates.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify it runs (idempotent) against the dev DB**

Run: `DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/backfill_release_failed_flags.py`
Expected: prints "Updated is_failed on N release lifecycle templates." Running twice → second run reports 0.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/backfill_release_failed_flags.py
git commit -m "chore(dora): backfill is_failed on existing tenants' release lifecycles (Phase 5 SP2)"
```

---

## Task 7: Frontend types + service

**Files:**
- Create: `frontend/src/types/dora.ts`, `frontend/src/services/doraService.ts`

- [ ] **Step 1: Types** — `frontend/src/types/dora.ts`:

```ts
export interface SeriesPoint { period: string; [metric: string]: number | string; }

export interface DeploymentFrequency { total: number; series: { period: string; count: number }[]; }
export interface LeadTime { median_seconds: number; p90_seconds: number; count: number; series: { period: string; median_seconds: number }[]; }
export interface ChangeFailureRate { rate: number; failed_count: number; shipped_count: number; }
export interface Mttr { mean_seconds: number; median_seconds: number; count: number; series: { period: string; mean_seconds: number }[]; }

export interface DoraSummary {
  deployment_frequency: DeploymentFrequency;
  lead_time: LeadTime;
  change_failure_rate: ChangeFailureRate;
  mttr: Mttr;
}

export interface DoraParams {
  date_from: string;
  date_to: string;
  environment_id?: number;
  release_id?: number;
  granularity?: 'day' | 'week' | 'month';
}
```

- [ ] **Step 2: Service** — `frontend/src/services/doraService.ts` (match the default-`api` import style of `releaseService.ts`; baseURL is already `/api/v1`):

```ts
import api from './api';
import type { DoraSummary, DoraParams } from '../types/dora';

export const doraService = {
  getSummary: (params: DoraParams) =>
    api.get<DoraSummary>('/metrics/dora', { params }).then((r) => r.data),
  exportUrl: (params: DoraParams) => {
    const q = new URLSearchParams(params as Record<string, string>).toString();
    return `/api/v1/metrics/dora/export?${q}`;
  },
};
```

- [ ] **Step 3: Type-check + commit**

Run: `npx tsc --noEmit` → PASS.

```bash
git add frontend/src/types/dora.ts frontend/src/services/doraService.ts
git commit -m "feat(dora): frontend types + service (Phase 5 SP2)"
```

---

## Task 8: DORA dashboard page + route + nav

**Files:**
- Create: `frontend/src/pages/insights/DoraDashboard.tsx`
- Modify: `frontend/src/components/navConfig.tsx`, `frontend/src/App.tsx`

- [ ] **Step 1: Implement the dashboard** — `frontend/src/pages/insights/DoraDashboard.tsx`. Mirror `src/pages/releases/ReleaseAnalytics.tsx` (local `useState` for filters + fetched `DoraSummary`, `useEffect` calling `doraService.getSummary`, cards + `DataTable`). Build:
  - Filter bar: `date_from`/`date_to` (default last 90 days, same `isoDate` helper as ReleaseAnalytics), environment (MUI Select fed by `environmentService.listEnvironments` — optional "All"), release (optional Autocomplete via `releaseService.list`), granularity (day/week/month Select, default week).
  - Four MUI `Card`s: **Deployment Frequency** (`total`, and avg/period), **Lead Time** (`median_seconds` humanized via a `formatDuration(seconds)` helper — e.g. "2d 4h"; show p90), **Change Failure Rate** (`(rate*100).toFixed(1)%` + `failed_count/shipped_count`; if `shipped_count===0` show "No shipped changes in range"), **MTTR** (`mean_seconds` humanized; show count).
  - A `DataTable` trend: merge the three per-bucket series (`deployment_frequency.series`, `lead_time.series`, `mttr.series`) by `period` into rows with columns: Period, Deployments, Lead Time (median, humanized), MTTR (mean, humanized). Rows sorted by period.
  - An **Export CSV** button: `window.open(doraService.exportUrl(params))` (or an anchor with the export URL).
  - Add a small local `formatDuration(seconds: number): string` helper (days/hours/minutes) at the top of the file.
- [ ] **Step 2: Route** — in `src/App.tsx`, add `import DoraDashboard` and a route `path="/insights/dora"` rendering `<DoraDashboard />` (place near other `/insights/*` or top-level routes).
- [ ] **Step 3: Un-gate nav** — in `src/components/navConfig.tsx`, change the DORA entry from `comingSoon: true` to remove the `comingSoon` flag (so it becomes a live link to `/insights/dora`).
- [ ] **Step 4: Verify**

Run: `npx tsc --noEmit` → PASS.
Run: `npx vitest run src/store` → PASS (sanity, no regressions).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/insights/DoraDashboard.tsx frontend/src/App.tsx frontend/src/components/navConfig.tsx
git commit -m "feat(dora): DORA dashboard page + route + nav (Phase 5 SP2)"
```

---

## Task 9: Admin — "Counts as failure" checkbox on terminal states

**Files:**
- Modify: `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`

- [ ] **Step 1: Implement** — In `LifecycleTemplatesPanel.tsx`, locate where a lifecycle **state** row is edited (states carry `key/label/is_initial/is_terminal`). For states where `is_terminal` is true, add a `FormControlLabel` + `Checkbox` labelled "Counts as failure" bound to the state's `is_failed` boolean; toggling it sets `state.is_failed` in the edited `definition` (persisted via the existing save path that PUTs the template). Only render the checkbox for terminal states (non-terminal states can't be failures). Follow the file's existing state-editing + Checkbox usage (it already imports `Checkbox`/`FormControlLabel`).

- [ ] **Step 2: Verify + commit**

Run: `npx tsc --noEmit` → PASS.

```bash
git add frontend/src/components/admin/LifecycleTemplatesPanel.tsx
git commit -m "feat(dora): admin 'counts as failure' flag on terminal lifecycle states (Phase 5 SP2)"
```

---

## Task 10: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Backend suite**

Run: `uv run --directory /Users/peter/Developer/Code/projects/envmgr/backend pytest tests/ -q`
Expected: all pass (1 pre-existing skip acceptable).

- [ ] **Step 2: Frontend**

Run (from `frontend/`): `npx tsc --noEmit` → clean; `npx vitest run --exclude 'e2e/**'` → pass.

- [ ] **Step 3: Manual eyeball (human)** — Browser automation is flaky here; hand to the user:
  - Backfill dev tenants: `DATABASE_URL=... PYTHONPATH=. uv run python scripts/backfill_release_failed_flags.py`.
  - Open **Insights → DORA Metrics** → the four cards populate for the last 90 days; change the date range/granularity and confirm numbers + the trend table update.
  - Export CSV downloads with the expected rows.
  - In tenant admin, open a release lifecycle template → a terminal state shows "Counts as failure"; toggling + saving persists.

---

## Self-Review Notes

- **Spec coverage:** DF + Lead Time (Task 2) ✓; release-based CFR with is_failed + causal incident + shipped denominator (Task 3) ✓; MTTR + summary (Task 4) ✓; on-demand/no-cache ✓; `is_failed` seed (Task 1) + admin checkbox (Task 9) + backfill (Task 6) ✓; API + CSV export + tenant isolation (Task 5) ✓; dashboard cards + trend table, no chart lib, un-gate nav (Task 8) ✓; types/service (Task 7) ✓; testing per metric + isolation ✓; manual eyeball (Task 10) ✓. Non-goals (cache, chart lib, project filter, PIR/health) excluded. **Deviation from spec:** no Redux `doraSlice` — the dashboard uses local state + direct service call, matching the `ReleaseAnalytics` precedent (simpler, consistent); noted in the plan header.
- **Type consistency:** `dora_summary` returns keys `deployment_frequency`/`lead_time`/`change_failure_rate`/`mttr` — matched by the API, the CSV writer, the TS `DoraSummary`, and the dashboard. Metric field names (`total`, `series[].count`, `median_seconds`, `p90_seconds`, `rate`/`failed_count`/`shipped_count`, `mean_seconds`) are identical across service, tests, TS types, and dashboard. `change_failure_rate` takes no `granularity` (window-based) everywhere it's called.
- **Assumptions flagged in-task:** the authed-client + second-tenant fixture names (Task 5), the exact state-editing spot in `LifecycleTemplatesPanel` (Task 9), and route placement (Task 8) — each says to mirror the named existing file.
