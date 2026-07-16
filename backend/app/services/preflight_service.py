"""Deployment preflight (`can-deploy`) — read-only evaluator.

Single entry point: `evaluate(...)`. Resolves env/subsystem slugs, then
walks five rules and produces a structured CanDeployResponse with
`blockers`, `warnings`, and `claim_matched`. No DB writes.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.schemas.preflight import (
    CanDeployBlocker,
    CanDeployResponse,
    CanDeployWarning,
    ClaimMatched,
)
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.build import Build
from app.db.models.change_request import ChangeRequest, ChangeRequestEnvironment
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment
from app.db.models.system import SubSystem


# Booking statuses that count as "active" for preflight purposes.
_ACTIVE_BOOKING_STATUSES = ("approved", "extension_requested")

# Window over which a "deployment in progress" warning is surfaced.
_DEPLOYMENT_IN_PROGRESS_WINDOW = timedelta(minutes=30)
_IN_FLIGHT_DEPLOYMENT_STATUSES = ("pending", "in_progress")


def _status_value(env_status) -> str:
    """Return the wire value for an Environment.status (handles enum + str)."""
    return env_status.value if hasattr(env_status, "value") else str(env_status)


async def evaluate(
    db: AsyncSession,
    *,
    tenant_id: int,
    environment_slug: str,
    subsystem_slug: str,
    release_id: int | None = None,
    booking_id: int | None = None,
) -> CanDeployResponse:
    """Evaluate the can-deploy gate for (tenant, env, subsystem) at "now".

    Pure read. No transitions, no side effects. Returns a structured
    answer; the caller (CI) decides what to do.
    """
    # 1. Resolve environment slug.
    env = (await db.execute(
        select(Environment).where(
            Environment.tenant_id == tenant_id,
            Environment.name == environment_slug,
            Environment.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if env is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "environment not found")

    # 2. Resolve subsystem slug.
    subsystem = (await db.execute(
        select(SubSystem).where(
            SubSystem.tenant_id == tenant_id,
            SubSystem.name == subsystem_slug,
            SubSystem.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if subsystem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "subsystem not found")

    now = datetime.now(timezone.utc)
    blockers: list[CanDeployBlocker] = []
    warnings: list[CanDeployWarning] = []
    claim_matched: ClaimMatched | None = None

    # Rule 1 — environment_inactive
    env_status_value = _status_value(env.status)
    if env_status_value != "active":
        blockers.append(CanDeployBlocker(
            type="environment_inactive",
            ref_kind="environment",
            ref_id=env.id,
            current_status=env_status_value,
        ))

    # Bookings active "now": start <= now < end, status in active set, not deleted.
    booking_q = (
        select(Booking)
        .options(selectinload(Booking.booking_request))
        .join(BookingRequest, Booking.booking_request_id == BookingRequest.id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.environment_id == env.id,
            Booking.deleted_at.is_(None),
            Booking.start_date <= now,
            Booking.end_date > now,
            Booking.status.in_(_ACTIVE_BOOKING_STATUSES),
            BookingRequest.deleted_at.is_(None),
        )
    )
    active_bookings = (await db.execute(booking_q)).scalars().all()

    # Rule 2 (exclusive_booking) and Rule 4 (non_exclusive_booking) walk the
    # same set; partition by booking_request.exclusive_use_requested.
    # Claim logic: prefer matched_via="booking_id" over "release_id" if both
    # apply to the same booking; first matching booking wins overall.
    for b in active_bookings:
        br = b.booking_request
        if br is None:
            continue
        if br.exclusive_use_requested:
            # Try to unlock via claim tokens.
            matched_via: str | None = None
            claim_value: int | None = None
            if booking_id is not None and booking_id == b.id:
                matched_via = "booking_id"
                claim_value = b.id
            elif (
                b.release_id is not None
                and release_id is not None
                and release_id == b.release_id
            ):
                matched_via = "release_id"
                claim_value = b.release_id

            if matched_via is not None:
                # Prefer booking_id-match if we already had a release_id match.
                if claim_matched is None or (
                    matched_via == "booking_id"
                    and claim_matched.matched_via != "booking_id"
                ):
                    claim_matched = ClaimMatched(
                        booking_id=b.id,
                        matched_via=matched_via,  # type: ignore[arg-type]
                        claim_value=claim_value,  # type: ignore[arg-type]
                    )
                # Claimed booking is NOT a blocker.
                continue

            blockers.append(CanDeployBlocker(
                type="exclusive_booking",
                ref_kind="booking",
                ref_id=b.id,
                title=br.project_name,
                until=b.end_date,
            ))
        else:
            # Rule 4 — non-exclusive booking is always a warning.
            warnings.append(CanDeployWarning(
                type="non_exclusive_booking",
                ref_kind="booking",
                ref_id=b.id,
                title=br.project_name,
                until=b.end_date,
            ))

    # Rule 3 — change_request_outage
    cr_q = (
        select(ChangeRequest)
        .join(
            ChangeRequestEnvironment,
            ChangeRequestEnvironment.change_request_id == ChangeRequest.id,
        )
        .where(
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
            ChangeRequest.has_outage.is_(True),
            ChangeRequest.outage_start.isnot(None),
            ChangeRequest.outage_end.isnot(None),
            ChangeRequest.outage_start <= now,
            ChangeRequest.outage_end > now,
            ChangeRequestEnvironment.environment_id == env.id,
        )
    )
    cr_rows = (await db.execute(cr_q)).scalars().all()
    for cr in cr_rows:
        # Respect subsystem narrowing: NULL = applies to all, else must match target.
        if cr.subsystem_id is not None and cr.subsystem_id != subsystem.id:
            continue
        blockers.append(CanDeployBlocker(
            type="change_request_outage",
            ref_kind="change_request",
            ref_id=cr.id,
            title=cr.title,
            until=cr.outage_end,
        ))

    # Rule 5 — deployment_in_progress
    # Match on (env, build's subsystem == target subsystem) within the
    # last `_DEPLOYMENT_IN_PROGRESS_WINDOW`.
    cutoff = now - _DEPLOYMENT_IN_PROGRESS_WINDOW
    dep_q = (
        select(Deployment)
        .join(Build, Deployment.build_id == Build.id)
        .where(
            Deployment.tenant_id == tenant_id,
            Deployment.environment_id == env.id,
            Deployment.deleted_at.is_(None),
            Deployment.status.in_(_IN_FLIGHT_DEPLOYMENT_STATUSES),
            Deployment.deployed_at >= cutoff,
            Build.subsystem_id == subsystem.id,
        )
    )
    in_flight = (await db.execute(dep_q)).scalars().all()
    for d in in_flight:
        warnings.append(CanDeployWarning(
            type="deployment_in_progress",
            ref_kind="deployment",
            ref_id=d.id,
            since=d.deployed_at,
        ))

    return CanDeployResponse(
        ok=len(blockers) == 0,
        environment_slug=environment_slug,
        subsystem_slug=subsystem_slug,
        checked_at=now,
        blockers=blockers,
        warnings=warnings,
        claim_matched=claim_matched,
    )
