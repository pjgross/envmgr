"""Phase 9 C4 Task 4 — rollback rehearsals: evidence that rolling back a
SYSTEM has actually been tried.

Per system, not per release: one rehearsal serves every release touching that
system until it goes stale. THERE IS NO STATE COLUMN and no scheduler — a
rehearsal's currency follows from its date and the tenant's validity period,
exactly as A4's escalation state, B5's decommission state and C2's waiver
state all do. `rehearsal_state` is the one place that decides "current" vs
"stale"; nothing else may re-derive it.

NOTHING HERE REFUSES ANYTHING. `record_rehearsal`'s 404 is input validation on
the rehearsal's own foreign key (the system must be in the caller's tenant),
not a policy verdict — same distinction rollback_plan_service draws for its
own two 404s. Whether a `failed` or stale rehearsal blocks readiness is
Task 5's `release_readiness_service`, which reads these rows but never writes
them.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.rollback import RehearsalCreate, RehearsalRead
from app.core.day_boundaries import expiry_boundary
from app.db.models.rollback import RollbackRehearsal
from app.db.models.user import User
from app.services import rollback_policy_service, system_service


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes where PostgreSQL hands back aware
    ones; comparing the two raises TypeError. Copied rather than imported,
    following the note in app/core/day_boundaries.py — this repo already
    carries this exact helper independently in several other services
    (contention_service, agreement_gap_service, environment_health_service,
    environment_utilization_service, release_metrics_service, gate_evidence_
    service, gate_waiver_service, environment_compliance_service,
    environment_decommission_service among them). Reaching into another
    module's private helper couples two files that share nothing else. The
    rule that must NOT be copied is the day boundary itself, which is why
    expiry_boundary is imported rather than reimplemented here.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def rehearsal_state(rehearsal: RollbackRehearsal, validity_days: int, now: datetime) -> str:
    """"current" or "stale". A DEADLINE IS A DAY: a rehearsal is current all
    through its last day — compared through expiry_boundary, never at instant
    precision, or a rehearsal recorded at 15:00 would expire mid-afternoon on
    its final day."""
    expires_at = _utc(rehearsal.rehearsed_at) + timedelta(days=validity_days)
    return "stale" if expires_at < expiry_boundary(now) else "current"


async def record_rehearsal(
    db: AsyncSession,
    system_id: int,
    tenant_id: int,
    user_id: int,
    data: RehearsalCreate,
) -> RollbackRehearsal:
    """Record one rehearsal row. Validates the system is in the caller's
    tenant (404 otherwise) — input validation on the FK, not a gate-state
    check. A `failed` outcome is recorded exactly as faithfully as `passed` —
    a rehearsal that failed is still a rehearsal that happened."""
    await system_service.get_system(db, system_id, tenant_id)
    rehearsal = RollbackRehearsal(
        tenant_id=tenant_id,
        system_id=system_id,
        rehearsed_at=data.rehearsed_at,
        rehearsed_by_user_id=user_id,
        outcome=data.outcome,
        notes=data.notes,
    )
    db.add(rehearsal)
    await db.flush()
    return rehearsal


async def list_rehearsals(
    db: AsyncSession, system_id: int, tenant_id: int
) -> list[RollbackRehearsal]:
    """Every live rehearsal for one system, newest first — full history, not
    just the latest. Validates the system is in the caller's tenant first."""
    await system_service.get_system(db, system_id, tenant_id)
    rows = (
        await db.execute(
            select(RollbackRehearsal)
            .where(
                RollbackRehearsal.system_id == system_id,
                RollbackRehearsal.tenant_id == tenant_id,
                RollbackRehearsal.deleted_at.is_(None),
            )
            .order_by(RollbackRehearsal.rehearsed_at.desc(), RollbackRehearsal.id.desc())
        )
    ).scalars().all()
    return list(rows)


async def latest_rehearsals_for_systems(
    db: AsyncSession, tenant_id: int, system_ids: list[int]
) -> dict[int, RollbackRehearsal]:
    """The single latest rehearsal per system, for a whole page of systems —
    ONE query, never one per system. Task 5's release_readiness_service is the
    intended caller: it needs one lookup per response, not one per row.

    tenant_id is NOT optional and NOT a convenience — without it, a caller
    that passes a system id belonging to another tenant (even by accident,
    e.g. via a stale id in a picker) would have that tenant's rehearsal data
    (outcome, notes, who ran it) returned to it. Ordered rehearsed_at DESC,
    id DESC: rehearsed_at is caller-supplied, so ties are ordinary and the id
    tiebreaker is what makes "latest" deterministic.
    """
    if not system_ids:
        return {}
    rows = (
        await db.execute(
            select(RollbackRehearsal)
            .where(
                RollbackRehearsal.tenant_id == tenant_id,
                RollbackRehearsal.system_id.in_(system_ids),
                RollbackRehearsal.deleted_at.is_(None),
            )
            .order_by(
                RollbackRehearsal.system_id,
                RollbackRehearsal.rehearsed_at.desc(),
                RollbackRehearsal.id.desc(),
            )
        )
    ).scalars().all()
    latest: dict[int, RollbackRehearsal] = {}
    for row in rows:
        latest.setdefault(row.system_id, row)  # first seen per system is the newest
    return latest


async def usernames_for(db: AsyncSession, user_ids: set[Optional[int]]) -> dict[int, str]:
    """Resolve rehearser usernames for the wire.

    DELIBERATELY NOT TENANT-QUALIFIED (no User.tenant_id == tenant_id). Under
    master-admin impersonation the rehearser can legitimately sit outside the
    system's own tenant — a tenant-qualified join would render them as
    nobody. Same rule as rollback_plan_service.usernames_for,
    gate_waiver_service.usernames_for and contention_service.usernames_for.
    """
    ids = {u for u in user_ids if u is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    ).all()
    return {uid: username for uid, username in rows}


def to_read(
    rehearsal: RollbackRehearsal, username: Optional[str], state: str
) -> RehearsalRead:
    """Shape one rehearsal ROW for the wire."""
    return RehearsalRead(
        id=rehearsal.id,
        system_id=rehearsal.system_id,
        rehearsed_at=rehearsal.rehearsed_at,
        rehearsed_by_user_id=rehearsal.rehearsed_by_user_id,
        rehearsed_by_username=username,
        outcome=rehearsal.outcome,
        notes=rehearsal.notes,
        state=state,
    )


async def reads_for_rehearsals(
    db: AsyncSession,
    tenant_id: int,
    rehearsals: list[RollbackRehearsal],
    now: Optional[datetime] = None,
) -> list[RehearsalRead]:
    """The wire-shaped form of a list of rehearsals — batched username lookup
    and one policy read, never one query per row."""
    if now is None:
        now = datetime.now(timezone.utc)
    policy = await rollback_policy_service.get_or_create_policy(db, tenant_id)
    usernames = await usernames_for(db, {r.rehearsed_by_user_id for r in rehearsals})
    return [
        to_read(
            r,
            usernames.get(r.rehearsed_by_user_id),
            rehearsal_state(r, policy.rehearsal_validity_days, now),
        )
        for r in rehearsals
    ]
