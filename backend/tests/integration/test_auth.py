"""Integration tests for /api/v1/auth endpoints and root health routes."""
import pytest
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
    # HTTPBearer raises 403 when no credentials provided
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_me_invalid_token_rejected(client: AsyncClient):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_malformed_header_rejected(client: AsyncClient):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "NotBearer token"})
    assert response.status_code == 403
