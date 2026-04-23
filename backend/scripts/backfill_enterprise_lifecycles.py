"""Backfill: seed the enterprise lifecycle template for every existing tenant.

Run once after migration p3s6enterprise lands. Idempotent — skips tenants that
already have the "Enterprise Release — default" lifecycle template.

Usage:
    cd backend
    uv run python scripts/backfill_enterprise_lifecycles.py
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.user import Tenant
from app.services import release_defaults


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        for t in tenants:
            await release_defaults.seed_release_defaults_for_tenant(db, t.id)
        await db.commit()
    await engine.dispose()
    print(f"Seeded enterprise lifecycle template for {len(tenants)} tenants.")


if __name__ == "__main__":
    asyncio.run(main())
