"""End-to-end: admin defines a release_change custom field, scope item create/update
round-trips the value, and subtype-scoped fields only apply to their kind."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate


@pytest_asyncio.fixture
async def release_lifecycle(db_session: AsyncSession, test_tenant):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Standard Release",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "done", "label": "Done", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "done", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


async def _setup_release(client, headers) -> int:
    r = await client.post(
        "/api/v1/releases", headers=headers,
        json={"name": "R", "release_type": "Major"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_unscoped_field_applies_to_every_kind(client: AsyncClient, auth_headers, release_lifecycle):
    """A field with entity_subtype=null shows up on story AND defect items."""
    # Define an unscoped field
    f = await client.post(
        "/api/v1/tenant/fields", headers=auth_headers,
        json={"entity_type": "release_change", "label": "Theme", "field_type": "text"},
    )
    assert f.status_code == 201, f.text

    rid = await _setup_release(client, auth_headers)

    # Story item — value persists
    s = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "S", "change_kind": "story", "custom_fields": {"theme": "Onboarding"}},
    )
    assert s.status_code == 201, s.text
    assert s.json()["custom_fields"]["theme"] == "Onboarding"

    # Defect item — value also persists
    d = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "D", "change_kind": "defect", "custom_fields": {"theme": "Perf"}},
    )
    assert d.status_code == 201, d.text
    assert d.json()["custom_fields"]["theme"] == "Perf"


@pytest.mark.asyncio
async def test_subtype_required_field_is_enforced_on_matching_kind(
    client: AsyncClient, auth_headers, release_lifecycle,
):
    """A required defect-only field blocks creating a defect without it, but not a story."""
    await client.post(
        "/api/v1/tenant/fields", headers=auth_headers,
        json={
            "entity_type": "release_change", "entity_subtype": "defect",
            "label": "Prod Bug Ref", "field_type": "text", "required": True,
        },
    )
    rid = await _setup_release(client, auth_headers)

    # Defect without the required field → 422
    d = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "D1", "change_kind": "defect"},
    )
    assert d.status_code == 422, d.text

    # Story without it → 201 (field doesn't apply)
    s = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "S1", "change_kind": "story"},
    )
    assert s.status_code == 201, s.text


@pytest.mark.asyncio
async def test_update_change_validates_type(client: AsyncClient, auth_headers, release_lifecycle):
    await client.post(
        "/api/v1/tenant/fields", headers=auth_headers,
        json={"entity_type": "release_change", "label": "Points", "field_type": "number"},
    )
    rid = await _setup_release(client, auth_headers)
    c = await client.post(
        f"/api/v1/releases/{rid}/changes", headers=auth_headers,
        json={"title": "C", "change_kind": "story"},
    )
    change_id = c.json()["id"]

    # Submitting a non-numeric value for a number field → 422
    bad = await client.put(
        f"/api/v1/release-changes/{change_id}", headers=auth_headers,
        json={"custom_fields": {"points": "not-a-number"}},
    )
    assert bad.status_code == 422, bad.text

    # Submitting a valid value → 200
    ok = await client.put(
        f"/api/v1/release-changes/{change_id}", headers=auth_headers,
        json={"custom_fields": {"points": 5}},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["custom_fields"]["points"] == 5
