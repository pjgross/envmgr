"""Environment operating-hours config CRUD + validation (Phase 5 SP5a).

One EnvironmentOperatingHours row per environment. `week` is 7 entries (0=Mon..6=Sun),
each {"closed": bool, "open": "HH:MM", "close": "HH:MM"}. Overnight windows (close <= open)
are out of scope and rejected. Tenant-scoped; IDOR-guarded on the environment FK.
"""
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment
from app.db.models.environment_operating_hours import EnvironmentOperatingHours

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_timezone(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Invalid timezone: {tz!r}")


def _validate_week(week) -> None:
    if not isinstance(week, list) or len(week) != 7:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="week must have exactly 7 entries (Mon..Sun)")
    for i, day in enumerate(week):
        if not isinstance(day, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"week[{i}] must be an object")
        if day.get("closed"):
            continue
        opened, closed = day.get("open"), day.get("close")
        if not (isinstance(opened, str) and _HHMM.match(opened)) or \
           not (isinstance(closed, str) and _HHMM.match(closed)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"week[{i}] open/close must be HH:MM")
        if opened >= closed:  # lexical compare is valid for zero-padded HH:MM
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"week[{i}] open must be before close")


async def _validate_env(db: AsyncSession, tenant_id: int, environment_id: int) -> Environment:
    env = (await db.execute(select(Environment).where(
        Environment.id == environment_id,
        Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if env is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Environment not found")
    return env


async def get_config(db: AsyncSession, tenant_id: int, environment_id: int):
    return (await db.execute(select(EnvironmentOperatingHours).where(
        EnvironmentOperatingHours.environment_id == environment_id,
        EnvironmentOperatingHours.tenant_id == tenant_id,
        EnvironmentOperatingHours.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def upsert_config(db: AsyncSession, tenant_id: int, environment_id: int,
                        timezone: str, week: list) -> EnvironmentOperatingHours:
    await _validate_env(db, tenant_id, environment_id)
    _validate_timezone(timezone)
    _validate_week(week)
    row = (await db.execute(select(EnvironmentOperatingHours).where(
        EnvironmentOperatingHours.environment_id == environment_id,
        EnvironmentOperatingHours.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if row is None:
        row = EnvironmentOperatingHours(
            tenant_id=tenant_id, environment_id=environment_id, timezone=timezone, week=week,
        )
        db.add(row)
    else:
        row.timezone = timezone
        row.week = week
        row.deleted_at = None
    await db.flush()
    return row
