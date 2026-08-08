"""Two people acknowledging the same thing at once must both get a 200.

THE RACE, PRECISELY. Both `upsert_ack`s read, branch, then write, behind a
unique constraint. If a second writer's INSERT lands between our read and our
write, ours is refused and — before this — surfaced as an IntegrityError, i.e.
a 500 on an ordinary governance action.

HOW IT IS REPRODUCED HERE. A genuine two-connection race is not reachable from a
single test session, so each test fabricates the exact state the race leaves:
the row exists, and our pre-read did not see it. That is done by stubbing the
lookup to answer None once — the seam sits UPSTREAM of the code under test, and
everything downstream of it (the insert, the constraint, the savepoint, the
re-read, the update) is production code running against a real database.

BOTH SERVICES ARE TESTED HERE ON PURPose. Fixing one alone would leave two
sibling endpoints with different concurrency behaviour, which is worse than the
bug; keeping their tests in one file is what makes that visible if someone
changes one of them.
"""
import pytest
from datetime import datetime, timezone, timedelta

from app.db.models.booking import Booking
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.usage_agreement_ack import UsageAgreementAck
from app.services import agreement_gap_service, conflict_service
from tests.factories import ensure_booking_type, ensure_environment_tier

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


async def _booking(db, tenant, user, *, start=T0, env=None) -> Booking:
    if env is None:
        tier = await ensure_environment_tier(db, tenant.id)
        env = Environment(tenant_id=tenant.id, name=f"race-{start.day}", tier_id=tier.id)
        db.add(env)
        await db.flush()
    bt = await ensure_booking_type(db, tenant.id)
    end = start + timedelta(days=3)
    req = BookingRequest(
        tenant_id=tenant.id, project_name="p", booking_type_id=bt.id,
        start_date=start, end_date=end, booked_by=user.id,
        context_tag="none", exclusive_use_requested=False,
    )
    db.add(req)
    await db.flush()
    b = Booking(
        tenant_id=tenant.id, environment_id=env.id, booking_request_id=req.id,
        start_date=start, end_date=end, status="submitted",
    )
    db.add(b)
    await db.flush()
    return b


def _blind_once(monkeypatch, module, name):
    """Make `module.name` answer None the first time, then behave normally.

    One call, not all of them: the re-read INSIDE `insert_or_reread` must see
    the winning row, or the test would prove only that we crash differently.
    """
    real = getattr(module, name)
    calls = {"n": 0}

    async def once_blind(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real(*a, **kw)

    monkeypatch.setattr(module, name, once_blind)
    return calls


@pytest.mark.asyncio
async def test_a_lost_agreement_ack_race_records_the_later_answer(
    db_session, test_tenant, test_user, monkeypatch
):
    booking = await _booking(db_session, test_tenant, test_user)
    # The row the other writer inserted a moment ago.
    db_session.add(UsageAgreementAck(
        tenant_id=test_tenant.id, booking_id=booking.id, notes="theirs",
        acknowledged_by=test_user.id, acknowledged_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()

    _blind_once(monkeypatch, agreement_gap_service, "get_ack")

    ack = await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes="mine", current_user=test_user,
        tenant_id=test_tenant.id,
    )

    # No IntegrityError, and the LATER answer is what is recorded.
    assert ack.notes == "mine"
    # Still exactly one row: we updated the winner rather than inserting a second.
    rows = (await db_session.execute(
        UsageAgreementAck.__table__.select().where(
            UsageAgreementAck.booking_id == booking.id
        )
    )).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_lost_conflict_ack_race_records_the_later_answer(
    db_session, test_tenant, test_user, monkeypatch
):
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    env = Environment(tenant_id=test_tenant.id, name="race-shared", tier_id=tier.id)
    db_session.add(env)
    await db_session.flush()
    mine = await _booking(db_session, test_tenant, test_user, env=env)
    other = await _booking(db_session, test_tenant, test_user, env=env,
                           start=T0 + timedelta(days=1))
    db_session.add(BookingConflictAck(
        tenant_id=test_tenant.id, booking_id=mine.id, other_booking_id=other.id,
        willing_to_share=False, notes="theirs",
        acknowledged_by=test_user.id, acknowledged_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()

    _blind_once(monkeypatch, conflict_service, "get_ack")

    ack = await conflict_service.upsert_ack(
        db_session, mine.id, other.id, willing_to_share=True, notes="mine",
        current_user=test_user, tenant_id=test_tenant.id,
    )

    assert ack.notes == "mine"
    assert ack.willing_to_share is True
    rows = (await db_session.execute(
        BookingConflictAck.__table__.select().where(
            BookingConflictAck.booking_id == mine.id
        )
    )).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_the_session_still_works_after_a_lost_race(
    db_session, test_tenant, test_user, monkeypatch
):
    """The savepoint's whole job.

    A failed flush puts the Session into pending-rollback on both engines, and
    PostgreSQL also poisons the transaction at the database level, so without
    `begin_nested` every statement after the constraint fires raises — and
    `get_db` would fail the request at commit even though the acknowledgement
    itself succeeded. Verified by mutation: dropping the savepoint fails this
    test and one other, on SQLite AND on PostgreSQL.
    """
    booking = await _booking(db_session, test_tenant, test_user)
    db_session.add(UsageAgreementAck(
        tenant_id=test_tenant.id, booking_id=booking.id, notes="theirs",
        acknowledged_by=test_user.id, acknowledged_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()
    _blind_once(monkeypatch, agreement_gap_service, "get_ack")

    await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes="mine", current_user=test_user,
        tenant_id=test_tenant.id,
    )

    # An ordinary query, after the constraint fired. This is the assertion that
    # fails on PostgreSQL if the savepoint is removed.
    later = await agreement_gap_service.get_ack(db_session, booking.id, test_tenant.id)
    assert later is not None and later.notes == "mine"


@pytest.mark.asyncio
async def test_an_unrelated_constraint_violation_is_not_swallowed(
    db_session, test_tenant, test_user, monkeypatch
):
    """`insert_or_reread` re-raises when the row is still absent afterwards.

    A refused insert whose re-read finds nothing was not a lost race — it was
    some other constraint, and returning quietly would turn a schema error into
    a silent no-op that reports success.
    """
    from sqlalchemy.exc import IntegrityError

    from app.core.upsert import insert_or_reread

    # A booking id that does not exist: the FK refuses it, and no row appears.
    async def finds_nothing():
        return None

    with pytest.raises(IntegrityError):
        await insert_or_reread(
            db_session,
            UsageAgreementAck(
                tenant_id=test_tenant.id, booking_id=10_000_000, notes="x",
                acknowledged_by=test_user.id,
                acknowledged_at=datetime.now(timezone.utc),
            ),
            finds_nothing,
        )
