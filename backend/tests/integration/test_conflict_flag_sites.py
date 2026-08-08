"""One conflicted booking, read every way, must answer identically.

WHY A REQUIRED FIELD IS NOT ENOUGH. `EnvBookingSummary.has_unacknowledged_conflicts`
and `bookings.py::_to_response`'s argument are both required now, so a new
construction site cannot FORGET to answer. But the natural way to satisfy a
required field is to pass a constant — `False` type-checks, satisfies Pydantic,
and reports every booking as conflict-free while `GET /bookings` says otherwise.
That is precisely how this field spent its whole life: defaulted `False` and set
by nobody.

So every assertion here compares one reading to ANOTHER reading of the same
booking, never to a literal. A constant at any single site breaks the
comparison; a constant at every site would still be caught by the acknowledge
step, which requires the answer to CHANGE.
"""
import pytest
from datetime import datetime, timezone, timedelta

from httpx import AsyncClient

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from tests.factories import ensure_booking_type, ensure_environment_tier

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


async def _env(db, tenant) -> Environment:
    tier = await ensure_environment_tier(db, tenant.id)
    env = Environment(tenant_id=tenant.id, name="Conflict Env", tier_id=tier.id)
    db.add(env)
    await db.flush()
    return env


async def _booking(db, tenant, user, env, *, start) -> Booking:
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


async def _readings(client: AsyncClient, headers: dict, booking: Booking, request_id: int) -> dict:
    """The same booking's conflict flag, harvested from every endpoint that
    reports it. Keys name the construction site, so a failure says WHICH
    builder disagreed rather than just that something did."""
    detail = (await client.get(f"/api/v1/bookings/{booking.id}", headers=headers)).json()
    listed = next(
        row for row in (await client.get("/api/v1/bookings/", headers=headers)).json()
        if row["id"] == booking.id
    )
    summary = next(
        c for c in (
            await client.get(f"/api/v1/booking-requests/{request_id}", headers=headers)
        ).json()["bookings"]
        if c["id"] == booking.id
    )
    return {
        "bookings.py::_to_response (detail)": detail["has_unacknowledged_conflicts"],
        "bookings.py::_to_response (list)": listed["has_unacknowledged_conflicts"],
        "booking_requests.py::_summaries": summary["has_unacknowledged_conflicts"],
    }


@pytest.mark.asyncio
async def test_every_builder_reports_the_same_conflict_flag(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
):
    env = await _env(db_session, test_tenant)
    mine = await _booking(db_session, test_tenant, test_user, env, start=T0)
    other = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))

    readings = await _readings(db_session and client, auth_headers, mine, mine.booking_request_id)
    assert set(readings.values()) == {True}, readings

    # And the OTHER booking sees it too — the conflict is symmetric, so a site
    # that hard-coded one answer would show here.
    other_readings = await _readings(client, auth_headers, other, other.booking_request_id)
    assert set(other_readings.values()) == {True}, other_readings


@pytest.mark.asyncio
async def test_the_conflicts_endpoint_reports_the_other_bookings_own_flag(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
):
    """`GET /bookings/{id}/conflicts` builds EnvBookingSummary directly rather
    than through `_summaries`, which is the site A2's review found leaving a
    different field null. Its `other_booking` must agree with that booking's
    own detail read."""
    env = await _env(db_session, test_tenant)
    mine = await _booking(db_session, test_tenant, test_user, env, start=T0)
    other = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))

    items = (
        await client.get(f"/api/v1/bookings/{mine.id}/conflicts", headers=auth_headers)
    ).json()
    row = next(i for i in items if i["other_booking"]["id"] == other.id)
    detail = (await client.get(f"/api/v1/bookings/{other.id}", headers=auth_headers)).json()

    assert row["other_booking"]["has_unacknowledged_conflicts"] == \
        detail["has_unacknowledged_conflicts"] is True


@pytest.mark.asyncio
async def test_acknowledging_flips_the_flag_at_every_site_together(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
):
    """The answer must CHANGE, everywhere, as one.

    A site that hard-coded `True` would pass the agreement tests above; only a
    state change catches it. Note the ack is DIRECTIONAL — answering about the
    other booking clears our flag and leaves theirs alone — so this also pins
    that the batch keyed the two bookings separately rather than answering once
    for the pair.
    """
    env = await _env(db_session, test_tenant)
    mine = await _booking(db_session, test_tenant, test_user, env, start=T0)
    other = await _booking(db_session, test_tenant, test_user, env, start=T0 + timedelta(days=1))

    before = await _readings(client, auth_headers, mine, mine.booking_request_id)
    assert set(before.values()) == {True}, before

    resp = await client.put(
        f"/api/v1/bookings/{mine.id}/conflicts/{other.id}/ack",
        json={"willing_to_share": True, "notes": "fine to share"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    after = await _readings(client, auth_headers, mine, mine.booking_request_id)
    assert set(after.values()) == {False}, after

    theirs = await _readings(client, auth_headers, other, other.booking_request_id)
    assert set(theirs.values()) == {True}, theirs
