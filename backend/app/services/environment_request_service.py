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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_request import (
    EnvironmentRequestCreate,
    EnvironmentRequestUpdate,
)
from app.core.events import publish_event
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows
from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.environment_tier import EnvironmentTier
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.user import User
from app.db.models.user_group import UserGroup, UserGroupMember
from app.services import lifecycle_service
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


async def _is_in_operations_group(
    db: AsyncSession, environment_id: Optional[int], user_id: int, tenant_id: int
) -> bool:
    if environment_id is None:
        return False
    found = (
        await db.execute(
            select(UserGroupMember.id)
            .join(Environment, Environment.operations_group_id == UserGroupMember.group_id)
            .where(
                Environment.id == environment_id,
                Environment.tenant_id == tenant_id,
                UserGroupMember.user_id == user_id,
                UserGroupMember.tenant_id == tenant_id,
            )
        )
    ).first()
    return found is not None


# The states whose decision belongs to the operating team. Moves OUT of the
# initial state — submit, cancel — need only the role gate the template
# already controls: the person requesting access is by definition not in the
# team that operates the environment, so gating their own submission on
# membership makes the primary user journey impossible. Product decision
# 2026-08; reproduced live as a Viewer getting 403 submitting their own draft.
APPROVAL_TARGET_STATES = frozenset({"approved", "rejected", "fulfilled"})


async def _get_template_for_request(
    db: AsyncSession, req: EnvironmentRequest, tenant_id: int
) -> Optional[LifecycleTemplate]:
    """The one tenant-scoped, non-deleted lookup of a request's lifecycle
    template — shared by assert_may_transition and allowed_transitions so
    they can never disagree about which template (or which tenant's copy of
    it) governs a request."""
    return (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.id == req.lifecycle_id,
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def assert_may_transition(
    db: AsyncSession,
    req: EnvironmentRequest,
    to_state: str,
    current_user: User,
    tenant_id: int,
) -> None:
    """The one place in this application that reads group membership for
    authorization, alongside environment_service.assert_may_edit_handover.

        may = role_allows(template, from, to, actor.role)
              AND ( to_state not in APPROVAL_TARGET_STATES
                    OR actor in target_environment.operations_group
                    OR actor.role == 'Admin' )

    The group check is gated on the TARGET state, not applied to every
    transition: it exists to keep the operating team in control of the
    decisions that are theirs (approve / reject / mark fulfilled), not to
    stop a requester submitting or cancelling their own draft — see
    APPROVAL_TARGET_STATES. Admin bypasses the GROUP check but not the ROLE
    check, so a request can never become permanently unactionable because a
    team was emptied — while the lifecycle template still means something.
    """
    tpl = await _get_template_for_request(db, req, tenant_id)
    if tpl is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lifecycle template not found")

    allowed, reason = lifecycle_service.validate_transition(
        tpl.definition, req.status, to_state, current_user.role, {}
    )
    if not allowed:
        # Same role-blocked-vs-invalid-transition split as booking_service:
        # a role the template excludes is a 403 (an authorization matter,
        # even though validate_transition itself doesn't return a status
        # code); an undefined transition or unmet required-field is a 400.
        if reason and ("not allowed" in reason or "role" in reason.lower()):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Your role cannot make this transition"
            )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            reason
            or f"Transition from '{req.status}' to '{to_state}' is not allowed",
        )

    is_admin = current_user.role == "Admin"
    if to_state in APPROVAL_TARGET_STATES and not is_admin:
        in_group = await _is_in_operations_group(
            db, req.environment_id, current_user.id, tenant_id
        )
        if not in_group:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only the operating team for this environment, or an admin, "
                "can action this request",
            )


async def _assert_routable(db: AsyncSession, req: EnvironmentRequest, tenant_id: int) -> None:
    """B3a's promise, honoured at submission.

    A request whose environment has no operating team has nobody to route to.
    Refusing here beats letting it through: a request only an Admin can see
    sits unactioned with nobody knowing why.
    """
    if req.kind != "access" or req.environment_id is None:
        return
    row = (
        await db.execute(
            select(Environment.name, Environment.operations_group_id).where(
                Environment.id == req.environment_id,
                Environment.tenant_id == tenant_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    name, group_id = row
    if group_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{name} has no operations team, so this request cannot be routed. "
            "Ask an admin to assign one.",
        )


async def _fulfil_new_environment(
    db: AsyncSession, req: EnvironmentRequest, tenant_id: int
) -> Environment:
    """Create the environment this request asked for.

    INACTIVE, not ACTIVE: the register must not claim an environment is
    available before anyone has built it. That drift between the register and
    reality is what this product exists to prevent — an admin flips it active
    once the infrastructure exists.

    The governance fields are populated by construction (tier, owner,
    expiry, operations team all come straight from the request), so a
    request-created environment can never appear in `?governance_gap=true`.
    The six handover fields stay null: there is nothing to hand over until it
    is built.
    """
    if req.operations_group_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This request has no operations team assigned. An admin must "
            "choose which team will operate the environment before it can be "
            "fulfilled.",
        )

    # An app-level guard, not merely test convenience for the Postgres-only
    # partial unique index (`uq_environment_tenant_name`, migration
    # `nameuniqguard`): that index is a raw `op.create_index(...)` gated to
    # `if dialect.name != "postgresql": return` and isn't declared on the
    # Environment model, so it's invisible to both test databases (both are
    # built with `Base.metadata.create_all`, never `alembic upgrade head`).
    # This check is what actually makes two live same-named environments
    # impossible everywhere this suite runs; the IntegrityError catch below
    # is the last-resort net for a race this check can't see.
    clash = (
        await db.execute(
            select(Environment.id).where(
                Environment.tenant_id == tenant_id,
                Environment.name == req.proposed_name,
                Environment.deleted_at.is_(None),
            )
        )
    ).first()
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An environment named '{req.proposed_name}' already exists in "
            "this tenant.",
        )

    env = Environment(
        tenant_id=tenant_id,
        name=req.proposed_name,
        description=req.justification,
        tier_id=req.tier_id,
        owner_user_id=req.requested_by,
        expires_at=req.expires_at,
        operations_group_id=req.operations_group_id,
        status=EnvironmentStatus.INACTIVE,
    )
    db.add(env)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Could not create an environment named '{req.proposed_name}' "
            "for this request.",
        ) from e
    return env


async def transition(
    db: AsyncSession,
    request_id: int,
    to_state: str,
    current_user: User,
    tenant_id: int,
) -> EnvironmentRequestView:
    view = await get_request_view(db, request_id, tenant_id)
    req = view.request

    # Authorization before business rules: an unauthorized caller must get a
    # 403, never a 409 that leaks *why* the transition would fail if they
    # were allowed to attempt it (e.g. "this environment has no operations
    # team").
    await assert_may_transition(db, req, to_state, current_user, tenant_id)

    if to_state == "submitted":
        await _assert_routable(db, req, tenant_id)

    created: Optional[Environment] = None
    if to_state == "fulfilled" and req.kind == "new_environment":
        # Before the status write: a failure here must abort the transition
        # too. get_db() wraps the request in one transaction, so raising
        # rolls back the flush above with it.
        created = await _fulfil_new_environment(db, req, tenant_id)

    from_state = req.status
    req.status = to_state
    if created is not None:
        req.created_environment_id = created.id
    await db.flush()

    await publish_event(
        db,
        event_type="EnvironmentRequestTransitioned",
        aggregate_id=req.id,
        aggregate_type="EnvironmentRequest",
        payload={"id": req.id, "from_state": from_state, "to_state": to_state},
        tenant_id=tenant_id,
    )
    return await get_request_view(db, request_id, tenant_id)


async def allowed_transitions(
    db: AsyncSession, request_id: int, current_user: User, tenant_id: int
) -> list[dict]:
    """Transitions this actor may ACTUALLY make — role and group both applied,
    mirroring assert_may_transition's per-transition APPROVAL_TARGET_STATES
    gate exactly.

    The detail page renders these as buttons. Returning a transition
    assert_may_transition would then refuse produces a button that always
    403s — and, since C1, a transition it would *wrongly* refuse (e.g. a
    requester's own submit) must not be hidden either.
    """
    view = await get_request_view(db, request_id, tenant_id)
    req = view.request
    tpl = await _get_template_for_request(db, req, tenant_id)
    if tpl is None:
        return []

    by_role = lifecycle_service.get_allowed_transitions(
        tpl.definition, req.status, current_user.role
    )
    if current_user.role == "Admin":
        return by_role

    gated = [t for t in by_role if t["to_state"] in APPROVAL_TARGET_STATES]
    ungated = [t for t in by_role if t["to_state"] not in APPROVAL_TARGET_STATES]
    if not gated:
        return ungated
    in_group = await _is_in_operations_group(
        db, req.environment_id, current_user.id, tenant_id
    )
    return by_role if in_group else ungated
