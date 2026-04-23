# Phase 3 Sub-2 (Enterprise Releases) — Smoke Checklist

Run after merging `feature/enterprise-releases` into `main` and deploying. Checks the full end-to-end flow in a running environment.

## Backend

- [ ] `alembic upgrade head` runs cleanly on an existing Phase 3 DB (applies `p3s6enterprise` + `p3s7memuniq`)
- [ ] `backend/scripts/backfill_enterprise_lifecycles.py` runs idempotently and seeds the default enterprise lifecycle template for every existing tenant
- [ ] `cd backend && uv run pytest tests/ -x -q` passes (should be 550+ tests, depending on exact tally)
- [ ] `cd backend && uv run pytest tests/integration/test_enterprise_release_happy_path.py -v` passes

## Frontend — create

- [ ] Navigate to `/releases/new` (Create Release) → Kind picker defaults to Project; selecting Enterprise filters the lifecycle template dropdown to `applies_to_kind='enterprise' | null` templates
- [ ] Creating an Enterprise-kind release persists `release_kind='enterprise'` and succeeds with the default enterprise lifecycle template
- [ ] Creating a Project-kind release still works as before (regression)

## Frontend — release list

- [ ] `/releases` shows the Project / Enterprise / All toggle
- [ ] Selecting Enterprise filters the grid to enterprise-kind rows only
- [ ] Selecting Project filters to project-kind rows only
- [ ] The Kind column shows a chip on each row

## Frontend — enterprise detail tabs

Open an enterprise release's detail page:

- [ ] Tab strip shows 10 tabs: Main, Members, Phases, Gates, Bookings, Events, Systems Impacted, Scope, Timeline, Report
- [ ] Main / Phases / Gates / Bookings / Events tabs reuse the existing project-release content (no regression)

## Frontend — admission workflow (Members tab)

- [ ] "Request admission…" button opens a picker listing project-kind releases with no active enterprise membership
- [ ] Submitting the picker creates a pending_request row visible in the Pending section
- [ ] Accept button moves the row to Accepted; the project's `parent_release_id` is set (verify via DB or API)
- [ ] Reject button prompts for notes, then leaves a row in the History section
- [ ] The same project cannot be requested into a second enterprise while pending or accepted (412/409 on retry — UI should surface the error)
- [ ] Remove action on an accepted row prompts for a reason, detaches the project, and leaves a row in History

## Frontend — lockdown + late scope

- [ ] Move the enterprise past `admission_closed` via the transition control
- [ ] Request + accept a new project admission → the Accepted row shows a "LATE" chip
- [ ] Reload the page — the chip persists (persisted on the membership row, not recomputed)

## Frontend — rollups + report

- [ ] Systems Impacted tab lists each system exactly once with role chips grouped by contributing project
- [ ] Scope tab lists Jira tickets (ReleaseChange rows) across accepted members with kind/status/search filters
- [ ] Timeline tab shows enterprise phases, each accepted child's phases, and any child-to-child dependencies
- [ ] Report tab renders with: header, members, systems impacted, Jira tickets grouped by project, notable events, dependencies
- [ ] Print button opens a print preview showing only the `.enterprise-report` section

## Frontend — project side

- [ ] On a project release's detail, the Enterprise tab shows the current parent (with a link), admission date, and history
- [ ] If the project has no membership, the tab shows the "not part of any enterprise" info alert

## Admin — lifecycle editor

- [ ] On `admin → Lifecycle Templates` (or equivalent), the editor shows a Kind picker (Any / Project / Enterprise)
- [ ] Selecting Enterprise reveals the Admission Lockdown radio (one state per template) and the Admission Permissions matrix (state × role × admit/reject/remove)
- [ ] Saving an enterprise-kind template persists `applies_to_kind`, `definition.states[i].is_admission_lockdown`, and `definition.action_permissions` correctly (verify via DB or GET)
- [ ] Creating a new enterprise template with a chosen lockdown state and using it on a new release works end-to-end

## Tenant isolation

- [ ] A second tenant cannot see memberships created by the first tenant (GET `/releases/{id}/memberships` from tenant B returns 404 or 200 with empty list)
- [ ] Cross-tenant admission attempts fail

## Known limitations (explicit reminders)

- Timeline tab shows phases as summary lists, not a visual Gantt (follow-up)
- `window.prompt()` still used for reject-notes and remove-reason; `useConfirm()` dialog variant is a separate piece of debt
- The Report tab does not yet support PDF export (HTML + Print only)
- Member-state summary in gate criteria is not yet surfaced in the Gate editor
