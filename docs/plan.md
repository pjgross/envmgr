# EnvManager — Implementation Roadmap

> Architecture: [architecture.md](architecture.md) | Guide: [../CLAUDE.md](../CLAUDE.md)

---

## Phase Overview

| Phase | Name | Status | Duration | Detail |
|-------|------|--------|----------|--------|
| 0 | Foundations & Guardrails | ✅ Complete | — | See below |
| 1 | Environment Inventory + Shared Booking | ✅ Complete | — | [phases/phase-1.md](phases/phase-1.md) |
| 2 | Change Management | ✅ Complete (MR !2, merge `3bb3833`, 2026-04-19) | 2–3 weeks | [phases/phase-2.md](phases/phase-2.md) |
| 2.5 | Hosts + multi-target CRs (Phase 6 pull-forward) | ✅ Complete (same MR) | — | [phases/phase-2.md](phases/phase-2.md#phase-25--hosts-and-multi-target-change-requests-phase-6-pull-forward) |
| 3 | Releases, Templates, Enterprise Release, Jira | ✅ Sub-1 merged 2026-04-20/21 (MRs !4–!13); ✅ Sub-2 (Enterprise Releases) merged 2026-04-23 (MR !15, `64c52e3`); ✅ follow-ups MR !17 (gate due dates + timeline diamonds, `a2f55de`) + MR !18 (tenant-configurable change kinds, `0fa2eb5`) on 2026-04-23. Sub-3 (Jira) deferred. | 6–8 weeks | [phases/phase-3.md](phases/phase-3.md) |
| 4 | Build Tracking + CI/CD Deployment Tracking | ⏳ Planned | 6–8 weeks | [phases/phase-4.md](phases/phase-4.md) |
| 5 | DORA Metrics + Health Dashboard + PIR | ⏳ Planned | 4–6 weeks | [phases/phase-5.md](phases/phase-5.md) |
| 6 | Infrastructure Topology | 🟡 Model pulled forward — Terraform/Neo4j/React Flow still pending | 6–8 weeks | [phases/phase-6.md](phases/phase-6.md) |
| 7 | Multi-Project Coordination | ⏳ Planned | 4–6 weeks | [phases/phase-7.md](phases/phase-7.md) |

---

## Phase 0: Foundations & Guardrails — ✅ Complete

**Delivered**:
- Docker Compose environment (PostgreSQL, Neo4j, Redis, NATS)
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

**Sub-project 2 — Enterprise Releases** (✅ merged, MR !15 = `64c52e3`, 2026-04-23). First-class enterprise releases on top of the existing module: `release_kind='enterprise'` with own lifecycle, phases, gates, bookings, events; admission workflow via new `release_membership` table (`pending_request → accepted/rejected/withdrawn` + `accepted → removed`); configurable admission-lockdown marker tagging late-arriving scope for audit (not blocking); state × role permissions for admit/reject/remove; rollup views for systems + scope + timeline + members; HTML report with print; project-side Enterprise tab; admin lifecycle editor extensions. 558 backend tests pass; happy-path integration test at `backend/tests/integration/test_enterprise_release_happy_path.py`. Spec: `docs/superpowers/specs/2026-04-22-enterprise-releases-design.md`. Plan: `docs/superpowers/plans/2026-04-22-enterprise-releases.md`. Smoke checklist: `docs/phases/phase-3-sub2-smoke-checklist.md`. **Post-merge action:** run `backend/scripts/backfill_enterprise_lifecycles.py` once per environment.

**Post-Sub-2 follow-ups** (✅ merged 2026-04-23):
- **MR !17** (`a2f55de`) — Release gates: self-contained due dates + timeline diamonds. Drops `release_gate.test_phase_id`; gates carry required `due_date`. `gate_criterion.due_date` removed — criteria inherit from the parent gate; `overdue_criterion_count` becomes gate-level. `GET /releases/timeline` returns `gates[]`; Gantt renders status-coloured diamonds (slate / green / red / amber). Migration `p3s8gateduedate` backfills `due_date` via chain: linked phase.end_date → MAX(criterion.due_date) → release.target_date → release.created_at. Spec: `docs/superpowers/specs/2026-04-23-release-gate-due-dates-design.md`. Plan: `docs/superpowers/plans/2026-04-23-release-gate-due-dates.md`.
- **MR !18** (`0fa2eb5`) — Tenant-configurable scope change kinds. Admin Scope Change Rules page adds an "Add a new change kind" panel (lowercase slug, ≤20 chars, dedupe). New `GET /tenant/scope-change-rules/kinds` lite endpoint, open to any tenant member. `ScopeItemDialog` / `CustomFieldDefinitionDialog` / `ScopeRollupTab` fetch the live list instead of hardcoding four kinds. No migration.

After MR !18, `main` tip = `0fa2eb5`, latest alembic revision = `p3s8gateduedate`, backend test count = 560 passed + 1 skipped.

**Deferred** (sub-project 3 + Phase 5): Jira webhook integration for scope import; Post-Implementation Reviews (PIR).

---

## Phase 4: CI/CD Deployment Tracking — ⏳ Planned

See [phases/phase-4.md](phases/phase-4.md).

**Objectives**: Build model (git SHA, branch, Jira tickets, pipeline steps); deployment ingestion from GitHub Actions; link deployments to builds, releases, and change requests; environment subsystem version updated on deployment.

---

## Phase 5: DORA Metrics — ⏳ Planned

See [phases/phase-5.md](phases/phase-5.md).

**Objectives**: Incident tracking (manual entry); DORA metrics dashboard (Deployment Frequency, Lead Time, Change Failure Rate, MTTR); Environment Health Check Dashboard (REST push API + status grid); Post-Implementation Reviews; release-level and environment utilization metrics.

---

## Phase 6: Infrastructure Topology — ⏳ Planned

See [phases/phase-6.md](phases/phase-6.md).

**Objectives**: GitHub integration for repository scanning, Terraform and Docker Compose parsers, infrastructure component modeling, Neo4j topology graph, React Flow visualization, environment comparison tool.

---

## Phase 7: Multi-Project Coordination — ⏳ Planned

See [phases/phase-7.md](phases/phase-7.md).

**Objectives**: Project management, usage agreements between projects, environment groups, project-aware conflict detection.
