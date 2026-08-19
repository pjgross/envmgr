"""Release booking service — wraps booking_service with release/phase context.

Provides `book_environment_for_phase` which creates a booking linked to a
release and test phase, then derives and sets the context_tag.
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.db.models.release import Release
from app.db.models.user import Tenant


async def book_environment_for_phase(
    db: AsyncSession,
    release_id: int,
    phase_id: Optional[int],
    environment_id: int,
    start: datetime,
    end: datetime,
    booking_type_id: int,
    tenant_id: int,
    user_id: int,
    project_name: Optional[str] = None,
    notes: Optional[str] = None,
    exclusive_use: bool = False,
    *,
    now: datetime,
) -> Booking:
    """Create a booking linked to a release and test phase.

    Delegates to booking_service.create_booking via the minimal interface,
    then calls derive_and_set_context_tag to populate context_tag.

    `now` is required and keyword-only, following this codebase's standing
    convention — it is threaded straight through to `create_booking`, whose
    Task 8 `assert_bookable` call is what makes this THE THIRD create path
    (the release booking path) covered by the teardown refusal without any
    code of its own: it delegates to `create_booking`, so it inherits the
    check for free.
    """
    # Verify the release exists and belongs to this tenant
    release = (
        await db.execute(
            select(Release).where(
                Release.id == release_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if release is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Release not found or does not belong to this tenant",
        )

    # Build the create payload and call the service
    from app.api.v1.schemas.booking import BookingCreate
    from app.services.booking_service import create_booking, derive_and_set_context_tag

    # We need a minimal current_user-like object for booking_service
    class _FakeUser:
        def __init__(self, tid, uid):
            self.active_tenant_id = tid
            self.id = uid
            self.role = "Admin"

    data = BookingCreate(
        environment_id=environment_id,
        start_date=start,
        end_date=end,
        booking_type_id=booking_type_id,
        project_name=project_name or release.name,
        notes=notes,
        exclusive_use=exclusive_use,
        release_id=release_id,
        test_phase_id=phase_id,
        custom_fields=None,
        context_tag=None,
        recurrence_rule=None,
    )

    fake_user = _FakeUser(tenant_id, user_id)
    booking, _warnings = await create_booking(db, data, fake_user, now=now)

    # Derive context tag from release_system roles
    await derive_and_set_context_tag(db, booking.id, tenant_id)

    return booking


async def bulk_book_environments(
    db: AsyncSession,
    release_id: int,
    environment_ids: list[int],
    phase_id: Optional[int],
    start: datetime,
    end: datetime,
    booking_type_id: int,
    tenant_id: int,
    user_id: int,
    project_name: Optional[str] = None,
    notes: Optional[str] = None,
    exclusive_use: bool = False,
    *,
    now: datetime,
) -> dict:
    """Book each environment for a release in one pass. Environments with a
    hard (exclusive) conflict for the window are skipped and reported; the rest
    are booked via book_environment_for_phase (which sets release/phase and
    derives context_tag). Returns {"created": [...], "skipped": [...]}."""
    from app.services.booking_service import check_overlap

    created: list[dict] = []
    skipped: list[dict] = []
    for env_id in environment_ids:
        overlap = await check_overlap(db, env_id, start, end, tenant_id, exclusive_use)
        if overlap.blocked:
            skipped.append({"environment_id": env_id, "conflicts": overlap.conflicts})
            continue
        try:
            booking = await book_environment_for_phase(
                db,
                release_id=release_id,
                phase_id=phase_id,
                environment_id=env_id,
                start=start,
                end=end,
                booking_type_id=booking_type_id,
                tenant_id=tenant_id,
                user_id=user_id,
                project_name=project_name,
                notes=notes,
                exclusive_use=exclusive_use,
                now=now,
            )
        except HTTPException as e:
            if e.status_code == status.HTTP_409_CONFLICT:
                if isinstance(e.detail, dict):
                    # The exclusive-use overlap shape: {"message", "conflicts"}.
                    skipped.append({
                        "environment_id": env_id,
                        "conflicts": e.detail.get("conflicts", []),
                        "reason": e.detail.get("message"),
                    })
                else:
                    # B5's decommission refusal (assert_bookable) raises a
                    # plain string detail — carry it through rather than
                    # discarding it, or the dialog reports "exclusive
                    # conflict" for a decommission teardown refusal.
                    skipped.append({
                        "environment_id": env_id,
                        "conflicts": [],
                        "reason": str(e.detail),
                    })
                continue
            raise
        created.append({"environment_id": env_id, "booking_id": booking.id, "warnings": overlap.warnings})

    return {"created": created, "skipped": skipped}
