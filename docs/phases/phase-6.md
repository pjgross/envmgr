# Phase 6: Infrastructure Topology

> Status: ⏳ **Planned** | Roadmap: [../plan.md](../plan.md)
> Duration: 6–8 weeks | Starts after Phase 5 completion

---

## Objectives

- GitHub integration for automated repository scanning
- Terraform and Docker Compose file parsers
- Infrastructure component modeling in PostgreSQL
- Topology graph in Neo4j for dependency analysis
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
- [ ] `InfrastructureComponent` model with source traceability
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
