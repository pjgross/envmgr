# Scope Windows — per-system scope-cutoff discoverability

**Date:** 2026-07-26
**Status:** Approved (design) — pending implementation plan
**Builds on:** `scope_deadline` + scope-creep feature (merged PR #11, migration `scopedeadline`)

## Problem

A release manager or project manager holding a change for a given **system** needs to answer:
*"Which upcoming releases for this system can I still get scope into, and by when?"*

Today the scope cutoff (`release.scope_deadline`) is visible only on an individual release's
detail page. There is no way to look across a system's releases and see, at a glance, which
scope windows are still **open**, which are **closing soon**, and which have **closed**.

This is **pillar A** (discoverability). Pillar B (scope-churn vs delay/issue analytics) is a
separate follow-on spec — see "Next: pillar B" below.

## Decisions (locked)

1. **Two surfaces, one backend:** a global **Scope Windows** page (primary lens = a system
   filter) AND a **Scope Windows tab** on the System detail page. Both consume the same
   extended releases-list endpoint.
2. **Window status is computed, no new columns.** Derived purely from `scope_deadline`,
   `actual_date`, and now.
3. **`closing_soon` threshold = 7 days** (module constant).
4. **Global page defaults to `release_kind == "project"`** (scope cutoffs are a project-release
   concept; enterprise rollups have no deadline), filter changeable.

## Window-status computation

A pure function `compute_scope_window(scope_deadline, actual_date, now) -> (status, days_to_cutoff)`:

| Condition (checked in order) | `window_status` | `days_to_cutoff` |
|---|---|---|
| `actual_date` is set (release shipped) | `shipped` | `None` |
| `scope_deadline` is `None` | `no_cutoff` | `None` |
| `now >= scope_deadline` | `closed` | `(scope_deadline - now).days` (≤ 0, negative) |
| `scope_deadline - now <= 7 days` | `closing_soon` | `(scope_deadline - now).days` (0–7) |
| otherwise | `open` | `(scope_deadline - now).days` (> 7) |

- `days_to_cutoff` is a signed integer day count (negative once the cutoff has passed), `None`
  when there is no meaningful cutoff (`shipped` / `no_cutoff`).
- Using `actual_date` (stamped at terminal deploy) rather than lifecycle **status** names keeps
  this independent of tenant-configurable state keys.
- Lives in a small helper module (`app/services/scope_window.py`) so it is unit-testable in
  isolation and reusable by both the list endpoint and any future analytics.

## Backend

Extend the existing releases list rather than adding a parallel subsystem.

### `list_releases` service (`release_service.py`)
- New optional param **`system_id: int | None`**. When set, restrict to releases linked to that
  system via a tenant-scoped subquery:
  `Release.id.in_(select(ReleaseSystem.release_id).where(system_id==…, tenant_id==…))`.
  (Subquery, not a join, to avoid duplicate release rows when a release links a system in
  multiple roles.)

### `GET /releases` endpoint (`api/v1/releases.py`, `list_releases` handler)
- Accept `system_id` query param and pass it through.
- After building the existing KPI dicts, additionally:
  - **Systems per release:** one grouped query over `ReleaseSystem` join `System` for the page's
    `release_ids`, producing `{release_id: [{id, name, role}, …]}` (tenant-scoped, non-deleted).
  - **Window fields:** for each release call `compute_scope_window(r.scope_deadline, r.actual_date, now)`.
- Populate the new response fields (below) on each `ReleaseListItemRead`.

### Schema (`schemas/release.py`)
Add to `ReleaseListItemRead` (all with safe defaults so other list callers are unaffected):
```python
    window_status: str = "no_cutoff"
    days_to_cutoff: Optional[int] = None
    systems: list["ReleaseSystemBrief"] = []
```
with a small `ReleaseSystemBrief { id: int, name: str, role: str }` model.

## Frontend

### Global Scope Windows page
- New page `pages/releases/ScopeWindows.tsx`, route **`/releases/scope-windows`** (App.tsx),
  nav entry **"Releases — Scope Windows"** in the existing *Release Management* group
  (`navConfig.tsx`), placed after Timeline.
- **Filters:** a **system** dropdown (primary lens; sourced from the existing systems
  list/service), plus a window-state toggle. Sends `system_id` + `release_kind` + reuses the
  release list thunk/service.
- **DataGrid columns:** release name (row-click / link → release detail Scope tab), system(s)
  (chips), type, status, target date, **scope deadline**, **window status** (colored chip —
  `open`=success, `closing_soon`=warning, `closed`=default, `shipped`=info, `no_cutoff`=default),
  **days to cutoff**, scope count, creep count.
- **Defaults:** `release_kind=project`; client-side default filter to actionable windows
  (`open` + `closing_soon`); sort by `days_to_cutoff` ascending (soonest cutoff first, `None`
  sorts last); a "Show closed / shipped / no-cutoff" toggle reveals the rest.

### System detail "Scope Windows" tab
- Add a 6th tab to `pages/systems/SystemDetail.tsx` (after "Topology"): **"Scope Windows"**.
- Renders a shared component (`components/releases/ScopeWindowsTable.tsx`) that the global page
  also uses, called here with a fixed `system_id` (the current system) and no system dropdown.
- Same columns/chips/sort; same default (actionable windows first, toggle for the rest).

### Types / store (`types/release.ts`, `store/releaseSlice.ts`, `services/releaseService.ts`)
- Add `window_status`, `days_to_cutoff`, `systems` to `ReleaseListItemResponse`.
- Add optional `system_id` to the release-list filter/params.
- Reuse the existing `fetchReleases` thunk (extend its arg to carry `system_id`), or add a
  dedicated `fetchScopeWindows` thunk if the default params differ enough — implementer's call,
  favouring reuse.

## Testing

**Backend**
- `compute_scope_window` unit tests: shipped (actual_date set) → `shipped`/None; no deadline →
  `no_cutoff`/None; deadline in past → `closed` with negative days; deadline in 3 days →
  `closing_soon` with days=3; deadline in 30 days → `open` with days=30; boundary at exactly 7 days.
- `GET /releases?system_id=` returns only releases linked to that system, tenant-scoped (a
  second tenant's release with the same system id is excluded); `systems` list hydrated with names.
- Enterprise release (no `scope_deadline`) → `window_status=no_cutoff`.
- A release with `actual_date` set but a past `scope_deadline` → `shipped` (actual_date wins).

**Frontend**
- Scope Windows page renders rows; window-state toggle filters; chip colors map correctly;
  row link targets the release Scope tab.
- System detail Scope Windows tab loads that system's releases only (fixed `system_id`).

## Next: pillar B (separate spec — scope-churn analytics)

Captured definitions from this brainstorm, to design next:
- **Scope change** = items entering a release after its `scope_deadline` (creep), counting adds
  **and** removes; for releases with no `scope_deadline`, fall back to the existing post-approval
  "Scope Change" baseline.
- **Delay** = both the count of "Reschedule Reason" events (target_date moved after leaving
  draft) **and** actual_date later than the earliest recorded target_date.
- **Release issue** = rolled-back/failed **deployments** and **missed go-live** (delivered after
  target date).
- Deliverable: aggregate correlation stats ("N releases had changing scope; of those, X% were
  delayed / had issues vs the no-change cohort"), with drill-down.

## Out of scope (YAGNI)
- The analytics/correlation dashboard (pillar B, above).
- Editing scope or scope_deadline from the windows view (row links to the release to act).
- Per-system grouped/rollup views beyond the system filter + System-detail tab.
- Notifications/reminders as a cutoff approaches.

## Affected files (indicative)
- `backend/app/services/scope_window.py` — new pure helper (create).
- `backend/app/services/release_service.py` — `system_id` filter in `list_releases`.
- `backend/app/api/v1/releases.py` — `system_id` param, systems + window fields in list handler.
- `backend/app/api/v1/schemas/release.py` — `window_status`, `days_to_cutoff`, `systems`,
  `ReleaseSystemBrief`.
- `frontend/src/pages/releases/ScopeWindows.tsx` — new global page (create).
- `frontend/src/components/releases/ScopeWindowsTable.tsx` — shared table (create).
- `frontend/src/pages/systems/SystemDetail.tsx` — new Scope Windows tab.
- `frontend/src/components/navConfig.tsx`, `frontend/src/App.tsx` — nav entry + route.
- `frontend/src/types/release.ts`, `store/releaseSlice.ts`, `services/releaseService.ts` — fields
  + `system_id` param.
