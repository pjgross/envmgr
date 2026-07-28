# DORA Metrics (Phase 5, Sub-Project 2)

**Date:** 2026-07-28
**Status:** Design approved, ready for implementation plan
**Programme:** Phase 5 — DORA Metrics, Health Dashboard & PIR
**Base branch:** `main` (SP1 Incident Tracking merged)

## Context

Sub-project 2 of Phase 5. Computes the four DORA metrics from data the platform already
captures — deployments, builds, releases, and incidents (SP1) — plus one small new
capability (an `is_failed` flag on lifecycle states, for release-based Change Failure
Rate). SP1 (incidents) is merged and provides the failure/restore signal.

Decisions locked during brainstorming:
- **Deployment Frequency & Lead Time are deployment-based** (real deploy events + git
  commit timestamps).
- **Change Failure Rate is release-based**: a failed change = a release that closed in a
  lifecycle state flagged **failed**, or a release that is the **causal** release of an
  incident.
- **MTTR** = mean restore time over **all** incidents resolved in the window.
- **On-demand computation** (live SQL aggregation); the Redis `MetricsCache` + background
  recalc from the phase-5 doc are **deferred** until a perf need is proven.
- **No charting library** — the dashboard uses stat cards + a trend `DataTable`, matching
  the existing `ReleaseAnalytics` page (the codebase has no chart dep).

### Existing data this reads (verified)

- `Deployment` (`deployment`): `build_id`, `environment_id`, `release_id?`,
  `deployed_at`, `completed_at?`, `status` ∈ {pending, in_progress, **success**, **failed**,
  **rolled_back**}, `tenant_id`, `deleted_at`.
- `Build` (`build`): `subsystem_id`, `git_sha`, **`commit_timestamp`**, `build_number`.
- `Release` (`release`): `status`, `target_date`, `actual_date`, `lifecycle_template_id`,
  `release_kind`. `ReleaseStatusHistory` (`release_status_history`): `to_state`,
  `changed_at` — used to find when a release entered its terminal state.
- `Incident` (`incident`, SP1): `deployment_id?`, causal `release_id?`, `detected_at`,
  `resolved_at?`, `tenant_id`, `deleted_at`.
- `LifecycleTemplate` (`lifecycle_template`): state machine in a `definition` JSON;
  states currently carry `key/label/is_initial/is_terminal`. This sub-project adds an
  optional `is_failed` per-state flag.

## Goal

Four DORA metrics, windowed and filterable, exposed via API + CSV export and a dashboard
page; plus an admin-configurable `is_failed` lifecycle-state flag that drives CFR.

## Non-Goals

- Redis `MetricsCache` / background recalc job (deferred; on-demand is sufficient).
- A charting library (cards + tables only).
- A "project" filter (environment + release + date range cover the need; revisit later).
- PIR (#4), environment health (#3), release/utilization metrics (#5).

## Design

### 1. Metric definitions

All metrics take a **window** (`date_from`, `date_to`, inclusive) and optional filters
`environment_id`, `release_id`; all queries are tenant-scoped and exclude soft-deleted
rows. A `granularity` (`day` | `week` | `month`, default `week`) buckets the trend series.

**Deployment Frequency**
- Count of deployments with `status = "success"` whose `deployed_at` is in the window,
  optionally filtered by `environment_id`/`release_id`.
- Returns a total and a per-bucket series (count per period).

**Lead Time for Changes**
- Over the same `success` deployments, compute per-deployment
  `lead_seconds = deployed_at − build.commit_timestamp` (join `Deployment.build_id →
  Build.commit_timestamp`).
- Aggregate = **median** `lead_seconds` (report also **p90** and sample count). Per-bucket
  series = median per period. Deployments whose build has a `commit_timestamp` later than
  `deployed_at` (clock skew / bad data) are clamped to 0 and flagged in the count, not
  dropped silently.

**Change Failure Rate (release-based)**
- A release's **close** = the most recent `ReleaseStatusHistory.changed_at` whose
  `to_state == release.status`, provided `release.status` is a **terminal** state in the
  release's lifecycle template `definition`. Fallback to `actual_date` if no matching
  history row exists.
- **Denominator** = releases whose close date is in the window **and** that have ≥1
  deployment (any terminal status: success/failed/rolled_back) — i.e. changes that
  actually shipped. This excludes cancelled/abandoned releases.
- **Numerator** = denominator releases that are **failed**, where failed =
  (the release's terminal state has `is_failed = true` in its lifecycle template)
  **OR** (the release is the causal `release_id` of ≥1 non-deleted incident whose
  `detected_at` is in the window).
- `CFR = numerator / denominator` (0 when denominator is 0). Also return the two counts.

**MTTR (mean time to restore)**
- Over incidents (non-deleted) with a non-null `resolved_at` in the window:
  `restore_seconds = resolved_at − detected_at`; MTTR = **mean** (report median + count
  too). Per-bucket series bucketed by `resolved_at`.

### 2. `is_failed` lifecycle-state flag

- **Definition shape:** each entry in a template's `definition.states` may carry an
  optional `is_failed: bool` (only meaningful on terminal states; absent = false). The
  interpreter (`lifecycle_service`) ignores it for transitions — it is read only by
  `dora_service` and surfaced/edited by the admin panel.
- **Seed (release defaults):** in `app/services/release_defaults.py`, mark
  `completed_with_issues` and `backed_out` as `is_failed: true` in `_MAJOR_DEFINITION`,
  `_MINOR_DEFINITION`, and `_EMERGENCY_DEFINITION` (Emergency has `backed_out`). `completed`
  stays success; `rejected`/`cancelled` remain unflagged (and are excluded from CFR anyway,
  having no deployments).
- **Admin editor:** add a "Counts as failure" checkbox to the per-terminal-state editor in
  `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`, persisted into the state's
  `is_failed` in the `definition`. Applies to any entity type; only surfaced for terminal
  states.
- **Backfill:** `backend/scripts/backfill_release_failed_flags.py` — for every existing
  tenant's release lifecycle templates, set `is_failed` on the appropriate terminal states
  if not already present (idempotent; mirrors `scripts/backfill_incident_lifecycles.py`).
  Uses a name/key map so custom templates are left untouched except the known default keys.

### 3. Backend — `dora_service.py` + `app/api/v1/metrics.py`

**`app/services/dora_service.py`** (pure, tenant-scoped, on-demand):

```
deployment_frequency(db, tenant_id, window, filters, granularity) -> {total, series[]}
lead_time(db, tenant_id, window, filters, granularity)           -> {median_seconds, p90_seconds, count, series[]}
change_failure_rate(db, tenant_id, window, filters)              -> {rate, failed_count, shipped_count}
mttr(db, tenant_id, window, filters, granularity)                -> {mean_seconds, median_seconds, count, series[]}
dora_summary(db, tenant_id, window, filters, granularity)        -> {deployment_frequency, lead_time, change_failure_rate, mttr}
```

- `window` = `(date_from, date_to)`; `filters` = `{environment_id?, release_id?}`.
- Bucketing is done in Python from the queried rows (portable across Postgres/SQLite-test)
  — fetch the relevant rows in the window, group into period buckets by the bucket-start
  date, aggregate per bucket. Row volumes at current scale make this fine; note in code
  that a SQL `date_trunc` path is the future optimization if needed.
- A shared helper resolves each release's terminal-close date + `is_failed` by loading the
  release's lifecycle template `definition` (one template fetch per distinct
  `lifecycle_template_id`, memoized within the call).

**`app/api/v1/metrics.py`** (thin endpoints → `dora_service`):
- `GET /api/v1/metrics/dora` — query params `date_from`, `date_to` (required),
  `environment_id?`, `release_id?`, `granularity?` → `dora_summary`.
- `GET /api/v1/metrics/dora/export` — same params → `text/csv` (one row per bucket with
  DF/lead-time/MTTR columns + a summary block for CFR). `Content-Disposition: attachment`.
- Any authenticated tenant user may read (metrics are tenant-scoped, no mutation).
- Mount the router in `app/main.py` at prefix `/api/v1` following the existing pattern.

### 4. Frontend — DORA dashboard

- `frontend/src/types/dora.ts`, `frontend/src/services/doraService.ts`,
  `frontend/src/store/doraSlice.ts` (thunk `fetchDora(params)` + state).
- `frontend/src/pages/insights/DoraDashboard.tsx` at route `/insights/dora`:
  - **Filter bar:** environment (Autocomplete/Select), release (searchable, optional),
    date range (from/to), granularity (day/week/month). Sensible default window (last 90
    days).
  - **4 metric cards:** Deployment Frequency (total + per-period avg), Lead Time (median,
    humanized e.g. "2d 4h", with p90), Change Failure Rate (% + `failed/shipped`), MTTR
    (mean, humanized). Mirror `ReleaseAnalytics` card styling.
  - **Trend table:** a `DataTable` with one row per period bucket — columns: period,
    deployments, lead-time median, incidents resolved, MTTR. (CFR shown as the headline
    card, not per-bucket, since it is release-window-based.)
  - **Export CSV** button hitting the export endpoint.
- **Nav:** flip the existing `{ label: 'DORA Metrics', path: '/insights/dora', comingSoon:
  true }` entry in `navConfig.tsx` to live (remove `comingSoon`), and add the route in
  `App.tsx`.

## Files

**Backend — create:** `app/services/dora_service.py`, `app/api/v1/metrics.py`,
`scripts/backfill_release_failed_flags.py`, tests
`tests/services/test_dora_service.py`, `tests/integration/test_dora_api.py`.
**Backend — modify:** `app/services/release_defaults.py` (`is_failed` on default states),
`app/main.py` (mount router), `LifecycleTemplatesPanel` backend schema if state shape is
validated server-side (check — likely the `definition` is free-form JSON, so no schema
change needed).

**Frontend — create:** `src/types/dora.ts`, `src/services/doraService.ts`,
`src/store/doraSlice.ts`, `src/pages/insights/DoraDashboard.tsx`, test
`src/store/__tests__/doraSlice.test.ts`.
**Frontend — modify:** `src/components/admin/LifecycleTemplatesPanel.tsx` ("Counts as
failure" checkbox), `src/components/navConfig.tsx` (un-gate DORA), `src/App.tsx` (route),
`src/store/index.ts` (register slice).

## Testing

**Backend (`dora_service`):**
- Deployment Frequency: counts only `success`; respects env/release filter; correct
  per-bucket grouping; window boundaries inclusive; empty window → 0.
- Lead Time: median + p90 over `deployed_at − commit_timestamp`; clock-skew clamp to 0;
  ignores non-success; empty → null/0 with count 0.
- CFR: denominator = shipped (has deployment) + closed-in-window; numerator counts
  `is_failed` terminal state AND causal-incident (and does not double-count a release that
  is both); cancelled/abandoned (no deployment) excluded; denominator 0 → rate 0.
- MTTR: mean + median over resolved-in-window incidents; unresolved excluded.
- Tenant isolation: metrics never include another tenant's deployments/releases/incidents.
- `is_failed` seed present on the default release templates.

**Backend (API):** `GET /metrics/dora` returns the four blocks; CSV export has the right
content-type + rows; missing `date_from/date_to` → 422.

**Frontend:** `doraSlice` thunk/reducer test; a light `DoraDashboard` render test (cards
populate from a mocked summary).

`tsc --noEmit` clean; full backend suite green; `vitest run` green.

## Risks

- **CFR close-date accuracy** depends on `ReleaseStatusHistory` having a row for the
  terminal transition. Releases transitioned before history was recorded fall back to
  `actual_date`; if both are missing the release is excluded from CFR (documented, and the
  denominator/numerator counts are returned so the gap is visible).
- **In-Python bucketing** loads window rows into memory. Fine at current scale; the code
  notes the `date_trunc` SQL path as the escalation if row counts grow.
- **`is_failed` on custom templates:** the backfill only touches known default state keys;
  tenants with customized release lifecycles must set the flag via the admin panel. The
  dashboard should not imply CFR is authoritative until failed states are marked — surface
  the `shipped_count` so a 0% CFR with real shipments is legible.
