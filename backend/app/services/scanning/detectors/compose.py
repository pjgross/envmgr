"""Compose detector — delegates to the importer that already exists.

Deliberately adds no parsing of its own: it is the control that proves the
registry works against known-good code.
"""
import re

from app.db.models.dependency import DependencySource
from app.db.models.system import SubSystemSource
from app.services import docker_compose_import_service
from app.services.scanning.declared import DeclaredState
from app.services.scanning.registry import Detector, ParseContext

# Base Compose files only. `docker-compose.override.yml`, `docker-compose.prod.yml`
# and friends are deliberately NOT claimed: an override is a fragment that
# merges onto a base file, and parsing one alone would import a partial
# service list as though it were the whole application. Supporting them means
# merging base + override before parsing, which the importer cannot do —
# claiming them without that would be confidently wrong rather than silent.
_PATTERN = re.compile(r"(?:^|/)(?:docker-compose|compose)\.ya?ml$")


def _matches(path: str) -> bool:
    return _PATTERN.search(path) is not None


async def _parse(ctx: ParseContext) -> DeclaredState:
    return docker_compose_import_service.parse_docker_compose(ctx.content, ctx.path)


DOCKER_COMPOSE = Detector(
    name="docker_compose",
    matches=_matches,
    parse=_parse,
    subsystem_source=SubSystemSource.DOCKER_COMPOSE,
    edge_source=DependencySource.DOCKER_COMPOSE,
)
