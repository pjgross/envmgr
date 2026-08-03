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
async def test_a_detector_whose_database_write_fails_does_not_poison_the_others(
    client, auth_headers, connected_system, monkeypatch
):
    """The realistic failure: a constraint violation, not a bare RuntimeError.

    A failed flush marks the session for rollback; without a savepoint per
    detector the next detector's write — or the request's own commit — raises
    PendingRollbackError and every successful detector's results are lost.
    """
    from app.services.scanning import scanner
    from app.services.scanning.registry import Detector, DetectorResult
    from app.services.scanning.detectors import DOCKER_COMPOSE
    from app.db.models.system import SubSystem

    async def _bad_write(ctx):
        # tenant_id is NOT NULL — this flush fails inside the detector.
        ctx.db.add(SubSystem(tenant_id=None, system_id=ctx.system_id, name="bad"))
        await ctx.db.flush()
        return DetectorResult(subsystems_created=1)

    broken = Detector(name="bad_writer", matches=lambda p: p.endswith(".yml"),
                      parse=_bad_write)
    monkeypatch.setattr(scanner, "get_detectors", lambda: [broken, DOCKER_COMPOSE])
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    by_name = {d["detector"]: d for d in resp.json()["detectors"]}
    assert by_name["bad_writer"]["errors"], "the failing detector must be recorded"
    assert not by_name["docker_compose"]["errors"], (
        "the healthy detector's results must survive the other's failed write"
    )


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


@pytest.mark.asyncio
async def test_aclose_is_called_even_when_the_scan_raises(
    client, auth_headers, connected_system, monkeypatch
):
    """A scan that raises must still release the GitHubClient's connection pool,
    or every failed scan leaks one. A 5xx from GitHub is also the case that
    decides the 'GitHub misbehaved' status code: GitHubUnavailable -> 502."""
    from app.services.scanning import scanner
    from app.services.github_client import GitHubClient

    closed = []
    original_aclose = GitHubClient.aclose

    async def _tracking_aclose(self):
        closed.append(True)
        await original_aclose(self)

    monkeypatch.setattr(GitHubClient, "aclose", _tracking_aclose)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    monkeypatch.setattr(scanner, "_transport", lambda: httpx.MockTransport(handler))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 502
    assert closed == [True]
