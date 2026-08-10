"""Phase 7 B4 — the protection level end to end.

B4 ADVISES. Nothing here may assert that a booking was refused, moved or
cancelled because of a protection level; `test_b4_advises_never_blocks.py`
holds the guard on that.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.protection_levels import (
    PROTECTION_HARD,
    PROTECTION_LEVELS,
    PROTECTION_SOFT,
)
from app.core.security import Role, get_password_hash
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.user import User
from tests.factories import ensure_booking_type, ensure_environment

# ── Local fixtures ───────────────────────────────────────────────────────────
# `tenant` and `user` come from tests/conftest.py. This repo has no
# repo-wide `lifecycle_template` or `booking_type` fixture — every module
# that needs one defines it locally (see test_release_happy_path.py) — so
# this module follows the same pattern rather than inventing shared fixtures.


@pytest_asyncio.fixture(scope="function")
async def lifecycle_template(db_session, tenant) -> LifecycleTemplate:
    """A minimal booking lifecycle template for `tenant`."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="booking",
        name="protection-level-test-lifecycle",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    await db_session.refresh(tpl)
    return tpl


@pytest_asyncio.fixture(scope="function")
async def booking_type(db_session, tenant) -> BookingType:
    """A real BookingType for `tenant`, via the shared FK helper (it creates
    its own lifecycle template, distinct from the one above)."""
    return await ensure_booking_type(db_session, tenant.id)


def test_the_two_levels_are_the_whole_vocabulary():
    assert PROTECTION_LEVELS == {PROTECTION_SOFT, PROTECTION_HARD}
    assert PROTECTION_SOFT == "soft"
    assert PROTECTION_HARD == "hard"


@pytest.mark.asyncio
async def test_a_new_booking_type_defaults_to_soft(db_session, tenant, lifecycle_template):
    bt = BookingType(
        tenant_id=tenant.id,
        name="Ad hoc",
        lifecycle_template_id=lifecycle_template.id,
    )
    db_session.add(bt)
    await db_session.flush()
    await db_session.refresh(bt)
    assert bt.default_protection_level == PROTECTION_SOFT
    # Null means "this type has no preset" — a legitimate state, not a
    # missing value, the same call B1 made for environment.expires_at.
    assert bt.default_duration_minutes is None


@pytest.mark.asyncio
async def test_a_new_request_defaults_to_soft(db_session, tenant, booking_type, user):
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=tenant.id,
        project_name="Regression",
        booking_type_id=booking_type.id,
        start_date=now,
        end_date=now + timedelta(days=1),
        booked_by=user.id,
    )
    db_session.add(req)
    await db_session.flush()
    await db_session.refresh(req)
    assert req.protection_level == PROTECTION_SOFT

    stored = (await db_session.execute(
        select(BookingRequest.protection_level).where(BookingRequest.id == req.id)
    )).scalar_one()
    assert stored == PROTECTION_SOFT


# ── Task 2: inheritance + the role gate on create ────────────────────────────
#
# These go through `client`, so they must be scoped to `test_tenant` — the
# tenant `auth_headers` (tests/conftest.py) logs into — NOT `tenant` above,
# which is a different, unrelated tenant used only by the two db-only tests.
# Pointing an API call's booking_type_id/environment_id at `tenant`'s rows
# while authenticating as `test_tenant`'s user would 400 as "Unknown
# booking_type_id" or 400 the environment lookup — it would not exercise the
# role gate at all. `booking_type` above is deliberately left alone for that
# reason; `api_booking_type` is its test_tenant-scoped counterpart.


@pytest_asyncio.fixture(scope="function")
async def api_booking_type(db_session, test_tenant) -> BookingType:
    """A soft-default BookingType in test_tenant, for the API-level tests
    below — distinct from `booking_type` above (scoped to `tenant`)."""
    return await ensure_booking_type(db_session, test_tenant.id, name="api-booking-type")


@pytest_asyncio.fixture(scope="function")
async def hard_booking_type(db_session, test_tenant) -> BookingType:
    """A BookingType in test_tenant whose default_protection_level is hard."""
    bt = await ensure_booking_type(db_session, test_tenant.id, name="hard-booking-type")
    bt.default_protection_level = PROTECTION_HARD
    await db_session.flush()
    await db_session.refresh(bt)
    return bt


@pytest_asyncio.fixture(scope="function")
async def environment(db_session, test_tenant) -> Environment:
    """A real environment in test_tenant, via the shared FK helper."""
    return await ensure_environment(db_session, test_tenant.id)


async def _login_as(client, db_session, test_tenant, username: str, role: str) -> dict:
    """Bearer headers for a fresh user of `role` in test_tenant.

    Follows the pattern in test_environment_groups_authz.py.
    """
    user = User(
        tenant_id=test_tenant.id,
        username=username,
        email=f"{username}@test.com",
        password_hash=get_password_hash("password123"),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "password123",
            "tenant_slug": test_tenant.slug,
        },
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="function")
async def developer_headers(client, db_session, test_tenant) -> dict:
    """Bearer headers for a Role.DEVELOPER user in test_tenant — a caller who
    may send the inherited protection level unchanged but may not choose a
    different one."""
    return await _login_as(client, db_session, test_tenant, "b4-developer", Role.DEVELOPER)


@pytest.mark.asyncio
async def test_a_request_inherits_its_booking_types_default(
    client, auth_headers, hard_booking_type, environment
):
    """The level is INHERITED, not defaulted to soft, when the type says hard."""
    r = await client.post(
        "/api/v1/booking-requests",
        headers=auth_headers,
        json={
            "project_name": "Release 24.4",
            "booking_type_id": hard_booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["request"]["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_an_admin_may_override_the_inherited_level(
    client, auth_headers, api_booking_type, environment
):
    r = await client.post(
        "/api/v1/booking-requests",
        headers=auth_headers,  # the shared fixture user is an Admin
        json={
            "project_name": "Perf run",
            "booking_type_id": api_booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": PROTECTION_HARD,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["request"]["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_a_developer_may_not_choose_a_level(
    client, developer_headers, api_booking_type, environment
):
    r = await client.post(
        "/api/v1/booking-requests",
        headers=developer_headers,
        json={
            "project_name": "Perf run",
            "booking_type_id": api_booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": PROTECTION_HARD,
        },
    )
    assert r.status_code == 403
    assert "protection" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_developer_may_send_the_inherited_level_unchanged(
    client, developer_headers, api_booking_type, environment
):
    """THE CARVE-OUT, AND IT IS LOAD-BEARING, NOT TIDY.

    BookingForm shows a non-admin their inherited level read-only and submits
    the whole form including it. Without this, the primary create journey 403s
    for everyone who is not an Admin or a Release Manager.
    """
    assert api_booking_type.default_protection_level == PROTECTION_SOFT
    r = await client.post(
        "/api/v1/booking-requests",
        headers=developer_headers,
        json={
            "project_name": "Perf run",
            "booking_type_id": api_booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": PROTECTION_SOFT,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["request"]["protection_level"] == PROTECTION_SOFT


@pytest.mark.asyncio
async def test_an_unknown_level_is_refused(
    client, auth_headers, api_booking_type, environment
):
    r = await client.post(
        "/api/v1/booking-requests",
        headers=auth_headers,
        json={
            "project_name": "Perf run",
            "booking_type_id": api_booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": "granite",
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_the_legacy_single_environment_path_inherits_too(
    client, auth_headers, hard_booking_type, environment
):
    """POST /bookings/ builds its own BookingRequest and must not skip this.

    Its response envelope is `BookingCreateResponse{booking, overlap_warnings}`
    (app/api/v1/schemas/booking.py) — unlike POST /booking-requests, it has no
    top-level `request` key.
    """
    r = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": environment.id,
            "project_name": "Legacy path",
            "booking_type_id": hard_booking_type.id,
            "start_date": "2026-10-01T09:00:00Z",
            "end_date": "2026-10-02T17:00:00Z",
        },
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["booking"]["protection_level"] == PROTECTION_HARD
