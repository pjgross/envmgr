"""Tests for release_scope_service — source-aware edit rules + Scope Change events."""
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_event import ReleaseEvent, ReleaseEventType
from app.db.models.user import Tenant
from app.api.v1.schemas.release_change import ReleaseChangeCreate, ReleaseChangeUpdate
from app.services import release_scope_service


# ── helpers ──────────────────────────────────────────────────────────────────

async def _make_release(db_session, tenant_id, user_id, status="draft"):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="Major",
        is_default=True,
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [],
            "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}},
        },
    )
    db_session.add(tpl)
    await db_session.flush()

    release = Release(
        tenant_id=tenant_id, name="R1", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id,
        status=status, raised_by=user_id,
    )
    db_session.add(release)
    await db_session.flush()
    return release


async def _seed_scope_change_event_type(db_session, tenant_id):
    et = ReleaseEventType(
        tenant_id=tenant_id, name="Scope Change", is_system=True
    )
    db_session.add(et)
    await db_session.flush()
    return et


# ── test_manual_item_fully_editable ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_item_fully_editable(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)
    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Login flow", change_kind="story"),
        tenant.id, user.id,
    )
    assert change.source == "manual"

    updated = await release_scope_service.update_change(
        db_session, change.id,
        ReleaseChangeUpdate(title="Updated login flow", external_status="In Review"),
        tenant.id, user.id,
    )
    assert updated.title == "Updated login flow"
    assert updated.external_status == "In Review"


# ── test_jira_item_read_only_fields_raise_422 ─────────────────────────────────

@pytest.mark.asyncio
async def test_jira_item_read_only_fields_raise_422(db_session, tenant, user):
    from fastapi import HTTPException
    release = await _make_release(db_session, tenant.id, user.id)

    # Directly create a jira-sourced item
    change = ReleaseChange(
        tenant_id=tenant.id, release_id=release.id,
        external_key="PROJ-1", title="Bug fix", change_kind="defect",
        source="jira",
    )
    db_session.add(change)
    await db_session.flush()

    # Attempting to edit 'title' on a jira item should raise 422
    with pytest.raises(HTTPException) as exc_info:
        await release_scope_service.update_change(
            db_session, change.id,
            ReleaseChangeUpdate(title="Hacked title"),
            tenant.id, user.id,
        )
    assert exc_info.value.status_code == 422
    assert "title" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_jira_item_allows_system_id_and_custom_fields(db_session, tenant, user, system):
    release = await _make_release(db_session, tenant.id, user.id)

    change = ReleaseChange(
        tenant_id=tenant.id, release_id=release.id,
        external_key="PROJ-2", title="Feature", change_kind="story",
        source="jira",
    )
    db_session.add(change)
    await db_session.flush()

    updated = await release_scope_service.update_change(
        db_session, change.id,
        ReleaseChangeUpdate(system_id=system.id, custom_fields={"priority": "high"}),
        tenant.id, user.id,
    )
    assert updated.system_id == system.id
    assert updated.custom_fields == {"priority": "high"}


# ── test_scope_change_event_emitted_when_release_approved ────────────────────

@pytest.mark.asyncio
async def test_scope_change_event_emitted_when_release_approved(db_session, tenant, user):
    await _seed_scope_change_event_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id, status="approved")

    await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="New feature post-approval", change_kind="story"),
        tenant.id, user.id,
    )

    events = (
        await db_session.execute(
            select(ReleaseEvent).where(ReleaseEvent.release_id == release.id)
        )
    ).scalars().all()
    assert len(events) == 1
    assert "Scope item added" in events[0].description


# ── test_scope_change_event_not_emitted_in_draft ──────────────────────────────

@pytest.mark.asyncio
async def test_scope_change_event_not_emitted_in_draft(db_session, tenant, user):
    await _seed_scope_change_event_type(db_session, tenant.id)
    release = await _make_release(db_session, tenant.id, user.id, status="draft")

    await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Draft change", change_kind="story"),
        tenant.id, user.id,
    )

    events = (
        await db_session.execute(
            select(ReleaseEvent).where(ReleaseEvent.release_id == release.id)
        )
    ).scalars().all()
    assert len(events) == 0


# ── test_tenant_isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation(db_session, tenant, user):
    from fastapi import HTTPException
    tenant_b = Tenant(name="Other Co", slug="other-co")
    db_session.add(tenant_b)
    await db_session.flush()

    release = await _make_release(db_session, tenant.id, user.id)
    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="Item A", change_kind="story"),
        tenant.id, user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await release_scope_service.update_change(
            db_session, change.id,
            ReleaseChangeUpdate(title="Hacked"),
            tenant_b.id, user.id,
        )
    assert exc_info.value.status_code == 404


# ── custom field validation ───────────────────────────────────────────────────

from app.db.models.custom_field import CustomFieldDefinition  # noqa: E402


@pytest.mark.asyncio
async def test_create_change_persists_valid_custom_fields(
    db_session, tenant, user, release_lifecycle_template,
):
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    # Define an unscoped field
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="theme", label="Theme", field_type="text", required=False, display_order=0,
    ))
    await db_session.flush()

    change = await release_scope_service.create_change(
        db_session, release_id=release.id, tenant_id=tenant.id, user_id=user.id,
        data=ReleaseChangeCreate(
            title="X", change_kind="story",
            custom_fields={"theme": "Onboarding"},
        ),
    )
    assert change.custom_fields == {"theme": "Onboarding"}


@pytest.mark.asyncio
async def test_create_change_enforces_required_visible_field(
    db_session, tenant, user, release_lifecycle_template,
):
    """A defect-only required field is enforced on defect items."""
    from fastapi import HTTPException
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text",
        required=True, display_order=0,
    ))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await release_scope_service.create_change(
            db_session, release_id=release.id, tenant_id=tenant.id, user_id=user.id,
            data=ReleaseChangeCreate(title="X", change_kind="defect"),
        )
    assert exc.value.status_code == 422
    assert "prod_bug_ref" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_change_ignores_required_field_for_other_subtype(
    db_session, tenant, user, release_lifecycle_template,
):
    """A required field on entity_subtype='defect' is NOT required for story items."""
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text",
        required=True, display_order=0,
    ))
    await db_session.flush()

    # Should NOT raise
    change = await release_scope_service.create_change(
        db_session, release_id=release.id, tenant_id=tenant.id, user_id=user.id,
        data=ReleaseChangeCreate(title="Y", change_kind="story"),
    )
    assert change.id is not None


@pytest.mark.asyncio
async def test_update_change_validates_type(
    db_session, tenant, user, release_lifecycle_template,
):
    from fastapi import HTTPException
    release = Release(
        tenant_id=tenant.id, name="R", release_type="Major", release_kind="project",
        lifecycle_template_id=release_lifecycle_template.id, status="draft", raised_by=user.id,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="points", label="Points", field_type="number",
        required=False, display_order=0,
    ))
    await db_session.flush()
    change = await release_scope_service.create_change(
        db_session, release_id=release.id, tenant_id=tenant.id, user_id=user.id,
        data=ReleaseChangeCreate(title="Z", change_kind="story"),
    )

    with pytest.raises(HTTPException) as exc:
        await release_scope_service.update_change(
            db_session, change_id=change.id, tenant_id=tenant.id, user_id=user.id,
            data=ReleaseChangeUpdate(custom_fields={"points": "not-a-number"}),
        )
    assert exc.value.status_code == 422
