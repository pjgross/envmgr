"""Request CRUD and mode validation. Authorization has its own file."""
import pytest

from tests.factories import ensure_environment, ensure_environment_tier, ensure_user_group


async def _env(db_session, tenant_id, group=True):
    env = await ensure_environment(db_session, tenant_id)
    if group:
        grp = await ensure_user_group(db_session, tenant_id)
        env.operations_group_id = grp.id
    await db_session.commit()
    return env


@pytest.mark.asyncio
async def test_create_an_access_request(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
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
async def test_access_request_without_an_environment_is_422(
    client, auth_headers, environment_request_lifecycle
):
    bad = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "justification": "no target"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text
    assert "environment_id" in bad.text


@pytest.mark.asyncio
async def test_new_environment_request_needs_name_tier_and_expiry(
    client, auth_headers, environment_request_lifecycle
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
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
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
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
    environment_request_lifecycle,
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
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
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


@pytest.mark.asyncio
async def test_patch_cannot_null_out_the_access_targets_environment(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """The service re-validates the resulting state after applying a PATCH, not
    just the incoming payload — this pins that a PATCH which would leave an
    'access' request without its environment_id is refused, naming the field."""
    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "first"},
        headers=auth_headers,
    )).json()["id"]

    broken = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"environment_id": None},
        headers=auth_headers,
    )
    assert broken.status_code == 422, broken.text
    assert "environment_id" in broken.text


@pytest.mark.asyncio
async def test_patch_cannot_null_out_the_new_environment_targets_tier(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf testing",
              "proposed_name": "Mortgage PERF", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]

    broken = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"tier_id": None},
        headers=auth_headers,
    )
    assert broken.status_code == 422, broken.text
    # Only tier_id is missing from the RESULTING state — proposed_name and
    # expires_at are still set on the row, untouched by this PATCH. A
    # validator that checked the payload instead of the merged object would
    # see those two as absent too (they're not in the payload) and name them
    # here as well, so this pins re-validation against the resulting object.
    assert "tier_id" in broken.text
    assert "proposed_name" not in broken.text
    assert "expires_at" not in broken.text


@pytest.mark.asyncio
async def test_patch_cannot_target_another_tenants_tier(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
    environment_request_lifecycle,
):
    """404, never 403 — mirrors test_cannot_target_another_tenants_environment
    but on the update path, which the committed suite never covered. This is
    the IDOR class a 2026-07-16 audit found four instances of, and which the
    previous sub-project's review found a fifth of specifically on an update
    path."""
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf testing",
              "proposed_name": "Mortgage PERF", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]

    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment_tier(db_session, other_tenant.id)
    await db_session.commit()

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"tier_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_patch_cannot_target_another_tenants_operations_group(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
    environment_request_lifecycle,
):
    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "first"},
        headers=auth_headers,
    )).json()["id"]

    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id)
    await db_session.commit()

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_patch_cannot_change_kind(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """EnvironmentRequestUpdate has no `kind` field, so Pydantic silently drops
    an unknown key rather than erroring — this pins that behaviour so a future
    schema change can't accidentally make mode-switching possible."""
    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "first"},
        headers=auth_headers,
    )).json()["id"]

    patched = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"kind": "new_environment"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["kind"] == "access"
