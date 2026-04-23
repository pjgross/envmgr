"""ApiKeyService — generate, authenticate, revoke, scope check."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import api_key_service


@pytest.mark.asyncio
async def test_create_returns_raw_key_once_and_stores_hash_only(db_session, tenant, user):
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.flush()
    assert raw.startswith("em_")
    assert len(raw) > 30
    # Stored value is a SHA-256 hex digest, 64 chars
    assert len(key.key_hash) == 64
    assert key.key_hash != raw


@pytest.mark.asyncio
async def test_authenticate_accepts_valid_key(db_session, tenant, user):
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.flush()

    authed = await api_key_service.authenticate(db_session, raw)
    assert authed.id == key.id


@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_key(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await api_key_service.authenticate(db_session, "em_notreal")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticate_rejects_expired_key(db_session, tenant, user):
    from fastapi import HTTPException
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Expired", scopes=["webhooks:deployment"],
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await api_key_service.authenticate(db_session, raw)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticate_rejects_revoked_key(db_session, tenant, user):
    from fastapi import HTTPException
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Dead", scopes=["webhooks:deployment"],
    )
    await db_session.flush()
    await api_key_service.revoke_key(db_session, tenant_id=tenant.id, key_id=key.id)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await api_key_service.authenticate(db_session, raw)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_scope_passes_and_fails(db_session, tenant, user):
    from fastapi import HTTPException
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Narrow", scopes=["webhooks:deployment"],
    )
    await db_session.flush()
    authed = await api_key_service.authenticate(db_session, raw)
    api_key_service.require_scope(authed, "webhooks:deployment")
    with pytest.raises(HTTPException) as exc:
        api_key_service.require_scope(authed, "admin:write")
    assert exc.value.status_code == 403
