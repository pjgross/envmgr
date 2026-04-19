"""Integration tests for the unified /environments/{id}/schedule endpoint
(Phase 2 Step 4).
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.system import System, SubSystem


@pytest_asyncio.fixture(scope="function")
async def test_subsystem(db_session, test_tenant):
    sys = System(tenant_id=test_tenant.id, name="ScheduleSys", description=None)
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(
        tenant_id=test_tenant.id,
        system_id=sys.id,
        name="ScheduleSub",
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
        name="CR Default",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


def _cr_payload(sub_id, env_id, lifecycle_id, start, end, **overrides):
    payload = {
        "title": "Schedule CR",
        "change_type": "configuration",
        "lifecycle_id": lifecycle_id,
        "subsystem_id": sub_id,
        "environment_ids": [env_id] if env_id is not None else [],
        "host_ids": [],
        "has_outage": False,
        "scheduled_start": start.isoformat(),
        "scheduled_end": end.isoformat(),
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_schedule_returns_empty_shape_when_nothing_in_window(
    client: AsyncClient, auth_headers, test_environment,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = (now + timedelta(days=30)).isoformat()
    end = (now + timedelta(days=60)).isoformat()

    resp = await client.get(
        f"/api/v1/environments/{test_environment.id}/schedule",
        headers=auth_headers,
        params={"start_date": start, "end_date": end},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["environment_id"] == test_environment.id
    assert body["bookings"] == []
    assert body["change_requests"] == []
    assert body["deployments"] == []


@pytest.mark.asyncio
async def test_schedule_returns_bookings_and_change_requests(
    client: AsyncClient,
    auth_headers,
    test_environment,
    test_booking,
    test_subsystem,
    test_cr_lifecycle,
):
    # test_booking fixture creates a booking starting +1d, ending +3d from now.
    # Put a CR in the overlapping window.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cr_start = now + timedelta(days=1, hours=6)
    cr_end = now + timedelta(days=1, hours=9)

    cr_resp = await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(
            test_subsystem.id, test_environment.id, test_cr_lifecycle.id, cr_start, cr_end
        ),
    )
    assert cr_resp.status_code == 201, cr_resp.text

    window_start = (now - timedelta(hours=1)).isoformat()
    window_end = (now + timedelta(days=7)).isoformat()

    resp = await client.get(
        f"/api/v1/environments/{test_environment.id}/schedule",
        headers=auth_headers,
        params={"start_date": window_start, "end_date": window_end},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["bookings"]) == 1
    assert body["bookings"][0]["id"] == test_booking.id
    assert body["bookings"][0]["environment_id"] == test_environment.id
    assert len(body["change_requests"]) == 1
    assert body["change_requests"][0]["title"] == "Schedule CR"
    assert body["change_requests"][0]["has_outage"] is False
    assert body["deployments"] == []


@pytest.mark.asyncio
async def test_schedule_filters_out_items_outside_window(
    client: AsyncClient,
    auth_headers,
    test_environment,
    test_subsystem,
    test_cr_lifecycle,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    # CR far in the future
    future_start = now + timedelta(days=100)
    future_end = future_start + timedelta(hours=1)

    await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(
            test_subsystem.id, test_environment.id, test_cr_lifecycle.id, future_start, future_end
        ),
    )

    # Ask for a window that doesn't include the CR
    resp = await client.get(
        f"/api/v1/environments/{test_environment.id}/schedule",
        headers=auth_headers,
        params={
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=7)).isoformat(),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["change_requests"] == []


@pytest.mark.asyncio
async def test_schedule_404_for_unknown_env(client: AsyncClient, auth_headers):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    resp = await client.get(
        "/api/v1/environments/99999/schedule",
        headers=auth_headers,
        params={
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_schedule_tenant_isolation(
    client: AsyncClient,
    db_session,
    auth_headers,
    test_environment,
    test_subsystem,
    test_cr_lifecycle,
):
    # Create a CR in tenant A
    now = datetime.now(timezone.utc).replace(microsecond=0)
    await client.post(
        "/api/v1/change-requests",
        headers=auth_headers,
        json=_cr_payload(
            test_subsystem.id, test_environment.id, test_cr_lifecycle.id,
            now + timedelta(hours=1), now + timedelta(hours=2),
        ),
    )

    # Tenant B shouldn't see tenant A's environment schedule at all
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash

    other = Tenant(name="Other", slug="other-sched")
    db_session.add(other)
    await db_session.flush()
    other_admin = User(
        tenant_id=other.id,
        username="otheradmin2",
        email="o2@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(other_admin)
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "otheradmin2", "password": "password123", "tenant_slug": "other-sched"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(
        f"/api/v1/environments/{test_environment.id}/schedule",
        headers=other_headers,
        params={
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=7)).isoformat(),
        },
    )
    assert resp.status_code == 404
