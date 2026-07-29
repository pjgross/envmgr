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

# Booking statuses that do NOT represent a live claim on an environment:
# draft (uncommitted) + the two terminal states (rejected, closed). Note this is a
# superset of conflict_service.TERMINAL_STATES ({rejected, closed}) — the metric also
# drops draft. Booking lifecycle has no "cancelled" state.
_INACTIVE_BOOKING_STATES = {"draft", "rejected", "closed"}


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


async def _closed_releases_in_window(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime
) -> tuple[list[Release], set[int]]:
    """Releases in a terminal lifecycle state whose close date is in the window,
    plus the set of release ids that have >=1 deployment ("shipped").

    Close-date resolution replicates dora_service.change_failure_rate (latest
    ReleaseStatusHistory into the current status, fallback actual_date) so the
    "closed in window" set is consistent with the DORA CFR denominator.
    """
    releases = (await db.execute(
        select(Release).where(Release.tenant_id == tenant_id, Release.deleted_at.is_(None))
    )).scalars().all()

    shipped_ids = set((await db.execute(
        select(Deployment.release_id).where(
            Deployment.tenant_id == tenant_id,
            Deployment.deleted_at.is_(None),
            Deployment.release_id.isnot(None),
        )
    )).scalars().all())

    tpl_cache: dict[int, dict] = {}

    async def _definition(tid: int) -> dict:
        if tid not in tpl_cache:
            tpl = (await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.id == tid,
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            tpl_cache[tid] = tpl.definition if tpl else {"states": []}
        return tpl_cache[tid]

    closed: list[Release] = []
    for r in releases:
        definition = await _definition(r.lifecycle_template_id)
        state = next((s for s in definition.get("states", []) if s.get("key") == r.status), None)
        if state is None or not state.get("is_terminal"):
            continue
        close_at = (await db.execute(
            select(ReleaseStatusHistory.changed_at).where(
                ReleaseStatusHistory.release_id == r.id,
                ReleaseStatusHistory.to_state == r.status,
            ).order_by(ReleaseStatusHistory.changed_at.desc()).limit(1)
        )).scalars().first() or r.actual_date
        close_at = _utc(close_at)
        if close_at is None or not (date_from <= close_at <= date_to):
            continue
        closed.append(r)
    return closed, shipped_ids


async def release_metrics(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime
) -> dict:
    """Release-level success rate, emergency %, and average cycle time over the window.

    success_rate is derived from dora_service.change_failure_rate (exact complement
    of the DORA CFR). emergency_pct and avg_cycle_time are computed from the
    closed-in-window release set.

    Note: emergency_pct/closed_count are over ALL closed-in-window releases, whereas
    success_rate/shipped_count/failed_count are over the shipped subset (closed releases
    with >=1 deployment) — a deliberate denominator difference.
    """
    cfr = await dora_service.change_failure_rate(db, tenant_id, date_from, date_to)
    shipped_count = cfr["shipped_count"]
    failed_count = cfr["failed_count"]
    success_rate = (1.0 - cfr["rate"]) if shipped_count else 0.0

    closed, shipped_ids = await _closed_releases_in_window(db, tenant_id, date_from, date_to)
    closed_count = len(closed)
    emergency_count = sum(1 for r in closed if r.release_type == "Emergency")
    emergency_pct = (emergency_count / closed_count) if closed_count else 0.0

    cycle_secs: list[float] = []
    for r in closed:
        if r.id in shipped_ids and r.actual_date is not None:
            created = _utc(r.created_at)
            actual = _utc(r.actual_date)
            cycle_secs.append(max(0.0, (actual - created).total_seconds()))
    avg_cycle = (sum(cycle_secs) / len(cycle_secs)) if cycle_secs else 0.0

    return {
        "success_rate": success_rate,
        "shipped_count": shipped_count,
        "failed_count": failed_count,
        "emergency_pct": emergency_pct,
        "emergency_count": emergency_count,
        "closed_count": closed_count,
        "avg_cycle_time_seconds": avg_cycle,
        "cycle_time_count": len(cycle_secs),
    }
