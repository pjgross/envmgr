# Release Metrics + Booking Conflicts (Phase 5, Sub-Project 5b)

**Date:** 2026-07-29
**Status:** Design approved, ready for implementation plan
**Programme:** Phase 5 — DORA Metrics, Health Dashboard & PIR
**Base branch:** `main` (SP1–SP4 merged)

## Context

Phase 5's final sub-project (SP5) was split into **5b** (this spec — release metrics +
booking conflicts, pure aggregation over existing data) and **5a** (environment operating
hours + utilization, a heavier new capability — separate spec, built next). This is 5b.

Adds release-level metrics (success rate, emergency %, average cycle time) and booking-
conflict counts, exposed via the existing metrics API and surfaced on the existing
`Releases — Analytics` page. No new models; all data already exists.

Decisions locked during brainstorming:
- **success_rate** reuses SP2's failed definition (a release is "failed" if it closed in an
  `is_failed` lifecycle state OR is the causal release of an incident) for consistency with
  the DORA Change Failure Rate.
- **avg cycle time** = mean(`actual_date − created_at`) over shipped releases (creation →
  ship), a release-level "time to ship" — deliberately distinct from DORA's commit→deploy
  lead time.
- **emergency %** = releases with `release_type == "Emergency"` ÷ total closed releases.
- Booking conflicts are counted **per environment per month**, reusing the existing
  `conflict_service` overlap logic (active/approved bookings only).
- UI: **extend the existing `Releases — Analytics` page** (cards + tables; no new page, no
  chart library).

### Existing pieces (verified)

- `Release` (`release`): `status` (lifecycle state), `release_type` (e.g. Major/Minor/
  Emergency), `actual_date`, `created_at` (from Base), `lifecycle_template_id`, `tenant_id`,
  `deleted_at`. `ReleaseStatusHistory` gives terminal-close timestamps.
- SP2 shipped `dora_service.change_failure_rate` (release-based failed logic + `is_failed`
  lifecycle-state flag) — the failed/shipped definition to reuse.
- `Booking` (`booking`): `environment_id`, `start_date`, `end_date`, `status`. `conflict_service`
  (`list_conflicts`) has the overlap logic to reuse.
- Metrics live at `app/api/v1/metrics.py` (SP2) + the `Releases — Analytics` page
  (`frontend/src/pages/releases/ReleaseAnalytics.tsx`, local-state + direct service, cards +
  `DataTable`, no chart lib).

## Goal

Release success-rate / emergency-% / avg-cycle-time and booking-conflict-per-env-per-month
metrics, on-demand and tenant-scoped, surfaced on the Releases — Analytics page.

## Non-Goals

- Environment operating hours + utilization (SP5a — next).
- CSV export (defer); per-project filter; any new model or migration.

## Design

### 1. Service — `backend/app/services/release_metrics_service.py`

All functions take a window (`date_from`, `date_to`), tenant-scoped, non-deleted.

- `release_metrics(db, tenant_id, date_from, date_to) -> dict`:
  - Consider releases whose **close date** (terminal-state transition, latest
    `ReleaseStatusHistory.changed_at` where `to_state == release.status`; fallback
    `actual_date`) falls in the window and whose status is terminal — the "closed in window"
    set. (Same close-date resolution as SP2 CFR; extract/share a helper if clean, else
    replicate the small logic.)
  - **shipped** = closed releases that had ≥1 deployment (mirrors SP2's "shipped" so
    success_rate is the exact complement of CFR). **failed** = shipped releases that are
    `is_failed`-terminal OR causal of an incident in the window (reuse the SP2 predicate).
  - `success_rate` = `(shipped - failed) / shipped` (0 when shipped == 0); return
    `shipped_count`, `failed_count`.
  - `emergency_pct` = `emergency_count / closed_count` where `emergency_count` = closed
    releases with `release_type == "Emergency"`; return counts (0 when closed_count == 0).
  - `avg_cycle_time_seconds` = mean(`actual_date − created_at`) over shipped releases with a
    non-null `actual_date` (clamp negatives to 0); return `count`.
  - **DRY note:** if reusing SP2's CFR internals is awkward, call
    `dora_service.change_failure_rate(db, tenant_id, date_from, date_to)` and derive
    `success_rate = 1 - rate`, `shipped_count`/`failed_count` from its result — the cleanest
    reuse. Prefer this. Compute `emergency_pct` and `avg_cycle_time` here.
- `booking_conflicts(db, tenant_id, date_from, date_to) -> list[dict]`:
  - Over active bookings (window overlaps `[date_from, date_to]`; status not in
    `{draft, rejected, closed}` — draft plus the two terminal booking states; the lifecycle
    has no `cancelled` state), detect overlapping pairs per environment (reuse
    `conflict_service`'s overlap logic; if its signature doesn't fit a bulk/window query,
    load the window's bookings per env and count overlapping pairs in Python).
  - Return rows `{environment_id, environment_name, month (YYYY-MM), conflict_count}` — a
    conflict counted in the month of its overlap start. Tenant-scoped.

### 2. API — extend `backend/app/api/v1/metrics.py`

- `GET /api/v1/metrics/releases?date_from=&date_to=` → `release_metrics` (JWT;
  `current_user.active_tenant_id`). `date_from`/`date_to` are `date` params, reusing the
  existing `_as_dt` helper (with `end_of_day=True` for `date_to`) so the window is
  full-day-inclusive — matching the SP2 fix.
- `GET /api/v1/metrics/bookings/conflicts?date_from=&date_to=` → `booking_conflicts`.
- Both default a sensible window if omitted? No — require `date_from`/`date_to` (422 if
  missing), consistent with `/dora`.

### 3. Frontend — extend `Releases — Analytics`

In `frontend/src/pages/releases/ReleaseAnalytics.tsx` (or a small new section component it
renders): add
- a **release-metrics card row**: Success Rate (`%` + `failed/shipped`), Emergency %
  (`% + count/total`), Avg Cycle Time (humanized via a `formatDuration`-style helper —
  reuse the one from `DoraDashboard` if exported, else a local copy);
- a **Booking Conflicts** `DataTable`: environment × month → conflict count (empty state
  "No booking conflicts in range").
The page already has a date range + fetch pattern; add two service calls
(`releaseMetricsService.releases(...)` and `.conflicts(...)`) and render below the existing
scope-churn content. No new nav entry.

Frontend files: `src/types/releaseMetrics.ts`, `src/services/releaseMetricsService.ts`
(`releases(params)`, `conflicts(params)`), and the additions to `ReleaseAnalytics.tsx`.

## Files

**Backend — create:** `app/services/release_metrics_service.py`, tests
`tests/services/test_release_metrics_service.py`, `tests/integration/test_release_metrics_api.py`.
**Backend — modify:** `app/api/v1/metrics.py` (two endpoints).
**Frontend — create:** `src/types/releaseMetrics.ts`, `src/services/releaseMetricsService.ts`.
**Frontend — modify:** `src/pages/releases/ReleaseAnalytics.tsx`.

## Testing

**Backend (`release_metrics_service`):**
- success_rate: a clean shipped release + a backed_out (is_failed) shipped release →
  success_rate 0.5; a release with a causal incident counts failed; empty window → 0 with
  counts 0.
- emergency_pct: Emergency vs non-Emergency closed releases → correct fraction.
- avg_cycle_time: mean of `actual_date − created_at` over shipped; negatives clamped;
  releases without `actual_date` excluded from the average.
- booking_conflicts: two overlapping active bookings on one env in a month → count 1 for
  that env/month; non-overlapping → 0; draft/cancelled bookings excluded; per-env grouping.
- Tenant isolation on both (another tenant's releases/bookings never counted).

**Backend (API):** `/metrics/releases` and `/metrics/bookings/conflicts` return 200 with the
right shape; missing dates → 422.

**Frontend:** service calls; a light render test that the cards + conflicts table populate
from a mocked response.

`tsc --noEmit` clean; full backend suite green; `vitest run` green.

## Risks

- **success_rate ↔ CFR consistency:** reusing `dora_service.change_failure_rate` keeps
  success_rate as the exact complement of the DORA CFR (no drift from a second definition).
  If instead the logic is re-implemented, the two could diverge — prefer the reuse path.
- **`created_at` availability:** `avg_cycle_time` relies on `Release.created_at` (from Base).
  Confirm it exists during planning; if a release lacks `actual_date` it's excluded from the
  average (documented).
- **Conflict double-counting:** an overlapping pair must be counted once per month bucket,
  not once per booking — the pair-based counting handles this; the test asserts count 1 for
  a single overlapping pair.
