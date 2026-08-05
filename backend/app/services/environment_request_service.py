"""Environment requests — CRUD, filtering, authorization and fulfilment.

Mode-dependent validation lives here rather than in the schema so a violation
can name the missing field. The schema cannot express "environment_id is
required when kind='access'" without a validator that produces a worse message.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_request import (
    EnvironmentRequestCreate,
    EnvironmentRequestUpdate,
)
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment import Environment
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.user import User
from app.db.models.user_group import UserGroup, UserGroupMember
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
        article = "An" if kind[:1].lower() in "aeiou" else "A"
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{article} '{kind}' request requires: {', '.join(missing)}",
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


# Fallback only, for a tenant with no environment_request template at all —
# which the seeder makes near-impossible, but a filter that excludes NOTHING
# when the lookup comes back empty would show every finished request in the
# queue.
_FALLBACK_TERMINAL_STATES = frozenset({"fulfilled", "rejected", "cancelled"})


async def terminal_states_for_tenant(db: AsyncSession, tenant_id: int) -> frozenset[str]:
    """The states in which a request needs nobody's attention.

    Derived from the tenant's own templates rather than hardcoded: tenant
    configurability is the whole reason this entity uses lifecycle templates
    instead of a fixed status enum, so a tenant that renames `fulfilled` or
    adds a `withdrawn` terminal must not get a queue that keeps showing
    finished work.

    Where a tenant has several environment_request templates, the union is
    used. A state terminal in one template is therefore excluded everywhere,
    which is the safe direction to be wrong in: the cost is a request briefly
    missing from a queue, not a finished one lingering in it forever.
    """
    definitions = (
        await db.execute(
            select(LifecycleTemplate.definition).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == ENTITY_TYPE,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if not definitions:
        # No environment_request template exists for this tenant at all —
        # the seeder makes this near-impossible, but the lookup genuinely has
        # nothing to say, so fall back to the hardcoded three.
        return _FALLBACK_TERMINAL_STATES
    terminal = {
        state["key"]
        for definition in definitions
        for state in (definition or {}).get("states", [])
        if state.get("is_terminal")
    }
    # Templates were found and read; if none of their states are marked
    # terminal, that is the tenant's actual configuration, not a lookup
    # failure — respecting it (returning empty rather than the fallback) is
    # the whole point of deriving this from the tenant's own templates.
    return frozenset(terminal)

REQUEST_SORTS = {
    "status": EnvironmentRequest.status,
    "kind": EnvironmentRequest.kind,
    "needed_by": EnvironmentRequest.needed_by,
    "created_at": EnvironmentRequest.created_at,
}


def _actionable_clause(tenant_id: int, user_id: int, is_admin: bool):
    """"Requests my team must action."

    Deliberately does NOT fold in the Admin group-bypass. An Admin sees
    new-environment requests plus access requests for teams they are actually
    in; folding the bypass in would return the whole tenant for every Admin,
    making the queue useless for the one user most likely to need it. The
    bypass exists so a transition is never impossible — it is not a claim about
    whose queue a request belongs in.
    """
    member_exists = (
        select(UserGroupMember.id)
        .where(
            UserGroupMember.group_id == Environment.operations_group_id,
            UserGroupMember.user_id == user_id,
            UserGroupMember.tenant_id == tenant_id,
        )
        .correlate(Environment)
        .exists()
    )
    access_clause = and_(
        EnvironmentRequest.kind == "access",
        member_exists,
    )
    if is_admin:
        return or_(access_clause, EnvironmentRequest.kind == "new_environment")
    return access_clause


async def list_requests(
    db: AsyncSession,
    tenant_id: int,
    *,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    status_filter: Optional[str] = None,
    kind: Optional[str] = None,
    environment_id: Optional[int] = None,
    mine_for_user_id: Optional[int] = None,
    actionable_for: Optional[tuple[int, bool]] = None,
) -> tuple[list[EnvironmentRequestView], int]:
    """Requests for a tenant, plus the unwindowed total.

    Every filter is applied in SQL. A filter applied in Python after the query
    would window the page before the filter and return quietly wrong results —
    see docs/pagination.md.
    """
    query = _view_query(tenant_id)
    if status_filter is not None:
        query = query.where(EnvironmentRequest.status == status_filter)
    if kind is not None:
        query = query.where(EnvironmentRequest.kind == kind)
    if environment_id is not None:
        query = query.where(EnvironmentRequest.environment_id == environment_id)
    if mine_for_user_id is not None:
        query = query.where(EnvironmentRequest.requested_by == mine_for_user_id)
    if actionable_for is not None:
        user_id, is_admin = actionable_for
        terminal = await terminal_states_for_tenant(db, tenant_id)
        query = query.where(
            EnvironmentRequest.status.notin_(terminal),
            EnvironmentRequest.requested_by != user_id,
            _actionable_clause(tenant_id, user_id, is_admin),
        )
    query = apply_sort(query, sort).order_by(EnvironmentRequest.id)
    rows, total = await fetch_page_rows(db, query, page)
    return [_to_view(r) for r in rows], total
