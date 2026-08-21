"""Phase 9 C4 Task 6 — rollback authorisation, over HTTP.

Covers the POST/GET round trip and the routing trap named in the task
assignment: a literal-segment route registered after a `/{id}` catch-all in
the same router gets captured by it (B6's `/bookings/contention-horizon` bug).
This file proves `/{release_id}/rollback-authorisations` is NOT swallowed by
`GET /{release_id}` by actually calling it over HTTP, rather than reasoning
about FastAPI's route-matching rules in advance.

The service-level tests (backend/tests/test_rollback_authorisation.py) cover
the 404s and the tenant-filter mutation proof directly.
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
async def test_an_authorisation_round_trips_over_http(client, auth_headers, release, system):
    post = await client.post(
        f"/api/v1/releases/{release.id}/rollback-authorisations",
        json={
            "decided_at": "2026-08-21T02:14:00Z",
            "trigger": "Checkout error rate above 5% for 10 minutes",
            "rationale": "Reverting to the previous build while we investigate",
            "system_ids": [system.id],
        },
        headers=auth_headers,
    )
    assert post.status_code == 201, post.text
    body = post.json()
    assert body["system_ids"] == [system.id]
    assert body["system_names"] == ["Payments API"]
    assert body["decided_by_username"] is not None

    got = await client.get(
        f"/api/v1/releases/{release.id}/rollback-authorisations", headers=auth_headers
    )
    assert got.status_code == 200
    listed = got.json()
    assert len(listed) == 1
    assert listed[0]["trigger"] == "Checkout error rate above 5% for 10 minutes"


@pytest.mark.asyncio
async def test_an_unknown_key_is_a_422(client, auth_headers, release, system):
    """The schema is extra='forbid', so a typo cannot be silently dropped."""
    resp = await client.post(
        f"/api/v1/releases/{release.id}/rollback-authorisations",
        json={
            "decided_at": "2026-08-21T02:14:00Z",
            "trigger": "t",
            "rationale": "r",
            "system_ids": [system.id],
            "sytsem_ids": [system.id],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_empty_system_list_is_a_422_over_http(client, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/rollback-authorisations",
        json={"decided_at": "2026-08-21T02:14:00Z", "trigger": "t", "rationale": "r",
              "system_ids": []},
        headers=auth_headers,
    )
    assert resp.status_code == 422
