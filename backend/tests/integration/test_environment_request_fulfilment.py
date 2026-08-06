"""Fulfilling a new-environment request creates the environment."""
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_request import EnvironmentRequest
from tests.factories import ensure_environment_tier, ensure_user_group


async def _approved_new_env_request(client, auth_headers, db_session, test_tenant):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf",
              "proposed_name": "Mortgage PERF", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]
    await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=auth_headers,
    )
    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=auth_headers,
    )
    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "approved"}, headers=auth_headers,
    )
    return rid, tier, group


@pytest.mark.asyncio
async def test_fulfilment_creates_an_inactive_environment(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """INACTIVE, not ACTIVE: the register must not claim an environment is
    available before anyone has built it."""
    rid, tier, group = await _approved_new_env_request(
        client, auth_headers, db_session, test_tenant
    )

    done = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "fulfilled"}, headers=auth_headers,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "fulfilled"
    assert body["created_environment_id"] is not None

    env = (await db_session.execute(
        select(Environment).where(Environment.id == body["created_environment_id"])
    )).scalar_one()
    assert env.name == "Mortgage PERF"
    assert env.status == EnvironmentStatus.INACTIVE
    assert env.tier_id == tier.id
    assert env.operations_group_id == group.id
    # The requester becomes the owner — the governance field is populated by
    # construction and can never be null on a request-created environment.
    assert env.owner_user_id is not None
    # Nothing to hand over until it is built.
    assert env.access_url is None


@pytest.mark.asyncio
async def test_fulfilling_an_access_request_creates_nothing(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    from tests.factories import ensure_environment

    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()
    before = (await db_session.execute(select(Environment.id))).scalars().all()

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "j"},
        headers=auth_headers,
    )).json()["id"]
    for state in ("submitted", "approved", "fulfilled"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )
        assert r.status_code == 200, r.text

    after = (await db_session.execute(select(Environment.id))).scalars().all()
    assert set(after) == set(before)
    assert r.json()["created_environment_id"] is None


@pytest.mark.asyncio
async def test_fulfilment_without_an_operations_group_is_refused(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """The created environment's operating team is not optional."""
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "perf",
              "proposed_name": "No Team", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=auth_headers,
    )).json()["id"]
    for state in ("submitted", "approved"):
        await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=auth_headers,
        )

    refused = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "fulfilled"}, headers=auth_headers,
    )
    assert refused.status_code == 409, refused.text
    assert "operations" in refused.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_failed_creation_rolls_back_the_transition(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """All three writes land together or none do.

    Deviates from the brief's suggested trigger (reusing an existing
    environment's name to trip `uq_environment_tenant_name`). That guard is a
    raw `op.create_index(...)` in migration `nameuniqguard`, gated to
    `if dialect.name != "postgresql": return`, and is never declared on the
    `Environment` model's `__table_args__`. Both test legs (tests/conftest.py)
    build the schema with `Base.metadata.create_all`, not
    `alembic upgrade head` — so that index exists in real Postgres deployments
    but in neither test database, on either engine (confirmed: running this
    test with the original duplicate-name trigger produced 200, not 409).

    FK-orphaning was tried next and also doesn't work here: every FK column
    `_fulfil_new_environment` writes onto the new `Environment` row
    (`tier_id`, `owner_user_id`, `operations_group_id`) is *also* an FK on
    `environment_request` itself, pointing at the same row — so deleting the
    referenced tier/group out from under an approved request fails with its
    own FOREIGN KEY constraint violation (the request still references it),
    before fulfilment is ever attempted.

    So `_fulfil_new_environment` now carries its own proactive tenant+name
    collision check (see the service) — engine-independent, and a real
    product guard in its own right rather than only a test convenience, since
    the Postgres-only index it duplicates is otherwise invisible to every
    test run in this suite. This test drives that path: fulfil one request
    to create an environment, then attempt to fulfil a second request for the
    same name.

    The literal "raise after `db.flush()` assigned an id, confirm no orphan
    row" property is proven separately by mutation (see task report) — this
    integration test's job is the everyday case: no orphan row, and the
    transition doesn't stick, when fulfilment is refused.
    """
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id)
    await db_session.commit()

    async def _approved(name: str) -> int:
        rid = (await client.post(
            "/api/v1/environment-requests",
            json={"kind": "new_environment", "justification": "clash",
                  "proposed_name": name, "tier_id": tier.id,
                  "expires_at": "2027-01-01T00:00:00Z"},
            headers=auth_headers,
        )).json()["id"]
        await client.patch(
            f"/api/v1/environment-requests/{rid}",
            json={"operations_group_id": group.id}, headers=auth_headers,
        )
        for state in ("submitted", "approved"):
            r = await client.post(
                f"/api/v1/environment-requests/{rid}/transition",
                json={"to_state": state}, headers=auth_headers,
            )
            assert r.status_code == 200, r.text
        return rid

    first_rid = await _approved("Clash Name")
    first_done = await client.post(
        f"/api/v1/environment-requests/{first_rid}/transition",
        json={"to_state": "fulfilled"}, headers=auth_headers,
    )
    assert first_done.status_code == 200, first_done.text

    second_rid = await _approved("Clash Name")
    clash = await client.post(
        f"/api/v1/environment-requests/{second_rid}/transition",
        json={"to_state": "fulfilled"}, headers=auth_headers,
    )
    assert clash.status_code == 409, clash.text

    still = (await client.get(
        f"/api/v1/environment-requests/{second_rid}", headers=auth_headers
    )).json()
    assert still["status"] == "approved", "the transition must not have stuck"
    assert still["created_environment_id"] is None

    matching = (await db_session.execute(
        select(Environment).where(
            Environment.tenant_id == test_tenant.id,
            Environment.name == "Clash Name",
        )
    )).scalars().all()
    assert len(matching) == 1, (
        "the second (failed) fulfilment must not leave an orphan "
        "environment row — only the first request's environment survives"
    )


@pytest.mark.asyncio
async def test_fulfilling_a_request_raised_under_impersonation_by_an_outside_user_is_refused(
    client, db_session, test_tenant, environment_request_lifecycle
):
    """req.owner_user_id is set to req.requested_by, which is
    current_user.id at request-CREATE time — not active_tenant_id. Under
    master-admin impersonation those belong to different tenants: a master
    admin can raise (and later fulfil) a new_environment request while
    impersonating a tenant that is not their home tenant. Without a tenant
    check on the owner, fulfilment would create an Environment in
    test_tenant whose owner_user_id points at a user in a different tenant —
    the exact "current_user.id doesn't belong to active_tenant_id" class
    CLAUDE.md already records as having broken an owner check elsewhere in
    this repo.

    The master admin's role is 'Admin' so the role/group gates on every
    transition pass on their own merits — the only way this reaches 409 is
    the dedicated owner-tenant check in _fulfil_new_environment.
    """
    from app.core.security import create_access_token, get_password_hash
    from app.db.models.user import Tenant, User

    tier = await ensure_environment_tier(db_session, test_tenant.id)
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops-owner-imp")
    await db_session.commit()

    home = Tenant(name="System Org Owner Imp", slug="system-owner-imp")
    db_session.add(home)
    await db_session.flush()
    master = User(
        tenant_id=home.id, username="owner-masteradmin",
        email="owner-masteradmin@example.com",
        password_hash=get_password_hash("password123"), role="Admin",
        is_active=True, is_master_admin=True,
    )
    db_session.add(master)
    await db_session.commit()

    token = create_access_token({
        "sub": str(master.id),
        "tenant_id": home.id,
        "impersonating_tenant_id": test_tenant.id,
    })
    headers = {"Authorization": f"Bearer {token}"}

    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "new_environment", "justification": "owner-imp",
              "proposed_name": "Owner Imp Env", "tier_id": tier.id,
              "expires_at": "2027-01-01T00:00:00Z"},
        headers=headers,
    )).json()["id"]
    await client.patch(
        f"/api/v1/environment-requests/{rid}",
        json={"operations_group_id": group.id}, headers=headers,
    )
    for state in ("submitted", "approved"):
        r = await client.post(
            f"/api/v1/environment-requests/{rid}/transition",
            json={"to_state": state}, headers=headers,
        )
        assert r.status_code == 200, r.text

    refused = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "fulfilled"}, headers=headers,
    )
    assert refused.status_code == 409, refused.text

    still = (await client.get(
        f"/api/v1/environment-requests/{rid}", headers=headers
    )).json()
    assert still["status"] == "approved", "the transition must not have stuck"
    assert still["created_environment_id"] is None

    matching = (await db_session.execute(
        select(Environment).where(
            Environment.tenant_id == test_tenant.id,
            Environment.name == "Owner Imp Env",
        )
    )).scalars().all()
    assert matching == [], (
        "no environment must be created when the requester does not belong "
        "to the tenant the request is being fulfilled in"
    )


@pytest.mark.asyncio
async def test_fulfilling_is_refused_to_a_non_admin_outside_the_operating_team(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """Authorization must be checked BEFORE fulfilment executes.

    A reviewer swapped assert_may_transition and the fulfilment block in
    `transition()` and every other test in this suite stayed green — nothing
    guarded against an unauthorized caller triggering environment creation
    before the 403. This is the dedicated coverage: a non-Admin outside the
    environment's operating team must be refused, and — the part the swap
    would break — no Environment may exist afterwards.
    """
    from app.core.security import get_password_hash
    from app.db.models.user import User as UserModel

    rid, tier, group = await _approved_new_env_request(
        client, auth_headers, db_session, test_tenant
    )

    outsider = UserModel(
        tenant_id=test_tenant.id, username="tm-outsider-fulfil",
        email="tm-outsider-fulfil@example.com",
        password_hash=get_password_hash("password123"),
        role="Test Manager", is_active=True,
    )
    db_session.add(outsider)
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={
        "username": "tm-outsider-fulfil", "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert login.status_code == 200, login.text
    outsider_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    refused = await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "fulfilled"}, headers=outsider_headers,
    )
    assert refused.status_code == 403, refused.text

    still = (await client.get(
        f"/api/v1/environment-requests/{rid}", headers=auth_headers
    )).json()
    assert still["status"] == "approved", "the transition must not have stuck"
    assert still["created_environment_id"] is None

    matching = (await db_session.execute(
        select(Environment).where(
            Environment.tenant_id == test_tenant.id,
            Environment.name == "Mortgage PERF",
        )
    )).scalars().all()
    assert matching == [], (
        "no environment must be created by an unauthorized fulfil attempt"
    )
