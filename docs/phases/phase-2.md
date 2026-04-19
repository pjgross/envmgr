# Phase 2: Change Management

> Status: ✅ **Merged to `main` via MR !2 on 2026-04-19** (merge commit `3bb3833`) | Roadmap: [../plan.md](../plan.md)
> Feature branch: `feature/phase-2-change-management` (head `bea9aae`, preserved)
> Implementation: 2026-04-18 → 2026-04-19 (Phase 2.5 pull-forward added before merge)
> Scope revised 2026-04-18 in light of Phase 1 extensions — see [phase-1.md §Post-Completion Extensions](phase-1.md).

---

## What's already delivered (pre-Phase-2 infra)

The booking-lifecycle extension work after the 2026-03-23 Phase 1 cutoff built most of the generic infrastructure this phase originally assumed as new:

| Infrastructure | Where | Reuse |
|---|---|---|
| Configurable lifecycle (`states`, `transitions`, `field_permissions` in JSONB) | `backend/app/db/models/booking_lifecycle.py` (`BookingLifecycleTemplate`) | Renamed to `lifecycle_template` + `entity_type` in Step 1 |
| `validate_transition` / `get_allowed_transitions` / `get_custom_field_permissions` | `backend/app/services/booking_lifecycle_service.py` | Renamed to `lifecycle_service.py`; signatures unchanged |
| Per-state standard-field + custom-field permissions | Template JSONB | Entity-aware validator added in `ENTITY_FIELD_SPECS` |
| Generic `CustomFieldDefinition.entity_type` | `backend/app/db/models/custom_field.py` | `"change_request"` added as valid value |
| Outbox event publishing via `publish_event()` | `backend/app/core/events.py` | Reused as-is with new event-type strings |
| Admin config UI routing (`/admin/config/:entityType`) | `frontend/src/pages/admin/EntityConfig.tsx` | Extended to `/admin/config/change-request` |
| `CustomFieldsSection` / `CustomFieldsDisplay` / `TransitionButtons` | `frontend/src/components/` | Reused verbatim in CR pages |
| Form primitives (`FormDialog` / `FormTextField` / `FormSelect`) + `useSnackbar` + `formatApiError` | Tier 1 modernisation | Reused in CR form + edit dialog |

---

## What Was Built

### Commit trail on `feature/phase-2-change-management`

| # | Commit | Summary |
|---|---|---|
| doc | `ae036b3` | Revised plan (phase-2.md); gitignore `.vite/` |
| 1 | `a2b262d` | Generalise lifecycle infra — `lifecycle_template` + `entity_type` + migration |
| 2 | `edeb2a5` | `ChangeRequest` + `ChangeHistory` models + migration |
| 3 | `7734f77` | `ChangeRequestService` + `/change-requests` router + default-lifecycle seeding + seed migration |
| 4 | `3498cd4` | Unified `/environments/{id}/schedule` endpoint |
| 5 | `a5dc55f` | Outage × booking conflict preview endpoint |
| 6 | `3528dbb` | Admin `LifecycleTemplatesPanel` generalised; Change Requests admin config |
| 7 | `dec6cb6` | CR frontend types + service + Redux slice |
| 8 | `f18a9e0` | CR List / Form / Detail pages + routing + nav |
| 9 | `bfe34c1` | `EnvironmentSchedule` component + new Schedule tab |
| fix | `0bcaf57` | Outage preview wired into form + custom fields UI + CR edit dialog |
| fix | `f8c65fa` | Lifecycle field validator made entity-aware (422 on CR lifecycle edit) |

### Backend additions

- **Generic lifecycle infrastructure**
  - Table `lifecycle_template` with `entity_type` column + `(tenant_id, entity_type)` index (renamed from `booking_lifecycle_template`)
  - `backend/app/services/lifecycle_service.py` — generic `validate_transition`, `get_allowed_transitions`, `get_custom_field_permissions`, CRUD for templates
  - `ENTITY_FIELD_SPECS` in `backend/app/api/v1/schemas/booking_lifecycle.py` declaring per-entity valid + mandatory standard-field names. `validate_definition_for_entity()` helper called from the service on create/update
- **ChangeRequest + ChangeHistory**
  - `backend/app/db/models/change_request.py` — `ChangeRequest` with FKs to `lifecycle_template`, `subsystem`, `environment`; `release_id` as nullable placeholder; `has_outage` + outage window fields; `custom_fields` JSON. `ChangeHistory` supports both state transitions and general field-level audit rows in one table.
  - `ChangeType` enum: `configuration` / `infrastructure` / `code_deployment`
- **Service + router**
  - `ChangeRequestService` — create / update / get / list (with filters) / transition / soft delete / get allowed transitions / `get_environment_schedule` / `preview_outage_conflicts`
  - Events emitted: `ChangeRequestCreated`, `ChangeRequestStateTransitioned`, `ChangeRequestCompleted` (on terminal-state transition)
  - Router `/api/v1/change-requests` — 8 endpoints (list, create, preview-outage-conflicts, detail, patch, transition, allowed-transitions, delete)
  - `tenant_service.create_tenant` now seeds CR default lifecycles (`Simple Approval` + `Emergency`) on tenant creation; migration `p2s3seedcr` backfills for existing tenants
- **Unified environment schedule**
  - `GET /api/v1/environments/{env_id}/schedule?start_date&end_date` returns `{bookings, change_requests, deployments: []}`. `deployments` is a forward-compatible placeholder Phase 4 will populate.

### Frontend additions

- **Admin**
  - `LifecycleTemplatesPanel` now takes `entityType` prop; `STANDARD_FIELDS_BY_ENTITY` map provides the correct standard-field list per entity
  - `/admin/config/change-request` route; "Change Requests" nav entry in `AdminLayout`
  - `bookingLifecycleSlice` reshaped to `templatesByEntity` keyed by entity; `selectBookingTemplates` + `selectTemplatesForEntity` selectors
- **CR feature pages**
  - `pages/change-requests/ChangeRequestList.tsx` — DataTable with status + environment filters, status chips, outage badge, row click → detail
  - `pages/change-requests/ChangeRequestForm.tsx` — `FormDialog` + zod; environment-scoped subsystem picker; debounced outage × booking conflict preview; `CustomFieldsSection` wired via `Controller`
  - `pages/change-requests/ChangeRequestDetail.tsx` — status header, summary card, description, custom-fields display, dynamic transition buttons (reusing `TransitionButtons`), history timeline, edit + delete buttons
  - `pages/change-requests/ChangeRequestEditDialog.tsx` — edits only the server-editable subset (lifecycle / environment / subsystem are immutable)
- **Unified schedule UI**
  - `pages/environments/EnvironmentSchedule.tsx` — FullCalendar with bookings (blue), CRs (orange), CRs with outage (red). `datesSet` drives the backend query so panning auto-refetches. Event click routes to underlying detail page
  - New "Schedule" tab on `EnvironmentDetail`
- **Plumbing**
  - `frontend/src/services/changeRequestService.ts`
  - `frontend/src/services/scheduleService.ts`
  - `frontend/src/store/changeRequestSlice.ts` (registered in `store/index.ts`)
  - `frontend/src/types/changeRequest.ts` — types + `CHANGE_TYPE_LABELS`
  - `'change_request'` added to `EntityType` union in `types/customField.ts`
  - `Change Requests` nav entry on main `AppLayout`

### Tests added

- `backend/tests/integration/test_change_requests.py` — 16 tests (CRUD, validation, transitions, role gating, soft delete, tenant isolation, outage conflict preview)
- `backend/tests/integration/test_environment_schedule.py` — 5 tests (empty-window shape, booking + CR, date filter, 404, tenant isolation)
- `backend/tests/test_booking_standard_field_permissions.py` — 3 new CR-specific tests for the entity-aware validator
- Full backend suite: **256 passed**

---

## Objectives

- Change request (TECR) CRUD on sub-resources (not the environment as a whole) ✅
- Generalise the existing booking lifecycle infrastructure so the same tables/services serve change requests and (later) releases ✅
- Outage flag on changes (is there an environment outage during the change?) ✅
- Change requests and bookings visible together on a unified environment schedule ✅
- Changes are used to link builds to test environments documenting a deployment ⏳ (Phase 4 — CR side ready; `Deployment.change_request_id` FK lands then)
- Change history and audit trail ✅
- Notifications on change status updates ⚠️ (events emitted via `publish_event()` → NATS; no consumer exists for bookings either — cross-cutting concern deferred beyond Phase 2)

---

## Backend Tasks

### Step 1 — Generalise existing lifecycle infrastructure ✅

- [x] Rename table `booking_lifecycle_template` → `lifecycle_template`; rename class `BookingLifecycleTemplate` → `LifecycleTemplate`. Add column `entity_type VARCHAR NOT NULL` with index on `(tenant_id, entity_type)`. Alembic migration backfills all existing rows to `entity_type='booking'`. _(commit `a2b262d`, migration `p2s1lifecycle`, includes split-brain guard for dev envs)_
- [x] Rename `backend/app/services/booking_lifecycle_service.py` → `lifecycle_service.py`. Keep function signatures (`validate_transition`, `get_allowed_transitions`, `get_custom_field_permissions`) — they already take a plain `definition` dict.
- [x] Rename `/api/v1/booking-lifecycle-templates` → `/api/v1/lifecycle-templates`; add `entity_type` query-param filter. Single-PR cutover — no back-compat alias needed (pre-production). _(Route path was already `/lifecycle-templates` at the module level; filter added.)_
- [x] Adjust booking code paths (service + router + frontend slice) to pass `entity_type='booking'` when creating / querying templates.

### Step 2 — `ChangeRequest` + `ChangeHistory` models ✅

- [x] `ChangeRequest` model (`backend/app/db/models/change_request.py`). _(commit `edeb2a5`)_
- [x] `ChangeHistory` model — supports both state-transition rows and general field-level audit rows in the same table via nullable `from_state`/`to_state` + `field_name`/`old_value`/`new_value` columns.
- [x] Alembic migration for both tables (`p2s2change`).
- [x] `"change_request"` added as a valid value in `CustomFieldDefinition.entity_type` (validated via the EntityType frontend union; backend already accepted any string).

### Step 3 — `ChangeRequestService` + router + events ✅

- [x] `ChangeRequestService` (`backend/app/services/change_request_service.py`) with all planned methods plus `preview_outage_conflicts` and `get_environment_schedule`. _(commit `7734f77`)_
- [x] Seed default CR lifecycles on tenant creation (`Simple Approval` + `Emergency`) — runtime seed on `create_tenant`; migration `p2s3seedcr` for existing tenants.
- [x] Events emitted via `publish_event()`: `ChangeRequestCreated`, `ChangeRequestStateTransitioned`, `ChangeRequestCompleted`.
- [x] Router `backend/app/api/v1/change_requests.py` with the planned endpoints plus `GET /{id}/allowed-transitions`.
- [⚠️] Notification consumer for `ChangeRequest*` events — **deferred**. Events are on NATS; neither Phase 2 nor Phase 1 built a consumer that turns them into user-visible notifications. Cross-cutting concern for a later phase.

### Step 4 — Unified environment schedule ✅

- [x] `ChangeRequestService.get_environment_schedule(env_id, tenant_id, start_date, end_date)`. _(commit `3498cd4`)_
- [x] `GET /api/v1/environments/{id}/schedule` — returns `{bookings, change_requests, deployments: []}`.

### Step 5 — CR × booking conflict advisory ✅

- [x] `POST /api/v1/change-requests/preview-outage-conflicts` endpoint _(backend: commit `a5dc55f`)_ — returns any bookings in the same env whose window overlaps the proposed outage. Not a hard rejection.
- [x] Wired into the CR form with 400ms debounce; results render as a non-blocking warning Alert listing affected bookings. _(frontend: commit `0bcaf57`)_

---

## Frontend Tasks

### Step 6 — Admin panel generalisation ✅

- [x] `LifecycleTemplatesPanel` accepts `entityType` prop; booking-only guard removed. `STANDARD_FIELDS_BY_ENTITY` map carries per-entity standard-field lists (booking vs change_request). _(commit `3528dbb`)_
- [x] Cloned/extended: `BookingTypesPanel` stays booking-specific (kept as-is — CRs don't need an equivalent types table). `EntityConfig` conditionally renders booking types for booking only.
- [x] `/admin/config/change-request` route via `EntityConfig`; nav entry added to `AdminLayout`.
- [x] `'change_request'` added to the `EntityType` union.

### Step 7 — CR service, slice, types ✅

- [x] `frontend/src/services/changeRequestService.ts` _(commit `dec6cb6`)_
- [x] `frontend/src/services/scheduleService.ts` _(commit `bfe34c1`)_
- [x] `frontend/src/store/changeRequestSlice.ts` (registered in `store/index.ts`)
- [x] `frontend/src/types/changeRequest.ts`
- [x] Lifecycle types — reused `AllowedTransition` from `bookingLifecycle.ts`; no separate `changeRequestLifecycle.ts` needed since the underlying types are already generic.

### Step 8 — CR pages ✅

- [x] `ChangeRequestList` with status + env filters. _(commit `f18a9e0`)_
- [x] `ChangeRequestForm` built on `FormDialog` + zod. Subsystem picker scoped to the chosen environment. Custom fields + debounced outage preview wired in commit `0bcaf57`.
- [x] `ChangeRequestDetail` reusing `TransitionButtons`, history timeline, `CustomFieldsDisplay`, plus `ChangeRequestEditDialog` (`0bcaf57`).
- [x] "Change Requests" nav entry on `AppLayout`.

### Step 9 — `EnvironmentSchedule` component ✅

- [x] `pages/environments/EnvironmentSchedule.tsx` — FullCalendar with two event sources (bookings blue, CRs orange, outage CRs red). Event click routes to underlying detail page. _(commit `bfe34c1`)_
- [x] Integrated as a new "Schedule" tab on `EnvironmentDetail`.

---

## Acceptance Criteria

- [x] Change requests can only be raised on sub-resources (subsystem), not on environments directly. _(service enforces via FK + validate_subsystem)_
- [x] Status transitions are validated against the lifecycle definition — invalid transitions return 400. _(covered by `test_transition_rejected_for_wrong_role`)_
- [x] Outage flag correctly records outage start/end; outage periods are visually distinct in the environment schedule. _(`CR_OUTAGE_COLOR` = red; title prefixed with ⚠︎)_
- [x] CR × booking outage overlap surfaces a non-blocking warning in the CR form.
- [x] `/api/v1/environments/{id}/schedule` returns bookings and change requests in a single sorted timeline; `deployments` field present as an empty array.
- [⚠️] Notifications sent on create, transition, and completion events — events emitted (tested); no consumer. See Objectives note.
- [x] All service methods have unit tests; all API endpoints have integration tests; fixtures mirror `test_booking_lifecycle.py` / `test_bookings.py`.
- [x] Tenant isolation verified: all new table queries filter by `tenant_id`; data from one tenant is never returned to another. _(covered by `test_tenant_isolation` × 2)_
- [x] Existing booking functionality unaffected by the lifecycle-table rename — full booking test suite still green (250 → 256 tests; all prior-green tests still green).

---

## Known Follow-ups / Tech Debt

- **Notifications consumer** — events emit but no listener turns them into user-visible output. Needed for both bookings and change requests; cross-cutting, deserves its own design.
- **No frontend unit tests for CR pages** — matches Phase 1 baseline. Vitest infra exists (Tier 1 modernisation) but no tests yet. Deferred per `docs/frontend-modernisation-plan.md` Tier 3.
- **`release_id` on `ChangeRequest`** — currently nullable `Integer` column without FK; Phase 3 adds `Release` table and the FK constraint.
- **`deployments: []` in schedule response** — Phase 4 populates.

---

## Phase 2.5 — Hosts and multi-target change requests (Phase 6 pull-forward)

Shipped on `feature/phase-2-change-management` after the main Phase 2 body.

### Why
Change requests could only be raised against a single subsystem in a single environment, so platform-level changes (reboot macmini, AWS ECS upgrade) had no natural home and stakeholders in other environments were blind to them.

### What changed
- **New `InfrastructureComponent` model** (`backend/app/db/models/infrastructure_component.py`) — Phase 6-shaped with `component_type`, `provider`, `region`, `location`, `source`, `external_id`, `tags`, so later Terraform / Docker Compose parsers slot in without schema churn.
- **New junction `environment_subsystem_host`** — M:M between a deployed subsystem and the hosts it runs on (replicas, multi-AZ).
- **New junctions `change_request_environment` + `change_request_host`** — a CR targets any combination of environments and hosts; the legacy `change_request.environment_id` FK is dropped (backfilled into the junction) and `subsystem_id` is now nullable.
- **Affected-env derivation**: host-scoped CRs resolve to the union of every environment whose subsystems live on that host, exposed as `derived_environment_ids` on every CR payload and surfaced in the outage-preview response.
- **Outage preview extended**: `/change-requests/preview-outage-conflicts` now takes `environment_ids + host_ids`, resolves the effective env set, and returns conflicts grouped per env.
- **Environment schedule** pulls in any CR whose env junction matches *or* whose hosts are attached to subsystems in that env.
- **Frontend**: new Hosts list page (`/infrastructure/hosts`), hosts multi-select on the CR form, a hosts sub-dialog on the environment subsystem row (primary/replica roles), and multi-env/multi-host chip columns on the CR list and detail pages.

### Explicitly deferred to Phase 6 proper
- Terraform `.tf` / `.tfstate` parser writing into `infrastructure_component` (source=`terraform`)
- Docker Compose parser
- GitHub repo scanner / App integration
- Neo4j topology sync of `infrastructure_component` + `environment_subsystem_host` + `change_request_host`
- React Flow topology page and environment-comparison diff
- Drift detection

### Migrations
- `p3s1infra` — adds `infrastructure_component` and `environment_subsystem_host`.
- `p3s2crmt` — adds CR env/host junctions, backfills from `change_request.environment_id`, drops that column, relaxes `subsystem_id` to nullable.

### Test coverage
10 new integration tests in `tests/integration/test_infrastructure_components.py` (host CRUD, idempotent junction PUT, CR multi-target validation, derived-env outage preview, host CR schedule pickup, env/host diff history). Existing Phase 2 tests updated for the new payload shape. Full suite: 266 passed.
