"""C4 RECORDS AND NEVER REFUSES.

The guard on the whole design, in the line of A3, A4, B2, B4, B5 and C2. If
any of these fails, C4 has started standing between a team and a recovery.

EnvManager does not execute rollbacks — CI does. `rollback_authorisation_
service.record_authorisation` validates ids only (release in tenant,
system_ids attached to the release); it never inspects plan state, rehearsal
state or the readiness verdict. Nothing in C4 is wired into the release
transition path, `can-deploy`, or the deployment status machine.

Fixture note: the brief's sketch used `release_with_changing_system` +
`system` + `policy_requiring_plans` straight from test_rollback_readiness.py
and test_rollback_plan.py. Reusing them directly is exactly the trap this
programme has hit three times before: test_rollback_readiness.py's own
`release_with_changing_system` only has a draft -> completed transition (no
`in_progress`), and test_rollback_plan.py's `system` fixture is attached to
a *different* release than `release_with_changing_system` (its own local
`release` fixture) — so posting rollback-authorisations with that system's
id against this release's id would 404 on the release_system membership
check, not prove anything about C4. Built self-contained fixtures below
instead, on `test_tenant`/`test_user` throughout (never the conftest
`tenant`/`system` fixtures, which point at a different tenant — "Phase3
Org" — the exact trap test_rollback_rehearsal.py hit).

The brief's `can-deploy` sketch used `environment_slug=environment.name` /
`subsystem_slug=subsystem.name`, matching C2's own guard note that
`Environment`/`SubSystem` have no `.slug` attribute — `preflight_service`
matches on `.name`. Kept as-is here.

The brief's deployment sketch spread `**deployment_in_success.webhook_
payload` after an explicit `"event_id": "c4-guard-1"` key in the same dict
literal — but a later key in a dict literal overrides an earlier one, so if
`webhook_payload` carried its own `event_id` the hardcoded one would be
silently discarded, and if it didn't, a NEW event_id starts a brand new
deployment at status `rolled_back` directly (`existing_is_None` skips the
whole transition-conflict check in `deployment_service.ingest`), which
proves nothing about "a deployment still reaches rolled_back" from
`success`. Fixed by having `deployment_in_success.webhook_payload` carry
the SAME event_id as the original ingest, and dropping the literal
`"event_id": "c4-guard-1"` override — the second POST must hit
`existing is not None` and walk `ALLOWED_TRANSITIONS["success"]`, which is
the actual thing the interfaces note asserts is allowed.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.models.environment import Environment
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import SubSystem, System
from app.services import api_key_service, change_request_service, rollback_policy_service
from tests.factories import ensure_environment, ensure_environment_tier, ensure_subsystem


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def api_key_headers(db_session, test_tenant, test_user) -> dict:
    """A key scoped for `webhooks:deployment` — the scope can-deploy and the
    deployment webhook both require."""
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=test_tenant.id, created_by=test_user.id,
        name="C4 Guard CI", scopes=["webhooks:deployment"],
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
async def system(db_session, test_tenant) -> System:
    """The changing component for the guard release below — deliberately
    NOT the conftest `system` fixture, which is built against `tenant`
    ("Phase3 Org"), a different tenant from `test_tenant`."""
    s = System(tenant_id=test_tenant.id, name="Payments API (C4 guard)")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def release_with_changing_system(db_session, test_tenant, test_user, system) -> Release:
    """A release reachable via draft -> in_progress, carrying ONE changing
    component (`system`) with NO rollback plan and NO rehearsal recorded —
    the exact shape release_readiness_service.evaluate() reports as
    `rollback_plan_missing` once a policy requires plans. Follows C2's
    `release_with_failed_block_gate` for the lifecycle shape (needs a real
    `in_progress` transition, unlike test_rollback_readiness.py's own
    release fixture, which only reaches `completed`)."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
        entity_type="release",
        name="C4 Guard Release Lifecycle",
        is_default=False,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "in_progress", "label": "In Progress", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "in_progress", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(template)
    await db_session.flush()

    release = Release(
        tenant_id=test_tenant.id,
        name="R-c4-guard",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()

    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release.id,
        system_id=system.id, role="changing",
    ))
    await db_session.commit()
    await db_session.refresh(release)
    return release


@pytest_asyncio.fixture
async def policy_requiring_plans(db_session, test_tenant):
    """Flips require_rollback_plan ON for real, through the real service
    call — follows test_rollback_readiness.py's fixture of the same name."""
    policy = await rollback_policy_service.update_policy(
        db_session, test_tenant.id, require_rollback_plan=True,
    )
    assert policy.require_rollback_plan is True, (
        "fixture must honestly produce a policy that REQUIRES a plan"
    )
    return policy


class _DeploymentInSuccess:
    def __init__(self, deployment_id: int, webhook_payload: dict):
        self.deployment_id = deployment_id
        self.webhook_payload = webhook_payload


@pytest_asyncio.fixture
async def deployment_in_success(client, db_session, test_tenant, test_user, api_key_headers) -> _DeploymentInSuccess:
    """A real deployment, ingested through the actual webhook, sitting in
    `success` — the state `success -> rolled_back` transitions from. Built
    against `test_tenant`, not conftest's `tenant`, to stay consistent with
    every other fixture in this file."""
    await change_request_service.seed_default_lifecycles(db_session, test_tenant.id)

    sys_ = System(tenant_id=test_tenant.id, name="Orders (C4 guard)")
    db_session.add(sys_)
    await db_session.flush()
    sub = SubSystem(tenant_id=test_tenant.id, system_id=sys_.id, name="orders-api-c4-guard")
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    env = Environment(tenant_id=test_tenant.id, name="sit-c4-guard", tier_id=tier.id)
    db_session.add_all([sub, env])
    await db_session.commit()

    event_id = str(uuid4())
    payload = {
        "event_id": event_id,
        "system_slug": sys_.name,
        "subsystem_slug": sub.name,
        "environment_slug": env.name,
        "status": "success",
        "deployed_at": datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc).isoformat(),
        "build": {
            "git_sha": "c4c4c4c4" * 4,
            "build_number": "#1",
            "commit_timestamp": datetime(2026, 8, 21, 1, 0, tzinfo=timezone.utc).isoformat(),
        },
    }
    resp = await client.post(
        "/api/v1/webhooks/deployment", json=payload, headers=api_key_headers,
    )
    assert resp.status_code == 200, resp.text
    deployment_id = resp.json()["deployment_id"]

    # webhook_payload carries the SAME event_id and every transport field
    # EXCEPT status — the guard test supplies its own status ("rolled_back").
    webhook_payload = {k: v for k, v in payload.items() if k != "status"}
    return _DeploymentInSuccess(deployment_id, webhook_payload)


# ── The guard ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_rollback_is_recordable_with_no_plan_and_a_blocking_policy(
    client, auth_headers, release_with_changing_system, system, policy_requiring_plans
):
    """The worst case: policy demands plans, none exists, production is on
    fire."""
    resp = await client.post(
        f"/api/v1/releases/{release_with_changing_system.id}/rollback-authorisations",
        json={
            "decided_at": "2026-08-21T02:14:00Z",
            "trigger": "error rate",
            "rationale": "reverting",
            "system_ids": [system.id],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_a_release_with_rollback_blockers_still_transitions(
    client, auth_headers, release_with_changing_system, policy_requiring_plans
):
    resp = await client.post(
        f"/api/v1/releases/{release_with_changing_system.id}/transition",
        json={"to_state": "in_progress"}, headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_can_deploy_answers_identically_with_and_without_rollback_state(
    client, api_key_headers, environment, subsystem, release_with_changing_system,
    policy_requiring_plans
):
    """can-deploy is UNTOUCHED by C4 — not one blocker, not one warning."""
    before = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}", headers=api_key_headers,
    )
    after = await client.get(
        f"/api/v1/webhooks/can-deploy?environment_slug={environment.name}"
        f"&subsystem_slug={subsystem.name}&release_id={release_with_changing_system.id}",
        headers=api_key_headers,
    )
    assert before.status_code == 200, before.text
    assert after.status_code == 200, after.text
    assert before.json()["blockers"] == after.json()["blockers"]
    assert before.json()["warnings"] == after.json()["warnings"]


@pytest.mark.asyncio
async def test_a_deployment_still_reaches_rolled_back(
    client, api_key_headers, deployment_in_success, policy_requiring_plans
):
    """Nothing in C4 may gate the deployment status machine. Reuses the
    SAME event_id as the original `success` ingest so this genuinely walks
    `deployment_service.ALLOWED_TRANSITIONS["success"]` rather than opening
    a brand-new deployment that starts life at `rolled_back`."""
    resp = await client.post(
        "/api/v1/webhooks/deployment",
        json={**deployment_in_success.webhook_payload, "status": "rolled_back"},
        headers=api_key_headers,
    )
    assert resp.status_code in (200, 201), resp.text
