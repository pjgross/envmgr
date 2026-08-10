import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy
from tests.factories import ensure_environment_tier


@pytest.mark.asyncio
async def test_a_policy_defaults_to_disabled_with_no_rule(db_session, test_tenant):
    policy = EnvironmentNamingPolicy(tenant_id=test_tenant.id)
    db_session.add(policy)
    await db_session.flush()
    await db_session.refresh(policy)

    assert policy.is_enabled is False
    assert policy.name_pattern is None
    assert policy.required_attributes == []
    assert policy.grace_days == 14
    assert policy.effective_from is not None


@pytest.mark.asyncio
async def test_name_compliant_starts_null_meaning_no_pattern_applies(
    db_session, test_tenant
):
    """NULL is 'no pattern applies', not 'unknown' and not 'failing'. Every
    clause and every cell downstream treats it as compliant."""
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    env = Environment(name="anything", tier_id=tier.id, tenant_id=test_tenant.id)
    db_session.add(env)
    await db_session.flush()
    await db_session.refresh(env)

    assert env.name_compliant is None


@pytest.mark.asyncio
async def test_one_policy_per_tenant(db_session, test_tenant):
    db_session.add(EnvironmentNamingPolicy(tenant_id=test_tenant.id))
    await db_session.flush()
    db_session.add(EnvironmentNamingPolicy(tenant_id=test_tenant.id))
    with pytest.raises(Exception):
        await db_session.flush()
