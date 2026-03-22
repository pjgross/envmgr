# Phase 2: Change Management

> Status: ⏳ **Planned** | Roadmap: [../plan.md](../plan.md)
> Duration: 4–6 weeks | Starts after Phase 1 completion

---

## Objectives

- Change request (TECR) CRUD on sub-resources (not the environment as a whole)
- Configurable change lifecycle per change type; at least one lifecycle includes an approval step
- Outage flag on changes (is there an environment outage during the change?)
- Change requests and bookings visible together on a unified environment schedule
- Link changes to releases and deployments
- Change history and audit trail
- Notifications on change status updates

---

## Backend Tasks

### Data Models & Migrations

- [ ] `ChangeRequest` model (`backend/app/db/models/change_request.py`)
  - Fields: `title`, `description`, `change_type` (configuration | infrastructure | code_deployment), `status`, `lifecycle_id` (FK to `LifecycleDefinition`), `subsystem_id` (FK → SubSystem — changes raised on sub-resources), `environment_id` (FK → Environment — for schedule display), `release_id` (nullable FK → Release), `has_outage` (bool), `outage_start` (nullable datetime), `outage_end` (nullable datetime), `scheduled_start`, `scheduled_end`, `tenant_id`, `deleted_at`
  - Note: `deployment_id` is **not** on ChangeRequest — the FK is on `Deployment.change_request_id` (Phase 4). Deployments link to changes, not the reverse.
- [ ] `ChangeHistory` model — field-level audit trail for change requests
- [ ] `LifecycleDefinition` model (`backend/app/db/models/lifecycle.py`)
  - Stores configurable state machines for `booking`, `change_request`, and `release` entity types
  - Fields: `entity_type` (enum: `booking | change_request | release`), `name`, `states` (JSONB array), `transitions` (JSONB — from → to allowed transitions), `tenant_id`
  - Phase 3 `Release.lifecycle_id` references this same table (entity_type = `release`); Phase 3 seeds default release lifecycles (Major, Minor, Emergency) on this model
- [ ] Alembic migrations for all new tables

### Service Layer

- [ ] `ChangeRequestService` (`backend/app/services/change_request_service.py`)
  - `create_change_request(tenant_id, data)` — validates subsystem scoping, writes event
  - `update_change_request(tenant_id, cr_id, data)`
  - `transition_status(tenant_id, cr_id, new_status)` — validates against lifecycle definition
  - `approve_change_request(tenant_id, cr_id)`
  - `reject_change_request(tenant_id, cr_id, reason)`
  - `list_change_requests(tenant_id, filters)` — by environment, subsystem, status, date range
  - `get_environment_schedule(tenant_id, env_id, start_date, end_date)` — returns bookings + change requests in a single unified timeline response
- [ ] `LifecycleService` (`backend/app/services/lifecycle_service.py`)
  - `get_lifecycle(entity_type, lifecycle_id)`
  - `validate_transition(current_status, new_status, lifecycle)`
  - Built-in default lifecycles seeded on tenant creation

### API Endpoints

- [ ] `backend/app/api/v1/change_requests.py`
  - `GET /api/v1/change-requests` — list with filters (env, subsystem, status, date range)
  - `POST /api/v1/change-requests` — create
  - `GET /api/v1/change-requests/{id}` — get single with full history
  - `PUT /api/v1/change-requests/{id}` — update
  - `POST /api/v1/change-requests/{id}/approve` — approve
  - `POST /api/v1/change-requests/{id}/reject` — reject with reason
  - `POST /api/v1/change-requests/{id}/transition` — generic status transition
  - `DELETE /api/v1/change-requests/{id}` — soft delete / cancel
- [ ] `GET /api/v1/environments/{id}/schedule` — unified environment schedule (bookings + change requests) for a date range
  - Response shape includes `deployments: []` as a forward-compatible field (always empty until Phase 4 populates it); consumers should expect this field and handle the empty array gracefully
- [ ] `backend/app/api/v1/lifecycles.py`
  - `GET /api/v1/lifecycles` — list available lifecycle definitions
  - `POST /api/v1/lifecycles` — create custom lifecycle (admin only)
  - `PUT /api/v1/lifecycles/{id}` — update lifecycle

### Events

- [ ] Events: `ChangeRequestCreated`, `ChangeRequestApproved`, `ChangeRequestRejected`, `ChangeRequestCompleted`
- [ ] Notification consumer for change request events

---

## Frontend Tasks

### Services & State

- [ ] `frontend/src/services/changeRequestService.ts` — CRUD and transition API calls
- [ ] `frontend/src/services/scheduleService.ts` — unified environment schedule API
- [ ] `frontend/src/store/changeRequestSlice.ts` — Redux slice with async thunks
- [ ] `frontend/src/types/changeRequest.ts` — `ChangeRequest`, `ChangeRequestCreate`, `ChangeType`, `OutageInfo`

### Pages & Components

- [ ] `frontend/src/pages/ChangeRequestList.tsx` — list with environment / subsystem / status filters
- [ ] `frontend/src/pages/ChangeRequestForm.tsx` — create/edit with:
  - Subsystem selector (change is on a sub-resource)
  - Change type selector
  - Outage toggle (yes/no) + outage start/end time picker (shown when yes)
  - Lifecycle selector (which lifecycle does this change follow?)
  - Scheduled start/end
  - Link to release (optional)
- [ ] `frontend/src/pages/ChangeRequestDetail.tsx` — detail view with history timeline and approval actions
- [ ] `frontend/src/components/EnvironmentSchedule.tsx` — unified timeline showing bookings (blue) and change requests / TECRs (orange) on the same axis; outage periods highlighted

---

## Acceptance Criteria

- [ ] Change requests can only be raised on sub-resources (subsystem), not on environments directly
- [ ] Status transitions are validated against the lifecycle definition — invalid transitions return 400
- [ ] Outage flag correctly records outage start/end; outage periods are visually distinct in the environment schedule
- [ ] `/api/v1/environments/{id}/schedule` returns bookings and change requests in a single sorted timeline
- [ ] Notifications sent on create, approve, reject, and complete events
- [ ] All service methods have unit tests; all API endpoints have integration tests
- [ ] Tenant isolation verified: all new table queries filter by `tenant_id`; data from one tenant is never returned to another
