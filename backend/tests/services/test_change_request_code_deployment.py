"""ChangeRequestService.create_code_deployment — auto CR for webhook deployments."""
import pytest
from sqlalchemy import select

from app.db.models.change_request import ChangeRequest, ChangeType
from app.services import change_request_service


@pytest.mark.asyncio
async def test_create_code_deployment_cr(db_session, tenant, user):
    # Seed the Code Deployment template.
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    await db_session.flush()

    cr = await change_request_service.create_code_deployment(
        db_session,
        tenant_id=tenant.id,
        raised_by=user.id,
        title="Deploy abc123 to sit",
        description="Automated via GitHub Actions",
    )
    await db_session.flush()

    row = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == cr.id)
    )).scalar_one()
    assert row.change_type == ChangeType.CODE_DEPLOYMENT
    assert row.status == "created"
    assert row.raised_by == user.id
    assert row.title.startswith("Deploy abc123")


@pytest.mark.asyncio
async def test_missing_template_raises(db_session, tenant, user):
    # No seed called — template should not exist.
    with pytest.raises(Exception):
        await change_request_service.create_code_deployment(
            db_session, tenant_id=tenant.id, raised_by=user.id,
            title="x", description="y",
        )
