import pytest
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange


@pytest.mark.asyncio
async def test_release_change_manual_item(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()

    rc = ReleaseChange(
        tenant_id=tenant.id, release_id=release.id,
        external_key=None, title="Add login dark mode",
        change_kind="story", source="manual",
    )
    db_session.add(rc); await db_session.flush()
    assert rc.id is not None
    assert rc.source == "manual"
    assert rc.external_key is None


@pytest.mark.asyncio
async def test_release_change_jira_stub_allowed(db_session, tenant, user, release_lifecycle_template):
    release = Release(tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
                      lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id)
    db_session.add(release); await db_session.flush()

    rc = ReleaseChange(
        tenant_id=tenant.id, release_id=release.id,
        external_key="PROJ-42", external_status="In Progress",
        title="Bug: overflow on mobile", change_kind="defect",
        jira_project_config_id=99,  # bare int OK; no FK until sub-project 3
        epic_id=77,
        source="jira",
    )
    db_session.add(rc); await db_session.flush()
    assert rc.external_key == "PROJ-42"
    assert rc.jira_project_config_id == 99
