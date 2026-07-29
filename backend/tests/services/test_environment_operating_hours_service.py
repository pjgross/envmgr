import pytest
from app.db.models.environment import Environment
from app.db.models.environment_operating_hours import EnvironmentOperatingHours


async def _env(db, tenant_id, name="Env"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


@pytest.mark.asyncio
async def test_operating_hours_row_roundtrips(db_session, tenant):
    env = await _env(db_session, tenant.id)
    row = EnvironmentOperatingHours(
        tenant_id=tenant.id, environment_id=env.id, timezone="Europe/London",
        week=[{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)],
    )
    db_session.add(row); await db_session.flush()
    assert row.id is not None
    assert row.week[0]["open"] == "09:00"
    assert row.deleted_at is None
