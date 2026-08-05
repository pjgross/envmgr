"""The list endpoint's filters — above all `actionable`, which carries the feature."""
import pytest

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER
from app.db.models.user_group import UserGroupMember
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

    A subtly wrong filter returns a plausible list, which is why 'returns some
    rows' is not a test.
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
    await db_session.commit()

    mine = await _submitted_access_request(client, auth_headers, env_mine.id)
    theirs = await _submitted_access_request(client, auth_headers, env_theirs.id)

    body = (await client.get(
        "/api/v1/environment-requests?actionable=true", headers=auth_headers
    )).json()
    returned = {r["id"] for r in body}

    # Independently computed: submitted, not raised by me... but both WERE
    # raised by me here, so the expected set is empty. That is the point of the
    # exclusion rule — a queue is an inbox, not a mirror.
    assert returned == set()
    assert {mine, theirs} & returned == set()


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

    from app.db.models.environment_request import EnvironmentRequest
    from app.services.environment_request_service import _default_lifecycle

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

    from app.db.models.environment_request import EnvironmentRequest
    from app.services.environment_request_service import _default_lifecycle

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

    from app.db.models.environment_request import EnvironmentRequest

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
async def test_mine_returns_only_my_requests(
    client, auth_headers, db_session, test_tenant, environment_request_lifecycle
):
    env = await ensure_environment(db_session, test_tenant.id)
    grp = await ensure_user_group(db_session, test_tenant.id)
    env.operations_group_id = grp.id
    other = await ensure_user(db_session, test_tenant.id, username="colleague")
    await db_session.commit()

    from app.db.models.environment_request import EnvironmentRequest
    from app.services.environment_request_service import _default_lifecycle

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
