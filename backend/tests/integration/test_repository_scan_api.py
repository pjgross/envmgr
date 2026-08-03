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
    by_name = {d["detector"]: d for d in body["detectors"]}
    assert "docker_compose" in by_name
    # Every registered detector is pre-seeded into the report regardless of
    # whether it matched anything, so "docker_compose in names" alone would
    # pass against a repo with no compose file at all. The scanned file is a
    # real compose file with one service — assert it was actually parsed.
    assert by_name["docker_compose"]["subsystems_created"] > 0


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
async def test_a_starved_detector_reports_paths_unread(
    client, auth_headers, connected_system, monkeypatch
):
    """300 .tf files ahead of docker-compose.yml in tree order would otherwise
    mean Compose is never fetched, yet its report is all zeros with no error —
    indistinguishable from "this repo has no compose file". The file cap must
    not just report globally that it stopped early; it must say, per
    detector, how many of ITS matches were never read.
    """
    from app.services.scanning import scanner
    monkeypatch.setattr(scanner.settings, "MAX_SCAN_FILES", 1)
    monkeypatch.setattr(
        scanner, "_transport",
        lambda: _github(["docker-compose.yml", "a.tf", "b.tf"]),
    )

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stopped_early"] is True
    by_name = {d["detector"]: d for d in body["detectors"]}
    # docker-compose.yml was first in tree order, so it made it under the cap.
    assert by_name["docker_compose"]["paths_unread"] == 0
    # a.tf and b.tf were dropped by the cap before the fetch loop reached them.
    assert by_name["terraform_hcl"]["paths_unread"] == 2


@pytest.mark.asyncio
async def test_a_failed_blob_fetch_is_recorded_and_does_not_abort_the_scan(
    client, auth_headers, connected_system, monkeypatch
):
    """A transient 5xx on ONE file must not discard every other detector's
    already-written results, and must not misreport the failure as 'repository
    not found, or the token cannot see it' — that message is for the whole
    repo, not a single blob a moment later."""
    from app.services.scanning import scanner

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/git/trees/" in url:
            return httpx.Response(200, json={
                "tree": [
                    {"path": "docker-compose.yml", "type": "blob"},
                    {"path": "broken.tf", "type": "blob"},
                ],
                "truncated": False,
            })
        if "/contents/broken.tf" in url:
            return httpx.Response(500, json={"message": "boom"})
        if "/contents/" in url:
            return httpx.Response(200, json={
                "content": base64.b64encode(COMPOSE).decode(), "encoding": "base64",
            })
        return httpx.Response(200, json={"default_branch": "main"})

    monkeypatch.setattr(scanner, "_transport", lambda: httpx.MockTransport(handler))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    by_name = {d["detector"]: d for d in resp.json()["detectors"]}
    assert any("broken.tf" in e for e in by_name["terraform_hcl"]["errors"])
    assert by_name["docker_compose"]["subsystems_created"] > 0, (
        "the healthy file's detector results must survive the other file's failed fetch"
    )


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
    realistic_client, db_engine, monkeypatch
):
    """Otherwise the UI keeps claiming 'connected' with a dead token.

    Must use `realistic_client`, not the shared `client` fixture: `client`
    shares one never-rolled-back session with the test body, so a deletion
    made on the way to the 401 stays visible in-process even if get_db's real
    rollback would have discarded it — which is exactly the bug this guards
    against. See app/db/base.py's get_db and the CRITICAL finding this test
    was written for.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.core.security import get_password_hash
    from app.db.models.user import Tenant, User
    from app.db.models.system import System
    from app.services.scanning import scanner
    from app.api.v1 import systems as systems_api

    Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # The endpoint's cleanup session uses the module-level AsyncSessionLocal —
    # bound to settings.DATABASE_URL, the real dev/prod database — so it has
    # to be repointed at this test's engine or the deletion would (attempt to)
    # land in a database this test never touches. This mirrors how
    # tests/unit/test_event_publisher.py handles the same module-level import.
    monkeypatch.setattr(systems_api, "AsyncSessionLocal", Session)

    async with Session() as setup:
        tenant = Tenant(name="Revoke Org", slug="revoke-org")
        setup.add(tenant)
        await setup.flush()
        user = User(
            tenant_id=tenant.id,
            username="revokeadmin",
            email="revoke@test.com",
            password_hash=get_password_hash("password123"),
            role="Admin",
            is_active=True,
        )
        setup.add(user)
        system = System(
            tenant_id=tenant.id, name="Payments",
            github_repository_url="https://github.com/acme/payments",
        )
        setup.add(system)
        await setup.flush()
        await tenant_secret_service.put_secret(
            setup, tenant.id, "github_oauth_token", "gho_abc", created_by=user.id,
        )
        await setup.commit()
        tenant_id, system_id = tenant.id, system.id

    login = await realistic_client.post("/api/v1/auth/login", json={
        "username": "revokeadmin", "password": "password123", "tenant_slug": "revoke-org",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    monkeypatch.setattr(scanner, "_transport", lambda: httpx.MockTransport(handler))

    resp = await realistic_client.post(
        f"/api/v1/systems/{system_id}/github/scan", headers=headers
    )
    assert resp.status_code == 401

    # Fresh session, opened after the request completed: this is what proves
    # the deletion survived get_db's rollback-on-exception rather than having
    # only ever lived in a session the test happened to share.
    async with Session() as verify:
        assert await tenant_secret_service.get_secret(
            verify, tenant_id, "github_oauth_token") is None


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
async def test_the_scan_arms_the_in_flight_marker_itself(
    client, auth_headers, connected_system, monkeypatch
):
    """test_a_second_concurrent_scan_is_rejected seeds `_in_flight` by hand
    before the request, so it would stay green even if `scan_repository`
    itself never called `_in_flight.add(key)` — it only proves the check is
    there, not the arming. Patch a detector's parse to observe the marker
    from inside a real, unseeded scan.
    """
    from app.services.scanning import scanner
    from app.services.scanning.registry import Detector, DetectorResult

    key = (connected_system.tenant_id, connected_system.id)
    assert key not in scanner._in_flight, "test isolation bug: marker was already set"
    seen_armed = []

    async def _observe(ctx):
        seen_armed.append(key in scanner._in_flight)
        return DetectorResult()

    watcher = Detector(name="watcher", matches=lambda p: p.endswith(".yml"), parse=_observe)
    monkeypatch.setattr(scanner, "get_detectors", lambda: [watcher])
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert seen_armed == [True], "the marker must be set before the walk runs, not after"
    assert key not in scanner._in_flight, "and released once the scan completes"


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
