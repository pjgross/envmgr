# backend/app/services/custom_field_service.py
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.custom_field import CustomFieldDefinition
from app.api.v1.schemas.custom_field import (
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
)


def _slugify(label: str) -> str:
    """Convert a label to a snake_case field_key."""
    slug = label.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if slug and slug[0].isdigit():
        slug = "f_" + slug
    return slug or "field"


async def list_definitions(
    db: AsyncSession, tenant_id: int, entity_type: str
) -> list[CustomFieldDefinition]:
    result = await db.execute(
        select(CustomFieldDefinition)
        .where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == entity_type,
            CustomFieldDefinition.deleted_at.is_(None),
        )
        .order_by(CustomFieldDefinition.display_order, CustomFieldDefinition.id)
    )
    return list(result.scalars().all())


async def get_active_field_keys(
    db: AsyncSession, tenant_id: int, entity_type: str
) -> set[str]:
    """Return the set of field_key values for active (non-deleted) definitions."""
    result = await db.execute(
        select(CustomFieldDefinition.field_key).where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == entity_type,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    return set(result.scalars().all())


async def create_definition(
    db: AsyncSession, tenant_id: int, data: CustomFieldDefinitionCreate
) -> CustomFieldDefinition:
    field_key = data.field_key or _slugify(data.label)

    # Enforce unique (tenant_id, entity_type, field_key) among active definitions
    existing = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == data.entity_type,
            CustomFieldDefinition.field_key == field_key,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A field with key '{field_key}' already exists for this entity type",
        )

    definition = CustomFieldDefinition(
        tenant_id=tenant_id,
        entity_type=data.entity_type,
        entity_subtype=data.entity_subtype,
        field_key=field_key,
        label=data.label,
        field_type=data.field_type,
        required=data.required,
        display_order=data.display_order,
    )
    db.add(definition)
    await db.flush()
    await db.refresh(definition)
    return definition


async def update_definition(
    db: AsyncSession, tenant_id: int, definition_id: int, data: CustomFieldDefinitionUpdate
) -> CustomFieldDefinition:
    result = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.id == definition_id,
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    definition = result.scalar_one_or_none()
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field definition not found")

    if data.label is not None:
        definition.label = data.label
    if data.required is not None:
        definition.required = data.required
    if data.display_order is not None:
        definition.display_order = data.display_order
    # entity_subtype: explicit None is a legitimate update (widen scope), so
    # distinguish via model_fields_set rather than truthiness.
    if "entity_subtype" in data.model_fields_set:
        definition.entity_subtype = data.entity_subtype

    await db.flush()
    await db.refresh(definition)
    return definition


async def delete_definition(
    db: AsyncSession, tenant_id: int, definition_id: int
) -> None:
    result = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.id == definition_id,
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.deleted_at.is_(None),
        )
    )
    definition = result.scalar_one_or_none()
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field definition not found")

    definition.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def validate_custom_fields(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str,
    values: Optional[dict],
    visible_field_keys: Optional[set[str]] = None,
) -> None:
    """Validate custom_fields dict against active definitions for this tenant+entity_type.

    Raises HTTPException(422) if required fields are missing or types are wrong.
    Unknown keys are permitted (soft-deleted fields may still have stored values).
    If visible_field_keys is provided, required validation is only enforced for
    fields in that set (state-driven visibility supersedes required).
    """
    definitions = await list_definitions(db, tenant_id, entity_type)
    if not definitions:
        return

    values = values or {}

    for defn in definitions:
        if not defn.required:
            continue
        # Skip required check if field is not visible in current state
        if visible_field_keys is not None and defn.field_key not in visible_field_keys:
            continue
        val = values.get(defn.field_key)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Required custom field '{defn.label}' ({defn.field_key}) is missing",
            )

    for defn in definitions:
        val = values.get(defn.field_key)
        if val is None:
            continue
        if defn.field_type == "number":
            try:
                float(val)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Custom field '{defn.label}' ({defn.field_key}) must be a number",
                )
        elif defn.field_type == "boolean":
            if not isinstance(val, bool):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Custom field '{defn.label}' ({defn.field_key}) must be a boolean",
                )


async def list_definitions_for_subtype(
    db: AsyncSession,
    tenant_id: int,
    entity_type: str,
    subtype: Optional[str],
) -> list[CustomFieldDefinition]:
    """Return active definitions for entity_type where entity_subtype IS NULL
    OR (if subtype is not None) entity_subtype == subtype.

    When subtype is None, returns only unscoped ('applies to all') definitions.
    Ordered by display_order, id — matches list_definitions.
    """
    from sqlalchemy import or_

    conditions = [CustomFieldDefinition.entity_subtype.is_(None)]
    if subtype is not None:
        conditions.append(CustomFieldDefinition.entity_subtype == subtype)

    result = await db.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.tenant_id == tenant_id,
            CustomFieldDefinition.entity_type == entity_type,
            CustomFieldDefinition.deleted_at.is_(None),
            or_(*conditions),
        ).order_by(CustomFieldDefinition.display_order, CustomFieldDefinition.id)
    )
    return list(result.scalars().all())
