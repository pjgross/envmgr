import pytest
from sqlalchemy import select

from app.db.models.gate_type import GateType
from app.services.gate_type_defaults import (
    STANDARD_GATE_TYPES,
    seed_gate_type_defaults_for_tenant,
)


@pytest.mark.asyncio
async def test_seeding_creates_the_eight_standard_types(db_session, test_tenant):
    await seed_gate_type_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(GateType).where(GateType.tenant_id == test_tenant.id)
        )
    ).scalars().all()

    assert len(rows) == len(STANDARD_GATE_TYPES) == 8
    assert {r.category for r in rows} == {
        "functional", "nfr", "integration", "security",
        "license", "accessibility", "business", "ops_readiness",
    }
    # Every standard type declares a behaviour; none is left to be guessed.
    assert all(r.failure_behaviour in {"block", "warn", "accept_with_exception"} for r in rows)


@pytest.mark.asyncio
async def test_seeding_is_idempotent_and_case_insensitive(db_session, test_tenant):
    db_session.add(GateType(
        tenant_id=test_tenant.id, name="security",
        failure_behaviour="warn", expected_evidence=[], display_order=0,
    ))
    await db_session.flush()

    await seed_gate_type_defaults_for_tenant(db_session, test_tenant.id)
    await seed_gate_type_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    names = [
        n.lower() for n in (
            await db_session.execute(
                select(GateType.name).where(GateType.tenant_id == test_tenant.id)
            )
        ).scalars().all()
    ]
    assert names.count("security") == 1
    assert len(names) == 8
