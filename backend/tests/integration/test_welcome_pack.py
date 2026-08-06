"""The Welcome Pack — a read model, stored nowhere."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.environment import EnvironmentStatus
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.user_group import UserGroupMember
from tests.factories import (
    ensure_environment,
    ensure_environment_tier,
    ensure_user,
    ensure_user_group,
)


async def _fulfilled_access_request(client, headers, db_session, tenant):
    group = await ensure_user_group(db_session, tenant.id, name="Platform Ops")
    member = await ensure_user(db_session, tenant.id, username="ops-ada")
    db_session.add(UserGroupMember(
        tenant_id=tenant.id, group_id=group.id, user_id=member.id
    ))
    env = await ensure_environment(db_session, tenant.id)
    env.operations_group_id = group.id
    env.access_url = "https://sit.example.com"
    env.connection_notes = "VPN: corp-vpn. Credentials: ask #platform-ops."
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "UAT"},
        headers=headers,
    )).json()["id"]
    for state in ("submitted", "approved", "fulfilled"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=headers,
        )
        assert r.status_code == 200, r.text
    return rid, env


@pytest.mark.asyncio
async def test_pack_is_refused_before_fulfilment(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]

    early = await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )
    assert early.status_code == 409, early.text


@pytest.mark.asyncio
async def test_pack_carries_the_environment_and_its_team(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    rid, env = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )
    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()

    assert pack["environment"]["name"] == env.name
    assert pack["access"]["access_url"] == "https://sit.example.com"
    # The member list travels WITH the response. Resolving it in the browser
    # against /tenant/users/lite — which is capped — is the `.find()`-into-a-
    # capped-collection failure that renders a miss as '—'.
    assert "ops-ada" in pack["support"]["operations_group_members"]


@pytest.mark.asyncio
async def test_unfilled_fields_read_as_not_provided(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """An empty section reads as 'there is nothing to do'. Absent data and
    checked-and-found-nothing must not be indistinguishable."""
    rid, _ = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )
    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()

    assert pack["support"]["sla_notes"] == "Not provided"
    assert pack["caveats"]["known_limitations"] == "Not provided"
    assert pack["offboarding"]["decommission_notes"] == "Not provided"


@pytest.mark.asyncio
async def test_pack_reads_live_from_the_environment(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """Nothing is frozen at fulfilment — a changed URL updates every pack."""
    rid, env = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )
    await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://moved.example.com"}, headers=auth_headers,
    )

    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()
    assert pack["access"]["access_url"] == "https://moved.example.com"


@pytest.mark.asyncio
async def test_pack_for_new_environment_request_describes_created_environment(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """The pack resolves its environment as `environment_id or
    created_environment_id`. The brief's tests only exercise the `access`
    path (environment_id); nothing else proves the created_environment_id
    branch works."""
    from datetime import datetime, timedelta, timezone

    from tests.factories import ensure_environment_tier

    group = await ensure_user_group(db_session, test_tenant.id, name="New-Env Ops")
    tier = await ensure_environment_tier(db_session, test_tenant.id, name="UAT")
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={
            "kind": "new_environment",
            "justification": "new sandbox",
            "proposed_name": "welcome-pack-new-env",
            "tier_id": tier.id,
            "expires_at": expires_at,
        },
        headers=auth_headers,
    )).json()["id"]

    # operations_group_id must be set before submission — a request can only
    # be edited while it is a draft, and _fulfil_new_environment requires it.
    patched = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text

    r = None
    for state in ("submitted", "approved", "fulfilled"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )
        assert r.status_code == 200, r.text

    created_environment_id = r.json()["created_environment_id"]
    assert created_environment_id is not None

    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()
    assert pack["environment"]["id"] == created_environment_id
    assert pack["environment"]["name"] == "welcome-pack-new-env"


@pytest.mark.asyncio
async def test_pack_for_cross_tenant_request_is_404(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
    environment_request_lifecycle,
):
    """A request id that belongs to another tenant must 404, never 403 and
    never a pack — same rule as get_request_view everywhere else."""
    rid, _ = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )

    other_tenant, other_user = await second_tenant_factory("Other Org", "other-tenant")
    other_login = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    other_headers = {
        "Authorization": f"Bearer {other_login.json()['access_token']}"
    }

    resp = await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=other_headers
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_member_list_ignores_another_tenants_membership_row(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
    environment_request_lifecycle,
):
    """The membership query must filter on tenant_id, the same way
    _view_query's joins do — a malformed row (here, a UserGroupMember whose
    tenant_id doesn't match the group it points at) must not surface another
    tenant's user in this tenant's welcome pack. This filter has gone missing
    twice before in this task set, and no prior test caught either time."""
    rid, env = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )

    other_tenant, other_user = await second_tenant_factory("Leak Org", "leak-org")
    # A malformed/cross-tenant row: tenant_id belongs to other_tenant, but
    # group_id points at test_tenant's real operations group.
    db_session.add(UserGroupMember(
        tenant_id=other_tenant.id, group_id=env.operations_group_id,
        user_id=other_user.id,
    ))
    await db_session.commit()

    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()

    assert other_user.username not in pack["support"]["operations_group_members"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_state,path",
    [
        ("submitted", ("submitted",)),
        ("approved", ("submitted", "approved")),
        ("rejected", ("submitted", "rejected")),
        ("cancelled", ("cancelled",)),
    ],
)
async def test_pack_is_refused_for_every_non_fulfilled_state(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle,
    target_state, path,
):
    """The 409 guard is `req.status == "fulfilled"`, not merely "not draft".
    A narrowing to `== "draft"` would leave `submitted`/`approved`/`rejected`/
    `cancelled` unguarded and every prior test (which only exercises `draft`)
    green."""
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]

    for to_state in path:
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": to_state}, headers=auth_headers,
        )
        assert r.status_code == 200, r.text

    resp = await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_pack_environment_lookup_is_tenant_scoped(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
    environment_request_lifecycle,
):
    """The pack's own `Environment` lookup filters on `tenant_id` as well as
    `id`. Dropping that filter is invisible through the normal creation path
    (a request's `environment_id` is validated against the active tenant at
    creation time), so this test bypasses creation and repoints an already-
    fulfilled request's `environment_id` at a real environment belonging to a
    different tenant. Correct behaviour is 404 — the row exists, just not for
    this tenant. This is the fourth instance of this exact blind spot on this
    branch (the `actionable` filter, `_is_in_operations_group`, and this
    task's own member-list query all had it missing until a test caught it)."""
    rid, _ = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )

    other_tenant, _ = await second_tenant_factory("Foreign Org", "foreign-org")
    foreign_env = await ensure_environment(db_session, other_tenant.id)
    await db_session.commit()

    req = (
        await db_session.execute(
            select(EnvironmentRequest).where(EnvironmentRequest.id == rid)
        )
    ).scalar_one()
    req.environment_id = foreign_env.id
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_pack_pins_every_field_to_its_expected_source(
    client, auth_headers, db_session, test_tenant, test_user,
    environment_request_lifecycle,
):
    """Proved concretely: wiring `access.support_contact` to `env.access_url`
    leaves the other 7 tests green, and the same is true of every other field
    below. Populate all six handover fields plus tier/status/owner/expiry and
    assert the *entire* response shape at once, so a field wired to the wrong
    source is caught regardless of which one it is."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Field-Pin Ops")
    member = await ensure_user(db_session, test_tenant.id, username="ops-pin")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=member.id
    ))
    owner = await ensure_user(db_session, test_tenant.id, username="env-owner")
    tier = await ensure_environment_tier(db_session, test_tenant.id, name="Pinned-Tier")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    env.owner_user_id = owner.id
    env.tier_id = tier.id
    env.status = EnvironmentStatus.MAINTENANCE
    expires_at = datetime(2027, 3, 15, tzinfo=timezone.utc)
    env.expires_at = expires_at
    await db_session.commit()

    handover = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={
            "access_url": "https://pinned.example.com",
            "connection_notes": "Connect via corp VPN, then SSH.",
            "support_contact": "#pinned-support",
            "sla_notes": "9am-5pm business days.",
            "known_limitations": "No SSO in this tier.",
            "decommission_notes": "Tear down after the pilot.",
        },
        headers=auth_headers,
    )
    assert handover.status_code == 200, handover.text

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={
            "kind": "access", "environment_id": env.id,
            "justification": "pin every field",
        },
        headers=auth_headers,
    )).json()["id"]
    for state in ("submitted", "approved", "fulfilled"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )
        assert r.status_code == 200, r.text

    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()

    assert pack["environment"]["id"] == env.id
    assert pack["environment"]["name"] == env.name
    assert pack["environment"]["tier"] == "Pinned-Tier"
    assert pack["environment"]["status"] == "maintenance"
    assert pack["environment"]["owner"] == "env-owner"
    # Deliberately None, not "Not provided" — a null expiry is a legitimate
    # "no expiry planned" state under this project's governance semantics,
    # not a missing value. Only free-text fields take the fallback.
    assert pack["environment"]["expires_at"].startswith("2027-03-15")

    assert pack["access"]["access_url"] == "https://pinned.example.com"
    assert pack["access"]["connection_notes"] == "Connect via corp VPN, then SSH."
    assert pack["access"]["support_contact"] == "#pinned-support"

    assert pack["support"]["sla_notes"] == "9am-5pm business days."
    assert pack["support"]["operations_group"] == "Field-Pin Ops"
    assert pack["support"]["operations_group_members"] == ["ops-pin"]

    assert pack["caveats"]["known_limitations"] == "No SSO in this tier."
    assert pack["offboarding"]["decommission_notes"] == "Tear down after the pilot."

    assert pack["context"]["requested_by"] == test_user.username
    assert pack["context"]["justification"] == "pin every field"
    assert pack["context"]["kind"] == "access"


@pytest.mark.asyncio
async def test_whitespace_only_handover_fields_read_as_not_provided(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle,
):
    """`_or_not_provided` strips before testing truthiness, so a field the
    team cleared by saving whitespace (rather than leaving it null) must
    still render as "Not provided", not as a blank string."""
    rid, env = await _fulfilled_access_request(
        client, auth_headers, db_session, test_tenant
    )
    handover = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={
            "access_url": "   ",
            "connection_notes": "   ",
            "support_contact": "   ",
            "sla_notes": "   ",
            "known_limitations": "   ",
            "decommission_notes": "   ",
        },
        headers=auth_headers,
    )
    assert handover.status_code == 200, handover.text

    pack = (await client.get(
        f"/api/v1/environment-requests/{rid}/welcome-pack", headers=auth_headers
    )).json()

    assert pack["access"]["access_url"] == "Not provided"
    assert pack["access"]["connection_notes"] == "Not provided"
    assert pack["access"]["support_contact"] == "Not provided"
    assert pack["support"]["sla_notes"] == "Not provided"
    assert pack["caveats"]["known_limitations"] == "Not provided"
    assert pack["offboarding"]["decommission_notes"] == "Not provided"

