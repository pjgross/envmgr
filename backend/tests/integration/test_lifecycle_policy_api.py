"""B5 Task 2 — the tenant's lifecycle policy and decommission-step vocabulary."""
import pytest


@pytest.mark.asyncio
async def test_a_tenant_with_no_policy_row_reads_the_defaults(client, auth_headers):
    """No row is a legitimate state, not a 404: idle detection is simply off."""
    r = await client.get("/api/v1/tenant/environment-lifecycle-policy", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["idle_detection_enabled"] is False
    assert body["idle_threshold_days"] == 30
    assert body["decommission_notice_days"] == 5


@pytest.mark.asyncio
async def test_saving_the_policy_round_trips(client, auth_headers):
    r = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=auth_headers,
        json={
            "idle_detection_enabled": True,
            "idle_threshold_days": 45,
            "decommission_notice_days": 7,
        },
    )
    assert r.status_code == 200
    assert r.json()["idle_threshold_days"] == 45

    again = await client.get(
        "/api/v1/tenant/environment-lifecycle-policy", headers=auth_headers
    )
    assert again.json()["decommission_notice_days"] == 7


@pytest.mark.asyncio
async def test_the_read_model_cannot_be_echoed_back(client, auth_headers):
    """extra='forbid' — B2's naming policy shipped a 422 on EVERY save because
    the frontend echoed GET's body, id and timestamps included, into PUT."""
    r = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=auth_headers,
        json={
            "id": 1,
            "tenant_id": 1,
            "idle_detection_enabled": True,
            "idle_threshold_days": 45,
            "decommission_notice_days": 7,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_thresholds_must_be_positive(client, auth_headers):
    r = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=auth_headers,
        json={
            "idle_detection_enabled": True,
            "idle_threshold_days": 0,
            "decommission_notice_days": 5,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_steps_are_seeded_and_listable(client, auth_headers):
    r = await client.get("/api/v1/tenant/decommission-steps", headers=auth_headers)
    assert r.status_code == 200
    assert {s["key"] for s in r.json()} == {"final_backup", "teardown"}


@pytest.mark.asyncio
async def test_only_an_admin_may_write_the_policy(client, member_headers):
    """Reads are open to any tenant member; writes are Admin — the split B3a
    established for user groups."""
    read = await client.get(
        "/api/v1/tenant/environment-lifecycle-policy", headers=member_headers
    )
    assert read.status_code == 200

    write = await client.put(
        "/api/v1/tenant/environment-lifecycle-policy",
        headers=member_headers,
        json={
            "idle_detection_enabled": True,
            "idle_threshold_days": 45,
            "decommission_notice_days": 5,
        },
    )
    assert write.status_code == 403
