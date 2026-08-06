"""The handover endpoint: who may write, and — more importantly — WHAT it accepts."""
import pytest

from app.core.security import get_password_hash
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from tests.factories import ensure_environment, ensure_environment_tier, ensure_user_group


async def _login(client, tenant_slug, username, password="password123"):
    r = await client.post("/api/v1/auth/login", json={
        "username": username, "password": password, "tenant_slug": tenant_slug,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _env_with_team(db_session, tenant, member_username=None, role="Developer"):
    group = await ensure_user_group(db_session, tenant.id, name="Ops")
    env = await ensure_environment(db_session, tenant.id)
    env.operations_group_id = group.id
    await db_session.flush()
    if member_username:
        # Not "@t.local" as in the brief — email-validator treats .local as an
        # IANA special-use TLD and rejects it, which breaks the login this
        # helper is about to perform with a 500 rather than the intended
        # status code. Same workaround as test_environment_request_authz.py.
        user = User(
            tenant_id=tenant.id, username=member_username,
            email=f"{member_username}@example.com",
            password_hash=get_password_hash("password123"),
            role=role, is_active=True,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(UserGroupMember(
            tenant_id=tenant.id, group_id=group.id, user_id=user.id
        ))
    await db_session.commit()
    return env, group


@pytest.mark.asyncio
async def test_the_operating_team_may_author_handover_fields(
    client, db_session, test_tenant
):
    """A Developer — who cannot touch PATCH /environments at all — can do this."""
    env, _ = await _env_with_team(db_session, test_tenant, "dev-in-team")
    headers = await _login(client, test_tenant.slug, "dev-in-team")

    ok = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://sit.example.com",
              "connection_notes": "VPN: corp-vpn. Credentials: ask #platform-ops."},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["access_url"] == "https://sit.example.com"


@pytest.mark.asyncio
async def test_a_non_member_is_refused(client, db_session, test_tenant):
    env, _ = await _env_with_team(db_session, test_tenant)
    outsider = User(
        tenant_id=test_tenant.id, username="outsider", email="o@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(outsider)
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "outsider")

    refused = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://nope"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_a_member_of_a_different_group_is_refused(client, db_session, test_tenant):
    """A membership check that matches ANY group in the tenant — rather than
    THIS environment's operations_group_id specifically — would pass
    test_a_non_member_is_refused too, since that outsider belongs to no group
    at all. This is the test that actually distinguishes the two: the actor
    is a member of a real group, just not the one operating this environment.
    """
    env, _ = await _env_with_team(db_session, test_tenant)
    other_group = await ensure_user_group(db_session, test_tenant.id, name="Other Team")
    member = User(
        tenant_id=test_tenant.id, username="wrong-team", email="wt@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=other_group.id, user_id=member.id
    ))
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "wrong-team")

    refused = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://nope"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_a_membership_row_denormalized_to_the_wrong_tenant_is_refused(
    client, db_session, test_tenant, second_tenant_factory,
):
    """`user_group_member.tenant_id` is denormalized (derivable through
    group_id) — see the model docstring. This row's group_id points at the
    REAL operating group and its user_id at a real user in test_tenant, but
    its tenant_id disagrees. Only a query that actually filters on
    UserGroupMember.tenant_id, not just Environment.tenant_id, refuses it."""
    other_tenant, _ = await second_tenant_factory("Other Org Handover", "other-org-handover")
    env, group = await _env_with_team(db_session, test_tenant)
    actor = User(
        tenant_id=test_tenant.id, username="bad-tenant-row", email="btr@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(actor)
    await db_session.flush()
    db_session.add(UserGroupMember(
        tenant_id=other_tenant.id, group_id=group.id, user_id=actor.id
    ))
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "bad-tenant-row")

    refused = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"access_url": "https://nope"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_an_admin_may_author_them_without_being_in_the_team(
    client, auth_headers, db_session, test_tenant
):
    env, _ = await _env_with_team(db_session, test_tenant)
    ok = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"support_contact": "#platform-ops"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text
    # Assert the WRITE, not just the status. A 200 alone would still pass if
    # update_handover silently no-opped on this path.
    assert ok.json()["support_contact"] == "#platform-ops"


@pytest.mark.asyncio
async def test_an_environment_with_no_team_is_admin_only(
    client, auth_headers, db_session, test_tenant
):
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = None
    await db_session.commit()

    ok = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"sla_notes": "best effort"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["sla_notes"] == "best effort"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"tier_id": 1},
        {"owner_user_id": 1},
        {"operations_group_id": 1},
        {"status": "active"},
        {"name": "renamed"},
        {"expires_at": "2030-01-01T00:00:00Z"},
    ],
)
async def test_it_rejects_every_non_handover_key(
    client, db_session, test_tenant, payload
):
    """THE test for this endpoint.

    Its safety rests on the narrow surface, not on the permission. A member of
    an operating team must not be able to change which team operates the
    environment, clear its owner, or rename it. Asserted by SENDING those keys,
    not by reading the schema.
    """
    env, _ = await _env_with_team(db_session, test_tenant, "dev-in-team")
    headers = await _login(client, test_tenant.slug, "dev-in-team")

    refused = await client.patch(
        f"/api/v1/environments/{env.id}/handover", json=payload, headers=headers,
    )
    assert refused.status_code == 422, f"{payload} was accepted: {refused.text}"


@pytest.mark.asyncio
async def test_handover_fields_are_absent_from_the_ordinary_update_path(
    client, auth_headers, db_session, test_tenant
):
    """One write path, not two to keep in step.

    The environment is given an owner first. Without one, PATCH /environments
    unconditionally 422s ("must have a named owner") regardless of what else
    is in the body — which would make this test pass for the wrong reason,
    true whether or not access_url is actually rejected. With an owner
    present, the 422 can only come from EnvironmentUpdate refusing the
    unknown key.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    env.owner_user_id = me.json()["id"]
    await db_session.commit()

    refused = await client.patch(
        f"/api/v1/environments/{env.id}",
        json={"access_url": "https://via-the-wrong-door"}, headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_an_environment_with_no_team_is_still_refused_to_a_non_admin(
    client, db_session, test_tenant
):
    """The other half of "no team degrades to Admin-only".

    The suite covered "not nobody" (an Admin succeeds) but never "not
    everybody". A NULL operations_group_id joins to no membership row, so a
    non-member is correctly refused — but nothing asserted it.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = None
    outsider = User(
        tenant_id=test_tenant.id, username="no-team-outsider",
        email="no-team-outsider@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(outsider)
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "no-team-outsider")

    refused = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"sla_notes": "best effort"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_m1_a_master_admin_whose_role_is_not_admin_may_author_handover(
    client, db_session, test_tenant,
):
    """M1: the rest of the app (booking_service) treats is_master_admin as
    satisfying an Admin bypass alongside role == 'Admin', and both frontend
    gates on this action already check is_master_admin — this backend check
    didn't, so a master admin whose own row isn't role 'Admin' saw an
    enabled control that then 403'd."""
    env, _ = await _env_with_team(db_session, test_tenant)
    master = User(
        tenant_id=test_tenant.id, username="m1-handover-master",
        email="m1-handover-master@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True, is_master_admin=True,
    )
    db_session.add(master)
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "m1-handover-master")

    ok = await client.patch(
        f"/api/v1/environments/{env.id}/handover",
        json={"support_contact": "#m1-support"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["support_contact"] == "#m1-support"
