from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dependency import DependencySource
from app.services.scanning.declared import DeclaredEdge, DeclaredState, DeclaredSubsystem

IMAGE_TYPE_MAP = {
    'postgres': 'database',
    'mysql': 'database',
    'mariadb': 'database',
    'mongo': 'database',
    'redis': 'cache',
    'memcached': 'cache',
    'rabbitmq': 'message_queue',
    'kafka': 'message_queue',
    'nats': 'message_queue',
    'nginx': 'api_gateway',
    'traefik': 'api_gateway',
    'caddy': 'api_gateway',
    'celery': 'worker',
}


def infer_component_type(image: str | None) -> str:
    if not image:
        return 'web_service'
    image_lower = image.lower()
    for key, ctype in IMAGE_TYPE_MAP.items():
        if key in image_lower:
            return ctype
    return 'web_service'


def parse_docker_compose(content: bytes, path: str) -> DeclaredState:
    """Read a compose file into the services and edges it declares.

    Pure: no database, no ids. Values are truncated to their column widths here
    so a stored row compares equal to the declaration it came from.
    """
    try:
        compose = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}")

    if not isinstance(compose, dict):
        raise ValueError(
            "Invalid docker-compose file: expected a YAML mapping at the top level"
        )

    services: dict[str, Any] = compose.get('services', {})
    if not isinstance(services, dict) or not services:
        raise ValueError("No services found in docker-compose file")

    declared = DeclaredState()
    for service_name, service_config in services.items():
        if not isinstance(service_name, str):
            continue
        service_config = service_config or {}
        image = service_config.get('image')
        technology = image.split(':')[0][:100] if image else None
        declared.subsystems.append(DeclaredSubsystem(
            name=service_name[:200],
            component_type=infer_component_type(image),
            technology=technology,
            source_path=path[:500],
        ))

    for service_name, service_config in services.items():
        if not isinstance(service_name, str):
            continue
        service_config = service_config or {}
        depends_on = service_config.get('depends_on', {})
        # depends_on is either a list of names or a mapping of name -> condition.
        if isinstance(depends_on, list):
            dep_names = depends_on
        elif isinstance(depends_on, dict):
            dep_names = list(depends_on.keys())
        else:
            dep_names = []

        ports = service_config.get('ports', [])
        port = None
        if ports:
            # ports are "host:container" strings or bare integers.
            try:
                port = int(str(ports[0]).split(':')[-1])
            except (ValueError, IndexError):
                port = None

        for dep_name in dep_names:
            if not isinstance(dep_name, str):
                continue
            declared.edges.append(DeclaredEdge(
                from_name=service_name[:200],
                to_name=dep_name[:200],
                port=port,
                source_path=path[:500],
            ))

    return declared


async def import_docker_compose(
    system_id: int,
    tenant_id: int,
    content: bytes,
    db: AsyncSession,
    path: str = "docker-compose.yml",
) -> dict[str, int]:
    """Parse a compose file and write what it declares.

    Kept for the direct-upload endpoint in api/v1/import_routes.py. The scan
    path does not use this — it parses once per file, accumulates, and applies
    the total, so two compose files no longer wipe each other's edges.
    """
    from app.db.models.system import SubSystemSource
    from app.services.scanning import reconcile

    declared = parse_docker_compose(content, path)
    result = await reconcile.apply(
        db,
        system_id=system_id,
        tenant_id=tenant_id,
        source=SubSystemSource.DOCKER_COMPOSE,
        edge_source=DependencySource.DOCKER_COMPOSE,
        declared=declared,
    )
    return {
        'subsystems_created': result.subsystems_created,
        'subsystems_updated': result.subsystems_updated,
        'dependencies_created': result.dependencies_written,
    }
