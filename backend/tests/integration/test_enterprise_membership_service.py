"""Integration tests for enterprise_membership_service.request_membership."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_membership import ReleaseMembership, MembershipState
from app.services import enterprise_membership_service


# ── Local helpers ─────────────────────────────────────────────────────────────


async def _make_lifecycle_template(db: AsyncSession, tenant_id: int) -> LifecycleTemplate:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Membership Test Lifecycle",
        is_default=False,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            ],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
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


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_membership_creates_pending_row(db_session, tenant, user):
    """Happy path: user requests admission, a pending_request row is created."""
    # Give the user the dynamic active_tenant_id attribute (mimics auth middleware)
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template(db_session, tenant.id)
    enterprise = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R1", release_kind="enterprise"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R1", release_kind="project"
    )

    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
        notes="Please admit us",
    )

    assert m.state == MembershipState.PENDING_REQUEST.value
    assert m.enterprise_release_id == enterprise.id
    assert m.project_release_id == project.id
    assert m.late_scope is False
    assert m.notes == "Please admit us"
    assert m.requested_by == user.id


@pytest.mark.asyncio
async def test_request_membership_rejects_duplicate_pending(db_session, tenant, user):
    """Second request for a project that already has a pending row → 409."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template(db_session, tenant.id)
    enterprise = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R2", release_kind="enterprise"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R2", release_kind="project"
    )

    # First request — should succeed
    await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )

    # Second request — should conflict
    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.request_membership(
            db_session,
            user=user,
            enterprise_id=enterprise.id,
            project_release_id=project.id,
        )
    assert getattr(exc.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_request_membership_rejects_wrong_kind(db_session, tenant, user):
    """Target not of release_kind='enterprise' → 422."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template(db_session, tenant.id)
    # Both releases are 'project' kind — target is not enterprise
    not_enterprise = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project Impostor", release_kind="project"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R3", release_kind="project"
    )

    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.request_membership(
            db_session,
            user=user,
            enterprise_id=not_enterprise.id,
            project_release_id=project.id,
        )
    assert getattr(exc.value, "status_code", None) == 422


# ── accept tests ──────────────────────────────────────────────────────────────


async def _make_lifecycle_template_with_admission(
    db: AsyncSession,
    tenant_id: int,
    action_permissions: dict | None = None,
) -> LifecycleTemplate:
    """Lifecycle template with an admission_closed lockdown state and action_permissions."""
    definition: dict = {
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "admission_open", "label": "Admission Open", "is_initial": False, "is_terminal": False},
            {"key": "admission_closed", "label": "Admission Closed", "is_initial": False, "is_terminal": False, "is_admission_lockdown": True},
            {"key": "integration_testing", "label": "Integration Testing", "is_initial": False, "is_terminal": False},
        ],
        "transitions": [],
        "field_permissions": {
            "draft": {"standard_fields": {}, "custom_fields": {}},
            "admission_open": {"standard_fields": {}, "custom_fields": {}},
            "admission_closed": {"standard_fields": {}, "custom_fields": {}},
            "integration_testing": {"standard_fields": {}, "custom_fields": {}},
        },
    }
    if action_permissions is not None:
        definition["action_permissions"] = action_permissions
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Enterprise Test Lifecycle",
        is_default=False,
        applies_to_kind="enterprise",
        definition=definition,
    )
    db.add(tpl)
    await db.flush()
    return tpl


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


@pytest.mark.asyncio
async def test_accept_sets_parent_and_flips_state(db_session, tenant, user):
    """Happy-path accept: state flips to accepted, project.parent_release_id points to enterprise, late_scope=False."""
    user.active_tenant_id = tenant.id

    # action_permissions allows Admin at admission_open
    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={"admission_open": {"membership.admit": ["Admin"]}},
    )
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R-Accept", status="admission_open"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R-Accept", release_kind="project"
    )

    # Request first
    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )

    # Accept
    accepted = await enterprise_membership_service.accept(
        db_session,
        user=user,
        membership_id=m.id,
    )

    assert accepted.state == MembershipState.ACCEPTED.value
    assert accepted.late_scope is False
    assert project.parent_release_id == enterprise.id


@pytest.mark.asyncio
async def test_accept_after_lockdown_flags_late_scope(db_session, tenant, user):
    """Accept after enterprise has transitioned past admission_closed → late_scope=True."""
    user.active_tenant_id = tenant.id

    # action_permissions allows Admin at integration_testing state
    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={"integration_testing": {"membership.admit": ["Admin"]}},
    )
    # Enterprise is already in integration_testing (past lockdown)
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R-Late", status="integration_testing"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R-Late", release_kind="project"
    )

    # Request from a project user
    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )

    # Accept — should flag late_scope=True
    accepted = await enterprise_membership_service.accept(
        db_session,
        user=user,
        membership_id=m.id,
    )

    assert accepted.state == MembershipState.ACCEPTED.value
    assert accepted.late_scope is True


@pytest.mark.asyncio
async def test_accept_without_permission_returns_403(db_session, tenant, user):
    """A Developer-role user attempting accept → HTTPException 403."""
    user.active_tenant_id = tenant.id

    # action_permissions only allows Admin, not Developer
    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={"admission_open": {"membership.admit": ["Admin"]}},
    )
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R-Perm", status="admission_open"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R-Perm", release_kind="project"
    )

    # Request membership (user is Admin, so this works)
    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )

    # Create a Developer user and attempt accept
    from app.db.models.user import User as UserModel
    from app.core.security import get_password_hash
    dev_user = UserModel(
        tenant_id=tenant.id,
        username="developer1",
        email="dev@test.com",
        password_hash=get_password_hash("password123"),
        role="Developer",
        is_active=True,
    )
    db_session.add(dev_user)
    await db_session.flush()
    dev_user.active_tenant_id = tenant.id

    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.accept(
            db_session,
            user=dev_user,
            membership_id=m.id,
        )
    assert getattr(exc.value, "status_code", None) == 403


# ── reject / withdraw / remove tests ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_sets_state(db_session, tenant, user):
    """Admin rejects pending → state='rejected', notes recorded."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={"admission_open": {"membership.reject": ["Admin"]}},
    )
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R-Reject", status="admission_open"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R-Reject", release_kind="project"
    )

    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )

    rejected = await enterprise_membership_service.reject(
        db_session,
        user=user,
        membership_id=m.id,
        notes="out of scope",
    )

    assert rejected.state == MembershipState.REJECTED.value
    assert rejected.notes == "out of scope"
    assert rejected.decided_by == user.id
    assert rejected.decided_at is not None


@pytest.mark.asyncio
async def test_withdraw_only_by_requester(db_session, tenant, user):
    """Another Developer attempting withdraw → 403. The original requester succeeds."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={},
    )
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R-Withdraw", status="admission_open"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R-Withdraw", release_kind="project"
    )

    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )

    # Create a Developer (stranger) user
    from app.db.models.user import User as UserModel
    from app.core.security import get_password_hash
    stranger = UserModel(
        tenant_id=tenant.id,
        username="stranger1",
        email="stranger@test.com",
        password_hash=get_password_hash("password123"),
        role="Developer",
        is_active=True,
    )
    db_session.add(stranger)
    await db_session.flush()
    stranger.active_tenant_id = tenant.id

    # Stranger cannot withdraw
    with pytest.raises(Exception) as exc:
        await enterprise_membership_service.withdraw(
            db_session,
            user=stranger,
            membership_id=m.id,
        )
    assert getattr(exc.value, "status_code", None) == 403

    # Original requester can withdraw
    withdrawn = await enterprise_membership_service.withdraw(
        db_session,
        user=user,
        membership_id=m.id,
    )

    assert withdrawn.state == MembershipState.WITHDRAWN.value
    assert withdrawn.decided_by == user.id


@pytest.mark.asyncio
async def test_remove_nulls_parent_and_writes_audit(db_session, tenant, user):
    """Admin removes an accepted membership → project.parent_release_id is nulled; removal_reason persisted."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={
            "admission_open": {
                "membership.admit": ["Admin"],
                "membership.remove": ["Admin"],
            }
        },
    )
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise R-Remove", status="admission_open"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project R-Remove", release_kind="project"
    )

    # Request → accept
    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )
    await enterprise_membership_service.accept(
        db_session,
        user=user,
        membership_id=m.id,
    )
    assert project.parent_release_id == enterprise.id

    # Remove
    removed = await enterprise_membership_service.remove(
        db_session,
        user=user,
        membership_id=m.id,
        reason="risk to target date",
    )

    assert removed.state == MembershipState.REMOVED.value
    assert removed.removal_reason == "risk to target date"
    assert removed.removed_by == user.id
    assert removed.removed_at is not None
    assert project.parent_release_id is None


# ── query helper tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_memberships_filters_by_state(db_session, tenant, user):
    """Filter by state list returns only matching rows."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={"admission_open": {"membership.admit": ["Admin"]}},
    )
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise Q-List", status="admission_open"
    )
    project1 = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project Q-List-1", release_kind="project"
    )
    project2 = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project Q-List-2", release_kind="project"
    )

    # Request both
    m1 = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project1.id,
    )
    m2 = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project2.id,
    )

    # Accept one
    await enterprise_membership_service.accept(
        db_session,
        user=user,
        membership_id=m1.id,
    )

    # Filter by pending_request — only m2 should appear
    rows, total = await enterprise_membership_service.list_memberships(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        states=[MembershipState.PENDING_REQUEST.value],
    )

    assert total == 1
    assert len(rows) == 1
    assert rows[0].id == m2.id
    assert rows[0].state == MembershipState.PENDING_REQUEST.value


@pytest.mark.asyncio
async def test_get_current_membership_for_project(db_session, tenant, user):
    """Returns the accepted row for a project, or None when none exists."""
    user.active_tenant_id = tenant.id

    tpl = await _make_lifecycle_template_with_admission(
        db_session,
        tenant.id,
        action_permissions={"admission_open": {"membership.admit": ["Admin"]}},
    )
    enterprise = await _make_enterprise_release(
        db_session, tenant.id, user.id, tpl.id, "Enterprise Q-Current", status="admission_open"
    )
    project = await _make_release(
        db_session, tenant.id, user.id, tpl.id, "Project Q-Current", release_kind="project"
    )

    # Before request: should return None
    result_none = await enterprise_membership_service.get_current_membership_for_project(
        db_session,
        user=user,
        project_release_id=project.id,
    )
    assert result_none is None

    # Request → accept
    m = await enterprise_membership_service.request_membership(
        db_session,
        user=user,
        enterprise_id=enterprise.id,
        project_release_id=project.id,
    )
    await enterprise_membership_service.accept(
        db_session,
        user=user,
        membership_id=m.id,
    )

    # After accept: should return the accepted row
    result = await enterprise_membership_service.get_current_membership_for_project(
        db_session,
        user=user,
        project_release_id=project.id,
    )
    assert result is not None
    assert result.id == m.id
    assert result.state == MembershipState.ACCEPTED.value
