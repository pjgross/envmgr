"""Integration tests for Environment and EnvironmentSystem endpoints."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.db.models.environment import Environment, EnvironmentStatus
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
# Helper: create a system for use in environment-system tests
# ---------------------------------------------------------------------------


async def _create_system(client, auth_headers, name="TestSystem"):
    resp = await client.post("/api/v1/systems/", headers=auth_headers, json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Environment tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_environment(client: AsyncClient, auth_headers):
    """POST /environments creates an environment and returns 201 with correct fields."""
    response = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "Staging", "environment_type": "staging"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Staging"
    assert data["environment_type"] == "staging"
    assert data["status"] == "active"
    assert "id" in data
    assert "tenant_id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_environment_duplicate_name(client: AsyncClient, auth_headers):
    """POST /environments with duplicate name returns 409."""
    payload = {"name": "DuplicateEnv", "environment_type": "test"}
    await client.post("/api/v1/environments/", headers=auth_headers, json=payload)
    response = await client.post("/api/v1/environments/", headers=auth_headers, json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_environments(client: AsyncClient, auth_headers):
    """GET /environments returns all non-deleted environments for the tenant."""
    await client.post("/api/v1/environments/", headers=auth_headers,
                      json={"name": "EnvAlpha", "environment_type": "dev"})
    await client.post("/api/v1/environments/", headers=auth_headers,
                      json={"name": "EnvBeta", "environment_type": "qa"})

    response = await client.get("/api/v1/environments/", headers=auth_headers)
    assert response.status_code == 200
    names = [e["name"] for e in response.json()]
    assert "EnvAlpha" in names
    assert "EnvBeta" in names


@pytest.mark.asyncio
async def test_list_environments_status_filter(client: AsyncClient, auth_headers):
    """GET /environments?status=inactive filters by status correctly."""
    await client.post("/api/v1/environments/", headers=auth_headers,
                      json={"name": "ActiveEnv", "environment_type": "test", "status": "active"})
    await client.post("/api/v1/environments/", headers=auth_headers,
                      json={"name": "InactiveEnv", "environment_type": "test", "status": "inactive"})

    response = await client.get("/api/v1/environments/?status=inactive", headers=auth_headers)
    assert response.status_code == 200
    names = [e["name"] for e in response.json()]
    assert "InactiveEnv" in names
    assert "ActiveEnv" not in names


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, auth_headers, other_auth_headers):
    """Environment created by tenant A is not visible to tenant B."""
    create_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "TenantAEnv", "environment_type": "staging"},
    )
    assert create_resp.status_code == 201
    env_id = create_resp.json()["id"]

    # Tenant B should get 404 for this environment
    get_resp = await client.get(f"/api/v1/environments/{env_id}", headers=other_auth_headers)
    assert get_resp.status_code == 404

    # Tenant B's list should not include TenantAEnv
    list_resp = await client.get("/api/v1/environments/", headers=other_auth_headers)
    names = [e["name"] for e in list_resp.json()]
    assert "TenantAEnv" not in names


@pytest.mark.asyncio
async def test_get_environment(client: AsyncClient, auth_headers):
    """GET /environments/{id} returns the correct environment."""
    create_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "GetMeEnv", "environment_type": "uat", "description": "UAT env"},
    )
    env_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/environments/{env_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == env_id
    assert data["name"] == "GetMeEnv"
    assert data["description"] == "UAT env"
    assert data["environment_type"] == "uat"


@pytest.mark.asyncio
async def test_update_environment(client: AsyncClient, auth_headers):
    """PATCH /environments/{id} updates specified fields."""
    create_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "OriginalEnv", "environment_type": "dev"},
    )
    env_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/v1/environments/{env_id}",
        headers=auth_headers,
        json={"name": "UpdatedEnv", "status": "maintenance"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "UpdatedEnv"
    assert data["status"] == "maintenance"
    # environment_type should be unchanged
    assert data["environment_type"] == "dev"


@pytest.mark.asyncio
async def test_delete_environment_soft(client: AsyncClient, auth_headers, db_session):
    """DELETE /environments/{id} soft-deletes; environment no longer appears in list."""
    create_resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "ToDeleteEnv", "environment_type": "dev"},
    )
    env_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/environments/{env_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    # Should return 404 now
    get_resp = await client.get(f"/api/v1/environments/{env_id}", headers=auth_headers)
    assert get_resp.status_code == 404

    # Should not appear in list
    list_resp = await client.get("/api/v1/environments/", headers=auth_headers)
    ids = [e["id"] for e in list_resp.json()]
    assert env_id not in ids

    # Verify deleted_at is set in DB
    from sqlalchemy import select
    result = await db_session.execute(
        select(Environment).where(Environment.id == env_id)
    )
    env = result.scalar_one_or_none()
    assert env is not None
    assert env.deleted_at is not None


# ---------------------------------------------------------------------------
# EnvironmentSystem tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_system_to_environment(client: AsyncClient, auth_headers):
    """POST /{env_id}/systems adds a system and returns 201 with nested system data."""
    sys_id = await _create_system(client, auth_headers, "SysForEnv")
    env_resp = await client.post("/api/v1/environments/", headers=auth_headers,
                                 json={"name": "EnvWithSys", "environment_type": "test"})
    env_id = env_resp.json()["id"]

    response = await client.post(
        f"/api/v1/environments/{env_id}/systems",
        headers=auth_headers,
        json={"system_id": sys_id, "status": "active"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["environment_id"] == env_id
    assert data["system_id"] == sys_id
    assert data["system"]["id"] == sys_id
    assert data["system"]["name"] == "SysForEnv"


@pytest.mark.asyncio
async def test_add_system_duplicate(client: AsyncClient, auth_headers):
    """Adding the same system to an environment twice returns 409."""
    sys_id = await _create_system(client, auth_headers, "DupSys")
    env_resp = await client.post("/api/v1/environments/", headers=auth_headers,
                                 json={"name": "DupEnv", "environment_type": "test"})
    env_id = env_resp.json()["id"]

    await client.post(f"/api/v1/environments/{env_id}/systems",
                      headers=auth_headers, json={"system_id": sys_id})
    response = await client.post(f"/api/v1/environments/{env_id}/systems",
                                 headers=auth_headers, json={"system_id": sys_id})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_update_system_in_environment(client: AsyncClient, auth_headers):
    """PATCH /{env_id}/systems/{sys_id} returns 200 with the current system row."""
    sys_id = await _create_system(client, auth_headers, "PatchSys")
    env_resp = await client.post("/api/v1/environments/", headers=auth_headers,
                                 json={"name": "PatchEnv", "environment_type": "dev"})
    env_id = env_resp.json()["id"]

    await client.post(f"/api/v1/environments/{env_id}/systems",
                      headers=auth_headers, json={"system_id": sys_id})

    response = await client.patch(
        f"/api/v1/environments/{env_id}/systems/{sys_id}",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["environment_id"] == env_id
    assert data["system_id"] == sys_id


@pytest.mark.asyncio
async def test_remove_system_from_environment(client: AsyncClient, auth_headers):
    """DELETE /{env_id}/systems/{sys_id} removes the link; not in list anymore."""
    sys_id = await _create_system(client, auth_headers, "RemoveSys")
    env_resp = await client.post("/api/v1/environments/", headers=auth_headers,
                                 json={"name": "RemoveEnv", "environment_type": "qa"})
    env_id = env_resp.json()["id"]

    await client.post(f"/api/v1/environments/{env_id}/systems",
                      headers=auth_headers, json={"system_id": sys_id})

    del_resp = await client.delete(
        f"/api/v1/environments/{env_id}/systems/{sys_id}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204

    # Should not be in the list anymore
    list_resp = await client.get(f"/api/v1/environments/{env_id}/systems", headers=auth_headers)
    assert list_resp.status_code == 200
    sys_ids = [s["system_id"] for s in list_resp.json()["systems"]]
    assert sys_id not in sys_ids


# ---------------------------------------------------------------------------
# Server-side sorting + search (sub-project C1 task 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_environments_default_order_unchanged(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """No sort_by: order must stay `name, id` — today's ordering, byte for byte.

    Insertion order (Charlie, Alpha, Bravo) deliberately disagrees with name
    order, so a response that happened to preserve insertion/id order would not
    accidentally satisfy this assertion. This is what makes C1 safe to merge
    before the frontend half moves filtering server-side.
    """
    charlie = Environment(tenant_id=test_tenant.id, name="Charlie", environment_type="SIT")
    alpha = Environment(tenant_id=test_tenant.id, name="Alpha", environment_type="SIT")
    bravo = Environment(tenant_id=test_tenant.id, name="Bravo", environment_type="SIT")
    db_session.add_all([charlie, alpha, bravo])
    await db_session.commit()

    response = await client.get("/api/v1/environments/", headers=auth_headers)
    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == [alpha.id, bravo.id, charlie.id]


@pytest.mark.asyncio
async def test_list_environments_sort_by_name_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    charlie = Environment(tenant_id=test_tenant.id, name="Charlie", environment_type="SIT")
    alpha = Environment(tenant_id=test_tenant.id, name="Alpha", environment_type="SIT")
    bravo = Environment(tenant_id=test_tenant.id, name="Bravo", environment_type="SIT")
    db_session.add_all([charlie, alpha, bravo])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/environments/?sort_by=name&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [e["id"] for e in asc.json()] == [alpha.id, bravo.id, charlie.id]

    desc = await client.get(
        "/api/v1/environments/?sort_by=name&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [e["id"] for e in desc.json()] == [charlie.id, bravo.id, alpha.id]


@pytest.mark.asyncio
async def test_list_environments_sort_by_environment_type_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """Names/ids are already in ascending order here, so only environment_type
    sorting — not the name tiebreaker or insertion order — could produce these
    sequences."""
    e1 = Environment(tenant_id=test_tenant.id, name="E1", environment_type="zebra")
    e2 = Environment(tenant_id=test_tenant.id, name="E2", environment_type="apple")
    e3 = Environment(tenant_id=test_tenant.id, name="E3", environment_type="middle")
    db_session.add_all([e1, e2, e3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/environments/?sort_by=environment_type&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [e["id"] for e in asc.json()] == [e2.id, e3.id, e1.id]

    desc = await client.get(
        "/api/v1/environments/?sort_by=environment_type&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [e["id"] for e in desc.json()] == [e1.id, e3.id, e2.id]


@pytest.mark.asyncio
async def test_list_environments_sort_by_status_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    s1 = Environment(
        tenant_id=test_tenant.id, name="S1", environment_type="SIT",
        status=EnvironmentStatus.MAINTENANCE,
    )
    s2 = Environment(
        tenant_id=test_tenant.id, name="S2", environment_type="SIT",
        status=EnvironmentStatus.ACTIVE,
    )
    s3 = Environment(
        tenant_id=test_tenant.id, name="S3", environment_type="SIT",
        status=EnvironmentStatus.DECOMMISSIONED,
    )
    db_session.add_all([s1, s2, s3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/environments/?sort_by=status&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [e["id"] for e in asc.json()] == [s2.id, s3.id, s1.id]

    desc = await client.get(
        "/api/v1/environments/?sort_by=status&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [e["id"] for e in desc.json()] == [s1.id, s3.id, s2.id]


@pytest.mark.asyncio
async def test_list_environments_sort_by_created_at_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c1 = Environment(
        tenant_id=test_tenant.id, name="C1", environment_type="SIT",
        created_at=base + timedelta(days=2),
    )
    c2 = Environment(
        tenant_id=test_tenant.id, name="C2", environment_type="SIT", created_at=base,
    )
    c3 = Environment(
        tenant_id=test_tenant.id, name="C3", environment_type="SIT",
        created_at=base + timedelta(days=1),
    )
    db_session.add_all([c1, c2, c3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/environments/?sort_by=created_at&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [e["id"] for e in asc.json()] == [c2.id, c3.id, c1.id]

    desc = await client.get(
        "/api/v1/environments/?sort_by=created_at&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [e["id"] for e in desc.json()] == [c1.id, c3.id, c2.id]


@pytest.mark.asyncio
async def test_list_environments_sort_by_unknown_field_is_422(
    client: AsyncClient, auth_headers
):
    """Through the real endpoint, not just Task 1's probe app."""
    response = await client.get(
        "/api/v1/environments/?sort_by=nonexistent", headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_environments_search_matches_case_insensitive_contains(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """search must agree with the browser's
    `name.toLowerCase().includes(q.toLowerCase())` — matches regardless of case,
    substrings match, and a name with no match at all is excluded."""
    prod = Environment(tenant_id=test_tenant.id, name="Production", environment_type="SIT")
    prod_backup = Environment(
        tenant_id=test_tenant.id, name="production-backup", environment_type="SIT"
    )
    staging = Environment(tenant_id=test_tenant.id, name="Staging", environment_type="SIT")
    db_session.add_all([prod, prod_backup, staging])
    await db_session.commit()

    response = await client.get("/api/v1/environments/?search=PROD", headers=auth_headers)
    assert response.status_code == 200
    ids = {e["id"] for e in response.json()}
    assert ids == {prod.id, prod_backup.id}
