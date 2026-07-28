from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment
from app.db.models.environment_health import EnvironmentHealthStatus

STALE_AFTER = timedelta(minutes=15)
INACTIVE_BOOKING_STATUSES = {"draft", "cancelled", "rejected"}
INACTIVE_CR_STATUSES = {"cancelled", "rejected"}


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def record_sample(db: AsyncSession, tenant_id: int, environment_id: int,
                        status: str, source: str, detail: Optional[str] = None,
                        recorded_at: Optional[datetime] = None) -> EnvironmentHealthStatus:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id, Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if env is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Environment not found")
    row = EnvironmentHealthStatus(
        tenant_id=tenant_id, environment_id=environment_id, status=status, source=source,
        detail=detail, recorded_at=recorded_at or datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


async def get_history(db: AsyncSession, tenant_id: int, environment_id: int, limit: int = 50):
    limit = max(1, min(limit, 500))
    return list((await db.execute(
        select(EnvironmentHealthStatus).where(
            EnvironmentHealthStatus.tenant_id == tenant_id,
            EnvironmentHealthStatus.environment_id == environment_id,
        ).order_by(EnvironmentHealthStatus.recorded_at.desc()).limit(limit)
    )).scalars().all())


async def _latest(db, tenant_id, environment_id) -> Optional[EnvironmentHealthStatus]:
    return (await db.execute(
        select(EnvironmentHealthStatus).where(
            EnvironmentHealthStatus.tenant_id == tenant_id,
            EnvironmentHealthStatus.environment_id == environment_id,
        ).order_by(EnvironmentHealthStatus.recorded_at.desc()).limit(1)
    )).scalars().first()


def _derive_status(latest: Optional[EnvironmentHealthStatus], now: datetime):
    if latest is None:
        return "unknown", None
    rec = _utc(latest.recorded_at)
    if now - rec > STALE_AFTER:
        return "unknown", rec
    return latest.status, rec


async def health_overview(db: AsyncSession, tenant_id: int, now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    envs = (await db.execute(select(Environment).where(
        Environment.tenant_id == tenant_id, Environment.deleted_at.is_(None),
        Environment.status != "decommissioned",
    ).order_by(Environment.name.asc()))).scalars().all()
    rows = []
    for env in envs:
        current, last_at = _derive_status(await _latest(db, tenant_id, env.id), now)
        booking = await _active_booking(db, tenant_id, env.id, now)
        outage = await _planned_outage(db, tenant_id, env.id, now)
        alert = current in ("down", "issue") and booking is not None and not outage
        rows.append({
            "environment_id": env.id, "environment_name": env.name,
            "current_status": current, "last_recorded_at": last_at,
            "active_booking": booking is not None, "active_booking_summary": booking,
            "planned_outage": outage, "alert": alert,
        })
    return rows


async def _active_booking(db, tenant_id, environment_id, now):  # replaced in Task 4
    return None


async def _planned_outage(db, tenant_id, environment_id, now):  # replaced in Task 4
    return False
