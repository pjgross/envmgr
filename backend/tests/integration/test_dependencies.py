"""Integration tests for SystemDependency and ComponentDependency endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.core.security import get_password_hash


# ---------------------------------------------------------------------------
# Extra fixtures for a second tenant (isolation tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def other_tenant(db_session) -> Tenant:
    tenant = Tenant(name="Other Org", slug="other-org-dep")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture(scope="function")
async def other_user(db_session, other_tenant) -> User:
    user = User(
        tenant_id=other_tenant.id,
        username="otheradmin_dep",
        email="admin_dep@other.com",
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
    response = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_system(client, auth_headers, name: str) -> int:
    resp = await client.post("/api/v1/systems/", headers=auth_headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_subsystem(client, auth_headers, system_id: int, name: str) -> int:
    resp = await client.post(
        f"/api/v1/systems/{system_id}/subsystems",
        headers=auth_headers,
        json={"name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# SystemDependency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_system_dependency(client: AsyncClient, auth_headers):
    """POST /systems/{id}/dependencies creates a dependency and returns 201."""
    from_id = await _create_system(client, auth_headers, "SysA")
    to_id = await _create_system(client, auth_headers, "SysB")

    resp = await client.post(
        f"/api/v1/systems/{from_id}/dependencies",
        headers=auth_headers,
        json={"to_system_id": to_id, "dependency_type": "api_call", "direction": "one_way"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["from_system_id"] == from_id
    assert data["to_system_id"] == to_id
    assert data["dependency_type"] == "api_call"
    assert data["direction"] == "one_way"
    assert data["source"] == "manual"
    assert data["to_system"]["id"] == to_id
    assert data["to_system"]["name"] == "SysB"
    assert data["is_incoming"] is False


@pytest.mark.asyncio
async def test_create_system_dependency_duplicate(client: AsyncClient, auth_headers):
    """Creating the same dependency twice returns 409."""
    from_id = await _create_system(client, auth_headers, "DupA")
    to_id = await _create_system(client, auth_headers, "DupB")

    payload = {"to_system_id": to_id, "dependency_type": "database"}
    await client.post(
        f"/api/v1/systems/{from_id}/dependencies", headers=auth_headers, json=payload
    )
    resp = await client.post(
        f"/api/v1/systems/{from_id}/dependencies", headers=auth_headers, json=payload
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_list_system_dependencies(client: AsyncClient, auth_headers):
    """GET /systems/{id}/dependencies returns all dependencies with nested to_system."""
    from_id = await _create_system(client, auth_headers, "ListFrom")
    to_id1 = await _create_system(client, auth_headers, "ListTo1")
    to_id2 = await _create_system(client, auth_headers, "ListTo2")

    await client.post(
        f"/api/v1/systems/{from_id}/dependencies",
        headers=auth_headers,
        json={"to_system_id": to_id1, "dependency_type": "api_call"},
    )
    await client.post(
        f"/api/v1/systems/{from_id}/dependencies",
        headers=auth_headers,
        json={"to_system_id": to_id2, "dependency_type": "message_queue"},
    )

    resp = await client.get(
        f"/api/v1/systems/{from_id}/dependencies", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 2
    to_names = {i["to_system"]["name"] for i in items}
    assert "ListTo1" in to_names
    assert "ListTo2" in to_names


@pytest.mark.asyncio
async def test_delete_system_dependency(client: AsyncClient, auth_headers):
    """DELETE /systems/{id}/dependencies/{dep_id} removes the dependency."""
    from_id = await _create_system(client, auth_headers, "DelFrom")
    to_id = await _create_system(client, auth_headers, "DelTo")

    create_resp = await client.post(
        f"/api/v1/systems/{from_id}/dependencies",
        headers=auth_headers,
        json={"to_system_id": to_id, "dependency_type": "event"},
    )
    dep_id = create_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/systems/{from_id}/dependencies/{dep_id}", headers=auth_headers
    )
    assert del_resp.status_code == 204, del_resp.text

    list_resp = await client.get(
        f"/api/v1/systems/{from_id}/dependencies", headers=auth_headers
    )
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_system_dep_tenant_isolation(
    client: AsyncClient, auth_headers, other_auth_headers
):
    """A system from another tenant cannot be used as to_system."""
    # Create a system in tenant A
    from_id = await _create_system(client, auth_headers, "TenantASys")

    # Create a system in tenant B
    other_to_id = await _create_system(client, other_auth_headers, "TenantBSys")

    # Tenant A tries to reference tenant B's system — should get 404
    resp = await client.post(
        f"/api/v1/systems/{from_id}/dependencies",
        headers=auth_headers,
        json={"to_system_id": other_to_id, "dependency_type": "api_call"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_list_includes_incoming_deps(client: AsyncClient, auth_headers):
    """Create A→B dependency; listing B's deps shows it with is_incoming=True."""
    sys_a = await _create_system(client, auth_headers, "IncomingA")
    sys_b = await _create_system(client, auth_headers, "IncomingB")

    # Create A → B
    await client.post(
        f"/api/v1/systems/{sys_a}/dependencies",
        headers=auth_headers,
        json={"to_system_id": sys_b, "dependency_type": "api_call"},
    )

    # List B's deps — should include the A→B dep as incoming
    resp = await client.get(
        f"/api/v1/systems/{sys_b}/dependencies", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    dep = items[0]
    assert dep["is_incoming"] is True
    assert dep["from_system_id"] == sys_a
    assert dep["to_system_id"] == sys_b
    # from_system should be populated
    assert dep["from_system"] is not None
    assert dep["from_system"]["id"] == sys_a


@pytest.mark.asyncio
async def test_delete_from_target_system(client: AsyncClient, auth_headers):
    """Create A→B, delete from B's perspective (using B's system_id endpoint)."""
    sys_a = await _create_system(client, auth_headers, "DeleteFromTargetA")
    sys_b = await _create_system(client, auth_headers, "DeleteFromTargetB")

    create_resp = await client.post(
        f"/api/v1/systems/{sys_a}/dependencies",
        headers=auth_headers,
        json={"to_system_id": sys_b, "dependency_type": "database"},
    )
    dep_id = create_resp.json()["id"]

    # Delete using B as the system_id context
    del_resp = await client.delete(
        f"/api/v1/systems/{sys_b}/dependencies/{dep_id}", headers=auth_headers
    )
    assert del_resp.status_code == 204, del_resp.text

    # Verify gone from A's perspective too
    list_resp = await client.get(
        f"/api/v1/systems/{sys_a}/dependencies", headers=auth_headers
    )
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_direction_two_way(client: AsyncClient, auth_headers):
    """Create a two_way dependency and verify direction is returned correctly."""
    sys_a = await _create_system(client, auth_headers, "TwoWayA")
    sys_b = await _create_system(client, auth_headers, "TwoWayB")

    create_resp = await client.post(
        f"/api/v1/systems/{sys_a}/dependencies",
        headers=auth_headers,
        json={"to_system_id": sys_b, "dependency_type": "message_queue", "direction": "two_way"},
    )
    assert create_resp.status_code == 201, create_resp.text
    data = create_resp.json()
    assert data["direction"] == "two_way"

    # Verify it appears in list
    list_resp = await client.get(
        f"/api/v1/systems/{sys_a}/dependencies", headers=auth_headers
    )
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["direction"] == "two_way"


# ---------------------------------------------------------------------------
# ComponentDependency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_component_dep_tenant_isolation(
    client: AsyncClient, auth_headers, other_auth_headers
):
    """A subsystem from another tenant cannot be used as to_subsystem."""
    # Create a system + subsystem in tenant A
    sys_a_id = await _create_system(client, auth_headers, "TenantASysComp")
    from_sub_id = await _create_subsystem(client, auth_headers, sys_a_id, "TenantASubComp")

    # Create a system + subsystem in tenant B
    sys_b_id = await _create_system(client, other_auth_headers, "TenantBSysComp")
    other_to_sub_id = await _create_subsystem(client, other_auth_headers, sys_b_id, "TenantBSubComp")

    # Tenant A tries to reference tenant B's subsystem — should get 404
    resp = await client.post(
        f"/api/v1/subsystems/{from_sub_id}/dependencies",
        headers=auth_headers,
        json={"to_subsystem_id": other_to_sub_id, "dependency_type": "api_call"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_component_dependency_crud(client: AsyncClient, auth_headers):
    """Create, list, and delete a component dependency."""
    sys_id = await _create_system(client, auth_headers, "CompSys")
    from_sub_id = await _create_subsystem(client, auth_headers, sys_id, "SubA")
    to_sub_id = await _create_subsystem(client, auth_headers, sys_id, "SubB")

    # Create
    create_resp = await client.post(
        f"/api/v1/subsystems/{from_sub_id}/dependencies",
        headers=auth_headers,
        json={
            "to_subsystem_id": to_sub_id,
            "dependency_type": "api_call",
            "direction": "one_way",
            "protocol": "HTTP",
            "port": 8080,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    data = create_resp.json()
    assert data["from_subsystem_id"] == from_sub_id
    assert data["to_subsystem_id"] == to_sub_id
    assert data["dependency_type"] == "api_call"
    assert data["direction"] == "one_way"
    assert data["protocol"] == "HTTP"
    assert data["port"] == 8080
    assert data["to_subsystem"]["id"] == to_sub_id
    assert data["to_subsystem"]["name"] == "SubB"
    assert data["is_incoming"] is False
    dep_id = data["id"]

    # List
    list_resp = await client.get(
        f"/api/v1/subsystems/{from_sub_id}/dependencies", headers=auth_headers
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Duplicate → 409
    dup_resp = await client.post(
        f"/api/v1/subsystems/{from_sub_id}/dependencies",
        headers=auth_headers,
        json={"to_subsystem_id": to_sub_id, "dependency_type": "database"},
    )
    assert dup_resp.status_code == 409, dup_resp.text

    # Delete
    del_resp = await client.delete(
        f"/api/v1/subsystems/{from_sub_id}/dependencies/{dep_id}", headers=auth_headers
    )
    assert del_resp.status_code == 204

    # Confirm deleted
    list_after = await client.get(
        f"/api/v1/subsystems/{from_sub_id}/dependencies", headers=auth_headers
    )
    assert list_after.json() == []


# ---------------------------------------------------------------------------
# Update (PATCH) tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_system_dependency(client: AsyncClient, auth_headers):
    """PATCH /systems/{id}/dependencies/{dep_id} updates type and direction."""
    from_id = await _create_system(client, auth_headers, "UpdateSysA")
    to_id = await _create_system(client, auth_headers, "UpdateSysB")

    create_resp = await client.post(
        f"/api/v1/systems/{from_id}/dependencies",
        headers=auth_headers,
        json={"to_system_id": to_id, "dependency_type": "api_call", "direction": "one_way"},
    )
    assert create_resp.status_code == 201, create_resp.text
    dep_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/systems/{from_id}/dependencies/{dep_id}",
        headers=auth_headers,
        json={"dependency_type": "message_queue", "direction": "two_way"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    data = patch_resp.json()
    assert data["dependency_type"] == "message_queue"
    assert data["direction"] == "two_way"
    assert data["from_system_id"] == from_id
    assert data["to_system_id"] == to_id
    assert data["is_incoming"] is False


@pytest.mark.asyncio
async def test_update_component_dependency(client: AsyncClient, auth_headers):
    """PATCH /subsystems/{id}/dependencies/{dep_id} updates type, direction, protocol, port."""
    sys_id = await _create_system(client, auth_headers, "UpdateCompSys")
    from_sub_id = await _create_subsystem(client, auth_headers, sys_id, "UpdateSubA")
    to_sub_id = await _create_subsystem(client, auth_headers, sys_id, "UpdateSubB")

    create_resp = await client.post(
        f"/api/v1/subsystems/{from_sub_id}/dependencies",
        headers=auth_headers,
        json={
            "to_subsystem_id": to_sub_id,
            "dependency_type": "api_call",
            "direction": "one_way",
            "protocol": "HTTP",
            "port": 8080,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    dep_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/subsystems/{from_sub_id}/dependencies/{dep_id}",
        headers=auth_headers,
        json={"dependency_type": "database", "direction": "two_way", "protocol": "gRPC", "port": 50051},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    data = patch_resp.json()
    assert data["dependency_type"] == "database"
    assert data["direction"] == "two_way"
    assert data["protocol"] == "gRPC"
    assert data["port"] == 50051
    assert data["from_subsystem_id"] == from_sub_id
    assert data["to_subsystem_id"] == to_sub_id
    assert data["is_incoming"] is False


@pytest.mark.asyncio
async def test_update_from_target_side(client: AsyncClient, auth_headers):
    """Create A→B dep, update from B's perspective (system_id=B); verify it works."""
    sys_a = await _create_system(client, auth_headers, "TargetUpdateA")
    sys_b = await _create_system(client, auth_headers, "TargetUpdateB")

    create_resp = await client.post(
        f"/api/v1/systems/{sys_a}/dependencies",
        headers=auth_headers,
        json={"to_system_id": sys_b, "dependency_type": "api_call", "direction": "one_way"},
    )
    assert create_resp.status_code == 201, create_resp.text
    dep_id = create_resp.json()["id"]

    # Update from B's perspective
    patch_resp = await client.patch(
        f"/api/v1/systems/{sys_b}/dependencies/{dep_id}",
        headers=auth_headers,
        json={"dependency_type": "event"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    data = patch_resp.json()
    assert data["dependency_type"] == "event"
    # From B's perspective this is incoming
    assert data["is_incoming"] is True
    assert data["from_system_id"] == sys_a
    assert data["to_system_id"] == sys_b
