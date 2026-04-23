"""GET /api/v1/builds — list + detail."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.build import Build
from app.api.v1.schemas.build import BuildRead


router = APIRouter()


@router.get("", response_model=list[BuildRead])
async def list_builds(
    subsystem_id: Optional[int] = Query(None),
    release_id: Optional[int] = Query(None),
    branch: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = select(Build).where(
        Build.tenant_id == current_user.active_tenant_id,
        Build.deleted_at.is_(None),
    )
    if subsystem_id is not None:
        q = q.where(Build.subsystem_id == subsystem_id)
    if release_id is not None:
        q = q.where(Build.release_id == release_id)
    if branch is not None:
        q = q.where(Build.git_branch == branch)
    if date_from is not None:
        q = q.where(Build.commit_timestamp >= date_from)
    if date_to is not None:
        q = q.where(Build.commit_timestamp <= date_to)
    q = q.order_by(Build.commit_timestamp.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


@router.get("/{build_id}", response_model=BuildRead)
async def get_build(
    build_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = (await db.execute(
        select(Build).where(
            Build.id == build_id,
            Build.tenant_id == current_user.active_tenant_id,
            Build.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Build not found")
    return row
