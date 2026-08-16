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
from app.db.models.booking import Booking
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.project import Project
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
async def test_a_booking_types_defaults_round_trip(client, auth_headers, api_lifecycle_template):
    """A4's ProjectCreate silently DISCARDED priority_rank because the schema
    had neither the field nor extra="forbid", and only a browser pass caught
    it. Read every field back through the API, not off the model."""
    r = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={
            "name": "Release cycle",
            "lifecycle_template_id": api_lifecycle_template.id,
            "default_protection_level": PROTECTION_HARD,
            "default_duration_minutes": 20160,
        },
    )
    assert r.status_code in (200, 201), r.text
    created = r.json()
    assert created["default_protection_level"] == PROTECTION_HARD
    assert created["default_duration_minutes"] == 20160

    listed = (await client.get("/api/v1/tenant/booking-types", headers=auth_headers)).json()
    mine = [t for t in listed if t["id"] == created["id"]][0]
    assert mine["default_protection_level"] == PROTECTION_HARD
    assert mine["default_duration_minutes"] == 20160


@pytest.mark.asyncio
async def test_an_unknown_key_on_a_booking_type_is_refused(client, auth_headers, api_lifecycle_template):
    r = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={
            "name": "Typo'd",
            "lifecycle_template_id": api_lifecycle_template.id,
            "default_protection": PROTECTION_HARD,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_duration_must_be_positive(client, auth_headers, api_lifecycle_template):
    r = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={
            "name": "Nonsense",
            "lifecycle_template_id": api_lifecycle_template.id,
            "default_duration_minutes": 0,
        },
    )
    assert r.status_code == 422


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
async def api_lifecycle_template(db_session, test_tenant) -> LifecycleTemplate:
    """A lifecycle template in test_tenant, for Task 6 tests that create a
    booking type through the API. The module-level `lifecycle_template`
    fixture above is scoped to `tenant` (see the comment above
    `api_booking_type`) and 404s "Lifecycle template not found" when handed
    to `client`/`auth_headers`, which log into `test_tenant` instead."""
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="booking",
        name="api-protection-level-test-lifecycle",
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


async def _login_as(
    client, db_session, test_tenant, username: str, role: str,
    is_master_admin: bool = False,
) -> dict:
    """Bearer headers for a fresh user of `role` in test_tenant.

    Follows the pattern in test_environment_groups_authz.py. `is_master_admin`
    is a separate flag from `role`, deliberately: `_may_set_protection`
    ORs a role check with `is_master_admin`, and a fixture that always paired
    `is_master_admin=True` with `role=Admin` could never isolate that second
    clause (a mutation deleting it would leave every such test green via the
    role check alone).
    """
    user = User(
        tenant_id=test_tenant.id,
        username=username,
        email=f"{username}@test.com",
        password_hash=get_password_hash("password123"),
        role=role,
        is_active=True,
        is_master_admin=is_master_admin,
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


@pytest_asyncio.fixture(scope="function")
async def release_manager_headers(client, db_session, test_tenant) -> dict:
    """Bearer headers for a Role.RELEASE_MANAGER user in test_tenant — the
    other role (besides Admin) that `_may_set_protection` names explicitly."""
    return await _login_as(
        client, db_session, test_tenant, "b4-release-manager", Role.RELEASE_MANAGER
    )


@pytest_asyncio.fixture(scope="function")
async def master_admin_non_privileged_role_headers(client, db_session, test_tenant) -> dict:
    """Bearer headers for a master admin whose own ROLE is Viewer — neither
    Admin nor Release Manager.

    Isolates the `or bool(user.is_master_admin)` clause of
    `_may_set_protection`: this user can only pass via that clause, so the
    fixture — and the test using it — is worthless if it instead gave the
    user `role=Role.ADMIN` alongside `is_master_admin=True`, which would
    satisfy the role check on its own and hide a deleted master-admin clause.
    """
    return await _login_as(
        client, db_session, test_tenant, "b4-master-admin", Role.VIEWER,
        is_master_admin=True,
    )


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
async def test_a_release_manager_may_override_the_inherited_level(
    client, release_manager_headers, api_booking_type, environment
):
    """`_may_set_protection` names Release Manager explicitly, alongside
    Admin — this is the branch fix-round-1 added coverage for. Mirrors
    test_an_admin_may_override_the_inherited_level above but for the other
    named role."""
    r = await client.post(
        "/api/v1/booking-requests",
        headers=release_manager_headers,
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
async def test_a_master_admin_may_override_the_inherited_level(
    client, master_admin_non_privileged_role_headers, api_booking_type, environment
):
    """Isolates `or bool(user.is_master_admin)` in `_may_set_protection`: the
    caller's own role is Viewer, so this can only pass via the master-admin
    clause — it fails if that clause is deleted (verified by mutation; see
    the fix-round-1 section of the task report).

    Matters beyond a coverage number: contention_service._is_admin's
    docstring records that the two places which forgot master admins showed
    one a control that 403'd on click.
    """
    r = await client.post(
        "/api/v1/booking-requests",
        headers=master_admin_non_privileged_role_headers,
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


# ── Task 3: the role gate on the UPDATE path ─────────────────────────────────
#
# `update_standard_fields` keys on the submitted key set — an omitted key
# means "leave alone" — so `current` for the role check is the STORED value,
# not a booking type's inherited default the way create_request uses it.


@pytest_asyncio.fixture(scope="function")
async def soft_request(
    db_session, test_tenant, developer_headers, api_booking_type, environment
) -> BookingRequest:
    """A BookingRequest at PROTECTION_SOFT, owned by the developer_headers
    user, with one Booking child.

    Depends on `developer_headers` rather than creating its own user so the
    "b4-developer" row `_login_as` creates is guaranteed to exist by the time
    this fixture runs; it then looks that user up by the fixed username to
    get an id for `booked_by`. `api_booking_type` and `environment` are both
    scoped to `test_tenant`, matching this fixture and the `client`-driven
    tests that consume it.
    """
    owner = (await db_session.execute(
        select(User).where(
            User.tenant_id == test_tenant.id, User.username == "b4-developer"
        )
    )).scalar_one()
    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="Soft request",
        booking_type_id=api_booking_type.id,
        start_date=now,
        end_date=now + timedelta(days=1),
        protection_level=PROTECTION_SOFT,
        booked_by=owner.id,
    )
    db_session.add(req)
    await db_session.flush()
    child = Booking(
        tenant_id=test_tenant.id,
        booking_request_id=req.id,
        environment_id=environment.id,
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    db_session.add(child)
    await db_session.flush()
    await db_session.refresh(req)
    return req


@pytest.mark.asyncio
async def test_an_admin_may_change_the_level_after_the_fact(
    client, auth_headers, soft_request
):
    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=auth_headers,
        json={"protection_level": PROTECTION_HARD},
    )
    assert r.status_code == 200, r.text
    assert r.json()["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_a_developer_may_not_change_the_level(
    client, developer_headers, soft_request
):
    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=developer_headers,
        json={"protection_level": PROTECTION_HARD},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_a_full_form_save_resending_an_unchanged_level_is_accepted(
    client, developer_headers, db_session, soft_request
):
    """The carve-out on the UPDATE path.

    An Admin marks someone's booking hard. The original booker then saves the
    edit form, which resends every standard field including the level they
    cannot change. That save must succeed — otherwise an admin action makes a
    booking permanently unsavable by its own owner.
    """
    soft_request.protection_level = PROTECTION_HARD
    await db_session.flush()

    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=developer_headers,
        json={
            "project_name": "Renamed by the booker",
            "protection_level": PROTECTION_HARD,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["project_name"] == "Renamed by the booker"
    assert r.json()["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_omitting_the_level_leaves_it_alone(
    client, developer_headers, db_session, soft_request
):
    """`update_standard_fields` keys on the submitted key set — an omitted key
    means "leave alone", so only an explicit value can change anything."""
    soft_request.protection_level = PROTECTION_HARD
    await db_session.flush()

    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=developer_headers,
        json={"project_name": "Still fine"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["protection_level"] == PROTECTION_HARD


# ── Fix round 1: an explicit `null` must not skip the role gate ─────────────
#
# `BookingRequestUpdate.protection_level` is `Optional[...] = None`, so a
# client can send a literal JSON `null`, not just omit the key. The
# endpoint's `exclude_unset` filter (booking_requests.py:348) lets that
# `null` into `values`, and `assert_may_set_protection`'s `submitted is None`
# branch means "not mentioned" — so without a guard, `null` sailed straight
# past the role check and 500'd on the column's NOT NULL constraint. `null`
# is a malformed VALUE for this field (there is no "no level" state), not an
# authorization question, so it is refused with a 422 for EVERY caller,
# admin included — the role does not rescue a bad value.


@pytest.mark.asyncio
async def test_a_developer_sending_an_explicit_null_level_is_a_422(
    client, developer_headers, soft_request
):
    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=developer_headers,
        json={"protection_level": None},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_an_admin_sending_an_explicit_null_level_is_also_a_422(
    client, auth_headers, soft_request
):
    """The role does not rescue a bad value — `null` fails for an Admin too,
    since assert_may_set_protection is never reached for a malformed value."""
    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=auth_headers,
        json={"protection_level": None},
    )
    assert r.status_code == 422, r.text


# ── Task 5: the list filter and the sort ─────────────────────────────────────
#
# `auth_headers` (tests/conftest.py) logs in as `test_user`, an Admin in
# `test_tenant` — the same tenant `api_booking_type` and `environment` above
# are scoped to. Bookings are inserted directly, exactly as `soft_request`
# above does: this filter/sort test only cares about protection_level, not
# booking validity, and going through the create API would run its overlap
# checks against 28 bookings sharing one environment for no reason.


async def _make_bookings(
    db_session, test_tenant, test_user, api_booking_type, environment, count, level,
) -> list[Booking]:
    now = datetime.now(timezone.utc)
    bookings: list[Booking] = []
    for i in range(count):
        req = BookingRequest(
            tenant_id=test_tenant.id,
            project_name=f"{level} booking {i}",
            booking_type_id=api_booking_type.id,
            start_date=now + timedelta(days=i),
            end_date=now + timedelta(days=i, hours=1),
            protection_level=level,
            booked_by=test_user.id,
        )
        db_session.add(req)
        await db_session.flush()
        booking = Booking(
            tenant_id=test_tenant.id,
            booking_request_id=req.id,
            environment_id=environment.id,
            start_date=req.start_date,
            end_date=req.end_date,
        )
        db_session.add(booking)
        bookings.append(booking)
    await db_session.flush()
    return bookings


@pytest_asyncio.fixture(scope="function")
async def soft_bookings_25(
    db_session, test_tenant, test_user, api_booking_type, environment
) -> list[Booking]:
    """25 bookings whose request is PROTECTION_SOFT, in test_tenant."""
    return await _make_bookings(
        db_session, test_tenant, test_user, api_booking_type, environment,
        25, PROTECTION_SOFT,
    )


@pytest_asyncio.fixture(scope="function")
async def hard_bookings_3(
    db_session, test_tenant, test_user, api_booking_type, environment
) -> list[Booking]:
    """3 bookings whose request is PROTECTION_HARD, in test_tenant."""
    return await _make_bookings(
        db_session, test_tenant, test_user, api_booking_type, environment,
        3, PROTECTION_HARD,
    )


@pytest_asyncio.fixture(scope="function")
async def project(db_session, test_tenant) -> Project:
    """A minimal tenant-scoped project — only for the filter-combination test
    below, to prove `?protection=` and `?project_id=` share one join rather
    than each opening its own."""
    p = Project(tenant_id=test_tenant.id, name="B4 filter combo project")
    db_session.add(p)
    await db_session.flush()
    await db_session.refresh(p)
    return p


@pytest.mark.asyncio
async def test_the_protection_filter_runs_in_sql_before_the_window(
    client, auth_headers, soft_bookings_25, hard_bookings_3
):
    """X-Total-Count must describe the FILTERED set, not the page and not the
    unfiltered total — otherwise the grid's footer lies and its paging is
    windowing the wrong result set."""
    r = await client.get(
        "/api/v1/bookings/?protection=hard&limit=2", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.headers["X-Total-Count"] == "3"
    assert len(r.json()) == 2
    assert all(b["protection_level"] == PROTECTION_HARD for b in r.json())


@pytest.mark.asyncio
async def test_omitting_the_filter_returns_both(
    client, auth_headers, soft_bookings_25, hard_bookings_3
):
    r = await client.get("/api/v1/bookings/?limit=100", headers=auth_headers)
    assert r.headers["X-Total-Count"] == "28"


@pytest.mark.asyncio
async def test_an_empty_protection_param_is_a_422_not_an_ignored_one(
    client, auth_headers
):
    """Nothing may ever emit `?protection=`. The UI spells no-selection as an
    OMITTED KEY (`any` in the URL, mapped to undefined), never `all` —
    buildParams' own sentinel — and never ''."""
    r = await client.get("/api/v1/bookings/?protection=", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_protection_value_is_a_422(client, auth_headers):
    r = await client.get("/api/v1/bookings/?protection=granite", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sorting_by_protection_orders_rendered_rows(
    client, auth_headers, soft_bookings_25, hard_bookings_3
):
    """Assert RENDERED ROW ORDER, never the emitted SQL token — the pagination
    pilot pinned the token and stayed green while the order users saw was
    wrong."""
    r = await client.get(
        "/api/v1/bookings/?sort_by=protection_level&sort_dir=asc&limit=100",
        headers=auth_headers,
    )
    levels = [b["protection_level"] for b in r.json()]
    assert levels == sorted(levels)
    assert levels[0] == PROTECTION_HARD  # 'hard' < 'soft'


@pytest.mark.asyncio
async def test_an_unknown_sort_by_is_a_422_not_a_silent_fallback(
    client, auth_headers
):
    r = await client.get("/api/v1/bookings/?sort_by=protection", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_protection_and_project_filters_combine(
    client, auth_headers, hard_bookings_3, project
):
    """Both list filters hang off ONE join (A3's rule). If a future change adds
    a second join for `protection`, this still passes but SQLAlchemy emits a
    duplicate-join warning — check the run's output, not just this assertion."""
    r = await client.get(
        f"/api/v1/bookings/?protection=hard&project_id={project.id}&limit=100",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
