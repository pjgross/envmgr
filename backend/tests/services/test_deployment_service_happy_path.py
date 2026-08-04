"""DeploymentService.ingest — success path with caller-supplied CR id."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.schemas.build import BuildPayload
from app.api.v1.schemas.deployment import DeploymentWebhookPayload
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.version import EnvironmentSubSystemVersion
from app.services import deployment_service
from tests.factories import ensure_environment_tier


async def _setup(db_session, tenant, user):
    """Create minimal system/subsystem/env/CR scaffolding."""
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.change_request import ChangeRequest
    from app.services import change_request_service

    await change_request_service.seed_default_lifecycles(db_session, tenant.id)

    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    tier = await ensure_environment_tier(db_session, tenant.id)
    env = Environment(tenant_id=tenant.id, name="sit", tier_id=tier.id)
    db_session.add_all([sub, env])
    await db_session.flush()

    # A pre-existing CR the caller references — use the service so lifecycle_id is set.
    cr = await change_request_service.create_code_deployment(
        db_session,
        tenant_id=tenant.id,
        raised_by=user.id,
        title="Manual CR",
        description="x",
    )
    await db_session.flush()
    return {"system": sys, "subsystem": sub, "environment": env, "cr": cr}


@pytest.mark.asyncio
async def test_ingest_success_creates_build_deployment_and_version_row(
    db_session, tenant, user,
):
    ctx = await _setup(db_session, tenant, user)
    payload = DeploymentWebhookPayload(
        event_id=uuid4(),
        system_slug="Orders",
        subsystem_slug="orders-api",
        environment_slug="sit",
        status="success",
        deployed_at=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        change_request_id=ctx["cr"].id,
        deployer_name="github.actor:alice",
        build=BuildPayload(
            git_sha="abcdef1234567890",
            build_number="#1",
            commit_timestamp=datetime(2026, 4, 23, 14, tzinfo=timezone.utc),
        ),
    )
    result = await deployment_service.ingest(
        db_session, tenant.id, payload, raised_by_user_id=user.id,
    )
    await db_session.flush()

    assert result.replayed is False
    build = (await db_session.execute(
        select(Build).where(Build.id == result.build_id)
    )).scalar_one()
    assert build.git_sha == "abcdef1234567890"

    deployment = (await db_session.execute(
        select(Deployment).where(Deployment.id == result.deployment_id)
    )).scalar_one()
    assert deployment.status == "success"
    assert deployment.environment_id == ctx["environment"].id
    assert deployment.change_request_id == ctx["cr"].id

    version = (await db_session.execute(
        select(EnvironmentSubSystemVersion).where(
            EnvironmentSubSystemVersion.environment_id == ctx["environment"].id,
            EnvironmentSubSystemVersion.subsystem_id == ctx["subsystem"].id,
        )
    )).scalars().all()
    assert len(version) == 1
    assert version[0].build_fk_id == build.id
    assert version[0].build_identifier == "abcdef123456"  # first 12 chars
