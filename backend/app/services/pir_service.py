"""One PIR per release: a summary and a status.

Everything the review FOUND lives in `pir_finding_service`. `PIR.incident_id`
was a single nullable FK read with `scalar_one_or_none`, making the incident
relationship 1:1 in both directions; it is now a many-to-many citation against a
went-wrong finding, because one incident often exposes two distinct process
failures and one failure often produces a run of incidents.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pir import PIR
from app.db.models.release import Release


async def _validate_release(db, tenant_id, release_id):
    r = (await db.execute(select(Release).where(
        Release.id == release_id, Release.tenant_id == tenant_id, Release.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Release not found")


async def get_for_release(db: AsyncSession, tenant_id: int, release_id: int) -> Optional[PIR]:
    return (await db.execute(select(PIR).where(
        PIR.release_id == release_id, PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def create_for_release(db: AsyncSession, tenant_id: int, release_id: int, data, user_id: int) -> PIR:
    await _validate_release(db, tenant_id, release_id)
    if await get_for_release(db, tenant_id, release_id) is not None:
        raise HTTPException(status_code=409, detail="A PIR already exists for this release")
    pir = PIR(
        tenant_id=tenant_id, release_id=release_id, summary=data.summary,
        status=data.status or "draft", created_by=user_id,
    )
    if pir.status == "complete":
        pir.completed_at = datetime.now(timezone.utc)
    db.add(pir)
    await db.flush()
    return pir


async def update(db: AsyncSession, tenant_id: int, release_id: int, data) -> PIR:
    pir = await get_for_release(db, tenant_id, release_id)
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(pir, k, v)
    if pir.status == "complete" and pir.completed_at is None:
        pir.completed_at = datetime.now(timezone.utc)
    if pir.status != "complete":
        pir.completed_at = None
    await db.flush()
    return pir


async def delete(db: AsyncSession, tenant_id: int, release_id: int) -> None:
    pir = await get_for_release(db, tenant_id, release_id)
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    pir.deleted_at = datetime.now(timezone.utc)
    await db.flush()
