# backend/app/services/release_closeout_service.py
"""Phase 9 C6 — hyper-care and closeout.

THE ONE PLACE IN PHASE 9 THAT REFUSES. `assert_may_close` (Task 5) raises a
422 from `release_service.transition_release` when the target state is
flagged `is_closed` and asks for something that is not there. Everything
else here computes on read and stores nothing.
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.test_phase import TestPhase

PHASE_KINDS = frozenset({"test", "hypercare"})
HYPERCARE = "hypercare"


async def live_hypercare_phase(
    db: AsyncSession, release_id: int, tenant_id: int
) -> Optional[TestPhase]:
    """The release's one live hyper-care phase, or None."""
    return (
        await db.execute(
            select(TestPhase).where(
                TestPhase.release_id == release_id,
                TestPhase.tenant_id == tenant_id,
                TestPhase.kind == HYPERCARE,
                TestPhase.deleted_at.is_(None),
            ).order_by(TestPhase.id).limit(1)
        )
    ).scalar_one_or_none()


async def assert_hypercare_slot_free(
    db: AsyncSession, release_id: int, tenant_id: int, *, exclude_phase_id: Optional[int] = None
) -> None:
    """At most one live hyper-care phase per release. In code, not a partial
    unique index — that would be inert on SQLite and untested there."""
    existing = await live_hypercare_phase(db, release_id, tenant_id)
    if existing is not None and existing.id != exclude_phase_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This release already has a hyper-care phase ('{existing.name}'); "
            "edit or delete it rather than adding a second.",
        )
