"""Pins the deliberate read/write authorization split on user groups.

`GET /tenant/groups`, `GET /tenant/groups/{id}` and `GET /tenant/groups/{id}/members`
are readable by any tenant member; the five writes — POST/PATCH/DELETE group,
POST/DELETE member — require Admin (see app/api/v1/user_groups.py). Nothing
before this file asserted either direction: flipping the three reads to
require_tenant_admin() left 83 tests passing, and opening the five writes to
get_current_user left 16 passing. Follows the non-admin-login pattern used in
test_admin.py / test_versions.py / test_criterion_role_authz.py — there is no
shared non-admin fixture in conftest.py.
"""
import pytest

from app.core.security import get_password_hash
from app.db.models.user import User
from tests.factories import ensure_user, ensure_user_group


async def _login_as(client, db_session, test_tenant, username, role):
    user = User(
        tenant_id=test_tenant.id,
        username=username,
        email=f"{username}@test.com",
        password_hash=get_password_hash("password123"),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "password123",
            "tenant_slug": test_tenant.slug,
        },
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_a_non_admin_can_read_all_three_gets(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Readable")
    member = await ensure_user(db_session, test_tenant.id, username="readable-member")
    await db_session.commit()
    added = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": member.id},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text

    headers = await _login_as(
        client, db_session, test_tenant, "groups-viewer", role="Viewer"
    )

    listed = await client.get("/api/v1/tenant/groups", headers=headers)
    assert listed.status_code == 200, listed.text

    detail = await client.get(f"/api/v1/tenant/groups/{group.id}", headers=headers)
    assert detail.status_code == 200, detail.text

    members = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members", headers=headers
    )
    assert members.status_code == 200, members.text
    assert [m["username"] for m in members.json()] == ["readable-member"]


@pytest.mark.asyncio
async def test_a_non_admin_cannot_perform_any_of_the_five_writes(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Guarded")
    member = await ensure_user(db_session, test_tenant.id, username="guarded-member")
    await db_session.commit()
    # Add the member as an Admin, so DELETE has a real membership row to
    # attempt to remove — a 403 must come from the auth check, not a 404
    # for a member that was never there.
    added = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": member.id},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text

    headers = await _login_as(
        client, db_session, test_tenant, "groups-developer", role="Developer"
    )

    created = await client.post(
        "/api/v1/tenant/groups", json={"name": "Nope"}, headers=headers
    )
    assert created.status_code == 403, created.text

    updated = await client.patch(
        f"/api/v1/tenant/groups/{group.id}",
        json={"name": "Renamed"},
        headers=headers,
    )
    assert updated.status_code == 403, updated.text

    another = await ensure_user(db_session, test_tenant.id, username="another-user")
    await db_session.commit()
    member_added = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": another.id},
        headers=headers,
    )
    assert member_added.status_code == 403, member_added.text

    member_removed = await client.delete(
        f"/api/v1/tenant/groups/{group.id}/members/{member.id}", headers=headers
    )
    assert member_removed.status_code == 403, member_removed.text

    deleted = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=headers
    )
    assert deleted.status_code == 403, deleted.text
