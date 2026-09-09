# backend/tests/test_release_closeout_api.py
"""Declared stable and handover confirmed: audit pairs set and cleared through
their own routes, 409 on re-set, events on every change, Admin/RM only,
project releases only, usernames resolved WITHOUT a tenant filter."""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.models.event_log import EventLog
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.user import User
from app.services.release_defaults import seed_release_defaults_for_tenant
from tests.factories import ensure_user_group


@pytest_asyncio.fixture
async def seeded(db_session, test_tenant):
    await seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user, seeded):
    tpl = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == test_tenant.id, LifecycleTemplate.name == "Major"))).scalar_one()
    rel = Release(tenant_id=test_tenant.id, name="R", release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="deployed", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    return rel


@pytest_asyncio.fixture
async def enterprise_release(db_session, test_tenant, test_user, seeded):
    tpl = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == test_tenant.id,
        LifecycleTemplate.applies_to_kind == "enterprise"))).scalar_one()
    rel = Release(tenant_id=test_tenant.id, name="E", release_type="Enterprise", release_kind="enterprise",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    return rel


async def _rm_headers(client, db_session, test_tenant):
    user = User(tenant_id=test_tenant.id, username="c6rm", email="c6rm@test.com",
                password_hash=get_password_hash("password123"), role="Release Manager", is_active=True)
    db_session.add(user)
    await db_session.commit()
    resp = await client.post("/api/v1/auth/login", json={
        "username": "c6rm", "password": "password123", "tenant_slug": test_tenant.slug})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _event_names(db_session, release_id):
    rows = (await db_session.execute(
        select(ReleaseEventType.name).join(ReleaseEvent, ReleaseEvent.event_type_id == ReleaseEventType.id)
        .where(ReleaseEvent.release_id == release_id))).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_declare_stable_sets_the_pair_and_records_an_event(client, auth_headers, release, db_session, test_user):
    resp = await client.post(f"/api/v1/releases/{release.id}/declare-stable",
                             json={"note": "no P1 in 14 days"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["declared_stable_at"] is not None
    assert body["declared_stable_by_username"] == test_user.username
    assert "Declared stable" in await _event_names(db_session, release.id)
    outbox = (await db_session.execute(select(EventLog).where(
        EventLog.event_type == "ReleaseDeclaredStable", EventLog.aggregate_id == release.id))).scalars().all()
    assert len(outbox) == 1


@pytest.mark.asyncio
async def test_declaring_twice_is_a_409(client, auth_headers, release):
    await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    resp = await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_withdraw_clears_the_pair_and_keeps_the_history(client, auth_headers, release, db_session):
    await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    resp = await client.delete(f"/api/v1/releases/{release.id}/declare-stable", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["declared_stable_at"] is None
    assert resp.json()["declared_stable_by_username"] is None
    names = await _event_names(db_session, release.id)
    assert "Declared stable" in names and "Stability declaration withdrawn" in names


@pytest.mark.asyncio
async def test_withdrawing_nothing_is_a_409(client, auth_headers, release):
    assert (await client.delete(f"/api/v1/releases/{release.id}/declare-stable",
                                headers=auth_headers)).status_code == 409


@pytest.mark.asyncio
async def test_confirm_handover_needs_a_group(client, auth_headers, release, db_session, test_tenant):
    resp = await client.post(f"/api/v1/releases/{release.id}/confirm-handover", json={}, headers=auth_headers)
    assert resp.status_code == 422, resp.text
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    put = await client.put(f"/api/v1/releases/{release.id}", json={"operations_group_id": group.id},
                           headers=auth_headers)
    assert put.status_code == 200, put.text
    assert put.json()["operations_group_name"] == "Platform Ops"
    resp = await client.post(f"/api/v1/releases/{release.id}/confirm-handover",
                             json={"note": "runbook handed over"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["handover_confirmed_at"] is not None
    assert "Ops handover confirmed" in await _event_names(db_session, release.id)
    assert (await client.delete(f"/api/v1/releases/{release.id}/confirm-handover",
                                headers=auth_headers)).status_code == 200
    assert "Ops handover withdrawn" in await _event_names(db_session, release.id)


@pytest.mark.asyncio
async def test_a_release_manager_may_declare_and_a_developer_may_not(client, member_headers, release, db_session, test_tenant):
    assert (await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={},
                              headers=member_headers)).status_code == 403
    rm = await _rm_headers(client, db_session, test_tenant)
    assert (await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={},
                              headers=rm)).status_code == 200


@pytest.mark.asyncio
async def test_enterprise_releases_are_refused(client, auth_headers, enterprise_release):
    assert (await client.post(f"/api/v1/releases/{enterprise_release.id}/declare-stable", json={},
                              headers=auth_headers)).status_code == 422


@pytest.mark.asyncio
async def test_the_declarers_name_resolves_from_outside_the_releases_tenant(client, auth_headers, release, db_session, second_tenant_factory):
    """Master-admin impersonation: the actor legitimately sits outside the
    release's tenant. A tenant-qualified username join renders them as nobody."""
    other_tenant, other_user = await second_tenant_factory()
    release.declared_stable_by = other_user.id
    from datetime import datetime, timezone
    release.declared_stable_at = datetime.now(timezone.utc)
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}", headers=auth_headers)).json()
    assert body["declared_stable_by_username"] == other_user.username


@pytest.mark.asyncio
async def test_an_archived_group_survives_a_full_form_save(client, auth_headers, release, db_session, test_tenant):
    group = await ensure_user_group(db_session, test_tenant.id, name="Old Ops")
    await client.put(f"/api/v1/releases/{release.id}", json={"operations_group_id": group.id}, headers=auth_headers)
    from datetime import datetime, timezone
    group.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    resend = await client.put(f"/api/v1/releases/{release.id}",
                              json={"name": "R renamed", "operations_group_id": group.id}, headers=auth_headers)
    assert resend.status_code == 200, resend.text
    other = await ensure_user_group(db_session, test_tenant.id, name="Fresh")
    other.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()
    new_assign = await client.put(f"/api/v1/releases/{release.id}",
                                  json={"operations_group_id": other.id}, headers=auth_headers)
    assert new_assign.status_code == 404


@pytest.mark.asyncio
async def test_operations_group_name_resolves_on_create(client, auth_headers, db_session, test_tenant, seeded):
    """POST /releases builds its response by hand (not through
    _release_with_permissions) — the name must be resolved there too, or a
    release created with operations_group_id comes back with the name null."""
    tpl = (await db_session.execute(select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == test_tenant.id, LifecycleTemplate.name == "Major"))).scalar_one()
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    resp = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "New Release", "release_type": "Major", "lifecycle_template_id": tpl.id,
        "operations_group_id": group.id})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["operations_group_id"] == group.id
    assert body["operations_group_name"] == "Platform Ops"


@pytest.mark.asyncio
async def test_confirming_handover_twice_is_a_409(client, auth_headers, release, db_session, test_tenant):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    await client.put(f"/api/v1/releases/{release.id}", json={"operations_group_id": group.id}, headers=auth_headers)
    await client.post(f"/api/v1/releases/{release.id}/confirm-handover", json={}, headers=auth_headers)
    resp = await client.post(f"/api/v1/releases/{release.id}/confirm-handover", json={}, headers=auth_headers)
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_withdrawing_an_unconfirmed_handover_is_a_409(client, auth_headers, release, db_session, test_tenant):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    await client.put(f"/api/v1/releases/{release.id}", json={"operations_group_id": group.id}, headers=auth_headers)
    resp = await client.delete(f"/api/v1/releases/{release.id}/confirm-handover", headers=auth_headers)
    assert resp.status_code == 409, resp.text


from datetime import datetime, timedelta, timezone

from app.db.models.test_phase import TestPhase
from tests.factories import make_incident


async def _hypercare_phase(db_session, release, start, end):
    phase = TestPhase(tenant_id=release.tenant_id, release_id=release.id, name="Hyper-care",
                      order=9, start_date=start, end_date=end, status="pending", kind="hypercare")
    db_session.add(phase)
    await db_session.commit()
    return phase


@pytest.mark.asyncio
async def test_closeout_read_with_nothing_set(client, auth_headers, release):
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["hypercare"] == {"state": "none", "phase": None,
                                 "declared_stable_at": None, "declared_stable_by_username": None}
    assert body["handover"]["operations_group_id"] is None
    assert body["pir"] == {"exists": False, "status": None, "completed_at": None}
    assert body["incidents"]["total"] == 0 and body["incidents"]["window_start"] is None
    # Major's closed states, in template order, none requiring anything yet.
    assert [t["state_key"] for t in body["close_targets"]] == ["completed", "completed_with_issues", "backed_out"]
    assert all(t["can_close"] and t["unmet"] == [] for t in body["close_targets"])


@pytest.mark.asyncio
async def test_close_targets_reflect_the_flags_and_the_same_wording_as_the_422(
    client, auth_headers, release, db_session
):
    from app.db.models.lifecycle import LifecycleTemplate
    tpl = await db_session.get(LifecycleTemplate, release.lifecycle_template_id)
    defn = dict(tpl.definition)
    for s in defn["states"]:
        if s["key"] == "completed":
            s["requires_pir_complete"] = True
            s["requires_handover_confirmed"] = True
    tpl.definition = defn
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    completed = next(t for t in body["close_targets"] if t["state_key"] == "completed")
    assert completed["can_close"] is False
    assert completed["unmet"] == ["the post-implementation review is not complete",
                                  "ops handover is not confirmed"]
    refused = await client.post(f"/api/v1/releases/{release.id}/transition",
                                json={"to_state": "completed"}, headers=auth_headers)
    assert refused.status_code == 422
    for reason in completed["unmet"]:
        assert reason in refused.json()["detail"]


@pytest.mark.asyncio
async def test_incidents_in_the_window_and_only_those(client, auth_headers, release, db_session, test_tenant, test_user):
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(days=10), now + timedelta(days=4)
    await _hypercare_phase(db_session, release, start, end)
    inside = await make_incident(db_session, test_tenant.id, title="inside", severity="P1",
                                 detected_at=now - timedelta(days=2))
    inside.release_id = release.id
    before = await make_incident(db_session, test_tenant.id, title="before", severity="P2",
                                 detected_at=start - timedelta(seconds=1))
    before.release_id = release.id
    other_release = await make_incident(db_session, test_tenant.id, title="other", severity="P1",
                                        detected_at=now - timedelta(days=1))
    await db_session.commit()

    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["hypercare"]["state"] == "active"
    assert body["incidents"]["total"] == 1
    assert [i["title"] for i in body["incidents"]["items"]] == ["inside"]
    assert body["incidents"]["by_severity"] == {"P1": 1, "P2": 0, "P3": 0, "P4": 0}
    assert datetime.fromisoformat(body["incidents"]["window_start"]) == start
    # Not yet ended and not declared: the window closes at `now`.
    assert datetime.fromisoformat(body["incidents"]["window_end"]) <= datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_declaring_stable_closes_the_window(client, auth_headers, release, db_session, test_tenant):
    now = datetime.now(timezone.utc)
    await _hypercare_phase(db_session, release, now - timedelta(days=10), now + timedelta(days=10))
    await client.post(f"/api/v1/releases/{release.id}/declare-stable", json={}, headers=auth_headers)
    late = await make_incident(db_session, test_tenant.id, title="after stable", severity="P3",
                               detected_at=now + timedelta(minutes=5))
    late.release_id = release.id
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["hypercare"]["state"] == "stable"
    assert body["incidents"]["total"] == 0


@pytest.mark.asyncio
async def test_another_tenants_incident_is_never_counted(client, auth_headers, release, db_session, second_tenant_factory):
    other_tenant, _ = await second_tenant_factory()
    now = datetime.now(timezone.utc)
    await _hypercare_phase(db_session, release, now - timedelta(days=3), None)
    foreign = await make_incident(db_session, other_tenant.id, title="foreign", detected_at=now)
    foreign.release_id = release.id  # constructible: tenant_id and release_id are uncross-checked
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["incidents"]["total"] == 0


@pytest.mark.asyncio
async def test_a_template_with_no_closed_state_returns_an_empty_target_list(client, auth_headers, db_session, test_tenant, test_user):
    from app.db.models.lifecycle import LifecycleTemplate
    tpl = LifecycleTemplate(tenant_id=test_tenant.id, entity_type="release", name="NoClose", is_default=False,
                            applies_to_kind="project",
                            definition={"states": [{"key": "draft", "label": "D", "is_initial": True, "is_terminal": False},
                                                   {"key": "done", "label": "Done", "is_initial": False, "is_terminal": True}],
                                        "transitions": [], "field_permissions": {}})
    db_session.add(tpl)
    await db_session.flush()
    rel = Release(tenant_id=test_tenant.id, name="NC", release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    body = (await client.get(f"/api/v1/releases/{rel.id}/closeout", headers=auth_headers)).json()
    assert body["close_targets"] == []


@pytest.mark.asyncio
async def test_closeout_read_is_open_to_a_developer_and_refused_on_enterprise(client, member_headers, auth_headers, release, enterprise_release):
    assert (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=member_headers)).status_code == 200
    assert (await client.get(f"/api/v1/releases/{enterprise_release.id}/closeout", headers=auth_headers)).status_code == 422


@pytest.mark.asyncio
async def test_by_severity_counts_are_grouped_not_fetched_per_severity(client, auth_headers, release, db_session, test_tenant):
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(days=10), now + timedelta(days=10)
    await _hypercare_phase(db_session, release, start, end)
    p1a = await make_incident(db_session, test_tenant.id, title="p1a", severity="P1", detected_at=now - timedelta(days=1))
    p1a.release_id = release.id
    p1b = await make_incident(db_session, test_tenant.id, title="p1b", severity="P1", detected_at=now - timedelta(days=2))
    p1b.release_id = release.id
    p3 = await make_incident(db_session, test_tenant.id, title="p3", severity="P3", detected_at=now - timedelta(days=3))
    p3.release_id = release.id
    outside = await make_incident(db_session, test_tenant.id, title="outside", severity="P2",
                                  detected_at=start - timedelta(days=1))
    outside.release_id = release.id
    await db_session.commit()

    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["incidents"]["by_severity"] == {"P1": 2, "P2": 0, "P3": 1, "P4": 0}
    assert body["incidents"]["total"] == 3


@pytest.mark.asyncio
async def test_an_incident_detected_exactly_at_window_start_counts(client, auth_headers, release, db_session, test_tenant):
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(days=5), now + timedelta(days=5)
    await _hypercare_phase(db_session, release, start, end)
    boundary = await make_incident(db_session, test_tenant.id, title="on the boundary", severity="P4", detected_at=start)
    boundary.release_id = release.id
    await db_session.commit()

    body = (await client.get(f"/api/v1/releases/{release.id}/closeout", headers=auth_headers)).json()
    assert body["incidents"]["total"] == 1
    assert body["incidents"]["by_severity"]["P4"] == 1
