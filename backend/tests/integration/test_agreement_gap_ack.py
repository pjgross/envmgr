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

from app.db.models.project import UsageAgreement
from app.db.models.usage_agreement_ack import UsageAgreementAck
from app.services import agreement_gap_service
from tests.factories import (
    ensure_booking,
    ensure_booking_type,
    ensure_environment,
    ensure_project,
    ensure_user,
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
    booking = await ensure_booking(
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
    covered = await ensure_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=env,
        project_id=project.id,
    )
    # A booking that names no project is never in gap either.
    no_project = await ensure_booking(
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
    theirs = await ensure_booking(
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
    booking, so a second row would be a second answer to a single question."""
    _project, _env, booking = await _in_gap_booking(db_session, test_tenant, test_user)
    second_user = await ensure_user(db_session, test_tenant.id, username="second-acker")

    first = await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes="first pass",
        current_user=test_user, tenant_id=test_tenant.id,
    )
    first_id = first.id

    resp = await client.put(
        f"/api/v1/bookings/{booking.id}/agreement-gap/ack",
        headers=auth_headers,
        json={"notes": "revised after review"},
    )
    assert resp.status_code == 200, resp.text

    second = await agreement_gap_service.upsert_ack(
        db_session, booking.id, notes="third pass",
        current_user=second_user, tenant_id=test_tenant.id,
    )

    assert await _ack_count(db_session) == 1
    assert second.id == first_id
    assert second.notes == "third pass"
    assert second.acknowledged_by == second_user.id
    stored = await agreement_gap_service.get_ack(db_session, booking.id, test_tenant.id)
    assert stored is not None
    assert stored.id == first_id
    assert stored.notes == "third pass"


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

    covered = await ensure_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=agreed_env,
        project_id=project.id,
    )
    unagreed = await ensure_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=unagreed_env,
        project_id=project.id,
    )
    acknowledged = await ensure_booking(
        db_session, test_tenant.id, booked_by=test_user.id, environment=unagreed_env,
        project_id=project.id,
    )
    no_project = await ensure_booking(
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
