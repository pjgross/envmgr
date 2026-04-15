from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.services import component_type_service
from app.api.v1.schemas.component_type import (
    ComponentTypeDefinitionCreate,
    ComponentTypeDefinitionUpdate,
    ComponentTypeDefinitionResponse,
)

router = APIRouter()


@router.get("/", response_model=list[ComponentTypeDefinitionResponse])
async def list_component_types(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await component_type_service.list_definitions(db, current_user.active_tenant_id)


@router.post("/", response_model=ComponentTypeDefinitionResponse, status_code=status.HTTP_201_CREATED)
async def create_component_type(
    data: ComponentTypeDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await component_type_service.create_definition(db, data, current_user.active_tenant_id)


@router.get("/{definition_id}", response_model=ComponentTypeDefinitionResponse)
async def get_component_type(
    definition_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await component_type_service.get_definition(db, definition_id, current_user.active_tenant_id)


@router.patch("/{definition_id}", response_model=ComponentTypeDefinitionResponse)
async def update_component_type(
    definition_id: int,
    data: ComponentTypeDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await component_type_service.update_definition(db, definition_id, data, current_user.active_tenant_id)


@router.delete("/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_component_type(
    definition_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await component_type_service.delete_definition(db, definition_id, current_user.active_tenant_id)
