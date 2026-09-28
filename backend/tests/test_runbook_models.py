"""The four runbook tables exist, round-trip, and carry the defaults the
services rely on. Schema parity with the migration is test_migration_schema_drift's
job; this file checks the models themselves."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db.models.runbook import (
    RunbookPlan, RunbookTask, RunbookTaskDependency, RunbookTaskEvent,
    SATISFIED_STATUSES, TASK_STATUSES,
)
from tests.runbook_helpers import link, make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_plan_with_tasks_and_an_edge_round_trips(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    a = await make_task(db_session, plan, "Deploy API")
    b = await make_task(db_session, plan, "Smoke test")
    await link(db_session, b, a)
    db_session.add(RunbookTaskEvent(tenant_id=test_tenant.id, task_id=a.id, from_status="not_started",
                                    to_status="in_progress", at=ANCHOR, recorded_at=ANCHOR,
                                    by_user_id=test_user.id))
    await db_session.commit()

    assert (await db_session.get(RunbookTask, a.id)).status == "not_started"
    edges = (await db_session.execute(select(RunbookTaskDependency))).scalars().all()
    assert [(e.task_id, e.predecessor_task_id) for e in edges] == [(b.id, a.id)]
    assert (await db_session.get(RunbookPlan, plan.id)).anchor_start_at is not None


def test_the_satisfied_set_is_exactly_done_and_skipped():
    assert SATISFIED_STATUSES == frozenset({"done", "skipped"})
    assert set(TASK_STATUSES) == {"not_started", "in_progress", "done", "failed", "skipped"}
