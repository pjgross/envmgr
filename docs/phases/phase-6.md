# Phase 6: Infrastructure Topology

> Status: 🟡 **Partially shipped — model + host-aware CRs landed in Phase 2.5** (MR !2, 2026-04-19). Remaining parsers / topology graph / visualisation still planned. | Roadmap: [../plan.md](../plan.md)
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

## Objectives (remaining)

- GitHub integration for automated repository scanning
- Terraform and Docker Compose file parsers (write into `infrastructure_component` with `source = terraform | docker_compose`, and into `SystemDependency` / `ComponentDependency`)
- Topology graph in Neo4j for dependency analysis (project `infrastructure_component` + `environment_subsystem_host` + `change_request_host` into the graph)
- React Flow interactive topology visualization
- Environment comparison tool (diff two environments)
- Drift detection (Terraform plan vs state)

---

## Planned Tasks

### Backend

- [ ] GitHub App / OAuth integration for repository access
- [ ] Repository scanner background worker
- [ ] Terraform parser (`.tf` → resource graph)
- [ ] Docker Compose parser (`docker-compose.yml` → service graph)
- [x] `InfrastructureComponent` model with source traceability (shipped in Phase 2.5)
- [ ] Neo4j sync consumer (project PostgreSQL data to graph)
- [ ] Drift detection service (compare `.tf` vs `.tfstate`)
- [ ] Topology API endpoints (`/api/v1/topology`)

### Frontend

- [ ] React Flow topology diagram component
- [ ] Environment topology page with zoom/pan/filter
- [ ] Environment comparison view (side-by-side diff)
- [ ] GitHub repository link UI on System detail
- [ ] Drift detection status indicators

---

## Notes

> Detailed task breakdown to be added when Phase 5 is complete and Phase 6 planning begins.

**Dependency model integration:**
> The Terraform and Docker Compose parsers in this phase **do not create a separate dependency model**. They write parsed connections into the `SystemDependency` and `ComponentDependency` tables established in Phase 1, using `source = terraform` or `source = docker_compose`. Manually declared dependencies (Phase 1, `source = manual`) and IaC-discovered dependencies coexist in the same tables and are queryable together. The `source` field allows filtering by how a dependency was discovered.
