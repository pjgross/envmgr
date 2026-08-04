from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.db.models.user import User
from app.services import docker_compose_import_service, excel_import_service, terraform_import_service
from app.api.v1.schemas.version import ImportResult

router = APIRouter()


class DockerComposeImportResponse(BaseModel):
    subsystems_created: int
    subsystems_updated: int
    dependencies_created: int


@router.post("/environments", response_model=ImportResult)
async def import_environments_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_admin()),
):
    """Import environments from an Excel (.xlsx) file."""
    file_bytes = await file.read()
    result = await excel_import_service.import_environments(
        db, file_bytes, current_user.active_tenant_id, current_user.id
    )
    return result


@router.post("/systems", response_model=ImportResult)
async def import_systems_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_admin()),
):
    """Import systems from an Excel (.xlsx) file."""
    file_bytes = await file.read()
    result = await excel_import_service.import_systems(
        db, file_bytes, current_user.active_tenant_id
    )
    return result


@router.post("/docker-compose", response_model=DockerComposeImportResponse)
async def import_docker_compose_endpoint(
    system_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(require_tenant_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Import a docker-compose.yml file, creating/updating subsystems and dependencies."""
    from app.services.system_service import get_system

    await get_system(db, system_id, current_user.active_tenant_id)

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
    try:
        result = await docker_compose_import_service.import_docker_compose(
            system_id=system_id,
            tenant_id=current_user.active_tenant_id,
            content=content,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    return result


class TerraformImportResponse(BaseModel):
    subsystems_created: int
    subsystems_updated: int


@router.post("/terraform", response_model=TerraformImportResponse)
async def import_terraform_endpoint(
    system_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(require_tenant_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Import a .tfstate file, creating/updating SubSystems from Terraform resources.
    Note: Dependencies are not imported (tfstate has no explicit dependency graph)."""
    from app.services.system_service import get_system

    await get_system(db, system_id, current_user.active_tenant_id)

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")

    try:
        result = await terraform_import_service.import_terraform(
            system_id=system_id,
            tenant_id=current_user.active_tenant_id,
            content=content,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    return result
