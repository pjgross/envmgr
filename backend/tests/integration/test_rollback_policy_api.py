import pytest


@pytest.mark.asyncio
async def test_an_unconfigured_tenant_reads_defaults(client, auth_headers):
    resp = await client.get("/api/v1/tenant/rollback-policy", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "require_rollback_plan": False,
        "require_current_rehearsal": False,
        "rehearsal_validity_days": 90,
    }


@pytest.mark.asyncio
async def test_a_non_admin_can_read_but_not_write(client, member_headers):
    """Reads open to any tenant member; only writes are Admin — deliberately
    unlike /tenant/users. B3a shipped this over-gated on that false analogy."""
    assert (await client.get("/api/v1/tenant/rollback-policy",
                             headers=member_headers)).status_code == 200
    resp = await client.put("/api/v1/tenant/rollback-policy",
                            json={"require_rollback_plan": True}, headers=member_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_an_omitted_key_leaves_that_setting_alone(client, auth_headers):
    await client.put("/api/v1/tenant/rollback-policy",
                     json={"require_rollback_plan": True, "rehearsal_validity_days": 30},
                     headers=auth_headers)
    await client.put("/api/v1/tenant/rollback-policy",
                     json={"rehearsal_validity_days": 45}, headers=auth_headers)
    body = (await client.get("/api/v1/tenant/rollback-policy",
                             headers=auth_headers)).json()
    assert body["require_rollback_plan"] is True, "omitted means leave alone"
    assert body["rehearsal_validity_days"] == 45


@pytest.mark.asyncio
async def test_a_zero_validity_period_is_refused(client, auth_headers):
    resp = await client.put("/api/v1/tenant/rollback-policy",
                            json={"rehearsal_validity_days": 0}, headers=auth_headers)
    assert resp.status_code == 422
