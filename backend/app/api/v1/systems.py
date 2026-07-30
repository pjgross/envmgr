from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.services import system_service
from app.core.pagination import Page, pagination, set_total_count
from app.api.v1.schemas.system import (
    SystemCreate,
    SystemUpdate,
    SystemResponse,
    SubSystemCreate,
    SubSystemUpdate,
    SubSystemResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# System endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[SystemResponse])
async def list_systems(
    response: Response,
    page: Page = Depends(pagination),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await system_service.list_systems(
        db, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return rows


@router.post("/", response_model=SystemResponse, status_code=status.HTTP_201_CREATED)
async def create_system(
    data: SystemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.create_system(db, data, current_user.active_tenant_id)


@router.get("/{system_id}", response_model=SystemResponse)
async def get_system(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await system_service.get_system(db, system_id, current_user.active_tenant_id)


@router.patch("/{system_id}", response_model=SystemResponse)
async def update_system(
    system_id: int,
    data: SystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.update_system(db, system_id, data, current_user.active_tenant_id)


@router.delete("/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await system_service.delete_system(db, system_id, current_user.active_tenant_id)


# ---------------------------------------------------------------------------
# SubSystem endpoints
# ---------------------------------------------------------------------------


@router.get("/{system_id}/subsystems", response_model=list[SubSystemResponse])
async def list_subsystems(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await system_service.list_subsystems(db, system_id, current_user.active_tenant_id)


@router.post(
    "/{system_id}/subsystems",
    response_model=SubSystemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subsystem(
    system_id: int,
    data: SubSystemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.create_subsystem(
        db, system_id, data, current_user.active_tenant_id
    )


@router.get("/{system_id}/subsystems/{sub_id}", response_model=SubSystemResponse)
async def get_subsystem(
    system_id: int,
    sub_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await system_service.get_subsystem(
        db, sub_id, system_id, current_user.active_tenant_id
    )


@router.patch("/{system_id}/subsystems/{sub_id}", response_model=SubSystemResponse)
async def update_subsystem(
    system_id: int,
    sub_id: int,
    data: SubSystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await system_service.update_subsystem(
        db, sub_id, system_id, data, current_user.active_tenant_id
    )


@router.delete("/{system_id}/subsystems/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subsystem(
    system_id: int,
    sub_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await system_service.delete_subsystem(
        db, sub_id, system_id, current_user.active_tenant_id
    )
