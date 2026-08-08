# Phase 6: Infrastructure Topology

> Status: ✅ **COMPLETE (2026-08-03).** Model + host-aware CRs (Phase 2.5), both IaC parsers, the topology API and the React Flow visualisation, environment comparison, GitHub OAuth + repository scanning, and drift detection are all shipped. Nothing outstanding — see *What was actually left* below for the corrected record. | Roadmap: [../plan.md](../plan.md)
> Duration: 6–8 weeks (remainder) | Started after Phase 5 completion

---

## Already delivered (via Phase 2.5 pull-forward on MR !2)

See [phase-2.md §Phase 2.5](phase-2.md#phase-25--hosts-and-multi-target-change-requests-phase-6-pull-forward) for full detail.

- `InfrastructureComponent` model (Phase 6-shaped: `component_type`, `provider`, `region`, `source`, `external_id`, `tags`) — already ready for Terraform / Docker Compose rows via the `source` enum.
- `environment_subsystem_host` M:M junction — deployed subsystem ↔ host (replicas, multi-AZ).
- `change_request_host` + `change_request_environment` junctions — CRs target any combination, with `derived_environment_ids` auto-surfacing envs whose subsystems run on the selected hosts.
- `/api/v1/infrastructure-components` CRUD + `/impact` endpoint + env-subsystem-host PUT/GET endpoints.
- Frontend: Hosts CRUD page, host-impact panel + booking Gantt on CR forms, per-env host attach dialog.

**Do not re-add any of the above.** Everything Phase 6 went on to build wrote *into* these existing tables rather than introducing new ones, and later work touching infrastructure topology should do the same — the model was deliberately shaped in Phase 2.5 to absorb Terraform and Docker Compose rows via the `source` enum.

---

## What was actually left — corrected 2026-08-03, and now all done

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

**All four sub-projects are now done** — environment comparison, env-topology SP4 (already shipped before it was recorded as outstanding), GitHub repository scanning, and drift detection.

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

### 2. Drift detection — ✅ shipped 2026-08-03

`GET /api/v1/systems/{id}/github/drift` plus a "Check drift" dialog on System detail. Spec:
[../superpowers/specs/2026-08-03-drift-detection-design.md](../superpowers/specs/2026-08-03-drift-detection-design.md).

**It compares repository IaC against the subsystem catalogue, not `.tfstate` against recorded
state** — because the framing above turned out not to match the code. The IaC parsers write
`SubSystem` rows, not `InfrastructureComponent` rows; nothing anywhere sets
`InfrastructureComponentSource.TERRAFORM`, which is still an unused enum value. So the
comparison that was actually available needed no `.tfstate` and no new data source. The
`.tf`-versus-`.tfstate` question is unchanged and remains out of scope, for the two reasons
already recorded: state is not normally committed, and `.tf` declares resources with no
computed values or resource ids, so the two formats do not produce comparable rows.

Three things worth carrying forward:

- **Parsing must not write.** The importers parsed and persisted in one pass, so "what the
  code declares" never existed as a value anyone could compare. Detectors now return a
  `DeclaredState`, and `reconcile.apply()` writes it while `reconcile.diff()` compares it —
  both reading the same value, which is what stops the report describing a change a scan
  would not make. A test asserts exactly that: `apply(declared)` then `diff(declared)` must
  report zero drift. It earned its keep immediately, catching a case where the two sides
  de-duplicated repeated edges in opposite directions.
- **Truncate in the parser, never in the writer.** If the writer truncated, a stored row
  would differ from the declaration it came from and every long name would report a phantom
  change on every run. Note SQLite does not enforce column widths at all, so removing a
  truncation fails **only** on the PostgreSQL leg.
- **Positive findings survive a partial read; absence findings do not.** GitHub truncates
  large trees and the scan caps files, and an unread file is indistinguishable from a deleted
  one. So "in the catalogue but not in the code" is not computed at all when the read was
  partial — it serialises as `null`, never `[]`, and the UI omits the group rather than
  rendering it empty. "We checked and found nothing" and "we could not check" are opposite
  conclusions.

Provenance was the enabling change: `SubSystem` gained `source` and `source_path`, without
which a resource deleted from the code cannot be told apart from one a person added by hand.

### 3. GitHub OAuth + repository scanning — ✅ shipped 2026-08-03

Connect a tenant's GitHub account via **OAuth device flow**, then scan a system's repository
on demand. Spec:
[../superpowers/specs/2026-08-03-github-repository-scanning-design.md](../superpowers/specs/2026-08-03-github-repository-scanning-design.md).

Scoped deliberately to **connect + scan on demand**. Automation — scheduled polling or
webhooks — was excluded: this app has one supervised asyncio loop and no task queue, and
adding a scheduler deserves its own spec. Device flow needs none, because the user is present
while they authorise.

Three things worth carrying forward:

- **`tenant_secret`** is the app's first reversible credential store — Fernet-encrypted, with
  a `key_version` per row and its own `SECRETS_ENCRYPTION_KEY`, deliberately not the JWT
  signing key. Phase 8's parked design wanted the same thing.
- **The detector registry** is the extensibility mechanism: a detector is a name, a path
  predicate and a parse function, and adding one is a module plus a list entry. That claim was
  tested rather than asserted — adding the Terraform detector touched only
  `detectors/__init__.py`, with zero changes to `registry.py` or `compose.py`.
- **A partial answer must never read as a complete one.** GitHub truncates the tree of a large
  repository, and the scan caps files fetched; both are first-class outcomes in the response
  and surfaced in the UI. Each detector also writes inside its own SAVEPOINT, so one
  detector's failed write cannot erase the others' results.

### 4. env-topology SP4 — group-by-system/host toggle — ✅ **already shipped**

**Corrected 2026-08-03. An earlier version of this file said `setGroupBy` was dead code and
only the UI control was missing. That was wrong.** The toggle exists in full: a System/Host
`ToggleButtonGroup` in `EnvironmentTopologyDiagram.tsx`, wired to `setGroupBy` and passed to
`TopologyCanvas` as `headerControls`. Verified in the browser — Host mode regroups the
diagram into host buckets (`UNASSIGNED`, `EXTERNAL`, and the named hosts) with dependency
edges preserved.

The false claim came from a **case-sensitive** `grep` for `groupBy`, which does not match
`setGroupBy`. Its spec and plan are
[../superpowers/specs/2026-07-27-topology-group-by-host-design.md](../superpowers/specs/2026-07-27-topology-group-by-host-design.md)
and [../superpowers/plans/2026-07-27-topology-group-by-host.md](../superpowers/plans/2026-07-27-topology-group-by-host.md);
the plan's checkboxes were never ticked, which is what made it look outstanding.

## Notes

> The per-sub-project task breakdowns live with their specs and plans under
> [../superpowers/](../superpowers/) rather than here — see the links in each section above.
> (This line previously read "to be added when Phase 5 is complete and Phase 6 planning
> begins", which outlived both.)

**Dependency model integration:**
> The Terraform and Docker Compose parsers in this phase **do not create a separate dependency model**. They write parsed connections into the `SystemDependency` and `ComponentDependency` tables established in Phase 1, using `source = terraform` or `source = docker_compose`. Manually declared dependencies (Phase 1, `source = manual`) and IaC-discovered dependencies coexist in the same tables and are queryable together. The `source` field allows filtering by how a dependency was discovered.
