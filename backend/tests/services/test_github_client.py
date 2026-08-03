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


@pytest.mark.asyncio
async def test_a_500_is_a_typed_error_not_a_raw_httpx_error():
    """A caller written against this client's exceptions must be able to catch
    everything it raises."""
    from app.services.github_client import GitHubError, GitHubUnavailable

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "Server Error"})

    with pytest.raises(GitHubUnavailable) as excinfo:
        await _client(handler).get_tree("o", "r", "main")
    assert isinstance(excinfo.value, GitHubError)


@pytest.mark.asyncio
async def test_a_malformed_body_is_a_typed_error_not_a_key_error():
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(GitHubUnexpectedResponse):
        await _client(handler).get_default_branch("o", "r")


@pytest.mark.asyncio
async def test_a_file_too_large_for_the_contents_api_is_an_error_not_empty_bytes():
    """GitHub returns encoding "none" with empty content above ~1MB. Returning
    b"" would hand a detector an empty file and look like a successful parse."""
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": "", "encoding": "none"})

    with pytest.raises(GitHubUnexpectedResponse):
        await _client(handler).get_blob("o", "r", "big.tf", "main")


@pytest.mark.asyncio
async def test_a_non_json_tree_body_is_typed():
    """The previous fix covered get_default_branch and left this open."""
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(GitHubUnexpectedResponse):
        await _client(handler).get_tree("o", "r", "main")


@pytest.mark.asyncio
async def test_a_non_json_blob_body_is_typed():
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(GitHubUnexpectedResponse):
        await _client(handler).get_blob("o", "r", "a.tf", "main")


@pytest.mark.asyncio
async def test_corrupt_base64_content_is_typed_not_a_decode_error():
    """binascii.Error would otherwise reach the scanner untyped."""
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": "!!!not base64!!!",
                                         "encoding": "base64"})

    with pytest.raises(GitHubUnexpectedResponse):
        await _client(handler).get_blob("o", "r", "a.tf", "main")


@pytest.mark.asyncio
async def test_the_encoding_message_survives_the_wrapper():
    """The bare re-raise keeps the specific message instead of the generic one."""
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": "", "encoding": "none"})

    with pytest.raises(GitHubUnexpectedResponse, match="unexpected content encoding"):
        await _client(handler).get_blob("o", "r", "big.tf", "main")


@pytest.mark.asyncio
async def test_the_same_http_client_is_reused_across_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"default_branch": "main"})

    client = _client(handler)
    await client.get_default_branch("o", "r")
    first = client._http
    await client.get_default_branch("o", "r")
    assert client._http is first
    await client.aclose()
    assert client._http is None


@pytest.mark.asyncio
async def test_a_tree_response_without_a_tree_key_is_an_error_not_an_empty_repo():
    """`.get("tree", [])` would report a malformed body as a repository with
    nothing in it — a successful scan that saw nothing."""
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"truncated": False})

    with pytest.raises(GitHubUnexpectedResponse):
        await _client(handler).get_tree("o", "r", "main")


@pytest.mark.asyncio
async def test_a_tree_response_without_truncated_defaults_to_false():
    """GitHub omits `truncated` when it is false — absence is normal here."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "tree": [{"path": "a.tf", "type": "blob"}]
        })

    result = await _client(handler).get_tree("o", "r", "main")
    assert result.paths == ["a.tf"]
    assert result.truncated is False


@pytest.mark.asyncio
async def test_a_transport_failure_is_a_typed_error():
    """A timeout or refused connection must not reach the caller as a bare 500."""
    from app.services.github_client import GitHubUnavailable

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(GitHubUnavailable):
        await _client(handler).get_tree("o", "r", "main")


@pytest.mark.asyncio
async def test_a_json_body_that_is_not_an_object_is_typed():
    from app.services.github_client import GitHubUnexpectedResponse

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "dict"])

    with pytest.raises(GitHubUnexpectedResponse):
        await _client(handler).get_default_branch("o", "r")
