from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.component_type import ComponentTypeDefinition
from app.api.v1.schemas.component_type import (
    ComponentTypeDefinitionCreate,
    ComponentTypeDefinitionUpdate,
)


async def list_definitions(
    db: AsyncSession, tenant_id: int
) -> list[ComponentTypeDefinition]:
    result = await db.execute(
        select(ComponentTypeDefinition)
        .where(
            ComponentTypeDefinition.tenant_id == tenant_id,
            ComponentTypeDefinition.deleted_at.is_(None),
        )
        .order_by(ComponentTypeDefinition.name)
    )
    return list(result.scalars().all())


async def get_definition(
    db: AsyncSession, definition_id: int, tenant_id: int
) -> ComponentTypeDefinition:
    result = await db.execute(
        select(ComponentTypeDefinition).where(
            ComponentTypeDefinition.id == definition_id,
            ComponentTypeDefinition.tenant_id == tenant_id,
            ComponentTypeDefinition.deleted_at.is_(None),
        )
    )
    definition = result.scalar_one_or_none()
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Component type definition not found",
        )
    return definition


async def create_definition(
    db: AsyncSession,
    data: ComponentTypeDefinitionCreate,
    tenant_id: int,
) -> ComponentTypeDefinition:
    # Check name uniqueness within tenant
    existing = await db.execute(
        select(ComponentTypeDefinition).where(
            ComponentTypeDefinition.name == data.name,
            ComponentTypeDefinition.tenant_id == tenant_id,
            ComponentTypeDefinition.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A component type with this name already exists in this tenant",
        )

    definition = ComponentTypeDefinition(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        category=data.category,
        icon=data.icon,
        field_definitions=[f.model_dump() for f in data.field_definitions] if data.field_definitions else None,
    )
    db.add(definition)
    await db.flush()
    await db.refresh(definition)
    return definition


async def update_definition(
    db: AsyncSession,
    definition_id: int,
    data: ComponentTypeDefinitionUpdate,
    tenant_id: int,
) -> ComponentTypeDefinition:
    definition = await get_definition(db, definition_id, tenant_id)

    if data.name is not None and data.name != definition.name:
        existing = await db.execute(
            select(ComponentTypeDefinition).where(
                ComponentTypeDefinition.name == data.name,
                ComponentTypeDefinition.tenant_id == tenant_id,
                ComponentTypeDefinition.id != definition_id,
                ComponentTypeDefinition.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A component type with this name already exists in this tenant",
            )

    update_data = data.model_dump(exclude_unset=True)
    if "field_definitions" in update_data and update_data["field_definitions"] is not None:
        update_data["field_definitions"] = [
            f.model_dump() if hasattr(f, "model_dump") else f
            for f in data.field_definitions
        ]
    for field, value in update_data.items():
        setattr(definition, field, value)

    await db.flush()
    await db.refresh(definition)
    return definition


async def delete_definition(
    db: AsyncSession, definition_id: int, tenant_id: int
) -> None:
    definition = await get_definition(db, definition_id, tenant_id)
    definition.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def validate_fields_against_type(
    db: AsyncSession,
    tenant_id: int,
    component_type_definition_id: int,
    custom_fields: Optional[dict],
) -> None:
    """Validate custom_fields against a component type's field definitions."""
    definition = await get_definition(db, component_type_definition_id, tenant_id)

    if not definition.field_definitions:
        return

    fields = custom_fields or {}

    for field_def in definition.field_definitions:
        key = field_def["field_key"]
        required = field_def.get("required", False)
        field_type = field_def.get("field_type", "text")

        if required and (key not in fields or fields[key] is None or fields[key] == ""):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Required field '{field_def['label']}' ({key}) is missing",
            )

        if key in fields and fields[key] is not None:
            value = fields[key]
            if field_type == "number" and not isinstance(value, (int, float)):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Field '{field_def['label']}' ({key}) must be a number",
                )
            if field_type == "boolean" and not isinstance(value, bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Field '{field_def['label']}' ({key}) must be a boolean",
                )
            if field_type == "text" and not isinstance(value, str):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Field '{field_def['label']}' ({key}) must be a string",
                )
