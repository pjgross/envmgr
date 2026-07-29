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
