"""Cross-tenant isolation for Phase 4 resources (api_keys, builds, deployments)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services import api_key_service, change_request_service
from tests.factories import ensure_environment_tier


async def _seed_one_tenant(db_session, tenant, user, name_prefix: str):
    """Create an api_key, build, deployment, CR in a single tenant."""
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.build import Build
    from app.db.models.deployment import Deployment

    await change_request_service.seed_default_lifecycles(db_session, tenant.id)

    sys_ = System(tenant_id=tenant.id, name=f"{name_prefix}-Orders")
    db_session.add(sys_)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys_.id, name=f"{name_prefix}-api")
    tier = await ensure_environment_tier(db_session, tenant.id)
    env = Environment(tenant_id=tenant.id, name=f"{name_prefix}-sit", tier_id=tier.id)
    db_session.add_all([sub, env])
    await db_session.flush()

    key, _raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name=f"{name_prefix}-key", scopes=["webhooks:deployment"],
    )

    build = Build(
        tenant_id=tenant.id, subsystem_id=sub.id,
        git_sha=f"{name_prefix.lower()}sha" + "0" * 30,
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    db_session.add(build)
    await db_session.flush()
    cr = await change_request_service.create_code_deployment(
        db_session, tenant_id=tenant.id, raised_by=user.id,
        title=f"{name_prefix} CR", description="x",
    )
    dep = Deployment(
        tenant_id=tenant.id, build_id=build.id, environment_id=env.id,
        change_request_id=cr.id, event_id=str(uuid4()),
        deployed_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        status="success",
    )
    db_session.add(dep)
    await db_session.commit()
    return {"api_key": key, "build": build, "deployment": dep, "cr": cr}


@pytest.mark.asyncio
async def test_tenant_a_cannot_see_tenant_b_resources(
    client, auth_headers, db_session, test_tenant, test_user,
    second_tenant_factory,
):
    a = await _seed_one_tenant(db_session, test_tenant, test_user, "A")

    other_tenant, other_user = await second_tenant_factory()
    b = await _seed_one_tenant(db_session, other_tenant, other_user, "B")

    r = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert r.status_code == 200
    ids = {k["id"] for k in r.json()}
    assert a["api_key"].id in ids
    assert b["api_key"].id not in ids

    r = await client.get("/api/v1/builds", headers=auth_headers)
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert a["build"].id in ids
    assert b["build"].id not in ids

    r = await client.get("/api/v1/deployments", headers=auth_headers)
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert a["deployment"].id in ids
    assert b["deployment"].id not in ids

    r = await client.get(f"/api/v1/builds/{b['build'].id}", headers=auth_headers)
    assert r.status_code == 404
    r = await client.get(f"/api/v1/deployments/{b['deployment'].id}", headers=auth_headers)
    assert r.status_code == 404

    r = await client.post(
        f"/api/v1/deployments/{a['deployment'].id}/link-change",
        headers=auth_headers,
        json={"change_request_id": b["cr"].id},
    )
    assert r.status_code == 400
