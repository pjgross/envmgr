from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.services import booking_lifecycle_service, booking_type_service
from app.api.v1.schemas.booking_lifecycle import (
    LifecycleTemplateCreate, LifecycleTemplateUpdate, LifecycleTemplateCopy,
    LifecycleTemplateResponse, BookingTypeCreate, BookingTypeUpdate, BookingTypeResponse,
)

router = APIRouter()


# ── Lifecycle Templates ──────────────────────────────────────────────────────

@router.get("/lifecycle-templates", response_model=list[LifecycleTemplateResponse])
async def list_lifecycle_templates(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_lifecycle_service.list_templates(db, current_user.active_tenant_id)


@router.post("/lifecycle-templates", response_model=LifecycleTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_lifecycle_template(
    data: LifecycleTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_lifecycle_service.create_template(db, data, current_user.active_tenant_id)


@router.get("/lifecycle-templates/{template_id}", response_model=LifecycleTemplateResponse)
async def get_lifecycle_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_lifecycle_service.get_template(db, template_id, current_user.active_tenant_id)


@router.put("/lifecycle-templates/{template_id}", response_model=LifecycleTemplateResponse)
async def update_lifecycle_template(
    template_id: int,
    data: LifecycleTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_lifecycle_service.update_template(db, template_id, data, current_user.active_tenant_id)


@router.post("/lifecycle-templates/{template_id}/copy", response_model=LifecycleTemplateResponse, status_code=status.HTTP_201_CREATED)
async def copy_lifecycle_template(
    template_id: int,
    data: LifecycleTemplateCopy,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_lifecycle_service.copy_template(db, template_id, data.name, current_user.active_tenant_id)


# ── Booking Types ────────────────────────────────────────────────────────────

@router.get("/booking-types", response_model=list[BookingTypeResponse])
async def list_booking_types(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_type_service.list_types(db, current_user.active_tenant_id)


@router.post("/booking-types", response_model=BookingTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_booking_type(
    data: BookingTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_type_service.create_type(db, data, current_user.active_tenant_id)


@router.get("/booking-types/{type_id}", response_model=BookingTypeResponse)
async def get_booking_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await booking_type_service.get_type(db, type_id, current_user.active_tenant_id)


@router.put("/booking-types/{type_id}", response_model=BookingTypeResponse)
async def update_booking_type(
    type_id: int,
    data: BookingTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await booking_type_service.update_type(db, type_id, data, current_user.active_tenant_id)
