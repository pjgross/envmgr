from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_request import (
    EnvironmentRequestCreate,
    EnvironmentRequestResponse,
    EnvironmentRequestTransition,
    EnvironmentRequestUpdate,
)
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user
from app.db.base import get_db
from app.services import environment_request_service

router = APIRouter()


@router.post(
    "", response_model=EnvironmentRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment_request(
    data: EnvironmentRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Any tenant member may raise a request — including a Viewer, who is the
    person most likely to need access."""
    view = await environment_request_service.create_request(
        db, data, current_user.id, current_user.active_tenant_id
    )
    return EnvironmentRequestResponse.from_view(view)


@router.get("", response_model=list[EnvironmentRequestResponse])
async def list_environment_requests(
    response: Response,
    status_filter: Optional[str] = Query(None, alias="status"),
    kind: Optional[str] = Query(None),
    environment_id: Optional[int] = Query(None),
    mine: bool = Query(False, description="Only requests I raised."),
    actionable: bool = Query(False, description="Only requests my team must action."),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(
        sorting(environment_request_service.REQUEST_SORTS, default="created_at",
                default_dir="desc")
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Readable by any tenant member. Only transitions are gated."""
    views, total = await environment_request_service.list_requests(
        db,
        current_user.active_tenant_id,
        page=page,
        sort=sort,
        status_filter=status_filter,
        kind=kind,
        environment_id=environment_id,
        mine_for_user_id=current_user.id if mine else None,
        actionable_for=(
            (current_user.id, current_user.role == "Admin") if actionable else None
        ),
    )
    set_total_count(response, total)
    return [EnvironmentRequestResponse.from_view(v) for v in views]


@router.get("/{request_id}", response_model=EnvironmentRequestResponse)
async def get_environment_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_request_service.get_request_view(
        db, request_id, current_user.active_tenant_id
    )
    return EnvironmentRequestResponse.from_view(view)


@router.patch("/{request_id}", response_model=EnvironmentRequestResponse)
async def update_environment_request(
    request_id: int,
    data: EnvironmentRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_request_service.update_request(
        db, request_id, data, current_user, current_user.active_tenant_id
    )
    return EnvironmentRequestResponse.from_view(view)


@router.post("/{request_id}/transition", response_model=EnvironmentRequestResponse)
async def transition_environment_request(
    request_id: int,
    data: EnvironmentRequestTransition,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    view = await environment_request_service.transition(
        db, request_id, data.to_state, current_user,
        current_user.active_tenant_id,
    )
    return EnvironmentRequestResponse.from_view(view)


@router.get("/{request_id}/allowed-transitions")
async def get_allowed_transitions(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_request_service.allowed_transitions(
        db, request_id, current_user, current_user.active_tenant_id
    )
