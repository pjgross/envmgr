"""The drift report endpoint. No network: a MockTransport stands in for GitHub."""
import base64

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import secrets as secrets_module
from app.db.models.system import SubSystem, SubSystemSource, System
from app.services import tenant_secret_service

COMPOSE = b"services:\n  api:\n    image: nginx\n  db:\n    image: postgres\n"


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


def _compose(body):
    return next(d for d in body["detectors"] if d["detector"] == "docker_compose")


@pytest.mark.asyncio
async def test_an_empty_catalogue_reports_everything_the_code_declares(
    client, auth_headers, connected_system, monkeypatch
):
    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    compose = _compose(resp.json())
    names = {s["name"] for s in compose["subsystems"]["missing_in_catalogue"]}
    assert names == {"api", "db"}
    assert compose["subsystems"]["missing_in_code"] == []


@pytest.mark.asyncio
async def test_the_report_writes_nothing(
    client, auth_headers, connected_system, db_session, monkeypatch
):
    """It is a report. Writing would change the answer it just gave."""
    from sqlalchemy import func, select

    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    # Captured before expire_all() below: connected_system.id is an expired
    # ORM attribute after that call, and refreshing it needs an async
    # (greenlet) context that plain attribute access outside `await` doesn't
    # have — MissingGreenlet, not a meaningful assertion failure.
    system_id = connected_system.id

    await client.get(
        f"/api/v1/systems/{system_id}/github/drift", headers=auth_headers
    )

    # `client` shares this session with the request handler, so without
    # expiring, the identity map would just answer from before the request
    # and the test would pass without proving anything.
    db_session.expire_all()
    count = (await db_session.execute(
        select(func.count()).select_from(SubSystem)
        .where(SubSystem.system_id == system_id)
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_a_truncated_tree_leaves_absence_null_with_a_reason(
    client, auth_headers, connected_system, monkeypatch
):
    from app.services.scanning import scanner
    monkeypatch.setattr(
        scanner, "_transport", lambda: _github(["docker-compose.yml"], truncated=True)
    )

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    compose = _compose(resp.json())
    assert compose["absence_computed"] is False
    assert compose["subsystems"]["missing_in_code"] is None
    assert "partial" in compose["absence_reason"]
    # Positive findings survive a partial read.
    assert compose["subsystems"]["missing_in_catalogue"]


@pytest.mark.asyncio
async def test_a_deleted_service_is_reported_as_missing_from_the_code(
    client, auth_headers, connected_system, db_session, monkeypatch
):
    db_session.add(SubSystem(
        tenant_id=connected_system.tenant_id, system_id=connected_system.id,
        name="legacy", component_type="web_service",
        source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.commit()

    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    compose = _compose(resp.json())
    assert compose["subsystems"]["missing_in_code"] == ["legacy"]


@pytest.mark.asyncio
async def test_a_repository_with_no_iac_files_still_reports_deleted_rows(
    client, auth_headers, connected_system, db_session, monkeypatch
):
    """Looks alarming, is correct: a complete read of an empty declared set.
    A system whose compose file was deleted wholesale is exactly what this
    report exists to surface, so it must not be special-cased into silence."""
    db_session.add(SubSystem(
        tenant_id=connected_system.tenant_id, system_id=connected_system.id,
        name="api", component_type="web_service",
        source=SubSystemSource.DOCKER_COMPOSE,
    ))
    await db_session.commit()

    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["README.md"]))

    resp = await client.get(
        f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
    )

    compose = _compose(resp.json())
    assert compose["absence_computed"] is True
    assert compose["subsystems"]["missing_in_code"] == ["api"]


@pytest.mark.asyncio
async def test_a_drift_report_is_rejected_while_a_scan_is_in_flight(
    client, auth_headers, connected_system, monkeypatch
):
    """The drift report shares the scan's in-flight lock: comparing against a
    catalogue a concurrent scan is mutating would report differences that
    exist on neither side."""
    from app.services.scanning import scanner
    monkeypatch.setattr(scanner, "_transport", lambda: _github(["docker-compose.yml"]))

    scanner._in_flight.add((connected_system.tenant_id, connected_system.id))
    try:
        resp = await client.get(
            f"/api/v1/systems/{connected_system.id}/github/drift", headers=auth_headers
        )
        assert resp.status_code == 409
    finally:
        scanner._in_flight.discard((connected_system.tenant_id, connected_system.id))


@pytest.mark.asyncio
async def test_drift_requires_a_connected_github_account(
    client, auth_headers, db_session, test_tenant
):
    system = System(
        tenant_id=test_tenant.id, name="Unconnected",
        github_repository_url="https://github.com/acme/other",
    )
    db_session.add(system)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/systems/{system.id}/github/drift", headers=auth_headers
    )

    assert resp.status_code == 409
    assert "not connected" in resp.json()["detail"]
