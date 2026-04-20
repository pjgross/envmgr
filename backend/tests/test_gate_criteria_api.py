from datetime import datetime, timezone, timedelta
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate


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
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft",     "to_state": "submitted", "allowed_roles": ["Admin"]},
                {"from_state": "submitted", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft":     {"standard_fields": {}, "custom_fields": {}},
                "submitted": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


async def _make_release_with_gate(client: AsyncClient, headers: dict) -> tuple[int, int]:
    """Create a release and a gate under it. Returns (release_id, gate_id)."""
    rel = await client.post(
        "/api/v1/releases",
        headers=headers,
        json={"name": "R", "release_type": "Major"},
    )
    assert rel.status_code == 201, rel.text
    rid = rel.json()["id"]

    gate = await client.post(
        f"/api/v1/releases/{rid}/gates",
        headers=headers,
        json={"name": "SIT Exit"},
    )
    assert gate.status_code == 201, gate.text
    return rid, gate.json()["id"]


@pytest.mark.asyncio
async def test_create_list_criterion(client: AsyncClient, auth_headers: dict, lifecycle):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    resp = await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "Zero Sev1"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "Zero Sev1"
    assert data["status"] == "open"
    assert data["is_overdue"] is False

    lst = await client.get(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria", headers=auth_headers,
    )
    assert lst.status_code == 200
    items = lst.json()
    assert len(items) == 1
    assert items[0]["id"] == data["id"]


@pytest.mark.asyncio
async def test_complete_triggers_gate_autopass(client: AsyncClient, auth_headers: dict, lifecycle):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    crit = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "A"},
    )).json()

    resp = await client.post(
        f"/api/v1/gate-criteria/{crit['id']}/complete", headers=auth_headers,
    )
    assert resp.status_code == 200

    # Gate should now be passed (via GET /releases/{rid}/gates)
    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert gates[0]["status"] == "passed"


@pytest.mark.asyncio
async def test_reopen_does_not_revert_gate(client: AsyncClient, auth_headers: dict, lifecycle):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    crit = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "A"},
    )).json()
    await client.post(f"/api/v1/gate-criteria/{crit['id']}/complete", headers=auth_headers)
    await client.post(f"/api/v1/gate-criteria/{crit['id']}/reopen", headers=auth_headers)

    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert gates[0]["status"] == "passed"


@pytest.mark.asyncio
async def test_release_overdue_endpoint(client: AsyncClient, auth_headers: dict, lifecycle):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    overdue = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "late", "due_date": past},
    )).json()
    _future = await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "future"},
    )

    resp = await client.get(f"/api/v1/releases/{rid}/overdue-criteria", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["id"] for r in rows] == [overdue["id"]]
    assert rows[0]["gate_name"] == "SIT Exit"
    assert rows[0]["is_overdue"] is True


@pytest.mark.asyncio
async def test_gate_list_includes_criteria_and_count(
    client: AsyncClient, auth_headers: dict, lifecycle,
):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "late", "due_date": past},
    )
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "ontime"},
    )

    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert len(gates[0]["criteria"]) == 2
    assert gates[0]["overdue_criterion_count"] == 1


@pytest.mark.asyncio
async def test_list_releases_includes_overdue_count(
    client: AsyncClient, auth_headers: dict, lifecycle,
):
    rid, gid = await _make_release_with_gate(client, auth_headers)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "late", "due_date": past},
    )
    releases = (await client.get("/api/v1/releases", headers=auth_headers)).json()
    row = next(r for r in releases if r["id"] == rid)
    assert row["overdue_criterion_count"] == 1
