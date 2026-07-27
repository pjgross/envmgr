# Release Systems — impacted-systems management

**Date:** 2026-07-27
**Status:** Approved (design) — pending implementation plan
**Depends on:** scope-windows (PR #12) — reuses the `ReleaseListItemResponse.systems[]` field and `system_id` filter it added.

## Problem

The backend already models the systems a release touches (`ReleaseSystem`: `release_id`,
`system_id`, `role`, `deployment_date`) and exposes CRUD endpoints
(`GET/POST /releases/{id}/systems`, `DELETE /release-systems/{id}`). The frontend
`releaseService` even has `listSystems`/`addSystem`/`removeSystem` — but **no UI calls them**.
Consequently a release's impacted-systems list can't be populated from the app, which is why the
Scope Windows system filter had nothing to filter on during testing.

Beyond filtering, the release manager needs the systems split by **kind** so they can plan test
work: which systems are being **changed**, which need **regression** testing (the input to
booking the right test environments), and which are **global/config-only** (e.g. monitoring tools
configured for new endpoints).

## Decisions (locked)

1. **System-level granularity** (no component/subsystem model) — reuse `ReleaseSystem` as-is.
2. **`role` is first-class**, with three values surfaced under clear labels:
   - `changing` → **Changing** (being modified)
   - `regression` → **Regression (needs testing)**
   - `config_only` → **Config only** (global systems, e.g. monitoring, configured for new endpoints)
3. **Two surfaces:** a new **"Systems" tab** on the release detail (manage: list/add/remove with
   role), and a **Systems column + system filter** on the main Releases — List page.
4. **Impacting filter matches any role** — a release that links a system in *any* role shows up
   in the system filter. (A role sub-filter can be added later.)
5. **Test-environment planning is a separate follow-on spec** — this feature only captures the
   systems + roles so that planning feature has data to work with.

## Backend

Minimal — the endpoints exist. One addition: surface the **system name** on the read model.

- **`ReleaseSystemRead`** (`schemas/release_system.py`): add `system_name: Optional[str] = None`.
- **`GET /releases/{id}/systems`** (`api/v1/releases.py`, `list_release_systems`): join `System`
  and hydrate `system_name` on each item:
  ```python
  rows = (await db.execute(
      select(ReleaseSystem, System.name)
      .join(System, System.id == ReleaseSystem.system_id)
      .where(ReleaseSystem.release_id == release_id, ReleaseSystem.tenant_id == tenant_id)
      .order_by(ReleaseSystem.id)
  )).all()
  out = []
  for rs, name in rows:
      item = ReleaseSystemRead.model_validate(rs)
      item.system_name = name
      out.append(item)
  return out
  ```
- **`POST /releases/{id}/systems`** (`add_release_system`): the tenant-validation query already
  selects the system; also fetch its name and set `system_name` on the returned read model (so
  the client gets a complete row without a refetch). Existing behaviour unchanged: 400 if the
  system isn't an active system in the tenant; 409 on duplicate `(release_id, system_id)`.
- **`role` validation:** accept only `changing` / `regression` / `config_only` (add a light
  validator on `ReleaseSystemCreate.role`, mirroring how other enum-ish strings are guarded), so
  the API rejects a typo'd role rather than storing it.

## Frontend

### New "Systems" tab on the release detail
- Add a **"Systems"** tab to `pages/releases/ReleaseDetail.tsx`, placed **after "Environments"**
  (renumber the subsequent `activeTab` conditionals — Linked Requests, Scope, RAID, Enterprise,
  Deployments each shift by one).
- New component `components/releases/ReleaseSystemsTab.tsx` (local-state CRUD, mirroring the
  self-contained pattern of `GatesTable`):
  - Fetches via `releaseService.listSystems(releaseId)` into local state.
  - Table columns: system name, **role** (colored chip — Changing=primary, Regression=warning,
    Config only=default), deployment date (optional), remove action.
  - Grouped or sorted by role so *Changing* / *Regression* / *Config only* read as distinct
    blocks — the view the RM scans when planning what to test.
  - **Add dialog:** system dropdown (`systemService.listSystems`, excluding already-linked
    systems), role select (default **Changing**), optional deployment date → `releaseService.addSystem`.
  - Remove → `releaseService.removeSystem`, with a confirm.
  - Friendly handling of the 409 (system already linked) and 400 (invalid system) errors.

### Main Releases list — Systems column + filter
- In `pages/releases/ReleaseList.tsx`:
  - Add a **Systems** column rendering `row.systems` as name chips (role shown in the chip
    tooltip). Uses the `systems[]` already returned by the list API.
  - Add a **system filter** dropdown (from `systemService.listSystems`); filter client-side —
    keep a release if `row.systems.some(s => s.id === selectedSystemId)` — consistent with the
    page's existing client-side status/type/kind filtering. "All systems" = no filter.

### Types / service (`types/release.ts`, `services/releaseService.ts`)
- Add `system_name: string | null` to `ReleaseSystemResponse`.
- Confirm `ReleaseSystemCreatePayload` carries `{ system_id, role, deployment_date? }` and that
  `role` is typed as `'changing' | 'regression' | 'config_only'`.
- Reuse the existing `releaseService.listSystems/addSystem/removeSystem` (currently unused) — no
  new Redux slice needed; the tab holds local state like other self-contained sub-resource UIs.

### Role labels (shared)
Define one small label/color map for the three roles and reuse it in the Systems tab, the list
column tooltip, and (optionally) the Scope Windows systems chips, so the vocabulary is consistent.

## Testing

**Backend**
- `GET /releases/{id}/systems` returns `system_name` hydrated for each linked system; tenant-scoped
  (a foreign-tenant release's systems are never returned).
- `POST` with a valid system + role creates the link and returns `system_name`; duplicate → 409;
  foreign-tenant / inactive system → 400; invalid `role` string → 422.

**Frontend**
- Systems tab: add a system (with role) → appears in the list; remove → disappears; already-linked
  system is not offered in the add dropdown.
- Releases list: Systems column shows chips; system filter narrows the list to releases impacting
  the chosen system.
- (No frontend unit tests per project convention — verify with `tsc` + `build`.)

## Follow-on (separate spec): test-environment planning
From a release's **Changing + Regression** systems, help the RM find and book test environments
that host those systems (environments already track systems via `EnvironmentSystem`). Scoped
separately once this foundation exists.

## Out of scope (YAGNI)
- Component/subsystem-level linkage.
- Auto-suggesting global/monitoring systems.
- The environment-booking suggestion itself (the follow-on above).
- A role sub-filter on the list (can be added later; filter matches any role for now).

## Affected files (indicative)
- `backend/app/api/v1/schemas/release_system.py` — `system_name` on read; `role` validation on create.
- `backend/app/api/v1/releases.py` — hydrate `system_name` in `list_release_systems` + `add_release_system`.
- `backend/tests/integration/` — release-systems API tests (hydration, tenant scope, role validation, 409).
- `frontend/src/components/releases/ReleaseSystemsTab.tsx` — new tab component (create).
- `frontend/src/pages/releases/ReleaseDetail.tsx` — new "Systems" tab + renumbered conditionals.
- `frontend/src/pages/releases/ReleaseList.tsx` — Systems column + system filter.
- `frontend/src/types/release.ts` — `system_name` on `ReleaseSystemResponse`; role union.
- (`frontend/src/services/releaseService.ts` — already has the needed methods.)
