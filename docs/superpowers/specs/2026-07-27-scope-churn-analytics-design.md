# Scope-Churn Analytics (pillar B) — does changing scope correlate with delays/issues?

**Date:** 2026-07-27
**Status:** Approved (design) — pending implementation plan
**Builds on:** the scope programme (PRs #11–#15). Reuses `scope_creep_count`, `'Scope Change'` /
`'Reschedule Reason'` release events, deployment statuses.

## Problem

The release manager can now see scope creep per release, but not the pattern across releases:
*does a release whose scope changed tend to slip or go wrong more than one whose scope held?* This
is pillar B from the scope-windows spec — a descriptive correlation between **scope churn** and
two outcomes: **delays** and **release issues**. There is no analytics endpoint or reporting page
today; this adds the first one.

It is honestly framed as observational (small-sample correlation, not causation).

## Decisions (locked)

1. **Cohort = shipped project releases in a date window.** A release is in-cohort if
   `release_kind == "project"`, `actual_date` is set, and `actual_date` falls in the selected
   `[date_from, date_to]`. Draft/in-flight releases are excluded (no outcome yet). Project-only
   because the scope baseline is a project-release concept.
2. **Per-release flags:**
   - **`scope_changed`** = `scope_creep_count > 0` (items entering after `scope_deadline`) **OR**
     the release has ≥1 `'Scope Change'` release event (the fallback baseline for releases without
     a deadline).
   - **`delayed`** = has ≥1 `'Reschedule Reason'` release event **OR** `actual_date > target_date`.
     *This is provably equivalent to "rescheduled OR late vs original target" without parsing
     reschedule-event text: a never-rescheduled release has original == current `target_date`, so
     `actual_date > target_date` is exactly "late vs original"; a rescheduled release is already
     caught by the first clause.* (When `target_date` is null, only the reschedule clause applies.)
   - **`had_issue`** = ≥1 non-deleted `Deployment` of the release with `status IN ('failed',
     'rolled_back')`.
3. **Output = two cohorts (scope-changed vs stable) with % delayed / % had-issue, plus a
   per-release drill-down.**

## Backend

### Endpoint
`GET /releases/scope-churn-analytics?date_from=&date_to=` → `ScopeChurnAnalyticsRead`. Register on
the main `router` **before** the `/{release_id}` route (like `/calendar` and `/timeline`), so the
static segment isn't captured as an id.

### Queries (all tenant-scoped)
1. **Cohort:** `Release` where `tenant_id`, `deleted_at IS NULL`, `release_kind == "project"`,
   `actual_date IS NOT NULL`, and (when provided) `actual_date >= date_from` / `<= date_to`.
2. `release_scope_service.scope_creep_counts(db, release_ids, tenant_id)` → creep per release.
3. **Scope-change events:** `ReleaseEvent` join `ReleaseEventType` (name `'Scope Change'`, tenant),
   `release_id IN ids` → set of release ids that have one.
4. **Reschedule events:** same join with name `'Reschedule Reason'` → set.
5. **Issue deployments:** `Deployment` where `release_id IN ids`, `tenant_id`, `deleted_at IS NULL`,
   `status IN ('failed','rolled_back')` → set.
6. Per release compute the three booleans; guard `delayed`'s date clause with
   `target_date is not None and actual_date > target_date`.

### Response schema (`schemas/scope_churn_analytics.py`)
```python
class ChurnCohort(BaseModel):
    count: int
    delayed_count: int
    delayed_pct: float       # round(100*delayed_count/count, 1); 0.0 when count == 0
    issue_count: int
    issue_pct: float

class ChurnReleaseRow(BaseModel):
    release_id: int
    name: str
    shipped_at: datetime     # actual_date
    scope_changed: bool
    delayed: bool
    had_issue: bool

class ScopeChurnAnalyticsRead(BaseModel):
    date_from: Optional[datetime]
    date_to: Optional[datetime]
    scope_changed: ChurnCohort   # releases where scope_changed is True
    stable: ChurnCohort          # releases where scope_changed is False
    releases: list[ChurnReleaseRow]   # all cohort releases, for drill-down
```
Both cohorts' `delayed_count`/`issue_count` count releases within that cohort whose `delayed` /
`had_issue` flag is true; percentages are of the cohort `count`.

Service lives in a small module (`app/services/scope_churn_service.py`) so the aggregation is
unit-testable independently of the endpoint.

## Frontend

### "Release Analytics" page
New page `pages/releases/ReleaseAnalytics.tsx`, route **`/releases/analytics`** (registered before
`/releases/:id` in `App.tsx`), nav entry **"Releases — Analytics"** in the Release Management group.

- **Date-range filter**: two date inputs (`date_from`/`date_to`), defaulting to the last 90 days by
  `actual_date`. Re-fetches on change.
- **Two cohort cards** (MUI `Card`): "Scope changed (N)" and "Stable scope (N)", each showing
  **% delayed** and **% had an issue** (and the raw counts). The headline comparison is the point,
  e.g. *"62% of scope-changed releases were delayed vs 20% of stable ones."*
- **Drill-down table** (`DataTable`): release name, shipped date, and **Scope changed / Delayed /
  Issue** chips per row; row-click → `/releases/{id}`.
- A short caption noting this is a descriptive correlation over the selected window, not causal.

### Types / service (`types/release.ts`, `services/releaseService.ts`)
- Add `ChurnCohortResponse`, `ChurnReleaseRow`, `ScopeChurnAnalyticsResponse` types.
- Add `releaseService.getScopeChurnAnalytics({ date_from?, date_to? })` →
  `GET /releases/scope-churn-analytics`.

## Testing

**Backend** (`tests/integration/test_scope_churn_analytics_api.py`)
- A shipped project release with creep (past a `scope_deadline`) + a `'Reschedule Reason'` event +
  a `failed` deployment → all three flags true; it lands in the `scope_changed` cohort and counts
  toward `delayed_count` and `issue_count`.
- A shipped project release, no creep / no scope-change event, on-time (`actual_date <=
  target_date`), no failed deploy → all flags false; in the `stable` cohort.
- A release with `actual_date` outside the window is excluded; a non-shipped release
  (`actual_date` null) is excluded; an enterprise release is excluded.
- `scope_changed` via the fallback: a release with a `'Scope Change'` event but no
  `scope_deadline` → `scope_changed` true.
- Percentages: a 2-release scope-changed cohort with 1 delayed → `delayed_pct == 50.0`; empty
  cohort → `0.0`.
- Tenant-scoped: another tenant's shipped release is not counted.

**Frontend** — no unit tests; verify `tsc --noEmit` + `npm run build`.

## Out of scope (YAGNI)
- Time-series / trend charts; per-system or per-release-type breakdowns.
- Statistical significance / confidence.
- Scheduled or exported reports.
- DORA metrics (separate Phase 5).

## Affected files (indicative)
- `backend/app/api/v1/schemas/scope_churn_analytics.py` — response schemas (create).
- `backend/app/services/scope_churn_service.py` — cohort + flag computation + aggregation (create).
- `backend/app/api/v1/releases.py` — `GET /releases/scope-churn-analytics` handler (before `/{release_id}`).
- `backend/tests/integration/test_scope_churn_analytics_api.py` — analytics API tests.
- `frontend/src/pages/releases/ReleaseAnalytics.tsx` — new page (create).
- `frontend/src/App.tsx`, `frontend/src/components/navConfig.tsx` — route + nav entry.
- `frontend/src/types/release.ts`, `frontend/src/services/releaseService.ts` — types + service method.
