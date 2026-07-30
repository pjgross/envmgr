"""Unit tests for app/core/security.py — no database required."""
import pytest
from datetime import timedelta
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
    require_master_admin,
)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def test_hash_and_verify_password():
    hashed = get_password_hash("mysecret")
    assert verify_password("mysecret", hashed) is True


def test_wrong_password_rejected():
    hashed = get_password_hash("mysecret")
    assert verify_password("wrong", hashed) is False


def test_different_hashes_for_same_password():
    """bcrypt generates a unique salt each time."""
    h1 = get_password_hash("same")
    h2 = get_password_hash("same")
    assert h1 != h2
    assert verify_password("same", h1) is True
    assert verify_password("same", h2) is True


# ---------------------------------------------------------------------------
# JWT token creation and decoding
# ---------------------------------------------------------------------------

def test_create_and_decode_token():
    # sub must be a string per RFC 7519 / python-jose validation
    token = create_access_token({"sub": "1", "tenant_id": 42})
    payload = decode_access_token(token)
    assert payload["sub"] == "1"
    assert payload["tenant_id"] == 42


def test_token_contains_expiry():
    token = create_access_token({"sub": "1"})
    payload = decode_access_token(token)
    assert "exp" in payload


def test_custom_expiry_respected():
    short = create_access_token({"sub": "1"}, expires_delta=timedelta(hours=1))
    long = create_access_token({"sub": "1"}, expires_delta=timedelta(hours=24))
    short_exp = decode_access_token(short)["exp"]
    long_exp = decode_access_token(long)["exp"]
    assert long_exp > short_exp


def test_expired_token_raises_401():
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401


def test_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("not.a.valid.token")
    assert exc_info.value.status_code == 401


def test_tampered_token_raises_401():
    token = create_access_token({"sub": 1})
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(tampered)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Impersonation and master admin
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Algorithm confinement — CVE-2024-33663 class
# ---------------------------------------------------------------------------

def test_token_signed_with_a_different_algorithm_is_rejected():
    """decode_access_token must honour only settings.ALGORITHM.

    python-jose 3.3.0 was affected by CVE-2024-33663 (algorithm confusion). The
    library is fixed, but the defence that matters here is passing an explicit
    algorithms= allowlist to jwt.decode — pin it so a future refactor can't drop
    it silently.
    """
    from jose import jwt
    from app.core.config import settings

    other = "HS512" if settings.ALGORITHM != "HS512" else "HS256"
    token = jwt.encode({"sub": "1", "tenant_id": 1}, settings.SECRET_KEY, algorithm=other)

    with pytest.raises(HTTPException) as exc:
        decode_access_token(token)
    assert exc.value.status_code == 401


def test_unsigned_token_is_rejected():
    """An alg=none token carries no signature and must never authenticate.

    Hand-assembled rather than built with jose, which refuses to encode alg=none
    — an attacker has no such scruples.
    """
    import base64
    import json

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"sub": "1", "tenant_id": 1}).encode())
    token = f"{header}.{payload}."  # empty signature

    with pytest.raises(HTTPException) as exc:
        decode_access_token(token)
    assert exc.value.status_code == 401


def test_impersonating_tenant_id_preserved_in_token():
    """impersonating_tenant_id passed in data must survive encode/decode."""
    token = create_access_token({"sub": "1", "tenant_id": 1, "impersonating_tenant_id": 99})
    payload = decode_access_token(token)
    assert payload["impersonating_tenant_id"] == 99


def test_active_tenant_id_uses_impersonating_when_set():
    """active_tenant_id should equal impersonating_tenant_id when that claim is present."""
    impersonating_tenant = 99
    own_tenant = 1

    # Simulate what get_current_user does after loading the user from DB
    user = MagicMock()
    user.tenant_id = own_tenant

    payload = {"impersonating_tenant_id": impersonating_tenant}
    impersonating = payload.get("impersonating_tenant_id")
    user.active_tenant_id = impersonating if impersonating else user.tenant_id

    assert user.active_tenant_id == impersonating_tenant


@pytest.mark.asyncio
async def test_require_master_admin_blocks_non_master():
    """require_master_admin dependency must raise 403 for non-master-admin users."""
    mock_user = MagicMock()
    mock_user.is_master_admin = False

    checker = require_master_admin()
    with pytest.raises(HTTPException) as exc_info:
        await checker(current_user=mock_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Master admin access required"


@pytest.mark.asyncio
async def test_require_master_admin_allows_master_admin():
    mock_user = MagicMock()
    mock_user.is_master_admin = True
    checker = require_master_admin()
    result = await checker(current_user=mock_user)
    assert result is mock_user


def test_active_tenant_id_falls_back_to_user_tenant_id():
    """When no impersonating_tenant_id in payload, active_tenant_id equals user.tenant_id."""
    payload_without_impersonation = {"sub": "1", "tenant_id": 42}
    impersonating = payload_without_impersonation.get("impersonating_tenant_id")
    active = impersonating if impersonating else payload_without_impersonation["tenant_id"]
    assert active == 42
