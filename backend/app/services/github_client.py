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


class GitHubError(RuntimeError):
    """Base for every error this client raises.

    Callers catch the specific subclasses they can act on and `GitHubError`
    for the rest; nothing from httpx or a malformed payload should reach them
    untyped.
    """


class GitHubAuthError(GitHubError):
    """401 — the token is revoked, expired, or wrong."""


class GitHubNotFound(GitHubError):
    """404, or a 403 that is not a rate limit: gone, or no access."""


class GitHubRateLimited(GitHubError):
    def __init__(self, reset_at: Optional[datetime]) -> None:
        super().__init__("GitHub API rate limit exceeded")
        self.reset_at = reset_at


class GitHubUnavailable(GitHubError):
    """5xx, or any status this client does not model."""


class GitHubUnexpectedResponse(GitHubError):
    """A 200 whose body is not shaped the way the API documents."""


@dataclass(frozen=True)
class TreeResult:
    paths: list[str]
    #: GitHub silently returns a partial tree for large repositories. Callers
    #: must surface this: a partial scan that reports success is worse than a
    #: scan that fails.
    truncated: bool


class GitHubClient:
    """Thin GitHub REST client.

    Holds one pooled httpx client for its lifetime, so **the caller must call
    `aclose()`** when finished — typically in a `finally`. A scan that forgets
    leaks a connection pool per run.
    """

    def __init__(self, token: str, transport: Optional[httpx.BaseTransport] = None) -> None:
        self._token = token
        self._transport = transport
        self._http: Optional[httpx.AsyncClient] = None

    def _client(self) -> httpx.AsyncClient:
        # One client for the object's lifetime: a scan fetches many blobs in
        # sequence, and a fresh client per call means a new connection (and a
        # new TLS handshake against real GitHub) for each one.
        if self._http is None:
            self._http = httpx.AsyncClient(
                transport=self._transport,
                timeout=_TIMEOUT,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

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
        if response.status_code >= 400:
            raise GitHubUnavailable(
                f"GitHub returned {response.status_code} for {response.request.url.path}"
            )

    async def get_default_branch(self, owner: str, repo: str) -> str:
        client = self._client()
        response = await client.get(f"{_API}/repos/{owner}/{repo}")
        self._raise_for_status(response)
        try:
            return response.json()["default_branch"]
        except (KeyError, ValueError) as exc:
            raise GitHubUnexpectedResponse(
                "repository response had no default_branch"
            ) from exc

    async def get_tree(self, owner: str, repo: str, ref: str) -> TreeResult:
        client = self._client()
        response = await client.get(
            f"{_API}/repos/{owner}/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
        )
        self._raise_for_status(response)
        try:
            payload = response.json()
            paths = [
                entry["path"]
                for entry in payload.get("tree", [])
                if entry.get("type") == "blob"
            ]
            truncated = bool(payload.get("truncated", False))
        except (KeyError, ValueError, TypeError) as exc:
            # ValueError covers json.JSONDecodeError; TypeError covers a
            # payload whose shape is right at the top level and wrong inside.
            raise GitHubUnexpectedResponse(
                "tree response was not shaped as expected"
            ) from exc
        return TreeResult(paths=paths, truncated=truncated)

    async def get_blob(self, owner: str, repo: str, path: str, ref: str) -> bytes:
        client = self._client()
        response = await client.get(
            f"{_API}/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}
        )
        self._raise_for_status(response)
        try:
            payload = response.json()
            if payload.get("encoding") != "base64":
                raise GitHubUnexpectedResponse(
                    f"unexpected content encoding: {payload.get('encoding')}"
                )
            return base64.b64decode(payload["content"])
        except GitHubUnexpectedResponse:
            raise
        except (KeyError, ValueError, TypeError) as exc:
            # binascii.Error subclasses ValueError, so corrupt base64 lands here
            # rather than escaping as an untyped decode failure.
            raise GitHubUnexpectedResponse(
                f"could not read blob content for {path}"
            ) from exc
