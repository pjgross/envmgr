"""Integration tests for Environment and EnvironmentSystem endpoints."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.db.models.environment import Environment, EnvironmentStatus
from app.core.security import get_password_hash
from tests.factories import ensure_environment_tier, post_environment


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
    response = await post_environment(client, auth_headers, "Staging")
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Staging"
    assert data["tier_name"] == "SIT"
    assert data["status"] == "active"
    assert "id" in data
    assert "tenant_id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_environment_duplicate_name(client: AsyncClient, auth_headers):
    """POST /environments with duplicate name returns 409."""
    await post_environment(client, auth_headers, "DuplicateEnv")
    response = await post_environment(client, auth_headers, "DuplicateEnv")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_environments(client: AsyncClient, auth_headers):
    """GET /environments returns all non-deleted environments for the tenant."""
    await post_environment(client, auth_headers, "EnvAlpha")
    await post_environment(client, auth_headers, "EnvBeta")

    response = await client.get("/api/v1/environments/", headers=auth_headers)
    assert response.status_code == 200
    names = [e["name"] for e in response.json()]
    assert "EnvAlpha" in names
    assert "EnvBeta" in names


@pytest.mark.asyncio
async def test_list_environments_status_filter(client: AsyncClient, auth_headers):
    """GET /environments?status=inactive filters by status correctly."""
    await post_environment(client, auth_headers, "ActiveEnv", status="active")
    await post_environment(client, auth_headers, "InactiveEnv", status="inactive")

    response = await client.get("/api/v1/environments/?status=inactive", headers=auth_headers)
    assert response.status_code == 200
    names = [e["name"] for e in response.json()]
    assert "InactiveEnv" in names
    assert "ActiveEnv" not in names


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, auth_headers, other_auth_headers):
    """Environment created by tenant A is not visible to tenant B."""
    create_resp = await post_environment(client, auth_headers, "TenantAEnv")
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
    create_resp = await post_environment(
        client, auth_headers, "GetMeEnv", description="UAT env"
    )
    env_id = create_resp.json()["id"]

    response = await client.get(f"/api/v1/environments/{env_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == env_id
    assert data["name"] == "GetMeEnv"
    assert data["description"] == "UAT env"
    assert data["tier_name"] == "SIT"


@pytest.mark.asyncio
async def test_update_environment(client: AsyncClient, auth_headers):
    """PATCH /environments/{id} updates specified fields."""
    create_resp = await post_environment(client, auth_headers, "OriginalEnv")
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
    # the tier should be unchanged
    assert data["tier_name"] == "SIT"


@pytest.mark.asyncio
async def test_delete_environment_soft(client: AsyncClient, auth_headers, db_session):
    """DELETE /environments/{id} soft-deletes; environment no longer appears in list."""
    create_resp = await post_environment(client, auth_headers, "ToDeleteEnv")
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
    env_resp = await post_environment(client, auth_headers, "EnvWithSys")
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
    env_resp = await post_environment(client, auth_headers, "DupEnv")
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
    env_resp = await post_environment(client, auth_headers, "PatchEnv")
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
    env_resp = await post_environment(client, auth_headers, "RemoveEnv")
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
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    charlie = Environment(tenant_id=test_tenant.id, name="Charlie", tier_id=tier.id)
    alpha = Environment(tenant_id=test_tenant.id, name="Alpha", tier_id=tier.id)
    bravo = Environment(tenant_id=test_tenant.id, name="Bravo", tier_id=tier.id)
    db_session.add_all([charlie, alpha, bravo])
    await db_session.commit()

    response = await client.get("/api/v1/environments/", headers=auth_headers)
    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == [alpha.id, bravo.id, charlie.id]


@pytest.mark.asyncio
async def test_list_environments_sort_by_name_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    charlie = Environment(tenant_id=test_tenant.id, name="Charlie", tier_id=tier.id)
    alpha = Environment(tenant_id=test_tenant.id, name="Alpha", tier_id=tier.id)
    bravo = Environment(tenant_id=test_tenant.id, name="Bravo", tier_id=tier.id)
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
async def test_list_environments_sort_by_tier_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    """Names/ids are already in ascending order here, so only the tier name —
    not the name tiebreaker or insertion order — could produce these
    sequences."""
    zebra = await ensure_environment_tier(db_session, test_tenant.id, name="zebra")
    apple = await ensure_environment_tier(db_session, test_tenant.id, name="apple")
    middle = await ensure_environment_tier(db_session, test_tenant.id, name="middle")
    e1 = Environment(tenant_id=test_tenant.id, name="E1", tier_id=zebra.id)
    e2 = Environment(tenant_id=test_tenant.id, name="E2", tier_id=apple.id)
    e3 = Environment(tenant_id=test_tenant.id, name="E3", tier_id=middle.id)
    db_session.add_all([e1, e2, e3])
    await db_session.commit()

    asc = await client.get(
        "/api/v1/environments/?sort_by=tier&sort_dir=asc", headers=auth_headers
    )
    assert asc.status_code == 200
    assert [e["id"] for e in asc.json()] == [e2.id, e3.id, e1.id]

    desc = await client.get(
        "/api/v1/environments/?sort_by=tier&sort_dir=desc", headers=auth_headers
    )
    assert desc.status_code == 200
    assert [e["id"] for e in desc.json()] == [e1.id, e3.id, e2.id]


@pytest.mark.asyncio
async def test_list_environments_sort_by_status_both_directions(
    client: AsyncClient, auth_headers, db_session, test_tenant
):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    s1 = Environment(
        tenant_id=test_tenant.id, name="S1", tier_id=tier.id,
        status=EnvironmentStatus.MAINTENANCE,
    )
    s2 = Environment(
        tenant_id=test_tenant.id, name="S2", tier_id=tier.id,
        status=EnvironmentStatus.ACTIVE,
    )
    s3 = Environment(
        tenant_id=test_tenant.id, name="S3", tier_id=tier.id,
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
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    c1 = Environment(
        tenant_id=test_tenant.id, name="C1", tier_id=tier.id,
        created_at=base + timedelta(days=2),
    )
    c2 = Environment(
        tenant_id=test_tenant.id, name="C2", tier_id=tier.id, created_at=base,
    )
    c3 = Environment(
        tenant_id=test_tenant.id, name="C3", tier_id=tier.id,
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
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    prod = Environment(tenant_id=test_tenant.id, name="Production", tier_id=tier.id)
    prod_backup = Environment(
        tenant_id=test_tenant.id, name="production-backup", tier_id=tier.id
    )
    staging = Environment(tenant_id=test_tenant.id, name="Staging", tier_id=tier.id)
    db_session.add_all([prod, prod_backup, staging])
    await db_session.commit()

    response = await client.get("/api/v1/environments/?search=PROD", headers=auth_headers)
    assert response.status_code == 200
    ids = {e["id"] for e in response.json()}
    assert ids == {prod.id, prod_backup.id}
