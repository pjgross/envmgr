"""Integration tests for Version Tracking (M5)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.db.models.system import System, SubSystem
from app.core.security import get_password_hash, create_access_token


# ---------------------------------------------------------------------------
# Fixtures for a second tenant (isolation tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def other_tenant(db_session) -> Tenant:
    tenant = Tenant(name="Other Version Org", slug="other-version-org")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture(scope="function")
async def other_user(db_session, other_tenant) -> User:
    user = User(
        tenant_id=other_tenant.id,
        username="otherversionadmin",
        email="admin@otherversion.com",
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


async def _create_env(client, auth_headers, name="VersionTestEnv") -> int:
    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": name, "environment_type": "test"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_system_and_subsystem(db_session, tenant_id: int) -> tuple[int, int]:
    """Create a system + subsystem directly in DB. Returns (system_id, subsystem_id)."""
    system = System(
        name="TestSystem",
        tenant_id=tenant_id,
    )
    db_session.add(system)
    await db_session.commit()
    await db_session.refresh(system)

    subsystem = SubSystem(
        name="TestSubSystem",
        system_id=system.id,
        tenant_id=tenant_id,
    )
    db_session.add(subsystem)
    await db_session.commit()
    await db_session.refresh(subsystem)

    return system.id, subsystem.id


async def _link_system_to_env(client, auth_headers, env_id: int, system_id: int) -> None:
    """Link a system to an environment via the API (required before recording versions)."""
    resp = await client.post(
        f"/api/v1/environments/{env_id}/systems",
        headers=auth_headers,
        json={"system_id": system_id},
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_version(client: AsyncClient, auth_headers, test_tenant, db_session):
    """POST /environments/{id}/versions creates a new version row."""
    env_id = await _create_env(client, auth_headers, "RecordVersionEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)
    await _link_system_to_env(client, auth_headers, env_id, sys_id)

    resp = await client.post(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
        json={
            "subsystem_id": sub_id,
            "build_identifier": "build-001",
            "version_label": "v1.0.0",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["environment_id"] == env_id
    assert data["subsystem_id"] == sub_id
    assert data["build_identifier"] == "build-001"
    assert data["version_label"] == "v1.0.0"
    assert data["subsystem_name"] == "TestSubSystem"
    assert "id" in data
    assert "installed_at" in data


@pytest.mark.asyncio
async def test_list_versions_all(client: AsyncClient, auth_headers, test_tenant, db_session):
    """GET /environments/{id}/versions returns all version history."""
    env_id = await _create_env(client, auth_headers, "ListAllVersionsEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)
    await _link_system_to_env(client, auth_headers, env_id, sys_id)

    # Record 3 versions
    for i in range(3):
        await client.post(
            f"/api/v1/environments/{env_id}/versions",
            headers=auth_headers,
            json={
                "subsystem_id": sub_id,
                "build_identifier": f"build-{i:03d}",
                "version_label": f"v1.{i}.0",
            },
        )

    resp = await client.get(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 3


@pytest.mark.asyncio
async def test_list_versions_current_only(client: AsyncClient, auth_headers, test_tenant, db_session):
    """GET /versions?current_only=true returns only one row per subsystem."""
    env_id = await _create_env(client, auth_headers, "CurrentOnlyEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)
    await _link_system_to_env(client, auth_headers, env_id, sys_id)

    # Record 3 versions for the same subsystem
    for i in range(3):
        await client.post(
            f"/api/v1/environments/{env_id}/versions",
            headers=auth_headers,
            json={
                "subsystem_id": sub_id,
                "build_identifier": f"build-{i:03d}",
                "version_label": f"v1.{i}.0",
            },
        )

    resp = await client.get(
        f"/api/v1/environments/{env_id}/versions?current_only=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Only 1 row — the latest — should come back
    assert len(data) == 1


@pytest.mark.asyncio
async def test_version_history_current_only_returns_latest(
    client: AsyncClient, auth_headers, test_tenant, db_session
):
    """
    Record 2 versions for the same subsystem.
    current_only=true must return only the later one (higher version_label / installed_at).
    """
    env_id = await _create_env(client, auth_headers, "HistoryLatestEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)
    await _link_system_to_env(client, auth_headers, env_id, sys_id)

    from datetime import datetime, timezone, timedelta

    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=1)

    await client.post(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
        json={
            "subsystem_id": sub_id,
            "build_identifier": "build-old",
            "version_label": "v1.0.0",
            "installed_at": t1.isoformat(),
        },
    )
    await client.post(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
        json={
            "subsystem_id": sub_id,
            "build_identifier": "build-new",
            "version_label": "v2.0.0",
            "installed_at": t2.isoformat(),
        },
    )

    # All history should have 2 rows
    all_resp = await client.get(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
    )
    assert len(all_resp.json()) == 2

    # current_only should return only the newer one
    current_resp = await client.get(
        f"/api/v1/environments/{env_id}/versions?current_only=true",
        headers=auth_headers,
    )
    data = current_resp.json()
    assert len(data) == 1
    assert data[0]["build_identifier"] == "build-new"
    assert data[0]["version_label"] == "v2.0.0"


@pytest.mark.asyncio
async def test_version_tenant_isolation(
    client: AsyncClient, auth_headers, other_auth_headers, other_tenant, db_session
):
    """Environment belonging to another tenant returns 404."""
    # Create env under other_tenant
    other_env_resp = await client.post(
        "/api/v1/environments/",
        headers=other_auth_headers,
        json={"name": "OtherTenantEnv", "environment_type": "test"},
    )
    assert other_env_resp.status_code == 201
    other_env_id = other_env_resp.json()["id"]

    _, sub_id = await _create_system_and_subsystem(db_session, other_tenant.id)

    # Try to record version for that env as the primary tenant user → 404
    resp = await client.post(
        f"/api/v1/environments/{other_env_id}/versions",
        headers=auth_headers,
        json={
            "subsystem_id": sub_id,
            "build_identifier": "build-x",
            "version_label": "v1.0.0",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_version_invalid_subsystem(
    client: AsyncClient, auth_headers, other_tenant, db_session
):
    """Subsystem belonging to another tenant returns 404."""
    env_id = await _create_env(client, auth_headers, "InvalidSubEnv")

    # Create a subsystem belonging to OTHER tenant
    _, other_sub_id = await _create_system_and_subsystem(db_session, other_tenant.id)

    resp = await client.post(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
        json={
            "subsystem_id": other_sub_id,
            "build_identifier": "build-x",
            "version_label": "v1.0.0",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_version_subsystem_not_linked_to_env(
    client: AsyncClient, auth_headers, test_tenant, db_session
):
    """Subsystem whose parent system is NOT linked to the environment returns 422."""
    env_id = await _create_env(client, auth_headers, "UnlinkedSysEnv")
    # Create system + subsystem but do NOT link the system to the environment
    _, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)

    resp = await client.post(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
        json={
            "subsystem_id": sub_id,
            "build_identifier": "build-x",
            "version_label": "v1.0.0",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH / DELETE tests
# ---------------------------------------------------------------------------


async def _record_version(client, auth_headers, env_id: int, sub_id: int, build_identifier="build-001", version_label="v1.0.0") -> int:
    resp = await client.post(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
        json={
            "subsystem_id": sub_id,
            "build_identifier": build_identifier,
            "version_label": version_label,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_update_version(client: AsyncClient, auth_headers, test_tenant, db_session):
    """PATCH /environments/{id}/versions/{vid} updates mutable fields."""
    env_id = await _create_env(client, auth_headers, "UpdateVersionEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)
    await _link_system_to_env(client, auth_headers, env_id, sys_id)
    version_id = await _record_version(client, auth_headers, env_id, sub_id)

    resp = await client.patch(
        f"/api/v1/environments/{env_id}/versions/{version_id}",
        headers=auth_headers,
        json={"build_identifier": "build-edited", "version_label": "v1.0.1"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == version_id
    assert data["build_identifier"] == "build-edited"
    assert data["version_label"] == "v1.0.1"


@pytest.mark.asyncio
async def test_update_version_partial(client: AsyncClient, auth_headers, test_tenant, db_session):
    """PATCH with only one field leaves others unchanged."""
    env_id = await _create_env(client, auth_headers, "PartialUpdateVersionEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)
    await _link_system_to_env(client, auth_headers, env_id, sys_id)
    version_id = await _record_version(client, auth_headers, env_id, sub_id, build_identifier="build-orig", version_label="v2.0.0")

    resp = await client.patch(
        f"/api/v1/environments/{env_id}/versions/{version_id}",
        headers=auth_headers,
        json={"build_identifier": "build-changed"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["build_identifier"] == "build-changed"
    assert data["version_label"] == "v2.0.0"  # unchanged


@pytest.mark.asyncio
async def test_delete_version(client: AsyncClient, auth_headers, test_tenant, db_session):
    """DELETE /environments/{id}/versions/{vid} removes the row (204)."""
    env_id = await _create_env(client, auth_headers, "DeleteVersionEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, test_tenant.id)
    await _link_system_to_env(client, auth_headers, env_id, sys_id)
    version_id = await _record_version(client, auth_headers, env_id, sub_id)

    resp = await client.delete(
        f"/api/v1/environments/{env_id}/versions/{version_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204, resp.text

    # Confirm gone — list should return 0
    list_resp = await client.get(
        f"/api/v1/environments/{env_id}/versions",
        headers=auth_headers,
    )
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_update_version_wrong_tenant_returns_404(
    client: AsyncClient, auth_headers, other_auth_headers, other_tenant, db_session, test_tenant
):
    """PATCH on a version belonging to another tenant returns 404."""
    # Create version under other_tenant
    other_env_id = await _create_env(client, other_auth_headers, "OtherTenantEditEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, other_tenant.id)
    await _link_system_to_env(client, other_auth_headers, other_env_id, sys_id)
    version_id = await _record_version(client, other_auth_headers, other_env_id, sub_id)

    # Try to edit it as the primary tenant admin → should 404
    resp = await client.patch(
        f"/api/v1/environments/{other_env_id}/versions/{version_id}",
        headers=auth_headers,
        json={"build_identifier": "hacked"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_version_wrong_tenant_returns_404(
    client: AsyncClient, auth_headers, other_auth_headers, other_tenant, db_session
):
    """DELETE on a version belonging to another tenant returns 404."""
    other_env_id = await _create_env(client, other_auth_headers, "OtherTenantDeleteEnv")
    sys_id, sub_id = await _create_system_and_subsystem(db_session, other_tenant.id)
    await _link_system_to_env(client, other_auth_headers, other_env_id, sys_id)
    version_id = await _record_version(client, other_auth_headers, other_env_id, sub_id)

    resp = await client.delete(
        f"/api/v1/environments/{other_env_id}/versions/{version_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_cannot_edit_version(client: AsyncClient, db_session, test_tenant, auth_headers):
    """A non-admin (Viewer) receives 403 when trying to PATCH a version."""
    viewer = User(
        tenant_id=test_tenant.id,
        username="versionviewer1",
        email="versionviewer1@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(viewer)
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={
        "username": "versionviewer1",
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # We don't need a real version_id — auth check happens before DB lookup
    resp = await client.patch(
        "/api/v1/environments/1/versions/1",
        headers=viewer_headers,
        json={"build_identifier": "nope"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_cannot_delete_version(client: AsyncClient, db_session, test_tenant):
    """A non-admin (Viewer) receives 403 when trying to DELETE a version."""
    viewer = User(
        tenant_id=test_tenant.id,
        username="versionviewer2",
        email="versionviewer2@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(viewer)
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={
        "username": "versionviewer2",
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.delete(
        "/api/v1/environments/1/versions/1",
        headers=viewer_headers,
    )
    assert resp.status_code == 403
