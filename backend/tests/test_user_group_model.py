"""The two tables B3a adds, and the column that points at one of them."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.user_group import UserGroup, UserGroupMember
from tests.factories import ensure_environment, ensure_user, ensure_user_group


@pytest.mark.asyncio
async def test_group_persists_with_its_tenant(db_session, test_tenant):
    group = UserGroup(tenant_id=test_tenant.id, name="Platform Ops")
    db_session.add(group)
    await db_session.flush()

    assert group.id is not None
    assert group.deleted_at is None
    assert group.description is None


@pytest.mark.asyncio
async def test_a_user_cannot_join_the_same_group_twice(db_session, test_tenant):
    """UNIQUE(group_id, user_id) — the add-member endpoint relies on it."""
    group = await ensure_user_group(db_session, test_tenant.id)
    user = await ensure_user(db_session, test_tenant.id, username="member-a")

    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=user.id
    ))
    await db_session.flush()

    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=user.id
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_environment_can_name_its_operations_group(db_session, test_tenant):
    group = await ensure_user_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)

    env.operations_group_id = group.id
    await db_session.flush()

    stored = (await db_session.execute(
        select(UserGroup.id).where(UserGroup.id == env.operations_group_id)
    )).scalar_one()
    assert stored == group.id


@pytest.mark.asyncio
async def test_operations_group_is_nullable(db_session, test_tenant):
    """Legacy rows keep a null rather than a fabricated group — see the spec."""
    env = await ensure_environment(db_session, test_tenant.id, slot=2)
    assert env.operations_group_id is None
