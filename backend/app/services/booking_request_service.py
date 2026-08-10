from typing import Any, Optional
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import publish_event
from app.core.pagination import Page, fetch_page
from app.core.protection_levels import PROTECTION_SOFT
from app.core.security import Role
from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest
from app.db.models.booking_lifecycle import BookingType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.environment import Environment
from app.db.models.user import User
from app.services import conflict_service, environment_group_service, project_service


def _may_set_protection(user: User) -> bool:
    """Admin, Release Manager, or a master admin acting in this tenant.

    Master admins are included for the reason contention_service._is_admin
    gives: the two places that forgot showed a master admin a control that
    403'd on click.
    """
    return (
        user.role in (Role.ADMIN, Role.RELEASE_MANAGER)
        or bool(user.is_master_admin)
    )


def assert_may_set_protection(
    user: User, *, submitted: Optional[str], current: str
) -> None:
    """Refuse a CHANGE of protection level by someone without the role.

    `current` is the value that would apply if the caller said nothing — the
    booking type's default on create, the stored value on update.

    THE UNCHANGED-VALUE CARVE-OUT IS LOAD-BEARING, NOT TIDY. The form shows a
    non-admin their level read-only and submits the whole form including it,
    so a bare role check breaks the primary create journey for every
    Developer and Test Manager. It is the same call B2's name rule made: the
    permission guards a CHANGE, not a MENTION.
    """
    if submitted is None or submitted == current:
        return
    if _may_set_protection(user):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only an Admin or Release Manager may change a booking's protection level",
    )


async def protection_levels_for(
    db: AsyncSession, booking_request_ids: set[int], tenant_id: int
) -> dict[int, str]:
    """Batch id -> protection_level for a set of BookingRequest ids.

    The EnvBookingSummary counterpart to project_service.get_project_names /
    environment_group_service.get_group_names: a construction site that reads
    a booking belonging to a DIFFERENT booking_request than the one already in
    hand (a conflict, a preview, a newly-added environment) has no ORM object
    to read protection_level off directly and must batch-resolve it here,
    tenant-scoped like those two.
    """
    if not booking_request_ids:
        return {}
    rows = (await db.execute(
        select(BookingRequest.id, BookingRequest.protection_level).where(
            BookingRequest.id.in_(booking_request_ids),
            BookingRequest.tenant_id == tenant_id,
        )
    )).all()
    return {rid: level for rid, level in rows}


async def _load_initial_state(db: AsyncSession, booking_type_id: int, tenant_id: int) -> str:
    bt = (await db.execute(
        select(BookingType).where(
            BookingType.id == booking_type_id,
            BookingType.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if bt is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown booking_type_id")
    tpl = (await db.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.id == bt.lifecycle_template_id
        )
    )).scalar_one()
    for s in tpl.definition.get("states", []):
        if s.get("is_initial"):
            return s["key"]
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lifecycle has no initial state")


async def create_request(
    db: AsyncSession,
    data: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> tuple[BookingRequest, dict[int, list[Booking]]]:
    env_ids: list[int] = data.get("environment_ids") or []
    group_ids: list[int] = data.get("environment_group_ids") or []

    if len(env_ids) != len(set(env_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "environment_ids must be unique"
        )
    if len(group_ids) != len(set(group_ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "environment_group_ids must be unique"
        )

    # (environment_id, environment_group_id | None), in request order.
    # Hand-picked first so a clash names the GROUP as the newcomer, which is
    # the more useful half of the message.
    pairs: list[tuple[int, Optional[int]]] = [(e, None) for e in env_ids]
    # environment_id -> the human label of whatever put it here
    origin: dict[int, str] = {e: "the environments you picked" for e in env_ids}

    for group_id in group_ids:
        group = await environment_group_service.get_group(db, group_id, tenant_id)
        # Single definition of "live member", shared with the group detail
        # page's count and member list (environment_group_service.
        # live_member_ids) — see its docstring for why this must not drift
        # from _member_query/_member_count_clause.
        members = await environment_group_service.live_member_ids(db, group_id, tenant_id)

        if not members:
            # Refused by name. Without this the caller gets either a silently
            # partial request or the generic "at least one environment",
            # neither of which says WHICH group was empty.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Environment group '{group.name}' has no environments",
            )

        for env_id in members:
            if env_id in origin:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{origin[env_id]} and environment group '{group.name}' both "
                    f"contain the same environment; an environment can appear "
                    f"only once on a request",
                )
            origin[env_id] = f"environment group '{group.name}'"
            pairs.append((env_id, group_id))

    if not pairs:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "At least one environment_id or environment_group_id is required",
        )

    all_env_ids = [e for e, _ in pairs]
    envs = (await db.execute(
        select(Environment).where(
            Environment.id.in_(all_env_ids),
            Environment.tenant_id == tenant_id,
        )
    )).scalars().all()
    if len(envs) != len(all_env_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "One or more environment_ids not found"
        )

    initial_state = await _load_initial_state(db, data["booking_type_id"], tenant_id)

    # A second read of the same row _load_initial_state already fetched — left
    # as its own query rather than contorting that helper's signature to hand
    # back the row too, per the task brief: one extra indexed lookup per
    # create is not worth bending an existing helper out of shape.
    booking_type = (await db.execute(
        select(BookingType).where(
            BookingType.id == data["booking_type_id"],
            BookingType.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    inherited_protection = (
        booking_type.default_protection_level
        if booking_type is not None
        else PROTECTION_SOFT
    )
    submitted_protection = data.get("protection_level")
    assert_may_set_protection(
        current_user, submitted=submitted_protection, current=inherited_protection
    )
    protection_level = (
        submitted_protection if submitted_protection is not None else inherited_protection
    )

    project_id = data.get("project_id")
    if project_id is not None:
        # Scoped to the ACTIVE tenant: under master-admin impersonation
        # current_user.id and active_tenant_id belong to different tenants, and
        # scoping to the wrong one 404s a legitimate request.
        await project_service.get_project(db, project_id, tenant_id)

    req = BookingRequest(
        tenant_id=tenant_id,
        project_name=data["project_name"],
        project_id=project_id,
        booking_type_id=data["booking_type_id"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        notes=data.get("notes"),
        context_tag=ContextTag(data.get("context_tag", "none")),
        exclusive_use_requested=data.get("exclusive_use_requested", False),
        protection_level=protection_level,
        custom_fields=data.get("custom_fields"),
        booked_by=current_user.id,
        delegate_user_ids=data.get("delegate_user_ids"),
    )
    db.add(req)
    await db.flush()

    children: list[Booking] = []
    for env_id, group_id in pairs:
        child = Booking(
            tenant_id=tenant_id,
            booking_request_id=req.id,
            environment_id=env_id,
            start_date=data["start_date"],
            end_date=data["end_date"],
            status=initial_state,
            environment_group_id=group_id,
        )
        db.add(child)
        children.append(child)
    await db.flush()

    detected: dict[int, list[conflict_service.ConflictingBooking]] = {}
    for c in children:
        others, _ = await conflict_service.list_conflicts(db, c.id, tenant_id)
        if others:
            detected[c.id] = others

    await publish_event(
        db,
        event_type="BookingRequestCreated",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "child_ids": [c.id for c in children]},
        tenant_id=tenant_id,
    )
    # Eagerly load the bookings relationship so callers (and tests) can access
    # req.bookings without triggering async lazy-load outside a greenlet.
    await db.refresh(req, ["bookings"])
    return req, detected


async def list_booking_requests(
    db: AsyncSession,
    tenant_id: int,
    page: Optional[Page] = None,
    project_id: Optional[int] = None,
) -> tuple[list[BookingRequest], int]:
    """Tenant's booking requests, newest first, with child bookings eagerly loaded.

    The eager load replaces a per-row `db.refresh`, which was one round trip per
    request row.

    `project_id`, when given, filters in SQL — the endpoint is bounded, so a
    Python-side filter would window the page before filtering and quietly
    return the wrong rows with a total that describes the unfiltered set.
    """
    query = (
        select(BookingRequest)
        .options(selectinload(BookingRequest.bookings))
        .where(
            BookingRequest.tenant_id == tenant_id,
            BookingRequest.deleted_at.is_(None),
        )
    )
    if project_id is not None:
        query = query.where(BookingRequest.project_id == project_id)
    query = query.order_by(BookingRequest.created_at.desc(), BookingRequest.id)
    return await fetch_page(db, query, page)


async def preview_conflicts(
    db: AsyncSession,
    *,
    environment_ids: list[int],
    start_date: datetime,
    end_date: datetime,
    tenant_id: int,
) -> dict[int, list[Booking]]:
    """Return a dict keyed by environment_id listing existing bookings that would overlap.
    No database mutation."""
    from sqlalchemy import not_
    results: dict[int, list[Booking]] = {}
    for env_id in environment_ids:
        stmt = (
            select(Booking)
            .where(
                Booking.tenant_id == tenant_id,
                Booking.environment_id == env_id,
                Booking.deleted_at.is_(None),
                not_(Booking.status.in_(conflict_service.TERMINAL_STATES)),
                Booking.start_date < end_date,
                Booking.end_date > start_date,
            )
            .order_by(Booking.start_date)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if rows:
            results[env_id] = list(rows)
    return results


async def _get_request(db: AsyncSession, request_id: int, tenant_id: int) -> BookingRequest:
    req = (await db.execute(
        select(BookingRequest).where(
            BookingRequest.id == request_id, BookingRequest.tenant_id == tenant_id
        )
    )).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


async def add_environment(
    db: AsyncSession,
    *,
    request_id: int,
    environment_id: int,
    start_date: datetime | None,
    end_date: datetime | None,
    current_user: User,
    tenant_id: int,
) -> Booking:
    req = await _get_request(db, request_id, tenant_id)

    env = (await db.execute(
        select(Environment).where(Environment.id == environment_id, Environment.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")

    # Reject if env already has a non-deleted child in this request
    existing = (await db.execute(
        select(Booking).where(
            Booking.booking_request_id == req.id,
            Booking.environment_id == environment_id,
            Booking.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Environment already in request")

    initial_state = await _load_initial_state(db, req.booking_type_id, tenant_id)

    child = Booking(
        tenant_id=tenant_id,
        booking_request_id=req.id,
        environment_id=environment_id,
        start_date=start_date or req.start_date,
        end_date=end_date or req.end_date,
        status=initial_state,
    )
    db.add(child)
    await db.flush()

    await publish_event(
        db,
        event_type="BookingEnvironmentAdded",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "booking_id": child.id, "environment_id": environment_id},
        tenant_id=tenant_id,
    )
    return child


async def remove_environment(
    db: AsyncSession,
    *,
    request_id: int,
    booking_id: int,
    current_user: User,
    tenant_id: int,
) -> None:
    req = await _get_request(db, request_id, tenant_id)
    child = (await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.booking_request_id == req.id,
            Booking.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    if child is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment booking not found in request")

    child.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="BookingEnvironmentRemoved",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "booking_id": child.id},
        tenant_id=tenant_id,
    )


# Fields editable at the request level — must match the spec's PATCH endpoint
STANDARD_REQUEST_FIELDS = {
    "project_name",
    "project_id",
    "booking_type_id",
    "start_date",
    "end_date",
    "notes",
    "context_tag",
    "exclusive_use_requested",
    "delegate_user_ids",
}


async def update_standard_fields(
    db: AsyncSession,
    *,
    request_id: int,
    values: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> BookingRequest:
    req = await _get_request(db, request_id, tenant_id)
    unknown = set(values) - STANDARD_REQUEST_FIELDS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown fields: {unknown}")

    if (
        "project_id" in values
        and values["project_id"] is not None
        and values["project_id"] != req.project_id
    ):
        # Scoped to the ACTIVE tenant — see the identical comment in
        # create_request for why. Resubmitting the CURRENT value must not
        # re-validate it — a project can be archived after being assigned,
        # and a full-form PATCH still round-trips the existing project_id.
        # Same exemption as project_service.update_project gives
        # team_group_id and environment_service gives operations_group_id:
        # accept an archived project when it equals the stored value, reject
        # it as a new assignment.
        await project_service.get_project(db, values["project_id"], tenant_id)

    # TODO permission gating using lifecycle field_permissions —
    # follow the same check used in booking_service.update_standard_fields today.
    # For now we allow the request owner to edit any standard field; sharpen in Task 16 once
    # the API wires permission checks.

    for k, v in values.items():
        if k == "context_tag" and v is not None:
            setattr(req, k, ContextTag(v))
        else:
            setattr(req, k, v)

    # Cascade start_date/end_date overrides to child Bookings so per-env dates stay in sync.
    if "start_date" in values or "end_date" in values:
        children = (await db.execute(
            select(Booking).where(
                Booking.booking_request_id == req.id, Booking.deleted_at.is_(None)
            )
        )).scalars().all()
        for child in children:
            if "start_date" in values:
                child.start_date = values["start_date"]
            if "end_date" in values:
                child.end_date = values["end_date"]
    await db.flush()

    await publish_event(
        db,
        event_type="BookingRequestUpdated",
        aggregate_id=req.id,
        aggregate_type="BookingRequest",
        payload={"request_id": req.id, "fields": list(values.keys())},
        tenant_id=tenant_id,
    )

    # Eagerly load the bookings relationship so callers (and tests) can access
    # req.bookings without triggering async lazy-load outside a greenlet.
    await db.refresh(req, ["bookings"])
    return req


async def update_custom_fields(
    db: AsyncSession,
    *,
    request_id: int,
    values: dict[str, Any],
    current_user: User,
    tenant_id: int,
) -> BookingRequest:
    req = await _get_request(db, request_id, tenant_id)
    req.custom_fields = values
    await db.flush()

    # Eagerly load the bookings relationship so callers (and tests) can access
    # req.bookings without triggering async lazy-load outside a greenlet.
    await db.refresh(req, ["bookings"])
    return req
