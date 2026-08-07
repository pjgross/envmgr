"""Environment group CRUD. Membership has its own file."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_environment, ensure_environment_group


@pytest.mark.asyncio
async def test_create_and_list_a_group(client, auth_headers):
    created = await client.post(
        "/api/v1/environment-groups",
        json={"name": "Mortgage SIT + Customer SIT", "description": "End-to-end pair"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Mortgage SIT + Customer SIT"
    assert created.json()["is_active"] is True
    assert created.json()["member_count"] == 0

    listed = await client.get("/api/v1/environment-groups", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [g["name"] for g in listed.json()] == ["Mortgage SIT + Customer SIT"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_duplicate_name_is_a_409_naming_the_conflict(client, auth_headers):
    await client.post(
        "/api/v1/environment-groups", json={"name": "Mortgage SIT"}, headers=auth_headers
    )
    again = await client.post(
        "/api/v1/environment-groups", json={"name": "mortgage sit"}, headers=auth_headers
    )
    assert again.status_code == 409, again.text
    assert "already exists" in again.json()["detail"].lower()


@pytest.mark.asyncio
async def test_name_uniqueness_is_scoped_per_tenant(
    client, auth_headers, db_session, second_tenant_factory
):
    """Two tenants may each have a group called the same thing. If this filter
    were dropped, tenant B's create would 409 against tenant A's row — which
    also leaks the existence of A's group through the error message."""
    other_tenant, _other_admin = await second_tenant_factory()
    await ensure_environment_group(db_session, other_tenant.id, name="Shared Name")
    await db_session.commit()

    mine = await client.post(
        "/api/v1/environment-groups", json={"name": "Shared Name"}, headers=auth_headers
    )
    assert mine.status_code == 201, mine.text


@pytest.mark.asyncio
async def test_member_count_travels_with_the_row(
    client, auth_headers, db_session, test_tenant
):
    """Counting in the browser against a separately-fetched members list is
    the `.find()`/`.length` failure docs/pagination.md documents — that list
    is capped, so the number would simply be wrong."""
    from app.db.models.environment_group import EnvironmentGroupMember

    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    one = await ensure_environment(db_session, test_tenant.id, slot=1)
    two = await ensure_environment(db_session, test_tenant.id, slot=2)
    for env in (one, two):
        db_session.add(EnvironmentGroupMember(
            tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id
        ))
    await db_session.commit()

    got = await client.get(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert got.status_code == 200, got.text
    assert got.json()["member_count"] == 2


@pytest.mark.asyncio
async def test_another_tenants_group_is_invisible_and_unreachable(
    client, auth_headers, db_session, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    listed = await client.get("/api/v1/environment-groups", headers=auth_headers)
    assert "Theirs" not in [g["name"] for g in listed.json()]

    # 404, never 403 — a 403 confirms the row exists in another tenant.
    got = await client.get(
        f"/api/v1/environment-groups/{theirs.id}", headers=auth_headers
    )
    assert got.status_code == 404, got.text


@pytest.mark.asyncio
async def test_another_tenants_group_cannot_be_updated_or_deleted(
    client, auth_headers, db_session, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    patched = await client.patch(
        f"/api/v1/environment-groups/{theirs.id}",
        json={"name": "Hijacked"}, headers=auth_headers,
    )
    assert patched.status_code == 404, patched.text

    deleted = await client.delete(
        f"/api/v1/environment-groups/{theirs.id}", headers=auth_headers
    )
    assert deleted.status_code == 404, deleted.text


@pytest.mark.asyncio
async def test_delete_is_a_soft_delete_and_is_never_refused(
    client, auth_headers, db_session, test_tenant
):
    """Deliberately unlike user_group_service.delete_group, which 409s while
    anything references it. A group accumulates every booking ever made
    against it, so a reference check would make it permanently undeletable."""
    from sqlalchemy import select
    from app.db.models.environment_group import EnvironmentGroup

    group = await ensure_environment_group(db_session, test_tenant.id, name="Old")
    await db_session.commit()

    gone = await client.delete(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text

    row = (await db_session.execute(
        select(EnvironmentGroup).where(EnvironmentGroup.id == group.id)
    )).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is not None, "must be soft, not hard"

    listed = (await client.get(
        "/api/v1/environment-groups", headers=auth_headers
    )).json()
    assert "Old" not in [g["name"] for g in listed]


@pytest.mark.asyncio
async def test_delete_cascade_does_not_touch_another_tenants_membership_row(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Defense in depth: the membership cascade inside delete_group filters
    on tenant_id as well as group_id, even though a group_id should only ever
    be referenced by rows in its own tenant. This proves the filter actually
    does something by manufacturing the one case where group_id alone is not
    enough — a malformed row whose tenant_id disagrees with its group's."""
    from app.db.models.environment_group import EnvironmentGroupMember

    other_tenant, _other_admin = await second_tenant_factory()
    group = await ensure_environment_group(db_session, test_tenant.id, name="Ours")
    other_env = await ensure_environment(db_session, other_tenant.id, slot=1)
    phantom = EnvironmentGroupMember(
        tenant_id=other_tenant.id, group_id=group.id, environment_id=other_env.id
    )
    db_session.add(phantom)
    await db_session.commit()

    deleted = await client.delete(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text

    await db_session.refresh(phantom)
    assert phantom.deleted_at is None, (
        "the cascade must be tenant-scoped, not group_id-scoped alone"
    )


@pytest.mark.asyncio
async def test_search_and_is_active_filter_in_sql(client, auth_headers):
    for name, active in (("Mortgage SIT", True), ("Savings SIT", True), ("Old Pair", False)):
        made = await client.post(
            "/api/v1/environment-groups",
            json={"name": name, "is_active": active}, headers=auth_headers,
        )
        assert made.status_code == 201, made.text

    found = await client.get(
        "/api/v1/environment-groups?search=mortgage", headers=auth_headers
    )
    assert [g["name"] for g in found.json()] == ["Mortgage SIT"]
    # A Python-side filter would window the page BEFORE filtering, so the
    # total must describe the filtered set, not the whole one.
    assert int(found.headers[TOTAL_COUNT_HEADER]) == 1

    active_only = await client.get(
        "/api/v1/environment-groups?is_active=true", headers=auth_headers
    )
    assert "Old Pair" not in [g["name"] for g in active_only.json()]
    assert int(active_only.headers[TOTAL_COUNT_HEADER]) == 2


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get(
        "/api/v1/environment-groups?sort_by=nonsense", headers=auth_headers
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_listing_folds_case_rather_than_collating_by_byte(client, auth_headers):
    """Both engines here collate by BYTE VALUE — SQLite's default is BINARY,
    and postgres:15-alpine runs musl libc, which implements no locales. So
    'a' < 'B' is false unless the query folds case explicitly."""
    for name in ("beta pair", "Alpha Pair", "Gamma Pair"):
        await client.post(
            "/api/v1/environment-groups", json={"name": name}, headers=auth_headers
        )

    listed = await client.get("/api/v1/environment-groups", headers=auth_headers)
    assert [g["name"] for g in listed.json()] == [
        "Alpha Pair", "beta pair", "Gamma Pair",
    ]
