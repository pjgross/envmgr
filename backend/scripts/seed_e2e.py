"""
Seed the E2E test database with a fresh test tenant and user.

Run before starting the E2E backend:
    DATABASE_URL=sqlite+aiosqlite:///./e2e_test.db python scripts/seed_e2e.py

Credentials seeded:
    tenant_slug : e2e
    username    : e2eadmin
    password    : e2epassword123
    role        : Admin
"""
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.db.base import Base
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./e2e_test.db")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL)

    # Drop and recreate tables for a clean slate
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        tenant = Tenant(name="E2E Test Org", slug="e2e")
        session.add(tenant)
        await session.flush()

        user = User(
            tenant_id=tenant.id,
            username="e2eadmin",
            email="e2e@test.com",
            password_hash=get_password_hash("e2epassword123"),
            role="Admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()

    await engine.dispose()
    print("✓ E2E database seeded: tenant=e2e, user=e2eadmin, password=e2epassword123")


asyncio.run(main())
