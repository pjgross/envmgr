import pytest
from datetime import datetime, timezone, timedelta
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.incident import Incident
from app.db.models.user import User, Tenant
from app.core.security import get_password_hash
from app.services import dora_service
from app.services.dora_service import _percentile

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


# ---------------------------------------------------------------------------
# Task 3: Change Failure Rate helpers + tests
# ---------------------------------------------------------------------------

_user_counter = 0


async def _user(db, tenant_id):
    """Create a minimal User row; counter ensures unique username/email."""
    global _user_counter
    _user_counter += 1
    u = User(
        tenant_id=tenant_id,
        username=f"dorauser{_user_counter}",
        email=f"dorauser{_user_counter}@test.com",
        password_hash=get_password_hash("x"),
        role="Viewer",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _release_template(db, tenant_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="RT",
        description="", is_default=True, is_system=True,
        definition={"states": [
            {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            {"key": "backed_out", "label": "Backed Out", "is_initial": False, "is_terminal": True, "is_failed": True},
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        ], "transitions": [], "field_permissions": {}},
    )
    db.add(tpl); await db.flush(); return tpl


async def _closed_release(db, tenant_id, tpl_id, status, close_dt, with_deploy=True):
    # Release requires release_type and raised_by (FK to user)
    u = await _user(db, tenant_id)
    r = Release(tenant_id=tenant_id, name="R", release_type="Major", release_kind="project",
                lifecycle_template_id=tpl_id, status=status, raised_by=u.id)
    db.add(r); await db.flush()
    # ReleaseStatusHistory requires changed_by (FK to user); no tenant_id column on this model
    db.add(ReleaseStatusHistory(release_id=r.id, to_state=status,
                                changed_at=close_dt, changed_by=u.id))
    if with_deploy:
        b = await _build(db, tenant_id, close_dt - timedelta(days=1))
        await _deploy(db, tenant_id, b.id, 1, close_dt, "success", release_id=r.id)
    await db.flush(); return r


@pytest.mark.asyncio
async def test_cfr_counts_failed_state_and_causal_incident(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # shipped + completed cleanly -> denominator only
    await _closed_release(db_session, tenant.id, tpl.id, "completed", t0)
    # shipped + backed_out (is_failed) -> failure
    await _closed_release(db_session, tenant.id, tpl.id, "backed_out", t0 + timedelta(days=1))
    # shipped + completed but has a causal incident -> failure
    r3 = await _closed_release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=2))
    db_session.add(Incident(tenant_id=tenant.id, title="x", severity="P1", status="new",
                            detected_at=t0 + timedelta(days=2), release_id=r3.id, source="manual"))
    # closed but NO deployment -> excluded from denominator
    await _closed_release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=3), with_deploy=False)
    await db_session.flush()
    res = await dora_service.change_failure_rate(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["shipped_count"] == 3
    assert res["failed_count"] == 2
    assert abs(res["rate"] - (2/3)) < 1e-9


@pytest.mark.asyncio
async def test_cfr_zero_when_no_shipped(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    res = await dora_service.change_failure_rate(db_session, tenant.id, t0, t0 + timedelta(days=1))
    assert res == {"rate": 0.0, "failed_count": 0, "shipped_count": 0}


# ---------------------------------------------------------------------------
# Task 4: MTTR + dora_summary tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mttr_mean_over_resolved_in_window(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    db_session.add(Incident(tenant_id=tenant.id, title="a", severity="P1", status="resolved",
                            detected_at=t0, resolved_at=t0 + timedelta(hours=2), source="manual"))
    db_session.add(Incident(tenant_id=tenant.id, title="b", severity="P2", status="resolved",
                            detected_at=t0, resolved_at=t0 + timedelta(hours=4), source="manual"))
    db_session.add(Incident(tenant_id=tenant.id, title="c", severity="P3", status="new",
                            detected_at=t0, resolved_at=None, source="manual"))  # unresolved -> excluded
    await db_session.flush()
    res = await dora_service.mttr(db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=1))
    assert res["count"] == 2
    assert res["mean_seconds"] == 3 * 3600


@pytest.mark.asyncio
async def test_summary_bundles_all_four(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    res = await dora_service.dora_summary(db_session, tenant.id, t0, t0 + timedelta(days=1))
    assert set(res) == {"deployment_frequency", "lead_time", "change_failure_rate", "mttr"}


# ---------------------------------------------------------------------------
# Task 5: Week & month bucketing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deployment_frequency_week_bucketing(db_session, tenant):
    """Two deployments in week-1, one in week-2 → two distinct weekly buckets."""
    # 2026-06-01 is a Monday; 2026-06-08 is the next Monday.
    week1_mon = datetime(2026, 6, 1, tzinfo=UTC)
    week1_wed = datetime(2026, 6, 3, tzinfo=UTC)
    week2_tue = datetime(2026, 6, 9, tzinfo=UTC)
    b = await _build(db_session, tenant.id, week1_mon - timedelta(days=1))
    await _deploy(db_session, tenant.id, b.id, 1, week1_mon, "success")
    await _deploy(db_session, tenant.id, b.id, 1, week1_wed, "success")
    await _deploy(db_session, tenant.id, b.id, 1, week2_tue, "success")
    res = await dora_service.deployment_frequency(
        db_session, tenant.id, week1_mon, week2_tue, granularity="week"
    )
    assert res["total"] == 3
    assert len(res["series"]) == 2
    # week-1 bucket: 2026-06-01
    assert res["series"][0] == {"period": "2026-06-01", "count": 2}
    # week-2 bucket: 2026-06-08
    assert res["series"][1] == {"period": "2026-06-08", "count": 1}


@pytest.mark.asyncio
async def test_deployment_frequency_month_bucketing(db_session, tenant):
    """Two deployments in June, one in July → two distinct monthly buckets."""
    june_start = datetime(2026, 6, 1, tzinfo=UTC)
    june_mid = datetime(2026, 6, 15, tzinfo=UTC)
    july_start = datetime(2026, 7, 1, tzinfo=UTC)
    b = await _build(db_session, tenant.id, june_start - timedelta(days=1))
    await _deploy(db_session, tenant.id, b.id, 1, june_start, "success")
    await _deploy(db_session, tenant.id, b.id, 1, june_mid, "success")
    await _deploy(db_session, tenant.id, b.id, 1, july_start, "success")
    res = await dora_service.deployment_frequency(
        db_session, tenant.id, june_start, july_start, granularity="month"
    )
    assert res["total"] == 3
    assert len(res["series"]) == 2
    assert res["series"][0] == {"period": "2026-06-01", "count": 2}
    assert res["series"][1] == {"period": "2026-07-01", "count": 1}


# ---------------------------------------------------------------------------
# Task 6: Lead-time p90
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lead_time_p90(db_session, tenant):
    """p90 over lead times of 1h,2h,3h,4h,5h matches _percentile formula."""
    t0 = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    lead_hours = [1, 2, 3, 4, 5]
    for h in lead_hours:
        b = await _build(db_session, tenant.id, t0 - timedelta(hours=h))
        await _deploy(db_session, tenant.id, b.id, 1, t0, "success")
    res = await dora_service.lead_time(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=1)
    )
    assert res["count"] == 5
    expected_p90 = _percentile(sorted(h * 3600 for h in lead_hours), 0.9)
    assert abs(res["p90_seconds"] - expected_p90) < 1e-6


# ---------------------------------------------------------------------------
# Task 7: CFR actual_date fallback (no ReleaseStatusHistory row)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cfr_actual_date_fallback_counts_in_shipped(db_session, tenant):
    """
    Release reaches terminal 'completed' state but has NO ReleaseStatusHistory row.
    actual_date falls inside the window → it is counted in shipped_count.
    Because 'completed' is not is_failed and no incident → failed_count unaffected.
    """
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    u = await _user(db_session, tenant.id)
    r = Release(tenant_id=tenant.id, name="R-fallback", release_type="Major",
                release_kind="project", lifecycle_template_id=tpl.id,
                status="completed", raised_by=u.id,
                actual_date=t0 + timedelta(days=1))
    db_session.add(r)
    await db_session.flush()
    # No ReleaseStatusHistory row — fallback to actual_date
    b = await _build(db_session, tenant.id, t0)
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success", release_id=r.id)
    await db_session.flush()
    res = await dora_service.change_failure_rate(
        db_session, tenant.id, t0, t0 + timedelta(days=7)
    )
    assert res["shipped_count"] == 1
    assert res["failed_count"] == 0


# ---------------------------------------------------------------------------
# Task 8: CFR non-terminal exclusion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cfr_non_terminal_release_excluded(db_session, tenant):
    """
    Release whose current status is non-terminal ('draft') is excluded from
    shipped_count even when it has a deployment in the window.
    """
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    u = await _user(db_session, tenant.id)
    r = Release(tenant_id=tenant.id, name="R-draft", release_type="Major",
                release_kind="project", lifecycle_template_id=tpl.id,
                status="draft", raised_by=u.id)
    db_session.add(r)
    await db_session.flush()
    b = await _build(db_session, tenant.id, t0 - timedelta(days=1))
    await _deploy(db_session, tenant.id, b.id, 1, t0, "success", release_id=r.id)
    await db_session.flush()
    res = await dora_service.change_failure_rate(
        db_session, tenant.id, t0, t0 + timedelta(days=7)
    )
    assert res["shipped_count"] == 0
    assert res["failed_count"] == 0


# ---------------------------------------------------------------------------
# Task 9: MTTR series + median
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mttr_series_and_median_across_two_weeks(db_session, tenant):
    """
    Incidents resolved in two different weeks produce two series buckets,
    and median_seconds is correct across all incidents.
    """
    # 2026-06-01 (Mon) week, 2026-06-08 (Mon) week
    w1 = datetime(2026, 6, 2, tzinfo=UTC)   # Tuesday in week 1
    w2 = datetime(2026, 6, 9, tzinfo=UTC)   # Tuesday in week 2
    # Week-1: one incident, 2h resolution
    db_session.add(Incident(
        tenant_id=tenant.id, title="i1", severity="P1", status="resolved",
        detected_at=w1 - timedelta(hours=2), resolved_at=w1, source="manual",
    ))
    # Week-2: two incidents, 4h and 6h resolution
    db_session.add(Incident(
        tenant_id=tenant.id, title="i2", severity="P2", status="resolved",
        detected_at=w2 - timedelta(hours=4), resolved_at=w2, source="manual",
    ))
    db_session.add(Incident(
        tenant_id=tenant.id, title="i3", severity="P2", status="resolved",
        detected_at=w2 - timedelta(hours=6), resolved_at=w2 + timedelta(hours=1), source="manual",
    ))
    await db_session.flush()
    res = await dora_service.mttr(
        db_session, tenant.id,
        datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 16, tzinfo=UTC),
        granularity="week",
    )
    assert res["count"] == 3
    assert len(res["series"]) == 2
    # week-1 bucket key = 2026-06-01 (Monday)
    assert res["series"][0]["period"] == "2026-06-01"
    assert abs(res["series"][0]["mean_seconds"] - 2 * 3600) < 1
    # week-2 bucket key = 2026-06-08 (Monday)
    assert res["series"][1]["period"] == "2026-06-08"
    # sorted vals: [2h, 4h, 7h] in seconds → median = 4h
    from statistics import median as _median
    expected_median = _median(sorted([2 * 3600, 4 * 3600, 7 * 3600]))
    assert abs(res["median_seconds"] - expected_median) < 1


# ---------------------------------------------------------------------------
# Task 10: Service-level tenant isolation for deployment_frequency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deployment_frequency_tenant_isolation(db_session, tenant):
    """
    A success deployment belonging to a SECOND tenant must NOT appear in
    deployment_frequency results for the first tenant.
    """
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    # Deployment for the primary tenant
    b1 = await _build(db_session, tenant.id, t0 - timedelta(days=1))
    await _deploy(db_session, tenant.id, b1.id, 1, t0, "success")

    # Create a second tenant inline
    t2 = Tenant(name="Isolated Org", slug="isolated-org")
    db_session.add(t2)
    await db_session.flush()

    # Deployment for the second tenant (same date range)
    b2 = await _build(db_session, t2.id, t0 - timedelta(days=1), subsystem_id=2)
    await _deploy(db_session, t2.id, b2.id, 1, t0, "success")

    res = await dora_service.deployment_frequency(
        db_session, tenant.id, t0, t0 + timedelta(days=7), granularity="week"
    )
    assert res["total"] == 1
