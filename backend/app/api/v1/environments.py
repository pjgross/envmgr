from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Response, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.pagination import Page, pagination, set_total_count
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.environment import EnvironmentStatus
from app.services import environment_service, environment_system_service
from app.services import version_service, change_request_service
from app.api.v1.schemas.environment import (
    EnvironmentCreate,
    EnvironmentUpdate,
    EnvironmentResponse,
    EnvironmentSystemCreate,
    EnvironmentSystemUpdate,
    EnvironmentSystemResponse,
    EnvironmentSystemsResponse,
    EnvironmentSubsystemResponse,
    EnvironmentSubsystemUpdate,
    EnvironmentTopologyResponse,
)
from app.api.v1.schemas.dependency import VerifyResponse
from app.api.v1.schemas.version import VersionCreate, VersionUpdate, VersionResponse
from app.api.v1.schemas.schedule import EnvironmentScheduleResponse
from app.api.v1.schemas.infrastructure_component import (
    EnvironmentSubSystemHostResponse,
    EnvironmentSubSystemHostsResponse,
    HostAttachment,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Environment endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[EnvironmentResponse])
async def list_environments(
    response: Response,
    status: Optional[EnvironmentStatus] = None,
    environment_type: Optional[str] = None,
    page: Page = Depends(pagination),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await environment_service.list_environments(
        db,
        current_user.active_tenant_id,
        status_filter=status,
        environment_type=environment_type,
        page=page,
    )
    set_total_count(response, total)
    return rows


@router.post("/", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    data: EnvironmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_service.create_environment(db, data, current_user.active_tenant_id)


@router.get("/{env_id}", response_model=EnvironmentResponse)
async def get_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_service.get_environment(db, env_id, current_user.active_tenant_id)


@router.patch("/{env_id}", response_model=EnvironmentResponse)
async def update_environment(
    env_id: int,
    data: EnvironmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_service.update_environment(
        db, env_id, data, current_user.active_tenant_id
    )


@router.delete("/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_service.delete_environment(db, env_id, current_user.active_tenant_id)


@router.get("/{env_id}/verify", response_model=VerifyResponse)
async def verify_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_service.verify_environment(
        db, env_id, current_user.active_tenant_id
    )


@router.get("/{env_id}/schedule", response_model=EnvironmentScheduleResponse)
async def get_environment_schedule(
    env_id: int,
    start_date: datetime = Query(..., description="Window start (inclusive)"),
    end_date: datetime = Query(..., description="Window end (exclusive)"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Unified schedule for `env_id`: bookings + change requests overlapping
    the date range. `deployments` is reserved for Phase 4 (always `[]` today).
    """
    return await change_request_service.get_environment_schedule(
        db,
        env_id,
        current_user.active_tenant_id,
        start_date,
        end_date,
    )


# ---------------------------------------------------------------------------
# EnvironmentSystem endpoints
# ---------------------------------------------------------------------------


@router.get("/{env_id}/systems", response_model=EnvironmentSystemsResponse)
async def list_systems_in_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_system_service.list_systems_in_environment(
        db, env_id, current_user.active_tenant_id
    )


@router.post(
    "/{env_id}/systems",
    response_model=EnvironmentSystemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_system_to_environment(
    env_id: int,
    data: EnvironmentSystemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_system_service.add_system_to_environment(
        db, env_id, data, current_user.active_tenant_id
    )


@router.patch("/{env_id}/systems/{system_id}", response_model=EnvironmentSystemResponse)
async def update_system_in_environment(
    env_id: int,
    system_id: int,
    data: EnvironmentSystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_system_service.update_system_in_environment(
        db, env_id, system_id, data, current_user.active_tenant_id
    )


@router.delete("/{env_id}/systems/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_system_from_environment(
    env_id: int,
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await environment_system_service.remove_system_from_environment(
        db, env_id, system_id, current_user.active_tenant_id
    )


# ---------------------------------------------------------------------------
# EnvironmentSubSystem endpoints
# ---------------------------------------------------------------------------


@router.get("/{env_id}/subsystems", response_model=list[EnvironmentSubsystemResponse])
async def list_environment_subsystems(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_system_service.get_environment_subsystems(
        db, env_id, current_user.active_tenant_id
    )


@router.patch("/{env_id}/subsystems/{subsystem_id}", response_model=EnvironmentSubsystemResponse)
async def update_environment_subsystem(
    env_id: int,
    subsystem_id: int,
    data: EnvironmentSubsystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_system_service.update_environment_subsystem(
        db, env_id, subsystem_id, data, current_user.active_tenant_id
    )


# ---------------------------------------------------------------------------
# EnvironmentSubSystem host attachments
# ---------------------------------------------------------------------------


@router.get(
    "/{env_id}/subsystems/{subsystem_id}/hosts",
    response_model=EnvironmentSubSystemHostsResponse,
)
async def list_env_subsystem_hosts(
    env_id: int,
    subsystem_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    hosts = await environment_system_service.list_env_subsystem_hosts(
        db, env_id, subsystem_id, current_user.active_tenant_id
    )
    return EnvironmentSubSystemHostsResponse(hosts=hosts)


@router.put(
    "/{env_id}/subsystems/{subsystem_id}/hosts",
    response_model=EnvironmentSubSystemHostsResponse,
)
async def set_env_subsystem_hosts(
    env_id: int,
    subsystem_id: int,
    attachments: list[HostAttachment],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    hosts = await environment_system_service.set_env_subsystem_hosts(
        db, env_id, subsystem_id, attachments, current_user.active_tenant_id
    )
    return EnvironmentSubSystemHostsResponse(hosts=hosts)


# ---------------------------------------------------------------------------
# Environment Topology
# ---------------------------------------------------------------------------


@router.get("/{env_id}/topology", response_model=EnvironmentTopologyResponse)
async def get_environment_topology(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_service.get_environment_topology(
        db, env_id, current_user.active_tenant_id
    )


# ---------------------------------------------------------------------------
# Version endpoints
# ---------------------------------------------------------------------------


@router.get("/{env_id}/versions", response_model=list[VersionResponse])
async def list_versions(
    env_id: int,
    current_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    versions = await version_service.list_versions(
        db, env_id, current_user.active_tenant_id, current_only=current_only
    )
    return [VersionResponse.from_orm_with_name(v) for v in versions]


@router.post(
    "/{env_id}/versions",
    response_model=VersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_version(
    env_id: int,
    data: VersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    version = await version_service.record_version(
        db, env_id, data, current_user.active_tenant_id
    )
    return VersionResponse.from_orm_with_name(version)


@router.patch("/{env_id}/versions/{version_id}", response_model=VersionResponse)
async def update_version(
    env_id: int,
    version_id: int,
    data: VersionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    version = await version_service.update_version(db, version_id, env_id, current_user.active_tenant_id, data)
    return VersionResponse.from_orm_with_name(version)


@router.delete("/{env_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_version(
    env_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await version_service.delete_version(db, version_id, env_id, current_user.active_tenant_id)
