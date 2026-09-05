"""Phase 9 C3 — Go/No-Go decision record."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.schemas.go_no_go import (
    GoNoGoConditionCreate,
    GoNoGoDecisionCreate,
    GoNoGoSignoffCreate,
)
from app.db.models.go_no_go import GoNoGoPerspective
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.services import go_no_go_defaults, go_no_go_service, rollback_policy_service
from tests.test_gate_readiness import _make_gate, _make_gate_type


# ── Local fixtures — NOT the shared `tenant`/`system` fixtures in conftest.py,
# which belong to a DIFFERENT tenant ("Phase3 Org") from `test_tenant`
# ("Test Org"). Mixing them silently queries across two tenants and can pass
# vacuously. Follows tests/test_rollback_plan.py:45-70, which scopes both to
# test_tenant for exactly this reason. ─────────────────────────────────────

@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user) -> Release:
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="Standard Release",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "completed", "allowed_roles": ["Admin"]},
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
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.flush()
    return r


@pytest_asyncio.fixture
async def other_tenant_user(second_tenant_factory):
    """A user in a SECOND tenant, built from conftest.py's
    `second_tenant_factory` — not the `tenant` fixture, which is a different
    tenant ("Phase3 Org") from `test_tenant` ("Test Org") and would let this
    test mix tenants silently rather than deliberately."""
    _, user = await second_tenant_factory()
    return user


async def _add_failing_blocking_gate(db_session, release, test_tenant) -> None:
    """A typed gate whose type's failure_behaviour is 'block' and whose own
    status is 'failed' — a blocker in release_readiness_service.evaluate's
    verdict. Built from tests/test_gate_readiness.py's own helpers
    (_make_gate_type / _make_gate), reused rather than reinvented."""
    gt = await _make_gate_type(
        db_session, test_tenant, name="SIT Exit", failure_behaviour="block"
    )
    await _make_gate(
        db_session, test_tenant, release, name="SIT Exit Gate",
        status="failed", gate_type_id=gt.id,
    )


@pytest.mark.asyncio
async def test_seeding_is_idempotent(db_session, test_tenant):
    await go_no_go_defaults.seed_go_no_go_perspective_defaults_for_tenant(
        db_session, test_tenant.id
    )
    await go_no_go_defaults.seed_go_no_go_perspective_defaults_for_tenant(
        db_session, test_tenant.id
    )
    rows = (await db_session.execute(
        select(GoNoGoPerspective).where(GoNoGoPerspective.tenant_id == test_tenant.id)
    )).scalars().all()
    assert [r.name for r in rows] == ["Quality", "Process", "Acceptance"]


@pytest.mark.asyncio
async def test_the_outcome_is_the_chairs_not_a_fold_of_the_signoffs(
    db_session, test_tenant, test_user, release
):
    """§2.11 asks for DISSENTS. A dissent only means something if the outcome
    can differ from unanimity — 'we went, over the Test Manager's objection'."""
    await go_no_go_defaults.seed_go_no_go_perspective_defaults_for_tenant(
        db_session, test_tenant.id
    )
    quality = (await db_session.execute(
        select(GoNoGoPerspective).where(
            GoNoGoPerspective.tenant_id == test_tenant.id,
            GoNoGoPerspective.name == "Quality",
        )
    )).scalar_one()

    decision = await go_no_go_service.record_decision(
        db_session, release.id, test_tenant.id, test_user.id,
        GoNoGoDecisionCreate(
            outcome="go",
            rationale="Residual risk accepted by the sponsor.",
            decided_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            attendees=[test_user.id],
            signoffs=[GoNoGoSignoffCreate(
                perspective_id=quality.id, user_id=test_user.id,
                verdict="no_go", dissent_note="Two P1 defects remain open.",
            )],
            conditions=[],
        ),
    )
    assert decision.outcome == "go"
    signoffs = await go_no_go_service.signoffs_for(db_session, decision.id)
    assert [(s.verdict, s.dissent_note) for s in signoffs] == [
        ("no_go", "Two P1 defects remain open.")
    ]


@pytest.mark.asyncio
async def test_a_decision_with_no_signoffs_is_recordable(
    db_session, test_tenant, test_user, release
):
    """C3 records; it does not police the completeness of its own record. A
    meeting where nobody signed is a real thing, and refusing to record it
    would be C3 refusing something."""
    decision = await go_no_go_service.record_decision(
        db_session, release.id, test_tenant.id, test_user.id,
        GoNoGoDecisionCreate(
            outcome="no_go", rationale="Quorum not reached.",
            decided_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            attendees=[], signoffs=[], conditions=[],
        ),
    )
    assert decision.id is not None


@pytest.mark.asyncio
async def test_the_snapshot_is_captured_server_side_and_does_not_move(
    db_session, test_tenant, test_user, release
):
    """The one place this codebase STORES what it elsewhere computes. An audit
    record that rewrites itself when a gate later passes is evidence of
    nothing."""
    decision = await go_no_go_service.record_decision(
        db_session, release.id, test_tenant.id, test_user.id,
        GoNoGoDecisionCreate(
            outcome="go", rationale="All clear.",
            decided_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            attendees=[], signoffs=[], conditions=[],
        ),
    )
    frozen_blockers = list(decision.snapshot_blockers)
    frozen_ok = decision.snapshot_ok

    # Change the world underneath the decision: add a failing blocking gate.
    await _add_failing_blocking_gate(db_session, release, test_tenant)

    reread = await go_no_go_service.get_decision(db_session, decision.id, test_tenant.id)
    assert reread.snapshot_blockers == frozen_blockers
    assert reread.snapshot_ok == frozen_ok


@pytest.mark.asyncio
async def test_a_blocking_rehearsal_finding_still_populates_the_snapshot_field(
    db_session, test_tenant, test_user, release
):
    """release_readiness_service._add() routes a rehearsal finding to
    `blockers`, not `warnings`, the moment a tenant sets
    require_current_rehearsal=True. snapshot_rehearsal_state must not go
    blank for exactly the tenant that treats a stale/missing rehearsal as a
    blocker — that would make snapshot_blockers name a rehearsal problem
    while snapshot_rehearsal_state claims there is none."""
    system = System(tenant_id=test_tenant.id, name="Payments API")
    db_session.add(system)
    await db_session.flush()
    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release.id,
        system_id=system.id, role="changing",
    ))
    await rollback_policy_service.update_policy(
        db_session, test_tenant.id, require_current_rehearsal=True,
    )
    await db_session.flush()

    decision = await go_no_go_service.record_decision(
        db_session, release.id, test_tenant.id, test_user.id,
        GoNoGoDecisionCreate(
            outcome="go", rationale="Proceeding despite the rehearsal gap.",
            decided_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            attendees=[], signoffs=[], conditions=[],
        ),
    )
    assert decision.snapshot_rehearsal_state == "rehearsal_missing"
    assert any(b["type"] == "rehearsal_missing" for b in decision.snapshot_blockers)


@pytest.mark.asyncio
async def test_a_naive_decided_at_is_normalized_to_utc_before_being_stored(
    db_session, test_tenant, test_user, release
):
    """decided_at is validated as UTC-assumed when naive (§2.11: backdating is
    legitimate). What gets STORED on the DateTime(timezone=True) column must
    be that same normalized value — not the original naive input — or the
    round-trip becomes dialect-dependent."""
    decision = await go_no_go_service.record_decision(
        db_session, release.id, test_tenant.id, test_user.id,
        GoNoGoDecisionCreate(
            outcome="go", rationale="All clear.",
            decided_at=datetime(2026, 9, 5, 10, 0),  # naive
            attendees=[], signoffs=[], conditions=[],
        ),
    )
    assert decision.decided_at.tzinfo is not None
    assert decision.decided_at == datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_future_decided_at_is_refused(
    db_session, test_tenant, test_user, release
):
    """Backdating is legitimate; postdating is not — C3 records a decision
    that was TAKEN."""
    with pytest.raises(HTTPException) as exc_info:
        await go_no_go_service.record_decision(
            db_session, release.id, test_tenant.id, test_user.id,
            GoNoGoDecisionCreate(
                outcome="go", rationale="All clear.",
                decided_at=datetime.now(timezone.utc) + timedelta(days=1),
                attendees=[], signoffs=[], conditions=[],
            ),
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_a_signatory_outside_the_tenant_still_resolves(
    db_session, test_tenant, other_tenant_user, release, test_user
):
    """Under master-admin impersonation a chair or signatory legitimately sits
    outside the decision's own tenant. A `User.tenant_id ==` join renders them
    as nobody — losing the one name a governance record exists to hold. This
    has already bitten A3, A4, B5 and C2."""
    names = await go_no_go_service.usernames_for(db_session, [other_tenant_user.id])
    assert names[other_tenant_user.id] == other_tenant_user.username


@pytest.mark.asyncio
async def test_closing_a_condition_does_not_touch_the_decision(
    db_session, test_tenant, test_user, release
):
    """Conditions are the ONE mutable part of an append-only record: closing
    one records a later FACT ABOUT the decision, not a rewrite of it."""
    decision = await go_no_go_service.record_decision(
        db_session, release.id, test_tenant.id, test_user.id,
        GoNoGoDecisionCreate(
            outcome="conditional_go", rationale="Go once the smoke pack passes.",
            decided_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            attendees=[], signoffs=[],
            conditions=[GoNoGoConditionCreate(text="Smoke pack green in UAT")],
        ),
    )
    before = (decision.outcome, decision.rationale, list(decision.snapshot_blockers))

    conditions = await go_no_go_service.conditions_for(db_session, decision.id)
    closed = await go_no_go_service.close_condition(
        db_session, conditions[0].id, test_tenant.id, test_user.id, met=True
    )
    assert closed.met_at is not None
    assert closed.met_by_user_id == test_user.id

    reread = await go_no_go_service.get_decision(db_session, decision.id, test_tenant.id)
    assert (reread.outcome, reread.rationale, list(reread.snapshot_blockers)) == before


# ── HTTP endpoints (Task 4) ──────────────────────────────────────────────────
#
# Following backend/tests/test_c4_records_never_refuses.py's shape: `client` +
# `auth_headers` (test_user is Admin in test_tenant), and the local `release`
# fixture above — NOT the conftest `tenant`/`system` fixtures, which point at
# a different tenant ("Phase3 Org").

async def _rm_headers(client, db_session, test_tenant) -> dict:
    """Bearer token headers for a Release Manager user in test_tenant.

    No shared fixture for this role exists in conftest.py (only `member_headers`
    for a Developer); built locally the way
    test_booking_standard_field_permissions.py does.
    """
    from app.core.security import get_password_hash
    from app.db.models.user import User

    user = User(
        tenant_id=test_tenant.id,
        username="gonogorm",
        email="gonogorm@test.com",
        password_hash=get_password_hash("password123"),
        role="Release Manager",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post("/api/v1/auth/login", json={
        "username": user.username,
        "password": "password123",
        "tenant_slug": test_tenant.slug,
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user


def _decision_payload(decided_at: datetime, **overrides) -> dict:
    payload = {
        "outcome": "go",
        "rationale": "All clear.",
        "decided_at": decided_at.isoformat(),
        "attendees": [],
        "signoffs": [],
        "conditions": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_post_go_no_go_returns_201_with_the_decision(
    client, auth_headers, test_user, release
):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/go-no-go",
        json=_decision_payload(datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)),
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["outcome"] == "go"
    assert body["release_id"] == release.id
    assert body["chaired_by_username"] == test_user.username
    assert body["signoffs"] == []
    assert body["conditions"] == []
    assert body["unmet_condition_count"] == 0


@pytest.mark.asyncio
async def test_get_go_no_go_returns_history_newest_first_with_total_count(
    client, auth_headers, release
):
    earlier = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    later = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    for when, rationale in ((earlier, "First meeting."), (later, "Second meeting.")):
        resp = await client.post(
            f"/api/v1/releases/{release.id}/go-no-go",
            json=_decision_payload(when, rationale=rationale),
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

    resp = await client.get(
        f"/api/v1/releases/{release.id}/go-no-go", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Total-Count"] == "2"
    body = resp.json()
    assert [d["rationale"] for d in body] == ["Second meeting.", "First meeting."]


@pytest.mark.asyncio
async def test_get_go_no_go_with_an_unknown_sort_by_is_422_not_a_silent_fallback(
    client, auth_headers, release
):
    resp = await client.get(
        f"/api/v1/releases/{release.id}/go-no-go",
        params={"sort_by": "nonsense"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_recording_a_decision_is_admin_or_release_manager_only(
    client, auth_headers, member_headers, db_session, test_tenant, release
):
    """A Developer gets 403; Admin and Release Manager both succeed —
    `require_role(Role.RELEASE_MANAGER)` already grants an Admin bypass."""
    resp = await client.post(
        f"/api/v1/releases/{release.id}/go-no-go",
        json=_decision_payload(datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)),
        headers=member_headers,
    )
    assert resp.status_code == 403

    resp = await client.post(
        f"/api/v1/releases/{release.id}/go-no-go",
        json=_decision_payload(
            datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc), rationale="Admin recorded this."
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text

    rm_headers, _ = await _rm_headers(client, db_session, test_tenant)
    resp = await client.post(
        f"/api/v1/releases/{release.id}/go-no-go",
        json=_decision_payload(
            datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc), rationale="RM recorded this."
        ),
        headers=rm_headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_patch_go_no_go_condition_closes_it(client, auth_headers, test_user, release):
    resp = await client.post(
        f"/api/v1/releases/{release.id}/go-no-go",
        json=_decision_payload(
            datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            outcome="conditional_go",
            rationale="Go once the smoke pack passes.",
            conditions=[{"text": "Smoke pack green in UAT", "owner_user_id": test_user.id}],
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    condition_id = resp.json()["conditions"][0]["id"]

    resp = await client.patch(
        f"/api/v1/go-no-go-conditions/{condition_id}",
        json={"met": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["met_at"] is not None
    assert body["met_by_username"] == test_user.username


@pytest.mark.asyncio
async def test_closing_a_condition_is_owner_or_admin_rm_only(
    client, member_headers, auth_headers, test_user, release
):
    """The Developer created for `member_headers` is neither the condition's
    owner (test_user is) nor Admin/RM, so closing it 403s; the owner (Admin
    here, satisfying both branches) still succeeds."""
    resp = await client.post(
        f"/api/v1/releases/{release.id}/go-no-go",
        json=_decision_payload(
            datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            outcome="conditional_go",
            rationale="Go once the smoke pack passes.",
            conditions=[{"text": "Smoke pack green in UAT", "owner_user_id": test_user.id}],
        ),
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    condition_id = resp.json()["conditions"][0]["id"]

    resp = await client.patch(
        f"/api/v1/go-no-go-conditions/{condition_id}",
        json={"met": True},
        headers=member_headers,
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"/api/v1/go-no-go-conditions/{condition_id}",
        json={"met": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


# ── Perspective CRUD HTTP endpoints (fix round 1) ────────────────────────────
#
# Following backend/tests/integration/test_gate_types_api.py's house pattern:
# `client` + `auth_headers` (Admin) + `member_headers` (Developer), asserting
# the write gate and status codes explicitly rather than trusting the code.

@pytest.mark.asyncio
async def test_a_tenant_member_can_read_the_seeded_perspectives_in_sort_order(
    client, auth_headers, member_headers, db_session, test_tenant
):
    await go_no_go_defaults.seed_go_no_go_perspective_defaults_for_tenant(
        db_session, test_tenant.id
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/tenant/go-no-go-perspectives", headers=member_headers
    )
    assert resp.status_code == 200, resp.text
    assert [p["name"] for p in resp.json()] == ["Quality", "Process", "Acceptance"]


@pytest.mark.asyncio
async def test_a_non_admin_cannot_create_or_update_a_perspective(
    client, auth_headers, member_headers
):
    resp = await client.post(
        "/api/v1/tenant/go-no-go-perspectives",
        json={"name": "Legal"},
        headers=member_headers,
    )
    assert resp.status_code == 403, resp.text

    created = await client.post(
        "/api/v1/tenant/go-no-go-perspectives",
        json={"name": "Legal"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    perspective_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/tenant/go-no-go-perspectives/{perspective_id}",
        json={"is_active": False},
        headers=member_headers,
    )
    assert updated.status_code == 403, updated.text


@pytest.mark.asyncio
async def test_an_admin_can_create_and_deactivate_a_perspective(client, auth_headers):
    created = await client.post(
        "/api/v1/tenant/go-no-go-perspectives",
        json={"name": "Security", "description": "Security sign-off.", "sort_order": 40},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Security"
    assert body["is_active"] is True
    perspective_id = body["id"]

    updated = await client.patch(
        f"/api/v1/tenant/go-no-go-perspectives/{perspective_id}",
        json={"is_active": False},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_active"] is False
    # The unchanged fields prove `exclude_unset` semantics: an omitted key
    # means "leave alone", not "reset to a default".
    assert updated.json()["name"] == "Security"
    assert updated.json()["sort_order"] == 40


@pytest.mark.asyncio
async def test_a_duplicate_perspective_name_for_the_same_tenant_is_409_not_500(
    client, auth_headers
):
    first = await client.post(
        "/api/v1/tenant/go-no-go-perspectives",
        json={"name": "Compliance"},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text

    dup = await client.post(
        "/api/v1/tenant/go-no-go-perspectives",
        json={"name": "Compliance"},
        headers=auth_headers,
    )
    assert dup.status_code == 409, dup.text


@pytest.mark.asyncio
async def test_a_name_duplicating_another_tenants_perspective_is_accepted(
    client, auth_headers, second_tenant_factory
):
    """The uniqueness constraint is per-tenant (`uq_go_no_go_perspective_
    tenant_name`), not global."""
    other_tenant, other_user = await second_tenant_factory()

    first = await client.post(
        "/api/v1/tenant/go-no-go-perspectives",
        json={"name": "Ops"},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text

    login = await client.post("/api/v1/auth/login", json={
        "username": other_user.username,
        "password": "password123",
        "tenant_slug": other_tenant.slug,
    })
    assert login.status_code == 200, login.text
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    second = await client.post(
        "/api/v1/tenant/go-no-go-perspectives",
        json={"name": "Ops"},
        headers=other_headers,
    )
    assert second.status_code == 201, second.text
