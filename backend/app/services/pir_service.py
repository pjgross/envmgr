from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pir import PIR
from app.db.models.release import Release
from app.db.models.incident import Incident


async def _validate_release(db, tenant_id, release_id):
    r = (await db.execute(select(Release).where(
        Release.id == release_id, Release.tenant_id == tenant_id, Release.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Release not found")


async def _validate_incident(db, tenant_id, incident_id):
    if incident_id is None:
        return
    i = (await db.execute(select(Incident).where(
        Incident.id == incident_id, Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if i is None:
        raise HTTPException(status_code=422, detail="incident_id does not reference a valid incident for this tenant")


async def get_for_release(db: AsyncSession, tenant_id: int, release_id: int) -> Optional[PIR]:
    return (await db.execute(select(PIR).where(
        PIR.release_id == release_id, PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def get_for_incident(db: AsyncSession, tenant_id: int, incident_id: int) -> Optional[PIR]:
    return (await db.execute(select(PIR).where(
        PIR.incident_id == incident_id, PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def create_for_release(db: AsyncSession, tenant_id: int, release_id: int, data, user_id: int) -> PIR:
    await _validate_release(db, tenant_id, release_id)
    if await get_for_release(db, tenant_id, release_id) is not None:
        raise HTTPException(status_code=409, detail="A PIR already exists for this release")
    await _validate_incident(db, tenant_id, data.incident_id)
    pir = PIR(
        tenant_id=tenant_id, release_id=release_id, incident_id=data.incident_id,
        summary=data.summary, root_cause=data.root_cause, what_went_well=data.what_went_well,
        what_went_wrong=data.what_went_wrong, action_plan=data.action_plan,
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
    if "incident_id" in payload:
        await _validate_incident(db, tenant_id, payload["incident_id"])
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


async def pir_status_for_incidents(db: AsyncSession, tenant_id: int, incident_ids) -> dict[int, str]:
    ids = [i for i in incident_ids if i is not None]
    if not ids:
        return {}
    rows = (await db.execute(select(PIR.incident_id, PIR.status).where(
        PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None), PIR.incident_id.in_(ids),
    ))).all()
    return {iid: st for iid, st in rows}
