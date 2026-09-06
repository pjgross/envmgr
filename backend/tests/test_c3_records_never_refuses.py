"""C3 RECORDS; IT REFUSES NOTHING.

The guard on the whole design, in the line of A3, A4, B2, B4, C2, C4 and the
PIR work. If any of these fails, C3 has started standing between a release
and its own release manager. A recorded `no_go` is the single most
plausible thing a future implementer would be tempted to wire into a
refusal ("well, obviously you shouldn't be able to ship after a no_go") —
so every check here is built against a release carrying a live `no_go`
decision, the worst case for this promise.

Fixture note: follows test_c2_advises_never_blocks.py's and
test_c4_records_never_refuses.py's shape — self-contained fixtures on
`test_tenant`/`test_user` throughout, never the conftest `tenant`/`system`
fixtures (a different tenant, "Phase3 Org"), and the legacy single-
environment `POST /api/v1/bookings/` (`BookingCreate`) for the booking
check because that is the write path that actually carries `release_id` —
`BookingRequestCreate` has no such field, exactly the reason C2's own
booking check used it.

`GET /api/v1/webhooks/can-deploy` has no injectable clock — `checked_at` is
`datetime.now(timezone.utc)` at call time, so it is the one field in the
response that is EXPECTED to differ between the two calls regardless of C3.
The comparison below pops that one key and then compares the two response
bodies for full equality, not just `blockers`/`warnings` — a preflight that
started refusing could still answer 200 with a changed `ok` or a new
`claim_matched`, which a narrower comparison would miss.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.models.booking_lifecycle import BookingType
from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.system import SubSystem, System
from app.services import api_key_service, change_request_service, lifecycle_service
from tests.factories import ensure_environment, ensure_environment_tier, ensure_subsystem


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_key_headers(db_session, test_tenant, test_user) -> dict:
    """A key scoped for `webhooks:deployment` — the scope can-deploy and the
    deployment webhook both require."""
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=test_tenant.id, created_by=test_user.id,
        name="C3 Guard CI", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    return {"X-Api-Key": raw}


@pytest_asyncio.fixture
async def environment(db_session, test_tenant):
    return await ensure_environment(db_session, test_tenant.id)


@pytest_asyncio.fixture
async def subsystem(db_session, test_tenant):
    return await ensure_subsystem(db_session, test_tenant.id)


@pytest_asyncio.fixture
async def booking_type(db_session, test_tenant) -> BookingType:
    """A booking type with a genuine lifecycle template (draft initial) —
    follows test_c2_advises_never_blocks.py's fixture of the same name."""
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="booking",
        name="c3-guard-booking-lifecycle",
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(
        tenant_id=test_tenant.id, name="c3-guard-booking-type", lifecycle_template_id=tpl.id
    )
    db_session.add(bt)
    await db_session.commit()
    await db_session.refresh(bt)
    return bt


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user) -> Release:
    """Reachable draft -> in_progress -> completed, both transitions
    Admin-only — two real transitions so "every transition allowed before is
    still allowed" is a non-trivial comparison, not a check against an empty
    list."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="C3 Guard Release Lifecycle",
        is_default=False,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "in_progress", "label": "In Progress", "is_initial": False, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "in_progress", "allowed_roles": ["Admin"]},
                {"from_state": "in_progress", "to_state": "completed", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(template)
    await db_session.flush()

    r = Release(
        tenant_id=test_tenant.id,
        name="R-c3-guard",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


async def _record_no_go(client, auth_headers, release_id: int) -> None:
    """POST one `no_go` decision on `release_id` — factored out so the
    transition test (fix round 1) can call this itself, BETWEEN its own
    before/after reads, rather than receiving a release that already has
    the decision baked in by a fixture."""
    resp = await client.post(
        f"/api/v1/releases/{release_id}/go-no-go",
        json={
            "outcome": "no_go",
            "rationale": "C3 guard: recorded deliberately to prove nothing downstream refuses.",
            "decided_at": "2026-09-05T10:00:00Z",
            "attendees": [],
            "signoffs": [],
            "conditions": [],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


@pytest_asyncio.fixture
async def release_with_no_go_decision(client, auth_headers, release) -> Release:
    """The release above, carrying one recorded `no_go` decision — the worst
    case: a future implementer reasoning "well, obviously you can't ship
    after a no_go" is exactly the refusal this whole guard exists to catch."""
    await _record_no_go(client, auth_headers, release.id)
    return release


# ── The guard ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_release_transition_allowed_before_is_still_allowed(
    client, auth_headers, release
):
    """Compares the computed allowed-transitions set from BEFORE any
    decision exists on this release to AFTER a `no_go` is recorded on it —
    genuinely across the write, not two reads both taken post-decision —
    then actually walks one of them, proving the computed answer and the
    real write path agree.

    Uses the plain `release` fixture (no decision yet) rather than
    `release_with_no_go_decision`: that fixture already POSTs the decision
    before the test body runs, which would make `status_before` a read
    taken AFTER the decision too, and the equality assertion would hold no
    matter what `record_decision` did to the release."""
    release_id = release.id

    lifecycle_resp = await client.get(
        f"/api/v1/releases/{release_id}/lifecycle", headers=auth_headers
    )
    assert lifecycle_resp.status_code == 200, lifecycle_resp.text
    definition = lifecycle_resp.json()["definition"]

    release_resp = await client.get(f"/api/v1/releases/{release_id}", headers=auth_headers)
    assert release_resp.status_code == 200, release_resp.text
    status_before = release_resp.json()["status"]

    before = lifecycle_service.get_allowed_transitions(definition, status_before, "Admin")
    assert before, "fixture must offer at least one real transition to compare"

    # NOW record the no_go — everything above ran with no decision on the
    # release at all.
    await _record_no_go(client, auth_headers, release_id)

    release_resp_after = await client.get(f"/api/v1/releases/{release_id}", headers=auth_headers)
    status_after = release_resp_after.json()["status"]
    after = lifecycle_service.get_allowed_transitions(definition, status_after, "Admin")

    assert after == before

    # And the transition genuinely still succeeds end to end.
    transition_resp = await client.post(
        f"/api/v1/releases/{release_id}/transition",
        json={"to_state": before[0]["to_state"]},
        headers=auth_headers,
    )
    assert transition_resp.status_code == 200, transition_resp.text


@pytest.mark.asyncio
async def test_can_deploy_answers_identically_with_and_without_the_decision(
    client, api_key_headers, environment, subsystem, release_with_no_go_decision
):
    """can-deploy is UNTOUCHED by C3 — the full response body, not just
    `blockers`/`warnings`, is identical apart from `checked_at`, the one
    field expected to differ because the endpoint has no injectable clock."""
    before = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}", headers=api_key_headers,
    )
    after = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}&release_id={release_with_no_go_decision.id}",
        headers=api_key_headers,
    )
    assert before.status_code == 200, before.text
    assert after.status_code == 200, after.text

    before_body = before.json()
    after_body = after.json()
    before_body.pop("checked_at")
    after_body.pop("checked_at")
    assert before_body == after_body


@pytest.mark.asyncio
async def test_a_deployment_can_still_be_recorded(
    client, api_key_headers, db_session, test_tenant, release_with_no_go_decision
):
    """A deployment against the release carrying the `no_go` — release_id is
    set on the payload so this is genuinely a deployment OF this release,
    not merely one that happens to exist alongside it."""
    await change_request_service.seed_default_lifecycles(db_session, test_tenant.id)

    sys_ = System(tenant_id=test_tenant.id, name="Orders (C3 guard)")
    db_session.add(sys_)
    await db_session.flush()
    sub = SubSystem(tenant_id=test_tenant.id, system_id=sys_.id, name="orders-api-c3-guard")
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    env = Environment(tenant_id=test_tenant.id, name="sit-c3-guard", tier_id=tier.id)
    db_session.add_all([sub, env])
    await db_session.commit()

    payload = {
        "event_id": str(uuid4()),
        "system_slug": sys_.name,
        "subsystem_slug": sub.name,
        "environment_slug": env.name,
        "status": "success",
        "deployed_at": datetime(2026, 9, 5, 11, 0, tzinfo=timezone.utc).isoformat(),
        "release_id": release_with_no_go_decision.id,
        "build": {
            "git_sha": "c3c3c3c3" * 4,
            "build_number": "#1",
            "commit_timestamp": datetime(2026, 9, 5, 10, 30, tzinfo=timezone.utc).isoformat(),
        },
    }
    resp = await client.post(
        "/api/v1/webhooks/deployment", json=payload, headers=api_key_headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_booking_can_still_be_created_on_the_release(
    client, auth_headers, environment, booking_type, release_with_no_go_decision
):
    """Uses the legacy single-environment POST /bookings/ (BookingCreate)
    because that's the write path that actually carries release_id —
    booking-requests' BookingRequestCreate has no such field. Same call C2's
    own guard makes."""
    resp = await client.post(
        "/api/v1/bookings/",
        json={
            "environment_id": environment.id,
            "project_name": "unaffected by a no_go decision",
            "booking_type_id": booking_type.id,
            "start_date": "2026-09-06T09:00:00Z",
            "end_date": "2026-09-07T17:00:00Z",
            "release_id": release_with_no_go_decision.id,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
