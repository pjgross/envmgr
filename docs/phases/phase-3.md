# Phase 3: Releases & Test Phases

> Status: ✅ **Sub-project 1 merged to `main`** (MR !4, merge commit `8f154bd`, 2026-04-20) | Roadmap: [../plan.md](../plan.md)
> Duration: 4–6 weeks | Sub-project 1 complete; sub-projects 2 & 3 + Phase 5 items deferred

## Sub-project 1 — Core Releases ✅ Merged

Delivered on `main` via MR !4 on 2026-04-20 (merge commit `8f154bd`).

| Artefact | Path |
|----------|------|
| Spec | `docs/superpowers/specs/2026-04-19-phase-3-core-releases-design.md` |
| Plan | `docs/superpowers/plans/2026-04-19-phase-3-core-releases.md` |
| Smoke checklist | `docs/phases/phase-3-sub1-smoke-checklist.md` |
| Happy-path test | `backend/tests/integration/test_release_happy_path.py` |

**Delivered in MR !4**: Release Template Library, Release CRUD, TestPhase + ReleaseGate + ReleaseSystem + ReleaseEvent + ReleaseChange models, full lifecycle transitions, release-booking linking with context_tag derivation, calendar and Gantt timeline views, frontend release list / form / detail (Main / Phases / Gates / Systems / Bookings / Scope / Events tabs), admin lifecycle + event-type management pages.

### Sub-project 1 follow-ups (same delivery window)

| MR | Commit | Summary |
|----|--------|---------|
| !5 | `8327f36` | Lifecycle permissions unified: `ReleaseRead` now carries `custom_field_permissions` + `standard_field_permissions` in the same shape as `BookingResponse`; shared `lifecycle_service.get_field_permissions_for_state` core. |
| !6 | `906ddef` | Gate criteria: `gate_criterion` table 1:N under `release_gate`; criteria have due_date, assigned_to, notes; gate auto-passes (one-way) when all criteria are `done`; per-release `overdue_criterion_count` exposed on list endpoint; drops `release_gate.acceptance_criteria` column. |
| !7 | `8f49c48` | Frontend MUI confirm sweep: new `useConfirm` hook + `ConfirmDialog` component replace 12 native `confirm()` + 4 `alert()` call sites. |
| !8 | `2031a76` | Hotfix: committed the `ConfirmDialog` + `useConfirm` files that were referenced by !7 but originally uncommitted. |
| !9 | `9c897c5` | Docs refresh: Phase 3 status flipped to merged across CLAUDE.md / plan.md / phase-3.md / requirements.md; GEMINI.md marked as historical. |
| !10 | `47cce5a` | Scope item custom fields: `release_change` joins the custom-field entity types; fields can be unscoped (apply to every `change_kind`) or scoped to one (`story`/`defect`/`task`/`spike`); validation + admin UI + `ScopeItemDialog` integration. Spec: `docs/superpowers/specs/2026-04-21-scope-custom-fields-design.md`. |
| !12 | `35e3a99` | Scope-item lifecycle: `release_id` nullable (items can sit in a backlog); new `release_change_release_history` + `release_change_status_history` + `scope_change_kind_rule` tables; `POST /release-changes/{id}/move` endpoint; jira-sourced items are read-only for moves; release soft-delete drops items to backlog with audit history; symmetric `scope_additions/removals/change_count` on release list gated by per-tenant kind rules (default: only `story` counts). Frontend: Move dialog, Backlog tab, History drawer, admin rules page. Plan: `~/.claude/plans/one-of-the-things-swirling-manatee.md`. |

Spec + plan for these follow-ups live under `docs/superpowers/specs/` and `docs/superpowers/plans/` with dates `2026-04-20` and `2026-04-21`.

**Deferred to sub-projects 2/3 and Phase 5**: Enterprise Releases (release trains), Jira Integration, Post-Implementation Reviews (PIR). These remain as planned tasks in this file and in Phase 5.

---

## Objectives

- Release Template Library — reusable templates with predefined phases, gates, and activities
- Project Releases with configurable types (Major, Minor, Emergency) and per-type state workflows
- Enterprise Releases (release trains) grouping multiple Project Releases
- Release lifecycle: phases, gates, activities, exit criteria
- System roles on a release (changing / regression / config_only) with optional deployment dates
- Release dependencies with date-impact alerts
- Release event log (audit trail: reschedule reasons, scope changes, etc.)
- Jira integration — import user stories and defects as release scope via webhooks
- Link bookings to release test phases (with auto-derived context tag)
- Post-Implementation Reviews (PIR)
- Release views: calendar + Gantt/schedule timeline

---

## Backend Tasks

### Data Models & Migrations

- [ ] `ReleaseTemplate` model (`backend/app/db/models/release_template.py`)
  - Fields: `name`, `description`, `release_type` (Major | Minor | Emergency | custom), `phases` (JSONB — predefined phase definitions), `gates` (JSONB), `activities` (JSONB), `version` (integer counter; incremented on each update — not a history table), `tenant_id`, `deleted_at`

- [ ] `Release` model (`backend/app/db/models/release.py`)
  - Fields: `name`, `description`, `release_type`, `release_kind` (project | enterprise), `parent_release_id` (nullable FK — for Enterprise Release membership), `template_id` (nullable FK), `status`, `lifecycle_id` (FK → `LifecycleDefinition` — same model as Phase 2; entity_type = `release`), `target_date`, `actual_date`, `tenant_id`, `deleted_at`

- [ ] Seed default `LifecycleDefinition` records (entity_type = `release`) for:
  - **Major**: `draft → submitted → approved → in_progress → sit → uat → staging → cab → deploying → deployed | rejected | cancelled`
  - **Minor**: `draft → approved → in_progress → sit → staging → deploying → deployed | cancelled`
  - **Emergency**: `draft → approved → deploying → deployed | cancelled` (fast-track — minimal gates)
  - Note: state names are examples; tenant admins can customize via the Lifecycle API

- [ ] `TestPhase` model (`backend/app/db/models/test_phase.py`)
  - Fields: `release_id`, `name` (SIT | UAT | Staging | custom), `start_date`, `end_date`, `status`, `order`, `tenant_id`

- [ ] `ReleaseGate` model — gate checkpoints between phases with pass/fail/override status

- [ ] `ReleaseSystem` model — junction: release ↔ system with role (`changing | regression | config_only`) and optional `deployment_date`

- [ ] `ReleaseChange` model — Jira user story or defect linked to a release (scope item); fields: `jira_key`, `title`, `type` (story | defect), `status`, `system_id` (optional), `release_id`, `tenant_id`

- [ ] `ReleaseDependency` model — `release_id` depends on `depends_on_release_id` (must deploy after)

- [ ] `ReleaseEvent` model — configurable event log entries on a release; fields: `release_id`, `event_type` (configurable), `description`, `occurred_at`, `recorded_by`, `tenant_id`

- [ ] `ReleaseEventType` model — configurable event type definitions (Reschedule Reason, Scope Change, Post-Go-Live Incident, etc.)

- [ ] `PostImplementationReview` (PIR) model — `release_id` (the release being reviewed), `incident_id` (nullable FK → Incident — the incident that triggered this PIR), `root_cause`, `action_plan`, `lessons_learned`, `status` (open | closed), `tenant_id`
  - PIR ↔ Incident is bidirectional: PIR holds `incident_id`; `GET /api/v1/incidents/{id}` resolves the PIR by querying `WHERE incident_id = ?`
  - `action_plan` documents how the fix will be delivered; problem managers reference `Incident.fix_release_id` (set separately on the Incident) to communicate the release that will implement the action plan

- [ ] Alembic migrations for all new tables

### Jira Integration

#### Data Models
- [ ] `JiraProjectConfig` model (`backend/app/db/models/jira_project_config.py`)
  - Fields: `jira_project_key`, `jira_project_name`, `jira_base_url`, `webhook_secret`, `credentials` (JSONB — encrypted API key / OAuth token), `field_mappings` (JSONB array), `copied_from_project_id` (nullable FK — audit trail only), `tenant_id`, `deleted_at`
  - `field_mappings` item shape: `{jira_field_path: str, display_name: str, envmgr_field_key: str, field_type: str}`

- [ ] `JiraEpic` model (`backend/app/db/models/jira_epic.py`)
  - Fields: `jira_key`, `title`, `description`, `jira_status`, `jira_project_config_id` (FK), `custom_fields` (JSONB), `tenant_id`, `deleted_at`

- [ ] Modify `ReleaseChange` model — add:
  - `epic_id` (nullable FK → `JiraEpic`)
  - `custom_fields` (JSONB — field-mapped values from Jira payload)
  - `jira_project_config_id` (FK → `JiraProjectConfig`)

#### Service Layer
- [ ] `JiraProjectConfigService` (`backend/app/services/jira_project_config_service.py`)
  - `create_config(tenant_id, data)`
  - `copy_from_project(source_config_id, overrides)` — deep-copies `field_mappings` into a new `JiraProjectConfig`; `copied_from_project_id` is set for audit
  - `update_field_mappings(config_id, mappings)`
  - `preview_mapping(config_id, sample_payload)` — applies `field_mappings` to a sample payload and returns the mapped result (no DB write)

- [ ] `JiraWebhookService` (`backend/app/services/jira_webhook_service.py`)
  - `verify_signature(payload_bytes, signature_header, webhook_secret)` — HMAC-SHA256 verification
  - `resolve_config(project_key, tenant_id)` → `JiraProjectConfig`
  - `apply_field_mappings(payload, field_mappings)` → `dict` of mapped custom fields
  - `handle_epic(payload, config)` — upsert `JiraEpic`; apply field mappings
  - `handle_issue(payload, config)` — upsert `ReleaseChange`:
    - Resolve `release_id` from `fixVersion` field matched against `Release.name`
    - Resolve `epic_id` from `fields.parent.key` (next-gen) or `fields.customfield_epic_link` (classic)
    - Apply field mappings to populate `custom_fields`
  - `dispatch(payload, tenant_id)` — entry point; routes to `handle_epic` or `handle_issue`

- [ ] `EpicService` (`backend/app/services/epic_service.py`)
  - `list_epics(tenant_id, filters)` — filter by project, status, release
  - `get_epic_with_stories(epic_id, tenant_id)` — Epic + all ReleaseChange records grouped by release
  - `get_epic_release_span(epic_id, tenant_id)` — returns distinct releases that contain stories from this Epic (derived query: `SELECT DISTINCT release_id FROM release_change WHERE epic_id = ?`)

#### API Endpoints
- [ ] `backend/app/api/v1/jira_projects.py`
  - `GET /api/v1/jira/projects` — list configured Jira projects
  - `POST /api/v1/jira/projects` — create new project config
  - `GET /api/v1/jira/projects/{id}` — get config details
  - `PUT /api/v1/jira/projects/{id}` — update config
  - `DELETE /api/v1/jira/projects/{id}` — soft delete
  - `POST /api/v1/jira/projects/{id}/copy-from/{source_id}` — clone field mappings from source project
  - `GET /api/v1/jira/projects/{id}/field-mappings` — view field mapping rules
  - `PUT /api/v1/jira/projects/{id}/field-mappings` — replace field mapping rules
  - `POST /api/v1/jira/projects/{id}/test-mapping` — body: sample Jira payload JSON; returns preview of mapped fields

- [ ] `backend/app/api/v1/webhooks/jira.py`
  - `POST /api/v1/webhooks/jira` — inbound Jira webhook; verifies signature; dispatches to `JiraWebhookService`

- [ ] `backend/app/api/v1/epics.py`
  - `GET /api/v1/epics` — list Epics (filter by project, status)
  - `GET /api/v1/epics/{id}` — Epic detail with stories grouped by release
  - `GET /api/v1/epics/{id}/releases` — derived release span for this Epic

### Service Layer

- [ ] `ReleaseTemplateService` — CRUD for template library; `create_release_from_template(template_id, overrides)`
- [ ] `ReleaseService`
  - `create_release(tenant_id, data)` — from template or from scratch
  - `create_enterprise_release(tenant_id, data)` — creates parent Enterprise Release
  - `add_project_to_enterprise(enterprise_id, project_release_id)` — admit project release
  - `transition_status(release_id, new_status)` — validate against lifecycle
  - `pass_gate(gate_id)` / `fail_gate(gate_id, reason)` / `override_gate(gate_id, reason)`
  - `set_system_role(release_id, system_id, role, deployment_date=None)`
  - `get_dependency_alert(release_id)` — check if any dependency's dates impact this release
  - `list_releases(tenant_id, filters)` — type, status, date range, enterprise/project
- [ ] `ReleaseChangeService` — create/update/delete scope items; bulk import from Jira
- [ ] `ReleaseEventService` — record and list release events
- [ ] `PIRService` — create and manage post-implementation reviews

### API Endpoints

- [ ] `backend/app/api/v1/release_templates.py` — CRUD for template library
- [ ] `backend/app/api/v1/releases.py`
  - Full CRUD + `GET /api/v1/releases/{id}/phases`
  - `POST /api/v1/releases/{id}/phases` — add test phase
  - `GET /api/v1/releases/{id}/systems` — systems with roles
  - `POST /api/v1/releases/{id}/systems` — add/update system role
  - `GET /api/v1/releases/{id}/changes` — Jira scope items
  - `GET /api/v1/releases/{id}/dependencies`
  - `POST /api/v1/releases/{id}/dependencies`
  - `GET /api/v1/releases/{id}/events`
  - `POST /api/v1/releases/{id}/events`
  - `GET /api/v1/releases/{id}/pir`
  - `POST /api/v1/releases/{id}/pir`
  - `POST /api/v1/releases/{id}/admit/{project_release_id}` — admit into enterprise release
  - `GET /api/v1/releases/calendar` — all releases for calendar view (date range)
  - `GET /api/v1/releases/timeline` — all releases for Gantt/schedule view
- [ ] `backend/app/api/v1/gates.py` — gate pass / fail / override endpoints
- [ ] `backend/app/api/v1/webhooks/jira.py` — Jira webhook receiver

### Events

- [ ] Events: `ReleaseCreated`, `ReleaseStatusChanged`, `GatePassed`, `GateFailed`, `JiraImportCompleted`, `PIRCreated`
- [ ] Notification consumers for release events (gate failures, dependency alerts)

---

## Frontend Tasks

### Services & State

- [ ] `frontend/src/services/releaseService.ts`
- [ ] `frontend/src/services/releaseTemplateService.ts`
- [ ] `frontend/src/services/jiraProjectService.ts` — project config + field mapping API calls
- [ ] `frontend/src/services/epicService.ts` — Epic list, detail, release span
- [ ] `frontend/src/store/releaseSlice.ts`
- [ ] `frontend/src/store/epicSlice.ts`
- [ ] `frontend/src/types/release.ts` — `Release`, `ReleaseKind`, `ReleaseType`, `TestPhase`, `ReleaseGate`, `ReleaseSystem`, `SystemRole`, `ReleaseChange`, `ReleaseDependency`, `ReleaseEvent`, `PIR`
- [ ] `frontend/src/types/jira.ts` — `JiraProjectConfig`, `FieldMapping`, `JiraEpic`

### Pages & Components

- [ ] `frontend/src/pages/ReleaseTemplateLibrary.tsx` — browse and manage templates
- [ ] `frontend/src/pages/ReleaseList.tsx` — list with filters; toggle Enterprise / Project view
- [ ] `frontend/src/pages/ReleaseForm.tsx` — create release from template or scratch; select type (Major/Minor/Emergency); set parent Enterprise Release
- [ ] `frontend/src/pages/ReleaseDetail.tsx` — tabbed detail view:
  - **Overview**: status, type, lifecycle progress, dependency alerts
  - **Systems**: add/edit system roles and deployment dates
  - **Scope**: Jira stories/defects grouped under their parent Epic as a collapsible header; Epics with no stories on this release are hidden
  - **Phases & Gates**: phase timeline with gate pass/fail actions
  - **Bookings**: linked environment bookings with context tags
  - **Events**: release event log
  - **PIR**: post-implementation review
- [ ] `frontend/src/components/ReleaseCalendar.tsx` — calendar view of releases and their phases
- [ ] `frontend/src/components/ReleaseGantt.tsx` — Gantt/schedule timeline showing phase durations and gates across multiple releases
- [ ] `frontend/src/components/EnterpriseReleaseView.tsx` — shows member project releases, admission status, and combined timeline
- [ ] `frontend/src/components/DependencyAlertBanner.tsx` — shows smart alerts when dependency dates have changed
- [ ] `frontend/src/pages/JiraIntegrationConfig.tsx` — admin page: list configured Jira projects, add/edit/delete, "copy from" dropdown to clone an existing project's field mappings
- [ ] `frontend/src/components/FieldMappingEditor.tsx` — table of mapping rows (Jira field path | Display name | EnvManager field key | Type); "Test mapping" panel — paste sample payload, see preview of extracted values
- [ ] `frontend/src/pages/EpicList.tsx` — searchable list of Epics; columns: key, title, status, release count (how many releases contain its stories)
- [ ] `frontend/src/pages/EpicDetail.tsx` — Epic detail: description, Jira status, custom fields; stories grouped by release with release name and status; cross-release timeline strip showing which releases the Epic spans

---

## Acceptance Criteria

- [ ] A Release can be created from a template; all predefined phases, gates, and activities are copied
- [ ] Enterprise Release can admit Project Releases; timeline shows all members
- [ ] System roles on a release correctly drive the `context_tag` on linked bookings (deployment vs regression)
- [ ] Jira webhook correctly creates ReleaseChange records when issues are linked to a Jira version; custom fields populated via field mappings
- [ ] Jira webhook for an Epic creates/updates a `JiraEpic` record
- [ ] Stories are linked to their parent Epic via `epic_id`; Epic-to-release span derived correctly
- [ ] `copy_from_project` creates an independent copy of field mappings; changes to source don't affect the copy
- [ ] `POST /api/v1/jira/projects/{id}/test-mapping` with a sample payload returns the mapped field preview correctly
- [ ] Scope tab on ReleaseDetail groups stories under Epic headers
- [ ] Gate pass/fail/override transitions are validated; failed gates block phase promotion
- [ ] Dependency alerts appear when a linked release's target date changes
- [ ] Release calendar and Gantt views render correctly with phase data
- [ ] PIR can be created and linked to incidents; PIR completion can gate release closure
- [ ] Release lifecycle transitions are validated against the `LifecycleDefinition` (entity_type = `release`); default Major/Minor/Emergency lifecycles are seeded on tenant creation
- [ ] CAB (Change Advisory Board) approval is implemented as a named Release Gate — no separate CAB model is needed
- [ ] All service methods have unit tests; all API endpoints have integration tests
- [ ] Tenant isolation verified: all new table queries filter by `tenant_id`; release data from one tenant is never visible to another
