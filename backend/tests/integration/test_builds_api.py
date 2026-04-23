"""GET /api/v1/builds + /{id} — JWT auth, filters, detail."""
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_list_and_detail(client, auth_headers, db_session, test_tenant):
    from app.db.models.system import System, SubSystem
    from app.db.models.build import Build
    sys = System(tenant_id=test_tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="orders-api")
    db_session.add(sub)
    await db_session.flush()
    b = Build(
        tenant_id=test_tenant.id, subsystem_id=sub.id, git_sha="deadbeef1234",
        build_number="#5", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    db_session.add(b)
    await db_session.commit()

    r = await client.get("/api/v1/builds", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(x["id"] == b.id for x in items)

    r = await client.get(f"/api/v1/builds/{b.id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["git_sha"] == "deadbeef1234"


@pytest.mark.asyncio
async def test_filter_by_subsystem(client, auth_headers, db_session, test_tenant):
    from app.db.models.system import System, SubSystem
    from app.db.models.build import Build
    sys = System(tenant_id=test_tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub_a = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="a")
    sub_b = SubSystem(tenant_id=test_tenant.id, system_id=sys.id, name="b")
    db_session.add_all([sub_a, sub_b])
    await db_session.flush()
    for sub, sha in [(sub_a, "aaaa"), (sub_b, "bbbb")]:
        db_session.add(Build(
            tenant_id=test_tenant.id, subsystem_id=sub.id, git_sha=sha * 4,
            build_number="#1", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
        ))
    await db_session.commit()

    r = await client.get(f"/api/v1/builds?subsystem_id={sub_a.id}", headers=auth_headers)
    shas = {x["git_sha"] for x in r.json()}
    assert shas == {"aaaa" * 4}
