# EnvManager — Implementation Roadmap

> Architecture: [architecture.md](architecture.md) | Guide: [../CLAUDE.md](../CLAUDE.md)

---

## Phase Overview

| Phase | Name | Status | Duration | Detail |
|-------|------|--------|----------|--------|
| 0 | Foundations & Guardrails | ✅ Complete | — | See below |
| 1 | Environment Inventory + Shared Booking | ✅ Complete | — | [phases/phase-1.md](phases/phase-1.md) |
| 2 | Change Management | 🚧 Implementation complete, pending MR | 2–3 weeks | [phases/phase-2.md](phases/phase-2.md) |
| 2.5 | Hosts + multi-target CRs (Phase 6 pull-forward) | 🚧 Implementation complete, pending MR | — | [phases/phase-2.md](phases/phase-2.md#phase-25--hosts-and-multi-target-change-requests-phase-6-pull-forward) |
| 3 | Releases, Templates, Enterprise Release, Jira | ⏳ Planned | 6–8 weeks | [phases/phase-3.md](phases/phase-3.md) |
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

## Phase 2: Change Management — 🚧 Implementation complete, pending MR

See [phases/phase-2.md](phases/phase-2.md) for the full commit trail and acceptance checklist.

**Delivered on `feature/phase-2-change-management`** (2026-04-18):
- Lifecycle infrastructure generalised: `booking_lifecycle_template` → `lifecycle_template` with `entity_type` column; `lifecycle_service` works across bookings + change requests + (later) releases
- `ChangeRequest` + `ChangeHistory` domain models; CRUD API at `/api/v1/change-requests`; seed `Simple Approval` + `Emergency` default lifecycles on tenant creation
- Unified `GET /api/v1/environments/{id}/schedule` returning `{bookings, change_requests, deployments: []}`
- Outage × booking conflict preview endpoint + non-blocking form warning
- Frontend: CR list / form / detail / edit dialog pages, generalised admin `LifecycleTemplatesPanel`, `EnvironmentSchedule` FullCalendar tab on `EnvironmentDetail`
- Backend suite: 256 passed

**Deferred**: change-notification consumer (cross-cutting, needed for bookings too); frontend unit tests (Tier 3 modernisation).

---

## Phase 3: Releases & Test Phases — ⏳ Planned

See [phases/phase-3.md](phases/phase-3.md).

**Objectives**: Release Template Library; Project Releases (Major/Minor/Emergency) with configurable workflows; Enterprise Releases (release trains); lifecycle phases and gates; system roles on releases (changing/regression/config_only); release dependencies with smart alerts; release event log; Jira webhook integration for scope import; Gantt/timeline view; Post-Implementation Reviews (PIR).

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
