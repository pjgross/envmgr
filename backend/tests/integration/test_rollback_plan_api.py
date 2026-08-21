"""Phase 9 C4 Task 2 — rollback plan CRUD, over HTTP.

Covers the PUT/GET round trip and the extra="forbid" schema guard. The
service-level tests (backend/tests/test_rollback_plan.py) cover the 404s and
the upsert/agree/clear-on-edit rules directly.
"""
import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user) -> Release:
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Standard Release",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
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
    db_session.add(template)
    await db_session.flush()
    r = Release(
        tenant_id=test_tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


@pytest_asyncio.fixture
async def system(db_session, test_tenant, release) -> System:
    s = System(tenant_id=test_tenant.id, name="Payments API")
    db_session.add(s)
    await db_session.flush()
    db_session.add(
        ReleaseSystem(
            tenant_id=test_tenant.id,
            release_id=release.id,
            system_id=s.id,
            role="changing",
        )
    )
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest.mark.asyncio
async def test_a_plan_round_trips_over_http(client, auth_headers, release, system):
    put = await client.put(
        f"/api/v1/releases/{release.id}/rollback-plans",
        json={"system_id": system.id, "steps": "Redeploy previous artefact",
              "reversibility": "lossy", "estimated_minutes": 20},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    got = await client.get(
        f"/api/v1/releases/{release.id}/rollback-plans", headers=auth_headers
    )
    assert got.status_code == 200
    body = got.json()
    assert len(body) == 1
    assert body[0]["reversibility"] == "lossy"
    assert body[0]["estimated_minutes"] == 20
    assert body[0]["agreed_at"] is None
    assert body[0]["system_name"] == "Payments API"


@pytest.mark.asyncio
async def test_an_unknown_key_is_a_422(client, auth_headers, release, system):
    """The schema is extra='forbid', so a typo cannot be silently dropped."""
    resp = await client.put(
        f"/api/v1/releases/{release.id}/rollback-plans",
        json={"system_id": system.id, "steps": "s", "reversibility": "reversible",
              "reversibilty": "typo"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_agreeing_a_plan_over_http(client, auth_headers, release, system):
    put = await client.put(
        f"/api/v1/releases/{release.id}/rollback-plans",
        json={"system_id": system.id, "steps": "s", "reversibility": "reversible"},
        headers=auth_headers,
    )
    plan_id = put.json()["id"]

    agreed = await client.post(
        f"/api/v1/releases/{release.id}/rollback-plans/{plan_id}/agree",
        headers=auth_headers,
    )
    assert agreed.status_code == 200, agreed.text
    body = agreed.json()
    assert body["agreed_at"] is not None
    assert body["agreed_by_username"] is not None


@pytest.mark.asyncio
async def test_deleting_a_plan_over_http(client, auth_headers, release, system):
    put = await client.put(
        f"/api/v1/releases/{release.id}/rollback-plans",
        json={"system_id": system.id, "steps": "s", "reversibility": "reversible"},
        headers=auth_headers,
    )
    plan_id = put.json()["id"]

    deleted = await client.delete(
        f"/api/v1/releases/{release.id}/rollback-plans/{plan_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204

    got = await client.get(
        f"/api/v1/releases/{release.id}/rollback-plans", headers=auth_headers
    )
    assert got.json() == []
