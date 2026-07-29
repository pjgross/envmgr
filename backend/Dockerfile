# syntax=docker/dockerfile:1

# ── deps ─────────────────────────────────────────────────────────────────────
# Dependencies resolve in their own layer so application edits don't reinstall
# the world. uv.lock is respected exactly (--frozen), matching CI.
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# curl is used by the container healthcheck below.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
COPY alembic.ini ./
COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 envmgr && chown -R envmgr:envmgr /app
USER envmgr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
