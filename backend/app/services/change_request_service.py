"""Change Request service — CRUD, lifecycle transitions, event publishing.

Multi-target aware (Phase 3): a CR can target any combination of environments
and infrastructure components (hosts). When a host is targeted, affected
environments are derived through the `environment_subsystem_host` junction and
exposed to consumers as `derived_environment_ids`.

Lifecycle mechanics (transition validation, allowed transitions, field
permissions) are delegated to the generic `app.services.lifecycle_service`.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import publish_event
from app.db.models.change_request import (
    ChangeHistory,
    ChangeRequest,
    ChangeRequestEnvironment,
    ChangeRequestHost,
)
from app.db.models.environment import (
    Environment,
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
)
from app.db.models.infrastructure_component import InfrastructureComponent
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.system import SubSystem
from app.db.models.user import User
from app.services import lifecycle_service, infrastructure_component_service
from app.api.v1.schemas.change_request import (
    ChangeRequestCreate,
    ChangeRequestUpdate,
)


ENTITY_TYPE = "change_request"


# ── Default lifecycle seeds (used by tenant_service on tenant creation) ──────

DEFAULT_LIFECYCLE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "Simple Approval",
        "is_default": True,
        "description": "Standard change-request flow with an approval gate.",
        "definition": {
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
                {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "submitted", "label": "Submit",
                 "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
                {"from_state": "submitted", "to_state": "approved", "label": "Approve",
                 "allowed_roles": ["Admin", "Release Manager"]},
                {"from_state": "submitted", "to_state": "rejected", "label": "Reject",
                 "allowed_roles": ["Admin", "Release Manager"]},
                {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision",
                 "allowed_roles": ["Admin", "Release Manager"]},
                {"from_state": "approved", "to_state": "completed", "label": "Mark Completed",
                 "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
            ],
            "field_permissions": {},
        },
    },
    {
        "name": "Emergency",
        "is_default": False,
        "description": "Minimal flow for urgent changes — no approval gate.",
        "definition": {
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "in_progress", "label": "In Progress", "is_initial": False, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "in_progress", "label": "Start",
                 "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
                {"from_state": "in_progress", "to_state": "completed", "label": "Mark Completed",
                 "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
            ],
            "field_permissions": {},
        },
    },
]


async def seed_default_lifecycles(db: AsyncSession, tenant_id: int) -> None:
    existing_names = set(
        (
            await db.execute(
                select(LifecycleTemplate.name).where(
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.entity_type == ENTITY_TYPE,
                    LifecycleTemplate.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    for spec in DEFAULT_LIFECYCLE_DEFINITIONS:
        if spec["name"] in existing_names:
            continue
        tpl = LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type=ENTITY_TYPE,
            name=spec["name"],
            description=spec["description"],
            is_default=spec["is_default"],
            definition=spec["definition"],
        )
        db.add(tpl)
    await db.flush()


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _load_lifecycle(
    db: AsyncSession, lifecycle_id: int, tenant_id: int
) -> LifecycleTemplate:
    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.id == lifecycle_id,
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == ENTITY_TYPE,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "lifecycle_id must refer to an active change-request lifecycle template",
        )
    return tpl


async def _initial_state(tpl: LifecycleTemplate) -> str:
    for s in tpl.definition.get("states", []):
        if s.get("is_initial"):
            return s["key"]
    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Lifecycle template has no initial state",
    )


async def _validate_environments(
    db: AsyncSession, environment_ids: list[int], tenant_id: int
) -> None:
    if not environment_ids:
        return
    result = await db.execute(
        select(Environment.id).where(
            Environment.id.in_(environment_ids),
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        )
    )
    found = {row[0] for row in result.all()}
    missing = set(environment_ids) - found
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"environment_ids contain invalid entries: {sorted(missing)}",
        )


async def _validate_hosts(
    db: AsyncSession, host_ids: list[int], tenant_id: int
) -> None:
    if not host_ids:
        return
    result = await db.execute(
        select(InfrastructureComponent.id).where(
            InfrastructureComponent.id.in_(host_ids),
            InfrastructureComponent.tenant_id == tenant_id,
            InfrastructureComponent.deleted_at.is_(None),
        )
    )
    found = {row[0] for row in result.all()}
    missing = set(host_ids) - found
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"host_ids contain invalid entries: {sorted(missing)}",
        )


async def _validate_subsystem_scope(
    db: AsyncSession,
    subsystem_id: Optional[int],
    environment_ids: list[int],
    tenant_id: int,
) -> None:
    if subsystem_id is None:
        return
    sub = (
        await db.execute(
            select(SubSystem).where(
                SubSystem.id == subsystem_id,
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "subsystem_id must refer to an active subsystem in this tenant",
        )


def _cr_load_options() -> list:
    return [
        selectinload(ChangeRequest.environments).selectinload(ChangeRequestEnvironment.environment),
        selectinload(ChangeRequest.hosts).selectinload(ChangeRequestHost.infrastructure_component),
    ]


async def _get_cr(
    db: AsyncSession, cr_id: int, tenant_id: int, include_deleted: bool = False
) -> ChangeRequest:
    stmt = (
        select(ChangeRequest)
        .options(*_cr_load_options())
        .where(
            ChangeRequest.id == cr_id,
            ChangeRequest.tenant_id == tenant_id,
        )
    )
    if not include_deleted:
        stmt = stmt.where(ChangeRequest.deleted_at.is_(None))
    cr = (await db.execute(stmt)).scalar_one_or_none()
    if cr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found")
    return cr


def _env_ids(cr: ChangeRequest) -> list[int]:
    return sorted({row.environment_id for row in cr.environments})


def _host_ids(cr: ChangeRequest) -> list[int]:
    return sorted({row.infrastructure_component_id for row in cr.hosts})


async def build_cr_response_dict(
    db: AsyncSession, cr: ChangeRequest, tenant_id: int
) -> dict:
    """Shape an ORM row into the ChangeRequestResponse payload, resolving
    junction collections and deriving host-sourced environments.
    """
    environment_ids = _env_ids(cr)
    host_ids = _host_ids(cr)

    derived_env_ids = sorted(
        set(
            await infrastructure_component_service.environments_affected_by_hosts(
                db, tenant_id, host_ids
            )
        )
        - set(environment_ids)
    )

    derived_environments_payload: list[dict] = []
    if derived_env_ids:
        name_rows = await db.execute(
            select(Environment.id, Environment.name).where(
                Environment.id.in_(derived_env_ids),
                Environment.tenant_id == tenant_id,
            )
        )
        name_map = {row[0]: row[1] for row in name_rows.all()}
        derived_environments_payload = [
            {"id": i, "name": name_map.get(i, f"Environment#{i}")}
            for i in derived_env_ids
        ]

    environments_payload = sorted(
        (
            {"id": row.environment.id, "name": row.environment.name}
            for row in cr.environments
            if row.environment is not None
        ),
        key=lambda e: e["id"],
    )
    hosts_payload = sorted(
        (
            {
                "id": row.infrastructure_component.id,
                "name": row.infrastructure_component.name,
                "component_type": row.infrastructure_component.component_type,
                "provider": row.infrastructure_component.provider,
                "region": row.infrastructure_component.region,
            }
            for row in cr.hosts
            if row.infrastructure_component is not None
        ),
        key=lambda h: h["id"],
    )

    return {
        "id": cr.id,
        "tenant_id": cr.tenant_id,
        "title": cr.title,
        "description": cr.description,
        "change_type": cr.change_type,
        "status": cr.status,
        "lifecycle_id": cr.lifecycle_id,
        "subsystem_id": cr.subsystem_id,
        "environment_ids": environment_ids,
        "host_ids": host_ids,
        "environments": environments_payload,
        "hosts": hosts_payload,
        "derived_environment_ids": derived_env_ids,
        "derived_environments": derived_environments_payload,
        "release_id": cr.release_id,
        "has_outage": cr.has_outage,
        "outage_start": cr.outage_start,
        "outage_end": cr.outage_end,
        "scheduled_start": cr.scheduled_start,
        "scheduled_end": cr.scheduled_end,
        "custom_fields": cr.custom_fields,
        "raised_by": cr.raised_by,
        "created_at": cr.created_at,
        "updated_at": cr.updated_at,
    }


# ── Public API ──────────────────────────────────────────────────────────────

async def create_change_request(
    db: AsyncSession,
    data: ChangeRequestCreate,
    current_user: User,
    tenant_id: int,
) -> ChangeRequest:
    environment_ids = sorted(set(data.environment_ids or []))
    host_ids = sorted(set(data.host_ids or []))

    if not environment_ids and not host_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "At least one environment_ids or host_ids entry is required",
        )

    tpl = await _load_lifecycle(db, data.lifecycle_id, tenant_id)
    await _validate_environments(db, environment_ids, tenant_id)
    await _validate_hosts(db, host_ids, tenant_id)
    await _validate_subsystem_scope(db, data.subsystem_id, environment_ids, tenant_id)
    initial_state = await _initial_state(tpl)

    cr = ChangeRequest(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        change_type=data.change_type,
        status=initial_state,
        lifecycle_id=data.lifecycle_id,
        subsystem_id=data.subsystem_id,
        release_id=data.release_id,
        has_outage=data.has_outage,
        outage_start=data.outage_start,
        outage_end=data.outage_end,
        scheduled_start=data.scheduled_start,
        scheduled_end=data.scheduled_end,
        custom_fields=data.custom_fields,
        raised_by=current_user.id,
    )
    db.add(cr)
    await db.flush()

    for env_id in environment_ids:
        db.add(
            ChangeRequestEnvironment(
                change_request_id=cr.id,
                environment_id=env_id,
                tenant_id=tenant_id,
            )
        )
    for host_id in host_ids:
        db.add(
            ChangeRequestHost(
                change_request_id=cr.id,
                infrastructure_component_id=host_id,
                tenant_id=tenant_id,
            )
        )

    db.add(
        ChangeHistory(
            change_request_id=cr.id,
            from_state=None,
            to_state=initial_state,
            changed_by=current_user.id,
            changed_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()

    derived_env_ids = sorted(
        set(
            await infrastructure_component_service.environments_affected_by_hosts(
                db, tenant_id, host_ids
            )
        )
        - set(environment_ids)
    )

    await publish_event(
        db,
        event_type="ChangeRequestCreated",
        aggregate_id=cr.id,
        aggregate_type="ChangeRequest",
        payload={
            "id": cr.id,
            "title": cr.title,
            "change_type": cr.change_type,
            "environment_ids": environment_ids,
            "host_ids": host_ids,
            "derived_environment_ids": derived_env_ids,
            "subsystem_id": cr.subsystem_id,
            "status": cr.status,
        },
        tenant_id=tenant_id,
    )
    return await _get_cr(db, cr.id, tenant_id)


async def get_change_request(
    db: AsyncSession, cr_id: int, tenant_id: int
) -> ChangeRequest:
    return await _get_cr(db, cr_id, tenant_id)


async def list_change_requests(
    db: AsyncSession,
    tenant_id: int,
    *,
    environment_id: Optional[int] = None,
    host_id: Optional[int] = None,
    subsystem_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    scheduled_from: Optional[datetime] = None,
    scheduled_to: Optional[datetime] = None,
) -> list[ChangeRequest]:
    stmt = (
        select(ChangeRequest)
        .options(*_cr_load_options())
        .where(
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
        )
    )
    if environment_id is not None:
        stmt = stmt.where(
            exists().where(
                (ChangeRequestEnvironment.change_request_id == ChangeRequest.id)
                & (ChangeRequestEnvironment.environment_id == environment_id)
            )
        )
    if host_id is not None:
        stmt = stmt.where(
            exists().where(
                (ChangeRequestHost.change_request_id == ChangeRequest.id)
                & (ChangeRequestHost.infrastructure_component_id == host_id)
            )
        )
    if subsystem_id is not None:
        stmt = stmt.where(ChangeRequest.subsystem_id == subsystem_id)
    if status_filter is not None:
        stmt = stmt.where(ChangeRequest.status == status_filter)
    if scheduled_from is not None:
        stmt = stmt.where(ChangeRequest.scheduled_end >= scheduled_from)
    if scheduled_to is not None:
        stmt = stmt.where(ChangeRequest.scheduled_start <= scheduled_to)
    stmt = stmt.order_by(ChangeRequest.scheduled_start.desc())
    return list((await db.execute(stmt)).scalars().all())


async def list_history(
    db: AsyncSession, cr_id: int, tenant_id: int
) -> list[ChangeHistory]:
    await _get_cr(db, cr_id, tenant_id)
    rows = (
        await db.execute(
            select(ChangeHistory)
            .where(ChangeHistory.change_request_id == cr_id)
            .order_by(ChangeHistory.changed_at.asc(), ChangeHistory.id.asc())
        )
    ).scalars()
    return list(rows)


async def _diff_target_lists(
    db: AsyncSession,
    cr: ChangeRequest,
    *,
    desired_env_ids: Optional[list[int]],
    desired_host_ids: Optional[list[int]],
    tenant_id: int,
    current_user: User,
) -> None:
    """Apply env / host junction diffs. Writes ChangeHistory rows per direction."""
    now = datetime.now(timezone.utc)

    if desired_env_ids is not None:
        desired_env_ids = sorted(set(desired_env_ids))
        current_env_ids = _env_ids(cr)
        if desired_env_ids != current_env_ids:
            await _validate_environments(db, desired_env_ids, tenant_id)
            cr.environments = [
                row for row in cr.environments if row.environment_id in desired_env_ids
            ]
            for env_id in set(desired_env_ids) - set(current_env_ids):
                cr.environments.append(
                    ChangeRequestEnvironment(
                        change_request_id=cr.id,
                        environment_id=env_id,
                        tenant_id=tenant_id,
                    )
                )
            db.add(
                ChangeHistory(
                    change_request_id=cr.id,
                    field_name="environments",
                    old_value={"ids": current_env_ids},
                    new_value={"ids": desired_env_ids},
                    changed_by=current_user.id,
                    changed_at=now,
                )
            )

    if desired_host_ids is not None:
        desired_host_ids = sorted(set(desired_host_ids))
        current_host_ids = _host_ids(cr)
        if desired_host_ids != current_host_ids:
            await _validate_hosts(db, desired_host_ids, tenant_id)
            cr.hosts = [
                row for row in cr.hosts if row.infrastructure_component_id in desired_host_ids
            ]
            for host_id in set(desired_host_ids) - set(current_host_ids):
                cr.hosts.append(
                    ChangeRequestHost(
                        change_request_id=cr.id,
                        infrastructure_component_id=host_id,
                        tenant_id=tenant_id,
                    )
                )
            db.add(
                ChangeHistory(
                    change_request_id=cr.id,
                    field_name="hosts",
                    old_value={"ids": current_host_ids},
                    new_value={"ids": desired_host_ids},
                    changed_by=current_user.id,
                    changed_at=now,
                )
            )


async def update_change_request(
    db: AsyncSession,
    cr_id: int,
    data: ChangeRequestUpdate,
    current_user: User,
    tenant_id: int,
) -> ChangeRequest:
    cr = await _get_cr(db, cr_id, tenant_id)
    changed = data.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)

    desired_env_ids = changed.pop("environment_ids", None)
    desired_host_ids = changed.pop("host_ids", None)

    scalar_fields = {
        "title",
        "description",
        "change_type",
        "subsystem_id",
        "release_id",
        "has_outage",
        "outage_start",
        "outage_end",
        "scheduled_start",
        "scheduled_end",
        "custom_fields",
    }
    for field, new_value in changed.items():
        if field not in scalar_fields:
            continue
        old_value = getattr(cr, field)
        if old_value == new_value:
            continue
        setattr(cr, field, new_value)
        db.add(
            ChangeHistory(
                change_request_id=cr.id,
                field_name=field,
                old_value={"value": old_value.isoformat() if isinstance(old_value, datetime) else old_value},
                new_value={"value": new_value.isoformat() if isinstance(new_value, datetime) else new_value},
                changed_by=current_user.id,
                changed_at=now,
            )
        )

    await _diff_target_lists(
        db,
        cr,
        desired_env_ids=desired_env_ids,
        desired_host_ids=desired_host_ids,
        tenant_id=tenant_id,
        current_user=current_user,
    )

    effective_env_ids = (
        sorted(set(desired_env_ids)) if desired_env_ids is not None else _env_ids(cr)
    )
    effective_host_ids = (
        sorted(set(desired_host_ids)) if desired_host_ids is not None else _host_ids(cr)
    )
    if not effective_env_ids and not effective_host_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A change request must target at least one environment or host",
        )
    await _validate_subsystem_scope(
        db, cr.subsystem_id, effective_env_ids, tenant_id
    )

    if cr.has_outage and (cr.outage_start is None or cr.outage_end is None):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "outage_start and outage_end must both be set when has_outage is true",
        )
    if cr.has_outage and cr.outage_end <= cr.outage_start:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "outage_end must be after outage_start",
        )
    if cr.scheduled_end <= cr.scheduled_start:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "scheduled_end must be after scheduled_start",
        )

    await db.flush()
    return await _get_cr(db, cr.id, tenant_id)


async def transition_status(
    db: AsyncSession,
    cr_id: int,
    to_state: str,
    current_user: User,
    tenant_id: int,
    notes: Optional[str] = None,
) -> ChangeRequest:
    cr = await _get_cr(db, cr_id, tenant_id)
    tpl = await _load_lifecycle(db, cr.lifecycle_id, tenant_id)

    record_values = {
        "title": cr.title or "",
        "description": cr.description or "",
        "change_type": cr.change_type or "",
        "scheduled_start": cr.scheduled_start,
        "scheduled_end": cr.scheduled_end,
        "has_outage": cr.has_outage,
        "outage_start": cr.outage_start,
        "outage_end": cr.outage_end,
        "release_id": cr.release_id,
        "custom_fields": cr.custom_fields or {},
    }
    allowed, reason = lifecycle_service.validate_transition(
        tpl.definition, cr.status, to_state, current_user.role, record_values
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            reason or f"Transition from '{cr.status}' to '{to_state}' is not allowed for role '{current_user.role}'",
        )

    from_state = cr.status
    cr.status = to_state
    db.add(
        ChangeHistory(
            change_request_id=cr.id,
            from_state=from_state,
            to_state=to_state,
            changed_by=current_user.id,
            changed_at=datetime.now(timezone.utc),
            notes=notes,
        )
    )
    await db.flush()

    await publish_event(
        db,
        event_type="ChangeRequestStateTransitioned",
        aggregate_id=cr.id,
        aggregate_type="ChangeRequest",
        payload={
            "id": cr.id,
            "from_state": from_state,
            "to_state": to_state,
        },
        tenant_id=tenant_id,
    )

    terminal = any(
        s.get("is_terminal") and s.get("key") == to_state
        for s in tpl.definition.get("states", [])
    )
    if terminal:
        await publish_event(
            db,
            event_type="ChangeRequestCompleted",
            aggregate_id=cr.id,
            aggregate_type="ChangeRequest",
            payload={"id": cr.id, "final_state": to_state},
            tenant_id=tenant_id,
        )

    return await _get_cr(db, cr.id, tenant_id)


async def get_allowed_transitions(
    db: AsyncSession,
    cr_id: int,
    current_user: User,
    tenant_id: int,
) -> list[dict]:
    cr = await _get_cr(db, cr_id, tenant_id)
    tpl = await _load_lifecycle(db, cr.lifecycle_id, tenant_id)
    return lifecycle_service.get_allowed_transitions(
        tpl.definition, cr.status, current_user.role
    )


async def soft_delete_change_request(
    db: AsyncSession, cr_id: int, tenant_id: int
) -> None:
    cr = await _get_cr(db, cr_id, tenant_id)
    cr.deleted_at = datetime.now(timezone.utc)
    await db.flush()


# ── Outage × booking conflict preview ───────────────────────────────────────

async def _booking_conflicts_for_env(
    db: AsyncSession,
    env_id: int,
    tenant_id: int,
    outage_start: datetime,
    outage_end: datetime,
    exclude_change_request_id: Optional[int] = None,
) -> list[dict]:
    from app.db.models.booking import Booking

    stmt = (
        select(Booking, Environment.name)
        .join(Environment, Environment.id == Booking.environment_id)
        .options(selectinload(Booking.booking_request))
        .where(
            Booking.environment_id == env_id,
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            Booking.status != "rejected",
            Booking.end_date > outage_start,
            Booking.start_date < outage_end,
        )
        .order_by(Booking.start_date.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": b.id,
            "environment_id": b.environment_id,
            "environment_name": env_name,
            "project_name": b.booking_request.project_name,
            "start_date": b.start_date,
            "end_date": b.end_date,
            "status": b.status,
        }
        for b, env_name in rows
    ]


async def preview_outage_conflicts(
    db: AsyncSession,
    *,
    environment_ids: list[int],
    host_ids: list[int],
    outage_start: datetime,
    outage_end: datetime,
    tenant_id: int,
    exclude_change_request_id: Optional[int] = None,
) -> dict:
    """Return booking conflicts grouped by environment for the proposed outage.

    Effective envs = explicit environment_ids ∪ envs derived from host_ids
    via the `environment_subsystem_host` junction. The derived-only set is
    echoed back so the UI can explain why additional envs appear.
    """
    explicit_env_ids = sorted(set(environment_ids))
    host_ids = sorted(set(host_ids))

    derived_env_ids = sorted(
        set(
            await infrastructure_component_service.environments_affected_by_hosts(
                db, tenant_id, host_ids
            )
        )
    )
    derived_only = sorted(set(derived_env_ids) - set(explicit_env_ids))
    effective_env_ids = sorted(set(explicit_env_ids) | set(derived_env_ids))

    env_name_map: dict[int, str] = {}
    if effective_env_ids:
        env_rows = await db.execute(
            select(Environment.id, Environment.name).where(
                Environment.id.in_(effective_env_ids),
                Environment.tenant_id == tenant_id,
            )
        )
        env_name_map = {row[0]: row[1] for row in env_rows.all()}

    per_env: list[dict] = []
    for env_id in effective_env_ids:
        conflicts = await _booking_conflicts_for_env(
            db,
            env_id,
            tenant_id,
            outage_start,
            outage_end,
            exclude_change_request_id=exclude_change_request_id,
        )
        per_env.append(
            {
                "environment_id": env_id,
                "environment_name": env_name_map.get(env_id, f"Environment#{env_id}"),
                "conflicts": conflicts,
            }
        )
    return {
        "environments": per_env,
        "derived_environment_ids": derived_only,
        "derived_environments": [
            {"id": i, "name": env_name_map.get(i, f"Environment#{i}")}
            for i in derived_only
        ],
    }


# ── Unified environment schedule ────────────────────────────────────────────

async def get_environment_schedule(
    db: AsyncSession,
    env_id: int,
    tenant_id: int,
    start_date: datetime,
    end_date: datetime,
) -> dict:
    """Return bookings + change requests overlapping `[start_date, end_date]`
    for `env_id`.

    Change requests include rows where:
      - env_id is in the CR's `change_request_environment` junction, OR
      - any of the CR's hosts are attached to a subsystem in this env via
        `environment_subsystem_host`.

    `deployments` is reserved for Phase 4 and always `[]` today.
    """
    from app.db.models.booking import Booking

    env = (
        await db.execute(
            select(Environment).where(
                Environment.id == env_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    bookings_stmt = (
        select(Booking)
        .options(selectinload(Booking.booking_request))
        .where(
            Booking.environment_id == env_id,
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            Booking.end_date > start_date,
            Booking.start_date < end_date,
        )
        .order_by(Booking.start_date.asc())
    )
    bookings = list((await db.execute(bookings_stmt)).scalars().all())

    env_junction = (
        select(ChangeRequestEnvironment.change_request_id)
        .where(ChangeRequestEnvironment.environment_id == env_id)
    )
    host_junction = (
        select(ChangeRequestHost.change_request_id)
        .join(
            EnvironmentSubSystemHost,
            EnvironmentSubSystemHost.infrastructure_component_id
            == ChangeRequestHost.infrastructure_component_id,
        )
        .join(
            EnvironmentSubSystem,
            EnvironmentSubSystem.id == EnvironmentSubSystemHost.environment_subsystem_id,
        )
        .where(EnvironmentSubSystem.environment_id == env_id)
    )

    cr_stmt = (
        select(ChangeRequest)
        .options(*_cr_load_options())
        .where(
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
            ChangeRequest.scheduled_end > start_date,
            ChangeRequest.scheduled_start < end_date,
            or_(
                ChangeRequest.id.in_(env_junction),
                ChangeRequest.id.in_(host_junction),
            ),
        )
        .order_by(ChangeRequest.scheduled_start.asc())
    )
    change_requests = list((await db.execute(cr_stmt)).scalars().all())

    return {
        "environment_id": env_id,
        "start_date": start_date,
        "end_date": end_date,
        "bookings": [
            {
                "id": b.id,
                "environment_id": b.environment_id,
                "project_name": b.booking_request.project_name,
                "start_date": b.start_date,
                "end_date": b.end_date,
                "status": b.status,
            }
            for b in bookings
        ],
        "change_requests": [
            {
                "id": cr.id,
                "environment_id": env_id,
                "environment_ids": _env_ids(cr),
                "host_ids": _host_ids(cr),
                "subsystem_id": cr.subsystem_id,
                "title": cr.title,
                "change_type": cr.change_type,
                "status": cr.status,
                "scheduled_start": cr.scheduled_start,
                "scheduled_end": cr.scheduled_end,
                "has_outage": cr.has_outage,
                "outage_start": cr.outage_start,
                "outage_end": cr.outage_end,
            }
            for cr in change_requests
        ],
        "deployments": [],
    }
