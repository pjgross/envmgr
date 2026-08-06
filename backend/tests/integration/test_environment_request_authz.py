"""The role × group × kind × Admin-bypass matrix.

Each test must FAIL if its rule is inverted, not merely pass today.
"""
import pytest

from app.core.security import get_password_hash
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.lifecycle import LifecycleTemplate
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


# ---------------------------------------------------------------------------
# Fix pass: C1, C2, I1, I2, I3, I4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_requester_may_submit_their_own_draft(
    client, db_session, test_tenant, environment_request_lifecycle
):
    """C1: the group gate must not block a requester from submitting — the
    person requesting access is by definition not on the team that operates
    the environment. Reproduced live as a 403 before this fix."""
    env = await ensure_environment(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-C1-submit")
    env.operations_group_id = group.id
    await db_session.commit()
    await _member(db_session, test_tenant, "viewer-submit", "Viewer", None)

    headers = await _login(client, test_tenant.slug, "viewer-submit")
    created = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]

    ok = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_a_requester_may_cancel_their_own_draft(
    client, db_session, test_tenant, environment_request_lifecycle
):
    """C1, the 'cancel' half: 'draft' is not an APPROVAL_TARGET_STATE either."""
    env = await ensure_environment(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-C1-cancel")
    env.operations_group_id = group.id
    await db_session.commit()
    await _member(db_session, test_tenant, "viewer-cancel", "Viewer", None)

    headers = await _login(client, test_tenant.slug, "viewer-cancel")
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=headers,
    )).json()["id"]

    ok = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "cancelled"}, headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_a_viewer_still_cannot_approve(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """C1 widens who may SUBMIT; it must not widen who may APPROVE. 'approved'
    stays in APPROVAL_TARGET_STATES, and a Viewer fails the ROLE gate on it
    regardless of group membership."""
    env = await ensure_environment(db_session, test_tenant.id)
    await _member(db_session, test_tenant, "viewer-noapprove", "Viewer", None)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "viewer-noapprove")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_admin_is_refused_a_transition_the_template_excludes_them_from(
    client, db_session, test_tenant, test_user, auth_headers, environment_request_lifecycle
):
    """C2: 'Admin bypasses the group, never the role' is untestable under the
    seeded template, where Admin sits in every transition's allowed_roles.
    Build a bespoke template that excludes Admin from one transition and
    prove an Admin is actually refused it — auth_headers is an Admin who is
    a member of no group, so the group bypass alone would let them through
    if the role gate did not independently bind."""
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id, entity_type="environment_request",
        name="No-Admin-Approve",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {"from_state": "submitted", "to_state": "approved", "label": "Approve",
                 "allowed_roles": ["Test Manager"]},
            ],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    env = await ensure_environment(db_session, test_tenant.id)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=test_user.id,
        justification="j", environment_id=env.id,
    )
    db_session.add(req)
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=auth_headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_membership_of_a_different_group_is_refused(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """I1: membership of ANY group in the tenant must not satisfy the check —
    only membership of the environment's OWN operating group. The outsider
    here is in group B; the environment is operated by group A."""
    group_a = await ensure_user_group(db_session, test_tenant.id, name="Ops A")
    group_b = await ensure_user_group(db_session, test_tenant.id, name="Ops B")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group_a.id
    await db_session.commit()
    await _member(db_session, test_tenant, "tm-groupb", "Test Manager", group_b)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-groupb")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_a_membership_row_denormalized_to_the_wrong_tenant_is_refused(
    client, db_session, test_tenant, test_user, second_tenant_factory,
    environment_request_lifecycle,
):
    """I2: the tenant_id filters in _is_in_operations_group are defence in
    depth, same as Task 4's actionable-clause finding. This row's group_id
    points at the REAL operating group, but its denormalized tenant_id
    disagrees — only a query that actually checks tenant_id refuses it."""
    other_tenant, _ = await second_tenant_factory("Other Org I2", "other-org-i2")
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-I2")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    actor = await _member(db_session, test_tenant, "tm-bad-tenant", "Test Manager", None)
    db_session.add(UserGroupMember(
        tenant_id=other_tenant.id, group_id=group.id, user_id=actor.id
    ))
    await db_session.commit()
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-bad-tenant")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "approved"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_allowed_transitions_offers_approve_to_an_in_group_approver(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """I3: the UI drives its buttons from this endpoint — it must offer
    what will actually succeed."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-I3-a")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    await _member(db_session, test_tenant, "tm-i3-in", "Test Manager", group)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-i3-in")
    resp = await client.get(
        f"/api/v1/environment-requests/{req.id}/allowed-transitions", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "approved" in {t["to_state"] for t in resp.json()}


@pytest.mark.asyncio
async def test_allowed_transitions_resolves_against_the_impersonated_tenant(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """I3: switching the endpoint's tenant argument to current_user.tenant_id
    would resolve the template lookup against the caller's HOME tenant under
    impersonation, missing it entirely and returning []. Mirrors
    test_the_group_check_resolves_against_the_impersonated_tenant."""
    from app.core.security import create_access_token
    from app.db.models.user import Tenant

    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-I3-imp")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()

    home = Tenant(name="System Org I3", slug="system-req-imp-i3")
    db_session.add(home)
    await db_session.flush()
    master = User(
        tenant_id=home.id, username="req-masteradmin-i3", email="rm-i3@imp.com",
        password_hash=get_password_hash("password123"), role="Test Manager",
        is_active=True, is_master_admin=True,
    )
    db_session.add(master)
    await db_session.flush()
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=master.id
    ))
    req = await _submitted_request(db_session, test_tenant, env, test_user)
    await db_session.commit()

    token = create_access_token({
        "sub": str(master.id),
        "tenant_id": home.id,
        "impersonating_tenant_id": test_tenant.id,
    })
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(
        f"/api/v1/environment-requests/{req.id}/allowed-transitions", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "approved" in {t["to_state"] for t in resp.json()}


@pytest.mark.asyncio
async def test_allowed_transitions_hides_group_gated_transitions_from_an_outsider(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """I3: dropping the group gate here leaves 29/29 green elsewhere — this
    is the dedicated coverage. An approver-role outsider must not see
    'approved' or 'rejected' offered."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-I3-b")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    await _member(db_session, test_tenant, "tm-i3-out", "Test Manager", None)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "tm-i3-out")
    resp = await client.get(
        f"/api/v1/environment-requests/{req.id}/allowed-transitions", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    to_states = {t["to_state"] for t in resp.json()}
    assert to_states.isdisjoint({"approved", "rejected", "fulfilled"})


@pytest.mark.asyncio
async def test_allowed_transitions_still_applies_the_role_gate(
    client, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """I3: dropping the ROLE gate specifically would leak 'draft' (Return
    for Revision, an APPROVER-only transition that is NOT group-gated under
    C1) to a Viewer who has no role permission for anything out of
    'submitted'. Membership doesn't matter here — role alone must produce
    an empty list."""
    env = await ensure_environment(db_session, test_tenant.id)
    await _member(db_session, test_tenant, "viewer-i3-role", "Viewer", None)
    req = await _submitted_request(db_session, test_tenant, env, test_user)

    headers = await _login(client, test_tenant.slug, "viewer-i3-role")
    resp = await client.get(
        f"/api/v1/environment-requests/{req.id}/allowed-transitions", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


@pytest.mark.asyncio
async def test_allowed_transitions_still_offers_submit_to_the_requester(
    client, db_session, test_tenant, environment_request_lifecycle
):
    """I3, after C1: a requester who is not on the operating team must still
    be offered 'submitted' for their own draft."""
    env = await ensure_environment(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-I3-c")
    env.operations_group_id = group.id
    await db_session.commit()
    await _member(db_session, test_tenant, "viewer-i3-submit", "Viewer", None)

    headers = await _login(client, test_tenant.slug, "viewer-i3-submit")
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=headers,
    )).json()["id"]

    resp = await client.get(
        f"/api/v1/environment-requests/{rid}/allowed-transitions", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "submitted" in {t["to_state"] for t in resp.json()}


@pytest.mark.asyncio
async def test_unauthorized_submit_is_403_not_409_even_with_no_operations_team(
    client, db_session, test_tenant, environment_request_lifecycle
):
    """I4: authorization must be checked before the routability business
    rule — an unauthorized caller must never learn 'this environment has no
    operations team' (409) instead of simply being refused (403). Uses a
    bespoke template that excludes the actor's role from draft->submitted,
    on an environment with no operations team, so the OLD ordering would
    surface the 409 first."""
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id, entity_type="environment_request",
        name="Admin-Only-Submit",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "submitted", "label": "Submit",
                 "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = None
    viewer = await _member(db_session, test_tenant, "viewer-i4", "Viewer", None)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="draft",
        lifecycle_id=tpl.id, requested_by=viewer.id,
        justification="j", environment_id=env.id,
    )
    db_session.add(req)
    await db_session.commit()

    headers = await _login(client, test_tenant.slug, "viewer-i4")
    refused = await client.post(
        f"/api/v1/environment-requests/{req.id}/transition",
        json={"to_state": "submitted"}, headers=headers,
    )
    assert refused.status_code == 403, refused.text
