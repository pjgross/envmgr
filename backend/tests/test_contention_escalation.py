"""A4 task 3: the escalation record — the only thing A4 stores.

A4 ADVISES; IT NEVER ACTS. `test_recording_a_decision_changes_nothing_on_either_booking`
is the guard on that promise for this half of the sub-project: a decision says
which booking a human thinks should give way, and touches neither booking's
status, dates nor lifecycle. Acting on it is the owning team's job, through the
ordinary transition path.

THE STATE IS COMPUTED, NEVER STORED — which is why A4 needs no background job.
`open`, `answered` and `expired` are facts about `respond_by` and `decided_at`,
so the expiry test asserts an expired escalation WITH NOTHING HAVING RUN. If a
status column ever appears, these tests are the ones that should stop it.

KEYED ON THE UNORDERED PAIR. A conflict is symmetric; the record is not. Every
test that can be asked in both directions is asked in both directions, because
half a symmetry is exactly the shape that shipped twice on A2 and once on task 2
of this sub-project — correct code, a rule guarded on one side only, and a later
tidy-up free to break the other half silently.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.db.models.booking import Booking
from app.db.models.contention_escalation import ContentionEscalation
from app.services import conflict_service, contention_service
from app.services.contention_service import (
    STATE_ANSWERED,
    STATE_EXPIRED,
    STATE_OPEN,
    normalise_pair,
)
# The SAME stub the acknowledgement race tests use, imported rather than copied:
# both reproduce one race, and two copies of the seam is how the two ends drift
# apart. It blinds a lookup for ONE call — the re-read inside `insert_or_reread`
# must still see the winning row, or the test proves only that we crash
# differently.
from tests.test_ack_upsert_races import _blind_once
from tests.factories import ensure_environment, ensure_user, make_booking

START = datetime(2026, 3, 1, tzinfo=timezone.utc)
END = datetime(2026, 3, 5, tzinfo=timezone.utc)

NOW = datetime(2026, 2, 1, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=7)
PAST = NOW - timedelta(days=7)


class _NoDatabase:
    """A stand-in that fails loudly if anything touches it.

    "Asks the database nothing" is a claim about a code path, and the only way
    to assert it without inspecting emitted SQL is to hand the function
    something that cannot answer a query. Same device as
    `test_contention_verdict.py`.
    """

    def __getattr__(self, name):  # pragma: no cover - only reached on failure
        raise AssertionError(
            f"the empty-input path must not touch the database (asked for .{name})"
        )


async def _conflicting_pair(db, tenant_id, user_id, slot=1):
    """Two bookings that really are in conflict: one environment, overlapping
    windows, neither in a terminal state.

    Real conflict, not a fabricated one — `create_escalation` composes
    `conflict_service.conflicts_with` (via `_pair_conflict_exists`) rather than
    re-deriving overlap, so a pair built to look conflicting without being so
    would fail for the wrong reason.
    """
    env = await ensure_environment(db, tenant_id, slot=slot)
    a = await make_booking(
        db, tenant_id, booked_by=user_id, environment=env, start=START, end=END
    )
    b = await make_booking(
        db,
        tenant_id,
        booked_by=user_id,
        environment=env,
        start=START + timedelta(days=1),
        end=END + timedelta(days=1),
    )
    return a, b


async def _escalate(db, tenant, user, a, b, *, owner=None, respond_by=FUTURE):
    return await contention_service.create_escalation(
        db,
        booking_id=a.id,
        other_booking_id=b.id,
        owner_user_id=(owner or user).id,
        respond_by=respond_by,
        current_user=user,
        tenant_id=tenant.id,
    )


async def _all_escalations(db):
    return (await db.execute(ContentionEscalation.__table__.select())).all()


# ---------------------------------------------------------------------------
# One contention, one record.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalating_from_either_direction_yields_one_record(
    db_session, test_tenant, test_user
):
    """(A,B) and (B,A) are ONE contention.

    Without normalisation plus the unique constraint, both owners escalating the
    same clash create two records — two owners, two clocks, and a decision
    recorded on whichever one the reader happens to open.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)

    first = await _escalate(db_session, test_tenant, test_user, a, b)
    second = await _escalate(db_session, test_tenant, test_user, b, a)

    assert second.id == first.id
    assert len(await _all_escalations(db_session)) == 1


@pytest.mark.asyncio
async def test_the_stored_pair_is_normalised(db_session, test_tenant, test_user):
    """`booking_id < other_booking_id` however the caller asked.

    Asserted for BOTH call orders over two separate pairs, so a normalisation
    applied on only one branch cannot pass.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    c, d = await _conflicting_pair(db_session, test_tenant.id, test_user.id, slot=2)

    forwards = await _escalate(db_session, test_tenant, test_user, a, b)
    backwards = await _escalate(db_session, test_tenant, test_user, d, c)

    assert (forwards.booking_id, forwards.other_booking_id) == (
        min(a.id, b.id),
        max(a.id, b.id),
    )
    assert (backwards.booking_id, backwards.other_booking_id) == (
        min(c.id, d.id),
        max(c.id, d.id),
    )
    assert forwards.booking_id < forwards.other_booking_id
    assert backwards.booking_id < backwards.other_booking_id


def test_normalise_pair_is_min_max():
    """The primitive itself, both ways round and for the degenerate case."""
    assert normalise_pair(2, 7) == (2, 7)
    assert normalise_pair(7, 2) == (2, 7)
    assert normalise_pair(5, 5) == (5, 5)


@pytest.mark.asyncio
async def test_get_escalation_finds_the_record_from_either_direction(
    db_session, test_tenant, test_user
):
    """A reader holding the pair the other way round must still find it —
    otherwise one of the two owners is told there is no escalation while looking
    at the clash it was raised for."""
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    created = await _escalate(db_session, test_tenant, test_user, a, b)

    forwards = await contention_service.get_escalation(
        db_session, a.id, b.id, test_tenant.id
    )
    backwards = await contention_service.get_escalation(
        db_session, b.id, a.id, test_tenant.id
    )
    assert forwards is not None and forwards.id == created.id
    assert backwards is not None and backwards.id == created.id


@pytest.mark.asyncio
async def test_a_second_escalation_does_not_move_the_first_ones_owner_or_deadline(
    db_session, test_tenant, test_user
):
    """Re-asking returns the record that exists, UNCHANGED.

    Deliberately unlike the two acknowledgement upserts, where the later answer
    wins: an acknowledgement is one person's answer to a question about their
    own booking, whereas an escalation names SOMEONE ELSE as the decider and
    starts a clock against them. Letting the second escalator silently reassign
    the owner and reset the deadline would let either party restart the other's
    clock at will — and, once a decision exists, would quietly re-open it.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    other_owner = await ensure_user(db_session, test_tenant.id, username="second-owner")

    first = await _escalate(db_session, test_tenant, test_user, a, b)
    again = await _escalate(
        db_session,
        test_tenant,
        test_user,
        b,
        a,
        owner=other_owner,
        respond_by=FUTURE + timedelta(days=30),
    )

    assert again.id == first.id
    assert again.owner_user_id == test_user.id
    assert contention_service._utc(again.respond_by) == FUTURE


@pytest.mark.asyncio
async def test_re_escalating_still_returns_the_record_once_the_pair_stops_clashing(
    db_session, test_tenant, test_user
):
    """Re-asking is idempotent for the LIFE of the escalation, not just while
    the clash lasts.

    Nothing re-checks overlap after creation and the dates are editable, so a
    pair can stop clashing while its escalation is still open and unanswered.
    With the conflict check ahead of the existing-record lookup, the second call
    then 400'd with "these two bookings are not in conflict" about a contention
    the caller is looking at — and a UI that re-posts on a double click would
    show exactly that. The check still guards every NEW record, which is the
    half of it that was doing work.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    first = await _escalate(db_session, test_tenant, test_user, a, b)

    # Move B clear of A, so the pair genuinely no longer overlaps.
    b.start_date = END + timedelta(days=10)
    b.end_date = END + timedelta(days=15)
    await db_session.flush()
    # Non-vacuous: assert the pair really has stopped clashing, or an edit that
    # silently failed to disjoin them would leave this test asserting nothing.
    conflicts, _total = await conflict_service.list_conflicts(
        db_session, a.id, test_tenant.id
    )
    assert b.id not in {row.booking.id for row in conflicts}

    again = await _escalate(db_session, test_tenant, test_user, b, a)

    assert again.id == first.id
    assert len(await _all_escalations(db_session)) == 1


@pytest.mark.asyncio
async def test_a_pair_that_never_clashed_still_cannot_be_escalated_afresh(
    db_session, test_tenant, test_user
):
    """The other half of the reordering above, stated separately.

    Returning an EXISTING record early must not weaken the check on a NEW one —
    the conflict check has simply moved behind the lookup, not gone.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    early = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=START, end=END,
    )
    late = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=END + timedelta(days=1), end=END + timedelta(days=5),
    )

    with pytest.raises(HTTPException) as excinfo:
        await _escalate(db_session, test_tenant, test_user, early, late)
    assert excinfo.value.status_code == 400
    assert len(await _all_escalations(db_session)) == 0


@pytest.mark.asyncio
async def test_uq_contention_pair_refuses_a_second_row_for_the_same_pair(
    db_session, test_tenant, test_user
):
    """THE CONSTRAINT ITSELF, with no stub and no `insert_or_reread`.

    `test_a_lost_create_race_records_one_escalation` was the only thing that
    failed when `uq_contention_pair` was removed — so deleting or rewriting that
    test would silently unguard the constraint too, and the constraint is the
    only thing that makes a second record for one contention IMPOSSIBLE rather
    than merely unlikely. This asserts the database refuses it; the race test
    then guards the RECOVERY, which is a different question.

    The insert runs inside a savepoint that is rolled back, because a failed
    flush leaves the session in a pending-rollback state on both engines and
    poisons the transaction outright on PostgreSQL — the same reason
    `app/core/upsert.py` uses one.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    lower, higher = normalise_pair(a.id, b.id)

    def _row():
        return ContentionEscalation(
            tenant_id=test_tenant.id,
            booking_id=lower,
            other_booking_id=higher,
            escalated_by=test_user.id,
            owner_user_id=test_user.id,
            respond_by=FUTURE,
        )

    savepoint = await db_session.begin_nested()
    db_session.add(_row())
    db_session.add(_row())
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await savepoint.rollback()

    assert len(await _all_escalations(db_session)) == 0


# ---------------------------------------------------------------------------
# The state, computed from two columns and nothing else.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_escalation_awaiting_its_deadline_is_open(
    db_session, test_tenant, test_user
):
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)

    assert escalation.decided_at is None
    assert contention_service.escalation_state(escalation, NOW) == STATE_OPEN


@pytest.mark.asyncio
async def test_a_passed_deadline_with_no_decision_is_expired_with_no_job_having_run(
    db_session, test_tenant, test_user
):
    """NOTHING RAN. No scheduler, no sweep, no status column — the escalation is
    expired because `respond_by` is in the past and `decided_at` is null, and it
    becomes expired the moment the clock passes it."""
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(
        db_session, test_tenant, test_user, a, b, respond_by=PAST
    )

    assert contention_service.escalation_state(escalation, NOW) == STATE_EXPIRED


@pytest.mark.asyncio
async def test_answering_late_is_still_answered(db_session, test_tenant, test_user):
    """THE ORDER OF THE TWO BRANCHES, pinned.

    `decided_at` is tested BEFORE `respond_by`. Reversed, a decision recorded
    after the deadline reads as `expired` — losing the fact that someone did
    decide, and inviting a second escalation of a contention that has an answer.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(
        db_session, test_tenant, test_user, a, b, respond_by=PAST
    )
    assert contention_service.escalation_state(escalation, NOW) == STATE_EXPIRED

    decided = await contention_service.record_decision(
        db_session,
        escalation.id,
        yields_booking_id=a.id,
        notes="late, but decided",
        current_user=test_user,
        tenant_id=test_tenant.id,
    )

    assert contention_service.escalation_state(decided, NOW) == STATE_ANSWERED


@pytest.mark.asyncio
async def test_the_deadline_is_compared_across_engines_without_raising(
    db_session, test_tenant, test_user
):
    """SQLite hands back naive datetimes for `DateTime(timezone=True)` while
    PostgreSQL hands back aware ones, and comparing the two raises TypeError.

    So the state is computed over a RE-READ row, not the one still in the
    identity map with the aware value the caller passed in — that is the only
    shape in which the missing normalisation actually fires, and it fires on one
    engine only.

    THIS GUARD IS BLIND ON POSTGRESQL, and measured rather than assumed:
    dropping `_utc` from `escalation_state` fails this test on SQLite and leaves
    all 53 green on the PostgreSQL leg, because that engine hands back aware
    values and the comparison simply works. The mirror image of the usual
    SQLite-cannot-see-this class — so a green PostgreSQL-only run is not
    evidence the normalisation is present.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)
    # Expire THIS ROW only, not the whole session: `expire_all` would also
    # expire the fixtures, and touching an expired ORM attribute from async
    # code raises MissingGreenlet — a failure with nothing to do with time
    # zones.
    db_session.expire(escalation)
    reread = await contention_service.get_escalation(
        db_session, a.id, b.id, test_tenant.id
    )

    assert contention_service.escalation_state(reread, NOW) == STATE_OPEN


class _FabricatedRow:
    """Just the two columns `escalation_state` reads.

    `escalation_state` is a PURE FUNCTION, so the naive/aware hazard can be put
    to it directly instead of via an engine that happens to produce naive values
    — which is what makes the two tests below fail on BOTH engines, unlike the
    round-trip test above. Not a substitute for it: that one is the only thing
    asserting SQLite really does hand back naive values in the first place.
    """

    def __init__(self, respond_by, decided_at=None):
        self.respond_by = respond_by
        self.decided_at = decided_at


def test_escalation_state_normalises_a_naive_respond_by():
    """The STORED side, fabricated naive exactly as SQLite returns it.

    Both outcomes are asserted, so the guard cannot be satisfied by a function
    that stopped comparing at all.
    """
    assert contention_service.escalation_state(
        _FabricatedRow(FUTURE.replace(tzinfo=None)), NOW
    ) == STATE_OPEN
    assert contention_service.escalation_state(
        _FabricatedRow(PAST.replace(tzinfo=None)), NOW
    ) == STATE_EXPIRED


def test_escalation_state_normalises_a_naive_now():
    """The CALLER'S side. `now` comes from whoever is rendering the row, and
    `datetime.utcnow()` — naive — is the historically easy mistake in this
    package. Unnormalised it raises TypeError from a READ path on both engines,
    500-ing every row of a list with a traceback nowhere near the call site that
    chose the wrong clock.
    """
    naive_now = NOW.replace(tzinfo=None)
    assert contention_service.escalation_state(
        _FabricatedRow(FUTURE), naive_now
    ) == STATE_OPEN
    assert contention_service.escalation_state(
        _FabricatedRow(PAST), naive_now
    ) == STATE_EXPIRED


# ---------------------------------------------------------------------------
# The answer.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_a_decision_stores_who_decided_what_and_when(
    db_session, test_tenant, test_user
):
    """All four columns, and the decider is the CALLER — not the owner the
    escalation named, who may well have handed it to someone else."""
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    owner = await ensure_user(db_session, test_tenant.id, username="named-owner")
    escalation = await _escalate(db_session, test_tenant, test_user, a, b, owner=owner)

    before = datetime.now(timezone.utc)
    decided = await contention_service.record_decision(
        db_session,
        escalation.id,
        yields_booking_id=b.id,
        notes="B can move to the following week",
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    after = datetime.now(timezone.utc)

    assert decided.decision_yields_booking_id == b.id
    assert decided.decision_notes == "B can move to the following week"
    assert decided.decided_by == test_user.id
    assert decided.owner_user_id == owner.id
    assert decided.decided_at is not None
    assert before <= contention_service._utc(decided.decided_at) <= after


@pytest.mark.asyncio
async def test_recording_a_decision_changes_nothing_on_either_booking(
    db_session, test_tenant, test_user
):
    """A4 ADVISES; IT NEVER ACTS.

    The one guard on the promise. A decision is a recorded opinion about which
    booking should give way; moving it is the owning team's job, through the
    ordinary transition path. That matters for A2 group bookings especially —
    the team moves its whole group atomically, and A4 must never reach inside
    one.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)
    a_id, b_id = a.id, b.id

    async def _stored_bookings():
        """Read the two rows BACK FROM THE DATABASE, not off the ORM objects.

        A decision that silently transitioned a booking through the service
        would leave the in-memory object as the test remembers it on some
        paths; and reading the same source before and after is also what keeps
        the comparison free of the naive/aware difference between engines.
        """
        rows = (await db_session.execute(
            Booking.__table__.select().where(Booking.id.in_([a_id, b_id]))
        )).all()
        return {
            row.id: (row.status, row.start_date, row.end_date, row.deleted_at,
                     row.environment_id, row.booking_request_id)
            for row in rows
        }

    before = await _stored_bookings()

    await contention_service.record_decision(
        db_session,
        escalation.id,
        yields_booking_id=b_id,
        notes=None,
        current_user=test_user,
        tenant_id=test_tenant.id,
    )

    assert await _stored_bookings() == before


@pytest.mark.asyncio
async def test_a_decision_naming_a_booking_outside_the_pair_is_refused(
    db_session, test_tenant, test_user
):
    """400. A decision that names a third booking is not a decision about this
    contention, and storing it would put an id in `decision_yields_booking_id`
    that no reader of the pair can explain."""
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    stranger, _ = await _conflicting_pair(
        db_session, test_tenant.id, test_user.id, slot=2
    )
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)

    with pytest.raises(HTTPException) as excinfo:
        await contention_service.record_decision(
            db_session,
            escalation.id,
            yields_booking_id=stranger.id,
            notes=None,
            current_user=test_user,
            tenant_id=test_tenant.id,
        )
    assert excinfo.value.status_code == 400

    # Nothing was recorded: a refused decision must not leave a half-answered
    # escalation, which `escalation_state` would report as `answered`.
    db_session.expire(escalation)
    still = await contention_service.get_escalation(
        db_session, a.id, b.id, test_tenant.id
    )
    assert still.decided_at is None
    assert contention_service.escalation_state(still, NOW) == STATE_OPEN


@pytest.mark.asyncio
async def test_either_member_of_the_pair_may_be_named_as_yielding(
    db_session, test_tenant, test_user
):
    """BOTH SIDES of the membership check.

    The pair is stored normalised, so a check written against `booking_id`
    alone accepts one member and refuses the other — and would refuse it for
    whichever booking happened to be given the higher id, which is invisible in
    a test that only ever names one of them.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    c, d = await _conflicting_pair(db_session, test_tenant.id, test_user.id, slot=2)
    first = await _escalate(db_session, test_tenant, test_user, a, b)
    second = await _escalate(db_session, test_tenant, test_user, c, d)

    lower = await contention_service.record_decision(
        db_session,
        first.id,
        yields_booking_id=first.booking_id,
        notes=None,
        current_user=test_user,
        tenant_id=test_tenant.id,
    )
    higher = await contention_service.record_decision(
        db_session,
        second.id,
        yields_booking_id=second.other_booking_id,
        notes=None,
        current_user=test_user,
        tenant_id=test_tenant.id,
    )

    assert lower.decision_yields_booking_id == first.booking_id
    assert higher.decision_yields_booking_id == second.other_booking_id


# ---------------------------------------------------------------------------
# What may be escalated.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalating_a_pair_that_is_not_in_conflict_is_refused(
    db_session, test_tenant, test_user
):
    """400, and the pair really does not overlap — same environment, disjoint
    windows. An escalation of a contention that does not exist has no answer to
    record and no clash for the decider to look at."""
    env = await ensure_environment(db_session, test_tenant.id)
    early = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=START, end=END,
    )
    late = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=END + timedelta(days=1), end=END + timedelta(days=5),
    )

    with pytest.raises(HTTPException) as excinfo:
        await _escalate(db_session, test_tenant, test_user, early, late)
    assert excinfo.value.status_code == 400
    assert len(await _all_escalations(db_session)) == 0


@pytest.mark.asyncio
async def test_escalating_a_pair_that_is_not_in_conflict_is_refused_either_way_round(
    db_session, test_tenant, test_user
):
    """The overlap question is symmetric, and so is the refusal.

    `conflicts_with` (via `_pair_conflict_exists`) is asked about ONE of the
    two bookings, so a pair checked from one side only would depend on which
    id the caller passed first.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    early = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=START, end=END,
    )
    late = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=END + timedelta(days=1), end=END + timedelta(days=5),
    )

    with pytest.raises(HTTPException) as excinfo:
        await _escalate(db_session, test_tenant, test_user, late, early)
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_a_pair_is_refused_when_the_named_counterparty_is_not_the_one_clashing(
    db_session, test_tenant, test_user
):
    """The check is a MEMBERSHIP question, not "does this booking clash at all".

    Composing `conflicts_with` into an EXISTS is only equivalent to asking
    `list_conflicts` and testing `higher in {...}` while the EXISTS pins the
    counterparty's id. Without that, a booking with ANY clash on its environment
    could be escalated against a booking it does not overlap — and the two
    innocent-looking spellings differ only on an environment holding three
    bookings, which no other test in this file builds.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    subject = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=START, end=END,
    )
    # A real clash for `subject`, so the EXISTS has something to find.
    await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=START + timedelta(days=1), end=END + timedelta(days=1),
    )
    # The booking actually named — same environment, disjoint window.
    bystander = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=END + timedelta(days=10), end=END + timedelta(days=15),
    )

    for pair in ((subject, bystander), (bystander, subject)):
        with pytest.raises(HTTPException) as excinfo:
            await _escalate(db_session, test_tenant, test_user, *pair)
        assert excinfo.value.status_code == 400
    assert len(await _all_escalations(db_session)) == 0


@pytest.mark.asyncio
async def test_a_terminal_booking_has_no_contention_to_escalate(
    db_session, test_tenant, test_user
):
    """400, from BOTH positions of the pair.

    A booking in a terminal state has no conflicts by definition — that is what
    `list_conflicts` says about its own subject, and what `conflicts_with` says
    about the counterparty. The two are separate filters on separate rows, so
    each side needs asking: the counterparty's lives inside `conflicts_with`,
    and the subject's is the only one this service has to carry itself.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    a.status = "closed"
    await db_session.flush()

    for pair in ((a, b), (b, a)):
        with pytest.raises(HTTPException) as excinfo:
            await _escalate(db_session, test_tenant, test_user, *pair)
        assert excinfo.value.status_code == 400
    assert len(await _all_escalations(db_session)) == 0


@pytest.mark.asyncio
async def test_escalating_a_soft_deleted_booking_is_404_whichever_id_it_holds(
    db_session, test_tenant, test_user
):
    """BOTH ID ORDERINGS, because one of them used to be fine.

    The overlap question is asked of ONE booking about the other, and the two
    positions are not symmetric: `conflicts_with` filters the counterparty's
    `deleted_at`, and the subject's has to be filtered separately. While the
    visibility check hung off the "no conflict" branch only, a pair whose
    LOWER-id member was soft-deleted sailed through — `list_conflicts` does not
    filter its subject's `deleted_at`, so the deleted booking still reported the
    live one as a clash — and an escalation was created against a deleted
    booking, naming an owner and starting a clock, with no withdraw path to
    remove it. The identical situation with the HIGHER-id member deleted was a
    clean 404. Two identical situations, two outcomes, decided by an id ordering
    no user can see.

    Reachable from the ordinary UI: a booking is cancelled while someone has the
    conflicts page open, and they click Escalate.
    """
    lower_deleted_a, lower_deleted_b = await _conflicting_pair(
        db_session, test_tenant.id, test_user.id, slot=1
    )
    higher_deleted_c, higher_deleted_d = await _conflicting_pair(
        db_session, test_tenant.id, test_user.id, slot=2
    )
    # `_conflicting_pair` creates the first booking first, so the first of each
    # tuple holds the lower id — asserted rather than assumed, because the whole
    # point of this test is which side is deleted.
    assert lower_deleted_a.id < lower_deleted_b.id
    assert higher_deleted_c.id < higher_deleted_d.id

    lower_deleted_a.deleted_at = datetime.now(timezone.utc)
    higher_deleted_d.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    for first, second in (
        (lower_deleted_a, lower_deleted_b),
        (lower_deleted_b, lower_deleted_a),
        (higher_deleted_c, higher_deleted_d),
        (higher_deleted_d, higher_deleted_c),
    ):
        with pytest.raises(HTTPException) as excinfo:
            await _escalate(db_session, test_tenant, test_user, first, second)
        assert excinfo.value.status_code == 404

    assert len(await _all_escalations(db_session)) == 0


@pytest.mark.asyncio
async def test_bookings_in_different_environments_are_not_a_contention(
    db_session, test_tenant, test_user
):
    """Overlapping in time is not enough — a contention is a clash over one
    environment, and `conflicts_with` is the single definition of that."""
    a = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id,
        environment=await ensure_environment(db_session, test_tenant.id, slot=1),
        start=START, end=END,
    )
    b = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id,
        environment=await ensure_environment(db_session, test_tenant.id, slot=2),
        start=START, end=END,
    )

    with pytest.raises(HTTPException) as excinfo:
        await _escalate(db_session, test_tenant, test_user, a, b)
    assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# Tenant scoping. Assume every tenant filter is unguarded until a named test
# fails without it. Cross-tenant is 404, NEVER 403.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalating_another_tenants_bookings_is_404_not_400(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """A booking that is not ours must not be confirmed to exist — and must not
    be described as "not in conflict" either, which is a claim about a row the
    caller cannot see and would be false besides: the other tenant's two
    bookings genuinely do clash.
    """
    other_tenant, other_admin = await second_tenant_factory()
    theirs_a, theirs_b = await _conflicting_pair(
        db_session, other_tenant.id, other_admin.id
    )

    with pytest.raises(HTTPException) as excinfo:
        await contention_service.create_escalation(
            db_session,
            booking_id=theirs_a.id,
            other_booking_id=theirs_b.id,
            owner_user_id=test_user.id,
            respond_by=FUTURE,
            current_user=test_user,
            tenant_id=test_tenant.id,
        )
    assert excinfo.value.status_code == 404
    assert len(await _all_escalations(db_session)) == 0


@pytest.mark.asyncio
async def test_escalating_one_of_our_bookings_against_another_tenants_is_404(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """The second booking is checked too, in both positions.

    A check on the subject alone leaves the counterparty unvalidated, and the
    record would then name a booking from a tenant the reader cannot open.
    """
    other_tenant, other_admin = await second_tenant_factory()
    ours, _ = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    theirs, _ = await _conflicting_pair(db_session, other_tenant.id, other_admin.id)

    for pair in ((ours, theirs), (theirs, ours)):
        with pytest.raises(HTTPException) as excinfo:
            await _escalate(db_session, test_tenant, test_user, *pair)
        assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_an_owner_from_another_tenant_is_refused(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """404 — `owner_user_id` is a client-supplied foreign key, the IDOR-class
    shape the 2026-07-16 isolation audit found four of. Naming another tenant's
    user as the decider would put a person who cannot see the contention on the
    hook for it."""
    other_tenant, other_admin = await second_tenant_factory()
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)

    with pytest.raises(HTTPException) as excinfo:
        await contention_service.create_escalation(
            db_session,
            booking_id=a.id,
            other_booking_id=b.id,
            owner_user_id=other_admin.id,
            respond_by=FUTURE,
            current_user=test_user,
            tenant_id=test_tenant.id,
        )
    assert excinfo.value.status_code == 404
    assert len(await _all_escalations(db_session)) == 0


@pytest.mark.asyncio
async def test_re_asking_with_a_cross_tenant_owner_returns_the_existing_record_unchanged(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """200, not 404 — deliberately, and pinned so it cannot drift back.

    The re-ask path returns the EXISTING record before `owner_user_id` is ever
    looked at (see the comment on the `existing` early return in
    `create_escalation`), so once a record exists, a cross-tenant — or simply
    nonexistent — owner id on a second call is silently ignored rather than
    validated. That is acceptable: nothing is created or reassigned from it,
    and the response carries the record's TRUE owner, not the one just
    supplied, so nothing is leaked and nothing needs correcting.
    """
    other_tenant, other_admin = await second_tenant_factory()
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)

    first = await _escalate(db_session, test_tenant, test_user, a, b)

    again = await contention_service.create_escalation(
        db_session,
        booking_id=b.id,
        other_booking_id=a.id,
        owner_user_id=other_admin.id,
        respond_by=FUTURE,
        current_user=test_user,
        tenant_id=test_tenant.id,
    )

    assert again.id == first.id
    assert again.owner_user_id == test_user.id


@pytest.mark.asyncio
async def test_another_tenants_escalation_is_invisible(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """`get_escalation` returns None and `record_decision` raises 404 — never
    403, which would confirm the record exists."""
    other_tenant, other_admin = await second_tenant_factory()
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    ours = await _escalate(db_session, test_tenant, test_user, a, b)

    assert await contention_service.get_escalation(
        db_session, a.id, b.id, other_tenant.id
    ) is None

    with pytest.raises(HTTPException) as excinfo:
        await contention_service.record_decision(
            db_session,
            ours.id,
            yields_booking_id=a.id,
            notes="not theirs to answer",
            current_user=other_admin,
            tenant_id=other_tenant.id,
        )
    assert excinfo.value.status_code == 404

    db_session.expire(ours)
    untouched = await contention_service.get_escalation(
        db_session, a.id, b.id, test_tenant.id
    )
    assert untouched.decided_at is None
    assert untouched.decision_yields_booking_id is None


@pytest.mark.asyncio
async def test_an_escalation_id_that_does_not_exist_is_404(
    db_session, test_tenant, test_user
):
    with pytest.raises(HTTPException) as excinfo:
        await contention_service.record_decision(
            db_session,
            10_000_000,
            yields_booking_id=1,
            notes=None,
            current_user=test_user,
            tenant_id=test_tenant.id,
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_a_soft_deleted_escalation_is_gone(db_session, test_tenant, test_user):
    """Soft deletes, not hard deletes — so every read filters `deleted_at`, and
    a withdrawn escalation neither renders nor accepts an answer."""
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)
    escalation.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    assert await contention_service.get_escalation(
        db_session, a.id, b.id, test_tenant.id
    ) is None
    assert await contention_service.escalations_for_pairs(
        db_session, [(a.id, b.id)], test_tenant.id
    ) == {}
    with pytest.raises(HTTPException) as excinfo:
        await contention_service.record_decision(
            db_session,
            escalation.id,
            yields_booking_id=a.id,
            notes=None,
            current_user=test_user,
            tenant_id=test_tenant.id,
        )
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# The race.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_lost_create_race_records_one_escalation(
    db_session, test_tenant, test_user, monkeypatch
):
    """Two people escalating the same clash at once must both get an answer.

    A genuine two-connection race is not reachable from one test session, so
    this fabricates exactly the state it leaves: the row exists, and our
    pre-read did not see it. Everything downstream of the stub — the insert,
    `uq_contention_pair`, the savepoint, the re-read — is production code
    against a real database, and the assertion is that the caller gets the
    winning record instead of an IntegrityError (a 500 on an ordinary
    governance action) and that there is still exactly ONE row.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    lower, higher = normalise_pair(a.id, b.id)
    # The row the other escalator inserted a moment ago.
    db_session.add(ContentionEscalation(
        tenant_id=test_tenant.id,
        booking_id=lower,
        other_booking_id=higher,
        escalated_by=test_user.id,
        owner_user_id=test_user.id,
        respond_by=FUTURE,
    ))
    await db_session.flush()

    _blind_once(monkeypatch, contention_service, "get_escalation")

    escalation = await _escalate(db_session, test_tenant, test_user, b, a)

    assert (escalation.booking_id, escalation.other_booking_id) == (lower, higher)
    assert len(await _all_escalations(db_session)) == 1

    # The session survives the refused insert — the savepoint's whole job. On
    # PostgreSQL a plain try/except leaves the transaction poisoned and every
    # later statement, including `get_db`'s commit, fails.
    assert await contention_service.get_escalation(
        db_session, a.id, b.id, test_tenant.id
    ) is not None


# ---------------------------------------------------------------------------
# The batch reads.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalations_for_pairs_answers_only_about_the_pairs_it_was_given(
    db_session, test_tenant, test_user
):
    """Keyed by the pair AS GIVEN — the same contract as `verdicts_for_pairs`,
    so a caller can look an escalation up with the tuple it already used for the
    verdict — and a pair with no escalation is simply absent."""
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    c, d = await _conflicting_pair(db_session, test_tenant.id, test_user.id, slot=2)
    escalated = await _escalate(db_session, test_tenant, test_user, a, b)
    await _escalate(db_session, test_tenant, test_user, c, d)

    found = await contention_service.escalations_for_pairs(
        db_session, [(b.id, a.id)], test_tenant.id
    )

    assert set(found) == {(b.id, a.id)}
    assert found[(b.id, a.id)].id == escalated.id
    assert (a.id, b.id) not in found
    assert (c.id, d.id) not in found


@pytest.mark.asyncio
async def test_escalations_for_pairs_reports_a_pair_with_no_escalation_by_omission(
    db_session, test_tenant, test_user
):
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)

    found = await contention_service.escalations_for_pairs(
        db_session, [(a.id, b.id)], test_tenant.id
    )
    assert found == {}


@pytest.mark.asyncio
async def test_escalations_for_pairs_never_returns_another_tenants_record(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """The tenant filter, asserted where it can actually change an answer: the
    pair ids are globally unique, so without it the other tenant's escalation is
    returned to a caller who cannot open either booking."""
    other_tenant, other_admin = await second_tenant_factory()
    theirs_a, theirs_b = await _conflicting_pair(
        db_session, other_tenant.id, other_admin.id
    )
    await contention_service.create_escalation(
        db_session,
        booking_id=theirs_a.id,
        other_booking_id=theirs_b.id,
        owner_user_id=other_admin.id,
        respond_by=FUTURE,
        current_user=other_admin,
        tenant_id=other_tenant.id,
    )

    found = await contention_service.escalations_for_pairs(
        db_session, [(theirs_a.id, theirs_b.id)], test_tenant.id
    )
    assert found == {}


@pytest.mark.asyncio
async def test_an_empty_pair_list_asks_the_database_nothing():
    assert await contention_service.escalations_for_pairs(_NoDatabase(), [], 1) == {}


@pytest.mark.asyncio
async def test_bookings_live_reports_a_live_pair(db_session, test_tenant, test_user):
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)

    live = await contention_service.bookings_live(
        db_session, [escalation], test_tenant.id
    )
    assert live == {escalation.id: True}


@pytest.mark.asyncio
async def test_an_escalation_outlives_its_bookings(
    db_session, test_tenant, test_user
):
    """DELIBERATE: the record survives, and only its liveness changes.

    An escalation is the audit trail of an argument, so soft-deleting a booking
    must not delete the ask or the answer — it must make the pair read as no
    longer live, so a UI can say the contention has gone away rather than
    silently dropping the row.
    """
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)
    b.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    assert await contention_service.get_escalation(
        db_session, a.id, b.id, test_tenant.id
    ) is not None
    live = await contention_service.bookings_live(
        db_session, [escalation], test_tenant.id
    )
    assert live == {escalation.id: False}


@pytest.mark.asyncio
async def test_bookings_live_is_false_once_either_booking_is_terminal(
    db_session, test_tenant, test_user
):
    """Both sides, and BOTH POSITIONS of the pair — a liveness test written
    against one column reports a closed counterparty as still live."""
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    c, d = await _conflicting_pair(db_session, test_tenant.id, test_user.id, slot=2)
    first = await _escalate(db_session, test_tenant, test_user, a, b)
    second = await _escalate(db_session, test_tenant, test_user, c, d)

    # Close the lower-id member of one pair and the higher-id member of the
    # other, so neither column can be the only one consulted.
    lower_of_first = a if a.id < b.id else b
    higher_of_second = c if c.id > d.id else d
    lower_of_first.status = "closed"
    higher_of_second.status = "rejected"
    await db_session.flush()

    live = await contention_service.bookings_live(
        db_session, [first, second], test_tenant.id
    )
    assert live == {first.id: False, second.id: False}


@pytest.mark.asyncio
async def test_bookings_live_never_reads_another_tenants_bookings(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """Asked as another tenant, a live pair is not live — the bookings are not
    visible to that tenant at all, and reporting them live would confirm their
    existence."""
    other_tenant, _other_admin = await second_tenant_factory()
    a, b = await _conflicting_pair(db_session, test_tenant.id, test_user.id)
    escalation = await _escalate(db_session, test_tenant, test_user, a, b)

    live = await contention_service.bookings_live(
        db_session, [escalation], other_tenant.id
    )
    assert live == {escalation.id: False}


@pytest.mark.asyncio
async def test_bookings_live_of_nothing_asks_the_database_nothing():
    assert await contention_service.bookings_live(_NoDatabase(), [], 1) == {}
