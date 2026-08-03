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
