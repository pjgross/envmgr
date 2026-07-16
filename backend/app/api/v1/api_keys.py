"""API key CRUD — tenant-admin only. Raw key shown once on create."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_tenant_admin
from app.db.base import get_db
from app.db.models.user import User
from app.services import api_key_service
from app.api.v1.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead


router = APIRouter()


def _to_read(k) -> ApiKeyRead:
    return ApiKeyRead.model_validate({
        "id": k.id,
        "name": k.name,
        "scopes": k.scopes or [],
        "created_by": k.created_by,
        "created_by_username": None,
        "last_used_at": k.last_used_at,
        "expires_at": k.expires_at,
        "created_at": k.created_at,
    })


@router.get("", response_model=list[ApiKeyRead])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    keys = await api_key_service.list_keys(db, current_user.active_tenant_id)
    user_ids = {k.created_by for k in keys}
    usernames: dict[int, str] = {}
    if user_ids:
        rows = (
            await db.execute(select(User.id, User.username).where(
                User.id.in_(user_ids),
                User.tenant_id == current_user.active_tenant_id,
            ))
        ).all()
        usernames = {r.id: r.username for r in rows}
    out = []
    for k in keys:
        item = _to_read(k)
        item.created_by_username = usernames.get(k.created_by)
        out.append(item)
    return out


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    data: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    key, raw = await api_key_service.create_key(
        db,
        tenant_id=current_user.active_tenant_id,
        created_by=current_user.id,
        name=data.name,
        scopes=data.scopes,
        expires_at=data.expires_at,
    )
    item = _to_read(key)
    return ApiKeyCreated(**item.model_dump(), raw_key=raw)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await api_key_service.revoke_key(
        db, tenant_id=current_user.active_tenant_id, key_id=key_id,
    )
    return None
