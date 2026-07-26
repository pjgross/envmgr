from datetime import datetime, timezone, timedelta
import pytest

from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.api.v1.schemas.gate_criterion import GateCriterionCreate, GateCriterionUpdate
from app.services import gate_criterion_service


async def _make_gate(db, tenant, user, lifecycle_tmpl) -> ReleaseGate:
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=lifecycle_tmpl.id, status="draft", raised_by=user.id,
    )
    db.add(release); await db.flush()
    gate = ReleaseGate(tenant_id=tenant.id, release_id=release.id, name="G", status="pending",
                      due_date=datetime.now(timezone.utc))
    db.add(gate); await db.flush()
    return gate


@pytest.mark.asyncio
async def test_create_criterion(db_session, tenant, user, release_lifecycle_template):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate_id=gate.id, tenant_id=tenant.id, user_id=user.id,
        data=GateCriterionCreate(title="Zero Sev1"),
    )
    assert crit.id is not None
    assert crit.status == "open"
    assert crit.title == "Zero Sev1"


@pytest.mark.asyncio
async def test_list_criteria_for_gate_excludes_soft_deleted(
    db_session, tenant, user, release_lifecycle_template
):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))
    await gate_criterion_service.delete_criterion(db_session, b.id, tenant.id)

    rows = await gate_criterion_service.list_criteria_for_gate(db_session, gate.id, tenant.id)
    assert [r.id for r in rows] == [a.id]


@pytest.mark.asyncio
async def test_update_edits_fields(db_session, tenant, user, release_lifecycle_template):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    await gate_criterion_service.update_criterion(
        db_session, crit.id, tenant.id,
        GateCriterionUpdate(title="A-rev", notes="more", assigned_to_user_id=user.id),
    )
    await db_session.refresh(crit)
    assert crit.title == "A-rev"
    assert crit.notes == "more"
    assert crit.assigned_to_user_id == user.id


@pytest.mark.asyncio
async def test_tenant_isolation_on_get(db_session, tenant, user, release_lifecycle_template):
    """A criterion from tenant A is 404 when queried as tenant B."""
    from fastapi import HTTPException
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))

    with pytest.raises(HTTPException) as exc_info:
        await gate_criterion_service.get_criterion(db_session, crit.id, tenant_id=99999)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_overdue_for_release(db_session, tenant, user, release_lifecycle_template):
    """Overdue = criterion is open AND its gate's due_date is in the past."""
    from app.db.models.release import Release
    release = Release(
        tenant_id=tenant.id, name="R-overdue", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release); await db_session.flush()

    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)

    from app.db.models.release_gate import ReleaseGate
    overdue_gate = ReleaseGate(tenant_id=tenant.id, release_id=release.id,
                               name="Past Gate", status="pending", due_date=past)
    future_gate = ReleaseGate(tenant_id=tenant.id, release_id=release.id,
                              name="Future Gate", status="pending", due_date=future)
    db_session.add_all([overdue_gate, future_gate]); await db_session.flush()

    overdue = await gate_criterion_service.create_criterion(
        db_session, overdue_gate.id, tenant.id, user.id, GateCriterionCreate(title="late"))
    _not_due_yet = await gate_criterion_service.create_criterion(
        db_session, future_gate.id, tenant.id, user.id, GateCriterionCreate(title="future"))

    rows = await gate_criterion_service.list_overdue_for_release(
        db_session, release_id=release.id, tenant_id=tenant.id)
    assert [crit.id for crit, _gate in rows] == [overdue.id]


from app.services import release_gate_service


@pytest.mark.asyncio
async def test_complete_criterion_autopasses_single(
    db_session, tenant, user, release_lifecycle_template
):
    """Single-criterion gate: completing the one criterion auto-passes."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))

    await gate_criterion_service.complete_criterion(db_session, crit.id, tenant.id, user.id, user.role)
    await db_session.refresh(gate)
    assert gate.status == "passed"
    assert gate.decided_by == user.id
    assert gate.decided_at is not None
    assert gate.decision_notes == "auto: all criteria met"


@pytest.mark.asyncio
async def test_complete_not_last_does_not_autopass(
    db_session, tenant, user, release_lifecycle_template
):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    _b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))

    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id, user.role)
    await db_session.refresh(gate)
    assert gate.status == "pending"


@pytest.mark.asyncio
async def test_zero_criteria_gate_does_not_autopass(
    db_session, tenant, user, release_lifecycle_template
):
    """Gate with no criteria rows must stay pending — called via helper directly."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    await release_gate_service.maybe_auto_pass_gate(db_session, gate, tenant.id, user.id)
    await db_session.refresh(gate)
    assert gate.status == "pending"


@pytest.mark.asyncio
async def test_soft_deleted_criterion_ignored_by_autopass(
    db_session, tenant, user, release_lifecycle_template
):
    """A deleted criterion shouldn't block or enable auto-pass."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))
    await gate_criterion_service.delete_criterion(db_session, b.id, tenant.id)

    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id, user.role)
    await db_session.refresh(gate)
    assert gate.status == "passed"


@pytest.mark.asyncio
async def test_reopen_after_autopass_does_not_revert_gate(
    db_session, tenant, user, release_lifecycle_template
):
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    crit = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    await gate_criterion_service.complete_criterion(db_session, crit.id, tenant.id, user.id, user.role)
    await db_session.refresh(gate)
    assert gate.status == "passed"

    await gate_criterion_service.reopen_criterion(db_session, crit.id, tenant.id, user.role)
    await db_session.refresh(gate)
    assert gate.status == "passed"  # one-way
    await db_session.refresh(crit)
    assert crit.status == "open"
    assert crit.completed_at is None
    assert crit.completed_by_user_id is None


@pytest.mark.asyncio
async def test_complete_on_already_passed_gate_does_not_re_emit(
    db_session, tenant, user, release_lifecycle_template
):
    """Completing a criterion on a passed gate is a no-op for gate state."""
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    a = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="A"))
    b = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="B"))

    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id, user.role)
    await gate_criterion_service.complete_criterion(db_session, b.id, tenant.id, user.id, user.role)
    await db_session.refresh(gate)
    decided_at_first = gate.decided_at
    assert gate.status == "passed"

    # Reopening and re-completing 'a' must NOT bump decided_at again
    await gate_criterion_service.reopen_criterion(db_session, a.id, tenant.id, user.role)
    await gate_criterion_service.complete_criterion(db_session, a.id, tenant.id, user.id, user.role)
    await db_session.refresh(gate)
    assert gate.decided_at == decided_at_first
