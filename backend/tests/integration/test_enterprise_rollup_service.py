"""Integration tests for enterprise_rollup_service.systems_rollup."""
import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System
from app.services import enterprise_membership_service, enterprise_rollup_service


# ── Local helpers ─────────────────────────────────────────────────────────────


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
        name="Enterprise Rollup Test Lifecycle",
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


async def _make_system(db: AsyncSession, tenant_id: int, name: str) -> System:
    s = System(tenant_id=tenant_id, name=name)
    db.add(s)
    await db.flush()
    return s


async def _attach_system(
    db: AsyncSession,
    tenant_id: int,
    release_id: int,
    system_id: int,
    role: str,
) -> ReleaseSystem:
    rs = ReleaseSystem(
        tenant_id=tenant_id,
        release_id=release_id,
        system_id=system_id,
        role=role,
    )
    db.add(rs)
    await db.flush()
    return rs


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_systems_rollup_aggregates_accepted_only(db_session, tenant, user):
    """Systems rollup covers all accepted children; each system appears once with roles per contributing project."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(db_session, tenant.id)
    ent = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise Rollup-1", status="admission_open"
    )
    p1 = await _make_release(db_session, tenant.id, user.id, tpl.id, "Project Rollup-P1")
    p2 = await _make_release(db_session, tenant.id, user.id, tpl.id, "Project Rollup-P2")

    sys_a = await _make_system(db_session, tenant.id, "System A")
    sys_b = await _make_system(db_session, tenant.id, "System B")

    # Attach sys_a to p1 with role='changing', to p2 with role='regression'
    await _attach_system(db_session, tenant.id, p1.id, sys_a.id, "changing")
    await _attach_system(db_session, tenant.id, p2.id, sys_a.id, "regression")
    # Attach sys_b to p2 with role='changing'
    await _attach_system(db_session, tenant.id, p2.id, sys_b.id, "changing")

    # Request + accept both projects
    m1 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p1.id
    )
    m2 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p2.id
    )
    await enterprise_membership_service.accept(db_session, user=user, membership_id=m1.id)
    await enterprise_membership_service.accept(db_session, user=user, membership_id=m2.id)

    rows = await enterprise_rollup_service.systems_rollup(
        db_session, user=user, enterprise_id=ent.id
    )

    # 2 rows — one per distinct system
    assert len(rows) == 2

    by_id = {r.system_id: r for r in rows}

    # sys_a: changing from p1, regression from p2
    row_a = by_id[sys_a.id]
    assert row_a.system_name == "System A"
    assert row_a.roles_by_project[p1.name] == ["changing"]
    assert row_a.roles_by_project[p2.name] == ["regression"]

    # sys_b: changing from p2 only
    row_b = by_id[sys_b.id]
    assert row_b.system_name == "System B"
    assert row_b.roles_by_project == {p2.name: ["changing"]}


@pytest.mark.asyncio
async def test_systems_rollup_ignores_non_accepted_children(db_session, tenant, user):
    """Projects in pending/rejected/withdrawn/removed states contribute nothing."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(db_session, tenant.id)
    ent = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise Rollup-2", status="admission_open"
    )
    p1 = await _make_release(db_session, tenant.id, user.id, tpl.id, "Project Rollup-Accept")
    p2 = await _make_release(db_session, tenant.id, user.id, tpl.id, "Project Rollup-Reject")

    sys_x = await _make_system(db_session, tenant.id, "System X (accepted project)")
    sys_y = await _make_system(db_session, tenant.id, "System Y (rejected project)")

    await _attach_system(db_session, tenant.id, p1.id, sys_x.id, "changing")
    await _attach_system(db_session, tenant.id, p2.id, sys_y.id, "changing")

    # Request both; accept only p1, reject p2
    m1 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p1.id
    )
    m2 = await enterprise_membership_service.request_membership(
        db_session, user=user, enterprise_id=ent.id, project_release_id=p2.id
    )
    await enterprise_membership_service.accept(db_session, user=user, membership_id=m1.id)
    await enterprise_membership_service.reject(
        db_session, user=user, membership_id=m2.id, notes="out of scope"
    )

    rows = await enterprise_rollup_service.systems_rollup(
        db_session, user=user, enterprise_id=ent.id
    )

    system_ids = {r.system_id for r in rows}
    assert sys_x.id in system_ids
    assert sys_y.id not in system_ids
    assert len(rows) == 1
