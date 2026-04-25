"""/api/v1/webhooks/can-deploy — HTTP integration tests."""
import pytest

from app.services import api_key_service


async def _scaffold(db_session, tenant, user):
    from app.db.models.environment import Environment
    from app.db.models.system import System, SubSystem
    sys_row = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys_row)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys_row.id, name="orders-api")
    env = Environment(
        tenant_id=tenant.id,
        name="sit",
        environment_type="integration",
    )
    db_session.add_all([sub, env])
    await db_session.flush()
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    return raw


@pytest.mark.asyncio
async def test_can_deploy_unauthenticated(client):
    r = await client.get(
        "/api/v1/webhooks/can-deploy",
        params={"environment_slug": "sit", "subsystem_slug": "orders-api"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_can_deploy_wrong_scope(client, db_session, tenant, user):
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Narrow", scopes=["other"],
    )
    await db_session.commit()
    r = await client.get(
        "/api/v1/webhooks/can-deploy",
        headers={"X-Api-Key": raw},
        params={"environment_slug": "sit", "subsystem_slug": "orders-api"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_can_deploy_happy_path(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    r = await client.get(
        "/api/v1/webhooks/can-deploy",
        headers={"X-Api-Key": raw},
        params={"environment_slug": "sit", "subsystem_slug": "orders-api"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["environment_slug"] == "sit"
    assert body["subsystem_slug"] == "orders-api"
    assert body["blockers"] == []
    assert body["warnings"] == []
    assert body["claim_matched"] is None


@pytest.mark.asyncio
async def test_can_deploy_environment_not_found(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    r = await client.get(
        "/api/v1/webhooks/can-deploy",
        headers={"X-Api-Key": raw},
        params={"environment_slug": "nope", "subsystem_slug": "orders-api"},
    )
    assert r.status_code == 404
