"""Backfill: seed the default incident lifecycle template for every existing tenant.

Run once after the incident-tables migration lands (tenants created before Phase 5
SP1 never ran the incident seed in tenant_service.create_tenant, so they cannot
create incidents until this backfill runs). Idempotent — skips tenants that already
have the "Default Incident Lifecycle" template.

Usage:
    cd backend
    uv run python scripts/backfill_incident_lifecycles.py
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.user import Tenant
from app.services import incident_defaults


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        for t in tenants:
            await incident_defaults.seed_incident_defaults_for_tenant(db, t.id)
        await db.commit()
    await engine.dispose()
    print(f"Seeded default incident lifecycle template for {len(tenants)} tenants.")


if __name__ == "__main__":
    asyncio.run(main())
