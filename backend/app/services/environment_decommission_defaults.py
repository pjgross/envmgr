"""Seed the two standard decommission steps. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill,
following environment_tier_defaults.py.

The migration carries its own literal copy of this list rather than importing
it: a migration reproduces the past, so it must not change meaning when this
module gains a third step.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment_decommission import EnvironmentDecommissionStep

STANDARD_STEPS: list[dict[str, Any]] = [
    {
        "key": "final_backup",
        "label": "Final backup taken",
        "description": "Record the snapshot id or backup job reference.",
        "display_order": 10,
        "is_required": True,
    },
    {
        "key": "teardown",
        "label": "Infrastructure torn down",
        "description": "Record the ticket or runbook run that removed it.",
        "display_order": 20,
        "is_required": True,
    },
]


async def seed_decommission_steps_for_tenant(
    db: AsyncSession, tenant_id: int
) -> None:
    """Create any standard step this tenant does not already have, matched on
    `key` so a re-run adds nothing."""
    existing = set(
        (
            await db.execute(
                select(EnvironmentDecommissionStep.key).where(
                    EnvironmentDecommissionStep.tenant_id == tenant_id
                )
            )
        ).scalars()
    )
    for step in STANDARD_STEPS:
        if step["key"] in existing:
            continue
        db.add(EnvironmentDecommissionStep(tenant_id=tenant_id, **step))
    await db.flush()
