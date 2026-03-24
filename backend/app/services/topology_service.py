from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.system import SubSystem
from app.db.models.dependency import ComponentDependency


async def get_system_topology(
    system_id: int,
    tenant_id: int,
    db: AsyncSession,
) -> tuple[list[SubSystem], list[ComponentDependency]]:
    """Return subsystems and the component dependencies between them for a given system."""
    # Get non-deleted subsystems belonging to this system
    result = await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    subsystems = result.scalars().all()
    subsystem_ids = [s.id for s in subsystems]

    if not subsystem_ids:
        return list(subsystems), []

    # Get component dependencies where BOTH endpoints are subsystems of this system
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
        )
    )
    dependencies = result.scalars().all()

    return list(subsystems), list(dependencies)
