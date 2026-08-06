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
    """EnvironmentRequestUpdate has no `kind` field. Before M3
    (extra="forbid") Pydantic silently dropped the unknown key and returned
    200 with the kind unchanged; M3 now refuses the whole PATCH instead —
    still never lets `kind` change, just louder about it, matching M3's
    fix for `status`/`created_environment_id` doing the same thing."""
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
    assert patched.status_code == 422, patched.text

    still = (await client.get(
        f"/api/v1/environment-requests/{rid}", headers=auth_headers
    )).json()
    assert still["kind"] == "access"


@pytest.mark.asyncio
async def test_custom_fields_is_not_persisted(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """M4: no tenant can define a custom-field vocabulary for this entity, so
    `custom_fields` is no longer part of the create schema at all — a value
    sent for it is simply not there to read back, and the response no longer
    carries the key."""
    env = await _env(db_session, test_tenant.id)
    created = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j",
              "custom_fields": {"anything": "goes"}},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert "custom_fields" not in created.json()


@pytest.mark.asyncio
async def test_patch_rejects_server_controlled_fields(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """M3: EnvironmentRequestUpdate now has extra="forbid". A PATCH carrying
    `status` or `created_environment_id` — fields the service, not the
    client, is meant to control — used to return 200 and silently drop both,
    which looks exactly like a successful edit."""
    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "first"},
        headers=auth_headers,
    )).json()["id"]

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"status": "fulfilled", "created_environment_id": 999},
        headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text

    still = (await client.get(
        f"/api/v1/environment-requests/{rid}", headers=auth_headers
    )).json()
    assert still["status"] == "draft"
    assert still["created_environment_id"] is None


# ---------------------------------------------------------------------------
# Fix pass: C1 — an approved new-environment request with no operations group
# was unrecoverable (fulfilment 409s forever on the null group, editing 409s
# because the request has left draft, and the seeded template gives
# 'approved' exactly one outgoing edge). update_request now carves out
# operations_group_id ALONE, for an Admin, on a new_environment request, from
# 'submitted' or 'approved'.
# ---------------------------------------------------------------------------


async def _groupless_new_env_request(client, auth_headers, db_session, test_tenant, to_status):
    """A new_environment request with NO operations group, walked to
    `to_status` ('submitted' or 'approved') via the real API.
    `_assert_routable` only gates 'access' requests, so this is exactly how a
    real request reaches 'approved' with a null operations_group_id."""
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "no team yet",
              "proposed_name": f"Groupless {to_status}", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]
    for state in ("submitted", "approved"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        if state == to_status:
            break
    return rid


@pytest.mark.asyncio
async def test_admin_can_fix_a_groupless_submitted_new_environment_request(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    group = await ensure_user_group(db_session, test_tenant.id, name="C1-Fix-Submitted")
    await db_session.commit()
    rid = await _groupless_new_env_request(
        client, auth_headers, db_session, test_tenant, to_status="submitted"
    )

    fixed = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=auth_headers,
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["operations_group_id"] == group.id
    assert fixed.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_admin_can_fix_a_groupless_approved_new_environment_request(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """The actual failure mode C1 fixes: 'approved' has exactly one outgoing
    edge (approved -> fulfilled) and fulfilment 409s forever without a group —
    this is the point of no return the fix reopens."""
    group = await ensure_user_group(db_session, test_tenant.id, name="C1-Fix-Approved")
    await db_session.commit()
    rid = await _groupless_new_env_request(
        client, auth_headers, db_session, test_tenant, to_status="approved"
    )

    fixed = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=auth_headers,
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["operations_group_id"] == group.id
    assert fixed.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_non_admin_cannot_use_the_group_only_carve_out(
    client, db_session, test_tenant, environment_request_lifecycle
):
    """The carve-out is Admin-only — a non-Admin is still refused while the
    request is non-draft, even for operations_group_id alone.

    I2 note: the actor here is deliberately the REQUEST'S OWN REQUESTER, not
    an unrelated third party. Before I2 reordered update_request's
    authorization-before-business-rule check, this test used a stranger who
    wasn't the requester either — meaning it passed for the wrong reason:
    ANY unauthorized caller now correctly gets 403 before this business rule
    is even reached (see test_i2_a_stranger_patching_a_submitted_request_
    gets_403_not_409), which would make a stranger's PATCH here 403 too. The
    actor must pass the "requester or admin" gate to actually reach — and
    be refused by — the carve-out's Admin-only condition."""
    from app.core.security import get_password_hash
    from app.db.models.user import User as UserModel
    from tests.factories import ensure_environment_tier

    non_admin = UserModel(
        tenant_id=test_tenant.id, username="c1-non-admin",
        email="c1-non-admin@example.com",
        password_hash=get_password_hash("password123"),
        role="Test Manager", is_active=True,
    )
    db_session.add(non_admin)
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="C1-NonAdmin")
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={
        "username": "c1-non-admin", "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "no team yet",
              "proposed_name": "Non-Admin Owned", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=headers,
    )).json()["id"]
    submitted = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=headers,
    )
    assert submitted.status_code == 200, submitted.text

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=headers,
    )
    assert refused.status_code == 409, refused.text


@pytest.mark.asyncio
async def test_group_plus_another_field_on_non_draft_is_still_409(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """The carve-out is exact: operations_group_id ALONE, nothing else."""
    group = await ensure_user_group(db_session, test_tenant.id, name="C1-Plus-Field")
    await db_session.commit()
    rid = await _groupless_new_env_request(
        client, auth_headers, db_session, test_tenant, to_status="submitted"
    )

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id, "justification": "also this"},
        headers=auth_headers,
    )
    assert refused.status_code == 409, refused.text


@pytest.mark.asyncio
async def test_an_access_request_is_still_409_on_a_non_draft_group_only_patch(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """The carve-out is scoped to kind == 'new_environment' — an access
    request's operations group comes from its target environment, not the
    request itself, and must not become independently editable post-draft."""
    env = await _env(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="C1-Access-Kind")
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]
    submitted = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    assert submitted.status_code == 200, submitted.text

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=auth_headers,
    )
    assert refused.status_code == 409, refused.text


# ---------------------------------------------------------------------------
# Final review pass: C1(a), I1 (write side), I2, I3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c1a_create_request_uses_the_templates_declared_initial_state(
    client, auth_headers, db_session, test_tenant,
):
    """C1(a): before the fix create_request always wrote the literal
    'draft', regardless of what the template declares. Reproduced live as a
    201 with status:'draft' for a template whose initial state is actually
    named 'new' — a state the template has no transitions out of, so every
    subsequent transition 400s."""
    definition = {
        "states": [
            {"key": "new", "label": "New", "is_initial": True, "is_terminal": False},
            {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            {"key": "fulfilled", "label": "Fulfilled", "is_initial": False, "is_terminal": True},
            {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "new", "to_state": "submitted", "label": "Submit",
             "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {},
    }
    created_tpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Renamed Initial", "entity_type": "environment_request",
              "definition": definition},
    )
    assert created_tpl.status_code == 201, created_tpl.text

    env = await _env(db_session, test_tenant.id)
    created = await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "new"


@pytest.mark.asyncio
async def test_i1_patch_cannot_contaminate_the_other_modes_field(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """I1 (write side): a new_environment draft PATCHed with an unrelated
    environment_id must not have it stick — update_request now nulls the
    off-mode field on every save, the same way create_request never sets it
    in the first place. Reproduced live as a fulfilled request whose Welcome
    Pack described a completely different environment's access URL and
    support contact."""
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    other_env = await _env(db_session, test_tenant.id, group=False)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "j",
              "proposed_name": "I1 Env", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]

    patched = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"environment_id": other_env.id, "justification": "still fine"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["environment_id"] is None
    assert patched.json()["justification"] == "still fine"
    assert patched.json()["proposed_name"] == "I1 Env"


@pytest.mark.asyncio
async def test_i2_a_stranger_patching_a_submitted_request_gets_403_not_409(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """I2: authorization must run before the draft-only business rule — Task
    5's fix for transition() never got applied to update_request. Before the
    fix, a non-requester non-admin PATCHing a submitted request got the
    workflow 409 ('can only be edited while draft') instead of a 403 — which
    both confirms the request exists past draft and leaks why an edit would
    fail to someone with no right to touch it at all."""
    from app.core.security import get_password_hash
    from app.db.models.user import User as UserModel

    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]
    submitted = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    assert submitted.status_code == 200, submitted.text

    stranger = UserModel(
        tenant_id=test_tenant.id, username="i2-stranger",
        email="i2-stranger@example.com",
        password_hash=get_password_hash("password123"),
        role="Developer", is_active=True,
    )
    db_session.add(stranger)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", json={
        "username": "i2-stranger", "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert login.status_code == 200, login.text
    stranger_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"justification": "trying to edit someone else's request"},
        headers=stranger_headers,
    )
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_i3_patch_with_an_explicit_null_justification_is_422_not_500(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """I3: min_length doesn't fire on an explicit None (only on a too-short
    string), and the column is NOT NULL — an unguarded setattr flushed
    straight into an IntegrityError and an unhandled 500."""
    env = await _env(db_session, test_tenant.id)
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "first"},
        headers=auth_headers,
    )).json()["id"]

    refused = await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"justification": None},
        headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text
    assert "justification" in refused.text
