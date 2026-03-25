from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import selectinload

from app.db.models.system import SubSystem, System
from app.db.models.dependency import ComponentDependency


async def get_system_topology(
    system_id: int,
    tenant_id: int,
    db: AsyncSession,
) -> tuple[
    list[SubSystem],
    list[ComponentDependency],
    list[SubSystem],
    list[ComponentDependency],
    dict[int, str],
]:
    """Return current subsystems, internal deps, external subsystems, cross-system deps,
    and a system_id→name map for the topology diagram."""

    # Current system's subsystems
    result = await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    subsystems = result.scalars().all()
    subsystem_ids = [s.id for s in subsystems]
    subsystem_id_set = set(subsystem_ids)

    # Always resolve current system name
    sys_result = await db.execute(
        select(System).where(System.id == system_id, System.tenant_id == tenant_id)
    )
    current_system = sys_result.scalar_one_or_none()
    system_names: dict[int, str] = {system_id: current_system.name} if current_system else {}

    if not subsystem_ids:
        return list(subsystems), [], [], [], system_names

    # Internal dependencies (both ends in current system)
    result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.tenant_id == tenant_id,
            ComponentDependency.from_subsystem_id.in_(subsystem_ids),
            ComponentDependency.to_subsystem_id.in_(subsystem_ids),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    internal_deps = result.scalars().all()

    # Cross-system dependencies (exactly one end is in current system)
    result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.tenant_id == tenant_id,
            or_(
                and_(
                    ComponentDependency.from_subsystem_id.in_(subsystem_ids),
                    ComponentDependency.to_subsystem_id.notin_(subsystem_ids),
                ),
                and_(
                    ComponentDependency.to_subsystem_id.in_(subsystem_ids),
                    ComponentDependency.from_subsystem_id.notin_(subsystem_ids),
                ),
            ),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    external_deps = result.scalars().all()

    # Collect external subsystem IDs referenced by cross-system deps
    external_subsystem_ids = set()
    for dep in external_deps:
        if dep.from_subsystem_id not in subsystem_id_set:
            external_subsystem_ids.add(dep.from_subsystem_id)
        if dep.to_subsystem_id not in subsystem_id_set:
            external_subsystem_ids.add(dep.to_subsystem_id)

    # Fetch external subsystems (non-deleted only)
    external_subsystems: list[SubSystem] = []
    if external_subsystem_ids:
        result = await db.execute(
            select(SubSystem).where(
                SubSystem.id.in_(external_subsystem_ids),
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )
        external_subsystems = list(result.scalars().all())

    # Filter cross-system deps to those where both endpoints are available
    found_ext_ids = {s.id for s in external_subsystems}
    external_deps = [
        d for d in external_deps
        if (d.from_subsystem_id in subsystem_id_set or d.from_subsystem_id in found_ext_ids)
        and (d.to_subsystem_id in subsystem_id_set or d.to_subsystem_id in found_ext_ids)
    ]

    # Resolve system names for all external systems
    external_system_ids = {s.system_id for s in external_subsystems} - {system_id}
    if external_system_ids:
        result = await db.execute(
            select(System).where(
                System.id.in_(external_system_ids),
                System.tenant_id == tenant_id,
            )
        )
        for sys in result.scalars().all():
            system_names[sys.id] = sys.name

    return (
        list(subsystems),
        list(internal_deps),
        external_subsystems,
        external_deps,
        system_names,
    )
