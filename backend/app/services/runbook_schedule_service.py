"""The runbook schedule, computed on read. PURE — no database access.

This is the ONLY place scheduling rules live. The composite read, the
timeline, and (C5b) the readiness finding all read its output; nothing may
re-derive a start time, a lateness flag or criticality elsewhere.

Minute precision, UTC. Deliberately NOT expiry_boundary's day rule: a cutover
is measured in minutes. See spec §5.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from app.db.models.runbook import SATISFIED_STATUSES


class CycleError(ValueError):
    def __init__(self, task_ids: set[int]):
        super().__init__(f"dependency cycle among tasks {sorted(task_ids)}")
        self.task_ids = task_ids


@dataclass(frozen=True)
class TaskInput:
    id: int
    duration_minutes: int
    fixed_start_at: Optional[datetime]
    status: str
    actual_started_at: Optional[datetime]
    actual_finished_at: Optional[datetime]


@dataclass(frozen=True)
class TaskSchedule:
    planned_start: datetime
    planned_finish: datetime
    forecast_start: datetime
    forecast_finish: datetime
    late_start: bool
    overrunning: bool
    slipped_past_fixed_start: bool
    blocked: bool
    critical: bool


@dataclass(frozen=True)
class PlanSchedule:
    tasks: dict[int, TaskSchedule]
    planned_end: datetime
    forecast_end: datetime
    slip_minutes: int
    state: str


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes, PostgreSQL aware ones; comparing the two
    is a TypeError on one engine only. Read naive as UTC, truncate to the minute."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


def topological_order(task_ids: Iterable[int], edges: Iterable[tuple[int, int]]) -> list[int]:
    """Kahn's algorithm, ties broken by id so the order is deterministic.
    `edges` are (task_id, predecessor_id)."""
    ids = sorted(set(task_ids))
    indegree = {i: 0 for i in ids}
    successors: dict[int, list[int]] = defaultdict(list)
    for task_id, pred_id in edges:
        if task_id in indegree and pred_id in indegree:
            indegree[task_id] += 1
            successors[pred_id].append(task_id)
    ready = deque(i for i in ids if indegree[i] == 0)
    order: list[int] = []
    while ready:
        current = ready.popleft()
        order.append(current)
        for nxt in sorted(successors[current]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(ids):
        raise CycleError(set(ids) - set(order))
    return order


def plan_state(statuses: Iterable[str]) -> str:
    """First match wins: complete, failed, in_progress, not_started. A plan
    with no tasks is not_started (never 'complete')."""
    s = list(statuses)
    if s and all(x in SATISFIED_STATUSES for x in s):
        return "complete"
    if any(x == "failed" for x in s):
        return "failed"
    if any(x != "not_started" for x in s):
        return "in_progress"
    return "not_started"


def compute(anchor: datetime, tasks: list[TaskInput], edges: list[tuple[int, int]],
            now: datetime) -> PlanSchedule:
    anchor = _utc(anchor)
    now = _utc(now)
    by_id = {t.id: t for t in tasks}
    edges = [(a, b) for a, b in edges if a in by_id and b in by_id]
    preds: dict[int, list[int]] = defaultdict(list)
    succs: dict[int, list[int]] = defaultdict(list)
    for task_id, pred_id in edges:
        preds[task_id].append(pred_id)
        succs[pred_id].append(task_id)
    order = topological_order(by_id, edges)

    def dur(t: TaskInput) -> timedelta:
        return timedelta(minutes=t.duration_minutes)

    # Planned pass — the baseline; ignores status.
    p_start: dict[int, datetime] = {}
    p_finish: dict[int, datetime] = {}
    for i in order:
        t = by_id[i]
        start = max((p_finish[p] for p in preds[i]), default=anchor)
        fixed = _utc(t.fixed_start_at)
        if fixed is not None:
            start = max(start, fixed)
        p_start[i], p_finish[i] = start, start + dur(t)

    # Forecast pass — the plan as it now stands.
    f_start: dict[int, datetime] = {}
    f_finish: dict[int, datetime] = {}
    pred_driven: dict[int, datetime] = {}
    blocked: dict[int, bool] = {}
    for i in order:
        t = by_id[i]
        driven = max((f_finish[p] for p in preds[i]), default=anchor)
        pred_driven[i] = driven
        blocked[i] = any(by_id[p].status == "failed" or blocked[p] for p in preds[i])
        started, finished = _utc(t.actual_started_at), _utc(t.actual_finished_at)
        if t.status == "done":
            f_start[i] = started or finished or driven
            f_finish[i] = finished or f_start[i]
        elif t.status in ("in_progress", "failed"):
            f_start[i] = started or now
            f_finish[i] = max(f_start[i] + dur(t), now)
        elif t.status == "skipped":
            f_start[i] = f_finish[i] = driven
        else:  # not_started
            start = driven
            fixed = _utc(t.fixed_start_at)
            if fixed is not None:
                start = max(start, fixed)
            f_start[i] = max(start, now)
            f_finish[i] = f_start[i] + dur(t)

    planned_end = max(p_finish.values(), default=anchor)
    forecast_end = max(f_finish.values(), default=anchor)

    # Backward pass over the forecast for total float. A task's latest finish
    # is the earliest latest-start of its successors (or the plan's end).
    latest_finish: dict[int, datetime] = {}
    for i in reversed(order):
        latest_finish[i] = min(
            (latest_finish[s] - (f_finish[s] - f_start[s]) for s in succs[i]),
            default=forecast_end,
        )

    result: dict[int, TaskSchedule] = {}
    for i in order:
        t = by_id[i]
        fixed = _utc(t.fixed_start_at)
        started = _utc(t.actual_started_at)
        result[i] = TaskSchedule(
            planned_start=p_start[i], planned_finish=p_finish[i],
            forecast_start=f_start[i], forecast_finish=f_finish[i],
            late_start=f_start[i] > p_start[i],
            overrunning=t.status == "in_progress" and started is not None and now > started + dur(t),
            slipped_past_fixed_start=fixed is not None and pred_driven[i] > fixed,
            blocked=blocked[i],
            critical=t.status not in SATISFIED_STATUSES and latest_finish[i] == f_finish[i],
        )

    slip = int((forecast_end - planned_end).total_seconds() // 60)
    return PlanSchedule(tasks=result, planned_end=planned_end, forecast_end=forecast_end,
                        slip_minutes=max(slip, 0), state=plan_state(t.status for t in tasks))
