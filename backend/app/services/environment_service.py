from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, delete, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import Page, fetch_page
from app.db.models.environment import (
    Environment,
    EnvironmentSystem,
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
    EnvironmentStatus,
)
from app.db.models.dependency import SystemDependency, ComponentDependency
from app.db.models.system import SubSystem, System
from app.api.v1.schemas.environment import EnvironmentCreate, EnvironmentUpdate
from app.core.events import publish_event
from app.services.custom_field_service import validate_custom_fields


async def list_environments(
    db: AsyncSession,
    tenant_id: int,
    status_filter: Optional[EnvironmentStatus] = None,
    environment_type: Optional[str] = None,
    page: Optional[Page] = None,
) -> tuple[list[Environment], int]:
    """Environments for a tenant, plus the unwindowed total.

    Returns the total even when `page` is None so callers have one shape to
    handle; see app/core/pagination.py.
    """
    query = (
        select(Environment)
        .where(Environment.tenant_id == tenant_id, Environment.deleted_at.is_(None))
    )
    if status_filter is not None:
        query = query.where(Environment.status == status_filter)
    if environment_type is not None:
        query = query.where(Environment.environment_type == environment_type)
    query = query.order_by(Environment.name)
    return await fetch_page(db, query, page)


async def get_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> Environment:
    result = await db.execute(
        select(Environment).where(
            Environment.id == env_id,
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        )
    )
    env = result.scalar_one_or_none()
    if env is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    return env


async def create_environment(
    db: AsyncSession, data: EnvironmentCreate, tenant_id: int
) -> Environment:
    # Check name uniqueness within tenant (active records only)
    existing = await db.execute(
        select(Environment).where(
            Environment.name == data.name,
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An environment with this name already exists in this tenant",
        )
    await validate_custom_fields(db, tenant_id, "environment", data.custom_fields)
    env = Environment(
        name=data.name,
        description=data.description,
        environment_type=data.environment_type,
        status=data.status,
        tenant_id=tenant_id,
        custom_fields=data.custom_fields,
    )
    db.add(env)
    await db.flush()
    await db.refresh(env)
    await publish_event(
        db,
        event_type="EnvironmentCreated",
        aggregate_id=env.id,
        aggregate_type="Environment",
        payload={"id": env.id, "name": env.name, "tenant_id": env.tenant_id},
        tenant_id=env.tenant_id,
    )
    return env


async def update_environment(
    db: AsyncSession, env_id: int, data: EnvironmentUpdate, tenant_id: int
) -> Environment:
    env = await get_environment(db, env_id, tenant_id)

    if data.name is not None and data.name != env.name:
        existing = await db.execute(
            select(Environment).where(
                Environment.name == data.name,
                Environment.tenant_id == tenant_id,
                Environment.id != env_id,
                Environment.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An environment with this name already exists in this tenant",
            )
        env.name = data.name

    if data.description is not None:
        env.description = data.description
    if data.environment_type is not None:
        env.environment_type = data.environment_type
    if data.status is not None:
        env.status = data.status
    if data.custom_fields is not None:
        env.custom_fields = data.custom_fields

    if data.custom_fields is not None:
        await validate_custom_fields(db, tenant_id, "environment", data.custom_fields)
    await db.flush()
    await db.refresh(env)
    await publish_event(
        db,
        event_type="EnvironmentUpdated",
        aggregate_id=env.id,
        aggregate_type="Environment",
        payload={"id": env.id, "name": env.name, "tenant_id": env.tenant_id},
        tenant_id=env.tenant_id,
    )
    return env


async def delete_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> None:
    env = await get_environment(db, env_id, tenant_id)

    # Hard-delete all environment_subsystem junction rows
    await db.execute(
        delete(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
    )

    env.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="EnvironmentDeleted",
        aggregate_id=env.id,
        aggregate_type="Environment",
        payload={"id": env.id, "name": env.name, "tenant_id": env.tenant_id},
        tenant_id=env.tenant_id,
    )


async def verify_environment(db: AsyncSession, env_id: int, tenant_id: int) -> dict:
    """Check system-level and component-level dependency coverage for an environment."""
    await get_environment(db, env_id, tenant_id)

    # Load assigned systems
    env_sys_result = await db.execute(
        select(EnvironmentSystem)
        .where(EnvironmentSystem.environment_id == env_id)
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys_rows = list(env_sys_result.scalars().all())
    env_system_map: dict[int, EnvironmentSystem] = {row.system_id: row for row in env_sys_rows}
    system_ids = list(env_system_map.keys())

    # ------------------------------------------------------------------ #
    # System-level pass (satisfied / missing only — no more "mocked")     #
    # ------------------------------------------------------------------ #
    deps_result = await db.execute(
        select(SystemDependency)
        .where(
            SystemDependency.from_system_id.in_(system_ids),
            SystemDependency.tenant_id == tenant_id,
        )
        .options(selectinload(SystemDependency.to_system))
    )
    all_deps = list(deps_result.scalars().all())

    deps_by_system: dict[int, list[SystemDependency]] = defaultdict(list)
    for dep in all_deps:
        deps_by_system[dep.from_system_id].append(dep)

    systems_result: list[dict] = []
    total_deps = satisfied_count = mocked_count = missing_count = 0

    for system_id, env_sys in env_system_map.items():
        verify_items: list[dict] = []
        for dep in deps_by_system[system_id]:
            to_id = dep.to_system_id
            if to_id in env_system_map:
                dep_status = "satisfied"
                satisfied_count += 1
            else:
                dep_status = "missing"
                missing_count += 1
            total_deps += 1
            to_system_name = dep.to_system.name if dep.to_system else f"System#{to_id}"
            verify_items.append({
                "to_system_id": to_id,
                "to_system_name": to_system_name,
                "dependency_type": dep.dependency_type,
                "status": dep_status,
            })
        systems_result.append({
            "system_id": system_id,
            "system_name": env_sys.system.name,
            "dependencies": verify_items,
        })

    # ------------------------------------------------------------------ #
    # Component-level pass                                                 #
    # ------------------------------------------------------------------ #
    comp_total = comp_satisfied = comp_mocked = comp_missing = 0
    comp_dep_items: list[dict] = []

    if system_ids:
        # Load all env subsystem mock status
        env_sub_result = await db.execute(
            select(EnvironmentSubSystem).where(
                EnvironmentSubSystem.environment_id == env_id,
                EnvironmentSubSystem.tenant_id == tenant_id,
            )
        )
        env_sub_map: dict[int, bool] = {
            row.subsystem_id: row.is_mocked for row in env_sub_result.scalars().all()
        }

        # Load subsystem IDs belonging to assigned systems
        env_subsystem_ids_result = await db.execute(
            select(SubSystem.id, SubSystem.name).where(
                SubSystem.system_id.in_(system_ids),
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )
        env_subsystem_id_to_name = {row[0]: row[1] for row in env_subsystem_ids_result.all()}
        env_subsystem_ids = list(env_subsystem_id_to_name.keys())

        if env_subsystem_ids:
            comp_deps_result = await db.execute(
                select(ComponentDependency)
                .where(
                    ComponentDependency.from_subsystem_id.in_(env_subsystem_ids),
                    ComponentDependency.tenant_id == tenant_id,
                )
                .options(
                    selectinload(ComponentDependency.from_subsystem),
                    selectinload(ComponentDependency.to_subsystem),
                )
            )
            all_comp_deps = list(comp_deps_result.scalars().all())
            for dep in all_comp_deps:
                to_id = dep.to_subsystem_id
                from_name = dep.from_subsystem.name if dep.from_subsystem else f"SubSystem#{dep.from_subsystem_id}"
                to_name = dep.to_subsystem.name if dep.to_subsystem else f"SubSystem#{to_id}"

                if to_id in env_sub_map:
                    is_mocked = env_sub_map[to_id]
                    dep_status = "mocked" if is_mocked else "satisfied"
                    if is_mocked:
                        comp_mocked += 1
                    else:
                        comp_satisfied += 1
                else:
                    dep_status = "missing"
                    comp_missing += 1

                comp_total += 1
                comp_dep_items.append({
                    "from_subsystem_id": dep.from_subsystem_id,
                    "from_subsystem_name": from_name,
                    "to_subsystem_id": to_id,
                    "to_subsystem_name": to_name,
                    "dependency_type": dep.dependency_type,
                    "status": dep_status,
                })

    return {
        "environment_id": env_id,
        "total_dependencies": total_deps,
        "satisfied_count": satisfied_count,
        "mocked_count": mocked_count,
        "missing_count": missing_count,
        "systems": systems_result,
        "component_total": comp_total,
        "component_satisfied": comp_satisfied,
        "component_mocked": comp_mocked,
        "component_missing": comp_missing,
        "component_dependencies": comp_dep_items,
    }


async def get_environment_topology(db: AsyncSession, env_id: int, tenant_id: int) -> dict:
    """Return all subsystems in the env + component deps for the topology diagram."""
    await get_environment(db, env_id, tenant_id)

    # Load env subsystems with mock status
    env_sub_result = await db.execute(
        select(EnvironmentSubSystem)
        .where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
        .options(
            selectinload(EnvironmentSubSystem.subsystem),
            selectinload(EnvironmentSubSystem.hosts).selectinload(
                EnvironmentSubSystemHost.infrastructure_component
            ),
        )
    )
    env_sub_rows = list(env_sub_result.scalars().all())

    if not env_sub_rows:
        return {
            "environment_id": env_id,
            "subsystems": [],
            "dependencies": [],
            "system_names": {},
            "outside_subsystems": [],
            "outside_dependencies": [],
        }

    env_subsystem_ids = [row.subsystem_id for row in env_sub_rows]
    env_subsystem_id_set = set(env_subsystem_ids)
    is_mocked_map = {row.subsystem_id: row.is_mocked for row in env_sub_rows}

    # Collect system IDs and names
    subsystem_to_system: dict[int, int] = {}
    for row in env_sub_rows:
        if row.subsystem:
            subsystem_to_system[row.subsystem_id] = row.subsystem.system_id

    system_ids = list({v for v in subsystem_to_system.values()})
    sys_result = await db.execute(
        select(System).where(System.id.in_(system_ids), System.tenant_id == tenant_id)
    )
    system_names: dict[int, str] = {s.id: s.name for s in sys_result.scalars().all()}

    # Internal deps (both endpoints in env)
    internal_result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.tenant_id == tenant_id,
            ComponentDependency.from_subsystem_id.in_(env_subsystem_ids),
            ComponentDependency.to_subsystem_id.in_(env_subsystem_ids),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    internal_deps = list(internal_result.scalars().all())

    # Cross-env deps (exactly one endpoint in env)
    cross_result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.tenant_id == tenant_id,
            or_(
                and_(
                    ComponentDependency.from_subsystem_id.in_(env_subsystem_ids),
                    ComponentDependency.to_subsystem_id.notin_(env_subsystem_ids),
                ),
                and_(
                    ComponentDependency.to_subsystem_id.in_(env_subsystem_ids),
                    ComponentDependency.from_subsystem_id.notin_(env_subsystem_ids),
                ),
            ),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    cross_deps = list(cross_result.scalars().all())

    # Collect outside subsystem IDs
    outside_sub_ids: set[int] = set()
    for dep in cross_deps:
        if dep.from_subsystem_id not in env_subsystem_id_set:
            outside_sub_ids.add(dep.from_subsystem_id)
        if dep.to_subsystem_id not in env_subsystem_id_set:
            outside_sub_ids.add(dep.to_subsystem_id)

    outside_subsystems: list[SubSystem] = []
    if outside_sub_ids:
        out_result = await db.execute(
            select(SubSystem).where(
                SubSystem.id.in_(outside_sub_ids),
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )
        outside_subsystems = list(out_result.scalars().all())

    found_outside_ids = {s.id for s in outside_subsystems}
    cross_deps = [
        d for d in cross_deps
        if (d.from_subsystem_id in env_subsystem_id_set or d.from_subsystem_id in found_outside_ids)
        and (d.to_subsystem_id in env_subsystem_id_set or d.to_subsystem_id in found_outside_ids)
    ]

    # Resolve system names for outside systems
    outside_system_ids = {s.system_id for s in outside_subsystems} - set(system_ids)
    if outside_system_ids:
        out_sys_result = await db.execute(
            select(System).where(System.id.in_(outside_system_ids), System.tenant_id == tenant_id)
        )
        for sys in out_sys_result.scalars().all():
            system_names[sys.id] = sys.name

    # Build subsystem nodes
    subsystem_nodes = []
    for row in env_sub_rows:
        sub = row.subsystem
        if sub is None:
            continue
        hosts = []
        for host_row in row.hosts:
            if host_row.deleted_at is not None:
                continue
            comp = host_row.infrastructure_component
            # Defence-in-depth: never surface a host from another tenant even if a
            # malformed junction row points at one (the write path already guards this).
            if comp is None or comp.deleted_at is not None or comp.tenant_id != tenant_id:
                continue
            hosts.append({
                "infrastructure_component_id": comp.id,
                "name": comp.name,
                "component_type": comp.component_type,
                "role": host_row.role,
            })
        subsystem_nodes.append({
            "id": sub.id,
            "name": sub.name,
            "component_type": sub.component_type,
            "technology": sub.technology,
            "system_id": sub.system_id,
            "is_mocked": row.is_mocked,
            "hosts": hosts,
        })

    outside_sub_nodes = [
        {
            "id": sub.id,
            "name": sub.name,
            "component_type": sub.component_type,
            "technology": sub.technology,
            "system_id": sub.system_id,
            "is_mocked": False,
            "hosts": [],
        }
        for sub in outside_subsystems
    ]

    return {
        "environment_id": env_id,
        "subsystems": subsystem_nodes,
        "dependencies": internal_deps,
        "system_names": {str(k): v for k, v in system_names.items()},
        "outside_subsystems": outside_sub_nodes,
        "outside_dependencies": cross_deps,
    }
