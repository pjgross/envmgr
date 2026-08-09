"""GET/PUT the tenant's environment naming policy.

Three deviations from the plan's Task 4, each forced by the code as it now
stands rather than as the plan imagined it:

1. `ensure_user` takes no `role` — it always builds an Admin. The Viewer is
   therefore constructed directly, the way `test_pagination_c.py` already does
   it, rather than widening a factory used by dozens of tests.
2. The catastrophic-pattern test uses `(a|a)*$`, NOT `(a+)+$`. Task 3's third
   rewrite swapped `re` for `regex`, which optimises `(a+)+$` away entirely —
   it is accepted now, in microseconds, and `test_the_patterns_that_escaped_
   are_now_HARMLESS_not_merely_refused` pins exactly that. Asserting a 422 on
   it would assert a behaviour the engine does not have.
3. The login password is `password123`, matching `conftest.test_user`.
"""
import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.models.environment import Environment
from app.db.models.user import User
from tests.factories import post_environment

POLICY_URL = "/api/v1/tenant/environment-naming-policy"

# A pattern `regex` genuinely is slow on — see the module docstring above and
# `tests/services/test_environment_compliance_evaluator.py`, which measures it.
SLOW_PATTERN = r"(a|a)*$"


def _body(**kw):
    b = dict(
        is_enabled=True,
        name_pattern=r"[a-z]+-(dev|uat|prod)-\d{2}",
        name_pattern_example="payments-uat-01",
        required_attributes=["owner"],
        grace_days=14,
    )
    b.update(kw)
    return b


@pytest.mark.asyncio
async def test_get_returns_a_disabled_policy_before_one_is_saved(client, auth_headers):
    r = await client.get(POLICY_URL, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_enabled"] is False
    assert r.json()["name_pattern"] is None


@pytest.mark.asyncio
async def test_put_then_get_round_trips(client, auth_headers):
    r = await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    assert r.status_code == 200, r.text
    r = await client.get(POLICY_URL, headers=auth_headers)
    assert r.json()["name_pattern"] == r"[a-z]+-(dev|uat|prod)-\d{2}"
    assert r.json()["required_attributes"] == ["owner"]


@pytest.mark.asyncio
async def test_reads_are_open_to_any_tenant_member_writes_are_admin(
    client, db_session, test_tenant
):
    """B3a's rule: the reason an environment is flagged has to be legible to
    the person who has to fix it. Deliberately unlike /tenant/users."""
    db_session.add(
        User(
            tenant_id=test_tenant.id,
            username="policy-viewer",
            email="policy-viewer@test.com",
            password_hash=get_password_hash("password123"),
            role="Viewer",
            is_active=True,
        )
    )
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": "policy-viewer",
            "password": "password123",
            "tenant_slug": test_tenant.slug,
        },
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get(POLICY_URL, headers=viewer_headers)).status_code == 200
    assert (
        await client.put(POLICY_URL, json=_body(), headers=viewer_headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_not_silently_dropped(client, auth_headers):
    """POST /projects silently discarded priority_rank for the want of
    extra='forbid', and POST /tenant/lifecycle-templates still drops
    required_fields today."""
    r = await client.put(POLICY_URL, json=_body(grace_dayz=3), headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_negative_grace_days_is_refused(client, auth_headers):
    r = await client.put(POLICY_URL, json=_body(grace_days=-1), headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_required_attribute_is_refused(client, auth_headers):
    r = await client.put(
        POLICY_URL, json=_body(required_attributes=["tier"]), headers=auth_headers
    )
    assert r.status_code == 422
    assert "tier" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_saving_a_policy_recomputes_every_environment_in_the_tenant(
    client, auth_headers, db_session, test_tenant
):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "Legacy Box")

    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    rows = dict(
        (
            await db_session.execute(
                select(Environment.name, Environment.name_compliant).where(
                    Environment.tenant_id == test_tenant.id
                )
            )
        ).all()
    )
    assert rows["payments-uat-01"] is True
    assert rows["Legacy Box"] is False


@pytest.mark.asyncio
async def test_disabling_a_policy_returns_every_verdict_to_null(
    client, auth_headers, db_session, test_tenant
):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    await client.put(POLICY_URL, json=_body(is_enabled=False), headers=auth_headers)

    verdicts = (
        (
            await db_session.execute(
                select(Environment.name_compliant).where(
                    Environment.tenant_id == test_tenant.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert verdicts == [None]


@pytest.mark.asyncio
async def test_effective_from_is_bumped_by_a_rule_change_but_not_by_grace_days(
    client, auth_headers
):
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    first = (await client.get(POLICY_URL, headers=auth_headers)).json()["effective_from"]

    await client.put(POLICY_URL, json=_body(grace_days=30), headers=auth_headers)
    after_grace = (await client.get(POLICY_URL, headers=auth_headers)).json()[
        "effective_from"
    ]
    assert after_grace == first, (
        "grace_days does not change what is asked of an environment"
    )

    await client.put(
        POLICY_URL,
        json=_body(
            grace_days=30,
            name_pattern=r"[a-z]+-\d{2}",
            name_pattern_example="payments-01",
        ),
        headers=auth_headers,
    )
    after_pattern = (await client.get(POLICY_URL, headers=auth_headers)).json()[
        "effective_from"
    ]
    assert after_pattern > first


@pytest.mark.asyncio
async def test_a_defined_custom_field_is_an_acceptable_required_attribute(
    client, auth_headers
):
    """The `cf:` branch, which the plan's suite left untested on its accepting
    side — the refusing side alone would stay green if every `cf:` key were
    rejected."""
    created = await client.post(
        "/api/v1/tenant/fields",
        headers=auth_headers,
        json={
            "entity_type": "environment",
            "field_key": "cost_centre",
            "label": "Cost Centre",
            "field_type": "text",
        },
    )
    assert created.status_code == 201, created.text

    ok = await client.put(
        POLICY_URL,
        json=_body(required_attributes=["owner", "cf:cost_centre"]),
        headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text

    r = await client.get(POLICY_URL, headers=auth_headers)
    assert r.json()["required_attributes"] == ["owner", "cf:cost_centre"]


@pytest.mark.asyncio
async def test_an_undefined_custom_field_key_is_refused_naming_the_key(
    client, auth_headers
):
    """A typo would otherwise mark the whole estate non-compliant against a
    field that does not exist, with nothing on any screen to explain why."""
    r = await client.put(
        POLICY_URL,
        json=_body(required_attributes=["cf:cost_centr"]),
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert "cost_centr" in r.json()["detail"]


@pytest.mark.asyncio
async def test_saving_a_policy_does_not_re_judge_another_tenants_estate(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """`recompute_tenant`'s tenant filter, named.

    A1 found a missing `tenant_id` filter eight times over, never once caught
    by a pre-existing test. This one writes across every environment it selects,
    so an unfiltered query would silently judge the whole install against one
    tenant's convention.
    """
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
    assert (
        await post_environment(client, other_headers, "Their Legacy Box")
    ).status_code == 201

    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    theirs = (
        await db_session.execute(
            select(Environment.name_compliant).where(
                Environment.tenant_id == other_tenant.id
            )
        )
    ).scalars().all()
    assert theirs == [None], "another tenant's environments were re-judged"

    ours = (
        await db_session.execute(
            select(Environment.name_compliant).where(
                Environment.tenant_id == test_tenant.id
            )
        )
    ).scalars().all()
    assert ours == [False], "our own environment was not judged"


@pytest.mark.asyncio
async def test_a_policy_is_not_readable_from_another_tenant(
    client, auth_headers, second_tenant_factory
):
    """`load_policy`'s tenant filter. Unfiltered, `scalar_one_or_none` would
    raise on the second tenant to save one rather than leak quietly — so the
    failure mode is a 500 on an unrelated tenant's read, which is harder to
    trace back here than a wrong answer."""
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

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

    r = await client.get(POLICY_URL, headers=other_headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_enabled"] is False
    assert r.json()["name_pattern"] is None


@pytest.mark.asyncio
async def test_a_catastrophic_pattern_is_refused_by_the_endpoint(client, auth_headers):
    """The endpoint inherits Task 3's save-time probe rather than re-deciding.

    `(a|a)*$` and not `(a+)+$`: see the module docstring. What the probe buys
    is that the admin hears about it NOW; a pattern the probe's alphabets miss
    is still bounded at every match by `MATCH_TIMEOUT_SECONDS`.
    """
    r = await client.put(
        POLICY_URL,
        json=_body(name_pattern=SLOW_PATTERN, name_pattern_example=None),
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert "too slow" in r.json()["detail"].lower()
