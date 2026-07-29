"""Incidents API — CRUD, lifecycle transitions, and detail hydration (Phase 5 SP1)."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import incident_service, pir_service
from app.api.v1.schemas.incident import (
    IncidentCreate, IncidentUpdate, IncidentTransition, IncidentDetail, IncidentListRow,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def _row(db: AsyncSession, inc, tenant_id: int, pir_status: str = "none") -> IncidentListRow:
    """Build an IncidentListRow with hydrated names and fix-release summary."""
    from app.services.incident_service import _name, _release_summary
    from app.db.models.system import System
    from app.db.models.environment import Environment
    from app.db.models.release import Release
    return IncidentListRow(
        id=inc.id,
        title=inc.title,
        severity=inc.severity,
        status=inc.status,
        detected_at=inc.detected_at,
        resolved_at=inc.resolved_at,
        system_id=inc.system_id,
        system_name=await _name(db, System, inc.system_id, tenant_id),
        environment_id=inc.environment_id,
        environment_name=await _name(db, Environment, inc.environment_id, tenant_id),
        release_id=inc.release_id,
        release_name=await _name(db, Release, inc.release_id, tenant_id),
        fix_release=await _release_summary(db, inc.fix_release_id, tenant_id),
        pir_status=pir_status,
    )


@router.get("", response_model=list[IncidentListRow])
async def list_incidents(
    status_: str | None = Query(None, alias="status"),
    severity: str | None = None,
    system_id: int | None = None,
    environment_id: int | None = None,
    release_id: int | None = None,
    source: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    filters = {
        "status": status_,
        "severity": severity,
        "system_id": system_id,
        "environment_id": environment_id,
        "release_id": release_id,
        "source": source,
        "date_from": date_from,
        "date_to": date_to,
    }
    rows = await incident_service.list_incidents(db, current_user.active_tenant_id, filters)
    # Bulk-fetch PIR statuses for all incidents in one query
    status_map = await pir_service.pir_status_for_incidents(
        db, current_user.active_tenant_id, [r.id for r in rows]
    )
    return [await _row(db, r, current_user.active_tenant_id, status_map.get(r.id, "none")) for r in rows]


@router.post("", response_model=IncidentDetail, status_code=status.HTTP_201_CREATED)
async def create_incident(
    data: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    inc = await incident_service.create_incident(db, data, current_user.active_tenant_id, current_user.id)
    return await incident_service.get_incident_detail(db, inc.id, current_user.active_tenant_id, current_user.role)


@router.get("/{incident_id}", response_model=IncidentDetail)
async def get_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    detail = await incident_service.get_incident_detail(
        db, incident_id, current_user.active_tenant_id, current_user.role
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return detail


@router.patch("/{incident_id}", response_model=IncidentDetail)
async def update_incident(
    incident_id: int,
    data: IncidentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await incident_service.update_incident(db, incident_id, data, current_user.active_tenant_id)
    return await incident_service.get_incident_detail(
        db, incident_id, current_user.active_tenant_id, current_user.role
    )


@router.post("/{incident_id}/transition", response_model=IncidentDetail)
async def transition_incident(
    incident_id: int,
    data: IncidentTransition,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await incident_service.transition(
        db, incident_id, data.to_state,
        current_user.active_tenant_id, current_user.id, current_user.role
    )
    return await incident_service.get_incident_detail(
        db, incident_id, current_user.active_tenant_id, current_user.role
    )


@router.delete("/{incident_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_incident(
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    await incident_service.delete_incident(db, incident_id, current_user.active_tenant_id)
