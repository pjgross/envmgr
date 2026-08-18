"""B5 Task 1 — the schema exists, and the seed is idempotent."""
import pytest
from sqlalchemy import select

from app.db.models.environment_decommission import (
    EnvironmentDecommission,
    EnvironmentDecommissionStep,
)
from app.db.models.environment_tier import EnvironmentTier
from app.services.environment_decommission_defaults import (
    seed_decommission_steps_for_tenant,
)
from tests.factories import ensure_environment_tier


@pytest.mark.asyncio
async def test_the_seed_is_idempotent(db_session, tenant):
    await seed_decommission_steps_for_tenant(db_session, tenant.id)
    await seed_decommission_steps_for_tenant(db_session, tenant.id)

    keys = (
        await db_session.execute(
            select(EnvironmentDecommissionStep.key).where(
                EnvironmentDecommissionStep.tenant_id == tenant.id
            )
        )
    ).scalars().all()

    assert sorted(keys) == ["final_backup", "teardown"]


@pytest.mark.asyncio
async def test_a_decommission_row_stores_no_state(db_session, tenant):
    """THE STATE IS COMPUTED. If this fails, someone added a state column and
    with it something to invalidate and a scheduler to run."""
    assert not hasattr(EnvironmentDecommission, "state")
    assert not hasattr(EnvironmentDecommission, "status")


@pytest.mark.asyncio
async def test_the_tier_threshold_defaults_to_null(db_session, tenant):
    """NULL means 'use the tenant default' — a legitimate state, not a missing
    value, exactly as B1's null expires_at is.

    Deviation from the brief: the `tenant` fixture creates a bare Tenant row
    (not through tenant_service.create_tenant()), so it seeds no tiers. Using
    ensure_environment_tier here matches every other model test in this suite
    that needs a real tier.
    """
    await ensure_environment_tier(db_session, tenant.id)

    tier = (
        await db_session.execute(
            select(EnvironmentTier).where(EnvironmentTier.tenant_id == tenant.id)
        )
    ).scalars().first()
    assert tier is not None
    assert tier.idle_threshold_days is None
