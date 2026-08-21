"""Tests for release_template_service CRUD + instantiate.

Uses in-memory SQLite via the shared db_session fixture.
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.db.models.gate_criterion import GateCriterion
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_template import ReleaseTemplate
from app.db.models.test_phase import TestPhase
from app.db.models.user import Tenant
from app.api.v1.schemas.release_template import (
    ReleaseTemplateCreate,
    ReleaseTemplateInstantiate,
    ReleaseTemplateUpdate,
    ReleaseTemplatePhase,
    ReleaseTemplateGate,
)
from app.services import release_template_service


# ── helpers ──────────────────────────────────────────────────────────────────

async def _seed_lifecycle(db_session, tenant_id, is_default=True):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Major",
        is_default=is_default,
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
                "completed": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


def _make_create_data(**kwargs):
    defaults = dict(
        name="Standard Template",
        release_type="Major",
        description="A standard template",
        phases=[
            ReleaseTemplatePhase(name="SIT", order=1, default_duration_days=5),
            ReleaseTemplatePhase(name="UAT", order=2, default_duration_days=7),
        ],
        gates=[
            ReleaseTemplateGate(name="SIT Exit", phase_name="SIT", acceptance_criteria="Zero Sev1"),
            ReleaseTemplateGate(name="Release Gate", phase_name=None, acceptance_criteria="Sign-off"),
        ],
    )
    defaults.update(kwargs)
    return ReleaseTemplateCreate(**defaults)


# ── test_create_and_bump_version_on_update ───────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_bump_version_on_update(db_session, tenant, user):
    data = _make_create_data()
    tpl = await release_template_service.create_template(db_session, data, tenant.id)
    assert tpl.id is not None
    assert tpl.version == 1
    assert tpl.name == "Standard Template"
    assert len(tpl.phases) == 2
    assert len(tpl.gates) == 2

    updated = await release_template_service.update_template(
        db_session, tpl.id, ReleaseTemplateUpdate(name="Updated Template"), tenant.id
    )
    assert updated.name == "Updated Template"
    assert updated.version == 2

    # Another update bumps again
    await release_template_service.update_template(
        db_session, tpl.id, ReleaseTemplateUpdate(description="new desc"), tenant.id
    )
    assert tpl.version == 3


# ── test_instantiate_materialises_phases_and_gates_with_computed_dates ────────

@pytest.mark.asyncio
async def test_instantiate_materialises_phases_and_gates_with_computed_dates(
    db_session, tenant, user
):
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    tpl_data = _make_create_data()
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    target = datetime(2026, 8, 1, tzinfo=timezone.utc)
    inst_data = ReleaseTemplateInstantiate(
        name="Release from Template",
        target_date=target,
    )
    release = await release_template_service.instantiate(
        db_session, tpl.id, inst_data, tenant.id, user.id
    )
    assert release.id is not None
    assert release.name == "Release from Template"
    assert release.template_id == tpl.id

    phases = (
        await db_session.execute(
            select(TestPhase).where(
                TestPhase.release_id == release.id,
                TestPhase.deleted_at.is_(None),
            ).order_by(TestPhase.order)
        )
    ).scalars().all()
    assert len(phases) == 2
    # UAT ends at target_date (last phase); SQLite strips tz info so compare naive
    uat = next(p for p in phases if p.name == "UAT")
    uat_end = uat.end_date.replace(tzinfo=None) if uat.end_date else None
    assert uat_end == target.replace(tzinfo=None)
    # SIT ends where UAT starts
    sit = next(p for p in phases if p.name == "SIT")
    assert sit.end_date == uat.start_date

    gates = (
        await db_session.execute(
            select(ReleaseGate).where(ReleaseGate.release_id == release.id)
        )
    ).scalars().all()
    assert len(gates) == 2

    # Each gate has acceptance_criteria set → one seeded criterion per gate
    from app.services import gate_criterion_service
    for gate in gates:
        criteria = await gate_criterion_service.list_criteria_for_gate(
            db_session, gate.id, tenant.id
        )
        assert len(criteria) == 1, f"gate '{gate.name}' expected 1 criterion, got {len(criteria)}"
        assert criteria[0].title == "Acceptance criteria"
        # notes holds the original acceptance_criteria text
        assert criteria[0].notes in ("Zero Sev1", "Sign-off")


# ── test_instantiate_release_level_gate_has_null_phase ────────────────────────

@pytest.mark.asyncio
async def test_instantiate_release_level_gate_has_null_phase(db_session, tenant, user):
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    tpl_data = _make_create_data()
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    target = datetime(2026, 9, 1, tzinfo=timezone.utc)
    release = await release_template_service.instantiate(
        db_session, tpl.id,
        ReleaseTemplateInstantiate(name="R", target_date=target),
        tenant.id, user.id
    )

    gates = (
        await db_session.execute(
            select(ReleaseGate).where(ReleaseGate.release_id == release.id)
        )
    ).scalars().all()
    release_level = next(g for g in gates if g.name == "Release Gate")
    # test_phase_id dropped — gate now carries due_date directly
    assert release_level.due_date is not None


# ── I5 (C2 final review): instantiate() sets test_phase_id ──────────────────
# ReleaseGate.test_phase_id shipped with a migration, a validator and an
# archived-value carve-out but was never written by the one place in the
# codebase that resolves a gate's phase by name — matched_phase, already
# computed here to derive gate_due_date, was thrown away instead of being
# recorded on the gate. Nothing reads the column yet; this only makes the
# phase linkage legible in the data instead of inferable from a name string.

@pytest.mark.asyncio
async def test_instantiate_sets_test_phase_id_from_the_matched_phase(db_session, tenant, user):
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    tpl_data = _make_create_data()
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    target = datetime(2026, 9, 1, tzinfo=timezone.utc)
    release = await release_template_service.instantiate(
        db_session, tpl.id,
        ReleaseTemplateInstantiate(name="R", target_date=target),
        tenant.id, user.id
    )

    phases = (
        await db_session.execute(
            select(TestPhase).where(TestPhase.release_id == release.id)
        )
    ).scalars().all()
    sit_phase = next(p for p in phases if p.name == "SIT")

    gates = (
        await db_session.execute(
            select(ReleaseGate).where(ReleaseGate.release_id == release.id)
        )
    ).scalars().all()

    sit_gate = next(g for g in gates if g.name == "SIT Exit")
    assert sit_gate.test_phase_id == sit_phase.id

    # Release-level gate (phase_name=None) must materialise with NO phase —
    # matched_phase is None, so test_phase_id must be None, not some
    # accidental default.
    release_gate = next(g for g in gates if g.name == "Release Gate")
    assert release_gate.test_phase_id is None


# ── test_delete_refused_when_in_use ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_refused_when_in_use(db_session, tenant, user):
    from fastapi import HTTPException
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    tpl_data = _make_create_data()
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    target = datetime(2026, 9, 1, tzinfo=timezone.utc)
    # Instantiate to create a release referencing the template
    await release_template_service.instantiate(
        db_session, tpl.id,
        ReleaseTemplateInstantiate(name="Linked Release", target_date=target),
        tenant.id, user.id
    )

    with pytest.raises(HTTPException) as exc_info:
        await release_template_service.delete_template(db_session, tpl.id, tenant.id)
    assert exc_info.value.status_code == 409


# ── test_delete_succeeds_when_not_in_use ─────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_succeeds_when_not_in_use(db_session, tenant, user):
    tpl_data = _make_create_data()
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    await release_template_service.delete_template(db_session, tpl.id, tenant.id)
    assert tpl.deleted_at is not None


# ── test_tenant_isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation(db_session, tenant, user):
    from fastapi import HTTPException
    tenant_b = Tenant(name="Other Co", slug="other-co")
    db_session.add(tenant_b)
    await db_session.flush()

    tpl_data = _make_create_data()
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    # Template is not visible to tenant B
    with pytest.raises(HTTPException) as exc_info:
        await release_template_service.get_template(db_session, tpl.id, tenant_b.id)
    assert exc_info.value.status_code == 404

    # Listing for tenant B returns nothing
    b_templates = await release_template_service.list_templates(db_session, tenant_b.id)
    assert len(b_templates) == 0


# ── Task 6c — release templates carry a gate type ────────────────────────────
#
# The design's central claim (docs/superpowers/specs) is that the SIT → UAT →
# PreProd → Production strictness ladder is expressed entirely through a
# tenant's release template materialising the right GateType per phase — "no
# second policy engine keyed on (type, tier)". Task 6b made a gate's type
# settable one gate at a time; these tests guard the bulk path, which is how
# gates actually get created in practice.

from app.db.models.gate_type import GateType
from app.services import release_readiness_service, gate_type_service
from app.api.v1.schemas.gate_type import GateTypeCreate


async def _make_gate_type(db_session, tenant_id, **kwargs) -> GateType:
    defaults = dict(
        name="Sign-off",
        failure_behaviour="warn",
        expected_evidence=[],
        is_active=True,
    )
    defaults.update(kwargs)
    row = GateType(tenant_id=tenant_id, **defaults)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_gate_config_with_type_materialises_typed_gate(db_session, tenant, user):
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    gate_type = await _make_gate_type(db_session, tenant.id, name="SIT Sign-off")

    tpl_data = _make_create_data(
        phases=[],
        gates=[
            ReleaseTemplateGate(
                name="SIT Gate", phase_name=None,
                acceptance_criteria=None, gate_type_id=gate_type.id,
            ),
        ],
    )
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    release = await release_template_service.instantiate(
        db_session, tpl.id,
        ReleaseTemplateInstantiate(name="R", target_date=datetime(2026, 9, 1, tzinfo=timezone.utc)),
        tenant.id, user.id,
    )

    gate = (
        await db_session.execute(
            select(ReleaseGate).where(ReleaseGate.release_id == release.id)
        )
    ).scalar_one()
    assert gate.gate_type_id == gate_type.id


@pytest.mark.asyncio
async def test_gate_config_with_no_gate_type_key_still_materialises_untyped(
    db_session, tenant, user
):
    """Back-compat: a template stored before this field existed has gate
    configs with NO 'gate_type_id' key at all — not a null value. Build the
    template that way directly (bypassing the schema, which always emits the
    key) to reproduce exactly what is sitting in the database today."""
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    tpl_data = _make_create_data(phases=[], gates=[])
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    # Overwrite with a gate config shaped like pre-6c stored data: no
    # 'gate_type_id' key present.
    tpl.gates = [{"name": "Legacy Gate", "phase_name": None, "acceptance_criteria": None}]
    db_session.add(tpl)
    await db_session.flush()

    release = await release_template_service.instantiate(
        db_session, tpl.id,
        ReleaseTemplateInstantiate(name="R", target_date=datetime(2026, 9, 1, tzinfo=timezone.utc)),
        tenant.id, user.id,
    )

    gate = (
        await db_session.execute(
            select(ReleaseGate).where(ReleaseGate.release_id == release.id)
        )
    ).scalar_one()
    assert gate.gate_type_id is None


@pytest.mark.asyncio
async def test_cross_tenant_gate_type_id_refused_at_save(db_session, tenant, user):
    from fastapi import HTTPException

    tenant_b = Tenant(name="Other Co 6c", slug="other-co-6c")
    db_session.add(tenant_b)
    await db_session.flush()
    foreign_type = await _make_gate_type(db_session, tenant_b.id, name="Theirs")

    tpl_data = _make_create_data(
        phases=[],
        gates=[
            ReleaseTemplateGate(
                name="G", phase_name=None,
                acceptance_criteria=None, gate_type_id=foreign_type.id,
            ),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        await release_template_service.create_template(db_session, tpl_data, tenant.id)
    assert exc_info.value.status_code == 404

    # Same rule applies on update.
    ok_tpl = await release_template_service.create_template(
        db_session, _make_create_data(phases=[], gates=[]), tenant.id
    )
    with pytest.raises(HTTPException) as exc_info:
        await release_template_service.update_template(
            db_session, ok_tpl.id,
            ReleaseTemplateUpdate(gates=[
                ReleaseTemplateGate(
                    name="G", phase_name=None,
                    acceptance_criteria=None, gate_type_id=foreign_type.id,
                ),
            ]),
            tenant.id,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_soft_deleted_gate_type_still_materialises(db_session, tenant, user):
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    gate_type = await _make_gate_type(db_session, tenant.id, name="Archived Sign-off")

    tpl_data = _make_create_data(
        phases=[],
        gates=[
            ReleaseTemplateGate(
                name="G", phase_name=None,
                acceptance_criteria=None, gate_type_id=gate_type.id,
            ),
        ],
    )
    # Valid (live type) at save time.
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    # Archived some time later — must NOT block materialisation.
    await gate_type_service.delete_type(db_session, gate_type.id, tenant.id)

    release = await release_template_service.instantiate(
        db_session, tpl.id,
        ReleaseTemplateInstantiate(name="R", target_date=datetime(2026, 9, 1, tzinfo=timezone.utc)),
        tenant.id, user.id,
    )

    gate = (
        await db_session.execute(
            select(ReleaseGate).where(ReleaseGate.release_id == release.id)
        )
    ).scalar_one()
    assert gate.gate_type_id == gate_type.id


@pytest.mark.asyncio
async def test_strictness_ladder_end_to_end_via_readiness_evaluate(db_session, tenant, user):
    """The payoff: two gates typed by two gate types with different
    expected_evidence lists produce DIFFERENT verdicts from
    release_readiness_service.evaluate() — the strictness ladder actually
    working, materialised in bulk from one template."""
    await _seed_lifecycle(db_session, tenant.id, is_default=True)
    lax = await _make_gate_type(
        db_session, tenant.id, name="SIT Sign-off", expected_evidence=[],
    )
    strict = await _make_gate_type(
        db_session, tenant.id, name="UAT Sign-off",
        expected_evidence=["Test execution report", "Defect summary"],
    )

    tpl_data = _make_create_data(
        phases=[],
        gates=[
            ReleaseTemplateGate(
                name="SIT Gate", phase_name=None,
                acceptance_criteria=None, gate_type_id=lax.id,
            ),
            ReleaseTemplateGate(
                name="UAT Gate", phase_name=None,
                acceptance_criteria=None, gate_type_id=strict.id,
            ),
        ],
    )
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    release = await release_template_service.instantiate(
        db_session, tpl.id,
        ReleaseTemplateInstantiate(name="R", target_date=datetime(2026, 9, 1, tzinfo=timezone.utc)),
        tenant.id, user.id,
    )

    gates = (
        await db_session.execute(
            select(ReleaseGate).where(ReleaseGate.release_id == release.id)
        )
    ).scalars().all()
    sit_gate = next(g for g in gates if g.name == "SIT Gate")
    uat_gate = next(g for g in gates if g.name == "UAT Gate")
    assert sit_gate.gate_type_id == lax.id
    assert uat_gate.gate_type_id == strict.id

    result = await release_readiness_service.evaluate(db_session, release.id, tenant.id)

    evidence_missing_gate_ids = {
        w.ref_id for w in result.warnings if w.type == "evidence_missing"
    }
    assert uat_gate.id in evidence_missing_gate_ids, (
        "the strict UAT type must warn about missing evidence"
    )
    assert sit_gate.id not in evidence_missing_gate_ids, (
        "the lax SIT type must NOT warn — it expects no evidence at all"
    )
    uat_warning = next(
        w for w in result.warnings
        if w.type == "evidence_missing" and w.ref_id == uat_gate.id
    )
    assert "Test execution report" in uat_warning.detail
    assert "Defect summary" in uat_warning.detail


# ── The set-based grandfather carve-out on template UPDATE ──────────────────
#
# ReleaseTemplateForm.tsx sends the WHOLE gates array on every save (create
# and update share one submit path, no dirty-tracking), so once any gate on
# a template carries a gate_type_id, an admin editing something unrelated —
# a due date, a name — re-sends that gate_type_id every time. Without a
# carve-out, archiving that type later makes the template permanently
# unsavable. Task 6b already carved this out on the sibling single-gate
# path; these tests hold the template path to the same standard.

@pytest.mark.asyncio
async def test_archived_gate_type_unchanged_in_reordered_gates_list_is_grandfathered(
    db_session, tenant, user
):
    gate_type = await _make_gate_type(db_session, tenant.id, name="Will Be Archived")
    other_type = await _make_gate_type(db_session, tenant.id, name="Untouched")

    tpl_data = _make_create_data(
        phases=[],
        gates=[
            ReleaseTemplateGate(
                name="A Gate", phase_name=None,
                acceptance_criteria=None, gate_type_id=gate_type.id,
            ),
            ReleaseTemplateGate(
                name="B Gate", phase_name=None,
                acceptance_criteria=None, gate_type_id=other_type.id,
            ),
        ],
    )
    tpl = await release_template_service.create_template(db_session, tpl_data, tenant.id)

    # Archived some time later.
    await gate_type_service.delete_type(db_session, gate_type.id, tenant.id)

    # Re-save: whole gates array re-sent, REORDERED (B first, A second) and
    # with an unrelated field (name) changed — exactly what the real form
    # does on every submit. Must NOT 404 — proves the carve-out is set-based,
    # not positional.
    updated = await release_template_service.update_template(
        db_session, tpl.id,
        ReleaseTemplateUpdate(
            name="Renamed Template",
            gates=[
                ReleaseTemplateGate(
                    name="B Gate", phase_name=None,
                    acceptance_criteria=None, gate_type_id=other_type.id,
                ),
                ReleaseTemplateGate(
                    name="A Gate", phase_name=None,
                    acceptance_criteria=None, gate_type_id=gate_type.id,
                ),
            ],
        ),
        tenant.id,
    )
    assert updated.name == "Renamed Template"
    saved_ids = {g["gate_type_id"] for g in updated.gates}
    assert gate_type.id in saved_ids
    assert other_type.id in saved_ids


@pytest.mark.asyncio
async def test_archived_gate_type_assigned_to_a_template_that_never_referenced_it_still_refused(
    db_session, tenant, user
):
    """The carve-out is scoped to a template's OWN stored gates. A type
    archived after being referenced by template A is not grandfathered on
    template B, which never referenced it before this save — that's a
    genuinely new assignment and must still 404."""
    from fastapi import HTTPException

    gate_type = await _make_gate_type(db_session, tenant.id, name="Will Be Archived Too")

    # Template A references the type (so it exists, live, at save time)...
    tpl_a_data = _make_create_data(
        phases=[],
        gates=[
            ReleaseTemplateGate(
                name="A Gate", phase_name=None,
                acceptance_criteria=None, gate_type_id=gate_type.id,
            ),
        ],
    )
    await release_template_service.create_template(db_session, tpl_a_data, tenant.id)

    # ...then it's archived.
    await gate_type_service.delete_type(db_session, gate_type.id, tenant.id)

    # Template B never referenced it. Assigning it now, after archival, on
    # an unrelated template must be refused — the carve-out does not leak
    # across templates.
    tpl_b = await release_template_service.create_template(
        db_session,
        _make_create_data(
            phases=[],
            gates=[
                ReleaseTemplateGate(
                    name="B Gate", phase_name=None,
                    acceptance_criteria=None, gate_type_id=None,
                ),
            ],
        ),
        tenant.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await release_template_service.update_template(
            db_session, tpl_b.id,
            ReleaseTemplateUpdate(gates=[
                ReleaseTemplateGate(
                    name="B Gate", phase_name=None,
                    acceptance_criteria=None, gate_type_id=gate_type.id,
                ),
            ]),
            tenant.id,
        )
    assert exc_info.value.status_code == 404
