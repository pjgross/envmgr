"""The list endpoint's filters — above all `actionable`, which carries the feature."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER
from app.db.models.environment_request import EnvironmentRequest
from app.db.models.user_group import UserGroupMember
from app.services.environment_request_service import (
    _default_lifecycle,
    _FALLBACK_TERMINAL_STATES,
    terminal_states_for_tenant,
)
from tests.factories import (
    ensure_environment, ensure_environment_tier, ensure_user, ensure_user_group,
)


async def _submitted_access_request(client, headers, env_id):
    rid = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env_id, "justification": "j"},
        headers=headers,
    )).json()["id"]
    await client.post(
        f"/api/v1/environment-requests/{rid}/transition",
        json={"to_state": "submitted"}, headers=headers,
    )
    return rid


@pytest.mark.asyncio
async def test_list_is_bounded_and_advertises_its_total(client, auth_headers):
    listed = await client.get("/api/v1/environment-requests", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert isinstance(listed.json(), list)
    assert TOTAL_COUNT_HEADER in listed.headers

    over = await client.get(
        f"/api/v1/environment-requests?limit={MAX_LIMIT + 1}", headers=auth_headers
    )
    assert over.status_code == 422


@pytest.mark.asyncio
async def test_actionable_matches_an_independently_computed_set(
    client, auth_headers, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """Differential test: the SQL filter's result vs a set computed in Python.

    Both requests are raised by someone else, so the self-exclusion clause
    treats them identically — the included/excluded split here is driven
    entirely by GROUP MEMBERSHIP, which is what makes this test discriminate
    on `actionable_clause`'s membership EXISTS specifically. (Self-exclusion
    and terminal-state exclusion are each covered by their own dedicated test
    below.)
    """
    group_mine = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    group_theirs = await ensure_user_group(db_session, test_tenant.id, name="Theirs")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group_mine.id, user_id=test_user.id
    ))

    env_mine = await ensure_environment(db_session, test_tenant.id, slot=1)
    env_mine.operations_group_id = group_mine.id
    env_theirs = await ensure_environment(db_session, test_tenant.id, slot=2)
    env_theirs.operations_group_id = group_theirs.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req_mine = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="for my team's environment", environment_id=env_mine.id,
    )
    req_theirs = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="for someone else's environment", environment_id=env_theirs.id,
    )
    db_session.add_all([req_mine, req_theirs])
    await db_session.commit()

    # Independently computed set: every non-terminal, not-mine request whose
    # environment's operations group I belong to.
    my_group_ids = {group_mine.id}
    candidates = {
        req_mine.id: env_mine.operations_group_id,
        req_theirs.id: env_theirs.operations_group_id,
    }
    expected = {rid for rid, gid in candidates.items() if gid in my_group_ids}

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    returned = {r["id"] for r in body}

    assert returned == expected
    assert req_mine.id in returned
    assert req_theirs.id not in returned


@pytest.mark.asyncio
async def test_actionable_excludes_my_own_requests(
    client, auth_headers, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """A request I raised, even for my own team's environment, is not in my
    queue — actionable is an inbox, not a mirror of everything I did."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=test_user.id
    ))
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    await db_session.commit()

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=test_user.id,
        justification="self-raised", environment_id=env.id,
    )
    db_session.add(req)
    await db_session.commit()

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    assert req.id not in {r["id"] for r in body}


@pytest.mark.asyncio
async def test_actionable_includes_another_users_request_for_my_team(
    client, auth_headers, db_session, test_tenant, test_user, environment_request_lifecycle
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=test_user.id
    ))
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="theirs", environment_id=env.id,
    )
    db_session.add(req)
    await db_session.commit()

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    assert [r["id"] for r in body] == [req.id]


@pytest.mark.asyncio
async def test_actionable_includes_new_environment_requests_for_admin(
    client, auth_headers, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """The Admin bypass: a `new_environment` request has no
    `operations_group_id` yet (it's what the request is asking for), so no
    membership check can apply to it. It routes to every Admin instead —
    that's the entire point of `actionable_clause`'s `if is_admin:` branch.

    `test_user` (from `auth_headers`) is already role='Admin', so this alone
    exercises the branch — no second actor needed.
    """
    assert test_user.role == "Admin"
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    await db_session.commit()

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="new_environment", status="submitted",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="need a fresh SIT environment", proposed_name="sit-new",
        tier_id=tier.id, expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(req)
    await db_session.commit()

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    assert req.id in {r["id"] for r in body}


@pytest.mark.asyncio
async def test_actionable_excludes_terminal_requests(
    client, auth_headers, db_session, test_tenant, test_user, environment_request_lifecycle
):
    group = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=test_user.id
    ))
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    for state in ("rejected", "cancelled", "fulfilled"):
        db_session.add(EnvironmentRequest(
            tenant_id=test_tenant.id, kind="access", status=state,
            lifecycle_id=tpl.id, requested_by=other.id,
            justification=state, environment_id=env.id,
        ))
    await db_session.commit()

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    assert body == []


@pytest.mark.asyncio
async def test_terminal_states_come_from_the_tenants_own_template(
    client, auth_headers, db_session, test_tenant, test_user, environment_request_lifecycle
):
    """A tenant that renames its terminal states must not get a queue that
    keeps showing finished work.

    Tenant configurability is the whole reason this entity uses lifecycle
    templates rather than a fixed enum; a hardcoded terminal set would quietly
    break exactly the customer that design serves.
    """
    from sqlalchemy import select
    from app.db.models.lifecycle import LifecycleTemplate

    group = await ensure_user_group(db_session, test_tenant.id, name="Mine")
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=test_user.id
    ))
    env = await ensure_environment(db_session, test_tenant.id)
    env.operations_group_id = group.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")

    # Rename this tenant's terminal state to something the code cannot know.
    tpl = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "environment_request",
        )
    )).scalars().first()
    definition = dict(tpl.definition)
    definition["states"] = [
        {**s, "key": "provisioned"} if s["key"] == "fulfilled" else s
        for s in definition["states"]
    ]
    tpl.definition = definition
    await db_session.commit()

    db_session.add(EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="provisioned",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="finished", environment_id=env.id,
    ))
    await db_session.commit()

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    assert body == [], "a renamed terminal state must still be excluded"


@pytest.mark.asyncio
async def test_terminal_states_distinguishes_no_template_from_none_terminal(
    db_session, test_tenant, environment_request_lifecycle, second_tenant_factory
):
    """`terminal_states_for_tenant` must fall back to the hardcoded three only
    when a tenant has no environment_request template at all — not whenever
    the computed set happens to be empty. A tenant whose template legitimately
    marks zero states terminal must get an empty set back, or the "tenant
    configurability" this function exists for is a lie for that tenant.
    """
    from sqlalchemy import select
    from app.db.models.lifecycle import LifecycleTemplate

    # No environment_request template anywhere for this tenant -> fallback.
    empty_tenant, _ = await second_tenant_factory("Empty Org", "empty-org")
    assert (
        await terminal_states_for_tenant(db_session, empty_tenant.id)
        == _FALLBACK_TERMINAL_STATES
    )

    # test_tenant DOES have a template (seeded by the fixture) — strip every
    # is_terminal flag so it legitimately declares zero terminal states.
    tpl = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "environment_request",
        )
    )).scalars().first()
    definition = dict(tpl.definition)
    definition["states"] = [{**s, "is_terminal": False} for s in definition["states"]]
    tpl.definition = definition
    await db_session.commit()

    assert await terminal_states_for_tenant(db_session, test_tenant.id) == frozenset()


@pytest.mark.asyncio
async def test_status_kind_and_environment_id_filters(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    """`status`, `kind` and `environment_id` had no coverage at all."""
    env_a = await ensure_environment(db_session, test_tenant.id, slot=1)
    env_b = await ensure_environment(db_session, test_tenant.id, slot=2)
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    req_draft_a = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="draft",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="draft on a", environment_id=env_a.id,
    )
    req_submitted_b = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="submitted",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="submitted on b", environment_id=env_b.id,
    )
    req_new_env_draft = EnvironmentRequest(
        tenant_id=test_tenant.id, kind="new_environment", status="draft",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="new env", proposed_name="x", tier_id=tier.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add_all([req_draft_a, req_submitted_b, req_new_env_draft])
    await db_session.commit()

    by_status = (await client.get(
        "/api/v1/environment-requests?status=draft", headers=auth_headers
    )).json()
    assert {r["id"] for r in by_status} == {req_draft_a.id, req_new_env_draft.id}

    by_kind = (await client.get(
        "/api/v1/environment-requests?kind=new_environment", headers=auth_headers
    )).json()
    assert {r["id"] for r in by_kind} == {req_new_env_draft.id}

    by_env = (await client.get(
        f"/api/v1/environment-requests?environment_id={env_b.id}", headers=auth_headers
    )).json()
    assert {r["id"] for r in by_env} == {req_submitted_b.id}


@pytest.mark.asyncio
async def test_mine_returns_only_my_requests(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    env = await ensure_environment(db_session, test_tenant.id)
    grp = await ensure_user_group(db_session, test_tenant.id)
    env.operations_group_id = grp.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    tpl = await _default_lifecycle(db_session, test_tenant.id)
    db_session.add(EnvironmentRequest(
        tenant_id=test_tenant.id, kind="access", status="draft",
        lifecycle_id=tpl.id, requested_by=other.id,
        justification="not mine", environment_id=env.id,
    ))
    await db_session.commit()

    mine_id = (await client.post(
        "/api/v1/environment-requests",
        json={"kind": "access", "environment_id": env.id, "justification": "mine"},
        headers=auth_headers,
    )).json()["id"]

    body = (await client.get(
        "/api/v1/environment-requests?mine=true", headers=auth_headers
    )).json()
    assert [r["id"] for r in body] == [mine_id]
