# Phase 5: DORA Metrics, Health Dashboard & PIR

> Status: ⏳ **Planned** | Roadmap: [../plan.md](../plan.md)
> Duration: 4–6 weeks | Starts after Phase 4 completion

---

## Objectives

- Incident tracking linked to deployments and environments (manual entry)
- Calculate the four DORA metrics: Deployment Frequency, Lead Time, Change Failure Rate, MTTR
- DORA metrics dashboard with trend charts and filters
- Environment Health Check Dashboard (REST API for up/down/issue status pushed by external tools)
- Post-Implementation Reviews (PIR) linked to incidents and releases
- Release-level metrics: success rate, environment utilization, booking conflicts

---

## Planned Tasks

### Backend

#### Incident Tracking
- [ ] `Incident` model with:
  - `title`, `description`, `environment_id`, `deployment_id` (nullable FK)
  - `release_id` (nullable FK → Release) — the **causal** release that introduced the problem; used for DORA Change Failure Rate
  - `fix_release_id` (nullable FK → Release) — the **fix** release that will deliver the correction; set by the problem manager
  - `detected_at`, `resolved_at`, `severity` (P1 | P2 | P3 | P4), `status` (open | resolved), `tenant_id`, `deleted_at`
- [ ] `Incident` CRUD API endpoints (`/api/v1/incidents`):
  - `GET /api/v1/incidents` — list; include `fix_release_target_date` and `pir_status` in response for overview columns
  - `POST /api/v1/incidents` — create (optionally set `release_id`, `fix_release_id`)
  - `GET /api/v1/incidents/{id}` — detail response includes:
    - `pir` — linked PIR (`root_cause`, `action_plan`, `status`) via `PIR.incident_id`; null if none exists
    - `fix_release` — release summary (`name`, `target_date`, `status`) + `ReleaseChange` records (Jira fix stories) grouped by Epic; null if `fix_release_id` not set
  - `PATCH /api/v1/incidents/{id}` — update incident fields including `fix_release_id`
  - `DELETE /api/v1/incidents/{id}` — soft delete
- [ ] Link incidents to deployments and releases (for Change Failure Rate and MTTR calculation)

#### DORA Metrics
- [ ] DORA metrics calculation service (time-windowed aggregations):
  - `deployment_frequency(env_id, period)` — deployments per day/week/month
  - `lead_time(release_id)` — time from build commit (git SHA) to successful deployment
  - `change_failure_rate(period)` — % deployments that triggered an incident
  - `mttr(period)` — average time from incident detection to resolution
- [ ] `MetricsCache` — pre-calculated DORA metrics stored in Redis (invalidated on new deployment/incident)
- [ ] Background job to recalculate metrics on new deployments/incidents
- [ ] DORA API endpoints (`/api/v1/metrics/dora`, `/api/v1/metrics/dora/deployment-frequency`, etc.)
- [ ] CSV export endpoint for metrics data
- [ ] Filters: by project, environment, release, and time period

#### Environment Health Check Dashboard
- [ ] `EnvironmentHealthStatus` model: `environment_id`, `status` (up | down | issue), `recorded_at`, `source` (free text — which tool reported it), `tenant_id`
- [ ] `POST /api/v1/environments/{id}/health` — accepts status push from external monitoring tools (no auth for push endpoint, or API-key auth)
- [ ] `GET /api/v1/environments/{id}/health/history` — status history with timestamps
- [ ] Health dashboard query: per-environment current status + active bookings + current planned TECRs (outage flag)
- [ ] Alert logic: if environment is `down` or `issue` during an active approved booking with no planned TECR outage → surface alert via notifications

#### Post-Implementation Reviews
- [ ] PIR model is **defined in Phase 3** (under Release Management); Phase 5 adds incident linking and metrics integration
- [ ] Ensure PIR endpoints (`/api/v1/releases/{id}/pir`) surface the linked incident's `fix_release_id` for problem manager communications
- [ ] PIR completion can be a configurable gate on release closure (already defined in Phase 3)

#### Release-Level Metrics
- [ ] `GET /api/v1/metrics/releases` — release success rate, avg lead time, emergency % of total
- [ ] `GET /api/v1/metrics/environments/utilization` — environment booking hours vs available hours
- [ ] `GET /api/v1/metrics/bookings/conflicts` — booking conflicts per environment per month

### Frontend

- [ ] DORA metrics dashboard page with:
  - Deployment Frequency chart (time series, bar)
  - Lead Time histogram
  - Change Failure Rate gauge
  - MTTR trend chart
  - Filter bar (project, environment, release, date range)
  - CSV export button
- [ ] `IncidentList.tsx` — list with severity, deployment, resolution filters; **Fix ETA** column (`fix_release_target_date`); **PIR Status** column (open / closed / none)
- [ ] `IncidentDetail.tsx` — detail page with:
  - **PIR panel**: linked PIR (root_cause, action_plan, status); "Create PIR" button if none linked yet
  - **Fix Release panel**: "Fix ETA" showing linked release name + target_date; searchable release dropdown to set `fix_release_id`; once linked, lists Jira `ReleaseChange` stories from that release grouped by Epic header (same grouping pattern as Release Scope tab on ReleaseDetail)
- [ ] `IncidentForm.tsx` — manual incident entry linked to deployment and release; optional fix release selector (searchable dropdown)
- [ ] Environment Health Dashboard page:
  - Grid of environments showing current status (traffic light: green/red/amber)
  - Click-through to environment detail showing: status history, active booking, current TECRs
  - Alert banner for environments down during an active booking with no planned outage
- [ ] PIR form and detail view (delivered in Phase 3; Phase 5 adds incident-linked navigation from IncidentDetail)
- [ ] Release metrics summary panel on the Release Detail page

---

## Notes

> Detailed task breakdown to be added when Phase 4 is complete and Phase 5 planning begins. The items above represent the confirmed scope; specific implementation details will be refined at phase start.

## Acceptance Criteria

- [ ] All four DORA metrics are calculated correctly for configurable time windows
- [ ] Incident `release_id` (causal) and `fix_release_id` (fix) are independent nullable FKs; both can be set independently
- [ ] `GET /api/v1/incidents/{id}` returns linked PIR and fix release with Jira stories
- [ ] Environment health alert fires when environment status is `down` or `issue` during an active approved booking with no planned TECR outage
- [ ] Tenant isolation verified: incidents, health statuses, and DORA metrics from one tenant are never accessible to another
