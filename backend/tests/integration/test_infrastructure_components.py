"""Integration tests for InfrastructureComponent + EnvironmentSubSystemHost."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.system import System, SubSystem
from app.db.models.environment import EnvironmentSubSystem


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def test_subsystem(db_session, test_tenant):
    sys_row = System(tenant_id=test_tenant.id, name="Billing")
    db_session.add(sys_row)
    await db_session.flush()
    sub = SubSystem(
        tenant_id=test_tenant.id,
        system_id=sys_row.id,
        name="billing-api",
        component_type="api_gateway",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


@pytest_asyncio.fixture(scope="function")
async def test_env_subsystem(db_session, test_tenant, test_environment, test_subsystem):
    link = EnvironmentSubSystem(
        environment_id=test_environment.id,
        subsystem_id=test_subsystem.id,
        tenant_id=test_tenant.id,
        is_mocked=False,
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    return link


def _host_payload(name="macmini", component_type="server", **overrides):
    payload = {
        "name": name,
        "component_type": component_type,
        "provider": "on_premise",
        "region": "local",
        "location": "macmini.lan",
    }
    payload.update(overrides)
    return payload


# ── InfrastructureComponent CRUD ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_infrastructure_component(client: AsyncClient, auth_headers):
    create = await client.post(
        "/api/v1/infrastructure-components/",
        headers=auth_headers,
        json=_host_payload(),
    )
    assert create.status_code == 201, create.text
    host = create.json()
    assert host["name"] == "macmini"
    assert host["component_type"] == "server"
    assert host["source"] == "manual"

    fetched = await client.get(
        f"/api/v1/infrastructure-components/{host['id']}", headers=auth_headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == host["id"]


@pytest.mark.asyncio
async def test_list_filters_by_type_and_provider(client, auth_headers):
    await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="macmini", component_type="server", provider="on_premise"),
    )
    await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="rds-prod", component_type="managed_database", provider="aws"),
    )
    all_ = await client.get("/api/v1/infrastructure-components/", headers=auth_headers)
    assert len(all_.json()) == 2

    aws_only = await client.get(
        "/api/v1/infrastructure-components/?provider=aws", headers=auth_headers
    )
    names = [c["name"] for c in aws_only.json()]
    assert names == ["rds-prod"]

    db_only = await client.get(
        "/api/v1/infrastructure-components/?component_type=managed_database",
        headers=auth_headers,
    )
    assert [c["name"] for c in db_only.json()] == ["rds-prod"]


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name(client, auth_headers):
    first = await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers, json=_host_payload(),
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers, json=_host_payload(),
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_delete_blocked_while_attached(
    client, auth_headers, test_environment, test_subsystem, test_env_subsystem
):
    host = (
        await client.post(
            "/api/v1/infrastructure-components/", headers=auth_headers, json=_host_payload(),
        )
    ).json()

    attach = await client.put(
        f"/api/v1/environments/{test_environment.id}/subsystems/{test_subsystem.id}/hosts",
        headers=auth_headers,
        json=[{"infrastructure_component_id": host["id"], "role": "primary"}],
    )
    assert attach.status_code == 200, attach.text

    blocked = await client.delete(
        f"/api/v1/infrastructure-components/{host['id']}", headers=auth_headers
    )
    assert blocked.status_code == 409

    # Detach → delete now succeeds
    detach = await client.put(
        f"/api/v1/environments/{test_environment.id}/subsystems/{test_subsystem.id}/hosts",
        headers=auth_headers,
        json=[],
    )
    assert detach.status_code == 200
    assert (
        await client.delete(
            f"/api/v1/infrastructure-components/{host['id']}", headers=auth_headers
        )
    ).status_code == 204


# ── EnvironmentSubSystemHost (PUT idempotency + role diff) ──────────────────

@pytest.mark.asyncio
async def test_put_hosts_is_idempotent_and_diffs_roles(
    client, auth_headers, test_environment, test_subsystem, test_env_subsystem
):
    h1 = (await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="ecs-1"),
    )).json()
    h2 = (await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="ecs-2"),
    )).json()

    base_url = f"/api/v1/environments/{test_environment.id}/subsystems/{test_subsystem.id}/hosts"
    body = [
        {"infrastructure_component_id": h1["id"], "role": "primary"},
        {"infrastructure_component_id": h2["id"], "role": "replica"},
    ]
    r1 = await client.put(base_url, headers=auth_headers, json=body)
    assert r1.status_code == 200, r1.text
    assert {h["infrastructure_component_id"] for h in r1.json()["hosts"]} == {h1["id"], h2["id"]}
    assert {h["role"] for h in r1.json()["hosts"]} == {"primary", "replica"}

    # Repeat → same state
    r2 = await client.put(base_url, headers=auth_headers, json=body)
    assert r2.status_code == 200
    assert len(r2.json()["hosts"]) == 2

    # Swap role on h1; drop h2
    new_body = [{"infrastructure_component_id": h1["id"], "role": "only"}]
    r3 = await client.put(base_url, headers=auth_headers, json=new_body)
    assert r3.status_code == 200
    hosts = r3.json()["hosts"]
    assert len(hosts) == 1
    assert hosts[0]["role"] == "only"


@pytest.mark.asyncio
async def test_put_hosts_rejects_unknown_host(
    client, auth_headers, test_environment, test_subsystem, test_env_subsystem
):
    r = await client.put(
        f"/api/v1/environments/{test_environment.id}/subsystems/{test_subsystem.id}/hosts",
        headers=auth_headers,
        json=[{"infrastructure_component_id": 99999}],
    )
    assert r.status_code == 404


# ── CR multi-target + derived-env outage preview ────────────────────────────

def _cr_payload(lifecycle_id, **overrides):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "title": "Host reboot",
        "change_type": "infrastructure",
        "lifecycle_id": lifecycle_id,
        "environment_ids": [],
        "host_ids": [],
        "has_outage": False,
        "scheduled_start": (now + timedelta(days=1)).isoformat(),
        "scheduled_end": (now + timedelta(days=1, hours=1)).isoformat(),
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture(scope="function")
async def cr_lifecycle(db_session, test_tenant):
    from app.db.models.lifecycle import LifecycleTemplate
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="change_request",
        name="Minimal",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "done", "label": "Done", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "done", "label": "Finish",
                 "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


@pytest.mark.asyncio
async def test_create_requires_at_least_one_target(client, auth_headers, cr_lifecycle):
    r = await client.post(
        "/api/v1/change-requests", headers=auth_headers,
        json=_cr_payload(cr_lifecycle.id),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_host_scoped_cr_derives_affected_envs_in_outage_preview(
    client, auth_headers, test_environment, test_subsystem, test_env_subsystem
):
    host = (await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="shared-host"),
    )).json()

    attach = await client.put(
        f"/api/v1/environments/{test_environment.id}/subsystems/{test_subsystem.id}/hosts",
        headers=auth_headers,
        json=[{"infrastructure_component_id": host["id"]}],
    )
    assert attach.status_code == 200

    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        "/api/v1/change-requests/preview-outage-conflicts",
        headers=auth_headers,
        json={
            "environment_ids": [],
            "host_ids": [host["id"]],
            "outage_start": (now + timedelta(days=1)).isoformat(),
            "outage_end": (now + timedelta(days=1, hours=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert test_environment.id in body["derived_environment_ids"]
    assert any(e["environment_id"] == test_environment.id for e in body["environments"])


@pytest.mark.asyncio
async def test_host_scoped_cr_appears_in_derived_env_schedule(
    client, auth_headers, test_environment, test_subsystem, test_env_subsystem, cr_lifecycle
):
    host = (await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="shared-host-2"),
    )).json()

    await client.put(
        f"/api/v1/environments/{test_environment.id}/subsystems/{test_subsystem.id}/hosts",
        headers=auth_headers,
        json=[{"infrastructure_component_id": host["id"]}],
    )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    cr_start = now + timedelta(days=1)
    cr_end = now + timedelta(days=1, hours=2)
    cr_resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(
            cr_lifecycle.id,
            title="Reboot shared host",
            host_ids=[host["id"]],
            scheduled_start=cr_start.isoformat(),
            scheduled_end=cr_end.isoformat(),
        ),
    )
    assert cr_resp.status_code == 201, cr_resp.text
    body = cr_resp.json()
    assert body["environment_ids"] == []
    assert body["host_ids"] == [host["id"]]
    assert test_environment.id in body["derived_environment_ids"]

    schedule = await client.get(
        f"/api/v1/environments/{test_environment.id}/schedule",
        headers=auth_headers,
        params={
            "start_date": (now - timedelta(hours=1)).isoformat(),
            "end_date": (now + timedelta(days=7)).isoformat(),
        },
    )
    assert schedule.status_code == 200
    titles = [cr["title"] for cr in schedule.json()["change_requests"]]
    assert "Reboot shared host" in titles


@pytest.mark.asyncio
async def test_host_impact_groups_envs_and_subsystems(
    client, auth_headers, test_environment, test_subsystem, test_env_subsystem
):
    h1 = (await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="impact-host-1"),
    )).json()
    h2 = (await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="impact-host-2"),
    )).json()

    attach = await client.put(
        f"/api/v1/environments/{test_environment.id}/subsystems/{test_subsystem.id}/hosts",
        headers=auth_headers,
        json=[
            {"infrastructure_component_id": h1["id"], "role": "primary"},
            {"infrastructure_component_id": h2["id"], "role": "replica"},
        ],
    )
    assert attach.status_code == 200, attach.text

    r = await client.get(
        "/api/v1/infrastructure-components/impact",
        headers=auth_headers,
        params=[("host_ids", h1["id"]), ("host_ids", h2["id"])],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["host_ids"]) == sorted([h1["id"], h2["id"]])
    assert len(body["environments"]) == 1
    env_entry = body["environments"][0]
    assert env_entry["environment_id"] == test_environment.id
    assert len(env_entry["subsystems"]) == 1
    sub_entry = env_entry["subsystems"][0]
    assert sub_entry["subsystem_id"] == test_subsystem.id
    match_by_host = {m["host_id"]: m for m in sub_entry["matches"]}
    assert match_by_host[h1["id"]]["role"] == "primary"
    assert match_by_host[h2["id"]]["role"] == "replica"


@pytest.mark.asyncio
async def test_host_impact_empty_for_no_host_ids(client, auth_headers):
    r = await client.get(
        "/api/v1/infrastructure-components/impact", headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"host_ids": [], "environments": []}


@pytest.mark.asyncio
async def test_update_writes_env_host_diff_history(
    client, auth_headers, test_environment, test_subsystem, cr_lifecycle
):
    host = (await client.post(
        "/api/v1/infrastructure-components/", headers=auth_headers,
        json=_host_payload(name="host-diff"),
    )).json()

    create = await client.post(
        "/api/v1/change-requests", headers=auth_headers,
        json=_cr_payload(
            cr_lifecycle.id,
            environment_ids=[test_environment.id],
        ),
    )
    cr_id = create.json()["id"]

    patch = await client.patch(
        f"/api/v1/change-requests/{cr_id}", headers=auth_headers,
        json={"host_ids": [host["id"]]},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["host_ids"] == [host["id"]]

    detail = await client.get(
        f"/api/v1/change-requests/{cr_id}", headers=auth_headers
    )
    history = detail.json()["history"]
    field_names = [h["field_name"] for h in history if h["field_name"]]
    assert "hosts" in field_names
