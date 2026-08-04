"""/api/v1/deployments — list, detail, link-change; + env deployments helper."""
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
from app.db.models.change_request import ChangeRequest
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.api.v1.schemas.deployment import DeploymentLinkChangeRequest, DeploymentRead


router = APIRouter()
env_sub_router = APIRouter()

# today's default ordering is `deployed_at DESC, id` (newest first) — sorting()
# must preserve that when no sort_by/sort_dir is requested at all, see
# default_dir on the dependency below. All three columns are plain
# String/DateTime columns on Deployment (no SQLAlchemy Enum), so there is no
# name/value storage divergence to worry about.
DEPLOYMENT_SORTS = {
    "status": Deployment.status,
    "deployer_name": Deployment.deployer_name,
    "deployed_at": Deployment.deployed_at,
}


def _deployment_to_read(
    dep: Deployment,
    build_sha: Optional[str],
    environment_name: Optional[str],
    release_name: Optional[str],
    cr_title: Optional[str],
) -> DeploymentRead:
    payload = {c.name: getattr(dep, c.name) for c in dep.__table__.columns}
    payload["build_sha_short"] = build_sha[:8] if build_sha else None
    payload["environment_name"] = environment_name
    payload["release_name"] = release_name
    payload["change_request_title"] = cr_title
    return DeploymentRead.model_validate(payload)


def _select_with_joins():
    return (
        select(Deployment, Build.git_sha, Environment.name, Release.name, ChangeRequest.title)
        .outerjoin(Build, Build.id == Deployment.build_id)
        .outerjoin(Environment, Environment.id == Deployment.environment_id)
        .outerjoin(Release, Release.id == Deployment.release_id)
        .outerjoin(ChangeRequest, ChangeRequest.id == Deployment.change_request_id)
    )


@router.get("", response_model=list[DeploymentRead])
async def list_deployments(
    response: Response,
    environment_id: Optional[int] = Query(None),
    release_id: Optional[int] = Query(None),
    build_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    environment_search: Optional[str] = Query(None),
    release_search: Optional[str] = Query(None),
    page: Page = Depends(pagination(default_limit=100, max_limit=500)),
    sort: Sort = Depends(sorting(DEPLOYMENT_SORTS, default="deployed_at", default_dir="desc")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = _select_with_joins().where(
        Deployment.tenant_id == current_user.active_tenant_id,
        Deployment.deleted_at.is_(None),
    )
    if environment_id is not None:
        q = q.where(Deployment.environment_id == environment_id)
    if release_id is not None:
        q = q.where(Deployment.release_id == release_id)
    if build_id is not None:
        q = q.where(Deployment.build_id == build_id)
    if status_filter is not None:
        q = q.where(Deployment.status == status_filter)
    if date_from is not None:
        q = q.where(Deployment.deployed_at >= date_from)
    if date_to is not None:
        q = q.where(Deployment.deployed_at <= date_to)
    if environment_search:
        q = q.where(Environment.name.ilike(f"%{environment_search}%"))
    if release_search:
        q = q.where(Release.name.ilike(f"%{release_search}%"))
    q = apply_sort(q, sort).order_by(Deployment.deployed_at.desc(), Deployment.id)
    rows, total = await fetch_page_rows(db, q, page)
    set_total_count(response, total)
    return [
        _deployment_to_read(d, sha, env_name, rel_name, cr_title)
        for d, sha, env_name, rel_name, cr_title in rows
    ]


@router.get("/{deployment_id}", response_model=DeploymentRead)
async def get_deployment(
    deployment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = (await db.execute(
        _select_with_joins().where(
            Deployment.id == deployment_id,
            Deployment.tenant_id == current_user.active_tenant_id,
            Deployment.deleted_at.is_(None),
        )
    )).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    dep, sha, env_name, rel_name, cr_title = row
    return _deployment_to_read(dep, sha, env_name, rel_name, cr_title)


@router.post("/{deployment_id}/link-change", response_model=DeploymentRead)
async def link_change(
    deployment_id: int,
    body: DeploymentLinkChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    dep = (await db.execute(
        select(Deployment).where(
            Deployment.id == deployment_id,
            Deployment.tenant_id == tenant_id,
            Deployment.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if dep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")

    # Must currently be linked to a Code Deployment template to be swapped.
    current_tpl = (await db.execute(
        select(LifecycleTemplate).join(
            ChangeRequest, ChangeRequest.lifecycle_id == LifecycleTemplate.id,
        ).where(ChangeRequest.id == dep.change_request_id)
    )).scalar_one_or_none()
    if current_tpl is None or current_tpl.name != "Code Deployment":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Deployment is linked to a human-authored change request; cannot swap.",
        )

    new_cr = (await db.execute(
        select(ChangeRequest).where(
            ChangeRequest.id == body.change_request_id,
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if new_cr is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Target change request not found")

    dep.change_request_id = new_cr.id
    await db.flush()
    await db.refresh(dep)

    # Re-fetch with joins for the response.
    row = (await db.execute(
        _select_with_joins().where(Deployment.id == dep.id)
    )).one()
    d, sha, env_name, rel_name, cr_title = row
    return _deployment_to_read(d, sha, env_name, rel_name, cr_title)


@env_sub_router.get("/{environment_id}/deployments", response_model=list[DeploymentRead])
async def list_environment_deployments(
    environment_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = _select_with_joins().where(
        Deployment.tenant_id == current_user.active_tenant_id,
        Deployment.environment_id == environment_id,
        Deployment.deleted_at.is_(None),
    # `deployed_at` is caller-supplied by CI, so several deployments sharing a
    # timestamp is ordinary rather than exceptional — without the `id`
    # tiebreaker LIMIT/OFFSET over those ties duplicates and drops rows across
    # pages. Matches the ordering of the flat `GET /deployments` sibling.
    ).order_by(Deployment.deployed_at.desc(), Deployment.id)
    rows, total = await fetch_page_rows(db, q, page)
    set_total_count(response, total)
    return [
        _deployment_to_read(d, sha, env_name, rel_name, cr_title)
        for d, sha, env_name, rel_name, cr_title in rows
    ]
