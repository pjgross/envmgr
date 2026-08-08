"""`bookings_with_unacknowledged_conflicts` — the batch behind the list's flag.

WHY THIS FILE EXISTS. `has_unacknowledged_conflicts` used to run per row on
`GET /bookings`, costing `list_conflicts` plus one `get_ack` PER CONFLICT for
every booking on the page. It is now one query, and the single-booking form is
derived from the batch rather than being a second implementation.

Every rule below was verified by MUTATION — remove the clause, watch the named
test fail. Before this file existed, dropping the tenant filter, the
self-exclusion, the terminal-state filter or the whole acknowledgement test
left the entire conflict suite green: `list_conflicts`' tests covered the
overlap rules, and nothing at all covered the flag. Three of those rules are
now guarded by `test_conflict_service.py` too, because both consumers share
one `conflicts_with` definition; what is left is the ack half and tenancy,
which is what this file owns.
"""
import pytest
from datetime import datetime, timezone, timedelta

from app.db.models.booking import Booking
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.services import conflict_service
from tests.factories import ensure_booking_type, ensure_environment_tier

T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


async def _env(db, tenant, name="env1", tier=None) -> Environment:
    tier = tier or await ensure_environment_tier(db, tenant.id)
    env = Environment(tenant_id=tenant.id, name=name, tier_id=tier.id)
    db.add(env)
    await db.flush()
    return env


async def _booking(db, tenant, user, env, *, start=T0, days=2, status="submitted",
                   booking_type=None, deleted_at=None) -> Booking:
    booking_type = booking_type or await ensure_booking_type(db, tenant.id)
    end = start + timedelta(days=days)
    req = BookingRequest(
        tenant_id=tenant.id, project_name="p", booking_type_id=booking_type.id,
        start_date=start, end_date=end, booked_by=user.id,
        context_tag="none", exclusive_use_requested=False,
    )
    db.add(req)
    await db.flush()
    b = Booking(
        tenant_id=tenant.id, environment_id=env.id, booking_request_id=req.id,
        start_date=start, end_date=end, status=status, deleted_at=deleted_at,
    )
    db.add(b)
    await db.flush()
    return b


async def _ack(db, tenant, user, *, booking_id, other_booking_id, willing_to_share, notes=None):
    """A conflict acknowledgement, inserted directly.

    Direct insertion is deliberate for the cross-tenant cases: no endpoint can
    write a row whose `tenant_id` disagrees with its booking's, which is
    exactly why the predicate's own filter has to refuse it.
    """
    row = BookingConflictAck(
        tenant_id=tenant.id, booking_id=booking_id, other_booking_id=other_booking_id,
        willing_to_share=willing_to_share, notes=notes,
        acknowledged_by=user.id, acknowledged_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


async def _flagged(db, tenant, *bookings) -> set[int]:
    return await conflict_service.bookings_with_unacknowledged_conflicts(
        db, [b.id for b in bookings], tenant.id
    )


# ── the core answer ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unanswered_conflict_flags_both_bookings(db_session, test_tenant, test_user):
    """Conflict is symmetric, and neither owner has answered."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    b = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))

    assert await _flagged(db_session, test_tenant, a, b) == {a.id, b.id}


@pytest.mark.asyncio
async def test_answering_clears_only_the_answerers_own_flag(db_session, test_tenant, test_user):
    """An ack is directional: `a` answering about `b` says nothing about whether
    `b`'s owner has answered about `a`."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    b = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))
    await _ack(db_session, test_tenant, test_user,
               booking_id=a.id, other_booking_id=b.id, willing_to_share=True)

    assert await _flagged(db_session, test_tenant, a, b) == {b.id}


@pytest.mark.asyncio
async def test_an_ack_carrying_only_notes_is_still_unanswered(db_session, test_tenant, test_user):
    """`willing_to_share IS NULL` means not yet answered, even with a row and
    notes present — the rule the old per-row form spelled `ack is None or
    ack.willing_to_share is None`. Dropping `~answered` or flipping
    `is_not(None)` fails here."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    b = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))
    await _ack(db_session, test_tenant, test_user, booking_id=a.id, other_booking_id=b.id,
               willing_to_share=None, notes="thinking about it")

    assert a.id in await _flagged(db_session, test_tenant, a)


@pytest.mark.asyncio
async def test_answering_false_still_counts_as_answered(db_session, test_tenant, test_user):
    """"No, I will not share" is an answer. Only NULL is unanswered — a truthiness
    test rather than a null test would wrongly keep flagging this."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    b = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))
    await _ack(db_session, test_tenant, test_user,
               booking_id=a.id, other_booking_id=b.id, willing_to_share=False)

    assert a.id not in await _flagged(db_session, test_tenant, a)


@pytest.mark.asyncio
async def test_one_answered_conflict_does_not_clear_another_unanswered_one(
    db_session, test_tenant, test_user
):
    """The flag is ANY-unanswered, not all-answered."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    b = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))
    c = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))
    await _ack(db_session, test_tenant, test_user,
               booking_id=a.id, other_booking_id=b.id, willing_to_share=True)

    assert a.id in await _flagged(db_session, test_tenant, a)
    assert c.id in await _flagged(db_session, test_tenant, c)


# ── what does not count as a conflict ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_booking_never_conflicts_with_itself(db_session, test_tenant, test_user):
    """Dropping `other.id != subject_id` makes every live booking permanently
    flagged. It survived the whole suite before `conflicts_with` was shared."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)

    assert await _flagged(db_session, test_tenant, a) == set()


@pytest.mark.asyncio
async def test_a_terminal_subject_is_never_flagged(db_session, test_tenant, test_user):
    """A closed booking has no conflicts, exactly as `list_conflicts` returns
    nothing for one. This is the filter on the SUBJECT, not on the other row."""
    env = await _env(db_session, test_tenant)
    closed = await _booking(db_session, test_tenant, test_user, env, status="closed")
    await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))

    assert await _flagged(db_session, test_tenant, closed) == set()


@pytest.mark.asyncio
async def test_a_soft_deleted_conflict_does_not_count(db_session, test_tenant, test_user):
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1),
                   deleted_at=datetime.now(timezone.utc))

    assert await _flagged(db_session, test_tenant, a) == set()


@pytest.mark.asyncio
async def test_a_booking_that_merely_abuts_does_not_conflict(db_session, test_tenant, test_user):
    """Half-open `[start, end)`: one ending exactly as the other starts is not an
    overlap. Turning `<` into `<=` fails here."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env, start=T0, days=2)
    await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=2), days=2)

    assert await _flagged(db_session, test_tenant, a) == set()


# ── tenancy ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_another_tenants_booking_is_never_a_conflict(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """Same environment id is impossible across tenants, but the same WINDOW is
    not, and without `other.tenant_id` the predicate would join on environment
    id alone. Seeded so both bookings sit on one environment row."""
    other_tenant, other_user = await second_tenant_factory()
    env = await _env(db_session, test_tenant)
    mine = await _booking(db_session, test_tenant, test_user, env)
    theirs = await _booking(
        db_session, other_tenant, other_user, env,
        start=T0 + timedelta(days=1),
        booking_type=await ensure_booking_type(db_session, other_tenant.id),
    )

    assert await _flagged(db_session, test_tenant, mine) == set()
    assert theirs.id not in await _flagged(db_session, test_tenant, mine)


@pytest.mark.asyncio
async def test_another_tenants_ack_row_never_clears_our_flag(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """`uq_conflict_ack_pair` is on `(booking_id, other_booking_id)` alone, so a
    row bearing another tenant's `tenant_id` is insertable. Without the ack's
    own tenant filter it would answer our conflict for us."""
    other_tenant, other_user = await second_tenant_factory()
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    b = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))
    await _ack(db_session, other_tenant, other_user,
               booking_id=a.id, other_booking_id=b.id, willing_to_share=True)

    assert a.id in await _flagged(db_session, test_tenant, a)


# ── the batch contract ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_it_answers_only_about_the_bookings_it_was_given(
    db_session, test_tenant, test_user
):
    """Dropping `Booking.id.in_(ids)` turns a page-bounded lookup into an
    estate-wide scan that reports rows the caller never asked about."""
    env = await _env(db_session, test_tenant)
    a = await _booking(db_session, test_tenant, test_user, env)
    b = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))

    assert await _flagged(db_session, test_tenant, a) == {a.id}
    assert b.id not in await _flagged(db_session, test_tenant, a)


@pytest.mark.asyncio
async def test_an_empty_page_asks_the_database_nothing(db_session, test_tenant):
    assert await conflict_service.bookings_with_unacknowledged_conflicts(
        db_session, [], test_tenant.id
    ) == set()


@pytest.mark.asyncio
async def test_the_batch_and_the_single_booking_form_agree(db_session, test_tenant, test_user):
    """The single form is the batch of one. Asserted AGAINST each other over a
    mixed population rather than separately — this codebase has shipped a count
    and a list, written apart, that disagreed two ways."""
    env = await _env(db_session, test_tenant)
    other_env = await _env(db_session, test_tenant, name="env2")
    unanswered = await _booking(db_session, test_tenant, test_user, env)
    partner = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))
    answered = await _booking(db_session, test_tenant, test_user, other_env)
    answered_partner = await _booking(db_session, test_tenant, test_user, other_env,
                                      start=T0 + timedelta(days=1))
    await _ack(db_session, test_tenant, test_user, booking_id=answered.id,
               other_booking_id=answered_partner.id, willing_to_share=True)
    alone = await _booking(db_session, test_tenant, test_user,
                           await _env(db_session, test_tenant, name="env3"))
    closed = await _booking(db_session, test_tenant, test_user, env, status="closed")

    population = [unanswered, partner, answered, answered_partner, alone, closed]
    batch = await _flagged(db_session, test_tenant, *population)
    for b in population:
        single = await conflict_service.has_unacknowledged_conflicts(
            db_session, b.id, test_tenant.id
        )
        assert single == (b.id in batch), f"booking {b.id}: single={single} batch={b.id in batch}"

    assert batch == {unanswered.id, partner.id, answered_partner.id}
