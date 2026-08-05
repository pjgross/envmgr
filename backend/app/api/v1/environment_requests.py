from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_request import (
    EnvironmentRequestCreate,
    EnvironmentRequestResponse,
    EnvironmentRequestUpdate,
)
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
