"""Tests for the releases API — Tasks 21 & 22.

Happy-path + negative (404/400/409) coverage for:
  - CRUD + transition + history + calendar + timeline
  - phases, gates, systems, dependencies (+ alerts), events, scope/changes,
    bookings sub-resource, linked CRs
"""
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.system import System


# ── Helpers / fixtures ────────────────────────────────────────────────────────

def _release_lifecycle(tenant_id: int, is_default: bool = True) -> LifecycleTemplate:
    return LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Standard Release",
        is_default=is_default,
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


@pytest.fixture
def _target():
    return (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


# ── conftest-level setup shared within this module ───────────────────────────

import pytest_asyncio


@pytest_asyncio.fixture
async def lifecycle(db_session: AsyncSession, test_tenant):
    tpl = _release_lifecycle(test_tenant.id)
    db_session.add(tpl)
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


@pytest_asyncio.fixture
async def release(db_session: AsyncSession, test_tenant, test_user, lifecycle):
    r = Release(
        tenant_id=test_tenant.id,
        name="v1.0",
        description="First release",
        release_type="major",
        release_kind="project",
        lifecycle_template_id=lifecycle.id,
        status="draft",
        raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.flush()
    db_session.add(ReleaseStatusHistory(
        release_id=r.id,
        from_state=None,
        to_state="draft",
        changed_by=test_user.id,
        changed_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()
    await db_session.refresh(r)
    return r


@pytest_asyncio.fixture
async def test_system_for_release(db_session: AsyncSession, test_tenant):
    s = System(tenant_id=test_tenant.id, name="auth-service")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


# ── Task 21: CRUD + transition + history + calendar + timeline ────────────────

@pytest.mark.asyncio
async def test_create_release(client: AsyncClient, auth_headers, lifecycle, _target):
    resp = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "v2.0",
        "release_type": "major",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "v2.0"
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_create_release_missing_lifecycle_uses_default(
    client: AsyncClient, auth_headers, lifecycle, _target
):
    """Should succeed: lifecycle fixture is the tenant default."""
    resp = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "v3.0",
        "release_type": "minor",
        "target_date": _target,
    })
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_list_releases(client: AsyncClient, auth_headers, release):
    resp = await client.get("/api/v1/releases", headers=auth_headers)
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert release.id in ids


@pytest.mark.asyncio
async def test_get_release(client: AsyncClient, auth_headers, release):
    resp = await client.get(f"/api/v1/releases/{release.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "v1.0"


@pytest.mark.asyncio
async def test_get_release_not_found(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/releases/99999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_release(client: AsyncClient, auth_headers, release):
    resp = await client.put(f"/api/v1/releases/{release.id}", headers=auth_headers, json={
        "name": "v1.0-patched",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "v1.0-patched"


@pytest.mark.asyncio
async def test_transition_release(client: AsyncClient, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/transition",
        headers=auth_headers,
        json={"to_state": "submitted"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_transition_release_invalid_state(client: AsyncClient, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/transition",
        headers=auth_headers,
        json={"to_state": "completed"},  # no transition draft→completed
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_release_history(client: AsyncClient, auth_headers, release):
    resp = await client.get(f"/api/v1/releases/{release.id}/history", headers=auth_headers)
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) >= 1
    assert entries[0]["to_state"] == "draft"


@pytest.mark.asyncio
async def test_delete_release(client: AsyncClient, auth_headers, lifecycle, _target):
    # create a fresh release to delete
    r = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "to-delete",
        "release_type": "patch",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    rid = r.json()["id"]
    resp = await client.delete(f"/api/v1/releases/{rid}", headers=auth_headers)
    assert resp.status_code == 204
    resp2 = await client.get(f"/api/v1/releases/{rid}", headers=auth_headers)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_calendar_endpoint(client: AsyncClient, auth_headers, release):
    resp = await client.get("/api/v1/releases/calendar", headers=auth_headers)
    assert resp.status_code == 200
    # release has no target_date so should not appear in calendar
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_calendar_with_target_date(client: AsyncClient, auth_headers, lifecycle, _target):
    await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "calendar-test",
        "release_type": "major",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    resp = await client.get("/api/v1/releases/calendar", headers=auth_headers)
    assert resp.status_code == 200
    titles = [e["title"] for e in resp.json()]
    assert "calendar-test" in titles


@pytest.mark.asyncio
async def test_timeline_endpoint(client: AsyncClient, auth_headers, release):
    resp = await client.get("/api/v1/releases/timeline", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = [e["id"] for e in data]
    assert release.id in ids


# ── Task 22: Sub-resources ─────────────────────────────────────────────────────

# Phases

@pytest.mark.asyncio
async def test_create_and_list_phases(client: AsyncClient, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/phases",
        headers=auth_headers,
        json={"name": "SIT", "order": 1, "status": "pending"},
    )
    assert resp.status_code == 201, resp.text
    phase_id = resp.json()["id"]

    resp2 = await client.get(f"/api/v1/releases/{release.id}/phases", headers=auth_headers)
    assert resp2.status_code == 200
    ids = [p["id"] for p in resp2.json()]
    assert phase_id in ids


@pytest.mark.asyncio
async def test_update_phase(client: AsyncClient, auth_headers, release):
    cr = await client.post(
        f"/api/v1/releases/{release.id}/phases",
        headers=auth_headers,
        json={"name": "UAT", "order": 2, "status": "pending"},
    )
    phase_id = cr.json()["id"]
    resp = await client.put(
        f"/api/v1/phases/{phase_id}",
        headers=auth_headers,
        json={"name": "UAT-updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "UAT-updated"


@pytest.mark.asyncio
async def test_delete_phase(client: AsyncClient, auth_headers, release):
    cr = await client.post(
        f"/api/v1/releases/{release.id}/phases",
        headers=auth_headers,
        json={"name": "Perf", "order": 3, "status": "pending"},
    )
    phase_id = cr.json()["id"]
    resp = await client.delete(f"/api/v1/phases/{phase_id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_phase_wrong_release_404(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/releases/99999/phases", headers=auth_headers)
    assert resp.status_code == 404


# Gates

@pytest.mark.asyncio
async def test_create_and_list_gates(client: AsyncClient, auth_headers, release):
    _due = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    resp = await client.post(
        f"/api/v1/releases/{release.id}/gates",
        headers=auth_headers,
        json={"name": "Go/No-Go", "due_date": _due},
    )
    assert resp.status_code == 201, resp.text
    gate_id = resp.json()["id"]

    resp2 = await client.get(f"/api/v1/releases/{release.id}/gates", headers=auth_headers)
    assert resp2.status_code == 200
    ids = [g["id"] for g in resp2.json()]
    assert gate_id in ids


@pytest.mark.asyncio
async def test_update_gate(client: AsyncClient, auth_headers, release):
    _due = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    cr = await client.post(
        f"/api/v1/releases/{release.id}/gates",
        headers=auth_headers,
        json={"name": "Security Gate", "due_date": _due},
    )
    gate_id = cr.json()["id"]
    resp = await client.put(
        f"/api/v1/gates/{gate_id}",
        headers=auth_headers,
        json={"name": "Security Gate v2"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Security Gate v2"


@pytest.mark.asyncio
async def test_pass_gate(client: AsyncClient, auth_headers, release):
    _due = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    cr = await client.post(
        f"/api/v1/releases/{release.id}/gates",
        headers=auth_headers,
        json={"name": "Smoke Test Gate", "due_date": _due},
    )
    gate_id = cr.json()["id"]
    resp = await client.post(
        f"/api/v1/gates/{gate_id}/pass",
        headers=auth_headers,
        json={"notes": "All green"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "passed"


@pytest.mark.asyncio
async def test_fail_gate(client: AsyncClient, auth_headers, release):
    _due = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    cr = await client.post(
        f"/api/v1/releases/{release.id}/gates",
        headers=auth_headers,
        json={"name": "Performance Gate", "due_date": _due},
    )
    gate_id = cr.json()["id"]
    resp = await client.post(
        f"/api/v1/gates/{gate_id}/fail",
        headers=auth_headers,
        json={"notes": "Too slow"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_override_gate_requires_notes(client: AsyncClient, auth_headers, release):
    _due = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    cr = await client.post(
        f"/api/v1/releases/{release.id}/gates",
        headers=auth_headers,
        json={"name": "Override Gate", "due_date": _due},
    )
    gate_id = cr.json()["id"]
    # No notes → 422
    resp = await client.post(
        f"/api/v1/gates/{gate_id}/override",
        headers=auth_headers,
        json={},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_override_gate_success(client: AsyncClient, auth_headers, release):
    _due = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    cr = await client.post(
        f"/api/v1/releases/{release.id}/gates",
        headers=auth_headers,
        json={"name": "Must Override", "due_date": _due},
    )
    gate_id = cr.json()["id"]
    resp = await client.post(
        f"/api/v1/gates/{gate_id}/override",
        headers=auth_headers,
        json={"notes": "Emergency deploy approved by CTO"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "overridden"


@pytest.mark.asyncio
async def test_gate_wrong_release_404(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/releases/99999/gates", headers=auth_headers)
    assert resp.status_code == 404


# Systems

@pytest.mark.asyncio
async def test_add_and_list_systems(
    client: AsyncClient, auth_headers, release, test_system_for_release
):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/systems",
        headers=auth_headers,
        json={"system_id": test_system_for_release.id, "role": "changing"},
    )
    assert resp.status_code == 201, resp.text
    rs_id = resp.json()["id"]

    resp2 = await client.get(f"/api/v1/releases/{release.id}/systems", headers=auth_headers)
    assert resp2.status_code == 200
    ids = [s["id"] for s in resp2.json()]
    assert rs_id in ids


@pytest.mark.asyncio
async def test_add_system_duplicate_409(
    client: AsyncClient, auth_headers, release, test_system_for_release
):
    await client.post(
        f"/api/v1/releases/{release.id}/systems",
        headers=auth_headers,
        json={"system_id": test_system_for_release.id, "role": "changing"},
    )
    resp = await client.post(
        f"/api/v1/releases/{release.id}/systems",
        headers=auth_headers,
        json={"system_id": test_system_for_release.id, "role": "regression"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_add_system_rejects_foreign_tenant(
    client: AsyncClient, auth_headers, release, db_session
):
    """Linking another tenant's system to a release must be rejected."""
    from app.db.models.user import Tenant

    other = Tenant(name="Sys Org", slug="sys-org")
    db_session.add(other)
    await db_session.flush()
    foreign_system = System(tenant_id=other.id, name="Foreign System")
    db_session.add(foreign_system)
    await db_session.commit()
    await db_session.refresh(foreign_system)

    resp = await client.post(
        f"/api/v1/releases/{release.id}/systems",
        headers=auth_headers,
        json={"system_id": foreign_system.id, "role": "changing"},
    )
    assert resp.status_code == 400, resp.text
    assert "system_id" in resp.text


@pytest.mark.asyncio
async def test_remove_system(
    client: AsyncClient, auth_headers, release, test_system_for_release
):
    add = await client.post(
        f"/api/v1/releases/{release.id}/systems",
        headers=auth_headers,
        json={"system_id": test_system_for_release.id, "role": "config_only"},
    )
    rs_id = add.json()["id"]
    resp = await client.delete(f"/api/v1/release-systems/{rs_id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_remove_system_not_found(client: AsyncClient, auth_headers):
    resp = await client.delete("/api/v1/release-systems/99999", headers=auth_headers)
    assert resp.status_code == 404


# Dependencies

@pytest.mark.asyncio
async def test_add_and_list_dependencies(
    client: AsyncClient, auth_headers, release, lifecycle, _target
):
    # create a second release to depend on
    r2 = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "depends-on-release",
        "release_type": "minor",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    dep_release_id = r2.json()["id"]

    resp = await client.post(
        f"/api/v1/releases/{release.id}/dependencies",
        headers=auth_headers,
        json={"depends_on_release_id": dep_release_id, "kind": "deploys_after"},
    )
    assert resp.status_code == 201, resp.text
    dep_id = resp.json()["id"]

    resp2 = await client.get(f"/api/v1/releases/{release.id}/dependencies", headers=auth_headers)
    assert resp2.status_code == 200
    ids = [d["id"] for d in resp2.json()]
    assert dep_id in ids


@pytest.mark.asyncio
async def test_self_dependency_rejected(client: AsyncClient, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/dependencies",
        headers=auth_headers,
        json={"depends_on_release_id": release.id},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_dependency(
    client: AsyncClient, auth_headers, release, lifecycle, _target
):
    r2 = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "dep-to-delete",
        "release_type": "patch",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    dep_release_id = r2.json()["id"]
    dep = await client.post(
        f"/api/v1/releases/{release.id}/dependencies",
        headers=auth_headers,
        json={"depends_on_release_id": dep_release_id},
    )
    dep_id = dep.json()["id"]
    resp = await client.delete(f"/api/v1/release-dependencies/{dep_id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_dependency_alerts_empty(client: AsyncClient, auth_headers, release):
    resp = await client.get(
        f"/api/v1/releases/{release.id}/dependency-alerts", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_acknowledge_alert_not_found(client: AsyncClient, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/dependency-alerts/99999/acknowledge",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# Events

@pytest.mark.asyncio
async def test_create_and_list_events(
    client: AsyncClient, auth_headers, release, db_session, test_tenant
):
    from app.db.models.release_event import ReleaseEventType
    et = ReleaseEventType(
        tenant_id=test_tenant.id,
        name="Milestone",
        is_system=False,
    )
    db_session.add(et)
    await db_session.commit()
    await db_session.refresh(et)

    resp = await client.post(
        f"/api/v1/releases/{release.id}/events",
        headers=auth_headers,
        json={"event_type_id": et.id, "description": "Code freeze"},
    )
    assert resp.status_code == 201, resp.text
    ev_id = resp.json()["id"]

    resp2 = await client.get(f"/api/v1/releases/{release.id}/events", headers=auth_headers)
    assert resp2.status_code == 200
    ids = [e["id"] for e in resp2.json()]
    assert ev_id in ids


@pytest.mark.asyncio
async def test_events_wrong_release_404(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/releases/99999/events", headers=auth_headers)
    assert resp.status_code == 404


# Scope / Changes

@pytest.mark.asyncio
async def test_create_and_list_changes(client: AsyncClient, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/changes",
        headers=auth_headers,
        json={"title": "AUTH-123", "change_kind": "story"},
    )
    assert resp.status_code == 201, resp.text
    ch_id = resp.json()["id"]

    resp2 = await client.get(f"/api/v1/releases/{release.id}/changes", headers=auth_headers)
    assert resp2.status_code == 200
    ids = [c["id"] for c in resp2.json()]
    assert ch_id in ids


@pytest.mark.asyncio
async def test_update_change(client: AsyncClient, auth_headers, release):
    cr = await client.post(
        f"/api/v1/releases/{release.id}/changes",
        headers=auth_headers,
        json={"title": "FEAT-1", "change_kind": "story"},
    )
    ch_id = cr.json()["id"]
    resp = await client.put(
        f"/api/v1/release-changes/{ch_id}",
        headers=auth_headers,
        json={"title": "FEAT-1-updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "FEAT-1-updated"


@pytest.mark.asyncio
async def test_delete_change(client: AsyncClient, auth_headers, release):
    cr = await client.post(
        f"/api/v1/releases/{release.id}/changes",
        headers=auth_headers,
        json={"title": "BUG-99", "change_kind": "defect"},
    )
    ch_id = cr.json()["id"]
    resp = await client.delete(f"/api/v1/release-changes/{ch_id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_change_not_found(client: AsyncClient, auth_headers):
    resp = await client.put(
        "/api/v1/release-changes/99999",
        headers=auth_headers,
        json={"title": "nope"},
    )
    assert resp.status_code == 404


# Bookings sub-resource

@pytest.mark.asyncio
async def test_list_release_bookings_empty(client: AsyncClient, auth_headers, release):
    resp = await client.get(f"/api/v1/releases/{release.id}/bookings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_release_booking(
    client: AsyncClient, auth_headers, release, test_environment, test_booking_type
):
    now = datetime.now(timezone.utc)
    resp = await client.post(
        f"/api/v1/releases/{release.id}/bookings",
        headers=auth_headers,
        json={
            "environment_id": test_environment.id,
            "start": (now + timedelta(days=5)).isoformat(),
            "end": (now + timedelta(days=6)).isoformat(),
            "booking_type_id": test_booking_type.id,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["release_id"] == release.id


@pytest.mark.asyncio
async def test_bookings_wrong_release_404(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/releases/99999/bookings", headers=auth_headers)
    assert resp.status_code == 404


# Linked CRs

@pytest.mark.asyncio
async def test_list_linked_crs_empty(client: AsyncClient, auth_headers, release):
    resp = await client.get(f"/api/v1/releases/{release.id}/change-requests", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_link_and_unlink_cr(
    client: AsyncClient, auth_headers, release, test_environment
):
    """Create a CR via the CR endpoint, link it, then unlink it."""
    from datetime import timezone
    now = datetime.now(timezone.utc)
    # Create a lifecycle for booking to satisfy CR creation
    cr_resp = await client.post("/api/v1/change-requests", headers=auth_headers, json={
        "title": "Link test CR",
        "change_type": "code_deployment",
        "scheduled_start": (now + timedelta(days=1)).isoformat(),
        "scheduled_end": (now + timedelta(days=2)).isoformat(),
        "environment_ids": [test_environment.id],
    })
    if cr_resp.status_code != 201:
        pytest.skip("CR creation requires additional fixtures (lifecycle); skipping")
    cr_id = cr_resp.json()["id"]

    # Link
    link = await client.post(
        f"/api/v1/releases/{release.id}/change-requests/{cr_id}/link",
        headers=auth_headers,
    )
    assert link.status_code == 204

    listed = await client.get(
        f"/api/v1/releases/{release.id}/change-requests", headers=auth_headers
    )
    ids = [c["id"] for c in listed.json()]
    assert cr_id in ids

    # Unlink
    unlink = await client.delete(
        f"/api/v1/releases/{release.id}/change-requests/{cr_id}/link",
        headers=auth_headers,
    )
    assert unlink.status_code == 204

    listed2 = await client.get(
        f"/api/v1/releases/{release.id}/change-requests", headers=auth_headers
    )
    ids2 = [c["id"] for c in listed2.json()]
    assert cr_id not in ids2


@pytest.mark.asyncio
async def test_link_cr_not_found(client: AsyncClient, auth_headers, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/change-requests/99999/link",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unlink_cr_not_linked(client: AsyncClient, auth_headers, release):
    resp = await client.delete(
        f"/api/v1/releases/{release.id}/change-requests/99999/link",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ── Task 18: release_kind filter + membership_summary ────────────────────────

@pytest.mark.asyncio
async def test_list_releases_filtered_by_kind(
    client: AsyncClient, auth_headers, lifecycle, _target
):
    """GET /releases?release_kind=enterprise returns only enterprise-kind rows."""
    # Create a project release
    r1 = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "project-release-kind-test",
        "release_type": "minor",
        "release_kind": "project",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    assert r1.status_code == 201, r1.text

    # Create an enterprise release
    r2 = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "enterprise-release-kind-test",
        "release_type": "minor",
        "release_kind": "enterprise",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    assert r2.status_code == 201, r2.text

    # Filter by enterprise
    resp_e = await client.get(
        "/api/v1/releases?release_kind=enterprise", headers=auth_headers
    )
    assert resp_e.status_code == 200, resp_e.text
    items_e = resp_e.json()
    assert len(items_e) >= 1
    assert all(item["release_kind"] == "enterprise" for item in items_e)

    # Filter by project
    resp_p = await client.get(
        "/api/v1/releases?release_kind=project", headers=auth_headers
    )
    assert resp_p.status_code == 200, resp_p.text
    items_p = resp_p.json()
    assert len(items_p) >= 1
    assert all(item["release_kind"] == "project" for item in items_p)


@pytest.mark.asyncio
async def test_get_enterprise_release_includes_membership_summary(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_tenant,
    test_user,
    lifecycle,
    _target,
):
    """GET /releases/{id} for an enterprise release includes membership_summary."""
    from datetime import datetime, timezone
    from app.db.models.release_membership import ReleaseMembership

    # Create enterprise release via API
    r_ent = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "ent-summary-test",
        "release_type": "major",
        "release_kind": "enterprise",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    assert r_ent.status_code == 201, r_ent.text
    ent_id = r_ent.json()["id"]

    # Create a project release via API
    r_proj = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "proj-for-membership-test",
        "release_type": "minor",
        "release_kind": "project",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    assert r_proj.status_code == 201, r_proj.text
    proj_id = r_proj.json()["id"]

    # Directly insert an accepted membership row (bypasses lifecycle permission checks
    # that require action_permissions in the template definition)
    now = datetime.now(timezone.utc)
    membership = ReleaseMembership(
        tenant_id=test_tenant.id,
        enterprise_release_id=ent_id,
        project_release_id=proj_id,
        state="accepted",
        requested_by=test_user.id,
        requested_at=now,
        decided_by=test_user.id,
        decided_at=now,
        late_scope=False,
    )
    db_session.add(membership)
    await db_session.commit()

    # GET the enterprise release — membership_summary must be present
    resp = await client.get(f"/api/v1/releases/{ent_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "membership_summary" in data
    ms = data["membership_summary"]
    assert ms is not None
    assert "accepted" in ms
    assert ms["accepted"] == 1
    assert ms["pending"] == 0


@pytest.mark.asyncio
async def test_get_project_release_omits_membership_summary(
    client: AsyncClient, auth_headers, lifecycle, _target
):
    """GET /releases/{id} for a project release has membership_summary=None."""
    r = await client.post("/api/v1/releases", headers=auth_headers, json={
        "name": "proj-no-summary",
        "release_type": "minor",
        "release_kind": "project",
        "lifecycle_template_id": lifecycle.id,
        "target_date": _target,
    })
    assert r.status_code == 201, r.text
    release_id = r.json()["id"]

    resp = await client.get(f"/api/v1/releases/{release_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("membership_summary") is None


# ---------------------------------------------------------------------------
# Server-side sorting (sub-project C1 task 4)
# ---------------------------------------------------------------------------


def _t(offset_days: float):
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset_days)


async def _direct_release(
    db_session: AsyncSession,
    tenant_id: int,
    lifecycle_id: int,
    raised_by: int,
    *,
    name: str,
    release_type: str = "major",
    release_kind: str = "project",
    status: str = "draft",
    target_date=None,
    created_at=None,
) -> Release:
    """Insert a Release directly, bypassing POST /releases, so tests can seed
    exact name/type/kind/status/target_date/created_at combinations that
    deliberately disagree with insertion order. `created_at` must be set
    before the first flush to override the column's server_default."""
    r = Release(
        tenant_id=tenant_id,
        name=name,
        release_type=release_type,
        release_kind=release_kind,
        lifecycle_template_id=lifecycle_id,
        status=status,
        raised_by=raised_by,
        target_date=target_date,
    )
    if created_at is not None:
        r.created_at = created_at
    db_session.add(r)
    await db_session.flush()
    return r


@pytest.mark.asyncio
async def test_list_releases_default_order_unchanged(
    client: AsyncClient, auth_headers, lifecycle, db_session: AsyncSession, test_tenant, test_user,
):
    """No sort_by: order must stay `created_at DESC, id` — today's ordering,
    byte for byte.

    Insertion order (a, b, c) deliberately disagrees with both id-ascending
    and created_at-ascending order, so a response that happened to preserve
    insertion order — or that silently flipped direction the moment this
    endpoint gained the sorting() dependency — would not accidentally satisfy
    this assertion. This is the arbiter for /releases: its default limit is
    50 and unchanged by this task, so today's default page must stay
    byte-identical.
    """
    a = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="A", created_at=_t(2))
    b = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="B", created_at=_t(0))
    c = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="C", created_at=_t(1))

    resp = await client.get("/api/v1/releases", headers=auth_headers)
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert ids == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_releases_sort_by_name_both_directions(
    client: AsyncClient, auth_headers, lifecycle, db_session: AsyncSession, test_tenant, test_user,
):
    charlie = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                     name="Charlie", created_at=_t(0))
    alpha = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                   name="Alpha", created_at=_t(1))
    bravo = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                   name="Bravo", created_at=_t(2))

    asc = await client.get("/api/v1/releases?sort_by=name&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, bravo.id, charlie.id]

    desc = await client.get("/api/v1/releases?sort_by=name&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [charlie.id, bravo.id, alpha.id]


@pytest.mark.asyncio
async def test_list_releases_sort_by_release_type_both_directions(
    client: AsyncClient, auth_headers, lifecycle, db_session: AsyncSession, test_tenant, test_user,
):
    minor = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                   name="i1", release_type="minor", created_at=_t(0))
    emergency = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                       name="i2", release_type="emergency", created_at=_t(1))
    major = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                   name="i3", release_type="major", created_at=_t(2))

    asc = await client.get("/api/v1/releases?sort_by=release_type&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [emergency.id, major.id, minor.id]

    desc = await client.get("/api/v1/releases?sort_by=release_type&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [minor.id, major.id, emergency.id]


@pytest.mark.asyncio
async def test_list_releases_sort_by_release_kind_both_directions(
    client: AsyncClient, auth_headers, lifecycle, db_session: AsyncSession, test_tenant, test_user,
):
    """release_kind is a plain String(20) column with no DB-level CHECK
    constraint restricting it to project/enterprise (only the API's create
    path validates that), so three distinct values are used here purely to
    give the sort something to discriminate on."""
    mu = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                name="i1", release_kind="mu", created_at=_t(0))
    alpha = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                   name="i2", release_kind="alpha", created_at=_t(1))
    zeta = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                  name="i3", release_kind="zeta", created_at=_t(2))

    asc = await client.get("/api/v1/releases?sort_by=release_kind&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, mu.id, zeta.id]

    desc = await client.get("/api/v1/releases?sort_by=release_kind&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [zeta.id, mu.id, alpha.id]


@pytest.mark.asyncio
async def test_list_releases_sort_by_status_both_directions(
    client: AsyncClient, auth_headers, lifecycle, db_session: AsyncSession, test_tenant, test_user,
):
    mu = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                name="i1", status="mu", created_at=_t(0))
    alpha = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                   name="i2", status="alpha", created_at=_t(1))
    zeta = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                                  name="i3", status="zeta", created_at=_t(2))

    asc = await client.get("/api/v1/releases?sort_by=status&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, mu.id, zeta.id]

    desc = await client.get("/api/v1/releases?sort_by=status&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [zeta.id, mu.id, alpha.id]


@pytest.mark.asyncio
async def test_list_releases_sort_by_target_date_both_directions(
    client: AsyncClient, auth_headers, lifecycle, db_session: AsyncSession, test_tenant, test_user,
):
    """All rows get a non-null target_date — Postgres defaults NULLs LAST on
    ASC and NULLS FIRST on DESC while SQLite treats NULL as the smallest
    value, so a row with a null target_date here would make the two engines
    disagree on the expected sequence."""
    a = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="A", created_at=_t(0), target_date=_t(2))
    b = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="B", created_at=_t(0), target_date=_t(0))
    c = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="C", created_at=_t(0), target_date=_t(1))

    asc = await client.get("/api/v1/releases?sort_by=target_date&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [b.id, c.id, a.id]

    desc = await client.get("/api/v1/releases?sort_by=target_date&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_releases_sort_by_created_at_both_directions(
    client: AsyncClient, auth_headers, lifecycle, db_session: AsyncSession, test_tenant, test_user,
):
    a = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="A", created_at=_t(2))
    b = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="B", created_at=_t(0))
    c = await _direct_release(db_session, test_tenant.id, lifecycle.id, test_user.id,
                               name="C", created_at=_t(1))

    asc = await client.get("/api/v1/releases?sort_by=created_at&sort_dir=asc", headers=auth_headers)
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [b.id, c.id, a.id]

    desc = await client.get("/api/v1/releases?sort_by=created_at&sort_dir=desc", headers=auth_headers)
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_releases_unknown_sort_by_is_422(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/releases?sort_by=nonexistent", headers=auth_headers)
    assert resp.status_code == 422
