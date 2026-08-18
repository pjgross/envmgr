"""B5 Task 8 — a booking running past teardown is refused, on EVERY create
path. THE MOST CONSEQUENTIAL TEST IN THE SUB-PROJECT: this and `tear_down`
itself are the only two things B5 changes outside its own records.

THE THREE CREATE PATHS ARE INDEPENDENT CODE. `booking_request_service` has
two of them (`create_request` and `add_environment` — the second a CREATE IN
DISGUISE that a grep-by-endpoint sweep misses, the exact shape that produced
the open `exclusive_use_requested` asymmetry CLAUDE.md still records) and
`booking_service` has the third (`create_booking`), which
`release_booking_service` delegates to, so covering it covers the release
booking path too. A date-extending EDIT is the same act as a create that
starts past teardown, so `PATCH .../standard-fields` gets its own coverage —
one test per path, because a test covering one path proves nothing about the
others.

Fixture shapes follow test_decommission_api.py's `env_with_owner_and_team` /
`owner_headers` / `team_headers` / `live_decommission` — this file needs the
identical pairing (a named owner who can REQUEST an extension, an operating
team who can DECIDE it) for the extension-interaction test, which is the
proof the rule is a DATE, not a stored flag: granting an extension must widen
what is bookable with no second write anywhere.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core.security import get_password_hash
from app.db.models.environment import EnvironmentStatus
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from app.services import environment_decommission_service
from tests.factories import ensure_booking_type, ensure_environment, ensure_user_group


def _iso(*, days: int) -> str:
    """A timestamp `days` from now, ISO-8601 — the same shape B5's extension
    routes and DecommissionCreate.scheduled_teardown_at accept."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def _login(client, tenant_slug, username, password="password123"):
    r = await client.post("/api/v1/auth/login", json={
        "username": username, "password": password, "tenant_slug": tenant_slug,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _request_body(environment_id: int, booking_type_id: int) -> dict:
    return {
        "project_name": "B5 task 8 refusal test",
        "booking_type_id": booking_type_id,
        "environment_ids": [environment_id],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def booking_type(db_session, test_tenant):
    return await ensure_booking_type(db_session, test_tenant.id)


@pytest_asyncio.fixture
async def plain_env(db_session, test_tenant):
    """An environment with no decommission at all — the control case."""
    return await ensure_environment(db_session, test_tenant.id, slot=801)


@pytest_asyncio.fixture
async def decommissioned_env(db_session, test_tenant):
    """THE DEGENERATE CASE B5 also closes: an environment already
    DECOMMISSIONED, with no live decommission row at all (teardown already
    ran to completion) — nothing on any create path looked at
    `environment.status` before Task 8."""
    env = await ensure_environment(db_session, test_tenant.id, slot=802)
    env.status = EnvironmentStatus.DECOMMISSIONED
    await db_session.commit()
    await db_session.refresh(env)
    return env


@pytest_asyncio.fixture
async def _env_with_team_and_owner(db_session, test_tenant):
    """A fresh environment with BOTH an operating team (to decide an
    extension) and a named owner (to request one) — the pairing every
    extension-interaction test needs, following test_decommission_api.py's
    `env_with_owner_and_team`. Deliberately two different people: requesting
    is gated on the owner, deciding on the team, and a fixture where one
    person is both would hide the difference."""
    group = await ensure_user_group(db_session, test_tenant.id, name="B5T8 Ops")
    env = await ensure_environment(db_session, test_tenant.id, slot=803)
    env.operations_group_id = group.id

    member = User(
        tenant_id=test_tenant.id, username="b5t8-team-member",
        email="b5t8-team-member@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=member.id
    ))

    owner = User(
        tenant_id=test_tenant.id, username="b5t8-owner",
        email="b5t8-owner@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(owner)
    await db_session.flush()
    env.owner_user_id = owner.id

    await db_session.commit()
    await db_session.refresh(env)
    return env


@pytest_asyncio.fixture
async def team_headers(client, test_tenant, _env_with_team_and_owner):
    return await _login(client, test_tenant.slug, "b5t8-team-member")


@pytest_asyncio.fixture
async def owner_headers(client, test_tenant, _env_with_team_and_owner):
    return await _login(client, test_tenant.slug, "b5t8-owner")


@pytest_asyncio.fixture
async def env_being_decommissioned(
    client, test_tenant, _env_with_team_and_owner, team_headers
):
    """The environment above, WITH a live decommission whose teardown is
    explicitly 10 days out — inside the window every "ends before" (day 2,
    accepted) / "ends after" (day 20, refused) test needs, and safely past
    the tenant's 5-day default notice period so the 422 on shortening the
    notice never fires."""
    r = await client.post(
        f"/api/v1/environments/{_env_with_team_and_owner.id}/decommission",
        headers=team_headers,
        json={"reason": "B5 task 8 fixture", "scheduled_teardown_at": _iso(days=10)},
    )
    assert r.status_code == 201, r.text
    return _env_with_team_and_owner


@pytest_asyncio.fixture
async def live_decommission(db_session, test_tenant, env_being_decommissioned):
    """The ORM row `env_being_decommissioned`'s own fixture just created —
    returned separately because the extension routes address a decommission
    by ITS OWN id, not its environment's."""
    return await environment_decommission_service.get_most_recent(
        db_session, test_tenant.id, env_being_decommissioned.id
    )


@pytest_asyncio.fixture
async def cancelled_decommission(client, auth_headers, live_decommission):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/cancel",
        headers=auth_headers, json={"reason": "not needed after all"},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest_asyncio.fixture
async def existing_request(client, auth_headers, plain_env, booking_type):
    """An existing BookingRequest spanning day1-day20, against a PLAIN
    environment — the request `test_add_environment_refuses_a_booking_past_
    teardown` adds `env_being_decommissioned` to (with no date override), so
    it inherits these dates."""
    r = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(plain_env.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=20),
    })
    assert r.status_code == 201, r.text
    return SimpleNamespace(id=r.json()["request"]["id"])


@pytest_asyncio.fixture
async def existing_booking(client, auth_headers, env_being_decommissioned, booking_type):
    """A booking against `env_being_decommissioned` that fits BEFORE
    teardown (day1-day2, accepted) — extending it past teardown is exactly
    what the date-extending edit test does next."""
    r = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=2),
    })
    assert r.status_code == 201, r.text
    body = r.json()["request"]
    child = body["bookings"][0]
    return SimpleNamespace(id=child["id"], booking_request_id=body["id"])


# ---------------------------------------------------------------------------
# The three create paths, plus the date-extending edit path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_booking_ending_before_teardown_is_accepted(
    client, auth_headers, env_being_decommissioned, booking_type
):
    r = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=2),
    })
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_create_request_refuses_a_booking_past_teardown(
    client, auth_headers, env_being_decommissioned, booking_type
):
    r = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=20),
    })
    assert r.status_code == 409, r.text
    assert env_being_decommissioned.name in r.json()["detail"]


@pytest.mark.asyncio
async def test_add_environment_refuses_a_booking_past_teardown(
    client, auth_headers, existing_request, env_being_decommissioned
):
    """A CREATE IN DISGUISE. This is the path a sweep by endpoint name misses."""
    r = await client.post(
        f"/api/v1/booking-requests/{existing_request.id}/environments",
        headers=auth_headers,
        json={"environment_id": env_being_decommissioned.id},
    )
    assert r.status_code == 409, r.text
    assert env_being_decommissioned.name in r.json()["detail"]


@pytest.mark.asyncio
async def test_the_legacy_booking_path_refuses_a_booking_past_teardown(
    client, auth_headers, env_being_decommissioned, booking_type
):
    r = await client.post("/api/v1/bookings/", headers=auth_headers, json={
        "environment_id": env_being_decommissioned.id,
        "start_date": _iso(days=1), "end_date": _iso(days=20),
        "booking_type_id": booking_type.id, "project_name": "legacy path test",
    })
    assert r.status_code == 409, r.text
    assert env_being_decommissioned.name in r.json()["detail"]


@pytest.mark.asyncio
async def test_extending_an_existing_booking_past_teardown_is_refused(
    client, auth_headers, existing_booking, env_being_decommissioned
):
    """Moving an end date past teardown is the same act as booking past it."""
    r = await client.patch(
        f"/api/v1/booking-requests/{existing_booking.booking_request_id}/standard-fields",
        headers=auth_headers, json={"end_date": _iso(days=20)},
    )
    assert r.status_code == 409, r.text
    assert env_being_decommissioned.name in r.json()["detail"]


# ---------------------------------------------------------------------------
# The design's proof: an extension moves the LINE, not a stored flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_granting_an_extension_permits_the_longer_booking_with_no_second_write(
    client, auth_headers, team_headers, owner_headers, env_being_decommissioned,
    live_decommission, booking_type,
):
    """THE WHOLE POINT OF THE DATE RULE. Nothing lifts a flag; the line moves."""
    refused = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=20),
    })
    assert refused.status_code == 409, refused.text

    ext = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "need it", "until": _iso(days=60)},
    )
    assert ext.status_code == 200, ext.text
    dec = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": True},
    )
    assert dec.status_code == 200, dec.text

    accepted = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=20),
    })
    assert accepted.status_code == 201, accepted.text


@pytest.mark.asyncio
async def test_a_cancelled_decommission_refuses_nothing(
    client, auth_headers, env_being_decommissioned, cancelled_decommission, booking_type,
):
    r = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(env_being_decommissioned.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=99),
    })
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_a_decommissioned_environment_takes_no_bookings_at_all(
    client, auth_headers, decommissioned_env, booking_type,
):
    """The degenerate case B5 also closes: nothing today looks at
    environment.status on any create path."""
    r = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(decommissioned_env.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=2),
    })
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_an_environment_with_no_decommission_is_unaffected(
    client, auth_headers, plain_env, booking_type,
):
    r = await client.post("/api/v1/booking-requests", headers=auth_headers, json={
        **_request_body(plain_env.id, booking_type.id),
        "start_date": _iso(days=1), "end_date": _iso(days=400),
    })
    assert r.status_code == 201, r.text
