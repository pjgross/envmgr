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


from httpx import AsyncClient


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
