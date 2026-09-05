from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from dateutil.rrule import rrulestr
from fastapi import HTTPException, status
from sqlalchemy import not_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest
from app.db.models.booking_lifecycle import (
    BookingStatusHistory,
    BookingType as BookingTypeModel,
)
from app.db.models.lifecycle import LifecycleTemplate
from app.api.v1.schemas.booking import BookingCreate
from app.core.booking_states import INACTIVE_BOOKING_STATUSES
from app.core.events import publish_event
from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.core.protection_levels import PROTECTION_SOFT
from app.services.custom_field_service import validate_custom_fields, get_active_field_keys
from app.services import (
    agreement_gap_service, booking_request_service, conflict_service,
    contention_forecast_service, environment_decommission_service, lifecycle_service,
)
from app.services.lifecycle_service import (
    validate_transition,
    get_allowed_transitions,
)
from app.api.v1.schemas.booking_lifecycle import VALID_STANDARD_FIELD_NAMES


@dataclass
class OverlapResult:
    blocked: bool
    conflicts: list[int] = field(default_factory=list)
    warnings: list[int] = field(default_factory=list)


async def check_overlap(
    db: AsyncSession,
    env_id: int,
    start: datetime,
    end: datetime,
    tenant_id: int,
    exclusive_use: bool,
    exclude_id: Optional[int] = None,
) -> OverlapResult:
    """
    Find bookings that overlap with [start, end] for this environment.
    Overlap condition: existing.start_date < end AND existing.end_date > start

    STRICT (`<`/`>`), NOT INCLUSIVE. Deliberately different from
    `list_bookings`' overlap clause below (`<=`/`>=`), which exists to answer
    "is anything live at this exact instant" for the dashboard's zero-width
    "live now" probe. Here, a booking ending exactly when a new one starts is
    a clean handoff, not a conflict — treating a touching boundary as
    overlapping would refuse back-to-back bookings on the same environment.
    Do not "unify" these two without re-deriving which behaviour each caller
    needs.
    """
    query = (
        select(Booking)
        .options(selectinload(Booking.booking_request))
        .where(
            Booking.environment_id == env_id,
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            Booking.status != "rejected",
            Booking.start_date < end,
            Booking.end_date > start,
        )
    )
    if exclude_id is not None:
        query = query.where(Booking.id != exclude_id)

    result = await db.execute(query)
    overlapping = list(result.scalars().all())

    if not overlapping:
        return OverlapResult(blocked=False)

    # If new booking is exclusive or any existing is exclusive → blocked
    has_exclusive = exclusive_use or any(
        b.booking_request.exclusive_use_requested for b in overlapping
    )

    if has_exclusive:
        return OverlapResult(
            blocked=True,
            conflicts=[b.id for b in overlapping],
        )

    # All shared — not blocked, just warnings
    return OverlapResult(
        blocked=False,
        warnings=[b.id for b in overlapping],
    )


async def create_booking(
    db: AsyncSession, data: BookingCreate, current_user, *, now: datetime
) -> tuple[Booking, list[int]]:
    """
    Returns (parent_booking, overlap_warnings_list).
    Raises 409 if exclusive conflict exists.

    Creates a BookingRequest parent plus a single-env Booking child (and optionally
    recurring children).  The legacy single-env POST /bookings/ endpoint delegates here,
    and so — via release_booking_service — does the release booking path.

    Task 8: THE LEGACY CREATE PATH. `assert_bookable` runs first, before
    `check_overlap` and before anything is written — and against the WIDEST
    window this call will actually create, not just the first occurrence.
    A recurrence_rule can generate up to 100 occurrences across a 365-day
    horizon (see below); checking only `data.end_date` left every later
    occurrence uncheckable, so the occurrence set is computed ONCE here,
    the check runs against the FURTHEST occurrence's end in that ONE
    batched call, and the actual generation loop further down reuses this
    exact `occurrences` list rather than recomputing it — the two can never
    see a different set of dates (review finding 2 on the B5 task-8 report).
    """
    occurrences: list[datetime] = []
    if data.recurrence_rule:
        try:
            rule = rrulestr(data.recurrence_rule, dtstart=data.start_date, ignoretz=False)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid recurrence rule: {exc}",
            )
        horizon = data.start_date + timedelta(days=365)
        # Generate occurrences AFTER the start_date (parent IS the first
        # occurrence) — same window and cap the generation loop below used
        # to compute independently; now computed once and shared.
        occurrences = list(rule.between(data.start_date, horizon, inc=False))[:100]

    duration = data.end_date - data.start_date
    furthest_end = max([data.end_date] + [dt + duration for dt in occurrences])

    await environment_decommission_service.assert_bookable(
        db, current_user.active_tenant_id, [data.environment_id],
        data.start_date, furthest_end, now=now,
    )

    overlap = await check_overlap(
        db,
        data.environment_id,
        data.start_date,
        data.end_date,
        current_user.active_tenant_id,
        data.exclusive_use,
    )
    if overlap.blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Exclusive booking conflict",
                "conflicts": overlap.conflicts,
            },
        )

    # Resolve visible custom field keys from the booking type's lifecycle template initial state.
    # State-driven visibility supersedes the required flag: only enforce required for visible fields.
    visible_cf_keys: Optional[set[str]] = None
    bt_result = await db.execute(
        select(BookingTypeModel).where(
            BookingTypeModel.id == data.booking_type_id,
            BookingTypeModel.tenant_id == current_user.active_tenant_id,
            BookingTypeModel.deleted_at.is_(None),
        )
    )
    booking_type = bt_result.scalar_one_or_none()
    if booking_type:
        tmpl_result = await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.id == booking_type.lifecycle_template_id,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
        template = tmpl_result.scalar_one_or_none()
        if template:
            definition = template.definition or {}
            initial_state = next(
                (s for s in definition.get("states", []) if s.get("is_initial")), None
            )
            if initial_state:
                state_perm = definition.get("field_permissions", {}).get(initial_state["key"], {})
                cf_config = state_perm.get("custom_fields") or {}
                visible_cf_keys = set(cf_config.keys())

    await validate_custom_fields(db, current_user.active_tenant_id, "booking", data.custom_fields, visible_cf_keys)

    # B4 — inherit the booking type's default protection level, gated the
    # identical way create_request is: booking_request_service.
    # assert_may_set_protection is the single definition of this rule, reused
    # verbatim rather than a second copy that could drift.
    inherited_protection = (
        booking_type.default_protection_level
        if booking_type is not None
        else PROTECTION_SOFT
    )
    submitted_protection = data.protection_level
    booking_request_service.assert_may_set_protection(
        current_user, submitted=submitted_protection, current=inherited_protection
    )
    protection_level = (
        submitted_protection if submitted_protection is not None else inherited_protection
    )

    # Determine context_tag
    if data.context_tag is not None and data.context_tag != ContextTag.NONE:
        ctx = data.context_tag
    elif data.release_id is not None:
        ctx = ContextTag.DEPLOYMENT
    elif data.test_phase_id is not None:
        ctx = ContextTag.REGRESSION
    else:
        ctx = ContextTag.NONE

    # delegate_user_ids not supported via this legacy endpoint; use POST /booking-requests/ for delegates
    # Create the parent BookingRequest first — every Booking must have one.
    booking_request = BookingRequest(
        tenant_id=current_user.active_tenant_id,
        project_name=data.project_name,
        booking_type_id=data.booking_type_id,
        start_date=data.start_date,
        end_date=data.end_date,
        notes=data.notes,
        context_tag=ctx,
        exclusive_use_requested=data.exclusive_use,
        protection_level=protection_level,
        custom_fields=data.custom_fields,
        booked_by=current_user.id,
    )
    db.add(booking_request)
    await db.flush()

    parent = Booking(
        environment_id=data.environment_id,
        booking_request_id=booking_request.id,
        start_date=data.start_date,
        end_date=data.end_date,
        status="draft",
        recurrence_rule=data.recurrence_rule,
        recurrence_parent_id=None,
        release_id=data.release_id,
        test_phase_id=data.test_phase_id,
        tenant_id=current_user.active_tenant_id,
    )
    db.add(parent)
    await db.flush()
    await db.refresh(parent)

    # Write initial history row
    history = BookingStatusHistory(
        booking_id=parent.id,
        from_state=None,
        to_state="draft",
        changed_by=current_user.id,
        changed_at=datetime.now(timezone.utc),
    )
    db.add(history)
    await db.flush()

    # Generate recurring occurrences if RRULE provided — `occurrences` and
    # `duration` were already computed once, up top, for the Task 8 date
    # check; reused verbatim here so the check and the actual writes can
    # never see a different set of dates.
    if occurrences:
        for dt in occurrences:
            child = Booking(
                environment_id=data.environment_id,
                booking_request_id=booking_request.id,
                start_date=dt,
                end_date=dt + duration,
                status="draft",
                recurrence_rule=None,  # children don't store the rule
                recurrence_parent_id=parent.id,
                release_id=data.release_id,
                test_phase_id=data.test_phase_id,
                tenant_id=current_user.active_tenant_id,
            )
            db.add(child)

        await db.flush()

    # Re-fetch the parent with relationships eagerly loaded
    parent = await get_booking(db, parent.id, current_user.active_tenant_id)
    await publish_event(
        db,
        event_type="BookingCreated",
        aggregate_id=parent.id,
        aggregate_type="Booking",
        payload={
            "id": parent.id,
            "project_name": parent.booking_request.project_name,
            "environment_id": parent.environment_id,
            "tenant_id": parent.tenant_id,
        },
        tenant_id=parent.tenant_id,
    )
    return parent, overlap.warnings


async def get_booking(db: AsyncSession, booking_id: int, tenant_id: int) -> Booking:
    result = await db.execute(
        select(Booking)
        .options(
            selectinload(Booking.environment),
            selectinload(Booking.booking_request).selectinload(BookingRequest.booker),
        )
        .where(
            Booking.id == booking_id,
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


async def list_bookings(
    db: AsyncSession,
    tenant_id: int,
    environment_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    booking_status: Optional[str] = None,
    project_id: Optional[int] = None,
    agreement_gap: Optional[bool] = None,
    protection: Optional[str] = None,
    active: Optional[bool] = None,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    *,
    now: datetime,
) -> tuple[list[Booking], int, dict[int, str]]:
    query = (
        select(Booking)
        .options(
            selectinload(Booking.environment),
            selectinload(Booking.booking_request).selectinload(BookingRequest.booker),
        )
        .where(
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
        )
    )
    if environment_id is not None:
        query = query.where(Booking.environment_id == environment_id)
    if start is not None and end is not None:
        # Interval overlap, decomposed rather than using GREATEST/LEAST —
        # SQLite has neither (see contention_forecast_service.overlapping_pairs).
        # `<=`/`>=` on both sides, not `<`/`>`, so a zero-width probe (start ==
        # end, which is what the "live now" dashboard tile sends) still
        # matches a booking spanning — or starting or ending exactly at —
        # that instant. INCLUSIVE, deliberately different from
        # `check_overlap`'s strict `<`/`>` above (that one decides whether a
        # NEW booking conflicts with an existing one; a touching boundary is
        # a clean handoff there, not an overlap). Do not "unify" the two.
        query = query.where(Booking.start_date <= end, Booking.end_date >= start)
    if booking_status is not None:
        query = query.where(Booking.status == booking_status)
    if active is not None:
        # `?start=&end=` alone answers "is anything booked over this window",
        # including a booking nobody has submitted yet (draft) or one that
        # was refused (rejected) — dates say nothing about whether a claim is
        # real. This is a SEPARATE filter from `booking_status` (which pins
        # ONE exact status) because "not draft/rejected/closed" cannot be
        # expressed as an equality: it is the codebase's own
        # `INACTIVE_BOOKING_STATUSES` set, notin'd (true) or exactly matched
        # (false) so the two values partition the estate rather than leaving
        # a gap either can miss. The Dashboard's "Bookings live now" tile and
        # its link both pass `active=true` for exactly this reason — a
        # booking nobody has submitted is not a live claim on the
        # environment, whatever its dates say.
        if active:
            query = query.where(Booking.status.notin_(INACTIVE_BOOKING_STATUSES))
        else:
            query = query.where(Booking.status.in_(INACTIVE_BOOKING_STATUSES))
    # Sorting by protection_level needs the same join as the three filters
    # below, even with none of them present — BOOKING_SORTS whitelists
    # BookingRequest.protection_level (app/api/v1/bookings.py), and a bare
    # `?sort_by=protection_level` reaches apply_sort() with no filter set at
    # all. Without this, that request 500s ("no such column:
    # booking_request.protection_level") rather than 422ing or sorting —
    # found by test_sorting_by_protection_orders_rendered_rows, which sorts
    # with no protection= alongside it.
    sorting_needs_request_join = sort is not None and sort.column is BookingRequest.protection_level
    if (
        project_id is not None
        or agreement_gap is not None
        or protection is not None
        or sorting_needs_request_join
    ):
        # In SQL, on the parent request — the endpoint is bounded (fetch_page
        # below), so a Python-side filter would window the page before filtering
        # and quietly return the wrong rows, and X-Total-Count would describe
        # the unfiltered set. booking_request_id is NOT NULL, so this inner join
        # drops no legitimate row, and it's a plain many-to-one (one
        # booking_request per booking) so it can't fan out duplicates the way a
        # one-to-many join would.
        #
        # ONE join for all three filters plus the sort above. `agreement_gap_
        # service.gap_clause` correlates against BOTH Booking and
        # BookingRequest, so a consumer that forgot this join would get a
        # cartesian product rather than an error — and joining twice (or more)
        # for these together would do the same, or trip a SQLAlchemy
        # duplicate-join warning.
        #
        # DELIBERATELY NOT TENANT-QUALIFIED, matching
        # `agreement_gap_service.gaps_for_bookings`, whose own join carries the
        # rule: qualify it in one place without the other and the SQL filter and
        # the per-row message disagree about a malformed booking. If a future
        # change wants it qualified, both must change in the same commit.
        # Tenant scoping lives on Booking.tenant_id above and inside the clause,
        # so an unqualified join can leak nothing.
        query = query.join(BookingRequest, Booking.booking_request_id == BookingRequest.id)
    if project_id is not None:
        query = query.where(BookingRequest.project_id == project_id)
    if agreement_gap is not None:
        # A3 WARNS: this narrows a list, it refuses nothing. `False` is the
        # exact complement — covered bookings AND those whose request names no
        # project — so true and false partition the estate rather than leaving
        # project-less bookings invisible to both.
        gap = agreement_gap_service.gap_clause(tenant_id)
        query = query.where(gap if agreement_gap else ~gap)
    if protection is not None:
        # B4 ADVISES: this narrows a list, it refuses nothing. On the same
        # BookingRequest join as project_id/agreement_gap above — not a second
        # join.
        query = query.where(BookingRequest.protection_level == protection)
    query = apply_sort(query, sort).order_by(Booking.start_date.asc(), Booking.id)
    rows, total = await fetch_page(db, query, page)
    # ONCE PER RESPONSE, NEVER ONCE PER ROW (B6 Task 4, following A3's
    # agreement-gap rule) — the whole page's ids in one call, handed back for
    # the endpoint's response builder to `.get(booking.id)` from. Absent key
    # means no contention; there is deliberately no "none" state to default
    # to instead.
    contention_states = await contention_forecast_service.contention_states_for_bookings(
        db, tenant_id, [b.id for b in rows], now=now,
    )
    return rows, total, contention_states


async def list_live_bookings(
    db: AsyncSession, tenant_id: int, environment_id: int, *, limit: int = 500,
) -> list[Booking]:
    """Bookings genuinely still on the calendar for one environment — every
    non-deleted booking except the TERMINAL ones
    (`conflict_service.TERMINAL_STATES`: rejected, closed).

    Backs the decommission teardown route's `remaining_bookings`, which must
    still surface a DRAFT booking — an uncommitted claim is still a claim
    worth naming before someone tears the environment down. That is why this
    excludes only TERMINAL_STATES and NOT the stricter
    `app.core.booking_states.INACTIVE_BOOKING_STATUSES` (which also drops
    draft) — that set answers a different question, "is this a genuine
    RESERVATION for scheduling purposes", not "is there anything left to
    tell someone about". Do not merge the two.

    Bounded, following this repo's pagination conventions — an unbounded
    list embedded in a single API response is a standing defect, not a
    feature, the same class `/tenant/users` was before it was capped.
    """
    query = (
        select(Booking)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.environment_id == environment_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(conflict_service.TERMINAL_STATES)),
        )
        .order_by(Booking.start_date.asc(), Booking.id)
        .limit(limit)
    )
    return list((await db.execute(query)).scalars().all())


async def _template_for_booking(db: AsyncSession, booking: Booking) -> LifecycleTemplate:
    """Resolve the lifecycle template governing `booking`'s transitions, via
    its booking type. Raises the same 404s `transition_state` always has —
    extracted so the group path validates by EXACTLY this rule, not a second
    copy of it that could drift.

    FAIL-CLOSED, deliberately: a missing booking type or template means
    validate_transition has nothing to check a transition against, and
    silently allowing (or silently refusing) a mutating request on missing
    configuration data is worse than a 404. Contrast
    `_template_for_booking_or_none` below, which fails open for read-only
    permission rendering, where a 404 would break an unrelated page instead
    of surfacing the real problem.
    """
    booking_type_id = booking.booking_request.booking_type_id
    result = await db.execute(
        select(BookingTypeModel).where(BookingTypeModel.id == booking_type_id)
    )
    booking_type_obj = result.scalar_one_or_none()
    if not booking_type_obj:
        raise HTTPException(status_code=404, detail="Booking type not found")

    tmpl_result = await db.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.id == booking_type_obj.lifecycle_template_id
        )
    )
    template = tmpl_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Lifecycle template not found")
    return template


def _record_values(br: BookingRequest) -> dict:
    """The flat record_values shape `validate_transition` checks
    `required_fields` against, built from a booking's parent BookingRequest.
    Extracted from `transition_state` so the group path uses the identical
    construction — a second copy would drift from what it validates."""
    return {
        "project_name": br.project_name or "",
        "start_date": br.start_date,
        "end_date": br.end_date,
        "booking_type": str(br.booking_type_id) if br.booking_type_id else "",
        "notes": br.notes or "",
        "exclusive_use": br.exclusive_use_requested,
        "context_tag": br.context_tag.value if br.context_tag else "",
        "custom_fields": br.custom_fields or {},
    }


async def transition_state(
    db: AsyncSession,
    booking_id: int,
    to_state: str,
    current_user,
    notes: str | None = None,
) -> Booking:
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)
    template = await _template_for_booking(db, booking)

    user_role = current_user.role
    allowed, reason = validate_transition(
        template.definition, booking.status, to_state, user_role,
        _record_values(booking.booking_request),
    )
    if not allowed:
        # Distinguish role-blocked (403) from invalid/undefined transition or required fields (400)
        if reason and ("not allowed" in reason or "role" in reason.lower()):
            raise HTTPException(status_code=403, detail="Your role cannot make this transition")
        raise HTTPException(status_code=400, detail=reason or f"Invalid transition: {booking.status} -> {to_state}")

    old_state = booking.status
    booking.status = to_state

    history = BookingStatusHistory(
        booking_id=booking.id,
        from_state=old_state,
        to_state=to_state,
        changed_by=current_user.id,
        changed_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(history)
    await db.flush()

    await publish_event(
        db,
        event_type="BookingStateTransitioned",
        aggregate_id=booking.id,
        aggregate_type="Booking",
        payload={"from_state": old_state, "to_state": to_state, "changed_by": current_user.id},
        tenant_id=booking.tenant_id,
    )
    await db.refresh(booking)
    # Reload with relationships after refresh
    booking = await get_booking(db, booking.id, booking.tenant_id)
    return booking


async def get_status_history(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> list[BookingStatusHistory]:
    # Verify booking belongs to tenant
    await get_booking(db, booking_id, tenant_id)
    result = await db.execute(
        select(BookingStatusHistory)
        .where(BookingStatusHistory.booking_id == booking_id)
        .order_by(BookingStatusHistory.changed_at.asc())
    )
    return list(result.scalars().all())


async def get_booking_allowed_transitions(
    db: AsyncSession, booking_id: int, current_user
) -> list[dict]:
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)
    template = await _template_for_booking(db, booking)
    return get_allowed_transitions(template.definition, booking.status, current_user.role)


async def _group_bookings(
    db: AsyncSession, request_id: int, group_id: int, tenant_id: int
) -> list[Booking]:
    """The live bookings on `request_id` that came from `group_id`.

    Scoped by the (request, group) pair, which is the atomic unit. Ordered by
    id so error messages and history rows are deterministic. Eager-loads
    `environment` and `booking_request` (+ `booker`) — `transition_group`
    reads `booking.environment.name` for its failure messages and
    `_record_values(booking.booking_request)`, and the route builds
    `BookingResponse` from the same objects; none of that is safe as a lazy
    load under AsyncSession.
    """
    rows = (await db.execute(
        select(Booking)
        .options(
            selectinload(Booking.environment),
            selectinload(Booking.booking_request).selectinload(BookingRequest.booker),
        )
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
        .where(
            Booking.booking_request_id == request_id,
            Booking.environment_group_id == group_id,
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            BookingRequest.tenant_id == tenant_id,
            # Defence-in-depth, not a live guard: nothing in the codebase
            # ever sets BookingRequest.deleted_at, so this clause is
            # currently unreachable. Kept for the same reason every other
            # tenant-scoped query here filters it — matches repo convention.
            BookingRequest.deleted_at.is_(None),
        )
        .order_by(Booking.id)
    )).scalars().all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No bookings for that environment group on this request",
        )
    return list(rows)


async def transition_group(
    db: AsyncSession,
    request_id: int,
    group_id: int,
    to_state: str,
    current_user,
    notes: str | None = None,
) -> list[Booking]:
    """Move every member of a group booking, or none of them.

    ALL-OR-NOTHING, validated before anything mutates. A half-transitioned
    group is the shape that produced two unrecoverable states on B3b, one of
    them asserted as correct by that branch's own test.

    Every failure is reported, not just the first: an approver needs to see
    everything that is wrong at once, because the repair is manual and
    per-member.
    """
    tenant_id = current_user.active_tenant_id
    bookings = await _group_bookings(db, request_id, group_id, tenant_id)
    template = await _template_for_booking(db, bookings[0])

    failures: list[str] = []
    role_blocked = False
    for booking in bookings:
        allowed, reason = validate_transition(
            template.definition, booking.status, to_state, current_user.role,
            _record_values(booking.booking_request),
        )
        if not allowed:
            env_name = booking.environment.name if booking.environment else str(
                booking.environment_id
            )
            failures.append(f"{env_name} (in '{booking.status}'): {reason}")
            if reason and ("not allowed" in reason or "role" in reason.lower()):
                role_blocked = True

    if failures:
        joined = "; ".join(failures)
        if role_blocked:
            raise HTTPException(
                status_code=403,
                detail=f"Your role cannot make this transition for: {joined}",
            )
        raise HTTPException(
            status_code=400,
            detail=(
                f"The group cannot move to '{to_state}' because its members "
                f"are not all able to: {joined}"
            ),
        )

    for booking in bookings:
        old_state = booking.status
        booking.status = to_state
        db.add(BookingStatusHistory(
            booking_id=booking.id,
            from_state=old_state,
            to_state=to_state,
            changed_by=current_user.id,
            changed_at=datetime.now(timezone.utc),
            notes=notes,
        ))
        await publish_event(
            db,
            event_type="BookingStateTransitioned",
            aggregate_id=booking.id,
            aggregate_type="Booking",
            payload={
                "from_state": old_state,
                "to_state": to_state,
                "changed_by": current_user.id,
            },
            tenant_id=booking.tenant_id,
        )
    await db.flush()
    # `updated_at` has a server-side `onupdate`, so after flush its value on
    # each mutated ORM object is expired and would trigger a lazy load
    # during response serialization — not safe under AsyncSession (the same
    # reason transition_state re-fetches after its own flush). Re-query
    # rather than db.refresh() each row individually: it also keeps the
    # eager-loaded relationships (environment, booking_request.booker) the
    # route's response-building needs.
    return await _group_bookings(db, request_id, group_id, tenant_id)


async def get_group_allowed_transitions(
    db: AsyncSession, request_id: int, group_id: int, current_user
) -> list[dict]:
    """The INTERSECTION of what every member allows.

    A transition not valid for all members must not be offered, or the UI
    shows a button that always fails — precisely what all-or-nothing exists
    to prevent.
    """
    tenant_id = current_user.active_tenant_id
    bookings = await _group_bookings(db, request_id, group_id, tenant_id)
    template = await _template_for_booking(db, bookings[0])

    per_member: list[set[str]] = []
    by_state: dict[str, dict] = {}
    for booking in bookings:
        allowed = get_allowed_transitions(
            template.definition, booking.status, current_user.role
        )
        per_member.append({t["to_state"] for t in allowed})
        for t in allowed:
            by_state.setdefault(t["to_state"], t)

    # Defence-in-depth, not a live guard: `_group_bookings` above raises 404
    # on an empty result, so `bookings` — and therefore `per_member`, built
    # by iterating it — is never empty here.
    if not per_member:
        return []
    common = set.intersection(*per_member)
    return [by_state[s] for s in sorted(common)]


async def delete_occurrence(db: AsyncSession, booking_id: int, current_user) -> None:
    """Soft-delete a single booking occurrence."""
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)

    is_owner = booking.booking_request.booked_by == current_user.id
    is_privileged = current_user.is_master_admin or current_user.role in ("Admin", "Release Manager")
    if not (is_owner or is_privileged):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this booking occurrence",
        )

    booking.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def delete_series(db: AsyncSession, booking_id: int, current_user) -> None:
    """Soft-delete the entire series (parent + all children)."""
    booking = await get_booking(db, booking_id, current_user.active_tenant_id)

    # Allow if owner or Admin/Release Manager/master admin
    is_owner = booking.booking_request.booked_by == current_user.id
    is_privileged = current_user.is_master_admin or current_user.role in ("Admin", "Release Manager")
    if not (is_owner or is_privileged):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own booking series",
        )

    # Find root: if booking has a parent, load the parent
    if booking.recurrence_parent_id is not None:
        root = await get_booking(db, booking.recurrence_parent_id, current_user.active_tenant_id)
    else:
        root = booking

    now = datetime.now(timezone.utc)
    root.deleted_at = now

    # Bulk soft-delete all children
    await db.execute(
        update(Booking)
        .where(
            Booking.recurrence_parent_id == root.id,
            Booking.deleted_at.is_(None),
        )
        .values(deleted_at=now)
    )

    await db.flush()


async def _template_for_booking_or_none(
    db: AsyncSession, booking: "Booking"
) -> LifecycleTemplate | None:
    """Resolve the lifecycle template for a booking via its booking_type, or
    None if either lookup misses.

    FAIL-OPEN, deliberately, unlike `_template_for_booking` above: every
    caller of this helper is rendering field permissions for display, not
    validating a mutation, and a booking whose template went missing (a data
    quality issue, not a request the caller controls) should still degrade
    to "nothing editable" rather than 404 out of an unrelated read. Do not
    point a validating call site at this helper — use `_template_for_booking`
    for that, which raises instead.
    """
    booking_type_id = booking.booking_request.booking_type_id
    bt = (
        await db.execute(
            select(BookingTypeModel).where(BookingTypeModel.id == booking_type_id)
        )
    ).scalar_one_or_none()
    if not bt:
        return None
    return (
        await db.execute(
            select(LifecycleTemplate).where(LifecycleTemplate.id == bt.lifecycle_template_id)
        )
    ).scalar_one_or_none()


async def _booking_field_permissions(
    db: AsyncSession, booking: "Booking", user_role: str
) -> dict:
    """Return {custom_field_permissions, standard_field_permissions} for a booking.
    Fail-closed: returns empty custom map + all-not-editable standard map if the
    booking type or template cannot be loaded."""
    template = await _template_for_booking_or_none(db, booking)
    if template is None:
        return {
            "custom_field_permissions": {},
            "standard_field_permissions": {f: {"editable": False} for f in VALID_STANDARD_FIELD_NAMES},
        }
    active_keys = await get_active_field_keys(db, booking.tenant_id, "booking")
    return lifecycle_service.get_field_permissions_for_state(
        template.definition,
        booking.status,
        user_role,
        active_keys,
        VALID_STANDARD_FIELD_NAMES,
    )


async def get_custom_field_perms_for_booking(
    db: AsyncSession, booking: "Booking", user_role: str
) -> dict[str, dict]:
    """Return the resolved custom_field_permissions map for a booking.
    Preserved for backward compatibility with existing callers."""
    perms = await _booking_field_permissions(db, booking, user_role)
    return perms["custom_field_permissions"]


def get_standard_field_permissions(
    definition: dict, state_key: str, user_role: str
) -> set[str]:
    """Return the set of standard permission keys editable by user_role in state_key.
    Fail-closed: returns empty set if state not configured.
    Preserved: some callers import this directly."""
    perm = definition.get("field_permissions", {}).get(state_key)
    if not perm:
        return set()
    standard_fields = perm.get("standard_fields", {})
    return {
        field_key
        for field_key, config in standard_fields.items()
        if user_role in config.get("editable_by", [])
    }


async def get_standard_field_perms_for_booking(
    db: AsyncSession, booking: "Booking", user_role: str
) -> dict[str, dict]:
    """Return editable status for all 7 standard fields for this booking's state+role."""
    perms = await _booking_field_permissions(db, booking, user_role)
    return perms["standard_field_permissions"]


async def update_standard_fields(
    db: AsyncSession,
    booking_id: int,
    values: dict,
    current_user,
    *,
    now: datetime,
) -> Booking:
    """Update per-env overrides on a booking.

    Only `start_date` and `end_date` are editable at the booking (per-env) level.
    All other standard fields moved to the booking_request; callers must use
    `booking_request_service.update_standard_fields` for those.

    Permissions are still enforced via the lifecycle template (fail-closed if
    template is missing).

    Task 8: this is a SEPARATE date-extending edit path from
    `booking_request_service.update_standard_fields` (the request-level
    cascade to every child) — a per-env override here can move just this one
    booking's dates past teardown without touching the parent request at
    all, so it gets its own `assert_bookable` call, against this booking's
    own environment_id.
    """
    ALLOWED_ENV_OVERRIDES = {"start_date", "end_date"}

    unknown = set(values) - ALLOWED_ENV_OVERRIDES
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Fields {sorted(unknown)} are no longer editable on a booking; "
                "use PATCH /booking-requests/{id}/standard-fields instead"
            ),
        )

    booking = await get_booking(db, booking_id, current_user.active_tenant_id)

    # Same fail-open lookup `_booking_field_permissions` uses: this is a
    # permission check ahead of a write to two fields, not a transition, and
    # a missing template must degrade to "nothing editable" (still fails
    # closed on the ACTUAL permission below), not 404 the whole request.
    template = await _template_for_booking_or_none(db, booking)
    editable_perm_keys: set[str] = set()
    if template:
        editable_perm_keys = get_standard_field_permissions(
            template.definition, booking.status, current_user.role
        )
    # Fail-closed: if template not found, editable_perm_keys stays empty

    for col_name in values:
        if col_name not in editable_perm_keys:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Field '{col_name}' is not editable in state '{booking.status}' for your role",
            )

    coerced: dict = {}
    for col_name, value in values.items():
        if col_name in {"start_date", "end_date"} and isinstance(value, str):
            # Accept ISO-8601 strings (with trailing Z) — coerce to timezone-aware datetime.
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid ISO-8601 datetime for {col_name}",
                )
        coerced[col_name] = value

    if "start_date" in coerced or "end_date" in coerced:
        new_start = coerced.get("start_date", booking.start_date)
        new_end = coerced.get("end_date", booking.end_date)
        await environment_decommission_service.assert_bookable(
            db, current_user.active_tenant_id, [booking.environment_id],
            new_start, new_end, now=now,
        )

    for col_name, value in coerced.items():
        setattr(booking, col_name, value)

    await db.flush()
    # Reload with relationships after flush
    booking = await get_booking(db, booking.id, booking.tenant_id)
    return booking


# ── Release context tag derivation ───────────────────────────────────────────

_ROLE_TO_CONTEXT_TAG: dict[str, ContextTag] = {
    "changing": ContextTag.DEPLOYMENT,
    "regression": ContextTag.REGRESSION,
    "config_only": ContextTag.NONE,
}


async def derive_and_set_context_tag(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> None:
    """Derive and set the context_tag on the booking's parent BookingRequest.

    Algorithm:
    1. If booking.release_id is None → set context_tag='none'; return.
    2. For every system linked to booking.environment via environment_system,
       look up a ReleaseSystem row for (release_id, system_id). First match wins.
    3. Map role to ContextTag: 'changing'->'deployment', 'regression'->'regression',
       'config_only'->'none', fallback 'none'.
    4. Write the tag to booking_request.context_tag.
    """
    from app.db.models.environment import EnvironmentSystem
    from app.db.models.release_system import ReleaseSystem

    booking = (
        await db.execute(
            select(Booking).where(
                Booking.id == booking_id,
                Booking.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if booking is None:
        return

    # Reload booking_request
    br = (
        await db.execute(
            select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
        )
    ).scalar_one_or_none()
    if br is None:
        return

    if booking.release_id is None:
        br.context_tag = ContextTag.NONE
        await db.flush()
        return

    # Get all system_ids for this environment
    env_systems = (
        await db.execute(
            select(EnvironmentSystem).where(
                EnvironmentSystem.environment_id == booking.environment_id,
                EnvironmentSystem.tenant_id == booking.tenant_id,
            )
        )
    ).scalars().all()

    derived_tag = ContextTag.NONE
    for env_sys in env_systems:
        rel_sys = (
            await db.execute(
                select(ReleaseSystem).where(
                    ReleaseSystem.release_id == booking.release_id,
                    ReleaseSystem.system_id == env_sys.system_id,
                    ReleaseSystem.tenant_id == booking.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if rel_sys is not None:
            derived_tag = _ROLE_TO_CONTEXT_TAG.get(rel_sys.role, ContextTag.NONE)
            break  # First match wins

    br.context_tag = derived_tag
    await db.flush()
