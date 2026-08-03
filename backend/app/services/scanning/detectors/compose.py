"""Compose detector — delegates to the importer that already exists.

Deliberately adds no parsing of its own: it is the control that proves the
registry works against known-good code.
"""
import re

from app.services import docker_compose_import_service
from app.services.scanning.registry import Detector, DetectorResult, ParseContext

# Any depth; the filename must be exactly one of the four Compose spellings.
_PATTERN = re.compile(r"(?:^|/)(?:docker-compose|compose)\.ya?ml$")


def _matches(path: str) -> bool:
    return _PATTERN.search(path) is not None


async def _parse(ctx: ParseContext) -> DetectorResult:
    result = await docker_compose_import_service.import_docker_compose(
        system_id=ctx.system_id,
        tenant_id=ctx.tenant_id,
        content=ctx.content,
        db=ctx.db,
    )
    return DetectorResult(
        subsystems_created=result.get("subsystems_created", 0),
        subsystems_updated=result.get("subsystems_updated", 0),
        dependencies_written=result.get("dependencies_created", 0),
    )


DOCKER_COMPOSE = Detector(name="docker_compose", matches=_matches, parse=_parse)
