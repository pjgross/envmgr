"""/api/v1/deployments — list, detail, link-change; + env deployments helper."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.change_request import ChangeRequest
from app.db.models.deployment import Deployment
from app.db.models.lifecycle import LifecycleTemplate
from app.api.v1.schemas.deployment import DeploymentLinkChangeRequest, DeploymentRead


router = APIRouter()
env_sub_router = APIRouter()


@router.get("", response_model=list[DeploymentRead])
async def list_deployments(
    environment_id: Optional[int] = Query(None),
    release_id: Optional[int] = Query(None),
    build_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = select(Deployment).where(
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
    q = q.order_by(Deployment.deployed_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(q)).scalars().all())


@router.get("/{deployment_id}", response_model=DeploymentRead)
async def get_deployment(
    deployment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = (await db.execute(
        select(Deployment).where(
            Deployment.id == deployment_id,
            Deployment.tenant_id == current_user.active_tenant_id,
            Deployment.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    return row


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
    return dep


@env_sub_router.get("/{environment_id}/deployments", response_model=list[DeploymentRead])
async def list_environment_deployments(
    environment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = select(Deployment).where(
        Deployment.tenant_id == current_user.active_tenant_id,
        Deployment.environment_id == environment_id,
        Deployment.deleted_at.is_(None),
    ).order_by(Deployment.deployed_at.desc())
    return list((await db.execute(q)).scalars().all())
