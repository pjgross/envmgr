"""Integration tests for the Booking System (M4)."""
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.user import Tenant, User
from app.db.models.environment import Environment
from app.core.security import get_password_hash


# ---------------------------------------------------------------------------
# Fixtures for a second tenant (isolation tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def other_tenant(db_session) -> Tenant:
    tenant = Tenant(name="Other Booking Org", slug="other-booking-org")
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture(scope="function")
async def other_user(db_session, other_tenant) -> User:
    user = User(
        tenant_id=other_tenant.id,
        username="otherbookingadmin",
        email="admin@otherbooking.com",
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


async def _create_env(client, auth_headers, name="TestEnv") -> int:
    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": name, "environment_type": "test"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_booking(client, auth_headers, env_id: int, **overrides) -> dict:
    payload = {
        "environment_id": env_id,
        "project_name": "Test Project",
        "start_date": "2026-04-01T10:00:00Z",
        "end_date": "2026-04-01T14:00:00Z",
        "booking_type": "shared",
        **overrides,
    }
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json=payload)
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_booking(client: AsyncClient, auth_headers):
    """POST /bookings creates a booking with status=pending."""
    env_id = await _create_env(client, auth_headers, "CreateBookingEnv")
    resp = await _create_booking(client, auth_headers, env_id)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "booking" in data
    booking = data["booking"]
    assert booking["status"] == "pending"
    assert booking["environment_id"] == env_id
    assert booking["project_name"] == "Test Project"
    assert booking["booking_type"] == "shared"
    assert data["overlap_warnings"] == []


@pytest.mark.asyncio
async def test_create_booking_returns_overlap_warnings_for_shared(client: AsyncClient, auth_headers):
    """Two shared bookings on same env/time both succeed; second returns overlap_warnings."""
    env_id = await _create_env(client, auth_headers, "OverlapWarnEnv")

    resp1 = await _create_booking(client, auth_headers, env_id)
    assert resp1.status_code == 201
    booking1_id = resp1.json()["booking"]["id"]

    resp2 = await _create_booking(client, auth_headers, env_id)
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert booking1_id in data2["overlap_warnings"]


@pytest.mark.asyncio
async def test_exclusive_booking_blocked(client: AsyncClient, auth_headers):
    """Creating an exclusive booking when a shared booking already exists → 409."""
    env_id = await _create_env(client, auth_headers, "ExclusiveBlockEnv")

    # Create a shared booking first and approve it
    resp1 = await _create_booking(client, auth_headers, env_id, booking_type="shared")
    assert resp1.status_code == 201
    shared_id = resp1.json()["booking"]["id"]

    # Approve the shared booking so it has status=approved
    approve_resp = await client.post(f"/api/v1/bookings/{shared_id}/approve", headers=auth_headers)
    assert approve_resp.status_code == 200

    # Now try to create an exclusive booking on the same time slot
    resp2 = await _create_booking(client, auth_headers, env_id, booking_type="exclusive")
    assert resp2.status_code == 409
    detail = resp2.json()["detail"]
    assert "conflicts" in detail
    assert shared_id in detail["conflicts"]


@pytest.mark.asyncio
async def test_list_bookings(client: AsyncClient, auth_headers):
    """GET /bookings returns all bookings; filter by environment_id works."""
    env1_id = await _create_env(client, auth_headers, "ListEnv1")
    env2_id = await _create_env(client, auth_headers, "ListEnv2")

    await _create_booking(client, auth_headers, env1_id, project_name="ProjA")
    await _create_booking(client, auth_headers, env2_id, project_name="ProjB")

    # List all
    all_resp = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert all_resp.status_code == 200
    names = [b["project_name"] for b in all_resp.json()]
    assert "ProjA" in names
    assert "ProjB" in names

    # Filter by env1
    env1_resp = await client.get(
        f"/api/v1/bookings/?environment_id={env1_id}", headers=auth_headers
    )
    assert env1_resp.status_code == 200
    env1_names = [b["project_name"] for b in env1_resp.json()]
    assert "ProjA" in env1_names
    assert "ProjB" not in env1_names


@pytest.mark.asyncio
async def test_list_bookings_date_range(client: AsyncClient, auth_headers):
    """Filter bookings by start/end date range."""
    env_id = await _create_env(client, auth_headers, "DateRangeEnv")

    # April booking
    await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "AprilProj",
            "start_date": "2026-04-01T10:00:00Z",
            "end_date": "2026-04-01T14:00:00Z",
            "booking_type": "shared",
        },
    )
    # May booking
    await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "MayProj",
            "start_date": "2026-05-01T10:00:00Z",
            "end_date": "2026-05-01T14:00:00Z",
            "booking_type": "shared",
        },
    )

    # Filter: April only
    resp = await client.get(
        "/api/v1/bookings/?start=2026-04-01T00%3A00%3A00Z&end=2026-04-30T23%3A59%3A59Z",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = [b["project_name"] for b in resp.json()]
    assert "AprilProj" in names
    assert "MayProj" not in names


@pytest.mark.asyncio
async def test_approve_booking(client: AsyncClient, auth_headers):
    """POST /bookings/{id}/approve sets status to approved."""
    env_id = await _create_env(client, auth_headers, "ApproveEnv")
    create_resp = await _create_booking(client, auth_headers, env_id)
    booking_id = create_resp.json()["booking"]["id"]

    resp = await client.post(f"/api/v1/bookings/{booking_id}/approve", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_reject_booking(client: AsyncClient, auth_headers):
    """POST /bookings/{id}/reject sets status to rejected."""
    env_id = await _create_env(client, auth_headers, "RejectEnv")
    create_resp = await _create_booking(client, auth_headers, env_id)
    booking_id = create_resp.json()["booking"]["id"]

    resp = await client.post(f"/api/v1/bookings/{booking_id}/reject", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_approve_parent_approves_children(client: AsyncClient, auth_headers):
    """Approving a parent recurring booking also approves all pending children."""
    env_id = await _create_env(client, auth_headers, "RecurApproveEnv")

    create_resp = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "RecurProj",
            "start_date": "2026-04-01T10:00:00Z",
            "end_date": "2026-04-01T14:00:00Z",
            "booking_type": "shared",
            "recurrence_rule": "FREQ=WEEKLY;COUNT=3",
        },
    )
    assert create_resp.status_code == 201
    parent_id = create_resp.json()["booking"]["id"]

    # Approve the parent
    approve_resp = await client.post(
        f"/api/v1/bookings/{parent_id}/approve", headers=auth_headers
    )
    assert approve_resp.status_code == 200

    # List all bookings and check all are approved
    list_resp = await client.get("/api/v1/bookings/", headers=auth_headers)
    bookings = list_resp.json()
    project_bookings = [b for b in bookings if b["project_name"] == "RecurProj"]
    assert all(b["status"] == "approved" for b in project_bookings), \
        f"Not all approved: {[(b['id'], b['status']) for b in project_bookings]}"


@pytest.mark.asyncio
async def test_recurring_booking_generates_occurrences(client: AsyncClient, auth_headers):
    """Creating a booking with RRULE generates multiple rows (parent + children)."""
    env_id = await _create_env(client, auth_headers, "RecurGenEnv")

    resp = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "Weekly Sprint",
            "start_date": "2026-04-01T09:00:00Z",
            "end_date": "2026-04-01T17:00:00Z",
            "booking_type": "shared",
            "recurrence_rule": "FREQ=WEEKLY;COUNT=4",
        },
    )
    assert resp.status_code == 201
    parent_id = resp.json()["booking"]["id"]

    # List all bookings and count occurrences for this project
    list_resp = await client.get("/api/v1/bookings/", headers=auth_headers)
    all_bookings = list_resp.json()
    weekly_bookings = [b for b in all_bookings if b["project_name"] == "Weekly Sprint"]
    # Parent + 3 children (COUNT=4 means 4 total, parent IS first, so 3 children)
    assert len(weekly_bookings) == 4, f"Expected 4 bookings, got {len(weekly_bookings)}"

    # Parent has no recurrence_parent_id
    parent = next(b for b in weekly_bookings if b["id"] == parent_id)
    assert parent["recurrence_parent_id"] is None
    assert parent["recurrence_rule"] == "FREQ=WEEKLY;COUNT=4"

    # Children reference parent
    children = [b for b in weekly_bookings if b["id"] != parent_id]
    assert len(children) == 3
    assert all(c["recurrence_parent_id"] == parent_id for c in children)
    assert all(c["recurrence_rule"] is None for c in children)


@pytest.mark.asyncio
async def test_delete_occurrence(client: AsyncClient, auth_headers):
    """DELETE /bookings/{id}/occurrence soft-deletes one row; siblings remain."""
    env_id = await _create_env(client, auth_headers, "DeleteOccEnv")

    resp = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "OccProj",
            "start_date": "2026-04-07T09:00:00Z",
            "end_date": "2026-04-07T17:00:00Z",
            "booking_type": "shared",
            "recurrence_rule": "FREQ=WEEKLY;COUNT=3",
        },
    )
    assert resp.status_code == 201
    parent_id = resp.json()["booking"]["id"]

    # Get all occurrences
    list_resp = await client.get("/api/v1/bookings/", headers=auth_headers)
    all_bookings = list_resp.json()
    occ_bookings = [b for b in all_bookings if b["project_name"] == "OccProj"]
    assert len(occ_bookings) == 3

    # Delete one child occurrence
    child = next(b for b in occ_bookings if b["recurrence_parent_id"] == parent_id)
    del_resp = await client.delete(
        f"/api/v1/bookings/{child['id']}/occurrence", headers=auth_headers
    )
    assert del_resp.status_code == 204

    # Should now have 2 bookings
    list_resp2 = await client.get("/api/v1/bookings/", headers=auth_headers)
    remaining = [b for b in list_resp2.json() if b["project_name"] == "OccProj"]
    assert len(remaining) == 2
    assert child["id"] not in [b["id"] for b in remaining]


@pytest.mark.asyncio
async def test_delete_series(client: AsyncClient, auth_headers):
    """DELETE /bookings/{id} soft-deletes parent + all children."""
    env_id = await _create_env(client, auth_headers, "DeleteSeriesEnv")

    resp = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": env_id,
            "project_name": "SeriesProj",
            "start_date": "2026-04-14T09:00:00Z",
            "end_date": "2026-04-14T17:00:00Z",
            "booking_type": "shared",
            "recurrence_rule": "FREQ=WEEKLY;COUNT=4",
        },
    )
    assert resp.status_code == 201
    parent_id = resp.json()["booking"]["id"]

    # Verify 4 bookings exist
    list_resp = await client.get("/api/v1/bookings/", headers=auth_headers)
    series_bookings = [b for b in list_resp.json() if b["project_name"] == "SeriesProj"]
    assert len(series_bookings) == 4

    # Delete the series
    del_resp = await client.delete(f"/api/v1/bookings/{parent_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    # All gone
    list_resp2 = await client.get("/api/v1/bookings/", headers=auth_headers)
    remaining = [b for b in list_resp2.json() if b["project_name"] == "SeriesProj"]
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_cancel_booking(client: AsyncClient, auth_headers):
    """POST /bookings/{id}/cancel by owner soft-deletes the booking."""
    env_id = await _create_env(client, auth_headers, "CancelBookingEnv")
    create_resp = await _create_booking(client, auth_headers, env_id, project_name="CancelMe")
    booking_id = create_resp.json()["booking"]["id"]

    cancel_resp = await client.post(
        f"/api/v1/bookings/{booking_id}/cancel", headers=auth_headers
    )
    assert cancel_resp.status_code == 204

    # Booking should be gone from list
    list_resp = await client.get("/api/v1/bookings/", headers=auth_headers)
    names = [b["project_name"] for b in list_resp.json()]
    assert "CancelMe" not in names

    # GET should return 404
    get_resp = await client.get(f"/api/v1/bookings/{booking_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_tenant_isolation(client: AsyncClient, auth_headers, other_auth_headers):
    """Booking from tenant A is not visible to tenant B."""
    env_id = await _create_env(client, auth_headers, "IsolationEnv")
    create_resp = await _create_booking(
        client, auth_headers, env_id, project_name="TenantAProject"
    )
    assert create_resp.status_code == 201
    booking_id = create_resp.json()["booking"]["id"]

    # Tenant B cannot see this booking in list
    list_resp = await client.get("/api/v1/bookings/", headers=other_auth_headers)
    assert list_resp.status_code == 200
    names = [b["project_name"] for b in list_resp.json()]
    assert "TenantAProject" not in names

    # Tenant B gets 404 when fetching by ID
    get_resp = await client.get(f"/api/v1/bookings/{booking_id}", headers=other_auth_headers)
    assert get_resp.status_code == 404
