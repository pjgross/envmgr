"""HTTP-level coverage for /api/v1/gates/{gate_id}/evidence and
/api/v1/gates/evidence/{evidence_id}.

test_gate_evidence.py exercises gate_evidence_service directly. Nothing
before this file exercised the router itself — Task 2 shipped its routes
with no HTTP test at all, and review called that a real regression gap.
Follows the pattern in test_gate_types_api.py: uses the shared
`member_headers` fixture (a non-Admin Developer in test_tenant) rather than a
local login helper.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from tests.factories import ensure_deployment, ensure_environment


@pytest_asyncio.fixture
async def gate(db_session, test_tenant, test_user) -> ReleaseGate:
    """A persisted ReleaseGate under a fresh Release in test_tenant."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Test Major",
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

    release = Release(
        tenant_id=test_tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()

    g = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name="SIT Exit",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(g)
    await db_session.commit()
    await db_session.refresh(g)
    return g


@pytest.mark.asyncio
async def test_adding_evidence_over_http(client, auth_headers, gate):
    created = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={"kind": "Runbook", "label": "Ops runbook", "url": "https://wiki/rb"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "Runbook"
    assert body["gate_id"] == gate.id
    assert body["deployment_id"] is None
    # Task 5: is_stale now always travels with the row. Fresh evidence with
    # no superseding deployment reads as current.
    assert body["is_stale"] is False

    listed = await client.get(f"/api/v1/gates/{gate.id}/evidence", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [row["label"] for row in listed.json()] == ["Ops runbook"]


@pytest.mark.asyncio
async def test_a_non_admin_member_can_add_and_list_evidence(client, member_headers, gate):
    """Any tenant member may add evidence — it is not Admin-gated."""
    created = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={"kind": "Test execution report", "label": "Regression run", "url": None},
        headers=member_headers,
    )
    assert created.status_code == 201, created.text

    listed = await client.get(f"/api/v1/gates/{gate.id}/evidence", headers=member_headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_a_cross_tenant_deployment_id_is_rejected_over_http(
    client, auth_headers, db_session, gate, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    other_env = await ensure_environment(db_session, other_tenant.id)
    other_deployment = await ensure_deployment(
        db_session, other_tenant.id, other_env.id, deployed_at=datetime.now(timezone.utc)
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={
            "kind": "Test execution report",
            "label": "Regression run",
            "url": "https://ci.example/1",
            "deployment_id": other_deployment.id,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_evidence_with_no_deployment_is_accepted_over_http(client, auth_headers, gate):
    resp = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={"kind": "Licence report", "label": "Vendor licence", "url": None},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["deployment_id"] is None


@pytest.mark.asyncio
async def test_deleting_evidence_over_http_soft_deletes(client, auth_headers, gate):
    created = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={"kind": "Runbook", "label": "To be removed", "url": None},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    evidence_id = created.json()["id"]

    deleted = await client.delete(
        f"/api/v1/gates/evidence/{evidence_id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text

    listed = await client.get(f"/api/v1/gates/{gate.id}/evidence", headers=auth_headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_an_unlisted_kind_is_accepted_over_http(client, auth_headers, gate):
    resp = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={"kind": "Something bespoke", "label": "One-off", "url": None},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "Something bespoke"


@pytest.mark.asyncio
async def test_evidence_for_a_gate_in_another_tenant_is_404(
    client, auth_headers, db_session, second_tenant_factory
):
    other_tenant, other_admin = await second_tenant_factory()
    template = LifecycleTemplate(
        tenant_id=other_tenant.id,
        entity_type="release",
        name="Other Major",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(template)
    await db_session.flush()
    release = Release(
        tenant_id=other_tenant.id,
        name="Other R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=other_admin.id,
    )
    db_session.add(release)
    await db_session.flush()
    other_gate = ReleaseGate(
        tenant_id=other_tenant.id,
        release_id=release.id,
        name="Other Gate",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(other_gate)
    await db_session.commit()
    await db_session.refresh(other_gate)

    resp = await client.get(f"/api/v1/gates/{other_gate.id}/evidence", headers=auth_headers)
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_a_non_admin_member_can_delete_evidence_over_http(client, member_headers, gate):
    """Deletion is soft and open to any tenant member, same as add/list —
    not Admin-gated."""
    created = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={"kind": "Runbook", "label": "Member-added", "url": None},
        headers=member_headers,
    )
    assert created.status_code == 201, created.text
    evidence_id = created.json()["id"]

    deleted = await client.delete(
        f"/api/v1/gates/evidence/{evidence_id}", headers=member_headers
    )
    assert deleted.status_code == 204, deleted.text

    listed = await client.get(f"/api/v1/gates/{gate.id}/evidence", headers=member_headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_posting_evidence_for_an_already_superseded_deployment_is_stale_immediately(
    client, auth_headers, db_session, test_tenant, gate
):
    """Deferred minor folded into I2: the superseding deployment already
    exists BEFORE the evidence citing the superseded one is even created —
    e.g. someone adding paperwork after the fact for an earlier deploy. Must
    read is_stale=true on the very first response, not just after a later
    deployment arrives (that path is test_is_stale_travels_over_the_wire,
    below)."""
    env = await ensure_environment(db_session, test_tenant.id)
    superseded = await ensure_deployment(
        db_session, test_tenant.id, env.id,
        deployed_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc), status="success",
    )
    # The superseding deployment already exists at POST time.
    await ensure_deployment(
        db_session, test_tenant.id, env.id,
        deployed_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc), status="success",
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={
            "kind": "Deployment record", "label": "Late paperwork for an old deploy",
            "url": None, "deployment_id": superseded.id,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_stale"] is True


@pytest.mark.asyncio
async def test_is_stale_travels_over_the_wire(
    client, auth_headers, db_session, test_tenant, gate
):
    """Task 5: is_stale is computed once per response and set explicitly on
    every row. Evidence citing a deployment later superseded by a successful
    redeploy of the same component into the same environment reads
    is_stale=true; evidence with no such later deployment reads false."""
    env = await ensure_environment(db_session, test_tenant.id)
    deployment_41 = await ensure_deployment(
        db_session, test_tenant.id, env.id,
        deployed_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc), status="success",
    )
    await db_session.commit()

    stale_evidence = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={
            "kind": "Deployment record", "label": "Superseded sign-off",
            "url": None, "deployment_id": deployment_41.id,
        },
        headers=auth_headers,
    )
    assert stale_evidence.status_code == 201, stale_evidence.text
    stale_evidence_id = stale_evidence.json()["id"]
    # Not stale yet — no later deployment exists.
    assert stale_evidence.json()["is_stale"] is False

    current_evidence = await client.post(
        f"/api/v1/gates/{gate.id}/evidence",
        json={"kind": "Runbook", "label": "No deployment link", "url": None},
        headers=auth_headers,
    )
    assert current_evidence.status_code == 201, current_evidence.text
    assert current_evidence.json()["is_stale"] is False

    # A later SUCCESSFUL deployment of the same component into the same
    # environment supersedes deployment_41.
    await ensure_deployment(
        db_session, test_tenant.id, env.id,
        deployed_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc), status="success",
    )
    await db_session.commit()

    listed = await client.get(f"/api/v1/gates/{gate.id}/evidence", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    by_id = {row["id"]: row for row in listed.json()}
    assert by_id[stale_evidence_id]["is_stale"] is True
    assert by_id[current_evidence.json()["id"]]["is_stale"] is False
