"""Group membership, read from both directions."""
import pytest
from sqlalchemy import select

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER
from app.db.models.environment_group import EnvironmentGroup, EnvironmentGroupMember
from app.services import environment_group_service
from tests.factories import ensure_environment, ensure_environment_group


@pytest.mark.asyncio
async def test_adding_a_member_returns_201_with_the_environment_name(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    created = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    # The environment's name travels with the row — never resolved in the
    # browser against a separately-fetched, capped collection.
    assert created.json()["environment_name"] == env.name
    assert created.json()["group_name"] == "Pair"
    assert created.json()["group_id"] == group.id
    assert created.json()["environment_id"] == env.id


@pytest.mark.asyncio
async def test_member_is_listed_from_both_directions_bounded_with_total_count(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    added = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text

    by_group = await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=auth_headers
    )
    assert by_group.status_code == 200, by_group.text
    assert [m["environment_name"] for m in by_group.json()] == [env.name]
    assert int(by_group.headers[TOTAL_COUNT_HEADER]) == 1

    by_env = await client.get(
        f"/api/v1/environments/{env.id}/groups", headers=auth_headers
    )
    assert by_env.status_code == 200, by_env.text
    assert [m["group_name"] for m in by_env.json()] == ["Pair"]
    assert int(by_env.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_both_list_endpoints_are_bounded(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    for url in (
        f"/api/v1/environment-groups/{group.id}/members",
        f"/api/v1/environments/{env.id}/groups",
    ):
        ok = await client.get(url, headers=auth_headers)
        assert ok.status_code == 200, ok.text
        assert TOTAL_COUNT_HEADER in ok.headers
        over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
        assert over.status_code == 422, over.text


@pytest.mark.asyncio
async def test_adding_another_tenants_environment_is_404(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id, slot=1)
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_adding_to_another_tenants_group_is_404(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs_group = await ensure_environment_group(
        db_session, other_tenant.id, name="Theirs"
    )
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/environment-groups/{theirs_group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_adding_the_same_environment_twice_is_409_naming_it(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text

    again = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert again.status_code == 409, again.text
    assert env.name in again.json()["detail"]


@pytest.mark.asyncio
async def test_re_adding_a_removed_environment_produces_one_live_member_not_two(
    client, auth_headers, db_session, test_tenant
):
    """The case a naive uniqueness check gets wrong: `add_member` must refuse
    only a LIVE duplicate, and after a removal + re-add there must be exactly
    one live row for (group, environment) — not two, and not zero."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    member_id = first.json()["id"]

    removed = await client.delete(
        f"/api/v1/environment-groups/{group.id}/members/{member_id}",
        headers=auth_headers,
    )
    assert removed.status_code == 204, removed.text

    re_added = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert re_added.status_code == 201, re_added.text

    listed = await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=auth_headers
    )
    assert [m["environment_name"] for m in listed.json()] == [env.name]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1

    live_rows = (
        await db_session.execute(
            select(EnvironmentGroupMember).where(
                EnvironmentGroupMember.group_id == group.id,
                EnvironmentGroupMember.environment_id == env.id,
                EnvironmentGroupMember.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(live_rows) == 1, "re-adding must produce exactly one live member"


@pytest.mark.asyncio
async def test_removing_a_member_is_a_soft_delete(
    client, auth_headers, db_session, test_tenant
):
    """A 204 and absence from the list are both equally true of a hard delete
    — the row itself must still exist, with deleted_at set."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    created = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    member_id = created.json()["id"]

    removed = await client.delete(
        f"/api/v1/environment-groups/{group.id}/members/{member_id}",
        headers=auth_headers,
    )
    assert removed.status_code == 204, removed.text

    listed = (await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=auth_headers
    )).json()
    assert listed == []

    row = (
        await db_session.execute(
            select(EnvironmentGroupMember).where(EnvironmentGroupMember.id == member_id)
        )
    ).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is not None, "must be soft, not hard"


@pytest.mark.asyncio
async def test_listing_groups_for_another_tenants_environment_is_404_not_empty_list(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """A1 shipped exactly this gap: 200 + [] instead of 404."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id, slot=1)
    await db_session.commit()

    refused = await client.get(
        f"/api/v1/environments/{theirs.id}/groups", headers=auth_headers
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_soft_deleted_group_membership_no_longer_appears_from_environment_side(
    client, auth_headers, db_session, test_tenant
):
    """Task 2's delete_group cascade soft-deletes membership rows; dropping
    that cascade must fail THIS test."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Doomed")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    created = await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    deleted = await client.delete(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text

    by_env = await client.get(
        f"/api/v1/environments/{env.id}/groups", headers=auth_headers
    )
    assert by_env.status_code == 200, by_env.text
    assert by_env.json() == []


# ── member_count agreement (brief's explicit ask) ───────────────────────────


@pytest.mark.asyncio
async def test_member_count_equals_the_number_of_rows_list_members_returns(
    client, auth_headers, db_session, test_tenant
):
    """_member_count_clause and list_members must agree — on A1 a count and a
    list were written three tasks apart and disagreed two ways, with zero
    coverage. Cover both the base case and after an environment is
    soft-deleted (the count's Environment join must match the list's)."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Trio")
    one = await ensure_environment(db_session, test_tenant.id, slot=1)
    two = await ensure_environment(db_session, test_tenant.id, slot=2)
    three = await ensure_environment(db_session, test_tenant.id, slot=3)
    await db_session.commit()

    for env in (one, two, three):
        added = await client.post(
            f"/api/v1/environment-groups/{group.id}/members",
            json={"environment_id": env.id},
            headers=auth_headers,
        )
        assert added.status_code == 201, added.text

    got = await client.get(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    listed = await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=auth_headers
    )
    assert got.json()["member_count"] == len(listed.json()) == 3

    # Now soft-delete one environment directly and confirm the count and the
    # list both drop it — via the SAME test-observable state.
    from datetime import datetime, timezone

    two.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    got_after = await client.get(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    listed_after = await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=auth_headers
    )
    assert got_after.json()["member_count"] == len(listed_after.json()) == 2
    assert two.name not in [m["environment_name"] for m in listed_after.json()]


# ── Defence in depth: a malformed row must not surface another tenant's name ──
# (same pattern as test_usage_agreements_api.py's _agreement_query tests)


@pytest.mark.asyncio
async def test_group_side_listing_ignores_a_malformed_cross_tenant_environment_row(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Guards _member_query's Environment join tenant filter.

    A malformed row — tenant_id is ours, but environment_id points at another
    tenant's environment — must not leak that environment's name into this
    tenant's group-side listing.
    """
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id, slot=1)
    await db_session.commit()

    db_session.add(EnvironmentGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, environment_id=theirs.id,
    ))
    await db_session.commit()

    listed = await client.get(
        f"/api/v1/environment-groups/{group.id}/members", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert theirs.name not in [m["environment_name"] for m in listed.json()]


@pytest.mark.asyncio
async def test_environment_side_listing_ignores_a_malformed_cross_tenant_group_row(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Guards _member_query's EnvironmentGroup join tenant filter.

    A malformed row — tenant_id is ours, but group_id points at another
    tenant's group — must not leak that group's name into this tenant's
    environment-side listing.
    """
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    other_tenant, _other_admin = await second_tenant_factory()
    theirs_group = await ensure_environment_group(
        db_session, other_tenant.id, name="Their Group"
    )
    await db_session.commit()

    db_session.add(EnvironmentGroupMember(
        tenant_id=test_tenant.id, group_id=theirs_group.id, environment_id=env.id,
    ))
    await db_session.commit()

    listed = await client.get(
        f"/api/v1/environments/{env.id}/groups", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert "Their Group" not in [m["group_name"] for m in listed.json()]


@pytest.mark.asyncio
async def test_cannot_remove_a_member_whose_own_tenant_id_is_not_ours(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Guards remove_member's own tenant_id filter, independent of
    get_group's — a malformed row whose group_id legitimately belongs to our
    group but whose tenant_id column does not match must still 404, not be
    silently soft-deleted."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Pair")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    other_tenant, _other_admin = await second_tenant_factory()
    await db_session.commit()

    member = EnvironmentGroupMember(
        tenant_id=other_tenant.id, group_id=group.id, environment_id=env.id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)

    refused = await client.delete(
        f"/api/v1/environment-groups/{group.id}/members/{member.id}",
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text

    row = (
        await db_session.execute(
            select(EnvironmentGroupMember).where(EnvironmentGroupMember.id == member.id)
        )
    ).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is None, "must not be deleted by another tenant's admin"


@pytest.mark.asyncio
async def test_environment_side_listing_ignores_a_membership_whose_group_predates_the_cascade(
    db_session, test_tenant
):
    """Isolates _member_query's own EnvironmentGroup.deleted_at join filter
    from delete_group's cascade: the group here is soft-deleted directly
    (bypassing delete_group), so the membership row's OWN deleted_at is still
    null — only the join filter can hide it from the environment side. This
    is exactly what a row created before the cascade shipped looks like, and
    it is also the only thing that would catch dropping deleted_at from the
    join without touching the cascade at all."""
    from datetime import datetime, timezone

    group = await ensure_environment_group(db_session, test_tenant.id, name="Predates Cascade")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.flush()

    member = EnvironmentGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id,
    )
    db_session.add(member)
    await db_session.flush()

    group.deleted_at = datetime.now(timezone.utc)  # bypass delete_group's cascade
    await db_session.commit()

    rows, total = await environment_group_service.list_groups_for_environment(
        db_session, env.id, test_tenant.id,
    )
    assert total == 0
    assert member.id not in [r[0].id for r in rows]


# ── Pagination tiebreaker over ties ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_paging_over_tied_environment_names_sees_each_member_once(
    db_session, test_tenant
):
    """Every member here points at DIFFERENT environments but the leading sort
    key for list_groups_for_environment ties across all rows because they all
    point at the SAME group name. Without the EnvironmentGroupMember.id
    tiebreaker, LIMIT/OFFSET over an incomplete order can return a row on more
    than one page and drop another entirely."""
    from app.core.pagination import Page

    group = await ensure_environment_group(db_session, test_tenant.id, name="Big Group")
    await db_session.flush()

    total_rows = 21
    envs = []
    for slot in range(1, total_rows + 1):
        env = await ensure_environment(db_session, test_tenant.id, slot=slot)
        envs.append(env)
    await db_session.flush()

    for env in envs:
        db_session.add(EnvironmentGroupMember(
            tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id,
        ))
    await db_session.flush()

    seen: list[int] = []
    page_size = 5
    offset = 0
    while True:
        rows, total = await environment_group_service.list_members(
            db_session, group.id, test_tenant.id,
            page=Page(limit=page_size, offset=offset),
        )
        assert total == total_rows
        if not rows:
            break
        seen.extend(member.id for member, _group_name, _env_name in rows)
        offset += page_size

    assert len(seen) == total_rows, f"expected {total_rows} rows, saw {len(seen)}"
    assert len(set(seen)) == total_rows, "a row was returned on more than one page"
