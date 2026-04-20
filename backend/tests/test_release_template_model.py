import pytest
from app.db.models.release_template import ReleaseTemplate


@pytest.mark.asyncio
async def test_release_template_persists(db_session, tenant, release_lifecycle_template):
    tmpl = ReleaseTemplate(
        tenant_id=tenant.id,
        name="Major Default",
        description="Standard major release shape",
        release_type="Major",
        default_lifecycle_template_id=release_lifecycle_template.id,
        phases=[{"name": "SIT", "order": 1, "default_duration_days": 5, "activities": []}],
        gates=[{"name": "SIT Exit", "phase_name": "SIT", "acceptance_criteria": "Zero Sev1"}],
        version=1,
    )
    db_session.add(tmpl)
    await db_session.flush()
    assert tmpl.id is not None
    assert tmpl.phases[0]["name"] == "SIT"
    assert tmpl.version == 1
