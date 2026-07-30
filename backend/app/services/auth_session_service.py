"""Session issuing, refresh-token rotation and login rate limiting.

Sessions were a single 24-hour JWT held in localStorage, with no server-side
record: logging out cleared the browser but the token stayed valid for the rest
of the day, and there was no way to revoke it. Nor was there any brake on
password guessing.

The shape here is the conventional one:

- a short-lived access token (JWT, 15 minutes) carrying the claims the app needs
- a long-lived refresh token (opaque random bytes, 14 days) that exists as a
  database row and can therefore be revoked
- rotation on every refresh, with replay of a spent token treated as evidence of
  theft and the whole family revoked

Access tokens are deliberately *not* checked against a deny-list on each request:
that would add a lookup to every authenticated call to shorten an exposure window
that is already 15 minutes. Revocation acts on the refresh token, so a stolen
access token dies on its own within that window. `revoke_all_for_user` exists for
the cases where waiting is not acceptable (password change, compromised account).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.db.models.refresh_token import LoginAttempt, RefreshToken
from app.db.models.user import User

ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 14

# Impersonation tokens carry more privilege than any other token in the system —
# a master admin acting inside someone else's tenant — and have no refresh flow,
# so they cannot be as short as a normal access token without making support work
# impossible. An hour is the compromise; it must never exceed it.
IMPERSONATION_TOKEN_MINUTES = 60

# Rate limiting. Per-username catches guessing at one account; per-IP catches an
# attacker walking a list of usernames from one host, which a per-username limit
# alone does nothing about.
MAX_FAILED_LOGINS = 5
MAX_FAILED_LOGINS_PER_IP = 20
LOCKOUT_WINDOW_MINUTES = 15


class InvalidRefreshToken(Exception):
    """Presented refresh token is unknown, expired, spent or revoked."""


class RefreshTokenRevocationWritten(InvalidRefreshToken):
    """Rejected, and sessions were revoked as a result.

    Distinct because the caller has to commit before returning the error:
    get_db() rolls back the request transaction when an endpoint raises, so a
    revocation written on the way to a 401 would otherwise be discarded — leaving
    the token that triggered replay detection working.
    """


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_token: str
    expires_in: int


def _hash(token: str) -> str:
    """Refresh tokens are stored hashed so a database leak yields no sessions.

    Plain SHA-256, not bcrypt: the token is 256 bits of `secrets` output, so
    there is no low-entropy guess to slow down, and login-time cost matters.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def issue_session(
    db: AsyncSession,
    user: User,
    *,
    user_agent: Optional[str] = None,
    client_ip: Optional[str] = None,
    impersonating_tenant_id: Optional[int] = None,
    family_id: Optional[str] = None,
) -> IssuedSession:
    """Mint an access token and a fresh refresh token for `user`."""
    claims: dict = {"sub": str(user.id), "tenant_id": user.tenant_id}
    if impersonating_tenant_id is not None:
        claims["impersonating_tenant_id"] = impersonating_tenant_id

    access_token = create_access_token(
        claims, expires_delta=timedelta(minutes=ACCESS_TOKEN_MINUTES)
    )

    refresh_token = secrets.token_urlsafe(32)
    row = RefreshToken(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=_hash(refresh_token),
        family_id=family_id or uuid.uuid4().hex,
        expires_at=_now() + timedelta(days=REFRESH_TOKEN_DAYS),
        user_agent=(user_agent or None) and user_agent[:300],
        client_ip=client_ip,
    )
    db.add(row)
    await db.flush()

    return IssuedSession(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_MINUTES * 60,
    )


async def _load_token(db: AsyncSession, refresh_token: str) -> RefreshToken:
    row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == _hash(refresh_token))
        )
    ).scalar_one_or_none()
    if row is None:
        raise InvalidRefreshToken("unknown refresh token")
    return row


async def _revoke_family(
    db: AsyncSession, family_id: str, *, reason: str
) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    await db.flush()


async def rotate_refresh_token(
    db: AsyncSession,
    refresh_token: str,
    *,
    user_agent: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> IssuedSession:
    """Exchange a refresh token for a new session, invalidating the old token."""
    row = await _load_token(db, refresh_token)

    if row.used_at is not None:
        # Someone is replaying a token that has already been exchanged. Either it
        # leaked, or a client raced itself; both are best handled by ending the
        # session rather than guessing which.
        await _revoke_family(db, row.family_id, reason="reuse_detected")
        raise RefreshTokenRevocationWritten("refresh token already used")

    if row.revoked_at is not None:
        raise InvalidRefreshToken("refresh token revoked")

    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # SQLite round-trips naive datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _now():
        raise InvalidRefreshToken("refresh token expired")

    user = (
        await db.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        await _revoke_family(db, row.family_id, reason="user_inactive")
        raise RefreshTokenRevocationWritten("user is not active")

    issued = await issue_session(
        db,
        user,
        user_agent=user_agent,
        client_ip=client_ip,
        family_id=row.family_id,
    )

    successor = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == _hash(issued.refresh_token)
            )
        )
    ).scalar_one()
    row.used_at = _now()
    row.replaced_by_id = successor.id
    await db.flush()

    return issued


async def revoke_refresh_token(
    db: AsyncSession, refresh_token: str, *, reason: str
) -> None:
    """Revoke one session. Unknown tokens are ignored so logout is idempotent."""
    try:
        row = await _load_token(db, refresh_token)
    except InvalidRefreshToken:
        return
    if row.revoked_at is None:
        row.revoked_at = _now()
        row.revoked_reason = reason
        await db.flush()


async def revoke_all_for_user(db: AsyncSession, user_id: int, *, reason: str) -> None:
    """Revoke every live session for a user — password change, compromise."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason=reason)
    )
    await db.flush()


# ── login rate limiting ──────────────────────────────────────────────────────


async def record_failed_login(
    db: AsyncSession, tenant_slug: str, username: str, client_ip: Optional[str]
) -> None:
    db.add(
        LoginAttempt(
            tenant_slug=tenant_slug,
            username=username,
            client_ip=client_ip,
            attempted_at=_now(),
        )
    )
    await db.flush()


async def clear_failed_logins(
    db: AsyncSession, tenant_slug: str, username: str
) -> None:
    """Called on success, so a user who eventually remembers isn't near the limit."""
    await db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.tenant_slug == tenant_slug, LoginAttempt.username == username
        )
    )
    await db.flush()


async def is_login_blocked(
    db: AsyncSession, tenant_slug: str, username: str, client_ip: Optional[str]
) -> bool:
    since = _now() - timedelta(minutes=LOCKOUT_WINDOW_MINUTES)

    by_username = (
        await db.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.tenant_slug == tenant_slug,
                LoginAttempt.username == username,
                LoginAttempt.attempted_at >= since,
            )
        )
    ).scalar_one()
    if by_username >= MAX_FAILED_LOGINS:
        return True

    if client_ip:
        by_ip = (
            await db.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(
                    LoginAttempt.client_ip == client_ip,
                    LoginAttempt.attempted_at >= since,
                )
            )
        ).scalar_one()
        if by_ip >= MAX_FAILED_LOGINS_PER_IP:
            return True

    return False


def decode_session_user(access_token: str) -> dict:
    """The user/tenant a just-issued access token refers to.

    Saves the caller re-deriving what issue_session already knew, without making
    it return the User and couple every caller to the ORM object's lifetime.
    """
    from app.core.security import decode_access_token

    claims = decode_access_token(access_token)
    return {
        "user_id": int(claims["sub"]),
        "tenant_id": claims["tenant_id"],
        "impersonating_tenant_id": claims.get("impersonating_tenant_id"),
    }
