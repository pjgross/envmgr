"""Release template service — CRUD + instantiate.

Materialises phases and gates when a release is created from a template.
Never calls db.commit(). All state changes publish outbox events.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.db.models.release import Release, ReleaseStatusHistory
from app.db.models.release_gate import ReleaseGate
from app.db.models.release_template import ReleaseTemplate
from app.db.models.test_phase import TestPhase
from app.api.v1.schemas.gate_criterion import GateCriterionCreate
from app.api.v1.schemas.release_template import (
    ReleaseTemplateCreate,
    ReleaseTemplateInstantiate,
    ReleaseTemplateUpdate,
)
from app.services import release_service


# ── Internal helpers ─────────────────────────────────────────────────────────

async def _get_template(
    db: AsyncSession, template_id: int, tenant_id: int
) -> ReleaseTemplate:
    tpl = (
        await db.execute(
            select(ReleaseTemplate).where(
                ReleaseTemplate.id == template_id,
                ReleaseTemplate.tenant_id == tenant_id,
                ReleaseTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Release template not found")
    return tpl


# ── Public API ───────────────────────────────────────────────────────────────

async def create_template(
    db: AsyncSession,
    data: ReleaseTemplateCreate,
    tenant_id: int,
) -> ReleaseTemplate:
    tpl = ReleaseTemplate(
        tenant_id=tenant_id,
        name=data.name,
        description=data.description,
        release_type=data.release_type,
        default_lifecycle_template_id=data.default_lifecycle_template_id,
        phases=[p.model_dump() for p in data.phases],
        gates=[g.model_dump() for g in data.gates],
        version=1,
    )
    db.add(tpl)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseTemplateCreated",
        aggregate_id=tpl.id,
        aggregate_type="ReleaseTemplate",
        payload={"id": tpl.id, "name": tpl.name, "release_type": tpl.release_type},
        tenant_id=tenant_id,
    )
    return tpl


async def list_templates(
    db: AsyncSession,
    tenant_id: int,
) -> list[ReleaseTemplate]:
    rows = (
        await db.execute(
            select(ReleaseTemplate).where(
                ReleaseTemplate.tenant_id == tenant_id,
                ReleaseTemplate.deleted_at.is_(None),
            ).order_by(ReleaseTemplate.name)
        )
    ).scalars().all()
    return list(rows)


async def get_template(
    db: AsyncSession,
    template_id: int,
    tenant_id: int,
) -> ReleaseTemplate:
    return await _get_template(db, template_id, tenant_id)


async def update_template(
    db: AsyncSession,
    template_id: int,
    data: ReleaseTemplateUpdate,
    tenant_id: int,
) -> ReleaseTemplate:
    tpl = await _get_template(db, template_id, tenant_id)

    update_data = data.model_dump(exclude_unset=True)
    # Serialise nested schemas to plain dicts if present
    if "phases" in update_data and update_data["phases"] is not None:
        update_data["phases"] = [
            p.model_dump() if hasattr(p, "model_dump") else p
            for p in update_data["phases"]
        ]
    if "gates" in update_data and update_data["gates"] is not None:
        update_data["gates"] = [
            g.model_dump() if hasattr(g, "model_dump") else g
            for g in update_data["gates"]
        ]
    for field, value in update_data.items():
        setattr(tpl, field, value)

    # Bump version on every save
    tpl.version = (tpl.version or 1) + 1
    await db.flush()
    await db.refresh(tpl)

    await publish_event(
        db,
        event_type="ReleaseTemplateUpdated",
        aggregate_id=tpl.id,
        aggregate_type="ReleaseTemplate",
        payload={"id": tpl.id, "name": tpl.name, "version": tpl.version},
        tenant_id=tenant_id,
    )
    return tpl


async def delete_template(
    db: AsyncSession,
    template_id: int,
    tenant_id: int,
) -> None:
    tpl = await _get_template(db, template_id, tenant_id)

    # Refuse if any active release references this template
    in_use = (
        await db.execute(
            select(func.count()).select_from(Release).where(
                Release.template_id == template_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if in_use:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot delete template: it is referenced by one or more active releases",
        )

    tpl.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    await publish_event(
        db,
        event_type="ReleaseTemplateDeleted",
        aggregate_id=tpl.id,
        aggregate_type="ReleaseTemplate",
        payload={"id": tpl.id, "name": tpl.name},
        tenant_id=tenant_id,
    )


async def instantiate(
    db: AsyncSession,
    template_id: int,
    data: ReleaseTemplateInstantiate,
    tenant_id: int,
    user_id: int,
) -> Release:
    """Create a Release + TestPhases + ReleaseGates from a template.

    Phase dates are back-computed from target_date using default_duration_days
    (last phase ends on target_date).
    """
    tpl = await _get_template(db, template_id, tenant_id)

    # Create the Release using release_service so we get the lifecycle resolution
    # and history row for free.
    from app.api.v1.schemas.release import ReleaseCreate
    release_data = ReleaseCreate(
        name=data.name,
        description=data.description,
        release_type=tpl.release_type,
        lifecycle_template_id=tpl.default_lifecycle_template_id,
        template_id=template_id,
        target_date=data.target_date,
        custom_fields=data.custom_fields,
    )
    release = await release_service.create_release(db, release_data, tenant_id, user_id)

    # Build phases with computed dates, working backwards from target_date
    phases_config = tpl.phases or []
    phase_objects: dict[str, TestPhase] = {}

    if phases_config:
        cursor = data.target_date
        # Iterate in reverse order so the last phase ends at target_date
        for phase_cfg in reversed(phases_config):
            if isinstance(phase_cfg, dict):
                name = phase_cfg.get("name", "Phase")
                order = phase_cfg.get("order", 0)
                duration_days = phase_cfg.get("default_duration_days", 5)
            else:
                name = phase_cfg.name
                order = phase_cfg.order
                duration_days = phase_cfg.default_duration_days

            end_date = cursor
            start_date = cursor - timedelta(days=duration_days)
            phase = TestPhase(
                tenant_id=tenant_id,
                release_id=release.id,
                name=name,
                order=order,
                start_date=start_date,
                end_date=end_date,
                status="pending",
            )
            db.add(phase)
            await db.flush()
            phase_objects[name] = phase
            cursor = start_date

    # Create gates, linking to the matching phase by name (or None for release-level)
    for gate_cfg in (tpl.gates or []):
        if isinstance(gate_cfg, dict):
            gate_name = gate_cfg.get("name", "Gate")
            phase_name = gate_cfg.get("phase_name")
            acceptance_criteria = gate_cfg.get("acceptance_criteria")
        else:
            gate_name = gate_cfg.name
            phase_name = gate_cfg.phase_name
            acceptance_criteria = gate_cfg.acceptance_criteria

        matched_phase = phase_objects.get(phase_name) if phase_name else None
        # Derive due_date: phase end_date → release target_date → release created_at
        if matched_phase and matched_phase.end_date:
            gate_due_date = matched_phase.end_date
        elif release.target_date:
            gate_due_date = release.target_date
        else:
            gate_due_date = release.created_at
        gate = ReleaseGate(
            tenant_id=tenant_id,
            release_id=release.id,
            name=gate_name,
            status="pending",
            due_date=gate_due_date,
        )
        db.add(gate)
        await db.flush()

        # Seed a single criterion from acceptance_criteria if present
        seed_text = (acceptance_criteria or "").strip()
        if seed_text:
            from app.services import gate_criterion_service
            await gate_criterion_service.create_criterion(
                db,
                gate_id=gate.id,
                tenant_id=tenant_id,
                user_id=user_id,
                data=GateCriterionCreate(title="Acceptance criteria", notes=seed_text),
            )

    await db.flush()
    return release
