"""The agent loop: ask, dispatch tool calls, feed results back, answer.

Read-only today (the registry holds one GET-shaped tool). The loop itself is
what a write-capable agent would also run on, which is why the step limit and
the explicit-error feedback are here and not in a caller.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.ai.client import AIClient, ToolCall
from app.services.ai.tools import REGISTRY, ToolContext, ToolSpec, error, openai_tool_definitions

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are the EnvManager copilot, an assistant for a test-environment "
    "register. Answer from the tools provided; do not invent environments, ids "
    "or statuses. Ids are integers. When a tool returns an error, correct the "
    "call and try again. Answer concisely."
)


class AgentStepLimit(Exception):
    """The model kept calling tools past `max_steps`."""


@dataclass(frozen=True)
class AgentTurn:
    name: str
    arguments: Optional[dict[str, Any]]
    result: str  # exactly what was fed back to the model


@dataclass(frozen=True)
class AgentResult:
    answer: str
    reasoning: Optional[str]
    turns: list[AgentTurn] = field(default_factory=list)
    steps: int = 0


async def _dispatch(ctx: ToolContext, call: ToolCall, tools: dict[str, ToolSpec]) -> str:
    spec = tools.get(call.name)
    if spec is None:
        return error(
            f"Unknown tool '{call.name}'. Available tools: {', '.join(sorted(tools))}."
        )
    if call.arguments is None:
        return error(
            f"The arguments for {call.name} were not valid JSON: {call.raw_arguments!r}. "
            "Send a JSON object."
        )
    try:
        return await spec.handler(ctx, call.arguments)
    except Exception:  # a handler bug must not take the whole turn down
        logger.exception("tool %s failed", call.name)
        return error(f"{call.name} failed internally; try a different query.")


async def run_agent(
    client: AIClient,
    ctx: ToolContext,
    question: str,
    *,
    model: str,
    tools: Optional[list[ToolSpec]] = None,
    reasoning_effort: Optional[str] = None,
    max_steps: int = 6,
    max_tokens: Optional[int] = None,
) -> AgentResult:
    specs = tools if tools is not None else list(REGISTRY.values())
    by_name = {s.name: s for s in specs}
    definitions = openai_tool_definitions(specs)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    turns: list[AgentTurn] = []
    for step in range(1, max_steps + 1):
        result = await client.chat(
            model=model, messages=messages, tools=definitions,
            reasoning_effort=reasoning_effort, max_tokens=max_tokens,
        )
        if not result.tool_calls:
            return AgentResult(
                answer=result.content, reasoning=result.reasoning, turns=turns, steps=step
            )
        messages.append({
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(c.arguments) if c.arguments is not None else c.raw_arguments,
                    },
                }
                for c in result.tool_calls
            ],
        })
        for call in result.tool_calls:
            fed_back = await _dispatch(ctx, call, by_name)
            turns.append(AgentTurn(name=call.name, arguments=call.arguments, result=fed_back))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": fed_back})
    raise AgentStepLimit(f"no answer after {max_steps} steps")
