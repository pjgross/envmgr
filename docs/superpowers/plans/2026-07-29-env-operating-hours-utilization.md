# Environment Operating Hours + Utilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-environment weekly operating-hours + timezone configuration, and a timezone-aware, DST-correct, union-based utilization metric (`booked ÷ total operating time`, ≤ 100%), surfaced per-environment and in aggregate.

**Architecture:** A new `EnvironmentOperatingHours` table (one JSON `week` row per env + IANA timezone) with a config-CRUD service and a separate pure utilization service that localizes wall-clock open/close per date via stdlib `zoneinfo` (DST-correct) and intersects operating segments with the union of active bookings. Three JWT endpoints (GET/PUT operating-hours, per-env utilization) plus an aggregate `/metrics/environments/utilization`, mirroring the SP5b/DORA on-demand pattern. Frontend adds an Operating Hours editor tab + utilization card on Environment detail and an Environment Utilization table on Releases — Analytics.

**Tech Stack:** FastAPI + async SQLAlchemy + Alembic, Python 3.12 `zoneinfo` (no new deps — confirmed resolvable), pytest/httpx; React 18 + TS strict + MUI + `@mui/x-data-grid`, vitest + Testing Library.

---

## Context for the implementer (read once)

Zero-context onboarding — read these before starting:

- **Spec:** `docs/superpowers/specs/2026-07-29-env-operating-hours-utilization-design.md`.
- **Booking active-definition (reuse):** a booking counts as active iff its `status` is NOT in `{"draft","rejected","closed"}`. Booking has `environment_id`, `start_date`/`end_date` (`DateTime(timezone=True)`), `status`, `tenant_id`, `deleted_at`. SQLite tests return **naive** datetimes — normalise with a `_utc()` helper before comparing.
- **Migration convention:** write DDL **manually** with `op.create_table()` — never `--autogenerate` (init_db uses create_all so autogenerate sees nothing). `alembic revision -m "..."` auto-sets `down_revision` to the current head. Current head is the PIR migration `4c95edc360c4`.
- **Enum/JSON/SQLite compat:** enum columns use `native_enum=False`; JSON via `sqlalchemy.types.JSON`. No native Postgres enums.
- **Service conventions:** services are pure, tenant-scoped, use `db.flush()` not `db.commit()`. Every FK write validates the FK belongs to the caller's tenant (IDOR guard) — see the health/incident services. Tenant from `current_user.active_tenant_id`.
- **Schemas live at `app/api/v1/schemas/`** (canonical), not `app/schemas/`.
- **`_as_dt` date helper** lives in `app/api/v1/metrics.py` — `_as_dt(d, *, end_of_day=False)` converts a `date` to a UTC datetime; `end_of_day=True` expands to `23:59:59.999999` so `date_to` is whole-day inclusive. Reuse it by importing.
- **Router mounting (`app/main.py`):** `environment_health_router` (prefix `/environments`) is mounted with `prefix="/api/v1"` BEFORE `environments_router`. New per-env routers follow the same shape.
- **Frontend sibling patterns:** `services/doraService.ts` + `services/releaseMetricsService.ts` (thin `api.get().then(r=>r.data)`); `components/environments/EnvironmentHealthTab.tsx` (per-env tab, `envId` prop); `pages/insights/HealthDashboard.test.tsx` (render-test pattern); `pages/releases/ReleaseAnalytics.tsx` (the Analytics page + its `DataTable`/`from`/`to` state). **Frontend date params must be plain `YYYY-MM-DD`** (the SP5b contract — ISO datetime strings 422 on a `date` param). **Never put `useSnackbar()` result in a `useCallback`/`useEffect` dep array** (SP4 infinite-loop lesson) — use a `useRef`.
- **EnvironmentDetail tabs** (`frontend/src/pages/environments/EnvironmentDetail.tsx`): tabs are `Overview(0) Systems(1) Components(2) Topology(3) Schedule(4) Deployments(5) Health(6)`, rendered as `{tab === 6 && <EnvironmentHealthTab envId={envId} />}`. You will add `Operating Hours` as tab index 7.

**Weekday convention (used everywhere):** `week` is a list of exactly 7 entries indexed by Python `date.weekday()` → **0 = Monday … 6 = Sunday**. Each entry is `{"closed": bool, "open": "HH:MM", "close": "HH:MM"}`; when `closed` is true, `open`/`close` are ignored.

**Run backend tests:** from `backend/`, `DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest <path> -q`.
**Run frontend:** from `frontend/`, `npx vitest run <path>` and `npx tsc --noEmit`.

---

## File Structure

**Backend — create:**
- `app/db/models/environment_operating_hours.py` — the `EnvironmentOperatingHours` model.
- `app/db/migrations/versions/<gen>_environment_operating_hours.py` — table DDL.
- `app/services/environment_operating_hours_service.py` — config CRUD + validation.
- `app/services/environment_utilization_service.py` — pure interval math + DB-backed utilization.
- `app/api/v1/schemas/environment_operating_hours.py` — request/response models.
- `app/api/v1/environment_operating_hours.py` — GET/PUT config + per-env utilization router.
- `tests/services/test_environment_operating_hours_service.py`
- `tests/services/test_environment_utilization_service.py`
- `tests/integration/test_environment_operating_hours_api.py`

**Backend — modify:** `app/main.py` (mount router), `app/api/v1/metrics.py` (aggregate endpoint), `app/db/base.py`? no. Model import: ensure the new model is imported so `create_all` sees it (add to wherever models are imported — check `app/db/models/__init__.py` or `app/main.py` model imports).

**Frontend — create:** `src/types/environmentOperatingHours.ts`, `src/services/environmentOperatingHoursService.ts`, `src/components/environments/EnvironmentOperatingHoursTab.tsx`, `src/components/environments/__tests__/EnvironmentOperatingHoursTab.test.tsx`, `src/pages/releases/__tests__/ReleaseAnalytics.utilization.test.tsx`.

**Frontend — modify:** `src/pages/environments/EnvironmentDetail.tsx` (add tab), `src/pages/releases/ReleaseAnalytics.tsx` (utilization table).

---

## Task 1: Model + migration

**Files:**
- Create: `backend/app/db/models/environment_operating_hours.py`
- Create: `backend/app/db/migrations/versions/<gen>_environment_operating_hours.py`
- Test: `backend/tests/services/test_environment_operating_hours_service.py` (a smoke test first)

- [ ] **Step 1: Write the failing smoke test**

Create `backend/tests/services/test_environment_operating_hours_service.py`:

```python
import pytest
from app.db.models.environment import Environment
from app.db.models.environment_operating_hours import EnvironmentOperatingHours


async def _env(db, tenant_id, name="Env"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


@pytest.mark.asyncio
async def test_operating_hours_row_roundtrips(db_session, tenant):
    env = await _env(db_session, tenant.id)
    row = EnvironmentOperatingHours(
        tenant_id=tenant.id, environment_id=env.id, timezone="Europe/London",
        week=[{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)],
    )
    db_session.add(row); await db_session.flush()
    assert row.id is not None
    assert row.week[0]["open"] == "09:00"
    assert row.deleted_at is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_operating_hours_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.db.models.environment_operating_hours`.

- [ ] **Step 3: Write the model**

Create `backend/app/db/models/environment_operating_hours.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentOperatingHours(Base):
    """Per-environment weekly operating hours + IANA timezone (one row per env).

    `week` is a list of exactly 7 entries indexed by weekday (0=Mon..6=Sun), each
    {"closed": bool, "open": "HH:MM", "close": "HH:MM"}. Absence of a row means the
    environment has no operating hours configured.
    """
    __tablename__ = "environment_operating_hours"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environment.id"), nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    week: Mapped[list] = mapped_column(JSON, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("environment_id", name="uq_env_operating_hours_env"),
    )
```

Then register the model for `create_all`/Alembic. `backend/app/db/models/__init__.py` explicitly imports every model and lists it in `__all__` (e.g. `from app.db.models.environment_health import EnvironmentHealthStatus  # noqa: F401` near line 61, and `"EnvironmentHealthStatus"` in the `__all__` list near line 120). Mirror exactly:
- Add near the other model imports: `from app.db.models.environment_operating_hours import EnvironmentOperatingHours  # noqa: F401`
- Add `"EnvironmentOperatingHours"` to the `__all__` list.

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_operating_hours_service.py -q`
Expected: PASS (1 test). (Tests use `create_all`, so the table exists without the migration.)

- [ ] **Step 5: Create the migration**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run alembic revision -m "environment operating hours"`

This creates a new file under `app/db/migrations/versions/`. Open it and replace `upgrade`/`downgrade` with:

```python
def upgrade() -> None:
    op.create_table(
        "environment_operating_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("week", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("environment_id", name="uq_env_operating_hours_env"),
    )
    op.create_index("ix_env_ophours_tenant_id", "environment_operating_hours", ["tenant_id"])
    op.create_index("ix_env_ophours_environment_id", "environment_operating_hours", ["environment_id"])


def downgrade() -> None:
    op.drop_table("environment_operating_hours")
```

Leave the generated `revision`/`down_revision` lines as alembic wrote them (do not edit — `down_revision` is auto-set to `4c95edc360c4`).

- [ ] **Step 6: Apply the migration**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run alembic upgrade head`
Expected: applies cleanly (no error). Confirm with `... alembic current` showing the new revision.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models/environment_operating_hours.py backend/app/db/migrations/versions/ backend/tests/services/test_environment_operating_hours_service.py backend/app/db/models/__init__.py
git commit -m "feat(env-hours): EnvironmentOperatingHours model + migration (Phase 5 SP5a)"
```
(Adjust the `git add` list to whichever file you edited for the model import.)

---

## Task 2: Operating-hours config service (CRUD + validation)

**Files:**
- Create: `backend/app/services/environment_operating_hours_service.py`
- Test: `backend/tests/services/test_environment_operating_hours_service.py` (append)

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/services/test_environment_operating_hours_service.py`:

```python
from fastapi import HTTPException  # noqa: E402
from app.services import environment_operating_hours_service as svc  # noqa: E402

_FULL_WEEK = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]


@pytest.mark.asyncio
async def test_upsert_creates_then_updates_single_row(db_session, tenant):
    env = await _env(db_session, tenant.id)
    r1 = await svc.upsert_config(db_session, tenant.id, env.id, "UTC", _FULL_WEEK)
    assert r1.timezone == "UTC"
    r2 = await svc.upsert_config(db_session, tenant.id, env.id, "Europe/London",
                                 [{"closed": True} for _ in range(7)])
    assert r2.id == r1.id  # same row updated, not a second row
    assert r2.timezone == "Europe/London"
    got = await svc.get_config(db_session, tenant.id, env.id)
    assert got.id == r1.id
    assert got.week[0]["closed"] is True


@pytest.mark.asyncio
async def test_upsert_invalid_timezone_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "Mars/Phobos", _FULL_WEEK)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_open_after_close_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    bad = [{"closed": False, "open": "17:00", "close": "09:00"}] + \
          [{"closed": True} for _ in range(6)]
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "UTC", bad)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_malformed_hhmm_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    bad = [{"closed": False, "open": "9am", "close": "17:00"}] + \
          [{"closed": True} for _ in range(6)]
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "UTC", bad)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_wrong_length_week_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "UTC", _FULL_WEEK[:5])
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_wrong_tenant_env_404(db_session, tenant):
    from app.db.models.user import Tenant
    t2 = Tenant(name="Other", slug="other-ophours")
    db_session.add(t2); await db_session.flush()
    env2 = await _env(db_session, t2.id, name="Env2")
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env2.id, "UTC", _FULL_WEEK)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_get_config_none_when_unset(db_session, tenant):
    env = await _env(db_session, tenant.id)
    assert await svc.get_config(db_session, tenant.id, env.id) is None
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_operating_hours_service.py -q`
Expected: the new tests FAIL — `ModuleNotFoundError: app.services.environment_operating_hours_service` (the Task-1 smoke test still passes).

- [ ] **Step 3: Write the service**

Create `backend/app/services/environment_operating_hours_service.py`:

```python
"""Environment operating-hours config CRUD + validation (Phase 5 SP5a).

One EnvironmentOperatingHours row per environment. `week` is 7 entries (0=Mon..6=Sun),
each {"closed": bool, "open": "HH:MM", "close": "HH:MM"}. Overnight windows (close <= open)
are out of scope and rejected. Tenant-scoped; IDOR-guarded on the environment FK.
"""
import re
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment
from app.db.models.environment_operating_hours import EnvironmentOperatingHours

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_timezone(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Invalid timezone: {tz!r}")


def _validate_week(week) -> None:
    if not isinstance(week, list) or len(week) != 7:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="week must have exactly 7 entries (Mon..Sun)")
    for i, day in enumerate(week):
        if not isinstance(day, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"week[{i}] must be an object")
        if day.get("closed"):
            continue
        opened, closed = day.get("open"), day.get("close")
        if not (isinstance(opened, str) and _HHMM.match(opened)) or \
           not (isinstance(closed, str) and _HHMM.match(closed)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"week[{i}] open/close must be HH:MM")
        if opened >= closed:  # lexical compare is valid for zero-padded HH:MM
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"week[{i}] open must be before close")


async def _validate_env(db: AsyncSession, tenant_id: int, environment_id: int) -> Environment:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id,
        Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if env is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    return env


async def get_config(db: AsyncSession, tenant_id: int, environment_id: int):
    return (await db.execute(select(EnvironmentOperatingHours).where(
        EnvironmentOperatingHours.environment_id == environment_id,
        EnvironmentOperatingHours.tenant_id == tenant_id,
        EnvironmentOperatingHours.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def upsert_config(db: AsyncSession, tenant_id: int, environment_id: int,
                        timezone: str, week: list) -> EnvironmentOperatingHours:
    await _validate_env(db, tenant_id, environment_id)
    _validate_timezone(timezone)
    _validate_week(week)
    row = (await db.execute(select(EnvironmentOperatingHours).where(
        EnvironmentOperatingHours.environment_id == environment_id,
        EnvironmentOperatingHours.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if row is None:
        row = EnvironmentOperatingHours(
            tenant_id=tenant_id, environment_id=environment_id, timezone=timezone, week=week,
        )
        db.add(row)
    else:
        row.timezone = timezone
        row.week = week
        row.deleted_at = None
    await db.flush()
    return row
```

- [ ] **Step 4: Run to verify all pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_operating_hours_service.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_operating_hours_service.py backend/tests/services/test_environment_operating_hours_service.py
git commit -m "feat(env-hours): operating-hours config service + validation (Phase 5 SP5a)"
```

---

## Task 3: Utilization pure helpers (intervals + operating segments, incl. DST)

**Files:**
- Create: `backend/app/services/environment_utilization_service.py`
- Test: `backend/tests/services/test_environment_utilization_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_environment_utilization_service.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta

from app.services import environment_utilization_service as util

UTC = timezone.utc


def _cfg(tz="UTC", week=None):
    """A lightweight stand-in for an EnvironmentOperatingHours row for pure-helper tests."""
    class _C:
        pass
    c = _C()
    c.timezone = tz
    c.week = week if week is not None else [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]
    return c


def test_merge_intervals_overlapping():
    t = datetime(2026, 6, 1, 9, tzinfo=UTC)
    ivals = [(t, t + timedelta(hours=3)), (t + timedelta(hours=2), t + timedelta(hours=4))]
    merged = util._merge_intervals(ivals)
    assert merged == [(t, t + timedelta(hours=4))]


def test_intersect_seconds():
    t = datetime(2026, 6, 1, 9, tzinfo=UTC)
    seg = (t, t + timedelta(hours=8))                     # 09:00-17:00
    ivals = [(t + timedelta(hours=1), t + timedelta(hours=3))]  # 10:00-12:00
    assert util._intersect(seg, ivals) == 2 * 3600


def test_operating_segments_weekday_total_one_week():
    # Mon-Fri 09:00-17:00 (8h), Sat/Sun closed → 5 days * 8h = 40h over a Mon..Sun window.
    week = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(5)] + \
           [{"closed": True}, {"closed": True}]
    cfg = _cfg("UTC", week)
    # 2026-06-01 is a Monday; window covers Mon..Sun.
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 40 * 3600
    assert len(segments) == 5


def test_operating_segments_dst_spring_forward_is_wall_clock():
    # Europe/London springs forward on 2026-03-29. Fixed 09:00-17:00 daily (8h wall-clock).
    # Window Sat 03-28 .. Mon 03-30 → 3 days * 8h = 24h regardless of the DST jump,
    # because 09:00-17:00 local is always 8 wall-clock hours.
    week = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]
    cfg = _cfg("Europe/London", week)
    start = datetime(2026, 3, 28, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 30, 23, 59, 59, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 24 * 3600
    # The 03-29 (DST) segment: 09:00 BST == 08:00 UTC, 17:00 BST == 16:00 UTC → still 8h.
    dst_day = [s for s in segments if s[0].date().isoformat() == "2026-03-29"][0]
    assert (dst_day[1] - dst_day[0]).total_seconds() == 8 * 3600
    assert dst_day[0].hour == 8  # 09:00 BST in UTC


def test_operating_segments_clips_to_window():
    week = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]
    cfg = _cfg("UTC", week)
    # Window starts mid-operating-hours on the single day 2026-06-01 10:00..12:00
    start = datetime(2026, 6, 1, 10, tzinfo=UTC)
    end = datetime(2026, 6, 1, 12, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 2 * 3600
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_utilization_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.environment_utilization_service`.

- [ ] **Step 3: Write the pure helpers**

Create `backend/app/services/environment_utilization_service.py`:

```python
"""Environment utilization (Phase 5 SP5a).

Utilization = booked ÷ total operating time over a window, union-based (each operating
second is booked or not), so utilization is 0..1. Operating hours are wall-clock times in
the environment's IANA timezone, localized per calendar date → DST-correct via zoneinfo.
Booked = active bookings (status not in {draft,rejected,closed}). Pure, tenant-scoped.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.services import environment_operating_hours_service as ops_service

_INACTIVE_BOOKING_STATES = {"draft", "rejected", "closed"}


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Merge overlapping/adjacent [start, end) intervals into a sorted disjoint list."""
    out: list[tuple[datetime, datetime]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _intersect(seg: tuple[datetime, datetime], intervals: list[tuple[datetime, datetime]]) -> float:
    """Seconds of `seg` covered by the (already-merged) `intervals`."""
    total = 0.0
    a, b = seg
    for c, d in intervals:
        lo = max(a, c)
        hi = min(b, d)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _operating_segments(config, date_from: datetime, date_to: datetime):
    """Return (list of UTC operating segments clipped to the window, total seconds).

    Iterates each calendar date in the window IN THE CONFIG'S TIMEZONE, localizes that
    day's wall-clock open/close, converts to UTC, and clips to [date_from, date_to].
    """
    tz = ZoneInfo(config.timezone)
    week = config.week
    segments: list[tuple[datetime, datetime]] = []
    total = 0.0
    d = date_from.astimezone(tz).date()
    last = date_to.astimezone(tz).date()
    while d <= last:
        entry = week[d.weekday()]
        if not entry.get("closed"):
            oh, om = _parse_hhmm(entry["open"])
            ch, cm = _parse_hhmm(entry["close"])
            local_open = datetime(d.year, d.month, d.day, oh, om, tzinfo=tz)
            local_close = datetime(d.year, d.month, d.day, ch, cm, tzinfo=tz)
            su = max(local_open.astimezone(timezone.utc), date_from)
            eu = min(local_close.astimezone(timezone.utc), date_to)
            if eu > su:
                segments.append((su, eu))
                total += (eu - su).total_seconds()
        d += timedelta(days=1)
    return segments, total
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_utilization_service.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_utilization_service.py backend/tests/services/test_environment_utilization_service.py
git commit -m "feat(env-hours): utilization interval + DST-aware operating-segment helpers (Phase 5 SP5a)"
```

---

## Task 4: DB-backed utilization (`environment_utilization` + `utilization_overview`)

**Files:**
- Modify: `backend/app/services/environment_utilization_service.py`
- Test: `backend/tests/services/test_environment_utilization_service.py` (append)

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/services/test_environment_utilization_service.py`:

```python
# --- DB-backed utilization -------------------------------------------------

from app.db.models.environment import Environment  # noqa: E402
from app.db.models.booking import Booking  # noqa: E402
from app.db.models.booking_request import BookingRequest  # noqa: E402
from app.db.models.user import User, Tenant  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.services import environment_operating_hours_service as ops_service  # noqa: E402

_MONFRI = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(5)] + \
          [{"closed": True}, {"closed": True}]

_uc = 0


async def _mk_env(db, tenant_id, name="Env"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


async def _mk_user(db, tenant_id):
    global _uc
    _uc += 1
    u = User(tenant_id=tenant_id, username=f"utu{_uc}", email=f"utu{_uc}@t.com",
             password_hash=get_password_hash("x"), role="Viewer", is_active=True)
    db.add(u); await db.flush(); return u


async def _mk_booking(db, tenant_id, env_id, user_id, start, end, status="approved"):
    req = BookingRequest(tenant_id=tenant_id, project_name="P", booked_by=user_id, booking_type_id=1,
                         start_date=start, end_date=end)
    db.add(req); await db.flush()
    b = Booking(tenant_id=tenant_id, environment_id=env_id, booking_request_id=req.id,
                start_date=start, end_date=end, status=status)
    db.add(b); await db.flush(); return b


@pytest.mark.asyncio
async def test_environment_utilization_single_booking(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    u = await _mk_user(db_session, tenant.id)
    await ops_service.upsert_config(db_session, tenant.id, env.id, "UTC", _MONFRI)
    # Window: Mon 2026-06-01 .. Sun 2026-06-07 → total 40h. Booking Tue 09:00-12:00 → 3h booked.
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 2, 9, tzinfo=UTC), datetime(2026, 6, 2, 12, tzinfo=UTC))
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["configured"] is True
    assert res["total_operating_seconds"] == 40 * 3600
    assert res["booked_operating_seconds"] == 3 * 3600
    assert abs(res["utilization_ratio"] - (3 / 40)) < 1e-9


@pytest.mark.asyncio
async def test_environment_utilization_union_of_overlapping(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    u = await _mk_user(db_session, tenant.id)
    await ops_service.upsert_config(db_session, tenant.id, env.id, "UTC", _MONFRI)
    # Two overlapping bookings Tue 09-12 and Tue 11-13 → union 09-13 within op hours = 4h (not 5h).
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 2, 9, tzinfo=UTC), datetime(2026, 6, 2, 12, tzinfo=UTC))
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 2, 11, tzinfo=UTC), datetime(2026, 6, 2, 13, tzinfo=UTC))
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["booked_operating_seconds"] == 4 * 3600


@pytest.mark.asyncio
async def test_environment_utilization_excludes_outside_hours_and_inactive(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    u = await _mk_user(db_session, tenant.id)
    await ops_service.upsert_config(db_session, tenant.id, env.id, "UTC", _MONFRI)
    # Booking on Sat (closed) → 0 booked
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 6, 9, tzinfo=UTC), datetime(2026, 6, 6, 17, tzinfo=UTC))
    # Draft booking during op hours → excluded
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 3, 9, tzinfo=UTC), datetime(2026, 6, 3, 17, tzinfo=UTC),
                      status="draft")
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["booked_operating_seconds"] == 0.0


@pytest.mark.asyncio
async def test_environment_utilization_unconfigured(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["configured"] is False
    assert res["total_operating_seconds"] == 0.0
    assert res["utilization_ratio"] == 0.0
    assert res["environment_name"] == env.name


@pytest.mark.asyncio
async def test_utilization_overview_lists_configured_counts_unconfigured(db_session, tenant):
    e1 = await _mk_env(db_session, tenant.id, name="AAA")
    e2 = await _mk_env(db_session, tenant.id, name="BBB")  # left unconfigured
    await ops_service.upsert_config(db_session, tenant.id, e1.id, "UTC", _MONFRI)
    res = await util.utilization_overview(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert [r["environment_name"] for r in res["rows"]] == ["AAA"]
    assert res["unconfigured_count"] == 1


@pytest.mark.asyncio
async def test_utilization_tenant_isolation(db_session, tenant):
    t2 = Tenant(name="Other2", slug="other-util")
    db_session.add(t2); await db_session.flush()
    e2 = await _mk_env(db_session, t2.id, name="ForeignEnv")
    await ops_service.upsert_config(db_session, t2.id, e2.id, "UTC", _MONFRI)
    res = await util.utilization_overview(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["rows"] == []
    assert res["unconfigured_count"] == 0
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_utilization_service.py -q`
Expected: the 6 new tests FAIL — `AttributeError: module ... has no attribute 'environment_utilization'`.

- [ ] **Step 3: Append the DB-backed functions**

Append to `backend/app/services/environment_utilization_service.py` (imports `Environment`, `Booking`, `not_`, `select`, `ops_service`, `_utc`, `_merge_intervals`, `_intersect`, `_operating_segments` are all already present from Task 3):

```python
async def environment_utilization(db: AsyncSession, tenant_id: int, environment_id: int,
                                  date_from: datetime, date_to: datetime) -> dict:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id,
        Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if env is None:
        from fastapi import HTTPException, status as _s
        raise HTTPException(status_code=_s.HTTP_404_NOT_FOUND, detail="Environment not found")

    config = await ops_service.get_config(db, tenant_id, environment_id)
    if config is None:
        return {
            "environment_id": environment_id, "environment_name": env.name,
            "configured": False, "timezone": None,
            "total_operating_seconds": 0.0, "booked_operating_seconds": 0.0,
            "utilization_ratio": 0.0,
        }

    segments, total = _operating_segments(config, date_from, date_to)
    rows = (await db.execute(
        select(Booking.start_date, Booking.end_date).where(
            Booking.tenant_id == tenant_id,
            Booking.environment_id == environment_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(_INACTIVE_BOOKING_STATES)),
            Booking.start_date < date_to,
            Booking.end_date > date_from,
        )
    )).all()
    intervals = _merge_intervals([(_utc(s), _utc(e)) for s, e in rows])
    booked = sum(_intersect(seg, intervals) for seg in segments)
    util_pct = (booked / total) if total else 0.0
    return {
        "environment_id": environment_id, "environment_name": env.name,
        "configured": True, "timezone": config.timezone,
        "total_operating_seconds": total, "booked_operating_seconds": booked,
        "utilization_ratio": util_pct,
    }


async def utilization_overview(db: AsyncSession, tenant_id: int,
                               date_from: datetime, date_to: datetime) -> dict:
    envs = (await db.execute(select(Environment).where(
        Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
    ))).scalars().all()
    rows = []
    unconfigured = 0
    for env in envs:
        r = await environment_utilization(db, tenant_id, env.id, date_from, date_to)
        if r["configured"]:
            rows.append(r)
        else:
            unconfigured += 1
    rows.sort(key=lambda r: r["environment_name"])
    return {"rows": rows, "unconfigured_count": unconfigured}
```

- [ ] **Step 4: Run to verify all pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/services/test_environment_utilization_service.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_utilization_service.py backend/tests/services/test_environment_utilization_service.py
git commit -m "feat(env-hours): DB-backed environment utilization + overview (Phase 5 SP5a)"
```

---

## Task 5: Schemas + operating-hours/utilization API router

**Files:**
- Create: `backend/app/api/v1/schemas/environment_operating_hours.py`
- Create: `backend/app/api/v1/environment_operating_hours.py`
- Modify: `backend/app/main.py` (mount router)
- Test: `backend/tests/integration/test_environment_operating_hours_api.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_environment_operating_hours_api.py`:

```python
"""Integration tests for the Environment Operating Hours + per-env utilization API (SP5a)."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.environment import Environment

UTC = timezone.utc

_FULL = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(5)] + \
        [{"closed": True}, {"closed": True}]


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


async def _env(db, tenant_id, name="SIT"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


@pytest.mark.asyncio
async def test_get_operating_hours_unset(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.get(f"/api/v1/environments/{env.id}/operating-hours")
    assert r.status_code == 200, r.text
    assert r.json() == {"configured": False, "timezone": None, "week": None}


@pytest.mark.asyncio
async def test_put_then_get_operating_hours(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.put(f"/api/v1/environments/{env.id}/operating-hours",
                                json={"timezone": "Europe/London", "week": _FULL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["timezone"] == "Europe/London"
    assert body["week"][0]["open"] == "09:00"
    g = await authed_client.get(f"/api/v1/environments/{env.id}/operating-hours")
    assert g.json()["timezone"] == "Europe/London"


@pytest.mark.asyncio
async def test_put_invalid_timezone_422(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.put(f"/api/v1/environments/{env.id}/operating-hours",
                                json={"timezone": "Nowhere/Nope", "week": _FULL})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_env_utilization_endpoint(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    await authed_client.put(f"/api/v1/environments/{env.id}/operating-hours",
                            json={"timezone": "UTC", "week": _FULL})
    r = await authed_client.get(f"/api/v1/environments/{env.id}/utilization",
                                params={"date_from": "2026-06-01", "date_to": "2026-06-07"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"environment_id", "environment_name", "configured", "timezone",
                         "total_operating_seconds", "booked_operating_seconds", "utilization_ratio"}
    assert body["total_operating_seconds"] == 40 * 3600


@pytest.mark.asyncio
async def test_env_utilization_requires_dates(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id)
    r = await authed_client.get(f"/api/v1/environments/{env.id}/utilization")
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/integration/test_environment_operating_hours_api.py -q`
Expected: FAIL — routes 404 (shape/`==` assertions fail; requires_dates gets 404 not 422).

- [ ] **Step 3: Write the schemas**

Create `backend/app/api/v1/schemas/environment_operating_hours.py`:

```python
from typing import Optional, List
from pydantic import BaseModel


class OperatingHoursDay(BaseModel):
    closed: bool = False
    open: Optional[str] = None
    close: Optional[str] = None


class OperatingHoursConfigIn(BaseModel):
    timezone: str
    week: List[OperatingHoursDay]


class OperatingHoursConfigResponse(BaseModel):
    configured: bool
    timezone: Optional[str] = None
    week: Optional[List[OperatingHoursDay]] = None


class EnvironmentUtilization(BaseModel):
    environment_id: int
    environment_name: str
    configured: bool
    timezone: Optional[str] = None
    total_operating_seconds: float
    booked_operating_seconds: float
    utilization_ratio: float


class UtilizationOverview(BaseModel):
    rows: List[EnvironmentUtilization]
    unconfigured_count: int
```

- [ ] **Step 4: Write the router**

Create `backend/app/api/v1/environment_operating_hours.py`:

```python
"""Environment operating-hours config + per-env utilization API (Phase 5 SP5a)."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import environment_operating_hours_service as ops_service
from app.services import environment_utilization_service as util_service
from app.api.v1.metrics import _as_dt
from app.api.v1.schemas.environment_operating_hours import (
    OperatingHoursConfigIn,
    OperatingHoursConfigResponse,
    EnvironmentUtilization,
)

router = APIRouter(prefix="/environments", tags=["environment-operating-hours"])


@router.get("/{env_id}/operating-hours", response_model=OperatingHoursConfigResponse)
async def get_operating_hours(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cfg = await ops_service.get_config(db, current_user.active_tenant_id, env_id)
    if cfg is None:
        return OperatingHoursConfigResponse(configured=False)
    return OperatingHoursConfigResponse(configured=True, timezone=cfg.timezone, week=cfg.week)


@router.put("/{env_id}/operating-hours", response_model=OperatingHoursConfigResponse)
async def put_operating_hours(
    env_id: int,
    body: OperatingHoursConfigIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cfg = await ops_service.upsert_config(
        db, current_user.active_tenant_id, env_id, body.timezone,
        [d.model_dump() for d in body.week],
    )
    return OperatingHoursConfigResponse(configured=True, timezone=cfg.timezone, week=cfg.week)


@router.get("/{env_id}/utilization", response_model=EnvironmentUtilization)
async def get_environment_utilization(
    env_id: int,
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await util_service.environment_utilization(
        db, current_user.active_tenant_id, env_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
    )
```

- [ ] **Step 5: Mount the router in `app/main.py`**

Find the block where `environment_health_router` is imported and included (search `environment_health_router`). Immediately after those two lines add:

```python
from app.api.v1 import environment_operating_hours as environment_operating_hours_router
app.include_router(environment_operating_hours_router.router, prefix="/api/v1")
```

(Both this router and the health router use `prefix="/environments"` internally and are mounted with `prefix="/api/v1"`; mounting before `environments_router` is safe. There is no bare-literal collision — all routes here are under `/{env_id}/...`.)

- [ ] **Step 6: Run to verify all pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/integration/test_environment_operating_hours_api.py -q`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/schemas/environment_operating_hours.py backend/app/api/v1/environment_operating_hours.py backend/app/main.py backend/tests/integration/test_environment_operating_hours_api.py
git commit -m "feat(env-hours): operating-hours + per-env utilization endpoints (Phase 5 SP5a)"
```

---

## Task 6: Aggregate utilization endpoint on the metrics router

**Files:**
- Modify: `backend/app/api/v1/metrics.py`
- Test: `backend/tests/integration/test_environment_operating_hours_api.py` (append)

- [ ] **Step 1: Append the failing tests**

Append to `backend/tests/integration/test_environment_operating_hours_api.py`:

```python
@pytest.mark.asyncio
async def test_metrics_environments_utilization_overview(authed_client, db_session, tenant):
    env = await _env(db_session, tenant.id, name="OverviewEnv")
    await authed_client.put(f"/api/v1/environments/{env.id}/operating-hours",
                            json={"timezone": "UTC", "week": _FULL})
    r = await authed_client.get("/api/v1/metrics/environments/utilization",
                                params={"date_from": "2026-06-01", "date_to": "2026-06-07"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"rows", "unconfigured_count"}
    assert any(row["environment_name"] == "OverviewEnv" for row in body["rows"])


@pytest.mark.asyncio
async def test_metrics_environments_utilization_requires_dates(authed_client):
    r = await authed_client.get("/api/v1/metrics/environments/utilization")
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/integration/test_environment_operating_hours_api.py -q -k overview or requires_dates`
Expected: the two new tests FAIL (route 404).

- [ ] **Step 3: Add the endpoint**

In `backend/app/api/v1/metrics.py`, extend the service import line to include the utilization service:

```python
from app.services import dora_service, release_metrics_service, environment_utilization_service
```

Append at the end of the file:

```python
@router.get("/environments/utilization")
async def get_environments_utilization(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_utilization_service.utilization_overview(
        db, current_user.active_tenant_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest tests/integration/test_environment_operating_hours_api.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/metrics.py backend/tests/integration/test_environment_operating_hours_api.py
git commit -m "feat(env-hours): aggregate /metrics/environments/utilization endpoint (Phase 5 SP5a)"
```

---

## Task 7: Frontend types + service

**Files:**
- Create: `frontend/src/types/environmentOperatingHours.ts`
- Create: `frontend/src/services/environmentOperatingHoursService.ts`

- [ ] **Step 1: Create the types**

Create `frontend/src/types/environmentOperatingHours.ts`:

```typescript
export interface OperatingHoursDay {
  closed: boolean;
  open?: string | null;   // "HH:MM"
  close?: string | null;  // "HH:MM"
}

export interface OperatingHoursConfig {
  configured: boolean;
  timezone?: string | null;
  week?: OperatingHoursDay[] | null;
}

export interface OperatingHoursConfigInput {
  timezone: string;
  week: OperatingHoursDay[];
}

export interface EnvironmentUtilization {
  environment_id: number;
  environment_name: string;
  configured: boolean;
  timezone?: string | null;
  total_operating_seconds: number;
  booked_operating_seconds: number;
  utilization_ratio: number; // 0..1
}

export interface UtilizationOverview {
  rows: EnvironmentUtilization[];
  unconfigured_count: number;
}

export interface UtilizationParams {
  date_from: string; // "YYYY-MM-DD"
  date_to: string;   // "YYYY-MM-DD"
}
```

- [ ] **Step 2: Create the service**

Create `frontend/src/services/environmentOperatingHoursService.ts`:

```typescript
import api from './api';
import type {
  OperatingHoursConfig,
  OperatingHoursConfigInput,
  EnvironmentUtilization,
  UtilizationOverview,
  UtilizationParams,
} from '../types/environmentOperatingHours';

export const environmentOperatingHoursService = {
  getConfig: (envId: number) =>
    api.get<OperatingHoursConfig>(`/environments/${envId}/operating-hours`).then((r) => r.data),
  putConfig: (envId: number, cfg: OperatingHoursConfigInput) =>
    api.put<OperatingHoursConfig>(`/environments/${envId}/operating-hours`, cfg).then((r) => r.data),
  utilization: (envId: number, params: UtilizationParams) =>
    api.get<EnvironmentUtilization>(`/environments/${envId}/utilization`, { params }).then((r) => r.data),
  overview: (params: UtilizationParams) =>
    api.get<UtilizationOverview>('/metrics/environments/utilization', { params }).then((r) => r.data),
};
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/environmentOperatingHours.ts frontend/src/services/environmentOperatingHoursService.ts
git commit -m "feat(env-hours): frontend operating-hours types + service (Phase 5 SP5a)"
```

---

## Task 8: Operating Hours editor tab + utilization card (Environment detail)

**Files:**
- Create: `frontend/src/components/environments/EnvironmentOperatingHoursTab.tsx`
- Create: `frontend/src/components/environments/__tests__/EnvironmentOperatingHoursTab.test.tsx`
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

- [ ] **Step 1: Write the failing render test**

Create `frontend/src/components/environments/__tests__/EnvironmentOperatingHoursTab.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EnvironmentOperatingHoursTab from '../EnvironmentOperatingHoursTab';

vi.mock('../../../services/environmentOperatingHoursService', () => ({
  environmentOperatingHoursService: {
    getConfig: vi.fn().mockResolvedValue({
      configured: true,
      timezone: 'Europe/London',
      week: [
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: true },
        { closed: true },
      ],
    }),
    putConfig: vi.fn(),
    utilization: vi.fn().mockResolvedValue({
      environment_id: 1, environment_name: 'SIT', configured: true, timezone: 'Europe/London',
      total_operating_seconds: 40 * 3600, booked_operating_seconds: 10 * 3600, utilization_ratio: 0.25,
    }),
    overview: vi.fn(),
  },
}));

describe('EnvironmentOperatingHoursTab', () => {
  it('loads the timezone from the existing config', async () => {
    render(<EnvironmentOperatingHoursTab envId={1} />);
    expect(await screen.findByDisplayValue('Europe/London')).toBeInTheDocument();
  });

  it('shows the utilization card percentage', async () => {
    render(<EnvironmentOperatingHoursTab envId={1} />);
    expect(await screen.findByText('25%')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/environments/__tests__/EnvironmentOperatingHoursTab.test.tsx`
Expected: FAIL — cannot find module `../EnvironmentOperatingHoursTab`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/environments/EnvironmentOperatingHoursTab.tsx`:

```tsx
/**
 * EnvironmentOperatingHoursTab — weekly operating-hours editor + a utilization card.
 * Local-state + direct-service; mirrors the DoraDashboard/HealthDashboard pattern.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Autocomplete, Box, Button, Card, CardContent, Checkbox, FormControlLabel,
  Snackbar, TextField, Typography,
} from '@mui/material';
import { environmentOperatingHoursService } from '../../services/environmentOperatingHoursService';
import type { OperatingHoursDay } from '../../types/environmentOperatingHours';

const DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const DEFAULT_WEEK: OperatingHoursDay[] = [
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: false, open: '09:00', close: '17:00' },
  { closed: true, open: '09:00', close: '17:00' },
  { closed: true, open: '09:00', close: '17:00' },
];

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  return Number.isInteger(h) ? `${h}h` : `${h.toFixed(1)}h`;
}

// IANA zones from the browser; fall back to a short list if unsupported.
function tzOptions(): string[] {
  const fn = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf;
  try {
    return fn ? fn('timeZone') : ['UTC', 'Europe/London', 'America/New_York'];
  } catch {
    return ['UTC', 'Europe/London', 'America/New_York'];
  }
}

export default function EnvironmentOperatingHoursTab({ envId }: { envId: number }) {
  const [timezone, setTimezone] = useState('UTC');
  const [week, setWeek] = useState<OperatingHoursDay[]>(DEFAULT_WEEK);
  const [util, setUtil] = useState<{ pct: number; booked: number; total: number; configured: boolean } | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const zones = useMemo(tzOptions, []);
  const loadedRef = useRef(false);

  // last-90-day window for the utilization card
  const params = useMemo(() => ({
    date_from: isoDate(new Date(Date.now() - 90 * 864e5)),
    date_to: isoDate(new Date()),
  }), []);

  useEffect(() => {
    environmentOperatingHoursService.getConfig(envId).then((cfg) => {
      if (cfg.configured && cfg.week && cfg.timezone) {
        setTimezone(cfg.timezone);
        setWeek(cfg.week.map((d) => ({ closed: d.closed, open: d.open ?? '09:00', close: d.close ?? '17:00' })));
      }
      loadedRef.current = true;
    }).catch(() => { loadedRef.current = true; });
  }, [envId]);

  const refreshUtil = () => {
    environmentOperatingHoursService.utilization(envId, params)
      .then((u) => setUtil({ pct: u.utilization_ratio, booked: u.booked_operating_seconds, total: u.total_operating_seconds, configured: u.configured }))
      .catch(() => setUtil(null));
  };
  useEffect(refreshUtil, [envId, params]);

  const setDay = (i: number, patch: Partial<OperatingHoursDay>) => {
    setWeek((w) => w.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  };

  const handleSave = () => {
    setError(null);
    environmentOperatingHoursService.putConfig(envId, { timezone, week })
      .then(() => { setSaved(true); refreshUtil(); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to save operating hours'));
  };

  return (
    <Box sx={{ p: 1 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>Operating Hours</Typography>

      {util && (
        <Card variant="outlined" sx={{ mb: 3, maxWidth: 360 }}>
          <CardContent>
            <Typography variant="subtitle2" color="text.secondary" gutterBottom>
              Utilization (last 90 days)
            </Typography>
            {util.configured ? (
              <>
                <Typography variant="h4" sx={{ fontWeight: 'bold' }}>
                  {Math.round(util.pct * 100)}%
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {formatHours(util.booked)} booked / {formatHours(util.total)} operating
                </Typography>
              </>
            ) : (
              <Typography variant="body2" color="text.secondary">Not configured yet</Typography>
            )}
          </CardContent>
        </Card>
      )}

      <Autocomplete
        size="small"
        sx={{ maxWidth: 360, mb: 2 }}
        options={zones}
        value={timezone}
        onChange={(_, v) => v && setTimezone(v)}
        renderInput={(p) => <TextField {...p} label="Timezone" />}
      />

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, maxWidth: 520 }}>
        {week.map((day, i) => (
          <Box key={DAY_LABELS[i]} sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Typography sx={{ width: 100 }}>{DAY_LABELS[i]}</Typography>
            <FormControlLabel
              control={<Checkbox checked={day.closed} onChange={(e) => setDay(i, { closed: e.target.checked })} />}
              label="Closed"
            />
            <TextField
              type="time" size="small" label="Open" disabled={day.closed}
              value={day.open ?? '09:00'} onChange={(e) => setDay(i, { open: e.target.value })}
              InputLabelProps={{ shrink: true }}
            />
            <TextField
              type="time" size="small" label="Close" disabled={day.closed}
              value={day.close ?? '17:00'} onChange={(e) => setDay(i, { close: e.target.value })}
              InputLabelProps={{ shrink: true }}
            />
          </Box>
        ))}
      </Box>

      {error && <Alert severity="error" sx={{ mt: 2, maxWidth: 520 }}>{error}</Alert>}

      <Button variant="contained" sx={{ mt: 2 }} onClick={handleSave}>Save</Button>

      <Snackbar
        open={saved} autoHideDuration={3000} onClose={() => setSaved(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="success" onClose={() => setSaved(false)}>Operating hours saved</Alert>
      </Snackbar>
    </Box>
  );
}
```

- [ ] **Step 4: Run the render test to verify it passes**

Run: `cd frontend && npx vitest run src/components/environments/__tests__/EnvironmentOperatingHoursTab.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire the tab into EnvironmentDetail**

In `frontend/src/pages/environments/EnvironmentDetail.tsx`:

(a) Add the import near the other tab imports (next to `EnvironmentHealthTab`):
```tsx
import EnvironmentOperatingHoursTab from '../../components/environments/EnvironmentOperatingHoursTab';
```

(b) Add the tab label after the `<Tab label="Health" />` line:
```tsx
        <Tab label="Operating Hours" />
```

(c) Add the tab content after the `{tab === 6 && <EnvironmentHealthTab envId={envId} />}` line:
```tsx
      {tab === 7 && <EnvironmentOperatingHoursTab envId={envId} />}
```

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/environments/EnvironmentOperatingHoursTab.tsx frontend/src/components/environments/__tests__/EnvironmentOperatingHoursTab.test.tsx frontend/src/pages/environments/EnvironmentDetail.tsx
git commit -m "feat(env-hours): operating-hours editor tab + utilization card (Phase 5 SP5a)"
```

---

## Task 9: Environment Utilization table on Releases — Analytics

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseAnalytics.tsx`
- Create: `frontend/src/pages/releases/__tests__/ReleaseAnalytics.utilization.test.tsx`

- [ ] **Step 1: Write the failing render test**

Create `frontend/src/pages/releases/__tests__/ReleaseAnalytics.utilization.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import ReleaseAnalytics from '../ReleaseAnalytics';

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
      success_rate: 0, shipped_count: 0, failed_count: 0, emergency_pct: 0,
      emergency_count: 0, closed_count: 0, avg_cycle_time_seconds: 0, cycle_time_count: 0,
    }),
    conflicts: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/environmentOperatingHoursService', () => ({
  environmentOperatingHoursService: {
    overview: vi.fn().mockResolvedValue({
      rows: [{
        environment_id: 1, environment_name: 'Mortgage SIT', configured: true, timezone: 'UTC',
        total_operating_seconds: 100 * 3600, booked_operating_seconds: 60 * 3600, utilization_ratio: 0.6,
      }],
      unconfigured_count: 2,
    }),
  },
}));

describe('ReleaseAnalytics environment utilization', () => {
  it('renders a utilization row with the environment name', async () => {
    render(<MemoryRouter><ReleaseAnalytics /></MemoryRouter>);
    expect(await screen.findByText('Mortgage SIT')).toBeInTheDocument();
  });

  it('shows the unconfigured-environments caption', async () => {
    render(<MemoryRouter><ReleaseAnalytics /></MemoryRouter>);
    expect(await screen.findByText(/2 environment/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/releases/__tests__/ReleaseAnalytics.utilization.test.tsx`
Expected: FAIL — `Unable to find an element with the text: Mortgage SIT` (and the mock for `environmentOperatingHoursService` is unused because the page doesn't call it yet).

- [ ] **Step 3: Add the utilization section to `ReleaseAnalytics.tsx`**

Make these edits (anchor by content):

(a) Add imports after the existing `releaseMetricsService` import:
```tsx
import { environmentOperatingHoursService } from '../../services/environmentOperatingHoursService';
import type { EnvironmentUtilization } from '../../types/environmentOperatingHours';
```

(b) Add a `formatHours` helper next to the existing `formatDuration` helper (module scope):
```tsx
function formatHours(seconds: number): string {
  const h = seconds / 3600;
  return Number.isInteger(h) ? `${h}h` : `${h.toFixed(1)}h`;
}
```

(c) Inside the component, next to the existing `metrics`/`conflicts` state, add:
```tsx
  const [utilization, setUtilization] = useState<EnvironmentUtilization[]>([]);
  const [unconfiguredEnvs, setUnconfiguredEnvs] = useState(0);
```

(d) In the existing metrics `useEffect` (the one keyed on `[from, to]` that fetches `releaseMetricsService`), add the overview fetch alongside the others:
```tsx
    environmentOperatingHoursService.overview(params)
      .then((o) => { setUtilization(o.rows); setUnconfiguredEnvs(o.unconfigured_count); })
      .catch(() => { setUtilization([]); setUnconfiguredEnvs(0); });
```

(e) Add a `utilizationColumns` memo next to the existing `conflictColumns` memo:
```tsx
  const utilizationColumns = useMemo<GridColDef<EnvironmentUtilization>[]>(
    () => [
      { field: 'environment_name', headerName: 'Environment', flex: 1, minWidth: 180 },
      {
        field: 'utilization_ratio', headerName: 'Utilization', width: 130, type: 'number',
        valueFormatter: (p) => `${Math.round((p.value as number) * 100)}%`,
      },
      {
        field: 'booked_operating_seconds', headerName: 'Booked', width: 120, type: 'number',
        valueFormatter: (p) => formatHours(p.value as number),
      },
      {
        field: 'total_operating_seconds', headerName: 'Operating', width: 120, type: 'number',
        valueFormatter: (p) => formatHours(p.value as number),
      },
    ],
    []
  );
```

(f) Render the section in the returned JSX, immediately AFTER the Booking Conflicts `</Box>` block (the `DataTable` for conflicts) and BEFORE the `{data && (` scope-churn block:
```tsx
      <Typography variant="subtitle1" sx={{ mb: 1 }}>Environment Utilization (operating hours)</Typography>
      {unconfiguredEnvs > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
          {unconfiguredEnvs} environment{unconfiguredEnvs !== 1 ? 's have' : ' has'} no operating hours configured.
        </Typography>
      )}
      <Box sx={{ height: 300, width: '100%', mb: 3 }}>
        <DataTable<EnvironmentUtilization>
          storageKey="release-analytics-utilization"
          rows={utilization}
          columns={utilizationColumns}
          emptyMessage="No environments with operating hours configured"
          getRowId={(row) => row.environment_id}
        />
      </Box>
```

- [ ] **Step 4: Run the render test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/releases/__tests__/ReleaseAnalytics.utilization.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Type-check + re-run the existing ReleaseAnalytics test**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/pages/releases/__tests__/`
Expected: no tsc errors; both the SP5b `ReleaseAnalytics.test.tsx` and the new utilization test pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/releases/ReleaseAnalytics.tsx frontend/src/pages/releases/__tests__/ReleaseAnalytics.utilization.test.tsx
git commit -m "feat(env-hours): environment utilization table on Releases — Analytics (Phase 5 SP5a)"
```

---

## Task 10: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Full backend suite**

Run: `cd backend && DATABASE_URL=sqlite+aiosqlite:///:memory: PYTHONPATH=. uv run pytest -q`
Expected: all pass (previous baseline 821 pass / 1 skip; this adds ~30 tests → ~851 pass / 1 skip). Fix any regression before continuing.

- [ ] **Step 2: Confirm the migration applies on Postgres**

Run: `cd backend && DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run alembic upgrade head && ... alembic current`
Expected: head is the new `environment operating hours` revision (already applied in Task 1; this confirms idempotency / no drift).

- [ ] **Step 3: Full frontend unit suite + type-check**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: tsc clean; all unit tests pass (baseline + ~6 new). NOTE: 3 pre-existing Playwright `e2e/*.spec.ts` files fail to collect under vitest — this is a known, unrelated environment quirk, not a regression.

- [ ] **Step 4: Clean tree**

Run: `git status`
Expected: clean working tree (all changes committed across Tasks 1–9).

---

## Self-Review (completed by plan author)

**Spec coverage:**
- `EnvironmentOperatingHours` model (one row/env, `week` JSON + tz, unique env) → Task 1. ✅
- Migration (manual DDL) → Task 1. ✅
- Config service (`get_config`/`upsert_config`, tz + week validation, IDOR guard, revive) → Task 2. ✅
- Utilization: interval union + DST-correct operating segments → Task 3; DB-backed `environment_utilization` (active bookings, union ∩ operating, unconfigured shape) + `utilization_overview` (configured rows + `unconfigured_count`) → Task 4. ✅
- Endpoints: GET/PUT operating-hours + per-env utilization → Task 5; aggregate `/metrics/environments/utilization` → Task 6. ✅
- Frontend types + service → Task 7; editor tab + utilization card + tab wiring → Task 8; Analytics utilization table + unconfigured caption → Task 9. ✅
- Tests: validation, union, DST, outside-hours/inactive exclusion, unconfigured, tenant isolation, API shapes + 422, render tests → Tasks 2–9. ✅
- Non-goals respected: no holidays/split-shifts/tenant-default/versioning/charts/CSV. ✅

**Type consistency:** the utilization dict keys returned by `environment_utilization` (Task 4) match the `EnvironmentUtilization` Pydantic model (Task 5), the TS `EnvironmentUtilization` interface (Task 7), the API shape assertion (Task 5), and the Analytics columns (Task 9): `environment_id, environment_name, configured, timezone, total_operating_seconds, booked_operating_seconds, utilization_ratio`. `utilization_overview` → `{rows, unconfigured_count}` matches `UtilizationOverview` (Task 5) + TS (Task 7) + the overview endpoint test (Task 6) + the page consumption (Task 9). `OperatingHoursConfigResponse` `{configured, timezone, week}` matches the GET/PUT tests (Task 5) and the TS `OperatingHoursConfig`. `week` weekday order (0=Mon..6=Sun) is consistent across model, service (`d.weekday()`), tests, and the editor's `DAY_LABELS`.

**Placeholder scan:** no TBD/TODO/"add validation"/"similar to Task N"; every code step shows full code. Content-anchored edit locations are flagged as such, not placeholders.

**Known reuse (documented):** the per-env utilization endpoint imports `_as_dt` from `metrics.py` (DRY — avoids a third copy of the date helper); `_INACTIVE_BOOKING_STATES` intentionally duplicates the SP5b set locally (the two services are independent; sharing a constant would couple them — a deliberate small duplication, matching SP5b's own choice).
