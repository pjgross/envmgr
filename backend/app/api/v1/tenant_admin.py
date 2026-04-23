from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import require_tenant_admin, get_current_user
from app.db.models.user import User
from app.services import tenant_service, user_admin_service, scope_change_rule_service
from app.api.v1.schemas import (
    TenantAdminSettings, TenantResponse, TenantUpdate,
    UserAdminCreate, UserAdminUpdate, UserRoleUpdate, UserResponse,
)
from app.api.v1.schemas.scope_change_rule import (
    ScopeChangeKindRuleRead,
    ScopeChangeKindRulesUpsertPayload,
)


class UserLite(BaseModel):
    id: int
    username: str

router = APIRouter()


@router.get("/settings", response_model=TenantResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await tenant_service.get_tenant(db, current_user.active_tenant_id)


@router.patch("/settings", response_model=TenantResponse)
async def update_settings(
    data: TenantAdminSettings,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await tenant_service.update_tenant(
        db, current_user.active_tenant_id, TenantUpdate(settings=data.settings)
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.list_users(db, current_user.active_tenant_id)


@router.get("/users/lite", response_model=list[UserLite])
async def list_users_lite(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Minimal {id, username} list for assignee pickers. Open to any tenant member."""
    rows = (
        await db.execute(
            select(User.id, User.username).where(
                User.tenant_id == current_user.active_tenant_id,
                User.is_active.is_(True),
            ).order_by(User.username)
        )
    ).all()
    return [UserLite(id=r.id, username=r.username) for r in rows]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserAdminCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.create_user_in_tenant(db, current_user.active_tenant_id, data)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.get_user(db, user_id, current_user.active_tenant_id)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.update_user(db, user_id, current_user.active_tenant_id, data)


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def set_user_role(
    user_id: int,
    data: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.set_user_role(db, user_id, current_user.active_tenant_id, data.role)


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.deactivate_user(db, user_id, current_user.active_tenant_id)


@router.post("/users/{user_id}/reactivate", response_model=UserResponse)
async def reactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await user_admin_service.reactivate_user(db, user_id, current_user.active_tenant_id)

@router.get("/scope-change-rules", response_model=list[ScopeChangeKindRuleRead])
async def get_scope_change_rules(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Return all scope-change-kind rules for the current tenant."""
    return await scope_change_rule_service.list_rules(
        db, current_user.active_tenant_id,
    )


@router.get("/scope-change-rules/kinds", response_model=list[str])
async def get_scope_change_kinds(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List of active change_kind names for the tenant. Open to any tenant
    member so the scope-item dialog and custom-field editor can populate
    their kind pickers."""
    rules = await scope_change_rule_service.list_rules(
        db, current_user.active_tenant_id,
    )
    return [r.change_kind for r in rules]


@router.put("/scope-change-rules", response_model=list[ScopeChangeKindRuleRead])
async def upsert_scope_change_rules(
    data: ScopeChangeKindRulesUpsertPayload,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """Upsert the scope-change-kind rules. Body carries the full set."""
    return await scope_change_rule_service.upsert_rules(
        db,
        current_user.active_tenant_id,
        [(r.change_kind, r.counts_as_scope_change) for r in data.rules],
    )

