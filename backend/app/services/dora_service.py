from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.incident import Incident


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
        key = _bucket_start(dep_at, granularity)
        buckets[key] = buckets.get(key, 0) + 1
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


async def change_failure_rate(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
) -> dict:
    # Terminal-close date per release: latest history row whose to_state == release.status.
    rel_conds = [Release.tenant_id == tenant_id, Release.deleted_at.is_(None)]
    if release_id is not None:
        rel_conds.append(Release.id == release_id)
    releases = (await db.execute(select(Release).where(*rel_conds))).scalars().all()

    # Memoize template definitions by id.
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

    # Releases with >=1 deployment (shipped), optionally env-filtered.
    dep_conds = [Deployment.tenant_id == tenant_id, Deployment.deleted_at.is_(None), Deployment.release_id.isnot(None)]
    if environment_id is not None:
        dep_conds.append(Deployment.environment_id == environment_id)
    shipped_ids = set((await db.execute(select(Deployment.release_id).where(*dep_conds))).scalars().all())

    shipped = 0
    failed = 0
    for r in releases:
        if r.id not in shipped_ids:
            continue
        definition = await _definition(r.lifecycle_template_id)
        state = next((s for s in definition.get("states", []) if s.get("key") == r.status), None)
        if state is None or not state.get("is_terminal"):
            continue  # not closed
        # close date = latest history changed_at into the current status; fallback actual_date
        close_at = (await db.execute(
            select(ReleaseStatusHistory.changed_at).where(
                ReleaseStatusHistory.release_id == r.id,
                ReleaseStatusHistory.to_state == r.status,
            ).order_by(ReleaseStatusHistory.changed_at.desc()).limit(1)
        )).scalars().first() or r.actual_date
        # SQLite returns naive datetimes; normalise to UTC for comparison.
        if close_at is not None and close_at.tzinfo is None:
            close_at = close_at.replace(tzinfo=timezone.utc)
        if close_at is None or not (date_from <= close_at <= date_to):
            continue
        shipped += 1
        is_failed_state = bool(state.get("is_failed"))
        has_causal_incident = (await db.execute(
            select(Incident.id).where(
                Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None),
                Incident.release_id == r.id,
                Incident.detected_at >= date_from, Incident.detected_at <= date_to,
            ).limit(1)
        )).scalars().first() is not None
        if is_failed_state or has_causal_incident:
            failed += 1
    rate = (failed / shipped) if shipped else 0.0
    return {"rate": rate, "failed_count": failed, "shipped_count": shipped}


async def mttr(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    # NOTE: environment_id is accepted for signature symmetry with the other calculators
    # but is intentionally ignored — incidents are not environment-filtered in this sub-project.
    conds = [
        Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None),
        Incident.resolved_at.isnot(None),
        Incident.resolved_at >= date_from, Incident.resolved_at <= date_to,
    ]
    if release_id is not None:
        conds.append(Incident.release_id == release_id)
    rows = (await db.execute(
        select(Incident.detected_at, Incident.resolved_at).where(*conds)
    )).all()
    per_bucket: dict[str, list[float]] = {}
    vals: list[float] = []
    for detected_at, resolved_at in rows:
        # SQLite returns naive datetimes; normalise to UTC for comparison.
        if detected_at is not None and detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=timezone.utc)
        if resolved_at is not None and resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)
        secs = max(0.0, (resolved_at - detected_at).total_seconds())
        vals.append(secs)
        per_bucket.setdefault(_bucket_start(resolved_at, granularity), []).append(secs)
    series = [{"period": k, "mean_seconds": sum(v) / len(v)} for k, v in sorted(per_bucket.items())]
    return {
        "mean_seconds": (sum(vals) / len(vals)) if vals else 0,
        "median_seconds": median(sorted(vals)) if vals else 0,
        "count": len(vals),
        "series": series,
    }


async def dora_summary(
    db: AsyncSession, tenant_id: int, date_from: datetime, date_to: datetime,
    environment_id: Optional[int] = None, release_id: Optional[int] = None,
    granularity: str = "week",
) -> dict:
    return {
        "deployment_frequency": await deployment_frequency(db, tenant_id, date_from, date_to, environment_id, release_id, granularity),
        "lead_time": await lead_time(db, tenant_id, date_from, date_to, environment_id, release_id, granularity),
        "change_failure_rate": await change_failure_rate(db, tenant_id, date_from, date_to, environment_id, release_id),
        "mttr": await mttr(db, tenant_id, date_from, date_to, environment_id, release_id, granularity),
    }
