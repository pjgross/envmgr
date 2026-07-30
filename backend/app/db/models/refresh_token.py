"""Refresh tokens and login attempt tracking.

Sessions used to be a single 24-hour JWT with no server-side record, so logging
out only cleared localStorage — the token stayed valid for the rest of its life
and there was no way to revoke it. These two tables give sessions a server side.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RefreshToken(Base):
    """One row per issued refresh token.

    Only a SHA-256 of the token is stored: a database leak must not hand out
    live sessions. The token itself is opaque random bytes, never a JWT — there
    is nothing to gain from making it self-describing when it has to be looked
    up anyway.
    """

    __tablename__ = "refresh_token"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Rotation chain. Every refresh issues a new token and marks the old one
    # used; presenting a used token means it leaked, so the whole family is
    # revoked (see auth_service.rotate_refresh_token).
    family_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    replaced_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("refresh_token.id", ondelete="SET NULL"), nullable=True
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Recorded to make "sessions signed in from where" answerable later; not used
    # for any authorisation decision, since both are client-controlled.
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_refresh_token_user_active", "user_id", "revoked_at"),
    )


class LoginAttempt(Base):
    """Failed login attempts, for rate limiting.

    Stored in PostgreSQL rather than Redis so the limit holds across replicas and
    survives a restart, and so it is testable without a running Redis. Login is
    not a hot path — a couple of indexed queries per attempt is not the cost that
    matters here.
    """

    __tablename__ = "login_attempt"

    # Not a foreign key: attempts are recorded for usernames that do not exist,
    # which is exactly the case worth rate limiting.
    tenant_slug: Mapped[str] = mapped_column(String(100), nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_login_attempt_identity", "tenant_slug", "username", "attempted_at"),
        Index("ix_login_attempt_ip", "client_ip", "attempted_at"),
    )
