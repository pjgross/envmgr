"""Integration tests for M6: Event Publishing (Outbox Pattern).

Tests verify that write operations create EventLog rows atomically.
NATS publisher worker is NOT tested here (no NATS in test environment).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models.event_log import EventLog
from app.db.models.user import Tenant, User
from app.db.models.environment import Environment
from app.core.security import get_password_hash


# ---------------------------------------------------------------------------
# Fixtures for a second tenant (isolation tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def other_tenant(db_session) -> Tenant:
    tenant = Tenant(name="Other Events Org", slug="other-events-org")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture(scope="function")
async def other_user(db_session, other_tenant) -> User:
    user = User(
        tenant_id=other_tenant.id,
        username="othereventsadmin",
        email="admin@otherevents.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def other_auth_headers(client, other_tenant, other_user) -> dict:
    response = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_env(client, auth_headers, name="EventTestEnv") -> int:
    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": name, "environment_type": "test"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_system(client, auth_headers, name="EventTestSystem") -> int:
    resp = await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_booking(client, auth_headers, env_id: int, **overrides) -> dict:
    payload = {
        "environment_id": env_id,
        "project_name": "Event Test Project",
        "start_date": "2026-05-01T10:00:00Z",
        "end_date": "2026-05-01T14:00:00Z",
        "booking_type": "shared",
        **overrides,
    }
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["booking"]


async def _get_events(db_session, event_type: str, aggregate_id: int) -> list[EventLog]:
    result = await db_session.execute(
        select(EventLog).where(
            EventLog.event_type == event_type,
            EventLog.aggregate_id == aggregate_id,
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Environment event tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_environment_emits_event(client: AsyncClient, auth_headers, db_session):
    """Creating an environment produces an EnvironmentCreated EventLog row."""
    env_id = await _create_env(client, auth_headers, "EnvCreatedEvent")

    events = await _get_events(db_session, "EnvironmentCreated", env_id)
    assert len(events) == 1
    evt = events[0]
    assert evt.aggregate_type == "Environment"
    assert evt.published_at is None  # not yet published to NATS
    assert evt.payload["id"] == env_id
    assert evt.payload["name"] == "EnvCreatedEvent"


@pytest.mark.asyncio
async def test_update_environment_emits_event(client: AsyncClient, auth_headers, db_session):
    """Updating an environment produces an EnvironmentUpdated EventLog row."""
    env_id = await _create_env(client, auth_headers, "EnvUpdateEvent")

    resp = await client.patch(
        f"/api/v1/environments/{env_id}",
        headers=auth_headers,
        json={"name": "EnvUpdateEventRenamed"},
    )
    assert resp.status_code == 200

    events = await _get_events(db_session, "EnvironmentUpdated", env_id)
    assert len(events) == 1
    evt = events[0]
    assert evt.aggregate_type == "Environment"
    assert evt.published_at is None


@pytest.mark.asyncio
async def test_delete_environment_emits_event(client: AsyncClient, auth_headers, db_session):
    """Deleting an environment produces an EnvironmentDeleted EventLog row."""
    env_id = await _create_env(client, auth_headers, "EnvDeleteEvent")

    resp = await client.delete(f"/api/v1/environments/{env_id}", headers=auth_headers)
    assert resp.status_code == 204

    events = await _get_events(db_session, "EnvironmentDeleted", env_id)
    assert len(events) == 1
    assert events[0].aggregate_type == "Environment"
    assert events[0].published_at is None


# ---------------------------------------------------------------------------
# System event tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_system_emits_event(client: AsyncClient, auth_headers, db_session):
    """Creating a system produces a SystemCreated EventLog row."""
    sys_id = await _create_system(client, auth_headers, "SystemCreatedEvent")

    events = await _get_events(db_session, "SystemCreated", sys_id)
    assert len(events) == 1
    evt = events[0]
    assert evt.aggregate_type == "System"
    assert evt.published_at is None
    assert evt.payload["id"] == sys_id
    assert evt.payload["name"] == "SystemCreatedEvent"


@pytest.mark.asyncio
async def test_update_system_emits_event(client: AsyncClient, auth_headers, db_session):
    """Updating a system produces a SystemUpdated EventLog row."""
    sys_id = await _create_system(client, auth_headers, "SystemUpdateEvent")

    resp = await client.patch(
        f"/api/v1/systems/{sys_id}",
        headers=auth_headers,
        json={"name": "SystemUpdateEventRenamed"},
    )
    assert resp.status_code == 200

    events = await _get_events(db_session, "SystemUpdated", sys_id)
    assert len(events) == 1
    evt = events[0]
    assert evt.aggregate_type == "System"
    assert evt.published_at is None


# ---------------------------------------------------------------------------
# Booking event tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_booking_emits_event(client: AsyncClient, auth_headers, db_session):
    """Creating a booking produces a BookingCreated EventLog row."""
    env_id = await _create_env(client, auth_headers, "CreateBookingEnv")
    booking = await _create_booking(client, auth_headers, env_id)
    booking_id = booking["id"]

    events = await _get_events(db_session, "BookingCreated", booking_id)
    assert len(events) == 1
    evt = events[0]
    assert evt.aggregate_type == "Booking"
    assert evt.published_at is None
    assert evt.payload["environment_id"] == env_id


@pytest.mark.asyncio
async def test_approve_booking_emits_event(client: AsyncClient, auth_headers, db_session):
    """Approving a booking produces a BookingApproved EventLog row."""
    env_id = await _create_env(client, auth_headers, "ApproveBookingEnv")
    booking = await _create_booking(client, auth_headers, env_id)
    booking_id = booking["id"]

    resp = await client.post(
        f"/api/v1/bookings/{booking_id}/approve", headers=auth_headers
    )
    assert resp.status_code == 200

    events = await _get_events(db_session, "BookingApproved", booking_id)
    assert len(events) == 1
    evt = events[0]
    assert evt.aggregate_type == "Booking"
    assert evt.published_at is None
    assert evt.payload["environment_id"] == env_id


@pytest.mark.asyncio
async def test_reject_booking_emits_event(client: AsyncClient, auth_headers, db_session):
    """Rejecting a booking produces a BookingRejected EventLog row."""
    env_id = await _create_env(client, auth_headers, "RejectBookingEnv")
    booking = await _create_booking(client, auth_headers, env_id)
    booking_id = booking["id"]

    resp = await client.post(
        f"/api/v1/bookings/{booking_id}/reject", headers=auth_headers
    )
    assert resp.status_code == 200

    events = await _get_events(db_session, "BookingRejected", booking_id)
    assert len(events) == 1
    assert events[0].aggregate_type == "Booking"
    assert events[0].published_at is None


@pytest.mark.asyncio
async def test_cancel_booking_emits_event(client: AsyncClient, auth_headers, db_session):
    """Cancelling a booking produces a BookingCancelled EventLog row."""
    env_id = await _create_env(client, auth_headers, "CancelBookingEnv")
    booking = await _create_booking(client, auth_headers, env_id)
    booking_id = booking["id"]

    resp = await client.post(
        f"/api/v1/bookings/{booking_id}/cancel", headers=auth_headers
    )
    assert resp.status_code == 204

    events = await _get_events(db_session, "BookingCancelled", booking_id)
    assert len(events) == 1
    assert events[0].aggregate_type == "Booking"
    assert events[0].published_at is None


# ---------------------------------------------------------------------------
# Tenant isolation test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_tenant_isolation(
    client: AsyncClient,
    auth_headers,
    other_auth_headers,
    db_session,
    test_tenant,
    other_tenant,
):
    """EventLog rows for tenant A are not visible when querying under tenant B context."""
    # Tenant A creates an environment → EnvironmentCreated event with tenant A's id
    env_id = await _create_env(client, auth_headers, "IsolationEnvA")

    # Verify the event belongs to test_tenant
    result = await db_session.execute(
        select(EventLog).where(
            EventLog.event_type == "EnvironmentCreated",
            EventLog.aggregate_id == env_id,
        )
    )
    events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].tenant_id == test_tenant.id

    # Querying events for the other tenant should return nothing
    result_other = await db_session.execute(
        select(EventLog).where(
            EventLog.tenant_id == other_tenant.id,
            EventLog.event_type == "EnvironmentCreated",
            EventLog.aggregate_id == env_id,
        )
    )
    other_events = list(result_other.scalars().all())
    assert len(other_events) == 0
