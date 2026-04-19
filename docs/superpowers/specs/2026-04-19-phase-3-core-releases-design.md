# Phase 3 Sub-Project 1 — Core Releases

**Date:** 2026-04-19
**Status:** Design — awaiting implementation plan
**Scope:** First of four sub-projects decomposed from Phase 3. Subsequent sub-projects: (2) Enterprise Releases, (3) Jira Integration, (4) PIR — PIR moves to Phase 5.

## Context

Phase 2 shipped Change Requests and generalised `lifecycle_template` across entity types. Phase 1 shipped environment bookings. The natural next step is **Releases**, which are the container that coordinates changes and bookings over multiple test phases. A release has:

- A lifecycle workflow (e.g. `Draft → Submitted → Approved → In Progress → Ready for Release → Completed | Completed with Issues | Backed Out | Cancelled`). Release types (Major / Minor / Emergency / custom Waterfall / Agile / AI-ML …) each get their own lifecycle template. Test phases (SIT, UAT, Staging) are **plan items inside the `in_progress` state, not states themselves** — this keeps workflow and plan orthogonal.
- Test phases (SIT, UAT, Staging — user-configurable) with start/end dates. Test phases form the release's plan Gantt.
- Gates with acceptance criteria, optionally pinned to specific phases. Failing or passing a gate records a decision with notes.
- Systems playing roles (changing / regression / config_only) with optional per-system deployment dates.
- Environment bookings — one booking per environment per phase, with **multiple environments allowed per phase**. Booking `context_tag` is auto-derived from the system's role on the release.
- Change requests linked via `change_request.release_id` (already stubbed in Phase 2).
- Scope items (user stories / defects) — manually added here, Jira-synced in sub-project 3.
- A tenant-configurable event log (audit trail).
- Dependency links to other releases, with banner alerts when a dependency's target date shifts.

Phase 3 sub-project 1 delivers the entire backbone above. Enterprise Releases, Jira integration, and PIR follow in their own MRs.

## Goals

- Create, edit, and transition a release through a type-specific lifecycle.
- Plan a release's phases and gates and render them as the release's Gantt.
- Book multiple environments against each phase atomically from the release form; continue to support ad-hoc bookings unchanged.
- See the status of all bookings and CRs linked to a release at a glance.
- Manage scope items manually (Jira syncs them in sub-project 3).
- Record events (reschedule reasons, scope changes, stakeholder notes) against a release.
- Maintain a release template library and instantiate fully-formed releases from templates.
- Alert release owners when a dependency's target date has shifted.

## Non-goals

- Enterprise Release parent/child admission flow and UI — **sub-project 2**. `parent_release_id` column lands now to avoid a second migration, but no API or UI references it.
- Jira webhook receiver, `JiraProjectConfig`, field mapping editor, `JiraEpic`, Epic pages — **sub-project 3**. `release_change` table ships in this sub-project; sub-project 3 populates it via webhook without schema change.
- `PostImplementationReview` and `Incident` linkage — **Phase 5**.
- Notification consumer for release/booking/CR events — cross-cutting carry-over already deferred.
- `deployments: []` population on the unified schedule endpoint — **Phase 4**.
- No new approval workflow on bookings; bookings keep their Phase 1 lifecycle.
- No Enterprise role model changes; RBAC reuses the existing roles.

## Data model

### New tables

#### `release_template`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK → tenant | Tenant-scoped. |
| `name` | str | |
| `description` | text | |
| `release_type` | str(50) | Free string; matches `lifecycle_template.name` or an admin-chosen label. |
| `default_lifecycle_template_id` | int FK → lifecycle_template, nullable | Falls back to tenant default with `entity_type='release'`. |
| `phases` | JSONB | `[{name, order, default_duration_days, activities: [str]}]` |
| `gates` | JSONB | `[{name, phase_name \| null, acceptance_criteria}]` |
| `version` | int | Bumped on each save (simple audit counter — no history table). |
| `deleted_at` | datetime, nullable | Soft delete. |

#### `release`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK → tenant | Tenant-scoped. |
| `name` | str(250) | |
| `description` | text, nullable | |
| `release_type` | str(50) | Free string; used to scope custom fields via `entity_subtype`. |
| `release_kind` | str(20) | `'project'` default; `'enterprise'` reserved for sub-project 2. |
| `parent_release_id` | int self-FK, nullable | Reserved for sub-project 2; no service logic reads it yet. |
| `template_id` | int FK → release_template, nullable | |
| `lifecycle_template_id` | int FK → lifecycle_template | Must have `entity_type='release'`. |
| `status` | str(100) | Lifecycle state; default `'draft'`. |
| `target_date` | datetime, nullable | |
| `actual_date` | datetime, nullable | Stamped on transition to a terminal completed/deployed state. |
| `custom_fields` | JSONB, nullable | |
| `raised_by` | int FK → user | |
| `deleted_at` | datetime, nullable | Soft delete. |

#### `release_status_history`
Immutable audit row, mirrors `booking_status_history`:
`release_id (FK), from_state, to_state, changed_by (FK → user), changed_at, notes`. No `deleted_at`.

#### `test_phase`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `release_id` | int FK → release, ondelete CASCADE | |
| `name` | str(100) | SIT / UAT / Staging / custom. |
| `order` | int | Drives ordering on Gantt and tables. |
| `start_date` | datetime, nullable | Nullable until the RM enters it. |
| `end_date` | datetime, nullable | Ditto. |
| `status` | str(50) | `'pending' \| 'active' \| 'complete' \| 'skipped'`. |
| `deleted_at` | datetime, nullable | |

#### `release_gate`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `release_id` | int FK → release, ondelete CASCADE | |
| `test_phase_id` | int FK → test_phase, nullable | Null = release-level gate (e.g. CAB). |
| `name` | str(150) | |
| `acceptance_criteria` | text | |
| `status` | str(20) | `'pending' \| 'passed' \| 'failed' \| 'overridden'`. |
| `decided_by` | int FK → user, nullable | |
| `decided_at` | datetime, nullable | |
| `decision_notes` | text, nullable | |
| `deleted_at` | datetime, nullable | |

#### `release_system` (junction)
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `release_id` | int FK → release, ondelete CASCADE | |
| `system_id` | int FK → system | |
| `role` | str(20) | `'changing' \| 'regression' \| 'config_only'`. |
| `deployment_date` | datetime, nullable | |

Unique `(release_id, system_id)`.

#### `release_dependency`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `release_id` | int FK → release, ondelete CASCADE | Dependent release. |
| `depends_on_release_id` | int FK → release | Release being depended on. |
| `kind` | str(20) | `'deploys_after'` default. |
| `notes` | text, nullable | |
| `last_dependency_target_date` | datetime, nullable | Captured on create; used to detect shifts. |

Unique `(release_id, depends_on_release_id)`. Check constraint `release_id != depends_on_release_id`.

#### `release_event_type`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `name` | str(100) | |
| `display_color` | str(7), nullable | Hex. |
| `is_system` | bool | Seeded types can't be deleted, only disabled. |
| `deleted_at` | datetime, nullable | |

#### `release_event`
Append-only audit/notes log. No `deleted_at`.
`id, tenant_id, release_id (FK cascade), event_type_id (FK → release_event_type), description (text), occurred_at (datetime), recorded_by (FK → user)`.

#### `release_change`
Scope items. Manually CRUDed in sub-project 1; populated by Jira webhook in sub-project 3.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `release_id` | int FK → release, ondelete CASCADE | |
| `external_key` | str(50), nullable | e.g. Jira key. Unique per tenant when non-null (enforced by partial index below). |
| `title` | str(500) | |
| `description` | text, nullable | |
| `change_kind` | str(20) | `'story' \| 'defect'`. |
| `external_status` | str(100), nullable | Jira status string once synced. |
| `system_id` | int FK → system, nullable | |
| `custom_fields` | JSONB, nullable | Jira-mapped values in sub-project 3. |
| `jira_project_config_id` | int, nullable | No FK until sub-project 3 ships the referenced table. |
| `epic_id` | int, nullable | Same — becomes FK in sub-project 3. |
| `source` | str(20) | `'manual' \| 'jira'`. Default `'manual'`. |
| `deleted_at` | datetime, nullable | |

Partial-unique index on `(tenant_id, external_key)` where `external_key IS NOT NULL`.

### Table modifications

#### `booking`
- `release_id`: promote from bare nullable int to real FK `ForeignKey("release.id", ondelete="SET NULL")`, still nullable.
- `test_phase_id`: promote similarly to `ForeignKey("test_phase.id", ondelete="SET NULL")`, still nullable.
- On write, `context_tag` is derived from the release's `release_system.role` for the system in the booking's environment subsystem chain. Stored on the row (not virtual) so reporting is cheap.

#### `change_request`
- `release_id`: promote to real FK `ForeignKey("release.id", ondelete="SET NULL")`, still nullable.

#### `custom_field_definition`
- Add `entity_subtype` (`String(50), nullable`). Null = applies to all subtypes.
- For releases, `entity_subtype` holds the release type string (e.g. `'Major'`, `'Agile Sprint'`). Same mechanism becomes available to bookings and CRs with no further schema work.
- The existing `lifecycle_states` column continues to drive per-state visibility.
- Editability per state + role stays in `lifecycle_template.definition.field_permissions` — unchanged.

### `ENTITY_FIELD_SPECS` registration
Add a `'release'` entry to `backend/app/api/v1/schemas/booking_lifecycle.py` listing the standard release field names: `name, description, release_type, target_date, actual_date, raised_by`. This unlocks `validate_definition_for_entity(..., 'release')`.

## Lifecycle + custom field conditionality

Releases plug into the existing `lifecycle_template` table. No new interpreter concept — the booking interpreter already handles per-state visibility (by presence in `field_permissions[state].custom_fields`), per-state editability, and per-state role gating via `editable_by[]`.

### Minimal extension: required-before-transition

One new key inside `field_permissions[state]`:

```json
"field_permissions": {
  "approved": {
    "standard_fields": { ... },
    "custom_fields":   { ... },
    "required_fields": ["business_sponsor", "risk_assessment"]
  }
}
```

Transition rule: before allowing `from_state → to_state`, every key in `field_permissions[to_state].required_fields` must have a non-empty value on the record (either a standard field or a custom field). `validate_transition()` becomes:

```
validate_transition(definition, from_state, to_state, user_role, record_values)
  -> (allowed: bool, reason: str | None)
```

Booking and CR lifecycles without `required_fields` behave exactly as today (empty set). Backward compatible.

### Seeded default lifecycle templates

Three `lifecycle_template` rows are seeded per tenant with `entity_type='release'` on tenant creation. The first (Major) is `is_default=True`. Admins can fork, rename, or replace.

**Major** — full governance:
`draft → submitted → approved → in_progress → ready_for_release → completed | completed_with_issues | backed_out | rejected | cancelled`.
Terminal: `completed, completed_with_issues, backed_out, rejected, cancelled`.
Test phases (SIT/UAT/Staging) live as `test_phase` rows inside `in_progress`, not as lifecycle states. Seed gates on the template (materialised into `release_gate` on instantiation): `SIT Exit`, `UAT Exit`, `Staging Exit`, `CAB Approval`. `CAB Approval` is a release-level gate (no `test_phase_id`) — passing it is what unblocks the `in_progress → ready_for_release` transition.

**Minor** — light approval:
`draft → approved → in_progress → ready_for_release → completed | completed_with_issues | backed_out | cancelled`.
Test phases and gates left to the template to decide; default template ships with SIT + Staging phases and a single `Staging Exit` gate.

**Emergency** — fast-track:
`draft → approved → in_progress → completed | backed_out | cancelled`. No default gates; RM may add bespoke gates per release.

### Release type scoping via `entity_subtype`

On the release form, the list of applicable custom fields is computed by:

```
applicable = SELECT * FROM custom_field_definition
  WHERE tenant_id = ?
    AND entity_type = 'release'
    AND (entity_subtype IS NULL OR entity_subtype = <release.release_type>)
    AND deleted_at IS NULL
```

This matches the user's requirement that Waterfall, Agile, and AI/ML teams can have different fields.

### What admins configure where

| Concern | Location |
|---|---|
| States + transitions + allowed roles | `lifecycle_template.definition` |
| Which custom field is visible/editable in which state | `lifecycle_template.definition.field_permissions` |
| Required-before-transition per state | `lifecycle_template.definition.field_permissions[state].required_fields` |
| Custom field existence + type + release-type scope | `custom_field_definition` |
| Gate names + acceptance criteria | `release_template.gates` (blueprint) and `release_gate` (instance) |
| Release types (names) | Free strings, no registry table. Admins create a lifecycle template with that name. |

## Release form + detail tabs

Same React component powers create and edit. On create, tabs 2–5 are disabled until the release is persisted (you can't book environments against a release that doesn't exist yet).

### Tab 1 — Main
Identity + standard + custom fields + lifecycle transition controls.

- Header: name, release type, current state chip, owner, target date, actual date, dependency-alert banner when applicable.
- Standard fields panel — editability per `field_permissions[current_state].standard_fields[field].editable_by[]`.
- Custom fields panel — fetched via `GET /api/v1/custom-fields?entity_type=release&entity_subtype=<release_type>`; editability honours `custom_fields[key].editable_by[]`.
- Transition panel — buttons for every `allowed_transitions(current_state, user_role)`. Disabled with tooltip when `required_fields` are empty.
- State-history drawer from the state chip → renders `release_status_history`.
- Event log drawer from an icon on the header → renders `release_event` rows.

**Components:**
- `pages/ReleaseForm.tsx` (outer shell + tabs)
- `components/releases/ReleaseMainTab.tsx`
- `components/releases/LifecycleAwareFieldsPanel.tsx` — **new shared primitive** generic across entity types (reusable by CRs and bookings later)
- `components/releases/TransitionControls.tsx` — reused by the list page's inline state changer

### Tab 2 — Gates & Test Phases
Release plan-of-record. Editable Gantt (phases as rows, gates as diamonds on the phase's timeline) plus a data table below for bulk edits.

- Drag phase bar to shift dates; drag right edge to resize. Gate diamonds click-to-open decision dialog.
- Phases table: name, order, start, end, status. Inline add/edit/reorder/delete. Delete prompts if there are active bookings on that phase.
- Gates table: name, phase (dropdown), acceptance criteria (multiline), status, decided-by/decided-at, decision notes. Pass / Fail / Override actions.

**Components:**
- `components/releases/PhaseGanttEditor.tsx` — extends the Phase 2 read-only Gantt with drag handles via a `readonly: boolean` prop
- `components/releases/PhasesTable.tsx`
- `components/releases/GatesTable.tsx`
- `components/releases/GateDecisionDialog.tsx`

### Tab 3 — Environments
Resource-view Gantt: rows = environments used in this release, bars = bookings coloured by phase.

- "Add environment to phase" button → dialog with phase (radio), environment multi-select, date range (default = phase dates), booking type. Uses existing booking conflict-detection banner.
- Bookings list beneath for accessibility/bulk overview. Columns: env, phase, start, end, type, lifecycle state, conflict status.
- Clicking a Gantt bar opens the existing booking detail modal.

**Components:**
- `components/releases/EnvironmentResourceGantt.tsx`
- `components/releases/AddPhaseBookingDialog.tsx`
- `components/releases/ReleaseBookingsTable.tsx`

### Tab 4 — Linked Requests
Release-manager status rollup.

- Bookings section: env, phase, start, end, booking type, **lifecycle state chip**, owner. Filters: state, phase.
- Change Requests section: title, target count (envs/hosts), change type, scheduled window, **lifecycle state chip**, raised_by. Filters: state. Includes "Link existing CR" dialog (search for CRs with `release_id IS NULL`).

**Components:**
- `components/releases/LinkedBookingsSection.tsx` (reuses `ReleaseBookingsTable.tsx` with column variants)
- `components/releases/LinkedChangeRequestsSection.tsx`
- `components/releases/LinkChangeRequestDialog.tsx`

### Tab 5 — Scope
User stories / defects.

- Table of `release_change` rows: external key (badge), title, kind, external status, system, source.
- "Add scope item" dialog — required: title, kind. Optional: external_key, external_status, system.
- **Editability by source:** rows with `source='manual'` are fully editable. Rows with `source='jira'` are read-only for Jira-owned fields (title, description, external_status, external_key); only the `system` association and local `custom_fields` remain editable. (In sub-project 1 no row has `source='jira'` since the webhook arrives in sub-project 3 — this rule is established now so the UI is ready.)
- Edit inline for manual rows, bulk delete.
- "Group by Epic" toggle — **disabled in sub-project 1** with tooltip "Epic grouping activates when Jira integration is configured".

**Components:**
- `components/releases/ScopeTable.tsx`
- `components/releases/ScopeItemDialog.tsx`

### Cross-cutting UI
- `UnsavedChangesProvider` warns on tab switch or nav.
- Client-side permission checks reuse `useHasRole()` + the field-permissions payload returned by `GET /releases/{id}`. Server remains authoritative.

## List, calendar, timeline

### Release list (`/releases`)
MUI DataGrid with columns: name, type, lifecycle state (chip), target_date, actual_date, target-date variance vs plan, owner, phase count, scope count, blocker count. Filters: type, state (multi), date range, scope contains, has-dependency-alert, owner. Toolbar: **New Release** (dropdown From-Template / Blank), Switch to calendar, Switch to timeline. No bulk actions in this sub-project.

### Release calendar (`/releases/calendar`)
FullCalendar. Events are phases (not whole releases) — gives a realistic "when is something happening" view. Coloured by release type. Click → release detail at `?tab=phases&phase=<id>`.

### Release timeline (`/releases/timeline`)
Multi-release Gantt. Rows = releases (filterable). Bars = phases coloured by state, gate diamonds overlaid. Dependency arrows drawn from `depends_on_release` → `release` for each `release_dependency` row. Dependency alert banner at the top when any shift is unacknowledged.

### Dependency alert banner
- `release_dependency.last_dependency_target_date` captured on create.
- `get_dependency_alerts(release_id)` service method compares current vs. captured target dates and returns `[{depends_on_release_id, depends_on_name, prior_target_date, current_target_date, diff_days}]`.
- Rendered on: release detail Main tab, release list row badge, timeline overlay. Owner dismisses the banner by either updating the dependent release's plan or clicking Acknowledge (updates `last_dependency_target_date` to current).

## Release event log

- Append-only `release_event` rows.
- Viewed via a right-hand drawer opened from the release header icon (keeps the visible tab count at 5).
- `release_event_type` seeded with: `Reschedule Reason`, `Scope Change`, `Stakeholder Note`, `Post-Go-Live Incident`. Admins manage the list in `LifecycleTemplatesPanel`.
- **Automatic** events emitted by the service layer:
  - `target_date` change → `Reschedule Reason` event with before/after (user prompted for reason on commit).
  - Scope item add/remove while state ≥ `approved` → `Scope Change`.
  - Gate fail/override → inline event with decision notes.
- **Manual** events: user picks type from dropdown + writes description.

## Template library

Pages under `/admin/release-templates`:
- List: type, phase count, gate count, last_updated, version.
- Form: metadata (name, type, default_lifecycle_template_id); phases editor (ordered list with name, default_duration_days, activities as JSONB checklist items); gates editor (name, parent phase or release-level, acceptance_criteria markdown).
- Save increments `version`.
- **"Create release from template"** action: `POST /api/v1/release-templates/{id}/instantiate`:
  1. Create `release` tied to template's `default_lifecycle_template_id` (or tenant default).
  2. Materialise each template phase into `test_phase`; dates computed as relative offsets from `target_date` walking backward using `default_duration_days`.
  3. Materialise each gate into `release_gate` attached to the right phase.
  4. Return the new release; form opens on edit view.

## API surface

Under `backend/app/api/v1/`:

### `releases.py`
- `GET /releases` — list with filters + pagination
- `POST /releases` — create (from scratch or from-template via payload flag)
- `GET /releases/{id}` — detail; payload includes field-permissions for the current state/role to drive client-side disabling
- `PUT /releases/{id}` — update
- `DELETE /releases/{id}` — soft delete
- `POST /releases/{id}/transition` — `{to_state, notes}`; validates role + required_fields; writes `release_status_history`; publishes `ReleaseStateChanged`
- Phases: `GET /releases/{id}/phases`, `POST /releases/{id}/phases`, `PUT /phases/{phase_id}`, `DELETE /phases/{phase_id}`
- Gates: `GET /releases/{id}/gates`, `POST /releases/{id}/gates`, `PUT /gates/{gate_id}`, `POST /gates/{gate_id}/pass`, `POST /gates/{gate_id}/fail`, `POST /gates/{gate_id}/override`
- Systems: `GET /releases/{id}/systems`, `POST /releases/{id}/systems`, `DELETE /release-systems/{id}`
- Dependencies: `GET /releases/{id}/dependencies`, `POST /releases/{id}/dependencies`, `DELETE /release-dependencies/{id}`, `GET /releases/{id}/dependency-alerts`, `POST /releases/{id}/dependency-alerts/{dep_id}/acknowledge`
- Bookings: `GET /releases/{id}/bookings`, `POST /releases/{id}/bookings`
- Linked CRs: `GET /releases/{id}/change-requests`, `POST /releases/{id}/change-requests/{cr_id}/link`, `DELETE /releases/{id}/change-requests/{cr_id}/link`
- Scope: `GET /releases/{id}/changes`, `POST /releases/{id}/changes`, `PUT /release-changes/{change_id}`, `DELETE /release-changes/{change_id}`
- Events: `GET /releases/{id}/events`, `POST /releases/{id}/events`
- Aggregates: `GET /releases/calendar?from&to`, `GET /releases/timeline?from&to`

### `release_templates.py`
- CRUD on `/release-templates` + `POST /release-templates/{id}/instantiate`

### `release_event_types.py`
- Admin CRUD

## Backend services

Under `backend/app/services/`:
- `release_service.py` — CRUD, transition, list filters, calendar/timeline projections
- `release_template_service.py` — CRUD + `instantiate(template_id, overrides)`
- `release_booking_service.py` — wraps `booking_service`; handles `context_tag` derivation
- `release_gate_service.py` — pass/fail/override with event emission
- `release_scope_service.py` — `release_change` CRUD; sub-project 3 adds `apply_jira_webhook(...)` alongside
- `release_dependency_service.py` — dependency graph + alert computation
- `release_event_service.py` — event + event_type CRUD

All services respect the outbox pattern (publish_event inside the transaction, never `db.commit()` inside a service).

## Booking + CR integration detail

### Booking context tag derivation
On booking create / update:
1. Look up `release_system` rows for `booking.release_id`.
2. Walk `booking.environment → environment_subsystem → system` to find the matching `release_system`.
3. Set `booking.context_tag = release_system.role` if matched.
4. If no match, leave `context_tag = none` and surface an amber "unmapped" badge on the booking row.

### Change request linkage
`change_request.release_id` already exists as a nullable int in Phase 2. Promote to FK (`ondelete='SET NULL'`). Linking a CR to a release is done via the Tab 4 "Link existing CR" dialog; the backend sets `cr.release_id` after authorising the caller has edit rights on both records.

## Events published

All via the existing outbox pattern:
- `ReleaseCreated`, `ReleaseUpdated`, `ReleaseStateChanged`
- `ReleasePhaseAdded/Updated/Removed`
- `ReleaseGatePassed/Failed/Overridden`
- `ReleaseChangeRequestLinked/Unlinked`
- `ReleaseDependencyDateShifted` — fires when a dependency's `target_date` changes; consumers deferred with the cross-cutting notification work
- `ReleaseScopeItemAdded/Updated/Removed`
- `ReleaseEventRecorded`

No new event for release-linked bookings — the existing `BookingCreated/Updated` events already carry `release_id` in their payload.

## Migration plan

Single Alembic migration file per convention, manually authored (no `--autogenerate`), executed in this order:

1. Create tables: `release_template`, `release`, `release_status_history`, `test_phase`, `release_gate`, `release_system`, `release_dependency`, `release_event_type`, `release_event`, `release_change`.
2. `ALTER TABLE booking` — add real FK constraints on `release_id` → `release.id` and `test_phase_id` → `test_phase.id`.
3. `ALTER TABLE change_request` — add real FK on `release_id` → `release.id`.
4. `ALTER TABLE custom_field_definition` — add `entity_subtype` column.
5. Data migration: seed three default `lifecycle_template` rows for every existing tenant (`entity_type='release'`, Major/Minor/Emergency).
6. Data migration: seed default `release_event_type` rows for every existing tenant.
7. Register `release` entry in `ENTITY_FIELD_SPECS`.

Tenant creation (in the auth/tenant service) gets the same seed logic so new tenants ship with release lifecycles + event types ready.

## Testing

### Backend
- Service-layer pytest suites per new service. Target: 268+N green bar.
- API integration tests per endpoint group.
- One **happy-path-from-template** test: instantiate → add bookings → transition through all states → pass gates → reach `completed`. Guards integration gaps.
- **Tenant isolation probe** per new table — creates rows in tenant A, asserts tenant B can't read them.
- `required_fields` transition validation tested with a field that's empty (block) and filled (allow).
- `entity_subtype` scoping: custom field defined for `Major` not shown for `Minor` release.

### Frontend
- No frontend unit tests (defers with the Tier-3 modernisation rollup already agreed).
- `npm run build` + lint clean.
- Manual smoke pass against the happy path above.

## Acceptance criteria

- A release can be created from a template; phases and gates are materialised correctly with sensible default dates.
- A release can be created from scratch and phases + gates added/edited via the Gates & Test Phases tab; changes render on the plan Gantt.
- Multiple environments can be booked against a single phase via Tab 3; each booking gets `release_id` + `test_phase_id` + derived `context_tag`.
- Standard and custom fields on the Main tab honour per-state editability from `lifecycle_template.definition.field_permissions`.
- A transition is blocked when a destination-state `required_fields` entry is empty; UI shows the blocked-reason tooltip.
- Custom fields defined with `entity_subtype = <release_type>` are only shown on releases of that type.
- Release types (Major / Minor / Emergency) seed default lifecycle templates on tenant creation; a tenant can fork and rename to get Waterfall / Agile / AI-ML lifecycles with no code change.
- Gates can be passed, failed, or overridden; decisions write `decided_by` + `decided_at` + `decision_notes` and emit a `release_event` automatically.
- Linked Requests tab lists all bookings + CRs for the release with lifecycle state chips; the RM can link an unassigned CR.
- Dependency alert banner renders on the Main tab, list row, and timeline when a dependency's `target_date` has shifted vs. `last_dependency_target_date`; Acknowledge updates the stored baseline.
- Release event log records automatic events (reschedule, scope change, gate decision) and supports manual entries with tenant-configurable event types.
- Release list, calendar, and timeline views render correctly with filters and dependency overlays.
- Tenant isolation verified: every new-table query filters by `tenant_id`; no cross-tenant reads.
- All service methods have unit tests; all API endpoints have integration tests.

## Out of scope (reminder)

- Enterprise Releases (`parent_release_id` UI, admission flow, combined timelines) → sub-project 2.
- Jira `JiraProjectConfig`, field-mapping editor, `JiraEpic`, webhook receiver, Epic pages → sub-project 3.
- `PostImplementationReview`, `Incident` linkage → Phase 5.
- Cross-cutting notification consumer → deferred carry-over.
- `deployments: []` population on `/environments/{id}/schedule` → Phase 4.
