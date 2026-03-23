from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.api.v1.schemas import UserAdminCreate, UserAdminUpdate
from app.core.security import get_password_hash, Role


async def list_users(db: AsyncSession, tenant_id: int) -> list[User]:
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
    )
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: int, tenant_id: int) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def create_user_in_tenant(db: AsyncSession, tenant_id: int, data: UserAdminCreate) -> User:
    # Check username uniqueness per tenant
    existing_username = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.username == data.username, User.deleted_at.is_(None))
    )
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists in this tenant")
    # Check email uniqueness per tenant
    existing_email = await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.email == data.email, User.deleted_at.is_(None))
    )
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists in this tenant")
    user = User(
        tenant_id=tenant_id,
        username=data.username,
        email=data.email,
        password_hash=get_password_hash(data.password),
        role=data.role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user_id: int, tenant_id: int, data: UserAdminUpdate) -> User:
    user = await get_user(db, user_id, tenant_id)
    if data.username is not None:
        existing = await db.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.username == data.username,
                User.id != user_id,
                User.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists in this tenant")
        user.username = data.username
    if data.email is not None:
        existing = await db.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.email == data.email,
                User.id != user_id,
                User.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists in this tenant")
        user.email = data.email
    await db.commit()
    await db.refresh(user)
    return user


async def set_user_role(db: AsyncSession, user_id: int, tenant_id: int, role: str) -> User:
    valid_roles = [Role.ADMIN, Role.RELEASE_MANAGER, Role.TEST_MANAGER, Role.DEVELOPER, Role.VIEWER]
    if role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
        )
    user = await get_user(db, user_id, tenant_id)
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def deactivate_user(db: AsyncSession, user_id: int, tenant_id: int) -> User:
    user = await get_user(db, user_id, tenant_id)
    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return user
