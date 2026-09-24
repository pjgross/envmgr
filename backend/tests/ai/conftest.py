"""Gate for the opt-in integration tests in this directory.

`AI_INTEGRATION=1` opts in; without it, or when `GET $AI_BASE_URL/models` is
not reachable, the integration module is skipped with a reason that says
which. CI has no route to the LAN, so there it always skips — and a run that
skipped everything has proved nothing, which is why the CLAUDE.md workflow
says to read the `-rs` summary.
"""
import os
from typing import Optional

import httpx

from app.core.config import settings


def integration_skip_reason() -> Optional[str]:
    if os.environ.get("AI_INTEGRATION") != "1":
        return "set AI_INTEGRATION=1 to run against the local AI test server"
    if not settings.AI_BASE_URL:
        return "AI_BASE_URL is not set (backend/.env) — nothing to run against"
    try:
        response = httpx.get(f"{settings.AI_BASE_URL.rstrip('/')}/models", timeout=5.0)
        response.raise_for_status()
        names = {m["id"] for m in response.json().get("data", [])}
    except Exception as exc:  # unreachable, refused, not JSON — all "skip"
        return f"AI server not reachable at {settings.AI_BASE_URL}: {exc!r}"
    wanted = {settings.AI_AGENT_MODEL, settings.AI_EMBED_MODEL}
    missing = wanted - names
    if missing:
        return f"AI server lacks configured aliases {sorted(missing)}; has {sorted(names)}"
    return None
