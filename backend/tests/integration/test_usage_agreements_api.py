"""Usage agreements: recorded, and — in A1 — read by nothing."""
import pytest
from sqlalchemy import select

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER
from app.db.models.project import UsageAgreement
from tests.factories import ensure_environment, ensure_project


@pytest.mark.asyncio
async def test_record_an_agreement_and_read_it_from_both_directions(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Mortgage")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    created = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id, "notes": "shared for UAT"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    # Both names travel with the row — never resolved against a capped list.
    assert created.json()["environment_name"] == env.name
    assert created.json()["project_name"] == "Mortgage"

    by_project = await client.get(
        f"/api/v1/projects/{project.id}/usage-agreements", headers=auth_headers
    )
    assert [a["environment_name"] for a in by_project.json()] == [env.name]
    assert int(by_project.headers[TOTAL_COUNT_HEADER]) == 1

    by_env = await client.get(
        f"/api/v1/environments/{env.id}/usage-agreements", headers=auth_headers
    )
    assert [a["project_name"] for a in by_env.json()] == ["Mortgage"]
    assert int(by_env.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_an_agreement_changes_no_booking_behaviour(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """A1 records; A3 enforces. Booking an environment the project has NO
    agreement for must still succeed.

    If this ever starts failing, someone has added enforcement without the
    rules — and A3 should be a deliberate change, not a surprise.
    """
    from datetime import datetime, timedelta, timezone

    project = await ensure_project(db_session, test_tenant.id, name="Unagreed")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    booked = await client.post(
        "/api/v1/booking-requests",
        json={
            "project_name": "no agreement anywhere",
            "project_id": project.id,
            "booking_type_id": test_booking_type.id,
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=1)).isoformat(),
            "environment_ids": [env.id],
        },
        headers=auth_headers,
    )
    assert booked.status_code in (200, 201), booked.text


@pytest.mark.asyncio
async def test_overlapping_windows_are_allowed_but_an_exact_duplicate_is_not(
    client, auth_headers, db_session, test_tenant
):
    """Deciding what an overlap MEANS is A3's job, once something reads them."""
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    url = f"/api/v1/projects/{project.id}/usage-agreements"

    first = await client.post(
        url,
        json={"environment_id": env.id,
              "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-06-30T00:00:00Z"},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text

    overlapping = await client.post(
        url,
        json={"environment_id": env.id,
              "starts_at": "2026-04-01T00:00:00Z", "ends_at": "2026-12-31T00:00:00Z"},
        headers=auth_headers,
    )
    assert overlapping.status_code == 201, overlapping.text

    exact = await client.post(
        url,
        json={"environment_id": env.id,
              "starts_at": "2026-01-01T00:00:00Z", "ends_at": "2026-06-30T00:00:00Z"},
        headers=auth_headers,
    )
    assert exact.status_code == 409, exact.text


@pytest.mark.asyncio
async def test_ends_before_starts_is_422(client, auth_headers, db_session, test_tenant):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    bad = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id,
              "starts_at": "2026-06-30T00:00:00Z", "ends_at": "2026-01-01T00:00:00Z"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_cannot_agree_against_another_tenants_environment(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    project = await ensure_project(db_session, test_tenant.id)
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id)
    await db_session.commit()

    refused = await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_both_list_endpoints_are_bounded(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    for url in (
        f"/api/v1/projects/{project.id}/usage-agreements",
        f"/api/v1/environments/{env.id}/usage-agreements",
    ):
        ok = await client.get(url, headers=auth_headers)
        assert ok.status_code == 200, ok.text
        assert TOTAL_COUNT_HEADER in ok.headers
        over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
        assert over.status_code == 422, over.text


@pytest.mark.asyncio
async def test_deleting_an_agreement_soft_deletes_it(
    client, auth_headers, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()
    aid = (await client.post(
        f"/api/v1/projects/{project.id}/usage-agreements",
        json={"environment_id": env.id}, headers=auth_headers,
    )).json()["id"]

    gone = await client.delete(
        f"/api/v1/projects/{project.id}/usage-agreements/{aid}", headers=auth_headers
    )
    assert gone.status_code == 204, gone.text

    listed = (await client.get(
        f"/api/v1/projects/{project.id}/usage-agreements", headers=auth_headers
    )).json()
    assert listed == []


# ── Defence in depth: a malformed row must not surface another tenant's name ──
# (the same pattern as test_projects_api's _view_query tests and
# test_welcome_pack's membership test — that filter has gone missing before in
# this task set, and no prior test caught it either time)


@pytest.mark.asyncio
async def test_environment_listing_ignores_a_malformed_cross_tenant_project_row(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Guards _agreement_query's Project join tenant filter.

    A malformed row — tenant_id is ours, but project_id points at another
    tenant's project — must not leak that project's name into this tenant's
    environment-side listing.
    """
    env = await ensure_environment(db_session, test_tenant.id)
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Their Project")
    await db_session.commit()

    db_session.add(UsageAgreement(
        tenant_id=test_tenant.id, project_id=theirs.id, environment_id=env.id,
    ))
    await db_session.commit()

    listed = await client.get(
        f"/api/v1/environments/{env.id}/usage-agreements", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert "Their Project" not in [a["project_name"] for a in listed.json()]


@pytest.mark.asyncio
async def test_project_listing_ignores_a_malformed_cross_tenant_environment_row(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Guards _agreement_query's Environment join tenant filter.

    A malformed row — tenant_id is ours, but environment_id points at another
    tenant's environment — must not leak that environment's name into this
    tenant's project-side listing.
    """
    project = await ensure_project(db_session, test_tenant.id)
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_environment(db_session, other_tenant.id)
    await db_session.commit()

    db_session.add(UsageAgreement(
        tenant_id=test_tenant.id, project_id=project.id, environment_id=theirs.id,
    ))
    await db_session.commit()

    listed = await client.get(
        f"/api/v1/projects/{project.id}/usage-agreements", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert theirs.name not in [a["environment_name"] for a in listed.json()]


@pytest.mark.asyncio
async def test_cannot_delete_an_agreement_whose_own_tenant_id_is_not_ours(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Guards delete_agreement's own tenant_id filter, independent of
    get_project's — a malformed row whose project_id legitimately belongs to
    our project but whose tenant_id column does not match must still 404,
    not be silently soft-deleted."""
    project = await ensure_project(db_session, test_tenant.id)
    env = await ensure_environment(db_session, test_tenant.id)
    other_tenant, _other_admin = await second_tenant_factory()
    await db_session.commit()

    agreement = UsageAgreement(
        tenant_id=other_tenant.id, project_id=project.id, environment_id=env.id,
    )
    db_session.add(agreement)
    await db_session.commit()
    await db_session.refresh(agreement)

    refused = await client.delete(
        f"/api/v1/projects/{project.id}/usage-agreements/{agreement.id}",
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text

    row = (
        await db_session.execute(
            select(UsageAgreement).where(UsageAgreement.id == agreement.id)
        )
    ).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is None, "must not be deleted by another tenant's admin"
