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
