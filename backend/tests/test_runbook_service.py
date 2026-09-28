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
from tests.runbook_helpers import make_plan, make_release, make_task

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
