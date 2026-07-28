import pytest
from sqlalchemy import select
from app.db.models.lifecycle import LifecycleTemplate
from app.services.release_defaults import seed_release_defaults_for_tenant


def _failed_keys(definition):
    return {s["key"] for s in definition["states"] if s.get("is_failed")}


@pytest.mark.asyncio
async def test_default_release_templates_flag_failed_states(db_session, tenant):
    await seed_release_defaults_for_tenant(db_session, tenant.id)
    await db_session.flush()
    rows = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "release",
        )
    )).scalars().all()
    by_name = {r.name: r for r in rows}
    # Major/Minor: completed_with_issues + backed_out are failures; completed is not.
    for name in ("Major", "Minor"):
        fk = _failed_keys(by_name[name].definition)
        assert "completed_with_issues" in fk
        assert "backed_out" in fk
        assert "completed" not in fk
        assert "cancelled" not in fk
    # Emergency: backed_out is a failure.
    assert "backed_out" in _failed_keys(by_name["Emergency"].definition)
