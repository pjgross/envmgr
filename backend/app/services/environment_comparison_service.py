"""Assemble a symmetric diff of two environments.

Everything is loaded per side and compared in Python over small in-memory
maps rather than as one large join: the result is bounded by the two
environments' own subsystems, and the per-dimension rules (see
`environment_comparison`) are far clearer as expressions than as SQL.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import (
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
    EnvironmentSystem,
)
from app.db.models.infrastructure_component import InfrastructureComponent
from app.db.models.system import SubSystem, System
from app.services.environment_comparison import difference_kinds, host_shape
from app.services.environment_service import get_environment
from app.services.version_service import list_versions

_KINDS = ("presence", "mocked", "version", "host_shape")


async def _systems(db: AsyncSession, env_id: int, tenant_id: int) -> dict[int, str]:
    rows = (await db.execute(
        select(System.id, System.name)
        .join(EnvironmentSystem, EnvironmentSystem.system_id == System.id)
        .where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.tenant_id == tenant_id,
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )).all()
    return {sid: name for sid, name in rows}


async def _side(db: AsyncSession, env_id: int, tenant_id: int) -> dict[int, dict]:
    """Everything comparable about one environment, keyed by subsystem id."""
    rows = (await db.execute(
        select(
            EnvironmentSubSystem.id,
            SubSystem.id,
            SubSystem.name,
            System.id,
            System.name,
            EnvironmentSubSystem.is_mocked,
            EnvironmentSubSystem.mock_notes,
        )
        .join(SubSystem, SubSystem.id == EnvironmentSubSystem.subsystem_id)
        .join(System, System.id == SubSystem.system_id)
        .where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )).all()

    env_sub_ids = [r[0] for r in rows]
    hosts: dict[int, list[tuple[str, Optional[str]]]] = {i: [] for i in env_sub_ids}
    if env_sub_ids:
        host_rows = (await db.execute(
            select(
                EnvironmentSubSystemHost.environment_subsystem_id,
                InfrastructureComponent.component_type,
                EnvironmentSubSystemHost.role,
            )
            .join(
                InfrastructureComponent,
                InfrastructureComponent.id
                == EnvironmentSubSystemHost.infrastructure_component_id,
            )
            .where(
                EnvironmentSubSystemHost.environment_subsystem_id.in_(env_sub_ids),
                EnvironmentSubSystemHost.tenant_id == tenant_id,
                EnvironmentSubSystemHost.deleted_at.is_(None),
                InfrastructureComponent.tenant_id == tenant_id,
                InfrastructureComponent.deleted_at.is_(None),
            )
        )).all()
        for env_sub_id, component_type, role in host_rows:
            value = getattr(component_type, "value", component_type)
            hosts[env_sub_id].append((value, role))

    # Reuse the endpoint's own current-version semantics rather than
    # reimplementing the dedup: list_versions already resolves "latest per
    # subsystem" with a ROW_NUMBER() window under current_only.
    # This re-validates the environment (compare_environments already did),
    # which is accepted here in exchange for not duplicating that dedup query.
    version_rows, _total = await list_versions(db, env_id, tenant_id, current_only=True)
    versions = {v.subsystem_id: v.version_label for v in version_rows}

    return {
        sub_id: {
            "subsystem_id": sub_id,
            "name": sub_name,
            "system_id": system_id,
            "system_name": system_name,
            "is_mocked": is_mocked,
            "mock_notes": mock_notes,
            "version": versions.get(sub_id),
            "host_shape": host_shape(hosts[env_sub_id]),
        }
        for (env_sub_id, sub_id, sub_name, system_id, system_name,
             is_mocked, mock_notes) in rows
    }


def _presence(in_left: bool, in_right: bool) -> str:
    if in_left and in_right:
        return "both"
    return "left_only" if in_left else "right_only"


async def compare_environments(
    db: AsyncSession, left_id: int, right_id: int, tenant_id: int
) -> dict:
    left_env = await get_environment(db, left_id, tenant_id)
    right_env = await get_environment(db, right_id, tenant_id)

    left_systems = await _systems(db, left_id, tenant_id)
    right_systems = await _systems(db, right_id, tenant_id)
    systems = [
        {
            "system_id": sid,
            "name": left_systems[sid] if sid in left_systems else right_systems[sid],
            "presence": _presence(sid in left_systems, sid in right_systems),
        }
        for sid in sorted(set(left_systems) | set(right_systems))
    ]
    systems.sort(key=lambda s: (s["name"].lower(), s["system_id"]))

    left_side = await _side(db, left_id, tenant_id)
    right_side = await _side(db, right_id, tenant_id)

    subsystems = []
    for sub_id in set(left_side) | set(right_side):
        left = left_side.get(sub_id)
        right = right_side.get(sub_id)
        meta = left or right
        presence = _presence(left is not None, right is not None)
        subsystems.append({
            "subsystem_id": sub_id,
            "name": meta["name"],
            "system_id": meta["system_id"],
            "system_name": meta["system_name"],
            "presence": presence,
            "left": _payload(left),
            "right": _payload(right),
            "differences": difference_kinds(presence, left, right),
        })

    # Differing first, then by system and subsystem name, with the id as a
    # unique tiebreaker so the order is identical on both engines.
    subsystems.sort(
        key=lambda r: (
            not r["differences"],
            r["system_name"].lower(),
            r["name"].lower(),
            r["subsystem_id"],
        )
    )

    return {
        "left": {"id": left_env.id, "name": left_env.name, "status": left_env.status},
        "right": {"id": right_env.id, "name": right_env.name, "status": right_env.status},
        "systems": systems,
        "subsystems": subsystems,
        "summary": {
            "compared": len(subsystems),
            "differing": sum(1 for r in subsystems if r["differences"]),
            # Built from the same arrays the rows carry, so a row and the
            # summary cannot disagree.
            "by_kind": {
                kind: sum(1 for r in subsystems if kind in r["differences"])
                for kind in _KINDS
            },
        },
    }


def _payload(side: Optional[dict]) -> Optional[dict]:
    if side is None:
        return None
    return {
        "is_mocked": side["is_mocked"],
        "mock_notes": side["mock_notes"],
        "version": side["version"],
        "host_shape": side["host_shape"],
    }
