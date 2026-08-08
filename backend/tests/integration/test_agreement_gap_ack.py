"""Acknowledging a usage-agreement gap (A3, task 3).

ONLY THE ACKNOWLEDGEMENT IS STORED. The gap itself stays computed, so these
tests assert the property that design exists to give: adding the missing
agreement clears the warning with no ack and no other action, and nothing
anywhere has to be invalidated.

A3 WARNS. Nothing here may refuse a booking — acknowledging is the only
mutation, and it is guarded by
test_usage_agreements_api.test_an_agreement_changes_no_booking_behaviour.
"""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models.project import UsageAgreement
from app.db.models.usage_agreement_ack import UsageAgreementAck
from app.services import agreement_gap_service
from tests.factories import (
    ensure_booking_type,
    ensure_environment,
    ensure_project,
    ensure_user,
    make_booking,
)

WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 30, tzinfo=timezone.utc)


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


async def _in_gap_booking(db, tenant, user, name="Unagreed"):
    """A booking whose project has no agreement for its environment."""
    project = await ensure_project(db, tenant.id, name=name)
    env = await ensure_environment(db, tenant.id)
    booking = await make_booking(
        db, tenant.id, booked_by=user.id, environment=env, project_id=project.id
    )
    return project, env, booking


async def _ack_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(UsageAgreementAck))).scalar_one()


@pytest.mark.asyncio
async def test_acknowledging_a_gap_returns_200_and_records_who_and_when(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """An ack with no author and no timestamp is not an audit trail — the whole
    point is that a reader can see who accepted the risk, and when."""
    _project, _env, booking = await _in_gap_booking(db_session, test_tenant, test_user)
    before = datetime.now(timezone.utc)

    resp = await client.put(
        f"/api/v1/bookings/{booking.id}/agreement-gap/ack",
        headers=auth_headers,
        json={"notes": "signed off by the programme board"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["notes"] == "signed off by the programme board"
    assert body["acknowledged_by"] == test_user.id
    acknowledged_at = datetime.fromisoformat(body["acknowledged_at"])
    if acknowledged_at.tzinfo is None:
        acknowledged_at = acknowledged_at.replace(tzinfo=timezone.utc)
    assert acknowledged_at >= before.replace(microsecond=0)


@pytest.mark.asyncio
async def test_the_flag_is_true_before_the_ack_and_false_after(
    db_session, test_tenant, test_user
):
    _project, _env, booking = await _in_gap_booking(db_session, test_tenant, test_user)

    assert await agreement_gap_service.has_unacknowledged_agreement_gap(
        db_session, booking.id, test_tenant.id
    ) is True

    await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes=None,
        current_user=test_user, tenant_id=test_tenant.id,
    )

    assert await agreement_gap_service.has_unacknowledged_agreement_gap(
        db_session, booking.id, test_tenant.id
    ) is False


@pytest.mark.asyncio
async def test_a_booking_with_no_gap_is_never_unacknowledged_ack_or_no_ack(
    db_session, test_tenant, test_user
):
    """The flag answers "is there something unacknowledged to warn about", not
    "is there an ack row" — mirroring conflict_service.has_unacknowledged_conflicts,
    which returns False early when there are no conflicts at all."""
    project = await ensure_project(db_session, test_tenant.id, name="Fully Agreed")
    env = await ensure_environment(db_session, test_tenant.id)
    await _agreement(db_session, test_tenant.id, project.id, env.id)
    covered = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        project_id=project.id,
    )
    # A booking that names no project is never in gap either.
    no_project = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        project_id=None,
    )

    for booking in (covered, no_project):
        assert await agreement_gap_service.has_unacknowledged_agreement_gap(
            db_session, booking.id, test_tenant.id
        ) is False

    # And acknowledging one anyway — which A3 must not refuse, since the gap
    # can close between the page rendering and the button being pressed —
    # leaves the answer unchanged rather than flipping it.
    for booking in (covered, no_project):
        await agreement_gap_service.upsert_ack(
            db_session, booking.id, notes="belt and braces",
            current_user=test_user, tenant_id=test_tenant.id,
        )
        assert await agreement_gap_service.has_unacknowledged_agreement_gap(
            db_session, booking.id, test_tenant.id
        ) is False


@pytest.mark.asyncio
async def test_adding_the_missing_agreement_clears_the_gap_with_no_ack_and_no_other_action(
    db_session, test_tenant, test_user
):
    """The property the computed-not-stored design exists to give.

    No ack is written, nothing is invalidated, no endpoint is called: the
    paperwork lands and the warning is simply gone next time it is asked for.
    A stored gap flag would still be sitting there saying otherwise.
    """
    project, env, booking = await _in_gap_booking(
        db_session, test_tenant, test_user, name="Late Paperwork"
    )
    assert await agreement_gap_service.has_unacknowledged_agreement_gap(
        db_session, booking.id, test_tenant.id
    ) is True

    await _agreement(db_session, test_tenant.id, project.id, env.id)

    assert await agreement_gap_service.has_unacknowledged_agreement_gap(
        db_session, booking.id, test_tenant.id
    ) is False
    assert await _ack_count(db_session) == 0, "nothing was acknowledged, and nothing needed to be"
    assert await agreement_gap_service.get_ack(
        db_session, booking.id, test_tenant.id
    ) is None


@pytest.mark.asyncio
async def test_acknowledging_another_tenants_booking_is_404(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
    second_tenant_factory,
):
    """404, never 403 — a cross-tenant id must not be confirmed to exist."""
    other_tenant, other_admin = await second_tenant_factory()
    await ensure_booking_type(db_session, other_tenant.id)
    their_project = await ensure_project(db_session, other_tenant.id, name="Theirs")
    their_env = await ensure_environment(db_session, other_tenant.id)
    theirs = await make_booking(
        db_session, other_tenant.id, booked_by=other_admin.id, environment=their_env,
        project_id=their_project.id,
    )

    resp = await client.put(
        f"/api/v1/bookings/{theirs.id}/agreement-gap/ack",
        headers=auth_headers,
        json={"notes": "not mine to accept"},
    )

    assert resp.status_code == 404
    assert await _ack_count(db_session) == 0
    # ...and their own warning is untouched: the refusal changed nothing.
    assert await agreement_gap_service.has_unacknowledged_agreement_gap(
        db_session, theirs.id, other_tenant.id
    ) is True


@pytest.mark.asyncio
async def test_acknowledging_a_booking_that_does_not_exist_is_404(
    db_session, test_tenant, test_user
):
    with pytest.raises(HTTPException) as excinfo:
        await agreement_gap_service.upsert_ack(
            db_session, 9_999_999, notes=None,
            current_user=test_user, tenant_id=test_tenant.id,
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_re_acknowledging_updates_the_existing_row_rather_than_adding_a_second(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """It is an upsert keyed on booking_id alone: a gap is a property of ONE
    booking, so a second row would be a second answer to a single question.

    The TIMESTAMP is asserted as carefully as the notes and the author. "Who
    accepted this risk, and when" is the only thing this table is for, and a
    re-ack that keeps the original `acknowledged_at` says a governance finding
    revised today was accepted three months ago. Dropping
    `existing.acknowledged_at = now` from the update branch was the one mutation
    the first version of this suite did not kill.
    """
    _project, _env, booking = await _in_gap_booking(db_session, test_tenant, test_user)
    second_user = await ensure_user(db_session, test_tenant.id, username="second-acker")

    first = await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes="first pass",
        current_user=test_user, tenant_id=test_tenant.id,
    )
    first_id = first.id
    # Read out as a VALUE, not held as an attribute: `first` is the same mapped
    # row every path below updates in place, so `first.acknowledged_at` would
    # move with it and compare equal to itself no matter what the code did.
    first_at = first.acknowledged_at

    resp = await client.put(
        f"/api/v1/bookings/{booking.id}/agreement-gap/ack",
        headers=auth_headers,
        json={"notes": "revised after review"},
    )
    assert resp.status_code == 200, resp.text
    # The HTTP path refreshes it too, not just the direct service call.
    via_http = datetime.fromisoformat(resp.json()["acknowledged_at"])
    if via_http.tzinfo is None:
        via_http = via_http.replace(tzinfo=timezone.utc)
    assert via_http > first_at, (
        "re-acknowledging over HTTP left the original timestamp in place"
    )

    second = await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes="third pass",
        current_user=second_user, tenant_id=test_tenant.id,
    )

    assert await _ack_count(db_session) == 1
    assert second.id == first_id
    assert second.notes == "third pass"
    assert second.acknowledged_by == second_user.id
    assert second.acknowledged_at > first_at, (
        "the update branch must refresh acknowledged_at, not only the notes and "
        "the author — otherwise the row records when the FIRST person looked"
    )
    stored = await agreement_gap_service.get_ack(db_session, booking.id, test_tenant.id)
    assert stored is not None
    assert stored.id == first_id
    assert stored.notes == "third pass"
    assert stored.acknowledged_at > first_at


@pytest.mark.asyncio
async def test_another_tenants_ack_row_never_suppresses_our_warning(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """Assume every tenant filter is unguarded until a named test fails without
    it. A malformed row — our booking, another tenant's tenant_id — must neither
    be returned by get_ack nor silence the flag."""
    other_tenant, other_admin = await second_tenant_factory()
    _project, _env, booking = await _in_gap_booking(db_session, test_tenant, test_user)

    db_session.add(
        UsageAgreementAck(
            tenant_id=other_tenant.id,
            booking_id=booking.id,
            notes="not ours",
            acknowledged_by=other_admin.id,
            acknowledged_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    assert await agreement_gap_service.get_ack(
        db_session, booking.id, test_tenant.id
    ) is None
    assert await agreement_gap_service.has_unacknowledged_agreement_gap(
        db_session, booking.id, test_tenant.id
    ) is True


@pytest.mark.asyncio
async def test_the_flag_never_contradicts_the_message_over_a_mixed_population(
    db_session, test_tenant, test_user
):
    """Two mechanisms answering one question means one test cannot guard both.

    `describe_gap` words the warning and `has_unacknowledged_agreement_gap`
    decides whether to show it; if they ever disagree, a booking is warned about
    with no message or acknowledged into silence while its message still reads.
    Asserted against each other, not separately — the A1 count-vs-list shape.
    """
    project = await ensure_project(db_session, test_tenant.id, name="Mixed")
    agreed_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    unagreed_env = await ensure_environment(db_session, test_tenant.id, slot=2)
    await _agreement(
        db_session, test_tenant.id, project.id, agreed_env.id,
        starts_at=WINDOW_START, ends_at=WINDOW_END,
    )

    covered = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=agreed_env,
        project_id=project.id,
    )
    unagreed = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=unagreed_env,
        project_id=project.id,
    )
    acknowledged = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=unagreed_env,
        project_id=project.id,
    )
    no_project = await make_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=unagreed_env,
        project_id=None,
    )
    await agreement_gap_service.upsert_ack(
        db_session, acknowledged.id, notes=None,
        current_user=test_user, tenant_id=test_tenant.id,
    )

    flags = {
        b.id: await agreement_gap_service.has_unacknowledged_agreement_gap(
            db_session, b.id, test_tenant.id
        )
        for b in (covered, unagreed, acknowledged, no_project)
    }
    assert flags == {
        covered.id: False,
        unagreed.id: True,
        acknowledged.id: False,
        no_project.id: False,
    }

    # Every booking the flag warns about has a message, and the only one it
    # stays quiet about DESPITE a message is the acknowledged one.
    messages = await agreement_gap_service.gaps_for_bookings(
        db_session, [covered, unagreed, acknowledged, no_project], test_tenant.id
    )
    assert set(messages) == {unagreed.id, acknowledged.id}
    for booking_id, flagged in flags.items():
        if flagged:
            assert booking_id in messages
    assert flags[acknowledged.id] is False and acknowledged.id in messages


@pytest.mark.asyncio
async def test_the_database_refuses_a_second_ack_row_for_one_booking(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """The upsert is not the only thing standing between one booking and two
    answers — `uq_agreement_ack_booking` is, and nothing else asserts it.

    Both engines get it: it is a plain `UniqueConstraint`, not a partial index,
    so SQLite's `create_all` emits and enforces it exactly as PostgreSQL does.
    (Partial indexes are the ones that go inert on SQLite; this is not one.)

    Two rows would make `get_ack`'s `scalar_one_or_none()` raise
    `MultipleResultsFound` and 500 every read of that booking's warning — a
    failure that surfaces on READ, long after the write that caused it.

    The duplicate is inserted under ANOTHER tenant's `tenant_id` as well as our
    own, because the constraint deliberately names `booking_id` ALONE. Widening
    it to `(tenant_id, booking_id)` — the reflexive thing to do to any
    tenant-scoped table — would let a second row exist after all, and only the
    cross-tenant half of this test would notice.
    """
    other_tenant, other_admin = await second_tenant_factory()
    _project, _env, booking = await _in_gap_booking(db_session, test_tenant, test_user)
    await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes="the one answer",
        current_user=test_user, tenant_id=test_tenant.id,
    )

    duplicates = [
        # Same tenant: the plain second-row case.
        (test_tenant.id, test_user.id),
        # Another tenant: proves the constraint is on booking_id alone.
        (other_tenant.id, other_admin.id),
    ]
    for tenant_id, user_id in duplicates:
        # A SAVEPOINT, so the failed INSERT does not abort the surrounding
        # transaction — on PostgreSQL every later statement in this test would
        # otherwise be refused with InFailedSQLTransaction.
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(
                    UsageAgreementAck(
                        tenant_id=tenant_id,
                        booking_id=booking.id,
                        notes="a second answer to one question",
                        acknowledged_by=user_id,
                        acknowledged_at=datetime.now(timezone.utc),
                    )
                )
                await db_session.flush()

    assert await _ack_count(db_session) == 1
    stored = await agreement_gap_service.get_ack(db_session, booking.id, test_tenant.id)
    assert stored is not None and stored.notes == "the one answer"


@pytest.mark.asyncio
async def test_a_misspelled_field_is_refused_rather_than_silently_dropped(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user
):
    """`extra="forbid"`, matching every write schema written since B1.

    Without it Pydantic ignores the unknown key and returns 200 with `notes`
    null: the caller is told the acknowledgement was recorded with their
    reasoning, and the audit trail holds a blank. That is the
    `POST /tenant/lifecycle-templates` failure CLAUDE.md records — a required
    field silently dropped, unconfigurable through the product, discovered
    sub-projects later.

    `ConflictAckUpsert` does NOT forbid extras. It predates the convention;
    `EnvironmentUpdate`, `EnvironmentHandoverUpdate`, `EnvironmentRequestUpdate`,
    `ProjectCreate/Update` and `EnvironmentGroupCreate/Update` all do.
    """
    _project, _env, booking = await _in_gap_booking(db_session, test_tenant, test_user)

    resp = await client.put(
        f"/api/v1/bookings/{booking.id}/agreement-gap/ack",
        headers=auth_headers,
        json={"note": "singular, and therefore not the field"},
    )

    assert resp.status_code == 422, resp.text
    assert await _ack_count(db_session) == 0, (
        "a refused request must write nothing — a 200 with notes=null is worse "
        "than a 422, because the reader believes the reasoning was recorded"
    )
    # The correctly-spelled key still works, so the rule is a spelling check and
    # not a broken endpoint.
    ok = await client.put(
        f"/api/v1/bookings/{booking.id}/agreement-gap/ack",
        headers=auth_headers,
        json={"notes": "plural, and therefore the field"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["notes"] == "plural, and therefore the field"
