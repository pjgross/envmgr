from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking_lifecycle import BookingType
from app.api.v1.schemas.booking_lifecycle import BookingTypeCreate, BookingTypeUpdate
from app.services.booking_lifecycle_service import get_template


async def create_type(
    db: AsyncSession, data: BookingTypeCreate, tenant_id: int
) -> BookingType:
    # Verify template belongs to this tenant
    await get_template(db, data.lifecycle_template_id, tenant_id)
    bt = BookingType(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        lifecycle_template_id=data.lifecycle_template_id,
        color=data.color,
        is_active=data.is_active,
    )
    db.add(bt)
    await db.flush()
    await db.refresh(bt)
    return bt


async def list_types(db: AsyncSession, tenant_id: int) -> list[BookingType]:
    result = await db.execute(
        select(BookingType).where(
            BookingType.tenant_id == tenant_id,
            BookingType.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def get_type(db: AsyncSession, type_id: int, tenant_id: int) -> BookingType:
    result = await db.execute(
        select(BookingType).where(
            BookingType.id == type_id,
            BookingType.tenant_id == tenant_id,
            BookingType.deleted_at.is_(None),
        )
    )
    bt = result.scalar_one_or_none()
    if not bt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking type not found")
    return bt


async def update_type(
    db: AsyncSession, type_id: int, data: BookingTypeUpdate, tenant_id: int
) -> BookingType:
    bt = await get_type(db, type_id, tenant_id)
    if data.name is not None:
        bt.name = data.name
    if data.description is not None:
        bt.description = data.description
    if data.lifecycle_template_id is not None:
        await get_template(db, data.lifecycle_template_id, tenant_id)
        bt.lifecycle_template_id = data.lifecycle_template_id
    if data.color is not None:
        bt.color = data.color
    if data.is_active is not None:
        bt.is_active = data.is_active
    await db.flush()
    await db.refresh(bt)
    return bt
