"""B5 — idle detection, derived in SQL on read.

NO DIALECT DATE ARITHMETIC. `boundary - N days` with a per-row N would need
PostgreSQL's interval syntax or SQLite's datetime(), and neither is portable.
Instead every distinct threshold is resolved to a plain INSTANT in Python and
injected as a literal in a CASE over tier_id — portable, indexable, and the
same trick `expiry_boundary` uses to keep a day-granular rule out of SQL.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import DateTime, and_, case, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.booking_states import INACTIVE_BOOKING_STATUSES
from app.core.day_boundaries import expiry_boundary
from app.db.models.booking import Booking
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment, EnvironmentStatus
from app.db.models.environment_tier import EnvironmentTier
from app.services import environment_lifecycle_policy_service


@dataclass(frozen=True)
class IdleState:
    """Everything the clause needs, resolved once per request."""

    enabled: bool
    cutoff_expr: object  # a SQL expression, or None when disabled


async def idle_state(db: AsyncSession, tenant_id: int, now: datetime) -> IdleState:
    policy = await environment_lifecycle_policy_service.get_policy(db, tenant_id)
    if not policy.idle_detection_enabled:
        return IdleState(enabled=False, cutoff_expr=None)

    boundary = expiry_boundary(now)
    default_cutoff = boundary - timedelta(days=policy.idle_threshold_days)

    overrides = (
        await db.execute(
            select(EnvironmentTier.id, EnvironmentTier.idle_threshold_days).where(
                EnvironmentTier.tenant_id == tenant_id,
                EnvironmentTier.idle_threshold_days.is_not(None),
            )
        )
    ).all()

    dt = DateTime(timezone=True)
    if not overrides:
        expr = literal(default_cutoff, dt)
    else:
        expr = case(
            *[
                (Environment.tier_id == tier_id,
                 literal(boundary - timedelta(days=days), dt))
                for tier_id, days in overrides
            ],
            else_=literal(default_cutoff, dt),
        )
    return IdleState(enabled=True, cutoff_expr=expr)


def idle_clause(state: IdleState, now: datetime):
    """No deployment and no booking overlapping [cutoff, now], for an ACTIVE
    environment older than its own threshold.

    Returns a always-false literal when detection is disabled, so callers need
    no branch and `?idle=false` still means what it says.
    """
    if not state.enabled:
        return literal(False)

    cutoff = state.cutoff_expr

    no_deployment = ~(
        select(Deployment.id)
        .where(
            Deployment.environment_id == Environment.id,
            Deployment.tenant_id == Environment.tenant_id,
            Deployment.deleted_at.is_(None),
            Deployment.deployed_at >= cutoff,
        )
        .exists()
    )
    # Overlap, not start: half-open, matching conflict_service's convention.
    no_booking = ~(
        select(Booking.id)
        .where(
            Booking.environment_id == Environment.id,
            Booking.tenant_id == Environment.tenant_id,
            Booking.deleted_at.is_(None),
            Booking.status.notin_(INACTIVE_BOOKING_STATUSES),
            Booking.start_date < now,
            Booking.end_date > cutoff,
        )
        .exists()
    )
    return and_(
        Environment.status == EnvironmentStatus.ACTIVE,
        Environment.created_at <= cutoff,
        no_deployment,
        no_booking,
    )
