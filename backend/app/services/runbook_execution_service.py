"""Phase 9 C5a — runbook task status transitions, who may make them, and the
append-only history.

THE INVARIANT: no task is in_progress or done while any predecessor is
anything other than done or skipped. Every refusal here protects that one
sentence (spec §4). It is the ONLY rule C5a enforces, and only on writes to
runbook records.

Membership is read in exactly one place, `team_ids_for`.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.schemas.runbook import TransitionRequest
from app.core.pagination import Page, fetch_page, fetch_page_rows
from app.core.security import Role
from app.db.models.environment import Environment
from app.db.models.release import Release
from app.db.models.runbook import (
    SATISFIED_STATUSES, RunbookPlan, RunbookTask, RunbookTaskDependency, RunbookTaskEvent,
)
from app.db.models.user_group import UserGroupMember
from app.services import runbook_service

EDGES: dict[str, tuple[str, ...]] = {
    "not_started": ("in_progress", "done", "skipped"),
    "in_progress": ("done", "failed"),
    "failed": ("in_progress", "skipped"),
    "done": ("not_started",),
    "skipped": ("not_started",),
}
_ORDER = ("in_progress", "done", "failed", "skipped", "not_started")
MANAGER_ONLY = {("not_started", "skipped"), ("failed", "skipped"),
                ("done", "not_started"), ("skipped", "not_started")}
NEEDS_PREDECESSORS = {("not_started", "in_progress"), ("not_started", "done")}
NEEDS_QUIET_SUCCESSORS = {("done", "not_started"), ("skipped", "not_started")}


def is_manager(user) -> bool:
    return bool(user.is_master_admin) or user.role in (Role.ADMIN, Role.RELEASE_MANAGER)


async def team_ids_for(db: AsyncSession, user_id: int, tenant_id: int, group_ids: set[int]) -> set[int]:
    """Which of `group_ids` the user is a member of, IN THIS TENANT. A task with
    no team, or a team with no members, simply matches nothing — degrading to
    managers only (B3b's rule)."""
    ids = {g for g in group_ids if g is not None}
    if not ids:
        return set()
    rows = (await db.execute(select(UserGroupMember.group_id).where(
        UserGroupMember.user_id == user_id, UserGroupMember.tenant_id == tenant_id,
        UserGroupMember.group_id.in_(ids)))).scalars().all()
    return set(rows)


def allowed_transitions(task_status: str, pred_statuses: list[str], succ_statuses: list[str], *,
                        manager: bool, team_member: bool) -> list[str]:
    """Targets the caller could perform RIGHT NOW. The UI renders only these."""
    out = []
    for to in EDGES.get(task_status, ()):
        pair = (task_status, to)
        if pair in MANAGER_ONLY:
            if not manager:
                continue
        elif not (manager or team_member):
            continue
        if pair in NEEDS_PREDECESSORS and any(s not in SATISFIED_STATUSES for s in pred_statuses):
            continue
        if pair in NEEDS_QUIET_SUCCESSORS and any(s != "not_started" for s in succ_statuses):
            continue
        out.append(to)
    return sorted(out, key=_ORDER.index)


async def _neighbours(db, task: RunbookTask, tenant_id: int) -> tuple[list[RunbookTask], list[RunbookTask]]:
    by_id = {t.id: t for t in await runbook_service.live_tasks(db, task.plan_id, tenant_id)}
    edges = await runbook_service.live_edges(db, task.plan_id, tenant_id)
    # Same race as runbook_view_service.read: live_tasks and live_edges are
    # two separate statements, so a task/edge committed between them can
    # leave an edge referencing an id absent from `by_id`. Filter, never
    # index blindly.
    edges = [(s, p) for s, p in edges if s in by_id and p in by_id]
    preds = [by_id[p] for s, p in edges if s == task.id]
    succs = [by_id[s] for s, p in edges if p == task.id]
    return preds, succs


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def transition(db: AsyncSession, task: RunbookTask, plan: RunbookPlan, tenant_id: int, user,
                     data: TransitionRequest, now: datetime) -> RunbookTask:
    to, frm = data.to_status, task.status
    pair = (frm, to)
    if to not in EDGES.get(frm, ()):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"'{task.name}' is {frm} and cannot move to {to}")
    manager = is_manager(user)
    if pair in MANAGER_ONLY:
        if not manager:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Only an Admin or Release Manager can skip or reopen a task")
    elif not manager:
        member = task.team_group_id is not None and task.team_group_id in await team_ids_for(
            db, user.id, tenant_id, {task.team_group_id})
        if not member:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Only the task's team, or an Admin or Release Manager, can update it")
    reason = (data.reason or "").strip() or None
    if pair in MANAGER_ONLY and reason is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A reason is required to skip or reopen a task")
    at = _utc(data.at) if data.at is not None else now
    if at > now:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "'at' cannot be in the future")
    # Back-dating is honest reporting and is not policed against OTHER tasks
    # (spec §4) — but a task cannot finish before its OWN recorded start.
    if frm == "in_progress" and task.actual_started_at is not None:
        started = _utc(task.actual_started_at)
        if at < started:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"'{task.name}' cannot finish before it started ({started.isoformat()})")

    preds, succs = await _neighbours(db, task, tenant_id)
    if pair in NEEDS_PREDECESSORS:
        blocking = [p for p in preds if p.status not in SATISFIED_STATUSES]
        if blocking:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{task.name}' cannot start until these are done or skipped: "
                + ", ".join(f"{p.name} ({p.status})" for p in blocking))
    if pair in NEEDS_QUIET_SUCCESSORS:
        moving = [s for s in succs if s.status != "not_started"]
        if moving:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{task.name}' cannot be reopened while tasks that depend on it have started: "
                + ", ".join(f"{s.name} ({s.status})" for s in moving))

    if to == "in_progress":
        task.actual_started_at, task.actual_finished_at = at, None
    elif to == "done" and frm == "not_started":
        task.actual_started_at = task.actual_finished_at = at
    elif to in ("done", "failed", "skipped"):
        task.actual_finished_at = at
    elif to == "not_started":
        task.actual_started_at = task.actual_finished_at = None
    task.status = to
    db.add(RunbookTaskEvent(tenant_id=tenant_id, task_id=task.id, from_status=frm, to_status=to,
                            at=at, recorded_at=now, by_user_id=user.id, note=reason))
    await db.flush()
    return task


async def list_events(db: AsyncSession, task_id: int, tenant_id: int,
                      page: Optional[Page]) -> tuple[list[RunbookTaskEvent], int]:
    query = (select(RunbookTaskEvent)
             .where(RunbookTaskEvent.task_id == task_id, RunbookTaskEvent.tenant_id == tenant_id)
             .order_by(RunbookTaskEvent.recorded_at.desc(), RunbookTaskEvent.id.desc()))
    return await fetch_page(db, query, page)


def ready_clause():
    """A task is READY when it is not_started, live, and no LIVE predecessor is
    unsatisfied. The SQL twin of allowed_transitions' predecessor rule —
    test_runbook_my_work.py holds the two equal. A soft-deleted predecessor
    counts as absent, as it does in runbook_service.live_edges."""
    pred = aliased(RunbookTask)
    return and_(
        RunbookTask.status == "not_started",
        RunbookTask.deleted_at.is_(None),
        ~exists().where(
            RunbookTaskDependency.task_id == RunbookTask.id,
            RunbookTaskDependency.predecessor_task_id == pred.id,
            pred.deleted_at.is_(None),
            pred.status.not_in(tuple(SATISFIED_STATUSES)),
        ),
    )


async def ready_queue(db: AsyncSession, tenant_id: int, user_id: int, page: Optional[Page]):
    """Tasks the user's teams could start now. Everyone — Admins included —
    sees only their OWN teams' tasks: this is "waiting on me", not a tenant list."""
    query = (
        select(RunbookTask.id.label("task_id"), RunbookTask.name.label("task_name"),
               RunbookPlan.id.label("plan_id"), Release.id.label("release_id"),
               Release.name.label("release_name"), Environment.name.label("environment_name"))
        .join(RunbookPlan, RunbookPlan.id == RunbookTask.plan_id)
        .join(Release, Release.id == RunbookPlan.release_id)
        .join(Environment, Environment.id == RunbookPlan.environment_id)
        .join(UserGroupMember, and_(UserGroupMember.group_id == RunbookTask.team_group_id,
                                    UserGroupMember.user_id == user_id,
                                    UserGroupMember.tenant_id == tenant_id))
        .where(RunbookTask.tenant_id == tenant_id, RunbookPlan.deleted_at.is_(None),
               Release.deleted_at.is_(None), ready_clause())
        .order_by(RunbookPlan.anchor_start_at, RunbookTask.id)
    )
    return await fetch_page_rows(db, query, page)
