"""Environment tier vocabulary — tenant-scoped CRUD.

Name uniqueness is enforced here rather than by a partial unique index: a
partial index is inert on SQLite, so half the test suite would not exercise it.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.api.v1.schemas.environment_tier import (
    EnvironmentTierCreate,
    EnvironmentTierUpdate,
)
from app.db.models.environment import Environment
from app.db.models.environment_tier import EnvironmentTier


async def list_tiers(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    include_inactive: bool = True,
) -> tuple[list[EnvironmentTier], int]:
    query = select(EnvironmentTier).where(
        EnvironmentTier.tenant_id == tenant_id,
        EnvironmentTier.deleted_at.is_(None),
    )
    if not include_inactive:
        query = query.where(EnvironmentTier.is_active.is_(True))
    # display_order defaults to 0, so ties are the normal case, not the
    # exception — the id tiebreaker is what stops LIMIT/OFFSET duplicating and
    # dropping rows across pages.
    query = apply_sort(query, sort).order_by(
        EnvironmentTier.display_order, EnvironmentTier.id
    )
    return await fetch_page(db, query, page)


async def get_tier(db: AsyncSession, tier_id: int, tenant_id: int) -> EnvironmentTier:
    tier = (
        await db.execute(
            select(EnvironmentTier).where(
                EnvironmentTier.id == tier_id,
                EnvironmentTier.tenant_id == tenant_id,
                EnvironmentTier.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if tier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Environment tier not found"
        )
    return tier


async def _assert_name_free(
    db: AsyncSession, tenant_id: int, name: str, exclude_id: Optional[int] = None
) -> None:
    query = select(EnvironmentTier.id).where(
        EnvironmentTier.tenant_id == tenant_id,
        EnvironmentTier.deleted_at.is_(None),
        func.lower(EnvironmentTier.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(EnvironmentTier.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tier with this name already exists in this tenant",
        )


async def create_tier(
    db: AsyncSession, data: EnvironmentTierCreate, tenant_id: int
) -> EnvironmentTier:
    await _assert_name_free(db, tenant_id, data.name)
    tier = EnvironmentTier(
        tenant_id=tenant_id,
        name=data.name.strip(),
        description=data.description,
        category=None,
        color=data.color,
        display_order=data.display_order,
        is_active=data.is_active,
        idle_threshold_days=data.idle_threshold_days,
    )
    db.add(tier)
    await db.flush()
    await db.refresh(tier)
    return tier


async def update_tier(
    db: AsyncSession, tier_id: int, data: EnvironmentTierUpdate, tenant_id: int
) -> EnvironmentTier:
    tier = await get_tier(db, tier_id, tenant_id)
    if data.name is not None and data.name.strip().lower() != tier.name.lower():
        await _assert_name_free(db, tenant_id, data.name, exclude_id=tier_id)
    if data.name is not None:
        tier.name = data.name.strip()
    if data.description is not None:
        tier.description = data.description
    if data.color is not None:
        tier.color = data.color
    if data.display_order is not None:
        tier.display_order = data.display_order
    if data.is_active is not None:
        tier.is_active = data.is_active
    # NULL is a legitimate value here ("use the tenant default"), not "leave
    # alone" — unlike the fields above, an explicit null must be honoured, so
    # this reads `model_fields_set` rather than `is not None`.
    if "idle_threshold_days" in data.model_fields_set:
        tier.idle_threshold_days = data.idle_threshold_days
    await db.flush()
    await db.refresh(tier)
    return tier


async def delete_tier(db: AsyncSession, tier_id: int, tenant_id: int) -> None:
    tier = await get_tier(db, tier_id, tenant_id)
    in_use = (
        await db.execute(
            select(Environment.id).where(
                Environment.tier_id == tier_id,
                Environment.tenant_id == tenant_id,
                # A soft-deleted environment is not a reference. Counting it
                # would make a tier unretirable forever once anything that used
                # it was deleted.
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This tier is in use by one or more environments",
        )
    tier.deleted_at = datetime.now(timezone.utc)
    await db.flush()
