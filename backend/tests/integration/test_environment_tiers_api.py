"""Tier configuration endpoints."""
import pytest


@pytest.mark.asyncio
async def test_list_returns_the_seeded_tiers_in_progression_order(
    client, auth_headers, db_session, test_tenant
):
    from app.services.environment_tier_defaults import (
        seed_environment_tier_defaults_for_tenant,
    )

    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()

    resp = await client.get("/api/v1/environment-tiers/", headers=auth_headers)
    assert resp.status_code == 200
    names = [row["name"] for row in resp.json()]
    assert names.index("Dev") < names.index("UAT") < names.index("Production")
    assert resp.headers["X-Total-Count"] == "8"


@pytest.mark.asyncio
async def test_create_rejects_a_duplicate_name_case_insensitively(
    client, auth_headers, db_session, test_tenant
):
    from app.services.environment_tier_defaults import (
        seed_environment_tier_defaults_for_tenant,
    )

    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "sit"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_then_update_then_soft_delete(client, auth_headers):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Integration", "color": "#123456", "display_order": 25},
    )
    assert created.status_code == 201
    tier_id = created.json()["id"]
    assert created.json()["category"] is None
    assert created.json()["is_active"] is True

    updated = await client.patch(
        f"/api/v1/environment-tiers/{tier_id}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False

    deleted = await client.delete(
        f"/api/v1/environment-tiers/{tier_id}", headers=auth_headers
    )
    assert deleted.status_code == 204

    listed = await client.get("/api/v1/environment-tiers/", headers=auth_headers)
    assert tier_id not in [row["id"] for row in listed.json()]


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    resp = await client.get(
        "/api/v1/environment-tiers/?sort_by=colour", headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_another_tenants_tier_is_invisible_and_unreachable(
    client, auth_headers, db_session, second_tenant_factory
):
    from app.db.models.environment_tier import EnvironmentTier

    other, _ = await second_tenant_factory()
    theirs = EnvironmentTier(tenant_id=other.id, name="Their Tier")
    db_session.add(theirs)
    await db_session.commit()

    listed = await client.get("/api/v1/environment-tiers/", headers=auth_headers)
    assert theirs.id not in [row["id"] for row in listed.json()]

    fetched = await client.get(
        f"/api/v1/environment-tiers/{theirs.id}", headers=auth_headers
    )
    assert fetched.status_code == 404
