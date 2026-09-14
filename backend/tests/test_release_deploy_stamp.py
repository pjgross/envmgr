"""`actual_date` is stamped by the `marks_deployed` flag, not by a state's name.

Before C6 `release_service._DEPLOYED_TERMINAL_STATES = {"completed",
"completed_with_issues"}` decided this, so a tenant that renamed either state
never got a deploy date, and an enterprise release never got one at all.
"""
import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release


def _template(tenant_id, states, transitions):
    return LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="Stamp", is_default=False,
        applies_to_kind="project",
        definition={"states": states, "transitions": transitions,
                    "field_permissions": {s["key"]: {"standard_fields": {}, "custom_fields": {}}
                                          for s in states}},
    )


@pytest_asyncio.fixture
async def release_with(db_session, test_tenant, test_user):
    async def _make(states, transitions):
        tpl = _template(test_tenant.id, states, transitions)
        db_session.add(tpl)
        await db_session.flush()
        rel = Release(tenant_id=test_tenant.id, name="R", release_type="Major",
                      release_kind="project", lifecycle_template_id=tpl.id,
                      status="draft", raised_by=test_user.id)
        db_session.add(rel)
        await db_session.commit()
        await db_session.refresh(rel)
        return rel
    return _make


DRAFT = {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}


@pytest.mark.asyncio
async def test_a_renamed_state_with_the_flag_stamps_actual_date(client, auth_headers, release_with):
    live = {"key": "live", "label": "Live", "is_terminal": False, "marks_deployed": True}
    rel = await release_with([DRAFT, live], [
        {"from_state": "draft", "to_state": "live", "label": "Go", "allowed_roles": ["Admin"]}])
    resp = await client.post(f"/api/v1/releases/{rel.id}/transition",
                             json={"to_state": "live"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["actual_date"] is not None


@pytest.mark.asyncio
async def test_completed_without_the_flag_does_not_stamp(client, auth_headers, release_with):
    completed = {"key": "completed", "label": "Completed", "is_terminal": True}
    rel = await release_with([DRAFT, completed], [
        {"from_state": "draft", "to_state": "completed", "label": "Go", "allowed_roles": ["Admin"]}])
    resp = await client.post(f"/api/v1/releases/{rel.id}/transition",
                             json={"to_state": "completed"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["actual_date"] is None


@pytest.mark.asyncio
async def test_the_stamp_happens_once(client, auth_headers, release_with):
    live = {"key": "live", "label": "Live", "is_terminal": False, "marks_deployed": True}
    done = {"key": "done", "label": "Done", "is_terminal": True, "marks_deployed": True}
    rel = await release_with([DRAFT, live, done], [
        {"from_state": "draft", "to_state": "live", "label": "Go", "allowed_roles": ["Admin"]},
        {"from_state": "live", "to_state": "done", "label": "Done", "allowed_roles": ["Admin"]}])
    first = (await client.post(f"/api/v1/releases/{rel.id}/transition",
                               json={"to_state": "live"}, headers=auth_headers)).json()["actual_date"]
    second = (await client.post(f"/api/v1/releases/{rel.id}/transition",
                                json={"to_state": "done"}, headers=auth_headers)).json()["actual_date"]
    assert first is not None and first == second
