"""booking_request.project_id — the link, and the IDOR surface it adds.

Two new FK write paths arrive here (create and update). Across the two
preceding sub-projects the same missing tenant_id filter appeared four times
and was never once caught by a test that already existed, so each path gets one
written for it deliberately.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from tests.factories import ensure_environment, ensure_project


def _payload(booking_type_id: int, environment_id: int, **extra) -> dict:
    now = datetime.now(timezone.utc)
    body = {
        "project_name": "Regression sweep",   # free text — the UI calls it Purpose
        "booking_type_id": booking_type_id,
        "start_date": now.isoformat(),
        "end_date": (now + timedelta(days=1)).isoformat(),
        "environment_ids": [environment_id],
    }
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_the_project_name_travels_with_the_booking(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """`project_name_link`, NOT `project_name` — that key is already taken on
    this model by the free text, and shadowing it would silently change what
    every existing client reads."""
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()["request"]
    assert body["project_id"] == project.id
    assert body["project_name_link"] == "Mortgage"
    # The two fields are different values and must stay distinguishable.
    assert body["project_name"] == "Regression sweep"


@pytest.mark.asyncio
async def test_a_booking_without_a_project_is_still_valid(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """The link is optional everywhere — A1 reports the gap, never blocks."""
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id),
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()["request"]
    assert body["project_id"] is None
    assert body["project_name_link"] is None


@pytest.mark.asyncio
async def test_cannot_book_against_another_tenants_project_on_create(
    client, auth_headers, db_session, test_tenant, test_booking_type,
    second_tenant_factory,
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    refused = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=theirs.id),
        headers=auth_headers,
    )
    # 404, never 403 — a 403 confirms the project exists in another tenant.
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_cannot_book_against_another_tenants_project_on_update(
    client, auth_headers, db_session, test_tenant, test_booking_type,
    second_tenant_factory,
):
    """The create path is the obvious one. The UPDATE path is where this class
    of gap has actually hidden in this codebase.

    NOTE ON THE ROUTE: the brief assumed `PATCH /booking-requests/{id}`, but
    booking requests only expose PATCH on two narrower sub-resources —
    `/standard-fields` and `/custom-fields` (see app/api/v1/booking_requests.py).
    `project_id` is a standard field, so this hits `/standard-fields`.
    """
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    refused = await client.patch(
        f"/api/v1/booking-requests/{rid}/standard-fields",
        json={"project_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_the_list_filters_by_project_in_sql(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    mortgage = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    savings = await ensure_project(db_session, test_tenant.id, name="Savings")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    for project in (mortgage, savings):
        made = await client.post(
            "/api/v1/booking-requests",
            json=_payload(test_booking_type.id, env.id, project_id=project.id),
            headers=auth_headers,
        )
        assert made.status_code in (200, 201), made.text

    filtered = await client.get(
        f"/api/v1/booking-requests?project_id={mortgage.id}", headers=auth_headers
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["project_name_link"] == "Mortgage"
    # A Python-side filter would window the page BEFORE filtering, so the total
    # must describe the filtered set, not the whole one.
    assert int(filtered.headers["X-Total-Count"]) == 1


@pytest.mark.asyncio
async def test_an_archived_projects_name_still_renders_on_its_bookings(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """Blanking the name would lose information the row still carries — the
    same call B3b made for a soft-deleted operating group."""
    project = await ensure_project(db_session, test_tenant.id, name="Wound Down")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    gone = await client.delete(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert gone.status_code == 204, gone.text

    still = await client.get(f"/api/v1/booking-requests/{rid}", headers=auth_headers)
    assert still.status_code == 200, still.text
    assert still.json()["project_name_link"] == "Wound Down"


# ── Finding 1: resubmitting the row's OWN archived project must not 404 ─────


@pytest.mark.asyncio
async def test_resubmitting_the_same_archived_project_on_update_succeeds(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """A full-form PATCH resubmitting the row's own project id — now archived —
    while changing an unrelated field must not 404. Reproduced against the
    unfixed code: project_service.get_project filters deleted_at IS NULL, so
    this 404'd even though nothing about the project link was changing."""
    project = await ensure_project(db_session, test_tenant.id, name="Archived Later")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    archived = await client.delete(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert archived.status_code == 204, archived.text

    saved = await client.patch(
        f"/api/v1/booking-requests/{rid}/standard-fields",
        json={"project_name": "renamed", "project_id": project.id},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["project_name"] == "renamed"
    assert body["project_id"] == project.id
    assert body["project_name_link"] == "Archived Later"


@pytest.mark.asyncio
async def test_assigning_a_different_archived_project_on_update_still_404s(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """The exemption is narrow: it only covers resubmitting the CURRENT value.
    A NEW assignment to a different archived project must still 404."""
    original = await ensure_project(db_session, test_tenant.id, name="Original")
    other = await ensure_project(db_session, test_tenant.id, name="Also Archived")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=original.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    archived = await client.delete(f"/api/v1/projects/{other.id}", headers=auth_headers)
    assert archived.status_code == 204, archived.text

    refused = await client.patch(
        f"/api/v1/booking-requests/{rid}/standard-fields",
        json={"project_id": other.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


# ── Finding 2: the update path's happy case was never asserted at all ───────


@pytest.mark.asyncio
async def test_the_project_link_persists_after_update(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """PATCH the link onto a row that had none, assert the response carries
    both the id and the resolved name, then re-GET and confirm it stuck."""
    project = await ensure_project(db_session, test_tenant.id, name="Newly Linked")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    saved = await client.patch(
        f"/api/v1/booking-requests/{rid}/standard-fields",
        json={"project_id": project.id},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["project_id"] == project.id
    assert saved.json()["project_name_link"] == "Newly Linked"

    reget = await client.get(f"/api/v1/booking-requests/{rid}", headers=auth_headers)
    assert reget.status_code == 200, reget.text
    assert reget.json()["project_id"] == project.id
    assert reget.json()["project_name_link"] == "Newly Linked"


# ── Finding 4: both PATCH responses must carry the name, not just project_id ─


@pytest.mark.asyncio
async def test_standard_fields_patch_response_carries_the_project_name(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    project = await ensure_project(db_session, test_tenant.id, name="Standard Path")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    # Patch an unrelated standard field — the project link is untouched.
    saved = await client.patch(
        f"/api/v1/booking-requests/{rid}/standard-fields",
        json={"notes": "updated notes"},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["project_name_link"] == "Standard Path"


@pytest.mark.asyncio
async def test_custom_fields_patch_response_carries_the_project_name(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    project = await ensure_project(db_session, test_tenant.id, name="Custom Path")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    saved = await client.patch(
        f"/api/v1/booking-requests/{rid}/custom-fields",
        json={"values": {"colour": "blue"}},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["project_name_link"] == "Custom Path"


# ── Finding 5: get_project_names' own tenant filter, unreachable via the API ─


@pytest.mark.asyncio
async def test_a_malformed_cross_tenant_project_row_does_not_leak_its_name(
    client, auth_headers, db_session, test_tenant, test_user, test_booking_type,
    second_tenant_factory,
):
    """No write path can produce this row — both create and update refuse a
    cross-tenant project id. This guards get_project_names' own tenant filter
    directly, in case that write-side defence is ever the only thing standing
    between a malformed row and a name leak."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Not Ours")
    await db_session.commit()

    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="Regression sweep",
        project_id=theirs.id,
        booking_type_id=test_booking_type.id,
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(days=1),
        booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.commit()
    await db_session.refresh(req)

    fetched = await client.get(f"/api/v1/booking-requests/{req.id}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["project_name_link"] is None


# ── GET /bookings (per-environment BookingResponse rows) ────────────────────
#
# BookingList.tsx renders GET /bookings, not GET /booking-requests — the
# per-environment shape, one row per Booking, is what Task 7 could not
# convert (only booking_request carries project_id). These tests cover the
# gap closed here: the same project_id/project_name_link pair added to
# BookingResponse the same way, populated from the parent booking_request in
# app/api/v1/bookings.py's _to_response.


@pytest.mark.asyncio
async def test_the_bookings_list_carries_project_link_distinct_from_purpose(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """project_name (free text, labelled "Purpose" in the UI) and
    project_name_link (the linked project's name) are different values on the
    same row and must stay distinguishable — never swapped."""
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=project.id),
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    booking_id = created.json()["request"]["bookings"][0]["id"]

    listed = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(b for b in listed.json() if b["id"] == booking_id)
    assert row["project_id"] == project.id
    assert row["project_name_link"] == "Mortgage"
    assert row["project_name"] == "Regression sweep"  # the free-text Purpose, untouched


@pytest.mark.asyncio
async def test_a_booking_without_a_project_link_still_lists(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id),
        headers=auth_headers,
    )
    assert created.status_code in (200, 201), created.text
    booking_id = created.json()["request"]["bookings"][0]["id"]

    listed = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(b for b in listed.json() if b["id"] == booking_id)
    assert row["project_id"] is None
    assert row["project_name_link"] is None


@pytest.mark.asyncio
async def test_the_bookings_list_filters_by_project_in_sql(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """The endpoint is bounded (pagination()), so the filter must run in SQL —
    a Python-side filter applied after fetch_page would window the page
    before filtering, and X-Total-Count would still describe the unfiltered
    set."""
    mortgage = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    savings = await ensure_project(db_session, test_tenant.id, name="Savings")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    booking_ids = {}
    for project in (mortgage, savings):
        made = await client.post(
            "/api/v1/booking-requests",
            json=_payload(test_booking_type.id, env.id, project_id=project.id),
            headers=auth_headers,
        )
        assert made.status_code in (200, 201), made.text
        booking_ids[project.name] = made.json()["request"]["bookings"][0]["id"]

    filtered = await client.get(
        f"/api/v1/bookings/?project_id={mortgage.id}", headers=auth_headers
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert [r["id"] for r in rows] == [booking_ids["Mortgage"]]
    assert rows[0]["project_name_link"] == "Mortgage"
    # A Python-side filter applied after the query would leave this describing
    # the unfiltered set (2), not the filtered one (1).
    assert int(filtered.headers["X-Total-Count"]) == 1


@pytest.mark.asyncio
async def test_bookings_list_does_not_leak_a_cross_tenant_projects_name(
    client, auth_headers, db_session, test_tenant, test_user, test_booking_type,
    second_tenant_factory,
):
    """GET /bookings resolves project_name_link via the same tenant-scoped
    project_service.get_project_names lookup as booking-requests, but at its
    own call site — guard it there too, since dropping the tenant_id argument
    in app/api/v1/bookings.py would not be caught by the booking-requests
    test above."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Not Ours")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    # No write path can produce this row (both create and update on
    # booking-requests refuse a cross-tenant project id) — construct it
    # directly, as the equivalent booking-requests guard above does.
    req = BookingRequest(
        tenant_id=test_tenant.id,
        project_name="Regression sweep",
        project_id=theirs.id,
        booking_type_id=test_booking_type.id,
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc) + timedelta(days=1),
        booked_by=test_user.id,
    )
    db_session.add(req)
    await db_session.flush()
    booking = Booking(
        tenant_id=test_tenant.id,
        booking_request_id=req.id,
        environment_id=env.id,
        start_date=req.start_date,
        end_date=req.end_date,
        status="draft",
    )
    db_session.add(booking)
    await db_session.commit()
    await db_session.refresh(booking)

    listed = await client.get("/api/v1/bookings/", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(b for b in listed.json() if b["id"] == booking.id)
    assert row["project_id"] == theirs.id
    assert row["project_name_link"] is None


# ── A3 prerequisite: a booking's project must be correctable ────────────────


@pytest.mark.asyncio
async def test_a_bookings_project_can_be_corrected_after_creation(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """A3 warns on project_id, so a mislinked booking must be fixable.

    Before this test existed, nothing asserted that PATCH .../standard-fields
    actually accepts project_id — STANDARD_REQUEST_FIELDS already contains
    it (booking_request_service.py), but the only remedy anyone had verified
    was delete-and-recreate.
    """
    wrong = await ensure_project(db_session, test_tenant.id, name="Wrong Project")
    right = await ensure_project(db_session, test_tenant.id, name="Right Project")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=wrong.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    fixed = await client.patch(
        f"/api/v1/booking-requests/{rid}/standard-fields",
        json={"project_id": right.id},
        headers=auth_headers,
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["project_id"] == right.id
    assert fixed.json()["project_name_link"] == "Right Project"

    # And it persisted, not merely echoed.
    again = await client.get(f"/api/v1/booking-requests/{rid}", headers=auth_headers)
    assert again.json()["project_id"] == right.id
