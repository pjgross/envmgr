"""Integration tests for Phase 2 change requests (Step 3)."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.system import System, SubSystem
from app.db.models.change_request import ChangeRequest
from app.db.models.event_log import EventLog


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def test_subsystem(db_session, test_tenant):
    sys = System(
        tenant_id=test_tenant.id,
        name="Test System",
        description=None,
    )
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(
        tenant_id=test_tenant.id,
        system_id=sys.id,
        name="Test Subsystem",
        component_type="api_gateway",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


@pytest_asyncio.fixture(scope="function")
async def test_cr_lifecycle(db_session, test_tenant):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="change_request",
        name="CR Simple Approval",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
                {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "submitted", "label": "Submit",
                 "allowed_roles": ["Admin", "Developer"]},
                {"from_state": "submitted", "to_state": "approved", "label": "Approve",
                 "allowed_roles": ["Admin"]},
                {"from_state": "submitted", "to_state": "rejected", "label": "Reject",
                 "allowed_roles": ["Admin"]},
                {"from_state": "approved", "to_state": "completed", "label": "Mark Completed",
                 "allowed_roles": ["Admin", "Developer"]},
            ],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


def _cr_payload(sub_id, env_id, lifecycle_id, **overrides):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "title": "Apply security patch",
        "description": "Rolls out CVE-2026-1234 patch to API layer.",
        "change_type": "code_deployment",
        "lifecycle_id": lifecycle_id,
        "subsystem_id": sub_id,
        "environment_ids": [env_id] if env_id is not None else [],
        "host_ids": [],
        "has_outage": False,
        "scheduled_start": (now + timedelta(days=1)).isoformat(),
        "scheduled_end": (now + timedelta(days=1, hours=2)).isoformat(),
    }
    payload.update(overrides)
    return payload


# ── Happy paths ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_change_request_happy_path(
    client: AsyncClient, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Apply security patch"
    assert body["status"] == "draft"
    assert body["change_type"] == "code_deployment"
    assert body["subsystem_id"] == test_subsystem.id
    assert body["environment_ids"] == [test_environment.id]
    assert body["host_ids"] == []
    assert body["derived_environment_ids"] == []


@pytest.mark.asyncio
async def test_create_records_initial_history_and_event(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle, db_session,
):
    resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    cr_id = resp.json()["id"]

    detail = await client.get(f"/api/v1/change-requests/{cr_id}", headers=auth_headers)
    assert detail.status_code == 200
    history = detail.json()["history"]
    assert len(history) == 1
    assert history[0]["from_state"] is None
    assert history[0]["to_state"] == "draft"

    evts = (await db_session.execute(select(EventLog).where(EventLog.aggregate_id == cr_id))).scalars().all()
    assert {e.event_type for e in evts} == {"ChangeRequestCreated"}


@pytest.mark.asyncio
async def test_list_and_filters(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    for title in ("A", "B"):
        resp = await client.post(
            "/api/v1/change-requests",
            headers=auth_headers,
            json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id, title=title),
        )
        assert resp.status_code == 201

    # No filter → 2
    resp = await client.get("/api/v1/change-requests", headers=auth_headers)
    assert len(resp.json()) == 2

    # environment filter
    resp = await client.get(
        f"/api/v1/change-requests?environment_id={test_environment.id}", headers=auth_headers
    )
    assert len(resp.json()) == 2
    resp = await client.get(
        "/api/v1/change-requests?environment_id=99999", headers=auth_headers
    )
    assert resp.json() == []


# ── Validation ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_rejects_invalid_change_type(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id,
                         change_type="nope"),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_outage_without_times(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id,
                         has_outage=True),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_unknown_subsystem(
    client, auth_headers, test_environment, test_cr_lifecycle,
):
    resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(99999, test_environment.id, test_cr_lifecycle.id),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_rejects_lifecycle_with_wrong_entity_type(
    client, auth_headers, test_subsystem, test_environment, test_booking_type, db_session,
):
    # test_booking_type creates a lifecycle template with entity_type='booking'
    booking_tpl_id = test_booking_type.lifecycle_template_id
    resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, booking_tpl_id),
    )
    assert resp.status_code == 400


# ── Update + history ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_records_field_history(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    create = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    cr_id = create.json()["id"]

    patch = await client.patch(
        f"/api/v1/change-requests/{cr_id}",
        headers=auth_headers,
        json={"title": "Revised title"},
    )
    assert patch.status_code == 200
    assert patch.json()["title"] == "Revised title"

    detail = await client.get(f"/api/v1/change-requests/{cr_id}", headers=auth_headers)
    history = detail.json()["history"]
    # First entry = initial transition; second = the title field change
    assert len(history) == 2
    assert history[1]["field_name"] == "title"


# ── Transitions ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_transition_allowed_for_admin(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle, db_session,
):
    create = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    cr_id = create.json()["id"]

    # draft → submitted
    r = await client.post(
        f"/api/v1/change-requests/{cr_id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"

    # terminal: submitted → rejected should emit Completed
    r2 = await client.post(
        f"/api/v1/change-requests/{cr_id}/transition",
        headers=auth_headers,
        json={"to_state": "rejected", "notes": "duplicate"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "rejected"

    evts = (
        await db_session.execute(select(EventLog).where(EventLog.aggregate_id == cr_id))
    ).scalars().all()
    types = {e.event_type for e in evts}
    assert {"ChangeRequestCreated", "ChangeRequestStateTransitioned", "ChangeRequestCompleted"} <= types


@pytest.mark.asyncio
async def test_transition_rejected_for_wrong_role(
    client, test_tenant, test_subsystem, test_environment, test_cr_lifecycle, db_session,
):
    # Make a Developer user (not Admin). The CR lifecycle allows draft→submitted
    # for Developer but submitted→approved only for Admin.
    from app.db.models.user import User
    from app.core.security import get_password_hash

    dev = User(
        tenant_id=test_tenant.id,
        username="devuser",
        email="dev@test.com",
        password_hash=get_password_hash("devpass123"),
        role="Developer",
        is_active=True,
    )
    db_session.add(dev)
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "devuser", "password": "devpass123", "tenant_slug": test_tenant.slug},
    )
    token = login.json()["access_token"]
    dev_headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/v1/change-requests",
        headers=dev_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    cr_id = create.json()["id"]

    # Developer can submit
    r = await client.post(
        f"/api/v1/change-requests/{cr_id}/transition",
        headers=dev_headers,
        json={"to_state": "submitted"},
    )
    assert r.status_code == 200

    # Developer CANNOT approve — should 400
    r2 = await client.post(
        f"/api/v1/change-requests/{cr_id}/transition",
        headers=dev_headers,
        json={"to_state": "approved"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_allowed_transitions_endpoint(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    create = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    cr_id = create.json()["id"]

    r = await client.get(
        f"/api/v1/change-requests/{cr_id}/allowed-transitions", headers=auth_headers
    )
    assert r.status_code == 200
    ts = r.json()
    assert any(t["to_state"] == "submitted" for t in ts)


# ── Soft delete + tenant isolation ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_soft_delete_hides_from_list_and_get(
    client, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    create = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    cr_id = create.json()["id"]

    d = await client.delete(f"/api/v1/change-requests/{cr_id}", headers=auth_headers)
    assert d.status_code == 204

    # List no longer returns it
    assert not any(
        c["id"] == cr_id
        for c in (await client.get("/api/v1/change-requests", headers=auth_headers)).json()
    )
    # Detail → 404
    assert (await client.get(f"/api/v1/change-requests/{cr_id}", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_preview_outage_conflicts_returns_overlapping_bookings(
    client: AsyncClient,
    auth_headers,
    test_environment,
    test_booking,  # +1d → +3d from now in test_environment
):
    # test_booking is scheduled roughly +1d → +3d; craft an outage window that overlaps.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        "/api/v1/change-requests/preview-outage-conflicts",
        headers=auth_headers,
        json={
            "environment_ids": [test_environment.id],
            "host_ids": [],
            "outage_start": (now + timedelta(days=1, hours=6)).isoformat(),
            "outage_end": (now + timedelta(days=1, hours=12)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["derived_environment_ids"] == []
    assert len(payload["environments"]) == 1
    env_block = payload["environments"][0]
    assert env_block["environment_id"] == test_environment.id
    assert len(env_block["conflicts"]) == 1
    assert env_block["conflicts"][0]["id"] == test_booking.id


@pytest.mark.asyncio
async def test_preview_outage_conflicts_empty_when_no_overlap(
    client: AsyncClient,
    auth_headers,
    test_environment,
    test_booking,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        "/api/v1/change-requests/preview-outage-conflicts",
        headers=auth_headers,
        json={
            "environment_ids": [test_environment.id],
            "host_ids": [],
            "outage_start": (now + timedelta(days=30)).isoformat(),
            "outage_end": (now + timedelta(days=31)).isoformat(),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["derived_environment_ids"] == []
    assert body["environments"][0]["conflicts"] == []


@pytest.mark.asyncio
async def test_preview_outage_conflicts_rejects_reversed_window(
    client: AsyncClient, auth_headers, test_environment,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    r = await client.post(
        "/api/v1/change-requests/preview-outage-conflicts",
        headers=auth_headers,
        json={
            "environment_ids": [test_environment.id],
            "host_ids": [],
            "outage_start": (now + timedelta(days=2)).isoformat(),
            "outage_end": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_tenant_isolation(
    client, db_session, auth_headers, test_subsystem, test_environment, test_cr_lifecycle,
):
    # Create a CR in tenant A
    create = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(test_subsystem.id, test_environment.id, test_cr_lifecycle.id),
    )
    cr_id = create.json()["id"]

    # Create a second tenant + admin user and log in as them
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash

    other = Tenant(name="Other Org", slug="other-org")
    db_session.add(other)
    await db_session.flush()
    other_admin = User(
        tenant_id=other.id,
        username="otheradmin",
        email="other@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(other_admin)
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "otheradmin", "password": "password123", "tenant_slug": other.slug},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Tenant B can't see tenant A's CR
    assert (
        await client.get(f"/api/v1/change-requests/{cr_id}", headers=other_headers)
    ).status_code == 404
    assert (await client.get("/api/v1/change-requests", headers=other_headers)).json() == []
