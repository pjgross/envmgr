"""Tests for release_template_service CRUD + instantiate.

Uses in-memory SQLite via the shared db_session fixture.
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

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
    assert release_level.test_phase_id is None


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
