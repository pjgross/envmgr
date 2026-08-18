"""B5 Task 4 — the state is COMPUTED, and its SQL predicate reproduces the same
branch order. Two mechanisms answering one question: every state test asserts
both, because that is the shape this codebase has repeatedly paid for."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.day_boundaries import expiry_boundary
from app.core.decommission_states import (
    STATE_CANCELLED, STATE_DUE, STATE_EXTENSION_REQUESTED, STATE_TORN_DOWN,
    STATE_WARNED, DECOMMISSION_STATES,
)
from app.db.models.environment_decommission import EnvironmentDecommission
from app.services.environment_decommission_service import (
    decommission_state, state_predicate,
)
from tests.factories import ensure_environment, ensure_user

NOW = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


def _row(**kw) -> EnvironmentDecommission:
    base = dict(
        warned_at=NOW - timedelta(days=1),
        scheduled_teardown_at=NOW + timedelta(days=4),
    )
    base.update(kw)
    return EnvironmentDecommission(**base)


def test_a_fresh_decommission_is_warned():
    assert decommission_state(_row(), NOW) == STATE_WARNED


def test_it_becomes_due_once_the_notice_elapses():
    row = _row(scheduled_teardown_at=NOW - timedelta(days=1))
    assert decommission_state(row, NOW) == STATE_DUE


def test_the_teardown_day_itself_is_still_warned():
    """A DEADLINE IS A DAY. At instant precision this reads `due` from one
    minute past midnight on its own teardown day, and ?state=warned then hides
    exactly the rows closest to their deadline — A4's bug, and B2's."""
    row = _row(scheduled_teardown_at=NOW.replace(hour=0, minute=0))
    assert decommission_state(row, NOW) == STATE_WARNED


def test_an_undecided_extension_outranks_the_clock():
    row = _row(
        scheduled_teardown_at=NOW - timedelta(days=1),
        extension_requested_at=NOW - timedelta(hours=2),
    )
    assert decommission_state(row, NOW) == STATE_EXTENSION_REQUESTED


def test_a_decided_extension_falls_through_to_the_clock():
    """Granting MOVES scheduled_teardown_at and LEAVES the block as the record
    of the decision, so branch 3 stops matching and the audit trail survives."""
    row = _row(
        scheduled_teardown_at=NOW + timedelta(days=30),
        extension_requested_at=NOW - timedelta(days=2),
        extension_decided_at=NOW - timedelta(days=1),
        extension_granted=True,
    )
    assert decommission_state(row, NOW) == STATE_WARNED


def test_torn_down_outranks_an_undecided_extension():
    row = _row(
        extension_requested_at=NOW - timedelta(days=2),
        torn_down_at=NOW - timedelta(hours=1),
    )
    assert decommission_state(row, NOW) == STATE_TORN_DOWN


def test_cancelled_outranks_everything():
    row = _row(
        extension_requested_at=NOW - timedelta(days=2),
        torn_down_at=NOW - timedelta(hours=1),
        cancelled_at=NOW - timedelta(minutes=1),
    )
    assert decommission_state(row, NOW) == STATE_CANCELLED


def test_an_unknown_state_raises():
    with pytest.raises(ValueError):
        state_predicate("nonsense", NOW)


@pytest.fixture
async def decommission_fixtures(db_session, tenant):
    """One persisted row per branch, plus two rows straddling the teardown-day
    boundary (`scheduled_teardown_at` at exactly `expiry_boundary(NOW)`, and
    one second before it) — so the parametrised agreement test below proves
    the predicate and the function agree AT the boundary, not just either side
    of it."""
    environment = await ensure_environment(db_session, tenant.id)
    user = await ensure_user(db_session, tenant.id)
    boundary = expiry_boundary(NOW)

    def make(**kw) -> EnvironmentDecommission:
        fields = dict(
            tenant_id=tenant.id,
            environment_id=environment.id,
            reason="B5 task 4 fixture row",
            initiated_by=user.id,
            warned_at=NOW - timedelta(days=1),
            scheduled_teardown_at=NOW + timedelta(days=4),
        )
        fields.update(kw)
        return EnvironmentDecommission(**fields)

    rows = [
        make(),  # warned: fresh, teardown well in the future
        make(scheduled_teardown_at=NOW - timedelta(days=1)),  # due
        make(
            scheduled_teardown_at=NOW - timedelta(days=1),
            extension_requested_at=NOW - timedelta(hours=2),
        ),  # extension_requested: outranks the elapsed clock
        make(
            extension_requested_at=NOW - timedelta(days=2),
            torn_down_at=NOW - timedelta(hours=1),
        ),  # torn_down: outranks the undecided extension
        make(
            extension_requested_at=NOW - timedelta(days=2),
            torn_down_at=NOW - timedelta(hours=1),
            cancelled_at=NOW - timedelta(minutes=1),
        ),  # cancelled: outranks everything
        make(scheduled_teardown_at=boundary),  # boundary, on the day: warned
        make(
            scheduled_teardown_at=boundary - timedelta(seconds=1)
        ),  # boundary, one second before the day: due
    ]
    db_session.add_all(rows)
    await db_session.flush()
    for row in rows:
        await db_session.refresh(row)
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize("state", DECOMMISSION_STATES)
async def test_the_predicate_and_the_function_agree(
    db_session, tenant, state, decommission_fixtures
):
    """One fixture spanning all five branches, including rows ON their boundary
    day. The filter and the rendered chip must not disagree."""
    rows = (
        await db_session.execute(
            select(EnvironmentDecommission).where(
                EnvironmentDecommission.tenant_id == tenant.id,
                state_predicate(state, NOW),
            )
        )
    ).scalars().all()

    selected = {r.id for r in rows}
    computed = {
        r.id for r in decommission_fixtures if decommission_state(r, NOW) == state
    }
    assert selected == computed
