"""GET /api/v1/deployments + detail + link-change + env deployments."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services import change_request_service


async def _seed(db_session, test_tenant, test_user, status="success"):
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.build import Build
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.db.models.deployment import Deployment
    await change_request_service.seed_default_lifecycles(db_session, test_tenant.id)

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
    db_session.add(build)
    await db_session.flush()
    cr = await change_request_service.create_code_deployment(
        db_session, tenant_id=test_tenant.id, raised_by=test_user.id,
        title="x", description="y",
    )
    dep = Deployment(
        tenant_id=test_tenant.id, build_id=build.id, environment_id=env.id,
        change_request_id=cr.id, event_id=str(uuid4()),
        deployed_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        status=status,
    )
    db_session.add(dep)
    await db_session.commit()
    return env, build, cr, dep


@pytest.mark.asyncio
async def test_list_and_detail(client, auth_headers, db_session, test_tenant, test_user):
    env, build, cr, dep = await _seed(db_session, test_tenant, test_user)

    r = await client.get("/api/v1/deployments", headers=auth_headers)
    assert r.status_code == 200
    assert any(d["id"] == dep.id for d in r.json())

    r = await client.get(f"/api/v1/deployments/{dep.id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "success"


@pytest.mark.asyncio
async def test_env_deployments(client, auth_headers, db_session, test_tenant, test_user):
    env, build, cr, dep = await _seed(db_session, test_tenant, test_user)
    r = await client.get(f"/api/v1/environments/{env.id}/deployments", headers=auth_headers)
    assert r.status_code == 200
    assert any(d["id"] == dep.id for d in r.json())


@pytest.mark.asyncio
async def test_link_change_replaces_autocreated_cr(client, auth_headers, db_session, test_tenant, test_user):
    """The seeded CR is created via create_code_deployment → uses the Code
    Deployment lifecycle template → swap allowed."""
    env, build, cr_auto, dep = await _seed(db_session, test_tenant, test_user)

    # Create a second human-authored CR using a different lifecycle template.
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.db.models.lifecycle import LifecycleTemplate
    from sqlalchemy import select
    other_tpl = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "change_request",
            LifecycleTemplate.name == "Simple Approval",
        )
    )).scalar_one()
    cr_human = ChangeRequest(
        tenant_id=test_tenant.id, title="Human CR", description="",
        change_type=ChangeType.CONFIGURATION, status="draft",
        lifecycle_id=other_tpl.id,
        raised_by=test_user.id,
        scheduled_start=datetime.now(timezone.utc),
        scheduled_end=datetime.now(timezone.utc),
    )
    db_session.add(cr_human)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/deployments/{dep.id}/link-change",
        headers=auth_headers,
        json={"change_request_id": cr_human.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["change_request_id"] == cr_human.id
