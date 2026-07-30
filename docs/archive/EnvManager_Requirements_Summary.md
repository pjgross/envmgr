# EnvManager — Project Requirements Summary

> **Historical document.** Captures the original requirements/design. Some decisions have since
> changed — notably Neo4j, described here as the topology graph store, was never used and was
> removed on 2026-07-30 ([decisions/2026-07-30-drop-neo4j.md](../decisions/2026-07-30-drop-neo4j.md)).
> [`../../CLAUDE.md`](../../CLAUDE.md) and [`../prod architecture.md`](../prod%20architecture.md) are authoritative for current state.

> A platform to model, track, book, and visualize test environments across on-premise and cloud infrastructure.

---

## 1. Background & Problem Statement

The organization currently manages test environments using a legacy system (with a known data model covering Systems, Builds, Test Environments, Releases, Bookings, and Change Requests). This system needs to be replaced with a modern, event-driven platform that supports multi-project coordination, release management, DORA metrics, and infrastructure topology visualization.

---

## 2. Functional Requirements

### 2.1 Environment Modeling

- Model both **on-premise and cloud** test environments
- Support **long-lived and ephemeral** environments
- Environments are composed of **sub-resources** (hardware, services, databases, cloud components, etc.)
- Environments must be modelable as **infrastructure topology diagrams** (e.g., AWS architecture diagrams showing components, layers, and connections)
- Support hierarchical modeling: **System → Sub-System → Component**
- Environments can be **grouped** into **Environment Groups** (e.g., a Mortgage SIT environment integrated with a Customer SIT environment forms a group)
- An environment can belong to **multiple environment groups** (e.g., a Customer environment used by all customer-facing systems)

### 2.2 Booking System

- Bookings are made at the **environment level** (not sub-resource level)
- Bookings can also be made at the **environment group level** (booking all member environments as one unit)
- Support **coordinated (shared) usage** and **exclusive use** bookings
- When booking, the system must **display existing bookings** in the requested time period
- Booking conflicts are **informational only** — the **approver makes the final decision**
- Bookings must have a **configurable lifecycle** (e.g., draft → submitted → approved/rejected)
- Bookings can be **linked to a release**

### 2.3 Multi-Project Coordination

- Multiple projects can use the **same environment simultaneously**
- Projects must document a **usage agreement** defining how they will cooperate in shared environments
- Usage agreements cover: booking rules, cooperation guidelines, SLAs, and access control

### 2.4 Change Management

- **Changes are raised on sub-resources** (not the environment as a whole)
- Changes track **planned modifications** to test environments
- Changes can be **linked to releases**
- Changes also document when **DevOps pipelines deploy new code** to environments
- Changes must have a **configurable lifecycle** (e.g., one lifecycle option is an approval workflow)

### 2.5 Release Management

- Releases have **test phases**: SIT, UAT, Staging (and others)
- Test environments are **associated with specific test phases** on a release
- Release **scope** is defined by **user stories imported from Jira**, tracked by release and test managers
- Bookings can be **linked to a release and test phase**
- Changes can be **linked to the release** they are responding to

### 2.6 Deployment Tracking

- CI/CD pipeline deployments are **recorded as changes** on environments
- Deployments track: environment, release, commit SHA, build number, deployer, timestamp, status
- Deployments are linked to releases and changes for full traceability

### 2.7 DORA Metrics

The system must provide the following DORA metrics to development teams:

| Metric | Description |
|--------|-------------|
| **Deployment Frequency** | How often code is deployed to environments |
| **Lead Time for Changes** | Time from commit to deployment |
| **Change Failure Rate** | % of deployments that cause incidents |
| **Mean Time to Recovery (MTTR)** | Average time to resolve incidents |

Additional modeling required for DORA:
- Incident tracking (linked to deployments)
- Deployment success/failure status
- Rollback tracking
- Release gate outcomes

### 2.8 Infrastructure Topology Visualization

- The system must be able to **generate architecture diagrams** from environment models (similar to AWS architecture diagrams with components, layers, and connections)
- Support **auto-import from Terraform state files**
- Support **topology snapshots** for point-in-time comparison
- **Drift detection**: compare actual infrastructure vs. Terraform state
- **Dependency/impact analysis**: show what is affected by a change to a component

### 2.9 Notifications & Events

- The system must send **webhooks** and/or **emails** when key events occur, including:
  - Booking created, approved, rejected
  - Booking conflict detected
  - Change request created, approved, started, completed
  - Deployment completed (success or failure)
  - Incident raised or resolved
- Notification targets and templates should be configurable

### 2.10 Integrations

| System | Integration Type |
|--------|-----------------|
| **ServiceNow / Helix CMDB** | Sync environments and configuration items |
| **Terraform** | Parse `.tfstate` files to auto-populate topology |
| **Jira** | Import user stories into release scope |
| **Jenkins / GitLab CI / GitHub Actions** | Ingest deployment events |
| **GitHub / GitLab / Bitbucket** | Link commits to deployments |
| **PagerDuty / Opsgenie / ServiceNow** | Import incidents for DORA metrics |

---

## 3. Non-Functional Requirements

### 3.1 Architecture

- **Event-driven architecture**: all state changes publish events
- **Graph database (Neo4j)**: primary application database for topology and navigation
- **Relational database (PostgreSQL)**: system of record for bookings, changes, releases; also used for reporting
- **Outbox pattern**: reliable event publishing from Postgres
- **CQRS-inspired**: separate read models for reporting to avoid load on the application database
- **Webhooks and email**: event consumers for notifications

### 3.2 Booking Conflict Handling

- Conflicts are **soft** — they do not hard-block a booking
- The system **surfaces conflicts** to the approver who makes the final decision

### 3.3 Lifecycle Configurability

- Both **bookings** and **changes** must support **definable lifecycles**
- One lifecycle option must support an **approval step**

### 3.4 Performance

- API response time < 200ms (95th percentile)
- Support 1,000+ concurrent users
- Handle 10,000+ environments
- Topology diagram generation < 5 seconds for 100 components

### 3.5 Security

- OAuth 2.0 / OIDC authentication
- Role-Based Access Control (RBAC): Admin, Release Manager, Test Manager, Developer, Viewer
- Project-scoped permissions
- API key support for CI/CD integrations
- Audit logging for all sensitive operations

### 3.6 Reliability

- 99.9% uptime SLA
- Graceful degradation (core booking works even if Neo4j is unavailable)
- Daily database backups
- Event replay capability for recovery

---

## 4. Infrastructure & Hosting

| Environment | Hardware | Notes |
|-------------|----------|-------|
| **Development / Test** | Mac Mini — 64 GB RAM | Docker Desktop |
| **Production** | MacBook — 128 GB RAM | Docker Desktop |

- All environments run on **Docker for Desktop**
- Containerized services: API, Frontend, PostgreSQL, Neo4j, Redis, Message Queue

---

## 5. Data Model (Key Entities)

The following entities form the core of the data model (based on the legacy system and new requirements):

| Entity | Description |
|--------|-------------|
| **Environment** | A test environment (on-premise or cloud) |
| **Environment Group** | A collection of environments bookable as one unit |
| **System** | A logical application or system |
| **Sub-System** | A component within a system |
| **Infrastructure Component** | A cloud/on-premise resource (Lambda, S3, VPC, server, etc.) |
| **Infrastructure Layer** | A logical grouping of components for diagram layout |
| **Infrastructure Connection** | A network or data flow between components |
| **Infrastructure Template** | A Terraform / CloudFormation template |
| **Infrastructure Snapshot** | A point-in-time topology capture |
| **Project** | A team or project using environments |
| **Usage Agreement** | Cooperation rules between projects sharing an environment |
| **Booking** | A time-based reservation of an environment or group |
| **Booking Request** | A booking pending approval |
| **Change Request** | A planned change to a sub-resource |
| **Release** | A software release with test phases |
| **Test Phase** | A phase within a release (SIT, UAT, Staging) |
| **Release Gate** | An approval checkpoint between phases |
| **Deployment** | A CI/CD deployment event |
| **Incident** | A production or test incident (for DORA metrics) |
| **Build** | A software build linked to a system and release |

---

## 6. Phased Delivery

| Phase | Scope | Duration |
|-------|-------|----------|
| **0** | Foundations: Docker setup, Postgres, Neo4j, Auth, CI/CD | 2 weeks |
| **1** | Environment Inventory + Shared Booking (MVP) | 6–8 weeks |
| **2** | Change Management on Sub-Resources | 4–6 weeks |
| **3** | Releases, Test Phases, Jira Integration | 4–6 weeks |
| **4** | CI/CD Deployment Tracking | 6–8 weeks |
| **5** | Incidents & DORA Metrics | 4–6 weeks |
| **6** | Infrastructure Topology Visualization | 6–8 weeks |
| **7** | Multi-Project Coordination & Environment Groups | 4–6 weeks |
| **8** | Advanced Features & Optimization | Ongoing |

**Total estimated duration: 36–50 weeks**

---

## 7. Out of Scope (for MVP)

- Mobile application
- AI-powered recommendations
- Cost tracking and optimization
- Compliance auditing
- Advanced analytics beyond DORA metrics

---

## 8. Open Questions / Decisions

- [ ] Which CI/CD tools are in use? (Jenkins, GitLab CI, GitHub Actions, other?)
- [ ] Which CMDB is primary? (ServiceNow or Helix?)
- [ ] Which incident management tool is in use? (PagerDuty, Opsgenie, ServiceNow?)
- [ ] What is the preferred authentication provider? (Keycloak, Auth0, Okta, or existing SSO?)
- [ ] Are there existing Terraform state files that can be used to seed the initial topology?
- [ ] What is the expected number of environments at launch?
- [ ] Are there existing booking/change approval workflows to replicate?

---

*Document generated from project discovery conversations — EnvManager Project*
