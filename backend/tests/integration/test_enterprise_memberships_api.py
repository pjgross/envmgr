"""HTTP integration tests for the enterprise membership API endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash


# ── Helpers ───────────────────────────────────────────────────────────────────


ENTERPRISE_LIFECYCLE_DEF = {
    "states": [
        {"key": "admission_open", "label": "Admission Open", "is_initial": True, "is_terminal": False},
        {"key": "admission_closed", "label": "Admission Closed", "is_initial": False, "is_terminal": False, "is_admission_lockdown": True},
    ],
    "transitions": [
        {"from_state": "admission_open", "to_state": "admission_closed", "allowed_roles": ["Admin"]},
    ],
    "field_permissions": {
        "admission_open": {"standard_fields": {}, "custom_fields": {}},
        "admission_closed": {"standard_fields": {}, "custom_fields": {}},
    },
    "action_permissions": {
        "admission_open": {
            "membership.admit": ["Admin"],
            "membership.reject": ["Admin"],
            "membership.remove": ["Admin"],
        },
        "admission_closed": {
            "membership.admit": ["Admin"],
            "membership.reject": ["Admin"],
            "membership.remove": ["Admin"],
        },
    },
}

PROJECT_LIFECYCLE_DEF = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
    ],
    "transitions": [],
    "field_permissions": {
        "draft": {"standard_fields": {}, "custom_fields": {}},
    },
}


async def _make_template(
    db: AsyncSession,
    tenant_id: int,
    name: str,
    definition: dict,
    is_default: bool = False,
) -> LifecycleTemplate:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=name,
        is_default=is_default,
        definition=definition,
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def _make_enterprise(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    template_id: int,
    name: str = "Enterprise R",
) -> Release:
    r = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Major",
        release_kind="enterprise",
        lifecycle_template_id=template_id,
        status="admission_open",
        raised_by=user_id,
    )
    db.add(r)
    await db.flush()
    return r


async def _make_project(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    template_id: int,
    name: str = "Project R",
) -> Release:
    r = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Minor",
        release_kind="project",
        lifecycle_template_id=template_id,
        status="draft",
        raised_by=user_id,
    )
    db.add(r)
    await db.flush()
    return r


# ── Per-test fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def setup(db_session: AsyncSession, test_tenant: Tenant, test_user: User, auth_headers: dict):
    """Create enterprise+project releases + return (auth_headers, enterprise_id, project_release_id)."""
    ent_tpl = await _make_template(db_session, test_tenant.id, "Ent-Tpl", ENTERPRISE_LIFECYCLE_DEF)
    proj_tpl = await _make_template(db_session, test_tenant.id, "Proj-Tpl", PROJECT_LIFECYCLE_DEF, is_default=True)
    enterprise = await _make_enterprise(db_session, test_tenant.id, test_user.id, ent_tpl.id)
    project = await _make_project(db_session, test_tenant.id, test_user.id, proj_tpl.id)
    await db_session.commit()
    return {
        "headers": auth_headers,
        "enterprise_id": enterprise.id,
        "project_release_id": project.id,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_membership_endpoint(client: AsyncClient, setup: dict):
    """POST /releases/{eid}/memberships → 201, state=pending_request."""
    headers = setup["headers"]
    eid = setup["enterprise_id"]
    pid = setup["project_release_id"]

    resp = await client.post(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        json={"project_release_id": pid, "notes": "Please admit us"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "pending_request"
    assert body["project_release_id"] == pid
    assert body["enterprise_release_id"] == eid
    assert body["notes"] == "Please admit us"


@pytest.mark.asyncio
async def test_list_memberships_filter_by_state(client: AsyncClient, setup: dict):
    """POST request, then GET /memberships?states=pending_request → exactly 1 result."""
    headers = setup["headers"]
    eid = setup["enterprise_id"]
    pid = setup["project_release_id"]

    await client.post(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        json={"project_release_id": pid},
    )

    resp = await client.get(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        params={"states": "pending_request"},
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["state"] == "pending_request"


@pytest.mark.asyncio
async def test_accept_endpoint(client: AsyncClient, setup: dict):
    """POST request, extract id, POST .../accept → 200, state=accepted."""
    headers = setup["headers"]
    eid = setup["enterprise_id"]
    pid = setup["project_release_id"]

    req_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        json={"project_release_id": pid},
    )
    assert req_resp.status_code == 201, req_resp.text
    mid = req_resp.json()["id"]

    accept_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/accept",
        headers=headers,
    )
    assert accept_resp.status_code == 200, accept_resp.text
    assert accept_resp.json()["state"] == "accepted"


@pytest.mark.asyncio
async def test_reject_endpoint_requires_notes(client: AsyncClient, setup: dict):
    """POST request, POST .../reject with notes → 200, state=rejected.
    Also: POST .../reject with empty body → 422."""
    headers = setup["headers"]
    eid = setup["enterprise_id"]
    pid = setup["project_release_id"]

    req_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        json={"project_release_id": pid},
    )
    assert req_resp.status_code == 201, req_resp.text
    mid = req_resp.json()["id"]

    # Missing notes → 422
    bad_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/reject",
        headers=headers,
        json={},
    )
    assert bad_resp.status_code == 422, bad_resp.text

    # With notes → 200
    ok_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/reject",
        headers=headers,
        json={"notes": "out of scope"},
    )
    assert ok_resp.status_code == 200, ok_resp.text
    assert ok_resp.json()["state"] == "rejected"


@pytest.mark.asyncio
async def test_remove_endpoint_requires_reason(client: AsyncClient, setup: dict):
    """Accept, then POST .../remove with reason → 200, state=removed."""
    headers = setup["headers"]
    eid = setup["enterprise_id"]
    pid = setup["project_release_id"]

    req_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        json={"project_release_id": pid},
    )
    assert req_resp.status_code == 201, req_resp.text
    mid = req_resp.json()["id"]

    await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/accept",
        headers=headers,
    )

    # Missing reason → 422
    bad_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/remove",
        headers=headers,
        json={},
    )
    assert bad_resp.status_code == 422, bad_resp.text

    # With reason → 200
    ok_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/remove",
        headers=headers,
        json={"reason": "dropped"},
    )
    assert ok_resp.status_code == 200, ok_resp.text
    assert ok_resp.json()["state"] == "removed"


@pytest.mark.asyncio
async def test_withdraw_endpoint(client: AsyncClient, setup: dict):
    """POST request, POST .../withdraw → 200, state=withdrawn."""
    headers = setup["headers"]
    eid = setup["enterprise_id"]
    pid = setup["project_release_id"]

    req_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        json={"project_release_id": pid},
    )
    assert req_resp.status_code == 201, req_resp.text
    mid = req_resp.json()["id"]

    withdraw_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/withdraw",
        headers=headers,
    )
    assert withdraw_resp.status_code == 200, withdraw_resp.text
    assert withdraw_resp.json()["state"] == "withdrawn"


@pytest.mark.asyncio
async def test_project_membership_endpoint(client: AsyncClient, setup: dict):
    """Accept, then GET /releases/{project_id}/membership → {current, history}."""
    headers = setup["headers"]
    eid = setup["enterprise_id"]
    pid = setup["project_release_id"]

    req_resp = await client.post(
        f"/api/v1/releases/{eid}/memberships",
        headers=headers,
        json={"project_release_id": pid},
    )
    assert req_resp.status_code == 201, req_resp.text
    mid = req_resp.json()["id"]

    await client.post(
        f"/api/v1/releases/{eid}/memberships/{mid}/accept",
        headers=headers,
    )

    view_resp = await client.get(
        f"/api/v1/releases/{pid}/membership",
        headers=headers,
    )
    assert view_resp.status_code == 200, view_resp.text
    data = view_resp.json()
    assert "current" in data
    assert "history" in data
    assert data["current"] is not None
    assert data["current"]["state"] == "accepted"
    assert len(data["history"]) >= 1


@pytest.mark.asyncio
async def test_cross_tenant_returns_404(
    client: AsyncClient,
    setup: dict,
    db_session: AsyncSession,
):
    """Other-tenant admin trying to GET memberships of first tenant's enterprise → 404."""
    eid = setup["enterprise_id"]

    # Create second tenant + user
    other_tenant = Tenant(name="Other Org", slug="other-org-memb")
    db_session.add(other_tenant)
    await db_session.flush()

    other_user = User(
        tenant_id=other_tenant.id,
        username="otheradmin_memb",
        email="otheradmin_memb@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()

    # Login as other tenant
    login_resp = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    assert login_resp.status_code == 200, login_resp.text
    other_token = login_resp.json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    # Try to access first tenant's enterprise memberships
    resp = await client.get(
        f"/api/v1/releases/{eid}/memberships",
        headers=other_headers,
    )
    assert resp.status_code == 404, resp.text
