"""Symmetric encryption for third-party credentials held on a tenant's behalf.

Deliberately separate from SECRET_KEY, which signs JWTs: the two have
different blast radii and different rotation schedules, and a single key
doing both jobs makes rotating either one harder than it should be.
"""
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# Bump when the encryption scheme or key changes. Stored per row so a future
# rotation can re-encrypt in place; retrofitting this later would mean a
# migration that decrypts every row with the key being retired.
CURRENT_KEY_VERSION = 1


class SecretDecryptionError(RuntimeError):
    """Raised when a stored secret cannot be decrypted.

    Always fail closed: returning garbage would mean sending a malformed
    credential to a third party and reading the resulting error as "their"
    problem.
    """


def _fernet() -> Fernet:
    key = settings.SECRETS_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "SECRETS_ENCRYPTION_KEY is not set. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> tuple[str, int]:
    """Returns (ciphertext, key_version)."""
    return _fernet().encrypt(plaintext.encode()).decode(), CURRENT_KEY_VERSION


def decrypt(ciphertext: str, key_version: int) -> str:
    if key_version != CURRENT_KEY_VERSION:
        raise SecretDecryptionError(
            f"secret was encrypted with key version {key_version}, "
            f"this build understands {CURRENT_KEY_VERSION}"
        )
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "stored secret could not be decrypted — SECRETS_ENCRYPTION_KEY may have changed"
        ) from exc
