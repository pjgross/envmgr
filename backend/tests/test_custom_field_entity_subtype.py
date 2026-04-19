import pytest
from app.db.models.custom_field import CustomFieldDefinition


@pytest.mark.asyncio
async def test_entity_subtype_is_persisted(db_session, tenant):
    cfd = CustomFieldDefinition(
        tenant_id=tenant.id,
        entity_type="release",
        entity_subtype="Major",
        field_key="business_sponsor",
        label="Business Sponsor",
        field_type="text",
        required=False,
        display_order=0,
    )
    db_session.add(cfd)
    await db_session.flush()
    assert cfd.id is not None
    assert cfd.entity_subtype == "Major"


@pytest.mark.asyncio
async def test_entity_subtype_nullable(db_session, tenant):
    cfd = CustomFieldDefinition(
        tenant_id=tenant.id,
        entity_type="release",
        entity_subtype=None,
        field_key="universal_field",
        label="Universal",
        field_type="text",
        required=False,
        display_order=0,
    )
    db_session.add(cfd)
    await db_session.flush()
    assert cfd.entity_subtype is None
