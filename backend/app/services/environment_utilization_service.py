"""Environment utilization (Phase 5 SP5a).

Utilization = booked ÷ total operating time over a window, union-based (each operating
second is booked or not), so utilization is 0..1. Operating hours are wall-clock times in
the environment's IANA timezone, localized per calendar date → DST-correct via zoneinfo.
Booked = active bookings (status not in {draft,rejected,closed}). Pure, tenant-scoped.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment
from app.db.models.booking import Booking
from app.services import environment_operating_hours_service as ops_service

_INACTIVE_BOOKING_STATES = {"draft", "rejected", "closed"}


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Merge overlapping/adjacent [start, end) intervals into a sorted disjoint list."""
    out: list[tuple[datetime, datetime]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _intersect(seg: tuple[datetime, datetime], intervals: list[tuple[datetime, datetime]]) -> float:
    """Seconds of `seg` covered by the (already-merged) `intervals`."""
    total = 0.0
    a, b = seg
    for c, d in intervals:
        lo = max(a, c)
        hi = min(b, d)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _operating_segments(config, date_from: datetime, date_to: datetime):
    """Return (list of UTC operating segments clipped to the window, total seconds).

    Iterates each calendar date in the window IN THE CONFIG'S TIMEZONE, localizes that
    day's wall-clock open/close, converts to UTC, and clips to [date_from, date_to].
    """
    date_from, date_to = _utc(date_from), _utc(date_to)
    tz = ZoneInfo(config.timezone)
    week = config.week
    segments: list[tuple[datetime, datetime]] = []
    total = 0.0
    d = date_from.astimezone(tz).date()
    last = date_to.astimezone(tz).date()
    while d <= last:
        entry = week[d.weekday()]
        if not entry.get("closed"):
            oh, om = _parse_hhmm(entry["open"])
            ch, cm = _parse_hhmm(entry["close"])
            local_open = datetime(d.year, d.month, d.day, oh, om, tzinfo=tz)
            local_close = datetime(d.year, d.month, d.day, ch, cm, tzinfo=tz)
            su = max(local_open.astimezone(timezone.utc), date_from)
            eu = min(local_close.astimezone(timezone.utc), date_to)
            if eu > su:
                segments.append((su, eu))
                total += (eu - su).total_seconds()
        d += timedelta(days=1)
    return segments, total
