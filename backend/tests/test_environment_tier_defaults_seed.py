"""The eight standard tiers are seeded per tenant, idempotently."""
import pytest
from sqlalchemy import select

from app.db.models.environment_tier import EnvironmentTier
from app.services.environment_tier_defaults import (
    STANDARD_TIERS,
    seed_environment_tier_defaults_for_tenant,
)


async def _tiers(db, tenant_id):
    return list(
        (
            await db.execute(
                select(EnvironmentTier).where(EnvironmentTier.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_seed_creates_the_eight_standard_tiers(db_session, test_tenant):
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = await _tiers(db_session, test_tenant.id)
    assert sorted(r.name for r in rows) == sorted(t["name"] for t in STANDARD_TIERS)
    assert {r.category for r in rows} == {t["category"] for t in STANDARD_TIERS}


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session, test_tenant):
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = await _tiers(db_session, test_tenant.id)
    assert len(rows) == len(STANDARD_TIERS)


@pytest.mark.asyncio
async def test_display_order_is_the_tier_progression_not_alphabetical(
    db_session, test_tenant
):
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = await _tiers(db_session, test_tenant.id)
    by_order = [r.name for r in sorted(rows, key=lambda r: r.display_order)]
    assert by_order.index("Dev") < by_order.index("UAT") < by_order.index("Production")


@pytest.mark.asyncio
async def test_seed_does_not_leak_across_tenants(
    db_session, test_tenant, second_tenant_factory
):
    other, _ = await second_tenant_factory()
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    assert await _tiers(db_session, other.id) == []


@pytest.mark.asyncio
async def test_creating_a_tenant_seeds_its_tiers(db_session):
    from app.api.v1.schemas import TenantCreate
    from app.services import tenant_service

    tenant = await tenant_service.create_tenant(
        db_session, TenantCreate(name="Tier Org", slug="tier-org")
    )

    rows = await _tiers(db_session, tenant.id)
    assert len(rows) == len(STANDARD_TIERS)
