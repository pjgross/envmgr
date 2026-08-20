"""Gate waivers — the record behind an overridden gate.

THERE IS NO STATE COLUMN. Live-versus-expired is computed here, through
expiry_boundary, so nothing has to be invalidated and no scheduler exists.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.day_boundaries import expiry_boundary
from app.db.models.gate_waiver import GateWaiver


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes where PostgreSQL returns aware ones.
    Comparing the two is a TypeError — an engine-dependent 500 invisible on the
    PostgreSQL leg."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def waiver_state(waiver: GateWaiver, now: datetime) -> str:
    """"live" or "expired". A DEADLINE IS A DAY: the expiry day itself is live."""
    expires_at = _utc(waiver.expires_at)
    if expires_at is None:
        return "live"
    return "expired" if expires_at < expiry_boundary(now) else "live"


async def latest_waivers_for_gates(
    db: AsyncSession, tenant_id: int, gate_ids: list[int]
) -> dict[int, GateWaiver]:
    """The current waiver per gate — ONE query for the page, never one per row.

    Rows accumulate as history; the newest live row per gate is current.
    """
    if not gate_ids:
        return {}
    rows = (
        await db.execute(
            select(GateWaiver)
            .where(
                GateWaiver.tenant_id == tenant_id,
                GateWaiver.gate_id.in_(gate_ids),
                GateWaiver.deleted_at.is_(None),
            )
            .order_by(GateWaiver.gate_id, GateWaiver.id.desc())
        )
    ).scalars().all()
    latest: dict[int, GateWaiver] = {}
    for row in rows:
        latest.setdefault(row.gate_id, row)  # first seen per gate is the newest
    return latest
