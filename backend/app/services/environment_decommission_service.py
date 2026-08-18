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
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.day_boundaries import expiry_boundary
from app.core.decommission_states import (
    STATE_CANCELLED, STATE_DUE, STATE_EXTENSION_REQUESTED, STATE_TORN_DOWN,
    STATE_WARNED,
)
from app.db.models.environment import Environment
from app.db.models.environment_decommission import EnvironmentDecommission
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
