"""Request correlation, metrics and the unhandled-exception handler."""
import asyncio
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.observability import (
    REQUEST_ID_HEADER,
    _RequestIdFilter,
    configure_logging,
    current_request_id,
    request_id_var,
)


@pytest.mark.asyncio
async def test_response_carries_a_request_id(client: AsyncClient):
    response = await client.get("/health")
    assert response.headers.get(REQUEST_ID_HEADER)


@pytest.mark.asyncio
async def test_caller_supplied_request_id_is_preserved(client: AsyncClient):
    """A gateway or upstream service should be able to set the correlation id."""
    response = await client.get("/health", headers={REQUEST_ID_HEADER: "abc123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc123"


@pytest.mark.asyncio
async def test_each_request_gets_a_distinct_id(client: AsyncClient):
    first = await client.get("/health")
    second = await client.get("/health")
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_request_counters(client: AsyncClient):
    await client.get("/health")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "envmgr_http_requests_total" in response.text


@pytest.mark.asyncio
async def test_metrics_label_by_route_template_not_concrete_path(client: AsyncClient):
    """Ids in label values would make cardinality unbounded."""
    await client.get("/api/v1/releases/4242")
    body = (await client.get("/metrics")).text
    assert "/4242" not in body


@pytest.mark.asyncio
async def test_metric_path_label_is_the_full_route_not_the_router_relative_one(
    client: AsyncClient,
):
    """`route.path` is relative to the router prefix — `/me`, `/{release_id}`.

    Used raw, unrelated endpoints from different routers collapse into one label
    (several routers expose a bare `/{id}`), so the metric becomes meaningless.
    """
    await client.get("/api/v1/releases/4242")
    body = (await client.get("/metrics")).text
    assert 'path="/api/v1/releases/{release_id}"' in body


@pytest.mark.asyncio
async def test_unhandled_exception_returns_correlatable_500_without_internals(db_session):
    """A route that raises must not leak the message, but must be traceable."""
    from app.main import app
    from app.db.base import get_db

    @app.get("/_test_boom", include_in_schema=False)
    async def _boom():
        raise RuntimeError("secret internal detail")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/_test_boom")
    finally:
        app.dependency_overrides.clear()
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/_test_boom"
        ]

    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["request_id"]


def test_request_id_defaults_outside_a_request():
    """Logging from a background worker must not explode for want of a request."""
    assert current_request_id() == "-"


def test_configure_logging_is_idempotent():
    """`uvicorn --reload` re-imports the module; handlers must not stack."""
    configure_logging()
    before = len(logging.getLogger().handlers)
    configure_logging()
    assert len(logging.getLogger().handlers) == before == 1


@pytest.mark.asyncio
async def test_access_log_line_carries_the_request_id(client: AsyncClient):
    """The access line is the main thing anyone greps by request id.

    The stamping happens in a logging Filter, so it has to be observed at emit
    time — hence a real handler rather than caplog, whose handler carries no
    filters of ours. An earlier version reset the contextvar in a `finally` that
    ran before the log call, so every access line said "-"; a contextvar-only
    assertion missed it and a container run caught it.
    """
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _Capture(level=logging.INFO)
    handler.addFilter(_RequestIdFilter())
    access_logger = logging.getLogger("envmgr.access")
    access_logger.addHandler(handler)
    try:
        await client.get("/api/v1/auth/me", headers={REQUEST_ID_HEADER: "req-42"})
    finally:
        access_logger.removeHandler(handler)

    assert captured, "no access log line emitted"
    assert [r.request_id for r in captured] == ["req-42"], (
        "access line lost the request id, or was emitted more than once"
    )


def test_request_id_is_scoped_to_the_request(client: AsyncClient):
    """And released afterwards, so background work doesn't inherit a stale id."""
    assert current_request_id() == "-"


@pytest.mark.asyncio
async def test_supervisor_restarts_a_crashing_publisher(monkeypatch):
    """A dead outbox publisher is invisible; the supervisor must bring it back."""
    from app.workers import event_publisher

    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("boom")
        await asyncio.sleep(3600)  # third run stays up

    monkeypatch.setattr(event_publisher, "run_event_publisher", flaky)
    monkeypatch.setattr(event_publisher, "_SUPERVISOR_BACKOFF", [0])

    task = asyncio.create_task(event_publisher.supervise_event_publisher())
    for _ in range(200):
        if calls >= 3:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls >= 3, "supervisor did not restart the crashed publisher"


@pytest.mark.asyncio
async def test_supervisor_propagates_cancellation(monkeypatch):
    """Shutdown must stop the worker, not restart it forever."""
    from app.workers import event_publisher

    async def forever():
        await asyncio.sleep(3600)

    monkeypatch.setattr(event_publisher, "run_event_publisher", forever)
    task = asyncio.create_task(event_publisher.supervise_event_publisher())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
