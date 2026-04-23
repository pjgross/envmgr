"""/api/v1/environments/{id}/schedule — deployments array populated."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_schedule_includes_deployments(client, auth_headers, db_session, test_tenant, test_user):
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.build import Build
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.db.models.deployment import Deployment

    sys = System(tenant_id=test_tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=test_tenant.id, name="sit", environment_type="integration")
    db_session.add_all([sub, env])
    await db_session.flush()
    build = Build(
        tenant_id=test_tenant.id, subsystem_id=sub.id, git_sha="a" * 40,
        build_number="#1", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )

    # A minimal CR — use the seeded Code Deployment template via the service helper.
    from app.services import change_request_service
    await change_request_service.seed_default_lifecycles(db_session, test_tenant.id)
    db_session.add(build)
    await db_session.flush()
    cr = await change_request_service.create_code_deployment(
        db_session, tenant_id=test_tenant.id, raised_by=test_user.id,
        title="x", description="y",
    )
    cr.status = "deployed"
    dep = Deployment(
        tenant_id=test_tenant.id, build_id=build.id, environment_id=env.id,
        change_request_id=cr.id, event_id=str(uuid4()),
        deployed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        status="success",
    )
    db_session.add(dep)
    await db_session.commit()

    r = await client.get(
        f"/api/v1/environments/{env.id}/schedule",
        headers=auth_headers,
        params={"start_date": "2026-04-22T00:00:00Z", "end_date": "2026-04-24T00:00:00Z"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(d["id"] == dep.id for d in body["deployments"])
