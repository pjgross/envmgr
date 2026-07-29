"""PIR (Post-Implementation Review) endpoints — one PIR per release.

Routes: /releases/{release_id}/pir  (GET / POST / PATCH / DELETE)
"""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import pir_service
from app.api.v1.schemas.pir import PIRCreate, PIRUpdate, PIRResponse

router = APIRouter(prefix="/releases", tags=["pir"])


@router.get("/{release_id}/pir", response_model=PIRResponse | None)
async def get_pir(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await pir_service.get_for_release(db, current_user.active_tenant_id, release_id)


@router.post("/{release_id}/pir", response_model=PIRResponse, status_code=status.HTTP_201_CREATED)
async def create_pir(
    release_id: int,
    data: PIRCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await pir_service.create_for_release(
        db, current_user.active_tenant_id, release_id, data, current_user.id
    )


@router.patch("/{release_id}/pir", response_model=PIRResponse)
async def update_pir(
    release_id: int,
    data: PIRUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await pir_service.update(db, current_user.active_tenant_id, release_id, data)


@router.delete("/{release_id}/pir", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pir(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await pir_service.delete(db, current_user.active_tenant_id, release_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
