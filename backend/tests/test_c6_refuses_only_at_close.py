"""C6 REFUSES EXACTLY AT A CLOSED STATE THAT ASKS FOR IT, AND NOWHERE ELSE.

The first deliberate refusal in Phase 9, after eight sub-projects whose
central promise was a named test asserting an ABSENCE (A3, A4, B2, B4, C2,
C4, the PIR work, C3). This file is the same kind of promise inverted: the
gate fires in ONE function (`release_closeout_service.assert_may_close`),
only on a state flagged `is_closed`, only for the `requires_*` flags that
state carries, and everything else in the product is byte-for-byte what it
was with the flags on.

Proved non-vacuous: deleting the `assert_may_close` call from
`release_service.transition_release` makes
`test_a_closed_state_requiring_a_pir_refuses_a_draft_pir` fail, and
restoring it makes it pass. A guard nobody has watched fail is a guard
nobody knows works.
"""
import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from tests.factories import ensure_user_group, make_incident

DRAFT = {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}
LIVE = {"key": "live", "label": "Live", "is_initial": False, "is_terminal": False}


def _definition(closed_flags: dict, *, also_on_live: dict | None = None):
    closed = {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True,
              "is_closed": True, **closed_flags}
    live = {**LIVE, **(also_on_live or {})}
    return {
        "states": [DRAFT, live, closed],
        "transitions": [
            {"from_state": "draft", "to_state": "live", "label": "Go live", "allowed_roles": ["Admin"]},
            {"from_state": "live", "to_state": "completed", "label": "Close", "allowed_roles": ["Admin"]},
        ],
        "field_permissions": {k: {"standard_fields": {}, "custom_fields": {}} for k in ("draft", "live", "completed")},
    }


@pytest_asyncio.fixture
async def make_release(db_session, test_tenant, test_user):
    async def _make(closed_flags: dict, status="live"):
        tpl = LifecycleTemplate(tenant_id=test_tenant.id, entity_type="release", name="C6",
                                is_default=False, applies_to_kind="project",
                                definition=_definition(closed_flags))
        db_session.add(tpl)
        await db_session.flush()
        rel = Release(tenant_id=test_tenant.id, name="R-c6", release_type="Major", release_kind="project",
                      lifecycle_template_id=tpl.id, status=status, raised_by=test_user.id)
        db_session.add(rel)
        await db_session.commit()
        await db_session.refresh(rel)
        return rel
    return _make


async def _close(client, headers, rid):
    return await client.post(f"/api/v1/releases/{rid}/transition",
                             json={"to_state": "completed"}, headers=headers)


@pytest.mark.asyncio
async def test_a_closed_state_with_no_requirements_closes_over_a_draft_pir(client, auth_headers, make_release):
    rel = await make_release({})
    assert (await client.post(f"/api/v1/releases/{rel.id}/pir", json={"summary": "s"},
                              headers=auth_headers)).status_code == 201
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_closed_state_requiring_a_pir_refuses_a_draft_pir(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True})
    await client.post(f"/api/v1/releases/{rel.id}/pir", json={"summary": "s"}, headers=auth_headers)
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 422, resp.text
    assert "post-implementation review is not complete" in resp.json()["detail"]
    still = (await client.get(f"/api/v1/releases/{rel.id}", headers=auth_headers)).json()
    assert still["status"] == "live"


@pytest.mark.asyncio
async def test_no_pir_at_all_is_incomplete(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True})
    assert (await _close(client, auth_headers, rel.id)).status_code == 422


@pytest.mark.asyncio
async def test_completing_the_pir_lets_the_release_close(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True})
    await client.post(f"/api/v1/releases/{rel.id}/pir", json={"summary": "s"}, headers=auth_headers)
    assert (await client.patch(f"/api/v1/releases/{rel.id}/pir", json={"status": "complete"},
                               headers=auth_headers)).status_code == 200
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, reason="Task 6 adds PUT operations_group_id and confirm-handover")
async def test_handover_requirement_refuses_until_confirmed(client, auth_headers, make_release, db_session, test_tenant):
    rel = await make_release({"requires_handover_confirmed": True})
    resp = await _close(client, auth_headers, rel.id)
    assert resp.status_code == 422 and "ops handover is not confirmed" in resp.json()["detail"]
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    assert (await client.put(f"/api/v1/releases/{rel.id}", json={"operations_group_id": group.id},
                             headers=auth_headers)).status_code == 200
    assert (await client.post(f"/api/v1/releases/{rel.id}/confirm-handover", json={},
                              headers=auth_headers)).status_code == 200
    assert (await _close(client, auth_headers, rel.id)).status_code == 200


@pytest.mark.asyncio
async def test_both_requirements_are_named_in_one_refusal(client, auth_headers, make_release):
    rel = await make_release({"requires_pir_complete": True, "requires_handover_confirmed": True})
    detail = (await _close(client, auth_headers, rel.id)).json()["detail"]
    assert "post-implementation review is not complete" in detail
    assert "ops handover is not confirmed" in detail


@pytest.mark.asyncio
async def test_the_gate_never_touches_a_non_closed_transition(client, auth_headers, make_release):
    """draft -> live is not a close, whatever the closed state demands."""
    rel = await make_release({"requires_pir_complete": True, "requires_handover_confirmed": True},
                             status="draft")
    resp = await client.post(f"/api/v1/releases/{rel.id}/transition",
                             json={"to_state": "live"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_with_both_flags_on_nothing_else_in_the_product_changes(
    client, auth_headers, make_release, db_session, test_tenant, test_user
):
    """A booking and an incident transition are what they were. Readiness in
    particular still says nothing about PIRs — the gate is NOT folded into
    `release_readiness_service`."""
    from app.services.incident_defaults import seed_incident_defaults_for_tenant
    await seed_incident_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
    rel = await make_release({"requires_pir_complete": True, "requires_handover_confirmed": True})

    readiness = (await client.get(f"/api/v1/releases/{rel.id}/readiness", headers=auth_headers)).json()
    blob = str(readiness).lower()
    # Not a bare "pir"/"handover" substring check: C2's waiver warning text is
    # "Waived by ..., expires ...", so "expires"/"expiry" would trip a naive
    # "pir" substring test the day a fixture gains a waived gate.
    assert "post-implementation" not in blob
    assert "closeout" not in blob
    assert not any(
        f["type"].startswith("pir") or "handover" in f["type"]
        for f in readiness["blockers"] + readiness["warnings"]
    )

    incident = await make_incident(db_session, test_tenant.id, title="hc incident", status="new")
    moved = await client.post(f"/api/v1/incidents/{incident.id}/transition",
                              json={"to_state": "investigating"}, headers=auth_headers)
    assert moved.status_code == 200, moved.text

    from tests.factories import ensure_environment, make_booking
    env = await ensure_environment(db_session, test_tenant.id)
    booking = await make_booking(db_session, test_tenant.id, booked_by=test_user.id, environment=env)
    assert booking.id is not None
