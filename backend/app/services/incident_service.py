from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.incident import Incident, IncidentStatusHistory
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.environment import Environment
from app.db.models.deployment import Deployment
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.system import System, SubSystem
from app.api.v1.schemas.incident import IncidentCreate, IncidentUpdate
from app.services import custom_field_service, lifecycle_service, pir_finding_service
from app.core.pagination import Page, Sort, apply_sort, fetch_page

_FK_MODELS = {
    "environment_id": Environment,
    "deployment_id": Deployment,
    "release_id": Release,
    "fix_release_id": Release,
    "system_id": System,
    "subsystem_id": SubSystem,
}


async def _validate_fk_tenant(db: AsyncSession, field: str, value: Optional[int], tenant_id: int) -> None:
    """Reject a FK that points at another tenant's row (IDOR guard)."""
    if value is None:
        return
    model = _FK_MODELS[field]
    row = (await db.execute(select(model).where(model.id == value))).scalar_one_or_none()
    if row is None or getattr(row, "tenant_id", None) != tenant_id or getattr(row, "deleted_at", None) is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail=f"{field} does not reference a valid record for this tenant")


async def _resolve_template(db: AsyncSession, template_id: Optional[int], tenant_id: int) -> LifecycleTemplate:
    stmt = select(LifecycleTemplate).where(
        LifecycleTemplate.tenant_id == tenant_id,
        LifecycleTemplate.entity_type == "incident",
        LifecycleTemplate.deleted_at.is_(None),
    )
    if template_id is not None:
        tpl = (await db.execute(stmt.where(LifecycleTemplate.id == template_id))).scalar_one_or_none()
        if tpl is None:
            raise HTTPException(status_code=422, detail="lifecycle_template_id must be an active incident template for this tenant")
        return tpl
    tpl = (await db.execute(stmt.where(LifecycleTemplate.is_default.is_(True)))).scalars().first()
    if tpl is None:
        raise HTTPException(status_code=422, detail="No default incident lifecycle template. Seed defaults for this tenant.")
    return tpl


def _initial_state(definition: dict) -> str:
    for s in definition.get("states", []):
        if s.get("is_initial"):
            return s["key"]
    raise HTTPException(status_code=500, detail="Incident lifecycle template has no initial state")


async def create_incident(db: AsyncSession, data: IncidentCreate, tenant_id: int, user_id: int) -> Incident:
    for field in _FK_MODELS:
        await _validate_fk_tenant(db, field, getattr(data, field), tenant_id)
    tpl = await _resolve_template(db, data.lifecycle_template_id, tenant_id)
    initial = _initial_state(tpl.definition)
    await custom_field_service.validate_custom_fields(db, tenant_id, "incident", data.custom_fields)

    now = datetime.now(timezone.utc)
    inc = Incident(
        tenant_id=tenant_id,
        title=data.title,
        description=data.description,
        severity=data.severity,
        lifecycle_template_id=tpl.id,
        status=initial,
        detected_at=data.detected_at or now,
        environment_id=data.environment_id,
        deployment_id=data.deployment_id,
        release_id=data.release_id,
        fix_release_id=data.fix_release_id,
        system_id=data.system_id,
        subsystem_id=data.subsystem_id,
        source=data.source,
        external_ref=data.external_ref,
        custom_fields=data.custom_fields,
    )
    db.add(inc)
    await db.flush()
    db.add(IncidentStatusHistory(
        tenant_id=tenant_id, incident_id=inc.id, from_state=None, to_state=initial,
        changed_by=user_id, changed_at=now,
    ))
    await db.flush()
    return inc


async def get_incident(db: AsyncSession, incident_id: int, tenant_id: int) -> Optional[Incident]:
    return (await db.execute(select(Incident).where(
        Incident.id == incident_id, Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None)
    ))).scalar_one_or_none()


async def list_incidents(
    db: AsyncSession,
    tenant_id: int,
    filters: dict,
    page: Optional[Page] = None,
    *,
    sort: Optional[Sort] = None,
) -> tuple[list[Incident], int]:
    conds = [Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None)]
    for f in ("status", "severity", "system_id", "environment_id", "release_id", "source"):
        if filters.get(f) not in (None, ""):
            conds.append(getattr(Incident, f) == filters[f])
    if filters.get("date_from"):
        conds.append(Incident.detected_at >= filters["date_from"])
    if filters.get("date_to"):
        conds.append(Incident.detected_at <= filters["date_to"])
    if filters.get("open") is not None:
        # "open" = non-terminal, resolved from the tenant's OWN incident
        # lifecycle template(s) (`is_terminal` on each state) — never a
        # hardcoded status. "open" is not itself a status value; see
        # lifecycle_service.terminal_status_clause.
        conds.append(await lifecycle_service.terminal_status_clause(
            db, tenant_id, "incident",
            template_id_column=Incident.lifecycle_template_id,
            status_column=Incident.status,
            terminal=not filters["open"],
        ))
    query = select(Incident).where(and_(*conds))
    query = apply_sort(query, sort).order_by(Incident.detected_at.desc(), Incident.id)
    return await fetch_page(db, query, page)


async def update_incident(db: AsyncSession, incident_id: int, data: IncidentUpdate, tenant_id: int) -> Incident:
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    payload = data.model_dump(exclude_unset=True)
    for field in _FK_MODELS:
        if field in payload:
            await _validate_fk_tenant(db, field, payload[field], tenant_id)
    if "custom_fields" in payload:
        await custom_field_service.validate_custom_fields(db, tenant_id, "incident", payload["custom_fields"])
    for k, v in payload.items():
        setattr(inc, k, v)
    await db.flush()
    return inc


async def delete_incident(db: AsyncSession, incident_id: int, tenant_id: int) -> None:
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    inc.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def get_status_history(db: AsyncSession, incident_id: int, tenant_id: int) -> list[IncidentStatusHistory]:
    return list((await db.execute(
        select(IncidentStatusHistory).where(
            IncidentStatusHistory.incident_id == incident_id,
            IncidentStatusHistory.tenant_id == tenant_id,
        ).order_by(IncidentStatusHistory.changed_at.asc())
    )).scalars().all())


async def transition(db: AsyncSession, incident_id: int, to_state: str,
                     tenant_id: int, user_id: int, user_role: str) -> Incident:
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    tpl = await _resolve_template(db, inc.lifecycle_template_id, tenant_id)
    record_values = {
        "title": inc.title, "description": inc.description, "severity": inc.severity,
        "custom_fields": inc.custom_fields or {},
    }
    ok, reason = lifecycle_service.validate_transition(
        tpl.definition, inc.status, to_state, user_role, record_values
    )
    if not ok:
        raise HTTPException(status_code=422, detail=reason)
    from_state = inc.status
    inc.status = to_state
    resolved_keys = {s["key"] for s in tpl.definition["states"] if s.get("is_resolved")}
    now = datetime.now(timezone.utc)
    if to_state in resolved_keys:
        inc.resolved_at = now
    elif from_state in resolved_keys:
        inc.resolved_at = None
    db.add(IncidentStatusHistory(
        tenant_id=tenant_id, incident_id=inc.id, from_state=from_state, to_state=to_state,
        changed_by=user_id, changed_at=now,
    ))
    await db.flush()
    return inc


async def _name(db: AsyncSession, model, row_id: Optional[int], tenant_id: int) -> Optional[str]:
    """Fetch the .name attribute of any model row by id scoped to tenant; returns None if missing."""
    if row_id is None:
        return None
    row = (await db.execute(
        select(model).where(model.id == row_id, model.tenant_id == tenant_id)
    )).scalar_one_or_none()
    return getattr(row, "name", None) if row else None


async def _release_summary(db: AsyncSession, release_id: Optional[int], tenant_id: int) -> Optional[dict]:
    """Return a lightweight release dict for the schemas.ReleaseSummary shape."""
    if release_id is None:
        return None
    r = (await db.execute(
        select(Release).where(Release.id == release_id, Release.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if r is None:
        return None
    return {"id": r.id, "name": r.name, "target_date": r.target_date, "status": r.status}


async def get_incident_detail(
    db: AsyncSession, incident_id: int, tenant_id: int, user_role: str
) -> Optional[dict]:
    """Return a fully-hydrated detail dict matching the IncidentDetail schema."""
    inc = await get_incident(db, incident_id, tenant_id)
    if inc is None:
        return None
    tpl = await _resolve_template(db, inc.lifecycle_template_id, tenant_id)
    transitions = lifecycle_service.get_allowed_transitions(tpl.definition, inc.status, user_role)

    # Group fix-release changes by epic_id (stringified), ungrouped when None
    changes_by_epic: dict[str, list] = {}
    if inc.fix_release_id is not None:
        rows = (await db.execute(
            select(ReleaseChange).where(
                ReleaseChange.release_id == inc.fix_release_id,
                ReleaseChange.tenant_id == tenant_id,
                ReleaseChange.deleted_at.is_(None),
            ).order_by(ReleaseChange.id.asc())
        )).scalars().all()
        for rc in rows:
            key = str(rc.epic_id) if rc.epic_id is not None else "ungrouped"
            changes_by_epic.setdefault(key, []).append(rc)

    return {
        "id": inc.id,
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "status": inc.status,
        "detected_at": inc.detected_at,
        "resolved_at": inc.resolved_at,
        "source": inc.source,
        "external_ref": inc.external_ref,
        "environment_id": inc.environment_id,
        "environment_name": await _name(db, Environment, inc.environment_id, tenant_id),
        "deployment_id": inc.deployment_id,
        "release_id": inc.release_id,
        "release": await _release_summary(db, inc.release_id, tenant_id),
        "fix_release_id": inc.fix_release_id,
        "fix_release": await _release_summary(db, inc.fix_release_id, tenant_id),
        "fix_release_changes_by_epic": changes_by_epic,
        "system_id": inc.system_id,
        "system_name": await _name(db, System, inc.system_id, tenant_id),
        "subsystem_id": inc.subsystem_id,
        "subsystem_name": await _name(db, SubSystem, inc.subsystem_id, tenant_id),
        "custom_fields": inc.custom_fields,
        "allowed_transitions": [{"to_state": t["to_state"], "label": t["label"]} for t in transitions],
        "status_history": await get_status_history(db, inc.id, tenant_id),
        "pir_citations": await pir_finding_service.citations_for_incident(db, tenant_id, inc.id),
    }
