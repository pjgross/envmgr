# EnvManager: Development Prompt for Agent

> **Historical document.** Captures the original requirements/design. Some decisions have since
> changed — notably Neo4j, described here as the topology graph store, was never used and was
> removed on 2026-07-30 ([decisions/2026-07-30-drop-neo4j.md](decisions/2026-07-30-drop-neo4j.md)).
> `CLAUDE.md` and `docs/prod architecture.md` are authoritative for current state.

**Comprehensive System Specification for Test Environment Management Platform**

---

## Executive Summary

Build EnvManager, a comprehensive test environment management platform that enables organizations to model, track, book, and visualize their test environments across on-premise and cloud infrastructure. The system supports multi-project coordination, release management, change tracking, deployment monitoring, DORA metrics reporting, and infrastructure topology visualization.

---

## 1. System Overview

### 1.1 Purpose

EnvManager solves the problem of test environment chaos by providing a centralized platform to:

- Model and track test environments (on-premise and cloud)
- Coordinate environment bookings across multiple projects
- Manage changes to environment configurations and sub-resources
- Track releases, test phases, and deployments
- Monitor DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, MTTR)
- Visualize infrastructure topology (like AWS architecture diagrams)
- Integrate with CMDBs (ServiceNow, Helix), CI/CD pipelines, and Jira

### 1.2 Key Capabilities

- **Environment Inventory**: Catalog all test environments with metadata, ownership, and status
- **Shared Booking System**: Coordinate environment usage across projects with optional exclusivity
- **Multi-Project Coordination**: Define usage agreements between projects sharing environments
- **Environment Groups**: Group multiple environments and book them as a single unit
- **Change Management**: Track planned changes to environments and sub-resources with approval workflows
- **Release Management**: Link bookings to releases with test phases (SIT, UAT, Staging)
- **Deployment Tracking**: Monitor CI/CD deployments and code changes to environments
- **DORA Metrics**: Calculate and report on key DevOps performance indicators
- **Infrastructure Topology**: Model cloud architecture and generate visual diagrams
- **Event-Driven Architecture**: Publish events for all state changes with webhook/email notifications
- **Federated Integration**: Sync data from CMDBs and Infrastructure-as-Code tools (Terraform)

---

## 2. System Architecture

### 2.1 Technology Stack

**Backend:**
- Language: Python 3.11+ or Node.js 18+
- Framework: FastAPI (Python) or Express.js (Node.js)
- Primary Database: PostgreSQL 15+ (system of record for bookings, changes, releases)
- Graph Database: Neo4j 5+ (topology modeling and navigation)
- Event Store: PostgreSQL with Outbox pattern or dedicated event log table
- Message Queue: RabbitMQ or AWS SQS (for async event processing)
- Cache: Redis (for session management and query caching)

**Frontend:**
- Framework: React 18+ with TypeScript
- UI Library: Material-UI or Ant Design
- State Management: Redux Toolkit or Zustand
- Visualization: D3.js or React Flow (for topology diagrams)
- Calendar/Booking: FullCalendar or custom booking component

**Infrastructure:**
- Containerization: Docker
- Orchestration: Kubernetes or Docker Compose
- API Gateway: Kong or AWS API Gateway
- Authentication: OAuth 2.0 / OIDC (Keycloak, Auth0, or Okta)
- Monitoring: Prometheus + Grafana
- Logging: ELK Stack (Elasticsearch, Logstash, Kibana) or CloudWatch

### 2.2 Architecture Pattern

The system follows a CQRS-inspired architecture with event sourcing:

- **PostgreSQL as System of Record**: All transactional data (bookings, changes, releases) stored in Postgres
- **Neo4j as Projection**: Infrastructure topology and relationships projected to Neo4j for graph queries
- **Event Log**: All state changes published as events to an event log (Postgres outbox table)
- **Event Consumers**: Async workers consume events to update Neo4j, send notifications, and update reporting tables
- **Reporting Database**: Denormalized views in Postgres for fast DORA metrics and KPI queries
- **Webhooks**: HTTP callbacks to external systems on key events
- **Email Notifications**: Triggered by events for approvals, conflicts, and status changes

---

## 3. Core Data Model

### 3.1 Primary Entities (PostgreSQL)

- **Environment**: Represents a test environment (e.g., "QA-ENV-01"). Attributes: name, description, type (on-premise/cloud), status, owner, tags, metadata.
- **Environment Group**: A collection of environments that can be booked together (e.g., "Customer Facing Systems"). Supports multi-environment bookings.
- **System**: A logical system or application (e.g., "Payment Service"). Environments belong to systems.
- **Sub-System**: A component within a system (e.g., "API Server", "Database"). Hierarchical relationship with System.
- **Project**: A project or team that uses environments (e.g., "Mobile App Team"). Multiple projects can share environments.
- **Project Environment Usage Agreement**: Defines how projects cooperate when sharing an environment. Includes booking rules, SLAs, and access control.
- **Booking**: A reservation of an environment or environment group for a specific time period. Linked to a project and optionally a release.
- **Booking Request**: A request to book an environment that requires approval. Tracks approval workflow.
- **Change Request**: A planned change to an environment or sub-resource. Includes approval workflow and lifecycle states.
- **Release**: A software release with test phases (SIT, UAT, Staging). Linked to Jira user stories and bookings.
- **Test Phase**: A phase within a release (e.g., "SIT", "UAT"). Has start/end dates and associated environments.
- **Deployment**: A CI/CD deployment event. Tracks code deployments to environments for DORA metrics.
- **Incident**: A production or test incident. Used to calculate Change Failure Rate and MTTR.
- **Infrastructure Component**: A cloud resource (e.g., Lambda, S3, VPC). Part of infrastructure topology.
- **Infrastructure Layer**: A logical grouping of components (e.g., "Frontend", "Backend"). Used for diagram layout.
- **Infrastructure Connection**: A network or data flow between components (e.g., "API Gateway → Lambda").
- **Infrastructure Template**: A Terraform or CloudFormation template. Linked to environments.
- **Infrastructure Snapshot**: A point-in-time capture of infrastructure topology for comparison and drift detection.

### 3.2 Graph Model (Neo4j)

Neo4j stores the infrastructure topology as a graph for efficient traversal and impact analysis:

- **Nodes**: Environment, System, SubSystem, Component, Layer, Template, Project
- **Relationships**: CONTAINS, DEPENDS_ON, CONNECTS_TO, DEPLOYED_FROM, USES_TEMPLATE, BELONGS_TO

---

## 4. Key Features to Implement

### 4.1 Environment Inventory & Modeling

- CRUD operations for environments, systems, and sub-systems
- Support for both on-premise and cloud environments
- Tagging and metadata (owner, cost center, compliance tags)
- Environment status tracking (active, inactive, maintenance, decommissioned)
- Hierarchical system modeling (System → Sub-System → Component)
- Integration with CMDBs (ServiceNow, Helix) for auto-sync

### 4.2 Booking System

- Calendar-based booking interface (similar to meeting room booking)
- Book individual environments or environment groups
- Booking types: Shared (coordinated) or Exclusive
- Overlap detection: Show existing bookings but allow approver to override
- Booking approval workflow with configurable approvers
- Link bookings to releases and test phases
- Recurring bookings (daily, weekly, monthly)
- Booking notifications (email, webhook) on creation, approval, rejection, conflicts

### 4.3 Multi-Project Coordination

- Define projects and assign team members
- Create usage agreements between projects for shared environments
- Usage agreement includes: booking rules, cooperation guidelines, SLAs, access control
- Project-aware conflict detection (check if projects have agreements)
- Dashboard showing which projects are using which environments

### 4.4 Change Management

- Create change requests for environments or sub-resources
- Change types: Configuration change, infrastructure change, code deployment
- Approval workflow with configurable lifecycle states
- Link changes to releases and deployments
- Change impact analysis (show affected components using Neo4j)
- Change history and audit trail
- Notifications on change status updates

### 4.5 Release Management

- Create releases with name, description, and target date
- Define test phases (SIT, UAT, Staging) with start/end dates
- Import user stories from Jira (via Jira API)
- Link bookings to releases and test phases
- Track release progress and environment readiness
- Release gates (approval checkpoints before moving to next phase)
- Release dashboard with status, blockers, and metrics

### 4.6 Deployment Tracking

- Ingest deployment events from CI/CD pipelines (Jenkins, GitLab CI, GitHub Actions)
- Track: deployment timestamp, environment, release, commit SHA, build number, deployer
- Link deployments to changes and releases
- Deployment status: success, failed, rolled back
- Deployment frequency calculation (for DORA metrics)
- Deployment history and rollback tracking

### 4.7 DORA Metrics Reporting

- **Deployment Frequency**: Count deployments per day/week/month
- **Lead Time for Changes**: Time from commit to production deployment
- **Change Failure Rate**: Percentage of deployments causing incidents
- **Mean Time to Recovery (MTTR)**: Average time to resolve incidents
- Dashboards with charts and trend analysis
- Filters by project, environment, release, time period
- Export metrics to CSV or PDF

### 4.8 Infrastructure Topology Visualization

- Model cloud infrastructure (AWS, Azure, GCP) as components and connections
- Auto-import from Terraform state files
- Define layers (frontend, backend, region) for diagram layout
- Generate architecture diagrams (PNG, SVG, PDF) like AWS architecture diagrams
- Interactive web-based topology viewer (zoom, pan, click for details)
- Topology snapshots for point-in-time comparison
- Drift detection: Compare actual infrastructure vs. Terraform state
- Dependency analysis: Show what depends on a component
- Health status visualization (color-code components by health)

### 4.9 Event-Driven Architecture

- Publish events for all state changes (booking created, change approved, deployment completed)
- Event schema with versioning (v1, v2, etc.)
- Outbox pattern for reliable event publishing
- Event consumers for: Neo4j updates, notifications, reporting table updates
- Webhook support: POST events to external URLs
- Email notifications with templates (booking approval, conflict alert, deployment failure)
- Event replay for debugging and recovery

### 4.10 Integrations

- **CMDB Integration**: Sync environments from ServiceNow or Helix CMDB
- **Jira Integration**: Import user stories and link to releases
- **CI/CD Integration**: Ingest deployment events from Jenkins, GitLab CI, GitHub Actions
- **Terraform Integration**: Parse .tfstate files to populate infrastructure topology
- **Source Control Integration**: Link commits to deployments (GitHub, GitLab, Bitbucket)
- **Incident Management Integration**: Import incidents from PagerDuty, Opsgenie, or ServiceNow

---

## 5. API Specification

### 5.1 Core API Endpoints

#### Environments
- `GET /api/environments` - List all environments
- `GET /api/environments/{id}` - Get environment details
- `POST /api/environments` - Create environment
- `PUT /api/environments/{id}` - Update environment
- `DELETE /api/environments/{id}` - Delete environment
- `GET /api/environments/{id}/bookings` - Get bookings for environment
- `GET /api/environments/{id}/topology` - Get infrastructure topology

#### Bookings
- `GET /api/bookings` - List all bookings
- `GET /api/bookings/{id}` - Get booking details
- `POST /api/bookings` - Create booking
- `PUT /api/bookings/{id}` - Update booking
- `DELETE /api/bookings/{id}` - Cancel booking
- `POST /api/bookings/{id}/approve` - Approve booking
- `POST /api/bookings/{id}/reject` - Reject booking
- `GET /api/bookings/conflicts` - Check for booking conflicts

#### Changes
- `GET /api/changes` - List all change requests
- `GET /api/changes/{id}` - Get change details
- `POST /api/changes` - Create change request
- `PUT /api/changes/{id}` - Update change request
- `POST /api/changes/{id}/approve` - Approve change
- `POST /api/changes/{id}/reject` - Reject change
- `GET /api/changes/{id}/impact` - Get change impact analysis

#### Releases
- `GET /api/releases` - List all releases
- `GET /api/releases/{id}` - Get release details
- `POST /api/releases` - Create release
- `PUT /api/releases/{id}` - Update release
- `GET /api/releases/{id}/phases` - Get test phases
- `POST /api/releases/{id}/phases` - Create test phase
- `GET /api/releases/{id}/deployments` - Get deployments for release

#### Deployments
- `GET /api/deployments` - List all deployments
- `GET /api/deployments/{id}` - Get deployment details
- `POST /api/deployments` - Record deployment
- `GET /api/deployments/frequency` - Get deployment frequency metrics

#### DORA Metrics
- `GET /api/metrics/dora` - Get all DORA metrics
- `GET /api/metrics/dora/deployment-frequency` - Get deployment frequency
- `GET /api/metrics/dora/lead-time` - Get lead time for changes
- `GET /api/metrics/dora/change-failure-rate` - Get change failure rate
- `GET /api/metrics/dora/mttr` - Get mean time to recovery

#### Infrastructure Topology
- `GET /api/topology/components` - List all components
- `POST /api/topology/components` - Create component
- `GET /api/topology/connections` - List all connections
- `POST /api/topology/connections` - Create connection
- `POST /api/topology/import/terraform` - Import from Terraform state
- `POST /api/topology/diagram` - Generate topology diagram
- `POST /api/topology/snapshots` - Create topology snapshot
- `POST /api/topology/compare` - Compare two snapshots

### 5.2 Authentication & Authorization

- OAuth 2.0 / OIDC for authentication
- Role-Based Access Control (RBAC): Admin, Release Manager, Test Manager, Developer, Viewer
- Project-based permissions (users can only see/modify their project's data)
- API key authentication for CI/CD integrations
- JWT tokens for session management

---

## 6. Database Schema

The complete PostgreSQL schema is provided in the attached "infrastructure-topology-schema" document. Key tables include:

- `test_environment`: Core environment data
- `environment_group`: Groups of environments
- `system`: Logical systems/applications
- `sub_system`: Components within systems
- `project`: Projects/teams using environments
- `project_environment_usage_agreement`: Cooperation agreements
- `environment_booking`: Booking records
- `environment_booking_request`: Booking approval workflow
- `environment_change_request`: Change management
- `release`: Software releases
- `test_phase`: Release test phases
- `deployment`: CI/CD deployment events
- `incident`: Production/test incidents
- `infrastructure_component`: Cloud resources
- `infrastructure_layer`: Diagram layers
- `infrastructure_connection`: Component connections
- `infrastructure_template`: IaC templates
- `infrastructure_snapshot`: Topology snapshots
- `infrastructure_change_history`: Topology audit trail
- `event_log`: Event sourcing table

---

## 7. Phased Implementation Plan

### Phase 0: Foundations & Guardrails (2 weeks)
- Set up development environment (Docker, Postgres, Neo4j, Redis)
- Initialize backend project (FastAPI or Express.js)
- Initialize frontend project (React + TypeScript)
- Set up CI/CD pipeline
- Configure authentication (OAuth 2.0)
- Create base database schema

### Phase 1: Environment Inventory + Shared Booking (6-8 weeks)
- Implement environment CRUD operations
- Implement system and sub-system modeling
- Build booking system with calendar UI
- Implement booking approval workflow
- Add overlap detection (soft conflicts)
- Create basic event publishing
- Build environment dashboard

### Phase 2: Change Management on Sub-Resources (4-6 weeks)
- Implement change request CRUD
- Build change approval workflow
- Link changes to environments and sub-resources
- Add change history and audit trail
- Implement change notifications

### Phase 3: Releases, Test Phases, and Booking Context (4-6 weeks)
- Implement release CRUD operations
- Add test phase management
- Integrate with Jira API for user story import
- Link bookings to releases
- Build release dashboard
- Add release gates

### Phase 4: CI/CD Deployment Tracking (6-8 weeks)
- Build deployment ingestion API
- Integrate with CI/CD tools (Jenkins, GitLab CI, GitHub Actions)
- Link deployments to releases and changes
- Track deployment status and failures
- Build deployment history view

### Phase 5: DORA Metrics (4-6 weeks)
- Implement incident tracking
- Calculate Deployment Frequency
- Calculate Lead Time for Changes
- Calculate Change Failure Rate
- Calculate MTTR
- Build DORA metrics dashboard
- Add export functionality (CSV, PDF)

### Phase 6: Infrastructure Topology Visualization (6-8 weeks)
- Implement infrastructure component modeling
- Build Terraform state parser
- Populate Neo4j with topology data
- Implement topology snapshot and comparison
- Build diagram generation service (Graphviz)
- Create interactive topology viewer (D3.js or React Flow)
- Add drift detection

### Phase 7: Multi-Project Coordination (4-6 weeks)
- Implement project management
- Build usage agreement system
- Add project-aware conflict detection
- Implement environment groups
- Build project dashboard

### Phase 8: Advanced Features & Optimization (Ongoing)
- Performance optimization
- Advanced reporting and analytics
- Mobile app (optional)
- AI-powered recommendations (optimal booking times, resource optimization)
- Cost tracking and optimization
- Compliance auditing

---

## 8. Non-Functional Requirements

### Performance
- API response time < 200ms for 95th percentile
- Support 1000+ concurrent users
- Handle 10,000+ environments
- Topology diagram generation < 5 seconds for 100 components

### Scalability
- Horizontal scaling for API servers
- Database read replicas for reporting queries
- Event processing queue for async operations
- CDN for static assets and generated diagrams

### Security
- OAuth 2.0 / OIDC authentication
- Role-Based Access Control (RBAC)
- API rate limiting
- SQL injection prevention (parameterized queries)
- XSS protection
- HTTPS only
- Audit logging for all sensitive operations

### Reliability
- Database backups (daily)
- Event replay capability for recovery
- Health check endpoints
- 99.9% uptime SLA
- Graceful degradation (if Neo4j is down, core booking still works)

### Observability
- Structured logging (JSON format)
- Metrics collection (Prometheus)
- Distributed tracing (Jaeger or Zipkin)
- Alerting for critical errors
- Dashboard for system health (Grafana)

---

## 9. Testing Requirements

- Unit tests for all business logic (80%+ coverage)
- Integration tests for API endpoints
- End-to-end tests for critical user flows (booking, approval, deployment)
- Load testing for API performance
- Security testing (OWASP Top 10)
- Database migration testing
- Event processing testing (ensure events are published and consumed correctly)

---

## 10. Documentation Requirements

- API documentation (OpenAPI/Swagger)
- Database schema documentation (ER diagrams)
- Architecture diagrams (system context, container, component)
- User guide (how to book environments, create releases, etc.)
- Admin guide (how to configure integrations, manage users)
- Developer guide (how to set up dev environment, contribute code)
- Runbook for operations (deployment, monitoring, troubleshooting)

---

## 11. Deliverables

- Source code (backend + frontend) in Git repository
- Docker Compose file for local development
- Kubernetes manifests for production deployment
- Database migration scripts
- API documentation (Swagger UI)
- User documentation
- Admin documentation
- Test suite with 80%+ coverage
- CI/CD pipeline configuration
- Monitoring and alerting setup

---

## 12. Success Criteria

- All Phase 1-7 features implemented and tested
- API response time < 200ms for 95th percentile
- System supports 1000+ concurrent users
- DORA metrics calculated correctly and match manual calculations
- Topology diagrams generated successfully from Terraform state
- Integration with Jira, CI/CD, and CMDB working
- User acceptance testing passed by 5+ test users
- Security audit passed (no critical vulnerabilities)
- Documentation complete and reviewed
- System deployed to production and stable for 2 weeks

---

## 13. Additional Context

This system is designed to be the single source of truth for test environment management. It replaces spreadsheets, wikis, and ad-hoc communication channels with a structured, auditable, and automated platform.

The infrastructure topology visualization feature is a key differentiator. It enables teams to:

- Automatically document their cloud architecture
- Detect drift between Terraform state and actual infrastructure
- Perform impact analysis before making changes
- Visualize dependencies and data flows
- Track infrastructure changes over time

The event-driven architecture ensures that all stakeholders are notified of important events (bookings, approvals, deployments, incidents) in real-time via webhooks and email.

The DORA metrics reporting provides development teams with actionable insights into their DevOps performance and helps identify bottlenecks in the delivery pipeline.

---

## 14. References

- PostgreSQL Schema: See attached "infrastructure-topology-schema" document
- Architecture Diagrams: See attached "EnvManager_Architecture_Guide.docx"
- Implementation Roadmap: See attached "EnvManager_Implementation_Roadmap.docx"
- DORA Metrics: https://cloud.google.com/blog/products/devops-sre/using-the-four-keys-to-measure-your-devops-performance
- Terraform State Format: https://www.terraform.io/docs/language/state/index.html
- Neo4j Graph Data Modeling: https://neo4j.com/developer/guide-data-modeling/
- Event Sourcing Pattern: https://martinfowler.com/eaaDev/EventSourcing.html
- Outbox Pattern: https://microservices.io/patterns/data/transactional-outbox.html

---

**End of Specification**
