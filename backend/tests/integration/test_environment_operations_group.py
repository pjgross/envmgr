"""The operations group as seen from the environment side."""
import pytest

from tests.factories import ensure_user_group, post_environment


@pytest.mark.asyncio
async def test_environment_read_carries_the_group_name(
    client, auth_headers, db_session, test_tenant
):
    """The name travels with the row, like tier_name and owner_username.

    Resolving it in the browser against the groups collection is the failure
    the pagination sweep documented: a `.find()` miss renders '—', which is
    information lost rather than hidden.
    """
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()

    created = await post_environment(
        client, auth_headers, "ops-env", operations_group_id=group.id
    )
    assert created.status_code == 201, created.text
    assert created.json()["operations_group_id"] == group.id
    assert created.json()["operations_group_name"] == "Platform Ops"


@pytest.mark.asyncio
async def test_operations_group_is_optional_on_create(client, auth_headers):
    created = await post_environment(client, auth_headers, "no-ops-env")
    assert created.status_code == 201, created.text
    assert created.json()["operations_group_id"] is None
    assert created.json()["operations_group_name"] is None


@pytest.mark.asyncio
async def test_explicit_null_clears_the_group(
    client, auth_headers, db_session, test_tenant
):
    """`operations_group_id` is typed `int | null`, not optional: the backend
    keys on model_fields_set, so an omitted key means 'leave alone' and only an
    explicit null can clear the field. Same contract B1 gave expires_at."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()
    env_id = (
        await post_environment(
            client, auth_headers, "clearable", operations_group_id=group.id
        )
    ).json()["id"]

    untouched = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"description": "still owned by ops"},
        headers=auth_headers,
    )
    assert untouched.json()["operations_group_id"] == group.id

    cleared = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"operations_group_id": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["operations_group_id"] is None


@pytest.mark.asyncio
async def test_cannot_point_at_another_tenants_group(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """The FK-write gap this change adds. 404, not 403."""
    # The fixture yields a FACTORY, and the factory returns (tenant, user).
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    refused = await post_environment(
        client, auth_headers, "leaky", operations_group_id=theirs.id
    )
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == "User group not found"


@pytest.mark.asyncio
async def test_a_soft_deleted_group_still_renders_its_name(
    client, auth_headers, db_session, test_tenant
):
    """Blanking the field would make a populated control render empty while
    form state still holds the id — the MUI out-of-range warning B1 hit with
    retired tiers and deactivated owners."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Retired Ops")
    await db_session.commit()
    env_id = (
        await post_environment(
            client, auth_headers, "orphaned", operations_group_id=group.id
        )
    ).json()["id"]

    deleted = await client.delete(
        f"/api/v1/tenant/groups/{group.id}", headers=auth_headers
    )
    assert deleted.status_code == 409, "the environment should block the delete"

    # Soft-delete it directly, bypassing delete_group's own guard. This is NOT
    # the state a reassign-then-delete would leave: delete_group 409s while any
    # environment still references the group (as just proven above), and
    # reassigning first would point this environment at a *different* group,
    # leaving the old one unreferenced — and therefore deletable through the
    # normal endpoint. Reaching "an environment still points at a
    # soft-deleted group" requires going around delete_group entirely, the
    # way this test does.
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.db.models.user_group import UserGroup

    stored = (await db_session.execute(
        select(UserGroup).where(UserGroup.id == group.id)
    )).scalar_one()
    stored.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    read = await client.get(f"/api/v1/environments/{env_id}", headers=auth_headers)
    assert read.json()["operations_group_name"] == "Retired Ops"


@pytest.mark.asyncio
async def test_governance_gap_reports_a_missing_operations_group(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()
    await post_environment(client, auth_headers, "has-ops", operations_group_id=group.id)
    await post_environment(client, auth_headers, "no-ops")

    gaps = await client.get(
        "/api/v1/environments/?governance_gap=true", headers=auth_headers
    )
    assert gaps.status_code == 200, gaps.text
    names = [e["name"] for e in gaps.json()]
    assert "no-ops" in names
    assert "has-ops" not in names


@pytest.mark.asyncio
async def test_governance_gap_false_excludes_a_row_missing_only_the_group(
    client, auth_headers, db_session, test_tenant
):
    """The discriminating half `governance_gap=false` was missing: the only
    existing coverage gave every "clean" row both an owner and a group, so it
    passes identically whether the rule is "owner AND group" or "owner only".
    A row with an owner but no group must be absent from the clean set."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()

    await post_environment(client, auth_headers, "owner-no-group")
    await post_environment(
        client, auth_headers, "owner-and-group", operations_group_id=group.id
    )

    clean = await client.get(
        "/api/v1/environments/?governance_gap=false", headers=auth_headers
    )
    assert clean.status_code == 200, clean.text
    names = [e["name"] for e in clean.json()]
    assert "owner-and-group" in names
    assert "owner-no-group" not in names


@pytest.mark.asyncio
async def test_patching_to_another_tenants_group_is_refused(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """The PATCH twin of test_cannot_point_at_another_tenants_group.
    `update_environment` validates `operations_group_id` through the same
    helper `create_environment_record` uses, so create-then-patch — the path
    an attacker would actually use to probe another tenant's group ids — must
    404 too, not just POST."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    created = await post_environment(client, auth_headers, "patch-target")
    env_id = created.json()["id"]

    refused = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"operations_group_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == "User group not found"


@pytest.mark.asyncio
async def test_filtering_by_operations_group(
    client, auth_headers, db_session, test_tenant
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Platform Ops")
    await db_session.commit()
    await post_environment(client, auth_headers, "mine", operations_group_id=group.id)
    await post_environment(client, auth_headers, "theirs")

    filtered = await client.get(
        f"/api/v1/environments/?operations_group_id={group.id}", headers=auth_headers
    )
    assert [e["name"] for e in filtered.json()] == ["mine"]


@pytest.mark.asyncio
async def test_saving_an_unrelated_field_survives_a_soft_deleted_group(
    client, auth_headers, db_session, test_tenant
):
    """The reproduction: EnvironmentDetail's edit form always resends the
    whole form, including the group id unchanged. Before this fix that 404'd
    "User group not found" the instant a group was retired, even for an edit
    that has nothing to do with the group — the environment became
    unsaveable. Re-submitting the SAME (now soft-deleted) id must succeed,
    exactly like re-submitting a deactivated owner already does.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.db.models.user_group import UserGroup

    group = await ensure_user_group(db_session, test_tenant.id, name="Going Away")
    await db_session.commit()
    env_id = (
        await post_environment(
            client, auth_headers, "keeps-its-group", operations_group_id=group.id
        )
    ).json()["id"]

    stored = (
        await db_session.execute(select(UserGroup).where(UserGroup.id == group.id))
    ).scalar_one()
    stored.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    saved = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"description": "edited", "operations_group_id": group.id},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["description"] == "edited"
    assert saved.json()["operations_group_id"] == group.id


@pytest.mark.asyncio
async def test_reassigning_to_a_different_soft_deleted_group_still_404s(
    client, auth_headers, db_session, test_tenant
):
    """The other half: the "unchanged value" exemption must not swallow a
    genuinely new assignment. A second, unrelated soft-deleted group must
    still be refused — it is not what this environment already stores.
    `other` is never referenced by anything, so the normal DELETE endpoint
    soft-deletes it without needing to reach into the database directly."""
    original = await ensure_user_group(db_session, test_tenant.id, name="Original")
    other = await ensure_user_group(db_session, test_tenant.id, name="Other Retired")
    await db_session.commit()
    env_id = (
        await post_environment(
            client, auth_headers, "reassign-target", operations_group_id=original.id
        )
    ).json()["id"]

    removed = await client.delete(
        f"/api/v1/tenant/groups/{other.id}", headers=auth_headers
    )
    assert removed.status_code == 204, removed.text

    refused = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"operations_group_id": other.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text
    assert refused.json()["detail"] == "User group not found"
