# Enterprise Releases — Design

**Date:** 2026-04-22
**Status:** Awaiting user review — ready for implementation planning after approval
**Related plan:** (to be created) `docs/superpowers/plans/2026-04-22-enterprise-releases.md`
**Phase:** 3 Sub-project 2

## Problem

A Release Manager coordinating a multi-team deployment window today has to treat every team's Project Release as an island. There is no system-supported way to:

- Group several Project Releases under a single coordination umbrella ("release train").
- Run integration testing across the grouped work on its own phases, gates, and bookings.
- Track every child's lifecycle state at a glance while deciding whether to progress the train.
- Accept/reject projects into the window via an auditable workflow, with permissions that mirror the rest of the lifecycle editing model.
- Mark late admissions as "late scope" after a configurable cutoff — for audit, not enforcement.
- Produce a single release report listing every Jira ticket and every system impacted across the train.

`release.release_kind` and `release.parent_release_id` were scaffolded in MR !4 but nothing consumes them. This spec makes Enterprise Releases a first-class, coordination-focused sibling of Project Releases.

## Scope

In scope:
- `release_kind='enterprise'` releases carry their **own** lifecycle, phases, gates (with criteria), bookings, events, custom fields.
- Admission workflow via a new `release_membership` table: `pending_request → accepted / rejected / withdrawn`; `accepted → removed`.
- Configurable "admission lockdown" marker per enterprise lifecycle state; late admissions get `late_scope=true` tagged at decision time but are **not** blocked.
- Permission matrix (state × role) for `membership.admit`, `membership.reject`, `membership.remove` — extends the existing JSON lifecycle definition with a new `action_permissions` block alongside the existing `field_permissions`.
- **Rollup views** on the enterprise: Systems Impacted (union of children's `release_system`), Scope (union of children's `release_change`), Member States, Combined Timeline.
- **Release report**: rendered HTML-only view of the enterprise at a point in time.
- Dependencies remain project→project only, independent of enterprise membership. Enterprise timeline still draws child-to-child dependency arrows.
- Frontend: kind-aware list filter, kind-aware detail page tabs, member admission UI, admin lifecycle editor extension for new permission keys + lockdown marker.

Explicitly out of scope (YAGNI):
- Multi-parenting (one enterprise per project, enforced).
- Enterprise-level dependencies as a first-class entity.
- Hard gates that block a child's deployment based on enterprise state. Coordination is advisory.
- Auto-transition of enterprise status based on children's states. RM transitions manually.
- PDF export. HTML report only. Markdown download deferred.
- Enterprise-owned scope items (stories that "live on the train" independent of a child).
- Enterprise-owned systems rows. Systems are derived from children.
- Jira webhook (Sub-project 3).
- PIR (Phase 5).

## Data model

### New table: `release_membership`

Stores the admission workflow as an audit log. `release.parent_release_id` remains the source of truth for **currently active** membership; `release_membership` records every request and decision for audit.

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | `bigserial` PK | no | |
| `tenant_id` | `FK tenant.id` | no | indexed |
| `enterprise_release_id` | `FK release.id` | no | service layer asserts `release_kind='enterprise'` |
| `project_release_id` | `FK release.id` | no | service layer asserts `release_kind='project'` |
| `state` | `varchar(30)` | no | `pending_request`, `accepted`, `rejected`, `withdrawn`, `removed` |
| `requested_by` | `FK user.id` | no | |
| `requested_at` | `timestamptz` | no | |
| `decided_by` | `FK user.id` | yes | user who accepted/rejected |
| `decided_at` | `timestamptz` | yes | |
| `removed_by` | `FK user.id` | yes | |
| `removed_at` | `timestamptz` | yes | |
| `removal_reason` | `text` | yes | |
| `late_scope` | `bool` | no, default `false` | computed at decision time; sticky |
| `notes` | `text` | yes | used on reject/withdraw |

Indexes:
- `(enterprise_release_id, state)`
- `(project_release_id, state)` — enforce "one `pending_request` per project" and "at most one `accepted` per project" via partial unique indexes:
  - `UNIQUE (project_release_id) WHERE state = 'pending_request'`
  - `UNIQUE (project_release_id) WHERE state = 'accepted'`

Transition rules (service-enforced, tested):
- `pending_request` → `accepted` | `rejected` | `withdrawn`
- `accepted` → `removed`
- `rejected`, `withdrawn`, `removed` are terminal (re-request creates a **new** row)

Behaviour on `accept`:
1. Check permission: requesting user has `membership.admit` in enterprise's **current lifecycle state**.
2. Check: project has no other `accepted` membership row (partial unique index enforces at DB level too).
3. Set `release.parent_release_id = enterprise.id` on the child.
4. Set `late_scope = true` if the enterprise's current state position is at-or-past the lockdown state in the lifecycle definition's ordered state list.
5. Write the row; emit `EnterpriseMembershipAccepted`.

Behaviour on `remove`:
1. Permission: `membership.remove` in enterprise's current state.
2. Null out child's `parent_release_id`.
3. Update row: `state='removed'`, `removed_by`, `removed_at`, `removal_reason`.
4. Emit `EnterpriseMembershipRemoved`.

### Extension: `LifecycleTemplate` (one new column) + `LifecycleDefinition` JSON shape

`LifecycleTemplate` today has no sub-discriminator beyond `entity_type`. Enterprise and Project releases both have `entity_type='release'`, so we add:

- New column `applies_to_kind: varchar(20) NULL` on `lifecycle_template`. Values: `'project'`, `'enterprise'`, or `NULL` (applies to either). The release-form kind picker filters templates by this column.

The state-machine structure lives in `LifecycleTemplate.definition` (JSON). Two additions to that JSON shape:

1. **`LifecycleState.is_admission_lockdown: bool = False`** — new optional field on each state entry. Service-level invariant: at most one state in a given template may have `is_admission_lockdown=true`. Only meaningful on templates with `applies_to_kind='enterprise'`.

2. **`LifecycleDefinition.action_permissions: dict[state_key, dict[action_key, list[role]]]`** — new top-level key. Mirrors `field_permissions` in shape (keyed by state_key) but expresses "which roles can perform action X while the entity is in state Y". Recognized `action_key` values for enterprise releases:
   - `membership.admit`
   - `membership.reject`
   - `membership.remove`

   `action_permissions` is optional overall and optional per-state. Missing entries mean the action is **denied** in that state. (Fail-closed matches field permissions behaviour.)

Pydantic schemas in `booking_lifecycle.py` get the new field + new dict; `validate_definition_for_entity` gets a new branch for enterprise-kind validation (single lockdown state, recognized action keys only). `migrate_field_permissions` is unaffected.

Seed the default enterprise lifecycle template with: Release Manager + Admin granted all three actions in every non-terminal state.

### Seed: default Enterprise lifecycle template

One `LifecycleTemplate` row (idempotent seed script, per-tenant on tenant creation):

- `name`: "Enterprise Release — default"
- `entity_type`: `release`
- `applies_to_kind`: `enterprise`
- `is_default`: `true`
- `definition.states` (list order is state order):
  - `draft` (initial) → `planning` → `admission_open` → **`admission_closed`** → `integration_testing` → `uat` → `staging` → `cab` → `deploying` → `deployed` (terminal)
  - `cancelled` (terminal)
- `definition.transitions`: linear chain + `* → cancelled` with `allowed_roles=['Admin','Release Manager']`.
- `definition.states[admission_closed].is_admission_lockdown = true`.
- `definition.action_permissions`: for every non-terminal state, `{admit,reject,remove}: ['Admin','Release Manager']`.

Project-release lifecycle templates remain untouched.

### No changes to

- `release_change`, `release_system`, `release_dependency`, `release_gate`, `gate_criterion`, `test_phase`, `release_event`, `release_event_type`, `release_status_history`, `booking`.

Enterprise releases use all of the above as-is: they are `release` rows, so they join to these tables via `release_id` just like project releases do.

## Service layer

### `enterprise_membership_service.py`

- `request_membership(user, enterprise_id, project_release_id, notes=None) -> ReleaseMembership`
  - Validates tenant match between enterprise and project.
  - Validates `enterprise.release_kind='enterprise'`, `project.release_kind='project'`.
  - Validates no existing `pending_request` or `accepted` row for this `project_release_id`.
  - Permission: any tenant member on the project release can request — no lifecycle-state gate on request itself. (Accept/reject/remove are the gated actions.)
- `accept(user, membership_id) -> ReleaseMembership`
  - Permission: `membership.admit` on enterprise current state × user role.
  - Re-checks partial unique index constraints.
  - Computes `late_scope` — see below.
  - Sets `release.parent_release_id` on child.
- `reject(user, membership_id, notes) -> ReleaseMembership` — permission `membership.reject`.
- `withdraw(user, membership_id) -> ReleaseMembership`
  - Allowed only by `requested_by` user, or by anyone with Admin role in tenant.
- `remove(user, membership_id, reason) -> ReleaseMembership` — permission `membership.remove`. Nulls child FK.
- `list_memberships(enterprise_id, states: list[str] | None)` — for the Members tab.

**Late-scope computation** (called inside `accept`):

```python
def _compute_late_scope(enterprise: Release, template: LifecycleTemplate) -> bool:
    states = template.definition["states"]  # ordered list
    lockdown_idx = next(
        (i for i, s in enumerate(states) if s.get("is_admission_lockdown")),
        None,
    )
    if lockdown_idx is None:
        return False
    current_idx = next(
        (i for i, s in enumerate(states) if s["key"] == enterprise.status),
        -1,
    )
    return current_idx >= lockdown_idx
```

State order is list-position in the JSON definition — there is no separate `order` column. Once stored on the membership row, `late_scope` is **not** recomputed. Editing the lockdown marker later does not rewrite history.

### `enterprise_rollup_service.py`

- `systems_rollup(enterprise_id) -> list[SystemRollupRead]`
  - Query: for all children with `state='accepted'`, join `release_system` by `release_id`, group by `system_id`, aggregate `{role: count}` and the list of contributing projects.
- `scope_rollup(enterprise_id, filters) -> list[ReleaseChangeRead]`
  - All `release_change` rows for accepted children (respects existing `release_change` visibility / soft-delete).
  - Filter keys: `change_kind`, `status`, `project_release_id`, `system_id`, `jira_key` search.
- `timeline_rollup(enterprise_id) -> TimelineRead`
  - Enterprise phases + each accepted child's phases, each child's status, dependency edges between accepted children.
- `member_state_summary(enterprise_id) -> list[{state: str, count: int, projects: [name]}]`
  - Grouping for the "X/Y children in state Z" helper on gate criteria.

All queries filter by `tenant_id` via the `release` join.

### `enterprise_report_service.py`

- `generate_report(enterprise_id, user) -> EnterpriseReportRead`
  - Composed dict of: enterprise header (name, status, target_date, actual_date, description), members (project name, kind, status, admitted_at, late_scope, decision_by), systems rollup, scope rollup grouped by project, enterprise events, notable child transitions (last 20 per child from `release_status_history`), dependency edges.
  - Emits `EnterpriseReportGenerated` event with `{enterprise_id, generated_by, generated_at}`.
  - No PDF, no markdown. HTML is rendered on the client from this JSON payload (see Frontend).

## API endpoints

All new endpoints enforce tenant scope via `current_user.active_tenant_id`.

### Membership

- `POST   /api/v1/releases/{enterprise_id}/memberships` — body `{project_release_id, notes?}`
- `GET    /api/v1/releases/{enterprise_id}/memberships?states=pending_request,accepted,...`
- `POST   /api/v1/releases/{enterprise_id}/memberships/{id}/accept`
- `POST   /api/v1/releases/{enterprise_id}/memberships/{id}/reject` — body `{notes}`
- `POST   /api/v1/releases/{enterprise_id}/memberships/{id}/withdraw`
- `POST   /api/v1/releases/{enterprise_id}/memberships/{id}/remove` — body `{reason}`
- `GET    /api/v1/releases/{project_release_id}/membership` — for the Enterprise tab on a project detail; returns current accepted row + history

### Rollups

- `GET /api/v1/releases/{enterprise_id}/rollup/systems`
- `GET /api/v1/releases/{enterprise_id}/rollup/scope` — query params mirror filter keys
- `GET /api/v1/releases/{enterprise_id}/rollup/timeline`
- `GET /api/v1/releases/{enterprise_id}/rollup/members`

### Report

- `GET /api/v1/releases/{enterprise_id}/report` — JSON payload used to render the HTML report on the client

### Existing endpoints — minor

- `GET /api/v1/releases` — accept optional `release_kind=project|enterprise` filter. Response already includes `release_kind`.
- `GET /api/v1/releases/{id}` — unchanged payload for project releases; for enterprise releases, include `membership_summary: {pending, accepted, rejected, withdrawn, removed}` counts.

## Events (outbox)

New event types:

- `EnterpriseMembershipRequested`
- `EnterpriseMembershipAccepted`
- `EnterpriseMembershipRejected`
- `EnterpriseMembershipWithdrawn`
- `EnterpriseMembershipRemoved`
- `EnterpriseReportGenerated`

Payloads carry `{enterprise_id, project_release_id, membership_id, actor_id, late_scope?}` as relevant. Consumer wiring to NATS follows the existing outbox pattern; no new consumers in this sub-project.

## Frontend

### Routing / list / form

- `ReleaseList.tsx`: add **kind toggle** (Project / Enterprise). Client-side filter on the existing list payload — no server round-trip change required beyond the optional query param.
- `ReleaseForm.tsx`:
  - "Kind" selector at the top (Project | Enterprise). Defaults to Project.
  - On Enterprise: hides system-role picker, dependency field (enterprise has none); lifecycle template picker only shows templates with `applies_to_kind='enterprise'` or `applies_to_kind IS NULL`.
  - On Project: unchanged.

### Enterprise detail page

`ReleaseDetail.tsx` branches on `release_kind`. Enterprise tab set:

1. **Main** — status, lifecycle progress, target/actual date, custom fields, description. Same bar as project releases.
2. **Members** — the centrepiece:
   - Section: **Pending requests** (pending_request rows) with Accept / Reject buttons, disabled when permission check fails for current enterprise state.
   - Section: **Accepted members** — DataGrid: project name, status chip (live from `release.status`), admitted_at, late_scope badge, remove action.
   - Section: **History** — collapsible. Shows rejected / withdrawn / removed rows.
   - "Request to admit project..." button opens a picker listing eligible projects (same tenant, kind=project, no other `pending_request` or `accepted` row).
3. **Phases** — own phases. Unchanged component.
4. **Gates** — own gates + criteria. Criterion editor gets a new optional "Linked member summary" read-only line (e.g., "3/5 children in `sit_complete` or later"). Purely informational.
5. **Bookings** — own bookings (integration env bookings). `context_tag` derives from enterprise name + phase, same rule as project releases.
6. **Events** — own event log.
7. **Systems Impacted** — **rollup, read-only**. DataGrid: system name, roles contributed by children (chips), contributing project list.
8. **Scope** — **rollup, read-only**. DataGrid grouped by project (or flat, toggleable): jira_key, title, kind, status, project release. Filters: kind, status, project, text. "Generate Report" button.
9. **Timeline** — combined Gantt. Top lane = enterprise phases. Sub-lanes per accepted child = child's phases, coloured by child status. Dependency arrows drawn child-to-child.
10. **Report** — HTML-rendered report from `GET /api/v1/releases/{enterprise_id}/report` JSON. Sections:
    - Title, enterprise status, target/actual date
    - Member projects with current states + late_scope flag
    - Systems impacted (grouped)
    - Jira tickets delivered (grouped by project)
    - Notable events (enterprise + top child transitions)
    - Dependency map (textual)
    - A "Print" button (`window.print()`) — no server-side PDF.

### Project detail page — new Enterprise tab

On `release_kind='project'`:

- New **Enterprise** tab.
- If no accepted membership → "This project is not part of an enterprise release." + "Request to join..." button.
- If accepted → card showing parent enterprise name (link), admission date, decided-by, late_scope if true, "Request removal" action (which just contacts the enterprise RM — no system action; removal is done from the enterprise side).
- History section: prior accepted/removed/rejected rows.

### Admin — lifecycle editor

Existing admin page at `/admin/lifecycles/{template_id}` extends:

- New "Kind" picker at the top (Project | Enterprise | Any) — persists to `LifecycleTemplate.applies_to_kind`.
- When `applies_to_kind='enterprise'`:
  - New "Admission permissions" block: state × role matrix for `membership.admit`, `membership.reject`, `membership.remove`. Persists to `definition.action_permissions`.
  - New "Admission lockdown" radio on each state row — single-select across the template. Persists to `states[i].is_admission_lockdown`.
- Project-kind lifecycle templates see none of the above.

### Services, slices, types

New files:
- `frontend/src/services/enterpriseMembershipService.ts`
- `frontend/src/services/enterpriseRollupService.ts`
- `frontend/src/services/enterpriseReportService.ts`
- `frontend/src/store/enterpriseMembershipSlice.ts`
- `frontend/src/types/enterpriseMembership.ts`
- `frontend/src/types/enterpriseReport.ts`

Existing `releaseSlice` / `releaseService` extended for the `release_kind` query param and enterprise-only response shape.

### Destructive confirmations

All destructive actions (Reject, Withdraw, Remove) use `useConfirm()` per the MR !7 project pattern.

## Permissions + role model

No new roles. `Role.RELEASE_MANAGER` and `Role.ADMIN` seeded with all three membership permissions on every state of the default enterprise lifecycle. Other roles opt-in via the admin editor.

## Migrations

One Alembic migration (schema):

1. `op.create_table('release_membership', ...)` with the columns listed above.
2. `op.create_index('uq_membership_pending_per_project', 'release_membership', ['project_release_id'], unique=True, postgresql_where=sa.text("state = 'pending_request'"))`
3. Same partial unique for `accepted`.
4. `op.add_column('lifecycle_template', sa.Column('applies_to_kind', sa.String(20), nullable=True))`

No schema change to `lifecycle_template.definition` — it is JSON; new keys (`states[i].is_admission_lockdown`, `action_permissions`) are additive and tolerated by existing code. `validate_definition_for_entity` is updated to recognise + enforce them.

Data migration (separate Alembic revision, data-only):
- For each tenant, ensure an enterprise lifecycle template exists. Create the default one from the seed spec above if absent. Existing `entity_type='release'` templates get `applies_to_kind='project'` backfilled (they were all project-only in practice).

## Testing

### Backend

- Service unit tests:
  - Happy-path `request → accept` → child `parent_release_id` set, membership row correct, `late_scope=false` pre-lockdown.
  - `accept` after lockdown → `late_scope=true`.
  - `request` when project already has `pending_request` → 409.
  - `accept` when project already has `accepted` row → 409.
  - `accept` without permission in current state → 403.
  - `reject` / `withdraw` / `remove` transitions and permission checks.
  - `remove` nulls `parent_release_id` on child and emits event.
- Rollup tests:
  - Accepted-only: removed/rejected memberships do not contribute to rollups.
  - Cross-tenant isolation on every rollup endpoint.
- Report test:
  - Given a fixture enterprise with 3 children, rollup payload is deterministic, includes all scope items, groups correctly.
- Integration happy path (`test_enterprise_release_happy_path.py`):
  - Create enterprise → create 2 projects → request + accept both → transition enterprise through `admission_closed` → request + accept a 3rd → assert `late_scope=true` → generate report → assert counts.
- Tenant isolation tests on every new endpoint.

### Frontend

- No new unit tests (Tier 3 modernisation not in scope this sub-project).
- Smoke checklist at `docs/archive/phase-3-sub2-smoke-checklist.md` covers UI flows.

## Acceptance criteria

- [ ] Creating a release with `kind=Enterprise` binds it to an enterprise-scope lifecycle template and hides project-only fields.
- [ ] A project release can be requested into an enterprise; an accept/reject by a permitted role moves it to the correct terminal state and sets/leaves `parent_release_id`.
- [ ] A project with an outstanding `pending_request` cannot have another requested (DB enforced).
- [ ] A project with an `accepted` membership cannot be accepted into another enterprise (DB enforced).
- [ ] Removing a project from an enterprise nulls `parent_release_id` and leaves the audit trail intact.
- [ ] Admitting a project after the enterprise has transitioned past `admission_closed` (or whichever state carries the lockdown marker) sets `late_scope=true` on the membership row; the UI shows a badge.
- [ ] The systems rollup lists each system exactly once, with roles sourced from all accepted children.
- [ ] The scope rollup lists every Jira ticket from every accepted child's `release_change`, grouped by child.
- [ ] The combined Gantt shows enterprise phases + per-child phase lanes + child-to-child dependency arrows.
- [ ] The Release Report renders HTML with all sections populated; the Print button prints a readable page.
- [ ] Project detail has an Enterprise tab showing current parent if any + history.
- [ ] Admin lifecycle editor exposes the three membership permission columns and the lockdown radio, for enterprise-scope templates only.
- [ ] All new endpoints filter by `tenant_id`; cross-tenant probes return 404.
- [ ] All service methods have unit tests; happy-path integration test passes.

## Out of scope (explicit reminder)

- Enterprise-level dependencies as a first-class entity (project↔project only).
- Multi-parenting (one enterprise per project, enforced).
- Hard gates that block child deployment based on enterprise state.
- Auto-transition of enterprise status based on children's states.
- PDF export / markdown download of the report.
- Enterprise-owned scope items or enterprise-owned system rows.
- Jira webhook integration (Sub-project 3).
- PIR (Phase 5).
- Notifications / email on membership events (infra not in place).
