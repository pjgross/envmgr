"""Integration tests for admin and tenant-admin endpoints, and login guard."""
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Part D — Login guard: disabled tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_tenant_cannot_login(client: AsyncClient, db_session):
    """A user belonging to a disabled tenant receives 403 on login."""
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash

    # Create a disabled tenant and a user in it
    disabled_tenant = Tenant(name="Disabled Org", slug="disabled-org", is_active=False)
    db_session.add(disabled_tenant)
    await db_session.commit()
    await db_session.refresh(disabled_tenant)

    user = User(
        tenant_id=disabled_tenant.id,
        username="disableduser",
        email="disableduser@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/api/v1/auth/login", json={
        "username": "disableduser",
        "password": "password123",
        "tenant_slug": "disabled-org",
    })
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Part E — Non-master-admin blocked from master admin endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_master_admin_cannot_access_admin_endpoints(
    client: AsyncClient, auth_headers
):
    """A regular (non-master-admin) user gets 403 on GET /api/v1/admin/tenants."""
    response = await client.get("/api/v1/admin/tenants", headers=auth_headers)
    assert response.status_code == 403
    assert "master admin" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Master admin fixtures and happy-path tests
# ---------------------------------------------------------------------------

import pytest_asyncio


@pytest_asyncio.fixture(scope="function")
async def master_admin_user(db_session, test_tenant):
    """A master-admin user belonging to test_tenant."""
    from app.db.models.user import User
    from app.core.security import get_password_hash

    user = User(
        tenant_id=test_tenant.id,
        username="masteradmin",
        email="masteradmin@test.com",
        password_hash=get_password_hash("masterpass1"),
        role="Admin",
        is_active=True,
        is_master_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def master_admin_headers(client, test_tenant, master_admin_user) -> dict:
    """Bearer token headers for master_admin_user."""
    response = await client.post("/api/v1/auth/login", json={
        "username": master_admin_user.username,
        "password": "masterpass1",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_master_admin_can_list_tenants(
    client: AsyncClient, master_admin_headers, test_tenant
):
    """Master admin can fetch tenant list."""
    response = await client.get("/api/v1/admin/tenants", headers=master_admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    slugs = [t["slug"] for t in data]
    assert test_tenant.slug in slugs


@pytest.mark.asyncio
async def test_master_admin_can_create_tenant(
    client: AsyncClient, master_admin_headers
):
    """Master admin can create a new tenant."""
    response = await client.post("/api/v1/admin/tenants", headers=master_admin_headers, json={
        "name": "New Tenant",
        "slug": "new-tenant",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "new-tenant"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_master_admin_can_disable_tenant(
    client: AsyncClient, master_admin_headers, test_tenant
):
    """Master admin can disable a tenant."""
    response = await client.post(
        f"/api/v1/admin/tenants/{test_tenant.id}/disable",
        headers=master_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_master_admin_can_list_tenant_users(
    client: AsyncClient, master_admin_headers, test_tenant, test_user
):
    """Master admin can list users for a tenant."""
    response = await client.get(
        f"/api/v1/admin/tenants/{test_tenant.id}/users",
        headers=master_admin_headers,
    )
    assert response.status_code == 200
    usernames = [u["username"] for u in response.json()]
    assert test_user.username in usernames


@pytest.mark.asyncio
async def test_master_admin_sign_in_as_tenant(
    client: AsyncClient, master_admin_headers, test_tenant
):
    """Master admin can get an impersonation token for a tenant."""
    response = await client.post(
        f"/api/v1/admin/tenants/{test_tenant.id}/sign-in-as",
        headers=master_admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["target_tenant"]["id"] == test_tenant.id


# ---------------------------------------------------------------------------
# Tenant admin happy-path tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def tenant_admin_headers(client, test_tenant, test_user) -> dict:
    """Bearer token headers for the test_user (role=Admin in test_tenant)."""
    response = await client.post("/api/v1/auth/login", json={
        "username": test_user.username,
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_tenant_admin_can_get_settings(
    client: AsyncClient, tenant_admin_headers, test_tenant
):
    """Tenant admin can fetch their own tenant settings."""
    response = await client.get("/api/v1/tenant/settings", headers=tenant_admin_headers)
    assert response.status_code == 200
    assert response.json()["id"] == test_tenant.id


@pytest.mark.asyncio
async def test_tenant_admin_can_list_users(
    client: AsyncClient, tenant_admin_headers, test_user
):
    """Tenant admin can list users in their tenant."""
    response = await client.get("/api/v1/tenant/users", headers=tenant_admin_headers)
    assert response.status_code == 200
    usernames = [u["username"] for u in response.json()]
    assert test_user.username in usernames


@pytest.mark.asyncio
async def test_tenant_admin_can_create_user(
    client: AsyncClient, tenant_admin_headers
):
    """Tenant admin can create a new user in their tenant."""
    response = await client.post("/api/v1/tenant/users", headers=tenant_admin_headers, json={
        "username": "newmember",
        "email": "newmember@test.com",
        "password": "password123",
        "role": "Developer",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "newmember"
    assert data["role"] == "Developer"


@pytest.mark.asyncio
async def test_tenant_admin_can_deactivate_user(
    client: AsyncClient, tenant_admin_headers, db_session, test_tenant
):
    """Tenant admin can deactivate a user."""
    from app.db.models.user import User
    from app.core.security import get_password_hash

    target = User(
        tenant_id=test_tenant.id,
        username="todeactivate",
        email="todeactivate@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    response = await client.post(
        f"/api/v1/tenant/users/{target.id}/deactivate",
        headers=tenant_admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_viewer_cannot_access_tenant_admin_endpoints(
    client: AsyncClient, db_session, test_tenant
):
    """A Viewer-role user cannot access tenant admin endpoints."""
    from app.db.models.user import User
    from app.core.security import get_password_hash, create_access_token

    viewer = User(
        tenant_id=test_tenant.id,
        username="viewer",
        email="viewer@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(viewer)
    await db_session.commit()
    await db_session.refresh(viewer)

    token = create_access_token(data={"sub": str(viewer.id), "tenant_id": test_tenant.id})
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/v1/tenant/users", headers=headers)
    assert response.status_code == 403
