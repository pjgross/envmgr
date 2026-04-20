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
    gate = ReleaseGate(tenant_id=tenant.id, release_id=release.id, name="G", status="pending")
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
    due = datetime.now(timezone.utc) + timedelta(days=1)
    await gate_criterion_service.update_criterion(
        db_session, crit.id, tenant.id,
        GateCriterionUpdate(title="A-rev", notes="more", due_date=due, assigned_to_user_id=user.id),
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
    gate = await _make_gate(db_session, tenant, user, release_lifecycle_template)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    overdue = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id,
        GateCriterionCreate(title="late", due_date=past))
    _not_due_yet = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id,
        GateCriterionCreate(title="future", due_date=future))
    _no_due_date = await gate_criterion_service.create_criterion(
        db_session, gate.id, tenant.id, user.id, GateCriterionCreate(title="nodate"))

    rows = await gate_criterion_service.list_overdue_for_release(
        db_session, release_id=gate.release_id, tenant_id=tenant.id)
    assert [r.id for r in rows] == [overdue.id]
