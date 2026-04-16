import pytest
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException

from app.services import conflict_service
from app.db.models.booking import Booking
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment


async def _make_env(db_session, test_tenant, name: str = "env1") -> Environment:
    env = Environment(tenant_id=test_tenant.id, name=name, environment_type="dev")
    db_session.add(env)
    await db_session.flush()
    return env


async def _make_booking(db_session, test_tenant, test_user, env, start, end, status="submitted") -> Booking:
    """Create a BookingRequest + child Booking for testing conflict detection."""
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="p",
        booking_type_id=1,  # dummy — not traversed for overlap
        start_date=start,
        end_date=end,
        booked_by=test_user.id,
        context_tag="none",
        exclusive_use_requested=False,
    )
    db_session.add(req)
    await db_session.flush()
    b = Booking(
        tenant_id=test_tenant.id,
        environment_id=env.id,
        booking_request_id=req.id,
        start_date=start,
        end_date=end,
        status=status,
    )
    db_session.add(b)
    await db_session.flush()
    return b


@pytest.mark.asyncio
async def test_overlap_same_env_open_window(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    b = await _make_booking(db_session, test_tenant, test_user, env, t0 + timedelta(days=1), t0 + timedelta(days=3))

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    ids = [c.id for c in conflicts]
    assert b.id in ids


@pytest.mark.asyncio
async def test_no_overlap_when_terminal(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2), status="rejected")
    await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2), status="closed")

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    assert conflicts == []


@pytest.mark.asyncio
async def test_no_overlap_different_env(db_session, test_tenant, test_user):
    env_a = await _make_env(db_session, test_tenant, name="env1")
    env_b = await _make_env(db_session, test_tenant, name="env2")

    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    a = await _make_booking(db_session, test_tenant, test_user, env_a, t0, t0 + timedelta(days=2))
    await _make_booking(db_session, test_tenant, test_user, env_b, t0, t0 + timedelta(days=2))

    conflicts = await conflict_service.list_conflicts(db_session, a.id, test_tenant.id)
    assert conflicts == []


async def _make_request_with_owner(db_session, test_tenant, test_user, delegates=None) -> BookingRequest:
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="p",
        booking_type_id=1,
        start_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 5, tzinfo=timezone.utc),
        booked_by=test_user.id,
        context_tag="none",
        exclusive_use_requested=False,
        delegate_user_ids=delegates,
    )
    db_session.add(req)
    await db_session.flush()
    return req


@pytest.mark.asyncio
async def test_ack_upsert_creates_then_updates(db_session, test_tenant, test_user):
    env = await _make_env(db_session, test_tenant)
    req = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req.id
    other = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await db_session.flush()

    ack = await conflict_service.upsert_ack(
        db_session, me.id, other.id, willing_to_share=True, notes="room to share",
        current_user=test_user, tenant_id=test_tenant.id,
    )
    assert ack.willing_to_share is True
    assert ack.notes == "room to share"
    assert ack.acknowledged_by == test_user.id
    assert ack.acknowledged_at is not None

    # Update
    ack2 = await conflict_service.upsert_ack(
        db_session, me.id, other.id, willing_to_share=False, notes="actually no",
        current_user=test_user, tenant_id=test_tenant.id,
    )
    assert ack2.id == ack.id
    assert ack2.willing_to_share is False
    assert ack2.notes == "actually no"


@pytest.mark.asyncio
async def test_ack_rejects_non_owner_non_delegate(db_session, test_tenant, test_user):
    from app.db.models.user import User
    from app.core.security import get_password_hash

    other_user = User(
        tenant_id=test_tenant.id,
        username="other",
        email="other@test",
        password_hash=get_password_hash("x"),
        role="Developer",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.flush()

    env = await _make_env(db_session, test_tenant)
    req = await _make_request_with_owner(db_session, test_tenant, test_user)
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req.id
    conflict = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await conflict_service.upsert_ack(
            db_session, me.id, conflict.id, willing_to_share=True, notes="",
            current_user=other_user, tenant_id=test_tenant.id,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_ack_allows_delegate(db_session, test_tenant, test_user):
    from app.db.models.user import User
    from app.core.security import get_password_hash

    delegate = User(
        tenant_id=test_tenant.id,
        username="delegate",
        email="delegate@test",
        password_hash=get_password_hash("x"),
        role="Developer",
        is_active=True,
    )
    db_session.add(delegate)
    await db_session.flush()

    env = await _make_env(db_session, test_tenant)
    req = await _make_request_with_owner(db_session, test_tenant, test_user, delegates=[delegate.id])
    t0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    me = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    me.booking_request_id = req.id
    other = await _make_booking(db_session, test_tenant, test_user, env, t0, t0 + timedelta(days=2))
    await db_session.flush()

    ack = await conflict_service.upsert_ack(
        db_session, me.id, other.id, willing_to_share=True, notes="",
        current_user=delegate, tenant_id=test_tenant.id,
    )
    assert ack.acknowledged_by == delegate.id
