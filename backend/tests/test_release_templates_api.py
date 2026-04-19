"""Tests for the release_templates API — Task 23."""
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate


@pytest.fixture
def _target():
    return (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()


import pytest_asyncio


@pytest_asyncio.fixture
async def lifecycle(db_session: AsyncSession, test_tenant):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Standard Release",
        is_default=True,
        definition={
            "states": [
                {"key": "draft",     "label": "Draft",     "is_initial": True,  "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


@pytest_asyncio.fixture
async def template(client: AsyncClient, auth_headers, lifecycle):
    resp = await client.post("/api/v1/release-templates", headers=auth_headers, json={
        "name": "Standard Major",
        "release_type": "major",
        "default_lifecycle_template_id": lifecycle.id,
        "phases": [
            {"name": "SIT", "order": 1, "default_duration_days": 7},
            {"name": "UAT", "order": 2, "default_duration_days": 5},
        ],
        "gates": [
            {"name": "Go/No-Go", "phase_name": "UAT"},
        ],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Happy path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_template(client: AsyncClient, auth_headers, lifecycle):
    resp = await client.post("/api/v1/release-templates", headers=auth_headers, json={
        "name": "Quick Fix Template",
        "release_type": "patch",
        "default_lifecycle_template_id": lifecycle.id,
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Quick Fix Template"
    assert data["version"] == 1


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient, auth_headers, template):
    resp = await client.get("/api/v1/release-templates", headers=auth_headers)
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert template["id"] in ids


@pytest.mark.asyncio
async def test_get_template(client: AsyncClient, auth_headers, template):
    resp = await client.get(f"/api/v1/release-templates/{template['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == template["name"]


@pytest.mark.asyncio
async def test_update_template(client: AsyncClient, auth_headers, template):
    resp = await client.put(
        f"/api/v1/release-templates/{template['id']}",
        headers=auth_headers,
        json={"name": "Standard Major v2"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Standard Major v2"
    assert data["version"] == 2  # version bumped


@pytest.mark.asyncio
async def test_delete_template(client: AsyncClient, auth_headers, lifecycle):
    r = await client.post("/api/v1/release-templates", headers=auth_headers, json={
        "name": "To Delete",
        "release_type": "minor",
    })
    tid = r.json()["id"]
    resp = await client.delete(f"/api/v1/release-templates/{tid}", headers=auth_headers)
    assert resp.status_code == 204
    resp2 = await client.get(f"/api/v1/release-templates/{tid}", headers=auth_headers)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_instantiate_template(client: AsyncClient, auth_headers, template, _target):
    resp = await client.post(
        f"/api/v1/release-templates/{template['id']}/instantiate",
        headers=auth_headers,
        json={
            "name": "Release from template",
            "target_date": _target,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Release from template"
    assert data["status"] == "draft"
    assert data["template_id"] == template["id"]


# ── Negative ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_template_not_found(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/release-templates/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_template_not_found(client: AsyncClient, auth_headers):
    resp = await client.put(
        "/api/v1/release-templates/99999",
        headers=auth_headers,
        json={"name": "ghost"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_instantiate_not_found(client: AsyncClient, auth_headers, _target):
    resp = await client.post(
        "/api/v1/release-templates/99999/instantiate",
        headers=auth_headers,
        json={"name": "ghost release", "target_date": _target},
    )
    assert resp.status_code == 404
