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


from fastapi import HTTPException  # noqa: E402
from app.services import environment_operating_hours_service as svc  # noqa: E402

_FULL_WEEK = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]


@pytest.mark.asyncio
async def test_upsert_creates_then_updates_single_row(db_session, tenant):
    env = await _env(db_session, tenant.id)
    r1 = await svc.upsert_config(db_session, tenant.id, env.id, "UTC", _FULL_WEEK)
    assert r1.timezone == "UTC"
    r2 = await svc.upsert_config(db_session, tenant.id, env.id, "Europe/London",
                                 [{"closed": True} for _ in range(7)])
    assert r2.id == r1.id  # same row updated, not a second row
    assert r2.timezone == "Europe/London"
    got = await svc.get_config(db_session, tenant.id, env.id)
    assert got.id == r1.id
    assert got.week[0]["closed"] is True


@pytest.mark.asyncio
async def test_upsert_invalid_timezone_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "Mars/Phobos", _FULL_WEEK)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_open_after_close_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    bad = [{"closed": False, "open": "17:00", "close": "09:00"}] + \
          [{"closed": True} for _ in range(6)]
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "UTC", bad)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_malformed_hhmm_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    bad = [{"closed": False, "open": "9am", "close": "17:00"}] + \
          [{"closed": True} for _ in range(6)]
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "UTC", bad)
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_wrong_length_week_422(db_session, tenant):
    env = await _env(db_session, tenant.id)
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env.id, "UTC", _FULL_WEEK[:5])
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_upsert_wrong_tenant_env_404(db_session, tenant):
    from app.db.models.user import Tenant
    t2 = Tenant(name="Other", slug="other-ophours")
    db_session.add(t2); await db_session.flush()
    env2 = await _env(db_session, t2.id, name="Env2")
    with pytest.raises(HTTPException) as ei:
        await svc.upsert_config(db_session, tenant.id, env2.id, "UTC", _FULL_WEEK)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_get_config_none_when_unset(db_session, tenant):
    env = await _env(db_session, tenant.id)
    assert await svc.get_config(db_session, tenant.id, env.id) is None
