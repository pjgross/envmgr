"""Pins the deliberate read/write authorization split on environment groups.

`GET /api/v1/environment-groups` and `GET /api/v1/environment-groups/{id}` are
readable by any tenant member — every booking form needs the group picker;
the three writes — POST/PATCH/DELETE — require Admin (see
app/api/v1/environment_groups.py).

Nothing before this file asserted either direction: `auth_headers` is always
role Admin, so swapping `require_tenant_admin()` for `get_current_user` on
POST would leave test_environment_groups_api.py entirely green, and nothing
would prove a non-admin can read at all. B3a shipped its group routes
over-gated on a false analogy to `/tenant/users` and it took a review to
catch — this is that review, in test form. Follows the pattern in
test_projects_authz.py.
"""
import pytest

from app.core.security import get_password_hash
from app.db.models.user import User
from tests.factories import ensure_environment, ensure_environment_group


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
async def test_a_non_admin_can_read_the_list_and_a_single_group(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_environment_group(
        db_session, test_tenant.id, name="Readable Group"
    )
    await db_session.commit()

    headers = await _login_as(
        client, db_session, test_tenant, "env-groups-viewer", role="Viewer"
    )

    listed = await client.get("/api/v1/environment-groups", headers=headers)
    assert listed.status_code == 200, listed.text
    assert group.id in [g["id"] for g in listed.json()]

    detail = await client.get(
        f"/api/v1/environment-groups/{group.id}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["name"] == "Readable Group"


@pytest.mark.asyncio
async def test_a_non_admin_cannot_perform_any_of_the_three_writes(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_environment_group(
        db_session, test_tenant.id, name="Guarded Group"
    )
    await db_session.commit()

    headers = await _login_as(
        client, db_session, test_tenant, "env-groups-developer", role="Developer"
    )

    created = await client.post(
        "/api/v1/environment-groups", json={"name": "Nope"}, headers=headers
    )
    assert created.status_code == 403, created.text

    updated = await client.patch(
        f"/api/v1/environment-groups/{group.id}",
        json={"description": "should not land"},
        headers=headers,
    )
    assert updated.status_code == 403, updated.text

    deleted = await client.delete(
        f"/api/v1/environment-groups/{group.id}", headers=headers
    )
    assert deleted.status_code == 403, deleted.text

    # Refused, not silently accepted: the group is still there and unchanged.
    still_listed = await client.get(
        "/api/v1/environment-groups", headers=auth_headers
    )
    assert "Guarded Group" in [g["name"] for g in still_listed.json()]


@pytest.mark.asyncio
async def test_a_non_admin_can_read_membership_from_both_directions(
    client, auth_headers, db_session, test_tenant
):
    """The three member routes get the same read/write split as the CRUD
    routes above: reads open to any tenant member, writes Admin."""
    group = await ensure_environment_group(
        db_session, test_tenant.id, name="Readable Members"
    )
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    added = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text

    headers = await _login_as(
        client, db_session, test_tenant, "env-groups-member-viewer", role="Viewer"
    )

    by_group = await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=headers
    )
    assert by_group.status_code == 200, by_group.text
    assert [m["environment_name"] for m in by_group.json()] == [env.name]

    by_env = await client.get(
        f"/api/v1/environments/{env.id}/groups", headers=headers
    )
    assert by_env.status_code == 200, by_env.text
    assert [m["group_name"] for m in by_env.json()] == ["Readable Members"]


@pytest.mark.asyncio
async def test_a_non_admin_cannot_add_or_remove_a_member(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_environment_group(
        db_session, test_tenant.id, name="Guarded Members"
    )
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    headers = await _login_as(
        client, db_session, test_tenant, "env-groups-member-developer", role="Developer"
    )

    added = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=headers,
    )
    assert added.status_code == 403, added.text

    # Add the member as Admin so there is something to try to remove.
    created = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    member_id = created.json()["id"]

    removed = await client.delete(
        f"/api/v1/environment-groups/{group.id}/members/{member_id}",
        headers=headers,
    )
    assert removed.status_code == 403, removed.text

    # Refused, not silently accepted: the member is still there and live.
    still_listed = await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=auth_headers
    )
    assert [m["environment_name"] for m in still_listed.json()] == [env.name]
