"""Integration tests for enterprise_report_service.generate_report."""
import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.services import enterprise_membership_service, enterprise_report_service


# ── Local helpers (mirrors test_enterprise_rollup_service.py) ─────────────────


async def _make_lifecycle_template_with_admission(
    db: AsyncSession,
    tenant_id: int,
) -> LifecycleTemplate:
    """Lifecycle template with admission states; Admin can admit."""
    definition: dict = {
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "admission_open", "label": "Admission Open", "is_initial": False, "is_terminal": False},
        ],
        "transitions": [],
        "field_permissions": {
            "draft": {"standard_fields": {}, "custom_fields": {}},
            "admission_open": {"standard_fields": {}, "custom_fields": {}},
        },
        "action_permissions": {
            "admission_open": {
                "membership.admit": ["Admin"],
                "membership.reject": ["Admin"],
            },
        },
    }
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Enterprise Report Test Lifecycle",
        is_default=False,
        applies_to_kind="enterprise",
        definition=definition,
    )
    db.add(tpl)
    await db.flush()
    return tpl


async def _make_release(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    lifecycle_template_id: int,
    name: str,
    release_kind: str = "project",
) -> Release:
    r = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Major",
        release_kind=release_kind,
        lifecycle_template_id=lifecycle_template_id,
        status="draft",
        raised_by=user_id,
    )
    db.add(r)
    await db.flush()
    return r


async def _make_enterprise_release(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    lifecycle_template_id: int,
    name: str,
    status: str = "admission_open",
) -> Release:
    r = Release(
        tenant_id=tenant_id,
        name=name,
        release_type="Major",
        release_kind="enterprise",
        lifecycle_template_id=lifecycle_template_id,
        status=status,
        raised_by=user_id,
    )
    db.add(r)
    await db.flush()
    return r


async def _make_scope_item(
    db,
    tenant_id,
    release_id,
    external_key,
    title,
    change_kind="story",
    external_status=None,
    system_id=None,
):
    from app.db.models.release_change import ReleaseChange

    item = ReleaseChange(
        tenant_id=tenant_id,
        release_id=release_id,
        external_key=external_key,
        title=title,
        change_kind=change_kind,
        external_status=external_status,
        system_id=system_id,
        source="manual",
    )
    db.add(item)
    await db.flush()
    return item


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_report_has_all_sections(db_session, tenant, user):
    """Report payload covers header, members, systems, scope_by_project, events, dependencies, generated_at/by."""
    user.active_tenant_id = tenant.id

    # Build lifecycle template
    tpl = await _make_lifecycle_template_with_admission(db_session, tenant.id)

    # Enterprise release
    ent = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "R-ENT-1", status="admission_open"
    )

    # Two project releases
    p_alpha = await _make_release(db_session, tenant.id, user.id, tpl.id, "Alpha")
    p_beta = await _make_release(db_session, tenant.id, user.id, tpl.id, "Beta")

    # One scope item on each
    await _make_scope_item(db_session, tenant.id, p_alpha.id, "ALPHA-1", "Alpha story", change_kind="story")
    await _make_scope_item(db_session, tenant.id, p_beta.id, "BETA-1", "Beta defect", change_kind="defect")

    # Request + accept both
    m1 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p_alpha.id
    )
    m2 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p_beta.id
    )
    await enterprise_membership_service.accept(db_session, user=user, membership_id=m1.id)
    await enterprise_membership_service.accept(db_session, user=user, membership_id=m2.id)

    # Generate report
    report = await enterprise_report_service.generate_report(
        db_session, user=user, enterprise_id=ent.id
    )

    # Header fields
    assert report.enterprise_id == ent.id
    assert report.name == "R-ENT-1"

    # Members: both project releases present
    assert {m.project_release_name for m in report.members} == {"Alpha", "Beta"}

    # Scope by project: both keys present
    assert "Alpha" in report.scope_by_project
    assert "Beta" in report.scope_by_project

    # Scope items correct
    assert {it.external_key for it in report.scope_by_project["Alpha"]} == {"ALPHA-1"}
    assert {it.external_key for it in report.scope_by_project["Beta"]} == {"BETA-1"}

    # generated_at and generated_by are populated
    assert report.generated_at
    assert report.generated_by

    # events list exists (may be empty if no ReleaseEvents recorded)
    assert isinstance(report.events, list)

    # dependencies list exists
    assert isinstance(report.dependencies, list)
