import pytest
from fastapi import HTTPException

from app.core.security import Role
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import gate_criterion_service
from app.api.v1.schemas.gate_criterion import GateCriterionCreate


async def _gate_with_role_criterion(db, tenant_id, template_id):
    r = Release(tenant_id=tenant_id, name="AZ", release_type="Test Major", release_kind="project",
                lifecycle_template_id=template_id, status="draft", raised_by=1)
    db.add(r)
    await db.flush()
    from datetime import datetime, timezone
    g = ReleaseGate(tenant_id=tenant_id, release_id=r.id, name="Scope Sign-off",
                    due_date=datetime.now(timezone.utc), status="pending")
    db.add(g)
    await db.flush()
    crit = await gate_criterion_service.create_criterion(
        db, gate_id=g.id, tenant_id=tenant_id, user_id=1,
        data=GateCriterionCreate(title="Scope signed off", assigned_role=Role.RELEASE_MANAGER),
    )
    return crit


@pytest.mark.asyncio
async def test_release_manager_can_complete(db_session, tenant, release_lifecycle_template):
    crit = await _gate_with_role_criterion(db_session, tenant.id, release_lifecycle_template.id)
    done = await gate_criterion_service.complete_criterion(
        db_session, crit.id, tenant.id, user_id=1, user_role=Role.RELEASE_MANAGER,
    )
    assert done.status == "done"


@pytest.mark.asyncio
async def test_admin_can_complete(db_session, tenant, release_lifecycle_template):
    crit = await _gate_with_role_criterion(db_session, tenant.id, release_lifecycle_template.id)
    done = await gate_criterion_service.complete_criterion(
        db_session, crit.id, tenant.id, user_id=1, user_role=Role.ADMIN,
    )
    assert done.status == "done"


@pytest.mark.asyncio
async def test_developer_cannot_complete_role_criterion(db_session, tenant, release_lifecycle_template):
    crit = await _gate_with_role_criterion(db_session, tenant.id, release_lifecycle_template.id)
    with pytest.raises(HTTPException) as ei:
        await gate_criterion_service.complete_criterion(
            db_session, crit.id, tenant.id, user_id=1, user_role=Role.DEVELOPER,
        )
    assert ei.value.status_code == 403
