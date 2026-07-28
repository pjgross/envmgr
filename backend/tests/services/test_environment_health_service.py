import pytest
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.db.models.environment import Environment
from app.services import environment_health_service as svc

UTC = timezone.utc

async def _env(db, tenant_id, name="Env A", status="active"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="SIT", status=status)
    db.add(e); await db.flush(); return e


@pytest.mark.asyncio
async def test_record_sample_defaults_recorded_at(db_session, tenant):
    env = await _env(db_session, tenant.id)
    row = await svc.record_sample(db_session, tenant.id, env.id, "up", "pingdom")
    assert row.status == "up" and row.source == "pingdom" and row.recorded_at is not None


@pytest.mark.asyncio
async def test_record_sample_rejects_other_tenant_env(db_session, tenant):
    with pytest.raises(HTTPException) as e:
        await svc.record_sample(db_session, tenant.id, 999999, "up", "x")
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_history_newest_first(db_session, tenant):
    env = await _env(db_session, tenant.id)
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    await svc.record_sample(db_session, tenant.id, env.id, "up", "x", recorded_at=t0)
    await svc.record_sample(db_session, tenant.id, env.id, "down", "x", recorded_at=t0 + timedelta(minutes=5))
    hist = await svc.get_history(db_session, tenant.id, env.id)
    assert [h.status for h in hist] == ["down", "up"]


@pytest.mark.asyncio
async def test_derive_status_fresh_stale_and_none(db_session, tenant):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    env = await _env(db_session, tenant.id)
    # no samples -> unknown
    ov = await svc.health_overview(db_session, tenant.id, now=now)
    assert ov[0]["current_status"] == "unknown"
    # fresh sample -> its status
    await svc.record_sample(db_session, tenant.id, env.id, "down", "x", recorded_at=now - timedelta(minutes=5))
    ov = await svc.health_overview(db_session, tenant.id, now=now)
    assert ov[0]["current_status"] == "down"
    # stale sample (>15m) -> unknown
    ov = await svc.health_overview(db_session, tenant.id, now=now + timedelta(minutes=20))
    assert ov[0]["current_status"] == "unknown"
