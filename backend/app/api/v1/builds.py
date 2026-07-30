"""GET /api/v1/builds — list + detail."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import (
    Page,
    Sort,
    apply_sort,
    fetch_page_rows,
    pagination,
    set_total_count,
    sorting,
)
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.build import Build
from app.db.models.release import Release
from app.db.models.system import SubSystem
from app.api.v1.schemas.build import BuildRead


router = APIRouter()

# `/builds` was the one list endpoint sub-project A never bounded: its own
# `limit=Query(100, le=500)`, no `set_total_count`, and an order-by with no
# tiebreaker at all (`commit_timestamp DESC` alone) — the exact
# LIMIT/OFFSET-over-a-partial-order bug A fixed everywhere else, just not
# caught here because this endpoint predates that sweep. `pagination()` below
# reproduces the old contract (default 100, cap 500) so no existing page
# shrinks; `Build.id` is added as the tiebreaker. `default_dir="desc"`
# preserves today's newest-first default the moment sorting() is adopted.
BUILD_SORTS = {
    "git_branch": Build.git_branch,
    "build_number": Build.build_number,
    "commit_timestamp": Build.commit_timestamp,
}


def _build_to_read(
    build: Build,
    subsystem_name: Optional[str],
    release_name: Optional[str],
) -> BuildRead:
    payload = {c.name: getattr(build, c.name) for c in build.__table__.columns}
    payload["subsystem_name"] = subsystem_name
    payload["release_name"] = release_name
    return BuildRead.model_validate(payload)


@router.get("", response_model=list[BuildRead])
async def list_builds(
    response: Response,
    subsystem_id: Optional[int] = Query(None),
    release_id: Optional[int] = Query(None),
    branch: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    subsystem_search: Optional[str] = Query(None),
    page: Page = Depends(pagination(default_limit=100, max_limit=500)),
    sort: Sort = Depends(
        sorting(BUILD_SORTS, default="commit_timestamp", default_dir="desc")
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = (
        select(Build, SubSystem.name, Release.name)
        .outerjoin(SubSystem, SubSystem.id == Build.subsystem_id)
        .outerjoin(Release, Release.id == Build.release_id)
        .where(
            Build.tenant_id == current_user.active_tenant_id,
            Build.deleted_at.is_(None),
        )
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
    if subsystem_search:
        q = q.where(SubSystem.name.ilike(f"%{subsystem_search}%"))
    q = apply_sort(q, sort).order_by(Build.commit_timestamp.desc(), Build.id)
    rows, total = await fetch_page_rows(db, q, page)
    set_total_count(response, total)
    return [_build_to_read(b, sub_name, rel_name) for b, sub_name, rel_name in rows]


@router.get("/{build_id}", response_model=BuildRead)
async def get_build(
    build_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = (await db.execute(
        select(Build, SubSystem.name, Release.name)
        .outerjoin(SubSystem, SubSystem.id == Build.subsystem_id)
        .outerjoin(Release, Release.id == Build.release_id)
        .where(
            Build.id == build_id,
            Build.tenant_id == current_user.active_tenant_id,
            Build.deleted_at.is_(None),
        )
    )).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Build not found")
    build, sub_name, rel_name = row
    return _build_to_read(build, sub_name, rel_name)
