"""Group CRUD. Membership has its own file; environment wiring has another."""
import pytest
from sqlalchemy import select

from app.core.pagination import TOTAL_COUNT_HEADER
from app.db.models.user_group import UserGroup
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
    group_id = group.id

    gone = await client.delete(
        f"/api/v1/tenant/groups/{group_id}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text

    listed = (await client.get("/api/v1/tenant/groups", headers=auth_headers)).json()
    assert "Free" not in [g["name"] for g in listed]

    # A 204 and absence from the list would pass identically for a hard
    # delete. Query the row directly: it must still exist, with deleted_at
    # set — environment.operations_group_id (and B3b's request history)
    # keep pointing at retired groups, so a hard delete would break those FKs.
    row = (
        await db_session.execute(
            select(UserGroup)
            .where(UserGroup.id == group_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    assert row is not None
    assert row.deleted_at is not None


@pytest.mark.asyncio
async def test_delete_blocked_message_reports_the_true_remainder(
    client, auth_headers, db_session, test_tenant
):
    """15 blocking environments — more than the 10-name cap.

    The old implementation capped the *query* at 11 rows and derived the
    remainder from `len(blockers) - 10`, so it could never report more than
    1 no matter how many environments actually blocked the delete. The true
    remainder here is 5.
    """
    group = await ensure_user_group(db_session, test_tenant.id, name="Overbooked")
    for slot in range(1, 16):
        env = await ensure_environment(db_session, test_tenant.id, slot=slot)
        env.operations_group_id = group.id
    await db_session.commit()

    refused = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert "and 5 more" in detail, detail
    assert detail.count("test-env-") == 10


@pytest.mark.asyncio
async def test_patch_explicit_null_clears_the_description(
    client, auth_headers, db_session, test_tenant
):
    """`if data.description is not None` could not tell an explicit null apart
    from an omitted key, so a client-emptied description silently reverted to
    its old value after a 200. Same contract environment_service gives
    expires_at/operations_group_id: the service keys on model_fields_set."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Described")
    group.description = "before"
    await db_session.commit()

    cleared = await client.patch(
        f"/api/v1/tenant/groups/{group.id}",
        json={"description": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["description"] is None


@pytest.mark.asyncio
async def test_patch_omitting_description_leaves_it_alone(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Untouched")
    group.description = "keep me"
    await db_session.commit()

    unchanged = await client.patch(
        f"/api/v1/tenant/groups/{group.id}",
        json={"name": "Untouched"},
        headers=auth_headers,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["description"] == "keep me"


@pytest.mark.asyncio
async def test_patch_explicit_null_name_is_a_422(client, auth_headers, db_session, test_tenant):
    """`name` is NOT NULL with min_length=1 — unlike description, an explicit
    null must never reach the service as a way to clear it."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Named")
    await db_session.commit()

    refused = await client.patch(
        f"/api/v1/tenant/groups/{group.id}",
        json={"name": None},
        headers=auth_headers,
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get(
        "/api/v1/tenant/groups?sort_by=nonsense", headers=auth_headers
    )
    assert bad.status_code == 422
