"""`my_work_service.build` — the five "waiting on me" queues under one clock.

§5: a dashboard that goes blank because one worklist is unhappy is worse than
one showing four of five and saying so. Every queue calls an existing,
already-exposed service seam — see the module docstring on
`app/services/my_work_service.py` for which one.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.factories import (
    add_group_member,
    ensure_environment,
    ensure_environment_request,
    ensure_user,
    ensure_user_group,
    make_booking,
    make_decommission,
    make_incident,
    make_pir_action,
)


@pytest.mark.asyncio
async def test_one_failing_queue_does_not_fail_the_response(
    db_session, test_tenant, test_user
):
    """§5: a dashboard that goes blank because one worklist is unhappy is worse
    than one showing four of five and saying so. `failed` is NOT the same as
    an empty queue — the card must never render "nothing waiting on you" for a
    queue that could not be computed."""
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    now = datetime.now(timezone.utc)
    from app.services import my_work_service

    with patch(
        "app.services.my_work_service._incidents_queue",
        side_effect=RuntimeError("boom"),
    ):
        res = await my_work_service.build(
            db_session, tenant_id=test_tenant.id, user=user, now=now
        )

    assert set(res.queues) == {
        "environment_requests", "contentions", "decommissions",
        "pir_actions", "incidents",
    }
    assert res.queues["incidents"].failed is True
    assert res.queues["incidents"].count == 0
    assert res.queues["incidents"].items == []
    assert all(not q.failed for k, q in res.queues.items() if k != "incidents")


@pytest.mark.asyncio
async def test_every_queue_sees_the_same_instant(db_session, test_tenant, test_user):
    """One clock. Two datetime.now() calls in one response can disagree across
    midnight, and `expiry_boundary` turns that into two different answers about
    what is overdue.

    Patching `.now()` to RAISE is not enough on its own: a `datetime.now()`
    call made INSIDE a queue builder raises an `AssertionError`, which is an
    `Exception` like any other, so `build()`'s own per-queue `except
    Exception` (the failure-isolation requirement) would quietly swallow it
    into `QueueResult(failed=True)` and the response would still come back
    with the right `as_of` — the two requirements interacting to hide exactly
    the violation this test exists to catch. The second assertion closes
    that: a clock call anywhere inside a builder must surface as a failed
    queue, not a silently-passing test.
    """
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    fixed = datetime(2026, 9, 4, 23, 59, 59, tzinfo=timezone.utc)
    from app.services import my_work_service

    with patch("app.services.my_work_service.datetime") as dt:
        dt.now.side_effect = AssertionError(
            "my_work_service must take no clock of its own; `now` is passed in"
        )
        res = await my_work_service.build(
            db_session, tenant_id=test_tenant.id, user=user, now=fixed
        )
    assert res.as_of == fixed
    assert not any(q.failed for q in res.queues.values()), (
        "a queue failed while `datetime.now()` was patched to raise — some "
        "queue builder is calling its own clock instead of using `now`"
    )


@pytest.mark.asyncio
async def test_items_carry_names_not_ids(
    db_session, test_tenant, test_user
):
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    await make_incident(db_session, test_tenant.id, title="Payments outage", status="open")
    now = datetime.now(timezone.utc)
    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=user, now=now
    )
    titles = [i.title for i in res.queues["incidents"].items]
    assert "Payments outage" in titles
    assert not any(t.startswith("#") for t in titles)


@pytest.mark.asyncio
async def test_each_queue_returns_at_most_five_items_but_counts_them_all(
    db_session, test_tenant, test_user
):
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    for i in range(8):
        await make_incident(db_session, test_tenant.id, title=f"Incident {i}", status="open")
    now = datetime.now(timezone.utc)
    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=user, now=now
    )
    assert res.queues["incidents"].count == 8
    assert len(res.queues["incidents"].items) == 5


# ---------------------------------------------------------------------------
# The other four queues, one test each — not in the brief verbatim, but
# `make_pir_action` and the decommission/contention/request seams exist
# precisely so these can be checked rather than assumed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_environment_requests_queue_uses_the_actionable_seam(
    db_session, test_tenant, test_user
):
    """Only a request my team must action shows up — never one I raised
    myself, and never one no team of mine can act on. Mirrors
    `environment_request_service.actionable_clause`'s own contract exactly."""
    me = await ensure_user(db_session, test_tenant.id, username='requests-me')
    group = await ensure_user_group(db_session, test_tenant.id, name='Ops')
    await add_group_member(db_session, group, me)
    env = await ensure_environment(
        db_session, test_tenant.id, slot=1, operations_group_id=group.id
    )
    other_requester = await ensure_user(db_session, test_tenant.id, username='requester')

    actionable = await ensure_environment_request(
        db_session, test_tenant.id, kind="access", status="submitted",
        environment_id=env.id, requested_by=other_requester.id,
    )
    mine = await ensure_environment_request(
        db_session, test_tenant.id, kind="access", status="submitted",
        environment_id=env.id, requested_by=me.id,
    )

    now = datetime.now(timezone.utc)
    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=me, now=now
    )
    ids = {i.id for i in res.queues["environment_requests"].items}
    assert actionable.id in ids
    assert mine.id not in ids


@pytest.mark.asyncio
async def test_contentions_queue_is_my_undecided_escalations(
    db_session, test_tenant, test_user
):
    """Only escalations naming me as owner, and only the ones I have not yet
    answered — `contention_service.worklist_query` is the seam; deciding one
    must remove it from the queue."""
    from app.db.models.contention_escalation import ContentionEscalation

    me = await ensure_user(db_session, test_tenant.id, username='contention-owner')
    escalator = await ensure_user(db_session, test_tenant.id, username='contention-raiser')
    env1 = await ensure_environment(db_session, test_tenant.id, slot=1)
    env2 = await ensure_environment(db_session, test_tenant.id, slot=2)

    now = datetime.now(timezone.utc)
    b1 = await make_booking(
        db_session, test_tenant.id, booked_by=escalator.id, environment=env1,
        start=now, end=now + timedelta(days=1),
    )
    b2 = await make_booking(
        db_session, test_tenant.id, booked_by=escalator.id, environment=env2,
        start=now, end=now + timedelta(days=1),
    )

    open_escalation = ContentionEscalation(
        tenant_id=test_tenant.id, booking_id=min(b1.id, b2.id),
        other_booking_id=max(b1.id, b2.id), escalated_by=escalator.id,
        owner_user_id=me.id, respond_by=now + timedelta(days=3),
    )
    db_session.add(open_escalation)
    await db_session.flush()

    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=me, now=now
    )
    ids = {i.id for i in res.queues["contentions"].items}
    assert open_escalation.id in ids

    open_escalation.decided_by = me.id
    open_escalation.decided_at = now
    open_escalation.decision_yields_booking_id = b1.id
    await db_session.flush()

    res2 = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=me, now=now
    )
    assert open_escalation.id not in {i.id for i in res2.queues["contentions"].items}


@pytest.mark.asyncio
async def test_decommissions_queue_is_narrowed_by_membership_for_everyone(
    db_session, test_tenant, test_user
):
    """Admins included — `environment_decommission_service.worklist_query`'s
    `member_user_id` has no bypass, and this queue must not add one."""
    admin = await ensure_user(db_session, test_tenant.id, username='decomm-admin', role="Admin")
    group = await ensure_user_group(db_session, test_tenant.id, name='Decomm Ops')
    env = await ensure_environment(
        db_session, test_tenant.id, slot=1, operations_group_id=group.id
    )
    now = datetime.now(timezone.utc)
    await make_decommission(
        db_session, test_tenant.id, environment_id=env.id,
        scheduled_teardown_at=now - timedelta(days=1),
    )

    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=admin, now=now
    )
    assert res.queues["decommissions"].count == 0, (
        "an Admin in no operations group must see an empty card, not a bypass"
    )

    member = await ensure_user(db_session, test_tenant.id, username='decomm-member')
    await add_group_member(db_session, group, member)
    res2 = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=member, now=now
    )
    assert res2.queues["decommissions"].count == 1


@pytest.mark.asyncio
async def test_pir_actions_queue_counts_overdue(db_session, test_tenant, test_user):
    """`overdue` is populated only for `pir_actions`, from the same
    `is_overdue`/`worklist_query` computation `GET /pir-actions` uses."""
    me = await ensure_user(db_session, test_tenant.id, username='pir-owner')
    now = datetime.now(timezone.utc)
    await make_pir_action(
        db_session, test_tenant.id, title="Overdue action", owner_id=me.id,
        due_date=now - timedelta(days=2), status="open",
    )
    await make_pir_action(
        db_session, test_tenant.id, title="Not due yet", owner_id=me.id,
        due_date=now + timedelta(days=5), status="open",
    )

    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=me, now=now
    )
    assert res.queues["pir_actions"].count == 2
    assert res.queues["pir_actions"].overdue == 1
    for other in ("environment_requests", "contentions", "decommissions", "incidents"):
        assert res.queues[other].overdue is None


@pytest.mark.asyncio
async def test_pir_actions_queue_excludes_closed_actions(
    db_session, test_tenant, test_user
):
    """A done/cancelled action is finished work, not something waiting on me
    — it must not inflate `count` (or ever appear in `items`), or a "waiting
    on me" card would accumulate closed work forever and never shrink."""
    me = await ensure_user(db_session, test_tenant.id, username='pir-owner-2')
    now = datetime.now(timezone.utc)
    live = await make_pir_action(
        db_session, test_tenant.id, title="Still open", owner_id=me.id,
        status="open",
    )
    done = await make_pir_action(
        db_session, test_tenant.id, title="Already done", owner_id=me.id,
        status="done",
    )
    cancelled = await make_pir_action(
        db_session, test_tenant.id, title="Cancelled", owner_id=me.id,
        status="cancelled",
    )

    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=me, now=now
    )
    assert res.queues["pir_actions"].count == 1
    ids = {i.id for i in res.queues["pir_actions"].items}
    assert live.id in ids
    assert done.id not in ids
    assert cancelled.id not in ids
