import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_request_endpoint(client: AsyncClient, auth_headers: dict, test_booking_type, test_environment):
    payload = {
        "project_name": "sprint-42",
        "booking_type_id": test_booking_type.id,
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2026-05-03T00:00:00Z",
        "environment_ids": [test_environment.id],
        "context_tag": "none",
    }
    resp = await client.post("/api/v1/booking-requests", headers=auth_headers, json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["request"]["project_name"] == "sprint-42"
    assert len(data["request"]["bookings"]) == 1
    assert data["detected_conflicts"] == {}


@pytest.mark.asyncio
async def test_preview_conflicts_endpoint(client: AsyncClient, auth_headers: dict, test_environment):
    resp = await client.post(
        "/api/v1/booking-requests/preview-conflicts",
        headers=auth_headers,
        json={
            "environment_ids": [test_environment.id],
            "start_date": "2026-05-01T00:00:00Z",
            "end_date": "2026-05-03T00:00:00Z",
        },
    )
    assert resp.status_code == 200
    assert "conflicts" in resp.json()
