"""Gate waivers — the record behind an overridden gate.

THERE IS NO STATE COLUMN. Live-versus-expired is computed here, through
expiry_boundary, so nothing has to be invalidated and no scheduler exists.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.release_gate import GateWaiverRead
from app.core.day_boundaries import expiry_boundary
from app.db.models.gate_waiver import GateWaiver
from app.db.models.user import User


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

    Rows accumulate as history; the newest row per gate is current, WHETHER
    LIVE OR EXPIRED — the query itself does not filter on state at all, only
    on `deleted_at`. "Current" means most recent, not live; `waiver_state`
    (above) is what decides live-versus-expired, computed separately at read
    time from `expires_at`.
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


async def usernames_for(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    """Resolve approver usernames for the wire.

    DELIBERATELY NOT TENANT-QUALIFIED (no `User.tenant_id == tenant_id`).
    Under master-admin impersonation the approver legitimately sits outside
    the gate's own tenant — a tenant-qualified join would render them as
    nobody, losing the one name a waiver's audit trail exists to hold.
    Same rule as `agreement_gap_service.ack_author_username` and
    `contention_service`'s decider-name lookup.
    """
    if not user_ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
    ).all()
    return {row.id: row.username for row in rows}


def to_read(waiver: GateWaiver, username: Optional[str], now: datetime) -> GateWaiverRead:
    """Shape one waiver ROW for the wire. `state` is computed here, from the
    SAME `now` the caller passes everywhere else in the response — never a
    fresh `datetime.now()` per row."""
    return GateWaiverRead(
        id=waiver.id,
        reason=waiver.reason,
        approved_by_user_id=waiver.approved_by_user_id,
        approved_by_username=username,
        expires_at=waiver.expires_at,
        remediation=waiver.remediation,
        created_at=waiver.created_at,
        state=waiver_state(waiver, now),
    )


async def waiver_reads_for_gates(
    db: AsyncSession,
    tenant_id: int,
    gate_ids: list[int],
    now: Optional[datetime] = None,
) -> dict[int, GateWaiverRead]:
    """The wire-shaped current waiver per gate — TWO queries for the whole
    page (latest_waivers_for_gates' one, plus one batched username lookup),
    never one per gate. ONE CLOCK for the whole page: `now` is resolved once
    here and handed to every row's `to_read`, so two gates in one response
    cannot disagree about what day it is.
    """
    now = now or datetime.now(timezone.utc)
    if not gate_ids:
        return {}
    waivers = await latest_waivers_for_gates(db, tenant_id, gate_ids)
    usernames = await usernames_for(
        db, {w.approved_by_user_id for w in waivers.values()}
    )
    return {
        gid: to_read(w, usernames.get(w.approved_by_user_id), now)
        for gid, w in waivers.items()
    }
