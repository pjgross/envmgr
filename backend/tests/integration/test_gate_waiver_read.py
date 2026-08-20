"""Task 10c — the waiver record is readable, not just written.

Before this file, `GateWaiver` rows accumulated in `gate_waiver` with no read
path anywhere: `ReleaseGateRead` had no waiver fields, and the only trace in
the product was the readiness verdict's pre-rendered warning string. This
covers the fix: `ReleaseGateRead.waiver`, populated by
`release_gate_service.list_gates` via the existing batch helper
`gate_waiver_service.latest_waivers_for_gates`, plus the `override_gate`
endpoint's own response (which would otherwise silently null the waiver it
just wrote — see `releases.py`'s comment on that site).
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import gate_waiver_service


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
async def test_a_pending_gate_returns_a_null_waiver(client, auth_headers, gate):
    listed = await client.get(f"/api/v1/releases/{gate.release_id}/gates", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = listed.json()[0]
    assert row["status"] == "pending"
    assert row["waiver"] is None


@pytest.mark.asyncio
async def test_overriding_a_gate_returns_a_live_waiver_immediately(client, auth_headers, gate, test_user):
    """Guards the override_gate endpoint's own response — model_validate(gate)
    alone would silently render `waiver: null` for the waiver just written,
    since ReleaseGate carries no such attribute and the field has a default."""
    far_future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    resp = await client.post(
        f"/api/v1/gates/{gate.id}/override",
        json={
            "notes": "Accepted risk pending fix",
            "expires_at": far_future,
            "remediation": "Fix tracked in ENV-999",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "overridden"
    assert body["waiver"] is not None
    assert body["waiver"]["state"] == "live"
    assert body["waiver"]["remediation"] == "Fix tracked in ENV-999"
    assert body["waiver"]["approved_by_user_id"] == test_user.id
    assert body["waiver"]["approved_by_username"] == test_user.username


@pytest.mark.asyncio
async def test_a_live_waiver_on_the_list_payload(client, auth_headers, gate, test_user):
    far_future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    override = await client.post(
        f"/api/v1/gates/{gate.id}/override",
        json={
            "notes": "Accepted risk",
            "expires_at": far_future,
            "remediation": "Will fix next sprint",
        },
        headers=auth_headers,
    )
    assert override.status_code == 200, override.text

    listed = await client.get(f"/api/v1/releases/{gate.release_id}/gates", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = listed.json()[0]
    assert row["status"] == "overridden"
    waiver = row["waiver"]
    assert waiver is not None
    assert waiver["state"] == "live"
    assert waiver["reason"] == "Accepted risk"
    assert waiver["remediation"] == "Will fix next sprint"
    assert waiver["approved_by_user_id"] == test_user.id
    assert waiver["approved_by_username"] == test_user.username


@pytest.mark.asyncio
async def test_an_expired_waiver_on_the_list_payload(client, auth_headers, gate, db_session, test_tenant, test_user):
    """override_gate takes expires_at at face value — a caller can waive with
    an already-past expiry (e.g. backfilling history). list_gates must report
    it as expired, not live."""
    from app.services import release_gate_service

    past = datetime.now(timezone.utc) - timedelta(days=5)
    await release_gate_service.override_gate(
        db_session, gate.id, notes="short-lived waiver", tenant_id=test_tenant.id,
        user_id=test_user.id, expires_at=past,
    )
    await db_session.flush()

    listed = await client.get(f"/api/v1/releases/{gate.release_id}/gates", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = listed.json()[0]
    waiver = row["waiver"]
    assert waiver is not None
    assert waiver["state"] == "expired"


@pytest.mark.asyncio
async def test_the_approver_username_resolves_from_outside_the_gates_tenant(
    client, auth_headers, gate, db_session, test_tenant, test_user, second_tenant_factory,
):
    """THE TRAP IN THIS FIELD. Under master-admin impersonation
    `current_user.id` and `current_user.active_tenant_id` legitimately belong
    to different tenants, so an override can name an approver who sits
    outside the gate's own tenant_id. A `User.tenant_id ==` join on the
    username lookup would render that approver as nobody — the audit trail
    losing exactly the name it exists to hold. See
    `gate_waiver_service.usernames_for`, and its siblings
    `agreement_gap_service.ack_author_username` /
    `contention_service`'s decider-name lookup, which carry the same rule.
    """
    from app.services import release_gate_service

    other_tenant, other_admin = await second_tenant_factory()
    assert other_tenant.id != test_tenant.id

    await release_gate_service.override_gate(
        db_session, gate.id, notes="approved by an out-of-tenant admin",
        tenant_id=test_tenant.id, user_id=test_user.id,
        approved_by_user_id=other_admin.id,
    )
    await db_session.flush()

    listed = await client.get(f"/api/v1/releases/{gate.release_id}/gates", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    waiver = listed.json()[0]["waiver"]
    assert waiver["approved_by_user_id"] == other_admin.id
    assert waiver["approved_by_username"] == other_admin.username, (
        "the approver's name must not be resolved with a tenant-qualified join — "
        "under impersonation they legitimately sit outside the gate's tenant"
    )


@pytest.mark.asyncio
async def test_latest_waivers_for_gates_is_called_once_for_a_multi_gate_page(
    client, auth_headers, db_session, test_tenant, test_user, monkeypatch,
):
    """ONE query for the whole page, never one per gate. Three overridden
    gates on one release must still call the batch helper exactly once."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Test Major 2",
        is_default=False,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(template)
    await db_session.flush()
    release = Release(
        tenant_id=test_tenant.id, name="R-batch", release_type="Major",
        lifecycle_template_id=template.id, raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()

    from app.services import release_gate_service

    gates = []
    for i in range(3):
        g = ReleaseGate(
            tenant_id=test_tenant.id, release_id=release.id, name=f"Gate {i}",
            due_date=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(g)
        await db_session.flush()
        gates.append(g)

    for g in gates:
        await release_gate_service.override_gate(
            db_session, g.id, notes="accepted", tenant_id=test_tenant.id, user_id=test_user.id,
        )
    await db_session.commit()

    call_count = 0
    original = gate_waiver_service.latest_waivers_for_gates

    async def counting_wrapper(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(gate_waiver_service, "latest_waivers_for_gates", counting_wrapper)

    listed = await client.get(f"/api/v1/releases/{release.id}/gates", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 3
    assert all(row["waiver"] is not None for row in listed.json())
    assert call_count == 1, "latest_waivers_for_gates must be called once per page, not once per gate"


@pytest.mark.asyncio
async def test_updating_an_overridden_gate_does_not_blank_its_waiver(
    client, auth_headers, gate, test_user,
):
    """Review finding on task 10c: PUT /gates/{id} returned the bare ORM
    object, so model_validate(gate) alone silently rendered `waiver: null`
    for a gate that was already overridden and stayed overridden — even
    though GatesTable's gate-type Select is deliberately enabled on an
    overridden gate (see gateTypeAndReadiness.test.tsx), and
    updateGate.fulfilled does a full-row Redux replace. Renaming or
    retyping an overridden gate must not make its waiver (and in
    particular an EXPIRED waiver's distinct state) disappear from the
    response until something else triggers a refetch.
    """
    far_future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    override = await client.post(
        f"/api/v1/gates/{gate.id}/override",
        json={
            "notes": "Accepted risk",
            "expires_at": far_future,
            "remediation": "Will fix next sprint",
        },
        headers=auth_headers,
    )
    assert override.status_code == 200, override.text
    assert override.json()["waiver"] is not None

    updated = await client.put(
        f"/api/v1/gates/{gate.id}",
        json={"name": "SIT Exit (renamed)"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "SIT Exit (renamed)"
    assert body["status"] == "overridden"
    waiver = body["waiver"]
    assert waiver is not None, (
        "PUT /gates/{id} must carry the same waiver the gate had before the "
        "update — model_validate(gate) alone silently drops it"
    )
    assert waiver["state"] == "live"
    assert waiver["remediation"] == "Will fix next sprint"
    assert waiver["approved_by_user_id"] == test_user.id
