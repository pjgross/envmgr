"""GET /api/v1/webhooks/release-ready (API-key) and
GET /api/v1/releases/{release_id}/readiness (JWT) — HTTP integration tests.

Both routes are thin wrappers around `gate_readiness_service.evaluate`, so
these tests exercise the AUTH and ROUTING layer C2 Task 7 adds, not the gate
rules themselves (Task 6's `tests/test_gate_readiness.py` owns those).
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models.gate_type import GateType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import api_key_service


# ── Fixtures ──────────────────────────────────────────────────────────────────

async def _release_lifecycle_template(db_session, tenant_id) -> LifecycleTemplate:
    template = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Test Major",
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
    return template


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user) -> Release:
    """A persisted, gate-free release under test_tenant."""
    template = await _release_lifecycle_template(db_session, test_tenant.id)
    r = Release(
        tenant_id=test_tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


@pytest_asyncio.fixture
async def release_with_blocker(db_session, test_tenant, release) -> Release:
    """The same release, plus a pending gate typed to block — a genuine
    blocker `evaluate()` will report, not a fabricated response."""
    gt = GateType(
        tenant_id=test_tenant.id, name="Go/No-Go", failure_behaviour="block",
    )
    db_session.add(gt)
    await db_session.flush()
    gate = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name="Go/No-Go Gate",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status="pending",
        gate_type_id=gt.id,
    )
    db_session.add(gate)
    await db_session.commit()
    await db_session.refresh(release)
    return release


@pytest_asyncio.fixture
async def api_key_headers(db_session, test_tenant, test_user) -> dict:
    """A key scoped for `webhooks:release`, in test_tenant — the scope the
    pipeline endpoint requires, deliberately not `webhooks:deployment`."""
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=test_tenant.id, created_by=test_user.id,
        name="CI release-ready", scopes=["webhooks:release"],
    )
    await db_session.commit()
    return {"X-Api-Key": raw}


@pytest_asyncio.fixture
async def deployment_only_api_key_headers(db_session, test_tenant, test_user) -> dict:
    """A key with ONLY the pre-existing deployment scope — must not be able
    to read governance detail through the new scope."""
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=test_tenant.id, created_by=test_user.id,
        name="CI deploy-only", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    return {"X-Api-Key": raw}


@pytest_asyncio.fixture
async def other_tenant_release(db_session, second_tenant_factory) -> Release:
    """A release that genuinely lives in a DIFFERENT tenant from
    api_key_headers/auth_headers, so a leak would be a real cross-tenant
    read, not merely a wrong-id lookup within the same tenant."""
    other_tenant, other_user = await second_tenant_factory()
    template = await _release_lifecycle_template(db_session, other_tenant.id)
    r = Release(
        tenant_id=other_tenant.id,
        name="Other Tenant's Release",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=other_user.id,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_it_always_returns_200_even_when_blocked(client, api_key_headers, release_with_blocker):
    """HTTP status is not the gate — can_deploy.py's docstring states the
    contract and this endpoint inherits it. A pipeline reads the body."""
    resp = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={release_with_blocker.id}",
        headers=api_key_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert resp.json()["blockers"]


@pytest.mark.asyncio
async def test_a_key_without_the_release_scope_is_refused(client, deployment_only_api_key_headers, release):
    """A new scope, not a reuse of webhooks:deployment: reusing it would
    silently widen what every existing deployment key can read to include
    waiver reasons, approver names and evidence URLs."""
    resp = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={release.id}", headers=deployment_only_api_key_headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_release_in_another_tenant_is_404(client, api_key_headers, other_tenant_release):
    resp = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={other_tenant_release.id}", headers=api_key_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_ui_route_and_the_pipeline_route_agree(
    client, auth_headers, api_key_headers, release_with_blocker
):
    """One evaluator, two surfaces. A gate chip contradicting the endpoint a
    pipeline obeys would be worse than neither."""
    ui = await client.get(f"/api/v1/releases/{release_with_blocker.id}/readiness", headers=auth_headers)
    pipeline = await client.get(
        f"/api/v1/webhooks/release-ready?release_id={release_with_blocker.id}",
        headers=api_key_headers,
    )
    assert ui.status_code == 200, ui.text
    assert pipeline.status_code == 200, pipeline.text
    assert ui.json()["ok"] == pipeline.json()["ok"]
    assert [b["ref_id"] for b in ui.json()["blockers"]] == [
        b["ref_id"] for b in pipeline.json()["blockers"]
    ]


@pytest.mark.asyncio
async def test_ui_route_is_not_swallowed_by_the_release_id_catchall(client, auth_headers, release_with_blocker):
    """B6 lost a red-run afternoon to a literal segment ('contention-horizon')
    registered after a `/{id}` catch-all that captured it and 422'd on int
    coercion. This route is two segments (`/{release_id}/readiness`), so no
    single-segment sibling can shadow it — proved here by calling it and
    checking the response is the READINESS shape (an `ok`/`blockers` verdict),
    not GET /{release_id}'s full ReleaseRead, and not a 422."""
    resp = await client.get(f"/api/v1/releases/{release_with_blocker.id}/readiness", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["release_id"] == release_with_blocker.id
    assert "blockers" in body and "warnings" in body
    assert "ok" in body
    # A ReleaseRead response (the catch-all's shape) has no 'ok'/'blockers' —
    # if this were swallowed, either of these keys would be absent instead.


@pytest.mark.asyncio
async def test_pipeline_route_404s_a_nonexistent_release(client, api_key_headers):
    resp = await client.get(
        "/api/v1/webhooks/release-ready?release_id=999999", headers=api_key_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ui_route_requires_auth(client, release):
    resp = await client.get(f"/api/v1/releases/{release.id}/readiness")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pipeline_route_requires_an_api_key(client, release):
    resp = await client.get(f"/api/v1/webhooks/release-ready?release_id={release.id}")
    assert resp.status_code == 401
