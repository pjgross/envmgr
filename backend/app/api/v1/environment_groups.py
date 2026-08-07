from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_group import (
    EnvironmentGroupCreate, EnvironmentGroupResponse, EnvironmentGroupUpdate,
    MemberCreate, MemberResponse,
)
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.services import environment_group_service

router = APIRouter()


@router.get("", response_model=list[EnvironmentGroupResponse])
async def list_environment_groups(
    response: Response,
    search: Optional[str] = Query(None, description="Case-insensitive name match."),
    is_active: Optional[bool] = Query(None),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(
        sorting(environment_group_service.ENVIRONMENT_GROUP_SORTS, default="name")
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readable by any tenant member — every booking form needs this picker."""
    views, total = await environment_group_service.list_groups(
        db, current_user.active_tenant_id,
        page=page, sort=sort, search=search, is_active=is_active,
    )
    set_total_count(response, total)
    return [EnvironmentGroupResponse.from_view(v) for v in views]


@router.post(
    "", response_model=EnvironmentGroupResponse, status_code=status.HTTP_201_CREATED
)
async def create_environment_group(
    data: EnvironmentGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await environment_group_service.create_group(
        db, data, current_user.active_tenant_id
    )
    return EnvironmentGroupResponse.from_view(view)


@router.get("/{group_id}", response_model=EnvironmentGroupResponse)
async def get_environment_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_group_service.get_group_view(
        db, group_id, current_user.active_tenant_id
    )
    return EnvironmentGroupResponse.from_view(view)


@router.patch("/{group_id}", response_model=EnvironmentGroupResponse)
async def update_environment_group(
    group_id: int,
    data: EnvironmentGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await environment_group_service.update_group(
        db, group_id, data, current_user.active_tenant_id
    )
    return EnvironmentGroupResponse.from_view(view)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_group_service.delete_group(
        db, group_id, current_user.active_tenant_id
    )


# ---------------------------------------------------------------------------
# Membership (group direction)
# ---------------------------------------------------------------------------


@router.get("/{group_id}/members", response_model=list[MemberResponse])
async def list_group_members(
    group_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readable by any tenant member — same split as the group CRUD."""
    rows, total = await environment_group_service.list_members(
        db, group_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [MemberResponse.from_row(r) for r in rows]


@router.post(
    "/{group_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_group_member(
    group_id: int,
    data: MemberCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    row = await environment_group_service.add_member(
        db, group_id, data, current_user.active_tenant_id
    )
    return MemberResponse.from_row(row)


@router.delete(
    "/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_group_member(
    group_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_group_service.remove_member(
        db, group_id, member_id, current_user.active_tenant_id
    )
