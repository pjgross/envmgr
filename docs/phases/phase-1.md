# Phase 1: Environment Inventory + Shared Booking

> Status: 🔄 **In Progress** | Roadmap: [../plan.md](../plan.md)
> Duration: 6–8 weeks

---

## Objectives

- Environment, System, and SubSystem CRUD with full multi-tenant isolation
- **System Catalog**: Systems are tenant-level definitions (not environment-scoped); Environments are composed of System instances via `EnvironmentSystem` junction records
- **Dependency modeling**: Systems and SubSystems declare service call dependencies on other Systems/SubSystems (manual entry; Phase 6 IaC import populates the same tables)
- **Environment Verify**: checks dependency completeness for an environment; surfaces missing systems with options to add or mark as mocked
- Environment tracks installed sub-system versions (updated on deployment)
- Booking system with calendar UI and soft conflict detection
- Booking types: Shared (coordinated) and Exclusive (blocks all others)
- Recurring bookings (daily/weekly/monthly via RRULE)
- Booking auto-tag (deployment vs regression) when linked to a release test phase
- Configurable booking lifecycle (approval workflow)
- Excel import for environments and systems
- Event publishing infrastructure (outbox pattern)
- PostgreSQL RLS policies for tenant isolation

---

## Backend Tasks

### Data Models & Migrations

- [ ] `Environment` model (`backend/app/db/models/environment.py`)
  - Fields: `name`, `description`, `environment_type`, `status` (enum: `active | inactive | maintenance | decommissioned`), `tenant_id`, `custom_fields` (JSONB), `deleted_at`
- [ ] `System` model (`backend/app/db/models/system.py`)
  - Fields: `name`, `description`, `tenant_id`, `github_repository_url`, `custom_fields` (JSONB), `deleted_at`
  - **No `environment_id`** — System is a tenant-level catalog entry
- [ ] `EnvironmentSystem` model (`backend/app/db/models/environment_system.py`)
  - Junction table: links a System to an Environment with instance-specific state
  - Fields: `environment_id` (FK → Environment), `system_id` (FK → System), `status` (enum: `active | inactive | mock`), `mock_notes` (nullable text), `tenant_id`, `created_at`
- [ ] `SystemDependency` model (`backend/app/db/models/system_dependency.py`)
  - Declares a service call dependency from one System to another
  - Fields: `from_system_id` (FK → System), `to_system_id` (FK → System), `description` (nullable), `dependency_type` (enum: `api_call | database | message_queue | event | file | other`), `source` (enum: `manual | terraform | docker_compose`; Phase 1 always `manual`; Phase 6 parsers set `terraform` or `docker_compose`), `tenant_id`, `deleted_at`
- [ ] `SubSystem` model (`backend/app/db/models/subsystem.py`)
  - Fields: `name`, `description`, `system_id` (FK → System), `tenant_id`, `custom_fields` (JSONB), `deleted_at`
  - SubSystem is part of the catalog (parent System is catalog-level)
- [ ] `ComponentDependency` model (`backend/app/db/models/component_dependency.py`)
  - Declares a service call dependency from one SubSystem to another (cross-system calls allowed)
  - Fields: `from_subsystem_id` (FK → SubSystem), `to_subsystem_id` (FK → SubSystem), `description` (nullable), `dependency_type` (enum: `api_call | database | message_queue | event | file | other`), `protocol` (nullable: `HTTP | gRPC | AMQP | TCP | other`), `port` (nullable int), `source` (enum: `manual | terraform | docker_compose`; Phase 6 parsers set `terraform` or `docker_compose`), `tenant_id`, `deleted_at`
- [ ] `EnvironmentSubSystemVersion` model (`backend/app/db/models/environment_subsystem_version.py`)
  - Tracks: `environment_id`, `subsystem_id`, `build_id` (nullable — FK constraint to `Build` table is added in Phase 4 migration; column exists from Phase 1 without constraint), `version_label`, `installed_at`, `tenant_id`
  - One record per subsystem per environment; updated on each deployment
- [ ] `Booking` model (`backend/app/db/models/booking.py`)
  - Fields: `environment_id` (FK → Environment), `environment_group_id` (nullable FK → EnvironmentGroup — Phase 7 activates group-level booking logic; column present from Phase 1 for forward compatibility), `project_name`, `booked_by`, `start_date`, `end_date`, `booking_type` (shared | exclusive), `status` (pending/approved/rejected), `notes`, `recurrence_rule` (RRULE string, nullable), `recurrence_parent_id` (FK to parent booking, nullable), `release_id` (nullable FK), `test_phase_id` (nullable FK — FK constraint to Phase 3 `TestPhase` table; column exists from Phase 1), `context_tag` (enum: `deployment | regression | none`, auto-computed), `tenant_id`, `deleted_at`
- [ ] Alembic migration for all new tables
- [ ] PostgreSQL RLS policies for `environment`, `system`, `environment_system`, `system_dependency`, `subsystem`, `component_dependency`, `booking`

### Service Layer

- [ ] `EnvironmentService` (`backend/app/services/environment_service.py`)
  - `list_environments(tenant_id, filters)` with pagination
  - `get_environment(tenant_id, env_id)`
  - `create_environment(tenant_id, data)`
  - `update_environment(tenant_id, env_id, data)`
  - `delete_environment(tenant_id, env_id)` (soft delete)
- [ ] `SystemService` (`backend/app/services/system_service.py`)
  - CRUD methods scoped to **tenant only** (no environment filter — catalog-level)
  - `list_systems(tenant_id, filters)` — returns all systems in the catalog
  - `get_system(tenant_id, system_id)`
  - `create_system(tenant_id, data)`, `update_system(...)`, `delete_system(...)` (soft delete)
- [ ] `EnvironmentSystemService` (`backend/app/services/environment_system_service.py`)
  - `add_system_to_environment(tenant_id, env_id, system_id)` — creates `EnvironmentSystem` record (`status = active`)
  - `remove_system_from_environment(tenant_id, env_id, system_id)` — removes `EnvironmentSystem` record
  - `update_system_status(tenant_id, env_id, system_id, status, mock_notes=None)` — updates status (active | inactive | mock)
  - `list_environment_systems(tenant_id, env_id)` — returns systems in environment with their status
- [ ] `DependencyService` (`backend/app/services/dependency_service.py`)
  - `list_system_dependencies(tenant_id, system_id)` — outgoing dependencies for a system
  - `create_system_dependency(tenant_id, data)` — `source` defaults to `manual`
  - `delete_system_dependency(tenant_id, dependency_id)`
  - `list_component_dependencies(tenant_id, subsystem_id)` — outgoing dependencies for a subsystem
  - `create_component_dependency(tenant_id, data)`
  - `delete_component_dependency(tenant_id, dependency_id)`
- [ ] `EnvironmentService.verify_environment(tenant_id, env_id)` — returns structured gap report:
  1. Get all `EnvironmentSystem` records for the environment
  2. For each system, get all `SystemDependency` records where `from_system_id = system`
  3. For each dependency target, classify as `satisfied` (active), `mocked` (status=mock), or `missing` (no record)
  4. Run component-level check: `ComponentDependency` targets whose parent system is missing or mocked → surface as `component_gaps` under the parent system entry
  5. Return `{ satisfied, missing: [{system, required_by, component_gaps, actions}], mocked }`
- [ ] `SubSystemService` (`backend/app/services/subsystem_service.py`)
  - CRUD methods scoped to tenant and system
- [ ] `BookingService` (`backend/app/services/booking_service.py`)
  - `create_booking(tenant_id, data)` — checks overlap, writes event
  - `approve_booking(tenant_id, booking_id)`
  - `reject_booking(tenant_id, booking_id, reason)`
  - `list_bookings(tenant_id, filters)` — date range, environment, status
  - `check_overlap(env_id, start_date, end_date, booking_type, exclude_id=None)` — soft conflict; exclusive bookings conflict with any other booking; shared bookings only surface as informational
  - `expand_recurrence(booking)` — generates child booking records from `recurrence_rule` (RRULE) for a defined horizon (e.g. 3 months ahead)
  - `compute_context_tag(booking, release)` — when booking is linked to a release test phase, derives `deployment` or `regression` based on the system role of the environment's system on that release

### API Endpoints

- [ ] `backend/app/api/v1/environments.py`
  - `GET /api/v1/environments` — list with pagination + filtering
  - `POST /api/v1/environments` — create
  - `GET /api/v1/environments/{id}` — get single
  - `PUT /api/v1/environments/{id}` — update
  - `DELETE /api/v1/environments/{id}` — soft delete
- [ ] `backend/app/api/v1/systems.py` — System catalog CRUD (no environment filter)
  - `GET /api/v1/systems` — list catalog (tenant-scoped; no env filter)
  - `POST /api/v1/systems` — create
  - `GET /api/v1/systems/{id}` — get single (includes dependency summary)
  - `PUT /api/v1/systems/{id}` — update
  - `DELETE /api/v1/systems/{id}` — soft delete
  - `GET /api/v1/systems/{id}/dependencies` — outgoing SystemDependency records
  - `POST /api/v1/systems/{id}/dependencies` — add SystemDependency
  - `DELETE /api/v1/systems/{id}/dependencies/{dep_id}` — remove SystemDependency
- [ ] Environment system membership endpoints (in `backend/app/api/v1/environments.py`)
  - `GET /api/v1/environments/{id}/systems` — list systems in environment with status
  - `POST /api/v1/environments/{id}/systems` — add a system from catalog to environment
  - `PATCH /api/v1/environments/{id}/systems/{system_id}` — update status / mock_notes
  - `DELETE /api/v1/environments/{id}/systems/{system_id}` — remove from environment
  - `GET /api/v1/environments/{id}/verify` — run Environment Verify; returns gap report
- [ ] `backend/app/api/v1/subsystems.py` — SubSystem catalog CRUD
  - `GET/POST/PUT/DELETE /api/v1/subsystems/{id}` — same CRUD pattern
  - `GET /api/v1/subsystems/{id}/dependencies` — outgoing ComponentDependency records
  - `POST /api/v1/subsystems/{id}/dependencies` — add ComponentDependency
  - `DELETE /api/v1/subsystems/{id}/dependencies/{dep_id}` — remove ComponentDependency
- [ ] `backend/app/api/v1/bookings.py`
  - `GET /api/v1/bookings` — list (date range, env, status filters)
  - `POST /api/v1/bookings` — create (triggers overlap check)
  - `GET /api/v1/bookings/{id}` — get single
  - `POST /api/v1/bookings/{id}/approve` — approve
  - `POST /api/v1/bookings/{id}/reject` — reject with reason
  - `DELETE /api/v1/bookings/{id}` — cancel (soft delete)
- [ ] Register all new routers in `backend/app/main.py`

### Event Infrastructure

- [ ] `Event`/`EventLog` model for outbox pattern
- [ ] Alembic migration for `event_log` table
- [ ] `publish_event()` utility in `backend/app/core/events.py`
- [ ] Background outbox worker that reads `event_log` and publishes to RabbitMQ

### Excel Import

- [ ] Excel import endpoint: `POST /api/v1/import/environments`
- [ ] Excel import endpoint: `POST /api/v1/import/systems`
- [ ] Update `ExcelImportService` to handle environment and system sheets
- [ ] Validation and error reporting in import response

---

## Frontend Tasks

### Services

- [ ] `frontend/src/services/environmentService.ts` — CRUD API calls + verify endpoint
- [ ] `frontend/src/services/systemService.ts` — catalog CRUD + dependency endpoints
- [ ] `frontend/src/services/bookingService.ts`

### Redux Slices

- [ ] `frontend/src/store/environmentSlice.ts` — list, create, update, delete thunks + selectors
- [ ] `frontend/src/store/systemSlice.ts`
- [ ] `frontend/src/store/bookingSlice.ts`

### TypeScript Types

- [ ] `frontend/src/types/environment.ts` — `Environment`, `EnvironmentCreate`, `EnvironmentUpdate`, `EnvironmentSystem`, `EnvironmentSystemStatus`, `VerifyResult`, `VerifyMissing`, `VerifyMocked`
- [ ] `frontend/src/types/system.ts` — `System`, `SystemCreate`, `SubSystem`, `SystemDependency`, `ComponentDependency`, `DependencyType`, `DependencySource`
- [ ] `frontend/src/types/booking.ts` — `Booking`, `BookingCreate`, `BookingStatus`, `BookingType` (shared | exclusive), `RecurrenceRule`

### Pages & Components

- [ ] `frontend/src/pages/SystemCatalog.tsx` — global system catalog list (not per-environment); search, filter; link to SystemDetail
- [ ] `frontend/src/pages/SystemDetail.tsx` — sub-systems list; **dependency graph panel** showing outgoing and incoming SystemDependency records (which systems this calls, which systems call this); link to add dependency
- [ ] `frontend/src/pages/SubSystemDetail.tsx` — component dependency list showing outgoing/incoming ComponentDependency records; link to add component dependency
- [ ] `frontend/src/pages/EnvironmentList.tsx` — list with search/filter, link to detail
- [ ] `frontend/src/pages/EnvironmentDetail.tsx` — tabbed detail view:
  - **Overview** tab: environment details, status, metadata
  - **Systems** tab: list of `EnvironmentSystem` records with status badges (active / inactive / mock); "Add System" button to search catalog and add; "Mark as mocked" action with mock_notes field; "Remove" action
  - **Verify** tab: Environment Verify panel showing gap report — satisfied systems (green), missing systems (red, with "Add" and "Mark as mocked" actions), mocked systems (amber, with mock_notes displayed); component-level gaps nested under parent system
  - **Bookings** tab: booking calendar and list for this environment
- [ ] `frontend/src/components/BookingCalendar.tsx` — calendar view of bookings per environment
- [ ] `frontend/src/pages/BookingList.tsx` — list view with status filters
- [ ] `frontend/src/pages/BookingForm.tsx` — create/edit booking form with:
  - Booking type selector (Shared / Exclusive)
  - Overlap warning panel showing conflicting bookings
  - Recurrence options (none / daily / weekly / monthly) with end-date or count
- [ ] Approval actions UI (approve/reject buttons with confirmation)
- [ ] Navigation links in sidebar/nav for Environments, Systems (catalog), and Bookings

---

## Acceptance Criteria

- [ ] All CRUD endpoints return correct status codes and paginated response format
- [ ] Tenant isolation verified: data from tenant A is never visible to tenant B
- [ ] System catalog list (`GET /api/v1/systems`) returns all tenant systems with no environment filter
- [ ] `POST /api/v1/environments/{id}/systems` correctly creates an `EnvironmentSystem` record with `status = active`
- [ ] `PATCH /api/v1/environments/{id}/systems/{system_id}` correctly updates status to `mock` with `mock_notes`
- [ ] `GET /api/v1/environments/{id}/verify` returns correct `satisfied`, `missing`, and `mocked` lists based on `SystemDependency` records and `EnvironmentSystem` records for the environment
- [ ] Component-level gaps appear nested under their parent system gap in the verify response
- [ ] Verify "missing" items include both "add_to_environment" and "mark_as_mock" in the `actions` array
- [ ] Booking overlap detection returns a warning (not a hard block) for conflicting date ranges; exclusive bookings show a stronger warning
- [ ] Recurring bookings create a parent record + expanded child records visible in calendar view
- [ ] Approved/rejected bookings reflect the correct status in list and detail views
- [ ] Excel import correctly creates or updates environments and systems
- [ ] Events are written to `event_log` table atomically with booking operations
- [ ] All new service methods have unit tests (`backend/tests/unit/`)
- [ ] All new API endpoints have integration tests (`backend/tests/integration/`)
- [ ] Tenant isolation verified: queries on all new tables filter by `tenant_id`; data from one tenant is never returned to another
