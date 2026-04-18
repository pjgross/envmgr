# Phase 1: Environment Inventory + Shared Booking

> Status: ✅ **Complete** | Roadmap: [../plan.md](../plan.md)
> Core completed: 2026-03-23 | Extensions through: 2026-04-18

---

## Objectives

- Environment, System, and SubSystem CRUD with full multi-tenant isolation
- **System Catalog**: Systems are tenant-level definitions (not environment-scoped); Environments are composed of System instances via `EnvironmentSystem` junction records
- **Dependency modeling**: Systems and SubSystems declare service call dependencies on other Systems/SubSystems with direction (one-way / two-way) and bidirectional visibility
- **Environment Verify**: checks dependency completeness for an environment; surfaces missing/mocked systems
- Environment tracks installed sub-system versions (updated on deployment)
- Booking system with calendar UI and conflict detection
- Booking types: Shared (coordinated) and Exclusive (blocks all others)
- Recurring bookings (daily/weekly/monthly via RRULE, pre-generated up to 1 year)
- Configurable booking lifecycle (approval workflow: pending → approved/rejected)
- Excel import for environments and systems
- Event publishing infrastructure (outbox pattern → NATS JetStream)

---

## What Was Built

### Data Models (`backend/app/db/models/`)

| Model | File | Notes |
|-------|------|-------|
| `System` | `system.py` | Tenant-level catalog; name unique per tenant (soft-delete aware) |
| `SubSystem` | `system.py` | Belongs to System; cascade soft-delete when parent deleted |
| `Environment` | `environment.py` | Status enum: active/inactive/maintenance/decommissioned |
| `EnvironmentSystem` | `environment.py` | Junction: System instance in an Environment with status + mock_notes |
| `SystemDependency` | `dependency.py` | from/to system, type, source, direction (one_way/two_way) |
| `ComponentDependency` | `dependency.py` | from/to subsystem, type, protocol, port, source, direction |
| `EnvironmentSubSystemVersion` | `version.py` | Append-only audit trail; no deleted_at |
| `Booking` | `booking.py` | RRULE recurrence; self-FK recurrence_parent_id with use_alter=True |
| `EventLog` | `event_log.py` | Outbox table; published_at=NULL until worker picks up |

All models: `native_enum=False` (VARCHAR storage), soft deletes via `deleted_at`.

### Services (`backend/app/services/`)

- `system_service.py` — System + SubSystem CRUD; cascade soft-delete; name uniqueness enforced at service layer
- `environment_service.py` — Environment CRUD + `verify_environment` (bulk dep query, no N+1)
- `environment_system_service.py` — add/update/remove systems from environments
- `dependency_service.py` — System + Component deps with bidirectional listing (outgoing + incoming), PATCH update, delete from either side
- `version_service.py` — always INSERT (append-only); current_only via Python dedup; validates subsystem is linked to environment before recording
- `excel_import_service.py` — openpyxl-based async import; skip existing by name; returns `{created, skipped, errors}`
- `booking_service.py` — overlap detection, RRULE expansion (parent = first occurrence, children capped at 100/year), approve/reject cascade to children
- `events.py` (`publish_event`) — adds EventLog row to session, NO commit (atomicity via get_db)
- `event_publisher.py` — background worker: SELECT FOR UPDATE SKIP LOCKED, publishes to `envmgr.events.<Type>.<Event>`, exponential backoff on NATS failure

### API Endpoints (`backend/app/api/v1/`)

```
# Systems
GET/POST                    /api/v1/systems
GET/PATCH/DELETE            /api/v1/systems/{id}
GET/POST/PATCH/DELETE       /api/v1/systems/{id}/subsystems[/{sub_id}]

# Dependencies (bidirectional — returns incoming + outgoing)
GET/POST                    /api/v1/systems/{id}/dependencies
PATCH/DELETE                /api/v1/systems/{id}/dependencies/{dep_id}
GET/POST                    /api/v1/subsystems/{id}/dependencies
PATCH/DELETE                /api/v1/subsystems/{id}/dependencies/{dep_id}

# Environments
GET/POST                    /api/v1/environments
GET/PATCH/DELETE            /api/v1/environments/{id}
GET                         /api/v1/environments/{id}/verify
GET/POST                    /api/v1/environments/{id}/systems
PATCH/DELETE                /api/v1/environments/{id}/systems/{sid}
GET/POST                    /api/v1/environments/{id}/versions

# Bookings
GET/POST                    /api/v1/bookings
GET                         /api/v1/bookings/{id}
POST                        /api/v1/bookings/{id}/approve
POST                        /api/v1/bookings/{id}/reject
POST                        /api/v1/bookings/{id}/cancel
DELETE                      /api/v1/bookings/{id}              (deletes series)
DELETE                      /api/v1/bookings/{id}/occurrence   (single occurrence)

# Import
POST                        /api/v1/import/environments
POST                        /api/v1/import/systems
```

### Frontend (`frontend/src/`)

| File | Description |
|------|-------------|
| `pages/systems/SystemCatalog.tsx` | DataGrid with name filter, "New System" dialog |
| `pages/systems/SystemDetail.tsx` | 4 tabs: Overview, SubSystems, Dependencies (bidirectional + edit), Component Deps (subsystem-level + edit) |
| `pages/environments/EnvironmentList.tsx` | Status chip filters, click → detail |
| `pages/environments/EnvironmentDetail.tsx` | 4 tabs: Overview, Systems, Versions, + Verify panel |
| `pages/bookings/BookingCalendar.tsx` | FullCalendar month/week; events colored by status; approve/reject actions |
| `pages/bookings/BookingForm.tsx` | RRULE builder (daily/weekly/monthly + UNTIL/COUNT) |
| `pages/import/ImportPage.tsx` | File upload for environments + systems; error table |
| `components/AppLayout.tsx` | MUI Drawer sidebar: Dashboard, Environments, Systems, Bookings, Import |
| `store/` | Redux slices for all entities |
| `services/` | Axios API clients for all entities |
| `types/` | TypeScript interfaces matching all backend schemas |

### Events Published

| Service | Event |
|---------|-------|
| environment_service | EnvironmentCreated / Updated / Deleted |
| system_service | SystemCreated / Updated / Deleted |
| booking_service | BookingCreated / Approved / Rejected / Cancelled |

### Tests

- `tests/integration/test_systems.py` — 11 tests
- `tests/integration/test_environments.py` — 12 tests
- `tests/integration/test_dependencies.py` — 13 tests (incl. bidirectional, edit, direction)
- `tests/integration/test_environment_verify.py` — satisfied/mocked/missing scenarios
- `tests/integration/test_bookings.py` — 14 tests (incl. recurring, overlap, series delete)
- `tests/integration/test_versions.py` — 7 tests
- `tests/integration/test_import.py` — 5 tests
- `tests/integration/test_events.py` — 10 tests
- `tests/unit/test_event_publisher.py` — 5 tests (mocked NATS)

**142/143 passing** (1 pre-existing failure in Phase 0 auth test: `test_tenant_admin_cannot_escalate_to_master_admin`)

---

## Deviations from Original Spec

| Area | Spec | Actual |
|------|------|--------|
| Event broker | RabbitMQ | NATS JetStream (matches stack; spec was a typo) |
| PostgreSQL RLS | Planned for Phase 1 | Deferred — app-level `tenant_id` filtering used throughout; sufficient for now |
| Recurring bookings | horizon "e.g., 3 months" | Pre-generate up to 1 year or 100 occurrences (whichever comes first) |
| EnvironmentSubSystemVersion | "One record per subsystem; updated on each deployment" | Append-only audit trail (multiple records per subsystem; use current_only=True to get latest) |
| Dependencies | Outgoing only | Bidirectional: listing includes both outgoing and incoming, with `is_incoming` flag and `direction` (one_way/two_way) field |
| Dependencies | No edit | PATCH endpoint added; edit dialog in frontend |
| Component Dependencies | Backend only | Full UI in SystemDetail → Component Deps tab |
| Migration approach | `--autogenerate` | Manual DDL only — `init_db()`'s `create_all` makes autogenerate produce empty files |

---

## Migrations Applied

| Revision | Description |
|----------|-------------|
| `bdaf96c2f222` | add_system_subsystem |
| (M2 revision) | add_environment_environment_system |
| `0d99256c6a56` | add_booking |
| `2436af1aef0c` | add_environment_subsystem_version |
| `cedd5a0a1194` | add_event_log |
| `b76537c3d46a` | add_direction_to_dependencies |

---

## Post-Completion Extensions (2026-03-24 → 2026-04-18)

After the 2026-03-23 cutoff, Phase 1 kept accruing functional polish before Phase 2 kicked off. Each extension has its own plan under `docs/superpowers/plans/` and the matching design spec under `docs/superpowers/specs/`.

### Backend additions

| Area | What landed | Plan file |
|------|-------------|-----------|
| Custom fields | `CustomFieldDefinition` + per-entity `custom_fields` JSON on Environment, System, Booking, BookingRequest; tenant-scoped CRUD API | `2026-03-23-custom-fields.md` |
| Topology verify | Environment topology diagram data (nodes + edges) + verify endpoint returning missing/mocked subsystems and component dep gaps | `2026-03-24-environment-subsystem-topology-verify.md` |
| Configurable booking lifecycle | `BookingType`, `LifecycleTemplate` (states + transitions + field permissions), `BookingStatusHistory`; per-type lifecycle; `/bookings/{id}/transition` + `/allowed-transitions` replace hardcoded approve/reject/cancel | `2026-03-25-booking-lifecycle.md`, `2026-03-25-booking-admin-lifecycle-tab.md`, `2026-03-25-booking-custom-field-type-state-permissions.md`, `2026-03-25-lifecycle-standard-field-permissions.md` |
| Component type catalog | `ComponentTypeDefinition` (tenant-level), assignment on EnvironmentSubSystem (real/mock toggle, mock notes) | `2026-03-26-environment-component-type-assignment.md` |
| Multi-env booking requests | `BookingRequest` parent → N `Booking` children; `BookingConflictAck` for soft conflicts; preview-conflicts endpoint; delegate users; per-env overrides via `EditEnvOverridesDialog` | `2026-04-15-multi-env-booking-lifecycle.md` |
| Received conflict feedback | `/bookings/{id}/received-feedback` + service aggregating other bookings' ack notes | `2026-04-18-received-conflict-feedback.md` |

### Frontend additions

- **DataGrid migrations**: Systems catalog and Environments list converted to MUI `DataGrid` with custom columns driven by `CustomFieldDefinition` (`2026-03-23-systems-environments-datagrid-custom-columns.md`).
- **Booking list redesign**: per-row kebab → dynamic transition actions from lifecycle; inline conflict indicator; status + context filters.
- **BookingForm**: multi-env picker, delegates autocomplete, debounced conflict preview, custom-fields subform.
- **BookingDetail**: environments panel with per-env transition buttons, conflicts panel (your feedback + feedback received tabs), env-override edit dialog.
- **Admin panels**: `BookingTypesPanel`, `LifecycleTemplatesPanel`, `ComponentTypesPanel`, `CustomFieldDefinitionManager` under `/admin/config/{entity}`.
- **Tier 1 frontend modernisation** (`docs/frontend-modernisation-plan.md`): `notistack` snackbars, `react-error-boundary`, `NotFound` 404, `createAppTheme` factory with light/dark/system mode persisted to localStorage, responsive `AppLayout` drawer, `DataTable` wrapper (density + column-visibility persistence), form-stack primitives (`FormDialog`, `FormTextField`, `FormSelect`) with `react-hook-form` + `zod`, `.prettierrc` + `.eslintrc.cjs`, `formatApiError` helper.

### Migrations added (selected)

`add_custom_field_definition`, `add_booking_types_lifecycle`, `add_booking_status_history`, `add_component_type_definition`, `add_booking_request_conflict_ack`, `backfill_booking_request_id`, `drop_legacy_booking_columns`.

---

## Known Issues / Tech Debt

- ~~`test_tenant_admin_cannot_escalate_to_master_admin` failing~~ — **fixed 2026-03-23** (commit `d3e3236` removed `is_master_admin` from `UserAdminUpdate` schema).
- ~~`security.py` uses deprecated `datetime.utcnow()`~~ — **fixed 2026-04-18** (commit `6578bc9` switched JWT exp calculation to `datetime.now(timezone.utc)`).
- `init_db()` + Alembic coexistence: `init_db` calls `create_all` at startup (useful for fresh dev envs) while Alembic handles production migrations; these can drift if not kept in sync. Mitigation is discipline — write manual Alembic DDL for every schema change.
- Frontend modernisation Tiers 2-4 (calendar drag, bulk ops, URL filter persistence, breadcrumbs, inline DataGrid edit, Vitest + RTL, CI, a11y pass, TanStack Query migration) explicitly deferred — revisit after Phase 2 if server-state ergonomics or UX polish becomes a pain point.
