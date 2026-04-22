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
