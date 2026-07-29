from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.db.models.user import User, Tenant
from app.core.security import (
    verify_password,
    create_access_token,
    get_current_user,
)
from app.api.v1.schemas import UserLogin, UserResponse, TokenResponse

# NOTE: there is deliberately no self-service registration endpoint. Users are
# created through POST /api/v1/tenant/users, which requires a tenant admin and
# forces the caller's own tenant — see app/api/v1/tenant_admin.py.

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """Login and get access token."""
    
    # Get tenant by slug
    result = await db.execute(
        select(Tenant).where(Tenant.slug == credentials.tenant_slug)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is disabled")

    # Get user by username and tenant
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant.id,
            User.username == credentials.username,
        )
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    # Create access token (sub must be a string per RFC 7519)
    access_token = create_access_token(
        data={"sub": str(user.id), "tenant_id": tenant.id}
    )
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Get current user information."""
    return current_user
