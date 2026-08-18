"""B5 — the tenant's idle-detection/decommission-notice policy, and CRUD for
the decommission-step checklist vocabulary.

Shaped like environment_compliance_service's naming policy (a single,
possibly-absent per-tenant row) and environment_tier_service (step CRUD):
name/key uniqueness is enforced here rather than by a partial unique index,
which is inert on SQLite — the same call B3a's group-name uniqueness made.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment_decommission import EnvironmentDecommissionStep
from app.db.models.environment_lifecycle_policy import EnvironmentLifecyclePolicy


async def get_policy(db: AsyncSession, tenant_id: int) -> EnvironmentLifecyclePolicy:
    """The tenant's policy, or an UNSAVED instance carrying the defaults.

    Never None. A caller that had to handle None would re-state the default
    thresholds, and two places stating one default is how they drift.
    """
    row = (
        await db.execute(
            select(EnvironmentLifecyclePolicy).where(
                EnvironmentLifecyclePolicy.tenant_id == tenant_id
            )
        )
    ).scalars().first()
    if row is not None:
        return row
    return EnvironmentLifecyclePolicy(
        tenant_id=tenant_id,
        idle_detection_enabled=False,
        idle_threshold_days=30,
        decommission_notice_days=5,
    )


async def upsert_policy(
    db: AsyncSession,
    tenant_id: int,
    *,
    idle_detection_enabled: bool,
    idle_threshold_days: int,
    decommission_notice_days: int,
) -> EnvironmentLifecyclePolicy:
    row = (
        await db.execute(
            select(EnvironmentLifecyclePolicy).where(
                EnvironmentLifecyclePolicy.tenant_id == tenant_id
            )
        )
    ).scalars().first()
    if row is None:
        row = EnvironmentLifecyclePolicy(tenant_id=tenant_id)
        db.add(row)
    row.idle_detection_enabled = idle_detection_enabled
    row.idle_threshold_days = idle_threshold_days
    row.decommission_notice_days = decommission_notice_days
    await db.flush()
    await db.refresh(row)
    return row


async def list_steps(
    db: AsyncSession, tenant_id: int, *, active_only: bool = False
) -> list[EnvironmentDecommissionStep]:
    """Every step currently on record for the tenant. A pure read — it does
    NOT seed. Every tenant is meant to carry the standard steps via
    tenant_service.create_tenant() (new tenants) and the `envdecommission`
    migration's backfill (tenants that predate it); a caller that has neither
    is a test-setup gap, not something this read path should paper over by
    writing rows on a GET.
    """
    query = select(EnvironmentDecommissionStep).where(
        EnvironmentDecommissionStep.tenant_id == tenant_id,
        EnvironmentDecommissionStep.deleted_at.is_(None),
    )
    if active_only:
        query = query.where(EnvironmentDecommissionStep.is_active.is_(True))
    query = query.order_by(
        EnvironmentDecommissionStep.display_order, EnvironmentDecommissionStep.id
    )
    return list((await db.execute(query)).scalars().all())


async def get_step(
    db: AsyncSession, step_id: int, tenant_id: int
) -> EnvironmentDecommissionStep:
    step = (
        await db.execute(
            select(EnvironmentDecommissionStep).where(
                EnvironmentDecommissionStep.id == step_id,
                EnvironmentDecommissionStep.tenant_id == tenant_id,
                EnvironmentDecommissionStep.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if step is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Decommission step not found",
        )
    return step


async def _assert_key_free(
    db: AsyncSession, tenant_id: int, key: str, exclude_id: Optional[int] = None
) -> None:
    query = select(EnvironmentDecommissionStep.id).where(
        EnvironmentDecommissionStep.tenant_id == tenant_id,
        EnvironmentDecommissionStep.deleted_at.is_(None),
        func.lower(EnvironmentDecommissionStep.key) == key.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(EnvironmentDecommissionStep.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A decommission step with this key already exists in this tenant",
        )


async def create_step(
    db: AsyncSession,
    tenant_id: int,
    *,
    key: str,
    label: str,
    description: Optional[str],
    display_order: int,
    is_required: bool,
    is_active: bool,
) -> EnvironmentDecommissionStep:
    await _assert_key_free(db, tenant_id, key)
    step = EnvironmentDecommissionStep(
        tenant_id=tenant_id,
        key=key.strip(),
        label=label.strip(),
        description=description,
        display_order=display_order,
        is_required=is_required,
        is_active=is_active,
    )
    db.add(step)
    await db.flush()
    await db.refresh(step)
    return step


async def update_step(
    db: AsyncSession,
    step_id: int,
    tenant_id: int,
    *,
    key: str,
    label: str,
    description: Optional[str],
    display_order: int,
    is_required: bool,
    is_active: bool,
) -> EnvironmentDecommissionStep:
    step = await get_step(db, step_id, tenant_id)
    if key.strip().lower() != step.key.lower():
        await _assert_key_free(db, tenant_id, key, exclude_id=step_id)
    step.key = key.strip()
    step.label = label.strip()
    step.description = description
    step.display_order = display_order
    step.is_required = is_required
    step.is_active = is_active
    await db.flush()
    await db.refresh(step)
    return step


async def delete_step(db: AsyncSession, step_id: int, tenant_id: int) -> None:
    """Soft delete. Deliberately NO refusal for a step a live decommission
    still needs: a retired step simply stops being required, and an
    attestation's `step_key` is a plain string precisely so old records still
    read correctly after their step definition is gone."""
    step = await get_step(db, step_id, tenant_id)
    step.deleted_at = datetime.now(timezone.utc)
    await db.flush()
