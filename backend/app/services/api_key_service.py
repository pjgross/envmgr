"""ApiKey service — raw key generation + SHA-256 hashing + auth."""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import ApiKey


RAW_PREFIX = "em_"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_raw() -> str:
    return RAW_PREFIX + secrets.token_urlsafe(32)


async def create_key(
    db: AsyncSession,
    tenant_id: int,
    created_by: int,
    name: str,
    scopes: list[str],
    expires_at: Optional[datetime] = None,
) -> tuple[ApiKey, str]:
    """Generate + persist an API key. Returns the ORM row AND the raw key
    (which must be shown to the user once and never stored)."""
    raw = _generate_raw()
    key = ApiKey(
        tenant_id=tenant_id,
        key_hash=_hash(raw),
        name=name,
        scopes=scopes,
        created_by=created_by,
        expires_at=expires_at,
    )
    db.add(key)
    await db.flush()
    return key, raw


async def list_keys(db: AsyncSession, tenant_id: int) -> list[ApiKey]:
    rows = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.tenant_id == tenant_id,
                ApiKey.deleted_at.is_(None),
            ).order_by(ApiKey.id.desc())
        )
    ).scalars().all()
    return list(rows)


async def revoke_key(db: AsyncSession, tenant_id: int, key_id: int) -> None:
    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.tenant_id == tenant_id,
                ApiKey.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def authenticate(db: AsyncSession, raw: str) -> ApiKey:
    """Look up a raw key by hash. Raises 401 if missing/expired/revoked."""
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == _hash(raw),
                ApiKey.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if key.expires_at is not None:
        expires = key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expired")
    return key


def require_scope(key: ApiKey, scope: str) -> None:
    if scope not in (key.scopes or []):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"API key is missing required scope '{scope}'",
        )
