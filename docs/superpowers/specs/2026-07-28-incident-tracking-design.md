# Incident Tracking (Phase 5, Sub-Project 1)

**Date:** 2026-07-28
**Status:** Design approved, ready for implementation plan
**Programme:** Phase 5 — DORA Metrics, Health Dashboard & PIR
**Base branch:** `main` (tip `d2ecb90`)

## Context

Phase 5 delivers DORA metrics, an environment health dashboard, and post-implementation
reviews. It decomposes into ~5 independent sub-projects; this is **sub-project 1 of 5**:

1. **Incident tracking** ← THIS SPEC
2. DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, MTTR)
3. Environment health-check dashboard
4. Post-Implementation Reviews (PIR)
5. Release / utilization metrics

Incident tracking is foundational: DORA's Change Failure Rate and MTTR (sub-project 2)
and PIR (sub-project 4) both consume incidents. It is self-contained and shippable on
its own.

Incidents are more than manual bug records. Per stakeholder intent, they must:
- be **importable in future from an ITSM tool** (Helix, ServiceNow) driving a company's
  incident-management process — so the model is import-ready now (no connector built yet);
- link to the **causal release** (used by DORA Change Failure Rate) and the **fix
  release** (used by problem management to tell stakeholders when the full fix reaches
  production);
- carry a **configurable lifecycle** showing current state, like other entities;
- support **tenant-configurable custom fields**, like other forms;
- link to the **failed system / subsystem**, so failure statistics can later be analysed
  per release *and* per system.

### Existing infrastructure this reuses (do not reinvent)

- **Lifecycle framework** — `LifecycleTemplate` (`app/db/models/lifecycle.py`): a
  tenant-scoped, `entity_type`-keyed state machine whose states/transitions/field-permissions
  live in a `definition` JSON blob, interpreted by `app/services/lifecycle_service.py`
  (`validate_transition`, `get_allowed_transitions`, `get_field_permissions_for_state`,
  `get_custom_field_permissions`, plus template CRUD/copy). `Release` already uses this via
  a `lifecycle_template_id` FK + a `status` state column. The admin API pattern is
  `app/api/v1/booking_lifecycle.py` (`/lifecycle-templates` CRUD + copy).
- **Custom-field framework** — `CustomFieldDefinition` (`app/db/models/custom_field.py`) +
  `app/services/custom_field_service.py` (`list_definitions`, `get_active_field_keys`,
  `validate_custom_fields`, `list_definitions_for_subtype`) + the generic admin API
  `app/api/v1/tenant_admin_fields.py` (takes `entity_type` as a query param — no allowlist).
  Entities carry a `custom_fields` JSON column. Frontend renders via the existing
  `LifecycleAwareFieldsPanel`.
- **Deployments & builds already exist**: `Deployment` (`build_id`, `environment_id`,
  `release_id?`, `deployed_at`, `status`) and `Build` (`git_sha`, `commit_timestamp`,
  `build_number`, `status`). Sub-project 2 will compute DORA from these + incidents.
- **`ReleaseChange`** (`release_change` table) has `epic_id` — the fix-release panel groups
  its records by epic, reusing the Release Scope-tab grouping pattern.
- **`System`** (`system`) and **`SubSystem`** (`subsystem`) are the failed-thing targets.

Incident tracking plugs into the lifecycle and custom-field frameworks as a new
`entity_type = "incident"` — exactly as `Release` did.

## Goal

A first-class, lifecycle-driven, custom-field-capable, import-ready `Incident` entity with
CRUD + lifecycle transitions, linked to causal/fix releases, failed system/subsystem,
environment, and suspect deployment; with list / form / detail UI and tenant-configurable
lifecycle + custom fields.

## Non-Goals (this sub-project)

- **No ITSM import connector** (Helix/ServiceNow). The model carries `source` +
  `external_ref` so a future connector can upsert; the connector itself is a later effort.
- **No DORA metric calculations** (CFR/MTTR/DF/Lead Time) — sub-project 2 consumes these
  incidents.
- **No PIR** model or panel — sub-project 4. `IncidentDetail` has no PIR panel yet.
- **No failure-analytics dashboards** (per-system / per-release) — sub-projects 2/5. This
  sub-project only *captures* the links those will aggregate.
- **No environment health / alerting** — sub-project 3.

## Design

### 1. Data model — `Incident` (`backend/app/db/models/incident.py`)

All enum-like columns are `String` with `native_enum=False` semantics (VARCHAR — SQLite
test compat), per project convention.

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | FK tenant, indexed | tenant scoping |
| `title` | String(500) | required |
| `description` | Text, nullable | |
| `severity` | String(2) | `P1`\|`P2`\|`P3`\|`P4` |
| `lifecycle_template_id` | FK `lifecycle_template`, nullable | resolved to the tenant's default `incident` template on create if not supplied |
| `status` | String(50) | current lifecycle state (initial state of the template) |
| `detected_at` | DateTime(tz) | when the incident began; defaults to now on manual create, or import-supplied |
| `resolved_at` | DateTime(tz), nullable | auto-set when transitioning into a state flagged resolved; cleared if it leaves that state |
| `environment_id` | FK `environment`, nullable | where it occurred |
| `deployment_id` | FK `deployment`, nullable | suspect deployment |
| `release_id` | FK `release`, nullable | **causal** release (DORA CFR) |
| `fix_release_id` | FK `release`, nullable | **fix** release (problem mgmt) |
| `system_id` | FK `system`, nullable | failed system |
| `subsystem_id` | FK `subsystem`, nullable | failed subsystem/component |
| `source` | String(30) | origin: `manual` (default) \| `helix` \| `servicenow` \| … |
| `external_ref` | String(200), nullable | external ticket id/key (ITSM import de-dup/link) |
| `custom_fields` | JSON, nullable | validated against `incident` `CustomFieldDefinition`s |
| `deleted_at` | DateTime(tz), nullable | soft delete |

Indexes: `(tenant_id, status)`, `(tenant_id, release_id)`, `(tenant_id, system_id)`,
`(tenant_id, source, external_ref)` (import lookups). No unique constraint on
`external_ref` in this sub-project (connector will decide upsert semantics later).

**`IncidentStatusHistory`** (`incident_status_history` table): `tenant_id`,
`incident_id` (FK, `ondelete=CASCADE`), `from_state` (nullable), `to_state`, `changed_by`
(FK user, nullable), `changed_at`. One row per transition (incl. the initial create →
initial state). Supports the detail timeline and future MTTR auditing.

### 2. Lifecycle — configurable, seeded default

Adopt the `LifecycleTemplate` framework with `entity_type = "incident"`. Seed one
**system default** template (`is_system=True`, `is_default=True`) per tenant (via the same
seeding path releases/bookings use — confirm the exact seed hook during planning):

```
New ─▶ Investigating ─▶ Identified ─▶ Fix Scheduled ─▶ Resolved ─▶ Closed
  └─────────────────────┴─▶ Cancelled            (Resolved sets resolved_at)
```

- Initial state: `New`. Terminal states: `Closed`, `Cancelled`.
- The state(s) that set `resolved_at` are marked in the template definition (a
  `resolved: true` flag on the `Resolved` state, read by the service on transition).
  Leaving a resolved state clears `resolved_at`.
- Field permissions + custom-field visibility per state come from the framework
  (`get_field_permissions_for_state`, `get_custom_field_permissions`) — no bespoke logic.

The template is tenant-editable through an incident lifecycle-template admin API mirroring
`booking_lifecycle.py`'s `/lifecycle-templates` CRUD + copy (entity_type `incident`).

### 3. Custom fields

Reuse `CustomFieldDefinition` / `custom_field_service` / `tenant_admin_fields` with
`entity_type = "incident"`. On create/update, `custom_fields` is validated via
`custom_field_service.validate_custom_fields(...)`. No new admin UI needed beyond pointing
the existing tenant-admin custom-fields screen at the `incident` entity type (verify the
frontend admin screen enumerates entity types from a list that must include `incident`).

### 4. API — `backend/app/api/v1/incidents.py` (+ `incident_service.py`)

Thin endpoints delegating to `incident_service`:

- `GET /api/v1/incidents` — list; filters: `status`, `severity`, `system_id`,
  `environment_id`, `release_id`, `source`, `date_from`/`date_to` (on `detected_at`).
  Response rows include `system_name`, `environment_name`, causal `release_name`, and
  `fix_release` summary (`name`, `target_date`, `status`) for the **Fix ETA** column.
- `POST /api/v1/incidents` — create. Resolves default `incident` lifecycle template if
  `lifecycle_template_id` omitted; sets `status` to the template's initial state; writes
  the initial `IncidentStatusHistory` row; validates `custom_fields`; validates every FK
  (`environment_id`/`deployment_id`/`release_id`/`fix_release_id`/`system_id`/`subsystem_id`)
  belongs to the caller's tenant (IDOR-hardening pattern).
- `GET /api/v1/incidents/{id}` — detail, hydrating:
  - causal & fix `release` summaries (`name`, `target_date`, `status`);
  - the **fix release's `ReleaseChange` records grouped by `epic_id`** (same shape as the
    Release Scope tab); `null`/empty when `fix_release_id` unset;
  - `system`/`subsystem`/`environment`/`deployment` display names;
  - `allowed_transitions` for the current state + caller role (via
    `lifecycle_service.get_allowed_transitions`);
  - custom-field definitions + values;
  - `status_history` (chronological).
- `PATCH /api/v1/incidents/{id}` — update fields (incl. `fix_release_id`, `system_id`,
  custom fields). Does **not** change `status` (that is transition-only). Re-validates FKs
  + custom fields.
- `POST /api/v1/incidents/{id}/transition` — body `{ to_state }`. Validates via
  `lifecycle_service.validate_transition`; updates `status`; sets/clears `resolved_at` per
  the target state's `resolved` flag; appends `IncidentStatusHistory`.
- `DELETE /api/v1/incidents/{id}` — soft delete (`deleted_at`).
- Incident lifecycle-template admin endpoints (mirror `booking_lifecycle.py`, entity_type
  `incident`).

Permissions: any authenticated tenant user may CRUD/transition (per stakeholder decision).
All queries filter by `current_user.active_tenant_id`.

### 5. Frontend

- `frontend/src/services/incidentService.ts` — API client.
- `frontend/src/store/incidentSlice.ts` — Redux slice + thunks (list/get/create/update/
  transition/delete).
- `frontend/src/pages/incidents/IncidentList.tsx` — DataGrid: title, severity, status
  (lifecycle chip), system, environment, causal release, **Fix ETA** (fix release
  `target_date`), `detected_at`, `resolved_at`; filter bar mirroring the list endpoint.
- `frontend/src/pages/incidents/IncidentForm.tsx` — create/edit dialog or page: title,
  description, severity, searchable pickers for environment / deployment / causal release /
  fix release / system → subsystem; `source`/`external_ref` shown read-mostly (populated by
  imports later); custom fields via the existing `LifecycleAwareFieldsPanel`.
- `frontend/src/pages/incidents/IncidentDetail.tsx` — header with lifecycle **status chip**
  + **transition buttons** (from `allowed_transitions`); **Fix-Release panel** (summary +
  `ReleaseChange`-by-epic); causal-release link; system/subsystem link; custom-fields panel;
  **status-history timeline**. **No PIR panel** (sub-project 4).
- Nav: an "Incidents" entry (under Insights or Release Management — confirm during planning).
- Admin: point the existing tenant-admin lifecycle-template + custom-field screens at
  `entity_type = "incident"` (add `incident` to their entity-type lists if enumerated).

### 6. Migration

One Alembic migration (manual DDL, per project convention): `op.create_table("incident", …)`
and `op.create_table("incident_status_history", …)` with the FKs/indexes above. Plus the
default-template seed (via the app's tenant seed path, not the migration, matching how
release/booking defaults are seeded — confirm in planning).

## Files

**Backend — create:**
- `app/db/models/incident.py` — `Incident`, `IncidentStatusHistory`
- `app/schemas/incident.py` — create/update/response/transition/list-row schemas
- `app/services/incident_service.py` — business logic
- `app/api/v1/incidents.py` — endpoints (CRUD + transition + incident lifecycle-templates)
- `alembic/versions/<rev>_incident_tables.py`

**Backend — modify:**
- `app/db/models/__init__.py` — register the new models
- `app/main.py` (or the router aggregator) — mount the incidents router
- lifecycle default-seed hook — add the `incident` default template
- (verify) any `entity_type` allowlist in custom-field/lifecycle admin includes `incident`

**Frontend — create:**
- `services/incidentService.ts`, `store/incidentSlice.ts`
- `pages/incidents/IncidentList.tsx`, `IncidentForm.tsx`, `IncidentDetail.tsx`
- `utils/incidentSeverity.ts` (label/color map) — small shared helper

**Frontend — modify:**
- store root reducer (register the slice), router (routes), nav menu (Incidents entry),
  and the tenant-admin entity-type lists (add `incident`).

## Testing

**Backend:**
- `incident_service` unit tests: create (default template resolution, initial state +
  history row), custom-field validation, PATCH, soft delete.
- Transition tests: valid transition updates `status` + appends history; invalid transition
  rejected (via `validate_transition`); entering `Resolved` sets `resolved_at`; leaving it
  clears it.
- **Tenant isolation**: creating/patching an incident that references another tenant's
  environment / deployment / release / fix_release / system / subsystem is rejected
  (IDOR-hardening — one test per FK).
- API integration tests: full CRUD + transition + detail hydration (fix-release
  ReleaseChange-by-epic grouping; `allowed_transitions`).

**Frontend:**
- `incidentSlice` thunk/reducer tests; a light `IncidentList` render/filter test.

`tsc --noEmit` clean; full backend suite (`tests/services/` + `tests/integration/`) green;
`vitest run` green.

## Risks

- **Default-template seeding path.** Releases/bookings seed their default templates somewhere
  specific; the incident default must hook the same path (not the migration). Planning must
  pin this down, else new tenants have no incident template and creates fail. Mitigation: on
  create, fall back to lazily creating the system-default template if none exists.
- **Custom-field / lifecycle admin entity-type allowlists.** If the frontend admin screens
  enumerate entity types from a hard-coded list, `incident` must be added or the config UI
  won't offer it. Backend `tenant_admin_fields` takes `entity_type` freely, so the API side
  is fine.
- **Scope creep toward analytics.** The failure-stats value (per system/release) is
  deliberately *not* built here — only the links. Keep the analytics in sub-projects 2/5.
