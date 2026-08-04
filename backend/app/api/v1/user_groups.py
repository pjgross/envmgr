from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.user_group import (
    UserGroupCreate,
    UserGroupResponse,
    UserGroupUpdate,
)
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.db.models.user_group import UserGroup
from app.services import user_group_service

router = APIRouter()

# `member_count` and `environment_count` are deliberately absent: both are
# computed by a correlated subquery, not backed by a single column, so neither
# can be sorted server-side. The grid marks those columns sortable: false.
USER_GROUP_SORTS = {
    "name": UserGroup.name,
    "created_at": UserGroup.created_at,
}


@router.get("/groups", response_model=list[UserGroupResponse])
async def list_user_groups(
    response: Response,
    search: Optional[str] = Query(None, description="Case-insensitive name match."),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(USER_GROUP_SORTS, default="name")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Every group for the tenant. Readable by any member — B3b needs every
    user to see which team operates an environment, and the environment form
    needs the list as its picker source."""
    views, total = await user_group_service.list_groups(
        db, current_user.active_tenant_id, page=page, sort=sort, search=search
    )
    set_total_count(response, total)
    return [UserGroupResponse.from_view(v) for v in views]


@router.post(
    "/groups", response_model=UserGroupResponse, status_code=status.HTTP_201_CREATED
)
async def create_user_group(
    data: UserGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await user_group_service.create_group(
        db, data, current_user.active_tenant_id
    )
    return UserGroupResponse.from_view(view)


@router.get("/groups/{group_id}", response_model=UserGroupResponse)
async def get_user_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """The group and its counts. The member list is a separate, bounded
    sub-resource — embedding it here would be an unbounded nested collection."""
    view = await user_group_service.get_group_view(
        db, group_id, current_user.active_tenant_id
    )
    return UserGroupResponse.from_view(view)


@router.patch("/groups/{group_id}", response_model=UserGroupResponse)
async def update_user_group(
    group_id: int,
    data: UserGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    view = await user_group_service.update_group(
        db, group_id, data, current_user.active_tenant_id
    )
    return UserGroupResponse.from_view(view)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await user_group_service.delete_group(
        db, group_id, current_user.active_tenant_id
    )
