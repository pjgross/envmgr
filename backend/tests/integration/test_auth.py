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
# POST /api/v1/auth/register
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient, test_tenant):
    response = await client.post("/api/v1/auth/register", json={
        "username": "newuser",
        "email": "newuser@test.com",
        "password": "password123",
        "tenant_id": test_tenant.id,
        "role": "Viewer",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "newuser"
    assert data["email"] == "newuser@test.com"
    assert data["role"] == "Viewer"
    assert data["tenant_id"] == test_tenant.id
    assert data["is_active"] is True
    assert "password" not in data
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_register_invalid_tenant(client: AsyncClient):
    response = await client.post("/api/v1/auth/register", json={
        "username": "ghost",
        "email": "ghost@test.com",
        "password": "password123",
        "tenant_id": 999999,
    })
    assert response.status_code == 404
    assert "Tenant not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient, test_tenant, test_user):
    response = await client.post("/api/v1/auth/register", json={
        "username": test_user.username,
        "email": "different@test.com",
        "password": "password123",
        "tenant_id": test_tenant.id,
    })
    assert response.status_code == 400
    assert "Username already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_tenant, test_user):
    response = await client.post("/api/v1/auth/register", json={
        "username": "differentname",
        "email": test_user.email,
        "password": "password123",
        "tenant_id": test_tenant.id,
    })
    assert response.status_code == 400
    assert "Email already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_default_role_is_viewer(client: AsyncClient, test_tenant):
    response = await client.post("/api/v1/auth/register", json={
        "username": "viewer",
        "email": "viewer@test.com",
        "password": "password123",
        "tenant_id": test_tenant.id,
    })
    assert response.status_code == 201
    assert response.json()["role"] == "Viewer"


@pytest.mark.asyncio
async def test_register_same_username_different_tenants(client: AsyncClient, db_session):
    """Same username is allowed in different tenants."""
    from app.db.models.user import Tenant
    tenant2 = Tenant(name="Second Org", slug="second-org")
    db_session.add(tenant2)
    await db_session.commit()
    await db_session.refresh(tenant2)

    r1 = await client.post("/api/v1/auth/register", json={
        "username": "shared", "email": "u@t1.com",
        "password": "password123", "tenant_id": tenant2.id,
    })
    # Create first tenant user inline
    from app.db.models.user import Tenant as TenantModel
    tenant1 = Tenant(name="First Org", slug="first-org")
    db_session.add(tenant1)
    await db_session.commit()
    await db_session.refresh(tenant1)

    r2 = await client.post("/api/v1/auth/register", json={
        "username": "shared", "email": "u@t2.com",
        "password": "password123", "tenant_id": tenant1.id,
    })
    assert r1.status_code == 201
    assert r2.status_code == 201


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
