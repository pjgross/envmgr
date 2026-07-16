from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.base import get_db


# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token scheme
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT access token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """Get the current authenticated user from JWT token."""
    from app.db.models.user import User
    
    token = credentials.credentials
    payload = decode_access_token(token)
    
    user_id_raw = payload.get("sub")
    tenant_id: int = payload.get("tenant_id")
    if user_id_raw is None or tenant_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    user_id = int(user_id_raw)
    
    # Query user from database
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    impersonating = payload.get("impersonating_tenant_id")
    # An impersonation claim is only honoured while the bearer is still a master
    # admin. If the privilege was revoked after the token was minted, ignore the
    # claim and fall back to the user's home tenant — closing cross-tenant access
    # without a request-time re-mint. (The claim itself is signed, so it can't be
    # forged; this guards the demoted-admin / stale-token case.)
    if impersonating and not user.is_master_admin:
        impersonating = None
    user.active_tenant_id = impersonating if impersonating else user.tenant_id

    return user


def require_role(required_role: str):
    """Dependency to require a specific role."""
    async def role_checker(current_user = Depends(get_current_user)):
        if current_user.is_master_admin:
            return current_user  # master admins can act in any tenant context
        if current_user.role != required_role and current_user.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role}' required",
            )
        return current_user
    return role_checker


def require_master_admin():
    """Dependency to require master admin privileges."""
    async def master_admin_checker(current_user=Depends(get_current_user)):
        if not current_user.is_master_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Master admin access required",
            )
        return current_user
    return master_admin_checker


# Role constants
class Role:
    ADMIN = "Admin"
    RELEASE_MANAGER = "Release Manager"
    TEST_MANAGER = "Test Manager"
    DEVELOPER = "Developer"
    VIEWER = "Viewer"


def require_tenant_admin():
    """Dependency to require tenant admin (Admin role) privileges."""
    return require_role(Role.ADMIN)


def api_key_auth(required_scope: str):
    """FastAPI dependency factory. Returns a dependency that requires a
    valid X-Api-Key header whose key has the given scope."""
    from datetime import datetime, timezone as _tz
    from fastapi import Depends, Header, HTTPException, status
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.base import get_db
    from app.services import api_key_service

    async def _dep(
        x_api_key: str | None = Header(default=None),
        db: AsyncSession = Depends(get_db),
    ):
        if not x_api_key:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
        key = await api_key_service.authenticate(db, x_api_key)
        api_key_service.require_scope(key, required_scope)
        # Bump last_used_at inline — small write inside the request
        # transaction; get_db auto-commits on success.
        key.last_used_at = datetime.now(_tz.utc)
        await db.flush()
        return key
    return _dep
