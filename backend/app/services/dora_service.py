from datetime import date, datetime, timedelta
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.build import Build
from app.db.models.deployment import Deployment


def _bucket_start(dt: datetime, granularity: str) -> str:
    d = dt.date()
    if granularity == "day":
        start = d
    elif granularity == "month":
        start = d.replace(day=1)
    else:  # week, Monday-start
        start = d - timedelta(days=d.weekday())
    return start.isoformat()


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


async def deployment_frequency(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    conds = [
        Deployment.tenant_id == tenant_id, Deployment.deleted_at.is_(None),
        Deployment.status == "success",
        Deployment.deployed_at >= date_from, Deployment.deployed_at <= date_to,
    ]
    if environment_id is not None:
        conds.append(Deployment.environment_id == environment_id)
    if release_id is not None:
        conds.append(Deployment.release_id == release_id)
    rows = (await db.execute(select(Deployment.deployed_at).where(*conds))).scalars().all()
    buckets: dict[str, int] = {}
    for dep_at in rows:
        buckets[_bucket_start(dep_at, granularity)] = buckets.get(_bucket_start(dep_at, granularity), 0) + 1
    series = [{"period": k, "count": v} for k, v in sorted(buckets.items())]
    return {"total": len(rows), "series": series}


async def lead_time(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    conds = [
        Deployment.tenant_id == tenant_id, Deployment.deleted_at.is_(None),
        Deployment.status == "success",
        Deployment.deployed_at >= date_from, Deployment.deployed_at <= date_to,
    ]
    if environment_id is not None:
        conds.append(Deployment.environment_id == environment_id)
    if release_id is not None:
        conds.append(Deployment.release_id == release_id)
    rows = (await db.execute(
        select(Deployment.deployed_at, Build.commit_timestamp)
        .join(Build, Build.id == Deployment.build_id)
        .where(*conds)
    )).all()
    per_bucket: dict[str, list[float]] = {}
    all_vals: list[float] = []
    for deployed_at, commit_ts in rows:
        lead = max(0.0, (deployed_at - commit_ts).total_seconds())
        all_vals.append(lead)
        per_bucket.setdefault(_bucket_start(deployed_at, granularity), []).append(lead)
    all_sorted = sorted(all_vals)
    series = [
        {"period": k, "median_seconds": median(v)} for k, v in sorted(per_bucket.items())
    ]
    return {
        "median_seconds": median(all_sorted) if all_sorted else 0,
        "p90_seconds": _percentile(all_sorted, 0.9),
        "count": len(all_vals),
        "series": series,
    }
