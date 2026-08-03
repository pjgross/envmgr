"""Encrypted per-tenant credential storage.

This app had no reversible secret storage before: api_key stores a one-way
hash, which is right for verifying inbound keys and useless for a token we
must replay outbound.
"""
import pytest
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet

from app.core import secrets as secrets_module
from app.core.secrets import SecretDecryptionError, decrypt, encrypt
from app.services import tenant_secret_service as svc


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """A real Fernet key per test run, never the deployment's."""
    monkeypatch.setattr(
        secrets_module.settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


def test_encrypt_then_decrypt_round_trips():
    ciphertext, version = encrypt("gho_exampletoken")
    assert ciphertext != "gho_exampletoken"
    assert decrypt(ciphertext, version) == "gho_exampletoken"


def test_the_ciphertext_does_not_contain_the_plaintext():
    ciphertext, _ = encrypt("gho_exampletoken")
    assert "gho_exampletoken" not in ciphertext


def test_decrypting_with_a_different_key_fails_closed(monkeypatch):
    """Fails loudly rather than returning garbage that would be sent to GitHub."""
    ciphertext, version = encrypt("gho_exampletoken")
    monkeypatch.setattr(
        secrets_module.settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    with pytest.raises(SecretDecryptionError):
        decrypt(ciphertext, version)


def test_an_unknown_key_version_is_refused():
    """Refuses rather than trying the current key on a row it did not encrypt."""
    ciphertext, _ = encrypt("gho_exampletoken")
    with pytest.raises(SecretDecryptionError):
        decrypt(ciphertext, 99)


def test_a_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(secrets_module.settings, "SECRETS_ENCRYPTION_KEY", "")
    with pytest.raises(RuntimeError, match="SECRETS_ENCRYPTION_KEY"):
        encrypt("anything")


@pytest.mark.asyncio
async def test_put_then_get_returns_the_plaintext(db_session, test_tenant, test_user):
    await svc.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc", created_by=test_user.id
    )
    assert await svc.get_secret(db_session, test_tenant.id, "github_oauth_token") == "gho_abc"


@pytest.mark.asyncio
async def test_putting_twice_replaces_rather_than_duplicating(
    db_session, test_tenant, test_user
):
    """(tenant_id, kind) is unique — reconnecting must not leave the old token behind."""
    await svc.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "old", created_by=test_user.id
    )
    await svc.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "new", created_by=test_user.id
    )
    assert await svc.get_secret(db_session, test_tenant.id, "github_oauth_token") == "new"


@pytest.mark.asyncio
async def test_a_secret_is_invisible_to_another_tenant(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """Tenant isolation is a security requirement in this project."""
    other, _ = await second_tenant_factory()
    await svc.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc", created_by=test_user.id
    )
    assert await svc.get_secret(db_session, other.id, "github_oauth_token") is None
    # Positive control: the owning tenant still sees it.
    assert await svc.get_secret(db_session, test_tenant.id, "github_oauth_token") == "gho_abc"


@pytest.mark.asyncio
async def test_an_expired_secret_is_not_returned(db_session, test_tenant, test_user):
    """Device-flow rows carry an expiry; a stale one must not be redeemable."""
    await svc.put_secret(
        db_session, test_tenant.id, "github_device_pending", "dev_code",
        created_by=test_user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    assert await svc.get_secret(db_session, test_tenant.id, "github_device_pending") is None


@pytest.mark.asyncio
async def test_delete_removes_the_secret(db_session, test_tenant, test_user):
    await svc.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc", created_by=test_user.id
    )
    assert await svc.delete_secret(db_session, test_tenant.id, "github_oauth_token") is True
    assert await svc.get_secret(db_session, test_tenant.id, "github_oauth_token") is None
    assert await svc.delete_secret(db_session, test_tenant.id, "github_oauth_token") is False
