"""B5 — the decommission's state, computed, and its SQL predicate.

Following A4's `contention_service`: `EnvironmentDecommission` stores facts
only (there is no `state` column and there must never be one), and the state
is derived here from those facts and the caller's clock. That is why B5 needs
no scheduler and nothing to invalidate when a notice period elapses.

THE BRANCH ORDER IS THE RULE. Cancelled outranks torn down (a record can be
both, if someone cancels a mistaken teardown after it already happened), torn
down outranks an undecided extension (the environment is gone; the request is
moot), and an undecided extension outranks the clock (the owner is owed an
answer before the notice runs out). `state_predicate` REPRODUCES this order in
SQL rather than approximating it — two mechanisms answering one question, so
every state in the parametrised test asserts both, and neither may drift from
the other without the test failing.

A DEADLINE IS A DAY, NOT AN INSTANT. Both functions compare
`scheduled_teardown_at` against `expiry_boundary(now)` — the start of today —
never against `now` itself. This project has shipped the instant-precision
version of this bug twice already: A4's escalations turned `expired` at one
minute past midnight on their own deadline day, and B2's quarantine grace lost
most of an environment's last grace day the same way. See
`app.core.day_boundaries.expiry_boundary` for the full account.
"""
from datetime import datetime, timedelta, timezone
from typing import Iterable, NamedTuple, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.day_boundaries import expiry_boundary
from app.core.decommission_states import (
    STATE_CANCELLED, STATE_DUE, STATE_EXTENSION_REQUESTED, STATE_TORN_DOWN,
    STATE_WARNED,
)
from app.core.pagination import Page, Sort, apply_sort, fetch_page
from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_decommission import (
    EnvironmentDecommission, EnvironmentDecommissionAttestation,
)
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from app.services import environment_lifecycle_policy_service
from app.services.environment_service import get_environment


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes where PostgreSQL hands back aware
    ones. A copy of `contention_service._utc` (itself one of several in this
    codebase), copied rather than imported for the reason recorded there:
    reaching into another module's private helper couples two files that
    share nothing else. The rule that must NOT be copied is the day boundary
    — that comes from `expiry_boundary`, and only from there.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def decommission_state(row: EnvironmentDecommission, now: datetime) -> str:
    """COMPUTED, never stored — which is why B5 needs no scheduler.

    THE BRANCH ORDER IS THE RULE. Cancelled outranks torn down (a record can be
    both if someone cancels a mistaken teardown), torn down outranks an
    undecided extension (the environment is gone; the request is moot), and an
    undecided extension outranks the clock (the owner is owed an answer before
    the notice runs out).

    THE TEARDOWN DAY ITSELF IS STILL `warned`. Compared against
    expiry_boundary(now) — the start of today — not against `now`. See that
    function for the defect this avoids and the two sub-projects that paid for
    it.
    """
    if row.cancelled_at is not None:
        return STATE_CANCELLED
    if row.torn_down_at is not None:
        return STATE_TORN_DOWN
    if row.extension_requested_at is not None and row.extension_decided_at is None:
        return STATE_EXTENSION_REQUESTED
    if _utc(row.scheduled_teardown_at) >= expiry_boundary(now):
        return STATE_WARNED
    return STATE_DUE


def state_predicate(state: str, now: datetime):
    """The five states as SQL, over the same columns `decommission_state` reads.

    IN SQL, NEVER IN PYTHON: a worklist filtered after the page was fetched
    would window the unfiltered set, and X-Total-Count would describe the wrong
    total. The branch order above is REPRODUCED here, not approximated.
    """
    boundary = expiry_boundary(now)
    D = EnvironmentDecommission

    not_terminal = and_(D.cancelled_at.is_(None), D.torn_down_at.is_(None))
    no_open_extension = or_(
        D.extension_requested_at.is_(None),
        D.extension_decided_at.is_not(None),
    )

    if state == STATE_CANCELLED:
        return D.cancelled_at.is_not(None)
    if state == STATE_TORN_DOWN:
        return and_(D.cancelled_at.is_(None), D.torn_down_at.is_not(None))
    if state == STATE_EXTENSION_REQUESTED:
        return and_(
            not_terminal,
            D.extension_requested_at.is_not(None),
            D.extension_decided_at.is_(None),
        )
    if state == STATE_WARNED:
        return and_(not_terminal, no_open_extension,
                    D.scheduled_teardown_at >= boundary)
    if state == STATE_DUE:
        return and_(not_terminal, no_open_extension,
                    D.scheduled_teardown_at < boundary)
    raise ValueError(f"unknown decommission state {state!r}")


def live_predicate(now: datetime):
    """A decommission that still constrains bookings: not cancelled, not torn
    down, not soft-deleted. Task 8's refusal hangs off exactly this."""
    D = EnvironmentDecommission
    return and_(
        D.deleted_at.is_(None),
        D.cancelled_at.is_(None),
        D.torn_down_at.is_(None),
    )


async def assert_bookable(
    db: AsyncSession,
    tenant_id: int,
    environment_ids: Sequence[int],
    start: datetime,
    end: datetime,
    *,
    now: datetime,
) -> None:
    """Refuse a booking whose window runs past a live decommission's teardown
    date. THE ONLY OTHER THING B5 CHANGES OUTSIDE ITS OWN RECORDS, besides
    `tear_down` itself.

    THE RULE IS THE DATE, NOT THE EXISTENCE OF A DECOMMISSION. The environment
    still exists until teardown and a team may legitimately need it next
    week — a blanket "has a live decommission" refusal would need a carve-out
    for exactly that. `scheduled_teardown_at` is read fresh on every call, so
    granting an extension (which MOVES that column — see `decide_extension`)
    widens what is bookable with NO second write anywhere in this function:
    the line simply moves.

    `start` is accepted for symmetry with the booking window this call always
    represents, but the rule only cares where the window ENDS — a booking
    that finishes before teardown is accepted regardless of when it starts.

    BATCHED — ONE query for every environment on the request, not one per
    environment; a group booking may name a dozen.

    Closes the degenerate case too: no create path anywhere looks at
    `environment.status`, so nothing today refuses a booking against an
    environment that has already been torn down. Caught in the same query,
    via the same LEFT JOIN — `Environment.status` needs no decommission row
    at all to be DECOMMISSIONED (a tenant could reach that status by other
    means later), so this half does not depend on `live_predicate` matching.
    """
    ids = list(dict.fromkeys(environment_ids))
    if not ids:
        return

    D = EnvironmentDecommission
    rows = (
        await db.execute(
            select(
                Environment.id, Environment.name, Environment.status,
                D.scheduled_teardown_at,
            )
            .select_from(Environment)
            .outerjoin(
                D,
                and_(
                    D.environment_id == Environment.id,
                    D.tenant_id == tenant_id,
                    live_predicate(now),
                ),
            )
            .where(Environment.id.in_(ids), Environment.tenant_id == tenant_id)
        )
    ).all()

    end_utc = _utc(end)
    for _env_id, name, env_status, teardown_at in rows:
        if env_status == EnvironmentStatus.DECOMMISSIONED:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{name} has already been decommissioned and cannot be booked",
            )
        if teardown_at is not None and _utc(teardown_at) < end_utc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{name} is scheduled to be torn down on "
                f"{_utc(teardown_at).date().isoformat()} — this booking runs "
                f"past that date",
            )


async def assert_may_run(db: AsyncSession, environment: Environment, user: User) -> None:
    """The operating team, or an Admin / master admin. Everything except
    requesting an extension goes through here.

    The THIRD reader of group membership in this application, after
    `environment_request_service.assert_may_transition` and
    `environment_service.assert_may_edit_handover` — read both before touching
    this, and keep all three in step: same tenant scoping (the join and the
    membership row are both filtered on the environment's own tenant), same
    Admin-or-master-admin bypass, and the same degradation to Admin-only when
    `operations_group_id` is NULL or the group has no members. A NULL group
    joins to no membership row, never to everyone or no one incorrectly — it
    is not a special case, just what the join naturally does.
    """
    if user.role == "Admin" or user.is_master_admin:
        return
    found = (
        await db.execute(
            select(UserGroupMember.id)
            .join(
                Environment,
                Environment.operations_group_id == UserGroupMember.group_id,
            )
            .where(
                Environment.id == environment.id,
                Environment.tenant_id == environment.tenant_id,
                UserGroupMember.user_id == user.id,
                UserGroupMember.tenant_id == environment.tenant_id,
            )
        )
    ).first()
    if found is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the operating team for this environment, or an admin, can "
            "run its decommission",
        )


async def assert_may_defend(db: AsyncSession, environment: Environment, user: User) -> None:
    """The environment's NAMED OWNER, or an Admin.

    Deliberately NOT gated on operating-team membership — unlike
    `assert_may_run`. B3b gated a requester's own submission on group
    membership and made the primary journey impossible, because the person
    defending an environment (declining teardown, requesting an extension) is
    by definition not on the team decommissioning it. Do not "tidy" these two
    helpers into one: they gate opposite parties.
    """
    if user.role == "Admin" or user.is_master_admin:
        return
    if environment.owner_user_id is not None and environment.owner_user_id == user.id:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only this environment's owner, or an admin, can do this",
    )


async def get_live(
    db: AsyncSession, tenant_id: int, environment_id: int, now: datetime
) -> Optional[EnvironmentDecommission]:
    """The one row matching `live_predicate` for this environment and tenant,
    or None. There can be at most one — enforced by `initiate`'s 409, not by
    a partial unique index (inert on SQLite, the same call B3a's group-name
    uniqueness made).

    `now` is REQUIRED, not defaulted — this function is reached from a route
    (directly by GET .../decommission, and indirectly through `initiate`),
    and a defaulted `datetime.now()` here would be a second clock in the same
    request, disagreeing with whatever instant the route used to render
    `state`. Callers take the clock once and pass it down.
    """
    return (
        await db.execute(
            select(EnvironmentDecommission).where(
                EnvironmentDecommission.tenant_id == tenant_id,
                EnvironmentDecommission.environment_id == environment_id,
                live_predicate(now),
            )
        )
    ).scalars().first()


async def get_most_recent(
    db: AsyncSession, tenant_id: int, environment_id: int
) -> Optional[EnvironmentDecommission]:
    """The most recently warned decommission for this environment, live or
    terminal, or None if it has never been decommissioned. Backs
    `GET /environments/{id}/decommission`: a 404 for "never decommissioned"
    would make the panel's ordinary case an error path, so the route answers
    null instead and this is what it reads to build that answer."""
    return (
        await db.execute(
            select(EnvironmentDecommission)
            .where(
                EnvironmentDecommission.tenant_id == tenant_id,
                EnvironmentDecommission.environment_id == environment_id,
                EnvironmentDecommission.deleted_at.is_(None),
            )
            .order_by(EnvironmentDecommission.warned_at.desc(), EnvironmentDecommission.id.desc())
        )
    ).scalars().first()


async def initiate(
    db: AsyncSession,
    tenant_id: int,
    environment_id: int,
    user: User,
    *,
    reason: str,
    scheduled_teardown_at: Optional[datetime] = None,
    now: datetime,
) -> EnvironmentDecommission:
    """Start a decommission. ORDER OF OPERATIONS IS THE RULE, exactly:

    resolve the environment (404 across tenants, never 403) -> assert_may_run
    -> reject a blank reason -> refuse a second LIVE decommission with 409 ->
    compute scheduled_teardown_at as warned_at + the tenant's
    decommission_notice_days -> refuse an EARLIER caller-supplied date with
    422 -> insert.

    The earlier-date refusal is not cosmetic: Task 8's booking refusal derives
    from this column, so an initiator who could shorten the notice would make
    the five-day warning advisory.

    `now` is REQUIRED and KEYWORD-ONLY, with no default — a defaulted
    `datetime.now()` here would be a second clock, taken a moment after the
    route's own `now`, that then disagrees with the `state` the route renders
    from the response. The caller (the route) takes the clock once and hands
    the same instant to `initiate` and to the response builder; `warned_at`
    on the stored row is exactly that instant, not a fresh read of the clock.
    """
    environment = await get_environment(db, environment_id, tenant_id)

    await assert_may_run(db, environment, user)

    if reason is None or not reason.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A reason is required — a decommission with no stated reason is "
            "not an audit record",
        )

    if await get_live(db, tenant_id, environment_id, now) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This environment already has a live decommission",
        )

    policy = await environment_lifecycle_policy_service.get_policy(db, tenant_id)
    warned_at = now
    earliest_teardown = warned_at + timedelta(days=policy.decommission_notice_days)

    if scheduled_teardown_at is not None:
        teardown = scheduled_teardown_at
        if teardown.tzinfo is None:
            teardown = teardown.replace(tzinfo=timezone.utc)
        if teardown < earliest_teardown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "scheduled_teardown_at cannot be earlier than the tenant's "
                f"{policy.decommission_notice_days}-day notice period",
            )
    else:
        teardown = earliest_teardown

    row = EnvironmentDecommission(
        tenant_id=tenant_id,
        environment_id=environment_id,
        reason=reason.strip(),
        warned_at=warned_at,
        scheduled_teardown_at=teardown,
        initiated_by=user.id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_decommission_by_id(
    db: AsyncSession, decommission_id: int, tenant_id: int
) -> EnvironmentDecommission:
    """Tenant-filtered lookup by the decommission's own id — the extension
    routes address a decommission directly, not through its environment, so
    this is the resolve step `initiate` gets for free from `get_environment`.
    404 across tenants, never 403 — a foreign-tenant id must be
    indistinguishable from one that never existed."""
    row = (
        await db.execute(
            select(EnvironmentDecommission).where(
                EnvironmentDecommission.id == decommission_id,
                EnvironmentDecommission.tenant_id == tenant_id,
                EnvironmentDecommission.deleted_at.is_(None),
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decommission not found")
    return row


async def request_extension(
    db: AsyncSession,
    decommission: EnvironmentDecommission,
    user: User,
    *,
    reason: str,
    until: datetime,
    now: datetime,
) -> EnvironmentDecommission:
    """The owner asking for more time. `assert_may_defend`: the environment's
    NAMED OWNER, or an Admin — deliberately NOT the operating team, which is
    who `decide_extension` gates.

    ORDER OF OPERATIONS: resolve the environment (404 across tenants) ->
    assert_may_defend -> 409 if the row is not LIVE (checked through
    `live_predicate`, not re-derived) -> 409 if an extension has already been
    requested on this row, granted or refused (ONE extension per
    decommission — spec's cancel-and-re-raise rule) -> 422 if `until` is not
    strictly later than the current `scheduled_teardown_at` -> set the four
    request fields.

    `now` is REQUIRED and KEYWORD-ONLY, no default, following Task 5's
    standing convention: a defaulted `datetime.now()` here would be a second
    clock disagreeing with the one the route uses to render `state`.
    """
    environment = await get_environment(
        db, decommission.environment_id, decommission.tenant_id
    )
    await assert_may_defend(db, environment, user)

    still_live = (
        await db.execute(
            select(EnvironmentDecommission.id).where(
                EnvironmentDecommission.id == decommission.id,
                EnvironmentDecommission.tenant_id == decommission.tenant_id,
                live_predicate(now),
            )
        )
    ).first()
    if still_live is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This decommission is no longer live — it has been cancelled or "
            "torn down",
        )

    if decommission.extension_requested_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This decommission already has an extension request on record — "
            "cancel this decommission and raise a new one instead",
        )

    until_utc = _utc(until)
    current_teardown = _utc(decommission.scheduled_teardown_at)
    if until_utc <= current_teardown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "until must be strictly later than the current "
            "scheduled_teardown_at, or this would shorten the notice period",
        )

    decommission.extension_requested_at = now
    decommission.extension_requested_by = user.id
    decommission.extension_reason = reason.strip()
    decommission.extension_until = until

    await db.flush()
    await db.refresh(decommission)
    return decommission


async def decide_extension(
    db: AsyncSession,
    decommission: EnvironmentDecommission,
    user: User,
    *,
    granted: bool,
    now: datetime,
) -> EnvironmentDecommission:
    """The operating team's answer. `assert_may_run`: the operating team, or
    an Admin — deliberately NOT the owner, who `request_extension` gates.
    The two helpers are never interchangeable: requesting and deciding gate
    opposite parties, the same split `assert_may_defend`'s own docstring
    describes.

    409 if there is no undecided request (`extension_requested_at` unset, or
    `extension_decided_at` already set — a second decision is refused the
    same way a second request is).

    GRANTING MOVES THE DATE; REFUSING MOVES NOTHING. On grant,
    `scheduled_teardown_at` becomes `extension_until` — that is what makes
    branch 3 of `decommission_state` stop matching and the row fall through
    to `warned` on the caller's clock. Neither branch clears the request
    block: it stays as the audit record of what was asked and decided.
    """
    environment = await get_environment(
        db, decommission.environment_id, decommission.tenant_id
    )
    await assert_may_run(db, environment, user)

    if (
        decommission.extension_requested_at is None
        or decommission.extension_decided_at is not None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "There is no undecided extension request on this decommission",
        )

    decommission.extension_decided_at = now
    decommission.extension_decided_by = user.id
    decommission.extension_granted = granted
    if granted:
        decommission.scheduled_teardown_at = decommission.extension_until

    await db.flush()
    await db.refresh(decommission)
    return decommission


async def _assert_still_live(
    db: AsyncSession, decommission: EnvironmentDecommission, now: datetime
) -> None:
    """Shared by `sign_attestation` and `tear_down`: both act on a decommission
    that must still be LIVE, checked through `live_predicate` rather than
    re-derived, the same way `request_extension` checks it."""
    still_live = (
        await db.execute(
            select(EnvironmentDecommission.id).where(
                EnvironmentDecommission.id == decommission.id,
                EnvironmentDecommission.tenant_id == decommission.tenant_id,
                live_predicate(now),
            )
        )
    ).first()
    if still_live is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This decommission is no longer live — it has been cancelled or "
            "already torn down",
        )


async def missing_required_steps(
    db: AsyncSession, decommission: EnvironmentDecommission
) -> list[str]:
    """The active, required, non-deleted steps for this tenant that this
    decommission has not yet signed.

    ONLY active AND required steps gate: `list_steps(active_only=True)`
    already drops soft-deleted and inactive rows, and the `is_required`
    filter below drops optional ones on top. A retired step (made inactive,
    or soft-deleted) stops gating immediately — that is what stops an
    admin's checklist tidy-up freezing a workflow mid-flight."""
    steps = await environment_lifecycle_policy_service.list_steps(
        db, decommission.tenant_id, active_only=True
    )
    required_keys = [step.key for step in steps if step.is_required]

    signed = set(
        (
            await db.execute(
                select(EnvironmentDecommissionAttestation.step_key).where(
                    EnvironmentDecommissionAttestation.decommission_id == decommission.id,
                    EnvironmentDecommissionAttestation.tenant_id == decommission.tenant_id,
                )
            )
        ).scalars()
    )
    return [key for key in required_keys if key not in signed]


async def sign_attestation(
    db: AsyncSession,
    decommission: EnvironmentDecommission,
    user: User,
    *,
    step_key: str,
    reference: Optional[str],
    notes: Optional[str],
    now: datetime,
) -> EnvironmentDecommissionAttestation:
    """A human confirming one checklist step happened. ORDER OF OPERATIONS:

    resolve the environment (404 across tenants) -> assert_may_run -> 409 if
    the decommission is no longer LIVE -> 422 if `step_key` is not in the
    tenant's CURRENT vocabulary (validated against EVERY non-deleted step,
    active or not — a step that has been retired is still a real step, it
    has simply stopped gating; see `missing_required_steps`) -> 409 on a
    duplicate signature, checked explicitly here first (SELECT-then-INSERT,
    so this is advisory, not the guarantee) -> insert, with the insert itself
    wrapped so a `uq_decommission_step` violation that slips through the
    SELECT — two signatures on the same step racing each other — still comes
    back as the same clean 409 rather than an unhandled IntegrityError.
    """
    environment = await get_environment(
        db, decommission.environment_id, decommission.tenant_id
    )
    await assert_may_run(db, environment, user)
    await _assert_still_live(db, decommission, now)

    steps = await environment_lifecycle_policy_service.list_steps(
        db, decommission.tenant_id, active_only=False
    )
    known_keys = {step.key for step in steps}
    if step_key not in known_keys:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{step_key!r} is not a recognised decommission step for this tenant",
        )

    duplicate = (
        await db.execute(
            select(EnvironmentDecommissionAttestation.id).where(
                EnvironmentDecommissionAttestation.decommission_id == decommission.id,
                EnvironmentDecommissionAttestation.tenant_id == decommission.tenant_id,
                EnvironmentDecommissionAttestation.step_key == step_key,
            )
        )
    ).first()
    if duplicate is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{step_key!r} has already been signed on this decommission",
        )

    row = EnvironmentDecommissionAttestation(
        tenant_id=decommission.tenant_id,
        decommission_id=decommission.id,
        step_key=step_key,
        signed_by=user.id,
        signed_at=now,
        reference=reference,
        notes=notes,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{step_key!r} has already been signed on this decommission",
        )
    await db.refresh(row)
    return row


async def tear_down(
    db: AsyncSession, decommission: EnvironmentDecommission, user: User, *, now: datetime
) -> EnvironmentDecommission:
    """THE ONE ACTING STEP in the whole of B5, besides Task 8's booking
    refusal. ORDER OF OPERATIONS: resolve the environment (404 across
    tenants) -> assert_may_run -> 409 if the decommission is no longer LIVE
    -> 422 NAMING every still-missing required step -> set
    `torn_down_at`/`torn_down_by` AND `environment.status =
    EnvironmentStatus.DECOMMISSIONED`.

    NOTHING ELSE MOVES. No booking is cancelled, transitioned, shortened or
    deleted, and no other environment is touched — this function stays
    exactly this small so that reading it is the proof, and Task 15 ships a
    guard test asserting it.
    """
    environment = await get_environment(
        db, decommission.environment_id, decommission.tenant_id
    )
    await assert_may_run(db, environment, user)
    await _assert_still_live(db, decommission, now)

    missing = await missing_required_steps(db, decommission)
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Every required step must be signed before teardown. Still "
            "missing: " + ", ".join(missing),
        )

    decommission.torn_down_at = now
    decommission.torn_down_by = user.id
    environment.status = EnvironmentStatus.DECOMMISSIONED

    await db.flush()
    await db.refresh(decommission)
    return decommission


async def cancel(
    db: AsyncSession,
    decommission: EnvironmentDecommission,
    user: User,
    *,
    reason: str,
    now: datetime,
) -> EnvironmentDecommission:
    """THE ESCAPE HATCH. Gated by `assert_may_run` — the operating team, or
    Admin/master admin — the same helper every other action here uses; Admin
    is always a bypass on it, which is what makes cancel "always available
    to Admin" true without a second, separate check.

    Deliberately NOT restricted to a LIVE row: `decommission_state` puts
    cancelled ahead of torn down precisely because someone may need to
    cancel a mistaken teardown after it already happened. The only thing
    refused here is cancelling an ALREADY-cancelled row.

    TOUCHES NOTHING ELSE. In particular this must never read or write
    `environment.status` — an environment whose decommission is cancelled
    was never decommissioned, even if it had already been torn down.
    """
    environment = await get_environment(
        db, decommission.environment_id, decommission.tenant_id
    )
    await assert_may_run(db, environment, user)

    if decommission.cancelled_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This decommission has already been cancelled"
        )

    if reason is None or not reason.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A reason is required — a cancellation with no stated reason is "
            "not an audit record",
        )

    decommission.cancelled_at = now
    decommission.cancelled_by = user.id
    decommission.cancel_reason = reason.strip()

    await db.flush()
    await db.refresh(decommission)
    return decommission


# ===========================================================================
# The worklist: GET /decommissions across every environment in the tenant.
# Follows contention_service's worklist half — a table, a batch view builder,
# and no gate of its own beyond tenant scoping (readable by any tenant
# member; who may ACT on a row is settled on the action routes above).
# ===========================================================================


DECOMMISSION_SORTS = {
    "scheduled_teardown_at": EnvironmentDecommission.scheduled_teardown_at,
    "warned_at": EnvironmentDecommission.warned_at,
    "environment": Environment.name,
}
# `state` is deliberately NOT in this whitelist. It is computed from three
# columns and a clock, not backed by a single column to ORDER BY — whitelisting
# it would 500 on a bare `?sort_by=state` the moment apply_sort tried to sort
# by it.


def worklist_query(
    tenant_id: int,
    *,
    now: datetime,
    sort: Optional[Sort] = None,
    state: Optional[str] = None,
):
    """The worklist query, EXPOSED so its ORDER BY can be asserted directly —
    the same seam `contention_service.worklist_query` and
    `environment_health_service.history_query` exist for: the tiebreaker
    cannot always be guarded behaviourally (a fixture's rows may happen to
    come back in a stable order without it), so this is the documented
    exception to the don't-assert-emitted-SQL rule.

    `state_predicate` DELIBERATELY DOES NOT FILTER `deleted_at` — that is
    `live_predicate`'s job, answering "is this decommission still live", a
    different question from the worklist's "does this row exist at all". This
    is the thing Task 4's reviewer flagged this task would trip over if the
    filter were forgotten here, so it is applied explicitly rather than folded
    into `state_predicate` itself.

    Joined to `Environment` (not merely filtered by `tenant_id` on
    `EnvironmentDecommission`) so `sort_by=environment` has a column to sort
    by — `DECOMMISSION_SORTS["environment"]` is `Environment.name`, and
    `apply_sort` needs that table present in the query's FROM clause.
    """
    D = EnvironmentDecommission
    query = (
        select(D)
        .join(Environment, Environment.id == D.environment_id)
        .where(D.tenant_id == tenant_id, D.deleted_at.is_(None))
    )
    if state is not None:
        query = query.where(state_predicate(state, now))
    # Chained AFTER apply_sort, never instead of it: none of the three
    # sortable columns is unique (scheduled_teardown_at ties are ordinary — a
    # batch of environments decommissioned together shares one date), and
    # LIMIT/OFFSET over a partial order duplicates and drops rows across pages
    # once ties exist.
    return apply_sort(query, sort).order_by(D.id)


async def list_decommissions(
    db: AsyncSession,
    tenant_id: int,
    *,
    state: Optional[str] = None,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
    now: datetime,
) -> tuple[list[EnvironmentDecommission], int]:
    """The worklist: every decommission this tenant can see — live and
    terminal alike, following `contention_service.list_escalations` (an
    escalation outlives its bookings; a decommission's history is as much the
    record as its live state, and nothing here filters on liveness).

    `state` is filtered IN SQL, before the window — a Python-side filter would
    window the unfiltered set first and leave `X-Total-Count` describing it,
    the only evidence from outside that the filter really ran in the query.
    `now` decides both this filter and every row's rendered state
    (`decommission_views` below) — taken ONCE by the caller (the route) and
    threaded through both, never re-read here.
    """
    return await fetch_page(
        db, worklist_query(tenant_id, now=now, sort=sort, state=state), page
    )


async def _usernames_for(db: AsyncSession, user_ids: Iterable[int]) -> dict[int, str]:
    """`user id -> username`. Mirrors `contention_service.usernames_for` —
    same trap, in batch form, in the sibling worklist this codebase now has
    two of: DELIBERATELY NOT TENANT-QUALIFIED. Under master-admin
    impersonation `initiated_by` may legitimately sit outside the row's own
    `tenant_id`, and a `User.tenant_id ==` join here would render that
    initiator as nobody — the same governance-trail loss A3's ack lost to
    exactly that join. Not a leak: the caller's authority to see this row was
    already settled by the tenant-filtered worklist query that produced it,
    and a username discloses nothing the row's own `initiated_by` column does
    not already.
    """
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    ).all()
    return {uid: username for uid, username in rows}


class _EnvironmentLabel(NamedTuple):
    name: str
    owner_user_id: Optional[int]


async def _environment_labels(
    db: AsyncSession, environment_ids: Iterable[int], tenant_id: int
) -> dict[int, "_EnvironmentLabel"]:
    """`environment id -> (name, owner_user_id)`, for a whole page in one
    query. READ-RENDERING, following `environment_service.get_environment_names`
    — deliberately does NOT filter `deleted_at`: a decommission against an
    environment that is itself now soft-deleted must still render that
    environment's name, not fall back to '#N'. Tenant-qualified, matching that
    function, so a malformed cross-tenant row resolves to nothing rather than
    leaking another tenant's environment name.
    """
    ids = {e for e in environment_ids if e is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                Environment.id, Environment.name, Environment.owner_user_id
            ).where(Environment.id.in_(ids), Environment.tenant_id == tenant_id)
        )
    ).all()
    return {
        env_id: _EnvironmentLabel(name, owner_id)
        for env_id, name, owner_id in rows
    }


class DecommissionView(NamedTuple):
    """One decommission plus everything a worklist row needs that is not a
    column: the computed state, and the three names resolved server-side so
    the browser never has to `.find()` one out of a capped picker collection
    (docs/pagination.md)."""

    decommission: EnvironmentDecommission
    state: str
    environment_name: Optional[str]
    initiated_by_username: Optional[str]
    owner_username: Optional[str]


async def decommission_views(
    db: AsyncSession,
    rows: Iterable[EnvironmentDecommission],
    tenant_id: int,
    now: datetime,
) -> dict[int, DecommissionView]:
    """`decommission id -> DecommissionView`, for a whole page in a fixed
    number of queries. BATCH, NEVER PER ROW — the N+1 shape three sub-projects
    have now had to undo on the contention conflicts endpoint.
    """
    rows = list(rows)
    if not rows:
        return {}
    env_labels = await _environment_labels(
        db, {row.environment_id for row in rows}, tenant_id
    )
    usernames = await _usernames_for(
        db,
        [row.initiated_by for row in rows]
        + [label.owner_user_id for label in env_labels.values()],
    )
    return {
        row.id: DecommissionView(
            decommission=row,
            state=decommission_state(row, now),
            environment_name=(
                env_labels[row.environment_id].name
                if row.environment_id in env_labels
                else None
            ),
            initiated_by_username=usernames.get(row.initiated_by),
            owner_username=(
                usernames.get(env_labels[row.environment_id].owner_user_id)
                if row.environment_id in env_labels
                else None
            ),
        )
        for row in rows
    }
