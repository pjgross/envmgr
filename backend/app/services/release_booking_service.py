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
) -> Booking:
    """Create a booking linked to a release and test phase.

    Delegates to booking_service.create_booking via the minimal interface,
    then calls derive_and_set_context_tag to populate context_tag.
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
    booking, _warnings = await create_booking(db, data, fake_user)

    # Derive context tag from release_system roles
    await derive_and_set_context_tag(db, booking.id)

    return booking
