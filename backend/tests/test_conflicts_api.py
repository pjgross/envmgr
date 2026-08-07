import pytest
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient

from app.api.v1.schemas.environment_group import MemberCreate
from app.services import environment_group_service
from tests.factories import ensure_environment, ensure_environment_group


@pytest.mark.asyncio
async def test_list_conflicts_empty(client: AsyncClient, auth_headers: dict, test_booking):
    resp = await client.get(f"/api/v1/bookings/{test_booking.id}/conflicts", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_upsert_conflict_ack(client: AsyncClient, auth_headers: dict, test_booking, test_conflicting_booking):
    resp = await client.put(
        f"/api/v1/bookings/{test_booking.id}/conflicts/{test_conflicting_booking.id}/ack",
        headers=auth_headers,
        json={"willing_to_share": True, "notes": "coordinated account ranges"},
    )
    assert resp.status_code == 200
    ack = resp.json()
    assert ack["willing_to_share"] is True
    assert ack["notes"] == "coordinated account ranges"


@pytest.mark.asyncio
async def test_received_feedback_empty(client: AsyncClient, auth_headers: dict, test_booking):
    resp = await client.get(
        f"/api/v1/bookings/{test_booking.id}/received-feedback",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_received_feedback_returns_row_with_context(
    client: AsyncClient,
    auth_headers: dict,
    db_session,
    test_tenant,
    test_user,
    test_booking,
    test_conflicting_booking,
):
    from app.db.models.booking_conflict_ack import BookingConflictAck

    ack = BookingConflictAck(
        tenant_id=test_tenant.id,
        booking_id=test_conflicting_booking.id,
        other_booking_id=test_booking.id,
        willing_to_share=True,
        notes="we can share later in the week",
        acknowledged_by=test_user.id,
        acknowledged_at=datetime(2026, 5, 1, 10, 30, tzinfo=timezone.utc),
    )
    db_session.add(ack)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/bookings/{test_booking.id}/received-feedback",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["willing_to_share"] is True
    assert row["notes"] == "we can share later in the week"
    assert row["acknowledged_by"]["username"] == test_user.username
    assert row["acknowledged_by"]["email"] == test_user.email
    assert row["source_booking"]["id"] == test_conflicting_booking.id
    assert row["source_request"]["project_name"] == "Conflicting Project"
    assert row["source_request"]["booked_by"]["id"] == test_user.id


# ── Review Finding 1: conflicts.py's own EnvBookingSummary sites ────────────
#
# `EnvBookingSummary` gained environment_group_id/environment_group_name in
# Task 4, but conflicts.py builds two EnvBookingSummary rows of its own —
# distinct construction sites from booking_requests.py's and bookings.py's,
# which grep for the two files a brief named would never surface. Both left
# the new fields at their None default, so a booking rendered its group name
# everywhere EXCEPT here.


async def _grouped_and_conflicting_bookings(client, auth_headers, db_session, test_tenant, test_booking_type):
    """A group-booked environment, then a second, hand-picked booking on the
    same environment with an overlapping window — the second conflicts with
    the first. Returns (group, grouped_booking_id, other_booking_id)."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Conflict Group")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await environment_group_service.add_member(
        db_session, group.id, MemberCreate(environment_id=env.id), test_tenant.id
    )
    await db_session.commit()

    now = datetime.now(timezone.utc)
    grouped = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "Grouped",
            "booking_type_id": test_booking_type.id,
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=5)).isoformat(),
            "environment_ids": [],
            "environment_group_ids": [group.id],
        },
        headers=auth_headers,
    )
    assert grouped.status_code == 201, grouped.text
    grouped_booking_id = grouped.json()["request"]["bookings"][0]["id"]

    other = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "Hand-picked",
            "booking_type_id": test_booking_type.id,
            "start_date": (now + timedelta(days=1)).isoformat(),
            "end_date": (now + timedelta(days=3)).isoformat(),
            "environment_ids": [env.id],
            "environment_group_ids": [],
        },
        headers=auth_headers,
    )
    assert other.status_code == 201, other.text
    other_booking_id = other.json()["request"]["bookings"][0]["id"]

    return group, grouped_booking_id, other_booking_id


@pytest.mark.asyncio
async def test_conflicts_endpoint_carries_the_other_bookings_group_name(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_booking_type
):
    group, grouped_booking_id, other_booking_id = await _grouped_and_conflicting_bookings(
        client, auth_headers, db_session, test_tenant, test_booking_type
    )

    resp = await client.get(
        f"/api/v1/bookings/{other_booking_id}/conflicts", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    conflict = items[0]["other_booking"]
    assert conflict["id"] == grouped_booking_id
    assert conflict["environment_group_id"] == group.id
    assert conflict["environment_group_name"] == "Conflict Group"


@pytest.mark.asyncio
async def test_received_feedback_endpoint_carries_the_acking_bookings_group_name(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_booking_type, test_user
):
    from app.db.models.booking_conflict_ack import BookingConflictAck

    group, grouped_booking_id, other_booking_id = await _grouped_and_conflicting_bookings(
        client, auth_headers, db_session, test_tenant, test_booking_type
    )

    # The GROUPED booking is the one leaving feedback about the hand-picked
    # one — so its group must render on `source_booking` in the response for
    # GET /bookings/{other_booking_id}/received-feedback.
    ack = BookingConflictAck(
        tenant_id=test_tenant.id,
        booking_id=grouped_booking_id,
        other_booking_id=other_booking_id,
        willing_to_share=True,
        notes="sharing the window",
        acknowledged_by=test_user.id,
        acknowledged_at=datetime.now(timezone.utc),
    )
    db_session.add(ack)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/bookings/{other_booking_id}/received-feedback", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    source = body[0]["source_booking"]
    assert source["id"] == grouped_booking_id
    assert source["environment_group_id"] == group.id
    assert source["environment_group_name"] == "Conflict Group"
