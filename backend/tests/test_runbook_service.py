"""runbook_service: plan and task writes, and the validation that keeps the
dependency graph honest. Transitions are test_runbook_execution.py's."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.v1.schemas.runbook import RunbookPlanCreate, RunbookPlanUpdate
from app.core.pagination import Page
from app.db.models.runbook import RunbookPlan
from app.services import runbook_service
from tests.factories import ensure_environment
from tests.runbook_helpers import link, make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


def _create(env_id, **kw):
    return RunbookPlanCreate(environment_id=env_id, name=kw.get("name", "Cutover"), anchor_start_at=ANCHOR,
                             deploy_pattern=kw.get("deploy_pattern"))


@pytest.mark.asyncio
async def test_create_then_a_second_live_plan_for_the_pair_is_a_409(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(test_environment.id))
    assert plan.id and plan.environment_id == test_environment.id
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(test_environment.id))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_deleted_plans_slot_is_revived_with_the_same_id_and_no_tasks(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    first = await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(test_environment.id))
    await make_task(db_session, first, "old task")
    await runbook_service.delete_plan(db_session, first, test_tenant.id)
    again = await runbook_service.create_plan(db_session, release.id, test_tenant.id,
                                              _create(test_environment.id, name="Take two", deploy_pattern="canary"))
    assert again.id == first.id
    assert again.deleted_at is None and again.name == "Take two" and again.deploy_pattern == "canary"
    assert await runbook_service.live_tasks(db_session, again.id, test_tenant.id) == []


@pytest.mark.asyncio
async def test_an_environment_from_another_tenant_or_archived_is_refused(db_session, test_tenant, test_user, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    other_tenant, _ = await second_tenant_factory()
    foreign = await ensure_environment(db_session, other_tenant.id, slot=11)
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(foreign.id))
    assert exc.value.status_code == 404
    archived = await ensure_environment(db_session, test_tenant.id, slot=12)
    archived.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_plan(db_session, release.id, test_tenant.id, _create(archived.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_plan_is_invisible_from_another_tenant(db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    other_tenant, _ = await second_tenant_factory()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.get_plan(db_session, plan.id, other_tenant.id)
    assert exc.value.status_code == 404
    rows, total = await runbook_service.list_plans(db_session, release.id, other_tenant.id, Page(limit=50, offset=0))
    assert rows == [] and total == 0


@pytest.mark.asyncio
async def test_update_changes_only_the_fields_sent(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    plan.notes = "keep me"
    await runbook_service.update_plan(db_session, plan, RunbookPlanUpdate(anchor_start_at=ANCHOR + timedelta(hours=1)))
    assert plan.notes == "keep me" and plan.anchor_start_at == ANCHOR + timedelta(hours=1)
    await runbook_service.update_plan(db_session, plan, RunbookPlanUpdate(notes=None))
    assert plan.notes is None


@pytest.mark.asyncio
async def test_a_plan_with_a_started_task_cannot_be_deleted(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    await make_task(db_session, plan, "running", status="in_progress")
    with pytest.raises(HTTPException) as exc:
        await runbook_service.delete_plan(db_session, plan, test_tenant.id)
    assert exc.value.status_code == 409
    assert (await db_session.get(RunbookPlan, plan.id)).deleted_at is None


@pytest.mark.asyncio
async def test_list_plans_orders_by_environment_name(db_session, test_tenant, test_user):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    zed = await ensure_environment(db_session, test_tenant.id, slot=13)
    zed.name = "zed-prod"
    await db_session.flush()
    alpha = await ensure_environment(db_session, test_tenant.id, slot=14)
    alpha.name = "Alpha-preprod"
    await db_session.flush()
    await make_plan(db_session, release, zed, anchor=ANCHOR)
    await make_plan(db_session, release, alpha, anchor=ANCHOR)
    rows, total = await runbook_service.list_plans(db_session, release.id, test_tenant.id, Page(limit=50, offset=0))
    assert [p.environment_id for p in rows] == [alpha.id, zed.id] and total == 2


@pytest.mark.asyncio
async def test_live_tasks_is_invisible_from_another_tenant(db_session, test_tenant, test_user, test_environment,
                                                            second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    await make_task(db_session, plan, "task one")
    other_tenant, _ = await second_tenant_factory()
    assert await runbook_service.live_tasks(db_session, plan.id, other_tenant.id) == []


@pytest.mark.asyncio
async def test_live_edges_excludes_a_soft_deleted_predecessor_and_is_invisible_from_another_tenant(
        db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    t1 = await make_task(db_session, plan, "t1")
    t2 = await make_task(db_session, plan, "t2")
    t3 = await make_task(db_session, plan, "t3")
    await link(db_session, t2, t1)  # edge (t2, t1)
    await link(db_session, t3, t2)  # edge (t3, t2)
    t1.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    edges = await runbook_service.live_edges(db_session, plan.id, test_tenant.id)
    assert edges == [(t3.id, t2.id)]  # (t2, t1) excluded: t1 is soft-deleted

    other_tenant, _ = await second_tenant_factory()
    assert await runbook_service.live_edges(db_session, plan.id, other_tenant.id) == []


@pytest.mark.asyncio
async def test_update_refuses_an_explicit_null_for_name_or_anchor(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    original_name, original_anchor = plan.name, plan.anchor_start_at

    with pytest.raises(HTTPException) as exc:
        await runbook_service.update_plan(db_session, plan, RunbookPlanUpdate(name=None))
    assert exc.value.status_code == 422
    assert plan.name == original_name

    with pytest.raises(HTTPException) as exc:
        await runbook_service.update_plan(db_session, plan, RunbookPlanUpdate(anchor_start_at=None))
    assert exc.value.status_code == 422
    assert plan.anchor_start_at == original_anchor


from sqlalchemy import select as _select

from app.api.v1.schemas.runbook import RunbookTaskCreate, RunbookTaskUpdate
from app.db.models.runbook import RunbookTask, RunbookTaskDependency
from tests.factories import ensure_user_group
from tests.runbook_helpers import attach_system, link, make_system


async def _plan(db, tenant, user, env):
    release = await make_release(db, tenant.id, user.id)
    return release, await make_plan(db, release, env, anchor=ANCHOR)


@pytest.mark.asyncio
async def test_create_task_with_predecessors_in_the_same_plan(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "A")
    b = await runbook_service.create_task(db_session, plan, test_tenant.id,
                                          RunbookTaskCreate(name="B", duration_minutes=10, predecessor_ids=[a.id]))
    assert await runbook_service.live_edges(db_session, plan.id, test_tenant.id) == [(b.id, a.id)]


@pytest.mark.asyncio
async def test_a_cycle_is_refused_naming_the_tasks(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "Deploy API")
    b = await make_task(db_session, plan, "Smoke test")
    await link(db_session, b, a)
    with pytest.raises(HTTPException) as exc:
        await runbook_service.set_predecessors(db_session, a, plan, test_tenant.id, [b.id])
    assert exc.value.status_code == 409
    assert "cycle" in exc.value.detail and "Deploy API" in exc.value.detail and "Smoke test" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await runbook_service.set_predecessors(db_session, a, plan, test_tenant.id, [a.id])
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_predecessor_from_another_plan_or_deleted_is_refused(db_session, test_tenant, test_user, test_environment):
    release, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    other_env = await ensure_environment(db_session, test_tenant.id, slot=21)
    other_plan = await make_plan(db_session, release, other_env, anchor=ANCHOR)
    mine = await make_task(db_session, plan, "mine")
    theirs = await make_task(db_session, other_plan, "theirs")
    gone = await make_task(db_session, plan, "gone")
    gone.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    for bad in (theirs.id, gone.id):
        with pytest.raises(HTTPException) as exc:
            await runbook_service.set_predecessors(db_session, mine, plan, test_tenant.id, [bad])
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_an_unsatisfied_predecessor_cannot_be_added_under_a_started_task(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    running = await make_task(db_session, plan, "running", status="in_progress")
    pending = await make_task(db_session, plan, "pending")
    finished = await make_task(db_session, plan, "finished", status="done")
    with pytest.raises(HTTPException) as exc:
        await runbook_service.set_predecessors(db_session, running, plan, test_tenant.id, [pending.id])
    assert exc.value.status_code == 409 and "pending" in exc.value.detail
    await runbook_service.set_predecessors(db_session, running, plan, test_tenant.id, [finished.id])  # fine


@pytest.mark.asyncio
async def test_set_predecessors_replaces_the_whole_set(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "A")
    b = await make_task(db_session, plan, "B")
    c = await make_task(db_session, plan, "C")
    await runbook_service.set_predecessors(db_session, c, plan, test_tenant.id, [a.id, b.id, a.id])
    assert sorted(await runbook_service.live_edges(db_session, plan.id, test_tenant.id)) == [(c.id, a.id), (c.id, b.id)]
    await runbook_service.set_predecessors(db_session, c, plan, test_tenant.id, [b.id])
    assert await runbook_service.live_edges(db_session, plan.id, test_tenant.id) == [(c.id, b.id)]


@pytest.mark.asyncio
async def test_a_started_task_cannot_be_deleted_and_a_not_started_one_takes_its_edges(db_session, test_tenant, test_user, test_environment):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    a = await make_task(db_session, plan, "A")
    b = await make_task(db_session, plan, "B")
    c = await make_task(db_session, plan, "C", status="in_progress")
    await link(db_session, b, a)
    with pytest.raises(HTTPException) as exc:
        await runbook_service.delete_task(db_session, c, test_tenant.id)
    assert exc.value.status_code == 409
    await runbook_service.delete_task(db_session, a, test_tenant.id)
    rows = (await db_session.execute(_select(RunbookTaskDependency))).scalars().all()
    assert rows == []   # hard-deleted in both directions
    assert (await db_session.get(RunbookTask, a.id)).deleted_at is not None


@pytest.mark.asyncio
async def test_team_validation_and_the_archived_carve_out(db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    ops = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    task = await runbook_service.create_task(db_session, plan, test_tenant.id,
                                             RunbookTaskCreate(name="T", duration_minutes=5, team_group_id=ops.id))
    ops.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    # re-sending the unchanged archived team is accepted
    await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                      RunbookTaskUpdate(name="T2", team_group_id=ops.id))
    fresh = await ensure_user_group(db_session, test_tenant.id, name="Archived")
    fresh.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                          RunbookTaskUpdate(team_group_id=fresh.id))
    assert exc.value.status_code == 404
    other_tenant, _ = await second_tenant_factory()
    foreign = await ensure_user_group(db_session, other_tenant.id, name="Foreign")
    with pytest.raises(HTTPException) as exc:
        await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                          RunbookTaskUpdate(team_group_id=foreign.id))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_system_must_be_on_the_release_unless_unchanged(db_session, test_tenant, test_user, test_environment):
    release, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    api = await make_system(db_session, test_tenant.id, "API")
    rs = await attach_system(db_session, release, api)
    stray = await make_system(db_session, test_tenant.id, "Stray")
    task = await runbook_service.create_task(db_session, plan, test_tenant.id,
                                             RunbookTaskCreate(name="Deploy", duration_minutes=5, system_id=api.id))
    with pytest.raises(HTTPException) as exc:
        await runbook_service.create_task(db_session, plan, test_tenant.id,
                                          RunbookTaskCreate(name="X", duration_minutes=5, system_id=stray.id))
    assert exc.value.status_code == 422
    await db_session.delete(rs)          # the system leaves the release (hard delete, as the API does)
    await db_session.flush()
    await runbook_service.update_task(db_session, task, plan, test_tenant.id,
                                      RunbookTaskUpdate(name="Deploy v2", system_id=api.id))
    assert task.system_id == api.id and task.name == "Deploy v2"


@pytest.mark.asyncio
async def test_a_task_in_another_tenant_is_not_found(db_session, test_tenant, test_user, test_environment, second_tenant_factory):
    _, plan = await _plan(db_session, test_tenant, test_user, test_environment)
    task = await make_task(db_session, plan, "T")
    other_tenant, _ = await second_tenant_factory()
    with pytest.raises(HTTPException) as exc:
        await runbook_service.get_task(db_session, task.id, other_tenant.id)
    assert exc.value.status_code == 404
