"""RAID log endpoints — per-release Risks / Assumptions / Issues / Dependencies."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.services import raid_service, raid_config_service, release_service
from app.api.v1.schemas.raid import RaidItemCreate, RaidItemUpdate, RaidItemRead, RaidPromotePayload

router = APIRouter(prefix="/releases", tags=["RAID"])


async def _require_release(db: AsyncSession, release_id: int, tenant_id: int):
    return await release_service.get_release(db, release_id, tenant_id)


def _assert_in_release(item, release_id: int) -> None:
    if item.release_id != release_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "RAID item not found")


@router.get("/{release_id}/raid", response_model=list[RaidItemRead])
async def list_raid(
    release_id: int,
    item_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    owner_id: Optional[int] = Query(None),
    rag: Optional[str] = Query(None),
    overdue: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    cfg = await raid_config_service.get_or_seed_config(db, tenant_id)
    items = await raid_service.list_items(
        db, release_id, tenant_id, item_type=item_type, status=status_filter,
        owner_id=owner_id, rag=rag, overdue=overdue, config=cfg)
    return [raid_service.to_read(i, cfg) for i in items]


@router.post("/{release_id}/raid", response_model=RaidItemRead, status_code=status.HTTP_201_CREATED)
async def create_raid(
    release_id: int,
    data: RaidItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    tenant_id = current_user.active_tenant_id
    item = await raid_service.create_item(db, release_id, data, tenant_id, current_user.id)
    cfg = await raid_config_service.get_or_seed_config(db, tenant_id)
    return raid_service.to_read(item, cfg)


@router.get("/{release_id}/raid/{item_id}", response_model=RaidItemRead)
async def get_raid(
    release_id: int, item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    item = await raid_service.get_item(db, item_id, tenant_id)
    _assert_in_release(item, release_id)
    cfg = await raid_config_service.get_or_seed_config(db, tenant_id)
    return raid_service.to_read(item, cfg)


@router.patch("/{release_id}/raid/{item_id}", response_model=RaidItemRead)
async def update_raid(
    release_id: int, item_id: int, data: RaidItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    item = await raid_service.get_item(db, item_id, tenant_id)
    _assert_in_release(item, release_id)
    item = await raid_service.update_item(db, item_id, data, tenant_id, current_user.id)
    cfg = await raid_config_service.get_or_seed_config(db, tenant_id)
    return raid_service.to_read(item, cfg)


@router.post("/{release_id}/raid/{item_id}/promote", response_model=RaidItemRead,
             status_code=status.HTTP_201_CREATED)
async def promote_raid(
    release_id: int, item_id: int, data: RaidPromotePayload,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    new = await raid_service.promote_item(db, release_id, item_id, data.target_type, tenant_id, current_user.id)
    cfg = await raid_config_service.get_or_seed_config(db, tenant_id)
    return raid_service.to_read(new, cfg)


@router.delete("/{release_id}/raid/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_raid(
    release_id: int, item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    item = await raid_service.get_item(db, item_id, tenant_id)
    _assert_in_release(item, release_id)
    await raid_service.delete_item(db, item_id, tenant_id, current_user.id)
