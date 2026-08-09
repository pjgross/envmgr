"""`POST .../environment-naming-policy/preview` — what a policy would do,
before it does it.

Two deviations from the plan, both the same ones Task 4 needed: the ReDoS
fixture is `(a|a)*$` and not `(a+)+$` (which `regex` optimises away and
accepts), and the Viewer is built directly because `ensure_user` takes no
`role` and the password is `password123`.
"""
import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.models.environment import Environment
from app.db.models.user import User
from tests.factories import post_environment

PREVIEW_URL = "/api/v1/tenant/environment-naming-policy/preview"
POLICY_URL = "/api/v1/tenant/environment-naming-policy"
PATTERN = r"[a-z]+-(dev|uat|prod)-\d{2}"


@pytest.mark.asyncio
async def test_preview_answers_who_this_would_hit_before_saving(client, auth_headers):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "Legacy Box")
    await post_environment(client, auth_headers, "Another Old One")

    r = await client.post(
        PREVIEW_URL,
        json={"name_pattern": PATTERN, "required_attributes": []},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_environments"] == 3
    assert body["in_gap"] == 2
    assert body["quarantined_now"] == 0, "a brand-new rule quarantines nothing"
    assert sorted(body["sample_names"]) == ["Another Old One", "Legacy Box"]


@pytest.mark.asyncio
async def test_preview_with_no_overrides_describes_the_policy_in_force(
    client, auth_headers
):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(
        POLICY_URL,
        json={
            "is_enabled": True,
            "name_pattern": r"[a-z]+-\d{2}",
            "name_pattern_example": "payments-01",
            "required_attributes": [],
            "grace_days": 14,
        },
        headers=auth_headers,
    )
    r = await client.post(PREVIEW_URL, json={}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["in_gap"] == 1


@pytest.mark.asyncio
async def test_preview_judges_the_candidate_not_the_stored_verdict(
    client, auth_headers
):
    """The whole point of a preview: it must answer for a pattern that is NOT
    the one in force.

    Reading `environment.name_compliant` — which belongs to the SAVED policy —
    would make every preview echo the current rule back, and the two fixtures
    below are chosen so that mistake is visible in both directions.
    """
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "billing-dev-07")
    # A policy everything passes, so every stored verdict is True.
    await client.put(
        POLICY_URL,
        json={
            "is_enabled": True,
            "name_pattern": PATTERN,
            "name_pattern_example": "payments-uat-01",
            "required_attributes": [],
            "grace_days": 14,
        },
        headers=auth_headers,
    )

    # A stricter candidate: only the payments one survives.
    stricter = await client.post(
        PREVIEW_URL, json={"name_pattern": r"payments-.*"}, headers=auth_headers
    )
    assert stricter.json()["in_gap"] == 1, "the preview echoed the stored verdict"
    assert stricter.json()["sample_names"] == ["billing-dev-07"]

    # And a laxer one: nothing is in gap, though nothing about the saved policy
    # changed.
    laxer = await client.post(
        PREVIEW_URL, json={"name_pattern": r".*"}, headers=auth_headers
    )
    assert laxer.json()["in_gap"] == 0


@pytest.mark.asyncio
async def test_preview_writes_nothing(client, auth_headers, db_session, test_tenant):
    """It is a POST because it carries a body, not because it changes anything.
    A preview that recomputed stored verdicts would apply the candidate policy
    as a side effect of looking at it."""
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(
        POLICY_URL,
        json={
            "is_enabled": True,
            "name_pattern": r".*",
            "name_pattern_example": None,
            "required_attributes": [],
            "grace_days": 14,
        },
        headers=auth_headers,
    )
    before = (
        await db_session.execute(
            select(Environment.name_compliant).where(
                Environment.tenant_id == test_tenant.id
            )
        )
    ).scalars().all()
    assert before == [True], "precondition: the saved policy passed it"

    await client.post(PREVIEW_URL, json={"name_pattern": PATTERN}, headers=auth_headers)

    after = (
        await db_session.execute(
            select(Environment.name_compliant).where(
                Environment.tenant_id == test_tenant.id
            )
        )
    ).scalars().all()
    assert after == before, "the preview rewrote the stored verdicts"


@pytest.mark.asyncio
async def test_preview_counts_what_is_already_past_grace(
    client, auth_headers, db_session, test_tenant
):
    """`quarantined_now` is the half an admin actually fears — "how many go
    straight to quarantined if I save this?" — and every other test here leaves
    grace unelapsed, so the branch that counts it never runs at all.

    Both clocks are aged, because quarantine needs both: the policy's
    `effective_from` (the candidate inherits the saved one) and each
    environment's own `created_at`.
    """
    from datetime import datetime, timedelta, timezone

    from app.services import environment_compliance_service as svc

    await post_environment(client, auth_headers, "Legacy Box")
    await post_environment(client, auth_headers, "payments-uat-01")
    await client.put(
        POLICY_URL,
        json={
            "is_enabled": True,
            "name_pattern": r".*",
            "name_pattern_example": None,
            "required_attributes": [],
            "grace_days": 1,
        },
        headers=auth_headers,
    )

    then = datetime.now(timezone.utc) - timedelta(days=30)
    for env in (
        (
            await db_session.execute(
                select(Environment).where(Environment.tenant_id == test_tenant.id)
            )
        )
        .scalars()
        .all()
    ):
        env.created_at = then
    policy = await svc.load_policy(db_session, test_tenant.id)
    policy.effective_from = then
    await db_session.flush()

    r = await client.post(PREVIEW_URL, json={"name_pattern": PATTERN}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["in_gap"] == 1
    assert body["quarantined_now"] == 1, (
        "an environment past both grace clocks was not counted as quarantined"
    )


@pytest.mark.asyncio
async def test_preview_runs_the_same_redos_guard_as_the_save_path(client, auth_headers):
    r = await client.post(
        PREVIEW_URL, json={"name_pattern": r"(a|a)*$"}, headers=auth_headers
    )
    assert r.status_code == 422
    assert "too slow" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_preview_refuses_an_unknown_required_attribute(client, auth_headers):
    r = await client.post(
        PREVIEW_URL, json={"required_attributes": ["tier"]}, headers=auth_headers
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_not_silently_dropped(client, auth_headers):
    r = await client.post(
        PREVIEW_URL, json={"name_patern": PATTERN}, headers=auth_headers
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_preview_is_admin_only(client, auth_headers, db_session, test_tenant):
    """Unlike the policy GET, which any tenant member may read. A preview runs
    a caller-supplied regex over the whole estate, so it stays with the people
    who may set the policy in the first place."""
    db_session.add(
        User(
            tenant_id=test_tenant.id,
            username="preview-viewer",
            email="preview-viewer@test.com",
            password_hash=get_password_hash("password123"),
            role="Viewer",
            is_active=True,
        )
    )
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "preview-viewer",
            "password": "password123",
            "tenant_slug": test_tenant.slug,
        },
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = await client.post(PREVIEW_URL, json={}, headers=headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_preview_counts_only_this_tenants_estate(
    client, auth_headers, second_tenant_factory
):
    other_tenant, other_admin = await second_tenant_factory()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": other_admin.username,
            "password": "password123",
            "tenant_slug": other_tenant.slug,
        },
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    await post_environment(client, other_headers, "Their Legacy Box")
    await post_environment(client, auth_headers, "Legacy Box")

    r = await client.post(PREVIEW_URL, json={"name_pattern": PATTERN}, headers=auth_headers)
    assert r.json()["total_environments"] == 1
    assert r.json()["sample_names"] == ["Legacy Box"]
