import pytest
from datetime import datetime, timezone, timedelta

from app.services import environment_utilization_service as util

UTC = timezone.utc


def _cfg(tz="UTC", week=None):
    """A lightweight stand-in for an EnvironmentOperatingHours row for pure-helper tests."""
    class _C:
        pass
    c = _C()
    c.timezone = tz
    c.week = week if week is not None else [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]
    return c


def test_merge_intervals_overlapping():
    t = datetime(2026, 6, 1, 9, tzinfo=UTC)
    ivals = [(t, t + timedelta(hours=3)), (t + timedelta(hours=2), t + timedelta(hours=4))]
    merged = util._merge_intervals(ivals)
    assert merged == [(t, t + timedelta(hours=4))]


def test_intersect_seconds():
    t = datetime(2026, 6, 1, 9, tzinfo=UTC)
    seg = (t, t + timedelta(hours=8))                          # 09:00-17:00
    ivals = [(t + timedelta(hours=1), t + timedelta(hours=3))]  # 10:00-12:00
    assert util._intersect(seg, ivals) == 2 * 3600


def test_operating_segments_weekday_total_one_week():
    # Mon-Fri 09:00-17:00 (8h), Sat/Sun closed → 5 days * 8h = 40h over a Mon..Sun window.
    week = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(5)] + \
           [{"closed": True}, {"closed": True}]
    cfg = _cfg("UTC", week)
    # 2026-06-01 is a Monday; window covers Mon..Sun.
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 40 * 3600
    assert len(segments) == 5


def test_operating_segments_dst_spring_forward_is_wall_clock():
    # Europe/London springs forward on 2026-03-29. Fixed 09:00-17:00 daily (8h wall-clock).
    # Window Sat 03-28 .. Mon 03-30 → 3 days * 8h = 24h regardless of the DST jump,
    # because 09:00-17:00 local is always 8 wall-clock hours.
    week = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]
    cfg = _cfg("Europe/London", week)
    start = datetime(2026, 3, 28, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 30, 23, 59, 59, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 24 * 3600
    # The 03-29 (DST) segment: 09:00 BST == 08:00 UTC, 17:00 BST == 16:00 UTC → still 8h.
    dst_day = [s for s in segments if s[0].date().isoformat() == "2026-03-29"][0]
    assert (dst_day[1] - dst_day[0]).total_seconds() == 8 * 3600
    assert dst_day[0].hour == 8  # 09:00 BST in UTC


def test_operating_segments_clips_to_window():
    week = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(7)]
    cfg = _cfg("UTC", week)
    # Window starts mid-operating-hours on the single day 2026-06-01 10:00..12:00
    start = datetime(2026, 6, 1, 10, tzinfo=UTC)
    end = datetime(2026, 6, 1, 12, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 2 * 3600


def test_operating_segments_spanning_spring_forward_real_elapsed():
    # Only Sunday open 00:00-06:00. 2026-03-29 (Sun) is the UK spring-forward date:
    # clocks jump 01:00->02:00, so 00:00-06:00 local is only 5 real UTC hours.
    week = [{"closed": True} for _ in range(6)] + [{"closed": False, "open": "00:00", "close": "06:00"}]
    cfg = _cfg("Europe/London", week)
    start = datetime(2026, 3, 28, tzinfo=UTC)
    end = datetime(2026, 3, 30, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 5 * 3600


def test_operating_segments_spanning_fall_back_real_elapsed():
    # 2026-10-25 (Sun) is the UK fall-back date: clocks go 02:00->01:00,
    # so 00:00-06:00 local is 7 real UTC hours.
    week = [{"closed": True} for _ in range(6)] + [{"closed": False, "open": "00:00", "close": "06:00"}]
    cfg = _cfg("Europe/London", week)
    start = datetime(2026, 10, 24, tzinfo=UTC)
    end = datetime(2026, 10, 26, tzinfo=UTC)
    segments, total = util._operating_segments(cfg, start, end)
    assert total == 7 * 3600


# --- DB-backed utilization -------------------------------------------------

from app.db.models.environment import Environment  # noqa: E402
from app.db.models.booking import Booking  # noqa: E402
from app.db.models.booking_request import BookingRequest  # noqa: E402
from app.db.models.user import User, Tenant  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.services import environment_operating_hours_service as ops_service  # noqa: E402

_MONFRI = [{"closed": False, "open": "09:00", "close": "17:00"} for _ in range(5)] + \
          [{"closed": True}, {"closed": True}]

_uc = 0


async def _mk_env(db, tenant_id, name="Env"):
    e = Environment(tenant_id=tenant_id, name=name, environment_type="test")
    db.add(e); await db.flush(); return e


async def _mk_user(db, tenant_id):
    global _uc
    _uc += 1
    u = User(tenant_id=tenant_id, username=f"utu{_uc}", email=f"utu{_uc}@t.com",
             password_hash=get_password_hash("x"), role="Viewer", is_active=True)
    db.add(u); await db.flush(); return u


async def _mk_booking(db, tenant_id, env_id, user_id, start, end, status="approved"):
    req = BookingRequest(tenant_id=tenant_id, project_name="P", booked_by=user_id, booking_type_id=1,
                         start_date=start, end_date=end)
    db.add(req); await db.flush()
    b = Booking(tenant_id=tenant_id, environment_id=env_id, booking_request_id=req.id,
                start_date=start, end_date=end, status=status)
    db.add(b); await db.flush(); return b


@pytest.mark.asyncio
async def test_environment_utilization_single_booking(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    u = await _mk_user(db_session, tenant.id)
    await ops_service.upsert_config(db_session, tenant.id, env.id, "UTC", _MONFRI)
    # Window: Mon 2026-06-01 .. Sun 2026-06-07 → total 40h. Booking Tue 09:00-12:00 → 3h booked.
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 2, 9, tzinfo=UTC), datetime(2026, 6, 2, 12, tzinfo=UTC))
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["configured"] is True
    assert res["total_operating_seconds"] == 40 * 3600
    assert res["booked_operating_seconds"] == 3 * 3600
    assert abs(res["utilization_pct"] - (3 / 40)) < 1e-9


@pytest.mark.asyncio
async def test_environment_utilization_union_of_overlapping(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    u = await _mk_user(db_session, tenant.id)
    await ops_service.upsert_config(db_session, tenant.id, env.id, "UTC", _MONFRI)
    # Two overlapping bookings Tue 09-12 and Tue 11-13 → union 09-13 within op hours = 4h (not 5h).
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 2, 9, tzinfo=UTC), datetime(2026, 6, 2, 12, tzinfo=UTC))
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 2, 11, tzinfo=UTC), datetime(2026, 6, 2, 13, tzinfo=UTC))
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["booked_operating_seconds"] == 4 * 3600


@pytest.mark.asyncio
async def test_environment_utilization_excludes_outside_hours_and_inactive(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    u = await _mk_user(db_session, tenant.id)
    await ops_service.upsert_config(db_session, tenant.id, env.id, "UTC", _MONFRI)
    # Booking on Sat (closed) → 0 booked
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 6, 9, tzinfo=UTC), datetime(2026, 6, 6, 17, tzinfo=UTC))
    # Draft booking during op hours → excluded
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 3, 9, tzinfo=UTC), datetime(2026, 6, 3, 17, tzinfo=UTC),
                      status="draft")
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["booked_operating_seconds"] == 0.0


@pytest.mark.asyncio
async def test_environment_utilization_unconfigured(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["configured"] is False
    assert res["total_operating_seconds"] == 0.0
    assert res["utilization_pct"] == 0.0
    assert res["environment_name"] == env.name


@pytest.mark.asyncio
async def test_utilization_overview_lists_configured_counts_unconfigured(db_session, tenant):
    e1 = await _mk_env(db_session, tenant.id, name="AAA")
    e2 = await _mk_env(db_session, tenant.id, name="BBB")  # left unconfigured
    await ops_service.upsert_config(db_session, tenant.id, e1.id, "UTC", _MONFRI)
    res = await util.utilization_overview(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert [r["environment_name"] for r in res["rows"]] == ["AAA"]
    assert res["unconfigured_count"] == 1


@pytest.mark.asyncio
async def test_utilization_tenant_isolation(db_session, tenant):
    t2 = Tenant(name="Other2", slug="other-util")
    db_session.add(t2); await db_session.flush()
    e2 = await _mk_env(db_session, t2.id, name="ForeignEnv")
    await ops_service.upsert_config(db_session, t2.id, e2.id, "UTC", _MONFRI)
    res = await util.utilization_overview(
        db_session, tenant.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["rows"] == []
    assert res["unconfigured_count"] == 0


@pytest.mark.asyncio
async def test_environment_utilization_excludes_rejected_and_closed(db_session, tenant):
    env = await _mk_env(db_session, tenant.id)
    u = await _mk_user(db_session, tenant.id)
    await ops_service.upsert_config(db_session, tenant.id, env.id, "UTC", _MONFRI)
    # rejected + closed bookings fully inside operating hours → both excluded → 0 booked
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 2, 9, tzinfo=UTC), datetime(2026, 6, 2, 12, tzinfo=UTC), status="rejected")
    await _mk_booking(db_session, tenant.id, env.id, u.id,
                      datetime(2026, 6, 3, 9, tzinfo=UTC), datetime(2026, 6, 3, 12, tzinfo=UTC), status="closed")
    res = await util.environment_utilization(
        db_session, tenant.id, env.id, datetime(2026, 6, 1, tzinfo=UTC),
        datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC))
    assert res["booked_operating_seconds"] == 0.0
