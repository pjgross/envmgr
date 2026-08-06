from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.project import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    UsageAgreementCreate,
    UsageAgreementResponse,
)
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.services import project_service

router = APIRouter()


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    response: Response,
    search: Optional[str] = Query(None, description="Case-insensitive name match."),
    is_active: Optional[bool] = Query(None),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(project_service.PROJECT_SORTS, default="name")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readable by any tenant member — every booking form needs the picker, and
    everyone needs to see which project a booking belongs to."""
    views, total = await project_service.list_projects(
        db, current_user.active_tenant_id,
        page=page, sort=sort, search=search, is_active=is_active,
    )
    set_total_count(response, total)
    return [ProjectResponse.from_view(v) for v in views]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await project_service.create_project(db, data, current_user.active_tenant_id)
    return ProjectResponse.from_view(view)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await project_service.get_project_view(
        db, project_id, current_user.active_tenant_id
    )
    return ProjectResponse.from_view(view)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await project_service.update_project(
        db, project_id, data, current_user.active_tenant_id
    )
    return ProjectResponse.from_view(view)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await project_service.delete_project(db, project_id, current_user.active_tenant_id)


@router.get("/{project_id}/usage-agreements", response_model=list[UsageAgreementResponse])
async def list_project_usage_agreements(
    project_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await project_service.list_agreements_for_project(
        db, project_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [UsageAgreementResponse.from_row(r) for r in rows]


@router.post(
    "/{project_id}/usage-agreements",
    response_model=UsageAgreementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_usage_agreement(
    project_id: int,
    data: UsageAgreementCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    row = await project_service.create_agreement(
        db, project_id, data, current_user.active_tenant_id
    )
    return UsageAgreementResponse.from_row(row)


@router.delete(
    "/{project_id}/usage-agreements/{agreement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_project_usage_agreement(
    project_id: int,
    agreement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await project_service.delete_agreement(
        db, project_id, agreement_id, current_user.active_tenant_id
    )
