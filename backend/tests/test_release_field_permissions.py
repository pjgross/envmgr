import pytest
from httpx import AsyncClient


RELEASE_DEF = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "name": {"editable_by": ["Admin", "Release Manager"]},
                "description": {"editable_by": ["Admin"]},
            },
            "custom_fields": {
                "sign_off": {"editable_by": ["Admin"]},
            },
        },
        "approved": {
            "standard_fields": {
                "name": {"editable_by": []},
            },
            "custom_fields": {
                "sign_off": {"editable_by": []},
            },
        },
    },
}


async def _setup_release(client: AsyncClient, headers: dict) -> int:
    """Create a release-entity lifecycle template, a release custom-field def,
    then create a release on that template. Returns release_id."""
    tmpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=headers,
        json={"name": "R Tmpl", "entity_type": "release", "definition": RELEASE_DEF},
    )
    assert tmpl.status_code == 201, tmpl.text
    tmpl_id = tmpl.json()["id"]

    cf = await client.post(
        "/api/v1/tenant/fields",
        headers=headers,
        json={"entity_type": "release", "label": "Sign Off", "field_key": "sign_off", "field_type": "text"},
    )
    assert cf.status_code in (200, 201), cf.text

    release = await client.post(
        "/api/v1/releases",
        headers=headers,
        json={
            "name": "Perm Test Release",
            "release_type": "project",
            "lifecycle_template_id": tmpl_id,
            "custom_fields": {"sign_off": "pending"},
        },
    )
    assert release.status_code == 201, release.text
    return release.json()["id"]


@pytest.mark.asyncio
async def test_get_release_includes_permissions(client: AsyncClient, auth_headers: dict):
    """GET /releases/{id} must include custom_field_permissions and standard_field_permissions."""
    release_id = await _setup_release(client, auth_headers)

    resp = await client.get(f"/api/v1/releases/{release_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "custom_field_permissions" in data
    assert "standard_field_permissions" in data

    # Admin in draft state can edit sign_off
    assert data["custom_field_permissions"]["sign_off"] == {"visible": True, "editable": True}
    # Admin in draft state can edit name + description
    assert data["standard_field_permissions"]["name"] == {"editable": True}
    assert data["standard_field_permissions"]["description"] == {"editable": True}
    # target_date is a valid standard field but not listed in state → not editable
    assert data["standard_field_permissions"]["target_date"] == {"editable": False}


@pytest.mark.asyncio
async def test_transition_release_returns_updated_permissions(client: AsyncClient, auth_headers: dict):
    """POST /releases/{id}/transition response has permissions reflecting the NEW state."""
    release_id = await _setup_release(client, auth_headers)

    resp = await client.post(
        f"/api/v1/releases/{release_id}/transition",
        headers=auth_headers,
        json={"to_state": "approved"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "approved"
    # In approved state, name has empty editable_by → not editable
    assert data["standard_field_permissions"]["name"] == {"editable": False}
    assert data["custom_field_permissions"]["sign_off"] == {"visible": True, "editable": False}


@pytest.mark.asyncio
async def test_update_release_returns_permissions(client: AsyncClient, auth_headers: dict):
    """PUT /releases/{id} response includes permissions (same shape as GET)."""
    release_id = await _setup_release(client, auth_headers)

    resp = await client.put(
        f"/api/v1/releases/{release_id}",
        headers=auth_headers,
        json={"description": "updated"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "custom_field_permissions" in data
    assert "standard_field_permissions" in data


@pytest.mark.asyncio
async def test_get_release_field_permissions_missing_template_fail_closed(db_session):
    """If the release's lifecycle_template_id doesn't resolve, return fail-closed maps."""
    from app.db.models.release import Release
    from app.services.release_service import get_release_field_permissions

    release = Release(
        tenant_id=1,
        name="ghost",
        description=None,
        release_type="project",
        release_kind="project",
        lifecycle_template_id=9999,  # does not exist
        status="draft",
        raised_by=1,
        custom_fields={},
    )
    result = await get_release_field_permissions(db_session, release, "Admin")
    assert result["custom_field_permissions"] == {}
    # All valid release standard fields present, all not editable
    assert all(v == {"editable": False} for v in result["standard_field_permissions"].values())
    assert "name" in result["standard_field_permissions"]
