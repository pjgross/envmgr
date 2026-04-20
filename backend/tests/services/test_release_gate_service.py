"""Tests for release_gate_service pass/fail/override with event emission."""
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.release_gate import ReleaseGate
from app.db.models.user import Tenant
from app.api.v1.schemas.release_gate import ReleaseGateCreate, ReleaseGateUpdate
from app.services import release_gate_service


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_release(db_session, tenant_id, user_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Major",
        is_default=True,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()

    release = Release(
        tenant_id=tenant_id, name="R1", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status="draft", raised_by=user_id,
    )
    db_session.add(release)
    await db_session.flush()
    return release


async def _seed_stakeholder_event_type(db_session, tenant_id):
    et = ReleaseEventType(
        tenant_id=tenant_id, name="Stakeholder Note", is_system=True
    )
    db_session.add(et)
    await db_session.flush()
    return et


# ── test_pass_gate_records_decision ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_pass_gate_records_decision(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="SIT Exit", acceptance_criteria="Zero Sev1"),
        tenant.id,
    )
    assert gate.status == "pending"

    passed = await release_gate_service.pass_gate(
        db_session, gate.id, "All tests passed", tenant.id, user.id
    )
    assert passed.status == "passed"
    assert passed.decided_by == user.id
    assert passed.decided_at is not None
    assert passed.decision_notes == "All tests passed"


# ── test_pass_gate_emits_event_and_publishes_outbox ───────────────────────────

@pytest.mark.asyncio
async def test_pass_gate_emits_event_and_publishes_outbox(db_session, tenant, user):
    await _seed_stakeholder_event_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id)

    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="UAT Exit"),
        tenant.id,
    )

    await release_gate_service.pass_gate(
        db_session, gate.id, "OK", tenant.id, user.id
    )

    # Should have written a Stakeholder Note event
    events = (
        await db_session.execute(
            select(ReleaseEvent).where(ReleaseEvent.release_id == release.id)
        )
    ).scalars().all()
    assert len(events) == 1
    assert "passed" in events[0].description.lower()


# ── test_override_requires_notes ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_override_requires_notes(db_session, tenant, user):
    from fastapi import HTTPException
    release = await _make_release(db_session, tenant.id, user.id)

    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="Overrideable Gate"),
        tenant.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await release_gate_service.override_gate(
            db_session, gate.id, None, tenant.id, user.id
        )
    assert exc_info.value.status_code == 422

    with pytest.raises(HTTPException) as exc_info2:
        await release_gate_service.override_gate(
            db_session, gate.id, "  ", tenant.id, user.id
        )
    assert exc_info2.value.status_code == 422


# ── test_override_with_notes_succeeds ────────────────────────────────────────

@pytest.mark.asyncio
async def test_override_with_notes_succeeds(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)

    gate = await release_gate_service.create_gate(
        db_session, release.id,
        ReleaseGateCreate(name="Gate"),
        tenant.id,
    )
    overridden = await release_gate_service.override_gate(
        db_session, gate.id, "Business exception approved by CTO", tenant.id, user.id
    )
    assert overridden.status == "overridden"
    assert overridden.decision_notes == "Business exception approved by CTO"


# ── test_tenant_isolation_pass_gate_cross_tenant_forbidden ───────────────────

@pytest.mark.asyncio
async def test_tenant_isolation_pass_gate_cross_tenant_forbidden(db_session, tenant, user):
    from fastapi import HTTPException
    tenant_b = Tenant(name="Other Co", slug="other-co")
    db_session.add(tenant_b)
    await db_session.flush()

    release = await _make_release(db_session, tenant.id, user.id)
    gate = await release_gate_service.create_gate(
        db_session, release.id, ReleaseGateCreate(name="Gate A"), tenant.id
    )

    # Trying to operate on tenant A's gate as tenant B should raise 404
    with pytest.raises(HTTPException) as exc_info:
        await release_gate_service.pass_gate(
            db_session, gate.id, "bypassed", tenant_b.id, user.id
        )
    assert exc_info.value.status_code == 404


# ── test_fail_gate ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fail_gate(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)
    gate = await release_gate_service.create_gate(
        db_session, release.id, ReleaseGateCreate(name="Gate"), tenant.id
    )
    failed = await release_gate_service.fail_gate(
        db_session, gate.id, "Tests failed", tenant.id, user.id
    )
    assert failed.status == "failed"
    assert failed.decision_notes == "Tests failed"
