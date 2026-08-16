"""B4 ADVISES; IT NEVER BLOCKS AND IT NEVER PREEMPTS.

The fourth sub-project running whose central promise is a named test rather
than an absence in the diff — after A1's
test_an_agreement_changes_no_booking_behaviour, A4's
test_a_contention_changes_no_booking_behaviour and B2's
test_b2_advises_never_blocks.

IF ANY TEST HERE FAILS, B4 HAS STARTED ACTING. Do not "fix" it by relaxing the
assertion.

Proved non-vacuous rather than assumed: inserting a real refusal into
booking_request_service.create_request (raise a 409 when any overlapping
booking's request is PROTECTION_HARD) makes
test_a_soft_booking_may_be_made_over_a_hard_one fail, and reverting it makes
it pass again. See the task report for the exact failure output.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.protection_levels import PROTECTION_HARD, PROTECTION_SOFT
from app.db.models.booking import Booking
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.services import booking_service
from tests.factories import ensure_environment

# ── Local fixtures ───────────────────────────────────────────────────────────
#
# All of this must be scoped to `test_tenant` — not the `tenant` fixture from
# tests/conftest.py (a different, unrelated tenant) — because the first three
# tests below go through `client`/`auth_headers`, which log into `test_tenant`.
# Keeping every fixture on one tenant lets `test_check_overlap_answers_
# identically_for_both_levels` (db-only) share the same `soft_booking` /
# `hard_booking` rows as the API-driven tests, rather than needing a second,
# disconnected set.


@pytest_asyncio.fixture(scope="function")
async def environment(db_session, test_tenant) -> Environment:
    """A real environment in test_tenant, via the shared FK helper."""
    return await ensure_environment(db_session, test_tenant.id)


@pytest_asyncio.fixture(scope="function")
async def booking_type(db_session, test_tenant) -> BookingType:
    """A booking type with a GENUINE draft→submitted transition.

    Not tests/factories.py's ensure_booking_type, whose lifecycle template
    declares "transitions": [] — allowed-transitions would then return []
    for every booking regardless of gating, and
    test_a_hard_booking_is_still_transitionable would pass while asserting
    nothing. Same trap test_b2_advises_never_blocks.py names for the same
    reason.
    """
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="booking",
        name="b4-guard-lifecycle",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {
                    "from_state": "draft",
                    "to_state": "submitted",
                    "label": "Submit",
                    "allowed_roles": ["Admin"],
                }
            ],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(
        tenant_id=test_tenant.id,
        name="b4-guard-booking-type",
        lifecycle_template_id=tpl.id,
    )
    db_session.add(bt)
    await db_session.flush()
    await db_session.refresh(bt)
    return bt


async def _make_booking(
    db_session, test_tenant, test_user, booking_type, environment, level, project_name,
) -> Booking:
    """One BookingRequest at `level` plus its one child Booking, on the same
    environment and the same dates every call uses — so a soft and a hard
    booking made this way always overlap."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1)
    end = start + timedelta(days=2)
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name=project_name,
        booking_type_id=booking_type.id,
        start_date=start,
        end_date=end,
        protection_level=level,
        booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()
    booking = Booking(
        tenant_id=test_tenant.id,
        booking_request_id=req.id,
        environment_id=environment.id,
        start_date=start,
        end_date=end,
    )
    db_session.add(booking)
    await db_session.flush()

    # Eager-load booking_request explicitly rather than db_session.refresh():
    # the tests access hard_booking.booking_request.booking_type_id as a plain
    # sync attribute, which needs the relationship already materialised — an
    # implicit lazy load outside an await raises MissingGreenlet.
    return (
        await db_session.execute(
            select(Booking)
            .options(selectinload(Booking.booking_request))
            .where(Booking.id == booking.id)
        )
    ).scalar_one()


@pytest_asyncio.fixture(scope="function")
async def soft_booking(
    db_session, test_tenant, test_user, booking_type, environment
) -> Booking:
    """One Booking whose parent request is PROTECTION_SOFT."""
    return await _make_booking(
        db_session, test_tenant, test_user, booking_type, environment,
        PROTECTION_SOFT, "Soft reservation",
    )


@pytest_asyncio.fixture(scope="function")
async def hard_booking(
    db_session, test_tenant, test_user, booking_type, environment
) -> Booking:
    """One Booking whose parent request is PROTECTION_HARD, same environment
    and dates as `soft_booking` — DECLARED protected, not mechanically so."""
    return await _make_booking(
        db_session, test_tenant, test_user, booking_type, environment,
        PROTECTION_HARD, "Hard reservation",
    )


@pytest.mark.asyncio
async def test_a_soft_booking_may_be_made_over_a_hard_one(
    client, auth_headers, hard_booking, environment
):
    """The whole point. A hard reservation is DECLARED protected, not
    mechanically protected."""
    r = await client.post(
        "/api/v1/booking-requests",
        headers=auth_headers,
        json={
            "project_name": "Booked right over the top",
            "booking_type_id": hard_booking.booking_request.booking_type_id,
            "start_date": hard_booking.start_date.isoformat(),
            "end_date": hard_booking.end_date.isoformat(),
            "environment_ids": [environment.id],
        },
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_check_overlap_answers_identically_for_both_levels(
    db_session, test_tenant, environment, soft_booking, hard_booking
):
    """`check_overlap` must not have learned about protection. Its answer is a
    function of dates, tenant, status and exclusive use — nothing else."""
    soft = await booking_service.check_overlap(
        db_session, environment.id, soft_booking.start_date,
        soft_booking.end_date, test_tenant.id, exclusive_use=False,
    )
    hard = await booking_service.check_overlap(
        db_session, environment.id, hard_booking.start_date,
        hard_booking.end_date, test_tenant.id, exclusive_use=False,
    )
    assert soft.blocked == hard.blocked is False


@pytest.mark.asyncio
async def test_a_hard_booking_is_still_transitionable(
    client, auth_headers, hard_booking
):
    allowed = (await client.get(
        f"/api/v1/bookings/{hard_booking.id}/allowed-transitions",
        headers=auth_headers,
    )).json()
    assert allowed, "a hard booking with no allowed transitions is a blocked one"


@pytest.mark.asyncio
async def test_a_hard_booking_is_still_editable(client, auth_headers, hard_booking):
    r = await client.patch(
        f"/api/v1/booking-requests/{hard_booking.booking_request_id}/standard-fields",
        headers=auth_headers,
        json={"notes": "still editable"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_recording_a_contention_decision_still_changes_no_booking(
    db_session, hard_booking, soft_booking
):
    """A4's guard, re-asserted with protection in play: the verdict now names a
    winner in cases it previously could not, and that must still move nothing."""
    # Refresh BEFORE the first snapshot too, not just after: SQLite hands back
    # naive datetimes on refresh while the just-flushed Python objects still
    # hold the aware values they were constructed with. Comparing an
    # un-refreshed "before" to a refreshed "after" reports a change that is
    # only the driver's naive-vs-aware representation, not a real mutation —
    # the same trap contention_service._utc's docstring exists to name.
    await db_session.refresh(hard_booking)
    await db_session.refresh(soft_booking)
    before = [
        (b.status, b.start_date, b.end_date, b.deleted_at)
        for b in (hard_booking, soft_booking)
    ]
    from app.services import contention_service as cs
    await cs.verdict_for_pair(
        db_session, hard_booking.id, soft_booking.id, hard_booking.tenant_id
    )
    await db_session.refresh(hard_booking)
    await db_session.refresh(soft_booking)
    after = [
        (b.status, b.start_date, b.end_date, b.deleted_at)
        for b in (hard_booking, soft_booking)
    ]
    assert before == after


def test_no_production_module_refuses_on_a_protection_level():
    """A structural assertion, deliberately — there is no behavioural test for
    "nobody anywhere raises on this value", and a grep is the only thing that
    covers code paths no fixture reaches.

    THIS IS A SMOKE ALARM, NOT A PROOF. The +-300-character window means a
    long docstring or comment sitting between a `raise` and its status code
    produces a FALSE POSITIVE (an innocent refusal gets flagged), and a
    refusal raised in a helper function one call away from the
    `protection_level` reference produces a FALSE NEGATIVE (a real violation
    is missed entirely — nothing here follows a call graph). The five
    behavioural tests above are the real guard on the promise; this one only
    catches the most obvious way someone could break it in the same function
    that reads the level.

    Two deliberate departures from the brief's first draft, both forced by
    running this against the real tree rather than assuming it:

    - The regex is `\\bprotection_level\\b`, not a bare substring. Without the
      word boundary, "protection_level" also matches inside the module name
      `app.core.protection_levels` — the import line at the top of
      booking_request_service.py — and that match's +-window then reaches an
      unrelated `HTTPException(400, "Unknown booking_type_id")` a few lines
      later purely by proximity, a false positive with nothing to do with the
      level itself.
    - "422" is accepted alongside "403": B4's OWN documented design (see this
      module's docstring and update_standard_fields) is a 403 role gate PLUS
      a 422 on an explicit `null` — the null value is malformed, not an
      authorization question, and is refused for every caller including an
      Admin. A grep that only tolerated 403 would flag that legitimate,
      intentional refusal on every run.
    - The window is +-300, not +-400. At 400 the STANDARD_REQUEST_FIELDS set
      literal's own `"protection_level"` entry (naming the field, not gating
      it) sits close enough to that same unrelated "Unknown fields" 400 to
      false-positive on it too. 300 keeps both real refusals (403 at ~283
      chars, 422 at ~87 chars) comfortably inside the window while dropping
      that collision — verified by sweeping window sizes against this tree
      rather than picked by feel.

    Same class of exception as the health-history tiebreaker's structural
    assertion, and documented here for the same reason.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for match in re.finditer(r"\bprotection_level\b", text):
            window = text[max(0, match.start() - 300) : match.end() + 300]
            if "HTTPException" in window and "403" not in window and "422" not in window:
                offenders.append(f"{path}:{text[:match.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "B4 may only ever raise 403 (role gate) or 422 (null value) on a "
        f"protection level. Found a refusal near: {offenders}"
    )
