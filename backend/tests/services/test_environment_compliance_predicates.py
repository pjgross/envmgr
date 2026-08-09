"""The one part of B2 with no precedent in this codebase: reaching inside the
`custom_fields` JSON column from SQL. It compiles to `->>` on PostgreSQL and
`json_extract` on SQLite, so it is tested on both legs before anything is
built on top of it."""
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.services.environment_compliance_service import custom_field_missing_clause
from tests.factories import ensure_environment_tier


async def _env(db, tenant_id, name, custom_fields):
    tier = await ensure_environment_tier(db, tenant_id)
    env = Environment(
        name=name, tier_id=tier.id, tenant_id=tenant_id, custom_fields=custom_fields
    )
    db.add(env)
    await db.flush()
    return env


@pytest.mark.asyncio
async def test_missing_key_absent_null_and_blank_all_count_as_missing(
    db_session, test_tenant
):
    await _env(db_session, test_tenant.id, "absent", {"other": "x"})
    await _env(db_session, test_tenant.id, "explicit-null", {"cost_centre": None})
    await _env(db_session, test_tenant.id, "blank", {"cost_centre": "   "})
    await _env(db_session, test_tenant.id, "no-json-at-all", None)
    await _env(db_session, test_tenant.id, "present", {"cost_centre": "CC-1"})

    rows = (
        await db_session.execute(
            select(Environment.name).where(
                Environment.tenant_id == test_tenant.id,
                custom_field_missing_clause("cost_centre"),
            )
        )
    ).scalars().all()

    assert sorted(rows) == ["absent", "blank", "explicit-null", "no-json-at-all"]


@pytest.mark.asyncio
async def test_a_numeric_value_counts_as_present(db_session, test_tenant):
    """A custom field of type `number` stores an int, not a string. Casting to
    text must not make 0 look absent — `0` is a supplied value."""
    await _env(db_session, test_tenant.id, "zero", {"seats": 0})
    rows = (
        await db_session.execute(
            select(Environment.name).where(
                Environment.tenant_id == test_tenant.id,
                custom_field_missing_clause("seats"),
            )
        )
    ).scalars().all()
    assert rows == []
