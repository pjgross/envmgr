"""Phase 9 C4 Task 7 — the per-tenant rollback policy admin API.

Reads are open to any tenant member; only writes are Admin — deliberately
unlike /tenant/users, which really is admin-gated throughout. A sibling
sub-project (B3a's UserGroup) shipped this over-gated on the false analogy
that "an admin-configured policy" means "an admin-only endpoint"; it took a
review to catch. See app/api/v1/user_groups.py for the same shape.

Nothing here refuses anything on the basis of rollback state — the 403 on a
non-admin write and the 422 on a bad value are ordinary authorization and
input validation, not C4's own rules.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.rollback import RollbackPolicyRead, RollbackPolicyUpdate
from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.services import rollback_policy_service

router = APIRouter()


@router.get("/rollback-policy", response_model=RollbackPolicyRead)
async def get_rollback_policy(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """This tenant's rollback policy, defaulted if never configured."""
    return await rollback_policy_service.get_or_create_policy(
        db, current_user.active_tenant_id
    )


@router.put("/rollback-policy", response_model=RollbackPolicyRead)
async def update_rollback_policy(
    data: RollbackPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Patch semantics: an omitted key leaves that setting alone."""
    return await rollback_policy_service.update_policy(
        db,
        current_user.active_tenant_id,
        require_rollback_plan=data.require_rollback_plan,
        require_current_rehearsal=data.require_current_rehearsal,
        rehearsal_validity_days=data.rehearsal_validity_days,
    )
