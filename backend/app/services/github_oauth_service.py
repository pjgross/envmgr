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
