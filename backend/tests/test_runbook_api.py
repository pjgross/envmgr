"""The runbook routes end to end: roles, the composite read, 409 wording on
the wire, tenant isolation, and history usernames resolved without a tenant
qualifier."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.factories import add_group_member, ensure_user_group
from tests.runbook_helpers import attach_system, login_headers, make_release, make_system

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc).isoformat()


async def _plan(client, headers, release_id, env_id):
    r = await client.post(f"/api/v1/releases/{release_id}/runbooks", headers=headers,
                          json={"environment_id": env_id, "name": "Prod cutover", "anchor_start_at": ANCHOR})
    assert r.status_code == 201, r.text
    return r.json()["plan"]   # the create route returns the composite


async def _task(client, headers, plan_id, name, **kw):
    r = await client.post(f"/api/v1/runbooks/{plan_id}/tasks", headers=headers,
                          json={"name": name, "duration_minutes": kw.pop("duration", 30), **kw})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_the_composite_read_carries_schedule_names_and_allowed_transitions(
        client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    api = await make_system(db_session, test_tenant.id, "Payments API")
    await attach_system(db_session, release, api)
    team = await ensure_user_group(db_session, test_tenant.id, name="Payments team")
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    a = await _task(client, auth_headers, plan["id"], "Deploy API", system_id=api.id, team_group_id=team.id, kind="deploy")
    b = await _task(client, auth_headers, plan["id"], "Smoke test", predecessor_ids=[a["id"]], duration=15)
    body = (await client.get(f"/api/v1/runbooks/{plan['id']}", headers=auth_headers)).json()
    assert body["plan"]["environment_name"] == test_environment.name and body["plan"]["state"] == "not_started"
    tasks = {t["name"]: t for t in body["tasks"]}
    assert tasks["Deploy API"]["team_name"] == "Payments team"
    assert tasks["Deploy API"]["system_name"] == "Payments API" and tasks["Deploy API"]["system_on_release"] is True
    assert tasks["Smoke test"]["predecessor_ids"] == [a["id"]]
    assert tasks["Smoke test"]["planned_start"].startswith("2026-10-01T18:30")
    assert tasks["Deploy API"]["allowed_transitions"] == ["in_progress", "done", "skipped"]
    assert tasks["Smoke test"]["allowed_transitions"] == ["skipped"]
    assert body["planned_end"].startswith("2026-10-01T18:45")


@pytest.mark.asyncio
async def test_out_of_order_start_is_a_409_naming_the_blocker(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    a = await _task(client, auth_headers, plan["id"], "Deploy API")
    b = await _task(client, auth_headers, plan["id"], "Smoke test", predecessor_ids=[a["id"]])
    r = await client.post(f"/api/v1/runbook-tasks/{b['id']}/transition", headers=auth_headers,
                          json={"to_status": "in_progress"})
    assert r.status_code == 409 and "Deploy API (not_started)" in r.json()["detail"]


@pytest.mark.asyncio
async def test_structure_is_admin_or_rm_and_status_is_the_team(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    team = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    await db_session.commit()
    dev, dev_headers = await login_headers(client, db_session, test_tenant, "c5dev", "Developer")
    rm, rm_headers = await login_headers(client, db_session, test_tenant, "c5rm", "Release Manager")
    await add_group_member(db_session, team, dev)
    await db_session.commit()
    denied = await client.post(f"/api/v1/releases/{release.id}/runbooks", headers=dev_headers,
                               json={"environment_id": test_environment.id, "name": "X", "anchor_start_at": ANCHOR})
    assert denied.status_code == 403
    plan = await _plan(client, rm_headers, release.id, test_environment.id)
    task = await _task(client, rm_headers, plan["id"], "Restart", team_group_id=team.id)
    assert (await client.patch(f"/api/v1/runbook-tasks/{task['id']}", headers=dev_headers,
                               json={"duration_minutes": 5})).status_code == 403
    ok = await client.post(f"/api/v1/runbook-tasks/{task['id']}/transition", headers=dev_headers,
                           json={"to_status": "in_progress"})
    assert ok.status_code == 200, ok.text
    listed = await client.get(f"/api/v1/releases/{release.id}/runbooks", headers=dev_headers)
    assert listed.status_code == 200 and listed.headers["X-Total-Count"] == "1"
    assert listed.json()[0]["state"] == "in_progress"


@pytest.mark.asyncio
async def test_an_unknown_field_is_a_422(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    r = await client.patch(f"/api/v1/runbooks/{plan['id']}", headers=auth_headers, json={"state": "complete"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_another_tenant_sees_nothing(client, auth_headers, db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    task = await _task(client, auth_headers, plan["id"], "T")
    other_tenant, other_user = await second_tenant_factory()
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"username": other_user.username, "password": "password123",
                                                      "tenant_slug": other_tenant.slug})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get(f"/api/v1/runbooks/{plan['id']}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/runbook-tasks/{task['id']}/events", headers=other)).status_code == 404
    assert (await client.post(f"/api/v1/runbook-tasks/{task['id']}/transition", headers=other,
                              json={"to_status": "in_progress"})).status_code == 404


@pytest.mark.asyncio
async def test_history_names_an_actor_from_outside_the_tenant(client, auth_headers, db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    task = await _task(client, auth_headers, plan["id"], "T")
    await client.post(f"/api/v1/runbook-tasks/{task['id']}/transition", headers=auth_headers, json={"to_status": "in_progress"})
    other_tenant, other_user = await second_tenant_factory()
    from sqlalchemy import update
    from app.db.models.runbook import RunbookTaskEvent
    await db_session.execute(update(RunbookTaskEvent).values(by_user_id=other_user.id))
    await db_session.commit()
    events = (await client.get(f"/api/v1/runbook-tasks/{task['id']}/events", headers=auth_headers)).json()
    assert events[0]["by_username"] == other_user.username


@pytest.mark.asyncio
async def test_a_system_that_left_the_release_still_renders_by_name(client, auth_headers, db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    api = await make_system(db_session, test_tenant.id, "Legacy API")
    rs = await attach_system(db_session, release, api)
    await db_session.commit()
    plan = await _plan(client, auth_headers, release.id, test_environment.id)
    await _task(client, auth_headers, plan["id"], "Deploy", system_id=api.id)
    await db_session.delete(rs)
    await db_session.commit()
    t = (await client.get(f"/api/v1/runbooks/{plan['id']}", headers=auth_headers)).json()["tasks"][0]
    assert t["system_name"] == "Legacy API" and t["system_on_release"] is False
