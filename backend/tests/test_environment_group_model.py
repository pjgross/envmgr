"""Environment groups, their membership junction, and the FK that column
has lacked since the March booking migration."""
import pytest
from sqlalchemy import select

from app.db.models.environment_group import EnvironmentGroup, EnvironmentGroupMember
from tests.factories import (
    ensure_environment, ensure_environment_group,
)


@pytest.mark.asyncio
async def test_group_persists_with_its_tenant(db_session, test_tenant):
    group = EnvironmentGroup(tenant_id=test_tenant.id, name="Mortgage SIT + Customer SIT")
    db_session.add(group)
    await db_session.flush()

    assert group.id is not None
    assert group.is_active is True
    assert group.deleted_at is None
    assert group.description is None


@pytest.mark.asyncio
async def test_an_environment_can_belong_to_several_groups(db_session, test_tenant):
    """requirements.md §2.1 says so explicitly, which is why membership is a
    junction table rather than a group_id column on environment."""
    env = await ensure_environment(db_session, test_tenant.id)
    a = await ensure_environment_group(db_session, test_tenant.id, name="Group A")
    b = await ensure_environment_group(db_session, test_tenant.id, name="Group B")

    for group in (a, b):
        db_session.add(EnvironmentGroupMember(
            tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id
        ))
    await db_session.flush()

    rows = (await db_session.execute(
        select(EnvironmentGroupMember.group_id).where(
            EnvironmentGroupMember.environment_id == env.id
        )
    )).scalars().all()
    assert sorted(rows) == sorted([a.id, b.id])


@pytest.mark.asyncio
async def test_a_group_holds_several_environments(db_session, test_tenant):
    group = await ensure_environment_group(db_session, test_tenant.id)
    one = await ensure_environment(db_session, test_tenant.id, slot=1)
    two = await ensure_environment(db_session, test_tenant.id, slot=2)

    for env in (one, two):
        db_session.add(EnvironmentGroupMember(
            tenant_id=test_tenant.id, group_id=group.id, environment_id=env.id
        ))
    await db_session.flush()

    rows = (await db_session.execute(
        select(EnvironmentGroupMember.environment_id).where(
            EnvironmentGroupMember.group_id == group.id
        )
    )).scalars().all()
    assert sorted(rows) == sorted([one.id, two.id])


@pytest.mark.asyncio
async def test_booking_can_now_name_the_group_it_came_from(
    db_session, test_tenant, test_booking_type, test_user
):
    """The column has existed since the March migration with no FK and no
    table. Nothing has ever written it; this is the first row that does."""
    from datetime import datetime, timedelta, timezone
    from app.db.models.booking import Booking
    from app.db.models.booking_request import BookingRequest

    group = await ensure_environment_group(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=test_tenant.id, project_name="Regression sweep",
        booking_type_id=test_booking_type.id,
        start_date=now, end_date=now + timedelta(days=1), booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    booking = Booking(
        tenant_id=test_tenant.id, booking_request_id=req.id, environment_id=env.id,
        start_date=now, end_date=now + timedelta(days=1), status="draft",
        environment_group_id=group.id,
    )
    db_session.add(booking)
    await db_session.flush()

    assert booking.environment_group_id == group.id


@pytest.mark.asyncio
async def test_a_booking_need_not_come_from_a_group(
    db_session, test_tenant, test_booking_type, test_user
):
    """Hand-picked environments leave it null, and those bookings keep
    transitioning independently — the atomic unit is the group's members."""
    from datetime import datetime, timedelta, timezone
    from app.db.models.booking import Booking
    from app.db.models.booking_request import BookingRequest

    env = await ensure_environment(db_session, test_tenant.id)
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=test_tenant.id, project_name="Hand picked",
        booking_type_id=test_booking_type.id,
        start_date=now, end_date=now + timedelta(days=1), booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()

    booking = Booking(
        tenant_id=test_tenant.id, booking_request_id=req.id, environment_id=env.id,
        start_date=now, end_date=now + timedelta(days=1), status="draft",
    )
    db_session.add(booking)
    await db_session.flush()

    assert booking.environment_group_id is None


@pytest.mark.asyncio
async def test_ensure_environment_group_is_scoped_per_tenant(
    db_session, test_tenant, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()

    mine = await ensure_environment_group(db_session, test_tenant.id, name="Shared")
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Shared")

    assert mine.id != theirs.id
    assert mine.tenant_id == test_tenant.id
    assert theirs.tenant_id == other_tenant.id
    assert (
        await ensure_environment_group(db_session, test_tenant.id, name="Shared")
    ).id == mine.id
