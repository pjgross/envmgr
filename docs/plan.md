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
| 3 | Releases, Templates, Enterprise Release, Jira | ✅ Sub-project 1 (Core Releases) complete — merged 2026-04-20/21 via MRs !4 (`8f154bd`), !5 (`8327f36` lifecycle perms), !6 (`906ddef` gate criteria), !7 (`8f49c48` MUI confirm sweep), !8 (`2031a76` hotfix). Sub-projects 2 (Enterprise Releases) + 3 (Jira Integration) deferred. | 6–8 weeks | [phases/phase-3.md](phases/phase-3.md) |
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

## Phase 3: Releases & Test Phases — ✅ Sub-project 1 merged to `main`

See [phases/phase-3.md](phases/phase-3.md) for the full MR trail (!4 core + !5–!8 follow-ups).

**Delivered** (MR !4, 2026-04-20, merge `8f154bd`): Release Template Library, Project Releases (Major/Minor/Emergency) with configurable lifecycle, Test Phases, Gates, System Roles on releases, Release Dependencies with date-impact alerts, Release Event Log, Scope items (`ReleaseChange`), release↔booking linking with derived context_tag, calendar + Gantt timeline views, frontend detail pages, admin lifecycle + event-type management.

**Delivered in follow-up MRs (2026-04-20/21)**: unified lifecycle field-permissions across release + booking (!5); individual gate criteria with due dates, assignees, notes, one-way auto-pass, per-release `overdue_criterion_count` (!6); reusable MUI `useConfirm` hook replacing native `confirm()` / `alert()` (!7 + !8 hotfix).

**Deferred** (sub-projects 2 + 3, and Phase 5): Enterprise Releases (release trains); Jira webhook integration for scope import; Post-Implementation Reviews (PIR).

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
