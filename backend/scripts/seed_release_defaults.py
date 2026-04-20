"""Idempotently seed Phase 3 release defaults for every existing tenant."""
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.user import Tenant
from app.services.release_defaults import seed_release_defaults_for_tenant


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as db:
        tenants = (await db.execute(select(Tenant))).scalars().all()
        for t in tenants:
            await seed_release_defaults_for_tenant(db, t.id)
        await db.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
