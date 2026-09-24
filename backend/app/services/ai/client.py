"""OpenAI-compatible chat + embeddings client.

Configuration is `AI_*` in app.core.config; model names are the gateway's
stable aliases. Nothing in here knows which model backs an alias, and nothing
in the rest of the app should reach the SDK directly — every AI call goes
through this seam so tests can substitute a scripted client.
"""
from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

# U+2010..U+2014 (hyphen, non-breaking hyphen, figure dash, en dash, em dash)
# and U+2212 (minus). gpt-oss writes ids like ORD‑1051 with U+2011.
_HYPHENS = str.maketrans({c: "-" for c in "‐‑‒–—−"})


def normalise_hyphens(text: str) -> str:
    """ASCII '-' for every Unicode dash a model may emit inside an id."""
    return text.translate(_HYPHENS)


class ModelRole(str, enum.Enum):
    """Which AI_*_MODEL alias a call is made under.

    The reasoning-effort policy hangs off the ROLE rather than the alias
    string so that swapping the model behind an alias on the server is the
    only change needed — unless the new model has a different quirk, in
    which case update `default_reasoning_effort` and CLAUDE.md together.
    """

    CHAT = "chat"
    AGENT = "agent"
    FAST = "fast"


def default_reasoning_effort(role: ModelRole) -> Optional[str]:
    """What to send as `reasoning_effort` unless the caller overrides it.

    Every alias accepts every value (the gateway translates what a model
    cannot honour — CLAUDE.md, "Local AI test server", 2026-09-23), so this
    policy is about SPEED, not safety:
    - agent (qwen3.8:27b): thinking off is the measured best; "none" is also
      the server default, sent explicitly so a server default changing does
      not change us.
    - chat (gpt-oss:20b): always reasons; unset means medium (~4 s). "low"
      keeps interactive replies sub-second.
    - fast (qwen3.5:4b): thinking off (~0.1 s); any other value switches
      ~100–200 tokens of reasoning on and costs ~2 s.
    Callers wanting a hard planning step pass "low"/"medium" themselves.
    """
    return {ModelRole.AGENT: "none", ModelRole.CHAT: "low", ModelRole.FAST: "none"}[role]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    # None when the model's arguments were not valid JSON; `raw_arguments`
    # then carries what it sent so the loop can tell it what was wrong.
    arguments: Optional[dict[str, Any]]
    raw_arguments: str = ""


@dataclass(frozen=True)
class ChatResult:
    content: str
    reasoning: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None


def parse_message(message: Any, finish_reason: Optional[str]) -> ChatResult:
    """Flatten an SDK ChatCompletionMessage into plain values.

    `reasoning_content` is not a declared SDK field; it arrives in
    `model_extra` when the model was thinking. It is returned separately and
    must never be concatenated into `content` by a caller.
    """
    extra = getattr(message, "model_extra", None) or {}
    reasoning = extra.get("reasoning_content")
    calls: list[ToolCall] = []
    for call in message.tool_calls or []:
        raw = call.function.arguments or ""
        try:
            parsed = json.loads(raw) if raw.strip() else {}
            if not isinstance(parsed, dict):
                parsed = None
        except json.JSONDecodeError:
            parsed = None
        calls.append(ToolCall(id=call.id, name=call.function.name, arguments=parsed, raw_arguments=raw))
    return ChatResult(
        content=message.content or "",
        reasoning=reasoning if reasoning else None,
        tool_calls=calls,
        finish_reason=finish_reason,
    )


class AIClient(Protocol):
    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatResult: ...

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleClient:
    """The real client. Constructed through `build_client`, never directly."""

    def __init__(self, base_url: str, api_key: str, timeout_seconds: int) -> None:
        # Imported here so the SDK is only loaded when AI is configured.
        from openai import AsyncOpenAI

        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        # max_retries=0: a retry on a slow local model doubles a 100 s wait
        # and, on a write-capable agent, could double a side effect.
        self._sdk = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatResult:
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response = await self._sdk.chat.completions.create(**kwargs)
        choice = response.choices[0]
        result = parse_message(choice.message, choice.finish_reason)
        usage = getattr(response, "usage", None)
        logger.info(
            "ai chat model=%s finish=%s tool_calls=%d tokens=%s",
            model, result.finish_reason, len(result.tool_calls),
            getattr(usage, "total_tokens", None),
        )
        return result

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        response = await self._sdk.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]


def build_client(settings: Any) -> Optional[OpenAICompatibleClient]:
    """None when AI_BASE_URL is unset — AI features are off, not broken."""
    if not settings.AI_BASE_URL:
        return None
    return OpenAICompatibleClient(
        base_url=settings.AI_BASE_URL,
        api_key=settings.AI_API_KEY,
        timeout_seconds=settings.AI_TIMEOUT_SECONDS,
    )
