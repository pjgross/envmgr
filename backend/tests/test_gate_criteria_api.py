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


async def _make_release_with_gate(
    client: AsyncClient, headers: dict, gate_due_date: str | None = None
) -> tuple[int, int]:
    """Create a release and a gate under it. Returns (release_id, gate_id).

    gate_due_date: ISO string for the gate's due_date; defaults to 7 days from now.
    """
    if gate_due_date is None:
        gate_due_date = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

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
        json={"name": "SIT Exit", "due_date": gate_due_date},
    )
    assert gate.status_code == 201, gate.text
    return rid, gate.json()["id"]


@pytest.mark.asyncio
async def test_gate_list_includes_assignee_username(
    client: AsyncClient, auth_headers: dict, lifecycle, test_user,
):
    """Criterion nested under GET /releases/{id}/gates should carry assignee_username."""
    rid, gid = await _make_release_with_gate(client, auth_headers)
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "A", "assigned_to_user_id": test_user.id},
    )
    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert gates[0]["criteria"][0]["assigned_to_username"] == test_user.username


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
    """Overdue criteria come from gates whose due_date is in the past."""
    past_gate_due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rid, gid = await _make_release_with_gate(client, auth_headers, gate_due_date=past_gate_due)

    # Two criteria on the past-due gate — both are "open" so both should be overdue.
    overdue1 = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "late one"},
    )).json()
    overdue2 = (await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers,
        json={"title": "late two"},
    )).json()

    # A second gate with a future due_date — its criterion should NOT appear.
    future_gate_due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    gate2 = (await client.post(
        f"/api/v1/releases/{rid}/gates",
        headers=auth_headers,
        json={"name": "UAT Exit", "due_date": future_gate_due},
    )).json()
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gate2['id']}/criteria",
        headers=auth_headers,
        json={"title": "future criterion"},
    )

    resp = await client.get(f"/api/v1/releases/{rid}/overdue-criteria", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    overdue_ids = {r["id"] for r in rows}
    assert overdue1["id"] in overdue_ids
    assert overdue2["id"] in overdue_ids
    # gate_name and gate_due_date are hydrated from the parent gate
    assert rows[0]["gate_name"] == "SIT Exit"
    assert rows[0]["gate_due_date"] is not None
    # Future-gate criterion must not appear
    assert gate2["id"] not in {r["gate_id"] for r in rows}


@pytest.mark.asyncio
async def test_gate_list_includes_criteria_and_count(
    client: AsyncClient, auth_headers: dict, lifecycle,
):
    """overdue_criterion_count on the gate reflects open criteria on a past-due gate."""
    past_gate_due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rid, gid = await _make_release_with_gate(client, auth_headers, gate_due_date=past_gate_due)
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "late"},
    )
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "also late"},
    )

    gates = (await client.get(f"/api/v1/releases/{rid}/gates", headers=auth_headers)).json()
    assert len(gates[0]["criteria"]) == 2
    assert gates[0]["overdue_criterion_count"] == 2


@pytest.mark.asyncio
async def test_list_releases_includes_overdue_count(
    client: AsyncClient, auth_headers: dict, lifecycle,
):
    """Release list row carries overdue_criterion_count from past-due gate criteria."""
    past_gate_due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    rid, gid = await _make_release_with_gate(client, auth_headers, gate_due_date=past_gate_due)
    await client.post(
        f"/api/v1/releases/{rid}/gates/{gid}/criteria",
        headers=auth_headers, json={"title": "late"},
    )
    releases = (await client.get("/api/v1/releases", headers=auth_headers)).json()
    row = next(r for r in releases if r["id"] == rid)
    assert row["overdue_criterion_count"] == 1
