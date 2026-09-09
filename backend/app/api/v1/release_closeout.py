"""Phase 9 C6 — declared stable, ops handover, and (Task 7) the closeout read.

Its own router rather than more lines in releases.py, the way go_no_go.py and
pir.py are. Mounted in main.py under /api/v1; every path starts /releases/{id}/
so no literal segment can collide with releases.py's `/{release_id}` catch-all.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.releases import _release_with_permissions
from app.api.v1.schemas.closeout import AuditNote
from app.api.v1.schemas.release import ReleaseRead
from app.core.security import Role, require_role
from app.db.base import get_db
from app.services import release_closeout_service, release_service

router = APIRouter(prefix="/releases", tags=["Closeout"])


async def _run(db, release_id, current_user, fn, note: Optional[str]) -> ReleaseRead:
    tenant_id = current_user.active_tenant_id
    release = await release_service.get_release(db, release_id, tenant_id)
    release = await fn(db, release, tenant_id=tenant_id, user_id=current_user.id, note=note)
    return await _release_with_permissions(db, release, current_user.role, current_user)


@router.post("/{release_id}/declare-stable", response_model=ReleaseRead)
async def declare_stable(release_id: int, data: AuditNote, db: AsyncSession = Depends(get_db),
                         current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.declare_stable, data.note)


@router.delete("/{release_id}/declare-stable", response_model=ReleaseRead)
async def withdraw_stable(release_id: int, db: AsyncSession = Depends(get_db),
                          current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.withdraw_stable, None)


@router.post("/{release_id}/confirm-handover", response_model=ReleaseRead)
async def confirm_handover(release_id: int, data: AuditNote, db: AsyncSession = Depends(get_db),
                           current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.confirm_handover, data.note)


@router.delete("/{release_id}/confirm-handover", response_model=ReleaseRead)
async def withdraw_handover(release_id: int, db: AsyncSession = Depends(get_db),
                            current_user=Depends(require_role(Role.RELEASE_MANAGER))):
    return await _run(db, release_id, current_user, release_closeout_service.withdraw_handover, None)
