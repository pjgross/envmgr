"""Governance filters and the new sortable columns.

Ordering is asserted on rendered row order over mixed-case data. An assertion
on the emitted SQL stays green while the order users see is wrong — that is
exactly what happened to the pagination pilot.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.environment import Environment
from app.db.models.environment_tier import EnvironmentTier

from tests.factories import ensure_user_group


async def _seed(db_session, tenant_id, owner_id):
    tiers = {}
    for name in ("apple", "Banana", "cherry"):
        tier = EnvironmentTier(tenant_id=tenant_id, name=name)
        db_session.add(tier)
        tiers[name] = tier
    await db_session.flush()

    # Every owned row also gets an operations group, so these rows stay
    # unambiguously "clean" now that governance_gap covers both fields —
    # only `no-owner` (missing both) should ever surface as a gap here.
    group = await ensure_user_group(db_session, tenant_id, name="Ops")

    soon = datetime.now(timezone.utc) + timedelta(days=5)
    later = datetime.now(timezone.utc) + timedelta(days=200)

    rows = [
        Environment(tenant_id=tenant_id, name="owned-soon", tier_id=tiers["apple"].id,
                    owner_user_id=owner_id, operations_group_id=group.id, expires_at=soon),
        Environment(tenant_id=tenant_id, name="owned-later", tier_id=tiers["Banana"].id,
                    owner_user_id=owner_id, operations_group_id=group.id, expires_at=later),
        Environment(tenant_id=tenant_id, name="no-owner", tier_id=tiers["cherry"].id,
                    owner_user_id=None, expires_at=later),
        Environment(tenant_id=tenant_id, name="no-expiry", tier_id=tiers["apple"].id,
                    owner_user_id=owner_id, operations_group_id=group.id, expires_at=None),
    ]
    for row in rows:
        db_session.add(row)
    await db_session.commit()
    return tiers


@pytest.mark.asyncio
async def test_governance_gap_returns_only_the_rows_missing_an_owner(
    client, auth_headers, db_session, test_tenant, test_user
):
    """A null expiry means "no expiry planned" — a legitimate state, not a gap.
    The `no-expiry` row NOT appearing is the discriminating half: without it
    this test passes under the old owner-or-expiry semantics too.

    Since B3a, the gap is missing OWNER *or* missing OPERATIONS GROUP; every
    owned row here also has a group (see `_seed`), so `no-owner` — missing
    both — is still the only row that surfaces."""
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?governance_gap=true", headers=auth_headers
    )
    assert resp.status_code == 200
    assert sorted(r["name"] for r in resp.json()) == ["no-owner"]
    # The header is the true total, not the page length.
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_expiring_within_days_excludes_a_null_expiry(
    client, auth_headers, db_session, test_tenant, test_user
):
    """'Expiring soon' and 'never given an expiry' are different problems."""
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?expiring_within_days=30", headers=auth_headers
    )
    assert [r["name"] for r in resp.json()] == ["owned-soon"]


@pytest.mark.asyncio
async def test_filtering_by_tier(client, auth_headers, db_session, test_tenant, test_user):
    tiers = await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        f"/api/v1/environments/?tier_id={tiers['apple'].id}", headers=auth_headers
    )
    assert sorted(r["name"] for r in resp.json()) == ["no-expiry", "owned-soon"]


@pytest.mark.asyncio
async def test_filtering_by_owner(client, auth_headers, db_session, test_tenant, test_user):
    """Added from a Task 3 review finding: the owner_user_id filter shipped
    untested, so deleting its `if` block left the suite green."""
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        f"/api/v1/environments/?owner_user_id={test_user.id}", headers=auth_headers
    )
    assert sorted(r["name"] for r in resp.json()) == [
        "no-expiry",
        "owned-later",
        "owned-soon",
    ]
    # The unowned row is the discriminating half — without it the filter could
    # be a no-op and this test would still pass.
    assert "no-owner" not in [r["name"] for r in resp.json()]


@pytest.mark.asyncio
async def test_sorting_by_owner_pins_the_unowned_row_last_on_asc(
    client, auth_headers, db_session, test_tenant, test_user
):
    """Added from a Task 3 review finding: `owner` was whitelisted as sortable
    with no ordering test, so NULL placement was unasserted in both directions.
    `owner` is an outer-joined User.username, NULL for every unowned row, and
    apply_sort pins NULLs last on ASC and first on DESC."""
    await _seed(db_session, test_tenant.id, test_user.id)

    asc = await client.get(
        "/api/v1/environments/?sort_by=owner&sort_dir=asc", headers=auth_headers
    )
    assert [r["name"] for r in asc.json()][-1] == "no-owner"

    desc = await client.get(
        "/api/v1/environments/?sort_by=owner&sort_dir=desc", headers=auth_headers
    )
    assert [r["name"] for r in desc.json()][0] == "no-owner"


@pytest.mark.asyncio
async def test_sorting_by_tier_folds_case(
    client, auth_headers, db_session, test_tenant, test_user
):
    """Both engines here collate by byte value, which would put 'Banana' before
    'apple'. apply_sort folds case, so the rendered order is alphabetical."""
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?sort_by=tier&sort_dir=asc", headers=auth_headers
    )
    assert [r["tier_name"] for r in resp.json()] == [
        "apple",
        "apple",
        "Banana",
        "cherry",
    ]


@pytest.mark.asyncio
async def test_sorting_by_expiry_pins_nulls_last_on_asc(
    client, auth_headers, db_session, test_tenant, test_user
):
    await _seed(db_session, test_tenant.id, test_user.id)

    resp = await client.get(
        "/api/v1/environments/?sort_by=expires_at&sort_dir=asc", headers=auth_headers
    )
    assert [r["name"] for r in resp.json()][-1] == "no-expiry"


@pytest.mark.asyncio
async def test_an_unwhitelisted_sort_field_is_422(client, auth_headers):
    resp = await client.get(
        "/api/v1/environments/?sort_by=environment_type", headers=auth_headers
    )
    assert resp.status_code == 422
