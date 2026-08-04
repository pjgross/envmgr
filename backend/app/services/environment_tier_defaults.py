"""Seed the eight standard environment tiers. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill,
following release_defaults.py and incident_defaults.py.

The tier migration carries its own literal copy of this list rather than
importing it. That is deliberate: a migration reproduces the past, so it must
not change meaning when this module gains a ninth tier.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment_tier import EnvironmentTier

STANDARD_TIERS: list[dict[str, Any]] = [
    {"name": "Dev",         "category": "dev",         "color": "#90A4AE", "display_order": 10},
    {"name": "SIT",         "category": "sit",         "color": "#42A5F5", "display_order": 20},
    {"name": "UAT",         "category": "uat",         "color": "#7E57C2", "display_order": 30},
    {"name": "Pre-Prod",    "category": "preprod",     "color": "#FFA726", "display_order": 40},
    {"name": "Performance", "category": "performance", "color": "#26A69A", "display_order": 50},
    {"name": "Training",    "category": "training",    "color": "#8D6E63", "display_order": 60},
    {"name": "Production",  "category": "production",  "color": "#EF5350", "display_order": 70},
    {"name": "Other",       "category": "other",       "color": "#BDBDBD", "display_order": 80},
]


async def seed_environment_tier_defaults_for_tenant(
    db: AsyncSession, tenant_id: int
) -> None:
    """Create any of the standard tiers this tenant does not already have.

    Matched on lowercased name so a tenant that already has 'sit' is not given a
    second 'SIT'.
    """
    existing = {
        name.lower()
        for name in (
            await db.execute(
                select(EnvironmentTier.name).where(
                    EnvironmentTier.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    }
    for tier in STANDARD_TIERS:
        if tier["name"].lower() in existing:
            continue
        db.add(
            EnvironmentTier(
                tenant_id=tenant_id,
                name=tier["name"],
                category=tier["category"],
                color=tier["color"],
                display_order=tier["display_order"],
                is_active=True,
            )
        )
