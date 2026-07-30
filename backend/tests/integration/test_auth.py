"""Integration tests for /api/v1/auth endpoints and root health routes."""
import pytest
import pytest_asyncio
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Root / Health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_root_returns_app_info(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "EnvManager"
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


# ---------------------------------------------------------------------------
# Self-service registration (removed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_service_registration_is_not_exposed(client: AsyncClient, test_tenant):
    """An unauthenticated caller must not be able to create a user at all.

    The endpoint used to accept a caller-supplied tenant_id and role, so anyone
    who could reach the API could mint an Admin in any tenant. User creation
    belongs to POST /api/v1/tenant/users, which is admin-gated and forces the
    caller's own tenant.
    """
    response = await client.post("/api/v1/auth/register", json={
        "username": "intruder",
        "email": "intruder@test.com",
        "password": "password123",
        "tenant_id": test_tenant.id,
        "role": "Admin",
    })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_creating_a_user_requires_authentication(client: AsyncClient):
    response = await client.post("/api/v1/tenant/users", json={
        "username": "intruder",
        "email": "intruder@test.com",
        "password": "password123",
        "role": "Admin",
    })
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_tenant, test_user):
    response = await client.post("/api/v1/auth/login", json={
        "username": test_user.username,
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == test_user.username
    assert data["user"]["tenant_id"] == test_tenant.id


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_tenant, test_user):
    response = await client.post("/api/v1/auth/login", json={
        "username": test_user.username,
        "password": "wrongpassword",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient, test_tenant):
    response = await client.post("/api/v1/auth/login", json={
        "username": "nobody",
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_wrong_tenant_slug(client: AsyncClient, test_user):
    response = await client.post("/api/v1/auth/login", json={
        "username": test_user.username,
        "password": "password123",
        "tenant_slug": "no-such-tenant",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, test_tenant, db_session):
    from app.db.models.user import User
    from app.core.security import get_password_hash
    inactive = User(
        tenant_id=test_tenant.id,
        username="inactive",
        email="inactive@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=False,
    )
    db_session.add(inactive)
    await db_session.commit()

    response = await client.post("/api/v1/auth/login", json={
        "username": "inactive",
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_returns_current_user(client: AsyncClient, auth_headers, test_user):
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == test_user.username
    assert data["email"] == test_user.email
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_me_no_token_rejected(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    # 401, not 403: HTTPBearer returns Unauthorized for absent credentials.
    # (FastAPI < 0.112 returned 403 here, which was the wrong semantics.)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token_rejected(client: AsyncClient):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_malformed_header_rejected(client: AsyncClient):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "NotBearer token"})
    # As above — an unparseable scheme is unauthenticated, not forbidden.
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Refresh, logout and rate limiting
# ---------------------------------------------------------------------------


async def _login(client, tenant, user, password="password123"):
    return await client.post(
        "/api/v1/auth/login",
        json={
            "username": user.username,
            "password": password,
            "tenant_slug": tenant.slug,
        },
    )


@pytest.mark.asyncio
async def test_login_returns_a_refresh_token(client: AsyncClient, test_tenant, test_user):
    body = (await _login(client, test_tenant, test_user)).json()
    assert body["refresh_token"]
    assert body["expires_in"] > 0


@pytest.mark.asyncio
async def test_refresh_exchanges_for_a_new_access_token(
    client: AsyncClient, test_tenant, test_user
):
    login = (await _login(client, test_tenant, test_user)).json()

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert response.status_code == 200
    refreshed = response.json()
    assert refreshed["access_token"]
    assert refreshed["refresh_token"] != login["refresh_token"]


@pytest.mark.asyncio
async def test_refreshed_access_token_works_on_a_protected_route(
    client: AsyncClient, test_tenant, test_user
):
    login = (await _login(client, test_tenant, test_user)).json()
    refreshed = (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        )
    ).json()

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refreshed['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == test_user.username


@pytest.mark.asyncio
async def test_refresh_with_a_spent_token_is_rejected(
    client: AsyncClient, test_tenant, test_user
):
    login = (await _login(client, test_tenant, test_user)).json()
    await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_logout_prevents_further_refresh(client: AsyncClient, test_tenant, test_user):
    """The point of the whole exercise: logout must actually end the session."""
    login = (await _login(client, test_tenant, test_user)).json()

    logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": login["refresh_token"]},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert logout.status_code == 204

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_repeated_wrong_passwords_are_eventually_rate_limited(
    client: AsyncClient, test_tenant, test_user
):
    from app.services.auth_session_service import MAX_FAILED_LOGINS

    for _ in range(MAX_FAILED_LOGINS):
        assert (await _login(client, test_tenant, test_user, "wrong")).status_code == 401

    blocked = await _login(client, test_tenant, test_user, "wrong")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


@pytest.mark.asyncio
async def test_rate_limit_blocks_even_the_correct_password(
    client: AsyncClient, test_tenant, test_user
):
    """Otherwise the limit is trivially bypassed by the attacker who guesses right."""
    from app.services.auth_session_service import MAX_FAILED_LOGINS

    for _ in range(MAX_FAILED_LOGINS):
        await _login(client, test_tenant, test_user, "wrong")

    assert (await _login(client, test_tenant, test_user)).status_code == 429


@pytest.mark.asyncio
async def test_a_successful_login_resets_the_failure_count(
    client: AsyncClient, test_tenant, test_user
):
    from app.services.auth_session_service import MAX_FAILED_LOGINS

    for _ in range(MAX_FAILED_LOGINS - 1):
        await _login(client, test_tenant, test_user, "wrong")
    assert (await _login(client, test_tenant, test_user)).status_code == 200

    for _ in range(MAX_FAILED_LOGINS - 1):
        await _login(client, test_tenant, test_user, "wrong")
    assert (await _login(client, test_tenant, test_user)).status_code == 200


@pytest.mark.asyncio
async def test_password_reset_revokes_existing_sessions(
    client: AsyncClient, db_session, test_tenant, test_user
):
    """A reset is how an account gets recovered after compromise.

    If the attacker's existing session survives it, the reset achieved nothing.
    """
    from app.db.models.user import User
    from app.core.security import get_password_hash
    from app.services import auth_session_service

    login = (await _login(client, test_tenant, test_user)).json()

    master = User(
        tenant_id=test_tenant.id,
        username="master",
        email="master@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_master_admin=True,
    )
    db_session.add(master)
    await db_session.flush()
    master_token = (await auth_session_service.issue_session(db_session, master)).access_token

    reset = await client.post(
        f"/api/v1/admin/tenants/{test_tenant.id}/users/{test_user.id}/reset-password",
        json={"new_password": "a-brand-new-password"},
        headers={"Authorization": f"Bearer {master_token}"},
    )
    assert reset.status_code == 200

    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert refresh.status_code == 401


@pytest.mark.asyncio
async def test_impersonation_token_is_not_longer_lived_than_a_normal_session(
    client: AsyncClient, db_session, test_tenant
):
    """It carries more privilege than any other token; it must not last longer."""
    from datetime import datetime, timezone
    from app.db.models.user import User, Tenant
    from app.core.security import get_password_hash, decode_access_token
    from app.services import auth_session_service

    target = Tenant(name="Target Org", slug="target-org")
    db_session.add(target)
    await db_session.flush()

    master = User(
        tenant_id=test_tenant.id,
        username="master2",
        email="master2@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_master_admin=True,
    )
    db_session.add(master)
    await db_session.flush()
    master_token = (await auth_session_service.issue_session(db_session, master)).access_token

    response = await client.post(
        f"/api/v1/admin/tenants/{target.id}/sign-in-as",
        headers={"Authorization": f"Bearer {master_token}"},
    )
    assert response.status_code == 200

    claims = decode_access_token(response.json()["access_token"])
    lifetime = datetime.fromtimestamp(claims["exp"], timezone.utc) - datetime.now(timezone.utc)
    assert lifetime.total_seconds() <= auth_session_service.IMPERSONATION_TOKEN_MINUTES * 60 + 5
    assert auth_session_service.IMPERSONATION_TOKEN_MINUTES <= 60


@pytest.mark.asyncio
async def test_replay_revokes_the_family_durably(client: AsyncClient, test_tenant, test_user):
    """The revocation has to survive the 401 that reports it.

    get_db() rolls back on exception, so writing the revocation and then raising
    discards it — the service-level test cannot see this because it never goes
    through that dependency. Caught by exercising the running API.
    """
    login = (await _login(client, test_tenant, test_user)).json()
    rotated = (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
        )
    ).json()

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert replay.status_code == 401

    # The thief may hold the rotated token; it must be dead too.
    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert after.status_code == 401


# ---------------------------------------------------------------------------
# Transaction-boundary behaviour
#
# The shared `client` fixture overrides get_db with a bare yield, so writes made
# on the way to an error are never rolled back and anything that depends on
# get_db's real commit/rollback looks fine when it isn't. These tests use a client
# whose override mirrors production.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def realistic_client(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from httpx import ASGITransport
    from app.db.base import get_db
    from app.main import app

    Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_failed_attempts_are_counted_across_real_transactions(
    realistic_client: AsyncClient, db_engine
):
    """The limiter records an attempt and then raises 401 on the same request.

    Under get_db's rollback-on-exception that discards the row, so the counter
    stays at zero and the limit never engages — which is what the running
    container showed while every harness test passed.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.core.security import get_password_hash
    from app.db.models.user import Tenant, User
    from app.services.auth_session_service import MAX_FAILED_LOGINS

    Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as setup:
        tenant = Tenant(name="Rate Org", slug="rate-org")
        setup.add(tenant)
        await setup.flush()
        setup.add(
            User(
                tenant_id=tenant.id,
                username="ratelimited",
                email="rl@test.com",
                password_hash=get_password_hash("password123"),
                role="Admin",
            )
        )
        await setup.commit()

    async def attempt(password: str):
        return await realistic_client.post(
            "/api/v1/auth/login",
            json={
                "username": "ratelimited",
                "password": password,
                "tenant_slug": "rate-org",
            },
        )

    for _ in range(MAX_FAILED_LOGINS):
        assert (await attempt("wrong")).status_code == 401

    blocked = await attempt("password123")
    assert blocked.status_code == 429, "failed attempts were not persisted"
    assert blocked.headers.get("Retry-After")
