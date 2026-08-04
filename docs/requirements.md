# EnvManager — Requirements

> **Authoritative reference for Claude Code sessions.**
> Source documents: [`archive/EnvManager_Requirements_Summary.md`](archive/EnvManager_Requirements_Summary.md), [`archive/EnvManager_Development_Prompt.md`](archive/EnvManager_Development_Prompt.md) (both superseded by this document — see [`archive/`](archive/)) and `Planview Release Verify Introduction`, a third-party vendor document kept outside this repository.
> Architecture: [prod architecture.md](prod%20architecture.md) | Roadmap: [plan.md](plan.md)

---

## 1. Problem Statement

EnvManager replaces a legacy test environment management system and eliminates reliance on spreadsheets, wikis, and ad-hoc communication. It provides a centralized, auditable, event-driven platform that enables teams to:

- Know which environments exist, what state they are in, and who is using them
- Coordinate shared environment usage across multiple projects without conflicts
- Track planned changes and CI/CD deployments to environments
- Manage software releases through structured test phases (SIT, UAT, Staging)
- Report DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, MTTR)
- Visualize infrastructure topology and detect drift from Terraform state

---

## 2. Functional Requirements

### 2.1 Environment Modeling

- Model **on-premise and cloud** test environments
- Support **long-lived and ephemeral** environments
- Environment hierarchy: **System → Sub-System** (each a separate entity; note: "Infrastructure Component" in §2.9 is a separate Phase 6 topology entity, not a third level of this hierarchy)
- Environments composed of sub-resources (hardware, services, databases, cloud components)
- Environments can be grouped into **Environment Groups** (e.g., "Mortgage SIT + Customer SIT")
- An environment can belong to **multiple environment groups**
- Environment status tracking: `active`, `inactive`, `maintenance`, `decommissioned`
- Tagging and metadata: owner, cost center, compliance tags
- Each environment tracks **which version/build of each sub-system is currently installed** — updated automatically on deployment, visible in the environment detail view
- Must be modelable as **infrastructure topology diagrams** (see §2.9)

#### System Catalog

- **Systems are tenant-level catalog entries** — they are not scoped to a specific environment
- An environment is composed of **instances** of catalog Systems, tracked via `EnvironmentSystem` junction records
- Each `EnvironmentSystem` record carries a `status`:
  - `active` — system is running in this environment
  - `inactive` — system is defined but not currently running
  - `mock` — system is deliberately mocked/stubbed in this environment (a documented gap)
- When marking a system as mocked, admins provide `mock_notes` explaining what stub is in use
- Systems and SubSystems can each declare **service call dependencies** on other Systems/SubSystems:
  - **System-level** (`SystemDependency`): System A calls System B (e.g., Checkout Service → Payment Gateway)
  - **Component-level** (`ComponentDependency`): SubSystem A.component calls SubSystem B.component, including cross-system calls
  - Dependency attributes: `dependency_type` (`api_call | database | message_queue | event | file | other`), optional `protocol` and `port` (component level)
  - Dependencies carry a `source` field: `manual` (Phase 1) or `terraform | docker_compose` (Phase 6 IaC import)

#### Environment Verify

- `GET /api/v1/environments/{id}/verify` checks whether all dependency targets of systems in the environment are also present
- For each system in the environment, the verifier checks all declared `SystemDependency` targets:
  - **Satisfied** — dependency target has an `active` `EnvironmentSystem` record in this environment
  - **Mocked** — dependency target has `EnvironmentSystem.status = mock` (acknowledged gap)
  - **Missing** — dependency target has no `EnvironmentSystem` record (unacknowledged gap)
- Component-level gaps are nested under their parent system gap
- On missing items, two actions are offered: "Add to environment" or "Mark as mocked"
- Verify response shape: `{ satisfied: [...], missing: [{system, required_by, component_gaps, actions}], mocked: [...] }`

### 2.2 Booking System

- Bookings made at the **environment level** or at the **environment group level** (books all member environments as one unit)
- Two booking types:
  - **Shared**: Multiple bookings can coexist; projects cooperate within the same environment
  - **Exclusive**: Only one booking active at a time; all other bookings are blocked for the period
- **Soft conflict detection**: conflicts are informational only — the approver makes the final decision
- When creating a booking, display all existing bookings in the requested time period
- **Recurring bookings**: support daily, weekly, and monthly recurrence patterns (RRULE format)
- **Configurable lifecycle**: bookings support a definable state machine; at minimum, one lifecycle must include an approval step (e.g., `draft → submitted → approved | rejected`)
- Bookings can be **linked to a release and test phase**
- When a booking is linked to a release test phase, it is **automatically tagged** based on the system role declared on the release:
  - `deployment` — the environment's system is marked as "changing" on the release (new build will be deployed here)
  - `regression` — the environment's system is marked as "regression only" on the release (no new build; testing alongside other changes)
  - No user input needed on the booking form — computed from the release
- Notifications on: booking created, approved, rejected, conflict detected

### 2.3 Multi-Project Coordination

- Multiple projects can use the same environment simultaneously
- Projects define **Usage Agreements** governing how they cooperate in a shared environment
- Usage agreements cover: booking rules, cooperation guidelines, SLAs, access control
- Project-aware conflict detection checks whether projects have valid agreements before flagging

### 2.4 Change Management

- Change requests raised on **sub-resources** (not the environment as a whole)
- Change types: configuration change, infrastructure change, code deployment
- **Configurable lifecycle** with at least one lifecycle option supporting an approval step
- Changes can be linked to a **release** and to a **deployment**
- Changes include **impact analysis** (which components are affected)
- Change requests include an **outage flag**: does this change cause an environment outage? If yes, outage start/end time is recorded
- Full change history and audit trail
- Change requests (TECRs) appear on the **unified environment schedule** alongside bookings, so all teams sharing an environment can see both planned changes and bookings in one view
- Notifications on change status updates

### 2.5 Release Management

> **Delivery status (2026-04-23):** Sub-1 (Core Releases) ✅ merged (MRs !4–!13); Sub-2 (Enterprise Releases) ✅ merged (MR !15, `64c52e3`). Sub-1 delivered Release Template Library, Project Releases with configurable lifecycle, Test Phases, Gates with criteria (due date + assignee + notes; one-way auto-pass; per-release overdue count), System Roles, Release Dependencies with date-impact alerts, Release Event Log, release-booking linking with derived context tag, calendar + Gantt views, scope items with moves + backlog + immutable history, per-tenant `change_kind` rules for scope-change KPIs. Sub-2 delivered first-class enterprise releases with own lifecycle/phases/gates/bookings, admission workflow (pending → accepted/rejected/withdrawn; accepted → removed) with state × role permissions, configurable admission-lockdown marker flagging late scope for audit, rollup views (systems/scope/timeline/members), HTML report with print, project-side Enterprise tab, admin lifecycle editor extensions. **Deferred:** Jira Integration (Sub-3), Post-Implementation Reviews (Phase 5).

#### Release Types
- Two top-level release kinds:
  - **Enterprise Release (Release Train)**: groups 2+ Project Releases that must be tested and deployed together; each member Project Release must be approved/admitted into the Enterprise Release; the Enterprise Release tracks combined test phases across all members
  - **Project Release**: an individual release for one team/project
- Project Release subtypes (configurable, rename-able): **Major**, **Minor**, **Emergency/Independent**
- Each release type has its own **configurable state workflow** (Emergency has a simplified/fast-track lifecycle)

#### Release Lifecycle
- Releases follow a lifecycle made up of **phases** (SDLC stages) and **gates** (approval checkpoints)
- Phases track stages relevant to release management (e.g., development, SIT, UAT, staging, CAB, production deployment)
- Gates define agreed exit criteria that must be met before the next phase begins
- Activities and tasks can be tracked within each phase

#### Release Templates
- A **Release Template Library** stores reusable release templates
- Each template pre-defines: lifecycle phases, gates, activities, and approval checkpoints
- Users create new releases from a template (not from scratch)
- Templates are updated after **post-implementation reviews** to incorporate process improvements
- Templates are versioned to track process evolution over time

#### Release Scope (Changes / User Stories)
- Release **scope** defined by **user stories and defects imported from Jira** via webhook events
- Multiple Jira projects can contribute scope to a single release
- Release scope changes (added/removed stories) are audited

**Jira Integration — per-project configuration:**
- Each Jira project has its own `JiraProjectConfig` record containing: project key, Jira base URL, webhook secret (HMAC), credentials, and field mappings
- **"Copy from existing project"**: when configuring a new Jira project, an admin can clone another project's field mappings as a starting point (creates an independent copy — changes don't propagate)
- Webhook signature is verified on every inbound event

**Custom field mapping:**
- Admins configure how Jira webhook payload fields (including custom fields) map to named custom fields on `ReleaseChange` scope items in EnvManager
- Each mapping entry: `jira_field_path` (JSON path into the Jira payload, e.g. `fields.customfield_10001`) → `display_name` + `envmgr_field_key` + `field_type`
- A "test mapping" tool lets admins paste a sample Jira webhook payload and preview the resulting field values before saving
- Mapped values stored in `custom_fields` JSONB on the `ReleaseChange` record

**Jira Epics:**
- Epics are imported from Jira via the same webhook mechanism (issue type = Epic)
- Stored as `JiraEpic` records with the same custom field mapping applied
- Stories and defects are linked to their parent Epic via `epic_id` FK (resolved from Jira's `parent.key` or `customfield_epic_link`)
- **Epic-to-release relationship is derived**: an Epic "appears in" a release because its child stories are scoped to that release — no direct Epic-release link needed
- **Project Manager view**: `GET /api/v1/epics/{id}/releases` shows all releases an Epic's stories are distributed across; `EpicDetail` page groups stories by release with a cross-release timeline strip
- On the Release Scope tab: stories are grouped under their parent Epic as a collapsible header

#### Release Systems
- Systems are linked to a release with a declared **role**:
  - `changing` — this system has new code being deployed as part of the release
  - `regression` — no code change; must be tested alongside changing systems
  - `config_only` — configuration change only; no new build
- **Code Implementation Dependency**: a system on a release can have a specific deployment date set (e.g., for multi-data-center rollouts, dark deployments with a feature flag to turn on later)

#### Release Environment Bookings
- Test environments and environment groups are linked to release test phases via bookings
- Bookings derive their context tag (`deployment` or `regression`) automatically from the system role on the release (see §2.2)
- Provides a complete test environment schedule linked to the release timeline

#### Release Gates & Dependencies
- **Release gates**: approval checkpoints between phases; all gate criteria must be met before the release progresses
- **Release dependencies**: a release can declare that it must deploy after another release (ordering)
- "Smart alerts" notify the release manager when a dependency's dates change and may impact this release

#### Release Events
- An optional, configurable **event log** on each release
- Event types are configurable: e.g., Reschedule Reason, Scope Change, Post-Go-Live Incident
- Used for audit trail, post-implementation reporting, and future process improvement

#### Release Views
- **Calendar view**: shows release bookings and environment usage across time
- **Schedule / Gantt timeline view**: shows phase durations, gates, and key dates across multiple releases side by side

#### Post-Implementation Reviews (PIR)
- P1/P2 incidents attributed to a release trigger a **PIR record** on that release
- PIR documents: root cause, action plan, lessons learned
- PIR completion can be configured as a gate before a release is formally closed

### 2.6 Build Tracking

> **Delivery status (2026-04-23):** ✅ merged via MR !20. `Build` model with `git_sha`, `git_branch`, `build_number`, `commit_timestamp`, `build_started_at` / `build_finished_at`, `jira_tickets[]`, `pipeline_steps[]`, `custom_fields`. Builds upserted by `(tenant_id, subsystem_id, git_sha)`; replays merge `pipeline_steps` and `custom_fields`. List + detail endpoints with `subsystem_name` / `release_name` denormalised onto `BuildRead`.

- A **Build** represents a new version of a system or component
- Build fields: `git_sha`, `branch`, `build_number`, optional `jira_tickets[]` (Jira issue keys included in the build), optional `pipeline_steps[]` (key execution steps from the DevOps pipeline with timestamps and status)
- Builds are linked to a **System** (or Sub-System) and a **Release**
- Build data is a primary source for **DORA metrics** (Lead Time calculation uses build commit timestamp)
- Builds are separate from Deployments (a Build is the artifact; a Deployment is the act of installing it into an environment)

### 2.7 Deployment Tracking

> **Delivery status (2026-04-25):** ✅ merged via MR !20 (backend, 2026-04-23) + MR !21 (frontend + API keys, 2026-04-25). `POST /api/v1/webhooks/deployment` authenticated by API key with `webhooks:deployment` scope; idempotent ingest keyed on `Deployment.event_id`; auto-creates a `code_deployment` ChangeRequest via the seeded `Code Deployment` lifecycle and transitions it (`deploying → deployed | failed`); manual relink supported only when the current CR is auto-generated. UI: top-level Builds and Deployments pages, Deployments tabs on EnvironmentDetail and ReleaseDetail, deployments rendered on the unified `EnvironmentSchedule`. Per-tenant API key admin page (`/tenant/api-keys`) with raw-key-shown-once dialog.

- Deployment events ingested from **GitHub Actions** (primary CI/CD tool)
- Deployments track: environment, release, build, commit SHA, build number, deployer, timestamp, status (`success | failed | rolled_back`)
- Deployments are **recorded as changes** on environments (linked to a Change Request)
- Deployments linked to releases and builds for full traceability
- Deployment frequency is a DORA data source

### 2.8 DORA Metrics

The four DORA metrics must be calculated and displayed:

| Metric | Calculation Basis |
|--------|-------------------|
| **Deployment Frequency** | Count of successful deployments per time window |
| **Lead Time for Changes** | Time from build commit (git SHA) to successful production deployment |
| **Change Failure Rate** | % of deployments that trigger an incident |
| **Mean Time to Recovery (MTTR)** | Average time from incident creation to resolution |

Additional data requirements:
- Incident tracking (see below)
- Deployment success/failure/rollback status
- Release gate outcomes
- Filters by project, environment, release, and time period
- Export to CSV

**Incident tracking lifecycle**:
- Phase 5: Manual entry of incidents in EnvManager (with linked deployment and environment)
- Later phase (post Phase 5): REST API ingestion, webhook push, import from external tools (PagerDuty, Opsgenie, ServiceNow)

**Incident → PIR → Fix Release traceability:**
- An incident carries two release FKs:
  - `release_id` — the release that **caused** the incident (used for DORA Change Failure Rate; may be null if cause is unknown)
  - `fix_release_id` — the upcoming release that will **deliver the fix** (set by the problem manager once a fix release is planned)
- An incident can be linked to a **PIR** (Post-Implementation Review) via `PIR.incident_id`; the PIR documents root cause and action plan
- Fix stories (Jira user stories / defects) are standard `ReleaseChange` scope items on the fix release — no separate linking model needed
- Full traceability chain: `Incident → fix_release_id → Release → ReleaseChange` (Jira fix stories grouped by Epic)
- **Problem Manager view**: `GET /api/v1/incidents/{id}` returns the linked PIR and fix release (name, target_date, Jira stories) so problem managers can immediately communicate "Fix expected in Release v2.3, target: 15 Apr" to end users
- Incident list (`GET /api/v1/incidents`) includes `fix_release_target_date` for a "Fix ETA" overview column

**Environment Health Check Dashboard** (Phase 5):
- Simple REST API endpoint: `POST /api/v1/environments/{id}/health` — accepts `status` (`up | down | issue`) pushed by external tools
- Populated by external monitoring scripts, test runners, or cron jobs (not by EnvManager's own monitoring)
- Dashboard shows per-environment: current status, active bookings, current planned TECRs (explaining whether outages are expected), and status history timeline
- If an environment is `down` or `issue` during an active booking with no planned TECR outage, the system surfaces an alert

**Post-Implementation Reviews** (Phase 5):
- PIR records linked to incidents and releases (see §2.5)
- Release-level metrics: release success rate, environment utilization, booking conflicts per month, emergency release % of total

### 2.9 Infrastructure Topology

- Model cloud infrastructure (AWS, Azure, GCP) as components and connections
- Auto-import from **Terraform state files** (`.tfstate`)
- Define **layers** (e.g., Frontend, Backend, Data) for diagram layout
- **Interactive web-based viewer** using React Flow (zoom, pan, click for details)
- **Topology snapshots**: point-in-time captures for comparison
- **Drift detection**: compare Terraform plan vs Terraform state
- **Dependency / impact analysis**: show what is affected by a change to a component (PostgreSQL recursive queries; Neo4j dropped 2026-07-30)
- Health status visualization (color-code components by status)
- ~~Neo4j is the graph store for topology~~ — **superseded 2026-07-30**: PostgreSQL is the system of record *and* serves topology; Neo4j was provisioned but never used and has been removed ([decisions/2026-07-30-drop-neo4j.md](decisions/2026-07-30-drop-neo4j.md))

**IaC-to-dependency model integration (Phase 6):**
- Terraform and Docker Compose parsers (Phase 6) populate the **same `SystemDependency` and `ComponentDependency` tables introduced in Phase 1** — they do not create a separate dependency model
- Parsed connections are written with `source = terraform | docker_compose` (vs. `manual` for Phase 1 entries)
- This means manually declared dependencies and auto-discovered IaC dependencies coexist in the same graph, queryable together

### 2.10 Notifications & Events

- All key state changes publish events (booking, change, deployment, incident)
- Event consumers: notification dispatch, reporting table updates
- Notification channels: **email** and **webhooks** (POST to external URLs)
- Notification templates are configurable per event type
- Event replay capability for debugging and recovery

Key events requiring notifications:
- Booking created / approved / rejected / conflict detected
- Change request created / approved / started / completed
- Deployment completed (success or failure)
- Incident raised / resolved

---

## 2A. Governance & Enterprise-TEM Expansion

> Added 2026-07-16 from the domain-introduction documents. Full capability matrix in
> [gap-analysis.md](gap-analysis.md). These sections describe the **governance discipline** that
> wraps the transactional core (§2.1–§2.10). Phase targets in §7.

### 2.11 Release Governance (Phase 9)

- **Release Intake Form** ("front door"): single validated channel; completeness check; per-category lead times; returns incomplete intakes for clarification
- **Risk classification / scoring** at intake (scope, blast radius, customer impact, regulatory scope, dependency footprint) → drives which gates and approvals apply
- **Content / scope freeze** at a defined milestone; lock components + versions; formal exception approval for post-freeze additions; **Scope Stability** KPI (% content unchanged window-start → deploy)
- **Go / No-Go decision record**: joint sign-off (Test Manager quality + Release Manager process + Business Sponsor acceptance); records go / conditional-go / no-go, rationale, conditions, attendees, dissents; "have you tested the rollback?" is a required question
- **Gate types + evidence + waivers**: typed gates (functional, NFR/performance, integration, security, license, accessibility, business, ops-readiness); per-gate failure behaviour (block / warn / accept-with-exception); waiver workflow with reason, approver, expiry, remediation
- **Rollback governance**: documented rollback plan agreed **before** deploy; data-reversibility flags surfaced at Plan time; in-flight rollback authorisation recorded (time, trigger, rationale); rollback rehearsal tracked as a gate
- **Deployment execution**: deployment plan + window on the release record; pre-deployment checklist as a required gate; deploy patterns (rolling / blue-green / canary) per category; post-deployment verification (smoke / synthetic) that can trigger rollback; traffic-ramp schedule with auto-pause
- **Hyper-care + closeout**: explicit hyper-care window; "declared stable" decision to move Operate → Improve; closeout confirms ops-ownership transfer and records outcome; retrospective produces owned, dated actions
- **Feature-flag governance**: per-environment flag state + drift; stale-flag tracking; flag lifecycle policy (rollout plan, success criteria, removal-by date); production-flag-change audit feeding the evidence pack
- **Read-only / "Stable Windows"**: periods where no deploys are allowed (extends the `can-deploy` preflight gate)

### 2.12 Environment Lifecycle & Governance (Phase 7 expanded)

- Environment **tiers** as a first-class field (Dev / SIT / UAT / Pre-Prod / Performance / Training / Production / Other)
- Extended status set incl. **Reserved** and **Idle** (beyond active/inactive/maintenance/decommissioned)
- **Named human owner** enforced per environment; **expiry / re-justification date** required
- **Naming & tagging conventions**: enforced naming pattern; mandatory tags (owner, cost centre, tier, expiry); quarantine/terminate untagged resources after a grace period
- **Environment Request Form** with mandatory fields + completeness validation; **Welcome Pack** auto-generated on handoff (URLs, credentials, VPN, support/SLA, data profile, known limitations, expiry, decommission steps)
- **Soft (preemptible) vs hard (protected) reservations**; time-slot bookings (half-day / sprint / release cycle)
- **Priority-ordered contention resolution** (configured priority order, not first-come-first-served); escalation to the Release Manager with a named owner + response window
- **Decommissioning process**: 5-day warning → extension approval → final backup → teardown → inventory/calendar update to Available; **idle auto-detection** (no deployments/logins/traffic for N days) flags ghost environments
- Forward **contention as a leading indicator** on the calendar (surface weeks out)

### 2.13 Test Data Management (Phase 10)

- **Data profile** per environment/request: synthetic / masked / subset / full-refresh, data classification, last refresh date, refresh cadence
- **Masking / anonymisation** of PII on Production snapshots; **one-way flow enforced (Production → non-Production, never reverse)**; post-load verification that no real data leaked
- **Scheduled data refreshes** per tier on a known cadence; **Refresh Cycle Time** metric; waive/defer with owner + escalation
- **Data swimlanes** / account-range partitioning and naming-convention prefixes for shared-environment test data; Team/Tenant-ID isolation
- Record masking / access-control **waivers** against the environment (never verbal)

### 2.14 Cost & FinOps (Phase 11)

- Cost fields on environments and releases: estimated monthly run-rate, funding source / cost centre, chargeback / showback model
- **Cost per Environment-Week** (fully loaded) surfacing ghost/idle costs
- **% of estate under IaC** (rebuildable from version control)
- Cloud **auto-stop / auto-start** schedules and cost guardrails on self-service creation
- **ROI model**: quantify benefits (slippage, change-failure, rollback, lead-time, emergency, audit) vs costs (tooling, people, run); compute Net Benefit, ROI %, Payback; baseline + 12-month target
- Sustainability / compute-footprint reporting (optional)

### 2.15 Compliance & Audit Evidence (Phase 12)

- **Regulatory regime** as a field on the release/environment (SOX, PCI DSS, GDPR/UK DPA, HIPAA, FCA/PRA, NIS2, FedRAMP, ISO 27001); derives required gates and evidence
- **Evidence pack** captured **at gate time** (not reconstructed at audit): scope, approvals, gate evidence, deployment log, hyper-care incidents, retrospective; attached to the release record
- **Evidence retention** matching the longest applicable regime; tamper-evident; indexed for retrieval within an audit-response window
- **Separation of duties** enforced by tooling (builder ≠ approver ≠ deployer) — depends on RBAC upgrade
- Control-bypass exceptions recorded with reason, approver, remediation date; exceptions-without-remediation flagged as standing findings

### 2.16 ITSM Integration & Enterprise Operations (Phase 13)

- **ITSM change-feed integration** (ServiceNow / BMC Helix / Jira Service Management): pull infrastructure/config/vendor changes onto the unified Environment + Release Schedule
- **Reconciliation** of the environment/release registers against CI/CD, ITSM, cloud tag inventory, and IaC state on a defined cadence, surfacing discrepancies
- **SLA / OLA management**: define, track, and publish SLA (consumer) + OLA (internal) performance monthly; on a missed SLA, surface which OLA failed underneath
- **KPI suite + baselining**: environment KPIs (Lead Time, Up-time, Defect Leakage due to Environment, Utilisation, MTTP, MTTR, Booking Honour, Refresh Cycle Time) and release KPIs (On-Time %, Scope Stability, Rollback Rate, Emergency %, Hotfix Lead Time, Pipeline Reliability); baseline at start, report deltas
- **5-level Maturity Model** with self-assessment questionnaire; **RACI** + **decision-rights / escalation matrix**; **TEM / RM function risk registers**
- **Communications**: Stakeholder Communications Plan, weekly bulletin, real-time status page; capacity/demand forecasting from the PMO roadmap
- BC/DR (RTO/RPO) for the register/calendar/evidence/dashboards with an out-of-band manual fallback

---

## 3. Non-Functional Requirements

### 3.1 Performance

- API response time < 200ms (95th percentile)
- Support 1,000+ concurrent users
- Handle 10,000+ environments
- Topology diagram generation < 5 seconds for 100 components

### 3.2 Security

- JWT authentication (current); OAuth 2.0 / OIDC deferred
- RBAC roles when auth is upgraded: Admin, Release Manager, Test Manager, Developer, Viewer
- API key support for CI/CD integrations (Phase 4+)
- Project-scoped permissions (users see only their project's data)
- Audit logging for all sensitive operations
- SQL injection prevention (parameterized queries), XSS protection, HTTPS only

### 3.3 Lifecycle Configurability

- Booking and Change Request state machines must be **configurable** (not hardcoded)
- States and transitions defined in configuration, not in application code
- At minimum, one built-in lifecycle for each must include an approval step

### 3.4 Reliability

- 99.9% uptime SLA
- Graceful degradation: core booking works even if NATS is unavailable (the outbox drains when it returns)
- Daily database backups
- Event replay capability for recovery

### 3.5 Observability

- Structured JSON logging
- Health check endpoints for all services
- Prometheus metrics collection
- Grafana dashboard for system health

---

## 4. Data Model (Key Entities)

| Entity | Phase | Description |
|--------|-------|-------------|
| **Tenant** | 0 ✅ | Organisation / multi-tenant isolation unit |
| **User** | 0 ✅ | Authenticated user within a tenant |
| **Environment** | 1 | A test environment (on-premise or cloud) |
| **Environment Group** | 7 | A collection of environments bookable as one unit |
| **System** | 1 | A logical application or service — tenant-level catalog entry (not environment-scoped) |
| **EnvironmentSystem** | 1 | Junction record linking a System to an Environment; status = active \| inactive \| mock |
| **SystemDependency** | 1 | A declared service call dependency between two Systems (source: manual \| terraform \| docker_compose) |
| **Sub-System** | 1 | A component within a System (also catalog-level) |
| **ComponentDependency** | 1 | A declared service call dependency between two SubSystems, cross-system calls allowed |
| **Infrastructure Component** | 6 | A cloud/on-premise resource (Lambda, S3, server, etc.) |
| **Infrastructure Layer** | 6 | A logical grouping of components for diagram layout |
| **Infrastructure Connection** | 6 | A network or data flow between components |
| **Infrastructure Snapshot** | 6 | Point-in-time topology capture |
| **Project** | 7 | A team or project using environments |
| **Usage Agreement** | 7 | Cooperation rules between projects sharing an environment |
| **Booking** | 1 | A time-based reservation (supports Shared / Exclusive, recurring) |
| **Change Request** | 2 | A planned change to a sub-resource |
| **Release** | 3 | A Project Release or Enterprise Release (release train) |
| **Release Template** | 3 | A reusable release template with predefined phases, gates, and activities |
| **Release Dependency** | 3 | An ordering relationship between releases |
| **Release Event** | 3 | An audit log entry on a release (reschedule reason, scope change, etc.) |
| **Test Phase** | 3 | A phase within a release (SIT, UAT, Staging) |
| **Release Gate** | 3 | An approval checkpoint between test phases |
| **JiraProjectConfig** | 3 | Per-project Jira integration config with webhook secret, credentials, and field mappings |
| **JiraEpic** | 3 | A Jira Epic with custom fields; stories linked to it; release span is derived |
| **Post-Implementation Review (PIR)** | 5 | Root cause + action plan for incidents attributed to a release |
| **Build** | 4 | A versioned software build (git SHA, branch, Jira tickets, pipeline steps) |
| **Deployment** | 4 | A CI/CD deployment event linked to a build and environment |
| **Incident** | 5 | An incident record; `release_id` = causal release; `fix_release_id` = fix delivery release; linked to PIR via `PIR.incident_id` |
| **Environment Health Status** | 5 | Point-in-time up/down/issue status pushed via REST API |
| **Event Log** | 1 | Outbox event store for reliable event publishing |
| **Release Intake** | 9 | Front-door request with risk score, before a Release is accepted |
| **Go/No-Go Decision** | 9 | Recorded joint sign-off (go/conditional/no-go, dissents) on a release |
| **Rollback Plan** | 9 | Documented rollback for a release incl. data-reversibility flags + in-flight auth record |
| **Gate Evidence** | 9/12 | Evidence artefact captured at a gate, attached to the release |
| **Feature Flag State** | 9 | Per-environment flag value + lifecycle (rollout, removal-by) |
| **Data Profile** | 10 | Per-environment test-data profile (synthetic/masked/subset, classification, refresh) |
| **Data Refresh** | 10 | A masked Prod→non-Prod refresh event with cadence + verification |
| **Cost Record** | 11 | Run-rate / funding / chargeback for an environment or release |
| **Regulatory Regime** | 12 | Compliance regime on a release/environment driving gates + evidence retention |
| **ITSM Change** | 13 | Infrastructure/config change pulled from ITSM onto the unified schedule |
| **SLA / OLA** | 13 | Service/operational level agreement definitions + monthly performance |

---

## 5. Key Decisions

| Decision | Resolution | Rationale |
|----------|------------|-----------|
| Authentication | Keep simple JWT/bcrypt for now | RBAC deferred; platform still in development |
| RBAC | Deferred | Will be implemented when auth is upgraded to OAuth 2.0/OIDC |
| Recurring bookings | Include in Phase 1 | Core booking requirement, not optional |
| Build entity | Separate from Deployment | Build = artifact (git SHA, branch, Jira tickets, pipeline steps); Deployment = install act |
| CI/CD integration | GitHub Actions only | Only tool in use at this organisation |
| Jira integration | Yes — Phase 3 | User story import for release scope |
| CMDB integration | Excluded | Not in use; can be added later if needed |
| Incident entry | Manual in EnvManager (Phase 5), then API/webhook (later phase) | Pragmatic starting point |
| Phase 8 | Excluded from plan | Listed as out of scope in requirements |
| Enterprise Release | Include in Phase 3 | Needed for managing coordinated multi-team production deployments |
| Release Templates | Full library in Phase 3 | Central to building a repeatable, improvable release process |
| Health Check Dashboard | Phase 5 (with DORA) | Belongs with monitoring and metrics; not Phase 1 priority |
| Booking system context | Auto-derived from release | Release declares system roles; bookings inherit context automatically |

---

## 6. Out of Scope

> **2026-07-16 scope change:** Following a gap analysis against the *Release Management* and
> *Environment Management* introduction documents ([gap-analysis.md](gap-analysis.md)), four
> previously-excluded areas were brought **into scope**: Test Data Management (Phase 10),
> Cost & FinOps (Phase 11), Compliance & Audit Evidence (Phase 12), and ITSM change-feed
> integration (Phase 13). See §2.11–§2.16 and §7.

Still out of scope:

- Mobile application
- AI-powered recommendations / Phase 8 advanced AI features (parked design)
- Advanced analytics beyond DORA metrics + the environment/release KPI set (§2.16)
- **Full two-way CMDB sync** (ITSM *change-feed* integration IS in scope — §2.15 — but bidirectional CMDB reconciliation as a source of truth is not)
- Environment automation / TECR-triggered provisioning pipelines (future REST API integration by customer tools — not built by EnvManager)

---

## 7. Phase Map

| Phase | Requirement Domains Addressed |
|-------|-------------------------------|
| 0 ✅ | Infrastructure setup, Auth foundation, Base models |
| 1 ✅ | Environment Modeling, Booking System (incl. recurring), Event Infrastructure |
| 2 | Change Management |
| 3 | Release Management (Enterprise + Project Releases, Templates, Dependencies, Events, System Roles, Gantt View, PIR), Jira Integration |
| 4 | Build Tracking, Deployment Tracking (GitHub Actions) |
| 5 | DORA Metrics, Incident Tracking (manual), Health Check Dashboard, PIR, scheduled health checks, booking honour/utilisation |
| 6 | Infrastructure Topology (Terraform, React Flow) + **Environment Drift detection & sync vs Production** (§2.12/B4) |
| 7 | Multi-Project Coordination, Environment Groups, Usage Agreements + **Environment Lifecycle & Governance** (§2.12: tiers, decommission, welcome pack, priority contention) |
| 8 | *(reserved — parked AI Copilot / AI-driven Integrations design)* |
| 9 | **Release Governance & Deployment Safety** (§2.11: intake, go/no-go, scope freeze, rollback, hyper-care, feature flags, deploy patterns) |
| 10 | **Test Data Management** (§2.13) |
| 11 | **Cost & FinOps** (§2.14) |
| 12 | **Compliance & Audit Evidence** (§2.15 — depends on RBAC/OAuth) |
| 13 | **ITSM Integration & Enterprise Operations** (§2.16: change feed, reconciliation, SLA/OLA, maturity, comms) |
| Post-13 | Incident API/webhook ingestion, external incident tool imports, RBAC/OAuth, full CMDB sync |
