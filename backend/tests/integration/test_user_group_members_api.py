"""Membership add/remove/list, including the two cross-tenant write paths."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_user, ensure_user_group


@pytest.mark.asyncio
async def test_add_list_and_remove_a_member(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    added = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": user.id},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    # The username travels with the row — the browser must not resolve it
    # against a separately-fetched, capped user collection.
    assert added.json()["username"] == "ada"

    listed = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert [m["username"] for m in listed.json()] == ["ada"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1

    removed = await client.delete(
        f"/api/v1/tenant/groups/{group.id}/members/{user.id}", headers=auth_headers
    )
    assert removed.status_code == 204, removed.text

    empty = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members", headers=auth_headers
    )
    assert empty.json() == []


@pytest.mark.asyncio
async def test_adding_the_same_member_twice_is_a_409(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    payload = {"user_id": user.id}
    first = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members", json=payload, headers=auth_headers
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members", json=payload, headers=auth_headers
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_cannot_add_a_user_from_another_tenant(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """The FK-write direction of tenant isolation — the class the 2026-07-16
    audit found four of. A cross-tenant id is a 404, never a 403: a 403 would
    confirm the user exists."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    # The fixture yields a FACTORY, and the factory returns (tenant, user).
    other_tenant, _other_admin = await second_tenant_factory()
    outsider = await ensure_user(db_session, other_tenant.id, username="outsider")
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": outsider.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_cannot_touch_a_group_from_another_tenant(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    other_group = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/tenant/groups/{other_group.id}/members",
        json={"user_id": user.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_removing_a_non_member_is_a_404(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    user = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    missing = await client.delete(
        f"/api/v1/tenant/groups/{group.id}/members/{user.id}", headers=auth_headers
    )
    assert missing.status_code == 404, missing.text


@pytest.mark.asyncio
async def test_a_master_admin_can_add_members_while_impersonating(
    client, db_session, test_tenant
):
    """Under impersonation `current_user.id` and `active_tenant_id` belong to
    different tenants.

    A validation scoped to the caller's *home* tenant 404s a legitimate
    request — the bug that made an owner check fail and, in B1, escaped a
    per-row handler and killed an entire spreadsheet upload. The group and the
    user here both live in the impersonated tenant and the acting admin does
    not, so a home-tenant lookup finds neither.
    """
    from app.core.security import create_access_token, get_password_hash
    from app.db.models.user import Tenant, User

    home = Tenant(name="System Org", slug="system-groups-imp")
    db_session.add(home)
    await db_session.flush()
    master = User(
        tenant_id=home.id, username="groups-masteradmin", email="gm@imp.com",
        password_hash=get_password_hash("x"), role="Admin", is_active=True,
        is_master_admin=True,
    )
    db_session.add(master)

    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    member = await ensure_user(db_session, test_tenant.id, username="ada")
    await db_session.commit()

    token = create_access_token({
        "sub": str(master.id),
        "tenant_id": home.id,
        "impersonating_tenant_id": test_tenant.id,
    })
    headers = {"Authorization": f"Bearer {token}"}

    added = await client.post(
        f"/api/v1/tenant/groups/{group.id}/members",
        json={"user_id": member.id},
        headers=headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["username"] == "ada"


@pytest.mark.asyncio
async def test_member_count_reflects_real_membership(
    client, auth_headers, db_session, test_tenant
):
    """Carried finding from Task 2's review: its tests only ever asserted
    member_count == 0, so the correlated subquery in list_groups /
    get_group_view was never proven to count anything. Prove it here."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    users = [
        await ensure_user(db_session, test_tenant.id, username=f"member-{i}")
        for i in range(3)
    ]
    await db_session.commit()

    for user in users:
        added = await client.post(
            f"/api/v1/tenant/groups/{group.id}/members",
            json={"user_id": user.id},
            headers=auth_headers,
        )
        assert added.status_code == 201, added.text

    detail = await client.get(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["member_count"] == 3

    listed = await client.get("/api/v1/tenant/groups", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(g for g in listed.json() if g["id"] == group.id)
    assert row["member_count"] == 3


@pytest.mark.asyncio
async def test_members_endpoint_bounds_the_page(
    client, auth_headers, db_session, test_tenant
):
    from app.core.pagination import MAX_LIMIT

    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    for i in range(3):
        user = await ensure_user(db_session, test_tenant.id, username=f"page-member-{i}")
        await db_session.commit()
        posted = await client.post(
            f"/api/v1/tenant/groups/{group.id}/members",
            json={"user_id": user.id},
            headers=auth_headers,
        )
        assert posted.status_code == 201, posted.text

    windowed = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members?limit=2", headers=auth_headers
    )
    assert windowed.status_code == 200, windowed.text
    assert len(windowed.json()) == 2
    assert int(windowed.headers[TOTAL_COUNT_HEADER]) == 3

    over = await client.get(
        f"/api/v1/tenant/groups/{group.id}/members?limit={MAX_LIMIT + 1}",
        headers=auth_headers,
    )
    assert over.status_code == 422
