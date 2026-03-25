import copy
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking_lifecycle import BookingLifecycleTemplate, BookingType
from app.api.v1.schemas.booking_lifecycle import (
    LifecycleDefinition, LifecycleTemplateCreate, LifecycleTemplateUpdate,
)


async def create_template(
    db: AsyncSession, data: LifecycleTemplateCreate, tenant_id: int
) -> BookingLifecycleTemplate:
    # Validate JSONB definition via Pydantic (raises ValidationError -> 422)
    LifecycleDefinition.model_validate(data.definition.model_dump())
    template = BookingLifecycleTemplate(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        is_default=data.is_default,
        definition=data.definition.model_dump(),
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def list_templates(db: AsyncSession, tenant_id: int) -> list[BookingLifecycleTemplate]:
    result = await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.tenant_id == tenant_id,
            BookingLifecycleTemplate.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def get_template(
    db: AsyncSession, template_id: int, tenant_id: int
) -> BookingLifecycleTemplate:
    result = await db.execute(
        select(BookingLifecycleTemplate).where(
            BookingLifecycleTemplate.id == template_id,
            BookingLifecycleTemplate.tenant_id == tenant_id,
            BookingLifecycleTemplate.deleted_at.is_(None),
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lifecycle template not found")
    return template


async def update_template(
    db: AsyncSession, template_id: int, data: LifecycleTemplateUpdate, tenant_id: int
) -> BookingLifecycleTemplate:
    template = await get_template(db, template_id, tenant_id)
    if data.name is not None:
        template.name = data.name
    if data.description is not None:
        template.description = data.description
    if data.is_default is not None:
        template.is_default = data.is_default
    if data.definition is not None:
        LifecycleDefinition.model_validate(data.definition.model_dump())
        template.definition = data.definition.model_dump()
    await db.flush()
    await db.refresh(template)
    return template


async def copy_template(
    db: AsyncSession, template_id: int, new_name: str, tenant_id: int
) -> BookingLifecycleTemplate:
    original = await get_template(db, template_id, tenant_id)
    new_template = BookingLifecycleTemplate(
        tenant_id=tenant_id,
        name=new_name,
        description=original.description,
        is_default=False,
        definition=copy.deepcopy(original.definition),
    )
    db.add(new_template)
    await db.flush()
    await db.refresh(new_template)
    return new_template


def validate_transition(definition: dict, from_state: str, to_state: str, user_role: str) -> bool:
    """Return True if the transition is allowed for this role."""
    for t in definition.get("transitions", []):
        if t["from_state"] == from_state and t["to_state"] == to_state:
            return user_role in t["allowed_roles"]
    return False


def get_allowed_transitions(definition: dict, current_state: str, user_role: str) -> list[dict]:
    """Return all transitions from current_state that this role can make."""
    return [
        t for t in definition.get("transitions", [])
        if t["from_state"] == current_state and user_role in t["allowed_roles"]
    ]


def get_editable_fields(definition: dict, current_state: str, user_role: str) -> list[str]:
    """Return fields editable in this state for this role. Fail-closed (empty list) if state not defined."""
    perm = definition.get("field_permissions", {}).get(current_state)
    if not perm:
        return []
    if user_role not in perm.get("editable_by", []):
        return []
    return perm.get("editable_fields", [])
