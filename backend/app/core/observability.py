"""Logging, request correlation and Prometheus metrics.

Before this module the backend had almost no operational visibility: seven
logging calls across 27k lines, no request ids, no handler for unexpected
exceptions (so tracebacks went to uvicorn's stderr and the client got a bare
500), and no /metrics — despite Prometheus and Grafana being part of the
production architecture.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

REQUEST_ID_HEADER = "X-Request-ID"

# Set per request so every log line emitted while handling it can be correlated,
# without threading an id through every function signature.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    return request_id_var.get()


# ── logging ──────────────────────────────────────────────────────────────────


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Install a single stdout handler on the root logger.

    JSON when DEBUG is off (production, where something is collecting stdout),
    human-readable when on. Idempotent — repeated calls replace the handler
    rather than stacking duplicates, which matters under `uvicorn --reload`.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if settings.DEBUG:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s — %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    else:
        handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    # uvicorn installs its own handlers; let them propagate to ours instead so
    # its lines share one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # uvicorn.access logs every request too, which would double every line —
    # and it cannot carry the request id or the handler duration. Ours wins.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # This level is the ONLY switch for SQL logging. The engine is built with
    # echo=False on purpose (see app/db/base.py): echo would attach a second
    # handler to the `sqlalchemy.engine.Engine` instance logger, and since that
    # logger still propagates here, every statement would be logged twice — once
    # in SQLAlchemy's format and once in ours. Setting a level cannot undo that;
    # only not attaching the handler can.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )

    # nats-py logs a full traceback at ERROR for *every* reconnect attempt. With
    # NATS down that is a stack trace every two seconds, which buries real
    # errors; the event publisher reports connectivity itself, with backoff.
    logging.getLogger("nats").setLevel(logging.CRITICAL)

    # Chatty at DEBUG and never interesting (passlib logs each handler it loads).
    for noisy in ("passlib", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.INFO)


# ── metrics ──────────────────────────────────────────────────────────────────

REQUESTS = Counter(
    "envmgr_http_requests_total",
    "HTTP requests handled.",
    ["method", "path", "status"],
)
REQUEST_DURATION = Histogram(
    "envmgr_http_request_duration_seconds",
    "HTTP request duration.",
    ["method", "path"],
)
UNHANDLED_EXCEPTIONS = Counter(
    "envmgr_unhandled_exceptions_total",
    "Requests that ended in an unhandled exception.",
    ["path"],
)


def _route_template(request: Request) -> str:
    """The route pattern, not the concrete path.

    `/api/v1/releases/{release_id}` rather than `/api/v1/releases/417` — one
    label value per endpoint instead of one per id, which would otherwise make
    cardinality unbounded.

    Built from the request path with parameter values substituted back out,
    rather than from `route.path`: that attribute is relative to the router's
    prefix (`/me`, `/{release_id}`), so unrelated endpoints from different
    routers would share a label.
    """
    if request.scope.get("route") is None:
        return "unmatched"

    template = request.url.path
    params = request.scope.get("path_params") or {}
    # Longest first, so an id of "1" can't clobber part of a longer value.
    for name, value in sorted(params.items(), key=lambda kv: -len(str(kv[1]))):
        template = template.replace(str(value), "{" + name + "}", 1)
    return template


# ── middleware ───────────────────────────────────────────────────────────────


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, log the request, and record metrics."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        logger = logging.getLogger("envmgr.access")
        started = time.perf_counter()

        # One try/finally around everything: the contextvar must still be set
        # while the access line is emitted. Resetting it in a finally around
        # call_next alone released it too early and every access line logged "-".
        try:
            try:
                response = await call_next(request)
            except Exception:
                elapsed = time.perf_counter() - started
                path = _route_template(request)
                UNHANDLED_EXCEPTIONS.labels(path=path).inc()
                REQUESTS.labels(method=request.method, path=path, status="500").inc()
                REQUEST_DURATION.labels(method=request.method, path=path).observe(elapsed)
                # Logged here rather than only in the exception handler so the
                # traceback is captured even if the handler itself fails.
                logger.exception(
                    "%s %s -> unhandled exception in %.1f ms",
                    request.method,
                    request.url.path,
                    elapsed * 1000,
                )
                raise

            elapsed = time.perf_counter() - started
            path = _route_template(request)
            REQUESTS.labels(
                method=request.method, path=path, status=str(response.status_code)
            ).inc()
            REQUEST_DURATION.labels(method=request.method, path=path).observe(elapsed)
            response.headers[REQUEST_ID_HEADER] = request_id

            # Health checks run every 30s per container; logging them buries
            # everything else.
            if request.url.path not in ("/health", "/metrics"):
                logger.info(
                    "%s %s -> %d in %.1f ms",
                    request.method,
                    request.url.path,
                    response.status_code,
                    elapsed * 1000,
                )
            return response
        finally:
            request_id_var.reset(token)


# ── wiring ───────────────────────────────────────────────────────────────────


def install_observability(app: FastAPI) -> None:
    """Add the middleware, the /metrics endpoint and a catch-all error handler."""
    app.add_middleware(RequestContextMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return PlainTextResponse(
            generate_latest(), media_type=CONTENT_TYPE_LATEST
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Return a correlatable 500 instead of leaking internals.

        The detail deliberately carries only the request id: the client gets
        something to quote in a bug report, and the traceback stays in the logs
        where the middleware already recorded it under the same id.
        """
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "request_id": current_request_id(),
            },
            headers={REQUEST_ID_HEADER: current_request_id()},
        )
