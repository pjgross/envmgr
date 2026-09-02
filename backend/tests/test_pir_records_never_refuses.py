"""PIR FINDINGS, ACTIONS AND CITATIONS RECORD. THEY REFUSE NOTHING.

A PIR is written after go-live, about a release people already consider
finished. Nothing here may block a release transition, an incident transition, a
deployment, or a booking — not an incomplete PIR, not a went-wrong finding, not
an overdue open action, not a cited incident.

requirements.md §2.5 asks for a configurable "PIR complete" gate before a release
is formally closed. That is deliberately NOT built, and this file is what will
fail the day someone builds it here by accident.

IF ANY TEST IN THIS FILE FAILS, THE PIR WORK HAS STARTED REFUSING SOMETHING.

The seventh sub-project running whose central promise is a named test rather
than an absence in the diff — after A3, A4, B2, B4, B5, C2 and C4.

Proved non-vacuous: inserting a real 409 on overdue actions into
`release_service.transition_release` makes
`test_a_release_with_an_overdue_action_still_transitions` fail, and removing it
again makes it pass. A guard nobody has watched fail is a guard nobody knows
works.

Fixture note, and it is the whole reason this file builds its own: every fixture
here hangs off `test_tenant`/`test_user`, never conftest's `tenant`/`user`
(a DIFFERENT tenant, "Phase3 Org"). `auth_headers` authenticates into
`test_tenant`, so a file mixing the two queries across tenants and passes
vacuously — the trap recorded in CLAUDE.md that C4's guard and
test_rollback_rehearsal.py both hit.

The plan sketched `GET /releases/{id}/allowed-transitions`. THERE IS NO SUCH
ROUTE. Rather than assert on the advertised transition list of a nearby one,
these tests PERFORM the transition and assert it succeeds — which is the claim
anyway, and is what the temporary refusal above actually breaks.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.models.environment import Environment
from app.db.models.incident import Incident
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.system import SubSystem, System
from app.services import api_key_service, change_request_service
from app.services.incident_defaults import seed_incident_defaults_for_tenant
from tests.factories import ensure_environment_tier

UTC = timezone.utc


@pytest_asyncio.fixture
async def guard_release(db_session, test_tenant, test_user) -> Release:
    """A release reachable via draft -> completed, so a transition can actually
    be attempted rather than merely advertised."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="PIR Guard Release Lifecycle",
        is_default=False,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False,
                 "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(template)
    await db_session.flush()
    release = Release(
        tenant_id=test_tenant.id,
        name="R-pir-guard",
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=template.id,
        status="draft",
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(release)
    return release


@pytest_asyncio.fixture
async def incident(db_session, test_tenant) -> Incident:
    await seed_incident_defaults_for_tenant(db_session, test_tenant.id)
    inc = Incident(tenant_id=test_tenant.id, title="Checkout 500s (PIR guard)", severity="P1",
                   status="new", detected_at=datetime(2026, 8, 1, tzinfo=UTC), source="manual")
    db_session.add(inc)
    await db_session.flush()
    await db_session.commit()
    return inc


@pytest_asyncio.fixture
async def bad_pir(client, auth_headers, guard_release, incident) -> int:
    """A release whose review is as damning as this feature can make it:
    incomplete, a went-wrong finding, an overdue open action, a cited incident.
    Returns the release id."""
    rid = guard_release.id
    assert (await client.post(f"/api/v1/releases/{rid}/pir", json={"summary": "s"},
                              headers=auth_headers)).status_code == 201
    fid = (await client.post(
        f"/api/v1/releases/{rid}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test",
              "root_cause": "Perf gate optional"}, headers=auth_headers)).json()["id"]
    assert (await client.post(
        f"/api/v1/releases/{rid}/pir/findings/{fid}/actions",
        json={"title": "Make the perf gate mandatory", "due_date": "2020-01-01T00:00:00Z"},
        headers=auth_headers)).status_code == 201
    assert (await client.post(
        f"/api/v1/releases/{rid}/pir/findings/{fid}/incidents",
        json={"incident_id": incident.id}, headers=auth_headers)).status_code == 201
    return rid


@pytest.mark.asyncio
async def test_the_fixture_really_is_as_bad_as_it_claims(client, auth_headers, bad_pir):
    """Guards the guard. If the fixture stops producing an overdue open action on
    an incomplete PIR, every test below passes while testing nothing."""
    body = (await client.get(f"/api/v1/releases/{bad_pir}/pir", headers=auth_headers)).json()
    assert body["status"] == "draft"
    action = body["findings"][0]["actions"][0]
    assert action["status"] == "open"
    assert action["is_overdue"] is True
    assert body["findings"][0]["incidents"] != []
    # And it is visible as outstanding work on the tenant-wide worklist, which is
    # the surface a "PIR complete" gate would most plausibly be wired to.
    worklist = (await client.get("/api/v1/pir-actions?overdue=true",
                                 headers=auth_headers)).json()
    assert [r["title"] for r in worklist] == ["Make the perf gate mandatory"]


@pytest.mark.asyncio
async def test_a_release_with_an_overdue_action_still_transitions(client, auth_headers, bad_pir):
    """The release moves, with an incomplete review and an overdue action on it."""
    resp = await client.post(f"/api/v1/releases/{bad_pir}/transition",
                             json={"to_state": "completed"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_the_cited_incident_still_transitions(client, auth_headers, bad_pir, incident):
    """Being cited in someone's review is not a hold on the incident."""
    detail = (await client.get(f"/api/v1/incidents/{incident.id}",
                               headers=auth_headers)).json()
    assert detail["pir_citations"] != []
    assert detail["allowed_transitions"] != []
    resp = await client.post(f"/api/v1/incidents/{incident.id}/transition",
                             json={"to_state": "investigating"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "investigating"


@pytest.mark.asyncio
async def test_an_incident_with_no_citation_is_still_fully_usable(client, auth_headers, incident):
    """Nothing anywhere requires an incident to be reviewed. The absence of a
    citation is an ordinary state, not a gap to be closed."""
    detail = (await client.get(f"/api/v1/incidents/{incident.id}",
                               headers=auth_headers)).json()
    assert detail["pir_citations"] == []
    assert detail["allowed_transitions"] != []


@pytest.mark.asyncio
async def test_the_readiness_verdict_says_nothing_about_pirs(client, auth_headers, bad_pir):
    """C2 and C4's verdict is read BEFORE a release goes live. A finding written
    afterwards must not appear in it — not as a blocker and not as a warning."""
    body = (await client.get(f"/api/v1/releases/{bad_pir}/readiness",
                             headers=auth_headers)).json()
    blob = str(body).lower()
    assert "pir" not in blob
    assert "post-implementation" not in blob
    assert "no load test" not in blob


@pytest.mark.asyncio
async def test_completing_a_pir_moves_nothing_on_the_release(client, auth_headers, bad_pir):
    """The other direction: a COMPLETE review does not advance anything either.
    Recording is not deciding."""
    before = (await client.get(f"/api/v1/releases/{bad_pir}", headers=auth_headers)).json()
    resp = await client.patch(f"/api/v1/releases/{bad_pir}/pir", json={"status": "complete"},
                              headers=auth_headers)
    assert resp.status_code == 200, resp.text
    after = (await client.get(f"/api/v1/releases/{bad_pir}", headers=auth_headers)).json()
    assert after["status"] == before["status"]
    assert after["actual_date"] == before["actual_date"]


@pytest_asyncio.fixture
async def api_key_headers(db_session, test_tenant, test_user) -> dict:
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=test_tenant.id, created_by=test_user.id,
        name="PIR Guard CI", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    return {"X-Api-Key": raw}


@pytest_asyncio.fixture
async def deployable(db_session, test_tenant):
    """A subsystem and an environment `can-deploy` can be asked about."""
    await change_request_service.seed_default_lifecycles(db_session, test_tenant.id)
    sys_ = System(tenant_id=test_tenant.id, name="Orders (PIR guard)")
    db_session.add(sys_)
    await db_session.flush()
    sub = SubSystem(tenant_id=test_tenant.id, system_id=sys_.id, name="orders-api-pir-guard")
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    env = Environment(tenant_id=test_tenant.id, name="sit-pir-guard", tier_id=tier.id)
    db_session.add_all([sub, env])
    await db_session.commit()
    return sub, env


@pytest.mark.asyncio
async def test_a_booking_can_still_be_made_while_an_overdue_action_exists(
    client, auth_headers, db_session, test_tenant, test_user, test_booking_type, bad_pir
):
    """The docstring at the top of this file promises bookings too, and until
    this test it promised something nothing here checked.

    A PIR action is raised after a release has gone live, about a delivery
    already considered finished — it cannot reach back and make an environment
    unbookable. `booking_request_service.create_request` is the modern path and
    the one B4/B5 guard the same way.
    """
    from app.services import booking_request_service
    from tests.factories import ensure_environment

    # conftest's `test_booking_type` — a booking type needs a lifecycle template
    # with an initial state, and building one by hand here would be a second,
    # drifting copy of that fixture.
    environment = await ensure_environment(db_session, test_tenant.id)

    start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    # The second element is the CONFLICTS map, not the bookings — an empty dict
    # is the ordinary case, so asserting on it would prove nothing either way.
    request, _conflicts = await booking_request_service.create_request(
        db_session,
        {
            "project_name": "Booked despite an overdue PIR action",
            "booking_type_id": test_booking_type.id,
            "start_date": start,
            "end_date": start + timedelta(days=2),
            "environment_ids": [environment.id],
        },
        test_user,
        test_tenant.id,
        now=datetime.now(UTC),
    )
    assert request.id is not None
    assert [b.environment_id for b in request.bookings] == [environment.id]


@pytest.mark.asyncio
async def test_can_deploy_is_byte_identical_with_and_without_the_pir(
    client, auth_headers, api_key_headers, deployable, guard_release, incident
):
    """`GET /webhooks/can-deploy` is what a pipeline obeys. A PIR is written after
    the deployment it reviews; it cannot retroactively refuse one.

    Asserted as "the same answer before and after", which is the claim stated
    directly — a test that merely checked `can_deploy is True` would pass even
    if a PIR turned a yes into a differently-worded yes.
    """
    sub, env = deployable
    rid = guard_release.id
    url = (f"/api/v1/webhooks/can-deploy?environment_slug={env.name}"
           f"&subsystem_slug={sub.name}&release_id={rid}")

    before = await client.get(url, headers=api_key_headers)
    assert before.status_code == 200, before.text

    await client.post(f"/api/v1/releases/{rid}/pir", json={"summary": "s"}, headers=auth_headers)
    fid = (await client.post(
        f"/api/v1/releases/{rid}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test"},
        headers=auth_headers)).json()["id"]
    await client.post(f"/api/v1/releases/{rid}/pir/findings/{fid}/actions",
                      json={"title": "A", "due_date": "2020-01-01T00:00:00Z"},
                      headers=auth_headers)
    await client.post(f"/api/v1/releases/{rid}/pir/findings/{fid}/incidents",
                      json={"incident_id": incident.id}, headers=auth_headers)

    after = await client.get(url, headers=api_key_headers)
    assert after.status_code == 200, after.text
    # `checked_at` is a per-request clock, not a verdict — everything else must
    # match exactly, the `ok` flag and every reason among it.
    assert {k: v for k, v in after.json().items() if k != "checked_at"} == \
        {k: v for k, v in before.json().items() if k != "checked_at"}
    assert "checked_at" in before.json(), "the excluded key must actually exist"


@pytest.mark.asyncio
async def test_a_deployment_still_lands_with_an_overdue_pir_action(
    client, api_key_headers, deployable, bad_pir
):
    """The webhook a pipeline calls after deploying. An overdue PIR action on
    some release in the tenant must not make a deployment unrecordable."""
    sub, env = deployable
    payload = {
        "event_id": str(uuid4()),
        "system_slug": "Orders (PIR guard)",
        "subsystem_slug": sub.name,
        "environment_slug": env.name,
        "status": "success",
        "deployed_at": datetime(2026, 8, 30, 2, 0, tzinfo=UTC).isoformat(),
        "build": {
            "git_sha": "abcd1234" * 5,
            "build_number": "#1",
            "commit_timestamp": datetime(2026, 8, 30, 1, 0, tzinfo=UTC).isoformat(),
        },
    }
    resp = await client.post("/api/v1/webhooks/deployment", json=payload,
                             headers=api_key_headers)
    assert resp.status_code == 200, resp.text
