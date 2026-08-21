"""Phase 9 C4 Task 5 — rollback findings folded into the ONE readiness
verdict (release_readiness_service.evaluate).

Covers: policy-driven severity (both flags default OFF, so day one is
warnings), the changing/config_only-vs-regression role split, irreversible
and lossy plans always warning regardless of policy, a failed rehearsal not
counting as current, the reversibility rollup on the response, that C2's own
gate findings are unaffected, and that the new batch lookups are called once
per response — never once per component.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.api.v1.schemas.rollback import RehearsalCreate, RollbackPlanCreate
from app.db.models.gate_type import GateType
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.services import (
    release_readiness_service,
    rollback_plan_service,
    rollback_policy_service,
    rollback_rehearsal_service,
)


# ── Shared fixtures ──────────────────────────────────────────────────────────

def _release_lifecycle(tenant_id: int) -> LifecycleTemplate:
    """Follows test_rollback_plan.py's precedent."""
    return LifecycleTemplate(
        tenant_id=tenant_id,
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


async def _make_release(db_session, test_tenant, test_user, *, name="R") -> Release:
    template = _release_lifecycle(test_tenant.id)
    db_session.add(template)
    await db_session.flush()
    r = Release(
        tenant_id=test_tenant.id,
        name=name,
        release_type="Major",
        lifecycle_template_id=template.id,
        raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.flush()
    return r


# ── Per-scenario systems — NOT the global conftest `system` fixture, which is
# built against the `tenant` fixture ("Phase3 Org"), a DIFFERENT tenant from
# `test_tenant` ("Test Org"). test_rollback_rehearsal.py hit this exact trap.

@pytest_asyncio.fixture
async def system_changing(db_session, test_tenant) -> System:
    s = System(tenant_id=test_tenant.id, name="Payments API")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def system_regression(db_session, test_tenant) -> System:
    s = System(tenant_id=test_tenant.id, name="Reporting Service")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def system_irreversible(db_session, test_tenant) -> System:
    s = System(tenant_id=test_tenant.id, name="Ledger DB")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def system_unagreed(db_session, test_tenant) -> System:
    s = System(tenant_id=test_tenant.id, name="Auth Service")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def release_with_changing_system(db_session, test_tenant, test_user, system_changing) -> Release:
    """One release_system row, role='changing', with NO rollback plan and NO
    rehearsal — honestly produces a component with nothing recorded yet."""
    release = await _make_release(db_session, test_tenant, test_user, name="R-changing")
    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release.id,
        system_id=system_changing.id, role="changing",
    ))
    await db_session.flush()
    return release


@pytest_asyncio.fixture
async def release_with_regression_system(db_session, test_tenant, test_user, system_regression) -> Release:
    """One release_system row, role='regression' — a component that is NOT
    being changed by this release and therefore has nothing to roll back."""
    release = await _make_release(db_session, test_tenant, test_user, name="R-regression")
    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release.id,
        system_id=system_regression.id, role="regression",
    ))
    await db_session.flush()
    return release


@pytest_asyncio.fixture
async def release_with_irreversible_plan(db_session, test_tenant, test_user, system_irreversible) -> Release:
    """A changing component with a REAL rollback plan recorded through the
    real service call, reversibility='irreversible'."""
    release = await _make_release(db_session, test_tenant, test_user, name="R-irreversible")
    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release.id,
        system_id=system_irreversible.id, role="changing",
    ))
    await db_session.flush()
    await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(
            system_id=system_irreversible.id,
            steps="One-way schema migration; no rollback path.",
            reversibility="irreversible",
        ),
    )
    return release


@pytest_asyncio.fixture
async def release_with_unagreed_plan(db_session, test_tenant, test_user, system_unagreed) -> Release:
    """A changing component with a plan that has been WRITTEN but never
    agreed (upsert_plan never sets agreed_at; only agree_plan does, and this
    fixture deliberately never calls it)."""
    release = await _make_release(db_session, test_tenant, test_user, name="R-unagreed")
    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release.id,
        system_id=system_unagreed.id, role="config_only",
    ))
    await db_session.flush()
    plan = await rollback_plan_service.upsert_plan(
        db_session, release.id, test_tenant.id, test_user.id,
        RollbackPlanCreate(
            system_id=system_unagreed.id,
            steps="Redeploy previous artefact.",
            reversibility="reversible",
        ),
    )
    assert plan.agreed_at is None, "fixture must honestly produce an UNAGREED plan"
    return release


@pytest_asyncio.fixture
async def policy_requiring_plans(db_session, test_tenant):
    """Flips require_rollback_plan ON for real, through the real service
    call — not a bare model mutation that could silently diverge from what
    the service actually persists."""
    policy = await rollback_policy_service.update_policy(
        db_session, test_tenant.id, require_rollback_plan=True,
    )
    assert policy.require_rollback_plan is True, (
        "fixture must honestly produce a policy that REQUIRES a plan"
    )
    return policy


@pytest_asyncio.fixture
async def failed_rehearsal_today(db_session, test_tenant, test_user, system_changing):
    """A rehearsal recorded TODAY, outcome='failed' — recent but failed, so
    it must not read as current no matter how fresh it is."""
    rehearsal = await rollback_rehearsal_service.record_rehearsal(
        db_session, system_changing.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime.now(timezone.utc), outcome="failed"),
    )
    assert rehearsal.outcome == "failed", "fixture must honestly produce a FAILED rehearsal"
    return rehearsal


@pytest_asyncio.fixture
async def release_with_failed_block_gate(db_session, test_tenant, test_user) -> Release:
    """C2's own failed-gate scenario, reused here to prove rollback findings
    do not disturb gate findings."""
    release = await _make_release(db_session, test_tenant, test_user, name="R-gate")
    gt = GateType(
        tenant_id=test_tenant.id, name="SIT Exit", failure_behaviour="block",
        expected_evidence=[],
    )
    db_session.add(gt)
    await db_session.flush()
    gate = ReleaseGate(
        tenant_id=test_tenant.id, release_id=release.id, name="SIT Exit Gate",
        due_date=datetime.now(timezone.utc) + timedelta(days=7),
        status="failed", gate_type_id=gt.id,
    )
    db_session.add(gate)
    await db_session.flush()
    return release


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_changing_component_with_no_plan_warns_by_default(
    db_session, test_tenant, release_with_changing_system
):
    """Policy defaults OFF, so day one is warnings, not a wall of blockers."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    assert result.ok is True
    assert "rollback_plan_missing" in [w.type for w in result.warnings]


@pytest.mark.asyncio
async def test_the_same_case_blocks_once_the_policy_requires_a_plan(
    db_session, test_tenant, release_with_changing_system, policy_requiring_plans
):
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    assert result.ok is False
    assert "rollback_plan_missing" in [b.type for b in result.blockers]


@pytest.mark.asyncio
async def test_a_regression_component_produces_no_rollback_findings(
    db_session, test_tenant, release_with_regression_system, policy_requiring_plans
):
    """A regression component is not being changed, so it has nothing to roll back."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_regression_system.id, test_tenant.id
    )
    rollback_types = [
        f.type for f in [*result.blockers, *result.warnings]
        if f.type.startswith("rollback_") or f.type.startswith("rehearsal_")
    ]
    assert rollback_types == []


@pytest.mark.asyncio
async def test_an_irreversible_change_never_blocks_even_with_policy_on(
    db_session, test_tenant, release_with_irreversible_plan, policy_requiring_plans
):
    """A one-way migration is a NORMAL thing to ship. Making it an error teaches
    teams to record it as reversible, destroying the signal."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_irreversible_plan.id, test_tenant.id
    )
    assert "rollback_irreversible" in [w.type for w in result.warnings]
    assert "rollback_irreversible" not in [b.type for b in result.blockers]


@pytest.mark.asyncio
async def test_an_unagreed_plan_is_reported_separately(
    db_session, test_tenant, release_with_unagreed_plan
):
    result = await release_readiness_service.evaluate(
        db_session, release_with_unagreed_plan.id, test_tenant.id
    )
    assert "rollback_plan_unagreed" in [w.type for w in result.warnings]


@pytest.mark.asyncio
async def test_a_failed_rehearsal_does_not_count_as_current(
    db_session, test_tenant, release_with_changing_system, failed_rehearsal_today
):
    """A rehearsal that FAILED proves the opposite of what the rule wants."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    types = [w.type for w in result.warnings]
    assert "rehearsal_missing" in types or "rehearsal_stale" in types


@pytest.mark.asyncio
async def test_the_response_carries_the_reversibility_rollup(
    db_session, test_tenant, release_with_irreversible_plan
):
    result = await release_readiness_service.evaluate(
        db_session, release_with_irreversible_plan.id, test_tenant.id
    )
    assert result.reversibility == "irreversible"


@pytest.mark.asyncio
async def test_an_orphaned_plan_does_not_move_reversibility(
    db_session, test_tenant, release_with_irreversible_plan, system_irreversible
):
    """Findings 1+2 (Defect B): DELETE /release-systems/{id} hard-deletes the
    release_system row but touches no rollback plan, so the plan stays LIVE —
    before this fix it kept driving `reversibility` to 'irreversible' with
    ZERO findings in blockers/warnings to explain it, which is exactly the
    shape that made ReadinessBanner render nothing while the pipeline route
    reported irreversible. The rollup must be computed over the SAME
    component set (changing_systems_for_release) the findings loop above
    already uses."""
    from sqlalchemy import delete as sa_delete

    from app.db.models.release_system import ReleaseSystem

    await db_session.execute(
        sa_delete(ReleaseSystem).where(
            ReleaseSystem.release_id == release_with_irreversible_plan.id,
            ReleaseSystem.system_id == system_irreversible.id,
        )
    )
    await db_session.flush()

    result = await release_readiness_service.evaluate(
        db_session, release_with_irreversible_plan.id, test_tenant.id
    )
    assert result.reversibility is None, (
        "a plan whose component is no longer on the release must not move "
        "the rollup"
    )
    rollback_types = [
        f.type for f in [*result.blockers, *result.warnings]
        if f.type.startswith("rollback_") or f.type.startswith("rehearsal_")
    ]
    assert rollback_types == []


@pytest.mark.asyncio
async def test_changing_systems_for_release_excludes_a_system_in_another_tenant(
    db_session, test_tenant, test_user, second_tenant_factory
):
    """Q9 — the tenant-filter probe the comment on `changing_systems_for_
    release`'s `System.tenant_id` filter cites ('see the mutation proof in
    test_rollback_readiness.py's report'). release_system.release_id and
    release_system.system_id are independent, uncross-checked fields (the
    same shape B6's cross-tenant booking leak took), so a release genuinely
    owned by test_tenant can point at a system belonging to a different
    tenant — and that system's name must never reach the verdict."""
    other_tenant, _other_admin = await second_tenant_factory(
        "Other Org Q9", "other-org-rollback-q9"
    )
    foreign_system = System(tenant_id=other_tenant.id, name="Other Tenant's System")
    db_session.add(foreign_system)
    await db_session.flush()

    release = await _make_release(db_session, test_tenant, test_user, name="R-q9")
    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release.id,
        system_id=foreign_system.id, role="changing",
    ))
    await db_session.flush()

    changing = await rollback_plan_service.changing_systems_for_release(
        db_session, release.id, test_tenant.id
    )
    assert changing == [], "a system belonging to another tenant must not appear in the verdict"


# ── Finding 6 — what a CURRENT 'partial' rehearsal means, pinned explicitly ──

@pytest_asyncio.fixture
async def current_partial_rehearsal(db_session, test_tenant, test_user, system_changing):
    """A rehearsal recorded TODAY, outcome='partial' — current, but not a
    clean pass. Before this fix, this exact combination was specified nowhere
    (not the design spec, not the user guide, not CLAUDE.md) and tested
    nowhere, and the frontend (RehearsalsPanel) disagreed with the backend
    about it."""
    rehearsal = await rollback_rehearsal_service.record_rehearsal(
        db_session, system_changing.id, test_tenant.id, test_user.id,
        RehearsalCreate(rehearsed_at=datetime.now(timezone.utc), outcome="partial"),
    )
    assert rehearsal.outcome == "partial", "fixture must honestly produce a PARTIAL rehearsal"
    return rehearsal


@pytest.mark.asyncio
async def test_a_current_partial_rehearsal_satisfies_the_requirement(
    db_session, test_tenant, release_with_changing_system, current_partial_rehearsal
):
    """PINNED: `evaluate()`'s rule is `rehearsal is None or outcome ==
    'failed'` — a CURRENT rehearsal whose outcome is 'partial' produces NO
    rehearsal finding at all, exactly like a current pass. RehearsalsPanel
    must render this the same way (`latestIsHealthy`), not the reverse."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    types = [f.type for f in [*result.blockers, *result.warnings]]
    assert "rehearsal_missing" not in types
    assert "rehearsal_stale" not in types


@pytest.mark.asyncio
async def test_gate_findings_are_unaffected(
    db_session, test_tenant, release_with_failed_block_gate
):
    """Adding rollback findings must not disturb C2's gate findings."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_failed_block_gate.id, test_tenant.id
    )
    assert "gate_failed" in [b.type for b in result.blockers]


@pytest.mark.asyncio
async def test_no_rollback_finding_names_a_gate(
    db_session, test_tenant, release_with_changing_system, policy_requiring_plans
):
    """gate_name is now Optional — every rollback construction site must set
    it explicitly to None rather than relying on the schema default, which is
    how C2 shipped a field permanently wrong at a site that forgot it."""
    result = await release_readiness_service.evaluate(
        db_session, release_with_changing_system.id, test_tenant.id
    )
    rollback_blockers = [b for b in result.blockers if b.type.startswith("rollback_")]
    assert rollback_blockers, "expected at least one rollback blocker under policy_requiring_plans"
    for b in rollback_blockers:
        assert b.gate_name is None
        assert b.ref_kind == "system"


# ── Batching proof ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_latest_rehearsals_for_systems_is_called_once_for_a_three_component_release(
    db_session, test_tenant, test_user, monkeypatch
):
    """ONE query for the whole page, never one per component. Three changing
    components on one release must still call the batch helper exactly once."""
    release = await _make_release(db_session, test_tenant, test_user, name="R-batch")
    for i in range(3):
        s = System(tenant_id=test_tenant.id, name=f"System {i}")
        db_session.add(s)
        await db_session.flush()
        db_session.add(ReleaseSystem(
            tenant_id=test_tenant.id, release_id=release.id,
            system_id=s.id, role="changing",
        ))
    await db_session.flush()

    call_count = 0
    original = rollback_rehearsal_service.latest_rehearsals_for_systems

    async def counting_wrapper(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(
        rollback_rehearsal_service, "latest_rehearsals_for_systems", counting_wrapper
    )

    result = await release_readiness_service.evaluate(db_session, release.id, test_tenant.id)

    assert len(result.warnings) >= 3  # each of the 3 systems is missing a plan+rehearsal
    assert call_count == 1, (
        "latest_rehearsals_for_systems must be called once per response, not once per component"
    )
