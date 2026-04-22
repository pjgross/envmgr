"""Enterprise rollup and report API endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.api.v1.schemas.enterprise_rollup import (
    SystemRollupRow,
    ScopeRollupItem,
    TimelineRollupRead,
    MemberRollupRow,
    EnterpriseReportRead,
)
from app.services import enterprise_rollup_service, enterprise_report_service

router = APIRouter()


@router.get(
    "/releases/{enterprise_id}/rollup/systems",
    response_model=list[SystemRollupRow],
)
async def systems_rollup(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.systems_rollup(
        db, user=user, enterprise_id=enterprise_id
    )


@router.get(
    "/releases/{enterprise_id}/rollup/scope",
    response_model=list[ScopeRollupItem],
)
async def scope_rollup(
    enterprise_id: int,
    change_kind: Optional[str] = None,
    status: Optional[str] = None,
    project_release_id: Optional[int] = None,
    system_id: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.scope_rollup(
        db, user=user, enterprise_id=enterprise_id,
        change_kind=change_kind, status=status,
        project_release_id=project_release_id, system_id=system_id, search=search,
    )


@router.get(
    "/releases/{enterprise_id}/rollup/timeline",
    response_model=TimelineRollupRead,
)
async def timeline_rollup(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.timeline_rollup(
        db, user=user, enterprise_id=enterprise_id
    )


@router.get(
    "/releases/{enterprise_id}/rollup/members",
    response_model=list[MemberRollupRow],
)
async def members_rollup(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_rollup_service.members_rollup(
        db, user=user, enterprise_id=enterprise_id
    )


@router.get(
    "/releases/{enterprise_id}/report",
    response_model=EnterpriseReportRead,
)
async def enterprise_report(
    enterprise_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enterprise_report_service.generate_report(
        db, user=user, enterprise_id=enterprise_id
    )
