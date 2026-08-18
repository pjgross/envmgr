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
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_

from app.core.day_boundaries import expiry_boundary
from app.core.decommission_states import (
    STATE_CANCELLED, STATE_DUE, STATE_EXTENSION_REQUESTED, STATE_TORN_DOWN,
    STATE_WARNED,
)
from app.db.models.environment_decommission import EnvironmentDecommission


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
