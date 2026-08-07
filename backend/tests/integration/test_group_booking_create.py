"""Task 4: booking a group.

`environment_group_ids` on `BookingRequestCreate` lets a booking name a group
instead of (or alongside) listing environments by hand. At create time the
group is expanded to its LIVE members and each resulting `Booking` carries
`environment_group_id` as provenance — membership is frozen from that point
on; the booking never re-reads the group later.

Read tests/integration/test_project_links_bookings.py first: `POST
/booking-requests` returns `{request, detected_conflicts}`, not the bare
request body, and that shape is reused throughout this file.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.environment import EnvironmentStatus
from app.db.models.environment_group import EnvironmentGroupMember
from app.services import environment_group_service
from app.api.v1.schemas.environment_group import MemberCreate
from tests.factories import ensure_environment, ensure_environment_group


def _payload(booking_type_id: int, **extra) -> dict:
    now = datetime.now(timezone.utc)
    body = {
        "project_name": "Group booking sweep",
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


# ── Booking a group expands to its live members ─────────────────────────────


@pytest.mark.asyncio
async def test_booking_a_group_creates_one_booking_per_live_member_and_names_the_group(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Mortgage SIT")
    env_a = await ensure_environment(db_session, test_tenant.id, slot=1)
    env_b = await ensure_environment(db_session, test_tenant.id, slot=2)
    await _add_member(db_session, group, env_a, test_tenant.id)
    await _add_member(db_session, group, env_b, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    bookings = created.json()["request"]["bookings"]
    assert len(bookings) == 2
    env_ids = {b["environment_id"] for b in bookings}
    assert env_ids == {env_a.id, env_b.id}
    for b in bookings:
        assert b["environment_group_id"] == group.id
        assert b["environment_group_name"] == "Mortgage SIT"


@pytest.mark.asyncio
async def test_a_hand_picked_environment_alongside_a_group_has_null_group_id(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """The two kinds coexist on one request — that is what makes the atomic
    unit the group's members rather than the whole request."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Savings SIT")
    grouped_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    hand_env = await ensure_environment(db_session, test_tenant.id, slot=2)
    await _add_member(db_session, group, grouped_env, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(
            test_booking_type.id,
            environment_ids=[hand_env.id],
            environment_group_ids=[group.id],
        ),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    bookings = created.json()["request"]["bookings"]
    assert len(bookings) == 2
    by_env = {b["environment_id"]: b for b in bookings}
    assert by_env[grouped_env.id]["environment_group_id"] == group.id
    assert by_env[grouped_env.id]["environment_group_name"] == "Savings SIT"
    assert by_env[hand_env.id]["environment_group_id"] is None
    assert by_env[hand_env.id]["environment_group_name"] is None


# ── Overlap rules ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_environment_reached_via_two_groups_is_refused_naming_both(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    shared_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    group_a = await ensure_environment_group(db_session, test_tenant.id, name="Group A")
    group_b = await ensure_environment_group(db_session, test_tenant.id, name="Group B")
    await _add_member(db_session, group_a, shared_env, test_tenant.id)
    await _add_member(db_session, group_b, shared_env, test_tenant.id)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(
            test_booking_type.id,
            environment_group_ids=[group_a.id, group_b.id],
        ),
        headers=auth_headers,
    )
    assert refused.status_code == 400, refused.text
    detail = refused.json()["detail"]
    assert "Group A" in detail
    assert "Group B" in detail


@pytest.mark.asyncio
async def test_an_environment_reached_via_a_group_and_by_hand_is_refused(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    shared_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    group = await ensure_environment_group(db_session, test_tenant.id, name="Group C")
    await _add_member(db_session, group, shared_env, test_tenant.id)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(
            test_booking_type.id,
            environment_ids=[shared_env.id],
            environment_group_ids=[group.id],
        ),
        headers=auth_headers,
    )
    assert refused.status_code == 400, refused.text
    assert "Group C" in refused.json()["detail"]


# ── "At least one environment", now spanning two fields ─────────────────────


@pytest.mark.asyncio
async def test_a_group_alone_satisfies_at_least_one_environment(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Solo Group")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await _add_member(db_session, group, env, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_ids=[], environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert len(created.json()["request"]["bookings"]) == 1


@pytest.mark.asyncio
async def test_empty_environment_ids_and_empty_group_ids_is_400_not_422(
    client, auth_headers, test_booking_type
):
    """Removing `min_length=1` from `environment_ids` turns an empty request
    from a Pydantic 422 into the service's 400 — a deliberate behaviour
    change nothing else in the suite asserts either way. Guard it
    explicitly, both the status code and that it is not the 422 shape."""
    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_ids=[], environment_group_ids=[]),
        headers=auth_headers,
    )
    assert refused.status_code == 400, refused.text
    assert refused.status_code != 422
    assert "environment" in refused.json()["detail"].lower()


@pytest.mark.asyncio
async def test_an_empty_group_is_refused_by_name(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Mortgage SIT")
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "Environment group 'Mortgage SIT' has no environments"


@pytest.mark.asyncio
async def test_a_group_whose_only_members_were_soft_deleted_is_treated_as_empty(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """delete_group cascades a soft delete to membership rows — a deleted
    group must hit the empty-group rule, not produce zero silent bookings."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Doomed Group")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await _add_member(db_session, group, env, test_tenant.id)
    await db_session.commit()

    deleted = await client.delete(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text

    # A deleted group also 404s via get_group, so the empty-group message is
    # unreachable through this exact path — assert the 404 instead, which is
    # the actual behaviour: get_group runs before the membership query.
    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


# ── A soft-deleted environment is not a live member ──────────────────────────


@pytest.mark.asyncio
async def test_a_soft_deleted_environments_membership_is_not_live(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """Unlike status, deletion DOES filter: `_member_query`'s definition of a
    live member is 'membership row undeleted AND environment undeleted'.
    Soft-delete the environment itself (not the membership row) and confirm
    the group still expands, but only to its one remaining live member."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Half Gone Group")
    gone_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    live_env = await ensure_environment(db_session, test_tenant.id, slot=2)
    await _add_member(db_session, group, gone_env, test_tenant.id)
    await _add_member(db_session, group, live_env, test_tenant.id)
    gone_env.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    bookings = created.json()["request"]["bookings"]
    assert len(bookings) == 1
    assert bookings[0]["environment_id"] == live_env.id


# ── Tenant isolation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_malformed_cross_tenant_membership_row_does_not_leak_the_environment(
    client, auth_headers, db_session, test_tenant, test_booking_type, second_tenant_factory
):
    """No write path can produce this row — `add_member` tenant-scopes both
    the group and the environment lookup. Construct it directly, the same
    way test_project_links_bookings.py guards get_project_names' own tenant
    filter: this proves the member query's `Environment.tenant_id ==
    tenant_id` clause is load-bearing on its own, independent of whatever
    stopped the row from being created."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id, slot=1)
    group = await ensure_environment_group(db_session, test_tenant.id, name="Malformed Group")
    member = EnvironmentGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, environment_id=theirs.id,
    )
    db_session.add(member)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    # The group has one membership row but it doesn't resolve to a live,
    # same-tenant environment, so this must be the empty-group 400 — never a
    # 201 that booked the other tenant's environment.
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "Environment group 'Malformed Group' has no environments"


@pytest.mark.asyncio
async def test_another_tenants_group_is_404(
    client, auth_headers, db_session, test_tenant, test_booking_type, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment_group(db_session, other_tenant.id, name="Not Ours")
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[theirs.id]),
        headers=auth_headers,
    )
    # 404, never 403 — a 403 confirms the group exists in another tenant.
    assert refused.status_code == 404, refused.text


# ── Status is not a filter on membership ─────────────────────────────────────


@pytest.mark.asyncio
async def test_an_inactive_or_maintenance_environment_still_expands_into_a_booking(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """Booking a future window on an environment that is currently down is
    legitimate, and create_request performs no status check on
    environment_ids either. Silently dropping a member would hand the user a
    partial group with no indication which environment vanished — assert the
    member COUNT, not just a 201."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Mixed Status Group")
    active_env = await ensure_environment(db_session, test_tenant.id, slot=1)
    inactive_env = await ensure_environment(db_session, test_tenant.id, slot=2)
    maintenance_env = await ensure_environment(db_session, test_tenant.id, slot=3)
    inactive_env.status = EnvironmentStatus.INACTIVE
    maintenance_env.status = EnvironmentStatus.MAINTENANCE
    await _add_member(db_session, group, active_env, test_tenant.id)
    await _add_member(db_session, group, inactive_env, test_tenant.id)
    await _add_member(db_session, group, maintenance_env, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    bookings = created.json()["request"]["bookings"]
    assert len(bookings) == 3
    assert {b["environment_id"] for b in bookings} == {
        active_env.id, inactive_env.id, maintenance_env.id
    }


# ── Membership is frozen at create ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_membership_is_frozen_at_create(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """environment_group_id is provenance, not a live link — a booking's
    environments must never be re-resolved by re-reading the group."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Frozen Group")
    env_keep = await ensure_environment(db_session, test_tenant.id, slot=1)
    env_remove = await ensure_environment(db_session, test_tenant.id, slot=2)
    env_added_later = await ensure_environment(db_session, test_tenant.id, slot=3)
    await _add_member(db_session, group, env_keep, test_tenant.id)
    row_remove = await _add_member(db_session, group, env_remove, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    rid = created.json()["request"]["id"]
    original_env_ids = {b["environment_id"] for b in created.json()["request"]["bookings"]}
    assert original_env_ids == {env_keep.id, env_remove.id}

    # Now mutate the group's membership: add one, remove one.
    member_remove_id = row_remove[0].id
    await client.post(
        f"/api/v1/environment-groups/{group.id}/members",
        json={"environment_id": env_added_later.id},
        headers=auth_headers,
    )
    removed = await client.delete(
        f"/api/v1/environment-groups/{group.id}/members/{member_remove_id}",
        headers=auth_headers,
    )
    assert removed.status_code == 204, removed.text

    reget = await client.get(f"/api/v1/booking-requests/{rid}", headers=auth_headers)
    assert reget.status_code == 200, reget.text
    bookings = reget.json()["bookings"]
    assert len(bookings) == 2
    assert {b["environment_id"] for b in bookings} == original_env_ids
    assert env_added_later.id not in {b["environment_id"] for b in bookings}


# ── What happens next: the group is soft-deleted after the booking exists ───


@pytest.mark.asyncio
async def test_a_group_booking_survives_the_groups_own_deletion(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """The request must still be readable, its bookings must still count and
    keep their environment_group_id, and the group's name must still render
    — get_group_names deliberately does NOT filter deleted_at, unlike
    get_group, which validates writes."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Soon Gone")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await _add_member(db_session, group, env, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    rid = created.json()["request"]["id"]

    deleted = await client.delete(
        f"/api/v1/environment-groups/{group.id}", headers=auth_headers
    )
    assert deleted.status_code == 204, deleted.text

    reget = await client.get(f"/api/v1/booking-requests/{rid}", headers=auth_headers)
    assert reget.status_code == 200, reget.text
    bookings = reget.json()["bookings"]
    assert len(bookings) == 1
    assert bookings[0]["environment_group_id"] == group.id
    assert bookings[0]["environment_group_name"] == "Soon Gone"

    # GET /bookings/ (the per-environment shape) must render the same name.
    listed = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(b for b in listed.json() if b["id"] == bookings[0]["id"])
    assert row["environment_group_id"] == group.id
    assert row["environment_group_name"] == "Soon Gone"


# ── Uniqueness of environment_group_ids itself, symmetric with environment_ids ──


@pytest.mark.asyncio
async def test_duplicate_environment_group_ids_are_refused(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    group = await ensure_environment_group(db_session, test_tenant.id, name="Dup Group")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await _add_member(db_session, group, env, test_tenant.id)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id, group.id]),
        headers=auth_headers,
    )
    assert refused.status_code == 400, refused.text
    assert "environment_group_ids must be unique" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_environment_ids_still_refused_unchanged(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """Task 4 adds group overlap rules; it must not touch the pre-existing
    duplicate hand-picked-environment_ids rule
    (tests/test_booking_request_service.py:90 covers the service directly —
    this is the same rule exercised through the API)."""
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_ids=[env.id, env.id]),
        headers=auth_headers,
    )
    assert refused.status_code == 400, refused.text
    assert "environment_ids must be unique" in refused.json()["detail"]


# ── The single-booking GET must carry the same group info as the list ───────


@pytest.mark.asyncio
async def test_getting_a_single_grouped_booking_carries_the_group_name(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """GET /bookings/{id} is a distinct call site from GET /bookings/ (list)
    — both must resolve `environment_group_name` independently, since each
    endpoint in app/api/v1/bookings.py builds its own group_names lookup."""
    group = await ensure_environment_group(db_session, test_tenant.id, name="Direct Fetch Group")
    env = await ensure_environment(db_session, test_tenant.id, slot=1)
    await _add_member(db_session, group, env, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, environment_group_ids=[group.id]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    booking_id = created.json()["request"]["bookings"][0]["id"]

    fetched = await client.get(f"/api/v1/bookings/{booking_id}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["environment_group_id"] == group.id
    assert fetched.json()["environment_group_name"] == "Direct Fetch Group"
