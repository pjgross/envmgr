import pytest
from datetime import datetime, timezone, timedelta
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.services import dora_service

UTC = timezone.utc

_build_counter = 0

async def _build(db, tenant_id, commit_dt, subsystem_id=1):
    # Note: Build has no `status` column; omit it (plan listed it but it's not on the model).
    # Use a counter in git_sha/build_number to avoid UNIQUE(tenant_id,subsystem_id,git_sha,build_number).
    global _build_counter
    _build_counter += 1
    sha = f"{_build_counter:040d}"
    b = Build(tenant_id=tenant_id, subsystem_id=subsystem_id, git_sha=sha,
              build_number=str(_build_counter), commit_timestamp=commit_dt)
    db.add(b); await db.flush(); return b

_deploy_counter = 0

async def _deploy(db, tenant_id, build_id, env_id, deployed_dt, status="success", release_id=None):
    # Use a counter to ensure event_id is unique even when deployed_dt is the same.
    global _deploy_counter
    _deploy_counter += 1
    d = Deployment(tenant_id=tenant_id, build_id=build_id, environment_id=env_id,
                   release_id=release_id, change_request_id=1,
                   event_id=f"e{deployed_dt.timestamp()}-{_deploy_counter}",
                   deployed_at=deployed_dt, status=status, custom_fields={})
    db.add(d); await db.flush(); return d


@pytest.mark.asyncio
async def test_deployment_frequency_counts_only_success_in_window(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b = await _build(db_session, tenant.id, t0 - timedelta(days=1))
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success")
    await _deploy(db_session, tenant.id, b.id, 1, t0 + timedelta(days=1), "success")
    await _deploy(db_session, tenant.id, b.id, 1, t0 + timedelta(days=2), "failed")     # excluded
    await _deploy(db_session, tenant.id, b.id, 1, t0 + timedelta(days=40), "success")   # out of window
    res = await dora_service.deployment_frequency(
        db_session, tenant.id, t0, t0 + timedelta(days=7), granularity="week")
    assert res["total"] == 2
    assert sum(p["count"] for p in res["series"]) == 2


@pytest.mark.asyncio
async def test_deployment_frequency_env_filter(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b = await _build(db_session, tenant.id, t0 - timedelta(days=1))
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success")
    await _deploy(db_session, tenant.id, b.id, 2, t0, "success")
    res = await dora_service.deployment_frequency(
        db_session, tenant.id, t0, t0 + timedelta(days=7), environment_id=1)
    assert res["total"] == 1


@pytest.mark.asyncio
async def test_lead_time_median_over_success(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b1 = await _build(db_session, tenant.id, t0 - timedelta(hours=2))
    b2 = await _build(db_session, tenant.id, t0 - timedelta(hours=4))
    await _deploy(db_session, tenant.id, b1.id, 1, t0, "success")   # 2h
    await _deploy(db_session, tenant.id, b2.id, 1, t0, "success")   # 4h
    res = await dora_service.lead_time(db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=1))
    assert res["count"] == 2
    assert res["median_seconds"] == 3 * 3600  # median of 2h,4h


@pytest.mark.asyncio
async def test_lead_time_clamps_clock_skew(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    b = await _build(db_session, tenant.id, t0 + timedelta(hours=1))  # commit AFTER deploy
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success")
    res = await dora_service.lead_time(db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=1))
    assert res["median_seconds"] == 0
