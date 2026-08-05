"""The role × group × kind × Admin-bypass matrix.

Each test must FAIL if its rule is inverted, not merely pass today.
"""
import pytest

from app.core.security import get_password_hash
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from tests.factories import ensure_environment, ensure_user_group


async def _login(client, tenant_slug, username, password="password123"):
    r = await client.post("/api/v1/auth/login", json={
        "username": username, "password": password, "tenant_slug": tenant_slug,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _member(db_session, tenant, username, role, group=None):
    # NOTE: not "@t.local" as in the brief — email-validator treats .local as
    # an IANA special-use TLD and rejects it, which broke every login in this
    # file with a 500 from UserResponse's EmailStr validation rather than the
    # intended 404/403 assertions. tests/factories.ensure_user has the same
    # latent ".local" bug; it just hasn't been exercised through a real login.
    user = User(
        tenant_id=tenant.id, username=username, email=f"{username}@example.com",
        password_hash=get_password_hash("password123"), role=role, is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    if group is not None:
        db_session.add(UserGroupMember(
            tenant_id=tenant.id, group_id=group.id, user_id=user.id
        ))
    await db_session.commit()
    return user


async def _submitted_request(db_session, tenant, env, requester):
    from app.services.environment_request_service import _default_lifecycle
    tpl = await _default_lifecycle(db_session, tenant.id)
    req = EnvironmentRequest(
        tenant_id=tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=requester.id,
        justification="j", environment_id=env.id,
    )
    db_session.add(req)
    await db_session.commit()
    return req


@pytest.mark.asyncio
async def test_right_role_in_the_group_may_approve(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    approver = await _member(db_session, test_tenant, "tm-in", "Test Manager", group)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-in")
    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_right_role_NOT_in_the_group_is_refused(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """The rule that makes routing mean anything."""
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    outsider = await _member(db_session, test_tenant, "tm-out", "Test Manager", None)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-out")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_wrong_role_in_the_group_is_refused(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """Membership does not confer approval rights — the template still rules."""
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    viewer = await _member(db_session, test_tenant, "viewer-in", "Viewer", group)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "viewer-in")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_admin_bypasses_the_group_but_not_the_role(
    client, db_session, test_tenant, test_user, auth_headers, environment_request_lifecycle
):
    """auth_headers is an Admin who is in no group."""
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text

    # The role check still applies: no transition exists from 'approved' to
    # 'submitted', so even an Admin cannot make it.
    bad = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    assert bad.status_code == 400, bad.text


@pytest.mark.asyncio
async def test_a_new_environment_request_needs_an_admin(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """There is no environment, so the group clause cannot apply."""
    from app.services.environment_request_service import _default_lifecycle
    from tests.factories import ensure_environment_tier

    tier = await ensure_environment_tier(db_session, test_tenant.id)
    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="new_environment", status="submitted",
        lifecycle_id=tpl.id, requested_by=test_user.id, justification="j",
        proposed_name="New", tier_id=tier.id,
    )
    db_session.add(req)
    await db_session.commit()
    await _member(db_session, test_tenant, "rm", "Release Manager", None)

    headers = await _login(client, test_tenant.slug, "rm")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_submitting_without_an_operations_group_is_refused(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """B3a's promise: B3b refuses to ROUTE a request that has no team.

    Refused at submission rather than at action — a request only an Admin can
    see is one that sits unactioned with nobody knowing why.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = None
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]

    refused = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    assert refused.status_code == 409, refused.text
    assert env.name in refused.json()["detail"]


@pytest.mark.asyncio
async def test_an_empty_group_degrades_to_admin_only(
    client, auth_headers, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """A group with no members must not make a request unactionable."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Empty")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_the_group_check_resolves_against_the_impersonated_tenant(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """Under master-admin impersonation `current_user.id` and
    `active_tenant_id` belong to DIFFERENT tenants.

    The membership lookup joins on tenant_id, so resolving it against the
    caller's home tenant finds nothing and 403s a legitimate action. This
    mismatch has already broken an owner validation in this repo and killed an
    entire spreadsheet upload.

    The acting user's role is 'Test Manager' — an approver role, so the ROLE
    gate passes on its own merits — and they are a MEMBER of the impersonated
    tenant's group. Their role is deliberately not 'Admin', so the Admin bypass
    cannot mask a broken group lookup: the only way this transition succeeds is
    if the membership query resolves against the ACTIVE tenant.
    """
    from app.core.security import create_access_token
    from app.db.models.user import Tenant
    from app.db.models.user_group import UserGroupMember

    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id

    home = Tenant(name="System Org", slug="system-req-imp")
    db_session.add(home)
    await db_session.flush()
    master = User(
        tenant_id=home.id, username="req-masteradmin", email="rm@imp.com",
        password_hash=get_password_hash("password123"), role="Test Manager",
        is_active=True, is_master_admin=True,
    )
    db_session.add(master)
    await db_session.flush()
    membership = UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=master.id
    )
    db_session.add(membership)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    token = create_access_token({
        "sub": str(master.id),
        "tenant_id": home.id,
        "impersonating_tenant_id": test_tenant.id,
    })
    headers = {"Authorization": f"Bearer {token}"}

    ok = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text
