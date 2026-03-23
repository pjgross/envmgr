from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import require_tenant_admin
from app.db.models.user import User
from app.services import excel_import_service
from app.api.v1.schemas.version import ImportResult

router = APIRouter()


@router.post("/environments", response_model=ImportResult)
async def import_environments_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_admin()),
):
    """Import environments from an Excel (.xlsx) file."""
    file_bytes = await file.read()
    result = await excel_import_service.import_environments(
        db, file_bytes, current_user.active_tenant_id
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
