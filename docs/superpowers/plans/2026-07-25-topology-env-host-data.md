# Environment Topology Host Data (SP2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-subsystem host assignments to the environment topology API response so the frontend can later group/duplicate subsystems by host.

**Architecture:** Backend-only. Add an inline `EnvSubsystemHostRef` model and a `hosts` field to `EnvSubsystemNode`, and populate it in `environment_service.get_environment_topology` by eager-loading the existing `EnvironmentSubSystem.hosts → infrastructure_component` relationship (filtering soft-deleted junctions/components). Outside subsystems get `hosts: []`.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, pytest (SQLite in-memory via `tests/conftest.py`).

**Spec:** [docs/superpowers/specs/2026-07-25-topology-env-host-data-design.md](../specs/2026-07-25-topology-env-host-data-design.md)

**Base branch:** `feature/topology-env-host-data` (already checked out, off `feature/topology-perf`).

**Commands** (run from `backend/`): `uv run pytest <path> -v`

---

## File Structure

**Create:**
- `backend/tests/integration/test_environment_topology_hosts.py` — service-level + API-level tests for the new `hosts` field.

**Modify:**
- `backend/app/api/v1/schemas/environment.py` — add `EnvSubsystemHostRef`; add `hosts` to `EnvSubsystemNode`.
- `backend/app/services/environment_service.py` — import `EnvironmentSubSystemHost`; eager-load hosts; populate `hosts` on in-env nodes; `hosts: []` on outside nodes.

---

## Task 1: Return per-subsystem hosts from the environment topology API

**Files:** as listed above.

This is one cohesive change (schema + service are validated together by the tests). TDD: write the failing service test, implement schema + service, then add the API-level test that locks schema serialization.

- [ ] **Step 1: Write the failing service-level test**

Create `backend/tests/integration/test_environment_topology_hosts.py`:

```python
"""Tests for host data in the environment topology response (SP2)."""
import pytest

from app.db.models.system import System, SubSystem
from app.db.models.environment import EnvironmentSubSystem, EnvironmentSubSystemHost
from app.db.models.infrastructure_component import (
    InfrastructureComponent,
    InfrastructureComponentType,
)
from app.db.models.dependency import ComponentDependency
from app.services.environment_service import get_environment_topology


async def _system_with_subsystem(db, tenant, name, comp_type="web_service"):
    sys_row = System(tenant_id=tenant.id, name=f"{name}-system")
    db.add(sys_row)
    await db.flush()
    sub = SubSystem(
        tenant_id=tenant.id, system_id=sys_row.id, name=name, component_type=comp_type
    )
    db.add(sub)
    await db.flush()
    return sub


async def _link(db, tenant, env, sub, is_mocked=False):
    link = EnvironmentSubSystem(
        environment_id=env.id, subsystem_id=sub.id, tenant_id=tenant.id, is_mocked=is_mocked
    )
    db.add(link)
    await db.flush()
    return link


async def _component(db, tenant, name, comp_type=InfrastructureComponentType.SERVER, deleted=False):
    comp = InfrastructureComponent(tenant_id=tenant.id, name=name, component_type=comp_type)
    if deleted:
        from datetime import datetime, timezone
        comp.deleted_at = datetime.now(timezone.utc)
    db.add(comp)
    await db.flush()
    return comp


async def _attach(db, tenant, link, comp, role=None, deleted=False):
    host = EnvironmentSubSystemHost(
        environment_subsystem_id=link.id,
        infrastructure_component_id=comp.id,
        tenant_id=tenant.id,
        role=role,
    )
    if deleted:
        from datetime import datetime, timezone
        host.deleted_at = datetime.now(timezone.utc)
    db.add(host)
    await db.flush()
    return host


def _node(result, sub_id):
    return next(n for n in result["subsystems"] if n["id"] == sub_id)


@pytest.mark.asyncio
async def test_node_carries_its_hosts_with_role(db_session, test_tenant, test_environment):
    a = await _system_with_subsystem(db_session, test_tenant, "svc-a")
    link_a = await _link(db_session, test_tenant, test_environment, a)
    c1 = await _component(db_session, test_tenant, "macmini", InfrastructureComponentType.SERVER)
    c2 = await _component(db_session, test_tenant, "rds", InfrastructureComponentType.MANAGED_DATABASE)
    await _attach(db_session, test_tenant, link_a, c1, role="primary")
    await _attach(db_session, test_tenant, link_a, c2, role=None)
    await db_session.commit()

    result = await get_environment_topology(db_session, test_environment.id, test_tenant.id)
    hosts = _node(result, a.id)["hosts"]
    by_id = {h["infrastructure_component_id"]: h for h in hosts}
    assert set(by_id) == {c1.id, c2.id}
    assert by_id[c1.id] == {
        "infrastructure_component_id": c1.id, "name": "macmini",
        "component_type": "server", "role": "primary",
    }
    assert by_id[c2.id]["component_type"] == "managed_database"
    assert by_id[c2.id]["role"] is None


@pytest.mark.asyncio
async def test_subsystem_without_hosts_returns_empty_list(db_session, test_tenant, test_environment):
    b = await _system_with_subsystem(db_session, test_tenant, "svc-b")
    await _link(db_session, test_tenant, test_environment, b)
    await db_session.commit()

    result = await get_environment_topology(db_session, test_environment.id, test_tenant.id)
    assert _node(result, b.id)["hosts"] == []


@pytest.mark.asyncio
async def test_soft_deleted_junction_and_component_are_excluded(db_session, test_tenant, test_environment):
    a = await _system_with_subsystem(db_session, test_tenant, "svc-a")
    link_a = await _link(db_session, test_tenant, test_environment, a)
    live = await _component(db_session, test_tenant, "live-host")
    dead_comp = await _component(db_session, test_tenant, "dead-host", deleted=True)
    dead_link_comp = await _component(db_session, test_tenant, "orphaned-host")
    await _attach(db_session, test_tenant, link_a, live, role="primary")
    await _attach(db_session, test_tenant, link_a, dead_comp)          # component soft-deleted
    await _attach(db_session, test_tenant, link_a, dead_link_comp, deleted=True)  # junction soft-deleted
    await db_session.commit()

    result = await get_environment_topology(db_session, test_environment.id, test_tenant.id)
    ids = [h["infrastructure_component_id"] for h in _node(result, a.id)["hosts"]]
    assert ids == [live.id]


@pytest.mark.asyncio
async def test_outside_subsystem_has_empty_hosts(db_session, test_tenant, test_environment):
    a = await _system_with_subsystem(db_session, test_tenant, "svc-a")
    link_a = await _link(db_session, test_tenant, test_environment, a)
    outside = await _system_with_subsystem(db_session, test_tenant, "svc-outside")  # not linked to env
    # cross-env dependency a -> outside makes `outside` an outside_subsystem
    db_session.add(ComponentDependency(
        tenant_id=test_tenant.id, from_subsystem_id=a.id, to_subsystem_id=outside.id,
        dependency_type="api_call", direction="one_way", source="manual",
    ))
    # give `a` a host so we also confirm in-env hosts still populate alongside outside nodes
    c1 = await _component(db_session, test_tenant, "macmini")
    await _attach(db_session, test_tenant, link_a, c1, role="primary")
    await db_session.commit()

    result = await get_environment_topology(db_session, test_environment.id, test_tenant.id)
    outside_node = next(n for n in result["outside_subsystems"] if n["id"] == outside.id)
    assert outside_node["hosts"] == []
    assert len(_node(result, a.id)["hosts"]) == 1
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd backend && uv run pytest tests/integration/test_environment_topology_hosts.py -v`
Expected: FAIL — the service does not yet put `hosts` on nodes (`KeyError: 'hosts'`).

- [ ] **Step 3: Add the schema**

In `backend/app/api/v1/schemas/environment.py`, add `EnvSubsystemHostRef` immediately before `class EnvSubsystemNode` and add the `hosts` field to `EnvSubsystemNode`:

```python
class EnvSubsystemHostRef(BaseModel):
    """A host an environment subsystem is deployed on, for the topology diagram."""
    infrastructure_component_id: int
    name: str
    component_type: str          # InfrastructureComponentType value (str-enum)
    role: Optional[str] = None


class EnvSubsystemNode(BaseModel):
    """Subsystem node for the environment topology response."""
    id: int
    name: str
    component_type: str
    technology: Optional[str] = None
    system_id: int
    is_mocked: bool
    hosts: list[EnvSubsystemHostRef] = []
```

(Only the `hosts: list[EnvSubsystemHostRef] = []` line is new on `EnvSubsystemNode`; keep the existing fields exactly as they are.)

- [ ] **Step 4: Update the service**

In `backend/app/services/environment_service.py`:

Add `EnvironmentSubSystemHost` to the environment-models import on line 10:

```python
from app.db.models.environment import (
    Environment,
    EnvironmentSystem,
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
    EnvironmentStatus,
)
```

In `get_environment_topology`, change the env-subsystem query's `.options(...)` to also eager-load hosts and their components:

```python
        .options(
            selectinload(EnvironmentSubSystem.subsystem),
            selectinload(EnvironmentSubSystem.hosts).selectinload(
                EnvironmentSubSystemHost.infrastructure_component
            ),
        )
```

Replace the in-env `subsystem_nodes` build loop so each node carries its live hosts:

```python
    subsystem_nodes = []
    for row in env_sub_rows:
        sub = row.subsystem
        if sub is None:
            continue
        hosts = []
        for host_row in row.hosts:
            if host_row.deleted_at is not None:
                continue
            comp = host_row.infrastructure_component
            if comp is None or comp.deleted_at is not None:
                continue
            hosts.append({
                "infrastructure_component_id": comp.id,
                "name": comp.name,
                "component_type": comp.component_type,
                "role": host_row.role,
            })
        subsystem_nodes.append({
            "id": sub.id,
            "name": sub.name,
            "component_type": sub.component_type,
            "technology": sub.technology,
            "system_id": sub.system_id,
            "is_mocked": row.is_mocked,
            "hosts": hosts,
        })
```

Add `"hosts": []` to each outside node dict:

```python
    outside_sub_nodes = [
        {
            "id": sub.id,
            "name": sub.name,
            "component_type": sub.component_type,
            "technology": sub.technology,
            "system_id": sub.system_id,
            "is_mocked": False,
            "hosts": [],
        }
        for sub in outside_subsystems
    ]
```

(The empty-environment early-return branch already returns `subsystems: []` / `outside_subsystems: []`, so it needs no change.)

- [ ] **Step 5: Run the service tests to confirm they pass**

Run: `cd backend && uv run pytest tests/integration/test_environment_topology_hosts.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Add the API-level test that locks schema serialization**

Append to `backend/tests/integration/test_environment_topology_hosts.py`:

```python
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_topology_endpoint_serializes_hosts(
    client: AsyncClient, auth_headers, db_session, test_tenant, test_environment
):
    a = await _system_with_subsystem(db_session, test_tenant, "svc-a")
    link_a = await _link(db_session, test_tenant, test_environment, a)
    c1 = await _component(db_session, test_tenant, "macmini", InfrastructureComponentType.SERVER)
    await _attach(db_session, test_tenant, link_a, c1, role="primary")
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/environments/{test_environment.id}/topology", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    node = next(n for n in resp.json()["subsystems"] if n["id"] == a.id)
    assert node["hosts"] == [{
        "infrastructure_component_id": c1.id,
        "name": "macmini",
        "component_type": "server",
        "role": "primary",
    }]
```

This proves the `EnvSubsystemHostRef` schema field exists and serializes through the endpoint (a missing schema field would be silently dropped by Pydantic, so the service-level tests alone would not catch it).

- [ ] **Step 7: Run the whole new test file + guard against regressions**

Run: `cd backend && uv run pytest tests/integration/test_environment_topology_hosts.py -v`
Expected: PASS (5 passed).
Run: `cd backend && uv run pytest tests/integration/test_infrastructure_components.py -q`
Expected: PASS (existing host/infra tests unaffected).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/schemas/environment.py \
        backend/app/services/environment_service.py \
        backend/tests/integration/test_environment_topology_hosts.py
git commit -m "feat(topology): return per-subsystem hosts in environment topology API"
```

---

## Done Criteria

- Each in-env `EnvSubsystemNode` carries `hosts: list[EnvSubsystemHostRef]` (`infrastructure_component_id`, `name`, `component_type`, `role`).
- Multi-host subsystems return all live hosts; soft-deleted junctions and soft-deleted/missing components are excluded; `role` (incl. `None`) is carried through.
- Outside subsystems return `hosts: []`.
- The `hosts` field serializes through `GET /environments/{id}/topology` (API test).
- New tests pass; existing infrastructure-component tests still pass.
