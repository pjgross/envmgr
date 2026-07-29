# Environment Operating Hours + Utilization (Phase 5, Sub-Project 5a)

**Date:** 2026-07-29
**Status:** Design approved, ready for implementation plan
**Programme:** Phase 5 — DORA Metrics, Health Dashboard & PIR
**Base branch:** `main` (SP1–SP4 + SP5b merged; tip `04913e0`)

## Context

Phase 5's final sub-project (SP5) was split into **5b** (release metrics + booking
conflicts — DONE, merged `04913e0`) and **5a** (this spec — environment operating hours +
utilization). 5a is the heavier half: it introduces a new capability (per-environment
operating-hours configuration) and a timezone-aware utilization metric computed against it.

Utilization answers "how much of an environment's *available* (operating) time is actually
booked?" — distinct from raw calendar occupancy, because environments are not assumed to run
24×7 or on a fixed business week (an explicit user requirement: **no business-day
assumption**). Each environment defines its own weekly operating hours and timezone.

### Existing pieces (verified)

- `Environment` (`environment`): `id, name, environment_type, status, tenant_id,
  custom_fields, deleted_at`. No operating-hours concept exists today.
- `Booking` (`booking`): `environment_id, start_date, end_date` (both
  `DateTime(timezone=True)`), `status`, `tenant_id`, `deleted_at`. SP5b established the
  **active-booking** definition: status ∉ `{draft, rejected, closed}` (the booking lifecycle
  states are `draft, submitted, approved, rejected, extension_requested, closed`; there is no
  `cancelled` state). Legacy seed rows may carry non-lifecycle statuses (e.g. uppercase
  `PENDING`) — those are treated as active (not in the excluded set).
- `GET /environments/{id}/schedule` already returns bookings + change requests over a window
  (a calendar view) — NOT utilization; unaffected by this work.
- Metrics live at `app/api/v1/metrics.py`; the `Releases — Analytics` page
  (`frontend/src/pages/releases/ReleaseAnalytics.tsx`, local-state + direct-service, cards +
  `DataTable`, no chart lib) already hosts release metrics + booking conflicts (SP5b).
- The Environment detail page uses a tabbed layout (SP3 added a Health tab as tab index 6).
- No timezone library is currently used; Python 3.12 stdlib **`zoneinfo`** is available.

Decisions locked during brainstorming:
- **Operating-hours model:** weekly recurring — 7 weekday rows, each open/close or closed —
  plus one IANA timezone per environment. No holiday/date exceptions, no split shifts.
- **Booked time:** active bookings (status ∉ `{draft, rejected, closed}`), reusing SP5b's
  definition for consistency.
- **Overlap rule:** **union** — each operating-hour is booked or not (binary), so
  `utilized + available = total` and utilization is always 0–100%. Contention is already
  surfaced separately by SP5b booking-conflicts.
- **Unconfigured environments:** excluded from the aggregate utilization view (NOT defaulted
  to 24×7); surfaced as a count ("N environments have no operating hours").
- **Historical windows:** utilization always uses the environment's *current* operating-hours
  config, even for past windows (no historical versioning — documented limitation).
- **UI:** operating-hours editor as a new tab on Environment detail; utilization shown both as
  an aggregate table on `Releases — Analytics` and as a per-environment card on Environment
  detail.

## Goal

Per-environment weekly operating-hours + timezone configuration, and a timezone-aware,
DST-correct utilization metric (`booked ÷ total operating time`, union-based, ≤ 100%),
on-demand and tenant-scoped, surfaced per-environment and in aggregate.

## Non-Goals

- Holiday / one-off date exceptions; split shifts (multiple intervals per day).
- Per-tenant default operating hours; bulk-apply across environments.
- Historical operating-hours versioning (utilization uses current config for any window).
- Charts / time-series of utilization (single scalar per env per window, like SP5b).
- CSV export (defer).

## Design

### 1. Data model — `EnvironmentOperatingHours`

New table `environment_operating_hours` (`backend/app/db/models/environment_operating_hours.py`),
**one row per environment** (absence of a row = "not configured"):

- `tenant_id` → FK `tenant.id`, indexed.
- `environment_id` → FK `environment.id`, indexed, **unique** (`UniqueConstraint` — one config
  per env). Enforced at both DB and service level (upsert).
- `timezone` → `String(64)`, IANA name (e.g. `Europe/London`, `UTC`).
- `week` → `JSON`: a list of exactly 7 entries indexed by weekday **0 = Monday … 6 = Sunday**,
  each `{"closed": bool, "open": "HH:MM", "close": "HH:MM"}`. When `closed` is true, `open`/
  `close` are ignored (stored as `null` or omitted).
- `created_at` / `updated_at` (from Base), `deleted_at` (soft delete; a cleared config is a
  soft-deleted row so it re-creates cleanly, mirroring the PIR pattern).

**Migration:** manual DDL via `op.create_table()` (per the project's Alembic convention — no
`--autogenerate`). All columns SQLite-compatible (JSON via `sqlalchemy.types.JSON`, no native
enum).

**Validation** (service layer, on write):
- `timezone` must resolve via `zoneinfo.ZoneInfo(tz)` (else 422).
- `week` must have 7 entries; each non-closed entry must have `open`/`close` matching
  `^\d{2}:\d{2}$`, valid 00:00–23:59, with `open < close` (else 422). (Overnight windows that
  cross midnight are out of scope — `close` must be after `open` on the same day.)

### 2. Services

**`backend/app/services/environment_operating_hours_service.py`** (config CRUD):
- `get_config(db, tenant_id, environment_id) -> EnvironmentOperatingHours | None` — the current
  (non-deleted) row for the env, tenant-scoped.
- `upsert_config(db, tenant_id, environment_id, timezone, week) -> EnvironmentOperatingHours` —
  IDOR-guards the env belongs to `tenant_id` and is not soft-deleted (404 otherwise); validates
  tz + week (422 otherwise); creates or updates the single row (revives a soft-deleted one).
  Uses `db.flush()` (never `db.commit()` — the outbox/session convention).

**`backend/app/services/environment_utilization_service.py`** (the calculation):
- `_operating_segments(config, date_from, date_to) -> tuple[list[tuple[datetime, datetime]], float]`
  — pure helper (no DB). Iterate each calendar date `D` from `date_from` to `date_to` **in the
  config's timezone**. For each date, look up `week[D.weekday()]`; if not closed, build
  `local_open = datetime(D, open, tzinfo=ZoneInfo(tz))` and `local_close` similarly, convert
  both to UTC (`.astimezone(timezone.utc)`), clip to `[date_from, date_to]`, and if non-empty
  append the `(start_utc, end_utc)` segment. Returns the list of UTC operating segments plus
  their total seconds. **DST-correct**: because open/close are wall-clock times localized
  per-date, a spring-forward/fall-back day naturally yields a 23h/25h calendar day while the
  operating window stays anchored to wall-clock time; `astimezone` applies the right offset for
  each date. (Times inside a DST skipped hour are rare for whole-hour operating bounds; zoneinfo
  resolves them deterministically — acceptable for this metric.)
- `environment_utilization(db, tenant_id, environment_id, date_from, date_to) -> dict`:
  - Load env (tenant-scoped, non-deleted) → 404 if missing.
  - Load its config. If none → return `{environment_id, environment_name, configured: False,
    timezone: None, total_operating_seconds: 0.0, booked_operating_seconds: 0.0,
    utilization_pct: 0.0}`.
  - Compute operating segments + `total`.
  - Load **active** bookings for the env (tenant-scoped, non-deleted, status ∉
    `{draft, rejected, closed}`, window-overlapping) → list of `(start, end)` UTC intervals
    (naive→UTC normalised).
  - `booked` = duration of `union(booking intervals) ∩ operating segments`. Compute by, for
    each operating segment, intersecting with the **merged** (union'd) booking intervals and
    summing — guarantees each operating-second is counted once (union rule).
  - `utilization_pct = booked / total` (0.0 when `total == 0`), returned as a 0–1 float.
  - Return `{environment_id, environment_name, configured: True, timezone,
    total_operating_seconds, booked_operating_seconds, utilization_pct}`.
- `utilization_overview(db, tenant_id, date_from, date_to) -> dict`:
  - For every non-deleted env in the tenant, compute `environment_utilization`.
  - Return `{rows: [<configured envs' util dicts, sorted by environment_name>],
    unconfigured_count: <int>}`. Unconfigured envs are counted, not listed as rows.

Interval helpers (`_merge_intervals`, `_intersect`) are small pure functions in the utilization
service, unit-tested directly.

### 3. API

**`backend/app/api/v1/environment_operating_hours.py`** (new router, mounted in `main.py`):
- `GET /api/v1/environments/{env_id}/operating-hours` → the config, or `{configured: false}`
  when none. JWT; `current_user.active_tenant_id`.
- `PUT /api/v1/environments/{env_id}/operating-hours` → body `{timezone, week}`; upserts;
  returns the saved config. JWT. (Authz: any authenticated tenant user, consistent with other
  per-environment configuration in this app.)
- `GET /api/v1/environments/{env_id}/utilization?date_from&date_to` → per-env utilization.
  `date_from`/`date_to` are required `date` params (422 if missing), normalised with the same
  end-of-day-inclusive helper pattern as SP2/SP5b (`date_to` inclusive of the whole day).

**Extend `backend/app/api/v1/metrics.py`:**
- `GET /api/v1/metrics/environments/utilization?date_from&date_to` → `utilization_overview`
  (JWT, required dates → 422). Mirrors SP5b's metrics endpoints (same `_as_dt` handling).

Pydantic schemas live at `app/api/v1/schemas/` (canonical location): an
`OperatingHoursDay`/`OperatingHoursConfig` request+response model and a utilization response
model. `week` validated as exactly 7 entries.

### 4. Frontend

Types `src/types/environmentOperatingHours.ts` (`OperatingHoursConfig`, `OperatingHoursDay`,
`EnvironmentUtilization`, `UtilizationOverview`) and service
`src/services/environmentOperatingHoursService.ts` (`getConfig(envId)`, `putConfig(envId, cfg)`,
`utilization(envId, params)`, `overview(params)`; params send plain `YYYY-MM-DD` — the SP5b
date-param contract).

- **Environment detail — new "Operating Hours" tab**
  (`components/environments/EnvironmentOperatingHoursTab.tsx`): a 7-row editor (Mon→Sun; each
  row a "Closed" toggle + `open`/`close` `type="time"` inputs) + an IANA timezone selector +
  Save. Loads existing config; Save calls `putConfig`. Uses a `useRef` for `useSnackbar()` if
  used in callbacks (the SP4 infinite-loop lesson). Below the editor, a **Utilization card**
  (util% + `booked / total` hours over a default last-90-day window) via `utilization(envId)`.
- **Releases — Analytics — Environment Utilization table**: add a section below the existing
  booking-conflicts table — a `DataTable` (Environment / Utilization % / Booked / Total hours),
  driven by the page's existing `from`/`to` range via `overview(params)`; empty-state
  "No environments with operating hours configured"; when `unconfigured_count > 0`, a caption
  "N environment(s) have no operating hours."

Humanized hours via a small `formatHours(seconds)` helper (e.g. `60h`, `1.5h`); utilization
shown as `NN%`.

## Files

**Backend — create:** `app/db/models/environment_operating_hours.py`, migration
`alembic revision -m "environment operating hours"` (manual DDL),
`app/services/environment_operating_hours_service.py`,
`app/services/environment_utilization_service.py`,
`app/api/v1/environment_operating_hours.py`,
`app/api/v1/schemas/environment_operating_hours.py`,
`tests/services/test_environment_operating_hours_service.py`,
`tests/services/test_environment_utilization_service.py`,
`tests/integration/test_environment_operating_hours_api.py`.
**Backend — modify:** `app/api/v1/metrics.py` (utilization overview endpoint), `app/main.py`
(mount the new router).
**Frontend — create:** `src/types/environmentOperatingHours.ts`,
`src/services/environmentOperatingHoursService.ts`,
`src/components/environments/EnvironmentOperatingHoursTab.tsx`, a render test.
**Frontend — modify:** `EnvironmentDetail` (add the tab), `ReleaseAnalytics.tsx` (utilization
table).

## Testing

**Backend — operating-hours service:** upsert creates then updates the single row; invalid tz →
422; `open >= close` → 422; malformed `HH:MM` → 422; wrong-tenant env → 404 (IDOR); soft-deleted
config revives on re-upsert.

**Backend — utilization service:**
- Known config (Mon–Fri 08:00–16:00 = 8h, Sat/Sun closed), a 1-week window → total = 40h.
- A single active booking covering Tue 09:00–12:00 → booked = 3h; utilization = 3/40.
- Two overlapping active bookings (Tue 09–12 and Tue 11–13) → union counts 09–13 within
  operating hours = 4h (not 5h) — the union rule.
- A booking outside operating hours (Sat) → contributes 0.
- draft/rejected/closed bookings excluded.
- **DST:** a window spanning a spring-forward date (e.g. Europe/London late March) with fixed
  09:00–17:00 hours → total reflects wall-clock 8h/day across the transition (the UTC span of
  the DST day differs but wall-clock hours are constant).
- Unconfigured env → `configured: false`, zero totals, excluded from overview rows but counted
  in `unconfigured_count`.
- Tenant isolation: another tenant's env/bookings never counted.

**Backend — API:** GET/PUT round-trip an operating-hours config; PUT with bad tz → 422;
per-env + aggregate utilization endpoints return 200 with the right shape; missing dates → 422;
tenant-scoped.

**Frontend:** service calls; a render test that the operating-hours editor loads a config and
the utilization card / analytics table populate from a mocked response.

`tsc --noEmit` clean; full backend suite green; `vitest run` green.

## Risks

- **DST correctness** is the main subtlety. Mitigation: localize wall-clock open/close per
  calendar date via `zoneinfo` and convert to UTC per date, rather than assuming a fixed
  UTC offset for the whole window. A dedicated DST test pins this.
- **Timezone data availability:** `zoneinfo` needs the OS tzdata or the `tzdata` package.
  **Confirmed 2026-07-29** in the backend env: `zoneinfo.ZoneInfo("Europe/London")` resolves and
  DST offsets shift correctly across the 2026-03-29 transition (09:00 local → +00:00 before,
  +01:00 after). No `tzdata` dependency needed. (Re-check if the prod container image is
  minimal/distroless.)
- **Unbounded windows:** `_operating_segments` iterates day-by-day; a multi-year window is
  O(days) but trivially cheap. No guard needed at current scale.
- **Current-config-for-historical-windows** is a deliberate simplification: utilization for a
  past window uses today's operating hours. Documented; acceptable because operating hours
  change rarely and this is a descriptive dashboard metric.
