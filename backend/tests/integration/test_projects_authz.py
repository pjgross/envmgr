"""Pins the deliberate read/write authorization split on projects.

`GET /api/v1/projects` and `GET /api/v1/projects/{id}` are readable by any
tenant member — every booking form needs the project picker; the three
writes — POST/PATCH/DELETE — require Admin (see app/api/v1/projects.py).
Nothing before this file asserted either direction: `auth_headers` is always
role Admin, so swapping `require_tenant_admin()` for `get_current_user` on
POST left all of test_projects_api.py passing, and nothing proved a non-admin
can read at all. Follows the pattern in test_user_group_authz.py — there is
no shared non-admin fixture in conftest.py.
"""
import pytest

from app.core.security import get_password_hash
from app.db.models.user import User
from tests.factories import ensure_environment, ensure_project, ensure_user_group


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
async def test_a_non_admin_can_read_the_list_and_a_single_project(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Readable Team")
    project = await ensure_project(db_session, test_tenant.id, name="Readable Project")
    project.team_group_id = group.id
    await db_session.commit()

    headers = await _login_as(
        client, db_session, test_tenant, "projects-viewer", role="Viewer"
    )

    listed = await client.get("/api/v1/projects", headers=headers)
    assert listed.status_code == 200, listed.text
    assert project.id in [p["id"] for p in listed.json()]

    detail = await client.get(f"/api/v1/projects/{project.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["name"] == "Readable Project"


@pytest.mark.asyncio
async def test_a_non_admin_cannot_perform_any_of_the_three_writes(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Guarded Project")
    await db_session.commit()

    headers = await _login_as(
        client, db_session, test_tenant, "projects-developer", role="Developer"
    )

    created = await client.post(
        "/api/v1/projects", json={"name": "Nope"}, headers=headers
    )
    assert created.status_code == 403, created.text

    updated = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"description": "should not land"},
        headers=headers,
    )
    assert updated.status_code == 403, updated.text

    deleted = await client.delete(
        f"/api/v1/projects/{project.id}", headers=headers
    )
    assert deleted.status_code == 403, deleted.text


# ── Finding 3: the same read/write split, for the usage-agreement routes ────
#
# `GET .../usage-agreements` (both directions) is readable by any tenant
# member; `POST`/`DELETE .../usage-agreements` require Admin. Nothing before
# this proved either direction: swapping require_tenant_admin() for
# get_current_user on the create route left every test in
# test_usage_agreements_api.py passing, because auth_headers is always Admin.


@pytest.mark.asyncio
async def test_a_non_admin_can_read_usage_agreements_from_both_directions(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Readable Agreement")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    headers = await _login_as(
        client, db_session, test_tenant, "agreements-viewer", role="Viewer"
    )

    by_project = await client.get(
        f"/api/v1/projects/{project.id}/usage-agreements", headers=headers
    )
    assert by_project.status_code == 200, by_project.text
    assert [a["environment_name"] for a in by_project.json()] == [env.name]

    by_env = await client.get(
        f"/api/v1/environments/{env.id}/usage-agreements", headers=headers
    )
    assert by_env.status_code == 200, by_env.text
    assert [a["project_name"] for a in by_env.json()] == ["Readable Agreement"]


@pytest.mark.asyncio
async def test_a_non_admin_cannot_create_or_delete_a_usage_agreement(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Guarded Agreement")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    existing = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert existing.status_code == 201, existing.text
    agreement_id = existing.json()["id"]

    headers = await _login_as(
        client, db_session, test_tenant, "agreements-developer", role="Developer"
    )

    created = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id, "notes": "should not land"},
        headers=headers,
    )
    assert created.status_code == 403, created.text

    deleted = await client.delete(
        f"/api/v1/projects/{project.id}/usage-agreements/{agreement_id}",
        headers=headers,
    )
    assert deleted.status_code == 403, deleted.text

    # Refused, not silently accepted: the original agreement is still there.
    still_listed = await client.get(
        f"/api/v1/projects/{project.id}/usage-agreements", headers=auth_headers
    )
    assert [a["id"] for a in still_listed.json()] == [agreement_id]
