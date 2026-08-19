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
from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_decommission import (
    EnvironmentDecommission, EnvironmentDecommissionStep,
)
from app.db.models.user import User
from app.db.models.user_group import UserGroupMember
from app.services import environment_decommission_service
from tests.factories import ensure_environment, ensure_user_group, make_booking


def _iso(*, days: int) -> str:
    """A timestamp `days` from now, ISO-8601 — the same shape the extension
    routes accept for `until`."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


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


@pytest.mark.asyncio
async def test_an_empty_group_degrades_to_admin_only(
    client, auth_headers, db_session, test_tenant
):
    """The other half of "degrades to Admin-only": a group that EXISTS but has
    NO MEMBERS must take the same code path as no group at all (a NULL
    operations_group_id, covered by test_with_no_operations_group_the_gate_
    degrades_to_admin_only). A membership check that special-cased the NULL
    FK but forgot the empty-join case would pass that test and still leave an
    empty group's environment permanently actionable by nobody but an admin
    who has to be told to intervene by accident."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Empty Decom Ops")
    env = await ensure_environment(db_session, test_tenant.id, slot=103)
    env.operations_group_id = group.id
    outsider = User(
        tenant_id=test_tenant.id, username="decom-empty-group-outsider",
        email="decom-empty-group-outsider@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(outsider)
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "decom-empty-group-outsider")

    refused = await client.post(
        f"/api/v1/environments/{env.id}/decommission",
        headers=headers, json={"reason": "no"},
    )
    assert refused.status_code == 403, refused.text

    allowed = await client.post(
        f"/api/v1/environments/{env.id}/decommission",
        headers=auth_headers, json={"reason": "yes"},
    )
    assert allowed.status_code == 201, allowed.text


@pytest.mark.asyncio
async def test_initiate_takes_one_injected_clock_not_two(
    db_session, test_tenant, test_user, env_with_team
):
    """ONE CLOCK PER REQUEST. `initiate` must not call `datetime.now()`
    itself — it must use exactly the `now` its caller hands it, and the
    stored `warned_at` must equal that instant EXACTLY, not merely be close
    to it (which a second, independent `datetime.now()` call a millisecond
    later would also satisfy). Pin a clock nowhere near the real wall clock
    so an accidental fallback to `datetime.now()` would fail this
    unmistakably rather than by a flaky microsecond margin.
    """
    pinned = datetime(2030, 6, 15, 9, 0, 0, tzinfo=timezone.utc)

    row = await environment_decommission_service.initiate(
        db_session, test_tenant.id, env_with_team.id, test_user,
        reason="pin the clock", now=pinned,
    )

    # SQLite hands back a naive datetime where PostgreSQL hands back an aware
    # one (the same engine difference `environment_decommission_service._utc`
    # exists to paper over) — normalise before comparing, not before storing.
    warned_at = row.warned_at
    if warned_at.tzinfo is None:
        warned_at = warned_at.replace(tzinfo=timezone.utc)
    assert warned_at == pinned
    # The same instant, fed to the state function the route uses to render
    # `state`, must agree with what was just stored -- proving there is one
    # clock for the whole request, not one for the write and another for the
    # read.
    assert environment_decommission_service.decommission_state(row, pinned) == "warned"


# ---------------------------------------------------------------------------
# Task 6 — the extension: the owner asking for more time, and the operating
# team granting or refusing it. `assert_may_defend` (the owner-side gate) has
# no coverage anywhere until this section — Task 5 wrote it but no route
# called it.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def env_with_owner_and_team(db_session, test_tenant, env_with_team):
    """`env_with_team`'s environment, plus a NAMED OWNER who is deliberately
    NOT a member of the operating team — the pairing every extension test
    needs, since requesting is gated on the owner and deciding on the team,
    and a fixture where one person is both would hide the difference."""
    owner = User(
        tenant_id=test_tenant.id, username="decom-owner",
        email="decom-owner@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(owner)
    await db_session.flush()
    env_with_team.owner_user_id = owner.id
    await db_session.commit()
    await db_session.refresh(env_with_team)
    return env_with_team


@pytest_asyncio.fixture
async def owner_headers(client, test_tenant, env_with_owner_and_team) -> dict:
    """Bearer headers for 'decom-owner', env_with_owner_and_team's named
    owner — not on the operating team, following assert_may_defend."""
    return await _login(client, test_tenant.slug, "decom-owner")


@pytest_asyncio.fixture
async def live_decommission(
    client, db_session, test_tenant, env_with_owner_and_team, team_headers,
    decommission_steps_seeded,
) -> EnvironmentDecommission:
    """A live decommission on env_with_owner_and_team, created through the
    real initiate route (as the operating team) so it carries every invariant
    that route enforces, rather than being built by hand.

    Depends on `decommission_steps_seeded` (added in Task 7): `test_tenant`
    is a bare row built directly, bypassing `tenant_service.create_tenant` —
    the only real path that seeds `final_backup`/`teardown` — so every
    attestation/teardown test needs the tenant's step vocabulary to actually
    exist, the same reason `environment_request_lifecycle` exists for B3b's
    tests."""
    r = await client.post(
        f"/api/v1/environments/{env_with_owner_and_team.id}/decommission",
        headers=team_headers, json={"reason": "extension fixture"},
    )
    assert r.status_code == 201, r.text
    row = await environment_decommission_service.get_most_recent(
        db_session, test_tenant.id, env_with_owner_and_team.id
    )
    return row


@pytest_asyncio.fixture
async def torn_down_decommission(
    db_session, test_tenant, env_with_owner_and_team, test_user
) -> EnvironmentDecommission:
    """A decommission that has already been torn down — built directly, since
    Task 6 ships no teardown route yet. `test_a_torn_down_decommission_takes_
    no_extension` exists precisely because `request_extension` must consult
    `live_predicate`, not just `extension_requested_at`."""
    now = datetime.now(timezone.utc)
    row = EnvironmentDecommission(
        tenant_id=test_tenant.id,
        environment_id=env_with_owner_and_team.id,
        reason="torn down fixture",
        warned_at=now,
        scheduled_teardown_at=now + timedelta(days=5),
        initiated_by=test_user.id,
        torn_down_at=now,
        torn_down_by=test_user.id,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_the_owner_may_request_an_extension(client, owner_headers, live_decommission):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers,
        json={"reason": "UAT runs to month end", "until": _iso(days=30)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "extension_requested"


@pytest.mark.asyncio
async def test_granting_moves_the_date_and_keeps_the_record(
    client, team_headers, owner_headers, live_decommission
):
    """Branch 3 stops matching and the row falls through to `warned` on the new
    clock — the audit trail survives because the block is not cleared."""
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers,
        json={"reason": "need it", "until": _iso(days=30)},
    )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": True},
    )
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["state"] == "warned"
    assert body["extension_granted"] is True
    assert body["extension_reason"] == "need it"
    assert body["scheduled_teardown_at"].startswith(_iso(days=30)[:10])


@pytest.mark.asyncio
async def test_refusing_moves_nothing(client, team_headers, owner_headers, live_decommission):
    before = live_decommission.scheduled_teardown_at
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "please", "until": _iso(days=30)},
    )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["extension_granted"] is False
    assert r.json()["scheduled_teardown_at"] == before.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_only_one_extension_per_decommission(
    client, team_headers, owner_headers, live_decommission
):
    """A second request is refused, pointing at cancel-and-re-raise."""
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "first", "until": _iso(days=30)},
    )
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": False},
    )
    second = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "again", "until": _iso(days=60)},
    )
    assert second.status_code == 409, second.text
    assert "cancel" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_the_team_may_not_request_an_extension_on_the_owners_behalf(
    client, team_headers, live_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=team_headers, json={"reason": "x", "until": _iso(days=30)},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_the_owner_may_not_decide_their_own_request(
    client, owner_headers, live_decommission
):
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": _iso(days=30)},
    )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=owner_headers, json={"granted": True},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_an_extension_must_be_later_than_the_current_date(
    client, owner_headers, live_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": _iso(days=1)},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_a_torn_down_decommission_takes_no_extension(
    client, owner_headers, torn_down_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{torn_down_decommission.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": _iso(days=30)},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_a_non_owner_tenant_member_may_not_request_an_extension(
    client, db_session, test_tenant, env_with_owner_and_team, live_decommission
):
    """The other half of assert_may_defend's coverage: an ordinary tenant
    member who is neither the owner nor on the operating team is 403 —
    distinguishing 'not the owner' from 'is the team', which
    test_the_team_may_not_request_an_extension_on_the_owners_behalf already
    covers."""
    stranger = User(
        tenant_id=test_tenant.id, username="decom-ext-stranger",
        email="decom-ext-stranger@example.com",
        password_hash=get_password_hash("password123"), role="Developer",
        is_active=True,
    )
    db_session.add(stranger)
    await db_session.commit()
    headers = await _login(client, test_tenant.slug, "decom-ext-stranger")

    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=headers, json={"reason": "x", "until": _iso(days=30)},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_an_admin_may_request_and_decide_an_extension(
    client, auth_headers, live_decommission
):
    """Admin is the bypass on BOTH gates — assert_may_defend and
    assert_may_run agree on that even though they otherwise gate opposite
    parties."""
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=auth_headers, json={"reason": "admin request", "until": _iso(days=30)},
    )
    assert r.status_code == 200, r.text

    d = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=auth_headers, json={"granted": True},
    )
    assert d.status_code == 200, d.text
    assert d.json()["extension_granted"] is True


@pytest.mark.asyncio
async def test_deciding_with_no_open_request_is_409(
    client, team_headers, env_with_owner_and_team
):
    """No request has ever been made against a freshly-initiated
    decommission — decide_extension must refuse, not silently no-op."""
    created = await client.post(
        f"/api/v1/environments/{env_with_owner_and_team.id}/decommission",
        headers=team_headers, json={"reason": "no request yet"},
    )
    assert created.status_code == 201, created.text

    r = await client.post(
        f"/api/v1/decommissions/{created.json()['id']}/extension/decision",
        headers=team_headers, json={"granted": True},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_a_foreign_tenants_decommission_is_404_not_403(
    client, owner_headers, db_session, second_tenant_factory
):
    """Cross-tenant is 404, never 403, on both extension routes — the same
    rule every other decommission route follows, per contentions.py."""
    other_tenant, other_admin = await second_tenant_factory(
        "Decom Extension Foreign Org", "decom-ext-foreign-org"
    )
    other_env = await ensure_environment(db_session, other_tenant.id, slot=301)
    other_row = EnvironmentDecommission(
        tenant_id=other_tenant.id,
        environment_id=other_env.id,
        reason="foreign",
        warned_at=datetime.now(timezone.utc),
        scheduled_teardown_at=datetime.now(timezone.utc) + timedelta(days=5),
        initiated_by=other_admin.id,
    )
    db_session.add(other_row)
    await db_session.commit()
    await db_session.refresh(other_row)

    r = await client.post(
        f"/api/v1/decommissions/{other_row.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": _iso(days=30)},
    )
    assert r.status_code == 404, r.text

    d = await client.post(
        f"/api/v1/decommissions/{other_row.id}/extension/decision",
        headers=owner_headers, json={"granted": True},
    )
    assert d.status_code == 404, d.text


# ---------------------------------------------------------------------------
# Task 6 review — two gaps carried forward, fixed here rather than in a new
# file since they extend coverage already in this section.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_extension_equal_to_the_current_date_is_refused(
    client, owner_headers, live_decommission
):
    """The STRICT-INEQUALITY BOUNDARY was untested:
    test_an_extension_must_be_later_than_the_current_date uses a date well
    inside the "too early" region, so a mutant relaxing `until_utc <=
    current_teardown` to `<` in `request_extension` passed the whole suite.
    `until` set to EXACTLY the current `scheduled_teardown_at` must still be
    a 422 — equal is not later."""
    equal = live_decommission.scheduled_teardown_at.isoformat()
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "x", "until": equal},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_only_one_extension_per_decommission_after_a_grant(
    client, team_headers, owner_headers, live_decommission
):
    """test_only_one_extension_per_decommission only exercised the guard
    after a REFUSAL. The guard keys on `extension_requested_at`, which a
    grant sets identically to a refusal, so a second request must 409 the
    same way after a GRANT — untested until now."""
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "first", "until": _iso(days=30)},
    )
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension/decision",
        headers=team_headers, json={"granted": True},
    )
    second = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/extension",
        headers=owner_headers, json={"reason": "again", "until": _iso(days=60)},
    )
    assert second.status_code == 409, second.text
    assert "cancel" in second.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Task 7 — attestations, gated teardown and cancel. `live_decommission` now
# depends on `decommission_steps_seeded`, so `final_backup`/`teardown` exist
# for every test below without each one seeding them by hand.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def booking_after_teardown(
    db_session, test_tenant, test_user, env_with_owner_and_team, live_decommission
):
    """A booking still on the calendar when teardown runs. Depends on
    `live_decommission` so the booking is created against the SAME
    environment id the decommission targets (env_with_owner_and_team and
    env_with_team are the same row — the latter fixture mutates and returns
    the former). TEARDOWN SURFACES THIS, NEVER TOUCHES IT: the response
    names it; a mutation proof below and the Task 15 guard test both cover
    that the row itself is unchanged."""
    return await make_booking(
        db_session, test_tenant.id,
        booked_by=test_user.id, environment=env_with_owner_and_team,
    )


@pytest.mark.asyncio
async def test_teardown_is_refused_until_every_required_step_is_signed(
    client, team_headers, live_decommission
):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    # NAMING the missing steps — a bare "not allowed" on a checklist is
    # unactionable.
    assert "final_backup" in detail and "teardown" in detail


@pytest.mark.asyncio
async def test_signing_every_step_permits_teardown(client, team_headers, live_decommission):
    for key in ("final_backup", "teardown"):
        s = await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers,
            json={"step_key": key, "reference": "SNAP-1", "notes": None},
        )
        assert s.status_code == 201

    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert r.status_code == 200
    assert r.json()["state"] == "torn_down"


@pytest.mark.asyncio
async def test_teardown_decommissions_the_environment(
    client, team_headers, db_session, live_decommission
):
    """THE ONE ACTING STEP. This and the booking refusal are the whole of what
    B5 changes outside its own records."""
    for key in ("final_backup", "teardown"):
        await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers, json={"step_key": key, "reference": "x", "notes": None},
        )
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )

    env = await db_session.get(Environment, live_decommission.environment_id)
    await db_session.refresh(env)
    assert env.status == EnvironmentStatus.DECOMMISSIONED


@pytest.mark.asyncio
async def test_an_optional_step_does_not_gate_teardown(
    client, team_headers, db_session, test_tenant, live_decommission
):
    step = EnvironmentDecommissionStep(
        tenant_id=test_tenant.id, key="dns", label="DNS removed",
        display_order=30, is_required=False, is_active=True,
    )
    db_session.add(step)
    await db_session.flush()

    for key in ("final_backup", "teardown"):
        await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers, json={"step_key": key, "reference": "x", "notes": None},
        )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_an_inactive_step_does_not_gate_teardown(
    client, team_headers, db_session, test_tenant, live_decommission
):
    """A retired step stops being required; it does not freeze the workflow.
    `is_required=True` here on purpose — it is INACTIVITY, not the required
    flag, that exempts it."""
    step = EnvironmentDecommissionStep(
        tenant_id=test_tenant.id, key="legacy_check", label="Legacy check",
        display_order=40, is_required=True, is_active=False,
    )
    db_session.add(step)
    await db_session.flush()

    for key in ("final_backup", "teardown"):
        await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers, json={"step_key": key, "reference": "x", "notes": None},
        )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_a_step_may_be_signed_only_once(client, team_headers, live_decommission):
    first = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers, json={"step_key": "final_backup", "reference": "a", "notes": None},
    )
    assert first.status_code == 201
    again = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers, json={"step_key": "final_backup", "reference": "b", "notes": None},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_a_signed_attestation_survives_a_reload(
    client, team_headers, live_decommission
):
    """B5 Task 12's fix: `GET /environments/{id}/decommission` must be able
    to tell the panel what has already been signed, or a reload makes an
    already-signed step look unsigned and a second sign attempt 409s with no
    explanation the UI can show. Checks the GET carries `step_key`, the
    signer's NAME (never a bare id — this repo's "never #N" rule), and the
    reference — and that the second sign attempt still 409s, same as
    test_a_step_may_be_signed_only_once above."""
    signed = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers,
        json={"step_key": "final_backup", "reference": "SNAP-42", "notes": None},
    )
    assert signed.status_code == 201, signed.text

    r = await client.get(
        f"/api/v1/environments/{live_decommission.environment_id}/decommission",
        headers=team_headers,
    )
    assert r.status_code == 200, r.text
    attestations = r.json()["attestations"]
    assert len(attestations) == 1
    entry = attestations[0]
    assert entry["step_key"] == "final_backup"
    assert entry["reference"] == "SNAP-42"
    assert entry["signed_by_username"] == "decom-team-member"

    again = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers,
        json={"step_key": "final_backup", "reference": "b", "notes": None},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_the_worklist_never_carries_attestations(
    client, team_headers, live_decommission
):
    """THIS MUST STAY OFF THE WORKLIST — signing a step must not turn every
    worklist row into a per-row query. `DecommissionWorklistRow.from_view`
    hardcodes an empty list rather than calling `list_attestations`."""
    signed = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers,
        json={"step_key": "final_backup", "reference": "SNAP-42", "notes": None},
    )
    assert signed.status_code == 201, signed.text

    r = await client.get("/api/v1/decommissions", headers=team_headers)
    assert r.status_code == 200, r.text
    row = next(row for row in r.json() if row["id"] == live_decommission.id)
    assert row["attestations"] == []


@pytest.mark.asyncio
async def test_an_unknown_step_key_is_refused(client, team_headers, live_decommission):
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/attestations",
        headers=team_headers, json={"step_key": "invented", "reference": None, "notes": None},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_admin_may_always_cancel(client, auth_headers, live_decommission):
    """THE ESCAPE HATCH. A4 established that an approval workflow without one
    produces unrecoverable states, and B3b shipped two."""
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/cancel",
        headers=auth_headers, json={"reason": "Kept after all"},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_cancelling_leaves_the_environment_active(
    client, auth_headers, db_session, live_decommission
):
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/cancel",
        headers=auth_headers, json={"reason": "Kept"},
    )
    env = await db_session.get(Environment, live_decommission.environment_id)
    await db_session.refresh(env)
    assert env.status == EnvironmentStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_cancelled_decommission_frees_the_environment_for_a_new_one(
    client, auth_headers, team_headers, live_decommission, env_with_team
):
    await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/cancel",
        headers=auth_headers, json={"reason": "Kept"},
    )
    again = await client.post(
        f"/api/v1/environments/{env_with_team.id}/decommission",
        headers=team_headers, json={"reason": "Actually no"},
    )
    assert again.status_code == 201


@pytest.mark.asyncio
async def test_teardown_reports_the_bookings_it_did_not_touch(
    client, team_headers, live_decommission, booking_after_teardown
):
    """SURFACES, never touches. The response names them; the rows are unchanged
    — the guard test in Task 15 proves the second half."""
    for key in ("final_backup", "teardown"):
        await client.post(
            f"/api/v1/decommissions/{live_decommission.id}/attestations",
            headers=team_headers, json={"step_key": key, "reference": "x", "notes": None},
        )
    r = await client.post(
        f"/api/v1/decommissions/{live_decommission.id}/teardown", headers=team_headers
    )
    assert booking_after_teardown.id in [b["id"] for b in r.json()["remaining_bookings"]]
