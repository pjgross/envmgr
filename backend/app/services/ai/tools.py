"""Tools a model may call. Additive allowlist — see the package docstring.

Contract for every handler:
- takes a `ToolContext` (tenant-scoped database access) and the model's
  arguments as a dict;
- returns a JSON STRING, because that is what goes back to the model verbatim;
- on bad input returns `{"error": "..."}` naming what was wrong and what is
  allowed. Never an empty result: models self-correct from an error and give
  up on an empty list (observed with gpt-oss sending `status: "all"`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.db.models.environment import EnvironmentStatus
from app.services import environment_service


@dataclass(frozen=True)
class ToolContext:
    db: AsyncSession
    tenant_id: int


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema, as OpenAI expects it
    handler: Handler


def error(message: str) -> str:
    return json.dumps({"error": message})


def _unknown_keys(arguments: dict[str, Any], allowed: set[str]) -> Optional[str]:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        return error(
            f"Unknown argument(s) {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
    return None


# The model is told about the cap so it can say "first 50" rather than "all".
_LIST_LIMIT = 50

_STATUS_VALUES = [s.value for s in EnvironmentStatus]


async def list_environments(ctx: ToolContext, arguments: dict[str, Any]) -> str:
    if (problem := _unknown_keys(arguments, {"status", "search"})) is not None:
        return problem
    status = arguments.get("status")
    status_filter: Optional[EnvironmentStatus] = None
    if status is not None:
        try:
            status_filter = EnvironmentStatus(str(status).lower())
        except ValueError:
            return error(
                f"Unknown status '{status}'. Allowed: {', '.join(_STATUS_VALUES)}. "
                "Omit status to list every environment."
            )
    search = arguments.get("search")
    views, total = await environment_service.list_environments(
        ctx.db, ctx.tenant_id, status_filter=status_filter,
        page=Page(limit=_LIST_LIMIT, offset=0), search=str(search) if search else None,
    )
    return json.dumps({
        "environments": [
            {
                "id": v.environment.id,
                "name": v.environment.name,
                "status": v.environment.status.value,
                "tier": v.tier_name,
            }
            for v in views
        ],
        "total": total,
        "truncated": total > len(views),
    })


LIST_ENVIRONMENTS = ToolSpec(
    name="list_environments",
    description=(
        "List the test environments in the caller's tenant, with their numeric "
        f"id, name, status and tier. Returns at most {_LIST_LIMIT} rows and the "
        "true total. Filter by status or by a name fragment."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": _STATUS_VALUES,
                "description": "Only environments in this status. Omit for all.",
            },
            "search": {
                "type": "string",
                "description": "Case-insensitive fragment of the environment name.",
            },
        },
        "additionalProperties": False,
    },
    handler=list_environments,
)


REGISTRY: dict[str, ToolSpec] = {LIST_ENVIRONMENTS.name: LIST_ENVIRONMENTS}


def openai_tool_definitions(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": s.description,
                "parameters": s.parameters,
            },
        }
        for s in specs
    ]
