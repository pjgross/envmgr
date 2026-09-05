"""Phase 9 C3 — Go/No-Go decision record."""
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.api.v1.schemas.go_no_go import GoNoGoDecisionCreate, GoNoGoSignoffCreate
from app.db.models.go_no_go import GoNoGoPerspective
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services import go_no_go_defaults, go_no_go_service
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
