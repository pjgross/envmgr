"""Integration tests for GET /environments/{id}/verify."""
import pytest
from httpx import AsyncClient
from tests.factories import post_environment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_system(client, auth_headers, name: str) -> int:
    resp = await client.post("/api/v1/systems/", headers=auth_headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_env(client, auth_headers, name: str) -> int:
    resp = await post_environment(client, auth_headers, name)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_to_env(client, auth_headers, env_id: int, system_id: int, sys_status: str = "active"):
    resp = await client.post(
        f"/api/v1/environments/{env_id}/systems",
        headers=auth_headers,
        json={"system_id": system_id, "status": sys_status},
    )
    assert resp.status_code == 201, resp.text


async def _add_dep(client, auth_headers, from_id: int, to_id: int, dep_type: str = "api_call"):
    resp = await client.post(
        f"/api/v1/systems/{from_id}/dependencies",
        headers=auth_headers,
        json={"to_system_id": to_id, "dependency_type": dep_type},
    )
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_empty_environment(client: AsyncClient, auth_headers):
    """An environment with no systems returns zero counts and empty systems list."""
    env_id = await _create_env(client, auth_headers, "EmptyEnv")

    resp = await client.get(f"/api/v1/environments/{env_id}/verify", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["environment_id"] == env_id
    assert data["total_dependencies"] == 0
    assert data["satisfied_count"] == 0
    assert data["mocked_count"] == 0
    assert data["missing_count"] == 0
    assert data["systems"] == []


@pytest.mark.asyncio
async def test_verify_all_satisfied(client: AsyncClient, auth_headers):
    """A depends on B; both in env as active → satisfied."""
    sys_a = await _create_system(client, auth_headers, "SatA")
    sys_b = await _create_system(client, auth_headers, "SatB")
    env_id = await _create_env(client, auth_headers, "SatEnv")

    await _add_to_env(client, auth_headers, env_id, sys_a)
    await _add_to_env(client, auth_headers, env_id, sys_b)
    await _add_dep(client, auth_headers, sys_a, sys_b)

    resp = await client.get(f"/api/v1/environments/{env_id}/verify", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_dependencies"] == 1
    assert data["satisfied_count"] == 1
    assert data["mocked_count"] == 0
    assert data["missing_count"] == 0

    # Find the entry for sys_a
    sys_entry = next(s for s in data["systems"] if s["system_id"] == sys_a)
    assert len(sys_entry["dependencies"]) == 1
    assert sys_entry["dependencies"][0]["status"] == "satisfied"
    assert sys_entry["dependencies"][0]["to_system_id"] == sys_b


@pytest.mark.asyncio
async def test_verify_missing_dep(client: AsyncClient, auth_headers):
    """A depends on B; only A in env → B missing."""
    sys_a = await _create_system(client, auth_headers, "MisA")
    sys_b = await _create_system(client, auth_headers, "MisB")
    env_id = await _create_env(client, auth_headers, "MisEnv")

    await _add_to_env(client, auth_headers, env_id, sys_a)
    # B is NOT added to the environment
    await _add_dep(client, auth_headers, sys_a, sys_b)

    resp = await client.get(f"/api/v1/environments/{env_id}/verify", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_dependencies"] == 1
    assert data["satisfied_count"] == 0
    assert data["mocked_count"] == 0
    assert data["missing_count"] == 1

    sys_entry = next(s for s in data["systems"] if s["system_id"] == sys_a)
    dep = sys_entry["dependencies"][0]
    assert dep["status"] == "missing"
    assert dep["to_system_id"] == sys_b
    assert dep["to_system_name"] == "MisB"


@pytest.mark.asyncio
async def test_verify_both_systems_present(client: AsyncClient, auth_headers):
    """A depends on B; both in env → system dep is satisfied (no system-level mocking)."""
    sys_a = await _create_system(client, auth_headers, "BothA")
    sys_b = await _create_system(client, auth_headers, "BothB")
    env_id = await _create_env(client, auth_headers, "BothEnv")

    await _add_to_env(client, auth_headers, env_id, sys_a)
    await _add_to_env(client, auth_headers, env_id, sys_b)
    await _add_dep(client, auth_headers, sys_a, sys_b)

    resp = await client.get(f"/api/v1/environments/{env_id}/verify", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_dependencies"] == 1
    assert data["satisfied_count"] == 1
    assert data["mocked_count"] == 0
    assert data["missing_count"] == 0

    sys_entry = next(s for s in data["systems"] if s["system_id"] == sys_a)
    assert sys_entry["dependencies"][0]["status"] == "satisfied"


@pytest.mark.asyncio
async def test_verify_no_dependencies(client: AsyncClient, auth_headers):
    """A system in env with no declared deps has empty dependencies list."""
    sys_a = await _create_system(client, auth_headers, "NoDep")
    env_id = await _create_env(client, auth_headers, "NoDepEnv")

    await _add_to_env(client, auth_headers, env_id, sys_a)

    resp = await client.get(f"/api/v1/environments/{env_id}/verify", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_dependencies"] == 0
    assert len(data["systems"]) == 1
    assert data["systems"][0]["system_id"] == sys_a
    assert data["systems"][0]["dependencies"] == []
