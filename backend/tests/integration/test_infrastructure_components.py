"""Integration tests for InfrastructureComponent + EnvironmentSubSystemHost."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.system import System, SubSystem
from app.db.models.environment import EnvironmentSubSystem
from app.db.models.infrastructure_component import (
    InfrastructureComponent,
    InfrastructureComponentSource,
    InfrastructureComponentType,
)


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


# ---------------------------------------------------------------------------
# Server-side sorting + widened search (sub-project C1 task 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_components_default_order_unchanged(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """No sort_by: order must stay `name, id` — today's ordering, byte for byte.

    Insertion order (Charlie, Alpha, Bravo) deliberately disagrees with name
    order, so a response that happened to preserve insertion/id order would not
    accidentally satisfy this assertion.
    """
    charlie = InfrastructureComponent(tenant_id=test_tenant.id, name="Charlie")
    alpha = InfrastructureComponent(tenant_id=test_tenant.id, name="Alpha")
    bravo = InfrastructureComponent(tenant_id=test_tenant.id, name="Bravo")
    db_session.add_all([charlie, alpha, bravo])
    await db_session.commit()

    response = await client.get("/api/v1/infrastructure-components/", headers=auth_headers)
    assert response.status_code == 200
    assert [c["id"] for c in response.json()] == [alpha.id, bravo.id, charlie.id]


@pytest.mark.asyncio
async def test_list_components_sort_by_name_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    charlie = InfrastructureComponent(tenant_id=test_tenant.id, name="Charlie")
    alpha = InfrastructureComponent(tenant_id=test_tenant.id, name="Alpha")
    bravo = InfrastructureComponent(tenant_id=test_tenant.id, name="Bravo")
    db_session.add_all([charlie, alpha, bravo])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=name&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [c["id"] for c in asc.json()] == [alpha.id, bravo.id, charlie.id]

    desc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=name&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [c["id"] for c in desc.json()] == [charlie.id, bravo.id, alpha.id]


@pytest.mark.asyncio
async def test_list_components_sort_by_component_type_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """Names/ids are already ascending here, so only component_type sorting —
    not the name tiebreaker or insertion order — could produce these sequences.

    component_type is stored via `values_callable` (the enum's `.value`, e.g.
    "cache"/"load_balancer"/"server"), so this also pins that sorting happens
    on the lowercase value column, not the Python-side enum name.
    """
    c1 = InfrastructureComponent(
        tenant_id=test_tenant.id, name="C1", component_type=InfrastructureComponentType.SERVER
    )
    c2 = InfrastructureComponent(
        tenant_id=test_tenant.id, name="C2", component_type=InfrastructureComponentType.CACHE
    )
    c3 = InfrastructureComponent(
        tenant_id=test_tenant.id, name="C3", component_type=InfrastructureComponentType.LOAD_BALANCER
    )
    db_session.add_all([c1, c2, c3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=component_type&sort_dir=asc",
        headers=auth_headers,
    )
    assert asc.status_code == 200
    assert [c["id"] for c in asc.json()] == [c2.id, c3.id, c1.id]

    desc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=component_type&sort_dir=desc",
        headers=auth_headers,
    )
    assert desc.status_code == 200
    assert [c["id"] for c in desc.json()] == [c1.id, c3.id, c2.id]


@pytest.mark.asyncio
async def test_list_components_sort_by_provider_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    p1 = InfrastructureComponent(tenant_id=test_tenant.id, name="P1", provider="zebra")
    p2 = InfrastructureComponent(tenant_id=test_tenant.id, name="P2", provider="alpha")
    p3 = InfrastructureComponent(tenant_id=test_tenant.id, name="P3", provider="mid")
    db_session.add_all([p1, p2, p3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=provider&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [c["id"] for c in asc.json()] == [p2.id, p3.id, p1.id]

    desc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=provider&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [c["id"] for c in desc.json()] == [p1.id, p3.id, p2.id]


@pytest.mark.asyncio
async def test_list_components_sort_by_region_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    r1 = InfrastructureComponent(tenant_id=test_tenant.id, name="R1", region="west")
    r2 = InfrastructureComponent(tenant_id=test_tenant.id, name="R2", region="east")
    r3 = InfrastructureComponent(tenant_id=test_tenant.id, name="R3", region="central")
    db_session.add_all([r1, r2, r3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=region&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [c["id"] for c in asc.json()] == [r3.id, r2.id, r1.id]

    desc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=region&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [c["id"] for c in desc.json()] == [r1.id, r2.id, r3.id]


@pytest.mark.asyncio
async def test_list_components_sort_by_source_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """source is also stored via `values_callable` — "docker_compose" < "manual"
    < "terraform" alphabetically."""
    s1 = InfrastructureComponent(
        tenant_id=test_tenant.id, name="S1", source=InfrastructureComponentSource.TERRAFORM
    )
    s2 = InfrastructureComponent(
        tenant_id=test_tenant.id, name="S2", source=InfrastructureComponentSource.MANUAL
    )
    s3 = InfrastructureComponent(
        tenant_id=test_tenant.id, name="S3", source=InfrastructureComponentSource.DOCKER_COMPOSE
    )
    db_session.add_all([s1, s2, s3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=source&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [c["id"] for c in asc.json()] == [s3.id, s2.id, s1.id]

    desc = await client.get(
        "/api/v1/infrastructure-components/?sort_by=source&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [c["id"] for c in desc.json()] == [s1.id, s2.id, s3.id]


@pytest.mark.asyncio
async def test_list_components_sort_by_unknown_field_is_422(client, auth_headers):
    """Through the real endpoint, not just Task 1's probe app."""
    response = await client.get(
        "/api/v1/infrastructure-components/?sort_by=nonexistent", headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_matches_name_even_when_provider_and_region_are_null(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """The nullable-column trap: `provider`/`region` are NULL on this row, and a
    naive widening that ANDs a per-field ILIKE (instead of ORing them) would
    turn `name ILIKE '%prod%' AND NULL AND NULL` into NULL — silently dropping
    a row whose name plainly matches. `provider`/`region` default to None here
    (never set), so this is exactly that shape.
    """
    match = InfrastructureComponent(tenant_id=test_tenant.id, name="prod-web-1")
    db_session.add(match)
    await db_session.commit()
    await db_session.refresh(match)
    assert match.provider is None
    assert match.region is None

    response = await client.get(
        "/api/v1/infrastructure-components/?search=prod", headers=auth_headers
    )
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()}
    assert match.id in ids


@pytest.mark.asyncio
async def test_search_widened_to_match_provider_when_name_does_not(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """The actual widening under test: a row whose `name` does not contain the
    search term at all is still returned because `provider` does. A search that
    only ever matched `name` (the un-widened code) would pass every test that
    only covers name matches and fail this one.
    """
    provider_match = InfrastructureComponent(
        tenant_id=test_tenant.id, name="Unrelated-Box", provider="aws-production"
    )
    no_match = InfrastructureComponent(
        tenant_id=test_tenant.id, name="Nothing-Here", provider="on_premise", region="dev-zone"
    )
    db_session.add_all([provider_match, no_match])
    await db_session.commit()

    response = await client.get(
        "/api/v1/infrastructure-components/?search=PROD", headers=auth_headers
    )
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()}
    assert ids == {provider_match.id}


@pytest.mark.asyncio
async def test_search_widened_to_match_region_when_name_does_not(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """Same widening, but for `region` specifically — a fix that widened
    `provider` and forgot `region` would fail this one while passing the
    provider-mirror test above."""
    region_match = InfrastructureComponent(
        tenant_id=test_tenant.id, name="Unrelated-Box-2", region="us-production-1"
    )
    no_match = InfrastructureComponent(
        tenant_id=test_tenant.id, name="Nothing-Here-2", provider="on_premise", region="dev-zone"
    )
    db_session.add_all([region_match, no_match])
    await db_session.commit()

    response = await client.get(
        "/api/v1/infrastructure-components/?search=PROD", headers=auth_headers
    )
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()}
    assert ids == {region_match.id}
