"""Spec §4, one test per row of the transition table, plus permissions,
reasons, `at`, and the invariant on reopen."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.schemas.runbook import TransitionRequest
from app.core.pagination import Page
from app.db.models.runbook import RunbookTaskEvent
from app.services import runbook_execution_service as ex
from app.services import runbook_service
from tests.factories import add_group_member, ensure_user, ensure_user_group
from tests.runbook_helpers import link, make_plan, make_release, make_task

ANCHOR = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
NOW = ANCHOR + timedelta(hours=1)


@pytest.fixture
async def world(db_session, test_tenant, test_user, test_environment):
    release = await make_release(db_session, test_tenant.id, test_user.id)
    plan = await make_plan(db_session, release, test_environment, anchor=ANCHOR)
    team = await ensure_user_group(db_session, test_tenant.id, name="DBA")
    member = await ensure_user(db_session, test_tenant.id, username="dba1", role="Developer")
    outsider = await ensure_user(db_session, test_tenant.id, username="dev2", role="Developer")
    rm = await ensure_user(db_session, test_tenant.id, username="rm1", role="Release Manager")
    await add_group_member(db_session, team, member)
    for u in (member, outsider, rm):
        u.active_tenant_id = test_tenant.id
    test_user.active_tenant_id = test_tenant.id
    return dict(plan=plan, team=team, member=member, outsider=outsider, rm=rm, admin=test_user,
                tenant_id=test_tenant.id)


async def _go(db, w, task, user, to, **kw):
    return await ex.transition(db, task, w["plan"], w["tenant_id"], user, TransitionRequest(to_status=to, **kw), NOW)


@pytest.mark.asyncio
async def test_start_is_refused_until_every_predecessor_is_satisfied(db_session, world):
    w = world
    a = await make_task(db_session, w["plan"], "Deploy API", team=w["team"])
    b = await make_task(db_session, w["plan"], "Deploy DB", team=w["team"], status="in_progress")
    tests = await make_task(db_session, w["plan"], "Run tests", team=w["team"])
    await link(db_session, tests, a, b)
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, tests, w["member"], "in_progress")
    assert exc.value.status_code == 409
    assert "Deploy API (not_started)" in exc.value.detail and "Deploy DB (in_progress)" in exc.value.detail
    a.status, b.status = "done", "skipped"
    await db_session.flush()
    await _go(db_session, w, tests, w["member"], "in_progress")
    assert tests.status == "in_progress" and tests.actual_started_at == NOW


@pytest.mark.asyncio
async def test_not_started_straight_to_done_stamps_both_times(db_session, world):
    t = await make_task(db_session, world["plan"], "Check", team=world["team"])
    at = NOW - timedelta(minutes=5)
    await _go(db_session, world, t, world["member"], "done", at=at)
    assert t.actual_started_at == at and t.actual_finished_at == at


@pytest.mark.asyncio
async def test_in_progress_to_done_and_to_failed(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"], status="in_progress")
    await _go(db_session, world, t, world["member"], "failed")
    assert t.status == "failed" and t.actual_finished_at == NOW


@pytest.mark.asyncio
async def test_retry_restamps_the_start_clears_the_finish_and_keeps_the_failure(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"], status="in_progress")
    await _go(db_session, world, t, world["member"], "failed", at=NOW - timedelta(minutes=10))
    await _go(db_session, world, t, world["member"], "in_progress")
    assert t.status == "in_progress" and t.actual_started_at == NOW and t.actual_finished_at is None
    events = (await db_session.execute(select(RunbookTaskEvent).where(RunbookTaskEvent.task_id == t.id)
                                       .order_by(RunbookTaskEvent.id))).scalars().all()
    assert [(e.from_status, e.to_status) for e in events] == [("in_progress", "failed"), ("failed", "in_progress")]


@pytest.mark.asyncio
async def test_skip_is_manager_only_needs_a_reason_and_ignores_predecessors(db_session, world):
    w = world
    pred = await make_task(db_session, w["plan"], "Pred")
    t = await make_task(db_session, w["plan"], "T", team=w["team"])
    await link(db_session, t, pred)
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, t, w["member"], "skipped", reason="n/a")
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, t, w["rm"], "skipped")
    assert exc.value.status_code == 422
    await _go(db_session, w, t, w["rm"], "skipped", reason="not needed in this region")
    assert t.status == "skipped"
    ev = (await db_session.execute(select(RunbookTaskEvent).where(RunbookTaskEvent.task_id == t.id))).scalar_one()
    assert ev.note == "not needed in this region" and ev.by_user_id == w["rm"].id


@pytest.mark.asyncio
async def test_reopen_is_refused_under_a_started_successor(db_session, world):
    w = world
    a = await make_task(db_session, w["plan"], "A", status="done")
    b = await make_task(db_session, w["plan"], "B", status="in_progress")
    await link(db_session, b, a)
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, a, w["admin"], "not_started", reason="ticked wrong task")
    assert exc.value.status_code == 409 and "B" in exc.value.detail
    b.status = "not_started"
    await db_session.flush()
    await _go(db_session, w, a, w["admin"], "not_started", reason="ticked wrong task")
    assert a.status == "not_started" and a.actual_started_at is None and a.actual_finished_at is None


@pytest.mark.asyncio
async def test_a_transition_not_in_the_table_is_a_409(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"], status="done")
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, world, t, world["member"], "failed")
    assert exc.value.status_code == 409 and "done" in exc.value.detail


@pytest.mark.asyncio
async def test_permissions_team_manager_outsider_and_the_empty_team(db_session, world, test_tenant):
    w = world
    t = await make_task(db_session, w["plan"], "T", team=w["team"])
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, w, t, w["outsider"], "in_progress")
    assert exc.value.status_code == 403
    no_team = await make_task(db_session, w["plan"], "No team")
    with pytest.raises(HTTPException):
        await _go(db_session, w, no_team, w["member"], "in_progress")
    empty = await ensure_user_group(db_session, test_tenant.id, name="Empty")
    empty_task = await make_task(db_session, w["plan"], "Empty team", team=empty)
    with pytest.raises(HTTPException):
        await _go(db_session, w, empty_task, w["member"], "in_progress")
    await _go(db_session, w, no_team, w["rm"], "in_progress")
    await _go(db_session, w, empty_task, w["admin"], "in_progress")


@pytest.mark.asyncio
async def test_a_master_admin_impersonating_is_a_manager(db_session, world, second_tenant_factory):
    other_tenant, master = await second_tenant_factory()
    master.is_master_admin = True
    master.role = "Developer"
    master.active_tenant_id = world["tenant_id"]
    t = await make_task(db_session, world["plan"], "T")
    await _go(db_session, world, t, master, "skipped", reason="impersonated fix")
    assert t.status == "skipped"


@pytest.mark.asyncio
async def test_membership_is_tenant_qualified(db_session, world, second_tenant_factory):
    """A member row carrying ANOTHER tenant's id must not grant anything here."""
    other_tenant, _ = await second_tenant_factory()
    stranger = await ensure_user(db_session, world["tenant_id"], username="stranger", role="Developer")
    stranger.active_tenant_id = world["tenant_id"]
    from app.db.models.user_group import UserGroupMember
    db_session.add(UserGroupMember(tenant_id=other_tenant.id, group_id=world["team"].id, user_id=stranger.id))
    await db_session.flush()
    t = await make_task(db_session, world["plan"], "T", team=world["team"])
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, world, t, stranger, "in_progress")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_at_in_the_future_is_422_and_omitted_means_now(db_session, world):
    t = await make_task(db_session, world["plan"], "T", team=world["team"])
    with pytest.raises(HTTPException) as exc:
        await _go(db_session, world, t, world["member"], "in_progress", at=NOW + timedelta(minutes=1))
    assert exc.value.status_code == 422
    await _go(db_session, world, t, world["member"], "in_progress")
    assert t.actual_started_at == NOW


@pytest.mark.asyncio
async def test_back_dating_before_a_predecessor_finished_is_accepted(db_session, world):
    """C5a does not police honest back-dating (spec §4)."""
    a = await make_task(db_session, world["plan"], "A", team=world["team"], status="in_progress")
    b = await make_task(db_session, world["plan"], "B", team=world["team"])
    await link(db_session, b, a)
    await _go(db_session, world, a, world["member"], "done", at=NOW)
    await _go(db_session, world, b, world["member"], "done", at=NOW - timedelta(minutes=30))
    assert b.status == "done"


@pytest.mark.parametrize("status, preds, succs, manager, member, expected", [
    ("not_started", ["done"], [], False, True, ["in_progress", "done"]),
    ("not_started", ["in_progress"], [], False, True, []),
    ("not_started", ["in_progress"], [], True, False, ["skipped"]),
    ("not_started", [], [], True, False, ["in_progress", "done", "skipped"]),
    ("in_progress", [], [], False, True, ["done", "failed"]),
    ("failed", [], [], False, True, ["in_progress"]),
    ("failed", [], [], True, False, ["in_progress", "skipped"]),
    ("done", [], ["not_started"], True, False, ["not_started"]),
    ("done", [], ["in_progress"], True, False, []),
    ("done", [], [], False, True, []),
    ("in_progress", [], [], False, False, []),
])
def test_allowed_transitions(status, preds, succs, manager, member, expected):
    assert ex.allowed_transitions(status, preds, succs, manager=manager, team_member=member) == expected


@pytest.mark.asyncio
async def test_events_are_newest_first_and_tenant_scoped(db_session, world, second_tenant_factory):
    t = await make_task(db_session, world["plan"], "T", team=world["team"])
    await _go(db_session, world, t, world["member"], "in_progress", at=NOW - timedelta(minutes=5))
    await _go(db_session, world, t, world["member"], "done")
    rows, total = await ex.list_events(db_session, t.id, world["tenant_id"], Page(limit=50, offset=0))
    assert [r.to_status for r in rows] == ["done", "in_progress"] and total == 2
    other_tenant, _ = await second_tenant_factory()
    rows, total = await ex.list_events(db_session, t.id, other_tenant.id, Page(limit=50, offset=0))
    assert rows == [] and total == 0


@pytest.mark.asyncio
async def test_transition_ignores_an_edge_referencing_an_unloaded_task(db_session, world, monkeypatch):
    """Fix round 2: _neighbours' live_tasks and live_edges are two separate
    statements, so a task/edge committed between them can leave a live edge
    naming an id absent from by_id. Reproduced by monkeypatching live_edges to
    add a phantom edge in both directions around the task under transition.
    Before the fix this KeyErrors inside _neighbours; after, the transition
    proceeds as if the phantom edge did not exist."""
    a = await make_task(db_session, world["plan"], "A", team=world["team"], status="done")
    b = await make_task(db_session, world["plan"], "B", team=world["team"])
    UNKNOWN_ID = 999_999_999

    original = runbook_service.live_edges

    async def with_phantom_edges(db, plan_id, tenant_id):
        edges = await original(db, plan_id, tenant_id)
        return edges + [(UNKNOWN_ID, a.id), (b.id, UNKNOWN_ID)]

    monkeypatch.setattr(runbook_service, "live_edges", with_phantom_edges)

    await _go(db_session, world, b, world["member"], "in_progress")
    assert b.status == "in_progress"
