from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import EnvironmentSubSystem, EnvironmentSubSystemHost
from app.db.models.infrastructure_component import (
    InfrastructureComponent,
    InfrastructureComponentSource,
    InfrastructureComponentType,
)
from app.api.v1.schemas.infrastructure_component import (
    InfrastructureComponentCreate,
    InfrastructureComponentUpdate,
)
from app.core.events import publish_event
from app.core.pagination import Page, fetch_page


async def list_infrastructure_components(
    db: AsyncSession,
    tenant_id: int,
    component_type: Optional[InfrastructureComponentType] = None,
    provider: Optional[str] = None,
    region: Optional[str] = None,
    source: Optional[InfrastructureComponentSource] = None,
    search: Optional[str] = None,
    page: Optional[Page] = None,
) -> tuple[list[InfrastructureComponent], int]:
    query = select(InfrastructureComponent).where(
        InfrastructureComponent.tenant_id == tenant_id,
        InfrastructureComponent.deleted_at.is_(None),
    )
    if component_type is not None:
        query = query.where(InfrastructureComponent.component_type == component_type)
    if provider is not None:
        query = query.where(InfrastructureComponent.provider == provider)
    if region is not None:
        query = query.where(InfrastructureComponent.region == region)
    if source is not None:
        query = query.where(InfrastructureComponent.source == source)
    if search:
        query = query.where(InfrastructureComponent.name.ilike(f"%{search}%"))
    query = query.order_by(InfrastructureComponent.name, InfrastructureComponent.id)
    return await fetch_page(db, query, page)


async def get_infrastructure_component(
    db: AsyncSession, component_id: int, tenant_id: int
) -> InfrastructureComponent:
    result = await db.execute(
        select(InfrastructureComponent).where(
            InfrastructureComponent.id == component_id,
            InfrastructureComponent.tenant_id == tenant_id,
            InfrastructureComponent.deleted_at.is_(None),
        )
    )
    component = result.scalar_one_or_none()
    if component is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Infrastructure component not found",
        )
    return component


async def create_infrastructure_component(
    db: AsyncSession, data: InfrastructureComponentCreate, tenant_id: int
) -> InfrastructureComponent:
    existing = await db.execute(
        select(InfrastructureComponent).where(
            InfrastructureComponent.name == data.name,
            InfrastructureComponent.tenant_id == tenant_id,
            InfrastructureComponent.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An infrastructure component with this name already exists in this tenant",
        )
    component = InfrastructureComponent(
        name=data.name,
        description=data.description,
        component_type=data.component_type,
        provider=data.provider,
        region=data.region,
        location=data.location,
        source=data.source,
        external_id=data.external_id,
        custom_fields=data.custom_fields,
        tags=data.tags,
        tenant_id=tenant_id,
    )
    db.add(component)
    await db.flush()
    await db.refresh(component)
    await publish_event(
        db,
        event_type="InfrastructureComponentCreated",
        aggregate_id=component.id,
        aggregate_type="InfrastructureComponent",
        payload={
            "id": component.id,
            "name": component.name,
            "component_type": component.component_type.value,
            "provider": component.provider,
            "region": component.region,
            "tenant_id": component.tenant_id,
        },
        tenant_id=component.tenant_id,
    )
    return component


async def update_infrastructure_component(
    db: AsyncSession,
    component_id: int,
    data: InfrastructureComponentUpdate,
    tenant_id: int,
) -> InfrastructureComponent:
    component = await get_infrastructure_component(db, component_id, tenant_id)

    if data.name is not None and data.name != component.name:
        existing = await db.execute(
            select(InfrastructureComponent).where(
                InfrastructureComponent.name == data.name,
                InfrastructureComponent.tenant_id == tenant_id,
                InfrastructureComponent.id != component_id,
                InfrastructureComponent.deleted_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An infrastructure component with this name already exists in this tenant",
            )
        component.name = data.name

    for field in (
        "description",
        "component_type",
        "provider",
        "region",
        "location",
        "source",
        "external_id",
        "custom_fields",
        "tags",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(component, field, value)

    await db.flush()
    await db.refresh(component)
    await publish_event(
        db,
        event_type="InfrastructureComponentUpdated",
        aggregate_id=component.id,
        aggregate_type="InfrastructureComponent",
        payload={"id": component.id, "name": component.name, "tenant_id": component.tenant_id},
        tenant_id=component.tenant_id,
    )
    return component


async def delete_infrastructure_component(
    db: AsyncSession, component_id: int, tenant_id: int
) -> None:
    component = await get_infrastructure_component(db, component_id, tenant_id)

    in_use = await db.execute(
        select(EnvironmentSubSystemHost.id).where(
            EnvironmentSubSystemHost.infrastructure_component_id == component_id,
            EnvironmentSubSystemHost.tenant_id == tenant_id,
            EnvironmentSubSystemHost.deleted_at.is_(None),
        ).limit(1)
    )
    if in_use.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete: this component is attached to one or more environment subsystems",
        )

    component.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="InfrastructureComponentDeleted",
        aggregate_id=component.id,
        aggregate_type="InfrastructureComponent",
        payload={"id": component.id, "name": component.name, "tenant_id": component.tenant_id},
        tenant_id=component.tenant_id,
    )


async def environments_affected_by_hosts(
    db: AsyncSession, tenant_id: int, host_ids: list[int]
) -> list[int]:
    """Return distinct environment IDs whose subsystems are deployed on any of the given hosts.

    Used by CR outage preview and the CR service.
    """
    if not host_ids:
        return []
    result = await db.execute(
        select(EnvironmentSubSystem.environment_id)
        .join(
            EnvironmentSubSystemHost,
            EnvironmentSubSystemHost.environment_subsystem_id == EnvironmentSubSystem.id,
        )
        .where(
            EnvironmentSubSystemHost.infrastructure_component_id.in_(host_ids),
            EnvironmentSubSystemHost.tenant_id == tenant_id,
            EnvironmentSubSystemHost.deleted_at.is_(None),
        )
        .distinct()
    )
    return [row[0] for row in result.all()]


async def host_impact(
    db: AsyncSession, tenant_id: int, host_ids: list[int]
) -> dict:
    """Shape used by the CR form impact panel.

    Returns one entry per environment whose subsystems are deployed on any
    of `host_ids`, with the matching subsystems and the specific hosts
    (+ role) they run on. The frontend renders this readonly so the
    environment manager sees impact without leaving the change form.

    Response:
        {
          "host_ids": [1, 2],
          "environments": [
            {
              "environment_id": 3,
              "environment_name": "uat",
              "subsystems": [
                {
                  "subsystem_id": 5,
                  "subsystem_name": "api",
                  "system_name": "Billing",
                  "is_mocked": false,
                  "matches": [{"host_id": 1, "host_name": "macmini", "role": "primary"}]
                }
              ]
            }
          ]
        }
    """
    from sqlalchemy.orm import aliased

    if not host_ids:
        return {"host_ids": [], "environments": []}

    from app.db.models.environment import Environment
    from app.db.models.system import SubSystem, System

    esh = EnvironmentSubSystemHost
    es = EnvironmentSubSystem
    ic = InfrastructureComponent
    ss = aliased(SubSystem)
    sy = aliased(System)
    env = aliased(Environment)

    stmt = (
        select(
            env.id.label("environment_id"),
            env.name.label("environment_name"),
            ss.id.label("subsystem_id"),
            ss.name.label("subsystem_name"),
            sy.name.label("system_name"),
            es.is_mocked.label("is_mocked"),
            ic.id.label("host_id"),
            ic.name.label("host_name"),
            esh.role.label("role"),
        )
        .join(es, es.id == esh.environment_subsystem_id)
        .join(env, env.id == es.environment_id)
        .join(ss, ss.id == es.subsystem_id)
        .join(sy, sy.id == ss.system_id)
        .join(ic, ic.id == esh.infrastructure_component_id)
        .where(
            esh.infrastructure_component_id.in_(host_ids),
            esh.tenant_id == tenant_id,
            esh.deleted_at.is_(None),
            env.deleted_at.is_(None),
        )
        .order_by(env.name, ss.name, ic.name)
    )
    rows = (await db.execute(stmt)).all()

    envs: dict[int, dict] = {}
    for row in rows:
        env_entry = envs.setdefault(
            row.environment_id,
            {
                "environment_id": row.environment_id,
                "environment_name": row.environment_name,
                "subsystems": {},
            },
        )
        sub_entry = env_entry["subsystems"].setdefault(
            row.subsystem_id,
            {
                "subsystem_id": row.subsystem_id,
                "subsystem_name": row.subsystem_name,
                "system_name": row.system_name,
                "is_mocked": row.is_mocked,
                "matches": [],
            },
        )
        sub_entry["matches"].append(
            {
                "host_id": row.host_id,
                "host_name": row.host_name,
                "role": row.role,
            }
        )

    return {
        "host_ids": sorted(set(host_ids)),
        "environments": [
            {
                "environment_id": e["environment_id"],
                "environment_name": e["environment_name"],
                "subsystems": list(e["subsystems"].values()),
            }
            for e in envs.values()
        ],
    }
