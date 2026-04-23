"""Code Deployment lifecycle must be seeded for every new tenant."""
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.services import change_request_service


@pytest.mark.asyncio
async def test_code_deployment_lifecycle_seeded(db_session, tenant):
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    await db_session.flush()

    row = (
        await db_session.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.tenant_id == tenant.id,
                LifecycleTemplate.entity_type == "change_request",
                LifecycleTemplate.name == "Code Deployment",
            )
        )
    ).scalar_one()
    assert row.is_system is True
    state_keys = {s["key"] for s in row.definition["states"]}
    assert state_keys == {"created", "deployed", "failed"}
    # Exactly one initial state: created
    initial = [s for s in row.definition["states"] if s.get("is_initial")]
    assert len(initial) == 1 and initial[0]["key"] == "created"
    # Two terminal states: deployed + failed
    terminal = {s["key"] for s in row.definition["states"] if s.get("is_terminal")}
    assert terminal == {"deployed", "failed"}
