from typing import Any

import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dependency import (
    ComponentDependency,
    DependencyDirection,
    DependencySource,
    DependencyType,
)
from app.db.models.system import SubSystem

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


async def import_docker_compose(
    system_id: int,
    tenant_id: int,
    content: bytes,
    db: AsyncSession,
) -> dict[str, int]:
    """
    Parse a docker-compose.yml and upsert subsystems + component dependencies.
    Returns counts of created/updated subsystems and created dependencies.
    """
    try:
        compose = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}")

    if not isinstance(compose, dict):
        raise ValueError("Invalid docker-compose file: expected a YAML mapping at the top level")

    services: dict[str, Any] = compose.get('services', {})
    if not services:
        raise ValueError("No services found in docker-compose file")

    # Load existing subsystems for this system (match by name for upsert)
    result = await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    existing = {s.name: s for s in result.scalars().all()}

    subsystems_created = 0
    subsystems_updated = 0
    name_to_id: dict[str, int] = {}

    for service_name, service_config in services.items():
        service_config = service_config or {}
        image = service_config.get('image')
        component_type = infer_component_type(image)
        technology = image.split(':')[0] if image else None  # strip tag

        if service_name in existing:
            # Update existing subsystem
            sub = existing[service_name]
            sub.component_type = component_type
            sub.technology = technology
            await db.flush()
            name_to_id[service_name] = sub.id
            subsystems_updated += 1
        else:
            # Create new subsystem
            sub = SubSystem(
                name=service_name,
                system_id=system_id,
                tenant_id=tenant_id,
                component_type=component_type,
                technology=technology,
            )
            db.add(sub)
            await db.flush()  # get the id
            name_to_id[service_name] = sub.id
            subsystems_created += 1

    # Delete existing docker_compose dependencies for this system's subsystems
    all_subsystem_ids = list(name_to_id.values()) + [
        s.id for s in existing.values() if s.name not in name_to_id
    ]
    if all_subsystem_ids:
        await db.execute(
            delete(ComponentDependency).where(
                ComponentDependency.tenant_id == tenant_id,
                ComponentDependency.from_subsystem_id.in_(all_subsystem_ids),
                ComponentDependency.source == DependencySource.DOCKER_COMPOSE,
            )
        )

    dependencies_created = 0
    for service_name, service_config in services.items():
        service_config = service_config or {}
        depends_on = service_config.get('depends_on', {})

        # depends_on can be a list of strings or a dict with condition keys
        if isinstance(depends_on, list):
            dep_names = depends_on
        elif isinstance(depends_on, dict):
            dep_names = list(depends_on.keys())
        else:
            dep_names = []

        from_id = name_to_id.get(service_name)
        if not from_id:
            continue

        ports = service_config.get('ports', [])
        port = None
        if ports:
            # ports can be "host:container" strings or integers
            first_port = str(ports[0])
            try:
                port = int(first_port.split(':')[-1])
            except (ValueError, IndexError):
                port = None

        for dep_name in dep_names:
            to_id = name_to_id.get(dep_name)
            if not to_id or to_id == from_id:
                continue
            dep = ComponentDependency(
                from_subsystem_id=from_id,
                to_subsystem_id=to_id,
                dependency_type=DependencyType.API_CALL,
                direction=DependencyDirection.ONE_WAY,
                source=DependencySource.DOCKER_COMPOSE,
                port=port,
                tenant_id=tenant_id,
            )
            db.add(dep)
            dependencies_created += 1

    await db.flush()
    return {
        'subsystems_created': subsystems_created,
        'subsystems_updated': subsystems_updated,
        'dependencies_created': dependencies_created,
    }
