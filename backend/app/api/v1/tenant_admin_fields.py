# backend/app/api/v1/tenant_admin_fields.py
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import require_tenant_admin
from app.services import custom_field_service
from app.api.v1.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
    CustomFieldDefinitionResponse,
)

router = APIRouter()


@router.get("/fields", response_model=list[CustomFieldDefinitionResponse])
async def list_fields(
    entity_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.list_definitions(db, current_user.active_tenant_id, entity_type)


@router.post("/fields", response_model=CustomFieldDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_field(
    data: CustomFieldDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.create_definition(db, current_user.active_tenant_id, data)


@router.patch("/fields/{field_id}", response_model=CustomFieldDefinitionResponse)
async def update_field(
    field_id: int,
    data: CustomFieldDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await custom_field_service.update_definition(db, current_user.active_tenant_id, field_id, data)


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(
    field_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await custom_field_service.delete_definition(db, current_user.active_tenant_id, field_id)
