"""Request CRUD and mode validation. Authorization has its own file."""
import pytest
import pytest_asyncio

from app.services.environment_request_defaults import (
    seed_environment_request_defaults_for_tenant,
)
from tests.factories import ensure_environment, ensure_environment_tier, ensure_user_group


@pytest_asyncio.fixture(autouse=True)
async def _seed_request_lifecycle(db_session, test_tenant):
    """The `test_tenant` fixture builds a bare Tenant row directly, bypassing
    tenant_service.create_tenant — the only place that calls the seeder — so
    every test in this file needs the environment_request lifecycle seeded by
    hand, the same way test_change_requests.py builds its own
    LifecycleTemplate rather than relying on one existing for test_tenant."""
    await seed_environment_request_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()


async def _env(db_session, tenant_id, group=True):
    env = await ensure_environment(db_session, tenant_id)
    if group:
        grp = await ensure_user_group(db_session, tenant_id)
        env.operations_group_id = grp.id
    await db_session.commit()
    return env


@pytest.mark.asyncio
async def test_create_an_access_request(client, auth_headers, db_session, test_tenant):
    env = await _env(db_session, test_tenant.id)

    created = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id,
              "justification": "Need it for UAT"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "access"
    assert body["status"] == "draft"
    # Display names travel with the row — never resolved in the browser
    # against a capped collection.
    assert body["environment_name"] == env.name
    # test_user (the fixture behind auth_headers) is seeded as "testadmin".
    assert body["requester_username"] == "testadmin"


@pytest.mark.asyncio
async def test_access_request_without_an_environment_is_422(client, auth_headers):
    bad = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "justification": "no target"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text
    assert "environment_id" in bad.text


@pytest.mark.asyncio
async def test_new_environment_request_needs_name_tier_and_expiry(
    client, auth_headers
):
    bad = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "need a perf env"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text
    for field in ("proposed_name", "tier_id", "expires_at"):
        assert field in bad.text


@pytest.mark.asyncio
async def test_create_a_new_environment_request(
    client, auth_headers, db_session, test_tenant
):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf testing",
              "proposed_name": "Mortgage PERF", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["proposed_name"] == "Mortgage PERF"
    assert created.json()["environment_id"] is None


@pytest.mark.asyncio
async def test_cannot_target_another_tenants_environment(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """404, never 403 — a 403 confirms the environment exists."""
    # The fixture yields a FACTORY; calling it returns (Tenant, User).
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": theirs.id,
              "justification": "leaky"},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_only_a_draft_can_be_edited(
    client, auth_headers, db_session, test_tenant
):
    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "first"},
        headers=auth_headers,
    )).json()["id"]

    edited = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"justification": "revised"},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["justification"] == "revised"

    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    frozen = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"justification": "too late"},
        headers=auth_headers,
    )
    assert frozen.status_code == 409, frozen.text
