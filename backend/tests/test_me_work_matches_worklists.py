"""§9's count-equivalence guard for `GET /me/work`.

For each of the five queues: seed rows on BOTH sides of the filter, then
assert `/me/work`'s count equals that queue's own worklist endpoint's
`X-Total-Count` under the SAME filter and the same clock.

Seeding only matching rows would let a broken filter — or no filter at all —
pass; that is the mistake this file exists to rule out. Every test below
therefore also seeds at least one row that must NOT be counted (wrong owner,
wrong status, self-raised, no group membership, or already decided) so a
missing predicate fails loudly instead of passing by accident.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.contention_escalation import ContentionEscalation
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
async def test_incidents_count_matches_the_worklist(
    client, auth_headers, test_tenant, db_session
):
    for i in range(3):
        await make_incident(
            db_session, test_tenant.id, title=f"open {i}", status="open"
        )
    for i in range(2):
        await make_incident(
            db_session, test_tenant.id, title=f"closed {i}", status="closed"
        )

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    worklist = await client.get(
        "/api/v1/incidents?status=open&limit=1", headers=auth_headers
    )

    assert mine.status_code == 200
    assert mine.json()["queues"]["incidents"]["count"] == int(
        worklist.headers["X-Total-Count"]
    )
    assert mine.json()["queues"]["incidents"]["count"] == 3


@pytest.mark.asyncio
async def test_pir_actions_count_matches_and_a_due_today_action_is_not_overdue(
    client, auth_headers, test_tenant, db_session, test_user
):
    """The day-not-instant rule: `expiry_boundary` means an action due TODAY is
    not yet overdue. Asserting it here pins the shared clock as well as the
    count."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    await make_pir_action(
        db_session, test_tenant.id, owner_id=test_user.id,
        status="open", due_date=today,
    )
    await make_pir_action(
        db_session, test_tenant.id, owner_id=test_user.id,
        status="done", due_date=today,
    )

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    worklist = await client.get(
        f"/api/v1/pir-actions?owner_id={test_user.id}&status=open&limit=1",
        headers=auth_headers,
    )
    q = mine.json()["queues"]["pir_actions"]
    assert q["count"] == int(worklist.headers["X-Total-Count"]) == 1
    assert q["overdue"] == 0, "due today is not overdue"


@pytest.mark.asyncio
async def test_a_decommission_due_today_is_warned_and_still_counts(
    client, auth_headers, test_tenant, db_session, test_user
):
    """B5's rule, restated at this seam because /me/work is a second reader of
    that state machine: `decommission_state` returns WARNED, never DUE, for
    the entire calendar day a teardown is scheduled on —
    `scheduled_teardown_at >= expiry_boundary(now)` — and only flips to DUE
    once that day has fully passed.

    Spec §5 defines this queue as `state=warned|extension_requested|due` —
    `_decommissions_queue` counts all three, `warned` included, deliberately:
    B5's decommissioning design is warn-then-act, and a card that stayed
    silent for the whole notice period and only lit up on the deadline day
    would surface the work at exactly the moment it is too late to act on
    calmly. So a decommission scheduled for TODAY (WARNED) must still appear
    here, exactly like one that is genuinely DUE.

    (This test used to assert the opposite — that a WARNED row must NOT
    count — matching this queue's old, spec-incorrect filter of
    `(due, extension_requested)` only. Corrected when `warned` was added to
    the filter; see `my_work_service.py`'s `_decommissions_queue`
    docstring.)

    `GET /decommissions` (the worklist endpoint) has no membership-narrowing
    filter at all — see `app/api/v1/decommissions.py`'s
    `list_decommission_worklist`, which is deliberately tenant-wide, not
    per-member — so there is no single filtered HTTP call to assert true
    X-Total-Count equivalence against here, unlike the other four queues.
    Both axes `_decommissions_queue` filters on are still seeded on both
    sides instead: a genuinely DUE decommission AND a WARNED (due-today) one
    on `test_user`'s own operations group (both counted — proves `warned` is
    included, not just `due`), a TORN_DOWN one on that same group (must not
    count — the state filter still excludes a terminal state, not just
    membership), and a genuinely DUE decommission on a DIFFERENT group
    `test_user` does not belong to (must not count — membership excludes
    it). Two rows surviving both filters yields a total of 2.
    """
    group = await ensure_user_group(db_session, test_tenant.id, name="Ops")
    await add_group_member(db_session, group, test_user)
    other_group = await ensure_user_group(db_session, test_tenant.id, name="OtherOps")

    env = await ensure_environment(
        db_session, test_tenant.id, slot=1, operations_group_id=group.id
    )
    other_env = await ensure_environment(
        db_session, test_tenant.id, slot=2, operations_group_id=other_group.id
    )
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    # Matching: mine (my group), and the teardown day has fully passed — DUE.
    await make_decommission(
        db_session, test_tenant.id, environment_id=env.id,
        scheduled_teardown_at=yesterday,
    )
    # Matching: mine, teardown scheduled for TODAY — WARNED, not yet DUE, but
    # still counted (the whole point of this test after the spec fix).
    await make_decommission(
        db_session, test_tenant.id, environment_id=env.id,
        scheduled_teardown_at=today,
    )
    # Not matching: mine, but TORN_DOWN — terminal, needs no human. Proves the
    # state filter still excludes something, not just membership.
    torn_down = await make_decommission(
        db_session, test_tenant.id, environment_id=env.id,
        scheduled_teardown_at=yesterday,
    )
    torn_down.torn_down_at = datetime.now(timezone.utc)
    await db_session.flush()
    # Not matching: genuinely DUE, but on an environment `test_user` does not
    # operate. Proves the membership filter runs, not just the state one.
    await make_decommission(
        db_session, test_tenant.id, environment_id=other_env.id,
        scheduled_teardown_at=yesterday,
    )

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    assert mine.json()["queues"]["decommissions"]["count"] == 2


@pytest.mark.asyncio
async def test_environment_requests_count_matches_the_worklist(
    client, auth_headers, test_tenant, db_session, test_user
):
    """`?actionable=true` — "requests my team must action," as Admin.

    Seeds a matching pair (new_environment requests, which the Admin bypass in
    `actionable_clause` covers regardless of group membership) alongside two
    rows that must NOT count: one the requester raised themselves (excluded by
    `requested_by != user_id` even for an Admin) and one access request against
    an environment whose operations group `test_user` does not belong to
    (excluded because `actionable_clause`'s access branch always requires
    membership, admin or not).
    """
    other = await ensure_user(db_session, test_tenant.id, username="other-requester")

    for _ in range(2):
        await ensure_environment_request(
            db_session, test_tenant.id,
            kind="new_environment", requested_by=other.id, status="draft",
        )
    # Not actionable: self-raised.
    await ensure_environment_request(
        db_session, test_tenant.id,
        kind="new_environment", requested_by=test_user.id, status="draft",
    )
    # Not actionable: access request, but test_user is not in this
    # environment's operations group (the default `ensure_environment` has
    # none at all).
    await ensure_environment_request(
        db_session, test_tenant.id,
        kind="access", requested_by=other.id, status="draft",
    )

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    worklist = await client.get(
        "/api/v1/environment-requests?actionable=true&limit=1", headers=auth_headers
    )

    assert mine.status_code == 200
    assert mine.json()["queues"]["environment_requests"]["count"] == int(
        worklist.headers["X-Total-Count"]
    )
    assert mine.json()["queues"]["environment_requests"]["count"] == 2


@pytest.mark.asyncio
async def test_contentions_count_matches_the_worklist(
    client, auth_headers, test_tenant, db_session, test_user
):
    """`?state=open&owner_user_id=<me>`.

    `my_work_service._contentions_queue` fetches every escalation owned by
    `user` (via `worklist_query(..., owner_user_id=...)`, no `state=` filter)
    and keeps the ones with `decided_at IS NULL` in Python. That is equal to
    `?state=open` only once every seeded row's `respond_by` is in the future —
    an expired-but-undecided row would be counted by the service but excluded
    by `state=open`, breaking the equivalence — so every escalation here uses
    a future deadline; only ownership and decided-vs-not vary.
    """
    other_owner = await ensure_user(db_session, test_tenant.id, username="other-owner")
    env = await ensure_environment(db_session, test_tenant.id, slot=3)
    bookings = [
        await make_booking(
            db_session, test_tenant.id, booked_by=test_user.id, environment=env
        )
        for _ in range(8)
    ]
    future = datetime.now(timezone.utc) + timedelta(days=10)

    def _pair(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    # Matching: mine, undecided, not expired.
    for i in range(2):
        lo, hi = _pair(bookings[i * 2].id, bookings[i * 2 + 1].id)
        db_session.add(ContentionEscalation(
            tenant_id=test_tenant.id, booking_id=lo, other_booking_id=hi,
            escalated_by=test_user.id, owner_user_id=test_user.id,
            respond_by=future,
        ))
    # Not mine: someone else owns this one.
    lo, hi = _pair(bookings[4].id, bookings[5].id)
    db_session.add(ContentionEscalation(
        tenant_id=test_tenant.id, booking_id=lo, other_booking_id=hi,
        escalated_by=test_user.id, owner_user_id=other_owner.id,
        respond_by=future,
    ))
    # Mine, but already decided — must not count on either side.
    lo, hi = _pair(bookings[6].id, bookings[7].id)
    db_session.add(ContentionEscalation(
        tenant_id=test_tenant.id, booking_id=lo, other_booking_id=hi,
        escalated_by=test_user.id, owner_user_id=test_user.id,
        respond_by=future, decided_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    worklist = await client.get(
        f"/api/v1/contention-escalations?state=open&owner_user_id={test_user.id}&limit=1",
        headers=auth_headers,
    )

    assert mine.status_code == 200
    assert mine.json()["queues"]["contentions"]["count"] == int(
        worklist.headers["X-Total-Count"]
    )
    assert mine.json()["queues"]["contentions"]["count"] == 2
