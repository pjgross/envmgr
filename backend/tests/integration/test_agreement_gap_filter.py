"""The gap on the API surface (A3, task 4).

Task 2 built the predicate and task 3 the acknowledgement; this is where A3
becomes visible: the gap rides on booking responses, on the create envelope,
and `GET /bookings?agreement_gap=` filters on it.

THE FILTER AND THE PER-BOOKING ANSWER ARE ASSERTED AGAINST EACH OTHER, not
separately. A1 shipped a count and a list, written three tasks apart, that
disagreed two ways with zero coverage, and A2 shipped an API that contradicted
itself about the same booking because one construction site of a shared type
was missed. Every test below that could be written as "the filter says X" is
instead written as "the filter and the row agree".

`X-Total-Count` is asserted on every filtered read. It is the only evidence
available from outside that the filter ran in SQL rather than over the page:
a Python-side filter would window first and report a total for the unfiltered
set.

A3 WARNS. Nothing here may refuse a booking; that promise is guarded by
test_usage_agreements_api.test_an_agreement_changes_no_booking_behaviour.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.api.v1.schemas.environment_group import MemberCreate
from app.core.pagination import TOTAL_COUNT_HEADER
from app.db.models.booking_conflict_ack import BookingConflictAck
from app.db.models.booking_lifecycle import BookingType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.project import UsageAgreement
from app.db.models.usage_agreement_ack import UsageAgreementAck
from app.services import (
    agreement_gap_service, booking_service, environment_group_service,
)
from tests.factories import (
    ensure_booking_type,
    ensure_environment,
    ensure_environment_group,
    ensure_project,
    make_booking,
)

# The same fixed calendar test_agreement_gap.py is written around.
WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 30, tzinfo=timezone.utc)
INSIDE_START = datetime(2026, 3, 1, tzinfo=timezone.utc)
INSIDE_END = datetime(2026, 3, 5, tzinfo=timezone.utc)
OUTSIDE_START = datetime(2026, 8, 1, tzinfo=timezone.utc)
OUTSIDE_END = datetime(2026, 8, 5, tzinfo=timezone.utc)


async def _agreement(db, tenant_id, project_id, environment_id, starts_at=None, ends_at=None):
    agreement = UsageAgreement(
        tenant_id=tenant_id,
        project_id=project_id,
        environment_id=environment_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(agreement)
    await db.flush()
    return agreement


class _Population:
    """Four bookings covering every branch of the predicate at once.

    Covered, outside-the-window, no-agreement-at-all and no-project — the same
    mixed population `test_agreement_gap.py`'s final test uses, because a filter
    that only ever sees one kind of row proves nothing about the other three.
    """

    def __init__(self, agreed_env, unagreed_env, covered, outside, uncovered, no_project):
        self.agreed_env = agreed_env
        self.unagreed_env = unagreed_env
        self.covered = covered
        self.outside = outside
        self.uncovered = uncovered
        self.no_project = no_project

    @property
    def in_gap(self) -> set[int]:
        return {self.outside.id, self.uncovered.id}

    @property
    def not_in_gap(self) -> set[int]:
        return {self.covered.id, self.no_project.id}

    @property
    def every(self) -> set[int]:
        return self.in_gap | self.not_in_gap


async def _population(db, tenant, user, booking_type) -> _Population:
    agreed_project = await ensure_project(db, tenant.id, name="Agreed")
    unagreed_project = await ensure_project(db, tenant.id, name="Unagreed")
    agreed_env = await ensure_environment(db, tenant.id, slot=1)
    unagreed_env = await ensure_environment(db, tenant.id, slot=2)
    await _agreement(
        db, tenant.id, agreed_project.id, agreed_env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )

    async def booking(env, project_id, start, end):
        return await make_booking(
            db, tenant.id, booked_by=user.id, environment=env,
            booking_type=booking_type, project_id=project_id, start=start, end=end,
        )

    return _Population(
        agreed_env=agreed_env,
        unagreed_env=unagreed_env,
        covered=await booking(agreed_env, agreed_project.id, INSIDE_START, INSIDE_END),
        outside=await booking(agreed_env, agreed_project.id, OUTSIDE_START, OUTSIDE_END),
        uncovered=await booking(unagreed_env, unagreed_project.id, INSIDE_START, INSIDE_END),
        no_project=await booking(agreed_env, None, INSIDE_START, INSIDE_END),
    )


async def _permissive_booking_type(db, tenant_id: int) -> BookingType:
    """A booking type whose lifecycle lets an Admin edit dates in `draft` and
    move a booking to `submitted`.

    The shared `test_booking_type` fixture permits neither (empty
    `field_permissions`, no transitions), and two of the six BookingResponse
    builders are only reachable through those two paths. Without this, "every
    builder populates the gap" could only be asserted for the builders that
    happen to be reachable — which is precisely how a construction site goes
    unnoticed.
    """
    template = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="booking",
        name="permissive",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {
                    "from_state": "draft", "to_state": "submitted", "label": "Submit",
                    "allowed_roles": ["Admin"],
                },
            ],
            "field_permissions": {
                "draft": {
                    "standard_fields": {
                        "start_date": {"editable_by": ["Admin"]},
                        "end_date": {"editable_by": ["Admin"]},
                    }
                }
            },
        },
    )
    db.add(template)
    await db.flush()
    booking_type = BookingType(
        tenant_id=tenant_id, name="Permissive", lifecycle_template_id=template.id
    )
    db.add(booking_type)
    await db.flush()
    return booking_type


async def _list(client, headers, query: str = ""):
    resp = await client.get(f"/api/v1/bookings/{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp


def _ids(resp) -> set[int]:
    return {row["id"] for row in resp.json()}


def _total(resp) -> int:
    return int(resp.headers[TOTAL_COUNT_HEADER])


# ── the create envelope ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_returns_agreement_gaps_beside_detected_conflicts(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_booking_type
):
    """The warning has to reach the person making the booking, at the moment
    they make it — a governance finding they only discover on a list page later
    is one they will never act on."""
    project = await ensure_project(db_session, test_tenant.id, name="No Agreement")
    env = await ensure_environment(db_session, test_tenant.id, slot=3)

    resp = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "a purpose, not a project",
            "project_id": project.id,
            "booking_type_id": test_booking_type.id,
            "start_date": INSIDE_START.isoformat(),
            "end_date": INSIDE_END.isoformat(),
            "environment_ids": [env.id],
        },
        headers=auth_headers,
    )

    # A3 WARNS: the booking is made.
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "detected_conflicts" in body
    booking_id = body["request"]["bookings"][0]["id"]
    gaps = body["agreement_gaps"]
    assert set(gaps) == {str(booking_id)}
    # Named, never `#N` — the reader must know WHICH environment to get an
    # agreement for.
    assert env.name in gaps[str(booking_id)]
    assert "No Agreement" in gaps[str(booking_id)]
    # And the same booking's summary says the same thing, rather than the
    # envelope and the row disagreeing about it.
    assert body["request"]["bookings"][0]["agreement_gap"] == gaps[str(booking_id)]
    assert body["request"]["bookings"][0]["has_unacknowledged_agreement_gap"] is True


@pytest.mark.asyncio
async def test_create_reports_no_gap_when_an_agreement_covers_the_booking(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_booking_type
):
    """The empty case is the one that decides whether the field is trustworthy:
    a map that is never empty is a banner, not a warning."""
    project = await ensure_project(db_session, test_tenant.id, name="Covered")
    env = await ensure_environment(db_session, test_tenant.id, slot=4)
    await _agreement(db_session, test_tenant.id, project.id, env.id)

    resp = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "a purpose, not a project",
            "project_id": project.id,
            "booking_type_id": test_booking_type.id,
            "start_date": INSIDE_START.isoformat(),
            "end_date": INSIDE_END.isoformat(),
            "environment_ids": [env.id],
        },
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["agreement_gaps"] == {}
    assert resp.json()["request"]["bookings"][0]["agreement_gap"] is None
    assert resp.json()["request"]["bookings"][0]["has_unacknowledged_agreement_gap"] is False


# ── the booking response ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_booking_response_carries_the_gap_and_the_flag(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    resp = await client.get(f"/api/v1/bookings/{pop.uncovered.id}", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert pop.unagreed_env.name in body["agreement_gap"]
    assert body["has_unacknowledged_agreement_gap"] is True


@pytest.mark.asyncio
async def test_acknowledging_clears_the_flag_but_not_the_message(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """The ack answers "do we accept this", not "is this true". A gap that
    vanished on acknowledgement would leave the estate's governance state
    unreadable the moment anyone clicked the button."""
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    acked = await client.put(
        f"/api/v1/bookings/{pop.uncovered.id}/agreement-gap/ack",
        json={"notes": "accepted by the programme board"},
        headers=auth_headers,
    )
    assert acked.status_code == 200, acked.text

    body = (
        await client.get(f"/api/v1/bookings/{pop.uncovered.id}", headers=auth_headers)
    ).json()
    assert body["agreement_gap"] is not None
    assert body["has_unacknowledged_agreement_gap"] is False


@pytest.mark.asyncio
async def test_every_booking_response_builder_populates_the_gap(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
):
    """One booking, read five ways, must answer identically.

    A2 left the API self-contradictory about the same booking by populating a
    new field at some construction sites of a shared builder and not others,
    and the suite stayed green because each endpoint was tested alone. These
    are compared to each other.

    THESE ARE FIVE OF THE TWELVE SITES. The other seven — the ones that need a
    second booking, a group, or a conflict to reach — are covered one apiece in
    "every construction site" below; see that section's banner for why a
    required field is not on its own enough to guard them.

    The booking used names a project with NO agreement for its environment at
    all, so neither moving its dates nor transitioning it can change the answer
    part-way through — a difference between two readings is a builder, never the
    predicate.
    """
    booking_type = await _permissive_booking_type(db_session, test_tenant.id)
    pop = await _population(db_session, test_tenant, test_user, booking_type)
    booking_id = pop.uncovered.id

    detail = (
        await client.get(f"/api/v1/bookings/{booking_id}", headers=auth_headers)
    ).json()
    listed = next(
        row for row in (await _list(client, auth_headers)).json() if row["id"] == booking_id
    )
    # start_date/end_date are the only fields editable at the booking level.
    patched = await client.patch(
        f"/api/v1/bookings/{booking_id}/standard-fields",
        json={"end_date": (INSIDE_END + timedelta(days=1)).isoformat()},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    transitioned = await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        json={"to_state": "submitted"},
        headers=auth_headers,
    )
    assert transitioned.status_code == 200, transitioned.text
    summary = next(
        row
        for row in (
            await client.get(
                f"/api/v1/booking-requests/{pop.uncovered.booking_request_id}",
                headers=auth_headers,
            )
        ).json()["bookings"]
        if row["id"] == booking_id
    )

    answers = [detail, listed, patched.json(), transitioned.json(), summary]
    assert detail["agreement_gap"] is not None
    assert {a["agreement_gap"] for a in answers} == {detail["agreement_gap"]}
    assert {a["has_unacknowledged_agreement_gap"] for a in answers} == {True}


# ── every construction site ──────────────────────────────────────────────────
#
# Twelve places populate the two new fields: six EnvBookingSummary(...) sites
# and six calls to bookings.py::_to_response. The test above reaches five of
# them; each test below reaches exactly one of the remaining seven.
#
# WHY THE REQUIRED FIELD IS NOT ENOUGH. `EnvBookingSummary.agreement_gap` has
# no default and `_to_response`'s `gap` is required-positional, so a site that
# FORGETS them raises. That guard is real and it is not the exposure: the
# natural way to silence it at a new or refactored site is to pass the
# constants — `agreement_gap=None, has_unacknowledged_agreement_gap=False`, or a
# literal `None` for `gap` — which is behaviour-preserving to the type system
# and wrong to the reader. Task 4's review applied exactly that mutation to all
# five non-`_summaries` EnvBookingSummary sites and to two `_to_response` calls,
# and 152 tests passed. Each test below fails under that mutation at its own
# site, by name.
#
# Every one asserts against `GET /bookings/{id}` rather than against a literal
# message: the failure being guarded is one endpoint answering DIFFERENTLY from
# another about the same booking, so the two answers are compared, never
# checked separately.


async def _uncovered_booking(
    db, tenant, user, booking_type, *, slot: int, project_name: str,
    start=INSIDE_START, end=INSIDE_END,
):
    """A booking whose project has no usage agreement for its environment at
    all — in gap, and unable to stop being in gap while the test runs.

    Returns (project, environment, booking).
    """
    project = await ensure_project(db, tenant.id, name=project_name)
    env = await ensure_environment(db, tenant.id, slot=slot)
    booking = await make_booking(
        db, tenant.id, booked_by=user.id, environment=env,
        booking_type=booking_type, project_id=project.id, start=start, end=end,
    )
    return project, env, booking


async def _gap_reported_by_detail(client, headers, booking_id: int) -> str:
    """What `GET /bookings/{id}` says about this booking — the reference answer
    every other endpoint is compared against."""
    resp = await client.get(f"/api/v1/bookings/{booking_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    message = resp.json()["agreement_gap"]
    assert message is not None, "the fixture booking is not in gap"
    return message


@pytest.mark.asyncio
async def test_the_create_envelopes_detected_conflicts_carry_the_others_gap(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """`detected_conflicts` describes OTHER people's bookings, and one of them
    being in gap is exactly the governance fact that should inform whether to
    contend for the environment. Site: booking_requests.py's create route."""
    _, env, existing = await _uncovered_booking(
        db_session, test_tenant, test_user, test_booking_type,
        slot=5, project_name="Conflicted Unagreed",
    )
    expected = await _gap_reported_by_detail(client, auth_headers, existing.id)

    resp = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "a purpose, not a project",
            "booking_type_id": test_booking_type.id,
            "start_date": INSIDE_START.isoformat(),
            "end_date": INSIDE_END.isoformat(),
            "environment_ids": [env.id],
        },
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    conflicting = [
        row for rows in resp.json()["detected_conflicts"].values() for row in rows
    ]
    row = next(r for r in conflicting if r["id"] == existing.id)
    assert row["agreement_gap"] == expected
    assert row["has_unacknowledged_agreement_gap"] is True


@pytest.mark.asyncio
async def test_preview_conflicts_carries_the_gap_of_the_booking_in_the_way(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """The booking wizard's preview is the same information one step earlier,
    and a preview that disagreed with the create it precedes would be worse than
    no preview. Site: booking_requests.py's preview-conflicts route."""
    _, env, existing = await _uncovered_booking(
        db_session, test_tenant, test_user, test_booking_type,
        slot=6, project_name="Previewed Unagreed",
    )
    expected = await _gap_reported_by_detail(client, auth_headers, existing.id)

    resp = await client.post(
        "/api/v1/booking-requests/preview-conflicts",
        json={
            "environment_ids": [env.id],
            "start_date": INSIDE_START.isoformat(),
            "end_date": INSIDE_END.isoformat(),
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    previewed = [row for rows in resp.json()["conflicts"].values() for row in rows]
    row = next(r for r in previewed if r["id"] == existing.id)
    assert row["agreement_gap"] == expected
    assert row["has_unacknowledged_agreement_gap"] is True


@pytest.mark.asyncio
async def test_adding_an_environment_to_a_request_returns_that_bookings_gap(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant,
    test_booking_type,
):
    """This route's whole response IS one EnvBookingSummary, and it is the
    moment the user chose the environment that has no agreement — the one place
    the warning is most actionable. Site: booking_requests.py's
    POST /{request_id}/environments route."""
    project = await ensure_project(db_session, test_tenant.id, name="Added Unagreed")
    first_env = await ensure_environment(db_session, test_tenant.id, slot=7)
    added_env = await ensure_environment(db_session, test_tenant.id, slot=8)

    created = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "a purpose, not a project",
            "project_id": project.id,
            "booking_type_id": test_booking_type.id,
            "start_date": INSIDE_START.isoformat(),
            "end_date": INSIDE_END.isoformat(),
            "environment_ids": [first_env.id],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["id"]

    added = await client.post(
        f"/api/v1/booking-requests/{request_id}/environments",
        json={"environment_id": added_env.id},
        headers=auth_headers,
    )

    assert added.status_code == 201, added.text
    row = added.json()
    # Named, never `#N`: the reader must know WHICH environment now needs an
    # agreement, and it is not the one they started from.
    assert added_env.name in row["agreement_gap"]
    assert row["has_unacknowledged_agreement_gap"] is True
    assert row["agreement_gap"] == await _gap_reported_by_detail(
        client, auth_headers, row["id"]
    )


@pytest.mark.asyncio
async def test_a_group_transition_response_carries_every_members_gap(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant,
):
    """A group transition answers with one BookingResponse per member, built by
    a call to `_to_response` that is NOT the list's. A group booking is the
    shape most likely to be in gap — an agreement is per environment, and a
    group hands a project several at once. Site: booking_requests.py's group
    transition route."""
    booking_type = await _permissive_booking_type(db_session, test_tenant.id)
    project = await ensure_project(db_session, test_tenant.id, name="Grouped Unagreed")
    group = await ensure_environment_group(db_session, test_tenant.id, name="Ungoverned")
    members = [
        await ensure_environment(db_session, test_tenant.id, slot=slot)
        for slot in (9, 10)
    ]
    for env in members:
        await environment_group_service.add_member(
            db_session, group.id, MemberCreate(environment_id=env.id), test_tenant.id
        )
    await db_session.flush()

    created = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "a purpose, not a project",
            "project_id": project.id,
            "booking_type_id": booking_type.id,
            "start_date": INSIDE_START.isoformat(),
            "end_date": INSIDE_END.isoformat(),
            "environment_ids": [],
            "environment_group_ids": [group.id],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["id"]

    moved = await client.post(
        f"/api/v1/booking-requests/{request_id}/groups/{group.id}/transition",
        json={"to_state": "submitted"},
        headers=auth_headers,
    )

    # A3 WARNS: every member moved, gap or no gap.
    assert moved.status_code == 200, moved.text
    rows = moved.json()
    assert len(rows) == len(members)
    for row in rows:
        assert row["status"] == "submitted"
        assert row["has_unacknowledged_agreement_gap"] is True
        assert row["agreement_gap"] == await _gap_reported_by_detail(
            client, auth_headers, row["id"]
        )
    # Each member names ITS OWN environment. The members share one
    # BookingRequest, so a batch keyed by the request rather than the booking
    # would hand every member the same message and still look populated.
    for env in members:
        row = next(r for r in rows if r["environment_id"] == env.id)
        assert env.name in row["agreement_gap"]
    assert len({row["agreement_gap"] for row in rows}) == len(members)


@pytest.mark.asyncio
async def test_the_conflicts_endpoint_carries_the_other_bookings_gap(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """The conflicts drawer is opened FROM the bookings grid row, so the two
    surfaces sit side by side: a row flagged in the grid and unflagged in the
    drawer is a self-contradiction the user sees in one glance. Site:
    conflicts.py's list_conflicts route."""
    _, env, theirs = await _uncovered_booking(
        db_session, test_tenant, test_user, test_booking_type,
        slot=11, project_name="Contending Unagreed",
    )
    mine = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        booking_type=test_booking_type, project_id=None,
        start=INSIDE_START, end=INSIDE_END,
    )
    expected = await _gap_reported_by_detail(client, auth_headers, theirs.id)

    resp = await client.get(
        f"/api/v1/bookings/{mine.id}/conflicts", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    other = next(
        item["other_booking"] for item in resp.json()
        if item["other_booking"]["id"] == theirs.id
    )
    assert other["agreement_gap"] == expected
    assert other["has_unacknowledged_agreement_gap"] is True


@pytest.mark.asyncio
async def test_received_feedback_carries_the_source_bookings_gap(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """Feedback arrives from the other holder of the environment, and whether
    that holder has an agreement for it is part of reading their message. Site:
    conflicts.py's received-feedback route."""
    _, env, theirs = await _uncovered_booking(
        db_session, test_tenant, test_user, test_booking_type,
        slot=12, project_name="Feedback Unagreed",
    )
    mine = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        booking_type=test_booking_type, project_id=None,
        start=INSIDE_START, end=INSIDE_END,
    )
    db_session.add(
        BookingConflictAck(
            tenant_id=test_tenant.id,
            booking_id=theirs.id,
            other_booking_id=mine.id,
            willing_to_share=True,
            notes="happy to share the second half of the week",
            acknowledged_by=test_user.id,
            acknowledged_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()
    expected = await _gap_reported_by_detail(client, auth_headers, theirs.id)

    resp = await client.get(
        f"/api/v1/bookings/{mine.id}/received-feedback", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    source = next(
        row["source_booking"] for row in resp.json()
        if row["source_booking"]["id"] == theirs.id
    )
    assert source["agreement_gap"] == expected
    assert source["has_unacknowledged_agreement_gap"] is True


@pytest.mark.asyncio
async def test_the_legacy_single_booking_create_carries_the_gap(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant,
    test_booking_type, monkeypatch,
):
    """`POST /bookings/` builds its response through `_to_response` like every
    other endpoint, and must report the gap of the booking it just made.

    WHY THIS TEST NEEDS A SEAM, AND WHAT THE SEAM IS. `BookingCreate` carries no
    `project_id` — the legacy route always creates a project-less request — so
    the booking it returns is structurally never in gap, and the site can only
    be observed by giving that request a project. The wrapper below runs the
    REAL service, keeps the REAL booking, and changes exactly one thing: the
    request it created names a project. That is precisely what the day
    `BookingCreate` gains a `project_id` looks like, and everything downstream
    of it here — the gap query, the message, the response — is production code.

    Without this the site is unobservable from outside, which is not the same as
    safe: it is the one place a future implementer could pass a literal `None`
    with the entire suite green, and the review that found this gap proved
    exactly that mutation costs nothing today.
    """
    project = await ensure_project(db_session, test_tenant.id, name="Legacy Unagreed")
    env = await ensure_environment(db_session, test_tenant.id, slot=13)
    real_create_booking = booking_service.create_booking

    async def create_then_link_a_project(db, data, current_user):
        booking, warnings = await real_create_booking(db, data, current_user)
        booking.booking_request.project_id = project.id
        await db.flush()
        return booking, warnings

    monkeypatch.setattr(booking_service, "create_booking", create_then_link_a_project)

    resp = await client.post(
        "/api/v1/bookings/",
        json={
            "environment_id": env.id,
            "project_name": "a purpose, not a project",
            "booking_type_id": test_booking_type.id,
            "start_date": INSIDE_START.isoformat(),
            "end_date": INSIDE_END.isoformat(),
        },
        headers=auth_headers,
    )

    # A3 WARNS: the booking is made.
    assert resp.status_code == 201, resp.text
    row = resp.json()["booking"]
    assert env.name in row["agreement_gap"]
    assert "Legacy Unagreed" in row["agreement_gap"]
    assert row["has_unacknowledged_agreement_gap"] is True
    assert row["agreement_gap"] == await _gap_reported_by_detail(
        client, auth_headers, row["id"]
    )


# ── the list filter ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_filter_returns_only_bookings_in_gap_and_the_total_agrees(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    resp = await _list(client, auth_headers, "?agreement_gap=true")

    assert _ids(resp) == pop.in_gap
    assert _total(resp) == len(pop.in_gap)


@pytest.mark.asyncio
async def test_the_filter_false_returns_the_complement(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """The complement INCLUDES the no-project booking. A booking with no project
    is not "unknown", it is not in gap — and a false filter that quietly dropped
    it would make true and false fail to partition the estate."""
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    resp = await _list(client, auth_headers, "?agreement_gap=false")

    assert _ids(resp) == pop.not_in_gap
    assert pop.no_project.id in _ids(resp)
    assert _total(resp) == len(pop.not_in_gap)


@pytest.mark.asyncio
async def test_omitting_the_parameter_returns_everything(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """Omission is the "no selection" sentinel, and it must not be spelled
    `all`: the frontend's buildParams drops a filter whose value is its own
    sentinel, so a vocabulary containing `all` builds byte-identical params for
    two different states and the grid never refetches."""
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    resp = await _list(client, auth_headers)
    assert _ids(resp) == pop.every
    assert _total(resp) == len(pop.every)

    refused = await client.get("/api/v1/bookings/?agreement_gap=all", headers=auth_headers)
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_the_filter_narrows_the_page_in_sql_not_after_it(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """`limit=1` over a filtered set must return one IN-GAP row and a total of
    two. A Python-side filter would window the unfiltered set first, so the row
    returned could be a covered booking and the total would be four."""
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    resp = await _list(client, auth_headers, "?agreement_gap=true&limit=1")

    assert len(resp.json()) == 1
    assert _ids(resp) <= pop.in_gap
    assert _total(resp) == len(pop.in_gap)


@pytest.mark.asyncio
async def test_the_filter_composes_with_the_other_list_filters(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """FastAPI drops unknown query params silently, so a filter that is merely
    DECLARED and never reaches the query looks exactly like one that works when
    it is the only filter present. Combining it with `environment_id` — which
    demonstrably does work — proves the narrowing came from this parameter."""
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    both = await _list(
        client, auth_headers,
        f"?agreement_gap=true&environment_id={pop.agreed_env.id}",
    )

    assert _ids(both) == {pop.outside.id}
    assert _total(both) == 1


# ── the two mechanisms, against each other ───────────────────────────────────


@pytest.mark.asyncio
async def test_the_filter_and_the_row_agree_over_a_mixed_population(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type,
):
    """The SQL clause decides the list; a Python dict decides each row's
    message. If they can disagree, the estate can hold a booking the list flags
    and the detail page calls fine."""
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    unfiltered = await _list(client, auth_headers)
    flagged_by_row = {r["id"] for r in unfiltered.json() if r["agreement_gap"] is not None}
    filtered_true = await _list(client, auth_headers, "?agreement_gap=true")
    filtered_false = await _list(client, auth_headers, "?agreement_gap=false")
    per_booking = {
        b.id
        for b in (pop.covered, pop.outside, pop.uncovered, pop.no_project)
        if (
            await client.get(f"/api/v1/bookings/{b.id}", headers=auth_headers)
        ).json()["agreement_gap"]
        is not None
    }

    assert flagged_by_row == _ids(filtered_true) == per_booking
    assert _ids(filtered_true) | _ids(filtered_false) == _ids(unfiltered)
    assert _ids(filtered_true) & _ids(filtered_false) == set()
    assert _total(filtered_true) + _total(filtered_false) == _total(unfiltered)


@pytest.mark.asyncio
async def test_the_batch_flag_and_the_single_booking_flag_agree(
    db_session, test_tenant, test_user, test_booking_type
):
    """`has_unacknowledged_agreement_gap` answers for one booking and
    `gap_warnings_for_bookings` for a page; a list endpoint that called the
    former in a loop would issue ~100 queries for a 50-row page, so the batch
    form exists. Two functions answering one question is the shape that produced
    A1's count-vs-list divergence, so they are asserted against each other.
    """
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)
    everything = [pop.covered, pop.outside, pop.uncovered, pop.no_project]

    # Acknowledge one of the two gaps, so the population exercises acked and
    # unacked gaps as well as gap and no-gap.
    await agreement_gap_service.upsert_ack(
        db_session, pop.outside.id, notes=None,
        current_user=test_user, tenant_id=test_tenant.id,
    )

    batch = await agreement_gap_service.gap_warnings_for_bookings(
        db_session, everything, test_tenant.id
    )

    for booking in everything:
        single = await agreement_gap_service.has_unacknowledged_agreement_gap(
            db_session, booking.id, test_tenant.id
        )
        warning = batch.get(booking.id)
        assert single is (warning is not None and warning.unacknowledged), booking.id
        assert (
            await agreement_gap_service.describe_gap(db_session, booking, test_tenant.id)
        ) == (warning.message if warning else None)

    assert batch[pop.outside.id].unacknowledged is False
    assert batch[pop.uncovered.id].unacknowledged is True


# ── tenant scoping ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_another_tenants_bookings_are_never_in_our_filtered_list(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type, second_tenant_factory,
):
    """Assume every tenant filter is unguarded until a named test fails without
    it. The gap clause carries a tenant_id of its own AND the query filters
    Booking.tenant_id; a filter that dropped either would surface another
    tenant's estate the moment the gap chip was clicked."""
    other_tenant, other_admin = await second_tenant_factory()
    other_type = await ensure_booking_type(db_session, other_tenant.id)
    their_project = await ensure_project(db_session, other_tenant.id, name="Theirs")
    their_env = await ensure_environment(db_session, other_tenant.id)
    theirs = await make_booking(
        db_session, other_tenant.id, booked_by=other_admin.id, environment=their_env,
        booking_type=other_type, project_id=their_project.id,
    )
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)

    # Their booking IS in gap — in their tenant.
    assert await agreement_gap_service.has_unacknowledged_agreement_gap(
        db_session, theirs.id, other_tenant.id
    ) is True

    resp = await _list(client, auth_headers, "?agreement_gap=true")
    assert theirs.id not in _ids(resp)
    assert _ids(resp) == pop.in_gap
    assert _total(resp) == len(pop.in_gap)


@pytest.mark.asyncio
async def test_another_tenants_ack_row_never_clears_our_listed_flag(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    test_booking_type, second_tenant_factory,
):
    """The batch ack lookup is a second place the ack table is read, so it needs
    its own guard: `uq_agreement_ack_booking` is on booking_id alone, so a
    malformed row carrying another tenant's tenant_id is insertable and must not
    silence our warning. The single-booking path's equivalent guard is
    test_agreement_gap_ack.test_another_tenants_ack_row_never_suppresses_our_warning.
    """
    other_tenant, other_admin = await second_tenant_factory()
    pop = await _population(db_session, test_tenant, test_user, test_booking_type)
    db_session.add(
        UsageAgreementAck(
            tenant_id=other_tenant.id,
            booking_id=pop.uncovered.id,
            notes="not ours",
            acknowledged_by=other_admin.id,
            acknowledged_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    listed = next(
        r for r in (await _list(client, auth_headers)).json() if r["id"] == pop.uncovered.id
    )
    assert listed["has_unacknowledged_agreement_gap"] is True


# ── A3 warns ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_surfacing_the_gap_refuses_nothing(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
):
    """A3 WARNS, IT NEVER BLOCKS. Every mutating path over a booking in gap
    still succeeds — creating it, editing it and transitioning it — and each one
    reports the gap while doing so."""
    booking_type = await _permissive_booking_type(db_session, test_tenant.id)
    pop = await _population(db_session, test_tenant, test_user, booking_type)

    created = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "still in gap",
            "project_id": (await ensure_project(db_session, test_tenant.id, "Unagreed")).id,
            "booking_type_id": booking_type.id,
            "start_date": (INSIDE_START + timedelta(days=30)).isoformat(),
            "end_date": (INSIDE_END + timedelta(days=30)).isoformat(),
            "environment_ids": [pop.unagreed_env.id],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["agreement_gaps"] != {}

    edited = await client.patch(
        f"/api/v1/bookings/{pop.uncovered.id}/standard-fields",
        json={"end_date": (INSIDE_END + timedelta(days=2)).isoformat()},
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["agreement_gap"] is not None

    moved = await client.post(
        f"/api/v1/bookings/{pop.uncovered.id}/transition",
        json={"to_state": "submitted"},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["agreement_gap"] is not None
