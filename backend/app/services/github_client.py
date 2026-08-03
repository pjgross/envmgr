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
