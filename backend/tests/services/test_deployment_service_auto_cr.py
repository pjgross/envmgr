"""If the webhook omits change_request_id, ingest auto-creates a code_deployment CR."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.schemas.build import BuildPayload
from app.api.v1.schemas.deployment import DeploymentWebhookPayload
from app.db.models.change_request import ChangeRequest, ChangeType
from app.services import change_request_service, deployment_service


@pytest.mark.asyncio
async def test_ingest_auto_creates_cr_when_omitted(db_session, tenant, user):
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment

    await change_request_service.seed_default_lifecycles(db_session, tenant.id)

    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit", environment_type="integration")
    db_session.add_all([sub, env])
    await db_session.flush()

    payload = DeploymentWebhookPayload(
        event_id=uuid4(),
        system_slug="Orders",
        subsystem_slug="orders-api",
        environment_slug="sit",
        status="success",
        deployed_at=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        change_request_id=None,  # not supplied
        build=BuildPayload(
            git_sha="deadbeef1234",
            build_number="#1",
            commit_timestamp=datetime(2026, 4, 23, 14, tzinfo=timezone.utc),
        ),
    )

    result = await deployment_service.ingest(
        db_session, tenant.id, payload, raised_by_user_id=user.id,
    )
    await db_session.flush()

    cr = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == result.change_request_id)
    )).scalar_one()
    assert cr.change_type == ChangeType.CODE_DEPLOYMENT
    assert cr.raised_by == user.id
