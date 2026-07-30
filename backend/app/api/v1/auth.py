from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.db.models.user import User, Tenant
from app.core.security import (
    verify_password,
    get_current_user,
)
from app.api.v1.schemas import RefreshRequest, UserLogin, UserResponse, TokenResponse
from app.services import auth_session_service


def _client_ip(request: Request) -> str | None:
    """Best-effort client address for rate limiting.

    X-Forwarded-For is client-controlled, so this is a throttling signal only and
    never an authorisation input. Behind the project's nginx it is the real peer;
    directly exposed it can be spoofed, which at worst spreads an attacker's
    per-IP budget — the per-username limit still applies.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None

# NOTE: there is deliberately no self-service registration endpoint. Users are
# created through POST /api/v1/tenant/users, which requires a tenant admin and
# forces the caller's own tenant — see app/api/v1/tenant_admin.py.

router = APIRouter()


async def _record_and_commit_failure(db: AsyncSession, credentials: UserLogin, client_ip):
    """Record a failed attempt and commit it before the 401 is raised.

    get_db() rolls back the request transaction on exception, so recording the
    attempt and then raising discards it — the counter never advances and the rate
    limit never engages. The commit has to happen here, on the way out.
    """
    await auth_session_service.record_failed_login(
        db, credentials.tenant_slug, credentials.username, client_ip
    )
    await db.commit()


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange credentials for a short-lived access token and a refresh token."""
    client_ip = _client_ip(request)

    # Checked before the password is even looked at, so a correct guess does not
    # bypass the limit.
    if await auth_session_service.is_login_blocked(
        db, credentials.tenant_slug, credentials.username, client_ip
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again later.",
            headers={
                "Retry-After": str(auth_session_service.LOCKOUT_WINDOW_MINUTES * 60)
            },
        )

    # Get tenant by slug
    result = await db.execute(
        select(Tenant).where(Tenant.slug == credentials.tenant_slug)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        await _record_and_commit_failure(db, credentials, client_ip)
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
        await _record_and_commit_failure(db, credentials, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    
    await auth_session_service.clear_failed_logins(
        db, credentials.tenant_slug, credentials.username
    )
    session = await auth_session_service.issue_session(
        db,
        user,
        user_agent=request.headers.get("User-Agent"),
        client_ip=client_ip,
    )

    return TokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(
    payload: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a refresh token for a new access token and a new refresh token.

    Deliberately unauthenticated: the caller's access token has usually expired,
    which is why they are here. The refresh token is the credential.
    """
    try:
        session = await auth_session_service.rotate_refresh_token(
            db,
            payload.refresh_token,
            user_agent=request.headers.get("User-Agent"),
            client_ip=_client_ip(request),
        )
    except auth_session_service.RefreshTokenRevocationWritten:
        # Replay detection revoked the family. That write has to be committed
        # here: get_db() rolls back on exception, which would otherwise discard
        # the revocation and leave the leaked token usable.
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    except auth_session_service.InvalidRefreshToken:
        # One undifferentiated 401: telling a caller whether a token was unknown,
        # expired or replayed only helps someone probing with stolen tokens.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    claims = auth_session_service.decode_session_user(session.access_token)
    user = (
        await db.execute(select(User).where(User.id == claims["user_id"]))
    ).scalar_one()

    return TokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """End this session.

    Revokes the presented refresh token only, so signing out on one device does
    not sign the user out everywhere. The access token is not denied-listed — it
    expires within ACCESS_TOKEN_MINUTES on its own, and checking a list on every
    request would cost far more than that window is worth.
    """
    await auth_session_service.revoke_refresh_token(
        db, payload.refresh_token, reason="logout"
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """Get current user information."""
    return current_user
