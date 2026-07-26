"""GateCriterion service — CRUD, complete/reopen, overdue query.

Auto-pass of the parent gate is implemented in Task 4. This module stays small
and pure: CRUD + queries. Events are published from the caller's transaction.
"""
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.gate_criterion import GateCriterion
from app.db.models.release_gate import ReleaseGate
from app.api.v1.schemas.gate_criterion import GateCriterionCreate, GateCriterionUpdate


async def _get_gate_scoped(
    db: AsyncSession, gate_id: int, tenant_id: int
) -> ReleaseGate:
    gate = (
        await db.execute(
            select(ReleaseGate).where(
                ReleaseGate.id == gate_id,
                ReleaseGate.tenant_id == tenant_id,
                ReleaseGate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if gate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release gate not found")
    return gate


async def get_criterion(
    db: AsyncSession, criterion_id: int, tenant_id: int
) -> GateCriterion:
    crit = (
        await db.execute(
            select(GateCriterion).where(
                GateCriterion.id == criterion_id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if crit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate criterion not found")
    return crit


async def list_criteria_for_gate(
    db: AsyncSession, gate_id: int, tenant_id: int
) -> list[GateCriterion]:
    rows = (
        await db.execute(
            select(GateCriterion).where(
                GateCriterion.gate_id == gate_id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
            ).order_by(GateCriterion.id)
        )
    ).scalars().all()
    return list(rows)


async def list_overdue_for_release(
    db: AsyncSession, release_id: int, tenant_id: int
) -> list[tuple[GateCriterion, ReleaseGate]]:
    """Overdue = criterion is open AND its gate's due_date < now()."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(GateCriterion, ReleaseGate)
            .join(ReleaseGate, ReleaseGate.id == GateCriterion.gate_id)
            .where(
                ReleaseGate.release_id == release_id,
                GateCriterion.tenant_id == tenant_id,
                GateCriterion.deleted_at.is_(None),
                GateCriterion.status == "open",
                ReleaseGate.deleted_at.is_(None),
                ReleaseGate.due_date < now,
            )
            .order_by(ReleaseGate.due_date, GateCriterion.id)
        )
    ).all()
    return [(c, g) for c, g in rows]


async def create_criterion(
    db: AsyncSession,
    gate_id: int,
    tenant_id: int,
    user_id: int,
    data: GateCriterionCreate,
) -> GateCriterion:
    gate = await _get_gate_scoped(db, gate_id, tenant_id)
    crit = GateCriterion(
        tenant_id=tenant_id,
        gate_id=gate.id,
        title=data.title,
        notes=data.notes,
        assigned_to_user_id=data.assigned_to_user_id,
        assigned_role=data.assigned_role,
        status="open",
    )
    db.add(crit)
    await db.flush()
    await publish_event(
        db,
        event_type="GateCriterionCreated",
        aggregate_id=crit.id,
        aggregate_type="GateCriterion",
        payload={"id": crit.id, "gate_id": gate.id, "title": crit.title},
        tenant_id=tenant_id,
    )
    return crit


async def update_criterion(
    db: AsyncSession,
    criterion_id: int,
    tenant_id: int,
    data: GateCriterionUpdate,
) -> GateCriterion:
    crit = await get_criterion(db, criterion_id, tenant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(crit, field, value)
    await db.flush()
    return crit


async def delete_criterion(
    db: AsyncSession, criterion_id: int, tenant_id: int
) -> None:
    crit = await get_criterion(db, criterion_id, tenant_id)
    crit.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def complete_criterion(
    db: AsyncSession,
    criterion_id: int,
    tenant_id: int,
    user_id: int,
    user_role: str,
) -> GateCriterion:
    """Mark a criterion done. If this makes the parent gate have all criteria
    done, auto-pass the gate (one-way)."""
    from app.services import release_gate_service  # lazy to avoid circular

    crit = await get_criterion(db, criterion_id, tenant_id)
    from app.core.security import Role
    if crit.assigned_role is not None:
        if user_role != crit.assigned_role and user_role != Role.ADMIN:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Only a {crit.assigned_role} or Admin can complete this criterion",
            )
    if crit.status == "done":
        return crit  # idempotent

    crit.status = "done"
    crit.completed_at = datetime.now(timezone.utc)
    crit.completed_by_user_id = user_id
    await db.flush()

    await publish_event(
        db,
        event_type="GateCriterionCompleted",
        aggregate_id=crit.id,
        aggregate_type="GateCriterion",
        payload={"id": crit.id, "gate_id": crit.gate_id, "completed_by": user_id},
        tenant_id=tenant_id,
    )

    gate = await release_gate_service.get_gate(db, crit.gate_id, tenant_id)
    await release_gate_service.maybe_auto_pass_gate(db, gate, tenant_id, user_id)
    return crit


async def reopen_criterion(
    db: AsyncSession, criterion_id: int, tenant_id: int, user_role: str,
) -> GateCriterion:
    """Set a done criterion back to open. Does NOT flip the gate back to pending."""
    crit = await get_criterion(db, criterion_id, tenant_id)
    from app.core.security import Role
    if crit.assigned_role is not None:
        if user_role != crit.assigned_role and user_role != Role.ADMIN:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Only a {crit.assigned_role} or Admin can reopen this criterion",
            )
    if crit.status == "open":
        return crit  # idempotent

    crit.status = "open"
    crit.completed_at = None
    crit.completed_by_user_id = None
    await db.flush()

    await publish_event(
        db,
        event_type="GateCriterionReopened",
        aggregate_id=crit.id,
        aggregate_type="GateCriterion",
        payload={"id": crit.id, "gate_id": crit.gate_id},
        tenant_id=tenant_id,
    )
    return crit
