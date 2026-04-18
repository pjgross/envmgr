# Phase 2: Change Management

> Status: ⏳ **Planned** | Roadmap: [../plan.md](../plan.md)
> Duration: 2–3 weeks | Starts after `main` merge of Phase 1 extensions (landed 2026-04-18)
> Scope revised 2026-04-18 in light of Phase 1 extensions — see [phase-1.md §Post-Completion Extensions](phase-1.md).

---

## What's already delivered

The booking-lifecycle extension work after the 2026-03-23 Phase 1 cutoff built most of the generic infrastructure this phase originally assumed as new:

| Infrastructure | Where | Status |
|---|---|---|
| Configurable lifecycle (`states`, `transitions`, `field_permissions` in JSONB) | `backend/app/db/models/booking_lifecycle.py` (`BookingLifecycleTemplate`) | Built — needs rename + `entity_type` column |
| `validate_transition` / `get_allowed_transitions` / `get_custom_field_permissions` | `backend/app/services/booking_lifecycle_service.py` | Already generic signatures |
| Per-state standard-field + custom-field permissions | Template JSONB | Already entity-agnostic |
| Generic `CustomFieldDefinition.entity_type` | `backend/app/db/models/custom_field.py` | Reuse — add `"change_request"` as a value |
| Outbox event publishing via `publish_event()` | `backend/app/core/events.py` | Reuse as-is with new event-type strings |
| Admin config UI routing (`/admin/config/:entityType`) | `frontend/src/pages/admin/EntityConfig.tsx` | Reuse — add CR route |
| `CustomFieldsSection` / `CustomFieldsDisplay` / `TransitionButtons` frontend primitives | `frontend/src/components/` | Entity-agnostic — reuse verbatim |
| Form primitives (`FormDialog` / `FormTextField` / `FormSelect` + zod + react-hook-form) and `useSnackbar` / `formatApiError` | Tier 1 modernisation | Reuse for CR forms/dialogs |

---

## Objectives

- Change request (TECR) CRUD on sub-resources (not the environment as a whole)
- Generalise the existing booking lifecycle infrastructure so the same tables/services serve change requests and (later) releases
- Outage flag on changes (is there an environment outage during the change?)
- Change requests and bookings visible together on a unified environment schedule
- Changes are used to link builds to test environments documenting a deployment (the link lives on `Deployment.change_request_id` in Phase 4; Phase 2 only prepares the CR side)
- Change history and audit trail
- Notifications on change status updates

---

## Backend Tasks

### Step 1 — Generalise existing lifecycle infrastructure

- [ ] Rename table `booking_lifecycle_template` → `lifecycle_template`; rename class `BookingLifecycleTemplate` → `LifecycleTemplate`. Add column `entity_type VARCHAR NOT NULL` with index on `(tenant_id, entity_type)`. Alembic migration backfills all existing rows to `entity_type='booking'`.
- [ ] Rename `backend/app/services/booking_lifecycle_service.py` → `lifecycle_service.py`. Keep function signatures (`validate_transition`, `get_allowed_transitions`, `get_custom_field_permissions`) — they already take a plain `definition` dict.
- [ ] Rename `/api/v1/booking-lifecycle-templates` → `/api/v1/lifecycle-templates`; add `entity_type` query-param filter. Single-PR cutover — no back-compat alias needed (pre-production).
- [ ] Adjust booking code paths (service + router + frontend slice) to pass `entity_type='booking'` when creating / querying templates.

### Step 2 — `ChangeRequest` + `ChangeHistory` models

- [ ] `ChangeRequest` model (`backend/app/db/models/change_request.py`)
  - Fields: `title`, `description`, `change_type` (enum: `configuration | infrastructure | code_deployment`), `status`, `lifecycle_id` (FK → `lifecycle_template`), `subsystem_id` (FK → `SubSystem` — CRs are raised on sub-resources), `environment_id` (FK → `Environment` — for schedule display), `release_id` (nullable — column only until Phase 3 creates the `Release` table), `has_outage` (bool), `outage_start` (nullable datetime), `outage_end` (nullable datetime), `scheduled_start`, `scheduled_end`, `custom_fields` (JSON), `tenant_id`, `deleted_at`.
  - Note: `deployment_id` is **not** on ChangeRequest — the FK is on `Deployment.change_request_id` (Phase 4). Deployments link to changes, not the reverse.
- [ ] `ChangeHistory` model — field-level audit trail, mirror `BookingStatusHistory` shape (`booking_lifecycle.py:45`).
- [ ] Alembic migrations for both tables.
- [ ] Add `"change_request"` as a valid value in `CustomFieldDefinition.entity_type` (no schema change — it's already a free-form VARCHAR).

### Step 3 — `ChangeRequestService` + router + events

- [ ] `ChangeRequestService` (`backend/app/services/change_request_service.py`)
  - `create_change_request(tenant_id, data)` — validates subsystem scoping, writes event
  - `update_change_request(tenant_id, cr_id, data)`
  - `transition_status(tenant_id, cr_id, new_status)` — delegates to `lifecycle_service.validate_transition()`
  - `approve_change_request(tenant_id, cr_id)` / `reject_change_request(tenant_id, cr_id, reason)` (thin wrappers over `transition_status`)
  - `list_change_requests(tenant_id, filters)` — by environment, subsystem, status, date range
- [ ] Seed default CR lifecycles on tenant creation: `simple-approval` (draft → submitted → approved / rejected → completed) and `emergency` (draft → in-progress → completed, no approval).
- [ ] Events (via existing `publish_event()`): `ChangeRequestCreated`, `ChangeRequestStateTransitioned`, `ChangeRequestCompleted`.
- [ ] `backend/app/api/v1/change_requests.py`
  - `GET /api/v1/change-requests` — list with filters
  - `POST /api/v1/change-requests` — create
  - `GET /api/v1/change-requests/{id}` — detail with history
  - `PATCH /api/v1/change-requests/{id}` — update
  - `POST /api/v1/change-requests/{id}/transition` — generic transition
  - `DELETE /api/v1/change-requests/{id}` — soft delete / cancel
- [ ] Notification consumer for `ChangeRequest*` events (mirror booking pattern).

### Step 4 — Unified environment schedule

- [ ] `ChangeRequestService.get_environment_schedule(tenant_id, env_id, start_date, end_date)` — aggregates bookings + CRs.
- [ ] `GET /api/v1/environments/{id}/schedule` — response shape `{bookings: [...], change_requests: [...], deployments: []}`. The `deployments` field is a forward-compatible empty array (Phase 4 populates it).

### Step 5 — CR × booking conflict advisory (design decision)

- [ ] When an outage window overlaps a booking in the same environment, surface a non-blocking **warning** in the CR form (mirrors the conflict-preview pattern used in `BookingForm`). Not a hard rejection — user acknowledges and proceeds.

---

## Frontend Tasks

### Step 6 — Admin panel generalisation

- [ ] `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` — remove the hardcoded `entityType==='booking'` guard around line 41; accept `entityType` from `EntityConfig` so the panel renders for change requests too.
- [ ] Clone `BookingTypesPanel.tsx` → `ChangeRequestTypesPanel.tsx` (rather than fully abstracting — cheaper; booking types have type-specific fields like `color`). Register under `/admin/config/change-request` via `EntityConfig.tsx`.
- [ ] Add `'change_request'` to the `EntityType` union in `frontend/src/types/customField.ts`.

### Step 7 — CR service, slice, types

- [ ] `frontend/src/services/changeRequestService.ts` (mirror `bookingService`).
- [ ] `frontend/src/services/scheduleService.ts` — unified environment schedule API.
- [ ] `frontend/src/store/changeRequestSlice.ts` (mirror `bookingSlice`).
- [ ] `frontend/src/types/changeRequest.ts` — `ChangeRequestResponse`, `ChangeRequestCreate`, `ChangeType`, `OutageInfo`.
- [ ] `frontend/src/types/changeRequestLifecycle.ts` — mirror `bookingLifecycle.ts` types.

### Step 8 — CR pages

- [ ] `frontend/src/pages/change-requests/ChangeRequestList.tsx` — MUI DataGrid with column-visibility persistence (pattern from `BookingList.tsx`), filters (env / subsystem / status / date range).
- [ ] `frontend/src/pages/change-requests/ChangeRequestForm.tsx` — built on `FormDialog` + zod. Fields: subsystem selector, change-type selector, outage toggle + start/end pickers, lifecycle dropdown (filtered by `entity_type='change_request'`), scheduled start/end, link to release (optional), custom fields via `CustomFieldsSection`.
- [ ] `frontend/src/pages/change-requests/ChangeRequestDetail.tsx` — detail view reusing `TransitionButtons` + history timeline + `CustomFieldsDisplay`.
- [ ] Add **Change Requests** nav group to `frontend/src/components/AppLayout.tsx` (Calendar / List sub-items mirroring Bookings).

### Step 9 — `EnvironmentSchedule` component

- [ ] `frontend/src/pages/environments/EnvironmentSchedule.tsx` — new FullCalendar usage with two event sources (bookings blue, CRs orange); outage windows visually distinct (diagonal stripes or darker band). Event click → navigate to underlying detail page. Integrate as a new tab inside `EnvironmentDetail.tsx`.

---

## Acceptance Criteria

- [ ] Change requests can only be raised on sub-resources (subsystem), not on environments directly.
- [ ] Status transitions are validated against the lifecycle definition — invalid transitions return 400.
- [ ] Outage flag correctly records outage start/end; outage periods are visually distinct in the environment schedule.
- [ ] CR × booking outage overlap surfaces a non-blocking warning in the CR form.
- [ ] `/api/v1/environments/{id}/schedule` returns bookings and change requests in a single sorted timeline; `deployments` field present as an empty array.
- [ ] Notifications sent on create, transition, and completion events.
- [ ] All service methods have unit tests; all API endpoints have integration tests; fixtures mirror `test_booking_lifecycle.py` / `test_bookings.py`.
- [ ] Tenant isolation verified: all new table queries filter by `tenant_id`; data from one tenant is never returned to another.
- [ ] Existing booking functionality unaffected by the lifecycle-table rename — full booking test suite (`backend/tests/integration/test_bookings.py`, `test_booking_lifecycle.py`, `test_booking_transitions.py`, `test_conflicts_api.py`) still green.
