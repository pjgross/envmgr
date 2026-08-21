"""Per-tenant rollback policy — get-or-create with defaults.

Modelled on raid_config_service.seed_default_config, which is already
get-or-create. Because an unseeded tenant simply gets defaults, C4 needs NO
deploy step — unlike B3b's envrequests, and unlike what C2's docs initially
and wrongly claimed.
"""
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.rollback import RollbackPolicy

DEFAULT_REHEARSAL_VALIDITY_DAYS = 90


async def get_or_create_policy(db: AsyncSession, tenant_id: int) -> RollbackPolicy:
    """Return this tenant's policy, creating it with defaults if absent."""
    existing = (
        await db.execute(
            select(RollbackPolicy).where(RollbackPolicy.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    policy = RollbackPolicy(
        tenant_id=tenant_id,
        require_rollback_plan=False,
        require_current_rehearsal=False,
        rehearsal_validity_days=DEFAULT_REHEARSAL_VALIDITY_DAYS,
    )
    db.add(policy)
    await db.flush()
    return policy


async def update_policy(
    db: AsyncSession,
    tenant_id: int,
    *,
    require_rollback_plan: Optional[bool] = None,
    require_current_rehearsal: Optional[bool] = None,
    rehearsal_validity_days: Optional[int] = None,
) -> RollbackPolicy:
    """Patch semantics: an omitted argument means "leave alone"."""
    policy = await get_or_create_policy(db, tenant_id)
    if require_rollback_plan is not None:
        policy.require_rollback_plan = require_rollback_plan
    if require_current_rehearsal is not None:
        policy.require_current_rehearsal = require_current_rehearsal
    if rehearsal_validity_days is not None:
        if rehearsal_validity_days < 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "rehearsal_validity_days must be at least 1",
            )
        policy.rehearsal_validity_days = rehearsal_validity_days
    await db.flush()
    return policy
