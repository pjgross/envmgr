"""Phase 9 C5a — runbook plan, task and dependency WRITES, and the validation
that keeps the graph honest. Status transitions live in
runbook_execution_service; the schedule in runbook_schedule_service.

C5a REFUSES ONLY WRITES TO ITS OWN RECORDS. Nothing in this file is consulted
by a deployment, a release transition, a booking, can-deploy or readiness —
tests/test_c5a_refuses_only_within_runbook.py is the guard.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.schemas.runbook import (
    PredecessorsUpdate, RunbookPlanCreate, RunbookPlanUpdate, RunbookTaskCreate, RunbookTaskUpdate,
)
from app.core.pagination import Page, fetch_page
from app.db.models.environment import Environment
from app.db.models.release_system import ReleaseSystem
from app.db.models.runbook import RunbookPlan, RunbookTask, RunbookTaskDependency, SATISFIED_STATUSES
from app.services import release_service, user_group_service
from app.services.runbook_schedule_service import CycleError, topological_order


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_plan(db: AsyncSession, plan_id: int, tenant_id: int) -> RunbookPlan:
    plan = (await db.execute(select(RunbookPlan).where(
        RunbookPlan.id == plan_id, RunbookPlan.tenant_id == tenant_id,
        RunbookPlan.deleted_at.is_(None)))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Runbook not found")
    return plan


async def list_plans(db: AsyncSession, release_id: int, tenant_id: int,
                     page: Optional[Page]) -> tuple[list[RunbookPlan], int]:
    query = (
        select(RunbookPlan)
        .join(Environment, Environment.id == RunbookPlan.environment_id)
        .where(RunbookPlan.release_id == release_id, RunbookPlan.tenant_id == tenant_id,
               RunbookPlan.deleted_at.is_(None))
        # Case folded explicitly: both engines collate by byte value (CLAUDE.md).
        .order_by(func.lower(Environment.name), RunbookPlan.id)
    )
    return await fetch_page(db, query, page)


async def _live_environment(db: AsyncSession, environment_id: int, tenant_id: int) -> Environment:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id, Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None)))).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Environment not found")
    return env


async def create_plan(db: AsyncSession, release_id: int, tenant_id: int,
                      data: RunbookPlanCreate) -> RunbookPlan:
    await release_service.get_release(db, release_id, tenant_id)
    await _live_environment(db, data.environment_id, tenant_id)
    rows = (await db.execute(select(RunbookPlan).where(
        RunbookPlan.release_id == release_id, RunbookPlan.environment_id == data.environment_id,
        RunbookPlan.tenant_id == tenant_id).order_by(RunbookPlan.id))).scalars().all()
    if any(p.deleted_at is None for p in rows):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This release already has a runbook for that environment")
    # REVIVE a soft-deleted slot rather than insert a second row (C4's lesson).
    # Its old tasks stay soft-deleted: a revived plan starts empty.
    plan = rows[0] if rows else RunbookPlan(tenant_id=tenant_id, release_id=release_id,
                                            environment_id=data.environment_id)
    plan.name = data.name
    plan.anchor_start_at = data.anchor_start_at
    plan.deploy_pattern = data.deploy_pattern
    plan.notes = data.notes
    plan.deleted_at = None
    if not rows:
        db.add(plan)
    await db.flush()
    return plan


async def update_plan(db: AsyncSession, plan: RunbookPlan, data: RunbookPlanUpdate) -> RunbookPlan:
    sent = data.model_fields_set
    if "name" in sent:
        if data.name is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name cannot be null")
        plan.name = data.name
    if "anchor_start_at" in sent:
        if data.anchor_start_at is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "anchor_start_at cannot be null")
        plan.anchor_start_at = data.anchor_start_at
    if "deploy_pattern" in sent:
        plan.deploy_pattern = data.deploy_pattern
    if "notes" in sent:
        plan.notes = data.notes
    await db.flush()
    return plan


async def live_tasks(db: AsyncSession, plan_id: int, tenant_id: int) -> list[RunbookTask]:
    return list((await db.execute(select(RunbookTask).where(
        RunbookTask.plan_id == plan_id, RunbookTask.tenant_id == tenant_id,
        RunbookTask.deleted_at.is_(None)).order_by(RunbookTask.sort_order, RunbookTask.id))).scalars().all())


async def live_edges(db: AsyncSession, plan_id: int, tenant_id: int) -> list[tuple[int, int]]:
    """(task_id, predecessor_id) where BOTH ends are live tasks of this plan.
    A soft-deleted predecessor counts as absent — the same rule
    runbook_execution_service.ready_clause applies in SQL."""
    succ, pred = aliased(RunbookTask), aliased(RunbookTask)
    rows = (await db.execute(
        select(RunbookTaskDependency.task_id, RunbookTaskDependency.predecessor_task_id)
        .join(succ, succ.id == RunbookTaskDependency.task_id)
        .join(pred, pred.id == RunbookTaskDependency.predecessor_task_id)
        .where(RunbookTaskDependency.tenant_id == tenant_id,
               succ.plan_id == plan_id, succ.deleted_at.is_(None),
               pred.plan_id == plan_id, pred.deleted_at.is_(None))
        .order_by(RunbookTaskDependency.id))).all()
    return [(a, b) for a, b in rows]


async def delete_plan(db: AsyncSession, plan: RunbookPlan, tenant_id: int) -> None:
    tasks = await live_tasks(db, plan.id, tenant_id)
    started = [t.name for t in tasks if t.status != "not_started"]
    if started:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A runbook whose tasks have started cannot be deleted — its history is "
                            f"the record. Started: {', '.join(started)}")
    now = _now()
    plan.deleted_at = now
    for t in tasks:
        t.deleted_at = now
    await db.flush()


async def get_task(db: AsyncSession, task_id: int, tenant_id: int) -> tuple[RunbookTask, RunbookPlan]:
    row = (await db.execute(
        select(RunbookTask, RunbookPlan)
        .join(RunbookPlan, RunbookPlan.id == RunbookTask.plan_id)
        .where(RunbookTask.id == task_id, RunbookTask.tenant_id == tenant_id,
               RunbookTask.deleted_at.is_(None), RunbookPlan.deleted_at.is_(None)))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Runbook task not found")
    return row[0], row[1]


async def _validate_team(db, tenant_id: int, new_id: Optional[int], current_id: Optional[int]) -> None:
    """A1's archived-value carve-out: an unchanged team is accepted even if it
    has since been archived; a NEW assignment must be a live group of this tenant."""
    if new_id is None or new_id == current_id:
        return
    await user_group_service.get_group(db, new_id, tenant_id)   # 404s on archived / foreign


async def _validate_system(db, plan: RunbookPlan, tenant_id: int, new_id: Optional[int],
                           current_id: Optional[int]) -> None:
    """The permission guards a CHANGE, not a mention (B2): an unchanged system
    that has since left the release is accepted on a full-form save."""
    if new_id is None or new_id == current_id:
        return
    on_release = (await db.execute(select(ReleaseSystem.id).where(
        ReleaseSystem.release_id == plan.release_id, ReleaseSystem.system_id == new_id,
        ReleaseSystem.tenant_id == tenant_id))).first()
    if on_release is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That system is not part of this release")


async def create_task(db: AsyncSession, plan: RunbookPlan, tenant_id: int,
                      data: RunbookTaskCreate) -> RunbookTask:
    await _validate_team(db, tenant_id, data.team_group_id, None)
    await _validate_system(db, plan, tenant_id, data.system_id, None)
    task = RunbookTask(
        tenant_id=tenant_id, plan_id=plan.id, name=data.name, description=data.description,
        team_group_id=data.team_group_id, system_id=data.system_id, kind=data.kind,
        duration_minutes=data.duration_minutes, fixed_start_at=data.fixed_start_at,
        sort_order=data.sort_order, status="not_started")
    db.add(task)
    await db.flush()
    if data.predecessor_ids:
        await set_predecessors(db, task, plan, tenant_id, data.predecessor_ids)
    return task


_NOT_NULL = {"name", "kind", "duration_minutes", "sort_order"}


async def update_task(db: AsyncSession, task: RunbookTask, plan: RunbookPlan, tenant_id: int,
                      data: RunbookTaskUpdate) -> RunbookTask:
    sent = data.model_fields_set
    for field in _NOT_NULL & sent:
        if getattr(data, field) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} cannot be null")
    if "team_group_id" in sent:
        await _validate_team(db, tenant_id, data.team_group_id, task.team_group_id)
    if "system_id" in sent:
        await _validate_system(db, plan, tenant_id, data.system_id, task.system_id)
    for field in ("name", "description", "team_group_id", "system_id", "kind",
                  "duration_minutes", "fixed_start_at", "sort_order"):
        if field in sent:
            setattr(task, field, getattr(data, field))
    await db.flush()
    return task


async def delete_task(db: AsyncSession, task: RunbookTask, tenant_id: int) -> None:
    if task.status != "not_started":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"'{task.name}' has started and cannot be deleted — its history is the record")
    await db.execute(delete(RunbookTaskDependency).where(
        RunbookTaskDependency.tenant_id == tenant_id,
        or_(RunbookTaskDependency.task_id == task.id,
            RunbookTaskDependency.predecessor_task_id == task.id)))
    task.deleted_at = _now()
    await db.flush()


async def set_predecessors(db: AsyncSession, task: RunbookTask, plan: RunbookPlan, tenant_id: int,
                           predecessor_ids: list[int]) -> None:
    """Replace the whole set, validated as one unit (spec §4)."""
    ids = list(dict.fromkeys(predecessor_ids))
    tasks = {t.id: t for t in await live_tasks(db, plan.id, tenant_id)}
    if task.id in ids:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This dependency would create a cycle through: {task.name}")
    missing = [i for i in ids if i not in tasks]
    if missing:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Not live tasks in this runbook: {', '.join(map(str, missing))}")
    if task.status != "not_started":
        unsatisfied = [tasks[i] for i in ids if tasks[i].status not in SATISFIED_STATUSES]
        if unsatisfied:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{task.name}' has already started, so it cannot wait on tasks that are not done: "
                + ", ".join(f"{t.name} ({t.status})" for t in unsatisfied))
    edges = [(a, b) for a, b in await live_edges(db, plan.id, tenant_id) if a != task.id]
    edges += [(task.id, i) for i in ids]
    try:
        topological_order(tasks, edges)
    except CycleError as exc:
        names = sorted(tasks[i].name for i in exc.task_ids if i in tasks)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This dependency would create a cycle through: {', '.join(names)}")
    await db.execute(delete(RunbookTaskDependency).where(
        RunbookTaskDependency.tenant_id == tenant_id, RunbookTaskDependency.task_id == task.id))
    for i in ids:
        db.add(RunbookTaskDependency(tenant_id=tenant_id, task_id=task.id, predecessor_task_id=i))
    await db.flush()
