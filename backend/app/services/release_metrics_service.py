"""Release/utilization metrics (Phase 5 SP5b).

Pure, tenant-scoped, on-demand aggregation over existing Release / Deployment /
Booking data. No new models. success_rate reuses dora_service.change_failure_rate
so it is the exact complement of the DORA Change Failure Rate.
"""
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.db.models.environment import Environment
from app.db.models.deployment import Deployment
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.services import dora_service

# Booking statuses that do NOT represent a live claim on an environment.
_INACTIVE_BOOKING_STATES = {"draft", "cancelled", "rejected"}


def _utc(dt: datetime | None) -> datetime | None:
    """Normalise a possibly-naive (SQLite) datetime to UTC-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def booking_conflicts(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime
) -> list[dict]:
    """Per-environment, per-month count of overlapping active-booking pairs.

    A "conflict" is an overlapping pair of active bookings (status not draft/
    cancelled/rejected) on the same environment. Each pair is counted once, in
    the calendar month of its overlap start (max of the two start dates).
    """
    rows = (await db.execute(
        select(
            Booking.environment_id, Booking.start_date, Booking.end_date, Environment.name
        )
        .join(Environment, Environment.id == Booking.environment_id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(_INACTIVE_BOOKING_STATES)),
            Environment.tenant_id == tenant_id,
            Environment.deleted_at.is_(None),
            # window overlap: the booking touches [date_from, date_to]
            Booking.start_date < date_to,
            Booking.end_date > date_from,
        )
    )).all()

    # group bookings by environment
    by_env: dict[tuple[int, str], list[tuple[datetime, datetime]]] = defaultdict(list)
    for env_id, start, end, env_name in rows:
        by_env[(env_id, env_name)].append((_utc(start), _utc(end)))

    # count overlapping pairs per env, bucketed by overlap-start month
    counts: dict[tuple[int, str, str], int] = defaultdict(int)
    for (env_id, env_name), bookings in by_env.items():
        n = len(bookings)
        for i in range(n):
            s1, e1 = bookings[i]
            for j in range(i + 1, n):
                s2, e2 = bookings[j]
                if s1 < e2 and e1 > s2:  # half-open overlap
                    overlap_start = max(s1, s2)
                    month = overlap_start.strftime("%Y-%m")
                    counts[(env_id, env_name, month)] += 1

    result = [
        {"environment_id": env_id, "environment_name": env_name,
         "month": month, "conflict_count": count}
        for (env_id, env_name, month), count in counts.items()
    ]
    result.sort(key=lambda r: (r["environment_name"], r["month"]))
    return result
