"""BuildService — upsert, validate custom fields, re-post updates pipeline_steps."""
from datetime import datetime, timezone

import pytest

from app.api.v1.schemas.build import BuildPayload
from app.db.models.custom_field import CustomFieldDefinition
from app.services import build_service


async def _make_subsystem(db_session, tenant_id):
    from app.db.models.system import System, SubSystem
    sys = System(tenant_id=tenant_id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant_id, system_id=sys.id, name="orders-api")
    db_session.add(sub)
    await db_session.flush()
    return sub


@pytest.mark.asyncio
async def test_upsert_inserts_new_build(db_session, tenant):
    sub = await _make_subsystem(db_session, tenant.id)
    payload = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    build = await build_service.upsert_build(
        db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload,
    )
    await db_session.flush()
    assert build.id is not None
    assert build.git_sha == "abc123"
    assert build.pipeline_steps == []


@pytest.mark.asyncio
async def test_upsert_updates_existing_build(db_session, tenant):
    sub = await _make_subsystem(db_session, tenant.id)
    payload1 = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
        pipeline_steps=[],
    )
    first = await build_service.upsert_build(
        db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload1,
    )
    await db_session.flush()

    payload2 = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
        pipeline_steps=[{"name": "test", "status": "success"}],
        jira_tickets=["PROJ-1"],
    )
    second = await build_service.upsert_build(
        db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload2,
    )
    await db_session.flush()

    assert second.id == first.id
    assert len(second.pipeline_steps) == 1
    assert second.jira_tickets == ["PROJ-1"]


@pytest.mark.asyncio
async def test_upsert_validates_custom_fields(db_session, tenant):
    from fastapi import HTTPException
    # Seed a required custom field definition
    defn = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="build", field_key="scan_id",
        label="Scan ID", field_type="text", required=True,
    )
    db_session.add(defn)
    sub = await _make_subsystem(db_session, tenant.id)
    await db_session.flush()

    payload = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
        custom_fields={},  # missing required field
    )
    with pytest.raises(HTTPException) as exc:
        await build_service.upsert_build(
            db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload,
        )
    assert exc.value.status_code == 422
