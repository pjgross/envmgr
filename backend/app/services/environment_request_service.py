"""Environment requests — CRUD, filtering, authorization and fulfilment.

Mode-dependent validation lives here rather than in the schema so a violation
can name the missing field. The schema cannot express "environment_id is
required when kind='access'" without a validator that produces a worse message.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_request import (
    EnvironmentRequestCreate,
    EnvironmentRequestUpdate,
)
from app.db.models.environment import Environment
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.user import User
from app.db.models.user_group import UserGroup
from app.services.environment_request_defaults import ENTITY_TYPE


@dataclass
class EnvironmentRequestView:
    """A request plus the display labels a UI needs without extra round-trips,
    following environment_service.EnvironmentView."""

    request: EnvironmentRequest
    environment_name: Optional[str]
    requester_username: Optional[str]
    tier_name: Optional[str]
    operations_group_name: Optional[str]


def _view_query(tenant_id: int):
    """The one select carrying a request's display labels.

    Every join is tenant-qualified — defence in depth matching
    environment_service._view_query: a malformed row must not surface another
    tenant's name.
    """
    return (
        select(
            EnvironmentRequest,
            Environment.name,
            User.username,
            EnvironmentTier.name,
            UserGroup.name,
        )
        .outerjoin(
            Environment,
            and_(
                Environment.id == EnvironmentRequest.environment_id,
                Environment.tenant_id == tenant_id,
            ),
        )
        .outerjoin(
            User,
            and_(
                User.id == EnvironmentRequest.requested_by,
                User.tenant_id == tenant_id,
            ),
        )
        .outerjoin(
            EnvironmentTier,
            and_(
                EnvironmentTier.id == EnvironmentRequest.tier_id,
                EnvironmentTier.tenant_id == tenant_id,
            ),
        )
        .outerjoin(
            UserGroup,
            and_(
                UserGroup.id == EnvironmentRequest.operations_group_id,
                UserGroup.tenant_id == tenant_id,
            ),
        )
        .where(
            EnvironmentRequest.tenant_id == tenant_id,
            EnvironmentRequest.deleted_at.is_(None),
        )
    )


def _to_view(row) -> EnvironmentRequestView:
    req, env_name, username, tier_name, group_name = row
    return EnvironmentRequestView(
        request=req, environment_name=env_name, requester_username=username,
        tier_name=tier_name, operations_group_name=group_name,
    )


async def get_request_view(
    db: AsyncSession, request_id: int, tenant_id: int
) -> EnvironmentRequestView:
    row = (
        await db.execute(
            _view_query(tenant_id).where(EnvironmentRequest.id == request_id)
        )
    ).first()
    if row is None:
        # 404 rather than 403 — a 403 confirms the row exists elsewhere.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return _to_view(row)


async def _assert_targets_are_ours(
    db: AsyncSession,
    tenant_id: int,
    *,
    environment_id: Optional[int] = None,
    tier_id: Optional[int] = None,
    operations_group_id: Optional[int] = None,
) -> None:
    """Every client-supplied FK is validated against the ACTIVE tenant.

    Under master-admin impersonation current_user.id and active_tenant_id
    belong to different tenants; scoping this to the wrong one 404s a
    legitimate request. This is also the IDOR class a 2026-07-16 audit of this
    repo found four instances of.
    """
    if environment_id is not None:
        found = (await db.execute(select(Environment.id).where(
            Environment.id == environment_id,
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
        ))).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    if tier_id is not None:
        found = (await db.execute(select(EnvironmentTier.id).where(
            EnvironmentTier.id == tier_id,
            EnvironmentTier.tenant_id == tenant_id,
            EnvironmentTier.deleted_at.is_(None),
        ))).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment tier not found")
    if operations_group_id is not None:
        found = (await db.execute(select(UserGroup.id).where(
            UserGroup.id == operations_group_id,
            UserGroup.tenant_id == tenant_id,
            UserGroup.deleted_at.is_(None),
        ))).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User group not found")


def _assert_mode_fields(
    kind: str,
    *,
    environment_id: Optional[int],
    proposed_name: Optional[str],
    tier_id: Optional[int],
    expires_at: Optional[datetime],
) -> None:
    missing: list[str] = []
    if kind == "access":
        if environment_id is None:
            missing.append("environment_id")
    else:
        if not proposed_name:
            missing.append("proposed_name")
        if tier_id is None:
            missing.append("tier_id")
        if expires_at is None:
            missing.append("expires_at")
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"A '{kind}' request requires: {', '.join(missing)}",
        )


async def _default_lifecycle(db: AsyncSession, tenant_id: int) -> LifecycleTemplate:
    tpl = (
        await db.execute(
            select(LifecycleTemplate)
            .where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == ENTITY_TYPE,
                LifecycleTemplate.deleted_at.is_(None),
            )
            .order_by(LifecycleTemplate.is_default.desc(), LifecycleTemplate.id)
        )
    ).scalars().first()
    if tpl is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This tenant has no environment-request lifecycle configured",
        )
    return tpl


async def create_request(
    db: AsyncSession,
    data: EnvironmentRequestCreate,
    requested_by: int,
    tenant_id: int,
) -> EnvironmentRequestView:
    _assert_mode_fields(
        data.kind,
        environment_id=data.environment_id,
        proposed_name=data.proposed_name,
        tier_id=data.tier_id,
        expires_at=data.expires_at,
    )
    await _assert_targets_are_ours(
        db, tenant_id,
        environment_id=data.environment_id, tier_id=data.tier_id,
    )
    tpl = await _default_lifecycle(db, tenant_id)

    req = EnvironmentRequest(
        tenant_id=tenant_id,
        kind=data.kind,
        status="draft",
        lifecycle_id=tpl.id,
        requested_by=requested_by,
        justification=data.justification,
        needed_by=data.needed_by,
        environment_id=data.environment_id if data.kind == "access" else None,
        proposed_name=data.proposed_name if data.kind == "new_environment" else None,
        tier_id=data.tier_id if data.kind == "new_environment" else None,
        expires_at=data.expires_at if data.kind == "new_environment" else None,
        custom_fields=data.custom_fields,
    )
    db.add(req)
    await db.flush()
    return await get_request_view(db, req.id, tenant_id)


async def update_request(
    db: AsyncSession,
    request_id: int,
    data: EnvironmentRequestUpdate,
    current_user: User,
    tenant_id: int,
) -> EnvironmentRequestView:
    view = await get_request_view(db, request_id, tenant_id)
    req = view.request

    if req.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A request can only be edited while it is a draft (this one is '{req.status}')",
        )
    is_admin = current_user.role == "Admin"
    if req.requested_by != current_user.id and not is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the requester or an admin can edit this request",
        )

    fields = data.model_dump(exclude_unset=True)
    await _assert_targets_are_ours(
        db, tenant_id,
        environment_id=fields.get("environment_id"),
        tier_id=fields.get("tier_id"),
        operations_group_id=fields.get("operations_group_id"),
    )
    for key, value in fields.items():
        setattr(req, key, value)

    _assert_mode_fields(
        req.kind,
        environment_id=req.environment_id, proposed_name=req.proposed_name,
        tier_id=req.tier_id, expires_at=req.expires_at,
    )
    await db.flush()
    return await get_request_view(db, request_id, tenant_id)
