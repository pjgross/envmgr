"""booking_request.project_id — the link, and the IDOR surface it adds.

Two new FK write paths arrive here (create and update). Across the two
preceding sub-projects the same missing tenant_id filter appeared four times
and was never once caught by a test that already existed, so each path gets one
written for it deliberately.
"""
from datetime import datetime, timedelta, timezone

import pytest

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
