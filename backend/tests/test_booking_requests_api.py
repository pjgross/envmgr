from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.db.models.environment import Environment


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


async def _create_request(client: AsyncClient, auth_headers: dict, booking_type_id: int, environment_id: int) -> dict:
    payload = {
        "project_name": "env-name-fix",
        "booking_type_id": booking_type_id,
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2026-05-03T00:00:00Z",
        "environment_ids": [environment_id],
        "context_tag": "none",
    }
    resp = await client.post("/api/v1/booking-requests", headers=auth_headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["request"]


# --- environment_name must never be null (rendered as `#N` in the UI) ------
#
# GET /booking-requests/{id} (and every sibling route that shares _to_response
# / _summaries) used to return environment_name: null for every child
# booking — the doc comment claimed the detail endpoint's caller filled it
# in, but nothing did. See booking_requests.py's _summaries/_to_response and
# environment_service.get_environment_names.

@pytest.mark.asyncio
async def test_create_response_includes_environment_name(client: AsyncClient, auth_headers: dict, test_booking_type, test_environment):
    req = await _create_request(client, auth_headers, test_booking_type.id, test_environment.id)
    assert req["bookings"][0]["environment_name"] == test_environment.name


@pytest.mark.asyncio
async def test_get_booking_request_includes_environment_name(client: AsyncClient, auth_headers: dict, test_booking_type, test_environment):
    req = await _create_request(client, auth_headers, test_booking_type.id, test_environment.id)

    resp = await client.get(f"/api/v1/booking-requests/{req['id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bookings"][0]["environment_name"] == test_environment.name


@pytest.mark.asyncio
async def test_list_booking_requests_includes_environment_name(client: AsyncClient, auth_headers: dict, test_booking_type, test_environment):
    await _create_request(client, auth_headers, test_booking_type.id, test_environment.id)

    resp = await client.get("/api/v1/booking-requests", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows, "expected at least one booking request"
    matching = [r for r in rows if any(b["environment_id"] == test_environment.id for b in r["bookings"])]
    assert matching, "expected the created request to be in the list"
    booking = next(b for b in matching[0]["bookings"] if b["environment_id"] == test_environment.id)
    assert booking["environment_name"] == test_environment.name


@pytest.mark.asyncio
async def test_update_standard_fields_includes_environment_name(client: AsyncClient, auth_headers: dict, test_booking_type, test_environment):
    req = await _create_request(client, auth_headers, test_booking_type.id, test_environment.id)

    resp = await client.patch(
        f"/api/v1/booking-requests/{req['id']}/standard-fields",
        headers=auth_headers,
        json={"notes": "updated notes"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bookings"][0]["environment_name"] == test_environment.name


@pytest.mark.asyncio
async def test_update_custom_fields_includes_environment_name(client: AsyncClient, auth_headers: dict, test_booking_type, test_environment):
    req = await _create_request(client, auth_headers, test_booking_type.id, test_environment.id)

    resp = await client.patch(
        f"/api/v1/booking-requests/{req['id']}/custom-fields",
        headers=auth_headers,
        json={"values": {"note": "x"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bookings"][0]["environment_name"] == test_environment.name


@pytest.mark.asyncio
async def test_get_booking_request_environment_name_survives_soft_delete(
    client: AsyncClient, auth_headers: dict, db_session, test_booking_type, test_environment
):
    """A booking against a soft-deleted environment must still render that
    environment's name — the resolver deliberately does not filter
    deleted_at, following environment_group_service.get_group_names."""
    req = await _create_request(client, auth_headers, test_booking_type.id, test_environment.id)

    test_environment.deleted_at = datetime.now(timezone.utc)
    db_session.add(test_environment)
    await db_session.commit()

    resp = await client.get(f"/api/v1/booking-requests/{req['id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bookings"][0]["environment_name"] == test_environment.name
    assert body["bookings"][0]["environment_id"] == test_environment.id


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
