"""Phase 9 C3 — the go-no-go condition close route, and the tenant-
configurable perspective vocabulary CRUD.

The decision `POST`/`GET` routes live in `releases.py`, beside the release
they belong to (`/releases/{id}/go-no-go`); everything here addresses a
`GoNoGoCondition` or a `GoNoGoPerspective` directly by its own id, with no
`/releases` prefix, so it gets its own router.

Perspectives: reads are open to any tenant member, writes are Admin-only —
the same split `gate_types.py`/`component_types.py` use. No delete: a
perspective is retired via `is_active=False` through the update path.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, require_tenant_admin
from app.db.base import get_db
from app.api.v1.schemas.go_no_go import (
    GoNoGoConditionClose,
    GoNoGoConditionRead,
    GoNoGoPerspectiveCreate,
    GoNoGoPerspectiveRead,
    GoNoGoPerspectiveUpdate,
)
from app.services import go_no_go_service

router = APIRouter(tags=["Go/No-Go"])
perspectives_router = APIRouter(prefix="/go-no-go-perspectives", tags=["Go/No-Go"])


async def _condition_read(
    db: AsyncSession, tenant_id: int, condition
) -> GoNoGoConditionRead:
    names = await go_no_go_service.usernames_for(
        db, [condition.owner_user_id, condition.met_by_user_id]
    )
    read = GoNoGoConditionRead.model_validate(condition)
    read.owner_username = (
        names.get(condition.owner_user_id) if condition.owner_user_id is not None else None
    )
    read.met_by_username = (
        names.get(condition.met_by_user_id) if condition.met_by_user_id is not None else None
    )
    return read


@router.patch("/go-no-go-conditions/{condition_id}", response_model=GoNoGoConditionRead)
async def close_condition(
    condition_id: int,
    data: GoNoGoConditionClose,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Close (`met=True`) or reopen (`met=False`) one condition.

    The condition is read first, tenant-filtered, so a cross-tenant id 404s
    before the owner-or-Admin/RM question is ever asked — a 403 would
    confirm the record exists. This is the ONE mutation an append-only
    decision allows; it never touches the decision's outcome, rationale or
    frozen snapshot.
    """
    tenant_id = current_user.active_tenant_id
    condition = await go_no_go_service.get_condition(db, condition_id, tenant_id)
    go_no_go_service.assert_may_close_condition(condition, current_user)

    closed = await go_no_go_service.close_condition(
        db, condition_id, tenant_id, current_user.id, data.met
    )
    return await _condition_read(db, tenant_id, closed)


@perspectives_router.get("", response_model=list[GoNoGoPerspectiveRead])
async def list_perspectives(
    include_inactive: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Reads are open to ANY tenant member; only writes are Admin — the same
    B3a call, deliberately unlike `/tenant/users`."""
    return await go_no_go_service.list_perspectives(
        db, current_user.active_tenant_id, include_inactive=include_inactive
    )


@perspectives_router.post(
    "", response_model=GoNoGoPerspectiveRead, status_code=status.HTTP_201_CREATED
)
async def create_perspective(
    data: GoNoGoPerspectiveCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await go_no_go_service.create_perspective(db, current_user.active_tenant_id, data)


@perspectives_router.patch("/{perspective_id}", response_model=GoNoGoPerspectiveRead)
async def update_perspective(
    perspective_id: int,
    data: GoNoGoPerspectiveUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await go_no_go_service.update_perspective(
        db, perspective_id, current_user.active_tenant_id, data
    )
