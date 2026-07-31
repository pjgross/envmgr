"""Enterprise-release membership API."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.pagination import Page, pagination, set_total_count
from app.db.base import get_db
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership
from app.db.models.user import User
from app.api.v1.schemas.release_membership import (
    ReleaseMembershipCreate,
    ReleaseMembershipRead,
    MembershipRejectRequest,
    MembershipRemoveRequest,
)
from app.services import enterprise_membership_service

router = APIRouter()


async def _hydrate_reads(
    db: AsyncSession, memberships: list[ReleaseMembership]
) -> list[ReleaseMembershipRead]:
    """Populate decorated fields (project_release_name/status + *_username) by
    batch-loading Users and Releases for a list of membership rows.
    """
    if not memberships:
        return []

    # Gather user ids, project release ids, and enterprise release ids to batch-load
    user_ids: set[int] = set()
    for m in memberships:
        user_ids.add(m.requested_by)
        if m.decided_by is not None:
            user_ids.add(m.decided_by)
        if m.removed_by is not None:
            user_ids.add(m.removed_by)
    project_ids = {m.project_release_id for m in memberships}
    enterprise_ids = {m.enterprise_release_id for m in memberships}

    # All memberships in a call share one tenant (loaded tenant-scoped upstream);
    # constrain the decoration loads to that tenant for defence in depth.
    tenant_id = memberships[0].tenant_id

    users_by_id: dict[int, User] = {}
    if user_ids:
        rows = (await db.execute(select(User).where(
            User.id.in_(user_ids), User.tenant_id == tenant_id,
        ))).scalars().all()
        users_by_id = {u.id: u for u in rows}

    # Batch-load both project and enterprise releases in a single query
    all_release_ids = project_ids | enterprise_ids
    releases_by_id: dict[int, Release] = {}
    if all_release_ids:
        rows = (await db.execute(select(Release).where(
            Release.id.in_(all_release_ids), Release.tenant_id == tenant_id,
        ))).scalars().all()
        releases_by_id = {r.id: r for r in rows}

    def _uname(uid: Optional[int]) -> Optional[str]:
        if uid is None:
            return None
        u = users_by_id.get(uid)
        return u.username if u else None

    reads: list[ReleaseMembershipRead] = []
    for m in memberships:
        r = ReleaseMembershipRead.model_validate(m)
        proj = releases_by_id.get(m.project_release_id)
        ent = releases_by_id.get(m.enterprise_release_id)
        r.project_release_name = proj.name if proj else None
        r.project_release_status = proj.status if proj else None
        r.enterprise_release_name = ent.name if ent else None
        r.requested_by_username = _uname(m.requested_by)
        r.decided_by_username = _uname(m.decided_by)
        r.removed_by_username = _uname(m.removed_by)
        reads.append(r)
    return reads


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
    return (await _hydrate_reads(db, [m]))[0]


@router.get(
    "/releases/{enterprise_id}/memberships",
    response_model=list[ReleaseMembershipRead],
)
async def list_memberships(
    enterprise_id: int,
    response: Response,
    states: Optional[str] = Query(None, description="CSV of states"),
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    state_list = [s.strip() for s in states.split(",")] if states else None
    rows, total = await enterprise_membership_service.list_memberships(
        db,
        user=user,
        enterprise_id=enterprise_id,
        states=state_list,
        page=page,
    )
    set_total_count(response, total)
    return await _hydrate_reads(db, rows)


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
    return (await _hydrate_reads(db, [m]))[0]


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
    return (await _hydrate_reads(db, [m]))[0]


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
    return (await _hydrate_reads(db, [m]))[0]


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
    return (await _hydrate_reads(db, [m]))[0]


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
    all_memberships = ([current] if current else []) + history
    reads = await _hydrate_reads(db, all_memberships)
    current_read = reads[0] if current else None
    history_reads = reads[(1 if current else 0):]
    return {
        "current": current_read.model_dump() if current_read else None,
        "history": [h.model_dump() for h in history_reads],
    }
