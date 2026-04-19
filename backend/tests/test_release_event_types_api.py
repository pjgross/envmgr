"""Tests for the release_event_types API — Task 23."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.release_event import ReleaseEventType

import pytest_asyncio


@pytest_asyncio.fixture
async def system_event_type(db_session: AsyncSession, test_tenant):
    """A system event type that cannot be renamed or deleted."""
    et = ReleaseEventType(
        tenant_id=test_tenant.id,
        name="Stakeholder Note",
        is_system=True,
    )
    db_session.add(et)
    await db_session.commit()
    await db_session.refresh(et)
    return et


@pytest_asyncio.fixture
async def custom_event_type(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v1/release-event-types", headers=auth_headers, json={
        "name": "Code Freeze",
        "display_color": "#ff0000",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Happy path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_event_type(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v1/release-event-types", headers=auth_headers, json={
        "name": "Milestone",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Milestone"
    assert data["is_system"] is False


@pytest.mark.asyncio
async def test_list_event_types(client: AsyncClient, auth_headers, custom_event_type):
    resp = await client.get("/api/v1/release-event-types", headers=auth_headers)
    assert resp.status_code == 200
    ids = [et["id"] for et in resp.json()]
    assert custom_event_type["id"] in ids


@pytest.mark.asyncio
async def test_update_event_type(client: AsyncClient, auth_headers, custom_event_type):
    resp = await client.put(
        f"/api/v1/release-event-types/{custom_event_type['id']}",
        headers=auth_headers,
        json={"display_color": "#00ff00"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_color"] == "#00ff00"


@pytest.mark.asyncio
async def test_delete_event_type(client: AsyncClient, auth_headers):
    r = await client.post("/api/v1/release-event-types", headers=auth_headers, json={
        "name": "To Delete",
    })
    et_id = r.json()["id"]
    resp = await client.delete(f"/api/v1/release-event-types/{et_id}", headers=auth_headers)
    assert resp.status_code == 204


# ── Negative ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_system_event_type_rename_rejected(
    client: AsyncClient, auth_headers, system_event_type
):
    """System event types cannot be renamed."""
    resp = await client.put(
        f"/api/v1/release-event-types/{system_event_type.id}",
        headers=auth_headers,
        json={"name": "Hacked Name"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_system_event_type_color_allowed(
    client: AsyncClient, auth_headers, system_event_type
):
    """System event types CAN have their display_color changed."""
    resp = await client.put(
        f"/api/v1/release-event-types/{system_event_type.id}",
        headers=auth_headers,
        json={"display_color": "#aabbcc"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_color"] == "#aabbcc"


@pytest.mark.asyncio
async def test_delete_system_event_type_rejected(
    client: AsyncClient, auth_headers, system_event_type
):
    resp = await client.delete(
        f"/api/v1/release-event-types/{system_event_type.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_not_found(client: AsyncClient, auth_headers):
    resp = await client.put(
        "/api/v1/release-event-types/99999",
        headers=auth_headers,
        json={"name": "ghost"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_not_found(client: AsyncClient, auth_headers):
    resp = await client.delete(
        "/api/v1/release-event-types/99999",
        headers=auth_headers,
    )
    assert resp.status_code == 404
