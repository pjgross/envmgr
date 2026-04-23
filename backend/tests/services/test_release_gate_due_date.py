"""Service-level tests for ReleaseGate.due_date migration — post-spec
2026-04-23. Covers create/update/list behaviours."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.gate_criterion import GateCriterion
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.api.v1.schemas.release_gate import ReleaseGateCreate
from app.services import release_gate_service


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_release(db_session, tenant_id, user_id, status="draft", name="R"):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=f"Tpl-{name}",
        is_default=False,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()

    release = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=tpl.id,
        status=status,
        raised_by=user_id,
    )
    db_session.add(release)
    await db_session.flush()
    return release


# ── Test 1: create_gate persists a passed-in due_date onto the gate row ──────

@pytest.mark.asyncio
async def test_create_gate_persists_due_date(db_session, tenant, user):
    """create_gate stores due_date on the row and the returned dict exposes it
    without leaking test_phase_id."""
    release = await _make_release(db_session, tenant.id, user.id)

    due = datetime.now(timezone.utc) + timedelta(days=7)

    gate = await release_gate_service.create_gate(
        db_session,
        release.id,
        ReleaseGateCreate(name="SIT Exit", due_date=due),
        tenant.id,
    )

    # The ORM row should carry the due_date.
    assert gate.due_date is not None
    # Truncate to seconds for comparison (DB may strip microseconds).
    assert abs((gate.due_date - due).total_seconds()) < 2

    # list_gates returns dicts; check the shape.
    gates = await release_gate_service.list_gates(db_session, release.id, tenant.id)
    assert len(gates) == 1
    g = gates[0]
    assert "due_date" in g
    assert g["due_date"] is not None
    assert "test_phase_id" not in g


# ── Test 2: list_gates returns correct overdue_criterion_count ───────────────

@pytest.mark.asyncio
async def test_list_gates_overdue_criterion_count(db_session, tenant, user):
    """Gates with a past due_date should report overdue_criterion_count == N
    (only open criteria count). Gates with a future due_date should report 0."""
    release = await _make_release(db_session, tenant.id, user.id, name="R2")

    past_due = datetime.now(timezone.utc) - timedelta(days=1)
    future_due = datetime.now(timezone.utc) + timedelta(days=7)

    gate_past = await release_gate_service.create_gate(
        db_session,
        release.id,
        ReleaseGateCreate(name="Past Gate", due_date=past_due),
        tenant.id,
    )
    gate_future = await release_gate_service.create_gate(
        db_session,
        release.id,
        ReleaseGateCreate(name="Future Gate", due_date=future_due),
        tenant.id,
    )

    # Add 2 open + 1 done criterion to each gate (no criterion-level due_date —
    # overdue_criterion_count is driven entirely by the gate's due_date).
    for gate in (gate_past, gate_future):
        db_session.add_all([
            GateCriterion(tenant_id=tenant.id, gate_id=gate.id, title="a", status="open"),
            GateCriterion(tenant_id=tenant.id, gate_id=gate.id, title="b", status="open"),
            GateCriterion(tenant_id=tenant.id, gate_id=gate.id, title="c", status="done"),
        ])
    await db_session.flush()

    rows = await release_gate_service.list_gates(db_session, release_id=release.id, tenant_id=tenant.id)
    assert len(rows) == 2

    by_name = {r["name"]: r for r in rows}
    # Past gate: gate due_date is in the past → 2 open criteria counted as overdue.
    assert by_name["Past Gate"]["overdue_criterion_count"] == 2
    # Future gate: gate due_date is in the future → 0 overdue regardless of criteria.
    assert by_name["Future Gate"]["overdue_criterion_count"] == 0
    assert "due_date" in by_name["Past Gate"]
    assert "test_phase_id" not in by_name["Past Gate"]
    assert "test_phase_id" not in by_name["Future Gate"]
