"""Evidence goes stale when its deployment is superseded.

Evidence links deployment D — build of subsystem S into environment E at time
T. It is STALE only if a LATER SUCCESSFUL deployment of S into E exists.
'success' is load-bearing: a failed redeploy leaves the evidence's own build
still running, and a rolled_back deployment means the earlier build is what
is running again — neither may supersede anything.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.gate_evidence import GateEvidence
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.services.gate_evidence_service import stale_evidence_ids
from tests.factories import ensure_change_request, ensure_environment, ensure_subsystem

UTC = timezone.utc
T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

_build_seq = 0
_deploy_seq = 0


async def _make_build(db, tenant_id, subsystem_id) -> Build:
    global _build_seq
    _build_seq += 1
    b = Build(
        tenant_id=tenant_id,
        subsystem_id=subsystem_id,
        git_sha=f"{_build_seq:040d}",
        build_number=f"stale-{_build_seq}",
        commit_timestamp=T0 - timedelta(days=1),
    )
    db.add(b)
    await db.flush()
    return b


async def _make_deployment(
    db, tenant_id, build_id, environment_id, deployed_at, status
) -> Deployment:
    global _deploy_seq
    _deploy_seq += 1
    change_request = await ensure_change_request(db, tenant_id)
    d = Deployment(
        tenant_id=tenant_id,
        build_id=build_id,
        environment_id=environment_id,
        change_request_id=change_request.id,
        event_id=f"stale-evt-{_deploy_seq}",
        deployed_at=deployed_at,
        status=status,
    )
    db.add(d)
    await db.flush()
    return d


@pytest_asyncio.fixture
async def gate(db_session, test_tenant, test_user) -> ReleaseGate:
    """A persisted ReleaseGate under a fresh Release in test_tenant."""
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

    release = Release(
        tenant_id=test_tenant.id,
        name="R",
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.flush()

    g = ReleaseGate(
        tenant_id=test_tenant.id,
        release_id=release.id,
        name="SIT Exit",
        due_date=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(g)
    await db_session.commit()
    await db_session.refresh(g)
    return g


@pytest_asyncio.fixture
async def evidence_context(db_session, test_tenant, test_user, gate) -> SimpleNamespace:
    """Evidence citing deployment D: build 41 of subsystem S into environment
    E, deployed at T0. Every `deploy_*` fixture below reaches into this same
    S/E pair so a later deployment actually collides with D."""
    subsystem = await ensure_subsystem(db_session, test_tenant.id, name="stale-eval-subsystem")
    environment = await ensure_environment(db_session, test_tenant.id, slot=41)

    build_41 = await _make_build(db_session, test_tenant.id, subsystem.id)
    deployment_41 = await _make_deployment(
        db_session, test_tenant.id, build_41.id, environment.id, T0, "success"
    )

    evidence = GateEvidence(
        tenant_id=test_tenant.id,
        gate_id=gate.id,
        kind="Deployment record",
        label="Build 41 sign-off",
        added_by=test_user.id,
        deployment_id=deployment_41.id,
    )
    db_session.add(evidence)
    await db_session.flush()

    return SimpleNamespace(
        tenant_id=test_tenant.id,
        subsystem=subsystem,
        environment=environment,
        build_41=build_41,
        deployment_41=deployment_41,
        evidence=evidence,
    )


@pytest_asyncio.fixture
async def evidence_on_build_41(evidence_context) -> GateEvidence:
    return evidence_context.evidence


@pytest_asyncio.fixture
async def deploy_build_42_successfully(db_session, evidence_context) -> Deployment:
    build_42 = await _make_build(db_session, evidence_context.tenant_id, evidence_context.subsystem.id)
    return await _make_deployment(
        db_session, evidence_context.tenant_id, build_42.id,
        evidence_context.environment.id, T0 + timedelta(hours=1), "success",
    )


@pytest_asyncio.fixture
async def deploy_build_42_and_fail(db_session, evidence_context) -> Deployment:
    build_42 = await _make_build(db_session, evidence_context.tenant_id, evidence_context.subsystem.id)
    return await _make_deployment(
        db_session, evidence_context.tenant_id, build_42.id,
        evidence_context.environment.id, T0 + timedelta(hours=1), "failed",
    )


@pytest_asyncio.fixture
async def deploy_build_42_and_roll_back(db_session, evidence_context) -> Deployment:
    build_42 = await _make_build(db_session, evidence_context.tenant_id, evidence_context.subsystem.id)
    return await _make_deployment(
        db_session, evidence_context.tenant_id, build_42.id,
        evidence_context.environment.id, T0 + timedelta(hours=1), "rolled_back",
    )


@pytest_asyncio.fixture
async def deploy_a_different_subsystem(db_session, evidence_context) -> Deployment:
    other_subsystem = await ensure_subsystem(
        db_session, evidence_context.tenant_id, name="stale-eval-other-subsystem"
    )
    build = await _make_build(db_session, evidence_context.tenant_id, other_subsystem.id)
    return await _make_deployment(
        db_session, evidence_context.tenant_id, build.id,
        evidence_context.environment.id, T0 + timedelta(hours=1), "success",
    )


@pytest_asyncio.fixture
async def deploy_same_build_to_another_env(db_session, evidence_context) -> Deployment:
    other_env = await ensure_environment(db_session, evidence_context.tenant_id, slot=42)
    build = await _make_build(db_session, evidence_context.tenant_id, evidence_context.subsystem.id)
    return await _make_deployment(
        db_session, evidence_context.tenant_id, build.id,
        other_env.id, T0 + timedelta(hours=1), "success",
    )


@pytest.mark.asyncio
async def test_a_later_successful_deployment_makes_evidence_stale(
    db_session, test_tenant, evidence_on_build_41, deploy_build_42_successfully
):
    """The whole point of the deployment link. A QA sign-off recorded against
    build 41 and then quietly undermined by a hotfix deploying 42 is exactly the
    failure the paperwork exists to prevent."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert evidence_on_build_41.id in stale


@pytest.mark.asyncio
async def test_a_failed_redeploy_does_not_make_evidence_stale(
    db_session, test_tenant, evidence_on_build_41, deploy_build_42_and_fail
):
    """A failed redeploy must not invalidate evidence that still correctly
    describes what is running."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


@pytest.mark.asyncio
async def test_a_rolled_back_deployment_does_not_make_evidence_stale(
    db_session, test_tenant, evidence_on_build_41, deploy_build_42_and_roll_back
):
    """After a rollback, build 41 is what is running again — so evidence for 41
    is current, not stale. Only status == 'success' counts."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


@pytest.mark.asyncio
async def test_a_deployment_of_a_different_component_is_irrelevant(
    db_session, test_tenant, evidence_on_build_41, deploy_a_different_subsystem
):
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


@pytest.mark.asyncio
async def test_a_deployment_into_a_different_environment_is_irrelevant(
    db_session, test_tenant, evidence_on_build_41, deploy_same_build_to_another_env
):
    """Evidence is about a component in an environment. A later deploy of the
    same component into Production says nothing about the UAT sign-off."""
    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


# ── Tenant-isolation probes ──────────────────────────────────────────────────
# "Assume every tenant filter is unguarded until a named test fails without
# it" (CLAUDE.md). Both probes below CONSTRUCT the cross-tenant row directly
# — id spaces are global, so a Build/Deployment can legitimately point its
# subsystem_id/environment_id at another tenant's real rows; nothing at the
# DB layer stops it, only the query's own tenant_id filter does. Each probe
# is built so that removing the filter it targets FLIPS the assertion (not
# just fails to change an already-empty result) — see the task-5 report for
# the actual mutation run.


@pytest.mark.asyncio
async def test_the_latest_deployment_lookup_is_tenant_scoped(
    db_session, test_tenant, second_tenant_factory, evidence_on_build_41
):
    """Tenant B deploys the SAME subsystem into the SAME environment (by id —
    constructed directly) after T0, successfully. If the 'latest successful
    deployment' query were not scoped to test_tenant, tenant B's deployment
    would supersede tenant A's evidence — a cross-tenant data leak into a
    verdict tenant A sees. It must not."""
    other_tenant, _other_admin = await second_tenant_factory()

    # Reach the real subsystem/environment ids off the deployment the
    # evidence cites, since the fixture only hands back the evidence row.
    referenced = (
        await db_session.execute(
            select(Deployment).where(Deployment.id == evidence_on_build_41.deployment_id)
        )
    ).scalar_one()
    build_41 = (
        await db_session.execute(select(Build).where(Build.id == referenced.build_id))
    ).scalar_one()

    other_build = await _make_build(db_session, other_tenant.id, build_41.subsystem_id)
    await _make_deployment(
        db_session, other_tenant.id, other_build.id, referenced.environment_id,
        T0 + timedelta(hours=1), "success",
    )

    stale = await stale_evidence_ids(db_session, test_tenant.id, [evidence_on_build_41])
    assert stale == set()


@pytest.mark.asyncio
async def test_the_evidence_deployment_lookup_is_tenant_scoped(
    db_session, test_tenant, test_user, gate, second_tenant_factory, evidence_context
):
    """Evidence whose deployment_id names ANOTHER tenant's deployment —
    simulating corrupted data or a write path that skips add_evidence's own
    validation, same shape as
    test_list_evidence_does_not_return_a_row_with_a_mismatched_tenant_id in
    test_gate_evidence.py. Must resolve to 'no such deployment in my tenant',
    never to a verdict computed from tenant B's real subsystem/environment
    ids matched against tenant A's own deployment history."""
    other_tenant, _other_admin = await second_tenant_factory()

    other_build = await _make_build(
        db_session, other_tenant.id, evidence_context.subsystem.id
    )
    cross_tenant_deployment = await _make_deployment(
        db_session, other_tenant.id, other_build.id,
        evidence_context.environment.id, T0, "success",
    )

    # A later, legitimate, same-tenant deployment of the same component —
    # present so the mutated query has something real to (wrongly) match.
    later_build = await _make_build(db_session, test_tenant.id, evidence_context.subsystem.id)
    await _make_deployment(
        db_session, test_tenant.id, later_build.id,
        evidence_context.environment.id, T0 + timedelta(hours=1), "success",
    )

    corrupt_evidence = GateEvidence(
        tenant_id=test_tenant.id,
        gate_id=gate.id,
        kind="Deployment record",
        label="Points at another tenant's deployment",
        added_by=test_user.id,
        deployment_id=cross_tenant_deployment.id,
    )
    db_session.add(corrupt_evidence)
    await db_session.flush()

    stale = await stale_evidence_ids(db_session, test_tenant.id, [corrupt_evidence])
    assert stale == set()
