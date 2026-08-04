"""Group CRUD. Membership has its own file; environment wiring has another."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_environment, ensure_user_group


@pytest.mark.asyncio
async def test_create_and_list_a_group(client, auth_headers):
    created = await client.post(
        "/api/v1/tenant/groups",
        json={"name": "Platform Ops", "description": "Runs the SIT estate"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Platform Ops"

    listed = await client.get("/api/v1/tenant/groups", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [g["name"] for g in listed.json()] == ["Platform Ops"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_duplicate_name_is_a_409_naming_the_conflict(client, auth_headers):
    await client.post(
        "/api/v1/tenant/groups", json={"name": "Platform Ops"}, headers=auth_headers
    )
    again = await client.post(
        "/api/v1/tenant/groups", json={"name": "platform ops"}, headers=auth_headers
    )
    assert again.status_code == 409, again.text
    # Case-insensitive, like the tier vocabulary — "Platform Ops" and
    # "platform ops" are the same team to a human.
    assert "already exists" in again.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_carries_the_counts_the_grid_shows(
    client, auth_headers, db_session, test_tenant
):
    """member_count and environment_count travel with the row.

    Resolving them in the browser against a separately-fetched collection is
    the failure the pagination sweep documented — a capped collection makes a
    count silently wrong rather than absent.
    """
    group = await ensure_user_group(db_session, test_tenant.id, name="Counted")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()

    body = (await client.get("/api/v1/tenant/groups", headers=auth_headers)).json()
    row = next(g for g in body if g["name"] == "Counted")
    assert row["member_count"] == 0
    assert row["environment_count"] == 1


@pytest.mark.asyncio
async def test_detail_does_not_embed_the_member_list(
    client, auth_headers, db_session, test_tenant
):
    """An embedded list would be an unbounded nested collection — the exact
    shape `GET /releases/{id}/membership` had to have bounded after the fact."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Detail")
    await db_session.commit()

    body = (await client.get(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )).json()
    assert "members" not in body
    assert body["member_count"] == 0


@pytest.mark.asyncio
async def test_delete_names_the_environments_that_block_it(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Busy")
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()

    refused = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert refused.status_code == 409, refused.text
    # The whole value of this response is *which* environments block it.
    assert env.name in refused.json()["detail"]


@pytest.mark.asyncio
async def test_delete_soft_deletes_when_nothing_references_it(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Free")
    await db_session.commit()

    gone = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text

    listed = (await client.get("/api/v1/tenant/groups", headers=auth_headers)).json()
    assert "Free" not in [g["name"] for g in listed]


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get(
        "/api/v1/tenant/groups?sort_by=nonsense", headers=auth_headers
    )
    assert bad.status_code == 422
