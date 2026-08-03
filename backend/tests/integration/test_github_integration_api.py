"""The GitHub connect journey. No network: the device-flow HTTP calls are patched."""
import httpx
import pytest
from cryptography.fernet import Fernet

from app.core import secrets as secrets_module
from app.services import tenant_secret_service


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(
        secrets_module.settings, "SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    from app.services import github_oauth_service
    monkeypatch.setattr(
        github_oauth_service.settings, "GITHUB_OAUTH_CLIENT_ID", "Iv1.testclient"
    )


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_status_is_disconnected_before_anything_happens(client, auth_headers):
    resp = await client.get("/api/v1/integrations/github", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


@pytest.mark.asyncio
async def test_connect_returns_the_user_code_but_never_the_device_code(
    client, auth_headers, monkeypatch
):
    """The device_code redeems the token. If it reached the browser it would be
    a credential handed to the client."""
    from app.services import github_oauth_service

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "SECRET_DEVICE_CODE",
            "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(handler))

    resp = await client.post("/api/v1/integrations/github/connect", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_code"] == "WDJB-MJHT"
    assert body["verification_uri"] == "https://github.com/login/device"
    assert "SECRET_DEVICE_CODE" not in resp.text
    assert "device_code" not in body


@pytest.mark.asyncio
async def test_polling_stores_the_token_and_reports_connected(
    client, auth_headers, db_session, test_tenant, monkeypatch
):
    from app.services import github_oauth_service

    def device_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "SECRET_DEVICE_CODE", "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler))
    started = await client.post("/api/v1/integrations/github/connect", headers=auth_headers)
    handle = started.json()["handle"]

    def token_handler(request: httpx.Request) -> httpx.Response:
        if "oauth/access_token" in str(request.url):
            return httpx.Response(200, json={"access_token": "gho_realtoken",
                                             "token_type": "bearer"})
        return httpx.Response(200, json={"login": "octocat"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(token_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{handle}/poll", headers=auth_headers
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["status"] == "connected"

    stored = await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token"
    )
    assert stored == "gho_realtoken"

    status = await client.get("/api/v1/integrations/github", headers=auth_headers)
    assert status.json()["connected"] is True
    assert status.json()["github_login"] == "octocat"
    # The token itself is never returned by any endpoint.
    assert "gho_realtoken" not in status.text


@pytest.mark.asyncio
async def test_authorization_pending_is_reported_without_storing_anything(
    client, auth_headers, db_session, test_tenant, monkeypatch
):
    from app.services import github_oauth_service

    def device_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "SECRET_DEVICE_CODE", "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler))
    handle = (await client.post(
        "/api/v1/integrations/github/connect", headers=auth_headers)).json()["handle"]

    def pending_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "authorization_pending"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(pending_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{handle}/poll", headers=auth_headers
    )
    assert polled.json()["status"] == "pending"
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token") is None


@pytest.mark.asyncio
async def test_access_denied_is_reported(client, auth_headers, monkeypatch):
    from app.services import github_oauth_service

    def device_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "D", "user_code": "U",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler))
    handle = (await client.post(
        "/api/v1/integrations/github/connect", headers=auth_headers)).json()["handle"]

    def denied_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "access_denied"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(denied_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{handle}/poll", headers=auth_headers
    )
    assert polled.json()["status"] == "denied"


@pytest.mark.asyncio
async def test_wrong_handle_cannot_redeem_a_different_flows_device_code(
    client, auth_headers, db_session, test_tenant, monkeypatch
):
    """Only one device flow is pending per tenant at a time — start_device_flow
    upserts the pending secret, so starting a second flow replaces the first.
    A handle from that first (now-stale) flow must not be able to poll and
    redeem whatever flow is currently pending. Without the stored_handle check
    the lookup is keyed only by tenant_id, so any handle string — including
    one belonging to an earlier flow — would reach and redeem the live
    device_code.
    """
    from app.services import github_oauth_service

    def device_handler_1(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "DEVICE_ONE", "user_code": "U1",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler_1))
    stale_handle = (await client.post(
        "/api/v1/integrations/github/connect", headers=auth_headers)).json()["handle"]

    def device_handler_2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "DEVICE_TWO", "user_code": "U2",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler_2))
    current_handle = (await client.post(
        "/api/v1/integrations/github/connect", headers=auth_headers)).json()["handle"]
    assert stale_handle != current_handle

    def token_handler(request: httpx.Request) -> httpx.Response:
        if "oauth/access_token" in str(request.url):
            return httpx.Response(200, json={"access_token": "gho_stolen",
                                             "token_type": "bearer"})
        return httpx.Response(200, json={"login": "attacker"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(token_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{stale_handle}/poll", headers=auth_headers
    )
    assert polled.json()["status"] == "expired"
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token") is None


@pytest.mark.asyncio
async def test_disconnect_removes_the_token(
    client, auth_headers, db_session, test_tenant, test_user
):
    await tenant_secret_service.put_secret(
        db_session, test_tenant.id, "github_oauth_token", "gho_abc",
        created_by=test_user.id,
    )
    await tenant_secret_service.put_secret(
        db_session, test_tenant.id, "github_login", "octocat",
        created_by=test_user.id,
    )
    await tenant_secret_service.put_secret(
        db_session, test_tenant.id, "github_device_pending", "handle:devicecode",
        created_by=test_user.id,
    )
    await db_session.commit()

    resp = await client.delete("/api/v1/integrations/github", headers=auth_headers)
    assert resp.status_code == 200
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_oauth_token") is None
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_login") is None
    assert await tenant_secret_service.get_secret(
        db_session, test_tenant.id, "github_device_pending") is None


@pytest.mark.asyncio
async def test_an_unmodelled_device_flow_error_is_502_not_500(
    client, auth_headers, monkeypatch
):
    """device_flow_disabled, incorrect_client_credentials, unsupported_grant_type
    and friends are real GitHub error strings this flow does not act on. Falling
    through to `payload["access_token"]` for one of these is a bare KeyError —
    an unhandled 500 that tells the user nothing, instead of the 502 that
    correctly blames GitHub rather than the request.
    """
    from app.services import github_oauth_service

    def device_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "device_code": "D", "user_code": "U",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900, "interval": 5,
        })

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(device_handler))
    handle = (await client.post(
        "/api/v1/integrations/github/connect", headers=auth_headers)).json()["handle"]

    def unmodelled_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "device_flow_disabled"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(unmodelled_handler))
    polled = await client.post(
        f"/api/v1/integrations/github/connect/{handle}/poll", headers=auth_headers
    )
    assert polled.status_code == 502, polled.text


@pytest.mark.asyncio
async def test_a_malformed_device_code_response_is_502_not_500(
    client, auth_headers, monkeypatch
):
    """A 200 whose body has none of the fields this flow requires — the other
    half of the same discipline, on the /connect leg rather than /poll."""
    from app.services import github_oauth_service

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    monkeypatch.setattr(github_oauth_service, "_transport", lambda: _transport(malformed_handler))
    resp = await client.post("/api/v1/integrations/github/connect", headers=auth_headers)
    assert resp.status_code == 502, resp.text


@pytest.mark.asyncio
async def test_connect_without_a_client_id_is_503(client, auth_headers, monkeypatch):
    """A clear answer beats failing obscurely inside an HTTP call."""
    from app.services import github_oauth_service
    monkeypatch.setattr(github_oauth_service.settings, "GITHUB_OAUTH_CLIENT_ID", "")

    resp = await client.post("/api/v1/integrations/github/connect", headers=auth_headers)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_a_non_admin_cannot_connect(client, db_session, test_tenant):
    """Connecting binds a credential for the whole tenant — admin only.

    The suite has no non-admin auth fixture, so a Member-role user is created
    and logged in here rather than skipping the check.
    """
    from app.core.security import get_password_hash
    from app.db.models.user import User

    member = User(
        tenant_id=test_tenant.id,
        username="testmember",
        email="member@test.com",
        password_hash=get_password_hash("password123"),
        role="Viewer",
        is_active=True,
    )
    db_session.add(member)
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={
        "username": member.username,
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert login.status_code == 200, login.text
    member_auth_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post("/api/v1/integrations/github/connect", headers=member_auth_headers)
    assert resp.status_code == 403
