"""Idempotency + status-transition table + CR state side effects."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.schemas.build import BuildPayload
from app.api.v1.schemas.deployment import DeploymentWebhookPayload
from app.db.models.change_request import ChangeRequest
from app.db.models.deployment import Deployment
from app.services import change_request_service, deployment_service
from tests.factories import ensure_environment_tier


async def _prep(db_session, tenant, user):
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    tier = await ensure_environment_tier(db_session, tenant.id)
    env = Environment(tenant_id=tenant.id, name="sit", tier_id=tier.id)
    db_session.add_all([sub, env])
    await db_session.flush()
    return sub, env


def _payload(event_id, status, sha="aaa111"):
    return DeploymentWebhookPayload(
        event_id=event_id,
        system_slug="Orders",
        subsystem_slug="orders-api",
        environment_slug="sit",
        status=status,
        deployed_at=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        build=BuildPayload(
            git_sha=sha,
            build_number="#1",
            commit_timestamp=datetime(2026, 4, 23, 14, tzinfo=timezone.utc),
        ),
    )


@pytest.mark.asyncio
async def test_replay_returns_replayed_true(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    ev = uuid4()
    r1 = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    r2 = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    assert r2.deployment_id == r1.deployment_id
    assert r2.replayed is True

    rows = (await db_session.execute(
        select(Deployment).where(Deployment.event_id == str(ev))
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_success_transitions_cr_to_deployed(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    r = await deployment_service.ingest(
        db_session, tenant.id, _payload(uuid4(), "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    cr = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == r.change_request_id)
    )).scalar_one()
    assert cr.status == "deployed"


@pytest.mark.asyncio
async def test_failed_transitions_cr_to_failed(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    r = await deployment_service.ingest(
        db_session, tenant.id, _payload(uuid4(), "failed"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    cr = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == r.change_request_id)
    )).scalar_one()
    assert cr.status == "failed"


@pytest.mark.asyncio
async def test_pending_to_success_via_update(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    ev = uuid4()
    await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "pending"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    r = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    deployment = (await db_session.execute(
        select(Deployment).where(Deployment.event_id == str(ev))
    )).scalar_one()
    assert deployment.status == "success"


@pytest.mark.asyncio
async def test_illegal_transition_rejected(db_session, tenant, user):
    from fastapi import HTTPException
    await _prep(db_session, tenant, user)
    ev = uuid4()
    await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await deployment_service.ingest(
            db_session, tenant.id, _payload(ev, "pending"), raised_by_user_id=user.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_rolled_back_emits_event_and_leaves_cr_alone(db_session, tenant, user):
    from app.db.models.event_log import EventLog
    await _prep(db_session, tenant, user)
    ev = uuid4()
    first = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    cr_before = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == first.change_request_id)
    )).scalar_one()
    assert cr_before.status == "deployed"

    await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "rolled_back"), raised_by_user_id=user.id,
    )
    await db_session.flush()

    dep = (await db_session.execute(
        select(Deployment).where(Deployment.event_id == str(ev))
    )).scalar_one()
    assert dep.status == "rolled_back"

    cr_after = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == first.change_request_id)
    )).scalar_one()
    assert cr_after.status == "deployed"

    events = (await db_session.execute(
        select(EventLog).where(
            EventLog.tenant_id == tenant.id,
            EventLog.event_type == "DeploymentRolledBack",
            EventLog.aggregate_id == dep.id,
        )
    )).scalars().all()
    assert len(events) == 1
