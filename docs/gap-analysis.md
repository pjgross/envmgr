# EnvManager — Capability Gap Analysis

> **Source of truth for scope coverage.** Compares the two domain-introduction documents
> (`Release Management Introduction.docx`, `Environment Management Introduction.docx`) against
> the planned functionality in [requirements.md](requirements.md) and [plan.md](plan.md).
> Produced 2026-07-16. This is a **living checklist** — update the Status column as items land.

## Method & legend

Each capability the two documents describe (or clearly imply) is listed and rated against what
EnvManager has built or planned. The intro docs describe a full **governance discipline**;
EnvManager already covers the **transactional core** (register/inventory, calendar/schedule,
bookings, releases with phases+gates, enterprise releases, builds, deployments, DORA, topology).
The value of this document is the delta.

| Status | Meaning |
|--------|---------|
| ✅ | Covered — built or explicitly planned in a phase |
| 🟡 | Partial — some aspect exists; the doc expects more |
| ❌ | Gap — not planned |
| 🎯 | **Newly in scope** (2026-07-16 decision) — was excluded, now targeted at a phase |
| 🅿️ | Deferred by prior decision (Jira, RBAC/OAuth) |

**2026-07-16 scope decision:** Test Data Management, Compliance/audit evidence, Cost tracking, and
ITSM integration — previously listed under `requirements.md §6 Out of Scope` — are now **in scope**
and mapped to new phases below.

New phases introduced by this analysis (Phase 8 remains reserved for the parked AI Copilot work):

| Phase | Name | Theme |
|-------|------|-------|
| **9** | Release Governance & Deployment Safety | intake, go/no-go, freeze, rollback, hyper-care, flags, deploy patterns |
| **10** | Test Data Management | 🎯 masking, one-way refresh, data profiles, swimlanes |
| **11** | Cost & FinOps | 🎯 cost-per-env, chargeback, ghost-cost, ROI, auto-stop/start |
| **12** | Compliance & Audit Evidence | 🎯 regulatory regime, evidence pack, retention, separation of duties |
| **13** | ITSM Integration & Enterprise Ops | 🎯 change feed, reconciliation, SLA/OLA, maturity, comms |
| **7 (expanded)** | Environment Lifecycle & Governance | tiers, decommission, welcome pack, priority contention |
| **6 (expanded)** | Topology + Environment Drift | drift detection & sync vs Production |

---

## A. Release Management

### A1. Data model / concepts
| Capability | Status | Where |
|---|---|---|
| Release as first-class record (name, category, train, stable ID) | ✅ | Phase 3 |
| Enterprise Release grouping ≥2 Project Releases | ✅ | Phase 3 Sub-2 |
| Standalone Project Release on own cadence | ✅ | Phase 3 |
| Release Categories (Major/Minor/Emergency) — configurable/renameable | ✅ | Phase 3 |
| Categories: Maintenance, Standard | 🟡 | configurable — add as tenant categories |
| Per-category lifecycle = ordered Phases + Gates | ✅ | Phase 3 |
| Release Templates (clone, enforce structure) | ✅ | Phase 3 |
| Release-Changes / scope items (stories, defects, change records) | ✅ | Phase 3 |
| Components + versions in scope, **plus explicit exclusions/deferrals** | 🟡 | Phase 9 |
| Release Systems / product lines / trains | ✅ | Phase 3 |
| Release name as FK linking evidence, rollback, sign-offs, reports | 🟡 | Phase 9/12 |
| Naming/versioning convention enforcement (RETAIL-MAJOR-2026.1) | ❌ | Phase 9 |
| Release status/state field (planned…deployed…hyper-care…closed) | ✅ | Phase 3 |
| Degraded/Failed states driven by monitoring | ❌ | Phase 9 |

### A2. Planning & register
| Capability | Status | Where |
|---|---|---|
| Release Register as single system of record | ✅ | Phase 3 |
| Register minimum fields: risk profile, approvals/evidence, cost, compliance | 🟡 | Phase 9/11/12 |
| Every release owned by a **named human** (name+email, not "the team") | 🟡 | Phase 9 |
| Cancelled/deferred releases recorded **with reason** | 🟡 | Phase 9 |
| Reconcile register vs CI/CD, ITSM, project trackers on cadence | ❌ | Phase 13 |
| Timeline milestones: content-freeze, go/no-go, hyper-care end | 🟡 | Phase 9 |
| Release cost estimate + chargeback/showback | 🎯 | Phase 11 |
| Capacity planning / demand forecasting (forward demand curve) | ❌ | Phase 13 |
| Release allocation mix (feature/tech-debt/fixes reservation) | ❌ | Phase 13 |

### A3. Intake & scope management
| Capability | Status | Where |
|---|---|---|
| **Release Intake Form** ("front door"), single channel | ❌ | Phase 9 |
| Intake completeness validation; return incomplete for clarification | ❌ | Phase 9 |
| Intake lead times per category | ❌ | Phase 9 |
| **Risk classification / scoring** at intake → drives gates+approvals | ❌ | Phase 9 |
| Content/scope **freeze** at milestone; lock components+versions | 🟡 | Phase 9 (admission-lockdown is adjacent) |
| Formal exception approval for post-freeze scope; record exceptions | 🟡 | Phase 9 |
| **Scope Stability** metric (% unchanged window-start → deploy) | ❌ | Phase 9 |
| Archive stale intakes; stale-intake-rate KPI | ❌ | Phase 9 |

### A4. Workflow / lifecycle
| Capability | Status | Where |
|---|---|---|
| Six-stage lifecycle Plan→Build→Validate→Deploy→Operate→Improve | 🟡 | Phase 9 (configurable today; Operate/Improve not modelled) |
| Entry/exit criteria per stage; block advance | ✅ | Phase 3 (gates+criteria) |
| Build-stage artefact rules (naming, version stamping, signing) | ❌ | Phase 9 |
| Immutable versioned artefacts; same artefact through all envs | ❌ | Phase 9 |
| Promotion through environment path, each gated on prior stage | 🟡 | Phase 4 preflight is adjacent; Phase 9 |
| Fully-automated fast path vs long gated path per category | 🟡 | Phase 9 |
| Multi-component release coordination (per-component promotion state) | 🟡 | Phase 9 |
| Operate/hyper-care tracked until "declared stable" or rolled back | ❌ | Phase 9 |

### A5. Approvals / gates
| Capability | Status | Where |
|---|---|---|
| Gates with named owner, defined input/output | ✅ | Phase 3 |
| Standard gate **types** (functional, NFR, security, license, a11y, ops-readiness) | 🟡 | Phase 9 |
| Per-gate failure behaviour: block / warn / accept-with-exception | 🟡 | Phase 9 |
| **Gate evidence capture** attached to the release record | ❌ | Phase 12 |
| **Go/No-Go forum** — joint Test/RM/Sponsor sign-off; any "no" decisive | ❌ | Phase 9 |
| Go/no-go decision recorded (go/conditional/no-go, rationale, dissents) | ❌ | Phase 9 |
| Gate **waiver/exception** workflow (reason, approver, expiry, remediation) | 🟡 | Phase 9 (override exists) |
| "Have you tested the rollback?" as a required go/no-go question | ❌ | Phase 9 |
| **Separation of duties** (builder ≠ approver ≠ deployer) | 🅿️→🎯 | Phase 12 (needs RBAC) |

### A6. Dependencies
| Capability | Status | Where |
|---|---|---|
| Dependencies between releases (A before B), visible on calendar | ✅ | Phase 3 |
| Slip in one release propagated to downstream | ✅ | Phase 3 (smart alerts) |
| Cross-release/cross-team dependency captured as risk at intake | 🟡 | Phase 9 |
| Project lineage on work items (Epic→stories, many-to-many) | 🅿️ | Phase 3 Sub-3 (Jira, deferred) |
| Two-way project↔release visibility | 🅿️ | depends on Jira |

### A7. Deployment execution & rollback
| Capability | Status | Where |
|---|---|---|
| Deployment tracking (env, build, commit, status incl. rolled_back) | ✅ | Phase 4 |
| Auto-raise Change Request from CI/CD deployment | ✅ | Phase 4 |
| `can-deploy` preflight gate | ✅ | Phase 4 Sub-3 |
| Deployment plan + window on the release record | 🟡 | Phase 9 |
| Pre-deployment checklist as a required gate | 🟡 | Phase 9 |
| Deploy patterns: rolling / blue-green / canary per category | ❌ | Phase 9 |
| Post-deployment verification (smoke/synthetic) → rollback trigger | ❌ | Phase 9 |
| Traffic-ramp schedule with auto-pause on adverse signal | ❌ | Phase 9 |
| **Documented rollback plan agreed before deploy**, per release | ❌ | Phase 9 |
| Data-reversibility flags surfaced at Plan time | ❌ | Phase 9 |
| In-flight rollback authorisation recorded (time, trigger, rationale) | ❌ | Phase 9 |
| Rollback rehearsal tracked as a gate (≥quarterly for critical) | ❌ | Phase 9 |
| Roll-forward / hotfix fast path | 🟡 | Phase 3 (Emergency lifecycle) |

### A8. Hyper-care / closeout / improvement
| Capability | Status | Where |
|---|---|---|
| Hyper-care window sized to the release | ❌ | Phase 9 |
| Explicit "declared stable" closeout decision (Operate→Improve) | ❌ | Phase 9 |
| Closeout: ops ownership transitioned; outcome recorded | ❌ | Phase 9 |
| Retrospective producing owned, dated actions | 🟡 | Phase 5 (PIR is adjacent) |
| Post-Implementation Reviews (PIR) | ✅ | Phase 5 (planned) |

### A9. Feature flags & progressive delivery
| Capability | Status | Where |
|---|---|---|
| Flag state per environment + flag drift across tiers | ❌ | Phase 9 |
| Stale-flag tracking; flag lifecycle policy (removal-by date) | ❌ | Phase 9 |
| Production-affecting flag-change audit → evidence pack | ❌ | Phase 9/12 |
| Canary / blue-green / progressive rollout as governed patterns | ❌ | Phase 9 |
| Feature-flag platform integration (LaunchDarkly, Unleash, Split) | ❌ | Phase 9 |

---

## B. Environment Management

### B1. Inventory / register
| Capability | Status | Where |
|---|---|---|
| Environment as first-class product with a lifecycle | ✅ | Phase 1 |
| Environment Register / inventory (system of record) | ✅ | Phase 1 |
| Components + versions installed per environment | ✅ | Phase 1 |
| Stubs / mocks / virtual services (`EnvironmentSystem.status=mock`) | ✅ | Phase 1 |
| Upstream/downstream + integration touchpoints per env | ✅ | Phase 1 (dependencies) |
| Environment **tiers** as first-class (Dev/SIT/UAT/Pre-Prod/Perf/Training) | 🟡 | Phase 7 |
| Status Active/**Reserved**/**Idle**/Decommissioning | 🟡 | Phase 7 (Reserved/Idle derived from bookings today) |
| Hosting platform type field (on-prem/AWS/Azure/GCP/SaaS) | 🟡 | Phase 7 |
| Shared vs dedicated as an environment attribute | 🟡 | Phase 7 |
| **Named human owner** enforced (reject "the platform team") | 🟡 | Phase 7 |
| **Data profile** (synthetic/masked/subset, classification, refresh date) | 🎯 | Phase 10 |
| **Cost** fields (run-rate, funding source, chargeback model) | 🎯 | Phase 11 |
| **Lifecycle** (provisioning date, expiry/review, decommission trigger) | ❌ | Phase 7 |
| **Compliance** (data classification, regime, last security review) | 🎯 | Phase 12 |
| Reconcile register vs CMDB / cloud tags / IaC state monthly | 🎯 | Phase 13 |
| Idle / over-utilised / scheduled-for-decommission report | ❌ | Phase 7/11 |
| **Naming & tagging conventions**; mandatory tags; untagged quarantine | ❌ | Phase 7 |

### B2. Booking / reservation
| Capability | Status | Where |
|---|---|---|
| Bookings (shared/exclusive, recurring), env or group level | ✅ | Phase 1 |
| Soft conflict detection (informational) | ✅ | Phase 1 |
| Configurable booking lifecycle with approval step | ✅ | Phase 1 |
| Booking↔release/test-phase linking with derived context tag | ✅ | Phase 3 |
| **Environment Request Form** ("Front Door") with mandatory fields + validation | 🟡 | Phase 7 |
| Time-slot booking (half-day / sprint / release cycle) | 🟡 | Phase 7 |
| **Soft (preemptible) vs hard (protected) reservations** | ❌ | Phase 7 |
| **Welcome Pack** auto-generated on handoff | ❌ | Phase 7 |
| **Booking honour** tracking (started on time, ran full duration) | ❌ | Phase 5/7 |
| **Utilisation against bookings** (flag booked-but-unused) | ❌ | Phase 5/11 |
| Archive stale request forms; stale-request KPI | ❌ | Phase 7 |

### B3. Scheduling / calendar / contention
| Capability | Status | Where |
|---|---|---|
| Master Environment Calendar / unified schedule | ✅ | Phase 2 |
| Schedule overlays bookings + change requests + deployments | ✅ | Phase 2/4 |
| Schedule overlays **data refreshes** | 🎯 | Phase 10 |
| Schedule overlays **infra/hardware changes from ITSM** | 🎯 | Phase 13 |
| Integrate env calendar with **Release Calendar** as one view | 🟡 | Phase 7/9 |
| Code-freeze / release-train / prod-change windows synced | ❌ | Phase 9/13 |
| **Forward contention as a leading indicator** (weeks out) | ❌ | Phase 7 |
| **Read-only / "Stable Windows"** (no deploys allowed) | ❌ | Phase 9 (extend can-deploy) |
| Cloud auto-stop / auto-start schedules | 🎯 | Phase 11 |
| Detect booking conflicts on shared env | ✅ | Phase 1 |
| **Configured priority order** (not first-come-first-served) | ❌ | Phase 7 |
| Priority tiers on bookings; escalation to Release Manager | ❌ | Phase 7 |
| Conflict-resolution path with named owner + response window | ❌ | Phase 7 |

### B4. Drift / config management
| Capability | Status | Where |
|---|---|---|
| **Environment Drift detection vs Production** | 🎯 | Phase 6 |
| Production-change trigger → notify Environment Manager | 🎯 | Phase 6/13 |
| Impact assessment: which test envs now out of sync | 🟡 | Phase 6 |
| Drift sync scheduling + post-sync parity verification | 🎯 | Phase 6 |
| `verify` endpoint (dependency presence) | ✅ | Phase 1 |
| % of estate under IaC (rebuildable) | 🎯 | Phase 11/13 |
| Change notice periods for shared-env config changes | ❌ | Phase 7 |

### B5. Topology
| Capability | Status | Where |
|---|---|---|
| Interactive topology viewer (React Flow), layers, snapshots, drift | ✅ | Phase 6 (planned) |
| Neo4j graph + impact analysis | ✅ | Phase 6 (planned) |
| **Code-promotion & data-refresh direction** as first-class flows | 🟡 | Phase 6 |
| Ownership boundaries + feedback flows on the diagram | 🟡 | Phase 6 |
| Version-controlled topology + quarterly review | ❌ | Phase 6 |

### B6. Health / incidents
| Capability | Status | Where |
|---|---|---|
| Health-check push API + Health Check Dashboard | ✅ | Phase 5 (planned) |
| Incident tracking (manual → API/webhook later) | ✅ | Phase 5 / Post-7 |
| Log environment faults as TECR (change request) | ✅ | Phase 2 |
| **Scheduled health checks / sanity scripts** (built-in) | ❌ | Phase 5 |
| **Auto-raise TECR from monitoring-detected faults** | ❌ | Phase 5/13 |
| Triage: environment incident vs software bug | 🟡 | Phase 5 |
| Track env incidents separately + trend | 🟡 | Phase 5 |
| **Production-incident reproduction environments** (prod-snapshot restore) | ❌ | Phase 7/10 |
| Snapshots before destructive tests | ❌ | Phase 10 |

### B7. Test Data Management 🎯 (Phase 10 — newly in scope)
| Capability | Status | Where |
|---|---|---|
| Data profile per environment/request | 🎯 | Phase 10 |
| Snapshot from Production + masking/anonymisation of PII | 🎯 | Phase 10 |
| Enforce one-way flow Production → non-Production | 🎯 | Phase 10 |
| Verification/sanity check that no real data leaked | 🎯 | Phase 10 |
| Scheduled data refreshes per tier; record last-refresh date | 🎯 | Phase 10 |
| Refresh Cycle Time metric; waive/defer with owner+escalation | 🎯 | Phase 10 |
| Data swimlanes / account-range partitioning; Team/Tenant isolation | 🎯 | Phase 10 |
| Record masking/access-control **waivers** against the environment | 🎯 | Phase 10/12 |

---

## C. Cross-cutting governance (both docs, mostly core)

| Capability | Status | Where |
|---|---|---|
| Role model (EM, RM, Test Manager, TDM, Developer, Ops, Sponsor…) | 🟡 | roles defined; RBAC enforcement 🅿️ |
| **RACI matrix** across lifecycle stages | ❌ | Phase 12/13 (needs RBAC) |
| **Decision-rights / escalation matrix** (one owner + response window) | ❌ | Phase 13 |
| **Separation of duties** enforced by tooling | 🅿️→🎯 | Phase 12 (needs RBAC) |
| **SLA / OLA management** (define, track, publish monthly; OLA-under-SLA) | 🎯 | Phase 13 |
| KPI **baselining** at implementation start; report deltas | ❌ | Phase 5/13 |
| **5-level Maturity Model** + self-assessment questionnaire | 🎯 | Phase 13 |
| **ROI model** (benefit vs cost, payback) | 🎯 | Phase 11 |
| Stakeholder Communications Plan + **weekly bulletin** + status page | 🟡 | Phase 13 |
| **TEM / RM function Risk Register** | ❌ | Phase 13 |
| Notification channels (email + webhook), configurable templates | ✅ | planned |
| Audit trail on entities (event log, change history) | ✅ | Phase 1+ |
| **Evidence pack captured at gate; regulatory regime field; retention** | 🎯 | Phase 12 |
| BC/DR for the register/calendar/evidence service (RTO/RPO) | ❌ | Phase 13 |

---

## D. Integrations

| Integration | Status | Where |
|---|---|---|
| CI/CD — GitHub Actions | ✅ | Phase 4 |
| CI/CD — GitLab (dogfooding) | ✅ | Phase 4 pre-work |
| CI/CD — multi-platform (Jenkins/Azure DevOps/Harness/Argo…) | 🟡 | GitHub-first by decision; revisit Phase 9/13 |
| Jira (ALM / scope import / Epic lineage) | 🅿️ | Phase 3 Sub-3 (deferred) |
| **ITSM (ServiceNow / BMC Helix / JSM)** — change feed + reconciliation | 🎯 | Phase 13 |
| Feature-flag platforms | ❌ | Phase 9 |
| Observability (Datadog/Splunk/Grafana) — release-dimension tags | 🟡 | Phase 5/9 (Prometheus/Grafana for infra today) |
| TDM / masking tooling | 🎯 | Phase 10 |
| Cloud providers (auto-stop/start, tags, cost/billing) | 🎯 | Phase 11 |
| PMO / portfolio planning (demand feed) | ❌ | Phase 13 |

---

## E. Remaining out of scope (unchanged)

Per `requirements.md §6`, still explicitly excluded after the 2026-07-16 decision:
- Mobile application
- AI-powered recommendations / **Phase 8 advanced AI features** (parked design captured separately)
- Advanced analytics beyond DORA + the KPI set above
- **Full CMDB two-way sync** (ITSM *change-feed* integration IS now in scope — Phase 13 — but bidirectional CMDB reconciliation as a source-of-truth is not)
- Environment automation / TECR-triggered provisioning pipelines (external customer tooling drives provisioning; EnvManager records, does not provision)

Specialised release types from the release doc (regulated / vendor / mobile / migration / AI-ML / chaos-rehearsal) are treated as **category modifiers** layered on the Phase 9 governance model where needed, not separate phases.
