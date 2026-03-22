# EnvManager — Implementation Roadmap

> Architecture: [architecture.md](architecture.md) | Guide: [../CLAUDE.md](../CLAUDE.md)

---

## Phase Overview

| Phase | Name | Status | Duration | Detail |
|-------|------|--------|----------|--------|
| 0 | Foundations & Guardrails | ✅ Complete | — | See below |
| 1 | Environment Inventory + Shared Booking | 🔄 In Progress | 6–8 weeks | [phases/phase-1.md](phases/phase-1.md) |
| 2 | Change Management | ⏳ Planned | 4–6 weeks | [phases/phase-2.md](phases/phase-2.md) |
| 3 | Releases, Templates, Enterprise Release, Jira | ⏳ Planned | 6–8 weeks | [phases/phase-3.md](phases/phase-3.md) |
| 4 | Build Tracking + CI/CD Deployment Tracking | ⏳ Planned | 6–8 weeks | [phases/phase-4.md](phases/phase-4.md) |
| 5 | DORA Metrics + Health Dashboard + PIR | ⏳ Planned | 4–6 weeks | [phases/phase-5.md](phases/phase-5.md) |
| 6 | Infrastructure Topology | ⏳ Planned | 6–8 weeks | [phases/phase-6.md](phases/phase-6.md) |
| 7 | Multi-Project Coordination | ⏳ Planned | 4–6 weeks | [phases/phase-7.md](phases/phase-7.md) |

---

## Phase 0: Foundations & Guardrails — ✅ Complete

**Delivered**:
- Docker Compose environment (PostgreSQL, Neo4j, Redis, RabbitMQ)
- FastAPI backend structure (`api`, `core`, `db`, `services`, `workers`)
- React frontend with TypeScript and Material-UI
- Authentication system (JWT, bcrypt, login/logout)
- Database models: `Tenant`, `User`, `CustomFieldDefinition`
- Alembic migrations setup
- Multi-tenancy foundation
- Excel import templates (environment, system, project)
- Excel parser service

---

## Phase 1: Environment Inventory + Shared Booking — 🔄 In Progress

See [phases/phase-1.md](phases/phase-1.md) for the full task checklist.

**Objectives**: Environment/System/SubSystem CRUD, booking system with calendar UI, approval workflow, overlap detection, event publishing, Excel import.

---

## Phase 2: Change Management — ⏳ Planned

See [phases/phase-2.md](phases/phase-2.md).

**Objectives**: Change request (TECR) CRUD on sub-resources, configurable lifecycle per change type, outage flag, unified environment schedule (bookings + TECRs), link changes to releases and deployments, change history and audit trail.

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
