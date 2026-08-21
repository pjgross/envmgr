"""HTTP-level coverage for /api/v1/gate-types.

test_gate_type_service.py exercises the service layer directly. Nothing
before this file exercised the router itself, so a future swap of
require_tenant_admin() for get_current_user on a write route — the exact
failure shape B3a shipped by false analogy with /tenant/users — would leave
the whole suite green. This is that review, in test form, following the
pattern in test_environment_groups_authz.py / test_projects_authz.py.

Uses the shared `member_headers` fixture (a non-Admin Developer in
test_tenant) rather than a local login helper — it existed for exactly this
and was unused.
"""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER


@pytest.mark.asyncio
async def test_a_non_admin_can_list_gate_types(client, auth_headers, member_headers):
    created = await client.post(
        "/api/v1/gate-types",
        json={"name": "Security", "failure_behaviour": "block"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    listed = await client.get("/api/v1/gate-types", headers=member_headers)
    assert listed.status_code == 200, listed.text
    assert "Security" in [g["name"] for g in listed.json()]


@pytest.mark.asyncio
async def test_a_non_admin_cannot_create_update_or_delete(
    client, auth_headers, member_headers
):
    created_as_admin = await client.post(
        "/api/v1/gate-types",
        json={"name": "UAT Sign-off", "failure_behaviour": "warn"},
        headers=auth_headers,
    )
    assert created_as_admin.status_code == 201, created_as_admin.text
    type_id = created_as_admin.json()["id"]

    created = await client.post(
        "/api/v1/gate-types",
        json={"name": "Nope", "failure_behaviour": "warn"},
        headers=member_headers,
    )
    assert created.status_code == 403, created.text

    updated = await client.put(
        f"/api/v1/gate-types/{type_id}",
        json={"description": "should not land"},
        headers=member_headers,
    )
    assert updated.status_code == 403, updated.text

    deleted = await client.delete(
        f"/api/v1/gate-types/{type_id}", headers=member_headers
    )
    assert deleted.status_code == 403, deleted.text

    # Refused, not silently accepted: the row is still there and unchanged.
    still_listed = await client.get("/api/v1/gate-types", headers=auth_headers)
    names = [g["name"] for g in still_listed.json()]
    assert "UAT Sign-off" in names
    assert "Nope" not in names


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get(
        "/api/v1/gate-types?sort_by=nonsense", headers=auth_headers
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_list_carries_x_total_count(client, auth_headers):
    made = await client.post(
        "/api/v1/gate-types",
        json={"name": "Perf Sign-off", "failure_behaviour": "warn"},
        headers=auth_headers,
    )
    assert made.status_code == 201, made.text

    listed = await client.get("/api/v1/gate-types", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert TOTAL_COUNT_HEADER in listed.headers
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == len(listed.json())


@pytest.mark.asyncio
async def test_create_returns_201(client, auth_headers):
    created = await client.post(
        "/api/v1/gate-types",
        json={"name": "Deploy Readiness", "failure_behaviour": "accept_with_exception"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Deploy Readiness"
