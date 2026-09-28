"""'Runbook tasks ready to start': the SQL predicate's own answers, and its
agreement with the composite read's allowed_transitions. Agreement alone would
prove only that two copies match, so each case is pinned independently too."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.pagination import Page
from app.services import runbook_execution_service as ex, runbook_view_service
from tests.factories import add_group_member, ensure_user, ensure_user_group
from tests.runbook_helpers import link, make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
async def setup(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id, name="Payments 4.2")
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    mine = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    theirs = await ensure_user_group(db_session, test_tenant.id, name="Theirs")
    me = await ensure_user(db_session, test_tenant.id, username="queue-me", role="Developer")
    me.active_tenant_id = test_tenant.id
    await add_group_member(db_session, mine, me)
    done = await make_task(db_session, plan, "done pred", status="done")
    skipped = await make_task(db_session, plan, "skipped pred", status="skipped")
    failed = await make_task(db_session, plan, "failed pred", status="failed")
    gone = await make_task(db_session, plan, "deleted pred")
    gone.deleted_at = ANCHOR
    tasks = {
        "ready_no_preds": await make_task(db_session, plan, "ready_no_preds", team=mine),
        "ready_done_skipped": await make_task(db_session, plan, "ready_done_skipped", team=mine),
        "blocked_by_failed": await make_task(db_session, plan, "blocked_by_failed", team=mine),
        "ready_deleted_pred": await make_task(db_session, plan, "ready_deleted_pred", team=mine),
        "already_running": await make_task(db_session, plan, "already_running", team=mine, status="in_progress"),
        "other_team": await make_task(db_session, plan, "other_team", team=theirs),
    }
    await link(db_session, tasks["ready_done_skipped"], done, skipped)
    await link(db_session, tasks["blocked_by_failed"], failed)
    await link(db_session, tasks["ready_deleted_pred"], gone)
    await db_session.flush()
    return dict(plan=plan, me=me, tasks=tasks, tenant_id=test_tenant.id)


EXPECTED = {"ready_no_preds", "ready_done_skipped", "ready_deleted_pred"}


@pytest.mark.asyncio
async def test_the_queue_holds_exactly_my_teams_ready_tasks(db_session, setup):
    rows, total = await ex.ready_queue(db_session, setup["tenant_id"], setup["me"].id, Page(limit=50, offset=0))
    assert {r.task_name for r in rows} == EXPECTED and total == 3
    assert {r.release_name for r in rows} == {"Payments 4.2"}


@pytest.mark.asyncio
async def test_the_queue_agrees_with_allowed_transitions(db_session, setup):
    body = await runbook_view_service.read(db_session, setup["plan"], setup["tenant_id"], setup["me"],
                                           ANCHOR + timedelta(hours=1))
    startable = {t.name for t in body.tasks if "in_progress" in t.allowed_transitions}
    rows, _ = await ex.ready_queue(db_session, setup["tenant_id"], setup["me"].id, Page(limit=50, offset=0))
    assert startable == {r.task_name for r in rows} == EXPECTED


@pytest.mark.asyncio
async def test_the_queue_is_tenant_scoped(db_session, setup, second_tenant_factory):
    other_tenant, _ = await second_tenant_factory()
    rows, total = await ex.ready_queue(db_session, other_tenant.id, setup["me"].id, Page(limit=50, offset=0))
    assert rows == [] and total == 0


@pytest.mark.asyncio
async def test_a_deleted_plan_leaves_the_queue(db_session, setup):
    setup["plan"].deleted_at = ANCHOR
    await db_session.flush()
    _, total = await ex.ready_queue(db_session, setup["tenant_id"], setup["me"].id, Page(limit=50, offset=0))
    assert total == 0


@pytest.mark.asyncio
async def test_me_work_serves_the_queue(client, db_session, test_tenant, setup):
    from tests.runbook_helpers import login_headers
    user, headers = await login_headers(client, db_session, test_tenant, "queue-http", "Developer")
    from app.db.models.user_group import UserGroup
    from sqlalchemy import select
    mine = (await db_session.execute(select(UserGroup).where(UserGroup.name == "Mine"))).scalar_one()
    await add_group_member(db_session, mine, user)
    await db_session.commit()
    body = (await client.get("/api/v1/me/work", headers=headers)).json()
    q = body["queues"]["runbook_tasks"]
    assert q["failed"] is False and q["count"] == 3
    assert all(i["url"].startswith("/releases/") and "tab=runbook" in i["url"] for i in q["items"])
