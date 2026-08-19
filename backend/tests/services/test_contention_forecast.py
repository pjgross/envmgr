"""B6 Task 1 — the overlap query. Task 2 — the fold into one state. READS ONLY."""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.contention_escalation import ContentionEscalation
from app.services import contention_forecast_service as svc
from app.services import contention_service
from tests.factories import ensure_environment, ensure_user, make_booking

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
FUTURE_DEADLINE = NOW + timedelta(days=7)
PAST_DEADLINE = NOW - timedelta(days=7)


@pytest.mark.asyncio
async def test_two_overlapping_bookings_are_one_normalised_pair(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW + timedelta(days=1), end=NOW + timedelta(days=4))

    pairs = await svc.overlapping_pairs(db_session, tenant.id)

    assert pairs == [(min(a.id, b.id), max(a.id, b.id))]


@pytest.mark.asyncio
async def test_bookings_on_different_environments_do_not_contend(db_session, tenant):
    e1 = await ensure_environment(db_session, tenant.id, slot=1)
    e2 = await ensure_environment(db_session, tenant.id, slot=2)
    user = await ensure_user(db_session, tenant.id)
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=e1,
                        start=NOW, end=NOW + timedelta(days=3))
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=e2,
                        start=NOW, end=NOW + timedelta(days=3))

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_touching_bookings_do_not_overlap(db_session, tenant):
    """Half-open [start, end) — one ending exactly as the other starts is not a
    clash. The same convention conflict_service uses."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=1))
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW + timedelta(days=1), end=NOW + timedelta(days=2))

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_a_rejected_booking_does_not_contend(db_session, tenant):
    """TERMINAL_STATES is {rejected, closed} — and DRAFTS ARE NOT IN IT, so a
    draft DOES contend. That is conflict_service's rule and B6 must not invent
    a different one."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=3))
    dead = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                               start=NOW, end=NOW + timedelta(days=3))
    dead.status = "rejected"
    await db_session.flush()

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_a_draft_booking_does_contend(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b.status = "draft"
    await db_session.flush()

    assert await svc.overlapping_pairs(db_session, tenant.id) == [
        (min(a.id, b.id), max(a.id, b.id))
    ]


@pytest.mark.asyncio
async def test_a_soft_deleted_booking_does_not_contend(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=3))
    gone = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                               start=NOW, end=NOW + timedelta(days=3))
    gone.deleted_at = NOW
    await db_session.flush()

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_another_tenants_bookings_never_pair(db_session, tenant, test_tenant):
    """Both sides must be in the tenant. A pair spanning two tenants is not a
    contention, it is a bug in whatever created it.

    There is no `other_tenant` fixture in conftest.py, so this uses `tenant`
    and `test_tenant` — two genuinely different tenants ("Phase3 Org" and
    "Test Org" respectively, per their docstrings), each with its own
    environment and pair of overlapping bookings.
    """
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW + timedelta(days=1), end=NOW + timedelta(days=4))

    other_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    other_user = await ensure_user(db_session, test_tenant.id)
    await make_booking(db_session, test_tenant.id, booked_by=other_user.id, environment=other_env,
                        start=NOW, end=NOW + timedelta(days=3))
    await make_booking(db_session, test_tenant.id, booked_by=other_user.id, environment=other_env,
                        start=NOW + timedelta(days=1), end=NOW + timedelta(days=4))

    pairs = await svc.overlapping_pairs(db_session, tenant.id)

    assert pairs == [(min(a.id, b.id), max(a.id, b.id))]


@pytest.mark.asyncio
async def test_only_one_side_need_be_in_the_requested_set(db_session, tenant):
    """LOAD-BEARING. A booking shown in September may clash with one running
    August to October that the calendar never renders. Requiring both sides in
    the set would hide exactly the long-running bookings most likely to
    collide."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    september = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                                    start=NOW, end=NOW + timedelta(days=2))
    spanning = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                                   start=NOW - timedelta(days=40),
                                   end=NOW + timedelta(days=40))

    pairs = await svc.overlapping_pairs(db_session, tenant.id, booking_ids=[september.id])

    assert pairs == [(min(september.id, spanning.id), max(september.id, spanning.id))]


@pytest.mark.asyncio
async def test_each_pair_appears_once_not_twice(db_session, tenant):
    """`b1.id < b2.id` normalises. Without it every clash is reported twice and
    the horizon count doubles."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=3))
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=3))

    assert len(await svc.overlapping_pairs(db_session, tenant.id)) == 1


@pytest.mark.asyncio
async def test_a_soft_deleted_booking_with_the_lower_id_does_not_contend(db_session, tenant):
    """Same rule as test_a_soft_deleted_booking_does_not_contend, but the
    excluded booking is created FIRST so it gets the LOWER id and lands in the
    b1 role (b1.id < b2.id puts it there). conflicts_with only filters the
    OTHER (b2) side's liveness, so this is the only shape that exercises
    b1.deleted_at.is_(None) at all — every other test in this file happens to
    create the excluded booking second, where conflicts_with's own filter on
    b2 already hides it regardless of whether the b1-side filter exists."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    gone = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                               start=NOW, end=NOW + timedelta(days=3))
    gone.deleted_at = NOW
    await db_session.flush()
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=3))

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_a_rejected_booking_with_the_lower_id_does_not_contend(db_session, tenant):
    """Same rule as test_a_rejected_booking_does_not_contend, but the excluded
    booking is created FIRST so it gets the LOWER id and lands in the b1 role,
    exercising b1.status.notin_(TERMINAL_STATES) rather than relying on
    conflicts_with's filter on the b2 side."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    dead = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                               start=NOW, end=NOW + timedelta(days=3))
    dead.status = "rejected"
    await db_session.flush()
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=3))

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_another_tenants_booking_with_the_lower_id_does_not_pair(db_session, tenant, test_tenant):
    """Mirrors the two tests above by creating the excluded (other-tenant)
    booking FIRST so it gets the lower id and lands in the b1 role, to check
    whether b1.tenant_id == tenant_id is reachable the same way the liveness
    filters are.

    IT IS NOT, and no fixture can make it so: Environment.id is a global
    primary key, not tenant-scoped, so `test_tenant`'s environment and
    `tenant`'s environment can never share an id. The join condition inside
    conflicts_with (`other.environment_id == environment_id`) already makes a
    cross-tenant pair unreachable regardless of row order or of whether
    b1.tenant_id is present at all — proven below by mutation, not asserted.
    This test is kept because the behaviour it documents (no cross-tenant pair
    when the foreign booking has the lower id) is still true and still worth
    pinning; it just is not the discriminator for this specific filter. See
    the report for the mutation result and Task 9's structural guard as the
    place that filter's necessity is actually carried.
    """
    other_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    other_user = await ensure_user(db_session, test_tenant.id)
    await make_booking(db_session, test_tenant.id, booked_by=other_user.id, environment=other_env,
                        start=NOW, end=NOW + timedelta(days=3))
    await make_booking(db_session, test_tenant.id, booked_by=other_user.id, environment=other_env,
                        start=NOW + timedelta(days=1), end=NOW + timedelta(days=4))

    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW + timedelta(days=1), end=NOW + timedelta(days=4))

    pairs = await svc.overlapping_pairs(db_session, tenant.id)

    assert pairs == [(min(a.id, b.id), max(a.id, b.id))]


@pytest.mark.asyncio
async def test_a_cross_tenant_booking_with_the_lower_id_does_not_pair(db_session, tenant, test_tenant):
    """The earlier `test_another_tenants_booking_with_the_lower_id_does_not_pair`
    could not exercise `b1.tenant_id == tenant_id` because two DIFFERENT
    tenants' environments can never share an `id` (Environment.id is a single
    global primary key) — so the join on `environment_id` already made a
    cross-tenant pair unreachable regardless of that filter.

    This test instead builds the MALFORMED shape that actually exercises it:
    `make_booking(db, tenant_id, *, environment, ...)` takes `tenant_id` and
    `environment` as independent arguments, and nothing in the schema or the
    factory cross-checks that `environment.tenant_id == tenant_id`. So a
    booking can be built whose `tenant_id` is one tenant while its
    `environment_id` points at an environment owned by a DIFFERENT tenant —
    here, a booking recorded under `test_tenant` but pointed at `tenant`'s
    environment, created FIRST so it lands in the b1 role.

    Without `b1.tenant_id == tenant_id`, that malformed row would pass every
    other b1-side filter, join (via `environment_id`) to the second, entirely
    legitimate booking made by `tenant` on its own environment, and be
    reported as a real contention within `tenant`. The filter is what refuses
    it.
    """
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    other_user = await ensure_user(db_session, test_tenant.id)

    malformed = await make_booking(db_session, test_tenant.id, booked_by=other_user.id,
                                    environment=env, start=NOW, end=NOW + timedelta(days=3))
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=3))

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


# ---------------------------------------------------------------------------
# Task 2 — folding each booking's pairs into one actionable state.
# ---------------------------------------------------------------------------


async def _escalate(db_session, tenant, user, a, b, *, respond_by, decided_at=None):
    """A ContentionEscalation on the NORMALISED pair, same shape as
    test_contention_escalation.py's direct-construction tests."""
    lower, higher = contention_service.normalise_pair(a.id, b.id)
    escalation = ContentionEscalation(
        tenant_id=tenant.id,
        booking_id=lower,
        other_booking_id=higher,
        escalated_by=user.id,
        owner_user_id=user.id,
        respond_by=respond_by,
        decided_at=decided_at,
    )
    db_session.add(escalation)
    await db_session.flush()
    return escalation


@pytest.mark.asyncio
async def test_a_clash_with_no_escalation_is_unowned(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [a.id, b.id], now=NOW
    )

    assert states == {a.id: svc.STATE_UNOWNED, b.id: svc.STATE_UNOWNED}


@pytest.mark.asyncio
async def test_an_open_escalation_is_owned(db_session, tenant):
    """A4's `open` — someone owns it and the deadline is running."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    await _escalate(db_session, tenant, user, a, b, respond_by=FUTURE_DEADLINE)

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [a.id, b.id], now=NOW
    )

    assert states == {a.id: svc.STATE_OWNED, b.id: svc.STATE_OWNED}


@pytest.mark.asyncio
async def test_an_expired_escalation_is_still_owned(db_session, tenant):
    """A4's third state renders as `owned`, not a fourth marker: an overdue
    escalation still has a NAMED OWNER who owes an answer. The booking's own
    page says it is overdue."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    escalation = await _escalate(db_session, tenant, user, a, b, respond_by=PAST_DEADLINE)
    # Confirm this really is A4's `expired`, not merely a stale-looking `open`.
    assert contention_service.escalation_state(escalation, NOW) == contention_service.STATE_EXPIRED

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [a.id, b.id], now=NOW
    )

    assert states == {a.id: svc.STATE_OWNED, b.id: svc.STATE_OWNED}


@pytest.mark.asyncio
async def test_an_answered_escalation_is_decided(db_session, tenant):
    """And the pair is STILL reported — A4 moves no booking, so the two
    bookings genuinely still overlap until a human reschedules one."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    a = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                            start=NOW, end=NOW + timedelta(days=3))
    await _escalate(db_session, tenant, user, a, b, respond_by=FUTURE_DEADLINE, decided_at=NOW)

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [a.id, b.id], now=NOW
    )

    assert states == {a.id: svc.STATE_DECIDED, b.id: svc.STATE_DECIDED}


@pytest.mark.asyncio
async def test_an_uncontended_booking_is_absent_from_the_map(db_session, tenant):
    """ABSENT, not a `none` state. A four-valued enum whose fourth value means
    "nothing to say" invites a consumer to render it, and an empty chip reads
    as a state of its own."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    lonely = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                                 start=NOW, end=NOW + timedelta(days=1))

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [lonely.id], now=NOW
    )

    assert states == {}


@pytest.mark.asyncio
async def test_the_most_actionable_state_wins(db_session, tenant):
    """A booking in three contentions shows the one that needs a human:
    unowned beats owned beats decided. Reverse the precedence and this fails."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    hub = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                             start=NOW, end=NOW + timedelta(days=10))
    # one decided, one owned, one unowned — build them with escalations as the
    # three tests above do, then:
    decided_peer = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                                       start=NOW, end=NOW + timedelta(days=1))
    owned_peer = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                                     start=NOW, end=NOW + timedelta(days=1))
    # unowned_peer deliberately gets no escalation at all.
    await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                        start=NOW, end=NOW + timedelta(days=1))

    await _escalate(db_session, tenant, user, hub, decided_peer,
                     respond_by=FUTURE_DEADLINE, decided_at=NOW)
    await _escalate(db_session, tenant, user, hub, owned_peer, respond_by=FUTURE_DEADLINE)

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [hub.id], now=NOW
    )
    assert states[hub.id] == svc.STATE_UNOWNED


@pytest.mark.asyncio
async def test_the_counterpart_outside_the_set_is_not_reported(db_session, tenant):
    """Only requested bookings get a state. The long-running counterpart is
    used to DECIDE the state, not to appear in the answer — otherwise a
    calendar month would render markers on bookings it never drew."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    user = await ensure_user(db_session, tenant.id)
    shown = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                               start=NOW, end=NOW + timedelta(days=2))
    spanning = await make_booking(db_session, tenant.id, booked_by=user.id, environment=env,
                                  start=NOW - timedelta(days=40),
                                  end=NOW + timedelta(days=40))

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [shown.id], now=NOW
    )

    assert set(states) == {shown.id}
    assert spanning.id not in states
