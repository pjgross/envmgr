"""
Seed the master admin user into the dev database.

Run after migrations:
    cd backend
    DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr PYTHONPATH=. uv run python scripts/seed_master_admin.py

Credentials seeded:
    tenant_slug : system
    username    : masteradmin
    password    : masteradmin123
    role        : Admin
    is_master_admin: True
"""
import asyncio
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.db.models.user import Tenant, User
from app.core.security import get_password_hash

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr"
)

async def main() -> None:
    engine = create_async_engine(DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        # Upsert system tenant
        result = await session.execute(select(Tenant).where(Tenant.slug == "system"))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(name="System", slug="system", is_active=True)
            session.add(tenant)
            await session.flush()
            print("✓ Created system tenant")
        else:
            print("✓ System tenant already exists")

        # Upsert master admin user
        result = await session.execute(
            select(User).where(User.username == "masteradmin", User.tenant_id == tenant.id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                tenant_id=tenant.id,
                username="masteradmin",
                email="masteradmin@system.internal",
                password_hash=get_password_hash("masteradmin123"),
                role="Admin",
                is_master_admin=True,
                is_active=True,
            )
            session.add(user)
            print("✓ Created master admin user")
        else:
            print("✓ Master admin user already exists")

        await session.commit()

    await engine.dispose()
    print("\nMaster admin credentials:")
    print("  tenant_slug : system")
    print("  username    : masteradmin")
    print("  password    : masteradmin123")

asyncio.run(main())
