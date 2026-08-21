import pytest
from fastapi import HTTPException

from app.api.v1.schemas.gate_type import GateTypeCreate
from app.services import gate_type_service


@pytest.mark.asyncio
async def test_duplicate_name_is_refused_case_insensitively(db_session, test_tenant):
    await gate_type_service.create_type(
        db_session, test_tenant.id,
        GateTypeCreate(name="Security", failure_behaviour="block"),
    )
    with pytest.raises(HTTPException) as exc:
        await gate_type_service.create_type(
            db_session, test_tenant.id,
            GateTypeCreate(name="security", failure_behaviour="warn"),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_type_from_another_tenant_is_not_visible(db_session, test_tenant, tenant):
    await gate_type_service.create_type(
        db_session, tenant.id, GateTypeCreate(name="Theirs", failure_behaviour="warn"),
    )
    rows, total = await gate_type_service.list_types(db_session, test_tenant.id)
    assert "Theirs" not in [r.name for r in rows]
    assert total == len(rows)


@pytest.mark.asyncio
async def test_an_unknown_failure_behaviour_is_a_422(db_session, test_tenant):
    with pytest.raises(Exception):
        GateTypeCreate(name="Odd", failure_behaviour="explode")
