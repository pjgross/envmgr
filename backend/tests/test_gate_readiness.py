from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.schemas.gate_evidence import GateEvidenceCreate
from app.db.models.build import Build
from app.db.models.gate_type import GateType
from app.db.models.gate_waiver import GateWaiver
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services import gate_evidence_service, gate_readiness_service, release_gate_service
from tests.factories import ensure_deployment, ensure_environment


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user) -> Release:
    """A persisted Release under test_tenant, following the gate/waiver/
    evidence test precedent."""
    template = LifecycleTemplate(
        tenant_id=test_tenant.id,
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


async def _make_gate(db_session, test_tenant, release, *, name="Gate", status="pending",
                      gate_type_id=None) -> ReleaseGate:
    g = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name=name,
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status=status,
        gate_type_id=gate_type_id,
    )
    db_session.add(g)
    await db_session.commit()
    await db_session.refresh(g)
    return g


async def _make_gate_type(db_session, test_tenant, *, name="Sign-off",
                           failure_behaviour="block", expected_evidence=None) -> GateType:
    gt = GateType(
        tenant_id=test_tenant.id,
        name=name,
        failure_behaviour=failure_behaviour,
        expected_evidence=expected_evidence or [],
    )
    db_session.add(gt)
    await db_session.commit()
    await db_session.refresh(gt)
    return gt


# ── Per-test fixtures, one per rules-table row ───────────────────────────────

@pytest_asyncio.fixture
async def pending_block_gate(db_session, test_tenant, release) -> ReleaseGate:
    """A typed gate whose type's failure_behaviour is 'block', still pending."""
    gt = await _make_gate_type(db_session, test_tenant, name="Go/No-Go", failure_behaviour="block")
    return await _make_gate(db_session, test_tenant, release, name="Go/No-Go Gate",
                             status="pending", gate_type_id=gt.id)


@pytest_asyncio.fixture
async def failed_gate(db_session, test_tenant, release) -> ReleaseGate:
    """A gate that was failed outright — never waived, never a warning."""
    gt = await _make_gate_type(db_session, test_tenant, name="SIT Exit", failure_behaviour="block")
    return await _make_gate(db_session, test_tenant, release, name="SIT Exit Gate",
                             status="failed", gate_type_id=gt.id)


@pytest_asyncio.fixture
async def overridden_gate_with_live_waiver(db_session, test_tenant, test_user, release) -> ReleaseGate:
    """Overridden via the real service call, so a real GateWaiver row with a
    live (far-future) expiry backs it — honestly produces what the name says."""
    gt = await _make_gate_type(db_session, test_tenant, name="UAT Exit", failure_behaviour="block")
    gate = await _make_gate(db_session, test_tenant, release, name="UAT Exit Gate",
                             status="pending", gate_type_id=gt.id)
    await release_gate_service.override_gate(
        db_session, gate.id, notes="accepted risk", tenant_id=test_tenant.id,
        user_id=test_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        remediation="fix in next sprint",
        approved_by_user_id=test_user.id,
    )
    await db_session.commit()
    await db_session.refresh(gate)
    return gate


@pytest_asyncio.fixture
async def overridden_gate_with_expired_waiver(db_session, test_tenant, test_user, release) -> ReleaseGate:
    """Overridden with a waiver whose expiry is genuinely in the past —
    inserted directly since override_gate always waives with a caller-given
    expiry, and none is naturally in the past at call time."""
    gt = await _make_gate_type(db_session, test_tenant, name="PreProd Exit", failure_behaviour="block")
    gate = await _make_gate(db_session, test_tenant, release, name="PreProd Exit Gate",
                             status="overridden", gate_type_id=gt.id)
    waiver = GateWaiver(
        tenant_id=test_tenant.id,
        gate_id=gate.id,
        reason="temporary risk acceptance",
        approved_by_user_id=test_user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=10),
        created_by=test_user.id,
    )
    db_session.add(waiver)
    await db_session.commit()
    await db_session.refresh(gate)
    return gate


@pytest_asyncio.fixture
async def gate_overridden_before_c2(db_session, test_tenant, release) -> ReleaseGate:
    """Status is 'overridden' but there is deliberately NO GateWaiver row —
    exactly what a pre-C2 override left behind."""
    gt = await _make_gate_type(db_session, test_tenant, name="Legacy Exit", failure_behaviour="block")
    return await _make_gate(db_session, test_tenant, release, name="Legacy Exit Gate",
                             status="overridden", gate_type_id=gt.id)


@pytest_asyncio.fixture
async def untyped_pending_gate(db_session, test_tenant, release) -> ReleaseGate:
    """gate_type_id is null — this is the default state of every gate that
    predates C2, with no backfill."""
    return await _make_gate(db_session, test_tenant, release, name="Untyped Gate",
                             status="pending", gate_type_id=None)


@pytest_asyncio.fixture
async def passed_gate_expecting_two_kinds_with_one(db_session, test_tenant, test_user, release) -> ReleaseGate:
    """A passed gate whose type expects two evidence kinds, but only one has
    been supplied."""
    gt = await _make_gate_type(
        db_session, test_tenant, name="UAT Sign-off", failure_behaviour="warn",
        expected_evidence=["Test execution report", "Defect summary"],
    )
    gate = await _make_gate(db_session, test_tenant, release, name="UAT Sign-off Gate",
                             status="passed", gate_type_id=gt.id)
    await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Test execution report", label="Regression run",
                            url="https://ci.example/1"),
    )
    await db_session.commit()
    await db_session.refresh(gate)
    return gate


@pytest_asyncio.fixture
async def passed_gate_with_stale_evidence(db_session, test_tenant, test_user, release):
    """Evidence links a deployment that a later successful deployment of the
    same subsystem+environment has since superseded — genuinely stale, not
    merely labelled so.

    Returns (gate, earlier_deployment, later_deployment) — the test needs
    both deployments' own build identity to assert the warning names both."""
    gt = await _make_gate_type(db_session, test_tenant, name="SIT Sign-off", failure_behaviour="warn")
    gate = await _make_gate(db_session, test_tenant, release, name="SIT Sign-off Gate",
                             status="passed", gate_type_id=gt.id)

    # ensure_deployment resolves its subsystem via the idempotent
    # ensure_subsystem(default name), so two calls with no override land on
    # the SAME subsystem+environment pair — exactly what makes the second
    # deployment supersede the first.
    env = await ensure_environment(db_session, test_tenant.id)
    earlier = await ensure_deployment(
        db_session, test_tenant.id, env.id,
        deployed_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    later = await ensure_deployment(
        db_session, test_tenant.id, env.id,
        deployed_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    await db_session.commit()

    await gate_evidence_service.add_evidence(
        db_session, gate.id, test_tenant.id, test_user.id,
        GateEvidenceCreate(kind="Deployment record", label="Named in both deployments",
                            url=None, deployment_id=earlier.id),
    )
    await db_session.commit()
    await db_session.refresh(gate)
    return gate, earlier, later


# ── Tests, one per row of the rules table ────────────────────────────────────

@pytest.mark.asyncio
async def test_a_pending_block_gate_is_a_blocker(db_session, test_tenant, release, pending_block_gate):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is False
    assert [b.type for b in result.blockers] == ["gate_pending"]
    assert result.blockers[0].ref_id == pending_block_gate.id


@pytest.mark.asyncio
async def test_a_failed_gate_is_a_blocker(db_session, test_tenant, release, failed_gate):
    """A failure is not waived, it is failed. To waive it you override it."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert [b.type for b in result.blockers] == ["gate_failed"]


@pytest.mark.asyncio
async def test_an_overridden_gate_with_a_live_waiver_is_only_a_warning(
    db_session, test_tenant, release, overridden_gate_with_live_waiver
):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    assert [w.type for w in result.warnings] == ["gate_waived"]


@pytest.mark.asyncio
async def test_an_expired_waiver_makes_the_gate_unmet_again(
    db_session, test_tenant, release, overridden_gate_with_expired_waiver
):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is False
    assert [b.type for b in result.blockers] == ["waiver_expired"]


@pytest.mark.asyncio
async def test_a_legacy_override_with_no_waiver_row_warns(
    db_session, test_tenant, release, gate_overridden_before_c2
):
    """Gates overridden before C2 keep their status and have no waiver row.
    They must not become blockers on the day this ships."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    assert [w.type for w in result.warnings] == ["gate_waived_no_record"]


@pytest.mark.asyncio
async def test_an_untyped_gate_warns_and_never_blocks(
    db_session, test_tenant, release, untyped_pending_gate
):
    """gate_type_id ships nullable with no backfill, so EVERY gate in EVERY
    existing tenant is untyped until someone types it. Inventing 'block' would
    turn on a wall of blockers nobody configured."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    assert [w.type for w in result.warnings] == ["gate_untyped"]


@pytest.mark.asyncio
async def test_a_passed_gate_missing_expected_evidence_warns(
    db_session, test_tenant, release, passed_gate_expecting_two_kinds_with_one
):
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok is True
    warning = next(w for w in result.warnings if w.type == "evidence_missing")
    assert "Defect summary" in warning.detail


@pytest.mark.asyncio
async def test_stale_evidence_warns_and_names_both_deployments(
    db_session, test_tenant, release, passed_gate_with_stale_evidence
):
    gate, earlier, later = passed_gate_with_stale_evidence
    earlier_build = (
        await db_session.execute(select(Build).where(Build.id == earlier.build_id))
    ).scalar_one()
    later_build = (
        await db_session.execute(select(Build).where(Build.id == later.build_id))
    ).scalar_one()

    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    warning = next(w for w in result.warnings if w.type == "evidence_stale")
    assert warning.ref_id is not None
    assert result.ok is True
    # The whole point of this test's name: BOTH deployments are actually
    # named, not just "a deployment has since been superseded".
    assert earlier_build.build_number in warning.detail
    assert later_build.build_number in warning.detail
    assert earlier_build.build_number != later_build.build_number


@pytest.mark.asyncio
async def test_ok_is_exactly_the_absence_of_blockers(
    db_session, test_tenant, release, pending_block_gate
):
    """ok is derived in one expression, mirroring preflight_service's
    `ok=len(blockers) == 0`. It cannot drift from blockers because it IS
    blockers."""
    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.ok == (len(result.blockers) == 0)


# ── Tenant isolation, proven by mutation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluate_404s_a_release_from_another_tenant(
    db_session, test_tenant, release, second_tenant_factory
):
    """Proven by mutation: fails if `Release.tenant_id == tenant_id` is
    removed from evaluate's release lookup."""
    other_tenant, _ = await second_tenant_factory()

    with pytest.raises(HTTPException) as exc:
        await gate_readiness_service.evaluate(db_session, release.id, other_tenant.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_evaluate_ignores_a_gate_row_whose_tenant_id_is_mismatched(
    db_session, test_tenant, release, second_tenant_factory
):
    """release_id alone already scopes ReleaseGate rows to test_tenant's own
    release (a release id is never shared across tenants), so a gate created
    through the normal write path can never probe ReleaseGate.tenant_id's own
    filter. This inserts a row directly, simulating corrupted data or a
    second write path that skips validation — the same shape as
    test_gate_evidence.py's mismatched-tenant probe — to exercise the
    query's own filter independent of write-path guarantees. Proven by
    mutation: fails if `ReleaseGate.tenant_id == tenant_id` is removed from
    evaluate's gate query."""
    other_tenant, _other_admin = await second_tenant_factory()

    mismatched = ReleaseGate(
        tenant_id=other_tenant.id,  # deliberately NOT test_tenant.id
        release_id=release.id,  # but points at test_tenant's own release
        name="Should never be evaluated",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status="failed",
    )
    db_session.add(mismatched)
    await db_session.commit()

    result = await gate_readiness_service.evaluate(db_session, release.id, test_tenant.id)
    assert result.blockers == []
    assert result.ok is True
