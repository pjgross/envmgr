import pytest
from sqlalchemy import select

from app.db.models.rollback import RollbackPolicy
from app.services.rollback_policy_service import get_or_create_policy


@pytest.fixture
async def other_tenant(second_tenant_factory):
    """A second tenant, built locally per the precedent in
    test_gate_evidence.py. NOT the `tenant` fixture — that creates yet a
    THIRD tenant ("Phase3 Org") distinct from both `test_tenant` and this one,
    and mixing it with `test_tenant`/`auth_headers` makes a test pass
    vacuously.
    """
    tenant, _admin = await second_tenant_factory()
    return tenant


@pytest.mark.asyncio
async def test_an_unseeded_tenant_gets_defaults_not_an_error(db_session, test_tenant):
    """An unseeded tenant must behave as defaults rather than erroring — that is
    what makes this feature need NO deploy step, unlike B3b's envrequests."""
    policy = await get_or_create_policy(db_session, test_tenant.id)
    assert policy.require_rollback_plan is False
    assert policy.require_current_rehearsal is False
    assert policy.rehearsal_validity_days == 90


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session, test_tenant):
    first = await get_or_create_policy(db_session, test_tenant.id)
    await db_session.flush()
    second = await get_or_create_policy(db_session, test_tenant.id)
    await db_session.flush()
    assert first.id == second.id
    rows = (
        await db_session.execute(
            select(RollbackPolicy).where(RollbackPolicy.tenant_id == test_tenant.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_policy_from_another_tenant_is_not_returned(db_session, test_tenant, other_tenant):
    mine = await get_or_create_policy(db_session, test_tenant.id)
    theirs = await get_or_create_policy(db_session, other_tenant.id)
    await db_session.flush()
    assert mine.id != theirs.id
    assert mine.tenant_id == test_tenant.id
