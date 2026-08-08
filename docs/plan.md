# EnvManager — Implementation Roadmap

> Architecture: [prod architecture.md](prod%20architecture.md) | Guide: [../CLAUDE.md](../CLAUDE.md)

---

## Phase Overview

| Phase | Name | Status | Duration | Detail |
|-------|------|--------|----------|--------|
| 0 | Foundations & Guardrails | ✅ Complete | — | See below |
| — | **Hardening programme** | ✅ Complete (2026-07-30, PRs #23–#33) — see [../CLAUDE.md](../CLAUDE.md) banner | 2 days | CI, Dockerfiles, dual-engine tests, auth sessions, observability, pagination |
| 1 | Environment Inventory + Shared Booking | ✅ Complete | — | [phases/phase-1.md](phases/phase-1.md) |
| 2 | Change Management | ✅ Complete (MR !2, merge `3bb3833`, 2026-04-19) | 2–3 weeks | [phases/phase-2.md](phases/phase-2.md) |
| 2.5 | Hosts + multi-target CRs (Phase 6 pull-forward) | ✅ Complete (same MR) | — | [phases/phase-2.md](phases/phase-2.md#phase-25--hosts-and-multi-target-change-requests-phase-6-pull-forward) |
| 3 | Releases, Templates, Enterprise Release, Jira | ✅ Sub-1 merged 2026-04-20/21 (MRs !4–!13); ✅ Sub-2 (Enterprise Releases) merged 2026-04-23 (MR !15, `64c52e3`); ✅ follow-ups MR !17 (gate due dates + timeline diamonds, `a2f55de`) + MR !18 (tenant-configurable change kinds, `0fa2eb5`) on 2026-04-23. Sub-3 (Jira) deferred. | 6–8 weeks | [phases/phase-3.md](phases/phase-3.md) |
| 4 | Build Tracking + CI/CD Deployment Tracking | ✅ Complete — Sub-1 (MR !20), Sub-2 (MR !21, `d802797`), Sub-3 (`can-deploy` preflight + required `build_number`) all merged | 6–8 weeks | [phases/phase-4.md](phases/phase-4.md) |
| 5 | DORA Metrics + Health Dashboard + PIR | ✅ Complete + in-app verified (2026-07-29) — SP1 Incidents (#20), SP2 DORA (#21), SP3 Env Health (#22), SP4 PIR, SP5b release/conflict metrics, SP5a operating hours + utilisation | 4–6 weeks | [phases/phase-5.md](phases/phase-5.md) |
| 6 | Infrastructure Topology **+ Environment Drift** | 🟡 Substantially shipped — both IaC parsers, topology API + React Flow, and **environment comparison** (2026-08-03) are done. Remaining: drift detection, GitHub scanning, env-topology SP4 | 6–8 weeks | [phases/phase-6.md](phases/phase-6.md) |
| 7 | Multi-Project Coordination **+ Environment Lifecycle & Governance** | 🟡 In progress (expanded 2026-07-16) — B1, B3a, B3b, A1, A2, A3 shipped; A4, B2, B4, B5, B6 remain | 6–8 weeks | [phases/phase-7.md](phases/phase-7.md) |
| 8 | *(reserved — parked AI Copilot / AI-driven Integrations)* | ⏸ Parked | — | — |
| 9 | Release Governance & Deployment Safety | ⏳ Planned (2026-07-16) | 6–8 weeks | — |
| 10 | Test Data Management | ⏳ Planned (2026-07-16) | 4–6 weeks | — |
| 11 | Cost & FinOps | ⏳ Planned (2026-07-16) | 3–4 weeks | — |
| 12 | Compliance & Audit Evidence | ⏳ Planned (2026-07-16, needs RBAC) | 4–6 weeks | — |
| 13 | ITSM Integration & Enterprise Operations | ⏳ Planned (2026-07-16) | 4–6 weeks | — |

> **2026-07-16 roadmap expansion.** Phases 9–13 (and the expansion of 6 & 7) were added from a gap
> analysis of the *Release Management* and *Environment Management* introduction documents. Full
> capability matrix: [gap-analysis.md](gap-analysis.md). Requirements: [requirements.md](requirements.md) §2.11–§2.16.

---

## Phase 0: Foundations & Guardrails — ✅ Complete

**Delivered**:
- Docker Compose environment (PostgreSQL, Neo4j, Redis, NATS) — *Neo4j since removed, never used: [decisions/2026-07-30-drop-neo4j.md](decisions/2026-07-30-drop-neo4j.md)*
- FastAPI backend structure (`api`, `core`, `db`, `services`, `workers`)
- React frontend with TypeScript and Material-UI
- Authentication system (JWT, bcrypt, login/logout)
- Database models: `Tenant`, `User`, `CustomFieldDefinition`
- Alembic migrations setup
- Multi-tenancy foundation
- Excel import templates (environment, system, project)
- Excel parser service

---

## Phase 1: Environment Inventory + Shared Booking — ✅ Complete

See [phases/phase-1.md](phases/phase-1.md) for the full task checklist.

**Objectives**: Environment/System/SubSystem CRUD, booking system with calendar UI, approval workflow, overlap detection, event publishing, Excel import.

---

## Phase 2: Change Management — ✅ Merged to `main` via MR !2 (2026-04-19)

See [phases/phase-2.md](phases/phase-2.md) for the full commit trail and acceptance checklist.

**Delivered** on `feature/phase-2-change-management`, merged into `main` at `3bb3833`:
- Lifecycle infrastructure generalised: `booking_lifecycle_template` → `lifecycle_template` with `entity_type` column; `lifecycle_service` works across bookings + change requests + (later) releases
- `ChangeRequest` + `ChangeHistory` domain models; CRUD API at `/api/v1/change-requests`; seed `Simple Approval` + `Emergency` default lifecycles on tenant creation
- Unified `GET /api/v1/environments/{id}/schedule` returning `{bookings, change_requests, deployments: []}`
- Outage × booking conflict preview endpoint + non-blocking form warning
- Frontend: CR list / form / detail / edit dialog pages, generalised admin `LifecycleTemplatesPanel`, `EnvironmentSchedule` FullCalendar tab on `EnvironmentDetail`
- **Phase 2.5 pull-forward** (same MR): `InfrastructureComponent` + host junctions, multi-target CRs, host-impact panel, readonly booking Gantt on CR form + detail
- Backend suite: 268 passed

**Deferred** (not Phase 2 regressions): change-notification consumer (cross-cutting, needed for bookings too); frontend unit tests (Tier 3 modernisation); `release_id` FK (Phase 3); `deployments: []` population (Phase 4).

---

## Phase 3: Releases & Test Phases — ✅ Sub-1 & Sub-2 on `main`

See [phases/phase-3.md](phases/phase-3.md) for the full MR trail and sub-project detail.

**Sub-project 1 — Core Releases** (✅ merged, MRs !4–!13, 2026-04-20/21). Release Template Library, Project Releases (Major/Minor/Emergency) with configurable lifecycle, Test Phases, Gates + criteria, System Roles, Release Dependencies with date-impact alerts, Release Event Log, Scope items with custom fields + lifecycle + moves/backlog/status history + per-tenant scope-change-kind rules, release↔booking linking, calendar + Gantt views, admin lifecycle + event-type management, unified lifecycle field-permissions, reusable MUI `useConfirm` hook.

**Sub-project 2 — Enterprise Releases** (✅ merged, MR !15 = `64c52e3`, 2026-04-23). First-class enterprise releases on top of the existing module: `release_kind='enterprise'` with own lifecycle, phases, gates, bookings, events; admission workflow via new `release_membership` table (`pending_request → accepted/rejected/withdrawn` + `accepted → removed`); configurable admission-lockdown marker tagging late-arriving scope for audit (not blocking); state × role permissions for admit/reject/remove; rollup views for systems + scope + timeline + members; HTML report with print; project-side Enterprise tab; admin lifecycle editor extensions. 558 backend tests pass; happy-path integration test at `backend/tests/integration/test_enterprise_release_happy_path.py`. Spec: `docs/superpowers/specs/2026-04-22-enterprise-releases-design.md`. Plan: `docs/superpowers/plans/2026-04-22-enterprise-releases.md`. Smoke checklist: `docs/archive/phase-3-sub2-smoke-checklist.md`. **Post-merge action:** run `backend/scripts/backfill_enterprise_lifecycles.py` once per environment.

**Post-Sub-2 follow-ups** (✅ merged 2026-04-23):
- **MR !17** (`a2f55de`) — Release gates: self-contained due dates + timeline diamonds. Drops `release_gate.test_phase_id`; gates carry required `due_date`. `gate_criterion.due_date` removed — criteria inherit from the parent gate; `overdue_criterion_count` becomes gate-level. `GET /releases/timeline` returns `gates[]`; Gantt renders status-coloured diamonds (slate / green / red / amber). Migration `p3s8gateduedate` backfills `due_date` via chain: linked phase.end_date → MAX(criterion.due_date) → release.target_date → release.created_at. Spec: `docs/superpowers/specs/2026-04-23-release-gate-due-dates-design.md`. Plan: `docs/superpowers/plans/2026-04-23-release-gate-due-dates.md`.
- **MR !18** (`0fa2eb5`) — Tenant-configurable scope change kinds. Admin Scope Change Rules page adds an "Add a new change kind" panel (lowercase slug, ≤20 chars, dedupe). New `GET /tenant/scope-change-rules/kinds` lite endpoint, open to any tenant member. `ScopeItemDialog` / `CustomFieldDefinitionDialog` / `ScopeRollupTab` fetch the live list instead of hardcoding four kinds. No migration.

After MR !18, `main` tip = `0fa2eb5`, latest alembic revision = `p3s8gateduedate`, backend test count = 560 passed + 1 skipped.

**Deferred** (sub-project 3 + Phase 5): Jira webhook integration for scope import; Post-Implementation Reviews (PIR).

---

## Phase 4: CI/CD Deployment Tracking — ✅ Sub-1 & Sub-2 on `main`

See [phases/phase-4.md](phases/phase-4.md) for the full delivery summary.

**Sub-project 1 — Backend** (✅ merged via MR !20 on 2026-04-23). `Build` and `Deployment` models with alembic revision `p4s1builddeploy`; `POST /api/v1/webhooks/deployment` authenticated by API key with `webhooks:deployment` scope; idempotent `DeploymentService.ingest` keyed on `event_id` that auto-creates a `code_deployment` ChangeRequest via the seeded `Code Deployment` lifecycle when none is supplied, and transitions the linked CR (`deploying → deployed | failed`) recording each transition in `change_history`; `Build` upsert keyed on `(tenant_id, subsystem_id, git_sha)` merging `pipeline_steps` + `custom_fields` on replay; `GET /builds`, `GET /deployments`, `POST /deployments/{id}/link-change`, `GET /environments/{id}/deployments`; `EnvironmentSchedule.deployments[]` populated.

**Sub-project 2 — Frontend UI + API keys** (✅ merged via MR !21 on 2026-04-25, `d802797`). `/tenant/api-keys` admin page with raw-key-shown-once dialog; top-level Builds and Deployments list/detail; `LinkChangeDialog` (relink only when current CR is auto-generated `Code Deployment`); Deployments tab on EnvironmentDetail and ReleaseDetail; deployments rendered on EnvironmentSchedule (FullCalendar) with palette + legend; admin `EntityConfig` extended with `build` + `deployment` slugs. Backend follow-on: `BuildRead` denormalises `subsystem_name` + `release_name`; `DeploymentRead` denormalises `environment_name`, `release_name`, `build_sha_short`, `change_request_title`; `_get_deployments_for_schedule` returns `build_sha` + `build_sha_short`. Cross-tenant isolation test landed in `backend/tests/integration/test_phase4_tenant_isolation.py`. Banner doc-only follow-up (MR !22) brought main tip to `dc5ca92`. Backend test count: **601 passed, 1 skipped**.

**Deferred** (still): Jira webhook integration (Phase 3 Sub-3), incident tracking + DORA dashboard + PIR (Phase 5).

---

## Phase 5: DORA Metrics — ✅ Complete

See [phases/phase-5.md](phases/phase-5.md).

**Objectives**: Incident tracking (manual entry); DORA metrics dashboard (Deployment Frequency, Lead Time, Change Failure Rate, MTTR); Environment Health Check Dashboard (REST push API + status grid); Post-Implementation Reviews; release-level and environment utilization metrics.

---

## Phase 6: Infrastructure Topology — 🟡 Substantially shipped

See [phases/phase-6.md](phases/phase-6.md).

**Objectives**: GitHub integration for repository scanning, Terraform and Docker Compose parsers, infrastructure component modeling, React Flow visualization, environment comparison tool.

**Corrected 2026-08-03**: all but three of these are already shipped — the parsers, the
topology API, the React Flow visualisation and the environment comparison tool. What
remains is drift detection, GitHub App/OAuth + repository scanning, and the env-topology
group-by toggle. See [phases/phase-6.md](phases/phase-6.md).

---

## Phase 7: Multi-Project Coordination + Environment Lifecycle & Governance — 🟡 In progress

**Shipped**: B1 (governance fields), B3a + B3b (user groups, environment request form + Welcome
Pack — B3 complete), A1 (projects + usage agreements), A2 (environment groups + atomic group
bookings), A3 (usage-agreement warnings, 2026-08-08). **Remaining**: A4, B2, B4, B5, B6.

See [phases/phase-7.md](phases/phase-7.md).

**Objectives** ([requirements.md §2.3](requirements.md)): Project management, usage agreements between projects, environment groups, project-aware conflict detection — §2.3 is where usage agreements live ("projects define Usage Agreements governing how they cooperate in a shared environment"), and the §2.12 citation below scopes only the expansion that follows it, not this sentence. **Expanded 2026-07-16** ([requirements.md §2.12](requirements.md)): environment tiers as a first-class field; Reserved/Idle states; named-owner + expiry enforcement; naming & tagging conventions with untagged-quarantine; Environment Request Form + auto-generated Welcome Pack; soft (preemptible) vs hard reservations; priority-ordered contention resolution with escalation; decommissioning process + idle auto-detection (ghost-cost control); forward contention as a calendar leading indicator.

---

## Phases 9–13: Governance & Enterprise-TEM Expansion — ⏳ Planned (2026-07-16)

Added from the gap analysis of the two domain-introduction documents. Capability matrix:
[gap-analysis.md](gap-analysis.md). Requirements: [requirements.md](requirements.md) §2.11, §2.13–§2.16.
Phase 8 remains reserved for the parked AI Copilot / AI-driven Integrations design.

### Phase 9 — Release Governance & Deployment Safety
Release Intake Form + risk scoring; content/scope freeze + Scope Stability KPI; Go/No-Go decision record (joint Test/RM/Sponsor sign-off, dissents); typed gates + evidence + waiver-with-expiry; rollback governance (plan-before-deploy, data-reversibility flags, in-flight authorisation record, rehearsal gate); deployment execution (pre-deploy checklist gate, blue-green/canary, post-deploy verification, traffic ramp); hyper-care window + "declared stable" closeout + retro actions; feature-flag governance (state/drift/lifecycle/audit); read-only "Stable Windows".

### Phase 10 — Test Data Management
Data profiles; Production-snapshot masking/anonymisation; one-way Prod→non-Prod enforcement + post-load leak check; scheduled refreshes + Refresh Cycle Time; data swimlanes / account-range partitioning; masking waivers recorded against the environment.

### Phase 11 — Cost & FinOps
Cost fields (run-rate, funding, chargeback/showback); Cost per Environment-Week; % estate under IaC; cloud auto-stop/start + creation guardrails; ROI model (baseline + 12-month target); optional sustainability reporting.

### Phase 12 — Compliance & Audit Evidence  *(depends on RBAC/OAuth upgrade)*
Regulatory-regime field driving gates/evidence; evidence pack captured at gate time; tamper-evident retention indexed for audit; separation of duties (builder ≠ approver ≠ deployer); control-bypass exception tracking.

### Phase 13 — ITSM Integration & Enterprise Operations
ITSM change-feed (ServiceNow/Helix/JSM) onto the unified schedule; register reconciliation vs CI/CD/ITSM/cloud-tags/IaC; SLA/OLA management with monthly publishing; full environment + release KPI suite with baselining; 5-level maturity model; RACI + decision-rights/escalation matrices; comms plan + weekly bulletin + status page; capacity/demand forecasting; BC/DR for the register/calendar/evidence services.
