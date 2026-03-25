import pytest
from httpx import AsyncClient
from app.core.security import get_password_hash
from app.db.models.user import User


DEFAULT_DEFINITION = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin", "Release Manager", "Developer"]},
        {"from_state": "submitted", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin", "Release Manager"]},
        {"from_state": "submitted", "to_state": "rejected", "label": "Reject", "allowed_roles": ["Admin", "Release Manager"]},
        {"from_state": "submitted", "to_state": "draft", "label": "Return", "allowed_roles": ["Admin", "Release Manager"]},
    ],
    "field_permissions": {
        "draft": {"editable_fields": ["project_name", "notes"], "editable_by": ["Admin", "Release Manager", "Developer"]},
        "submitted": {"editable_fields": ["notes"], "editable_by": ["Admin", "Release Manager"]},
        "approved": {"editable_fields": [], "editable_by": []},
        "rejected": {"editable_fields": [], "editable_by": []},
    }
}


async def _setup_booking_type(client, auth_headers) -> int:
    """Create a lifecycle template + booking type, return booking_type_id."""
    tmpl_resp = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Standard", "definition": DEFAULT_DEFINITION},
    )
    assert tmpl_resp.status_code == 201, tmpl_resp.text
    template_id = tmpl_resp.json()["id"]

    bt_resp = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "Standard Booking", "lifecycle_template_id": template_id},
    )
    assert bt_resp.status_code == 201, bt_resp.text
    return bt_resp.json()["id"]


async def _setup_env(client, auth_headers, name="TransitionTestEnv") -> int:
    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": name, "environment_type": "test"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_booking(client, auth_headers, env_id: int, booking_type_id: int, **overrides) -> dict:
    payload = {
        "environment_id": env_id,
        "project_name": "Test Project",
        "start_date": "2026-06-01T10:00:00Z",
        "end_date": "2026-06-07T10:00:00Z",
        "booking_type_id": booking_type_id,
        "exclusive_use": False,
        **overrides,
    }
    resp = await client.post("/api/v1/bookings/", headers=auth_headers, json=payload)
    return resp


@pytest.mark.asyncio
async def test_transition_state_valid(client: AsyncClient, auth_headers: dict):
    """A user can submit a draft booking."""
    booking_type_id = await _setup_booking_type(client, auth_headers)
    env_id = await _setup_env(client, auth_headers, "TransitionEnv1")

    create_resp = await _create_booking(client, auth_headers, env_id, booking_type_id)
    assert create_resp.status_code == 201, create_resp.text
    booking_id = create_resp.json()["booking"]["id"]
    assert create_resp.json()["booking"]["status"] == "draft"

    resp = await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_transition_invalid_transition(client: AsyncClient, auth_headers: dict):
    """Cannot jump from draft directly to approved."""
    booking_type_id = await _setup_booking_type(client, auth_headers)
    env_id = await _setup_env(client, auth_headers, "TransitionEnv2")

    create_resp = await _create_booking(
        client, auth_headers, env_id, booking_type_id,
        project_name="Test Project 2",
        start_date="2026-07-01T10:00:00Z",
        end_date="2026-07-07T10:00:00Z",
    )
    booking_id = create_resp.json()["booking"]["id"]

    resp = await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "approved"},
    )
    assert resp.status_code == 400  # draft -> approved is not a valid transition


@pytest.mark.asyncio
async def test_history_written_on_transition(client: AsyncClient, auth_headers: dict):
    """A history row is written for each transition."""
    booking_type_id = await _setup_booking_type(client, auth_headers)
    env_id = await _setup_env(client, auth_headers, "TransitionEnv3")

    create_resp = await _create_booking(
        client, auth_headers, env_id, booking_type_id,
        project_name="Test Project 3",
        start_date="2026-08-01T10:00:00Z",
        end_date="2026-08-07T10:00:00Z",
    )
    booking_id = create_resp.json()["booking"]["id"]

    await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted", "notes": "Ready for review"},
    )
    history_resp = await client.get(f"/api/v1/bookings/{booking_id}/history", headers=auth_headers)
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert len(history) >= 2  # initial creation row + transition
    last = history[-1]
    assert last["to_state"] == "submitted"
    assert last["notes"] == "Ready for review"


@pytest.mark.asyncio
async def test_allowed_transitions_returns_transitions(client: AsyncClient, auth_headers: dict):
    """GET /allowed-transitions returns transitions for current user role."""
    booking_type_id = await _setup_booking_type(client, auth_headers)
    env_id = await _setup_env(client, auth_headers, "TransitionEnv4")

    create_resp = await _create_booking(
        client, auth_headers, env_id, booking_type_id,
        project_name="Test Project 4",
        start_date="2026-09-01T10:00:00Z",
        end_date="2026-09-07T10:00:00Z",
    )
    booking_id = create_resp.json()["booking"]["id"]

    resp = await client.get(f"/api/v1/bookings/{booking_id}/allowed-transitions", headers=auth_headers)
    assert resp.status_code == 200
    transitions = resp.json()
    to_states = [t["to_state"] for t in transitions]
    assert "submitted" in to_states  # Admin can submit from draft


@pytest.mark.asyncio
async def test_approve_shortcut_only_works_from_submitted(client: AsyncClient, auth_headers: dict):
    """POST /approve returns 400 if booking is not in submitted state."""
    booking_type_id = await _setup_booking_type(client, auth_headers)
    env_id = await _setup_env(client, auth_headers, "TransitionEnv5")

    create_resp = await _create_booking(
        client, auth_headers, env_id, booking_type_id,
        project_name="Test Project 5",
        start_date="2026-10-01T10:00:00Z",
        end_date="2026-10-07T10:00:00Z",
    )
    booking_id = create_resp.json()["booking"]["id"]

    resp = await client.post(f"/api/v1/bookings/{booking_id}/approve", headers=auth_headers)
    assert resp.status_code == 400  # booking is in draft, not submitted


@pytest.mark.asyncio
async def test_transition_invalid_role(client: AsyncClient, auth_headers: dict, db_session, test_tenant):
    """A user with 'Developer' role gets 403 when attempting a transition that requires Admin or Release Manager."""
    booking_type_id = await _setup_booking_type(client, auth_headers)
    env_id = await _setup_env(client, auth_headers, "TransitionEnv6")

    # Create a booking as Admin (starts in draft)
    create_resp = await _create_booking(
        client, auth_headers, env_id, booking_type_id,
        project_name="Test Project 6",
        start_date="2026-11-01T10:00:00Z",
        end_date="2026-11-07T10:00:00Z",
    )
    assert create_resp.status_code == 201, create_resp.text
    booking_id = create_resp.json()["booking"]["id"]

    # Transition draft -> submitted as Admin (allowed for all roles)
    submit_resp = await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )
    assert submit_resp.status_code == 200, submit_resp.text

    # Create a user with a role that is not Admin or ReleaseManager
    user_role_user = User(
        tenant_id=test_tenant.id,
        username="testuser",
        email="user@test.com",
        password_hash=get_password_hash("password123"),
        role="Developer",
        is_active=True,
    )
    db_session.add(user_role_user)
    await db_session.commit()
    await db_session.refresh(user_role_user)

    # Log in as the User-role user
    login_resp = await client.post("/api/v1/auth/login", json={
        "username": "testuser",
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert login_resp.status_code == 200, login_resp.text
    user_token = login_resp.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # Attempt submitted -> approved as User role — should be 403
    resp = await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        headers=user_headers,
        json={"to_state": "approved"},
    )
    assert resp.status_code == 403
