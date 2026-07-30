import pytest
from datetime import datetime, timezone, timedelta

from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.user import User, Tenant
from app.core.security import get_password_hash
from app.services import release_metrics_service
from tests.factories import ensure_booking_type, ensure_change_request, ensure_environment, ensure_subsystem

UTC = timezone.utc

_user_counter = 0


async def _user(db, tenant_id):
    global _user_counter
    _user_counter += 1
    u = User(tenant_id=tenant_id, username=f"rmuser{_user_counter}",
             email=f"rmuser{_user_counter}@test.com",
             password_hash=get_password_hash("x"), role="Viewer", is_active=True)
    db.add(u); await db.flush(); return u


async def _env(db, tenant_id, name):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


async def _booking_request(db, tenant_id, user_id):
    # Required non-defaulted columns: tenant_id, project_name, booking_type_id (FK — any int
    # is fine, SQLite tests don't enforce FKs), start_date, end_date, booked_by. context_tag
    # and exclusive_use_requested have model defaults. The request-level dates are placeholders;
    # conflict overlap is computed from the Booking rows, not the request.
    req = BookingRequest(
        tenant_id=tenant_id, project_name="Proj", booked_by=user_id,
        booking_type_id=(await ensure_booking_type(db, tenant_id)).id,
        start_date=datetime(2026, 6, 1, tzinfo=UTC), end_date=datetime(2026, 6, 30, tzinfo=UTC),
    )
    db.add(req); await db.flush(); return req


async def _booking(db, tenant_id, env_id, req_id, start, end, status="approved"):
    b = Booking(tenant_id=tenant_id, environment_id=env_id, booking_request_id=req_id,
                start_date=start, end_date=end, status=status)
    db.add(b); await db.flush(); return b


@pytest.mark.asyncio
async def test_conflicts_counts_one_overlapping_pair(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Two bookings that overlap (b2 starts before b1 ends)
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["environment_id"] == env.id
    assert rows[0]["environment_name"] == "SIT"
    assert rows[0]["month"] == "2026-06"
    assert rows[0]["conflict_count"] == 1


@pytest.mark.asyncio
async def test_conflicts_non_overlapping_is_zero(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=1))
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=2), t0 + timedelta(days=3))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []


@pytest.mark.asyncio
async def test_conflicts_excludes_draft_and_closed(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Overlapping window, but one booking is draft and one is closed → no counted pair
    await _booking(db_session, tenant.id, env.id, req.id, t0, t0 + timedelta(days=3), status="draft")
    await _booking(db_session, tenant.id, env.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4), status="closed")
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []


@pytest.mark.asyncio
async def test_conflicts_per_env_grouping(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env_a = await _env(db_session, tenant.id, "SIT")
    env_b = await _env(db_session, tenant.id, "UAT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Overlapping pair on env_a; overlapping pair on env_b
    await _booking(db_session, tenant.id, env_a.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env_a.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await _booking(db_session, tenant.id, env_b.id, req.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, tenant.id, env_b.id, req.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert len(rows) == 2
    by_env = {r["environment_name"]: r["conflict_count"] for r in rows}
    assert by_env == {"SIT": 1, "UAT": 1}


@pytest.mark.asyncio
async def test_conflicts_tenant_isolation(db_session, tenant):
    u = await _user(db_session, tenant.id)
    env = await _env(db_session, tenant.id, "SIT")
    req = await _booking_request(db_session, tenant.id, u.id)
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    # Second tenant with its own overlapping pair
    t2 = Tenant(name="Other Org", slug="other-org-rm")
    db_session.add(t2); await db_session.flush()
    u2 = await _user(db_session, t2.id)
    env2 = await _env(db_session, t2.id, "SIT2")
    req2 = await _booking_request(db_session, t2.id, u2.id)
    await _booking(db_session, t2.id, env2.id, req2.id, t0, t0 + timedelta(days=3))
    await _booking(db_session, t2.id, env2.id, req2.id, t0 + timedelta(days=1), t0 + timedelta(days=4))
    await db_session.flush()
    # Query the FIRST tenant (which has no bookings) → empty
    rows = await release_metrics_service.booking_conflicts(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 30, tzinfo=UTC))
    assert rows == []


# ---------------------------------------------------------------------------
# release_metrics
# ---------------------------------------------------------------------------

from app.db.models.release import Release, ReleaseStatusHistory  # noqa: E402
from app.db.models.lifecycle import LifecycleTemplate  # noqa: E402
from app.db.models.deployment import Deployment  # noqa: E402
from app.db.models.build import Build  # noqa: E402
from app.db.models.incident import Incident  # noqa: E402

_build_counter = 0
_deploy_counter = 0


async def _build(db, tenant_id, commit_dt, subsystem_id=None):
    global _build_counter
    _build_counter += 1
    sha = f"rm{_build_counter:038d}"
    if subsystem_id is None:
        subsystem_id = (await ensure_subsystem(db, tenant_id)).id
    b = Build(tenant_id=tenant_id, subsystem_id=subsystem_id, git_sha=sha,
              build_number=str(_build_counter), commit_timestamp=commit_dt)
    db.add(b); await db.flush(); return b


async def _deploy(db, tenant_id, build_id, env_id, deployed_dt, release_id, change_request_id=None):
    global _deploy_counter
    _deploy_counter += 1
    if env_id is not None and env_id < 1000:
        # Small integers are slots, not real ids — see tests.factories.
        env_id = (await ensure_environment(db, tenant_id, env_id)).id
    if change_request_id is None:
        change_request_id = (await ensure_change_request(db, tenant_id)).id
    d = Deployment(tenant_id=tenant_id, build_id=build_id, environment_id=env_id,
                   release_id=release_id, change_request_id=change_request_id,
                   event_id=f"rm-e{deployed_dt.timestamp()}-{_deploy_counter}",
                   deployed_at=deployed_dt, status="success", custom_fields={})
    db.add(d); await db.flush(); return d


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


async def _release(db, tenant_id, tpl_id, status, close_dt, *, release_type="Major",
                   created_at=None, actual_date=None, with_deploy=True):
    u = await _user(db, tenant_id)
    r = Release(tenant_id=tenant_id, name="R", release_type=release_type, release_kind="project",
                lifecycle_template_id=tpl_id, status=status, raised_by=u.id,
                actual_date=actual_date)
    if created_at is not None:
        r.created_at = created_at  # override server_default so cycle-time is deterministic
    db.add(r); await db.flush()
    db.add(ReleaseStatusHistory(release_id=r.id, to_state=status, changed_at=close_dt, changed_by=u.id))
    if with_deploy:
        b = await _build(db, tenant_id, close_dt - timedelta(days=1))
        await _deploy(db, tenant_id, b.id, 1, close_dt, r.id)
    await db.flush(); return r


@pytest.mark.asyncio
async def test_success_rate_half_when_one_of_two_failed(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    await _release(db_session, tenant.id, tpl.id, "completed", t0)                     # clean
    await _release(db_session, tenant.id, tpl.id, "backed_out", t0 + timedelta(days=1))  # failed
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["shipped_count"] == 2
    assert res["failed_count"] == 1
    assert abs(res["success_rate"] - 0.5) < 1e-9


@pytest.mark.asyncio
async def test_causal_incident_counts_as_failed(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    r = await _release(db_session, tenant.id, tpl.id, "completed", t0)
    db_session.add(Incident(tenant_id=tenant.id, title="x", severity="P1", status="new",
                            detected_at=t0, release_id=r.id, source="manual"))
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["shipped_count"] == 1
    assert res["failed_count"] == 1
    assert res["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_empty_window_zeroes(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0, t0 + timedelta(days=1))
    assert res["shipped_count"] == 0
    assert res["success_rate"] == 0.0
    assert res["emergency_pct"] == 0.0
    assert res["closed_count"] == 0
    assert res["avg_cycle_time_seconds"] == 0.0
    assert res["cycle_time_count"] == 0


@pytest.mark.asyncio
async def test_emergency_pct(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # 1 Emergency + 3 non-Emergency closed releases → 25%
    await _release(db_session, tenant.id, tpl.id, "completed", t0, release_type="Emergency")
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=1), release_type="Major")
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=2), release_type="Minor")
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=3), release_type="Major")
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["closed_count"] == 4
    assert res["emergency_count"] == 1
    assert abs(res["emergency_pct"] - 0.25) < 1e-9


@pytest.mark.asyncio
async def test_avg_cycle_time_over_shipped(db_session, tenant):
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # created 2 days before ship → 2-day cycle; created 4 days before → 4-day cycle. mean = 3 days.
    await _release(db_session, tenant.id, tpl.id, "completed", t0,
                   created_at=t0 - timedelta(days=2), actual_date=t0)
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=1),
                   created_at=(t0 + timedelta(days=1)) - timedelta(days=4),
                   actual_date=t0 + timedelta(days=1))
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["cycle_time_count"] == 2
    assert abs(res["avg_cycle_time_seconds"] - 3 * 86400) < 1


@pytest.mark.asyncio
async def test_avg_cycle_time_excludes_null_actual_date_and_clamps_negative(db_session, tenant):
    t0 = datetime(2026, 6, 10, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # shipped, actual_date present, but created AFTER actual_date → clamp to 0
    await _release(db_session, tenant.id, tpl.id, "completed", t0,
                   created_at=t0 + timedelta(days=1), actual_date=t0)
    # shipped but NO actual_date → excluded from the cycle-time average
    await _release(db_session, tenant.id, tpl.id, "completed", t0 + timedelta(days=1),
                   created_at=t0 - timedelta(days=2), actual_date=None)
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    # only the first (clamped to 0) contributes
    assert res["cycle_time_count"] == 1
    assert res["avg_cycle_time_seconds"] == 0.0


@pytest.mark.asyncio
async def test_release_metrics_tenant_isolation(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    t2 = Tenant(name="Other Org2", slug="other-org-rm2")
    db_session.add(t2); await db_session.flush()
    tpl2 = await _release_template(db_session, t2.id)
    await _release(db_session, t2.id, tpl2.id, "completed", t0, release_type="Emergency")
    await db_session.flush()
    # Query the first tenant → nothing counted
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["closed_count"] == 0
    assert res["shipped_count"] == 0


@pytest.mark.asyncio
async def test_emergency_pct_over_all_closed_including_unshipped(db_session, tenant):
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    tpl = await _release_template(db_session, tenant.id)
    # closed Emergency release with NO deployment → counts toward closed/emergency but NOT shipped
    await _release(db_session, tenant.id, tpl.id, "completed", t0,
                   release_type="Emergency", with_deploy=False)
    await db_session.flush()
    res = await release_metrics_service.release_metrics(
        db_session, tenant.id, t0 - timedelta(days=1), t0 + timedelta(days=7))
    assert res["closed_count"] == 1
    assert res["emergency_count"] == 1
    assert res["emergency_pct"] == 1.0
    assert res["shipped_count"] == 0
