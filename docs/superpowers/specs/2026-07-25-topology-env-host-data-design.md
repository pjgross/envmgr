# Environment Topology API: Host Data (Sub-Project 2)

**Date:** 2026-07-25
**Status:** Design approved, ready for implementation plan
**Programme:** Environment topology parity + group-by-system/host (SP2 of 4)

## Context

The environment-topology parity effort (see
`2026-07-25-topology-shared-engine-design.md`) will add a **group-by-system /
group-by-host** switch to the environment topology diagram. The switch is
client-side: the API returns host assignments per subsystem and the frontend
re-groups in the browser. Today the environment topology API
(`GET /api/v1/environments/{env_id}/topology` →
`environment_service.get_environment_topology`) returns subsystems, dependencies,
system names, and "outside" subsystems/dependencies — but **no host data**.

This sub-project adds per-subsystem host assignments to that response. It is a
backend-only change. Consuming it (grouping, duplication, buckets) is SP3/SP4.

The plumbing already exists and is reused, not rebuilt:
- `InfrastructureComponent` model (deploy target: server / cluster / managed DB / …)
  with `component_type`, `provider`, `region`, and a soft-delete `deleted_at`.
- `EnvironmentSubSystemHost` junction (`environment_subsystem_id`,
  `infrastructure_component_id`, `role: str | None`, soft-delete `deleted_at`) —
  many-to-many; a subsystem can span multiple hosts.
- `EnvironmentSubSystem.hosts` relationship;
  `EnvironmentSubSystemHost.infrastructure_component` relationship.
- A `PUT /environments/{env_id}/subsystems/{sub_id}/hosts` endpoint and
  `_host_to_response` already manage/read host attachments elsewhere.

## Goal

Enrich `EnvironmentTopologyResponse` so each in-environment subsystem node carries
the list of infrastructure components it is deployed on, with enough detail for the
frontend to render host groups and duplicate a multi-host subsystem under each host.

## Non-Goals

- No frontend changes (SP3/SP4).
- No new host-management endpoints (attachment is already handled elsewhere).
- No change to the systems topology API.
- No "empty host group" support (a host with zero subsystems is not represented —
  hosts are carried inline per subsystem, not as a separate catalogue).

## Design

### Response shape (Approach A — inline per-subsystem host list)

Add a lightweight host-ref model and a `hosts` field to the existing
`EnvSubsystemNode` (in `app/api/v1/schemas/environment.py`):

```python
class EnvSubsystemHostRef(BaseModel):
    """A host an environment subsystem is deployed on, for the topology diagram."""
    infrastructure_component_id: int
    name: str
    component_type: str          # InfrastructureComponentType value (str-enum)
    role: Optional[str] = None   # free-text, e.g. "primary"/"replica"; may be null


class EnvSubsystemNode(BaseModel):
    id: int
    name: str
    component_type: str
    technology: Optional[str] = None
    system_id: int
    is_mocked: bool
    hosts: list[EnvSubsystemHostRef] = []   # NEW; [] for outside subsystems
```

`EnvironmentTopologyResponse` is otherwise unchanged (it already contains
`subsystems`, `dependencies`, `system_names`, `outside_subsystems`,
`outside_dependencies`). `outside_subsystems` nodes always get `hosts: []` — they
are deployed in a different environment, so they have no hosts here and will render
in the single "External" group in host mode (SP4).

Rationale for inline (vs. normalized top-level `hosts` catalogue +
`subsystem_hosts` junction array): it mirrors how `is_mocked` already lives on the
node, is exactly what SP4's group-by-host transform consumes (read `node.hosts`,
duplicate the node under each ref, derive the host-group name/type from the ref),
and needs no client-side join. We have no use for empty host groups, so the
catalogue form buys nothing.

### Service change (`environment_service.get_environment_topology`)

- Eager-load hosts on the env-subsystem query:
  `selectinload(EnvironmentSubSystem.hosts).selectinload(EnvironmentSubSystemHost.infrastructure_component)`.
- When building each in-env `subsystem_nodes` entry, populate `hosts` from
  `row.hosts`, filtering out:
  - junction rows with `deleted_at` set, and
  - rows whose `infrastructure_component` is missing or has `deleted_at` set.
- Each surviving row becomes
  `{ "infrastructure_component_id": comp.id, "name": comp.name,
     "component_type": comp.component_type, "role": host_row.role }`.
- `outside_sub_nodes` continue to be built without hosts (implicitly `hosts: []`
  via the schema default; set explicitly to `[]` for clarity).
- Host attachments are included regardless of the subsystem's `is_mocked` flag
  (truthful to what is recorded).

The empty-environment early-return branch is unaffected (no subsystems → no hosts).

### Data flow

```
GET /environments/{id}/topology
  → environment_service.get_environment_topology
      → load EnvironmentSubSystem + subsystem + hosts + infrastructure_component
      → per in-env node: hosts = [EnvSubsystemHostRef(...) for live host rows]
      → outside nodes: hosts = []
  → EnvironmentTopologyResponse (subsystems now carry `hosts`)
```

## Testing

Backend tests (SQLite in-memory, existing `tests/conftest.py` fixtures):
- A subsystem with **two** host attachments returns both refs with correct
  `infrastructure_component_id` / `name` / `component_type` / `role` (proves the
  multi-host case SP4 depends on).
- A subsystem with **no** hosts returns `hosts: []`.
- A host junction with `deleted_at` set is **excluded**; a junction pointing at a
  soft-deleted `InfrastructureComponent` is **excluded**.
- `role` is carried through, including `None`.
- An **outside** subsystem (cross-environment dependency) returns `hosts: []`.
- The existing environment-topology tests still pass (the new field is additive).

## Risks

- **N+1 / missing eager-load:** forgetting the nested `selectinload` would either
  lazy-load per row (async → error under `AsyncSession`) or require extra queries.
  Mitigated by the explicit nested `selectinload` and a test that exercises a
  multi-host subsystem.
- **Soft-deleted hosts leaking:** must filter both the junction `deleted_at` and the
  component `deleted_at`. Covered by tests.
- **Enum serialization:** `InfrastructureComponentType` is a `str`-enum, so
  `component_type: str` on the ref serializes to its value without special handling
  (same pattern as `EnvSubsystemNode.component_type`).
