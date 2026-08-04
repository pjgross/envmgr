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
async def test_a_path_claimed_by_several_detectors_goes_to_all_of_them(
    client, auth_headers, connected_system, monkeypatch
):
    """"First match wins" would make behaviour depend on registry order.

    Two fake detectors both claim the same path here; both must see it,
    regardless of which one the registry happens to list first.
    """
    from app.services.scanning import scanner
    from app.services.scanning.registry import Detector
    from app.services.scanning.declared import DeclaredState
    from app.db.models.system import SubSystemSource

    async def _parse(ctx):
        return DeclaredState()

    first = Detector(
        name="first", matches=lambda p: p.endswith(".yml"), parse=_parse,
        subsystem_source=SubSystemSource.MANUAL,
    )
    second = Detector(
        name="second", matches=lambda p: p.endswith(".yml"), parse=_parse,
        subsystem_source=SubSystemSource.MANUAL,
    )
    monkeypatch.setattr(scanner, "get_detectors", lambda: [first, second])
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    by_name = {d["detector"]: d for d in resp.json()["detectors"]}
    assert by_name["first"]["paths"] == ["docker-compose.yml"]
    assert by_name["second"]["paths"] == ["docker-compose.yml"]


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
    from app.services.scanning.registry import Detector
    from app.services.scanning.detectors import DOCKER_COMPOSE
    from app.db.models.system import SubSystemSource

    async def _boom(ctx):
        raise RuntimeError("detector exploded")

    broken = Detector(
        name="broken", matches=lambda p: p.endswith(".yml"), parse=_boom,
        subsystem_source=SubSystemSource.MANUAL,
    )
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

    Parsing is pure now, so a detector cannot fail its own write from inside
    `parse` any more — the write happens in `reconcile.apply`. What a broken
    detector *can* still do is declare a value `apply` cannot persist: `name`
    is NOT NULL on `subsystem`, so a declaration with `name=None` fails the
    flush inside `apply`'s own SAVEPOINT with a real `IntegrityError`.
    """
    from app.services.scanning import scanner
    from app.services.scanning.registry import Detector
    from app.services.scanning.declared import DeclaredState, DeclaredSubsystem
    from app.services.scanning.detectors import DOCKER_COMPOSE
    from app.db.models.system import SubSystemSource

    async def _bad_parse(ctx):
        return DeclaredState(subsystems=[DeclaredSubsystem(
            name=None, component_type="service",
            technology=None, source_path=ctx.path,
        )])

    broken = Detector(
        name="bad_writer", matches=lambda p: p.endswith(".yml"), parse=_bad_parse,
        subsystem_source=SubSystemSource.MANUAL,
    )
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
    from app.services.scanning.registry import Detector
    from app.services.scanning.declared import DeclaredState
    from app.db.models.system import SubSystemSource

    key = (connected_system.tenant_id, connected_system.id)
    assert key not in scanner._in_flight, "test isolation bug: marker was already set"
    seen_armed = []

    async def _observe(ctx):
        seen_armed.append(key in scanner._in_flight)
        return DeclaredState()

    watcher = Detector(
        name="watcher", matches=lambda p: p.endswith(".yml"), parse=_observe,
        subsystem_source=SubSystemSource.MANUAL,
    )
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
async def test_the_in_flight_marker_is_still_held_while_apply_runs(
    client, auth_headers, connected_system, monkeypatch
):
    """`_with_repository` used to release `_in_flight` in its own `finally`
    as soon as `_walk` returned — BEFORE `scan_repository`'s apply loop ran.
    A second click that arrives after the network-bound walk finishes but
    before the first request's writes commit would then pass the in-flight
    check and run `reconcile.apply` concurrently with it: two check-then-act
    writes over `catalogue()`, which has no unique constraint on
    (name, system_id, tenant_id) to catch the collision — the loser
    silently disappears from both `apply()` and `diff()`.

    Observed from inside `reconcile.apply` itself — the only vantage point
    that actually proves the marker is held for the *write*, not merely for
    the walk. (test_a_second_concurrent_scan_is_rejected and
    test_the_scan_arms_the_in_flight_marker_itself both stop at the walk;
    neither would catch the marker being released early.)
    """
    from app.services.scanning import scanner, reconcile

    key = (connected_system.tenant_id, connected_system.id)
    seen_armed = []
    original_apply = reconcile.apply

    async def _observing_apply(db, **kwargs):
        seen_armed.append(key in scanner._in_flight)
        return await original_apply(db, **kwargs)

    monkeypatch.setattr(reconcile, "apply", _observing_apply)
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.post(
        f"/api/v1/systems/{connected_system.id}/github/scan", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert seen_armed, "reconcile.apply was never invoked — test setup bug"
    assert all(seen_armed), (
        "the in-flight marker must still be held while reconcile.apply runs, "
        "not released as soon as the walk itself returns"
    )


@pytest.mark.asyncio
async def test_a_401_from_a_blob_fetch_partway_through_the_walk_still_clears_the_token(
    realistic_client, db_engine, monkeypatch
):
    """GitHubAuthError and GitHubRateLimited are deliberately NOT caught by
    the walk's per-file except tuple: a 401 is dead for every remaining
    file and must reach the endpoint's token cleanup, not be swallowed as a
    per-file detector error and returned as a 200 with the dead token still
    in place.

    Unlike test_a_401_from_github_clears_the_stored_token — which 401s on
    every call, including get_default_branch, and so never actually reaches
    the fetch loop — this returns 200 for the branch and tree calls and
    only 401s on the blob fetch, exercising the fetch loop's exception
    handling specifically.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.core.security import get_password_hash
    from app.db.models.user import Tenant, User
    from app.db.models.system import System
    from app.services.scanning import scanner
    from app.api.v1 import systems as systems_api

    Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(systems_api, "AsyncSessionLocal", Session)

    async with Session() as setup:
        tenant = Tenant(name="Revoke Org 2", slug="revoke-org-2")
        setup.add(tenant)
        await setup.flush()
        user = User(
            tenant_id=tenant.id,
            username="revokeadmin2",
            email="revoke2@test.com",
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
        "username": "revokeadmin2", "password": "password123", "tenant_slug": "revoke-org-2",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/contents/" in url:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if "/git/trees/" in url:
            return httpx.Response(200, json={
                "tree": [{"path": "docker-compose.yml", "type": "blob"}],
                "truncated": False,
            })
        return httpx.Response(200, json={"default_branch": "main"})

    monkeypatch.setattr(scanner, "_transport", lambda: httpx.MockTransport(handler))

    resp = await realistic_client.post(
        f"/api/v1/systems/{system_id}/github/scan", headers=headers
    )
    assert resp.status_code == 401, resp.text

    async with Session() as verify:
        assert await tenant_secret_service.get_secret(
            verify, tenant_id, "github_oauth_token") is None


@pytest.mark.asyncio
async def test_a_close_failure_does_not_replace_a_propagating_auth_error(
    realistic_client, db_engine, monkeypatch
):
    """If `aclose()` raises while a GitHubAuthError is propagating and that
    close failure is allowed to replace it, the endpoint's
    `except GitHubAuthError` never runs: the caller gets a 500 instead of a
    401 and the revoked token is never cleared — the UI keeps claiming
    'connected' forever.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.core.security import get_password_hash
    from app.db.models.user import Tenant, User
    from app.db.models.system import System
    from app.services.scanning import scanner
    from app.services.github_client import GitHubClient
    from app.api.v1 import systems as systems_api

    Session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(systems_api, "AsyncSessionLocal", Session)

    async def _boom_aclose(self):
        raise RuntimeError("connection pool close failed")

    monkeypatch.setattr(GitHubClient, "aclose", _boom_aclose)

    async with Session() as setup:
        tenant = Tenant(name="Revoke Org 3", slug="revoke-org-3")
        setup.add(tenant)
        await setup.flush()
        user = User(
            tenant_id=tenant.id,
            username="revokeadmin3",
            email="revoke3@test.com",
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
        "username": "revokeadmin3", "password": "password123", "tenant_slug": "revoke-org-3",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    monkeypatch.setattr(scanner, "_transport", lambda: httpx.MockTransport(handler))

    resp = await realistic_client.post(
        f"/api/v1/systems/{system_id}/github/scan", headers=headers
    )
    assert resp.status_code == 401, resp.text

    async with Session() as verify:
        assert await tenant_secret_service.get_secret(
            verify, tenant_id, "github_oauth_token") is None


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
