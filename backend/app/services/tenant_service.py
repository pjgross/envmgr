from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import Tenant
from app.api.v1.schemas import TenantCreate, TenantUpdate
from app.services import change_request_service, scope_change_rule_service, raid_config_service
from app.services.release_defaults import seed_release_defaults_for_tenant


async def list_tenants(db: AsyncSession) -> list[Tenant]:
    result = await db.execute(select(Tenant).order_by(Tenant.name))
    return list(result.scalars().all())


async def get_tenant(db: AsyncSession, tenant_id: int) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


async def create_tenant(db: AsyncSession, data: TenantCreate) -> Tenant:
    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tenant slug already exists")
    tenant = Tenant(name=data.name, slug=data.slug, settings=data.settings)
    db.add(tenant)
    await db.flush()
    # Seed default change-request lifecycles so admins have something to link
    # change requests to out of the box.
    await change_request_service.seed_default_lifecycles(db, tenant.id)
    # Seed default release lifecycle templates + event types.
    await seed_release_defaults_for_tenant(db, tenant.id)
    # Seed default scope-change-kind rules (story=True, others=False).
    await scope_change_rule_service.seed_default_rules(db, tenant.id)
    # Seed default RAID probability/impact scales and RAG bands.
    await raid_config_service.seed_default_config(db, tenant.id)
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def update_tenant(db: AsyncSession, tenant_id: int, data: TenantUpdate) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    if data.name is not None:
        tenant.name = data.name
    if data.slug is not None:
        tenant.slug = data.slug
    if data.settings is not None:
        tenant.settings = data.settings
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def disable_tenant(db: AsyncSession, tenant_id: int) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    tenant.is_active = False
    await db.commit()
    await db.refresh(tenant)
    return tenant
