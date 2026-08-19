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


# --- B5: the per-tier idle_threshold_days override -------------------------
#
# NULL means "inherit the tenant's environment_lifecycle_policy.idle_threshold_days"
# — a legitimate state, not a missing value. update_tier reads this field via
# `model_fields_set` rather than `is not None` specifically so an explicit
# null can CLEAR a stored override, unlike every other nullable field on this
# schema (description, color), which the service only ever sets. Tests 5 and
# 6 below only mean something as a pair: 5 proves an explicit null clears it,
# 6 proves an omitted key does NOT — a one-word change from
# `model_fields_set` back to `is not None` would silently pass 6 while
# failing 5, and the tier would be stuck at its last value forever with a UI
# that shows a blank box.


@pytest.mark.asyncio
async def test_create_with_idle_threshold_days_round_trips_on_the_response(
    client, auth_headers
):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Perf", "idle_threshold_days": 45},
    )
    assert created.status_code == 201
    assert created.json()["idle_threshold_days"] == 45


@pytest.mark.asyncio
async def test_create_without_idle_threshold_days_comes_back_null_not_a_default(
    client, auth_headers
):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Training"},
    )
    assert created.status_code == 201
    assert created.json()["idle_threshold_days"] is None


@pytest.mark.asyncio
async def test_update_sets_an_override_on_a_tier_that_had_none(client, auth_headers):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "DR"},
    )
    tier_id = created.json()["id"]
    assert created.json()["idle_threshold_days"] is None

    updated = await client.patch(
        f"/api/v1/environment-tiers/{tier_id}",
        headers=auth_headers,
        json={"idle_threshold_days": 90},
    )
    assert updated.status_code == 200
    assert updated.json()["idle_threshold_days"] == 90


@pytest.mark.asyncio
async def test_update_changes_an_existing_override_to_a_different_number(
    client, auth_headers
):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Sandbox", "idle_threshold_days": 14},
    )
    tier_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/environment-tiers/{tier_id}",
        headers=auth_headers,
        json={"idle_threshold_days": 21},
    )
    assert updated.status_code == 200
    assert updated.json()["idle_threshold_days"] == 21


@pytest.mark.asyncio
async def test_update_clearing_the_override_sends_explicit_null(client, auth_headers):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Load Test", "idle_threshold_days": 60},
    )
    tier_id = created.json()["id"]
    assert created.json()["idle_threshold_days"] == 60

    updated = await client.patch(
        f"/api/v1/environment-tiers/{tier_id}",
        headers=auth_headers,
        json={"idle_threshold_days": None},
    )
    assert updated.status_code == 200
    assert updated.json()["idle_threshold_days"] is None


@pytest.mark.asyncio
async def test_update_omitting_idle_threshold_days_leaves_an_override_alone(
    client, auth_headers
):
    created = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "UAT2", "idle_threshold_days": 60},
    )
    tier_id = created.json()["id"]

    # No idle_threshold_days key at all — same shape as an ordinary edit of
    # an unrelated field (display_order here), the way a full-form save that
    # never touched this field would send it.
    updated = await client.patch(
        f"/api/v1/environment-tiers/{tier_id}",
        headers=auth_headers,
        json={"display_order": 5},
    )
    assert updated.status_code == 200
    assert updated.json()["idle_threshold_days"] == 60


@pytest.mark.asyncio
async def test_idle_threshold_days_out_of_range_is_422(client, auth_headers):
    too_low = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Bad Low", "idle_threshold_days": 0},
    )
    assert too_low.status_code == 422

    too_high = await client.post(
        "/api/v1/environment-tiers/",
        headers=auth_headers,
        json={"name": "Bad High", "idle_threshold_days": 3651},
    )
    assert too_high.status_code == 422
