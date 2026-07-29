"""DORA Metrics API endpoints (Phase 5 SP2).

GET /api/v1/metrics/dora        — summary (all four DORA metrics)
GET /api/v1/metrics/dora/export — CSV download of the per-bucket series
GET /api/v1/metrics/releases            — release success-rate / emergency% / avg cycle time
GET /api/v1/metrics/bookings/conflicts  — per-environment/per-month booking-conflict counts

date_from/date_to accept either a plain date ("2026-01-01") or a full ISO-8601
datetime string ("2026-01-01T00:00:00Z"). Both are normalised to UTC datetimes
before being forwarded to the service layer.
"""
import csv
import io
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import dora_service, release_metrics_service

router = APIRouter(prefix="/metrics", tags=["metrics"])

_UTC = timezone.utc


def _as_dt(d: date | datetime, *, end_of_day: bool = False) -> datetime:
    """Convert a date or datetime to a UTC-aware datetime.

    A plain `date` used as the inclusive upper bound (`end_of_day=True`) expands to the
    last microsecond of that day, so the whole day's events fall within `<= date_to`.
    """
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=_UTC)
    if end_of_day:
        return datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=_UTC)
    return datetime(d.year, d.month, d.day, tzinfo=_UTC)


@router.get("/dora")
async def get_dora(
    date_from: date = Query(...),
    date_to: date = Query(...),
    environment_id: int | None = None,
    release_id: int | None = None,
    granularity: Literal["day", "week", "month"] = "week",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await dora_service.dora_summary(
        db, current_user.active_tenant_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
        environment_id, release_id, granularity,
    )


@router.get("/dora/export")
async def export_dora(
    date_from: date = Query(...),
    date_to: date = Query(...),
    environment_id: int | None = None,
    release_id: int | None = None,
    granularity: Literal["day", "week", "month"] = "week",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    summary = await dora_service.dora_summary(
        db, current_user.active_tenant_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
        environment_id, release_id, granularity,
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["metric", "period", "value"])
    for p in summary["deployment_frequency"]["series"]:
        w.writerow(["deployment_frequency", p["period"], p["count"]])
    for p in summary["lead_time"]["series"]:
        w.writerow(["lead_time_median_seconds", p["period"], p["median_seconds"]])
    for p in summary["mttr"]["series"]:
        w.writerow(["mttr_mean_seconds", p["period"], p["mean_seconds"]])
    cfr = summary["change_failure_rate"]
    w.writerow(["change_failure_rate", "window", cfr["rate"]])
    w.writerow(["cfr_failed_count", "window", cfr["failed_count"]])
    w.writerow(["cfr_shipped_count", "window", cfr["shipped_count"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dora-metrics.csv"},
    )


@router.get("/releases")
async def get_release_metrics(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_metrics_service.release_metrics(
        db, current_user.active_tenant_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
    )


@router.get("/bookings/conflicts")
async def get_booking_conflicts(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await release_metrics_service.booking_conflicts(
        db, current_user.active_tenant_id,
        _as_dt(date_from), _as_dt(date_to, end_of_day=True),
    )
