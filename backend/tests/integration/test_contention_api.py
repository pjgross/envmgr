"""A4 task 4: the verdict and the escalation on the API surface.

A4 ADVISES; IT NEVER ACTS. `test_a_contention_changes_no_booking_behaviour` at
the foot of this file is the guard the whole sub-project rests on — A4's
counterpart to A1's `test_an_agreement_changes_no_booking_behaviour`, written
for the same reason: to catch a LATER sub-project quietly making this act.

THE TWO PERMISSION GATES LIVE HERE AND NOWHERE ELSE. `create_escalation` and
`record_decision` carry no authorization of their own (task 3), so every rule
about who may ask and who may answer is asserted through HTTP:

  - escalating  — the owner or a delegate of EITHER contending booking, or an
    Admin. `conflict_service._authorize_ack` is the precedent, widened to the
    pair because a contention belongs to both sides of it.
  - deciding    — the NAMED OWNER, or an Admin. The Admin path is not a
    convenience: A4 ships no edit and no withdraw path, so a wrong owner or a
    short deadline can only be resolved by someone else being able to answer.
    B3b established that gating solely on one person leaves a workflow
    permanently stuck the day that person leaves.

CROSS-TENANT IS 404, NEVER 403 — a 403 confirms the row exists.

THE VERDICT IS ASSERTED AGAINST `verdict_for_pair`, never against a literal.
`ConflictItem.contention` is a REQUIRED field, which guards only that a site
ANSWERS; a site can still satisfy it with a constant, and hardcoding one is
exactly the mutation `has_unacknowledged_conflicts` survived at every
construction site since it shipped. So the endpoint's answer is compared with
the service's, over a population holding all four outcomes at once.

`X-Total-Count` is asserted on every filtered read of the worklist. It is the
only evidence available from outside that the state filter ran in SQL rather
than over the page: a Python-side filter would window first and report a total
for the unfiltered set.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.pagination import TOTAL_COUNT_HEADER
from app.core.security import get_password_hash
from app.db.models.booking import Booking
from app.db.models.user import User
from app.services import contention_service
from app.services.contention_service import (
    OUTCOME_EQUAL_RANK,
    OUTCOME_NO_PROJECT,
    OUTCOME_RANKED,
    OUTCOME_UNRANKED,
    STATE_ANSWERED,
    STATE_EXPIRED,
    STATE_OPEN,
)
from tests.factories import (
    ensure_booking_type,
    ensure_environment,
    ensure_project,
    make_booking,
)

START = datetime(2026, 3, 1, tzinfo=timezone.utc)
END = datetime(2026, 3, 5, tzinfo=timezone.utc)
FUTURE = datetime.now(timezone.utc) + timedelta(days=7)
PAST = datetime.now(timezone.utc) - timedelta(days=7)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


async def _login(client, tenant, username: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "tenant_slug": tenant.slug},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _user(db, tenant, username: str, role: str = "Developer") -> User:
    """A real, loggable-in user. `role` matters: the Admin fallback on both
    gates keys on it, so a test asserting a 403 must use a non-Admin.

    `@test.com`, not `@test.local`: the login response is an `EmailStr`, and
    `.local` is a reserved name that Pydantic refuses — the login 500s rather
    than failing the assertion under test.
    """
    user = User(
        tenant_id=tenant.id,
        username=username,
        email=f"{username}@test.com",
        password_hash=get_password_hash("password123"),
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _pair(db, tenant, booked_by: int, *, slot=1, projects=(None, None)):
    """Two bookings that really are in conflict: one environment, overlapping
    windows, neither terminal.

    A real clash, not a fabricated one — the escalate route composes
    `conflict_service.conflicts_with`, so a pair built to look conflicting
    without being so would fail for the wrong reason.
    """
    env = await ensure_environment(db, tenant.id, slot=slot)
    a = await make_booking(
        db, tenant.id, booked_by=booked_by, environment=env,
        project_id=projects[0], start=START, end=END,
    )
    b = await make_booking(
        db, tenant.id, booked_by=booked_by, environment=env,
        project_id=projects[1], start=START + timedelta(days=1),
        end=END + timedelta(days=1),
    )
    return a, b


async def _request_of(db, booking):
    """The parent BookingRequest — where `booked_by` and `delegate_user_ids`,
    the two things the escalate gate reads, actually live."""
    from app.db.models.booking_request import BookingRequest

    return await db.get(BookingRequest, booking.booking_request_id)


async def _escalate(client, headers, a_id: int, b_id: int, *, owner_user_id: int,
                    respond_by: datetime = FUTURE):
    return await client.post(
        f"/api/v1/bookings/{a_id}/contentions/{b_id}/escalate",
        json={"owner_user_id": owner_user_id, "respond_by": respond_by.isoformat()},
        headers=headers,
    )


async def _conflicts(client, headers, booking_id: int):
    resp = await client.get(
        f"/api/v1/bookings/{booking_id}/conflicts", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _total(resp) -> int:
    return int(resp.headers[TOTAL_COUNT_HEADER])


def _ids(resp) -> set[int]:
    return {row["id"] for row in resp.json()}


# ---------------------------------------------------------------------------
# The verdict, on the conflicts endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_conflicts_endpoint_carries_the_verdict_for_the_pair(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """Every conflict item carries a `contention`, and it says what
    `verdict_for_pair` says about the SAME pair — asserted against each other,
    never against a literal."""
    high = await ensure_project(db_session, test_tenant.id, name="High")
    low = await ensure_project(db_session, test_tenant.id, name="Low")
    high.priority_rank = 1
    low.priority_rank = 5
    await db_session.flush()
    mine, theirs = await _pair(
        db_session, test_tenant, test_user.id, projects=(high.id, low.id)
    )

    items = await _conflicts(client, auth_headers, mine.id)

    assert len(items) == 1
    contention = items[0]["contention"]
    expected = await contention_service.verdict_for_pair(
        db_session, mine.id, theirs.id, test_tenant.id
    )
    assert contention["outcome"] == expected.outcome == OUTCOME_RANKED
    assert contention["winner_booking_id"] == expected.winner_booking_id == mine.id
    assert contention["reason"] == expected.reason
    assert contention["escalation"] is None


@pytest.mark.asyncio
async def test_the_four_outcomes_read_through_the_endpoint_over_one_mixed_population(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """FOUR PAIRS, FOUR OUTCOMES, ONE PAGE — and each compared with
    `verdict_for_pair`.

    This is the test that catches a `contention` hardcoded to a constant at the
    construction site. A required field guards only that the site ANSWERS; the
    natural way to silence it is a literal, which is behaviour-preserving to the
    type system and wrong to every reader. One outcome per row means no constant
    can satisfy all four, and the batch call has to key on the right pair.
    """
    ranked = await ensure_project(db_session, test_tenant.id, name="Ranked 1")
    lower = await ensure_project(db_session, test_tenant.id, name="Ranked 5")
    unranked = await ensure_project(db_session, test_tenant.id, name="No rank")
    equal = await ensure_project(db_session, test_tenant.id, name="Also ranked 1")
    ranked.priority_rank = 1
    lower.priority_rank = 5
    equal.priority_rank = 1
    await db_session.flush()

    env = await ensure_environment(db_session, test_tenant.id, slot=1)

    async def booking(project_id, offset):
        return await make_booking(
            db_session, test_tenant.id, booked_by=test_user.id, environment=env,
            project_id=project_id,
            start=START + timedelta(hours=offset),
            end=END + timedelta(hours=offset),
        )

    subject = await booking(ranked.id, 0)
    beaten = await booking(lower.id, 1)
    projectless = await booking(None, 2)
    unrankable = await booking(unranked.id, 3)
    tied = await booking(equal.id, 4)

    items = await _conflicts(client, auth_headers, subject.id)
    by_id = {item["other_booking"]["id"]: item["contention"] for item in items}

    assert set(by_id) == {beaten.id, projectless.id, unrankable.id, tied.id}
    assert by_id[beaten.id]["outcome"] == OUTCOME_RANKED
    assert by_id[beaten.id]["winner_booking_id"] == subject.id
    assert by_id[projectless.id]["outcome"] == OUTCOME_NO_PROJECT
    assert by_id[unrankable.id]["outcome"] == OUTCOME_UNRANKED
    assert by_id[tied.id]["outcome"] == OUTCOME_EQUAL_RANK
    # …and every one of them agrees with the service asked about the same pair.
    for other_id, contention in by_id.items():
        expected = await contention_service.verdict_for_pair(
            db_session, subject.id, other_id, test_tenant.id
        )
        assert contention["outcome"] == expected.outcome, other_id
        assert contention["winner_booking_id"] == expected.winner_booking_id, other_id
        assert contention["reason"] == expected.reason, other_id
    # Three of the four carry no winner, each with its own reason: a page that
    # reported one reason for all of them would still pass the outcomes above.
    assert len({c["reason"] for c in by_id.values()}) == 4


@pytest.mark.asyncio
async def test_the_conflicts_endpoint_carries_the_escalation_once_one_is_raised(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """The escalation rides on the verdict, so the conflicts drawer can say "a
    decision has been asked for" instead of offering to ask again."""
    mine, theirs = await _pair(db_session, test_tenant, test_user.id)
    created = await _escalate(
        client, auth_headers, mine.id, theirs.id, owner_user_id=test_user.id
    )
    assert created.status_code == 201, created.text

    items = await _conflicts(client, auth_headers, mine.id)

    escalation = items[0]["contention"]["escalation"]
    assert escalation is not None
    assert escalation["id"] == created.json()["id"]
    assert escalation["state"] == STATE_OPEN
    assert escalation["bookings_live"] is True
    assert escalation["owner_user_id"] == test_user.id
    assert escalation["owner_username"] == test_user.username


# ---------------------------------------------------------------------------
# Escalating.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalating_returns_201_and_the_record(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    a, b = await _pair(db_session, test_tenant, test_user.id)

    resp = await _escalate(client, auth_headers, a.id, b.id, owner_user_id=test_user.id)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Stored normalised, whichever way round the caller asked.
    assert (body["booking_id"], body["other_booking_id"]) == (
        min(a.id, b.id), max(a.id, b.id),
    )
    assert body["owner_user_id"] == test_user.id
    assert body["owner_username"] == test_user.username
    assert body["state"] == STATE_OPEN
    assert body["bookings_live"] is True
    assert body["decided_at"] is None
    assert body["decision_yields_booking_id"] is None


@pytest.mark.asyncio
async def test_escalating_twice_returns_the_same_record_with_200(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """201 the first time, 200 the second — and the SAME record, asked the other
    way round. A UI that re-posts on a double click must not create a second
    contention, nor be told its own escalation is an error."""
    a, b = await _pair(db_session, test_tenant, test_user.id)
    other_owner = await _user(db_session, test_tenant, "second-owner")

    first = await _escalate(
        client, auth_headers, a.id, b.id, owner_user_id=test_user.id
    )
    again = await _escalate(
        client, auth_headers, b.id, a.id, owner_user_id=other_owner.id,
        respond_by=FUTURE + timedelta(days=30),
    )

    assert first.status_code == 201, first.text
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    # Unchanged: re-asking never reassigns the owner or restarts the clock.
    assert again.json()["owner_user_id"] == test_user.id


@pytest.mark.asyncio
async def test_escalating_a_pair_that_is_not_in_conflict_is_400_naming_why(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    env = await ensure_environment(db_session, test_tenant.id)
    early = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=START, end=END,
    )
    late = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        start=END + timedelta(days=1), end=END + timedelta(days=5),
    )

    resp = await _escalate(
        client, auth_headers, early.id, late.id, owner_user_id=test_user.id
    )

    assert resp.status_code == 400, resp.text
    assert "not in conflict" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_escalating_as_neither_owner_delegate_nor_admin_is_403(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """The gate the API owns outright — `create_escalation` carries none.

    A contention names someone else as the decider and starts a clock against
    them; a bystander must not be able to do that to two bookings they have no
    part in.
    """
    a, b = await _pair(db_session, test_tenant, test_user.id)
    stranger = await _user(db_session, test_tenant, "stranger")
    await db_session.commit()
    headers = await _login(client, test_tenant, "stranger", "password123")

    resp = await _escalate(client, headers, a.id, b.id, owner_user_id=test_user.id)

    assert resp.status_code == 403, resp.text
    # WHICH 403: a status alone would also be satisfied by some unrelated gate
    # refusing this caller before the escalate gate was ever consulted.
    assert "escalate this contention" in resp.json()["detail"]
    listed = await client.get("/api/v1/contention-escalations", headers=auth_headers)
    assert listed.json() == [], "a refused escalation must record nothing"
    assert stranger.id != test_user.id


@pytest.mark.asyncio
async def test_a_delegate_of_either_booking_may_escalate(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """BOTH SIDES. A contention belongs to both bookings, so the gate is asked
    of the pair, not of the subject — a rule written against the first id only
    would refuse whichever party happened to open the other booking's drawer.
    """
    a, b = await _pair(db_session, test_tenant, test_user.id, slot=1)
    c, d = await _pair(db_session, test_tenant, test_user.id, slot=2)
    first_delegate = await _user(db_session, test_tenant, "delegate-of-first")
    second_delegate = await _user(db_session, test_tenant, "delegate-of-second")

    (await _request_of(db_session, a)).delegate_user_ids = [first_delegate.id]
    (await _request_of(db_session, d)).delegate_user_ids = [second_delegate.id]
    await db_session.commit()

    for username, subject, other in (
        ("delegate-of-first", a, b),
        # The delegate is on the SECOND booking named in the URL.
        ("delegate-of-second", c, d),
    ):
        headers = await _login(client, test_tenant, username, "password123")
        resp = await _escalate(
            client, headers, subject.id, other.id, owner_user_id=test_user.id
        )
        assert resp.status_code == 201, (username, resp.text)


@pytest.mark.asyncio
async def test_an_admin_who_owns_neither_booking_may_escalate(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """The Admin fallback on the escalate gate. Both bookings belong to someone
    else entirely, and the admin is neither owner nor delegate of either."""
    booker = await _user(db_session, test_tenant, "booker")
    a, b = await _pair(db_session, test_tenant, booker.id)

    resp = await _escalate(client, auth_headers, a.id, b.id, owner_user_id=booker.id)

    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_escalating_another_tenants_bookings_is_404_not_403(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    second_tenant_factory,
):
    """404, NEVER 403 — a 403 confirms the bookings exist.

    A 404 is also what an unrouted URL answers, so the same call is made first
    against OUR OWN pair: without that, this test passes against an application
    that has no escalate route at all.
    """
    other_tenant, other_admin = await second_tenant_factory()
    await ensure_booking_type(db_session, other_tenant.id)
    ours_a, ours_b = await _pair(db_session, test_tenant, test_user.id, slot=1)
    theirs_a, theirs_b = await _pair(db_session, other_tenant, other_admin.id, slot=2)

    routed = await _escalate(
        client, auth_headers, ours_a.id, ours_b.id, owner_user_id=test_user.id
    )
    assert routed.status_code == 201, routed.text

    resp = await _escalate(
        client, auth_headers, theirs_a.id, theirs_b.id, owner_user_id=other_admin.id
    )

    assert resp.status_code == 404, resp.text
    # …and WHICH 404: an unrouted URL says "Not Found".
    assert resp.json()["detail"] == "Booking not found"


@pytest.mark.asyncio
async def test_a_bystander_escalating_another_tenants_bookings_gets_404_not_403(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    second_tenant_factory,
):
    """404, NEVER 403 — for a caller the Admin fallback does not carry.

    The gate's own refusal reads `BookingRequest` without a tenant filter, so
    with the visibility check removed a bystander naming two of another tenant's
    bookings is told "you are not the owner of these" — which confirms they
    exist. Every other cross-tenant test here is made as an Admin, and an Admin
    is answered 404 by the write path whatever this gate does; only a
    non-privileged caller can tell the two apart.

    THE DETAIL IS ASSERTED, NOT JUST THE STATUS. An unrouted URL answers 404
    too, and this test cannot make a successful call through the route first
    (its whole point is a caller with no authority over any pair). Measured, not
    inferred: with the escalate POST's path renamed, 23 of this file's tests
    fail and the status-only form of this one PASSES — and it is the ONLY test
    that fails when `_assert_bookings_visible` is removed from
    `assert_may_escalate`, so its vacuity would leave that guard unguarded the
    day the route moves. `_assert_bookings_visible` raises "Booking not found";
    FastAPI's unrouted 404 says "Not Found", so the assertion below also pins
    WHICH 404 was raised.
    """
    other_tenant, other_admin = await second_tenant_factory()
    await ensure_booking_type(db_session, other_tenant.id)
    theirs_a, theirs_b = await _pair(db_session, other_tenant, other_admin.id)
    await _user(db_session, test_tenant, "outsider")
    await db_session.commit()
    headers = await _login(client, test_tenant, "outsider", "password123")

    resp = await _escalate(
        client, headers, theirs_a.id, theirs_b.id, owner_user_id=other_admin.id
    )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Booking not found", (
        "a bare 404 assertion is satisfied by an unrouted URL — this pins the "
        "404 the visibility check raises"
    )


@pytest.mark.asyncio
async def test_a_misspelled_key_on_the_escalate_body_is_a_422(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """`extra="forbid"`: a misspelled key must be refused, not silently dropped.
    Dropped, the caller believes they set a deadline that was never stored."""
    a, b = await _pair(db_session, test_tenant, test_user.id)

    resp = await client.post(
        f"/api/v1/bookings/{a.id}/contentions/{b.id}/escalate",
        json={
            "owner_user_id": test_user.id,
            "respond_by": FUTURE.isoformat(),
            "respondby": PAST.isoformat(),
        },
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Deciding.
# ---------------------------------------------------------------------------


async def _escalation_owned_by(client, headers, db, tenant, booker_id, owner_id, *, slot=1):
    a, b = await _pair(db, tenant, booker_id, slot=slot)
    created = await _escalate(client, headers, a.id, b.id, owner_user_id=owner_id)
    assert created.status_code == 201, created.text
    return a, b, created.json()


@pytest.mark.asyncio
async def test_the_named_owner_may_record_the_decision(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    owner = await _user(db_session, test_tenant, "named-owner")
    a, b, escalation = await _escalation_owned_by(
        client, auth_headers, db_session, test_tenant, test_user.id, owner.id
    )
    await db_session.commit()
    headers = await _login(client, test_tenant, "named-owner", "password123")

    resp = await client.put(
        f"/api/v1/contention-escalations/{escalation['id']}/decision",
        json={"yields_booking_id": b.id, "notes": "B moves to the following week"},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision_yields_booking_id"] == b.id
    assert body["decision_notes"] == "B moves to the following week"
    assert body["decided_by"] == owner.id
    assert body["decided_by_username"] == owner.username
    assert body["state"] == STATE_ANSWERED


@pytest.mark.asyncio
async def test_an_admin_who_is_not_the_owner_may_record_the_decision(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """THE B3b LESSON, made a rule.

    A4 ships no edit and no withdraw path, so an escalation naming the wrong
    owner — or one whose owner has left — has exactly one way out: someone with
    authority answers it. Gating solely on the named person leaves the
    contention permanently unanswerable, which is how B3b produced two
    unrecoverable states.
    """
    owner = await _user(db_session, test_tenant, "absent-owner")
    a, b, escalation = await _escalation_owned_by(
        client, auth_headers, db_session, test_tenant, test_user.id, owner.id
    )

    # test_user is an Admin, and is NOT the named owner.
    resp = await client.put(
        f"/api/v1/contention-escalations/{escalation['id']}/decision",
        json={"yields_booking_id": a.id},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["decided_by"] == test_user.id
    assert escalation["owner_user_id"] == owner.id


@pytest.mark.asyncio
async def test_anybody_else_may_not_record_the_decision(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """403 — and the escalation is untouched, so it does not read as answered."""
    owner = await _user(db_session, test_tenant, "the-owner")
    stranger = await _user(db_session, test_tenant, "not-the-owner")
    a, b, escalation = await _escalation_owned_by(
        client, auth_headers, db_session, test_tenant, test_user.id, owner.id
    )
    await db_session.commit()
    headers = await _login(client, test_tenant, "not-the-owner", "password123")

    resp = await client.put(
        f"/api/v1/contention-escalations/{escalation['id']}/decision",
        json={"yields_booking_id": a.id},
        headers=headers,
    )

    assert resp.status_code == 403, resp.text
    # WHICH 403 — see the sibling escalate test for why the status alone is weak.
    assert "decide this contention" in resp.json()["detail"]
    assert stranger.id != owner.id
    listed = await client.get("/api/v1/contention-escalations", headers=auth_headers)
    assert listed.json()[0]["state"] == STATE_OPEN
    assert listed.json()[0]["decided_at"] is None


@pytest.mark.asyncio
async def test_deciding_another_tenants_escalation_is_404_not_403(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    second_tenant_factory,
):
    """404, never 403. The caller is an Admin of their own tenant, so the Admin
    fallback must not be reached before the tenant filter.

    A 404 is also what an unrouted URL answers, so one of our own escalations is
    decided first: without that, this test passes against an application that
    has no decision route at all.
    """
    other_tenant, other_admin = await second_tenant_factory()
    ours_a, _ours_b, ours = await _escalation_owned_by(
        client, auth_headers, db_session, test_tenant, test_user.id, test_user.id
    )
    routed = await client.put(
        f"/api/v1/contention-escalations/{ours['id']}/decision",
        json={"yields_booking_id": ours_a.id},
        headers=auth_headers,
    )
    assert routed.status_code == 200, routed.text

    await ensure_booking_type(db_session, other_tenant.id)
    theirs_a, theirs_b = await _pair(db_session, other_tenant, other_admin.id, slot=2)
    theirs = await contention_service.create_escalation(
        db_session,
        booking_id=theirs_a.id,
        other_booking_id=theirs_b.id,
        owner_user_id=other_admin.id,
        respond_by=FUTURE,
        current_user=other_admin,
        tenant_id=other_tenant.id,
    )
    await db_session.flush()

    resp = await client.put(
        f"/api/v1/contention-escalations/{theirs.id}/decision",
        json={"yields_booking_id": theirs_a.id},
        headers=auth_headers,
    )

    assert resp.status_code == 404, resp.text
    # …and WHICH 404: an unrouted URL says "Not Found".
    assert resp.json()["detail"] == "Escalation not found"
    db_session.expire(theirs)
    untouched = await contention_service.get_escalation(
        db_session, theirs_a.id, theirs_b.id, other_tenant.id
    )
    assert untouched.decided_at is None


@pytest.mark.asyncio
async def test_a_misspelled_key_on_the_decision_body_is_a_422(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    a, b, escalation = await _escalation_owned_by(
        client, auth_headers, db_session, test_tenant, test_user.id, test_user.id
    )

    resp = await client.put(
        f"/api/v1/contention-escalations/{escalation['id']}/decision",
        json={"yields_booking_id": a.id, "note": "singular"},
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# The worklist.
# ---------------------------------------------------------------------------


class _Worklist:
    def __init__(self, open_, answered, expired):
        self.open = open_
        self.answered = answered
        self.expired = expired

    @property
    def every(self) -> set[int]:
        return {self.open, self.answered, self.expired}


async def _worklist_population(client, headers, db, tenant, user) -> _Worklist:
    """One escalation in each of the three states, built through the API.

    The states are COMPUTED, so `expired` is produced by a deadline in the past
    and nothing else — no sweep, no status column, no job.
    """
    a, b = await _pair(db, tenant, user.id, slot=1)
    c, d = await _pair(db, tenant, user.id, slot=2)
    e, f = await _pair(db, tenant, user.id, slot=3)

    still_open = await _escalate(client, headers, a.id, b.id, owner_user_id=user.id)
    to_answer = await _escalate(client, headers, c.id, d.id, owner_user_id=user.id)
    expired = await _escalate(
        client, headers, e.id, f.id, owner_user_id=user.id, respond_by=PAST
    )
    for resp in (still_open, to_answer, expired):
        assert resp.status_code == 201, resp.text

    answered = await client.put(
        f"/api/v1/contention-escalations/{to_answer.json()['id']}/decision",
        json={"yields_booking_id": d.id, "notes": "d gives way"},
        headers=headers,
    )
    assert answered.status_code == 200, answered.text

    return _Worklist(
        open_=still_open.json()["id"],
        answered=to_answer.json()["id"],
        expired=expired.json()["id"],
    )


@pytest.mark.asyncio
async def test_the_worklist_returns_every_escalation_when_no_state_is_asked_for(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """Omission is the "no selection" sentinel, and it must not be spelled
    `all`: the frontend's buildParams drops a filter whose value is its own
    sentinel, so a vocabulary containing `all` builds byte-identical params for
    two different states and the grid never refetches."""
    pop = await _worklist_population(
        client, auth_headers, db_session, test_tenant, test_user
    )

    resp = await client.get("/api/v1/contention-escalations", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert _ids(resp) == pop.every
    assert _total(resp) == 3

    refused = await client.get(
        "/api/v1/contention-escalations?state=all", headers=auth_headers
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_filtering_by_state_returns_the_right_rows_and_the_total_agrees(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """All three states, each asked for by name, with `X-Total-Count` asserted
    every time — the only evidence from outside that the predicate ran in SQL
    and not over the page."""
    pop = await _worklist_population(
        client, auth_headers, db_session, test_tenant, test_user
    )

    for state, expected in (
        (STATE_OPEN, pop.open),
        (STATE_ANSWERED, pop.answered),
        (STATE_EXPIRED, pop.expired),
    ):
        resp = await client.get(
            f"/api/v1/contention-escalations?state={state}", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert _ids(resp) == {expected}, state
        assert _total(resp) == 1, state
        # The row's own computed state agrees with the filter that selected it —
        # two mechanisms answering one question, asserted against each other.
        assert resp.json()[0]["state"] == state


@pytest.mark.asyncio
async def test_the_state_filter_narrows_the_page_in_sql_not_after_it(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """`limit=1` over a filtered set must return one row OF THAT STATE and a
    total of one. A Python-side filter would window the unfiltered set first, so
    the row returned could be any of the three and the total would be three."""
    pop = await _worklist_population(
        client, auth_headers, db_session, test_tenant, test_user
    )

    resp = await client.get(
        "/api/v1/contention-escalations?state=open&limit=1", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1
    assert _ids(resp) == {pop.open}
    assert _total(resp) == 1


@pytest.mark.asyncio
async def test_the_worklist_is_bounded(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """`limit` windows the page while the total describes the whole set."""
    pop = await _worklist_population(
        client, auth_headers, db_session, test_tenant, test_user
    )

    resp = await client.get(
        "/api/v1/contention-escalations?limit=2", headers=auth_headers
    )

    assert len(resp.json()) == 2
    assert _ids(resp) < pop.every
    assert _total(resp) == 3


@pytest.mark.asyncio
async def test_the_worklist_refuses_a_sort_field_outside_its_whitelist(
    client: AsyncClient, auth_headers: dict
):
    """422, not a silent fallback: a client shown a different order than it
    asked for, with no error, renders it as though it were the order requested.
    """
    resp = await client.get(
        "/api/v1/contention-escalations?sort_by=owner_user_id", headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_the_worklist_actually_orders_by_the_field_it_was_asked_for(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """RENDERED ROW ORDER, over data whose id order is neither sorted order.

    The 422 above proves only that `sort_by` is VALIDATED. Measured, not
    inferred: replacing `apply_sort(query, sort)` with `apply_sort(query, None)`
    in `list_escalations` — accept the parameter, refuse garbage, then ignore it
    — left all 27 of this file's other tests green. The worklist grid would
    render a sorted header over rows in `id` order and nothing would object.
    This is docs/pagination.md's rule in its own words: assert the order the user
    sees, never the SQL that was emitted.

    The three below are created so that `id` order matches NEITHER `respond_by`
    ascending NOR descending, so a query that dropped the sort and fell through
    to the `id` tiebreaker fails both assertions rather than half of them.
    """
    a, b = await _pair(db_session, test_tenant, test_user.id, slot=1)
    c, d = await _pair(db_session, test_tenant, test_user.id, slot=2)
    e, f = await _pair(db_session, test_tenant, test_user.id, slot=3)

    # Created FIRST, due LAST.
    latest = await _escalate(
        client, auth_headers, a.id, b.id, owner_user_id=test_user.id,
        respond_by=FUTURE + timedelta(days=20),
    )
    soonest = await _escalate(
        client, auth_headers, c.id, d.id, owner_user_id=test_user.id,
        respond_by=FUTURE + timedelta(days=5),
    )
    middling = await _escalate(
        client, auth_headers, e.id, f.id, owner_user_id=test_user.id,
        respond_by=FUTURE + timedelta(days=10),
    )
    for resp in (latest, soonest, middling):
        assert resp.status_code == 201, resp.text
    creation_order = [r.json()["id"] for r in (latest, soonest, middling)]
    assert creation_order == sorted(creation_order), (
        "the premise of this test is that id order differs from respond_by order"
    )

    async def _order(query: str) -> list[int]:
        resp = await client.get(
            f"/api/v1/contention-escalations?{query}", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        return [row["id"] for row in resp.json()]

    assert await _order("sort_by=respond_by&sort_dir=asc") == [
        soonest.json()["id"], middling.json()["id"], latest.json()["id"],
    ]
    # `sort_dir=desc` is asserted too: an implementation that ordered by the
    # right column and ignored the direction would pass the ascending case alone.
    assert await _order("sort_by=respond_by&sort_dir=desc") == [
        latest.json()["id"], middling.json()["id"], soonest.json()["id"],
    ]

    # `decided_at` is null on every open row, which is the NULL pinning
    # `apply_sort` does explicitly — SQLite sorts NULL first on ASC and
    # PostgreSQL last, so an unpinned ORDER BY here returns a different page per
    # engine. Answered rows first, the two open ones after in id order.
    answered = await client.put(
        f"/api/v1/contention-escalations/{middling.json()['id']}/decision",
        json={"yields_booking_id": f.id},
        headers=auth_headers,
    )
    assert answered.status_code == 200, answered.text
    assert await _order("sort_by=decided_at&sort_dir=asc") == [
        middling.json()["id"], latest.json()["id"], soonest.json()["id"],
    ]


@pytest.mark.asyncio
async def test_another_tenants_escalations_never_appear_in_our_worklist(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    second_tenant_factory,
):
    """Assume every tenant filter is unguarded until a named test fails without
    it."""
    other_tenant, other_admin = await second_tenant_factory()
    await ensure_booking_type(db_session, other_tenant.id)
    theirs_a, theirs_b = await _pair(db_session, other_tenant, other_admin.id)
    theirs = await contention_service.create_escalation(
        db_session,
        booking_id=theirs_a.id,
        other_booking_id=theirs_b.id,
        owner_user_id=other_admin.id,
        respond_by=FUTURE,
        current_user=other_admin,
        tenant_id=other_tenant.id,
    )
    await db_session.flush()
    pop = await _worklist_population(
        client, auth_headers, db_session, test_tenant, test_user
    )

    resp = await client.get("/api/v1/contention-escalations", headers=auth_headers)

    assert _ids(resp) == pop.every
    assert theirs.id not in _ids(resp)
    assert _total(resp) == 3


@pytest.mark.asyncio
async def test_an_escalation_whose_bookings_have_moved_on_keeps_its_record(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """DELIBERATE: the record survives its bookings, and only its liveness
    changes.

    An escalation is the trail of a decision that was asked for, which is the
    only reason to store it at all — a record that vanished when a booking
    closed would erase the audit A4 exists to create. `bookings_live` is
    COMPUTED from the two bookings' `deleted_at` and terminal status, never
    stored, so it needs no sweep to become false.
    """
    a, b = await _pair(db_session, test_tenant, test_user.id)
    created = await _escalate(
        client, auth_headers, a.id, b.id, owner_user_id=test_user.id
    )
    assert created.status_code == 201, created.text
    assert created.json()["bookings_live"] is True

    b.status = "closed"
    await db_session.flush()

    listed = await client.get("/api/v1/contention-escalations", headers=auth_headers)
    assert _ids(listed) == {created.json()["id"]}, "the record must not vanish"
    assert listed.json()[0]["bookings_live"] is False
    assert _total(listed) == 1

    # And it still reads back through the decision route, which is the whole
    # point: a contention that has gone away may still need answering on paper.
    decided = await client.put(
        f"/api/v1/contention-escalations/{created.json()['id']}/decision",
        json={"yields_booking_id": b.id, "notes": "closed itself, for the record"},
        headers=auth_headers,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["bookings_live"] is False
    assert decided.json()["state"] == STATE_ANSWERED


@pytest.mark.asyncio
async def test_a_soft_deleted_booking_makes_the_pair_read_as_no_longer_live(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """The other half of `bookings_live` — soft deletion, not a terminal status.
    Both are read by the same batch call, and a route that skipped it entirely
    would report every dead contention as live."""
    a, b = await _pair(db_session, test_tenant, test_user.id)
    created = await _escalate(
        client, auth_headers, a.id, b.id, owner_user_id=test_user.id
    )
    assert created.status_code == 201, created.text

    a.deleted_at = datetime.now(timezone.utc)
    await db_session.flush()

    listed = await client.get("/api/v1/contention-escalations", headers=auth_headers)
    assert listed.json()[0]["bookings_live"] is False


@pytest.mark.asyncio
async def test_the_deciders_name_resolves_from_outside_the_escalations_tenant(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    second_tenant_factory,
):
    """THE TRAP IN THE USERNAME FIELDS: the join must NOT be tenant-qualified.

    Under master-admin impersonation `current_user.id` and
    `current_user.active_tenant_id` belong to different tenants, so
    `record_decision` legitimately writes a `decided_by` outside the
    escalation's own `tenant_id`. A `User.tenant_id == tenant_id` join renders
    that decider as nobody — the governance trail losing exactly the name it
    exists to hold, and only under impersonation, which nothing else in this
    file exercises. `agreement_gap_service.ack_author_username` carries the same
    rule and its reasoning.
    """
    other_tenant, other_admin = await second_tenant_factory()
    a, b, escalation = await _escalation_owned_by(
        client, auth_headers, db_session, test_tenant, test_user.id, test_user.id
    )
    await contention_service.record_decision(
        db_session,
        escalation["id"],
        yields_booking_id=a.id,
        notes="decided by the impersonating master admin",
        current_user=other_admin,
        tenant_id=test_tenant.id,
    )
    await db_session.flush()

    listed = await client.get("/api/v1/contention-escalations", headers=auth_headers)

    row = listed.json()[0]
    assert row["decided_by"] == other_admin.id
    assert row["decided_by_username"] == other_admin.username, (
        "the decider's name must not be resolved with a tenant-qualified join — "
        "under impersonation they legitimately sit outside the tenant"
    )
    assert other_tenant.id != test_tenant.id


# ---------------------------------------------------------------------------
# A4 ADVISES; IT NEVER ACTS.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_contention_changes_no_booking_behaviour(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
):
    """A4 ADVISES; IT NEVER ACTS.

    Detecting a contention, escalating it, and recording a decision that names
    a booking must leave both bookings byte-identical — EVERY COLUMN, not a
    chosen few (see `_stored` for why the chosen few were not enough). This is
    A4's counterpart to A1's `test_an_agreement_changes_no_booking_behaviour`,
    written for the same reason: to catch a LATER sub-project quietly making
    this act. If it fails, A4 has started acting.
    """
    a, b = await _pair(db_session, test_tenant, test_user.id)
    a_id, b_id = a.id, b.id

    async def _stored():
        """THE WHOLE ROW, read BACK FROM THE DATABASE.

        Not off the ORM objects — a transition applied through the service would
        leave the in-memory objects as the test remembers them on some paths.

        And not a hand-picked tuple of columns, which is what this guard used to
        snapshot: `(status, start_date, end_date, updated_at)`. Three of those
        four are real, but `updated_at` contributes NOTHING and must not be
        trusted as the catch-all it looks like. `Base.updated_at` is
        `onupdate=func.now()`, and this test never commits, so on PostgreSQL
        `now()` is transaction-start time and cannot change within the flow,
        while on SQLite `CURRENT_TIMESTAMP` has one-second resolution over a
        sub-second test. A mutant in which `record_decision` also SOFT-DELETES
        the yielding booking — A4 acting in the most destructive way available,
        and this codebase's standard idiom for removing a row — passed the
        four-column form on BOTH engines.

        `dict(row._mapping)` closes the whole class rather than guessing which
        column a later sub-project will reach for.
        """
        rows = (await db_session.execute(
            Booking.__table__.select().where(Booking.id.in_([a_id, b_id]))
        )).all()
        return {row.id: dict(row._mapping) for row in rows}

    before = await _stored()

    # The whole flow, through the API: see the contention, escalate it, answer
    # it — with the answer naming `b` as the booking that should give way.
    items = await _conflicts(client, auth_headers, a_id)
    assert items[0]["contention"] is not None
    created = await _escalate(
        client, auth_headers, a_id, b_id, owner_user_id=test_user.id
    )
    assert created.status_code == 201, created.text
    decided = await client.put(
        f"/api/v1/contention-escalations/{created.json()['id']}/decision",
        json={"yields_booking_id": b_id, "notes": "b gives way"},
        headers=auth_headers,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["decision_yields_booking_id"] == b_id

    # INCLUDING the booking the decision names as yielding.
    assert await _stored() == before
