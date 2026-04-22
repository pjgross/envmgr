"""HTTP integration tests for the enterprise rollup + report API endpoints."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash


# ── Lifecycle definitions ──────────────────────────────────────────────────────

ENTERPRISE_LIFECYCLE_DEF = {
    "states": [
        {"key": "admission_open", "label": "Admission Open", "is_initial": True, "is_terminal": False},
    ],
    "transitions": [],
    "field_permissions": {
        "admission_open": {"standard_fields": {}, "custom_fields": {}},
    },
    "action_permissions": {
        "admission_open": {
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


# ── DB helpers ─────────────────────────────────────────────────────────────────


async def _make_template(
    db: AsyncSession,
    tenant_id: int,
    name: str,
    definition: dict,
    is_default: bool = False,
    applies_to_kind: str | None = None,
) -> LifecycleTemplate:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=name,
        is_default=is_default,
        applies_to_kind=applies_to_kind,
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
    name: str,
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


async def _make_system(db: AsyncSession, tenant_id: int, name: str) -> System:
    s = System(tenant_id=tenant_id, name=name)
    db.add(s)
    await db.flush()
    return s


async def _attach_system(
    db: AsyncSession,
    tenant_id: int,
    release_id: int,
    system_id: int,
    role: str = "changing",
) -> ReleaseSystem:
    rs = ReleaseSystem(
        tenant_id=tenant_id,
        release_id=release_id,
        system_id=system_id,
        role=role,
    )
    db.add(rs)
    await db.flush()
    return rs


async def _make_scope_item(
    db: AsyncSession,
    tenant_id: int,
    release_id: int,
    external_key: str,
    title: str,
    change_kind: str = "story",
) -> ReleaseChange:
    item = ReleaseChange(
        tenant_id=tenant_id,
        release_id=release_id,
        external_key=external_key,
        title=title,
        change_kind=change_kind,
        source="manual",
    )
    db.add(item)
    await db.flush()
    return item


# ── Setup fixture ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def setup(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_user: User,
    auth_headers: dict,
    client: AsyncClient,
):
    """
    Build:
      - 1 enterprise release (admission_open)
      - 2 project releases, each admitted (accepted membership)
      - 1 system attached to each project
      - 1 scope item on each project
    Returns dict with headers, enterprise_id, project_ids, system_ids.
    """
    ent_tpl = await _make_template(
        db_session, test_tenant.id, "Ent-Tpl-Rollup", ENTERPRISE_LIFECYCLE_DEF,
        applies_to_kind="enterprise",
    )
    proj_tpl = await _make_template(
        db_session, test_tenant.id, "Proj-Tpl-Rollup", PROJECT_LIFECYCLE_DEF,
        is_default=True,
    )

    enterprise = await _make_enterprise(
        db_session, test_tenant.id, test_user.id, ent_tpl.id, "Enterprise Rollup API"
    )
    p1 = await _make_project(db_session, test_tenant.id, test_user.id, proj_tpl.id, "Project Alpha")
    p2 = await _make_project(db_session, test_tenant.id, test_user.id, proj_tpl.id, "Project Beta")

    sys_a = await _make_system(db_session, test_tenant.id, "System Alpha")
    sys_b = await _make_system(db_session, test_tenant.id, "System Beta")

    await _attach_system(db_session, test_tenant.id, p1.id, sys_a.id, "changing")
    await _attach_system(db_session, test_tenant.id, p2.id, sys_b.id, "changing")

    await _make_scope_item(db_session, test_tenant.id, p1.id, "SC-A1", "Alpha story", "story")
    await _make_scope_item(db_session, test_tenant.id, p2.id, "SC-B1", "Beta defect", "defect")

    await db_session.commit()

    # Request + accept both memberships via HTTP
    for pid in [p1.id, p2.id]:
        req_resp = await client.post(
            f"/api/v1/releases/{enterprise.id}/memberships",
            headers=auth_headers,
            json={"project_release_id": pid},
        )
        assert req_resp.status_code == 201, req_resp.text
        mid = req_resp.json()["id"]
        acc_resp = await client.post(
            f"/api/v1/releases/{enterprise.id}/memberships/{mid}/accept",
            headers=auth_headers,
        )
        assert acc_resp.status_code == 200, acc_resp.text

    return {
        "headers": auth_headers,
        "enterprise_id": enterprise.id,
        "project_ids": [p1.id, p2.id],
        "system_ids": [sys_a.id, sys_b.id],
    }


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_systems_rollup_returns_list(client: AsyncClient, setup: dict):
    """GET /releases/{eid}/rollup/systems → 200, list with 2 system rows."""
    eid = setup["enterprise_id"]
    headers = setup["headers"]

    resp = await client.get(f"/api/v1/releases/{eid}/rollup/systems", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    system_ids = {row["system_id"] for row in body}
    assert system_ids == set(setup["system_ids"])


@pytest.mark.asyncio
async def test_scope_rollup_filter_by_change_kind(client: AsyncClient, setup: dict):
    """GET /releases/{eid}/rollup/scope?change_kind=story → 200, only story items."""
    eid = setup["enterprise_id"]
    headers = setup["headers"]

    resp = await client.get(
        f"/api/v1/releases/{eid}/rollup/scope",
        headers=headers,
        params={"change_kind": "story"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["change_kind"] == "story"
    assert body[0]["external_key"] == "SC-A1"


@pytest.mark.asyncio
async def test_timeline_rollup_returns_expected_shape(client: AsyncClient, setup: dict):
    """GET /releases/{eid}/rollup/timeline → 200, dict with enterprise_phases/child_phases_by_release/dependencies."""
    eid = setup["enterprise_id"]
    headers = setup["headers"]

    resp = await client.get(f"/api/v1/releases/{eid}/rollup/timeline", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "enterprise_phases" in body
    assert "child_phases_by_release" in body
    assert "dependencies" in body
    assert isinstance(body["enterprise_phases"], list)
    assert isinstance(body["child_phases_by_release"], dict)
    assert isinstance(body["dependencies"], list)


@pytest.mark.asyncio
async def test_members_rollup_returns_accepted_list(client: AsyncClient, setup: dict):
    """GET /releases/{eid}/rollup/members → 200, list of 2 accepted members."""
    eid = setup["enterprise_id"]
    headers = setup["headers"]

    resp = await client.get(f"/api/v1/releases/{eid}/rollup/members", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    project_ids = {row["project_release_id"] for row in body}
    assert project_ids == set(setup["project_ids"])


@pytest.mark.asyncio
async def test_report_endpoint_has_required_keys(client: AsyncClient, setup: dict):
    """GET /releases/{eid}/report → 200, payload has members + systems + scope_by_project."""
    eid = setup["enterprise_id"]
    headers = setup["headers"]

    resp = await client.get(f"/api/v1/releases/{eid}/report", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "members" in body
    assert "systems" in body
    assert "scope_by_project" in body
    assert isinstance(body["members"], list)
    assert isinstance(body["systems"], list)
    assert isinstance(body["scope_by_project"], dict)
    assert len(body["members"]) == 2
    assert len(body["systems"]) == 2
    # Both projects contribute scope items
    assert "Project Alpha" in body["scope_by_project"]
    assert "Project Beta" in body["scope_by_project"]
