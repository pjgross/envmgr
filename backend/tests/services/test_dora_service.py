import pytest
from datetime import datetime, timezone, timedelta
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.incident import Incident
from app.db.models.user import User
from app.core.security import get_password_hash
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
