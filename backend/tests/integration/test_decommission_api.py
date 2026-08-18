"""B5 Task 5 — initiating a decommission, and the two permission rules.

Fixture shapes follow tests/integration/test_environment_handover.py, the
second reader of group membership in this app (assert_may_edit_handover) —
this file's `assert_may_run` is the third, and the fixtures deliberately test
the same "no team degrades to Admin-only" and "wrong tenant is 404 not 403"
shapes that file and test_environment_requests_api.py already established.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.core.security import get_password_hash
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from tests.factories import ensure_environment, ensure_user_group


async def _login(client, tenant_slug, username, password="password123"):
    r = await client.post("/api/v1/auth/login", json={
        "username": username, "password": password, "tenant_slug": tenant_slug,
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def env_with_team(db_session, test_tenant):
    """An environment whose operations_group_id points at a group containing
    a known user, 'decom-team-member' — the user team_headers logs in as."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Decom Ops")
    env = await ensure_environment(db_session, test_tenant.id, slot=101)
    env.operations_group_id = group.id
    await db_session.flush()

    member = User(
        tenant_id=test_tenant.id, username="decom-team-member",
        email="decom-team-member@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=group.id, user_id=member.id
    ))
    await db_session.commit()
    return env


@pytest_asyncio.fixture
async def team_headers(client, test_tenant, env_with_team):
    """Bearer headers for 'decom-team-member', a member of env_with_team's
    operating team. Depends on env_with_team so the user exists first."""
    return await _login(client, test_tenant.slug, "decom-team-member")


@pytest_asyncio.fixture
async def other_member_headers(client, db_session, test_tenant, env_with_team):
    """A member of a DIFFERENT group — not env_with_team's operating team.
    Distinguishes 'not on any team' (member_headers, the shared fixture) from
    'on a team, just not this one' the way test_environment_handover.py's
    test_a_member_of_a_different_group_is_refused does."""
    other_group = await ensure_user_group(db_session, test_tenant.id, name="Other Ops")
    stranger = User(
        tenant_id=test_tenant.id, username="decom-other-team",
        email="decom-other-team@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(stranger)
    await db_session.flush()
    db_session.add(UserGroupMember(
        tenant_id=test_tenant.id, group_id=other_group.id, user_id=stranger.id
    ))
    await db_session.commit()
    return await _login(client, test_tenant.slug, "decom-other-team")


@pytest_asyncio.fixture
async def env_without_team(db_session, test_tenant):
    """operations_group_id is NULL — most environments today. The gate must
    degrade to Admin-only, not to nobody and not to everybody."""
    env = await ensure_environment(db_session, test_tenant.id, slot=102)
    env.operations_group_id = None
    await db_session.commit()
    return env


@pytest_asyncio.fixture
async def foreign_env(db_session, second_tenant_factory):
    """Another tenant's environment. Every route here must answer 404, never
    403, so a caller cannot use the status code to learn the row exists."""
    other_tenant, _other_admin = await second_tenant_factory(
        "Decom Foreign Org", "decom-foreign-org"
    )
    return await ensure_environment(db_session, other_tenant.id, slot=201)


@pytest.mark.asyncio
async def test_the_operations_team_may_initiate(client, team_headers, env_with_team):
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "Project closed"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "warned"


@pytest.mark.asyncio
async def test_the_teardown_date_defaults_to_the_notice_period(
    client, team_headers, env_with_team
):
    """§2.12's five-day warning, from the tenant's decommission_notice_days
    (the unsaved default policy's value — see get_policy)."""
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "Project closed"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    warned = datetime.fromisoformat(body["warned_at"])
    teardown = datetime.fromisoformat(body["scheduled_teardown_at"])
    assert (teardown - warned).days == 5


@pytest.mark.asyncio
async def test_the_initiator_may_set_a_later_date(client, team_headers, env_with_team):
    later = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "End of contract", "scheduled_teardown_at": later},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_the_initiator_may_not_shorten_the_notice(client, team_headers, env_with_team):
    """An initiator who could shorten the notice would make the five-day
    warning advisory, and the booking refusal derives from this date."""
    sooner = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
        json={"reason": "Urgent", "scheduled_teardown_at": sooner},
    )
    assert r.status_code == 422, r.text
    assert "notice" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_stranger_may_not_initiate(client, other_member_headers, env_with_team):
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=other_member_headers,
        json={"reason": "no"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_an_admin_may_always_initiate(client, auth_headers, env_with_team):
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=auth_headers,
        json={"reason": "Admin override"},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_with_no_operations_group_the_gate_degrades_to_admin_only(
    client, auth_headers, member_headers, env_without_team
):
    """B3b's rule, carried over verbatim. operations_group_id is nullable and
    most environments have no group yet; a permission resolving to nobody is a
    stuck workflow."""
    refused = await client.post(
        f"/api/v1/environments/{env_without_team.id}/decommission",
        headers=member_headers, json={"reason": "no"},
    )
    assert refused.status_code == 403, refused.text

    allowed = await client.post(
        f"/api/v1/environments/{env_without_team.id}/decommission",
        headers=auth_headers, json={"reason": "yes"},
    )
    assert allowed.status_code == 201, allowed.text


@pytest.mark.asyncio
async def test_only_one_live_decommission_per_environment(
    client, team_headers, env_with_team
):
    first = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "one"},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "two"},
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_a_reason_is_required(client, team_headers, env_with_team):
    """A decommission with no stated reason is not an audit record."""
    r = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "   "},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_another_tenants_environment_is_404_not_403(
    client, team_headers, foreign_env
):
    r = await client.post(
        f"/api/v1/environments/{foreign_env.id}/decommission",
        headers=team_headers, json={"reason": "no"},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_get_decommission_is_null_when_never_decommissioned(
    client, auth_headers, env_with_team
):
    """Null, not 404 — the panel's normal case must not be an error path."""
    r = await client.get(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() is None


@pytest.mark.asyncio
async def test_get_decommission_returns_the_live_record(
    client, team_headers, env_with_team
):
    created = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "check the getter"},
    )
    assert created.status_code == 201, created.text

    r = await client.get(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == created.json()["id"]
    assert r.json()["state"] == "warned"


@pytest.mark.asyncio
async def test_get_decommission_on_a_foreign_tenant_environment_is_404(
    client, team_headers, foreign_env
):
    r = await client.get(
        f"/api/v1/environments/{foreign_env.id}/decommission",
        headers=team_headers,
    )
    assert r.status_code == 404, r.text
