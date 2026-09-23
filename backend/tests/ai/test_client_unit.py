"""app.services.ai.client — no network.

The client is a thin seam over the OpenAI-compatible gateway described in
CLAUDE.md ("Local AI test server"). What is worth pinning without a server is
the part that decides what the rest of the app sees: reasoning is split off
from the answer, tool calls are parsed into plain values, the per-role
reasoning_effort policy encodes the model quirks found on 2026-09-23, and the
client is absent — not broken — when AI_BASE_URL is unset.
"""
from types import SimpleNamespace

import pytest

from app.services.ai.client import (
    ChatResult,
    ModelRole,
    ToolCall,
    build_client,
    default_reasoning_effort,
    normalise_hyphens,
    parse_message,
)


def _message(content=None, reasoning=None, tool_calls=None):
    """A stand-in with the attributes the SDK's ChatCompletionMessage exposes."""
    extra = {"reasoning_content": reasoning} if reasoning is not None else {}
    return SimpleNamespace(content=content, tool_calls=tool_calls, model_extra=extra)


def test_reasoning_is_split_off_from_the_answer():
    result = parse_message(_message(content="PONG", reasoning="Need to say PONG."), "stop")
    assert result == ChatResult(
        content="PONG", reasoning="Need to say PONG.", tool_calls=[], finish_reason="stop"
    )


def test_a_message_with_no_reasoning_field_reads_reasoning_as_none():
    result = parse_message(_message(content="hi"), "stop")
    assert result.reasoning is None
    assert result.content == "hi"


def test_a_null_content_reads_as_empty_string():
    # A tool-call turn has content None; callers concatenate answers.
    assert parse_message(_message(content=None), "tool_calls").content == ""


def test_tool_call_arguments_are_parsed_from_json():
    call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="list_environments", arguments='{"status": "active"}'),
    )
    result = parse_message(_message(tool_calls=[call]), "tool_calls")
    assert result.tool_calls == [
        ToolCall(id="call_1", name="list_environments", arguments={"status": "active"},
                 raw_arguments='{"status": "active"}')
    ]


def test_unparseable_tool_arguments_are_kept_as_an_error_not_raised():
    # The agent loop must be able to tell the model what was wrong; a parse
    # error that raised here would abort the whole turn instead.
    call = SimpleNamespace(id="c", function=SimpleNamespace(name="x", arguments="{not json"))
    result = parse_message(_message(tool_calls=[call]), "tool_calls")
    assert result.tool_calls[0].arguments is None
    assert result.tool_calls[0].raw_arguments == "{not json"


def test_unicode_hyphens_are_normalised():
    # gpt-oss writes ORD‑1051 with U+2011; every dash in U+2010–U+2014 and the
    # minus sign U+2212 must become ASCII '-'. Plain '-' is untouched.
    assert normalise_hyphens("ORD‑1051 SIT–2 x−y a-b—c") == "ORD-1051 SIT-2 x-y a-b-c"


def test_reasoning_effort_policy_per_role():
    # Server behaviour as of 2026-09-23 (CLAUDE.md, "Local AI test server"):
    # every alias accepts every value. The policy is about SPEED, not safety:
    # agent and fast are "none" by default server-side (sending it is
    # explicit, and survives a server default changing); chat always reasons
    # and its unset default is medium (~4 s), so "low" keeps it sub-second.
    assert default_reasoning_effort(ModelRole.AGENT) == "none"
    assert default_reasoning_effort(ModelRole.CHAT) == "low"
    assert default_reasoning_effort(ModelRole.FAST) == "none"


def test_no_client_when_ai_base_url_is_unset():
    settings = SimpleNamespace(AI_BASE_URL="", AI_API_KEY="local", AI_TIMEOUT_SECONDS=120)
    assert build_client(settings) is None


def test_client_is_built_from_settings_when_configured():
    settings = SimpleNamespace(
        AI_BASE_URL="http://ai.example:4000/v1", AI_API_KEY="local", AI_TIMEOUT_SECONDS=7
    )
    client = build_client(settings)
    assert client is not None
    assert client.base_url == "http://ai.example:4000/v1"
    assert client.timeout_seconds == 7
