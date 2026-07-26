from datetime import datetime, timezone, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.release_gate import ReleaseGate
from app.db.models.gate_criterion import GateCriterion
from app.services import release_service
from app.services.release_service import SCOPE_SIGNOFF_GATE_NAME
from app.api.v1.schemas.release import ReleaseCreate, ReleaseUpdate


def _naive(dt: datetime) -> datetime:
    """Strip timezone info for comparison — SQLite drops tzinfo on round-trip."""
    return dt.replace(tzinfo=None) if dt is not None else dt


async def _gates(db, release_id, tenant_id):
    return (await db.execute(
        select(ReleaseGate).where(
            ReleaseGate.release_id == release_id,
            ReleaseGate.tenant_id == tenant_id,
            ReleaseGate.deleted_at.is_(None),
        )
    )).scalars().all()


@pytest.mark.asyncio
async def test_setting_deadline_at_create_makes_gate(db_session, tenant, user, release_lifecycle_template):
    deadline = datetime.now(timezone.utc) + timedelta(days=7)
    rel = await release_service.create_release(
        db_session,
        ReleaseCreate(name="R1", release_type="Test Major", release_kind="project", scope_deadline=deadline),
        tenant.id, user.id,
    )
    await db_session.flush()
    gates = await _gates(db_session, rel.id, tenant.id)
    assert len(gates) == 1
    assert gates[0].name == SCOPE_SIGNOFF_GATE_NAME
    assert _naive(gates[0].due_date) == _naive(deadline)
    crits = (await db_session.execute(
        select(GateCriterion).where(GateCriterion.gate_id == gates[0].id)
    )).scalars().all()
    assert len(crits) == 1
    assert crits[0].title == "Scope signed off"
    assert crits[0].assigned_role == "Release Manager"


@pytest.mark.asyncio
async def test_setting_deadline_on_update_makes_gate_idempotently(db_session, tenant, user, release_lifecycle_template):
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R2", release_type="Test Major", release_kind="project"),
        tenant.id, user.id,
    )
    await db_session.flush()
    d1 = datetime.now(timezone.utc) + timedelta(days=3)
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=d1), tenant.id, user.id)
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=d1), tenant.id, user.id)
    gates = await _gates(db_session, rel.id, tenant.id)
    assert len(gates) == 1


@pytest.mark.asyncio
async def test_changing_deadline_syncs_pending_gate_due_date(db_session, tenant, user, release_lifecycle_template):
    d1 = datetime.now(timezone.utc) + timedelta(days=3)
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R3", release_type="Test Major", release_kind="project", scope_deadline=d1),
        tenant.id, user.id,
    )
    await db_session.flush()
    d2 = d1 + timedelta(days=5)
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=d2), tenant.id, user.id)
    gates = await _gates(db_session, rel.id, tenant.id)
    assert _naive(gates[0].due_date) == _naive(d2)


@pytest.mark.asyncio
async def test_clearing_deadline_keeps_gate(db_session, tenant, user, release_lifecycle_template):
    d1 = datetime.now(timezone.utc) + timedelta(days=3)
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R4", release_type="Test Major", release_kind="project", scope_deadline=d1),
        tenant.id, user.id,
    )
    await db_session.flush()
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=None), tenant.id, user.id)
    gates = await _gates(db_session, rel.id, tenant.id)
    assert len(gates) == 1


@pytest.mark.asyncio
async def test_enterprise_release_rejects_deadline(db_session, tenant, user, release_lifecycle_template):
    with pytest.raises(HTTPException) as ei:
        await release_service.create_release(
            db_session,
            ReleaseCreate(name="ENT", release_type="Test Major", release_kind="enterprise",
                          scope_deadline=datetime.now(timezone.utc)),
            tenant.id, user.id,
        )
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_changing_deadline_leaves_decided_gate_untouched(db_session, tenant, user, release_lifecycle_template):
    d1 = datetime.now(timezone.utc) + timedelta(days=3)
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R5", release_type="Test Major", release_kind="project", scope_deadline=d1),
        tenant.id, user.id,
    )
    await db_session.flush()
    gate = (await _gates(db_session, rel.id, tenant.id))[0]

    # Decide the gate directly on the ORM object.
    gate.status = "passed"
    gate.decided_by = user.id
    gate.decided_at = datetime.now(timezone.utc)
    await db_session.flush()

    d2 = d1 + timedelta(days=5)
    await release_service.update_release(db_session, rel.id, ReleaseUpdate(scope_deadline=d2), tenant.id, user.id)

    # Decided gate must NOT be re-synced — due_date stays at the original deadline.
    refreshed = (await _gates(db_session, rel.id, tenant.id))[0]
    assert _naive(refreshed.due_date) == _naive(d1)


@pytest.mark.asyncio
async def test_enterprise_update_rejects_deadline(db_session, tenant, user, release_lifecycle_template):
    rel = await release_service.create_release(
        db_session, ReleaseCreate(name="R6", release_type="Test Major", release_kind="project"),
        tenant.id, user.id,
    )
    await db_session.flush()

    # Flip to enterprise directly (create blocks enterprise+deadline, so this is
    # the only way to exercise the update guard).
    rel.release_kind = "enterprise"
    await db_session.flush()

    with pytest.raises(HTTPException) as ei:
        await release_service.update_release(
            db_session, rel.id,
            ReleaseUpdate(scope_deadline=datetime.now(timezone.utc) + timedelta(days=2)),
            tenant.id, user.id,
        )
    assert ei.value.status_code == 422
