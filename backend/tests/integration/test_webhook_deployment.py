"""/api/v1/webhooks/deployment — HTTP integration tests."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services import api_key_service, change_request_service


async def _scaffold(db_session, tenant, user):
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit", environment_type="integration")
    db_session.add_all([sub, env])
    await db_session.flush()
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    return raw


def _body(event_id=None):
    return {
        "event_id": str(event_id or uuid4()),
        "system_slug": "Orders",
        "subsystem_slug": "orders-api",
        "environment_slug": "sit",
        "status": "success",
        "deployed_at": datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc).isoformat(),
        "build": {
            "git_sha": "cafef00d" * 4,
            "build_number": "#1",
            "commit_timestamp": datetime(2026, 4, 23, 14, tzinfo=timezone.utc).isoformat(),
        },
    }


@pytest.mark.asyncio
async def test_webhook_happy_path(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    r = await client.post(
        "/api/v1/webhooks/deployment",
        headers={"X-Api-Key": raw},
        json=_body(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replayed"] is False
    assert "deployment_id" in body


@pytest.mark.asyncio
async def test_webhook_replay(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    ev = uuid4()
    r1 = await client.post(
        "/api/v1/webhooks/deployment", headers={"X-Api-Key": raw}, json=_body(ev),
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/api/v1/webhooks/deployment", headers={"X-Api-Key": raw}, json=_body(ev),
    )
    assert r2.status_code == 200
    assert r2.json()["replayed"] is True
    assert r2.json()["deployment_id"] == r1.json()["deployment_id"]


@pytest.mark.asyncio
async def test_webhook_unauthenticated(client):
    r = await client.post("/api/v1/webhooks/deployment", json=_body())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_wrong_scope(client, db_session, tenant, user):
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Narrow", scopes=["other"],
    )
    await db_session.commit()
    r = await client.post(
        "/api/v1/webhooks/deployment",
        headers={"X-Api-Key": raw}, json=_body(),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_webhook_rejects_missing_build_number(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    body = _body()
    del body["build"]["build_number"]
    r = await client.post(
        "/api/v1/webhooks/deployment",
        headers={"X-Api-Key": raw}, json=body,
    )
    assert r.status_code == 422
    assert "build_number" in r.text


@pytest.mark.asyncio
async def test_webhook_rejects_empty_build_number(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    body = _body()
    body["build"]["build_number"] = ""
    r = await client.post(
        "/api/v1/webhooks/deployment",
        headers={"X-Api-Key": raw}, json=body,
    )
    assert r.status_code == 422
