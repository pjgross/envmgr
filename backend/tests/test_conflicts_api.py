import pytest
from httpx import AsyncClient


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


from datetime import datetime, timezone


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
