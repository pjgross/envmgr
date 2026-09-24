"""Real calls against the local AI test server. Opt-in: AI_INTEGRATION=1.

    cd backend && AI_INTEGRATION=1 uv run pytest tests/ai -q -rs

Assertions are on BEHAVIOUR — which tool was called with which arguments,
which ids and names appear in the answer, that no reasoning leaks — never on
wording. Model output is non-deterministic, so the flow runs several times
and a pass RATE is required; a single green run proves little and a single
red run proves nothing.

Skips (with a reason) rather than fails when the server is unreachable, so
CI — which has no route to the LAN — is unaffected. See CLAUDE.md,
"Local AI test server".
"""
from __future__ import annotations

import logging
import re

import pytest

from app.core.config import settings
from app.db.models.environment import EnvironmentStatus
from app.services.ai.client import (
    ModelRole,
    build_client,
    default_reasoning_effort,
    normalise_hyphens,
)
from app.services.ai.copilot_service import run_agent
from app.services.ai.tools import ToolContext
from tests.ai.conftest import integration_skip_reason
from tests.factories import ensure_environment

_reason = integration_skip_reason()
pytestmark = pytest.mark.skipif(_reason is not None, reason=_reason or "")

logger = logging.getLogger(__name__)

RUNS = 5
REQUIRED_PASSES = 4

# A leak is reasoning prose or a think tag inside the answer. The gateway now
# guarantees reasoning stays in reasoning_content (ai-status --test pins it),
# so this is a regression guard on OUR side of the seam: `<think>` is the
# qwen3 marker; "We are given"/"The user wants" is what a leak looked like on
# the old copilot-fast before 2026-09-23.
_LEAK = re.compile(r"<think>|\bWe are given\b|\bThe user (wants|asks|requests)\b", re.I)


async def _seed(db, tenant_id):
    active_1 = await ensure_environment(db, tenant_id, slot=1)
    active_2 = await ensure_environment(db, tenant_id, slot=2)
    inactive = await ensure_environment(db, tenant_id, slot=3)
    inactive.status = EnvironmentStatus.INACTIVE
    await db.flush()
    return [active_1, active_2], inactive


def _pass_rate(outcomes: list[tuple[bool, str]]) -> None:
    passes = sum(1 for ok, _ in outcomes if ok)
    report = "\n".join(f"  run {i + 1}: {'PASS' if ok else 'FAIL'} — {why}" for i, (ok, why) in enumerate(outcomes))
    logger.info("pass rate %d/%d\n%s", passes, len(outcomes), report)
    assert passes >= REQUIRED_PASSES, f"{passes}/{len(outcomes)} passed, need {REQUIRED_PASSES}\n{report}"


async def test_copilot_agent_lists_the_active_environments_through_the_tool(
    db_session, test_tenant
):
    """One real copilot flow end to end: question → tool call → answer.

    Passes a run when the model (a) called list_environments, (b) named every
    active environment in its answer, (c) did not name the inactive one, and
    (d) leaked no reasoning into the answer.
    """
    client = build_client(settings)
    assert client is not None
    active, inactive = await _seed(db_session, test_tenant.id)
    ctx = ToolContext(db=db_session, tenant_id=test_tenant.id)

    outcomes: list[tuple[bool, str]] = []
    for _ in range(RUNS):
        result = await run_agent(
            client, ctx,
            "Which environments are currently active? Give their names and ids.",
            model=settings.AI_AGENT_MODEL,
            reasoning_effort=default_reasoning_effort(ModelRole.AGENT),
            max_tokens=600,
        )
        answer = normalise_hyphens(result.answer)
        called = [t.name for t in result.turns]
        problems = []
        if "list_environments" not in called:
            problems.append(f"tool not called (turns={called})")
        for env in active:
            if env.name not in answer:
                problems.append(f"missing active {env.name}")
        if inactive.name in answer:
            problems.append(f"named inactive {inactive.name}")
        if _LEAK.search(answer):
            problems.append("reasoning leaked into answer")
        if not answer.strip():
            problems.append("empty answer")
        outcomes.append((not problems, "; ".join(problems) or f"{len(result.turns)} tool turn(s), {result.steps} step(s)"))
        logger.info("answer: %r", answer)

    _pass_rate(outcomes)


async def test_copilot_agent_names_the_environment_ids_it_was_given(db_session, test_tenant):
    """The ids in the answer must be ids the tool returned — never invented."""
    client = build_client(settings)
    assert client is not None
    active, _ = await _seed(db_session, test_tenant.id)
    ctx = ToolContext(db=db_session, tenant_id=test_tenant.id)
    real_ids = {str(e.id) for e in active}

    outcomes: list[tuple[bool, str]] = []
    for _ in range(RUNS):
        result = await run_agent(
            client, ctx,
            f"What is the numeric id of the environment named {active[0].name}?",
            model=settings.AI_AGENT_MODEL,
            reasoning_effort=default_reasoning_effort(ModelRole.AGENT),
            max_tokens=300,
        )
        answer = normalise_hyphens(result.answer)
        numbers = set(re.findall(r"\d+", answer))
        problems = []
        if str(active[0].id) not in numbers:
            problems.append(f"id {active[0].id} absent from {answer!r}")
        invented = numbers - real_ids - {"1", "2", "3"}  # slot digits in names
        if invented:
            problems.append(f"numbers not from the tool: {sorted(invented)}")
        outcomes.append((not problems, "; ".join(problems) or "ok"))

    _pass_rate(outcomes)


async def test_embedding_width_matches_the_configured_dimensions():
    client = build_client(settings)
    assert client is not None
    vectors = await client.embed(model=settings.AI_EMBED_MODEL, texts=["booking", "release"])
    assert len(vectors) == 2
    assert all(len(v) == settings.AI_EMBED_DIMENSIONS for v in vectors)
    assert vectors[0] != vectors[1]
