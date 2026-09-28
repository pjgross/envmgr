"""runbook_schedule_service.compute against hand-worked plans. Pure: no DB."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.runbook_schedule_service import (
    CycleError, TaskInput, compute, plan_state, topological_order,
)

A = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)   # anchor, 18:00 day 1
BEFORE = A - timedelta(days=1)                           # a "now" before anything


def t(id, dur=30, status="not_started", fixed=None, start=None, finish=None):
    return TaskInput(id=id, duration_minutes=dur, fixed_start_at=fixed, status=status,
                     actual_started_at=start, actual_finished_at=finish)


def m(n):
    return A + timedelta(minutes=n)


def test_a_chain_runs_back_to_back_from_the_anchor():
    s = compute(A, [t(1, 30), t(2, 20)], [(2, 1)], BEFORE)
    assert (s.tasks[1].planned_start, s.tasks[1].planned_finish) == (m(0), m(30))
    assert (s.tasks[2].planned_start, s.tasks[2].planned_finish) == (m(30), m(50))
    assert s.planned_end == m(50) and s.forecast_end == m(50)
    assert s.slip_minutes == 0 and s.state == "not_started"


def test_a_join_waits_for_the_latest_predecessor():
    # tests (3) cannot run until both deploys (1: 30m, 2: 90m) are done
    s = compute(A, [t(1, 30), t(2, 90), t(3, 15)], [(3, 1), (3, 2)], BEFORE)
    assert s.tasks[3].planned_start == m(90)


def test_a_fixed_start_later_than_the_predecessors_wins():
    next_evening = A + timedelta(days=1)
    s = compute(A, [t(1, 60), t(2, 10, fixed=next_evening)], [(2, 1)], BEFORE)
    assert s.tasks[2].planned_start == next_evening
    assert s.tasks[2].slipped_past_fixed_start is False


def test_the_second_evening_slips_when_a_pre_task_overruns():
    # pre-task planned 60m, started on time, still running 25h later
    next_evening = A + timedelta(days=1)
    now = A + timedelta(hours=25)
    s = compute(A, [t(1, 60, status="in_progress", start=A), t(2, 10, fixed=next_evening)], [(2, 1)], now)
    assert s.tasks[2].planned_start == next_evening
    assert s.tasks[2].forecast_start == now
    assert s.tasks[2].slipped_past_fixed_start is True
    assert s.tasks[2].late_start is True
    assert s.tasks[1].overrunning is True


def test_a_skipped_task_passes_time_through():
    s = compute(A, [t(1, 30, status="done", start=m(0), finish=m(30)), t(2, 60, status="skipped"), t(3, 10)],
                [(2, 1), (3, 2)], m(31))
    assert s.tasks[2].forecast_start == m(30) and s.tasks[2].forecast_finish == m(30)
    assert s.tasks[3].forecast_start == m(31)   # floored at now, not m(30)


def test_a_failed_task_blocks_everything_after_it_and_a_retry_clears_it():
    failed = compute(A, [t(1, 30, status="failed", start=m(0), finish=m(10)), t(2), t(3)],
                     [(2, 1), (3, 2)], m(20))
    assert failed.tasks[2].blocked and failed.tasks[3].blocked
    assert failed.state == "failed"
    retried = compute(A, [t(1, 30, status="in_progress", start=m(15)), t(2), t(3)],
                      [(2, 1), (3, 2)], m(20))
    assert not retried.tasks[2].blocked and retried.state == "in_progress"


def test_an_overdue_task_is_forecast_to_start_now_never_in_the_past():
    now = m(45)
    s = compute(A, [t(1, 30)], [], now)
    assert s.tasks[1].planned_start == m(0)
    assert s.tasks[1].forecast_start == now
    assert s.tasks[1].late_start is True
    assert s.slip_minutes == 45


def test_the_critical_path_is_the_longer_branch():
    # 1 → 3 (30m) and 2 → 3 (90m): only 2 and 3 are critical
    s = compute(A, [t(1, 30), t(2, 90), t(3, 15)], [(3, 1), (3, 2)], BEFORE)
    assert (s.tasks[1].critical, s.tasks[2].critical, s.tasks[3].critical) == (False, True, True)


def test_done_and_skipped_tasks_are_never_critical():
    s = compute(A, [t(1, 30, status="done", start=m(0), finish=m(30)), t(2, 30)], [(2, 1)], m(30))
    assert s.tasks[1].critical is False and s.tasks[2].critical is True


def test_a_zero_duration_milestone_takes_no_time():
    s = compute(A, [t(1, 30), t(2, 0), t(3, 10)], [(2, 1), (3, 2)], BEFORE)
    assert s.tasks[2].planned_start == s.tasks[2].planned_finish == m(30)
    assert s.tasks[3].planned_start == m(30)


def test_a_plan_with_no_tasks_ends_at_its_anchor():
    s = compute(A, [], [], BEFORE)
    assert s.planned_end == A and s.forecast_end == A and s.state == "not_started"


def test_seconds_are_truncated_and_naive_datetimes_are_read_as_utc():
    naive_anchor = datetime(2026, 10, 1, 18, 0, 42)            # what SQLite hands back
    naive_start = datetime(2026, 10, 1, 18, 5, 59)
    s = compute(naive_anchor, [t(1, 30, status="in_progress", start=naive_start)], [], m(6))
    assert s.tasks[1].planned_start == A
    assert s.tasks[1].forecast_start == m(5)


def test_a_cycle_raises_rather_than_looping():
    with pytest.raises(CycleError) as exc:
        topological_order([1, 2, 3], [(1, 2), (2, 1), (3, 1)])
    assert exc.value.task_ids == {1, 2, 3}
    with pytest.raises(CycleError):
        compute(A, [t(1), t(2)], [(1, 2), (2, 1)], BEFORE)


@pytest.mark.parametrize("statuses, state", [
    ([], "not_started"),
    (["not_started", "not_started"], "not_started"),
    (["done", "not_started"], "in_progress"),
    (["done", "skipped"], "complete"),
    (["done", "failed", "in_progress"], "failed"),
])
def test_plan_state_first_match_wins(statuses, state):
    assert plan_state(statuses) == state
