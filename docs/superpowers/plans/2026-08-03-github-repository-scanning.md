# GitHub Repository Scanning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect a tenant's GitHub account once via OAuth device flow, then scan a system's repository on demand to discover infrastructure, feeding the Compose parser that already exists and a new Terraform HCL parser.

**Architecture:** An encrypted `tenant_secret` table underpins everything, because this app has no reversible secret storage today. A thin GitHub client (httpx, injectable transport) fetches the repo tree in one call. A **detector registry** — name, path predicate, parse function — decides what gets parsed, so adding a technology later is a module plus a list entry and cannot disturb existing detectors.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic · `cryptography` (Fernet, **new**) · `python-hcl2` (**new**) · httpx · React 18 + TypeScript + MUI · pytest (dual-engine) · vitest

**Spec:** [docs/superpowers/specs/2026-08-03-github-repository-scanning-design.md](../specs/2026-08-03-github-repository-scanning-design.md)

## Global Constraints

- **`SECRETS_ENCRYPTION_KEY` is separate from `SECRET_KEY`.** Never encrypt stored credentials with the JWT signing key.
- **No endpoint ever returns a secret.** `GET /integrations/github` answers `{connected, github_login, connected_at}` and nothing more. There is no read-back path.
- The GitHub `device_code` **stays server-side, encrypted** — it redeems the token and must never reach the browser.
- `key_version` is stored on every secret row from the first migration.
- **A path goes to every detector that claims it**, never just the first — registry order must not affect behaviour.
- **A detector that raises is recorded; the other detectors still run and the scan still reports.**
- **Partial results are never reported as success**: tree `truncated: true` and hitting `MAX_SCAN_FILES` (200) are both first-class outcomes in the response.
- One scan at a time per system; a concurrent scan is a 409.
- Every query on a tenant-scoped table filters `tenant_id`; soft-deleted rows excluded where the model has `deleted_at`.
- Services never call `db.commit()` — `get_db()` commits on success; use `await db.flush()` for mid-transaction ids.
- Enum columns use `native_enum=False`. Migrations are hand-written DDL, never `--autogenerate`.
- Backend tests pass on **both** engines: default SQLite plus `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test`.
- No network in tests — the GitHub client takes an injectable httpx transport.
- Every test verified by breaking what it covers; report the mutation output.

## File Structure

**Backend**
- Create `backend/app/core/secrets.py` — Fernet encrypt/decrypt plus `SecretDecryptionError`. No DB.
- Create `backend/app/db/models/tenant_secret.py` — the model.
- Create `backend/app/db/migrations/versions/20260803_1200_tenantsecrets_add_tenant_secret.py` — `down_revision = 'authsessions'`.
- Create `backend/app/services/tenant_secret_service.py` — tenant-scoped put/get/delete.
- Create `backend/app/services/github_client.py` — HTTP only: default branch, tree, blob. Maps GitHub errors to typed exceptions.
- Create `backend/app/services/github_oauth_service.py` — device flow.
- Create `backend/app/api/v1/integrations_github.py` — connect / poll / status / disconnect.
- Create `backend/app/services/scanning/__init__.py`, `registry.py`, `scanner.py`.
- Create `backend/app/services/scanning/detectors/__init__.py`, `compose.py`, `terraform_hcl.py`.
- Create `backend/app/services/terraform_hcl_import_service.py` — the HCL parser proper, mirroring `terraform_import_service`'s upsert-by-name.
- Modify `backend/app/core/config.py` — `GITHUB_OAUTH_CLIENT_ID`, `SECRETS_ENCRYPTION_KEY`, `MAX_SCAN_FILES`.
- Modify `backend/app/main.py` — register the integrations router.
- Modify `backend/app/api/v1/systems.py` — the scan endpoint.
- Modify `backend/pyproject.toml` — `cryptography`, `python-hcl2`.

**Frontend**
- Create `frontend/src/types/githubIntegration.ts`, `frontend/src/services/githubIntegrationService.ts`.
- Create `frontend/src/pages/admin/GitHubIntegration.tsx` — connect/disconnect journey.
- Create `frontend/src/components/systems/ScanRepositoryDialog.tsx` — trigger and results.
- Modify `frontend/src/App.tsx`, `frontend/src/components/navConfig.tsx`, `frontend/src/pages/systems/SystemDetail.tsx`.

---

### Task 1: Encrypted tenant secrets

The foundation. Security-sensitive, so it lands and is reviewed on its own.

**Files:**
- Create: `backend/app/core/secrets.py`, `backend/app/db/models/tenant_secret.py`, `backend/app/services/tenant_secret_service.py`, `backend/app/db/migrations/versions/20260803_1200_tenantsecrets_add_tenant_secret.py`
- Modify: `backend/app/core/config.py`, `backend/pyproject.toml`
- Test: `backend/tests/services/test_tenant_secret_service.py`

**Interfaces:**
- Produces: `encrypt(plaintext) -> tuple[str, int]`, `decrypt(ciphertext, key_version) -> str`, `SecretDecryptionError`; and `put_secret(db, tenant_id, kind, plaintext, created_by, expires_at=None)`, `get_secret(db, tenant_id, kind) -> str | None`, `delete_secret(db, tenant_id, kind) -> bool`. Tasks 2 and 6 consume these.

- [ ] **Step 1: Add the dependency and config**

`backend/pyproject.toml`, beside the other dependencies:

```toml
    # Fernet for symmetric encryption of stored third-party credentials.
    # Deliberately NOT reusing SECRET_KEY (JWT signing) — different blast
    # radius, different rotation schedule.
    "cryptography==43.0.1",
```

`backend/app/core/config.py`, inside `Settings`:

```python
    # Encrypts third-party credentials at rest. Separate from SECRET_KEY on
    # purpose. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SECRETS_ENCRYPTION_KEY: str = ""
```

Then `cd backend && uv sync`.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/services/test_tenant_secret_service.py`:

```python
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
```

- [ ] **Step 3: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_tenant_secret_service.py -q
```

Expected: collection error — `app.core.secrets` does not exist.

- [ ] **Step 4: Implement the encryption helper**

Create `backend/app/core/secrets.py`:

```python
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
```

- [ ] **Step 5: Implement the model**

Create `backend/app/db/models/tenant_secret.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantSecret(Base):
    """A third-party credential held on a tenant's behalf, encrypted at rest.

    One row per (tenant, kind): reconnecting replaces rather than accumulating.
    `expires_at` exists for short-lived rows such as an in-flight OAuth device
    code, which is itself a credential and so shares this table's encryption
    rather than getting a second, parallel mechanism.
    """

    __tablename__ = "tenant_secret"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", name="uq_tenant_secret_tenant_kind"),
    )

    def __repr__(self) -> str:
        # Never include ciphertext — reprs end up in logs.
        return f"<TenantSecret(tenant={self.tenant_id}, kind='{self.kind}')>"
```

Register it in `backend/app/db/models/__init__.py` alongside the other models, following the existing import style there.

- [ ] **Step 6: Implement the service**

Create `backend/app/services/tenant_secret_service.py`:

```python
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
    if row.expires_at is not None and row.expires_at <= datetime.now(timezone.utc):
        # Expired rows are treated as absent rather than deleted here: deletion
        # is a write, and reads should not mutate.
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
```

- [ ] **Step 7: Write the migration**

Create `backend/app/db/migrations/versions/20260803_1200_tenantsecrets_add_tenant_secret.py`:

```python
"""tenant_secret — encrypted third-party credentials

Revision ID: tenantsecrets
Revises: authsessions
Create Date: 2026-08-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'tenantsecrets'
down_revision: Union[str, None] = 'authsessions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_secret",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "kind", name="uq_tenant_secret_tenant_kind"),
    )
    op.create_index("ix_tenant_secret_tenant_id", "tenant_secret", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_secret_tenant_id", table_name="tenant_secret")
    op.drop_table("tenant_secret")
```

`created_at`/`updated_at` are included explicitly because `Base` defines them and a migration-built database that omits them drifts from a `create_all` one — the defect the `basetimestamps` migration exists to fix.

- [ ] **Step 8: Run the tests on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_tenant_secret_service.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest tests/services/test_tenant_secret_service.py -q
```

Expected: `10 passed` on each.

- [ ] **Step 9: Verify the migration builds the same schema as the model**

```bash
cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: no errors in either direction. Then confirm the drift guard still passes:

```bash
PYTHONPATH=. uv run pytest tests/ -q -k "drift or migration"
```

- [ ] **Step 10: Verify the tests discriminate**

Back files up with `cp` first; restore with `cp`, never `git checkout`.

1. In `decrypt`, drop the `key_version` check. Expected: `test_an_unknown_key_version_is_refused` FAILS.
2. In `decrypt`, catch `InvalidToken` and `return ""` instead of raising. Expected: `test_decrypting_with_a_different_key_fails_closed` FAILS.
3. In `get_secret`, drop the `expires_at` check. Expected: `test_an_expired_secret_is_not_returned` FAILS.
4. In `get_secret`, drop `TenantSecret.tenant_id == tenant_id`. Expected: `test_a_secret_is_invisible_to_another_tenant` FAILS.

- [ ] **Step 11: Commit**

```bash
git add backend/app/core/secrets.py backend/app/db/models/tenant_secret.py \
        backend/app/db/models/__init__.py backend/app/services/tenant_secret_service.py \
        backend/app/db/migrations/versions/20260803_1200_tenantsecrets_add_tenant_secret.py \
        backend/app/core/config.py backend/pyproject.toml backend/uv.lock \
        backend/tests/services/test_tenant_secret_service.py
git commit -m "feat(secrets): encrypted per-tenant credential storage"
```

---

### Task 2: GitHub client

HTTP only — no database, no business logic. Injectable transport so nothing in the suite touches the network.

**Files:**
- Create: `backend/app/services/github_client.py`
- Test: `backend/tests/services/test_github_client.py`

**Interfaces:**
- Produces: `GitHubClient(token: str, transport=None)` with `async get_default_branch(owner, repo) -> str`, `async get_tree(owner, repo, ref) -> TreeResult`, `async get_blob(owner, repo, path, ref) -> bytes`; `TreeResult(paths: list[str], truncated: bool)`; and exceptions `GitHubAuthError`, `GitHubRateLimited(reset_at)`, `GitHubNotFound`. Tasks 3 and 6 consume these.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_github_client.py`:

```python
"""GitHub HTTP client. No network: every test injects a transport."""
import httpx
import pytest

from app.services.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubNotFound,
    GitHubRateLimited,
)


def _client(handler) -> GitHubClient:
    return GitHubClient(token="gho_test", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_get_tree_returns_every_path():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "tree": [
                {"path": "docker-compose.yml", "type": "blob"},
                {"path": "infra/main.tf", "type": "blob"},
                {"path": "infra", "type": "tree"},
            ],
            "truncated": False,
        })

    result = await _client(handler).get_tree("o", "r", "main")
    # Directories are not files to parse.
    assert result.paths == ["docker-compose.yml", "infra/main.tf"]
    assert result.truncated is False


@pytest.mark.asyncio
async def test_a_truncated_tree_is_reported_not_swallowed():
    """GitHub silently returns a partial tree for large repos. Unreported, a
    scan of a big repository looks exactly like a complete one."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "tree": [{"path": "docker-compose.yml", "type": "blob"}],
            "truncated": True,
        })

    result = await _client(handler).get_tree("o", "r", "main")
    assert result.truncated is True


@pytest.mark.asyncio
async def test_401_becomes_an_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(GitHubAuthError):
        await _client(handler).get_tree("o", "r", "main")


@pytest.mark.asyncio
async def test_a_rate_limit_carries_its_reset_time():
    """403 with remaining=0 is a rate limit, not a permission problem — the
    caller needs to say when it will clear rather than telling the user to
    check their access."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "rate limit exceeded"}, headers={
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1786000000",
        })

    with pytest.raises(GitHubRateLimited) as excinfo:
        await _client(handler).get_tree("o", "r", "main")
    assert excinfo.value.reset_at is not None


@pytest.mark.asyncio
async def test_a_403_that_is_not_a_rate_limit_is_not_reported_as_one():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"}, headers={
            "X-RateLimit-Remaining": "4999",
        })

    with pytest.raises(GitHubNotFound):
        await _client(handler).get_tree("o", "r", "main")


@pytest.mark.asyncio
async def test_404_becomes_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(GitHubNotFound):
        await _client(handler).get_tree("o", "r", "main")


@pytest.mark.asyncio
async def test_get_blob_decodes_base64_content():
    import base64

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "content": base64.b64encode(b"services:\n  api:\n").decode(),
            "encoding": "base64",
        })

    assert await _client(handler).get_blob("o", "r", "docker-compose.yml", "main") == (
        b"services:\n  api:\n"
    )


@pytest.mark.asyncio
async def test_get_default_branch_reads_it_from_the_repo():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"default_branch": "trunk"})

    assert await _client(handler).get_default_branch("o", "r") == "trunk"


@pytest.mark.asyncio
async def test_the_token_is_sent_as_a_bearer_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"default_branch": "main"})

    await _client(handler).get_default_branch("o", "r")
    assert seen["auth"] == "Bearer gho_test"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_github_client.py -q
```

Expected: collection error — no module `app.services.github_client`.

- [ ] **Step 3: Implement**

Create `backend/app/services/github_client.py`:

```python
"""Thin GitHub REST client. HTTP only — no database, no business logic.

The transport is injectable so the suite never touches the network.
"""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

_API = "https://api.github.com"
_TIMEOUT = 20.0


class GitHubAuthError(RuntimeError):
    """401 — the token is revoked, expired, or wrong."""


class GitHubNotFound(RuntimeError):
    """404, or a 403 that is not a rate limit: gone, or no access."""


class GitHubRateLimited(RuntimeError):
    def __init__(self, reset_at: Optional[datetime]) -> None:
        super().__init__("GitHub API rate limit exceeded")
        self.reset_at = reset_at


@dataclass(frozen=True)
class TreeResult:
    paths: list[str]
    #: GitHub silently returns a partial tree for large repositories. Callers
    #: must surface this: a partial scan that reports success is worse than a
    #: scan that fails.
    truncated: bool


class GitHubClient:
    def __init__(self, token: str, transport: Optional[httpx.BaseTransport] = None) -> None:
        self._token = token
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=_TIMEOUT,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise GitHubAuthError("GitHub rejected the stored token")
        if response.status_code == 403:
            # A 403 is only a rate limit when the remaining count is zero;
            # otherwise it is an access problem and saying "try later" would
            # send the user to wait for something that will never change.
            if response.headers.get("X-RateLimit-Remaining") == "0":
                raw = response.headers.get("X-RateLimit-Reset")
                reset_at = (
                    datetime.fromtimestamp(int(raw), tz=timezone.utc) if raw else None
                )
                raise GitHubRateLimited(reset_at)
            raise GitHubNotFound("GitHub denied access to this repository")
        if response.status_code == 404:
            raise GitHubNotFound("repository not found, or the token cannot see it")
        response.raise_for_status()

    async def get_default_branch(self, owner: str, repo: str) -> str:
        async with self._client() as client:
            response = await client.get(f"{_API}/repos/{owner}/{repo}")
            self._raise_for_status(response)
            return response.json()["default_branch"]

    async def get_tree(self, owner: str, repo: str, ref: str) -> TreeResult:
        async with self._client() as client:
            response = await client.get(
                f"{_API}/repos/{owner}/{repo}/git/trees/{ref}",
                params={"recursive": "1"},
            )
            self._raise_for_status(response)
            payload = response.json()
        return TreeResult(
            paths=[e["path"] for e in payload.get("tree", []) if e.get("type") == "blob"],
            truncated=bool(payload.get("truncated", False)),
        )

    async def get_blob(self, owner: str, repo: str, path: str, ref: str) -> bytes:
        async with self._client() as client:
            response = await client.get(
                f"{_API}/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}
            )
            self._raise_for_status(response)
            payload = response.json()
        if payload.get("encoding") != "base64":
            raise RuntimeError(f"unexpected content encoding: {payload.get('encoding')}")
        return base64.b64decode(payload["content"])
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_github_client.py -q
```

Expected: `9 passed`. (No PostgreSQL leg — this task touches no database.)

- [ ] **Step 5: Verify the tests discriminate**

Back the file up with `cp`; restore with `cp`, never `git checkout`.

1. In `get_tree`, hardcode `truncated=False`. Expected: `test_a_truncated_tree_is_reported_not_swallowed` FAILS.
2. In `_raise_for_status`, treat every 403 as a rate limit (drop the remaining-count check). Expected: `test_a_403_that_is_not_a_rate_limit_is_not_reported_as_one` FAILS.
3. In `get_tree`, stop filtering on `type == "blob"`. Expected: `test_get_tree_returns_every_path` FAILS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/github_client.py backend/tests/services/test_github_client.py
git commit -m "feat(github): REST client with typed errors and truncation reporting"
```

---

### Task 3: OAuth device flow

**Files:**
- Create: `backend/app/services/github_oauth_service.py`, `backend/app/api/v1/integrations_github.py`
- Modify: `backend/app/core/config.py` (add `GITHUB_OAUTH_CLIENT_ID: str = ""`), `backend/app/main.py`
- Test: `backend/tests/integration/test_github_integration_api.py`

**Interfaces:**
- Consumes: `put_secret`/`get_secret`/`delete_secret` from Task 1.
- Produces: `GET/POST/DELETE /api/v1/integrations/github…`. Task 6 relies on the token being stored under kind `github_oauth_token`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_github_integration_api.py`:

```python
"""The GitHub connect journey. No network: the device-flow HTTP calls are patched."""
import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import secrets as secrets_module
from app.services import tenant_secret_service


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(
        secrets_module.settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    from app.services import github_oauth_service
    monkeypatch.setattr(
        github_oauth_service.settings, "GITHUB_OAUTH_CLIENT_ID", "Iv1.testclient"
    )


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_status_is_disconnected_before_anything_happens(client, auth_headers):
    resp = await client.get("/api/v1/integrations/github", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


@pytest.mark.asyncio
async def test_connect_returns_the_user_code_but_never_the_device_code(
    client, auth_headers, monkeypatch
):
    """The device_code redeems the token. If it reached the browser it would be
    a credential handed to the client."""
    from app.services import github_oauth_service

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "SECRET_DEVICE_CODE",
            "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(handler))

    resp = await client.post("/api/v1/integrations/github/connect", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_code"] == "WDJB-MJHT"
    assert body["verification_uri"] == "https://github.com/login/device"
    assert "SECRET_DEVICE_CODE" not in resp.text
    assert "device_code" not in body


@pytest.mark.asyncio
async def test_polling_stores_the_token_and_reports_connected(
    client, auth_headers, db_session, test_tenant, monkeypatch
):
    from app.services import github_oauth_service

    def device_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "SECRET_DEVICE_CODE", "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler))
    started = await client.post("/api/v1/integrations/github/connect", headers=auth_headers)
    handle = started.json()["handle"]

    def token_handler(request: httpx.Request) -> httpx.Response:
        if "oauth/access_token" in str(request.url):
            return httpx.Response(200, json={"access_token": "gho_realtoken",
                                             "token_type": "bearer"})
        return httpx.Response(200, json={"login": "octocat"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(token_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{handle}/poll", headers=auth_headers
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["status"] == "connected"

    stored = await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token"
    )
    assert stored == "gho_realtoken"

    status = await client.get("/api/v1/integrations/github", headers=auth_headers)
    assert status.json()["connected"] is True
    assert status.json()["github_login"] == "octocat"
    # The token itself is never returned by any endpoint.
    assert "gho_realtoken" not in status.text


@pytest.mark.asyncio
async def test_authorization_pending_is_reported_without_storing_anything(
    client, auth_headers, db_session, test_tenant, monkeypatch
):
    from app.services import github_oauth_service

    def device_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "SECRET_DEVICE_CODE", "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler))
    handle = (await client.post(
        "/api/v1/integrations/github/connect", headers=auth_headers)).json()["handle"]

    def pending_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "authorization_pending"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(pending_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{handle}/poll", headers=auth_headers
    )
    assert polled.json()["status"] == "pending"
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token") is None


@pytest.mark.asyncio
async def test_access_denied_is_reported(client, auth_headers, monkeypatch):
    from app.services import github_oauth_service

    def device_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "D", "user_code": "U",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler))
    handle = (await client.post(
        "/api/v1/integrations/github/connect", headers=auth_headers)).json()["handle"]

    def denied_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "access_denied"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(denied_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{handle}/poll", headers=auth_headers
    )
    assert polled.json()["status"] == "denied"


@pytest.mark.asyncio
async def test_disconnect_removes_the_token(
    client, auth_headers, db_session, test_tenant, test_user
):
    await tenant_secret_service.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc",
        created_by=test_user.id,
    )
    await db_session.commit()

    resp = await client.delete("/api/v1/integrations/github", headers=auth_headers)
    assert resp.status_code == 200
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token") is None


@pytest.mark.asyncio
async def test_connect_without_a_client_id_is_503(client, auth_headers, monkeypatch):
    """A clear answer beats failing obscurely inside an HTTP call."""
    from app.services import github_oauth_service
    monkeypatch.setattr(github_oauth_service.settings, "GITHUB_OAUTH_CLIENT_ID", "")

    resp = await client.post("/api/v1/integrations/github/connect", headers=auth_headers)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_a_non_admin_cannot_connect(client, member_auth_headers):
    """Connecting binds a credential for the whole tenant — admin only.

    If the suite has no non-admin fixture, create a Member-role user and log in
    within this test rather than skipping the check.
    """
    resp = await client.post("/api/v1/integrations/github/connect", headers=member_auth_headers)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_github_integration_api.py -q
```

Expected: 404s from the missing router, and a collection error for `github_oauth_service`.

- [ ] **Step 3: Add the config**

`backend/app/core/config.py`, inside `Settings`:

```python
    # OAuth App client id for the GitHub device flow. Device flow needs no
    # client secret, which is a large part of why it was chosen.
    GITHUB_OAUTH_CLIENT_ID: str = ""
```

- [ ] **Step 4: Implement the service**

Create `backend/app/services/github_oauth_service.py`:

```python
"""GitHub OAuth device flow.

The user is present while they authorise, so polling happens inside the
request cycle — this integration needs no scheduler, which is what keeps it
clear of infrastructure the app does not have.
"""
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import tenant_secret_service

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"

TOKEN_KIND = "github_oauth_token"
PENDING_KIND = "github_device_pending"
LOGIN_KIND = "github_login"

#: Read-only: this integration never writes to GitHub.
SCOPE = "repo"


def _transport() -> Optional[httpx.BaseTransport]:
    """Seam for tests; None means the real network."""
    return None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=_transport(), timeout=20.0, headers={"Accept": "application/json"}
    )


class GitHubNotConfigured(RuntimeError):
    pass


def _require_client_id() -> str:
    if not settings.GITHUB_OAUTH_CLIENT_ID:
        raise GitHubNotConfigured("GITHUB_OAUTH_CLIENT_ID is not set")
    return settings.GITHUB_OAUTH_CLIENT_ID


async def start_device_flow(db: AsyncSession, tenant_id: int, user_id: int) -> dict:
    """Begin the flow. The device_code is stored encrypted and never returned."""
    client_id = _require_client_id()
    async with _client() as http:
        response = await http.post(
            DEVICE_CODE_URL, data={"client_id": client_id, "scope": SCOPE}
        )
        response.raise_for_status()
        payload = response.json()

    handle = pysecrets.token_urlsafe(16)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(payload.get("expires_in", 900))
    )
    # The handle keys the pending row; the device_code stays server-side.
    await tenant_secret_service.put_secret(
        db, tenant_id, PENDING_KIND,
        f"{handle}:{payload['device_code']}",
        created_by=user_id, expires_at=expires_at,
    )
    return {
        "handle": handle,
        "user_code": payload["user_code"],
        "verification_uri": payload["verification_uri"],
        "expires_in": int(payload.get("expires_in", 900)),
        "interval": int(payload.get("interval", 5)),
    }


async def poll_device_flow(
    db: AsyncSession, tenant_id: int, user_id: int, handle: str
) -> dict:
    """Poll GitHub once. Returns {"status": pending|slow_down|connected|denied|expired}."""
    client_id = _require_client_id()
    stored = await tenant_secret_service.get_secret(db, tenant_id, PENDING_KIND)
    if stored is None:
        return {"status": "expired"}
    stored_handle, _, device_code = stored.partition(":")
    if stored_handle != handle:
        return {"status": "expired"}

    async with _client() as http:
        response = await http.post(ACCESS_TOKEN_URL, data={
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        response.raise_for_status()
        payload = response.json()

    error = payload.get("error")
    if error == "authorization_pending":
        return {"status": "pending"}
    if error == "slow_down":
        return {"status": "slow_down", "interval": int(payload.get("interval", 10))}
    if error == "access_denied":
        await tenant_secret_service.delete_secret(db, tenant_id, PENDING_KIND)
        return {"status": "denied"}
    if error == "expired_token":
        await tenant_secret_service.delete_secret(db, tenant_id, PENDING_KIND)
        return {"status": "expired"}

    token = payload["access_token"]
    async with _client() as http:
        who = await http.get(USER_URL, headers={"Authorization": f"Bearer {token}"})
        login = who.json().get("login", "") if who.status_code == 200 else ""

    await tenant_secret_service.put_secret(
        db, tenant_id, TOKEN_KIND, token, created_by=user_id
    )
    # The login is not a secret, but it lives here so status has one place to
    # read from rather than a second table for one string.
    await tenant_secret_service.put_secret(
        db, tenant_id, LOGIN_KIND, login, created_by=user_id
    )
    await tenant_secret_service.delete_secret(db, tenant_id, PENDING_KIND)
    return {"status": "connected", "github_login": login}


async def get_status(db: AsyncSession, tenant_id: int) -> dict:
    token = await tenant_secret_service.get_secret(db, tenant_id, TOKEN_KIND)
    if token is None:
        return {"connected": False, "github_login": None, "connected_at": None}
    login = await tenant_secret_service.get_secret(db, tenant_id, LOGIN_KIND)
    return {"connected": True, "github_login": login or None, "connected_at": None}


async def disconnect(db: AsyncSession, tenant_id: int) -> None:
    await tenant_secret_service.delete_secret(db, tenant_id, TOKEN_KIND)
    await tenant_secret_service.delete_secret(db, tenant_id, LOGIN_KIND)
    await tenant_secret_service.delete_secret(db, tenant_id, PENDING_KIND)
```

`get_status` returns `connected_at: None` for now — the row's `created_at` would serve, but reading it means a second query and the UI does not use it yet. If a later task needs it, take it from `TenantSecret.created_at`.

- [ ] **Step 5: Implement the endpoints**

Create `backend/app/api/v1/integrations_github.py`:

```python
"""GitHub integration: connect, poll, status, disconnect."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_tenant_admin
from app.db.base import get_db
from app.services import github_oauth_service
from app.services.github_oauth_service import GitHubNotConfigured

router = APIRouter(prefix="/integrations/github", tags=["integrations"])


class ConnectStarted(BaseModel):
    handle: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class IntegrationStatus(BaseModel):
    connected: bool
    github_login: str | None = None
    connected_at: str | None = None


@router.get("", response_model=IntegrationStatus)
async def github_status(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Never returns the token — only whether one is held, and whose it is."""
    return await github_oauth_service.get_status(db, current_user.active_tenant_id)


@router.post("/connect", response_model=ConnectStarted)
async def github_connect(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    try:
        return await github_oauth_service.start_device_flow(
            db, current_user.active_tenant_id, current_user.id
        )
    except GitHubNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.post("/connect/{handle}/poll")
async def github_connect_poll(
    handle: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    try:
        return await github_oauth_service.poll_device_flow(
            db, current_user.active_tenant_id, current_user.id, handle
        )
    except GitHubNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.delete("")
async def github_disconnect(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Local only. GitHub's own grant is unaffected — the UI must say so."""
    await github_oauth_service.disconnect(db, current_user.active_tenant_id)
    return {"disconnected": True}
```

Register it in `backend/app/main.py` beside the other routers:

```python
app.include_router(integrations_github_router.router, prefix="/api/v1")
```

with the matching import alongside the existing router imports.

- [ ] **Step 6: Run the tests on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_github_integration_api.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest tests/integration/test_github_integration_api.py -q
```

Expected: `8 passed` on each. If the suite has no non-admin auth fixture, create the Member user inside that one test rather than deleting the assertion.

- [ ] **Step 7: Verify the tests discriminate**

Back files up with `cp`; restore with `cp`, never `git checkout`.

1. Add `device_code` to `start_device_flow`'s return dict. Expected: `test_connect_returns_the_user_code_but_never_the_device_code` FAILS.
2. In `poll_device_flow`, store the token before checking `error`. Expected: `test_authorization_pending_is_reported_without_storing_anything` FAILS.
3. Change `require_tenant_admin()` to `get_current_user` on `/connect`. Expected: `test_a_non_admin_cannot_connect` FAILS.
4. Drop the `stored_handle != handle` check. Expected: no test fails — **report this**, and add a test that a wrong handle cannot redeem another flow's device code.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/github_oauth_service.py \
        backend/app/api/v1/integrations_github.py backend/app/main.py \
        backend/app/core/config.py \
        backend/tests/integration/test_github_integration_api.py
git commit -m "feat(github): OAuth device-flow connect journey"
```

---

### Task 4: Detector registry and the Compose detector

**Files:**
- Create: `backend/app/services/scanning/__init__.py`, `backend/app/services/scanning/registry.py`, `backend/app/services/scanning/detectors/__init__.py`, `backend/app/services/scanning/detectors/compose.py`
- Test: `backend/tests/services/test_scanning_registry.py`

**Interfaces:**
- Produces: `Detector`, `ParseContext`, `DetectorResult`, `DETECTORS`. Tasks 5 and 6 consume all four.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_scanning_registry.py`:

```python
"""The detector registry.

Adding a technology must be a module plus a list entry, and must not be able
to disturb detectors that already work.
"""
import pytest

from app.services.scanning.registry import DETECTORS, DetectorResult, ParseContext
from app.services.scanning.detectors.compose import DOCKER_COMPOSE


@pytest.mark.parametrize("path", [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "deploy/docker-compose.yml",
    "a/b/c/compose.yaml",
])
def test_compose_claims_compose_files_at_any_depth(path):
    assert DOCKER_COMPOSE.matches(path) is True


@pytest.mark.parametrize("path", [
    "main.tf",
    "README.md",
    "docker-compose.yml.bak",
    "not-compose.yml",
    "composer.json",
])
def test_compose_does_not_claim_unrelated_files(path):
    assert DOCKER_COMPOSE.matches(path) is False


def test_every_registered_detector_has_a_unique_name():
    names = [d.name for d in DETECTORS]
    assert len(names) == len(set(names))


def test_detector_result_totals_are_addable():
    """The scan sums results across detectors without knowing what any did."""
    a = DetectorResult(subsystems_created=1, subsystems_updated=2, dependencies_written=3)
    b = DetectorResult(subsystems_created=10, subsystems_updated=20, dependencies_written=30)
    total = a + b
    assert (total.subsystems_created, total.subsystems_updated, total.dependencies_written) == (
        11, 22, 33
    )


def test_warnings_survive_addition():
    a = DetectorResult(warnings=["a"])
    b = DetectorResult(warnings=["b"])
    assert (a + b).warnings == ["a", "b"]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_scanning_registry.py -q
```

Expected: collection error — no `app.services.scanning`.

- [ ] **Step 3: Implement the registry**

Create `backend/app/services/scanning/__init__.py` (empty) and `backend/app/services/scanning/registry.py`:

```python
"""Detector registry.

A detector is a name, a path predicate, and a parse function. Adding one is a
module plus an entry in DETECTORS: it cannot alter traversal, authentication
or rate-limit handling, because it never sees them — it receives only the
paths it claimed.
"""
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class DetectorResult:
    subsystems_created: int = 0
    subsystems_updated: int = 0
    dependencies_written: int = 0
    warnings: list[str] = field(default_factory=list)

    def __add__(self, other: "DetectorResult") -> "DetectorResult":
        return DetectorResult(
            subsystems_created=self.subsystems_created + other.subsystems_created,
            subsystems_updated=self.subsystems_updated + other.subsystems_updated,
            dependencies_written=self.dependencies_written + other.dependencies_written,
            warnings=[*self.warnings, *other.warnings],
        )


@dataclass(frozen=True)
class ParseContext:
    content: bytes
    path: str
    system_id: int
    tenant_id: int
    db: AsyncSession
    #: Fetch another file from the same repository. A Helm or Kustomize
    #: detector needs a companion file (values.yaml, an .env beside a compose
    #: file); without this it would have to own the walk.
    fetch: Callable[[str], Awaitable[Optional[bytes]]]


@dataclass(frozen=True)
class Detector:
    name: str
    matches: Callable[[str], bool]
    parse: Callable[[ParseContext], Awaitable[DetectorResult]]
```

- [ ] **Step 4: Implement the Compose detector**

Create `backend/app/services/scanning/detectors/__init__.py` (empty) and `backend/app/services/scanning/detectors/compose.py`:

```python
"""Compose detector — delegates to the importer that already exists.

Deliberately adds no parsing of its own: it is the control that proves the
registry works against known-good code.
"""
import re

from app.services import docker_compose_import_service
from app.services.scanning.registry import Detector, DetectorResult, ParseContext

# Any depth; the filename must be exactly one of the four Compose spellings.
_PATTERN = re.compile(r"(?:^|/)(?:docker-compose|compose)\.ya?ml$")


def _matches(path: str) -> bool:
    return _PATTERN.search(path) is not None


async def _parse(ctx: ParseContext) -> DetectorResult:
    result = await docker_compose_import_service.import_docker_compose(
        system_id=ctx.system_id,
        tenant_id=ctx.tenant_id,
        content=ctx.content,
        db=ctx.db,
    )
    return DetectorResult(
        subsystems_created=result.get("subsystems_created", 0),
        subsystems_updated=result.get("subsystems_updated", 0),
        dependencies_written=result.get("dependencies_created", 0),
    )


DOCKER_COMPOSE = Detector(name="docker_compose", matches=_matches, parse=_parse)
```

Create the registry list at the bottom of `registry.py`… **no** — to avoid a circular import (detectors import the registry), put `DETECTORS` in `backend/app/services/scanning/detectors/__init__.py`:

```python
from app.services.scanning.detectors.compose import DOCKER_COMPOSE
from app.services.scanning.registry import Detector

#: Every registered detector. Adding one is an import plus an entry here.
DETECTORS: list[Detector] = [DOCKER_COMPOSE]
```

Update the test's import to `from app.services.scanning.detectors import DETECTORS`.

Do **not** add a `get_detectors()` helper to `registry.py` — Task 6's scanner defines the
single lazy accessor, and two of them would drift.

**Check the actual return keys** of `docker_compose_import_service.import_docker_compose` in `backend/app/services/docker_compose_import_service.py` and map them correctly — if they differ from `subsystems_created` / `subsystems_updated` / `dependencies_created`, use the real names and say so in your report.

- [ ] **Step 5: Run to verify they pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_scanning_registry.py -q
```

Expected: `13 passed`.

- [ ] **Step 6: Verify the tests discriminate**

Back the file up with `cp`; restore with `cp`.

1. Loosen `_PATTERN` to `r"compose"`. Expected: `test_compose_does_not_claim_unrelated_files` FAILS on `composer.json`.
2. Anchor `_PATTERN` with `^` so it only matches at the repo root. Expected: the parametrised depth cases FAIL.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scanning/ backend/tests/services/test_scanning_registry.py
git commit -m "feat(scanning): detector registry with the Compose detector"
```

---

### Task 5: Terraform HCL detector

**Files:**
- Create: `backend/app/services/terraform_hcl_import_service.py`, `backend/app/services/scanning/detectors/terraform_hcl.py`
- Modify: `backend/app/services/scanning/detectors/__init__.py`, `backend/pyproject.toml`
- Test: `backend/tests/services/test_terraform_hcl_import_service.py`

**Interfaces:**
- Consumes: `Detector`, `ParseContext`, `DetectorResult` from Task 4.
- Produces: `TERRAFORM_HCL` in `DETECTORS`; `import_terraform_hcl(system_id, tenant_id, content, db) -> dict`.

This task is also the proof of the extensibility claim: **it must add a detector without modifying `registry.py`, `compose.py`, or the scanner.**

- [ ] **Step 1: Add the dependency**

`backend/pyproject.toml`:

```toml
    # Parses Terraform .tf source. The existing terraform_import_service reads
    # .tfstate, which is normally not committed — a repository scanner needs
    # the source form.
    "python-hcl2==7.3.1",
```

Then `cd backend && uv sync`.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/services/test_terraform_hcl_import_service.py`:

```python
"""Terraform .tf (HCL source) import.

Distinct from terraform_import_service, which parses .tfstate. HCL gives
DECLARED resources: no computed values, no resource ids. The two will not
produce identical rows for the same infrastructure.
"""
import pytest

from app.db.models.system import SubSystem, System
from app.services import terraform_hcl_import_service as svc

TF = b"""
resource "aws_instance" "api" {
  ami           = "ami-123"
  instance_type = "t3.micro"
}

resource "aws_db_instance" "main" {
  engine = "postgres"
}

variable "region" {
  default = "eu-west-2"
}
"""


@pytest.fixture
async def system(db_session, test_tenant):
    row = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_resources_become_subsystems(db_session, test_tenant, system):
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert result["subsystems_created"] == 2

    from sqlalchemy import select
    names = {s.name for s in (await db_session.execute(
        select(SubSystem).where(SubSystem.system_id == system.id)
    )).scalars().all()}
    assert names == {"aws_instance.api", "aws_db_instance.main"}


@pytest.mark.asyncio
async def test_non_resource_blocks_are_ignored(db_session, test_tenant, system):
    """variable/output/provider blocks are not infrastructure to inventory."""
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert result["subsystems_created"] == 2  # not 3 — `variable` excluded


@pytest.mark.asyncio
async def test_reimporting_updates_rather_than_duplicating(
    db_session, test_tenant, system
):
    await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    second = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=TF, db=db_session
    )
    assert second["subsystems_created"] == 0
    assert second["subsystems_updated"] == 2


@pytest.mark.asyncio
async def test_invalid_hcl_raises_a_value_error(db_session, test_tenant, system):
    """The scanner turns this into a per-detector error rather than a 500."""
    with pytest.raises(ValueError):
        await svc.import_terraform_hcl(
            system_id=system.id, tenant_id=test_tenant.id,
            content=b'resource "aws_instance" {{{ broken', db=db_session,
        )


@pytest.mark.asyncio
async def test_an_empty_file_creates_nothing(db_session, test_tenant, system):
    result = await svc.import_terraform_hcl(
        system_id=system.id, tenant_id=test_tenant.id, content=b"", db=db_session
    )
    assert result["subsystems_created"] == 0
```

Add to `backend/tests/services/test_scanning_registry.py`:

```python
def test_terraform_claims_tf_files_only():
    from app.services.scanning.detectors.terraform_hcl import TERRAFORM_HCL

    assert TERRAFORM_HCL.matches("main.tf") is True
    assert TERRAFORM_HCL.matches("infra/modules/vpc/main.tf") is True
    assert TERRAFORM_HCL.matches("terraform.tfstate") is False
    assert TERRAFORM_HCL.matches("notes.txt") is False
    # .tfvars is configuration, not resource declarations.
    assert TERRAFORM_HCL.matches("prod.tfvars") is False


def test_adding_a_detector_did_not_disturb_the_existing_one():
    """The extensibility claim, asserted rather than assumed."""
    from app.services.scanning.detectors import DETECTORS

    names = [d.name for d in DETECTORS]
    assert "docker_compose" in names and "terraform_hcl" in names
    compose = next(d for d in DETECTORS if d.name == "docker_compose")
    assert compose.matches("docker-compose.yml") is True
    assert compose.matches("main.tf") is False
```

- [ ] **Step 3: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_terraform_hcl_import_service.py tests/services/test_scanning_registry.py -q
```

Expected: collection error for the new module.

- [ ] **Step 4: Implement the parser**

Create `backend/app/services/terraform_hcl_import_service.py`:

```python
"""Import Terraform .tf source (HCL) as SubSystems.

Distinct from terraform_import_service, which parses .tfstate. HCL gives
DECLARED resources — no computed values, no resource ids — so this and a
tfstate import of the same infrastructure will not produce identical rows.
Naming is `<type>.<name>`, the address Terraform itself uses.
"""
import io

import hcl2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system import SubSystem


async def import_terraform_hcl(
    system_id: int, tenant_id: int, content: bytes, db: AsyncSession
) -> dict[str, int]:
    if not content.strip():
        return {"subsystems_created": 0, "subsystems_updated": 0}

    try:
        parsed = hcl2.load(io.StringIO(content.decode("utf-8")))
    except Exception as exc:  # hcl2 raises a variety of parser errors
        raise ValueError(f"Invalid Terraform HCL: {exc}") from exc

    # Only `resource` blocks are infrastructure to inventory; variable,
    # output, provider and locals are not.
    addresses: list[str] = []
    for block in parsed.get("resource", []) or []:
        if not isinstance(block, dict):
            continue
        for resource_type, bodies in block.items():
            names = bodies.keys() if isinstance(bodies, dict) else []
            for name in names:
                addresses.append(f"{resource_type}.{name}")

    existing = {
        s.name: s
        for s in (await db.execute(
            select(SubSystem).where(
                SubSystem.system_id == system_id,
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )).scalars().all()
    }

    created = updated = 0
    for address in addresses:
        if address in existing:
            updated += 1
            continue
        db.add(SubSystem(tenant_id=tenant_id, system_id=system_id, name=address))
        created += 1
    await db.flush()
    return {"subsystems_created": created, "subsystems_updated": updated}
```

Check `SubSystem`'s required columns in `backend/app/db/models/system.py` and supply any others it needs; report anything the plan missed.

- [ ] **Step 5: Implement the detector and register it**

Create `backend/app/services/scanning/detectors/terraform_hcl.py`:

```python
"""Terraform HCL detector."""
from app.services import terraform_hcl_import_service
from app.services.scanning.registry import Detector, DetectorResult, ParseContext


def _matches(path: str) -> bool:
    # .tfstate and .tfvars are deliberately excluded: state is not normally
    # committed, and tfvars is configuration rather than resource declarations.
    return path.endswith(".tf")


async def _parse(ctx: ParseContext) -> DetectorResult:
    result = await terraform_hcl_import_service.import_terraform_hcl(
        system_id=ctx.system_id, tenant_id=ctx.tenant_id,
        content=ctx.content, db=ctx.db,
    )
    return DetectorResult(
        subsystems_created=result["subsystems_created"],
        subsystems_updated=result["subsystems_updated"],
    )


TERRAFORM_HCL = Detector(name="terraform_hcl", matches=_matches, parse=_parse)
```

In `backend/app/services/scanning/detectors/__init__.py`, add the import and the entry — **and change nothing else in the package**:

```python
from app.services.scanning.detectors.compose import DOCKER_COMPOSE
from app.services.scanning.detectors.terraform_hcl import TERRAFORM_HCL
from app.services.scanning.registry import Detector

DETECTORS: list[Detector] = [DOCKER_COMPOSE, TERRAFORM_HCL]
```

- [ ] **Step 6: Run the tests on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_terraform_hcl_import_service.py tests/services/test_scanning_registry.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest tests/services/test_terraform_hcl_import_service.py tests/services/test_scanning_registry.py -q
```

Expected: `20 passed` on each.

- [ ] **Step 7: Verify the tests discriminate**

1. Make `_matches` return `path.endswith((".tf", ".tfstate"))`. Expected: `test_terraform_claims_tf_files_only` FAILS.
2. Include every block type, not only `resource`. Expected: `test_non_resource_blocks_are_ignored` FAILS.
3. Always create rather than checking `existing`. Expected: `test_reimporting_updates_rather_than_duplicating` FAILS.

- [ ] **Step 8: Report whether the extensibility claim held**

State in your report whether adding this detector required editing `registry.py`, `compose.py`, or the scanner. If it did, say so plainly — that is the claim failing, and it matters more than the feature.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/terraform_hcl_import_service.py \
        backend/app/services/scanning/detectors/ backend/pyproject.toml backend/uv.lock \
        backend/tests/services/test_terraform_hcl_import_service.py \
        backend/tests/services/test_scanning_registry.py
git commit -m "feat(scanning): Terraform HCL detector"
```

---

### Task 6: The scan endpoint

**Files:**
- Create: `backend/app/services/scanning/scanner.py`
- Modify: `backend/app/api/v1/systems.py`, `backend/app/core/config.py` (`MAX_SCAN_FILES: int = 200`)
- Test: `backend/tests/integration/test_repository_scan_api.py`

**Interfaces:**
- Consumes: `GitHubClient` (Task 2), `get_secret` (Task 1), `DETECTORS`/`ParseContext`/`DetectorResult` (Tasks 4–5).
- Produces: `POST /api/v1/systems/{system_id}/github/scan`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_repository_scan_api.py`:

```python
"""Repository scan. No network: a MockTransport stands in for GitHub."""
import base64
import json

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import secrets as secrets_module
from app.db.models.system import System
from app.services import tenant_secret_service

COMPOSE = b"services:\n  api:\n    image: nginx\n"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(
        secrets_module.settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


@pytest.fixture
async def connected_system(db_session, test_tenant, test_user):
    system = System(
        tenant_id=test_tenant.id, name="Payments",
        github_repository_url="https://github.com/acme/payments",
    )
    db_session.add(system)
    await db_session.flush()
    await tenant_secret_service.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc",
        created_by=test_user.id,
    )
    await db_session.commit()
    return system


def _github(tree, *, truncated=False, blob=COMPOSE):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/git/trees/" in url:
            return httpx.Response(200, json={
                "tree": [{"path": p, "type": "blob"} for p in tree],
                "truncated": truncated,
            })
        if "/contents/" in url:
            return httpx.Response(200, json={
                "content": base64.b64encode(blob).decode(), "encoding": "base64",
            })
        return httpx.Response(200, json={"default_branch": "main"})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_a_scan_reports_per_detector_results(
    client, auth_headers, connected_system, monkeypatch
):
    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["truncated"] is False
    assert body["stopped_early"] is False
    names = {d["detector"] for d in body["detectors"]}
    assert "docker_compose" in names


@pytest.mark.asyncio
async def test_a_truncated_tree_is_reported(
    client, auth_headers, connected_system, monkeypatch
):
    """The one failure mode that otherwise looks exactly like success."""
    from app.services.scanning import scanner
    monkeypatch.setattr(
        scanner, "_transport", lambda: _github(["docker-compose.yml"], truncated=True)
    )

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.json()["truncated"] is True


@pytest.mark.asyncio
async def test_hitting_the_file_cap_is_reported(
    client, auth_headers, connected_system, monkeypatch
):
    from app.services.scanning import scanner
    monkeypatch.setattr(scanner.settings, "MAX_SCAN_FILES", 2)
    monkeypatch.setattr(
        scanner, "_transport",
        lambda: _github(["a/docker-compose.yml", "b/docker-compose.yml",
                         "c/docker-compose.yml"]),
    )

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    body = resp.json()
    assert body["stopped_early"] is True
    assert body["files_scanned"] == 2


@pytest.mark.asyncio
async def test_a_detector_that_raises_does_not_stop_the_others(
    client, auth_headers, connected_system, monkeypatch
):
    """A new detector must not be able to break the ones already working."""
    from app.services.scanning import scanner
    from app.services.scanning.registry import Detector, DetectorResult
    from app.services.scanning.detectors import DOCKER_COMPOSE

    async def _boom(ctx):
        raise RuntimeError("detector exploded")

    broken = Detector(name="broken", matches=lambda p: p.endswith(".yml"), parse=_boom)
    monkeypatch.setattr(scanner, "get_detectors", lambda: [broken, DOCKER_COMPOSE])
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200
    by_name = {d["detector"]: d for d in resp.json()["detectors"]}
    assert by_name["broken"]["errors"]
    assert not by_name["docker_compose"]["errors"]


@pytest.mark.asyncio
async def test_scanning_without_a_connection_is_409(
    client, auth_headers, db_session, test_tenant
):
    system = System(
        tenant_id=test_tenant.id, name="Unconnected",
        github_repository_url="https://github.com/acme/x",
    )
    db_session.add(system)
    await db_session.commit()
    await db_session.refresh(system)

    resp = await client.post(
        f"/api/v1/systems/{system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_a_system_without_a_repository_url_is_422(
    client, auth_headers, db_session, test_tenant, test_user
):
    system = System(tenant_id=test_tenant.id, name="No repo")
    db_session.add(system)
    await tenant_secret_service.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc",
        created_by=test_user.id,
    )
    await db_session.commit()
    await db_session.refresh(system)

    resp = await client.post(
        f"/api/v1/systems/{system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_401_from_github_clears_the_stored_token(
    client, auth_headers, connected_system, db_session, test_tenant, monkeypatch
):
    """Otherwise the UI keeps claiming 'connected' with a dead token."""
    from app.services.scanning import scanner

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    monkeypatch.setattr(scanner, "_transport", lambda: httpx.MockTransport(handler))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 401
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token") is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_repository_scan_api.py -q
```

Expected: 404s — the endpoint does not exist.

- [ ] **Step 3: Add the config**

`backend/app/core/config.py`:

```python
    # A repository with hundreds of .tf files would otherwise mean hundreds of
    # sequential API calls against a rate limit. Hitting this cap is reported,
    # never silent.
    MAX_SCAN_FILES: int = 200
```

- [ ] **Step 4: Implement the scanner**

Create `backend/app/services/scanning/scanner.py`:

```python
"""Walk a repository once, hand matched files to the detectors that claimed them."""
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.github_client import GitHubClient
from app.services.scanning.registry import Detector, DetectorResult, ParseContext

_REPO_URL = re.compile(r"github\.com[:/]+([^/]+)/([^/.]+)")


def _transport() -> Optional[httpx.BaseTransport]:
    """Seam for tests; None means the real network."""
    return None


def get_detectors() -> list[Detector]:
    from app.services.scanning.detectors import DETECTORS
    return DETECTORS


@dataclass
class DetectorReport:
    detector: str
    paths: list[str] = field(default_factory=list)
    result: DetectorResult = field(default_factory=DetectorResult)
    errors: list[str] = field(default_factory=list)


def parse_repo_url(url: Optional[str]) -> tuple[str, str]:
    match = _REPO_URL.search(url or "")
    if not match:
        raise ValueError(
            f"could not read an owner/repo from the system's GitHub URL: {url!r}"
        )
    return match.group(1), match.group(2)


async def scan_repository(
    db: AsyncSession, *, token: str, system_id: int, tenant_id: int, repo_url: str
) -> dict:
    owner, repo = parse_repo_url(repo_url)
    client = GitHubClient(token=token, transport=_transport())

    ref = await client.get_default_branch(owner, repo)
    tree = await client.get_tree(owner, repo, ref)

    detectors = get_detectors()
    reports = {d.name: DetectorReport(detector=d.name) for d in detectors}

    # A path goes to EVERY detector that claims it — "first match wins" would
    # make behaviour depend on registry order.
    claimed: list[tuple[str, list[Detector]]] = []
    for path in tree.paths:
        wanted = [d for d in detectors if d.matches(path)]
        if wanted:
            claimed.append((path, wanted))

    stopped_early = len(claimed) > settings.MAX_SCAN_FILES
    claimed = claimed[: settings.MAX_SCAN_FILES]

    async def fetch(path: str) -> Optional[bytes]:
        try:
            return await client.get_blob(owner, repo, path, ref)
        except Exception:
            return None

    for path, wanted in claimed:
        content = await client.get_blob(owner, repo, path, ref)
        for detector in wanted:
            report = reports[detector.name]
            report.paths.append(path)
            try:
                report.result = report.result + await detector.parse(
                    ParseContext(
                        content=content, path=path, system_id=system_id,
                        tenant_id=tenant_id, db=db, fetch=fetch,
                    )
                )
            except Exception as exc:
                # One detector failing must not take the others with it.
                report.errors.append(f"{path}: {exc}")

    return {
        "ref": ref,
        "files_scanned": len(claimed),
        "truncated": tree.truncated,
        "stopped_early": stopped_early,
        "detectors": [
            {
                "detector": r.detector,
                "paths": r.paths,
                "subsystems_created": r.result.subsystems_created,
                "subsystems_updated": r.result.subsystems_updated,
                "dependencies_written": r.result.dependencies_written,
                "warnings": r.result.warnings,
                "errors": r.errors,
            }
            for r in reports.values()
        ],
    }
```

- [ ] **Step 5: Implement the one-scan-at-a-time guard**

The spec requires a concurrent scan of the same system to be a 409, because two scans would
upsert the same subsystems by name and interleave their writes. Add to `scanner.py`:

```python
#: Systems with a scan in flight. In-process only, which is honest for a
#: single-process deployment: it stops the double-click and the impatient
#: second tab, not a second replica. A distributed lock would need Redis and
#: is not warranted until the app runs more than one worker.
_in_flight: set[tuple[int, int]] = set()


class ScanAlreadyRunning(RuntimeError):
    pass
```

and wrap the body of `scan_repository` so the key is added on entry and removed in a
`finally`:

```python
    key = (tenant_id, system_id)
    if key in _in_flight:
        raise ScanAlreadyRunning("a scan of this system is already running")
    _in_flight.add(key)
    try:
        ...existing body...
    finally:
        _in_flight.discard(key)
```

Add this test to `backend/tests/integration/test_repository_scan_api.py`:

```python
@pytest.mark.asyncio
async def test_a_second_concurrent_scan_is_rejected(
    client, auth_headers, connected_system, monkeypatch
):
    """Two scans would upsert the same subsystems by name and interleave."""
    from app.services.scanning import scanner

    scanner._in_flight.add((connected_system.tenant_id, connected_system.id))
    try:
        resp = await client.post(
            f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
        )
        assert resp.status_code == 409
    finally:
        scanner._in_flight.discard((connected_system.tenant_id, connected_system.id))


@pytest.mark.asyncio
async def test_the_in_flight_marker_is_released_after_a_failure(
    client, auth_headers, connected_system, monkeypatch
):
    """Without the finally, one failed scan would block that system forever."""
    from app.services.scanning import scanner

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    monkeypatch.setattr(scanner, "_transport", lambda: httpx.MockTransport(handler))
    await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert (connected_system.tenant_id, connected_system.id) not in scanner._in_flight
```

- [ ] **Step 6: Implement the endpoint**

In `backend/app/api/v1/systems.py`, add:

```python
@router.post("/{system_id}/github/scan")
async def scan_system_repository(
    system_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Scan the system's GitHub repository and import what the detectors find."""
    tenant_id = current_user.active_tenant_id
    system = await get_system(db, system_id, tenant_id)

    token = await tenant_secret_service.get_secret(db, tenant_id, "github_oauth_token")
    if token is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "GitHub is not connected for this tenant. Connect it under "
            "Administration → GitHub Integration.",
        )

    try:
        return await scanner.scan_repository(
            db, token=token, system_id=system_id, tenant_id=tenant_id,
            repo_url=system.github_repository_url,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except ScanAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except GitHubAuthError:
        # Clear it so the UI stops claiming "connected" with a dead token.
        await tenant_secret_service.delete_secret(db, tenant_id, "github_oauth_token")
        await tenant_secret_service.delete_secret(db, tenant_id, "github_login")
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "GitHub rejected the stored token. Reconnect the integration.",
        )
    except GitHubRateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"GitHub API rate limit exceeded. Resets at {exc.reset_at}.",
        )
    except GitHubNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
```

with imports for `tenant_secret_service`, `scanner`, `ScanAlreadyRunning`, and the three GitHub exceptions.

- [ ] **Step 7: Run the tests on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_repository_scan_api.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest tests/integration/test_repository_scan_api.py -q
```

Expected: `9 passed` on each.

- [ ] **Step 8: Verify the tests discriminate**

1. Hardcode `"truncated": False` in the returned dict. Expected: `test_a_truncated_tree_is_reported` FAILS.
2. Remove the `try/except` around `detector.parse`. Expected: `test_a_detector_that_raises_does_not_stop_the_others` FAILS.
3. Remove the `MAX_SCAN_FILES` slice. Expected: `test_hitting_the_file_cap_is_reported` FAILS.
4. Remove the `delete_secret` calls in the `GitHubAuthError` handler. Expected: `test_a_401_from_github_clears_the_stored_token` FAILS.
5. Replace the `finally: _in_flight.discard(key)` with a discard on the success path only. Expected: `test_the_in_flight_marker_is_released_after_a_failure` FAILS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/scanning/scanner.py backend/app/api/v1/systems.py \
        backend/app/core/config.py backend/tests/integration/test_repository_scan_api.py
git commit -m "feat(scanning): repository scan endpoint"
```

---

### Task 7: Frontend — connect journey and scan

**Files:**
- Create: `frontend/src/types/githubIntegration.ts`, `frontend/src/services/githubIntegrationService.ts`, `frontend/src/pages/admin/GitHubIntegration.tsx`, `frontend/src/components/systems/ScanRepositoryDialog.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/navConfig.tsx`, `frontend/src/pages/systems/SystemDetail.tsx`
- Test: `frontend/src/pages/admin/__tests__/GitHubIntegration.test.tsx`, `frontend/src/components/systems/__tests__/ScanRepositoryDialog.test.tsx`

**Interfaces:**
- Consumes: the endpoints from Tasks 3 and 6.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/admin/__tests__/GitHubIntegration.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/githubIntegrationService', () => ({
  githubIntegrationService: {
    status: vi.fn(),
    connect: vi.fn(),
    poll: vi.fn(),
    disconnect: vi.fn(),
  },
}));

import { githubIntegrationService } from '../../../services/githubIntegrationService';
import GitHubIntegration from '../GitHubIntegration';

function renderPage() {
  return render(
    <MemoryRouter>
      <GitHubIntegration />
    </MemoryRouter>
  );
}

describe('GitHubIntegration', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the user code and the verification link after starting', async () => {
    vi.mocked(githubIntegrationService.status).mockResolvedValue({
      connected: false, github_login: null, connected_at: null,
    });
    vi.mocked(githubIntegrationService.connect).mockResolvedValue({
      handle: 'h1', user_code: 'WDJB-MJHT',
      verification_uri: 'https://github.com/login/device',
      expires_in: 900, interval: 5,
    });
    vi.mocked(githubIntegrationService.poll).mockResolvedValue({ status: 'pending' });

    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: /connect github/i }));

    expect(await screen.findByText('WDJB-MJHT')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /github\.com\/login\/device/i })).toBeInTheDocument();
  });

  it('reports the connected account once polling succeeds', async () => {
    vi.mocked(githubIntegrationService.status).mockResolvedValue({
      connected: true, github_login: 'octocat', connected_at: null,
    });

    renderPage();
    expect(await screen.findByText(/octocat/)).toBeInTheDocument();
  });

  it('says plainly that disconnecting does not revoke the grant at GitHub', async () => {
    // Telling someone their token is dead when it is not would be worse than
    // the extra sentence.
    vi.mocked(githubIntegrationService.status).mockResolvedValue({
      connected: true, github_login: 'octocat', connected_at: null,
    });

    renderPage();
    await screen.findByText(/octocat/);
    expect(screen.getByText(/still need to revoke it in GitHub/i)).toBeInTheDocument();
  });
});
```

Create `frontend/src/components/systems/__tests__/ScanRepositoryDialog.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/githubIntegrationService', () => ({
  githubIntegrationService: { scan: vi.fn() },
}));

import { githubIntegrationService } from '../../../services/githubIntegrationService';
import ScanRepositoryDialog from '../ScanRepositoryDialog';

const RESULT = {
  ref: 'main',
  files_scanned: 2,
  truncated: false,
  stopped_early: false,
  detectors: [
    { detector: 'docker_compose', paths: ['docker-compose.yml'], subsystems_created: 3,
      subsystems_updated: 0, dependencies_written: 2, warnings: [], errors: [] },
  ],
};

describe('ScanRepositoryDialog', () => {
  beforeEach(() => vi.clearAllMocks());

  it('reports what each detector found', async () => {
    vi.mocked(githubIntegrationService.scan).mockResolvedValue(RESULT);
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/docker_compose/)).toBeInTheDocument();
    expect(screen.getByText(/3 subsystems created/i)).toBeInTheDocument();
  });

  it('warns when the repository tree was truncated', async () => {
    // A partial scan must never look like a complete one.
    vi.mocked(githubIntegrationService.scan).mockResolvedValue({ ...RESULT, truncated: true });
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/too large to read in full/i)).toBeInTheDocument();
  });

  it('warns when the file cap stopped the scan early', async () => {
    vi.mocked(githubIntegrationService.scan).mockResolvedValue({
      ...RESULT, stopped_early: true,
    });
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/stopped after/i)).toBeInTheDocument();
  });

  it('shows a detector error without hiding the detectors that worked', async () => {
    vi.mocked(githubIntegrationService.scan).mockResolvedValue({
      ...RESULT,
      detectors: [
        ...RESULT.detectors,
        { detector: 'terraform_hcl', paths: ['main.tf'], subsystems_created: 0,
          subsystems_updated: 0, dependencies_written: 0, warnings: [],
          errors: ['main.tf: Invalid Terraform HCL'] },
      ],
    });
    render(<ScanRepositoryDialog open systemId={1} onClose={() => {}} />);

    await userEvent.click(screen.getByRole('button', { name: /scan/i }));

    expect(await screen.findByText(/Invalid Terraform HCL/)).toBeInTheDocument();
    expect(screen.getByText(/3 subsystems created/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/pages/admin/__tests__/GitHubIntegration.test.tsx src/components/systems/__tests__/ScanRepositoryDialog.test.tsx
```

Expected: FAIL — the modules do not resolve.

- [ ] **Step 3: Implement types and service**

Create `frontend/src/types/githubIntegration.ts`:

```ts
export interface GitHubStatus {
  connected: boolean;
  github_login: string | null;
  connected_at: string | null;
}

export interface DeviceFlowStarted {
  handle: string;
  user_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
}

export type PollStatus = 'pending' | 'slow_down' | 'connected' | 'denied' | 'expired';

export interface PollResult {
  status: PollStatus;
  github_login?: string;
  interval?: number;
}

export interface DetectorReport {
  detector: string;
  paths: string[];
  subsystems_created: number;
  subsystems_updated: number;
  dependencies_written: number;
  warnings: string[];
  errors: string[];
}

export interface ScanResult {
  ref: string;
  files_scanned: number;
  /** GitHub returned a partial tree — the scan saw only part of the repository. */
  truncated: boolean;
  /** The file cap stopped the scan before every match was read. */
  stopped_early: boolean;
  detectors: DetectorReport[];
}
```

Create `frontend/src/services/githubIntegrationService.ts`:

```ts
import api from './api';
import type {
  DeviceFlowStarted, GitHubStatus, PollResult, ScanResult,
} from '../types/githubIntegration';

export const githubIntegrationService = {
  status: (): Promise<GitHubStatus> =>
    api.get('/integrations/github').then((r) => r.data),

  connect: (): Promise<DeviceFlowStarted> =>
    api.post('/integrations/github/connect').then((r) => r.data),

  poll: (handle: string): Promise<PollResult> =>
    api.post(`/integrations/github/connect/${handle}/poll`).then((r) => r.data),

  disconnect: (): Promise<void> =>
    api.delete('/integrations/github').then(() => undefined),

  scan: (systemId: number): Promise<ScanResult> =>
    api.post(`/systems/${systemId}/github/scan`).then((r) => r.data),
};
```

- [ ] **Step 4: Implement the integration page**

Create `frontend/src/pages/admin/GitHubIntegration.tsx` following the shape of the other
pages under `frontend/src/pages/admin/`: a status area, a **Connect GitHub** button, and a
**Disconnect** button.

The only non-obvious part is the polling loop, so here it is in full — everything else is a
`Paper`, a `Button` and a `Typography`:

```tsx
  // GitHub tells us how often to poll and can raise it mid-flow with
  // `slow_down`. Honour both rather than picking our own interval: polling
  // faster than instructed is how a client gets rate-limited.
  useEffect(() => {
    if (!pending) return undefined;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async (delaySeconds: number) => {
      timer = setTimeout(async () => {
        if (cancelled) return;
        try {
          const result = await githubIntegrationService.poll(pending.handle);
          if (cancelled) return;
          if (result.status === 'connected') {
            setPending(null);
            setStatus(await githubIntegrationService.status());
            return;
          }
          if (result.status === 'denied' || result.status === 'expired') {
            setPending(null);
            setError(
              result.status === 'denied'
                ? 'Authorisation was declined on GitHub.'
                : 'The code expired before it was authorised. Start again.'
            );
            return;
          }
          // pending, or slow_down with a longer interval GitHub chose.
          tick(result.interval ?? pending.interval);
        } catch {
          if (!cancelled) {
            setPending(null);
            setError('Lost contact with GitHub while waiting for authorisation.');
          }
        }
      }, delaySeconds * 1000);
    };

    tick(pending.interval);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pending]);
```

Render `pending.user_code` in a `Typography variant="h4"` so it can be read off the screen,
and `pending.verification_uri` as an `<a>` opening in a new tab.

When connected, render the account name and this text verbatim, because it is the honest statement the spec requires:

```tsx
<Typography variant="body2" color="text.secondary">
  Disconnecting removes the token from EnvManager. You will still need to revoke it
  in GitHub under Settings → Applications → Authorized OAuth Apps.
</Typography>
```

Route it at `/admin/github` in `App.tsx` and add a nav entry under Administration in `navConfig.tsx`, following the existing entries' shape.

- [ ] **Step 5: Implement the scan dialog**

Create `frontend/src/components/systems/ScanRepositoryDialog.tsx` — props `{ open: boolean; systemId: number; onClose: () => void }`. A **Scan** button calls `githubIntegrationService.scan(systemId)`; results render one block per detector with paths and counts, phrased as `"{n} subsystems created"`, `"{n} updated"`, `"{n} dependencies"`. Detector `errors` render in an error `Alert` **without suppressing the other detectors' results**.

`truncated` renders: `The repository was too large to read in full — some files were not scanned.`
`stopped_early` renders: `Scan stopped after {files_scanned} files.`

Wire a **Scan repository** button into `SystemDetail.tsx` that opens the dialog, disabled with an explanatory tooltip when the system has no `github_repository_url`.

- [ ] **Step 6: Run the tests, types and lint**

```bash
cd frontend && npx vitest run src/pages/admin src/components/systems && npx tsc --noEmit && npm run lint
```

- [ ] **Step 7: Verify the tests discriminate**

Back files up with `cp`; restore with `cp`.

1. Drop the `truncated` warning from the dialog. Expected: `warns when the repository tree was truncated` FAILS.
2. Render only the first detector. Expected: `shows a detector error without hiding the detectors that worked` FAILS.
3. Remove the revoke-at-GitHub sentence. Expected: `says plainly that disconnecting does not revoke the grant at GitHub` FAILS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/githubIntegration.ts \
        frontend/src/services/githubIntegrationService.ts \
        frontend/src/pages/admin/GitHubIntegration.tsx \
        frontend/src/components/systems/ScanRepositoryDialog.tsx \
        frontend/src/App.tsx frontend/src/components/navConfig.tsx \
        frontend/src/pages/systems/SystemDetail.tsx \
        frontend/src/pages/admin/__tests__/GitHubIntegration.test.tsx \
        frontend/src/components/systems/__tests__/ScanRepositoryDialog.test.tsx
git commit -m "feat(github): connect journey and repository scan UI"
```

---

### Task 8: Deployment notes, verification, and the PR

- [ ] **Step 1: Every gate, both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest -q
cd ../frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

Then the dependency audit, since two dependencies were added:

```bash
cd backend && uv run python scripts/audit_dependencies.py
```

- [ ] **Step 2: Verify in the browser**

`SECRETS_ENCRYPTION_KEY` and `GITHUB_OAUTH_CLIENT_ID` must be in `backend/.env` first. Without a registered OAuth App you can still verify: the integration page renders and reports disconnected; **Connect** without a client id returns a clear 503 rather than an opaque failure; the Scan button is disabled with its tooltip on a system with no repository URL; and a system *with* a URL but no connection reports the 409 message naming where to connect.

**Say plainly in your report which parts you could not verify without a real OAuth App and a real repository** — do not describe an end-to-end scan you did not run.

- [ ] **Step 3: Document the two new deploy-time secrets**

`CLAUDE.md`'s Production Deployment section currently names `SECRET_KEY` and `POSTGRES_PASSWORD` as required. Add `SECRETS_ENCRYPTION_KEY` — how to generate it, and that **losing it makes every stored credential unrecoverable**, requiring every tenant to reconnect. Add `GITHUB_OAUTH_CLIENT_ID` as optional, disabling only the GitHub integration when absent.

Record in `docs/dependency-audit.md` that `cryptography` and `python-hcl2` were added, and why.

- [ ] **Step 4: Update the phase docs**

Mark sub-project 3 (GitHub scanning) shipped in `docs/phases/phase-6.md`, leaving drift detection as the only remainder. Note for whoever takes it that the HCL parser now exists and that declared resources differ from resolved state.

- [ ] **Step 5: Commit, push, open the PR**

- [ ] **Step 6: Confirm all four CI jobs pass before reporting done.** Do not report ready on a partial result.
