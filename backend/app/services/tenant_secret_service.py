"""Tenant-scoped storage for encrypted third-party credentials."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets import decrypt, encrypt
from app.db.models.tenant_secret import TenantSecret


async def put_secret(
    db: AsyncSession,
    tenant_id: int,
    kind: str,
    plaintext: str,
    *,
    created_by: Optional[int] = None,
    expires_at: Optional[datetime] = None,
) -> TenantSecret:
    """Store or replace the secret for (tenant, kind)."""
    ciphertext, key_version = encrypt(plaintext)
    existing = (await db.execute(
        select(TenantSecret).where(
            TenantSecret.tenant_id == tenant_id, TenantSecret.kind == kind
        )
    )).scalar_one_or_none()

    if existing is not None:
        existing.ciphertext = ciphertext
        existing.key_version = key_version
        existing.expires_at = expires_at
        existing.created_by = created_by
        await db.flush()
        return existing

    row = TenantSecret(
        tenant_id=tenant_id, kind=kind, ciphertext=ciphertext,
        key_version=key_version, created_by=created_by, expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row


async def get_secret(db: AsyncSession, tenant_id: int, kind: str) -> Optional[str]:
    """The decrypted secret, or None when absent or expired."""
    row = (await db.execute(
        select(TenantSecret).where(
            TenantSecret.tenant_id == tenant_id, TenantSecret.kind == kind
        )
    )).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at is not None:
        expires_at = row.expires_at
        if expires_at.tzinfo is None:  # SQLite round-trips naive datetimes
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            # Expired rows are treated as absent rather than deleted here:
            # deletion is a write, and reads should not mutate.
            return None
    row.last_used_at = datetime.now(timezone.utc)
    return decrypt(row.ciphertext, row.key_version)


async def delete_secret(db: AsyncSession, tenant_id: int, kind: str) -> bool:
    """True if a row was removed."""
    result = await db.execute(
        delete(TenantSecret).where(
            TenantSecret.tenant_id == tenant_id, TenantSecret.kind == kind
        )
    )
    return (result.rowcount or 0) > 0
