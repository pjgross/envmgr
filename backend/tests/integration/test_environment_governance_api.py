"""Tier, owner and expiry on the environment API."""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.environment_tier import EnvironmentTier


async def _tier(db_session, tenant_id, name="SIT", **kwargs):
    tier = EnvironmentTier(tenant_id=tenant_id, name=name, **kwargs)
    db_session.add(tier)
    await db_session.commit()
    await db_session.refresh(tier)
    return tier


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()


@pytest.mark.asyncio
async def test_create_requires_tier_owner_and_expiry(
    client, auth_headers, db_session, test_tenant
):
    tier = await _tier(db_session, test_tenant.id)

    missing = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "no-owner", "tier_id": tier.id},
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_create_returns_tier_and_owner_names_on_the_row(
    client, auth_headers, db_session, test_tenant, test_user
):
    tier = await _tier(db_session, test_tenant.id, color="#42A5F5")

    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "sit-1",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    # Display names travel with the row — never resolved client-side against a
    # capped collection.
    assert body["tier_name"] == "SIT"
    assert body["tier_color"] == "#42A5F5"
    assert body["owner_username"] == test_user.username


@pytest.mark.asyncio
async def test_a_tier_from_another_tenant_is_rejected(
    client, auth_headers, db_session, test_tenant, test_user, second_tenant_factory
):
    other, _ = await second_tenant_factory()  # the fixture returns (tenant, user)
    theirs = await _tier(db_session, other.id, name="Theirs")

    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "cross-tenant",
            "tier_id": theirs.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    assert resp.status_code in (404, 422)


@pytest.mark.asyncio
async def test_an_owner_from_another_tenant_is_rejected(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """The owner is a client-supplied foreign key too — the tier is not the only
    one that has to be checked against the caller's tenant."""
    _, their_user = await second_tenant_factory()
    tier = await _tier(db_session, test_tenant.id)

    resp = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "cross-tenant-owner",
            "tier_id": tier.id,
            "owner_user_id": their_user.id,
            "expires_at": _future(),
        },
    )
    assert resp.status_code in (404, 422)


@pytest.mark.asyncio
async def test_patching_a_legacy_environment_requires_filling_the_owner_gap(
    client, auth_headers, db_session, test_tenant, test_user
):
    """A legacy row (null owner, null expiry) cannot be patched at all until the
    patch supplies an OWNER. Every edit is an opportunity to close the gap.

    Product decision: a null expiry is a legitimate "no expiry planned" state,
    not a missing value, so — unlike the owner — it must never block a patch.
    This test used to also require `expires_at` in the accepted patch; that
    requirement is gone on purpose.
    """
    tier = await _tier(db_session, test_tenant.id)
    from app.db.models.environment import Environment

    legacy = Environment(
        tenant_id=test_tenant.id, name="legacy", tier_id=tier.id
    )
    db_session.add(legacy)
    await db_session.commit()
    await db_session.refresh(legacy)

    refused = await client.patch(
        f"/api/v1/environments/{legacy.id}",
        headers=auth_headers,
        json={"description": "just a note"},
    )
    assert refused.status_code == 422

    # Owner only — no expires_at. This is the discriminating half: under the
    # old "owner AND expiry" rule this same patch would still 422.
    accepted = await client.patch(
        f"/api/v1/environments/{legacy.id}",
        headers=auth_headers,
        json={
            "description": "just a note",
            "owner_user_id": test_user.id,
        },
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["owner_username"] == test_user.username
    assert body["expires_at"] is None


@pytest.mark.asyncio
async def test_patching_a_compliant_environment_needs_nothing_extra(
    client, auth_headers, db_session, test_tenant, test_user
):
    tier = await _tier(db_session, test_tenant.id)
    created = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "compliant",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    env_id = created.json()["id"]

    patched = await client.patch(
        f"/api/v1/environments/{env_id}",
        headers=auth_headers,
        json={"description": "fine"},
    )
    assert patched.status_code == 200


@pytest.mark.asyncio
async def test_governance_gap_filter_selects_only_rows_missing_an_owner(
    client, auth_headers, db_session, test_tenant, test_user
):
    """The gap is reportable, which is the whole reason owner stays nullable in
    the database rather than being backfilled with a fabrication.

    Product decision: `governance_gap` means missing OWNER only — a null
    expiry is "no expiry planned", a legitimate state, not a gap. The
    no-owner-but-has-expiry vs has-owner-but-no-expiry pair below is the
    discriminating half: without it, this test would pass just as well under
    the old "owner or expiry" semantics.
    """
    from app.db.models.environment import Environment

    tier = await _tier(db_session, test_tenant.id)
    # No owner, no expiry either — the gap case.
    legacy = Environment(tenant_id=test_tenant.id, name="legacy", tier_id=tier.id)
    db_session.add(legacy)
    await db_session.commit()
    await db_session.refresh(legacy)

    compliant = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "compliant",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    compliant_id = compliant.json()["id"]

    # Has an owner but no expiry — under the OLD "owner or expiry" semantics
    # this would count as a gap. Under the new semantics it must not: an
    # owner is present, so it is clean, and a null expiry is "no expiry
    # planned", not a gap. `POST /environments` still requires `expires_at`
    # (unchanged — the form path always states one), so this row — the shape
    # the spreadsheet import produces — is built directly, the same way the
    # `legacy` row above is.
    no_expiry = Environment(
        tenant_id=test_tenant.id,
        name="owner-no-expiry",
        tier_id=tier.id,
        owner_user_id=test_user.id,
    )
    db_session.add(no_expiry)
    await db_session.commit()
    await db_session.refresh(no_expiry)
    no_expiry_id = no_expiry.id

    gaps = await client.get(
        "/api/v1/environments/?governance_gap=true", headers=auth_headers
    )
    assert gaps.status_code == 200
    assert [e["id"] for e in gaps.json()] == [legacy.id]

    clean = await client.get(
        "/api/v1/environments/?governance_gap=false", headers=auth_headers
    )
    assert sorted(e["id"] for e in clean.json()) == sorted(
        [compliant_id, no_expiry_id]
    )


@pytest.mark.asyncio
async def test_expiring_within_days_excludes_a_null_expiry(
    client, auth_headers, db_session, test_tenant, test_user
):
    """A null expiry is not 'expiring soon' — it is a governance gap, which is a
    different question with its own filter."""
    from app.db.models.environment import Environment

    tier = await _tier(db_session, test_tenant.id)
    db_session.add(Environment(tenant_id=test_tenant.id, name="no-expiry", tier_id=tier.id))
    await db_session.commit()

    soon = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "expires-soon",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        },
    )
    soon_id = soon.json()["id"]
    await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "expires-later",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )

    resp = await client.get(
        "/api/v1/environments/?expiring_within_days=30", headers=auth_headers
    )
    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [soon_id]


@pytest.mark.asyncio
async def test_deleting_a_tier_in_use_is_refused(
    client, auth_headers, db_session, test_tenant, test_user
):
    tier = await _tier(db_session, test_tenant.id)
    await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "uses-the-tier",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )

    resp = await client.delete(
        f"/api/v1/environment-tiers/{tier.id}", headers=auth_headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_a_tier_becomes_deletable_once_its_environment_is_soft_deleted(
    client, auth_headers, db_session, test_tenant, test_user
):
    """A soft-deleted environment is not a reference — otherwise a tier could
    never be retired once anything that used it had been deleted."""
    tier = await _tier(db_session, test_tenant.id)
    created = await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={
            "name": "short-lived",
            "tier_id": tier.id,
            "owner_user_id": test_user.id,
            "expires_at": _future(),
        },
    )
    env_id = created.json()["id"]

    blocked = await client.delete(
        f"/api/v1/environment-tiers/{tier.id}", headers=auth_headers
    )
    assert blocked.status_code == 409

    await client.delete(f"/api/v1/environments/{env_id}", headers=auth_headers)

    allowed = await client.delete(
        f"/api/v1/environment-tiers/{tier.id}", headers=auth_headers
    )
    assert allowed.status_code == 204


@pytest.mark.asyncio
async def test_spreadsheet_import_falls_back_to_other_and_creates_no_tier(
    db_session, test_tenant, test_user
):
    """A vocabulary the admin configures must not be extendable by uploading a
    spreadsheet. Counted before and after, because 'it used Other' and 'it
    invented a tier called Other' look identical from the row alone."""
    from sqlalchemy import func, select

    from app.db.models.environment import Environment
    from app.db.models.environment_tier import EnvironmentTier
    from app.services import excel_import_service
    from app.services.environment_tier_defaults import (
        seed_environment_tier_defaults_for_tenant,
    )
    from tests.integration.test_import import make_environment_excel

    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    async def _tier_count():
        return (
            await db_session.execute(
                select(func.count())
                .select_from(EnvironmentTier)
                .where(EnvironmentTier.tenant_id == test_tenant.id)
            )
        ).scalar_one()

    before = await _tier_count()

    result = await excel_import_service.import_environments(
        db_session,
        make_environment_excel([{"Name": "from-spreadsheet", "Type": "wibble"}]),
        test_tenant.id,
        test_user.id,
    )
    assert result["created"] == 1, result

    after = await _tier_count()
    assert after == before, "the import created a tier"

    env = (
        await db_session.execute(
            select(Environment).where(
                Environment.tenant_id == test_tenant.id,
                Environment.name == "from-spreadsheet",
            )
        )
    ).scalar_one()
    tier = (
        await db_session.execute(
            select(EnvironmentTier).where(EnvironmentTier.id == env.tier_id)
        )
    ).scalar_one()
    assert tier.category == "other"


@pytest.mark.asyncio
async def test_spreadsheet_import_matches_a_known_tier_case_insensitively(
    db_session, test_tenant, test_user
):
    from sqlalchemy import select

    from app.db.models.environment import Environment
    from app.db.models.environment_tier import EnvironmentTier
    from app.services import excel_import_service
    from app.services.environment_tier_defaults import (
        seed_environment_tier_defaults_for_tenant,
    )
    from tests.integration.test_import import make_environment_excel

    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    await excel_import_service.import_environments(
        db_session,
        make_environment_excel([{"Name": "lower-case-uat", "Type": "uat"}]),
        test_tenant.id,
        test_user.id,
    )

    env = (
        await db_session.execute(
            select(Environment).where(Environment.name == "lower-case-uat")
        )
    ).scalar_one()
    tier = (
        await db_session.execute(
            select(EnvironmentTier).where(EnvironmentTier.id == env.tier_id)
        )
    ).scalar_one()
    assert tier.name == "UAT"


@pytest.mark.asyncio
async def test_spreadsheet_import_into_a_tenant_with_no_tiers_says_so(
    db_session, test_tenant, test_user
):
    """Rather than an AttributeError on a None tier."""
    from fastapi import HTTPException

    from app.services import excel_import_service
    from tests.integration.test_import import make_environment_excel

    with pytest.raises(HTTPException) as exc:
        await excel_import_service.import_environments(
            db_session,
            make_environment_excel([{"Name": "nowhere", "Type": "dev"}]),
            test_tenant.id,
            test_user.id,
        )
    assert exc.value.status_code == 422
    assert "tier" in exc.value.detail.lower()
