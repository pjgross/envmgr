# Phase 6: Infrastructure Topology

> Status: 🟡 **Substantially shipped.** Model + host-aware CRs (Phase 2.5), both IaC parsers, the topology API and the React Flow visualisation are all done; environment comparison shipped 2026-08-03. Three sub-projects remain — see *What is actually left* below. | Roadmap: [../plan.md](../plan.md)
> Duration: 6–8 weeks (remainder) | Starts after Phase 5 completion

---

## Already delivered (via Phase 2.5 pull-forward on MR !2)

See [phase-2.md §Phase 2.5](phase-2.md#phase-25--hosts-and-multi-target-change-requests-phase-6-pull-forward) for full detail.

- `InfrastructureComponent` model (Phase 6-shaped: `component_type`, `provider`, `region`, `source`, `external_id`, `tags`) — already ready for Terraform / Docker Compose rows via the `source` enum.
- `environment_subsystem_host` M:M junction — deployed subsystem ↔ host (replicas, multi-AZ).
- `change_request_host` + `change_request_environment` junctions — CRs target any combination, with `derived_environment_ids` auto-surfacing envs whose subsystems run on the selected hosts.
- `/api/v1/infrastructure-components` CRUD + `/impact` endpoint + env-subsystem-host PUT/GET endpoints.
- Frontend: Hosts CRUD page, host-impact panel + booking Gantt on CR forms, per-env host attach dialog.

**Do not re-add any of the above in Phase 6 proper.** The remaining Phase 6 tasks below write *into* these existing tables rather than introducing new ones.

---

## What is actually left — corrected 2026-08-03

The task list below was two-thirds wrong. Verified against the code, not the roadmap:

| Previously listed as pending | Reality |
|---|---|
| Terraform parser | **Shipped** — `terraform_import_service.py`, `POST /import/terraform`, UI on System detail |
| Docker Compose parser | **Shipped** — `docker_compose_import_service.py`, writes `ComponentDependency` with `source=docker_compose` |
| Topology API endpoints | **Shipped** — `/systems/{id}/topology`, `/environments/{id}/topology` |
| React Flow topology diagram | **Shipped** — `TopologyCanvas` + ELK, focus, filter, collapse |
| Environment topology page | **Shipped** — env-topology SP1–SP3 |
| GitHub repo link on System detail | **Shipped** — the field exists and renders |
| Neo4j sync consumer | **Obsolete** — Neo4j removed, see [decisions/2026-07-30-drop-neo4j.md](../decisions/2026-07-30-drop-neo4j.md) |

The remainder is four independent sub-projects, each getting its own spec:

### 1. Environment comparison — ✅ shipped 2026-08-03

Diff two environments across presence (systems and subsystems), mocked-vs-real, deployed
version, and host shape. `GET /api/v1/environments/compare?left=&right=` plus a standalone
page at `/environments/compare`.

Spec: [../superpowers/specs/2026-08-03-environment-comparison-design.md](../superpowers/specs/2026-08-03-environment-comparison-design.md).

Two decisions worth carrying into the rest of Phase 6:

- **Host *shape*, never host identity.** Hostnames differ between environments by design, so
  comparing them would mark every subsystem different. The comparison is over a sorted
  `{component_type, role, count}` list, which catches replica counts, missing standbys and
  host-class differences while staying quiet about names.
- **The API is symmetric; the reference is presentation.** Nominating a reference
  environment reframes the same differences as risk in the UI. Keeping it out of the API
  means one response serves both the triage and fidelity views.

### 2. Drift detection — not started

Compare IaC-declared against recorded state. Needs a decision first on how `.tfstate` is
obtained — uploaded by hand like today's `.tf` files, or pulled from a remote backend. That
decision partly belongs to sub-project 3, so specify them together or do 3 first.

### 3. GitHub App / OAuth + repository scanner — not started

Automated repository scanning to replace today's manual file upload. App registration,
OAuth, a background worker, scheduling and credential storage. The largest piece, and it
unlocks 2.

### 4. env-topology SP4 — group-by-system/host toggle, not started

**The machinery is already complete**: both groupings (`bySystem`, `byHost`), the host graph
transform and the edge resolver all exist, and
`frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx` already holds
`const [groupBy, setGroupBy] = useState<'system' | 'host'>('system')`. `setGroupBy` is never
called — only the UI control is missing. Small.

## Notes

> Detailed task breakdown to be added when Phase 5 is complete and Phase 6 planning begins.

**Dependency model integration:**
> The Terraform and Docker Compose parsers in this phase **do not create a separate dependency model**. They write parsed connections into the `SystemDependency` and `ComponentDependency` tables established in Phase 1, using `source = terraform` or `source = docker_compose`. Manually declared dependencies (Phase 1, `source = manual`) and IaC-discovered dependencies coexist in the same tables and are queryable together. The `source` field allows filtering by how a dependency was discovered.
