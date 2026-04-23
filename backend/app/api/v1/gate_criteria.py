"""API — gate criteria.

Endpoints:
  POST   /releases/{release_id}/gates/{gate_id}/criteria   — create
  GET    /releases/{release_id}/gates/{gate_id}/criteria   — list for gate
  PUT    /gate-criteria/{criterion_id}                     — edit
  POST   /gate-criteria/{criterion_id}/complete            — mark done (may auto-pass gate)
  POST   /gate-criteria/{criterion_id}/reopen              — back to open
  DELETE /gate-criteria/{criterion_id}                     — soft delete
  GET    /releases/{release_id}/overdue-criteria           — flat overdue list

Auth: all endpoints require get_current_user. No role-gating for v1.
"""
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.db.models.user import User
from app.services import gate_criterion_service, release_service
from app.api.v1.schemas.gate_criterion import (
    GateCriterionCreate,
    GateCriterionUpdate,
    GateCriterionRead,
    GateCriterionWithGate,
)


# Sub-resource router — mounted at /releases
release_sub_router = APIRouter(prefix="/releases", tags=["Gate Criteria"])

# Top-level router — mounted at /gate-criteria
router = APIRouter(prefix="/gate-criteria", tags=["Gate Criteria"])


def _crit_to_dict(c) -> dict:
    """Convert a GateCriterion ORM object to a plain dict safe for Pydantic validation.

    Avoids MissingGreenlet errors that arise when Pydantic accesses ORM attributes
    outside an async context after a session flush.
    """
    return {
        "id": c.id, "gate_id": c.gate_id, "title": c.title, "notes": c.notes,
        "assigned_to_user_id": c.assigned_to_user_id,
        "assigned_to_username": None, "status": c.status,
        "completed_at": c.completed_at, "completed_by_user_id": c.completed_by_user_id,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


async def _attach_assignee_username(
    db: AsyncSession, read: GateCriterionRead, user_id: int | None
) -> GateCriterionRead:
    if user_id is None:
        return read
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is not None:
        read.assigned_to_username = u.username
    return read


@release_sub_router.post(
    "/{release_id}/gates/{gate_id}/criteria",
    response_model=GateCriterionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_criterion(
    release_id: int,
    gate_id: int,
    data: GateCriterionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    # Tenant-scope the release to avoid leaking gate existence across tenants.
    await release_service.get_release(db, release_id, tenant_id)
    crit = await gate_criterion_service.create_criterion(
        db, gate_id=gate_id, tenant_id=tenant_id, user_id=current_user.id, data=data,
    )
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(_crit_to_dict(crit)), crit.assigned_to_user_id,
    )


@release_sub_router.get(
    "/{release_id}/gates/{gate_id}/criteria",
    response_model=List[GateCriterionRead],
)
async def list_criteria(
    release_id: int,
    gate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await release_service.get_release(db, release_id, tenant_id)
    rows = await gate_criterion_service.list_criteria_for_gate(db, gate_id, tenant_id)
    out: list[GateCriterionRead] = []
    for r in rows:
        out.append(
            await _attach_assignee_username(
                db, GateCriterionRead.model_validate(_crit_to_dict(r)), r.assigned_to_user_id,
            )
        )
    return out


@release_sub_router.get(
    "/{release_id}/overdue-criteria",
    response_model=List[GateCriterionWithGate],
)
async def list_overdue(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await release_service.get_release(db, release_id, tenant_id)
    rows = await gate_criterion_service.list_overdue_for_release(db, release_id, tenant_id)
    out: list[GateCriterionWithGate] = []
    for crit, gate in rows:
        out.append(GateCriterionWithGate.model_validate({
            **_crit_to_dict(crit),
            "gate_name": gate.name,
            "gate_due_date": gate.due_date,
        }))
    return out


@router.put("/{criterion_id}", response_model=GateCriterionRead)
async def update_criterion(
    criterion_id: int,
    data: GateCriterionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    crit = await gate_criterion_service.update_criterion(db, criterion_id, tenant_id, data)
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(_crit_to_dict(crit)), crit.assigned_to_user_id,
    )


@router.post("/{criterion_id}/complete", response_model=GateCriterionRead)
async def complete_criterion(
    criterion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    crit = await gate_criterion_service.complete_criterion(
        db, criterion_id, tenant_id, current_user.id,
    )
    await db.refresh(crit)
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(_crit_to_dict(crit)), crit.assigned_to_user_id,
    )


@router.post("/{criterion_id}/reopen", response_model=GateCriterionRead)
async def reopen_criterion(
    criterion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    crit = await gate_criterion_service.reopen_criterion(db, criterion_id, tenant_id)
    await db.refresh(crit)
    return await _attach_assignee_username(
        db, GateCriterionRead.model_validate(_crit_to_dict(crit)), crit.assigned_to_user_id,
    )


@router.delete("/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_criterion(
    criterion_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await gate_criterion_service.delete_criterion(db, criterion_id, tenant_id)
