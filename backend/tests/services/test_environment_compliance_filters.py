"""`?compliance_gap=` and `?quarantined=`, both decided in SQL.

DEVIATION FROM THE PLAN: it builds its no-expiry fixtures with
`post_environment(..., expires_at=None)`, which cannot work —
`EnvironmentCreate.expires_at` is a REQUIRED `datetime`, so that call is a 422
and the environment is never created. Only `EnvironmentUpdate` carries the
nullable form, where an explicit null is what clears an expiry (B1's rule:
an omitted key means "leave alone"). `_env_without_expiry` therefore creates
the row and then clears the expiry through PATCH, which is also the only route
a real tenant has to that state short of the spreadsheet import.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.services import environment_compliance_service as svc
from tests.factories import post_environment

POLICY_URL = "/api/v1/tenant/environment-naming-policy"
ENVS_URL = "/api/v1/environments/"


def _body(**kw):
    b = dict(
        is_enabled=True,
        name_pattern=r"[a-z]+-(dev|uat|prod)-\d{2}",
        name_pattern_example="payments-uat-01",
        required_attributes=[],
        grace_days=14,
    )
    b.update(kw)
    return b


async def _names(client, headers, **params):
    r = await client.get(ENVS_URL, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return sorted(e["name"] for e in r.json())


async def _age(db_session, tenant_id, name, *, days):
    """Push both quarantine clocks back: the policy's `effective_from` and the
    environment's own `created_at`.

    Quarantine needs BOTH to have run out — grace runs from whichever came
    later — so a fixture that moves only one can never be quarantined.
    """
    env = (
        await db_session.execute(
            select(Environment).where(
                Environment.tenant_id == tenant_id, Environment.name == name
            )
        )
    ).scalar_one()
    then = datetime.now(timezone.utc) - timedelta(days=days)
    env.created_at = then
    policy = await svc.load_policy(db_session, tenant_id)
    policy.effective_from = then
    await db_session.flush()


async def _env_without_expiry(client, headers, name):
    """An environment with `expires_at IS NULL` — a legitimate state ("no
    expiry planned"), reachable only through PATCH or the spreadsheet import."""
    r = await post_environment(client, headers, name)
    assert r.status_code == 201, r.text
    env_id = r.json()["id"]
    cleared = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"expires_at": None},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["expires_at"] is None
    return env_id


@pytest.mark.asyncio
async def test_with_no_policy_nothing_is_in_gap_and_nothing_is_quarantined(
    client, auth_headers
):
    await post_environment(client, auth_headers, "Anything At All")
    assert await _names(client, auth_headers, compliance_gap="true") == []
    assert await _names(client, auth_headers, compliance_gap="false") == [
        "Anything At All"
    ]
    assert await _names(client, auth_headers, quarantined="true") == []


@pytest.mark.asyncio
async def test_true_and_false_partition_the_estate(client, auth_headers):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    in_gap = await _names(client, auth_headers, compliance_gap="true")
    clean = await _names(client, auth_headers, compliance_gap="false")
    everything = await _names(client, auth_headers)
    assert in_gap == ["Legacy Box"]
    assert sorted(in_gap + clean) == everything, "no row may be invisible to both"


@pytest.mark.asyncio
async def test_an_empty_filter_value_is_a_422_not_an_ignored_param(
    client, auth_headers
):
    r = await client.get(ENVS_URL, params={"compliance_gap": ""}, headers=auth_headers)
    assert r.status_code == 422
    r = await client.get(ENVS_URL, params={"quarantined": ""}, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_missing_required_attribute_is_a_gap(client, auth_headers):
    """The name conforms; the attribute does not."""
    await _env_without_expiry(client, auth_headers, "payments-uat-01")
    await client.put(
        POLICY_URL, json=_body(required_attributes=["expiry"]), headers=auth_headers
    )
    assert await _names(client, auth_headers, compliance_gap="true") == [
        "payments-uat-01"
    ]


@pytest.mark.asyncio
async def test_a_null_verdict_counts_as_compliant_under_a_live_policy(
    client, auth_headers
):
    """A policy with required attributes but NO pattern leaves every verdict
    NULL while the policy is enabled. NULL means 'no pattern applies' and
    counts as COMPLIANT — writing the clause as `.is_not(True)` instead of
    `.is_(False)` puts the whole estate in gap and this is the only test that
    sees it."""
    await post_environment(client, auth_headers, "Anything At All")
    await client.put(
        POLICY_URL,
        json=_body(
            name_pattern=None, name_pattern_example=None, required_attributes=["owner"]
        ),
        headers=auth_headers,
    )
    # The environment has an owner (post_environment supplies one), so the only
    # thing that could put it in gap is a mis-read NULL verdict.
    assert await _names(client, auth_headers, compliance_gap="true") == []

    # And the same rule through the OTHER evaluation. Asserting only the filter
    # left `_gap_messages` free to read the verdict as falsy rather than
    # `is False` — measured — which prints "the name does not match this
    # tenant's naming convention" on every row of an attributes-only policy
    # while the filter calls them all compliant. That is precisely the SQL/
    # mirror disagreement the agreement test exists for, and its fixture cannot
    # reach it: a policy WITH a pattern has no NULL verdicts to mis-read.
    row = (await client.get(ENVS_URL, headers=auth_headers)).json()[0]
    assert row["name_compliant"] is None, "precondition: no pattern was applied"
    assert row["compliance_gaps"] == [], row["compliance_gaps"]


@pytest.mark.asyncio
async def test_nothing_is_quarantined_while_the_policy_is_younger_than_grace(
    client, auth_headers
):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(grace_days=14), headers=auth_headers)
    assert await _names(client, auth_headers, compliance_gap="true") == ["Legacy Box"]
    assert await _names(client, auth_headers, quarantined="true") == []


@pytest.mark.asyncio
async def test_quarantine_bites_once_grace_has_elapsed(
    client, auth_headers, db_session, test_tenant
):
    """BOTH clocks have to have run out, which is why this ages the environment
    as well as the policy.

    The plan aged only the policy and expected quarantine — impossible against
    its own clause, since a row created moments ago is still inside its own
    grace whatever the policy's age. That is the correct behaviour and the
    reason for it: an environment created today under a year-old policy has not
    yet had its grace period.
    """
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(grace_days=1), headers=auth_headers)

    await _age(db_session, test_tenant.id, "Legacy Box", days=30)

    assert await _names(client, auth_headers, quarantined="true") == ["Legacy Box"]
    # The complement must stay a partition, the same as compliance_gap's.
    assert await _names(client, auth_headers, quarantined="false") == []


@pytest.mark.asyncio
async def test_a_deadline_is_a_day(client, auth_headers, db_session, test_tenant):
    """A4's class of bug: at instant precision an environment created at 15:00
    loses most of its last grace day, and the filter hides the rows closest to
    their deadline. Created 15:00 on day 0 with grace_days=1 is NOT quarantined
    on day 1."""
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(grace_days=1), headers=auth_headers)

    now = datetime.now(timezone.utc)
    env = (
        await db_session.execute(
            select(Environment).where(Environment.name == "Legacy Box")
        )
    ).scalar_one()
    env.created_at = (now - timedelta(days=1)).replace(hour=15, minute=0, second=0)
    policy = await svc.load_policy(db_session, test_tenant.id)
    policy.effective_from = now - timedelta(days=30)
    await db_session.flush()

    assert await _names(client, auth_headers, quarantined="true") == []


@pytest.mark.asyncio
async def test_the_response_carries_the_verdict_and_its_messages(client, auth_headers):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    row = (await client.get(ENVS_URL, headers=auth_headers)).json()[0]
    assert row["name_compliant"] is False
    assert row["quarantined"] is False
    assert any("naming convention" in m for m in row["compliance_gaps"])


@pytest.mark.asyncio
async def test_the_detail_page_agrees_with_the_list(client, auth_headers):
    """Two code paths build the same three fields — `list_environments` and
    `get_environment_view`. Wiring only the list leaves the detail page showing
    an environment as clean while the grid flags it, which is the shape B2
    exists to avoid."""
    r = await post_environment(client, auth_headers, "Legacy Box")
    env_id = r.json()["id"]
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    listed = (await client.get(ENVS_URL, headers=auth_headers)).json()[0]
    detail = (await client.get(f"{ENVS_URL}{env_id}", headers=auth_headers)).json()
    for field in ("name_compliant", "quarantined", "compliance_gaps"):
        assert detail[field] == listed[field], field


@pytest.mark.asyncio
async def test_quarantined_is_not_sortable(client, auth_headers):
    """It is computed from a column plus the policy, so there is no single
    column to order by — docs/pagination.md's permanently-unsortable set."""
    r = await client.get(
        ENVS_URL, params={"sort_by": "quarantined"}, headers=auth_headers
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_another_tenants_environments_are_never_quarantined_by_our_policy(
    client, auth_headers, db_session, test_tenant, second_tenant_factory
):
    """Two separate things, and the second needs asking directly.

    Through the API, `list_environments` scopes its own query, so the tenant
    filter INSIDE `quarantined_ids` cannot change any answer a request can
    reach — removing it leaves every API-level assertion here green (measured).
    It is defence in depth against a future caller that hands over ids from a
    wider query, so it is exercised as such: called with another tenant's
    environment id, under our tenant, it must return nothing.
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
    await client.put(POLICY_URL, json=_body(grace_days=1), headers=auth_headers)
    await _age(db_session, test_tenant.id, "Legacy Box", days=30)

    assert await _names(client, auth_headers, quarantined="true") == ["Legacy Box"]
    theirs = (await client.get(ENVS_URL, headers=other_headers)).json()
    assert [e["name"] for e in theirs] == ["Their Legacy Box"]
    assert theirs[0]["quarantined"] is False
    assert theirs[0]["compliance_gaps"] == []

    # Now the filter itself, which no request can reach past its caller's own
    # scoping. Their environment has to be made quarantinable BY EVERY OTHER
    # TEST IN THE CLAUSE, so that the tenant filter is the only thing left that
    # can exclude it. Ageing it alone is not enough: their tenant has no policy,
    # so its stored verdict is NULL and `name_compliant IS FALSE` excludes it
    # for a reason that has nothing to do with tenancy — measured, the version
    # without this line passes with the filter deleted.
    their_env = (
        await db_session.execute(
            select(Environment).where(Environment.tenant_id == other_tenant.id)
        )
    ).scalar_one()
    their_env.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    their_env.name_compliant = False
    await db_session.flush()

    policy = await svc.load_policy(db_session, test_tenant.id)
    assert (
        await svc.quarantined_ids(
            db_session,
            test_tenant.id,
            policy,
            datetime.now(timezone.utc),
            [their_env.id],
        )
        == set()
    ), "quarantined_ids judged another tenant's environment against our policy"


@pytest.mark.asyncio
async def test_the_grace_cutoff_is_a_DAY_boundary_at_any_hour_of_the_run(
    client, auth_headers, db_session, test_tenant
):
    """Written because mutating `expiry_boundary(now)` to a bare `now` SURVIVED
    the whole suite — twice over.

    `test_a_deadline_is_a_day` above backdates `created_at` to 15:00, so it only
    discriminates when the suite happens to run after 15:00 UTC: before then the
    instant-precision cutoff (`now - grace`) still falls *before* 15:00 and the
    mutant agrees with the correct answer. Run it at 11:36 and it is green with
    the rule removed. A guard whose verdict depends on the wall clock is not a
    guard.

    So this one injects `now` instead of trusting it: an environment created
    EARLIER THE SAME DAY, with zero grace. The day-granular cutoff is the start
    of `now`'s day, which is *before* the row was created, so it is NOT
    quarantined — an environment keeps the rest of the day it was created,
    exactly as it keeps the rest of the day a policy takes effect (which is why
    a 0-day grace changes nothing until the next UTC midnight; see the admin
    guide). Under `now - grace` the cutoff would be midday and the row would be
    quarantined hours early.
    """
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(grace_days=0), headers=auth_headers)

    env = (
        await db_session.execute(
            select(Environment).where(Environment.name == "Legacy Box")
        )
    ).scalar_one()
    policy = await svc.load_policy(db_session, test_tenant.id)

    # A fixed clock: nothing here reads the real time of day.
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    env.created_at = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
    policy.effective_from = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
    await db_session.flush()

    assert (
        await svc.quarantined_ids(db_session, test_tenant.id, policy, now, [env.id])
        == set()
    ), "an environment created earlier the same day was quarantined before its day was out"

    # And the boundary bites the moment the day turns — the same clause, one day
    # later, with nothing else changed. Without this half the assertion above
    # would also pass if quarantine never fired at all.
    tomorrow = datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc)
    assert await svc.quarantined_ids(
        db_session, test_tenant.id, policy, tomorrow, [env.id]
    ) == {env.id}, "quarantine never bit, so the assertion above proved nothing"


@pytest.mark.asyncio
async def test_the_sql_clause_and_the_python_mirror_agree_row_for_row(
    client, auth_headers, db_session, test_tenant
):
    """Three evaluations of one rule — the SQL filter, the message-wording
    mirror, and (from Task 7) the preview — must never disagree. A1 shipped a
    count and a list, written three tasks apart, that disagreed two ways.
    """
    # A matrix: conforming/not x expiry present/absent.
    await post_environment(client, auth_headers, "payments-uat-01")
    await _env_without_expiry(client, auth_headers, "payments-dev-02")
    await post_environment(client, auth_headers, "Legacy Box")
    await _env_without_expiry(client, auth_headers, "Another Old One")

    await client.put(
        POLICY_URL,
        json=_body(required_attributes=["expiry"]),
        headers=auth_headers,
    )

    policy = await svc.load_policy(db_session, test_tenant.id)
    envs = (
        (
            await db_session.execute(
                select(Environment).where(Environment.tenant_id == test_tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(envs) == 4, "the matrix did not build"

    # What SQL says.
    sql_in_gap = set(
        (
            await db_session.execute(
                select(Environment.id).where(
                    Environment.tenant_id == test_tenant.id,
                    svc.noncompliance_clause(policy),
                )
            )
        )
        .scalars()
        .all()
    )
    # What the message builder says.
    gaps = svc.gaps_for_environments(envs, policy)
    mirror_in_gap = {env_id for env_id, msgs in gaps.items() if msgs}

    assert sql_in_gap, "the fixture put nothing in gap — the test proves nothing"
    assert sql_in_gap == mirror_in_gap, (
        "the SQL clause and the message mirror disagree about which "
        "environments are in gap"
    )

    # And the preview, asked the same question about the policy already in
    # force. Since Task 7 the preview CALLS `_gap_messages` rather than
    # re-implementing it, so this cannot drift the way the plan feared — what
    # it still catches is the preview's own plumbing: which pattern it resolves
    # for an omitted override, how it computes the candidate verdict, and which
    # environments it counts at all.
    _, in_gap, _, _ = await svc.preview_policy(
        db_session,
        test_tenant.id,
        name_pattern=policy.name_pattern,
        required_attributes=list(policy.required_attributes),
    )
    assert in_gap == len(sql_in_gap), (
        "the preview disagrees with the SQL clause about how many environments "
        "the policy in force puts in gap"
    )
