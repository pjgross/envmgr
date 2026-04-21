import pytest
from app.db.models.custom_field import CustomFieldDefinition
from app.services import custom_field_service


@pytest.mark.asyncio
async def test_list_definitions_for_subtype_returns_unscoped_and_matching(
    db_session, tenant
):
    """list_definitions_for_subtype returns definitions with entity_subtype IS NULL
    OR entity_subtype == the given subtype. Non-matching subtypes are excluded."""
    any_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="theme", label="Theme", field_type="text", required=False, display_order=0,
    )
    defect_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text", required=False, display_order=1,
    )
    story_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="story",
        field_key="story_points", label="Points", field_type="number", required=False, display_order=2,
    )
    db_session.add_all([any_def, defect_def, story_def])
    await db_session.flush()

    defect_rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", "defect",
    )
    assert {d.field_key for d in defect_rows} == {"theme", "prod_bug_ref"}

    story_rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", "story",
    )
    assert {d.field_key for d in story_rows} == {"theme", "story_points"}


@pytest.mark.asyncio
async def test_list_definitions_for_subtype_ignores_soft_deleted(
    db_session, tenant
):
    from datetime import datetime, timezone
    d = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="retired", label="Retired", field_type="text", required=False, display_order=0,
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(d)
    await db_session.flush()
    rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", "defect",
    )
    assert rows == []


@pytest.mark.asyncio
async def test_list_definitions_for_subtype_null_subtype_returns_only_unscoped(
    db_session, tenant
):
    """Calling with subtype=None returns ONLY entity_subtype IS NULL rows."""
    any_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype=None,
        field_key="theme", label="Theme", field_type="text", required=False, display_order=0,
    )
    defect_def = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="release_change", entity_subtype="defect",
        field_key="prod_bug_ref", label="Prod Bug Ref", field_type="text", required=False, display_order=1,
    )
    db_session.add_all([any_def, defect_def])
    await db_session.flush()
    rows = await custom_field_service.list_definitions_for_subtype(
        db_session, tenant.id, "release_change", None,
    )
    assert [r.field_key for r in rows] == ["theme"]
