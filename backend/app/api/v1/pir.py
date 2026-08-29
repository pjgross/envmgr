"""PIR (Post-Implementation Review) endpoints — one PIR per release.

Routes: /releases/{release_id}/pir  (GET / POST / PATCH / DELETE)
"""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import pir_service, pir_finding_service
from app.api.v1.schemas.pir import PIRCreate, PIRUpdate, PIRResponse
from app.api.v1.schemas.pir_finding import (
    PirFindingCreate,
    PirFindingResponse,
    PirFindingUpdate,
)

router = APIRouter(prefix="/releases", tags=["pir"])


async def _hydrate(db: AsyncSession, tenant_id: int, pir):
    """One PIR with its findings, built once so every route returns the same shape."""
    if pir is None:
        return None
    body = PIRResponse.model_validate(pir).model_dump()
    body["findings"] = [
        PirFindingResponse.model_validate(f).model_dump()
        for f in await pir_finding_service.findings_for_pir(db, tenant_id, pir.id)
    ]
    return body


@router.get("/{release_id}/pir", response_model=PIRResponse | None)
async def get_pir(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    return await _hydrate(db, tenant_id, await pir_service.get_for_release(db, tenant_id, release_id))


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


@router.post("/{release_id}/pir/findings", response_model=PirFindingResponse,
             status_code=status.HTTP_201_CREATED)
async def create_finding(
    release_id: int,
    data: PirFindingCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    return await pir_finding_service.create_finding(db, tenant_id, pir, data, current_user.id)


@router.patch("/{release_id}/pir/findings/{finding_id}", response_model=PirFindingResponse)
async def update_finding(
    release_id: int,
    finding_id: int,
    data: PirFindingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    return await pir_finding_service.update_finding(db, tenant_id, finding_id, data)


@router.delete("/{release_id}/pir/findings/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_finding(
    release_id: int,
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    await pir_finding_service.delete_finding(db, tenant_id, finding_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
