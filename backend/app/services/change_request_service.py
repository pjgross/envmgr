"""Change Request service — CRUD, lifecycle transitions, event publishing.

Mirrors the booking_request_service shape where reasonable. Lifecycle mechanics
(transition validation, allowed transitions, field permissions) are delegated
to the generic `app.services.lifecycle_service` — see Phase 2 Step 1.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.change_request import ChangeRequest, ChangeHistory
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.system import SubSystem
from app.db.models.user import User
from app.services import lifecycle_service
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
    """Insert the two default change-request lifecycle templates for a tenant.

    Idempotent: skips any template whose name already exists for
    (tenant_id, entity_type='change_request').
    """
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


async def _validate_subsystem_environment(
    db: AsyncSession, subsystem_id: int, environment_id: int, tenant_id: int
) -> None:
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
    env = (
        await db.execute(
            select(Environment).where(
                Environment.id == environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if env is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "environment_id must refer to an active environment in this tenant",
        )


async def _get_cr(
    db: AsyncSession, cr_id: int, tenant_id: int, include_deleted: bool = False
) -> ChangeRequest:
    stmt = select(ChangeRequest).where(
        ChangeRequest.id == cr_id,
        ChangeRequest.tenant_id == tenant_id,
    )
    if not include_deleted:
        stmt = stmt.where(ChangeRequest.deleted_at.is_(None))
    cr = (await db.execute(stmt)).scalar_one_or_none()
    if cr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change request not found")
    return cr


# ── Public API ──────────────────────────────────────────────────────────────

async def create_change_request(
    db: AsyncSession,
    data: ChangeRequestCreate,
    current_user: User,
    tenant_id: int,
) -> ChangeRequest:
    tpl = await _load_lifecycle(db, data.lifecycle_id, tenant_id)
    await _validate_subsystem_environment(
        db, data.subsystem_id, data.environment_id, tenant_id
    )
    initial_state = await _initial_state(tpl)

    cr = ChangeRequest(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        change_type=data.change_type,
        status=initial_state,
        lifecycle_id=data.lifecycle_id,
        subsystem_id=data.subsystem_id,
        environment_id=data.environment_id,
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

    await publish_event(
        db,
        event_type="ChangeRequestCreated",
        aggregate_id=cr.id,
        aggregate_type="ChangeRequest",
        payload={
            "id": cr.id,
            "title": cr.title,
            "change_type": cr.change_type,
            "environment_id": cr.environment_id,
            "subsystem_id": cr.subsystem_id,
            "status": cr.status,
        },
        tenant_id=tenant_id,
    )
    await db.refresh(cr)
    return cr


async def get_change_request(
    db: AsyncSession, cr_id: int, tenant_id: int
) -> ChangeRequest:
    return await _get_cr(db, cr_id, tenant_id)


async def list_change_requests(
    db: AsyncSession,
    tenant_id: int,
    *,
    environment_id: Optional[int] = None,
    subsystem_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    scheduled_from: Optional[datetime] = None,
    scheduled_to: Optional[datetime] = None,
) -> list[ChangeRequest]:
    stmt = select(ChangeRequest).where(
        ChangeRequest.tenant_id == tenant_id,
        ChangeRequest.deleted_at.is_(None),
    )
    if environment_id is not None:
        stmt = stmt.where(ChangeRequest.environment_id == environment_id)
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
    # Tenant scoping via the parent CR
    await _get_cr(db, cr_id, tenant_id)
    rows = (
        await db.execute(
            select(ChangeHistory)
            .where(ChangeHistory.change_request_id == cr_id)
            .order_by(ChangeHistory.changed_at.asc(), ChangeHistory.id.asc())
        )
    ).scalars()
    return list(rows)


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

    for field, new_value in changed.items():
        old_value = getattr(cr, field)
        if old_value == new_value:
            continue
        setattr(cr, field, new_value)
        db.add(
            ChangeHistory(
                change_request_id=cr.id,
                field_name=field,
                old_value={"value": old_value} if not isinstance(old_value, (datetime,)) else {"value": old_value.isoformat()},
                new_value={"value": new_value} if not isinstance(new_value, (datetime,)) else {"value": new_value.isoformat()},
                changed_by=current_user.id,
                changed_at=now,
            )
        )

    # Re-run outage consistency check after update
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
    await db.refresh(cr)
    return cr


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

    allowed = lifecycle_service.validate_transition(
        tpl.definition, cr.status, to_state, current_user.role
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Transition from '{cr.status}' to '{to_state}' is not allowed for role '{current_user.role}'",
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

    await db.refresh(cr)
    return cr


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
