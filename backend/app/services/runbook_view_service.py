"""The composite runbook read: plan + tasks + edges + the computed schedule +
rendered names + per-task allowed_transitions for the caller. The UI renders
only what this returns and never re-derives a rule."""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.runbook import RunbookPlanRead, RunbookRead, RunbookTaskRead
from app.db.models.release_system import ReleaseSystem
from app.db.models.runbook import RunbookPlan, RunbookTask
from app.db.models.system import System
from app.services import environment_service, runbook_execution_service, runbook_service, user_group_service
from app.services.runbook_schedule_service import TaskInput, compute, plan_state


def _inputs(tasks: list[RunbookTask]) -> list[TaskInput]:
    return [TaskInput(id=t.id, duration_minutes=t.duration_minutes, fixed_start_at=t.fixed_start_at,
                      status=t.status, actual_started_at=t.actual_started_at,
                      actual_finished_at=t.actual_finished_at) for t in tasks]


async def _system_names(db, ids: set, tenant_id: int) -> dict[int, str]:
    """Read-rendering: does NOT filter deleted_at — an archived system still names itself."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(System.id, System.name).where(
        System.id.in_(ids), System.tenant_id == tenant_id))).all()
    return {i: n for i, n in rows}


async def plan_reads(db: AsyncSession, plans: list[RunbookPlan], tenant_id: int) -> list[RunbookPlanRead]:
    env_names = await environment_service.get_environment_names(db, {p.environment_id for p in plans}, tenant_id)
    ids = [p.id for p in plans]
    statuses: dict[int, list[str]] = defaultdict(list)
    if ids:
        rows = (await db.execute(select(RunbookTask.plan_id, RunbookTask.status).where(
            RunbookTask.plan_id.in_(ids), RunbookTask.tenant_id == tenant_id,
            RunbookTask.deleted_at.is_(None)))).all()
        for plan_id, st in rows:
            statuses[plan_id].append(st)
    return [RunbookPlanRead(id=p.id, release_id=p.release_id, environment_id=p.environment_id,
                            environment_name=env_names.get(p.environment_id), name=p.name,
                            anchor_start_at=p.anchor_start_at, deploy_pattern=p.deploy_pattern,
                            notes=p.notes, state=plan_state(statuses[p.id])) for p in plans]


async def read(db: AsyncSession, plan: RunbookPlan, tenant_id: int, user, now: datetime) -> RunbookRead:
    tasks = await runbook_service.live_tasks(db, plan.id, tenant_id)
    by_id = {t.id: t for t in tasks}
    edges = await runbook_service.live_edges(db, plan.id, tenant_id)
    # live_tasks and live_edges are two separate statements: under READ
    # COMMITTED, a task/edge committed by another request between them can
    # leave an edge whose task or predecessor id isn't in `by_id` (schedule
    # computation) or `tasks`. Filter rather than index blindly —
    # runbook_schedule_service.compute already does this defensively for its
    # own by_id; this composite must too, or `by_id[p]`/`by_id[s]` below
    # KeyErrors on the stale edge.
    edges = [(s, p) for s, p in edges if s in by_id and p in by_id]
    schedule = compute(plan.anchor_start_at, _inputs(tasks), edges, now)
    preds: dict[int, list[int]] = defaultdict(list)
    succs: dict[int, list[int]] = defaultdict(list)
    for s, p in edges:
        preds[s].append(p)
        succs[p].append(s)

    team_names = await user_group_service.get_group_names(db, {t.team_group_id for t in tasks})
    system_names = await _system_names(db, {t.system_id for t in tasks}, tenant_id)
    on_release = set((await db.execute(select(ReleaseSystem.system_id).where(
        ReleaseSystem.release_id == plan.release_id, ReleaseSystem.tenant_id == tenant_id))).scalars().all())
    manager = runbook_execution_service.is_manager(user)
    my_teams = await runbook_execution_service.team_ids_for(
        db, user.id, tenant_id, {t.team_group_id for t in tasks})
    [plan_read] = await plan_reads(db, [plan], tenant_id)

    out = []
    for t in tasks:
        sch = schedule.tasks[t.id]
        out.append(RunbookTaskRead(
            id=t.id, name=t.name, description=t.description, kind=t.kind,
            team_group_id=t.team_group_id, team_name=team_names.get(t.team_group_id),
            system_id=t.system_id, system_name=system_names.get(t.system_id),
            system_on_release=t.system_id is None or t.system_id in on_release,
            duration_minutes=t.duration_minutes, fixed_start_at=t.fixed_start_at, status=t.status,
            actual_started_at=t.actual_started_at, actual_finished_at=t.actual_finished_at,
            sort_order=t.sort_order, predecessor_ids=sorted(preds[t.id]),
            planned_start=sch.planned_start, planned_finish=sch.planned_finish,
            forecast_start=sch.forecast_start, forecast_finish=sch.forecast_finish,
            late_start=sch.late_start, overrunning=sch.overrunning,
            slipped_past_fixed_start=sch.slipped_past_fixed_start, blocked=sch.blocked, critical=sch.critical,
            allowed_transitions=runbook_execution_service.allowed_transitions(
                t.status, [by_id[p].status for p in preds[t.id]], [by_id[s].status for s in succs[t.id]],
                manager=manager, team_member=t.team_group_id in my_teams),
        ))
    out.sort(key=lambda r: (r.planned_start, r.sort_order, r.id))
    return RunbookRead(plan=plan_read, planned_end=schedule.planned_end, forecast_end=schedule.forecast_end,
                       slip_minutes=schedule.slip_minutes, tasks=out)
