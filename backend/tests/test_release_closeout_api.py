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
