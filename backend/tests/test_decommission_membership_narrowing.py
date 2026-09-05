"""Optional group-membership narrowing on `environment_decommission_service.
worklist_query` — the decommissions half of `/my-work`'s "needing action"
queue. NO Admin bypass: `test_an_admin_is_narrowed_too` pins the design
decision recorded on `environment_request_service.actionable_clause` — the
group bypass exists so a transition is never impossible, not to decide whose
personal queue a row belongs in.
"""
import pytest
from datetime import datetime, timezone

from tests.factories import (
    add_group_member,
    ensure_environment,
    ensure_user,
    ensure_user_group,
    make_decommission,
)


@pytest.mark.asyncio
async def test_narrowing_returns_only_environments_whose_ops_group_i_am_in(
    db_session, test_tenant, test_user
):
    """Build the fixtures with this repo's factories; do NOT point a row at an
    id you did not create (SQLite ignored FKs until PRAGMA foreign_keys=ON and
    ~40 tests were inserting broken rows)."""
    me = await ensure_user(db_session, test_tenant.id, username='queue-member')
    mine_group = await ensure_user_group(db_session, test_tenant.id, name='Mine')
    await add_group_member(db_session, mine_group, me)
    theirs_group = await ensure_user_group(db_session, test_tenant.id, name='Theirs')

    mine_env = await ensure_environment(
        db_session, test_tenant.id, slot=1, operations_group_id=mine_group.id
    )
    theirs_env = await ensure_environment(
        db_session, test_tenant.id, slot=2, operations_group_id=theirs_group.id
    )
    orphan_env = await ensure_environment(
        db_session, test_tenant.id, slot=3, operations_group_id=None
    )

    mine = await make_decommission(
        db_session, test_tenant.id, environment_id=mine_env.id
    )
    theirs = await make_decommission(
        db_session, test_tenant.id, environment_id=theirs_env.id
    )
    orphan = await make_decommission(
        db_session, test_tenant.id, environment_id=orphan_env.id
    )

    now = datetime.now(timezone.utc)
    from app.services import environment_decommission_service as svc

    q = svc.worklist_query(test_tenant.id, now=now, member_user_id=me.id)
    ids = {row.id for row in (await db_session.execute(q)).scalars()}
    assert mine.id in ids
    assert theirs.id not in ids
    assert orphan.id not in ids, (
        "an environment with NO operations group is nobody's queue — it must "
        "not fall through into everyone's"
    )


@pytest.mark.asyncio
async def test_without_the_parameter_nothing_changes(
    db_session, test_tenant
):
    """`/decommissions` is the estate-wide worklist and must be unaffected."""
    env = await ensure_environment(
        db_session, test_tenant.id, slot=1, operations_group_id=None
    )
    d = await make_decommission(db_session, test_tenant.id, environment_id=env.id)
    now = datetime.now(timezone.utc)
    from app.services import environment_decommission_service as svc

    q = svc.worklist_query(test_tenant.id, now=now)
    assert d.id in {row.id for row in (await db_session.execute(q)).scalars()}


@pytest.mark.asyncio
async def test_an_admin_is_narrowed_too(
    db_session, test_tenant, test_user
):
    """§5's "(Admin: all)" was struck. /my-work is a PERSONAL queue and follows
    `environment_request_service.actionable_clause`'s recorded reasoning: the
    Admin group-bypass exists so a transition is never impossible, and is not a
    claim about whose queue a row belongs in. An Admin in no group sees none.
    """
    admin = await ensure_user(
        db_session, test_tenant.id, username='queue-admin', role='Admin'
    )
    other_group = await ensure_user_group(db_session, test_tenant.id, name='Other')
    env = await ensure_environment(
        db_session, test_tenant.id, slot=1, operations_group_id=other_group.id
    )
    await make_decommission(db_session, test_tenant.id, environment_id=env.id)

    now = datetime.now(timezone.utc)
    from app.services import environment_decommission_service as svc

    q = svc.worklist_query(test_tenant.id, now=now, member_user_id=admin.id)
    assert (await db_session.execute(q)).scalars().all() == []
