"""C2 ADVISES; IT NEVER BLOCKS.

The guard on the whole design, in the line of A3, A4, B2 and B4. If any of
these fails, C2 has started acting and the spec is no longer true.

Fixture note: the brief's sketch used `environment.slug`/`subsystem.slug` and
a `POST /api/v1/booking-requests` payload with `purpose`/`release_id` keys.
Neither exists on the real schema — `Environment`/`SubSystem` have no `slug`
attribute (`preflight_service` matches on `.name` instead), and
`BookingRequestCreate` is `extra="forbid"` with no `release_id` field and no
`purpose` field at all (that's `project_name`). `release_id` lives only on
the LEGACY single-environment `POST /api/v1/bookings/` (`BookingCreate`), so
that's the path used here for the booking test — it is also the more direct
proof, since it puts the release id directly on the row a hostile C2 would
have to notice.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models.booking_lifecycle import BookingType
from app.db.models.gate_criterion import GateCriterion
from app.db.models.gate_type import GateType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import api_key_service
from tests.factories import ensure_environment, ensure_subsystem


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_key_headers(db_session, test_tenant, test_user) -> dict:
    """A key scoped for `webhooks:deployment` — the scope can-deploy requires."""
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=test_tenant.id, created_by=test_user.id,
        name="CI can-deploy", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    return {"X-Api-Key": raw}


@pytest_asyncio.fixture
async def environment(db_session, test_tenant):
    return await ensure_environment(db_session, test_tenant.id)


@pytest_asyncio.fixture
async def subsystem(db_session, test_tenant):
    return await ensure_subsystem(db_session, test_tenant.id)


@pytest_asyncio.fixture
async def booking_type(db_session, test_tenant) -> BookingType:
    """A booking type with a genuine lifecycle template (draft initial)."""
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="booking",
        name="c2-guard-booking-lifecycle",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(tenant_id=test_tenant.id, name="c2-guard-booking-type", lifecycle_template_id=tpl.id)
    db_session.add(bt)
    await db_session.commit()
    await db_session.refresh(bt)
    return bt


@pytest_asyncio.fixture
async def release_with_failed_block_gate(db_session, test_tenant, test_user) -> Release:
    """A release, reachable via draft -> in_progress, carrying one FAILED
    gate whose type's failure_behaviour is 'block' — a genuine blocker
    release_readiness_service.evaluate() will report, not a fabricated one."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="C2 Guard Release Lifecycle",
        is_default=False,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "in_progress", "label": "In Progress", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "in_progress", "allowed_roles": ["Admin"]},
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

    gate_type = GateType(
        tenant_id=test_tenant.id, name="Go/No-Go", failure_behaviour="block", expected_evidence=[],
    )
    db_session.add(gate_type)
    await db_session.flush()

    gate = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name="Go/No-Go Gate",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status="failed",
        gate_type_id=gate_type.id,
    )
    db_session.add(gate)
    await db_session.commit()
    await db_session.refresh(release)
    return release


@pytest_asyncio.fixture
async def gate_expecting_evidence_with_open_criteria(db_session, test_tenant, test_user) -> ReleaseGate:
    """A pending gate whose type expects evidence that has not been supplied,
    plus a genuinely open criterion — neither is a refusal at pass_gate,
    only ever a warning in the read-only verdict."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="C2 Guard Evidence Release Lifecycle",
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
        tenant_id=test_tenant.id,
        name="R2",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()

    gate_type = GateType(
        tenant_id=test_tenant.id, name="UAT Sign-off", failure_behaviour="warn",
        expected_evidence=["Test execution report"],
    )
    db_session.add(gate_type)
    await db_session.flush()

    gate = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name="UAT Sign-off Gate",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status="pending",
        gate_type_id=gate_type.id,
    )
    db_session.add(gate)
    await db_session.flush()

    criterion = GateCriterion(
        tenant_id=test_tenant.id, gate_id=gate.id, title="Sign off from QA lead", status="open",
    )
    db_session.add(criterion)
    await db_session.commit()
    await db_session.refresh(gate)
    return gate


# ── The guard ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_release_with_a_failed_block_gate_still_transitions(
    client, auth_headers, release_with_failed_block_gate
):
    resp = await client.post(
        f"/api/v1/releases/{release_with_failed_block_gate.id}/transition",
        json={"to_state": "in_progress"}, headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_can_deploy_answers_identically_with_and_without_gate_state(
    client, api_key_headers, environment, subsystem, release_with_failed_block_gate
):
    """can-deploy is UNTOUCHED — not one blocker, not one warning."""
    before = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}", headers=api_key_headers,
    )
    after = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}&release_id={release_with_failed_block_gate.id}",
        headers=api_key_headers,
    )
    assert before.status_code == 200, before.text
    assert after.status_code == 200, after.text
    assert before.json()["blockers"] == after.json()["blockers"]
    assert before.json()["warnings"] == after.json()["warnings"]


@pytest.mark.asyncio
async def test_a_gate_can_still_be_passed_with_open_criteria_and_no_evidence(
    client, auth_headers, gate_expecting_evidence_with_open_criteria
):
    """C2 does not tighten pass_gate. Missing evidence is a WARNING in the
    verdict, never a refusal at the write."""
    resp = await client.post(
        f"/api/v1/gates/{gate_expecting_evidence_with_open_criteria.id}/pass",
        json={"notes": "signed off"}, headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_booking_is_unaffected_by_gate_state(
    client, auth_headers, environment, booking_type, release_with_failed_block_gate
):
    """Gate state reaches nothing outside the release page. Uses the legacy
    single-environment POST /bookings/ (BookingCreate) because that's the
    write path that actually carries release_id — booking-requests'
    BookingRequestCreate has no such field."""
    resp = await client.post(
        "/api/v1/bookings/",
        json={
            "environment_id": environment.id,
            "project_name": "unaffected by gates",
            "booking_type_id": booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-02T17:00:00Z",
            "release_id": release_with_failed_block_gate.id,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
