"""Enterprise-release membership API."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.api.v1.schemas.release_membership import (
    ReleaseMembershipCreate,
    ReleaseMembershipRead,
    MembershipRejectRequest,
    MembershipRemoveRequest,
)
from app.services import enterprise_membership_service

router = APIRouter()


def _to_read(m) -> ReleaseMembershipRead:
    return ReleaseMembershipRead.model_validate(m)


@router.post(
    "/releases/{enterprise_id}/memberships",
    response_model=ReleaseMembershipRead,
    status_code=status.HTTP_201_CREATED,
)
async def request_membership(
    enterprise_id: int,
    body: ReleaseMembershipCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.request_membership(
        db,
        user=user,
        enterprise_id=enterprise_id,
        project_release_id=body.project_release_id,
        notes=body.notes,
    )
    return _to_read(m)


@router.get(
    "/releases/{enterprise_id}/memberships",
    response_model=list[ReleaseMembershipRead],
)
async def list_memberships(
    enterprise_id: int,
    states: Optional[str] = Query(None, description="CSV of states"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    state_list = [s.strip() for s in states.split(",")] if states else None
    rows = await enterprise_membership_service.list_memberships(
        db,
        user=user,
        enterprise_id=enterprise_id,
        states=state_list,
    )
    return [_to_read(r) for r in rows]


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/accept",
    response_model=ReleaseMembershipRead,
)
async def accept_membership(
    enterprise_id: int,
    membership_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.accept(
        db,
        user=user,
        membership_id=membership_id,
    )
    return _to_read(m)


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/reject",
    response_model=ReleaseMembershipRead,
)
async def reject_membership(
    enterprise_id: int,
    membership_id: int,
    body: MembershipRejectRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.reject(
        db,
        user=user,
        membership_id=membership_id,
        notes=body.notes,
    )
    return _to_read(m)


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/withdraw",
    response_model=ReleaseMembershipRead,
)
async def withdraw_membership(
    enterprise_id: int,
    membership_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.withdraw(
        db,
        user=user,
        membership_id=membership_id,
    )
    return _to_read(m)


@router.post(
    "/releases/{enterprise_id}/memberships/{membership_id}/remove",
    response_model=ReleaseMembershipRead,
)
async def remove_membership(
    enterprise_id: int,
    membership_id: int,
    body: MembershipRemoveRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    m = await enterprise_membership_service.remove(
        db,
        user=user,
        membership_id=membership_id,
        reason=body.reason,
    )
    return _to_read(m)


@router.get(
    "/releases/{project_release_id}/membership",
    response_model=dict,
)
async def project_membership_view(
    project_release_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    current = await enterprise_membership_service.get_current_membership_for_project(
        db,
        user=user,
        project_release_id=project_release_id,
    )
    history = await enterprise_membership_service.list_history_for_project(
        db,
        user=user,
        project_release_id=project_release_id,
    )
    return {
        "current": _to_read(current).model_dump() if current else None,
        "history": [_to_read(h).model_dump() for h in history],
    }
