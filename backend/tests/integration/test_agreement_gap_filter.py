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

from app.core.pagination import TOTAL_COUNT_HEADER
from app.db.models.booking_lifecycle import BookingType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.project import UsageAgreement
from app.db.models.usage_agreement_ack import UsageAgreementAck
from app.services import agreement_gap_service
from tests.factories import (
    ensure_booking_type,
    ensure_environment,
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
