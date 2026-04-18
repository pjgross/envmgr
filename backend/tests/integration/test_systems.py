"""Integration tests for System and SubSystem endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.db.models.system import System, SubSystem
from app.core.security import get_password_hash


# ---------------------------------------------------------------------------
# Extra fixtures for a second tenant (tenant isolation tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def other_tenant(db_session) -> Tenant:
    """A second tenant for isolation tests."""
    tenant = Tenant(name="Other Org", slug="other-org")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture(scope="function")
async def other_user(db_session, other_tenant) -> User:
    """An admin user belonging to other_tenant."""
    user = User(
        tenant_id=other_tenant.id,
        username="otheradmin",
        email="admin@other.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def other_auth_headers(client, other_tenant, other_user) -> dict:
    """Bearer token for other_user."""
    response = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_system(client: AsyncClient, auth_headers):
    """POST /systems creates a system and returns 201 with correct fields."""
    response = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "Payments", "description": "Payment processing system"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Payments"
    assert data["description"] == "Payment processing system"
    assert "id" in data
    assert "tenant_id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_system_duplicate_name(client: AsyncClient, auth_headers):
    """POST /systems with duplicate name returns 409."""
    payload = {"name": "DuplicateSystem"}
    await client.post("/api/v1/systems/", headers=auth_headers, json=payload)
    response = await client.post("/api/v1/systems/", headers=auth_headers, json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_systems(client: AsyncClient, auth_headers):
    """GET /systems returns only systems belonging to the current tenant."""
    # Create two systems
    await client.post("/api/v1/systems/", headers=auth_headers, json={"name": "Alpha"})
    await client.post("/api/v1/systems/", headers=auth_headers, json={"name": "Beta"})

    response = await client.get("/api/v1/systems/", headers=auth_headers)
    assert response.status_code == 200
    names = [s["name"] for s in response.json()]
    assert "Alpha" in names
    assert "Beta" in names


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, auth_headers, other_auth_headers):
    """System created by tenant A is not visible to tenant B."""
    create_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "TenantASystem"},
    )
    assert create_resp.status_code == 201
    system_id = create_resp.json()["id"]

    # Tenant B should get 404 for this system
    get_resp = await client.get(f"/api/v1/systems/{system_id}", headers=other_auth_headers)
    assert get_resp.status_code == 404

    # Tenant B's list should not include TenantASystem
    list_resp = await client.get("/api/v1/systems/", headers=other_auth_headers)
    names = [s["name"] for s in list_resp.json()]
    assert "TenantASystem" not in names


@pytest.mark.asyncio
async def test_get_system(client: AsyncClient, auth_headers):
    """GET /systems/{id} returns the correct system."""
    create_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "GetMe", "github_repository_url": "https://github.com/example/repo"},
    )
    system_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/systems/{system_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == system_id
    assert data["name"] == "GetMe"
    assert data["github_repository_url"] == "https://github.com/example/repo"


@pytest.mark.asyncio
async def test_update_system(client: AsyncClient, auth_headers):
    """PATCH /systems/{id} updates specified fields."""
    create_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "OriginalName"},
    )
    system_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/v1/systems/{system_id}",
        headers=auth_headers,
        json={"name": "UpdatedName", "description": "Now with description"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "UpdatedName"
    assert data["description"] == "Now with description"


@pytest.mark.asyncio
async def test_delete_system_soft(client: AsyncClient, auth_headers):
    """DELETE /systems/{id} soft-deletes the system; it no longer appears in list."""
    create_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "ToDelete"},
    )
    system_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/systems/{system_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Should return 404 now
    get_resp = await client.get(f"/api/v1/systems/{system_id}", headers=auth_headers)
    assert get_resp.status_code == 404

    # Should not appear in list
    list_resp = await client.get("/api/v1/systems/", headers=auth_headers)
    ids = [s["id"] for s in list_resp.json()]
    assert system_id not in ids


@pytest.mark.asyncio
async def test_delete_system_cascades_subsystems(client: AsyncClient, auth_headers, db_session):
    """Deleting a system soft-deletes all its subsystems."""
    create_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "ParentSystem"},
    )
    system_id = create_resp.json()["id"]

    # Add a subsystem
    sub_resp = await client.post(
        f"/api/v1/systems/{system_id}/subsystems",
        headers=auth_headers,
        json={"name": "ChildSubSystem"},
    )
    assert sub_resp.status_code == 201
    sub_id = sub_resp.json()["id"]

    # Delete parent
    await client.delete(f"/api/v1/systems/{system_id}", headers=auth_headers)

    # Subsystem should be gone from the list (404 on parent → can't list, check DB directly)
    from sqlalchemy import select
    result = await db_session.execute(
        select(SubSystem).where(SubSystem.id == sub_id)
    )
    subsystem = result.scalar_one_or_none()
    assert subsystem is not None
    assert subsystem.deleted_at is not None


@pytest.mark.asyncio
async def test_subsystem_crud(client: AsyncClient, auth_headers):
    """Full CRUD for subsystems."""
    # Create parent system
    sys_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "SubTestSystem"},
    )
    system_id = sys_resp.json()["id"]

    # Create subsystem
    create_resp = await client.post(
        f"/api/v1/systems/{system_id}/subsystems",
        headers=auth_headers,
        json={"name": "SubA", "description": "First sub"},
    )
    assert create_resp.status_code == 201
    sub_data = create_resp.json()
    sub_id = sub_data["id"]
    assert sub_data["name"] == "SubA"
    assert sub_data["system_id"] == system_id

    # List
    list_resp = await client.get(f"/api/v1/systems/{system_id}/subsystems", headers=auth_headers)
    assert list_resp.status_code == 200
    names = [s["name"] for s in list_resp.json()]
    assert "SubA" in names

    # Get
    get_resp = await client.get(
        f"/api/v1/systems/{system_id}/subsystems/{sub_id}", headers=auth_headers
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == sub_id

    # Update
    update_resp = await client.patch(
        f"/api/v1/systems/{system_id}/subsystems/{sub_id}",
        headers=auth_headers,
        json={"name": "SubA-Updated"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "SubA-Updated"

    # Delete
    del_resp = await client.delete(
        f"/api/v1/systems/{system_id}/subsystems/{sub_id}", headers=auth_headers
    )
    assert del_resp.status_code == 204

    # Should be gone
    get_after = await client.get(
        f"/api/v1/systems/{system_id}/subsystems/{sub_id}", headers=auth_headers
    )
    assert get_after.status_code == 404


@pytest.mark.asyncio
async def test_get_nonexistent_system(client: AsyncClient, auth_headers):
    """GET /systems/{id} for a non-existent ID returns 404."""
    response = await client.get("/api/v1/systems/999999", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_subsystem_duplicate_name(client: AsyncClient, auth_headers):
    """POST /systems/{id}/subsystems with duplicate name returns 409."""
    # Create parent system
    sys_resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "DuplicateSubSystem"},
    )
    assert sys_resp.status_code == 201
    system_id = sys_resp.json()["id"]

    # Create a subsystem
    await client.post(
        f"/api/v1/systems/{system_id}/subsystems",
        headers=auth_headers,
        json={"name": "DuplicateSub", "description": "first"},
    )
    # Try to create another with the same name
    response = await client.post(
        f"/api/v1/systems/{system_id}/subsystems",
        headers=auth_headers,
        json={"name": "DuplicateSub", "description": "second"},
    )
    assert response.status_code == 409
