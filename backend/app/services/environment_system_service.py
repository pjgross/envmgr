from fastapi import HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models.environment import (
    EnvironmentSystem,
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
)
from app.db.models.infrastructure_component import InfrastructureComponent
from app.db.models.system import System, SubSystem
from app.db.models.dependency import SystemDependency
from app.db.models.version import EnvironmentSubSystemVersion
from app.services.environment_service import get_environment
from app.services import component_type_service
from app.api.v1.schemas.environment import (
    EnvironmentSystemCreate,
    EnvironmentSystemUpdate,
    EnvironmentSystemsResponse,
    EnvironmentSystemResponse,
    SystemSummary,
    EnvironmentSubsystemResponse,
    EnvironmentSubsystemUpdate,
    VersionSummary,
)
from app.api.v1.schemas.infrastructure_component import (
    EnvironmentSubSystemHostResponse,
    HostAttachment,
    InfrastructureComponentSummary,
)


async def list_systems_in_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> EnvironmentSystemsResponse:
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSystem)
        .where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.tenant_id == tenant_id,
        )
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys_rows = list(result.scalars().all())
    assigned_system_ids = {row.system_id for row in env_sys_rows}

    # Compute missing systems: system-dep targets not in environment
    missing_systems: list[SystemSummary] = []
    if assigned_system_ids:
        deps_result = await db.execute(
            select(SystemDependency)
            .where(
                SystemDependency.from_system_id.in_(assigned_system_ids),
                SystemDependency.tenant_id == tenant_id,
            )
            .options(selectinload(SystemDependency.to_system))
        )
        seen_missing: set[int] = set()
        for dep in deps_result.scalars().all():
            to_id = dep.to_system_id
            if to_id not in assigned_system_ids and to_id not in seen_missing:
                seen_missing.add(to_id)
                if dep.to_system:
                    missing_systems.append(
                        SystemSummary(
                            id=dep.to_system.id,
                            name=dep.to_system.name,
                            description=dep.to_system.description,
                        )
                    )

    systems = [
        EnvironmentSystemResponse(
            id=row.id,
            environment_id=row.environment_id,
            system_id=row.system_id,
            system=row.system,
        )
        for row in env_sys_rows
    ]
    return EnvironmentSystemsResponse(systems=systems, missing_systems=missing_systems)


async def add_system_to_environment(
    db: AsyncSession,
    env_id: int,
    data: EnvironmentSystemCreate,
    tenant_id: int,
) -> EnvironmentSystem:
    await get_environment(db, env_id, tenant_id)

    sys_result = await db.execute(
        select(System).where(
            System.id == data.system_id,
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    if sys_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")

    existing = await db.execute(
        select(EnvironmentSystem).where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.system_id == data.system_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System is already assigned to this environment",
        )

    env_sys = EnvironmentSystem(
        environment_id=env_id,
        system_id=data.system_id,
        tenant_id=tenant_id,
    )
    db.add(env_sys)
    await db.flush()

    # Auto-create EnvironmentSubSystem rows for each subsystem
    subs_result = await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == data.system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    subsystems = list(subs_result.scalars().all())
    if subsystems:
        stmt = pg_insert(EnvironmentSubSystem).values([
            {
                "environment_id": env_id,
                "subsystem_id": sub.id,
                "tenant_id": tenant_id,
                "is_mocked": False,
            }
            for sub in subsystems
        ]).on_conflict_do_nothing(index_elements=["environment_id", "subsystem_id"])
        await db.execute(stmt)

    await db.refresh(env_sys, ["system"])
    return env_sys


async def _get_env_system(
    db: AsyncSession, env_id: int, system_id: int, tenant_id: int
) -> EnvironmentSystem:
    await get_environment(db, env_id, tenant_id)
    result = await db.execute(
        select(EnvironmentSystem)
        .where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.system_id == system_id,
            EnvironmentSystem.tenant_id == tenant_id,
        )
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys = result.scalar_one_or_none()
    if env_sys is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System not found in this environment",
        )
    return env_sys


async def update_system_in_environment(
    db: AsyncSession,
    env_id: int,
    system_id: int,
    data: EnvironmentSystemUpdate,
    tenant_id: int,
) -> EnvironmentSystem:
    """No-op update kept for route compatibility. Returns current row."""
    return await _get_env_system(db, env_id, system_id, tenant_id)


async def remove_system_from_environment(
    db: AsyncSession, env_id: int, system_id: int, tenant_id: int
) -> None:
    env_sys = await _get_env_system(db, env_id, system_id, tenant_id)

    # Clean up EnvironmentSubSystem rows for this system's subsystems
    subs_result = await db.execute(
        select(SubSystem.id).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
        )
    )
    subsystem_ids = [row[0] for row in subs_result.all()]
    if subsystem_ids:
        await db.execute(
            delete(EnvironmentSubSystem).where(
                EnvironmentSubSystem.environment_id == env_id,
                EnvironmentSubSystem.subsystem_id.in_(subsystem_ids),
            )
        )

    await db.delete(env_sys)
    await db.flush()


# ---------------------------------------------------------------------------
# EnvironmentSubSystem operations
# ---------------------------------------------------------------------------


async def get_environment_subsystems(
    db: AsyncSession, env_id: int, tenant_id: int
) -> list[EnvironmentSubsystemResponse]:
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSubSystem)
        .where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
        .options(
            selectinload(EnvironmentSubSystem.subsystem),
            selectinload(EnvironmentSubSystem.component_type_definition),
        )
    )
    rows = list(result.scalars().all())

    # Collect subsystem IDs to batch-load system names and latest versions
    subsystem_ids = [row.subsystem_id for row in rows]
    if not subsystem_ids:
        return []

    # Batch load system names via the subsystem→system relationship
    subsystem_result = await db.execute(
        select(SubSystem)
        .where(SubSystem.id.in_(subsystem_ids))
        .options(selectinload(SubSystem.system))
    )
    subsystem_map = {sub.id: sub for sub in subsystem_result.scalars().all()}

    # Batch load latest version per subsystem
    from sqlalchemy import func
    latest_version_subq = (
        select(
            EnvironmentSubSystemVersion.subsystem_id,
            func.max(EnvironmentSubSystemVersion.installed_at).label("max_installed"),
        )
        .where(
            EnvironmentSubSystemVersion.environment_id == env_id,
            EnvironmentSubSystemVersion.subsystem_id.in_(subsystem_ids),
        )
        .group_by(EnvironmentSubSystemVersion.subsystem_id)
        .subquery()
    )
    versions_result = await db.execute(
        select(EnvironmentSubSystemVersion).join(
            latest_version_subq,
            (EnvironmentSubSystemVersion.subsystem_id == latest_version_subq.c.subsystem_id)
            & (EnvironmentSubSystemVersion.installed_at == latest_version_subq.c.max_installed),
        ).where(EnvironmentSubSystemVersion.environment_id == env_id)
    )
    version_map: dict[int, EnvironmentSubSystemVersion] = {
        v.subsystem_id: v for v in versions_result.scalars().all()
    }

    out = []
    for row in rows:
        sub = subsystem_map.get(row.subsystem_id)
        if sub is None:
            continue
        ver = version_map.get(row.subsystem_id)
        out.append(
            EnvironmentSubsystemResponse(
                id=row.id,
                environment_id=row.environment_id,
                subsystem_id=row.subsystem_id,
                subsystem_name=sub.name,
                component_type=sub.component_type,
                component_type_definition_id=row.component_type_definition_id,
                component_type_definition_name=(
                    row.component_type_definition.name
                    if row.component_type_definition else None
                ),
                technology=sub.technology,
                system_id=sub.system_id,
                system_name=sub.system.name if sub.system else f"System#{sub.system_id}",
                is_mocked=row.is_mocked,
                mock_notes=row.mock_notes,
                custom_fields=row.custom_fields,
                latest_version=VersionSummary(
                    build_identifier=ver.build_identifier,
                    version_label=ver.version_label,
                    installed_at=ver.installed_at,
                ) if ver else None,
            )
        )
    return out


async def update_environment_subsystem(
    db: AsyncSession,
    env_id: int,
    subsystem_id: int,
    data: EnvironmentSubsystemUpdate,
    tenant_id: int,
) -> EnvironmentSubsystemResponse:
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.subsystem_id == subsystem_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subsystem not found in this environment",
        )

    if data.is_mocked is not None:
        row.is_mocked = data.is_mocked
    if data.mock_notes is not None:
        row.mock_notes = data.mock_notes

    # Handle component type definition assignment
    if "component_type_definition_id" in data.model_fields_set:
        if data.component_type_definition_id is None:
            # Clear the type and custom fields
            row.component_type_definition_id = None
            row.custom_fields = None
        else:
            await component_type_service.get_definition(
                db, data.component_type_definition_id, tenant_id
            )
            row.component_type_definition_id = data.component_type_definition_id

    if data.custom_fields is not None:
        if row.component_type_definition_id:
            await component_type_service.validate_fields_against_type(
                db, tenant_id, row.component_type_definition_id, data.custom_fields
            )
        row.custom_fields = data.custom_fields

    await db.flush()

    # Return full response (re-use get function)
    subs = await get_environment_subsystems(db, env_id, tenant_id)
    match = next((s for s in subs if s.subsystem_id == subsystem_id), None)
    if match is None:
        raise HTTPException(status_code=500, detail="Failed to reload subsystem")
    return match


# ---------------------------------------------------------------------------
# EnvironmentSubSystemHost operations — multi-host deployment targeting
# ---------------------------------------------------------------------------


async def _get_env_subsystem(
    db: AsyncSession, env_id: int, subsystem_id: int, tenant_id: int
) -> EnvironmentSubSystem:
    await get_environment(db, env_id, tenant_id)
    result = await db.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.subsystem_id == subsystem_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subsystem not found in this environment",
        )
    return row


def _host_to_response(host_row: EnvironmentSubSystemHost) -> EnvironmentSubSystemHostResponse:
    comp = host_row.infrastructure_component
    return EnvironmentSubSystemHostResponse(
        id=host_row.id,
        environment_subsystem_id=host_row.environment_subsystem_id,
        infrastructure_component_id=host_row.infrastructure_component_id,
        infrastructure_component=InfrastructureComponentSummary(
            id=comp.id,
            name=comp.name,
            component_type=comp.component_type,
            provider=comp.provider,
            region=comp.region,
        ),
        role=host_row.role,
    )


async def list_env_subsystem_hosts(
    db: AsyncSession, env_id: int, subsystem_id: int, tenant_id: int
) -> list[EnvironmentSubSystemHostResponse]:
    env_sub = await _get_env_subsystem(db, env_id, subsystem_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSubSystemHost)
        .where(
            EnvironmentSubSystemHost.environment_subsystem_id == env_sub.id,
            EnvironmentSubSystemHost.tenant_id == tenant_id,
            EnvironmentSubSystemHost.deleted_at.is_(None),
        )
        .options(selectinload(EnvironmentSubSystemHost.infrastructure_component))
        .order_by(EnvironmentSubSystemHost.id)
    )
    return [_host_to_response(row) for row in result.scalars().all()]


async def set_env_subsystem_hosts(
    db: AsyncSession,
    env_id: int,
    subsystem_id: int,
    attachments: list[HostAttachment],
    tenant_id: int,
) -> list[EnvironmentSubSystemHostResponse]:
    """Replace the full host attachment set for one env-subsystem row.

    Idempotent: repeating the same payload yields the same state. Hosts no
    longer present are hard-deleted (the junction is intrinsically ephemeral
    deployment state — no soft-delete value). Roles are updated in place.
    """
    env_sub = await _get_env_subsystem(db, env_id, subsystem_id, tenant_id)

    # Deduplicate incoming attachments (last-write-wins for role conflicts)
    desired: dict[int, str | None] = {}
    for a in attachments:
        desired[a.infrastructure_component_id] = a.role

    if desired:
        host_result = await db.execute(
            select(InfrastructureComponent.id).where(
                InfrastructureComponent.id.in_(list(desired.keys())),
                InfrastructureComponent.tenant_id == tenant_id,
                InfrastructureComponent.deleted_at.is_(None),
            )
        )
        found_ids = {row[0] for row in host_result.all()}
        missing = set(desired) - found_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Infrastructure component(s) not found: {sorted(missing)}",
            )

    current_result = await db.execute(
        select(EnvironmentSubSystemHost).where(
            EnvironmentSubSystemHost.environment_subsystem_id == env_sub.id,
            EnvironmentSubSystemHost.tenant_id == tenant_id,
        )
    )
    current_rows = list(current_result.scalars().all())
    current_by_host = {row.infrastructure_component_id: row for row in current_rows}

    # Delete rows no longer desired
    for host_id, row in current_by_host.items():
        if host_id not in desired:
            await db.delete(row)

    # Upsert desired
    for host_id, role in desired.items():
        existing = current_by_host.get(host_id)
        if existing is None:
            db.add(
                EnvironmentSubSystemHost(
                    environment_subsystem_id=env_sub.id,
                    infrastructure_component_id=host_id,
                    tenant_id=tenant_id,
                    role=role,
                )
            )
        else:
            existing.role = role
            existing.deleted_at = None

    await db.flush()
    return await list_env_subsystem_hosts(db, env_id, subsystem_id, tenant_id)
