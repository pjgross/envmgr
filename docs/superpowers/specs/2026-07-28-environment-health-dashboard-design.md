# Environment Health Dashboard (Phase 5, Sub-Project 3)

**Date:** 2026-07-28
**Status:** Design approved, ready for implementation plan
**Programme:** Phase 5 — DORA Metrics, Health Dashboard & PIR
**Base branch:** `main` (SP1 + SP2 merged)

## Context

Sub-project 3 of Phase 5, independent of the others. Adds an **operational health** signal
for environments — pushed by external monitoring tools — and a dashboard that correlates
each environment's live health with its active bookings and planned change-request outages,
raising a **computed** alert when an environment is down/degraded during an active booking
with no planned outage to explain it.

Decisions locked during brainstorming:
- **Alert is computed on the dashboard** (a derived signal + red banner), NOT a persistent
  notification/alert record. The app has no notification infrastructure; building one is
  deferred until multiple features need it.
- **Health-push endpoint authenticates with an API key** (external monitoring tools),
  reusing the existing `api_key_auth` mechanism.
- Staleness threshold **15 minutes** → an environment with no recent sample shows `unknown`.
- "Planned outage" = a change request linked to the environment with `has_outage`, whose
  outage window (or scheduled window when explicit outage times are null) covers *now*.
- Dashboard lives under **Insights** (alongside DORA Metrics).

### Existing pieces this builds on (verified)

- `Environment` (`environment`): `name`, `environment_type`, `status`
  (`EnvironmentStatus`: active/inactive/maintenance/decommissioned — the **lifecycle**
  status, distinct from operational health), `tenant_id`, `deleted_at`.
- `Booking` (`booking`): `environment_id`, `start_date`, `end_date`, `status`, `tenant_id`,
  `deleted_at` — used for "active booking now".
- `ChangeRequest` (`change_request`): `has_outage`, `outage_start`, `outage_end`,
  `scheduled_start`, `scheduled_end`, `status`, `deleted_at`; linked to environments via
  `ChangeRequestEnvironment` (`change_request_environment`: `change_request_id`,
  `environment_id`) — used for "planned outage now".
- **API-key auth:** `api_key_auth(required_scope: str)` in `app/core/security.py` (reads the
  `X-API-Key` header, authenticates via `api_key_service.authenticate`, checks the scope is
  in the key's free-form `scopes` list). Keys are tenant-scoped.

## Goal

Capture per-environment health samples via an API-key push endpoint, and present a health
dashboard (traffic-light grid + computed alert banner) plus an environment-detail health
section, correlating health with bookings and planned outages.

## Non-Goals

- **No persistent alerts/notifications** (computed live only — no acknowledgement/history
  of alerts).
- **No manual/user health entry UI** — API-key push only (external monitoring).
- **No health retention/pruning** (append-only samples; retention is a later concern).
- **No per-subsystem health** — environment-level only.
- PIR (#4), release/utilization metrics (#5).

## Design

### 1. Data model — `EnvironmentHealthStatus` (`backend/app/db/models/environment_health.py`)

Append-only time-series (no soft delete):

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | FK tenant, indexed | tenant scoping |
| `environment_id` | FK `environment` | which env |
| `status` | String(10) | `up` \| `down` \| `issue` |
| `recorded_at` | DateTime(tz) | when the sample was observed; defaults to now if not supplied |
| `source` | String(100) | free text — which tool reported (e.g. "pingdom", "nagios") |
| `detail` | String(500), nullable | optional short message |

Index `(tenant_id, environment_id, recorded_at desc)` for the latest-sample and history
queries. Manual Alembic migration (`op.create_table`).

### 2. Push endpoint — `POST /api/v1/environments/{env_id}/health`

- **Auth:** `Depends(api_key_auth("environment:health"))` — a new scope string. (Scopes are
  a free-form list on each key; confirm during planning whether the API-key admin UI needs
  `environment:health` added to a selectable list, or accepts free-form scopes.)
- Body: `{ status: "up"|"down"|"issue", source: str, detail?: str, recorded_at?: datetime }`
  (`recorded_at` defaults to now).
- Validates `env_id` belongs to the API key's tenant (the `api_key_auth` dependency exposes
  the authenticated key → its `tenant_id`); rejects cross-tenant / missing env with 404/422.
- Inserts one `EnvironmentHealthStatus` row; returns 201 with the created sample.

### 3. History — `GET /api/v1/environments/{env_id}/health/history`

- JWT-authenticated (`get_current_user`), tenant-scoped. Returns the most recent N samples
  (default 50, `limit` query param, capped) for that environment, newest first.

### 4. Dashboard query — `GET /api/v1/environments/health`

JWT-authenticated. For each non-deleted, non-`decommissioned` environment in the tenant,
compute (in one service call, `environment_health_service.health_overview`):

- **current_status / last_recorded_at:** the latest `EnvironmentHealthStatus` sample for the
  env. If none, or `recorded_at` older than **15 minutes** (a module constant
  `STALE_AFTER = timedelta(minutes=15)`), `current_status = "unknown"`.
- **active_booking:** a non-deleted `Booking` for the env whose `start_date <= now <=
  end_date` and whose `status` is **not** in the excluded set `{draft, cancelled, rejected}`
  (an "active/approved" booking). Returns a bool + a small summary (project name, window).
  (Pin the exact excluded statuses against the default booking lifecycle during planning.)
- **planned_outage:** a non-deleted `ChangeRequest` linked to the env (via
  `ChangeRequestEnvironment`) with `has_outage = true` whose outage window
  (`outage_start..outage_end`, or `scheduled_start..scheduled_end` when outage times are
  null) covers *now*, and whose `status` is not cancelled/rejected. Returns a bool.
- **alert:** `current_status in {"down", "issue"}` AND `active_booking` AND NOT
  `planned_outage`.

Returns `list[{ environment_id, environment_name, current_status, last_recorded_at,
active_booking, active_booking_summary, planned_outage, alert }]`.

### 5. Frontend

- `frontend/src/types/environmentHealth.ts`, `frontend/src/services/environmentHealthService.ts`.
- **Health dashboard page** `frontend/src/pages/insights/HealthDashboard.tsx` at
  `/insights/health` (local `useState` + direct service call, mirroring `DoraDashboard`/
  `ReleaseAnalytics` — no Redux slice):
  - A red **alert banner** at the top listing environments in the alert condition (or
    hidden when none).
  - A `DataTable` grid: environment name, a **traffic-light status chip**
    (green=`up`, red=`down`, amber=`issue`, grey=`unknown`), last-recorded time, active
    booking (name/window or "—"), planned outage (yes/—), and an alert flag. Row → env detail.
  - Follows the display-name convention (never `#id`).
- **Env-detail health section:** on the Environment detail page
  (`frontend/src/pages/environments/EnvironmentDetail*` — find the tabbed detail), add a
  **Health** tab/section showing current status chip, a **status-history timeline** (from
  `/health/history`), the active booking, and current change-requests-with-outage (TECRs).
- **Nav:** add a "Environment Health" entry under Insights (`navConfig.tsx`), route in
  `App.tsx`.

### 6. Migration + wiring

One Alembic migration for `environment_health_status`. Register the model in
`app/db/models/__init__.py`. Add the router (`app/api/v1/environment_health.py`) to
`app/main.py`. No tenant-seed changes (no per-tenant defaults needed).

## Files

**Backend — create:** `app/db/models/environment_health.py`,
`app/api/v1/schemas/environment_health.py`, `app/services/environment_health_service.py`,
`app/api/v1/environment_health.py`, `alembic/versions/<rev>_environment_health.py`, tests
`tests/services/test_environment_health_service.py`, `tests/integration/test_environment_health_api.py`.
**Backend — modify:** `app/db/models/__init__.py` (register model), `app/main.py` (mount router).

**Frontend — create:** `src/types/environmentHealth.ts`,
`src/services/environmentHealthService.ts`, `src/pages/insights/HealthDashboard.tsx`, plus
the env-detail health section component.
**Frontend — modify:** `src/components/navConfig.tsx` (nav entry), `src/App.tsx` (route),
the Environment detail page (add the Health tab/section).

## Testing

**Backend (`environment_health_service`):**
- `record_sample` inserts a row with the given status/source, defaulting `recorded_at`.
- `current_status` derivation: latest sample wins; no samples → `unknown`; a sample older
  than 15 min → `unknown`; a fresh sample → its status.
- **Alert truth table:** `down` + active booking + no planned outage → **alert**;
  `down` + active booking + planned outage → no alert; `up` + active booking → no alert;
  `down` + no active booking → no alert; `issue` behaves like `down` for alerting.
- active_booking excludes draft/cancelled/rejected and out-of-window bookings.
- planned_outage: outage-window covers now → true; scheduled-window fallback when outage
  times null; window not covering now → false.
- Tenant isolation: overview/history never include another tenant's environments/samples.

**Backend (API):**
- Push with a valid API key (scope `environment:health`) records a sample (201); missing key
  → 401; key without the scope → 403; env from another tenant → 404.
- History + overview endpoints return tenant-scoped data; overview reflects the alert flag.

**Frontend:** service call + a light `HealthDashboard` render test (status chips + alert
banner from a mocked overview).

`tsc --noEmit` clean; full backend suite green; `vitest run` green.

## Risks

- **Booking "active/approved" status coupling:** the excluded-status set
  `{draft, cancelled, rejected}` must match the real default booking lifecycle terminal/
  initial states — verify against `booking` lifecycle defaults during planning; a wrong set
  makes the alert over- or under-fire. Mitigation: the alert also requires the booking
  window to cover *now*, which already excludes most noise.
- **Staleness vs push cadence:** 15 min assumes monitoring pushes at least that often; a
  slower cadence shows `unknown` (grey) rather than a false green. This is the safe failure
  mode (never claim healthy without a fresh sample) and is called out in the UI legend.
- **API-key scope availability:** if the API-key admin UI offers a fixed scope list,
  `environment:health` must be added there so operators can mint monitoring keys; if scopes
  are free-form, no UI change is needed. Confirm during planning.
