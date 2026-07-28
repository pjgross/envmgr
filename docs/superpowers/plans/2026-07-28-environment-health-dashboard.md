# Environment Health Dashboard (Phase 5 SP3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture per-environment operational health samples via an API-key push endpoint, and present a health dashboard (traffic-light grid + computed alert banner) plus an environment-detail health section, correlating health with active bookings and planned change-request outages.

**Architecture:** A new append-only `EnvironmentHealthStatus` time-series; a tenant-scoped `environment_health_service` computes current status (with a 15-min staleness rule), the active booking, the planned outage, and a derived alert — all on-demand. The push endpoint authenticates with an API key; the dashboard/history endpoints use JWT. Frontend follows the local-state + direct-service pattern (like `DoraDashboard`), no Redux slice, no charting library.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest; React 18 + TS strict + MUI + `@mui/x-data-grid`; vitest.

**Spec:** `docs/superpowers/specs/2026-07-28-environment-health-dashboard-design.md`

---

## Reference facts (verified)

- **`api_key_auth(required_scope)`** (`app/core/security.py:139`) is a dependency factory reading the `X-Api-Key` header; it returns the authenticated `ApiKey` row, which has `.tenant_id` and `.scopes`. Use `key = Depends(api_key_auth("environment:health"))` → `key.tenant_id`.
- **`Environment`**: `name`, `environment_type`, `status` (`EnvironmentStatus` enum: active/inactive/maintenance/**decommissioned** — string values), `tenant_id`, `deleted_at`.
- **`Booking`**: `environment_id`, `start_date`, `end_date`, `status` (starts `draft`), `tenant_id`, `deleted_at`. Booking display field: `project_name` (confirm it exists on the model during Task 4; the booking dialogs use it).
- **`ChangeRequest`**: `has_outage`, `outage_start`, `outage_end`, `scheduled_start`, `scheduled_end`, `status`, `deleted_at`; linked to environments via **`ChangeRequestEnvironment`** (`change_request_environment`: `change_request_id`, `environment_id`).
- Conventions: `db.flush()` not commit; every query filters `tenant_id`; migrations manual (`op.create_table`); enum-ish columns are `String`. SQLite tests return **naive** datetimes — normalize with a `_utc()` helper before comparing to an aware `now` (same pattern as `dora_service`).
- Router mount idiom (`app/main.py`): follow incidents/metrics — router declares its own prefix, mounted at `/api/v1`.
- Frontend analytics precedent: `DoraDashboard.tsx` / `ReleaseAnalytics.tsx` — local `useState` + direct service, cards/`DataTable`, no slice.
- Backend cmds from `backend/` (`uv run pytest`, `uv run python`); frontend from `frontend/` (`npx`).

---

## File Structure

**Backend — create:** `app/db/models/environment_health.py`, `app/api/v1/schemas/environment_health.py`, `app/services/environment_health_service.py`, `app/api/v1/environment_health.py`, `alembic/versions/<rev>_environment_health.py`, tests `tests/services/test_environment_health_service.py`, `tests/integration/test_environment_health_api.py`.
**Backend — modify:** `app/db/models/__init__.py`, `app/main.py`.
**Frontend — create:** `src/types/environmentHealth.ts`, `src/services/environmentHealthService.ts`, `src/pages/insights/HealthDashboard.tsx`, plus an env-detail health section component.
**Frontend — modify:** `src/components/navConfig.tsx`, `src/App.tsx`, the Environment detail page.

---

## Task 1: `EnvironmentHealthStatus` model + migration

**Files:**
- Create: `backend/app/db/models/environment_health.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: `backend/alembic/versions/<rev>_environment_health.py`

- [ ] **Step 1: Write the model** — `backend/app/db/models/environment_health.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentHealthStatus(Base):
    __tablename__ = "environment_health_status"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environment.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # up | down | issue
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_env_health_tenant_env_recorded", "tenant_id", "environment_id", "recorded_at"),
    )
```

- [ ] **Step 2: Register** in `backend/app/db/models/__init__.py` (match existing import/`__all__` style):

```python
from app.db.models.environment_health import EnvironmentHealthStatus  # noqa: F401
```

- [ ] **Step 3: Migration** — `alembic revision -m "environment health status"`, then manual DDL:

```python
def upgrade() -> None:
    op.create_table(
        "environment_health_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_env_health_tenant_id", "environment_health_status", ["tenant_id"])
    op.create_index("ix_env_health_environment_id", "environment_health_status", ["environment_id"])
    op.create_index("ix_env_health_tenant_env_recorded", "environment_health_status",
                    ["tenant_id", "environment_id", "recorded_at"])


def downgrade() -> None:
    op.drop_table("environment_health_status")
```

- [ ] **Step 4: Apply + verify**

Run: `alembic upgrade head` (if it errors with DuplicateTable because `init_db` create_all already made it — the known project quirk — `alembic stamp head` and confirm the table exists, mirroring how the incident-tables migration was handled).
Run: `uv run python -c "from app.db.models import EnvironmentHealthStatus; print('ok')"` → `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models/environment_health.py backend/app/db/models/__init__.py backend/alembic/versions/
git commit -m "feat(health): EnvironmentHealthStatus model & migration (Phase 5 SP3)"
```

---

## Task 2: Schemas

**Files:**
- Create: `backend/app/api/v1/schemas/environment_health.py`

- [ ] **Step 1: Write schemas** (Pydantic v2, `ConfigDict(from_attributes=True)` on responses):

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

HEALTH_STATUSES = {"up", "down", "issue"}


class HealthSampleCreate(BaseModel):
    status: str
    source: str
    detail: Optional[str] = None
    recorded_at: Optional[datetime] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in HEALTH_STATUSES:
            raise ValueError(f"status must be one of {sorted(HEALTH_STATUSES)}")
        return v


class HealthSample(BaseModel):
    id: int
    environment_id: int
    status: str
    recorded_at: datetime
    source: str
    detail: Optional[str]
    model_config = ConfigDict(from_attributes=True)


class ActiveBookingSummary(BaseModel):
    project_name: str
    start_date: datetime
    end_date: datetime


class EnvironmentHealthOverviewRow(BaseModel):
    environment_id: int
    environment_name: str
    current_status: str                    # up | down | issue | unknown
    last_recorded_at: Optional[datetime]
    active_booking: bool
    active_booking_summary: Optional[ActiveBookingSummary]
    planned_outage: bool
    alert: bool
```

- [ ] **Step 2: Verify import + commit**

Run: `uv run python -c "import app.api.v1.schemas.environment_health; print('ok')"` → `ok`.

```bash
git add backend/app/api/v1/schemas/environment_health.py
git commit -m "feat(health): schemas (Phase 5 SP3)"
```

---

## Task 3: `environment_health_service` — record + history + status derivation (TDD)

**Files:**
- Create: `backend/app/services/environment_health_service.py`
- Test: `backend/tests/services/test_environment_health_service.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.db.models.environment import Environment
from app.services import environment_health_service as svc

UTC = timezone.utc

async def _env(db, tenant_id, name="Env A", status="active"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="SIT", status=status)
    db.add(e); await db.flush(); return e


@pytest.mark.asyncio
async def test_record_sample_defaults_recorded_at(db_session, tenant):
    env = await _env(db_session, tenant.id)
    row = await svc.record_sample(db_session, tenant.id, env.id, "up", "pingdom")
    assert row.status == "up" and row.source == "pingdom" and row.recorded_at is not None


@pytest.mark.asyncio
async def test_record_sample_rejects_other_tenant_env(db_session, tenant):
    with pytest.raises(HTTPException) as e:
        await svc.record_sample(db_session, tenant.id, 999999, "up", "x")
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_history_newest_first(db_session, tenant):
    env = await _env(db_session, tenant.id)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    await svc.record_sample(db_session, tenant.id, env.id, "up", "x", recorded_at=t0)
    await svc.record_sample(db_session, tenant.id, env.id, "down", "x", recorded_at=t0 + timedelta(minutes=5))
    hist = await svc.get_history(db_session, tenant.id, env.id)
    assert [h.status for h in hist] == ["down", "up"]


@pytest.mark.asyncio
async def test_derive_status_fresh_stale_and_none(db_session, tenant):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    env = await _env(db_session, tenant.id)
    # no samples -> unknown
    ov = await svc.health_overview(db_session, tenant.id, now=now)
    assert ov[0]["current_status"] == "unknown"
    # fresh sample -> its status
    await svc.record_sample(db_session, tenant.id, env.id, "down", "x", recorded_at=now - timedelta(minutes=5))
    ov = await svc.health_overview(db_session, tenant.id, now=now)
    assert ov[0]["current_status"] == "down"
    # stale sample (>15m) -> unknown
    ov = await svc.health_overview(db_session, tenant.id, now=now + timedelta(minutes=20))
    assert ov[0]["current_status"] == "unknown"
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/services/test_environment_health_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.environment_health_service`.

- [ ] **Step 3: Implement the service (record/history/derivation + overview skeleton)**

`backend/app/services/environment_health_service.py`:

```python
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment
from app.db.models.environment_health import EnvironmentHealthStatus

STALE_AFTER = timedelta(minutes=15)
INACTIVE_BOOKING_STATUSES = {"draft", "cancelled", "rejected"}
INACTIVE_CR_STATUSES = {"cancelled", "rejected"}


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def record_sample(db: AsyncSession, tenant_id: int, environment_id: int,
                        status: str, source: str, detail: Optional[str] = None,
                        recorded_at: Optional[datetime] = None) -> EnvironmentHealthStatus:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id, Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if env is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Environment not found")
    row = EnvironmentHealthStatus(
        tenant_id=tenant_id, environment_id=environment_id, status=status, source=source,
        detail=detail, recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


async def get_history(db: AsyncSession, tenant_id: int, environment_id: int, limit: int = 50):
    limit = max(1, min(limit, 500))
    return list((await db.execute(
        select(EnvironmentHealthStatus).where(
            EnvironmentHealthStatus.tenant_id == tenant_id,
            EnvironmentHealthStatus.environment_id == environment_id,
        ).order_by(EnvironmentHealthStatus.recorded_at.desc()).limit(limit)
    )).scalars().all())


async def _latest(db, tenant_id, environment_id) -> Optional[EnvironmentHealthStatus]:
    return (await db.execute(
        select(EnvironmentHealthStatus).where(
            EnvironmentHealthStatus.tenant_id == tenant_id,
            EnvironmentHealthStatus.environment_id == environment_id,
        ).order_by(EnvironmentHealthStatus.recorded_at.desc()).limit(1)
    )).scalars().first()


def _derive_status(latest: Optional[EnvironmentHealthStatus], now: datetime):
    if latest is None:
        return "unknown", None
    rec = _utc(latest.recorded_at)
    if now - rec > STALE_AFTER:
        return "unknown", rec
    return latest.status, rec


async def health_overview(db: AsyncSession, tenant_id: int, now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    envs = (await db.execute(select(Environment).where(
        Environment.tenant_id == tenant_id, Environment.deleted_at.is_(None),
        Environment.status != "decommissioned",
    ).order_by(Environment.name.asc()))).scalars().all()
    rows = []
    for env in envs:
        current, last_at = _derive_status(await _latest(db, tenant_id, env.id), now)
        booking = await _active_booking(db, tenant_id, env.id, now)
        outage = await _planned_outage(db, tenant_id, env.id, now)
        alert = current in ("down", "issue") and booking is not None and not outage
        rows.append({
            "environment_id": env.id, "environment_name": env.name,
            "current_status": current, "last_recorded_at": last_at,
            "active_booking": booking is not None, "active_booking_summary": booking,
            "planned_outage": outage, "alert": alert,
        })
    return rows
```

(`_active_booking` and `_planned_outage` are added in Task 4 — for now the file won't import them; include stub definitions returning `None`/`False` so Task 3 tests pass, then replace in Task 4. Add at the end:)

```python
async def _active_booking(db, tenant_id, environment_id, now):  # replaced in Task 4
    return None


async def _planned_outage(db, tenant_id, environment_id, now):  # replaced in Task 4
    return False
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/services/test_environment_health_service.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_health_service.py backend/tests/services/test_environment_health_service.py
git commit -m "feat(health): record/history/status-derivation service (Phase 5 SP3)"
```

---

## Task 4: `environment_health_service` — active booking, planned outage, alert (TDD)

**Files:**
- Modify: `backend/app/services/environment_health_service.py`
- Test: append to `backend/tests/services/test_environment_health_service.py`

- [ ] **Step 1: Write the failing tests** (append; add imports)

```python
from app.db.models.booking import Booking
from app.db.models.change_request import ChangeRequest, ChangeRequestEnvironment

async def _booking(db, tenant_id, env_id, start, end, status="approved"):
    b = Booking(tenant_id=tenant_id, environment_id=env_id, start_date=start, end_date=end, status=status)
    db.add(b); await db.flush(); return b

async def _cr_outage(db, tenant_id, env_id, o_start, o_end, has_outage=True, status="approved"):
    cr = ChangeRequest(tenant_id=tenant_id, title="CR", change_type="standard", status=status,
                       lifecycle_id=_cr_tpl_id, scheduled_start=o_start, scheduled_end=o_end,
                       raised_by=_user_id, has_outage=has_outage, outage_start=o_start, outage_end=o_end)
    db.add(cr); await db.flush()
    db.add(ChangeRequestEnvironment(tenant_id=tenant_id, change_request_id=cr.id, environment_id=env_id))
    await db.flush(); return cr


@pytest.mark.asyncio
async def test_alert_truth_table(db_session, tenant, user):
    global _cr_tpl_id, _user_id
    _user_id = user.id
    # a change_request lifecycle template id for this tenant (seed/lookup):
    from app.db.models.lifecycle import LifecycleTemplate
    from sqlalchemy import select as _sel
    _cr_tpl_id = (await db_session.execute(_sel(LifecycleTemplate.id).where(
        LifecycleTemplate.tenant_id == tenant.id, LifecycleTemplate.entity_type == "change_request").limit(1))).scalars().first()
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    win = (now - timedelta(hours=1), now + timedelta(hours=1))

    async def overview_for(env):
        return next(r for r in await svc.health_overview(db_session, tenant.id, now=now) if r["environment_id"] == env.id)

    # down + active booking + no outage -> ALERT
    e1 = await _env(db_session, tenant.id, "e1")
    await svc.record_sample(db_session, tenant.id, e1.id, "down", "x", recorded_at=now)
    await _booking(db_session, tenant.id, e1.id, *win)
    assert (await overview_for(e1))["alert"] is True

    # down + active booking + planned outage -> no alert
    e2 = await _env(db_session, tenant.id, "e2")
    await svc.record_sample(db_session, tenant.id, e2.id, "down", "x", recorded_at=now)
    await _booking(db_session, tenant.id, e2.id, *win)
    await _cr_outage(db_session, tenant.id, e2.id, *win)
    assert (await overview_for(e2))["alert"] is False

    # up + active booking -> no alert
    e3 = await _env(db_session, tenant.id, "e3")
    await svc.record_sample(db_session, tenant.id, e3.id, "up", "x", recorded_at=now)
    await _booking(db_session, tenant.id, e3.id, *win)
    assert (await overview_for(e3))["alert"] is False

    # down + NO active booking -> no alert
    e4 = await _env(db_session, tenant.id, "e4")
    await svc.record_sample(db_session, tenant.id, e4.id, "down", "x", recorded_at=now)
    assert (await overview_for(e4))["alert"] is False

    # draft booking is not "active" -> down + draft booking -> no alert
    e5 = await _env(db_session, tenant.id, "e5")
    await svc.record_sample(db_session, tenant.id, e5.id, "down", "x", recorded_at=now)
    await _booking(db_session, tenant.id, e5.id, *win, status="draft")
    assert (await overview_for(e5))["alert"] is False
```

If `Booking` or `ChangeRequest` need additional required fields the DB rejects on flush, add them minimally (mirror how `tests/services/` build these rows elsewhere — e.g. `ChangeRequest` may need more columns; check `tests/services/test_change_request*` for the constructor).

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/services/test_environment_health_service.py -k alert -q`
Expected: FAIL — the stub `_active_booking`/`_planned_outage` make e1's alert False.

- [ ] **Step 3: Replace the stubs with real implementations**

In `environment_health_service.py`, replace the two stub functions and add imports at the top (`from app.db.models.booking import Booking`, `from app.db.models.change_request import ChangeRequest, ChangeRequestEnvironment`):

```python
async def _active_booking(db, tenant_id, environment_id, now):
    rows = (await db.execute(select(Booking).where(
        Booking.tenant_id == tenant_id, Booking.environment_id == environment_id,
        Booking.deleted_at.is_(None),
    ))).scalars().all()
    for b in rows:
        if b.status in INACTIVE_BOOKING_STATUSES:
            continue
        start, end = _utc(b.start_date), _utc(b.end_date)
        if start and end and start <= now <= end:
            return {"project_name": getattr(b, "project_name", None) or "Booking",
                    "start_date": start, "end_date": end}
    return None


async def _planned_outage(db, tenant_id, environment_id, now):
    rows = (await db.execute(
        select(ChangeRequest)
        .join(ChangeRequestEnvironment, ChangeRequestEnvironment.change_request_id == ChangeRequest.id)
        .where(
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequestEnvironment.environment_id == environment_id,
            ChangeRequest.deleted_at.is_(None),
            ChangeRequest.has_outage.is_(True),
        )
    )).scalars().all()
    for cr in rows:
        if cr.status in INACTIVE_CR_STATUSES:
            continue
        start = _utc(cr.outage_start) or _utc(cr.scheduled_start)
        end = _utc(cr.outage_end) or _utc(cr.scheduled_end)
        if start and end and start <= now <= end:
            return True
    return False
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/services/test_environment_health_service.py -q`
Expected: PASS (all — 5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_health_service.py backend/tests/services/test_environment_health_service.py
git commit -m "feat(health): active-booking + planned-outage + alert computation (Phase 5 SP3)"
```

---

## Task 5: API endpoints + router mount + tenant isolation (TDD)

**Files:**
- Create: `backend/app/api/v1/environment_health.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_environment_health_api.py`

- [ ] **Step 1: Write the failing integration tests** (mirror the `authed_client` + API-key fixtures used by existing integration tests; create an API key with the `environment:health` scope via `api_key_service` in the test setup — see how `tests/integration/` mints keys, or call `api_key_service.create_key`)

```python
import pytest


@pytest.mark.asyncio
async def test_health_push_with_api_key(authed_client, health_api_key, demo_environment_id):
    r = await authed_client.post(
        f"/api/v1/environments/{demo_environment_id}/health",
        json={"status": "down", "source": "pytest"},
        headers={"X-Api-Key": health_api_key},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "down"


@pytest.mark.asyncio
async def test_health_push_missing_key_401(authed_client, demo_environment_id):
    r = await authed_client.post(
        f"/api/v1/environments/{demo_environment_id}/health",
        json={"status": "up", "source": "x"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_health_overview_and_history(authed_client, health_api_key, demo_environment_id):
    await authed_client.post(f"/api/v1/environments/{demo_environment_id}/health",
                             json={"status": "issue", "source": "x"},
                             headers={"X-Api-Key": health_api_key})
    ov = await authed_client.get("/api/v1/environments/health")
    assert ov.status_code == 200
    assert any(r["environment_id"] == demo_environment_id for r in ov.json())
    hist = await authed_client.get(f"/api/v1/environments/{demo_environment_id}/health/history")
    assert hist.status_code == 200 and len(hist.json()) >= 1
```

Build the fixtures: `demo_environment_id` = create an Environment in the test tenant; `health_api_key` = mint an API key with scope `["environment:health"]` for that tenant via `api_key_service` and yield its raw token. Mirror the exact fixture/setup style already in `tests/integration/`.

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/integration/test_environment_health_api.py -q`
Expected: FAIL — 404 (routes not mounted).

- [ ] **Step 3: Implement the router**

`backend/app/api/v1/environment_health.py`:

```python
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, api_key_auth
from app.services import environment_health_service as svc
from app.api.v1.schemas.environment_health import (
    HealthSampleCreate, HealthSample, EnvironmentHealthOverviewRow,
)

router = APIRouter(prefix="/environments", tags=["environment-health"])


@router.post("/{env_id}/health", response_model=HealthSample, status_code=status.HTTP_201_CREATED)
async def push_health(
    env_id: int, data: HealthSampleCreate,
    db: AsyncSession = Depends(get_db),
    key=Depends(api_key_auth("environment:health")),
):
    return await svc.record_sample(db, key.tenant_id, env_id, data.status, data.source, data.detail, data.recorded_at)


@router.get("/{env_id}/health/history", response_model=list[HealthSample])
async def health_history(
    env_id: int, limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user),
):
    return await svc.get_history(db, current_user.active_tenant_id, env_id, limit)


@router.get("/health", response_model=list[EnvironmentHealthOverviewRow])
async def health_overview(
    db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user),
):
    return await svc.health_overview(db, current_user.active_tenant_id)
```

NOTE the route order: FastAPI matches in declaration order, so `/{env_id}/health` and `/{env_id}/health/history` must be declared such that `/health` (the collection overview) isn't shadowed by `/{env_id}`. Because `/health` has no path param and `/{env_id}/health/history` is more specific, declare `GET /health` LAST is fine — but to be safe, keep `/health` as its own segment (it is: `/environments/health` vs `/environments/{env_id}/health`). FastAPI distinguishes these correctly since `health` is a literal that won't coerce to the `int` `env_id`. Verify with the tests.

- [ ] **Step 4: Mount the router** — in `backend/app/main.py`, next to the metrics/incidents mounts:

```python
from app.api.v1 import environment_health as environment_health_router
app.include_router(environment_health_router.router, prefix="/api/v1")
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/integration/test_environment_health_api.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Add a tenant-isolation + scope test** (append)

```python
@pytest.mark.asyncio
async def test_push_key_without_scope_403(authed_client, no_scope_api_key, demo_environment_id):
    r = await authed_client.post(f"/api/v1/environments/{demo_environment_id}/health",
                                 json={"status": "up", "source": "x"},
                                 headers={"X-Api-Key": no_scope_api_key})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_overview_tenant_scoped(authed_client, other_tenant_environment_with_down_sample):
    ov = await authed_client.get("/api/v1/environments/health")
    assert ov.status_code == 200
    assert all(r["environment_id"] != other_tenant_environment_with_down_sample for r in ov.json())
```

`no_scope_api_key` = a key with scopes `[]` (or some other scope); `other_tenant_environment_with_down_sample` = a second tenant's env + sample. Mirror the second-tenant fixture pattern from `tests/integration/test_incident_tenant_isolation.py`.

- [ ] **Step 7: Run + commit**

Run: `uv run pytest tests/integration/test_environment_health_api.py -q` → PASS.

```bash
git add backend/app/api/v1/environment_health.py backend/app/main.py backend/tests/integration/test_environment_health_api.py
git commit -m "feat(health): API (push[api-key] + history + overview) with isolation (Phase 5 SP3)"
```

---

## Task 6: Frontend types + service

**Files:**
- Create: `frontend/src/types/environmentHealth.ts`, `frontend/src/services/environmentHealthService.ts`

- [ ] **Step 1: Types** — `frontend/src/types/environmentHealth.ts`:

```ts
export type HealthStatus = 'up' | 'down' | 'issue' | 'unknown';

export interface HealthSample {
  id: number; environment_id: number; status: 'up' | 'down' | 'issue';
  recorded_at: string; source: string; detail: string | null;
}
export interface ActiveBookingSummary { project_name: string; start_date: string; end_date: string; }
export interface EnvironmentHealthOverviewRow {
  environment_id: number; environment_name: string;
  current_status: HealthStatus; last_recorded_at: string | null;
  active_booking: boolean; active_booking_summary: ActiveBookingSummary | null;
  planned_outage: boolean; alert: boolean;
}
```

- [ ] **Step 2: Service** — `frontend/src/services/environmentHealthService.ts` (default `api` import; baseURL is `/api/v1`):

```ts
import api from './api';
import type { EnvironmentHealthOverviewRow, HealthSample } from '../types/environmentHealth';

export const environmentHealthService = {
  overview: () => api.get<EnvironmentHealthOverviewRow[]>('/environments/health').then((r) => r.data),
  history: (envId: number, limit = 50) =>
    api.get<HealthSample[]>(`/environments/${envId}/health/history`, { params: { limit } }).then((r) => r.data),
};
```

- [ ] **Step 3: tsc + commit**

Run: `npx tsc --noEmit` → PASS.

```bash
git add frontend/src/types/environmentHealth.ts frontend/src/services/environmentHealthService.ts
git commit -m "feat(health): frontend types + service (Phase 5 SP3)"
```

---

## Task 7: Health dashboard page + route + nav

**Files:**
- Create: `frontend/src/pages/insights/HealthDashboard.tsx`
- Modify: `frontend/src/components/navConfig.tsx`, `frontend/src/App.tsx`

- [ ] **Step 1: Implement the page** — `frontend/src/pages/insights/HealthDashboard.tsx`. Mirror `DoraDashboard.tsx` (local `useState` + `useEffect` calling `environmentHealthService.overview()`; MUI, `DataTable`). Build:
  - A local `STATUS_COLOR: Record<HealthStatus, 'success'|'error'|'warning'|'default'> = { up:'success', down:'error', issue:'warning', unknown:'default' }` for the traffic-light `Chip`.
  - A red **alert banner** (`Alert severity="error"`) shown only when `rows.some(r => r.alert)`, listing the environment names in alert.
  - A `DataTable` with columns: Environment (name), Status (Chip via `STATUS_COLOR`), Last Seen (`last_recorded_at` formatted or "—"), Active Booking (`active_booking_summary?.project_name` or "—"), Planned Outage (`planned_outage ? 'Yes' : '—'`), Alert (a red flag/Chip when `alert`). Row click → `/environments/${environment_id}`.
  - Follow the display-name convention (never `#id`).
- [ ] **Step 2: Route** — add `/insights/health` → `<HealthDashboard />` in `src/App.tsx`.
- [ ] **Step 3: Nav** — add an "Environment Health" entry (QueryStats/health icon) under the Insights group in `src/components/navConfig.tsx`, path `/insights/health`.
- [ ] **Step 4: Verify** — `npx tsc --noEmit` → PASS; `npx vitest run src/store` → PASS (sanity).
- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/insights/HealthDashboard.tsx frontend/src/App.tsx frontend/src/components/navConfig.tsx
git commit -m "feat(health): environment health dashboard page + route + nav (Phase 5 SP3)"
```

---

## Task 8: Environment-detail Health section

**Files:**
- Create: `frontend/src/components/environments/EnvironmentHealthTab.tsx` (or the sibling pattern)
- Modify: the Environment detail page (add a "Health" tab)

- [ ] **Step 1: Implement** — Create `EnvironmentHealthTab.tsx` taking an `envId` prop: on mount, call `environmentHealthService.history(envId)` and render:
  - The current status (the newest sample's status as a `Chip`, or "unknown" if the newest is stale/absent — compute client-side against a 15-min threshold, or just show the newest sample's status + timestamp).
  - A **status-history timeline** (list of samples: status chip + `recorded_at` + source + detail), newest first.
  Mirror the read-only timeline pattern used by `IncidentDetail`'s status history.
- [ ] **Step 2: Wire the tab** — Find the Environment detail page (the tabbed view with Overview/Systems/Components/Topology/Schedule/Deployments — search `src/pages/environments/` for the tab strip). Add a **Health** tab rendering `<EnvironmentHealthTab envId={envId} />`, following the exact tab-add pattern (label + panel index), mirroring how the Topology/Schedule tabs are wired.
- [ ] **Step 3: Verify + commit**

Run: `npx tsc --noEmit` → PASS.

```bash
git add frontend/src/components/environments/EnvironmentHealthTab.tsx frontend/src/  # env detail page
git commit -m "feat(health): environment-detail Health tab (status + history) (Phase 5 SP3)"
```

---

## Task 9: Full verification + manual eyeball

**Files:** none.

- [ ] **Step 1: Backend suite**

Run: `uv run --directory /Users/peter/Developer/Code/projects/envmgr/backend pytest tests/ -q`
Expected: all pass (1 pre-existing skip acceptable).

- [ ] **Step 2: Frontend**

Run (from `frontend/`): `npx tsc --noEmit` → clean; `npx vitest run --exclude 'e2e/**'` → pass.

- [ ] **Step 3: Manual eyeball (human)** — browser automation is flaky; hand to the user:
  - Mint an API key with the `environment:health` scope (tenant admin → API keys). Push a couple of samples:
    `curl -X POST localhost:8000/api/v1/environments/<id>/health -H "X-Api-Key: <key>" -H "Content-Type: application/json" -d '{"status":"down","source":"manual"}'`
  - Open **Insights → Environment Health**: the env shows a red **down** chip; if it has an active booking and no planned outage, the **alert banner** appears and the row is flagged.
  - Push `{"status":"up"}` → the chip turns green, alert clears.
  - Open the environment detail → **Health** tab → current status + history timeline show the samples.

---

## Self-Review Notes

- **Spec coverage:** model + migration (Task 1); schemas (Task 2); record/history/staleness derivation (Task 3); active-booking + planned-outage + alert (Task 4); API push[api-key]+history+overview + isolation/scope tests (Task 5); frontend types/service (Task 6); dashboard grid + alert banner + nav (Task 7); env-detail Health tab (Task 8); verification + eyeball (Task 9). Non-goals (persistent notifications, manual entry, retention, per-subsystem) excluded. ✅
- **Type consistency:** `health_overview` returns dicts with keys matching `EnvironmentHealthOverviewRow` (backend schema) and the TS `EnvironmentHealthOverviewRow`. `record_sample(db, tenant_id, environment_id, status, source, detail=None, recorded_at=None)` signature is identical across service, tests, and the API route. `_utc` normalization used for every naive/aware comparison (recorded_at, booking window, CR window). `STALE_AFTER`/`INACTIVE_BOOKING_STATUSES`/`INACTIVE_CR_STATUSES` defined once.
- **Assumptions flagged in-task:** the exact `authed_client` + API-key + second-tenant fixture names (Task 5), `Booking.project_name` presence (Task 4 — `getattr(..., "project_name", None)` guards it), the env-detail tab-strip location (Task 8), and whether the API-key admin UI needs `environment:health` added to a scope list (spec risk — verify; free-form scopes need no change). Booking "inactive" status set `{draft, cancelled, rejected}` is asserted by the draft-booking alert test.
