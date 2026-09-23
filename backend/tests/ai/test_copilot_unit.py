"""The agent loop — scripted client, real tool registry, real database.

These pin the application's own behaviour around the model: which tool it
dispatched with which arguments, what it fed back, and that reasoning never
reaches the answer. What the model would actually say is the integration
suite's job (test_copilot_integration.py).
"""
import json

import pytest

from app.services.ai.client import ChatResult, ToolCall
from app.services.ai.copilot_service import AgentStepLimit, run_agent
from app.services.ai.tools import REGISTRY, ToolContext
from tests.factories import ensure_environment


class ScriptedClient:
    """Returns the scripted ChatResults in order and records every request."""

    def __init__(self, script: list[ChatResult]):
        self._script = list(script)
        self.requests: list[dict] = []

    async def chat(self, *, model, messages, tools=None, reasoning_effort=None, max_tokens=None):
        self.requests.append(
            {"model": model, "messages": list(messages), "tools": tools,
             "reasoning_effort": reasoning_effort, "max_tokens": max_tokens}
        )
        if not self._script:
            raise AssertionError("script exhausted")
        return self._script.pop(0)

    async def embed(self, *, model, texts):  # pragma: no cover - not used here
        raise NotImplementedError


def _tool_turn(name, arguments, call_id="call_1"):
    return ChatResult(
        content="", reasoning=None, finish_reason="tool_calls",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def _final(content, reasoning=None):
    return ChatResult(content=content, reasoning=reasoning, tool_calls=[], finish_reason="stop")


async def test_a_tool_call_is_dispatched_and_its_result_fed_back(db_session, test_tenant):
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    client = ScriptedClient([
        _tool_turn("list_environments", {"status": "active"}),
        _final(f"{env.name} (id {env.id}) is active."),
    ])

    result = await run_agent(
        client, ToolContext(db=db_session, tenant_id=test_tenant.id),
        "Which environments are active?", model="copilot-agent",
    )

    assert result.answer == f"{env.name} (id {env.id}) is active."
    assert [(t.name, t.arguments) for t in result.turns] == [
        ("list_environments", {"status": "active"})
    ]
    # The second request carried the assistant's tool call and our tool
    # message, in that order, addressed by the call id.
    second = client.requests[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["id"] == "call_1"
    assert second[-1] == {
        "role": "tool", "tool_call_id": "call_1", "content": result.turns[0].result,
    }
    assert json.loads(result.turns[0].result)["environments"][0]["id"] == env.id


async def test_the_tool_definitions_and_effort_policy_travel_with_every_request(
    db_session, test_tenant
):
    client = ScriptedClient([_final("Nothing to do.")])
    await run_agent(
        client, ToolContext(db=db_session, tenant_id=test_tenant.id), "hi",
        model="copilot-agent", reasoning_effort="none",
    )
    request = client.requests[0]
    assert request["model"] == "copilot-agent"
    assert request["reasoning_effort"] == "none"
    assert [t["function"]["name"] for t in request["tools"]] == ["list_environments"]
    assert request["messages"][0]["role"] == "system"
    assert request["messages"][-1] == {"role": "user", "content": "hi"}


async def test_reasoning_never_reaches_the_answer(db_session, test_tenant):
    client = ScriptedClient([_final("PONG", reasoning="The user wants PONG.")])
    result = await run_agent(
        client, ToolContext(db=db_session, tenant_id=test_tenant.id), "ping", model="m",
    )
    assert result.answer == "PONG"
    assert "The user wants PONG." not in result.answer


async def test_an_unknown_tool_is_reported_to_the_model_not_raised(db_session, test_tenant):
    client = ScriptedClient([
        _tool_turn("delete_everything", {}),
        _final("I cannot do that."),
    ])
    result = await run_agent(
        client, ToolContext(db=db_session, tenant_id=test_tenant.id), "wipe it", model="m",
    )
    fed_back = json.loads(client.requests[1]["messages"][-1]["content"])
    assert "delete_everything" in fed_back["error"]
    assert "list_environments" in fed_back["error"]  # names what IS available
    assert result.answer == "I cannot do that."


async def test_unparseable_arguments_are_reported_to_the_model(db_session, test_tenant):
    broken = ChatResult(
        content="", reasoning=None, finish_reason="tool_calls",
        tool_calls=[ToolCall(id="c1", name="list_environments", arguments=None,
                             raw_arguments="{oops")],
    )
    client = ScriptedClient([broken, _final("Sorry.")])
    await run_agent(
        client, ToolContext(db=db_session, tenant_id=test_tenant.id), "x", model="m",
    )
    fed_back = json.loads(client.requests[1]["messages"][-1]["content"])
    assert "JSON" in fed_back["error"]


async def test_a_tool_error_is_fed_back_and_the_model_may_retry(db_session, test_tenant):
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    client = ScriptedClient([
        _tool_turn("list_environments", {"status": "all"}, call_id="c1"),
        _tool_turn("list_environments", {}, call_id="c2"),
        _final(f"There is one: {env.name}."),
    ])
    result = await run_agent(
        client, ToolContext(db=db_session, tenant_id=test_tenant.id), "list them", model="m",
    )
    first = json.loads(result.turns[0].result)
    assert "error" in first and "all" in first["error"]
    assert json.loads(result.turns[1].result)["total"] == 1
    assert result.answer.endswith(f"{env.name}.")


async def test_the_step_limit_is_enforced(db_session, test_tenant):
    client = ScriptedClient([_tool_turn("list_environments", {}) for _ in range(5)])
    with pytest.raises(AgentStepLimit):
        await run_agent(
            client, ToolContext(db=db_session, tenant_id=test_tenant.id), "loop",
            model="m", max_steps=3,
        )
    assert len(client.requests) == 3
