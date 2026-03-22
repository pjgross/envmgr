"""Unit tests for app/core/security.py — no database required."""
import pytest
from datetime import timedelta
from fastapi import HTTPException

from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
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
