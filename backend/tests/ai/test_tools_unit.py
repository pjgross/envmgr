"""The copilot's first tool, list_environments — real database, no LLM.

A tool is the LLM's only view of the data, so it has the same tenant rule as
an endpoint and one extra: bad arguments come back as an explicit error the
model can act on, never as an empty result (models self-correct from errors
and give up on empty results).
"""
import json

import pytest

from app.db.models.environment import EnvironmentStatus
from app.services.ai.tools import REGISTRY, ToolContext, openai_tool_definitions
from tests.factories import ensure_environment


async def _call(db, tenant_id, **arguments) -> dict:
    spec = REGISTRY["list_environments"]
    raw = await spec.handler(ToolContext(db=db, tenant_id=tenant_id), arguments)
    return json.loads(raw)


async def test_it_lists_the_tenants_environments(db_session, test_tenant):
    a = await ensure_environment(db_session, test_tenant.id, slot=1)
    b = await ensure_environment(db_session, test_tenant.id, slot=2)
    b.status = EnvironmentStatus.INACTIVE
    await db_session.flush()

    result = await _call(db_session, test_tenant.id)

    assert result["total"] == 2
    assert {e["name"] for e in result["environments"]} == {a.name, b.name}
    assert all({"id", "name", "status", "tier"} <= set(e) for e in result["environments"])


async def test_status_filters_in_sql(db_session, test_tenant):
    a = await ensure_environment(db_session, test_tenant.id, slot=1)
    b = await ensure_environment(db_session, test_tenant.id, slot=2)
    b.status = EnvironmentStatus.INACTIVE
    await db_session.flush()

    result = await _call(db_session, test_tenant.id, status="active")

    assert [e["name"] for e in result["environments"]] == [a.name]
    assert result["total"] == 1


async def test_another_tenants_environments_are_invisible(
    db_session, test_tenant, second_tenant_factory
):
    other, _ = await second_tenant_factory()
    await ensure_environment(db_session, test_tenant.id, slot=1)
    await ensure_environment(db_session, other.id, slot=1)

    result = await _call(db_session, test_tenant.id)

    assert result["total"] == 1


async def test_an_unknown_status_is_an_explicit_error_naming_the_allowed_values(
    db_session, test_tenant
):
    # gpt-oss was observed sending status: "all". An empty list here would
    # read to the model as "no environments"; an error tells it what to fix.
    result = await _call(db_session, test_tenant.id, status="all")

    assert "error" in result
    assert "all" in result["error"]
    for allowed in ("active", "inactive", "maintenance", "decommissioned"):
        assert allowed in result["error"]
    assert "environments" not in result


async def test_an_unknown_argument_is_an_explicit_error(db_session, test_tenant):
    result = await _call(db_session, test_tenant.id, colour="blue")
    assert "colour" in result["error"]


def test_tool_definitions_are_openai_shaped():
    defs = openai_tool_definitions([REGISTRY["list_environments"]])
    assert defs == [
        {
            "type": "function",
            "function": {
                "name": "list_environments",
                "description": REGISTRY["list_environments"].description,
                "parameters": REGISTRY["list_environments"].parameters,
            },
        }
    ]
    # The allowed statuses are declared to the model, not only enforced.
    statuses = defs[0]["function"]["parameters"]["properties"]["status"]["enum"]
    assert set(statuses) == {s.value for s in EnvironmentStatus}
