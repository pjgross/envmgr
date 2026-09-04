"""`GET /me/work` — the personal inbox, one round trip.

Thin on purpose: every rule lives in `my_work_service.build` (§9's
"no restated predicates") and in the five worklist seams it calls. This route
contributes exactly one thing of its own — the clock.

ONE CLOCK: `now` is taken here, once, and threaded into `build()` unchanged.
`my_work_service` never calls `datetime.now()` itself — see its own module
docstring and Task 3's guard test. Two clocks in one response could disagree
across midnight, which would make `overdue` counts and `expiry_boundary`-based
filters answer differently within the same payload.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.my_work import MyWorkResponse
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.user import User
from app.services import my_work_service

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/work", response_model=MyWorkResponse)
async def my_work(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    return await my_work_service.build(
        db,
        # NOT .tenant_id — under master-admin impersonation the two differ,
        # and every queue here must be computed in the tenant the caller is
        # actually looking at.
        tenant_id=current_user.active_tenant_id,
        user=current_user,
        now=now,
    )
