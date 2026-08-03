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

#: `repo` is the narrowest OAuth App scope that can read private repositories.
#: It is NOT read-only — OAuth Apps have no read-only equivalent — even though
#: this integration only ever reads. A GitHub App with `contents: read` is the
#: way to narrow it, and is recorded as the follow-on.
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


class GitHubOAuthError(RuntimeError):
    """Any GitHub response this flow does not model: a transport failure, a
    non-2xx status, a non-JSON body, a JSON body missing a key the flow
    depends on, or an `error` string neither `poll_device_flow` nor the
    caller recognises (`device_flow_disabled`, `incorrect_client_credentials`,
    `unsupported_grant_type`, ...). Without this, any of those becomes a bare
    KeyError/HTTPStatusError that reaches the endpoint untyped and turns into
    a 500 — "Lost contact with GitHub" in the UI — instead of the 502 that
    actually describes what happened.
    """


def _require_client_id() -> str:
    if not settings.GITHUB_OAUTH_CLIENT_ID:
        raise GitHubNotConfigured("GITHUB_OAUTH_CLIENT_ID is not set")
    return settings.GITHUB_OAUTH_CLIENT_ID


async def start_device_flow(db: AsyncSession, tenant_id: int, user_id: int) -> dict:
    """Begin the flow. The device_code is stored encrypted and never returned."""
    client_id = _require_client_id()
    async with _client() as http:
        try:
            response = await http.post(
                DEVICE_CODE_URL, data={"client_id": client_id, "scope": SCOPE}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise GitHubOAuthError(f"GitHub device code request failed: {exc}") from exc
        except ValueError as exc:
            raise GitHubOAuthError(
                f"GitHub device code response was not JSON: {exc}"
            ) from exc

    try:
        device_code = payload["device_code"]
        user_code = payload["user_code"]
        verification_uri = payload["verification_uri"]
    except (KeyError, TypeError) as exc:
        raise GitHubOAuthError(
            f"GitHub device code response was missing a required field: {exc}"
        ) from exc

    handle = pysecrets.token_urlsafe(16)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(payload.get("expires_in", 900))
    )
    # The handle keys the pending row; the device_code stays server-side.
    await tenant_secret_service.put_secret(
        db, tenant_id, PENDING_KIND,
        f"{handle}:{device_code}",
        created_by=user_id, expires_at=expires_at,
    )
    return {
        "handle": handle,
        "user_code": user_code,
        "verification_uri": verification_uri,
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
        try:
            response = await http.post(ACCESS_TOKEN_URL, data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise GitHubOAuthError(f"GitHub token request failed: {exc}") from exc
        except ValueError as exc:
            raise GitHubOAuthError(f"GitHub token response was not JSON: {exc}") from exc

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
    if error is not None:
        # device_flow_disabled, incorrect_client_credentials,
        # unsupported_grant_type, or any other error string GitHub documents
        # that this flow does not otherwise act on. Falling through would
        # read payload["access_token"] from a response that never had one.
        raise GitHubOAuthError(f"GitHub device flow error: {error}")

    try:
        token = payload["access_token"]
    except (KeyError, TypeError) as exc:
        raise GitHubOAuthError(
            f"GitHub token response was missing access_token: {exc}"
        ) from exc
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
    created_at = await tenant_secret_service.get_created_at(db, tenant_id, TOKEN_KIND)
    return {
        "connected": True,
        "github_login": login or None,
        "connected_at": created_at.isoformat() if created_at else None,
    }


async def disconnect(db: AsyncSession, tenant_id: int) -> None:
    await tenant_secret_service.delete_secret(db, tenant_id, TOKEN_KIND)
    await tenant_secret_service.delete_secret(db, tenant_id, LOGIN_KIND)
    await tenant_secret_service.delete_secret(db, tenant_id, PENDING_KIND)
