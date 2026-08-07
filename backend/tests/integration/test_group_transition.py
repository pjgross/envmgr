"""Task 5: the atomic group transition.

Group bookings (Task 4) share `(booking_request_id, environment_group_id)` as
their atomic unit. This file proves `POST
/booking-requests/{request_id}/groups/{group_id}/transition` moves every
member of that unit or none of them, that `GET .../allowed-transitions`
offers only what every member allows, and that the per-booking endpoint
(`POST /bookings/{id}/transition`) stays the one repair tool for a diverged
group.

Read tests/integration/test_group_booking_create.py first for the shape of
`POST /booking-requests` and its helpers, several of which are mirrored here.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.models.booking import Booking
from app.db.models.booking_lifecycle import BookingStatusHistory, BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.event_log import EventLog
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.user import User
from app.services import environment_group_service
from app.api.v1.schemas.environment_group import MemberCreate
from tests.factories import ensure_environment, ensure_environment_group


# ── Shared fixtures/helpers ──────────────────────────────────────────────────

# draft --(all roles)--> submitted --(Admin/RM)--> approved --(Admin/RM)--> closed [terminal]
#                              \--(Admin/RM)--> rejected [terminal]
GROUP_TRANSITION_DEFINITION = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
        {"key": "closed", "label": "Closed", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {
            "from_state": "draft", "to_state": "submitted", "label": "Submit",
            "allowed_roles": ["Admin", "Release Manager", "Developer"],
        },
        {
            "from_state": "submitted", "to_state": "approved", "label": "Approve",
            "allowed_roles": ["Admin", "Release Manager"],
        },
        {
            "from_state": "submitted", "to_state": "rejected", "label": "Reject",
            "allowed_roles": ["Admin", "Release Manager"],
        },
        {
            "from_state": "approved", "to_state": "closed", "label": "Close",
            "allowed_roles": ["Admin", "Release Manager"],
        },
    ],
    "field_permissions": {
        "draft": {
            "standard_fields": {
                "project_name": {"editable_by": ["Admin", "Release Manager", "Developer"]},
                "start_date": {"editable_by": ["Admin", "Release Manager", "Developer"]},
                "end_date": {"editable_by": ["Admin", "Release Manager", "Developer"]},
                "booking_type": {"editable_by": ["Admin", "Release Manager", "Developer"]},
            }
        },
        "submitted": {"standard_fields": {}},
        "approved": {"standard_fields": {}},
        "rejected": {"standard_fields": {}},
        "closed": {"standard_fields": {}},
    },
}


def _payload(booking_type_id: int, **extra) -> dict:
    now = datetime.now(timezone.utc)
    body = {
        "project_name": "Group transition sweep",
        "booking_type_id": booking_type_id,
        "start_date": now.isoformat(),
        "end_date": (now + timedelta(days=1)).isoformat(),
        "environment_ids": [],
    }
    body.update(extra)
    return body


async def _add_member(db_session, group, env, tenant_id):
    return await environment_group_service.add_member(
        db_session, group.id, MemberCreate(environment_id=env.id), tenant_id
    )


async def _make_transitionable_booking_type(client, auth_headers) -> int:
    """A booking type with real states/transitions to move through.

    `test_booking_type` (conftest.py) ships an empty `transitions` list, so
    nothing is reachable through it — mirrors test_group_booking_create.py's
    helper of the same shape.
    """
    tmpl = await client.post(
        "/api/v1/tenant/lifecycle-templates",
        headers=auth_headers,
        json={"name": "Group Transition Template", "definition": GROUP_TRANSITION_DEFINITION},
    )
    assert tmpl.status_code == 201, tmpl.text
    bt = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={"name": "Transitionable Group Booking", "lifecycle_template_id": tmpl.json()["id"]},
    )
    assert bt.status_code == 201, bt.text
    return bt.json()["id"]


# draft --(all roles)--> submitted, where 'submitted' requires project_name.
REQUIRED_FIELDS_DEFINITION = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
    ],
    "transitions": [
        {
            "from_state": "draft", "to_state": "submitted", "label": "Submit",
            "allowed_roles": ["Admin", "Release Manager", "Developer"],
        },
    ],
    "field_permissions": {
        "draft": {"standard_fields": {}},
        "submitted": {
            "standard_fields": {},
            "required_fields": ["project_name"],
        },
    },
}


async def _make_required_fields_booking_type(db_session, tenant_id: int) -> int:
    """A booking type whose draft->submitted transition requires
    `project_name` to be non-empty on the parent BookingRequest.

    Built directly against the DB rather than through
    `POST /tenant/lifecycle-templates`: `LifecycleFieldPermission` (the
    schema behind that route) has no `required_fields` attribute, so
    Pydantic silently drops the key on the way in — the route cannot carry
    `required_fields` at all, only direct construction of the `definition`
    JSON blob can (the same reason tests/test_lifecycle_required_fields.py
    hand-builds its definitions). That is a pre-existing gap, not this
    task's to fix; what matters here is that the transition below still
    runs through the REAL endpoint (`POST /bookings/{id}/transition` /
    the group equivalent), so `_record_values` is genuinely exercised.

    Exists to prove `_record_values` (booking_service.py) is wired
    correctly: it is the ONLY thing that turns `BookingRequest.project_name`
    into the `record_values["project_name"]` key `validate_transition`
    checks `required_fields` against. A renamed or dropped key there makes
    every transition in the system — individual AND group — either wrongly
    refuse (a present field reads as missing) or wrongly allow (a missing
    field reads as present).
    """
    template = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="booking",
        name="Required Fields Template",
        definition=REQUIRED_FIELDS_DEFINITION,
    )
    db_session.add(template)
    await db_session.flush()
    booking_type = BookingType(
        tenant_id=tenant_id,
        name="Required Fields Booking",
        lifecycle_template_id=template.id,
    )
    db_session.add(booking_type)
    await db_session.commit()
    return booking_type.id


async def _developer_headers(client, db_session, test_tenant) -> dict:
    """A second user in `test_tenant` with a role the template doesn't grant
    submitted->approved/rejected to — for the role-blocked (403) case."""
    user = User(
        tenant_id=test_tenant.id,
        username="groupdev",
        email="groupdev@test.com",
        password_hash=get_password_hash("password123"),
        role="Developer",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", json={
        "username": "groupdev", "password": "password123", "tenant_slug": test_tenant.slug,
    })
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_group_request(
    client, auth_headers, db_session, test_tenant, booking_type_id,
    n=2, group_name="Group", extra_payload=None, slot_offset=0,
):
    """Book a fresh group of `n` live members into a new BookingRequest.

    Returns (request_id, group, envs, booking_ids) where `envs` and
    `booking_ids` are index-aligned.
    """
    group = await ensure_environment_group(db_session, test_tenant.id, name=group_name)
    envs = [
        await ensure_environment(db_session, test_tenant.id, slot=slot_offset + i + 1)
        for i in range(n)
    ]
    for env in envs:
        await _add_member(db_session, group, env, test_tenant.id)
    await db_session.commit()

    payload = _payload(booking_type_id, environment_group_ids=[group.id])
    if extra_payload:
        payload.update(extra_payload)
    created = await client.post("/api/v1/booking-requests", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    rid = created.json()["request"]["id"]
    by_env = {b["environment_id"]: b["id"] for b in created.json()["request"]["bookings"]}
    booking_ids = [by_env[e.id] for e in envs]
    return rid, group, envs, booking_ids


async def _group_transition(client, headers, rid, group_id, to_state, notes=None):
    body = {"to_state": to_state}
    if notes is not None:
        body["notes"] = notes
    return await client.post(
        f"/api/v1/booking-requests/{rid}/groups/{group_id}/transition",
        json=body, headers=headers,
    )


async def _group_allowed_transitions(client, headers, rid, group_id):
    return await client.get(
        f"/api/v1/booking-requests/{rid}/groups/{group_id}/allowed-transitions",
        headers=headers,
    )


async def _individual_transition(client, headers, booking_id, to_state):
    return await client.post(
        f"/api/v1/bookings/{booking_id}/transition",
        json={"to_state": to_state}, headers=headers,
    )


async def _status_of(client, headers, booking_id) -> str:
    resp = await client.get(f"/api/v1/bookings/{booking_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["status"]


async def _history_count(client, headers, booking_id) -> int:
    resp = await client.get(f"/api/v1/bookings/{booking_id}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    return len(resp.json())


async def _db_history_count(db_session, booking_id) -> int:
    """Like `_history_count`, but bypasses `GET /bookings/{id}/history` — that
    route 404s for a soft-deleted booking (it calls `get_booking` first),
    so a test that soft-deletes a row and still needs its history count must
    query the table directly."""
    rows = (await db_session.execute(
        select(BookingStatusHistory).where(BookingStatusHistory.booking_id == booking_id)
    )).scalars().all()
    return len(rows)


async def _events_for(db_session, booking_id: int) -> list[EventLog]:
    rows = (await db_session.execute(
        select(EventLog).where(
            EventLog.event_type == "BookingStateTransitioned",
            EventLog.aggregate_id == booking_id,
        )
    )).scalars().all()
    return list(rows)


async def _latest_history_note(db_session, booking_id: int) -> str | None:
    rows = (await db_session.execute(
        select(BookingStatusHistory)
        .where(BookingStatusHistory.booking_id == booking_id)
        .order_by(BookingStatusHistory.changed_at.desc(), BookingStatusHistory.id.desc())
    )).scalars().all()
    assert rows, f"no history rows for booking {booking_id}"
    return rows[0].notes


# ── All members move together ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_members_move_together(client, auth_headers, db_session, test_tenant):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Move Together",
    )

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 200, resp.text
    bodies = resp.json()
    assert {b["status"] for b in bodies} == {"submitted"}
    assert {b["id"] for b in bodies} == set(booking_ids)
    assert all(b["environment_group_id"] == group.id for b in bodies)
    assert all(b["environment_group_name"] == "Move Together" for b in bodies)

    for bid in booking_ids:
        assert await _status_of(client, auth_headers, bid) == "submitted"
        # A group-created booking (via POST /booking-requests) gets no
        # initial history row the way the legacy POST /bookings/ does — only
        # this transition itself.
        assert await _history_count(client, auth_headers, bid) == 1


# ── Every member gets its own event, not a group-level one ──────────────────


@pytest.mark.asyncio
async def test_group_transition_emits_one_event_per_member(
    client, auth_headers, db_session, test_tenant,
):
    """The brief was explicit: per-booking events, not a group event. One
    BookingStateTransitioned EventLog row per member, right tenant_id,
    payload {from_state, to_state, changed_by} — mirrors
    tests/integration/test_events.py's test_approve_booking_emits_event, but
    for the group path and asserting the per-member fan-out that test has no
    reason to cover."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Events Per Member",
    )

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 200, resp.text

    for bid in (a_id, b_id):
        events = await _events_for(db_session, bid)
        assert len(events) == 1, f"booking {bid} got {len(events)} events, want exactly 1"
        evt = events[0]
        assert evt.aggregate_type == "Booking"
        assert evt.tenant_id == test_tenant.id
        assert set(evt.payload.keys()) == {"from_state", "to_state", "changed_by"}
        assert evt.payload["from_state"] == "draft"
        assert evt.payload["to_state"] == "submitted"
        assert isinstance(evt.payload["changed_by"], int)

    # No group-level event under either booking's id and no third row under
    # some other aggregate — total across both members is exactly two.
    total = len(await _events_for(db_session, a_id)) + len(await _events_for(db_session, b_id))
    assert total == 2


# ── notes reach every member's history row ───────────────────────────────────


@pytest.mark.asyncio
async def test_group_transition_notes_land_on_every_members_history_row(
    client, auth_headers, db_session, test_tenant,
):
    """Every test helper elsewhere in this file passes notes=None, which
    can't tell a wired `notes=notes` apart from a dropped one. Supply a real
    note and check it reaches EVERY member's BookingStatusHistory row, not
    just the response body."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Notes Land",
    )

    resp = await _group_transition(
        client, auth_headers, rid, group.id, "submitted", notes="Approved for the sprint window",
    )
    assert resp.status_code == 200, resp.text

    for bid in (a_id, b_id):
        assert await _latest_history_note(db_session, bid) == "Approved for the sprint window"


# ── _record_values coverage: required_fields must reach a real transition ───


@pytest.mark.asyncio
async def test_individual_transition_succeeds_when_required_field_is_present(
    client, auth_headers, db_session, test_tenant,
):
    """`_payload` always sets a non-empty project_name, so draft->submitted
    must succeed against a template that requires it. Rename the
    "project_name" key inside `_record_values` (booking_service.py) and this
    flips to 400 — proving the helper's key names are load-bearing, not
    just its shape."""
    booking_type_id = await _make_required_fields_booking_type(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()
    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(booking_type_id, environment_ids=[env.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    booking_id = created.json()["request"]["bookings"][0]["id"]

    resp = await _individual_transition(client, auth_headers, booking_id, "submitted")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_individual_transition_blocks_when_required_field_is_empty(
    client, auth_headers, db_session, test_tenant,
):
    """The other half of the same guard: a genuinely empty project_name is
    correctly refused, proving required_fields enforcement is live at all
    through the endpoint (not just bypassed by an empty record_values)."""
    booking_type_id = await _make_required_fields_booking_type(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()
    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(booking_type_id, environment_ids=[env.id], project_name=""),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    booking_id = created.json()["request"]["bookings"][0]["id"]

    resp = await _individual_transition(client, auth_headers, booking_id, "submitted")
    assert resp.status_code == 400, resp.text
    assert "project_name" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_group_transition_succeeds_when_required_field_is_present(
    client, auth_headers, db_session, test_tenant,
):
    """The group path's mirror of
    test_individual_transition_succeeds_when_required_field_is_present —
    `transition_group` reads the identical `_record_values` helper, so this
    is the discriminator for the group call site specifically."""
    booking_type_id = await _make_required_fields_booking_type(db_session, test_tenant.id)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Required Fields Group",
    )

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 200, resp.text
    assert {b["status"] for b in resp.json()} == {"submitted"}


@pytest.mark.asyncio
async def test_group_transition_blocks_when_required_field_is_empty(
    client, auth_headers, db_session, test_tenant,
):
    booking_type_id = await _make_required_fields_booking_type(db_session, test_tenant.id)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2,
        group_name="Required Fields Group Blocked", extra_payload={"project_name": ""},
    )

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 400, resp.text
    assert "project_name" in resp.json()["detail"]


# ── A hand-picked booking on the same request does not move ─────────────────


@pytest.mark.asyncio
async def test_a_hand_picked_booking_on_the_same_request_does_not_move(
    client, auth_headers, db_session, test_tenant,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    group = await ensure_environment_group(db_session, test_tenant.id, name="Mixed Request Group")
    grouped_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    hand_env = await ensure_environment(db_session, test_tenant.id, slot=2)
    await _add_member(db_session, group, grouped_env, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(
            booking_type_id,
            environment_ids=[hand_env.id],
            environment_group_ids=[group.id],
        ),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    rid = created.json()["request"]["id"]
    by_env = {b["environment_id"]: b for b in created.json()["request"]["bookings"]}
    hand_booking_id = by_env[hand_env.id]["id"]
    grouped_booking_id = by_env[grouped_env.id]["id"]
    assert by_env[hand_env.id]["environment_group_id"] is None

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 200, resp.text

    assert await _status_of(client, auth_headers, grouped_booking_id) == "submitted"
    assert await _status_of(client, auth_headers, hand_booking_id) == "draft"
    assert await _history_count(client, auth_headers, hand_booking_id) == 0


# ── A refused member blocks the whole group; nothing moves ──────────────────


@pytest.mark.asyncio
async def test_a_refused_member_blocks_the_whole_group_nothing_moves(
    client, auth_headers, db_session, test_tenant,
):
    """A is individually advanced to 'submitted' first (through the real
    repair-tool endpoint, not by hand-writing a status). B stays 'draft'.
    Attempting to move the group to 'submitted' is then invalid for A
    (submitted->submitted is not a defined transition) even though it would
    be valid for B — the whole group must refuse, and B must be untouched."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Blocks Whole Group",
    )

    pre = await _individual_transition(client, auth_headers, a_id, "submitted")
    assert pre.status_code == 200, pre.text
    a_history_before = await _history_count(client, auth_headers, a_id)
    b_history_before = await _history_count(client, auth_headers, b_id)

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 400, resp.text

    # Nothing moved: A stays exactly where its OWN individual transition put
    # it, B stays exactly where it started, and no history rows were added to
    # either side of the failed attempt — a plain HTTP-status assertion would
    # also pass a transition that applied and then rolled back for an
    # unrelated reason, so check the history count itself.
    assert await _status_of(client, auth_headers, a_id) == "submitted"
    assert await _status_of(client, auth_headers, b_id) == "draft"
    assert await _history_count(client, auth_headers, a_id) == a_history_before
    assert await _history_count(client, auth_headers, b_id) == b_history_before


# ── Every failure is reported, not just the first ────────────────────────────


@pytest.mark.asyncio
async def test_every_failure_is_reported_not_just_the_first(
    client, auth_headers, db_session, test_tenant,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id, c_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=3, group_name="Two Bad Apples",
    )

    # A and C individually advanced; B stays draft.
    assert (await _individual_transition(client, auth_headers, a_id, "submitted")).status_code == 200
    assert (await _individual_transition(client, auth_headers, c_id, "submitted")).status_code == 200

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert envs[0].name in detail  # A
    assert envs[2].name in detail  # C


# ── role-blocked is 403, invalid-transition is 400 ───────────────────────────


@pytest.mark.asyncio
async def test_role_blocked_group_transition_is_403(
    client, auth_headers, db_session, test_tenant,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Role Blocked",
    )
    ok = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert ok.status_code == 200, ok.text

    dev_headers = await _developer_headers(client, db_session, test_tenant)
    resp = await _group_transition(client, dev_headers, rid, group.id, "approved")
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_invalid_transition_group_transition_is_400(
    client, auth_headers, db_session, test_tenant,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Invalid Transition",
    )
    # draft -> approved is not a defined transition.
    resp = await _group_transition(client, auth_headers, rid, group.id, "approved")
    assert resp.status_code == 400, resp.text


# ── allowed-transitions is the intersection ──────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_transitions_is_the_intersection(
    client, auth_headers, db_session, test_tenant,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Intersection Group",
    )
    # A stays draft (allows only 'submitted'); B individually advanced to
    # 'submitted' (allows only 'approved'/'rejected'). No to_state is valid
    # for both, so nothing must be offered — in particular not 'submitted',
    # which IS valid for A alone.
    assert (await _individual_transition(client, auth_headers, b_id, "submitted")).status_code == 200

    resp = await _group_allowed_transitions(client, auth_headers, rid, group.id)
    assert resp.status_code == 200, resp.text
    to_states = {t["to_state"] for t in resp.json()}
    assert to_states == set()
    assert "submitted" not in to_states
    assert "approved" not in to_states


# ── Divergence is recoverable ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_divergence_is_recoverable(client, auth_headers, db_session, test_tenant):
    """End-to-end journey the design accepts in exchange for keeping the
    individual endpoint open: diverge one member by hand, watch the group
    transition refuse and name the odd one out, repair it individually, then
    watch the group transition succeed."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Recoverable",
    )

    both_submitted = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert both_submitted.status_code == 200, both_submitted.text

    # Diverge A ahead of B via the individual endpoint.
    ahead = await _individual_transition(client, auth_headers, a_id, "approved")
    assert ahead.status_code == 200, ahead.text
    assert await _status_of(client, auth_headers, a_id) == "approved"
    assert await _status_of(client, auth_headers, b_id) == "submitted"

    # The group transition now refuses, naming A's environment and its state.
    refused = await _group_transition(client, auth_headers, rid, group.id, "approved")
    assert refused.status_code == 400, refused.text
    detail = refused.json()["detail"]
    assert envs[0].name in detail
    assert "approved" in detail

    # Repair: bring B up to match A, individually — the only repair tool.
    repaired = await _individual_transition(client, auth_headers, b_id, "approved")
    assert repaired.status_code == 200, repaired.text

    # The group transition now succeeds for both.
    closed = await _group_transition(client, auth_headers, rid, group.id, "closed")
    assert closed.status_code == 200, closed.text
    assert {b["status"] for b in closed.json()} == {"closed"}


@pytest.mark.asyncio
async def test_the_per_booking_endpoint_still_works_on_a_group_member(
    client, auth_headers, db_session, test_tenant,
):
    """Forbidding this was explicitly rejected — it is the repair tool."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Repair Tool Works",
    )
    resp = await _individual_transition(client, auth_headers, a_id, "submitted")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "submitted"
    assert resp.json()["environment_group_id"] == group.id


# ── Tenant isolation: 404, both directions ───────────────────────────────────


@pytest.mark.asyncio
async def test_a_group_id_from_another_tenant_is_404(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=1, group_name="Ours",
    )
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    resp = await _group_transition(client, auth_headers, rid, theirs.id, "submitted")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_a_request_id_from_another_tenant_is_404(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=1, group_name="Ours Group",
    )
    other_tenant, other_admin = await second_tenant_factory()
    other_login = await client.post("/api/v1/auth/login", json={
        "username": other_admin.username, "password": "password123", "tenant_slug": other_tenant.slug,
    })
    assert other_login.status_code == 200, other_login.text
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

    other_tmpl_id = await _make_transitionable_booking_type(client, other_headers)
    other_rid, other_group, _envs, _ids = await _create_group_request(
        client, other_headers, db_session, other_tenant, other_tmpl_id, n=1, group_name="Theirs Group",
    )

    # Our tenant, their request id (with OUR OWN group id) -> 404.
    resp = await _group_transition(client, auth_headers, other_rid, group.id, "submitted")
    assert resp.status_code == 404, resp.text


# ── A group id with no bookings on that request is 404 ──────────────────────


@pytest.mark.asyncio
async def test_a_group_id_with_no_bookings_on_that_request_is_404(
    client, auth_headers, db_session, test_tenant,
):
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, booking_ids = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=1, group_name="Used Group",
    )
    unused_group = await ensure_environment_group(db_session, test_tenant.id, name="Never Booked")
    await db_session.commit()

    resp = await _group_transition(client, auth_headers, rid, unused_group.id, "submitted")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "No bookings for that environment group on this request"


# ── Mutation-guard: _group_bookings must exclude soft-deleted members ───────


@pytest.mark.asyncio
async def test_a_soft_deleted_members_booking_is_not_swept_into_the_group_transition(
    client, auth_headers, db_session, test_tenant,
):
    """A is advanced to 'submitted' then its booking row is soft-deleted. If
    it were still swept in, submitted->submitted would refuse the whole
    group; excluding it correctly lets B (still draft) transition alone."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Soft Deleted Member",
    )
    assert (await _individual_transition(client, auth_headers, a_id, "submitted")).status_code == 200
    a_history_before = await _history_count(client, auth_headers, a_id)

    a_row = (await db_session.execute(
        select(Booking).where(Booking.id == a_id)
    )).scalar_one()
    a_row.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 200, resp.text
    assert {b["id"] for b in resp.json()} == {b_id}

    assert await _db_history_count(db_session, a_id) == a_history_before


# ── Mutation-guard: Booking.tenant_id must be part of _group_bookings ───────


@pytest.mark.asyncio
async def test_a_malformed_bookings_own_tenant_id_does_not_join_the_group_transition(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
):
    """No write path can produce this row (bookings always inherit the
    caller's tenant). Construct it directly to prove `Booking.tenant_id ==
    tenant_id` is load-bearing in `_group_bookings` on its own: give it a
    status ('submitted') that would refuse the whole group if it were
    incorrectly swept in alongside our real, still-draft member."""
    other_tenant, _other_admin = await second_tenant_factory()
    other_env = await ensure_environment(db_session, other_tenant.id, slot=1)

    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (real_id,) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=1, group_name="Tenant Id Malformed",
    )
    real_req = (await db_session.execute(
        select(BookingRequest).where(BookingRequest.id == rid)
    )).scalar_one()

    malformed = Booking(
        tenant_id=other_tenant.id,
        environment_id=other_env.id,
        environment_group_id=group.id,
        booking_request_id=real_req.id,
        start_date=real_req.start_date,
        end_date=real_req.end_date,
        status="submitted",
    )
    db_session.add(malformed)
    await db_session.commit()

    resp = await _group_transition(client, auth_headers, rid, group.id, "submitted")
    assert resp.status_code == 200, resp.text
    assert {b["id"] for b in resp.json()} == {real_id}


# ── Mutation-guard: BookingRequest.tenant_id must be part of _group_bookings ─


@pytest.mark.asyncio
async def test_a_malformed_bookings_own_request_tenant_mismatch_does_not_join(
    client, auth_headers, db_session, test_tenant, second_tenant_factory,
):
    """A different malformed shape from the Booking.tenant_id case: here the
    booking's OWN tenant_id legitimately matches ours, but its
    booking_request_id points at a request belonging to another tenant. No
    write path produces this either. Calling the endpoint with THAT
    request's id must still 404 — proving the join's `BookingRequest.tenant_id
    == tenant_id` clause, not merely `Booking.tenant_id`, gates the read."""
    other_tenant, other_admin = await second_tenant_factory()
    other_login = await client.post("/api/v1/auth/login", json={
        "username": other_admin.username, "password": "password123", "tenant_slug": other_tenant.slug,
    })
    assert other_login.status_code == 200, other_login.text
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    other_tmpl_id = await _make_transitionable_booking_type(client, other_headers)
    other_rid, other_group, _e, _b = await _create_group_request(
        client, other_headers, db_session, other_tenant, other_tmpl_id, n=1, group_name="Their Real Group",
    )
    other_req = (await db_session.execute(
        select(BookingRequest).where(BookingRequest.id == other_rid)
    )).scalar_one()

    our_group = await ensure_environment_group(db_session, test_tenant.id, name="Our Group For Malformed")
    our_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await _add_member(db_session, our_group, our_env, test_tenant.id)
    await db_session.commit()

    malformed = Booking(
        tenant_id=test_tenant.id,
        environment_id=our_env.id,
        environment_group_id=our_group.id,
        booking_request_id=other_req.id,
        start_date=other_req.start_date,
        end_date=other_req.end_date,
        status="draft",
    )
    db_session.add(malformed)
    await db_session.commit()

    resp = await _group_transition(client, auth_headers, other_rid, our_group.id, "submitted")
    assert resp.status_code == 404, resp.text


# ── Mutation-guard: the atomic unit is (request_id, group_id), not group_id alone


@pytest.mark.asyncio
async def test_the_same_group_booked_on_two_requests_only_the_targeted_request_moves(
    client, auth_headers, db_session, test_tenant,
):
    """The same group can legitimately be booked into two separate
    BookingRequests over time. Transitioning it on one must never touch its
    booking on the other — the atomic unit is the (request, group) pair."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    group = await ensure_environment_group(db_session, test_tenant.id, name="Reused Across Requests")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await _add_member(db_session, group, env, test_tenant.id)
    await db_session.commit()

    first = await client.post(
        "/api/v1/booking-requests",
        json=_payload(booking_type_id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    rid1 = first.json()["request"]["id"]
    booking1_id = first.json()["request"]["bookings"][0]["id"]

    second = await client.post(
        "/api/v1/booking-requests",
        json=_payload(booking_type_id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert second.status_code == 201, second.text
    rid2 = second.json()["request"]["id"]
    booking2_id = second.json()["request"]["bookings"][0]["id"]
    assert rid1 != rid2
    assert booking1_id != booking2_id

    resp = await _group_transition(client, auth_headers, rid1, group.id, "submitted")
    assert resp.status_code == 200, resp.text
    assert {b["id"] for b in resp.json()} == {booking1_id}

    assert await _status_of(client, auth_headers, booking1_id) == "submitted"
    assert await _status_of(client, auth_headers, booking2_id) == "draft"
    assert await _history_count(client, auth_headers, booking2_id) == 0


# ── What happens next to a diverged group: mixed end state, not a stuck one ──


@pytest.mark.asyncio
async def test_a_diverged_group_ends_as_a_mixed_end_state_not_a_stuck_one(
    client, auth_headers, db_session, test_tenant,
):
    """Not a defect — a recorded finding that was reviewed and adjudicated
    as correct behaviour, not a bug to fix.

    A group whose members end in DIFFERENT terminal states has no work left.
    `rollup_status` reports `mixed` here exactly as it always has for a
    hand-picked multi-environment request whose members end differently —
    nobody calls that stuck.

    Even the worse variant the review checked — members diverging into
    NON-terminal branches that never reconverge — is not stuck either: each
    member can still be individually driven to completion via
    `POST /bookings/{id}/transition`. What is lost is the GROUP affordance
    (no single to_state is valid for every member any more), not the
    ability to finish the work — precisely the trade the design accepts in
    exchange for keeping the individual endpoint open as the repair tool.

    The general reason this can never produce an unreachable state:
    `transition_group` validates each member with the identical
    `validate_transition` call the individual path uses, against the same
    template (both go through `_template_for_booking`/`_record_values` in
    booking_service.py). Group reachability is a strict SUBSET of
    individual reachability — the group endpoint can refuse to move a
    booking the individual endpoint would accept, but it can never drive a
    booking anywhere the individual endpoint could not — so it cannot create
    a state nothing can leave."""
    booking_type_id = await _make_transitionable_booking_type(client, auth_headers)
    rid, group, envs, (a_id, b_id) = await _create_group_request(
        client, auth_headers, db_session, test_tenant, booking_type_id, n=2, group_name="Forked Terminal",
    )
    assert (await _group_transition(client, auth_headers, rid, group.id, "submitted")).status_code == 200

    # A -> rejected (terminal). B -> approved -> closed (terminal).
    assert (await _individual_transition(client, auth_headers, a_id, "rejected")).status_code == 200
    assert (await _individual_transition(client, auth_headers, b_id, "approved")).status_code == 200
    assert (await _individual_transition(client, auth_headers, b_id, "closed")).status_code == 200

    # The group affordance is spent: no single to_state is valid for both
    # rejected and closed (both have zero outgoing transitions).
    spent = await _group_transition(client, auth_headers, rid, group.id, "closed")
    assert spent.status_code == 400, spent.text

    allowed = await _group_allowed_transitions(client, auth_headers, rid, group.id)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == []

    # The bookings themselves are not stuck — 'rejected' and 'closed' are
    # both correctly terminal states with no outgoing transitions at all,
    # individually or otherwise. There is no repair path because there is
    # nothing left to repair.
    a_terminal = await _individual_transition(client, auth_headers, a_id, "closed")
    assert a_terminal.status_code == 400, a_terminal.text
    b_terminal = await _individual_transition(client, auth_headers, b_id, "rejected")
    assert b_terminal.status_code == 400, b_terminal.text
